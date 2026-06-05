"""flask forge rules — Rule management CLI commands."""
from __future__ import annotations

import json
import sys
from typing import Any

import click


@click.group("rules")
def rules_cli() -> None:
	"""Manage pgappforge business rules."""


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _get_session() -> Any:
	"""Return the Flask-SQLAlchemy session, raising UsageError if unavailable."""
	try:
		from flask import current_app
		return current_app.appbuilder.get_session
	except RuntimeError as exc:
		raise click.UsageError(
			"No Flask application context — run inside 'flask' CLI or push an app context."
		) from exc


def _load_rulesets(session: Any, name: str | None, tenant: str | None) -> list:
	"""Query RuleSets, optionally filtered by name and/or tenant_id."""
	from .models import RuleSet
	from sqlalchemy import select

	stmt = select(RuleSet)
	if name:
		stmt = stmt.where(RuleSet.name == name)
	if tenant:
		stmt = stmt.where(RuleSet.tenant_id == tenant)
	return session.execute(stmt).scalars().all()


# ---------------------------------------------------------------------------
# export
# ---------------------------------------------------------------------------

@rules_cli.command("export")
@click.option("--output", "-o", default="-", help="Output file (default: stdout)")
@click.option("--ruleset", "-r", default=None, help="Export specific ruleset by name")
@click.option("--tenant", "-t", default=None, help="Filter by tenant_id")
def rules_export(output: str, ruleset: str | None, tenant: str | None) -> None:
	"""Export all rulesets to YAML."""
	from .dsl import decompile_to_yaml

	session = _get_session()
	rulesets = _load_rulesets(session, ruleset, tenant)

	if not rulesets:
		click.echo("No rulesets found.", err=True)
		return

	chunks: list[str] = []
	for rs in rulesets:
		# Build a plain dict from the ORM object
		rs_dict = {
			"name":          rs.name,
			"model_name":    rs.model_name,
			"priority":      rs.priority,
			"stop_on_match": rs.stop_on_match,
			"enabled":       rs.enabled,
		}
		for opt in ("description", "tenant_id", "schedule_cron"):
			val = getattr(rs, opt, None)
			if val is not None:
				rs_dict[opt] = val

		rules_list = [
			{
				"name":               r.name,
				"trigger_event":      r.trigger_event,
				"trigger_type":       r.trigger_type,
				"conditions_json":    r.conditions_json or [],
				"actions_json":       r.actions_json or [],
				"order":              r.order,
				"enabled":            r.enabled,
				"stop_after_actions": r.stop_after_actions,
				"status":             r.status,
			}
			for r in (rs.rules or [])
		]

		try:
			yaml_text = decompile_to_yaml(rs_dict, rules_list)
		except Exception as exc:
			click.echo(f"Error decompiling ruleset {rs.name!r}: {exc}", err=True)
			continue

		chunks.append(f"# ── Ruleset: {rs.name} ──\n{yaml_text}")

	combined = "\n---\n".join(chunks)

	if output == "-":
		click.echo(combined)
	else:
		with open(output, "w", encoding="utf-8") as fh:
			fh.write(combined)
		click.echo(f"Exported {len(rulesets)} ruleset(s) to {output}")


# ---------------------------------------------------------------------------
# import
# ---------------------------------------------------------------------------

