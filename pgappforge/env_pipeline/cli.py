"""
pgappforge/env_pipeline/cli.py

Flask CLI command group: ``flask forge env``

Commands:
  list     — show all configured environments
  diff     — config diff between two environments
  deploy   — deploy with pre-flight checks + optional migration
  promote  — promote schema/config from one environment to another
"""
from __future__ import annotations

import subprocess
import sys

import click

from pgappforge.env_pipeline.config import PgAppForgeConfig


@click.group("env")
def env() -> None:
	"""Environment pipeline management (dev → staging → production)."""


# ── env list ─────────────────────────────────────────────────────────────────

@env.command("list")
@click.option("--config", "-c", default="pgappforge.yaml", show_default=True,
              help="Path to pgappforge.yaml")
def env_list(config: str) -> None:
	"""List all configured environments."""
	cfg = PgAppForgeConfig.load(config)

	click.echo(f"{'Environment':<22} {'Debug':<8} {'MFA':<6} {'MockMPesa':<12} {'AI':<6}")
	click.echo("-" * 60)

	for name, e in cfg.environments.items():
		marker = " <- default" if name == cfg.default_environment else ""
		click.echo(
			f"{name:<22} "
			f"{str(e.debug):<8} "
			f"{str(e.require_mfa):<6} "
			f"{str(e.mock_mpesa):<12} "
			f"{str(e.ai_features):<6}"
			f"{marker}"
		)

	if cfg.environments:
		click.echo(f"\n{len(cfg.environments)} environment(s) configured.")


# ── env diff ─────────────────────────────────────────────────────────────────

@env.command("diff")
@click.argument("env_from")
@click.argument("env_to")
@click.option("--config", "-c", default="pgappforge.yaml", show_default=True,
              help="Path to pgappforge.yaml")
def env_diff(env_from: str, env_to: str, config: str) -> None:
	"""Show configuration differences between two environments.

	\b
	Example:
	  flask forge env diff development production
	"""
	cfg = PgAppForgeConfig.load(config)

	if env_from not in cfg.environments:
		click.echo(f"Environment '{env_from}' not found.", err=True)
		sys.exit(1)
	if env_to not in cfg.environments:
		click.echo(f"Environment '{env_to}' not found.", err=True)
		sys.exit(1)

	e_from = cfg.environments[env_from]
	e_to = cfg.environments[env_to]

	click.echo(f"Diff: {env_from} -> {env_to}")
	click.echo("=" * 50)

	# Skip fields that are always environment-specific or sensitive
	skip = {"name", "database_uri", "env_vars"}
	diffs_found = 0

	for field_name in e_from.__dataclass_fields__:  # type: ignore[attr-defined]
		if field_name in skip:
			continue
		v_from = getattr(e_from, field_name)
		v_to = getattr(e_to, field_name)
		if v_from != v_to:
			click.echo(f"  {field_name}:")
			click.echo(f"    {env_from}: {v_from!r}")
			click.echo(f"    {env_to}:   {v_to!r}")
			diffs_found += 1

	# Show extra_plugins diff
	p_from = set(e_from.extra_plugins)
	p_to = set(e_to.extra_plugins)
	added = p_to - p_from
	removed = p_from - p_to
	if added or removed:
		click.echo("  extra_plugins:")
		for p in sorted(added):
			click.echo(f"    + {p}")
		for p in sorted(removed):
			click.echo(f"    - {p}")
		diffs_found += 1

	if diffs_found == 0:
		click.echo("  (no differences)")
	else:
		click.echo(f"\n{diffs_found} field(s) differ.")


# ── env deploy ────────────────────────────────────────────────────────────────

@env.command("deploy")
@click.argument("environment")
@click.option("--config", "-c", default="pgappforge.yaml", show_default=True,
              help="Path to pgappforge.yaml")
@click.option("--dry-run", is_flag=True, help="Show what would happen without making changes")
@click.option("--skip-migrate", is_flag=True, help="Skip database migration step")
def env_deploy(environment: str, config: str, dry_run: bool, skip_migrate: bool) -> None:
	"""Deploy to an environment with pre-flight checks.

	\b
	Example:
	  flask forge env deploy production
	  flask forge env deploy staging --dry-run
	"""
	cfg = PgAppForgeConfig.load(config)

	if environment not in cfg.environments:
		click.echo(f"Environment '{environment}' not found.", err=True)
		sys.exit(1)

	env_cfg = cfg.environments[environment]
	prefix = "[DRY RUN] " if dry_run else ""
	click.echo(f"{prefix}Deploying to: {environment}")

	# Pre-flight checks
	click.echo("\nPre-flight checks:")
	checks = [
		("Database URI configured", bool(env_cfg.database_uri)),
		(
			"Production requires MFA",
			not (environment == "production" and not env_cfg.require_mfa),
		),
	]

	all_pass = True
	for check_name, result in checks:
		status = "OK" if result else "FAIL"
		click.echo(f"  [{status}] {check_name}")
		if not result:
			all_pass = False

	if not all_pass:
		click.echo("\nPre-flight failed. Deployment aborted.", err=True)
		sys.exit(1)

	click.echo("\nAll checks passed.")

	# Apply environment-specific env_vars
	if env_cfg.env_vars and not dry_run:
		click.echo(f"Setting {len(env_cfg.env_vars)} environment variable(s)...")

	# Database migration
	if not skip_migrate and not dry_run:
		click.echo("Running database migrations...")
		result = subprocess.run(
			["flask", "db", "upgrade"],
			capture_output=True,
			text=True,
		)
		if result.returncode != 0:
			click.echo(f"Migration failed:\n{result.stderr}", err=True)
			_log_deployment_safe(environment, "FAILED", notes="migration failure")
			sys.exit(1)
		click.echo("  Migrations complete.")

	if not dry_run:
		_log_deployment_safe(environment, "SUCCESS")
		click.echo(f"\nDeployment to {environment} complete.")
	else:
		click.echo("\n(dry run — no changes made)")


# ── env promote ───────────────────────────────────────────────────────────────

@env.command("promote")
@click.argument("source_env")
@click.argument("target_env")
@click.option("--config", "-c", default="pgappforge.yaml", show_default=True,
              help="Path to pgappforge.yaml")
@click.option("--confirm", is_flag=True,
              help="Skip the interactive confirmation prompt")
def env_promote(source_env: str, target_env: str, config: str, confirm: bool) -> None:
	"""Promote schema/config from one environment to another.

	NOTE: Data is never promoted — only schema migrations and configuration.

	\b
	Example:
	  flask forge env promote staging production --confirm
	"""
	cfg = PgAppForgeConfig.load(config)

	for env_name in (source_env, target_env):
		if env_name not in cfg.environments:
			click.echo(f"Environment '{env_name}' not found.", err=True)
			sys.exit(1)

	if not confirm:
		click.confirm(f"Promote {source_env} -> {target_env}?", abort=True)

	click.echo(f"Promoting {source_env} -> {target_env}")
	click.echo("NOTE: Data is not promoted — schema migrations and config only.")

	_log_deployment_safe(target_env, "PROMOTE", source_env=source_env)

	click.echo(
		f"\nPromotion logged. Run:\n"
		f"  flask forge env deploy {target_env}\n"
		f"to apply migrations on the target environment."
	)


# ── Internal helpers ──────────────────────────────────────────────────────────

def _log_deployment_safe(environment: str, action: str, **extra) -> None:
	"""Write a deployment log entry; silently swallows errors outside app context."""
	try:
		from pgappforge.env_pipeline.deployment_log import log_deployment
		log_deployment(environment, action, **extra)
	except Exception:
		pass
