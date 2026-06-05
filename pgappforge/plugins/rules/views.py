"""
pgappforge/plugins/rules/views.py

RulesBuilderView — visual no-code rules builder UI + JSON REST API.

Routes
------
GET  /rules/               — builder dashboard (HTML)
GET  /rules/api/rulesets   — list all rule sets
POST /rules/api/rulesets   — create rule set
GET  /rules/api/rulesets/<id>  — get ruleset + rules
PUT  /rules/api/rulesets/<id>  — update ruleset fields
DELETE /rules/api/rulesets/<id> — delete ruleset
POST /rules/api/rules      — create rule
PUT  /rules/api/rules/<id> — update rule
DELETE /rules/api/rules/<id> — delete rule
POST /rules/api/test       — dry-run evaluate
GET  /rules/api/export/<ruleset_id> — export ruleset JSON
POST /rules/api/import     — import ruleset JSON
"""
from __future__ import annotations

import json
import logging
from typing import Any

from flask import current_app, jsonify, make_response, request
from flask_babel import lazy_gettext as _

from pgappforge.baseviews import BaseView
from pgappforge.security.decorators import has_access
from pgappforge import expose

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_session():
	try:
		from pgappforge import db  # type: ignore[attr-defined]
		return db.session
	except Exception:
		from flask_sqlalchemy import SQLAlchemy  # type: ignore[import]
		db_ext: SQLAlchemy = current_app.extensions["sqlalchemy"]
		return db_ext.session


def _json_error(msg: str, status: int = 400):
	return jsonify({"error": msg}), status


def _ruleset_to_dict(rs, include_rules: bool = False) -> dict[str, Any]:
	d: dict[str, Any] = {
		"id":          rs.id,
		"name":        rs.name,
		"description": rs.description,
		"model_name":  rs.model_name,
		"enabled":     rs.enabled,
		"priority":    rs.priority,
		"rule_count":  len(rs.rules),
	}
	if include_rules:
		d["rules"] = [_rule_to_dict(r) for r in rs.rules]
	return d


def _rule_to_dict(r) -> dict[str, Any]:
	return {
		"id":              r.id,
		"ruleset_id":      r.ruleset_id,
		"name":            r.name,
		"trigger_event":   r.trigger_event,
		"conditions_json": r.conditions_json or [],
		"actions_json":    r.actions_json or [],
		"enabled":         r.enabled,
		"order":           r.order,
	}


# ---------------------------------------------------------------------------
# View
# ---------------------------------------------------------------------------