@rules_cli.command("import")
@click.argument("path")
@click.option("--dry-run", is_flag=True, help="Validate without saving")
@click.option("--overwrite", is_flag=True, help="Overwrite existing ruleset by name")
def rules_import(path: str, dry_run: bool, overwrite: bool) -> None:
	"""Import rulesets from a YAML file.

	PATH may contain multiple YAML documents separated by '---'.
	"""
	from .dsl import compile_yaml
	from .models import Rule, RuleSet
	from sqlalchemy import select

	try:
		with open(path, encoding="utf-8") as fh:
			raw = fh.read()
	except OSError as exc:
		raise click.UsageError(f"Cannot read {path!r}: {exc}") from exc

	# Support multi-document YAML files split by ---
	import re
	documents = [d.strip() for d in re.split(r"^---\s*$", raw, flags=re.MULTILINE) if d.strip()]
	if not documents:
		raise click.UsageError("File contains no YAML documents.")

	session = _get_session()
	imported = skipped = errors = 0

	for i, doc_text in enumerate(documents, 1):
		# Skip comment-only chunks (e.g. the "# ── Ruleset: …" header lines)
		non_comment = "\n".join(
			ln for ln in doc_text.splitlines() if not ln.strip().startswith("#")
		).strip()
		if not non_comment:
			continue

		try:
			compiled = compile_yaml(non_comment)
		except Exception as exc:
			click.echo(f"[doc {i}] Compile error: {exc}", err=True)
			errors += 1
			continue

		rs_data = compiled["ruleset"]
		rules_data = compiled["rules"]
		rs_name = rs_data["name"]

		# Check for existing ruleset
		existing = session.execute(
			select(RuleSet).where(RuleSet.name == rs_name)
		).scalar_one_or_none()

		if existing and not overwrite:
			click.echo(
				f"[doc {i}] Skipping ruleset {rs_name!r} — already exists "
				f"(use --overwrite to replace)",
				err=True,
			)
			skipped += 1
			continue

		if dry_run:
			click.echo(
				f"[doc {i}] DRY-RUN: would {'overwrite' if existing else 'create'} "
				f"ruleset {rs_name!r} with {len(rules_data)} rule(s)"
			)
			imported += 1
			continue

		try:
			if existing and overwrite:
				# Delete child rules; update ruleset in place
				for old_rule in list(existing.rules or []):
					session.delete(old_rule)
				session.flush()
				for k, v in rs_data.items():
					if hasattr(existing, k):
						setattr(existing, k, v)
				rs_obj = existing
			else:
				rs_obj = RuleSet(**{
					k: v for k, v in rs_data.items()
					if k not in ("yaml_source",) or True  # include yaml_source
				})
				session.add(rs_obj)

			session.flush()  # get rs_obj.id

			for r in rules_data:
				rule = Rule(
					ruleset_id=rs_obj.id,
					name=r["name"],
					trigger_event=r["trigger_event"],
					trigger_type=r.get("trigger_type", "model_event"),
					conditions_json=r.get("conditions_json", []),
					actions_json=r.get("actions_json", []),
					order=r.get("order", 0),
					enabled=r.get("enabled", True),
					stop_after_actions=r.get("stop_after_actions", False),
					status=r.get("status", "active"),
				)
				session.add(rule)

			session.commit()
			click.echo(
				f"[doc {i}] {'Overwrote' if existing else 'Imported'} ruleset "
				f"{rs_name!r} ({len(rules_data)} rule(s))"
			)
			imported += 1

		except Exception as exc:
			session.rollback()
			click.echo(f"[doc {i}] DB error for ruleset {rs_name!r}: {exc}", err=True)
			errors += 1

	click.echo(
		f"\nDone — imported={imported} skipped={skipped} errors={errors}"
		+ (" (dry-run)" if dry_run else "")
	)


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------

@rules_cli.command("list")
@click.option("--model", "-m", default=None, help="Filter by model name")
@click.option("--enabled/--disabled", default=None, help="Filter by enabled state")
def rules_list(model: str | None, enabled: bool | None) -> None:
	"""List all rulesets."""
	from .models import RuleSet
	from sqlalchemy import select

	session = _get_session()
	stmt = select(RuleSet)
	if model:
		stmt = stmt.where(RuleSet.model_name == model)
	if enabled is not None:
		stmt = stmt.where(RuleSet.enabled.is_(enabled))
	stmt = stmt.order_by(RuleSet.priority, RuleSet.name)

	rulesets = session.execute(stmt).scalars().all()

	if not rulesets:
		click.echo("No rulesets found.")
		return

	# Header
	fmt = "{:<5}  {:<30}  {:<25}  {:>8}  {:<8}  {:<6}  {}"
	click.echo(fmt.format("ID", "NAME", "MODEL", "PRIORITY", "ENABLED", "RULES", "CRON"))
	click.echo("-" * 100)

	for rs in rulesets:
		rule_count = len(rs.rules) if rs.rules else 0
		cron = rs.schedule_cron or ""
		click.echo(fmt.format(
			rs.id,
			(rs.name or "")[:30],
			(rs.model_name or "")[:25],
			rs.priority,
			str(rs.enabled),
			rule_count,
			cron,
		))

	click.echo(f"\nTotal: {len(rulesets)} ruleset(s)")


# ---------------------------------------------------------------------------
# test
# ---------------------------------------------------------------------------

@rules_cli.command("test")
@click.argument("ruleset_name")
@click.option(
	"--record-json", "-j",
	default="{}",
	help="Record context as JSON string (default: {})",
)
@click.option(
	"--event", "-e",
	default="on_create",
	help="Event to simulate (default: on_create)",
)
def rules_test(ruleset_name: str, record_json: str, event: str) -> None:
	"""Test a ruleset with sample data (dry run, no DB writes).

	RULESET_NAME is the exact name of the ruleset to test.

	Example:

	\b
	    flask forge rules test "Invoice Validation" \\
	        --record-json '{"amount": 0, "customer_id": 1}' \\
	        --event before_create
	"""
	from .engine import get_rules_engine
	from .dsl import _normalise_event

	# Parse record JSON
	try:
		ctx: dict = json.loads(record_json)
	except json.JSONDecodeError as exc:
		raise click.UsageError(f"--record-json is not valid JSON: {exc}") from exc

	if not isinstance(ctx, dict):
		raise click.UsageError("--record-json must be a JSON object (dict)")

	canonical_event = _normalise_event(event)

	# Build a lightweight mock record from the context dict so the engine's
	# _record_to_dict / attribute-history paths don't choke on a plain dict.
	class _MockRecord:
		"""Minimal SQLAlchemy-free record stub for dry-run testing."""
		def __init__(self, data: dict) -> None:
			for k, v in data.items():
				setattr(self, k, v)
			self.id = data.get("id", 0)

		def __repr__(self) -> str:
			return f"<MockRecord {ctx!r}>"

	mock_record = _MockRecord(ctx)

	# Determine model_name from the ruleset
	from .models import RuleSet
	from sqlalchemy import select

	session = _get_session()
	rs = session.execute(
		select(RuleSet).where(RuleSet.name == ruleset_name)
	).scalar_one_or_none()

	if rs is None:
		raise click.UsageError(f"Ruleset {ruleset_name!r} not found.")

	model_name = rs.model_name

	engine = get_rules_engine()
	result = engine.evaluate_dry(model_name, canonical_event, mock_record, session=session)

	# Pretty-print results
	click.echo(f"\nDry-run: ruleset={ruleset_name!r} model={model_name!r} event={canonical_event!r}")
	click.echo(f"Context: {json.dumps(ctx, default=str, indent=2)}")
	click.echo()
	click.echo(f"Rules matched:        {result['rules_matched'] or '(none)'}")
	click.echo(f"Would block:          {result['would_block']}")
	if result["would_block"]:
		if result.get("block_field"):
			click.echo(f"  field:              {result['block_field']!r}")
		click.echo(f"  message:            {result['block_message']!r}")
	if result["would_set"]:
		click.echo(f"Would set fields:     {json.dumps(result['would_set'], default=str)}")
	if result["would_send_emails"]:
		click.echo(f"Would send emails:    {result['would_send_emails']}")
	if result["would_call_webhooks"]:
		click.echo(f"Would call webhooks:  {result['would_call_webhooks']}")
	if result["would_create_records"]:
		click.echo(f"Would create records: {result['would_create_records']}")
	if result["would_start_workflows"]:
		click.echo(f"Would start workflows:{result['would_start_workflows']}")