class RulesBuilderView(BaseView):
	"""Visual no-code rules builder with REST API backend."""

	route_base = "/rules"

	# ------------------------------------------------------------------
	# HTML dashboard
	# ------------------------------------------------------------------

	@expose("/")
	@has_access
	def index(self):
		session = _get_session()
		from .models import RuleSet
		rule_sets = (
			session.query(RuleSet)
			.order_by(RuleSet.priority, RuleSet.name)
			.all()
		)
		rows_html = ""
		for rs in rule_sets:
			enabled_badge = (
				'<span class="label label-success">Yes</span>'
				if rs.enabled
				else '<span class="label label-default">No</span>'
			)
			rows_html += f"""
			<tr>
				<td>{rs.id}</td>
				<td><a href="#" onclick="populateRulesetForm({rs.id})">{rs.name}</a></td>
				<td><code>{rs.model_name}</code></td>
				<td>{enabled_badge}</td>
				<td>{len(rs.rules)}</td>
				<td>
					<button class="btn btn-xs btn-warning" onclick="populateRulesetForm({rs.id})">
						<i class="fa fa-pencil"></i> Edit
					</button>
					<button class="btn btn-xs btn-danger" onclick="deleteRuleset({rs.id})">
						<i class="fa fa-trash"></i>
					</button>
					<button class="btn btn-xs btn-info" onclick="exportRuleset({rs.id})">
						<i class="fa fa-download"></i>
					</button>
				</td>
			</tr>"""

		html = f"""
<!DOCTYPE html>
<html>
<head>
	<title>Rules Builder</title>
	<link rel="stylesheet" href="/static/appbuilder/css/bootstrap.min.css"/>
	<link rel="stylesheet" href="/static/appbuilder/css/font-awesome.min.css"/>
	<script src="/static/appbuilder/js/jquery-latest.js"></script>
	<script src="/static/appbuilder/js/bootstrap.min.js"></script>
	<script src="/static/appbuilder/js/rules_builder.js"></script>
	<style>
		body {{ padding: 20px; }}
		.condition-row, .action-row {{ margin-bottom: 8px; }}
		#conditions-container .row, #actions-container .row {{ margin-bottom: 6px; }}
	</style>
</head>
<body>
<div class="container-fluid">
	<h2><i class="fa fa-sitemap"></i> Rules Engine Builder</h2>

	<!-- Toolbar -->
	<div class="btn-toolbar" style="margin-bottom:16px">
		<button class="btn btn-primary" data-toggle="modal" data-target="#rulesetModal"
			onclick="clearRulesetForm()">
			<i class="fa fa-plus"></i> New RuleSet
		</button>
		<button class="btn btn-default" onclick="importRuleset()">
			<i class="fa fa-upload"></i> Import
		</button>
	</div>

	<!-- RuleSets table -->
	<div class="panel panel-default">
		<div class="panel-heading"><strong>Rule Sets</strong></div>
		<table class="table table-striped table-bordered">
			<thead>
				<tr>
					<th>ID</th><th>Name</th><th>Model</th>
					<th>Enabled</th><th>Rules</th><th>Actions</th>
				</tr>
			</thead>
			<tbody id="ruleset-table-body">
				{rows_html}
			</tbody>
		</table>
	</div>
</div>

<!-- RuleSet Modal -->
<div class="modal fade" id="rulesetModal" tabindex="-1" role="dialog">
	<div class="modal-dialog modal-lg" role="document">
		<div class="modal-content">
			<div class="modal-header">
				<button type="button" class="close" data-dismiss="modal">
					<span>&times;</span>
				</button>
				<h4 class="modal-title" id="rulesetModalTitle">New RuleSet</h4>
			</div>
			<div class="modal-body">
				<input type="hidden" id="ruleset-id" value=""/>
				<div class="form-group">
					<label>RuleSet Name</label>
					<input type="text" class="form-control" id="ruleset-name"
						placeholder="e.g. Invoice Validation Rules"/>
				</div>
				<div class="form-group">
					<label>Model Name</label>
					<input type="text" class="form-control" id="ruleset-model"
						placeholder="e.g. Invoice"/>
				</div>
				<div class="form-group">
					<label>Description</label>
					<textarea class="form-control" id="ruleset-description" rows="2"></textarea>
				</div>
				<div class="form-group">
					<label>Priority <small class="text-muted">(lower = runs first)</small></label>
					<input type="number" class="form-control" id="ruleset-priority" value="100"/>
				</div>

				<hr/>
				<h5>Rules</h5>
				<div class="form-group">
					<label>Rule Name</label>
					<input type="text" class="form-control" id="rule-name"
						placeholder="e.g. Block zero-amount invoices"/>
				</div>
				<div class="form-group">
					<label>Trigger Event</label>
					<select class="form-control" id="rule-trigger">
						<option value="on_create">on_create</option>
						<option value="on_update">on_update</option>
						<option value="on_delete">on_delete</option>
						<option value="on_field_change:">on_field_change: (append field name)</option>
					</select>
				</div>

				<h6>Conditions</h6>
				<div id="conditions-container"></div>
				<button type="button" class="btn btn-xs btn-default"
					onclick="addConditionRow()">
					<i class="fa fa-plus"></i> Add Condition
				</button>

				<h6 style="margin-top:12px">Actions</h6>
				<div id="actions-container"></div>
				<button type="button" class="btn btn-xs btn-default"
					onclick="addActionRow()">
					<i class="fa fa-plus"></i> Add Action
				</button>

				<hr/>
				<div id="test-result-area" style="display:none" class="alert alert-info"></div>
			</div>
			<div class="modal-footer">
				<button type="button" class="btn btn-default" data-dismiss="modal">Cancel</button>
				<button type="button" class="btn btn-info" onclick="testRule()">
					<i class="fa fa-play"></i> Test
				</button>
				<button type="button" class="btn btn-success" onclick="saveRuleset()">
					<i class="fa fa-save"></i> Save
				</button>
			</div>
		</div>
	</div>
</div>

<!-- Import Modal -->
<div class="modal fade" id="importModal" tabindex="-1" role="dialog">
	<div class="modal-dialog" role="document">
		<div class="modal-content">
			<div class="modal-header">
				<button type="button" class="close" data-dismiss="modal">&times;</button>
				<h4 class="modal-title">Import RuleSet JSON</h4>
			</div>
			<div class="modal-body">
				<textarea class="form-control" id="import-json" rows="10"
					placeholder="Paste exported JSON here..."></textarea>
			</div>
			<div class="modal-footer">
				<button type="button" class="btn btn-default" data-dismiss="modal">Cancel</button>
				<button type="button" class="btn btn-primary" onclick="doImport()">Import</button>
			</div>
		</div>
	</div>
</div>
</body>
</html>"""
		return html

	# ------------------------------------------------------------------
	# API — RuleSets
	# ------------------------------------------------------------------

	@expose("/api/rulesets", methods=("GET",))
	@has_access
	def api_rulesets_list(self):
		session = _get_session()
		from .models import RuleSet
		rule_sets = session.query(RuleSet).order_by(RuleSet.priority, RuleSet.name).all()
		return jsonify([_ruleset_to_dict(rs) for rs in rule_sets])

	@expose("/api/rulesets", methods=("POST",))
	@has_access
	def api_rulesets_create(self):
		session = _get_session()
		from .models import RuleSet
		data = request.get_json(silent=True) or {}
		name       = data.get("name", "").strip()
		model_name = data.get("model_name", "").strip()
		if not name:
			return _json_error("name is required")
		if not model_name:
			return _json_error("model_name is required")

		rs = RuleSet(
			name=name,
			model_name=model_name,
			description=data.get("description"),
			enabled=bool(data.get("enabled", True)),
			priority=int(data.get("priority", 100)),
		)
		session.add(rs)
		try:
			session.commit()
		except Exception as exc:
			session.rollback()
			return _json_error(f"DB error: {exc}", 500)
		return jsonify(_ruleset_to_dict(rs)), 201

	@expose("/api/rulesets/<int:rs_id>", methods=("GET",))
	@has_access
	def api_rulesets_get(self, rs_id: int):
		session = _get_session()
		from .models import RuleSet
		rs = session.get(RuleSet, rs_id)
		if rs is None:
			return _json_error("not found", 404)
		return jsonify(_ruleset_to_dict(rs, include_rules=True))

	@expose("/api/rulesets/<int:rs_id>", methods=("PUT",))
	@has_access
	def api_rulesets_update(self, rs_id: int):
		session = _get_session()
		from .models import RuleSet
		rs = session.get(RuleSet, rs_id)
		if rs is None:
			return _json_error("not found", 404)
		data = request.get_json(silent=True) or {}
		if "name" in data:
			rs.name = data["name"]
		if "description" in data:
			rs.description = data["description"]
		if "model_name" in data:
			rs.model_name = data["model_name"]
		if "enabled" in data:
			rs.enabled = bool(data["enabled"])
		if "priority" in data:
			rs.priority = int(data["priority"])
		try:
			session.commit()
		except Exception as exc:
			session.rollback()
			return _json_error(f"DB error: {exc}", 500)
		return jsonify(_ruleset_to_dict(rs))

	@expose("/api/rulesets/<int:rs_id>", methods=("DELETE",))
	@has_access
	def api_rulesets_delete(self, rs_id: int):
		session = _get_session()
		from .models import RuleSet
		rs = session.get(RuleSet, rs_id)
		if rs is None:
			return _json_error("not found", 404)
		session.delete(rs)
		try:
			session.commit()
		except Exception as exc:
			session.rollback()
			return _json_error(f"DB error: {exc}", 500)
		return jsonify({"deleted": rs_id})

	# ------------------------------------------------------------------
	# API — Rules
	# ------------------------------------------------------------------

	@expose("/api/rules", methods=("POST",))
	@has_access
	def api_rules_create(self):
		session = _get_session()
		from .models import Rule
		data = request.get_json(silent=True) or {}
		ruleset_id = data.get("ruleset_id")
		name       = (data.get("name") or "").strip()
		if not ruleset_id:
			return _json_error("ruleset_id is required")
		if not name:
			return _json_error("name is required")

		rule = Rule(
			ruleset_id=int(ruleset_id),
			name=name,
			trigger_event=data.get("trigger_event", "on_create"),
			conditions_json=data.get("conditions_json") or [],
			actions_json=data.get("actions_json") or [],
			enabled=bool(data.get("enabled", True)),
			order=int(data.get("order", 0)),
		)
		session.add(rule)
		try:
			session.commit()
		except Exception as exc:
			session.rollback()
			return _json_error(f"DB error: {exc}", 500)
		return jsonify(_rule_to_dict(rule)), 201

	@expose("/api/rules/<int:rule_id>", methods=("PUT",))
	@has_access
	def api_rules_update(self, rule_id: int):
		session = _get_session()
		from .models import Rule
		rule = session.get(Rule, rule_id)
		if rule is None:
			return _json_error("not found", 404)
		data = request.get_json(silent=True) or {}
		if "name" in data:
			rule.name = data["name"]
		if "trigger_event" in data:
			rule.trigger_event = data["trigger_event"]
		if "conditions_json" in data:
			rule.conditions_json = data["conditions_json"]
		if "actions_json" in data:
			rule.actions_json = data["actions_json"]
		if "enabled" in data:
			rule.enabled = bool(data["enabled"])
		if "order" in data:
			rule.order = int(data["order"])
		try:
			session.commit()
		except Exception as exc:
			session.rollback()
			return _json_error(f"DB error: {exc}", 500)
		return jsonify(_rule_to_dict(rule))

	@expose("/api/rules/<int:rule_id>", methods=("DELETE",))
	@has_access
	def api_rules_delete(self, rule_id: int):
		session = _get_session()
		from .models import Rule
		rule = session.get(Rule, rule_id)
		if rule is None:
			return _json_error("not found", 404)
		session.delete(rule)
		try:
			session.commit()
		except Exception as exc:
			session.rollback()
			return _json_error(f"DB error: {exc}", 500)
		return jsonify({"deleted": rule_id})

	# ------------------------------------------------------------------
	# API — Test / dry-run
	# ------------------------------------------------------------------

	@expose("/api/test", methods=("POST",))
	@has_access
	def api_test(self):
		"""
		Dry-run: evaluate conditions against a synthetic record dict using
		evaluate_dry() for a full structured result.
		Does NOT execute actions — returns what *would* happen.
		"""
		session = _get_session()
		from .models import RuleSet
		from .engine import RulesEngine

		data       = request.get_json(silent=True) or {}
		ruleset_id = data.get("ruleset_id")
		record_ctx = data.get("record") or {}
		event      = data.get("event", "on_create")

		if not ruleset_id:
			return _json_error("ruleset_id is required")

		rs = session.get(RuleSet, int(ruleset_id))
		if rs is None:
			return _json_error("RuleSet not found", 404)

		# Build a proxy object that supports getattr() for evaluate_dry()
		class _RecordProxy:
			def __init__(self, d: dict[str, Any]) -> None:
				self.__dict__.update(d)

		record_proxy = _RecordProxy(record_ctx)
		engine = RulesEngine()
		dry_run = engine.evaluate_dry(rs.model_name, event, record_proxy, session=session)

		return jsonify({"ruleset": rs.name, "dry_run": dry_run})

	# ------------------------------------------------------------------
	# API — Validate rule JSON structure
	# ------------------------------------------------------------------

	@expose("/api/validate", methods=("POST",))
	@has_access
	def api_validate(self):
		"""Validate rule JSON structure — conditions and actions syntax only."""
		from .engine import _OPS

		data       = request.get_json(silent=True) or {}
		conditions = data.get("conditions_json") or []
		actions    = data.get("actions_json") or []

		errors: list[dict[str, str]] = []

		# --- validate conditions ---
		valid_ops = set(_OPS.keys())
		for i, cond in enumerate(conditions):
			path_prefix = f"conditions[{i}]"
			if not isinstance(cond, dict):
				errors.append({"path": path_prefix, "message": "must be an object"})
				continue
			if not cond.get("field") or not isinstance(cond.get("field"), str):
				errors.append({"path": f"{path_prefix}.field", "message": "field is required and must be a string"})
			op = cond.get("op")
			if not op:
				errors.append({"path": f"{path_prefix}.op", "message": "op is required"})
			elif op not in valid_ops:
				errors.append({
					"path": f"{path_prefix}.op",
					"message": f"unknown op {op!r}; valid: {sorted(valid_ops)}",
				})
			if "value" not in cond:
				errors.append({"path": f"{path_prefix}.value", "message": "value key is required"})

		# --- validate actions ---
		valid_action_types = {
			"block", "set_field", "add_error", "send_email",
			"call_webhook", "create_record", "start_workflow",
		}
		for i, action in enumerate(actions):
			path_prefix = f"actions[{i}]"
			if not isinstance(action, dict):
				errors.append({"path": path_prefix, "message": "must be an object"})
				continue
			atype = action.get("type")
			if not atype:
				errors.append({"path": f"{path_prefix}.type", "message": "type is required"})
				continue
			if atype not in valid_action_types:
				errors.append({
					"path": f"{path_prefix}.type",
					"message": f"unknown type {atype!r}; valid: {sorted(valid_action_types)}",
				})
				continue
			if atype == "set_field":
				if not action.get("field"):
					errors.append({"path": f"{path_prefix}.field", "message": "set_field requires field"})
			if atype in ("block", "add_error"):
				if not action.get("message"):
					errors.append({"path": f"{path_prefix}.message", "message": f"{atype} requires message"})
			if atype == "add_error":
				if not action.get("field"):
					errors.append({"path": f"{path_prefix}.field", "message": "add_error requires field"})
			if atype == "call_webhook":
				if not action.get("url"):
					errors.append({"path": f"{path_prefix}.url", "message": "call_webhook requires url"})
			if atype == "create_record":
				if not action.get("model"):
					errors.append({"path": f"{path_prefix}.model", "message": "create_record requires model"})
			if atype == "start_workflow":
				if not action.get("workflow_type"):
					errors.append({"path": f"{path_prefix}.workflow_type", "message": "start_workflow requires workflow_type"})

		return jsonify({"valid": len(errors) == 0, "errors": errors})

	# ------------------------------------------------------------------
	# API — Visualize ruleset as Mermaid flowchart
	# ------------------------------------------------------------------

	@expose("/api/visualize/<int:rs_id>", methods=("GET",))
	@has_access
	def api_visualize(self, rs_id: int):
		"""Return a Mermaid flowchart diagram of the ruleset's rule flow."""
		session = _get_session()
		from .models import RuleSet

		rs = session.get(RuleSet, rs_id)
		if rs is None:
			return _json_error("not found", 404)

		rules = [r for r in rs.rules if r.enabled]

		def _safe_id(text: str) -> str:
			"""Strip Mermaid-unsafe chars from node labels."""
			import re
			return re.sub(r'[^a-zA-Z0-9_]', '_', text)

		def _trunc(text: str, n: int = 30) -> str:
			return text[:n] + "…" if len(text) > n else text

		lines: list[str] = ["flowchart TD"]
		rs_label = _trunc(rs.name, 35)
		lines.append(f'    START(["{rs_label}"])')

		prev = "START"
		for i, rule in enumerate(rules):
			rule_node = f"R{i + 1}"
			rule_label = _trunc(f"{rule.name}\\n{rule.trigger_event}", 50)
			lines.append(f'    {rule_node}{{"{rule_label}"}}')
			lines.append(f'    {prev} --> {rule_node}')

			# Emit one node per action
			for j, action in enumerate(rule.actions_json or []):
				atype = action.get("type", "unknown")
				a_node = f"A{i + 1}_{j + 1}"
				if atype == "block":
					detail = _trunc(action.get("message", ""), 25)
					a_label = f"block: {detail}"
				elif atype == "add_error":
					detail = _trunc(action.get("message", ""), 25)
					a_label = f"add_error({action.get('field','')}): {detail}"
				elif atype == "set_field":
					a_label = f"set_field: {action.get('field','')}={_trunc(str(action.get('value','')), 15)}"
				elif atype == "send_email":
					a_label = f"send_email: {_trunc(action.get('to',''), 20)}"
				elif atype == "call_webhook":
					a_label = f"webhook: {_trunc(action.get('url',''), 20)}"
				elif atype == "create_record":
					a_label = f"create_record: {action.get('model','')}"
				elif atype == "start_workflow":
					a_label = f"start_workflow: {action.get('workflow_type','')}"
				else:
					a_label = f"action: {atype}"
				lines.append(f'    {a_node}["{a_label}"]')
				lines.append(f'    {rule_node} -->|"conditions match"| {a_node}')

			prev = rule_node

		lines.append(f'    END([Done])')
		lines.append(f'    {prev} -->|"no match"| END')

		mermaid = "\n".join(lines)
		return jsonify({"mermaid": mermaid})

	# ------------------------------------------------------------------
	# API — Export / Import
	# ------------------------------------------------------------------

	@expose("/api/export/<int:rs_id>", methods=("GET",))
	@has_access
	def api_export(self, rs_id: int):
		session = _get_session()
		from .models import RuleSet
		rs = session.get(RuleSet, rs_id)
		if rs is None:
			return _json_error("not found", 404)

		export_data = _ruleset_to_dict(rs, include_rules=True)
		# Remove DB-specific id so re-import creates new rows
		export_data.pop("id", None)
		for r in export_data.get("rules", []):
			r.pop("id", None)
			r.pop("ruleset_id", None)

		response = make_response(json.dumps(export_data, indent=2, default=str))
		response.headers["Content-Type"] = "application/json"
		response.headers["Content-Disposition"] = (
			f'attachment; filename="ruleset_{rs_id}.json"'
		)
		return response

	@expose("/api/import", methods=("POST",))
	@has_access
	def api_import(self):
		session = _get_session()
		from .models import RuleSet, Rule

		data = request.get_json(silent=True) or {}
		name       = (data.get("name") or "").strip()
		model_name = (data.get("model_name") or "").strip()
		if not name:
			return _json_error("name is required in import payload")
		if not model_name:
			return _json_error("model_name is required in import payload")

		rs = RuleSet(
			name=name,
			model_name=model_name,
			description=data.get("description"),
			enabled=bool(data.get("enabled", True)),
			priority=int(data.get("priority", 100)),
		)
		session.add(rs)
		session.flush()  # get rs.id

		for r_data in data.get("rules", []):
			rule = Rule(
				ruleset_id=rs.id,
				name=(r_data.get("name") or "imported rule"),
				trigger_event=r_data.get("trigger_event", "on_create"),
				conditions_json=r_data.get("conditions_json") or [],
				actions_json=r_data.get("actions_json") or [],
				enabled=bool(r_data.get("enabled", True)),
				order=int(r_data.get("order", 0)),
			)
			session.add(rule)

		try:
			session.commit()
		except Exception as exc:
			session.rollback()
			return _json_error(f"DB error: {exc}", 500)

		return jsonify(_ruleset_to_dict(rs, include_rules=True)), 201
