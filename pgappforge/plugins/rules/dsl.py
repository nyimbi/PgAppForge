"""
pgappforge/plugins/rules/dsl.py

YAML DSL compiler for human-writable rule definitions.

Public surface
--------------
compile_yaml(yaml_text)           -> dict  (ruleset + rules ready for DB import)
decompile_to_yaml(ruleset, rules) -> str   (round-trip back to YAML)

The YAML format is intentionally terse.  Actions use keyword shorthands;
conditions support both flat leaf dicts and nested any_of / all_of groups.
"""
from __future__ import annotations

import json
import logging
from typing import Any

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Trigger-event normalisation
# ---------------------------------------------------------------------------

_EVENT_ALIASES: dict[str, str] = {
	"before_create":  "on_before_create",
	"before_update":  "on_before_update",
	"before_delete":  "on_before_delete",
	"after_create":   "on_create",
	"after_update":   "on_update",
	"after_delete":   "on_delete",
	"on_create":      "on_create",
	"on_update":      "on_update",
	"on_delete":      "on_delete",
	"on_before_create": "on_before_create",
	"on_before_update": "on_before_update",
	"on_before_delete": "on_before_delete",
	"on_schedule":    "on_schedule",
	"api":            "api",
	"form_submit":    "form_submit",
}


def _normalise_event(raw: str) -> str:
	"""Normalise a YAML 'on' value to the engine's canonical event string.

	Passes through 'on_field_change:<field>' variants unchanged.
	"""
	if raw.startswith("on_field_change:"):
		return raw
	return _EVENT_ALIASES.get(raw, raw)


# ---------------------------------------------------------------------------
# Condition compiler
# ---------------------------------------------------------------------------

def _compile_condition(cond: Any) -> dict[str, Any]:
	"""Convert one YAML condition node to the engine's internal dict format.

	Leaf (has 'field'):
	    {field, op, value, logic?}  →  pass through unchanged

	Group (has 'any_of' or 'all_of'):
	    {any_of: [...]}  →  {type: "group", join: "OR",  conditions: [...]}
	    {all_of: [...]}  →  {type: "group", join: "AND", conditions: [...]}
	"""
	if not isinstance(cond, dict):
		raise ValueError(f"condition must be a dict, got {type(cond).__name__}: {cond!r}")

	if "any_of" in cond:
		return {
			"type": "group",
			"join": "OR",
			"conditions": [_compile_condition(c) for c in cond["any_of"]],
		}
	if "all_of" in cond:
		return {
			"type": "group",
			"join": "AND",
			"conditions": [_compile_condition(c) for c in cond["all_of"]],
		}

	# Leaf condition
	required = {"field", "op", "value"}
	missing = required - cond.keys()
	# 'is_null' / 'is_not_null' don't need a value
	if "op" in cond and cond["op"] in ("is_null", "is_not_null"):
		missing -= {"value"}
	if missing - {"value"}:  # field + op are always required
		raise ValueError(f"condition missing required keys {missing!r}: {cond!r}")

	compiled: dict[str, Any] = {
		"field": cond["field"],
		"op":    cond["op"],
		"value": cond.get("value"),
	}
	if "logic" in cond:
		compiled["logic"] = cond["logic"].upper()
	return compiled


# ---------------------------------------------------------------------------
# Action compiler
# ---------------------------------------------------------------------------

def _compile_action(action: Any) -> dict[str, Any]:
	"""Convert one YAML action shorthand to the engine's {type, ...} format.

	Shorthands
	----------
	block: "message"
	set_field: {field, value}
	send_email: {to, subject, body?}
	notify_user: {user_id, message}
	call_webhook: {url, payload?}
	transform_value: {field, transform}
	create_record: {model, fields}
	add_error: {field, message}
	start_workflow: {process_definition, context?}
	update_related: {fk_field, model, set}

	Passthrough: if the action already has a 'type' key it is returned as-is.
	"""
	if not isinstance(action, dict):
		raise ValueError(f"action must be a dict, got {type(action).__name__}: {action!r}")

	# Already in engine format
	if "type" in action:
		return dict(action)

	if len(action) != 1:
		raise ValueError(
			f"action shorthand must have exactly one key, got {list(action.keys())!r}"
		)

	key, val = next(iter(action.items()))

	if key == "block":
		return {"type": "block", "message": str(val)}

	if key == "set_field":
		_require_dict(val, "set_field")
		_require_keys(val, {"field", "value"}, "set_field")
		return {"type": "set_field", "field": val["field"], "value": val["value"]}

	if key == "send_email":
		_require_dict(val, "send_email")
		_require_keys(val, {"to", "subject"}, "send_email")
		result: dict[str, Any] = {
			"type":    "send_email",
			"to":      val["to"],
			"subject": val["subject"],
		}
		if "body" in val:
			result["body"] = val["body"]
		return result

	if key == "notify_user":
		_require_dict(val, "notify_user")
		_require_keys(val, {"user_id", "message"}, "notify_user")
		result = {
			"type":    "notify_user",
			"user_id": val["user_id"],
			"message": val["message"],
		}
		if "level" in val:
			result["level"] = val["level"]
		return result

	if key == "call_webhook":
		_require_dict(val, "call_webhook")
		_require_keys(val, {"url"}, "call_webhook")
		result = {"type": "call_webhook", "url": val["url"]}
		if "payload" in val:
			result["payload"] = val["payload"]
		return result

	if key == "transform_value":
		_require_dict(val, "transform_value")
		_require_keys(val, {"field", "transform"}, "transform_value")
		return {
			"type":      "transform_value",
			"field":     val["field"],
			"transform": val["transform"],
		}

	if key == "create_record":
		_require_dict(val, "create_record")
		_require_keys(val, {"model", "fields"}, "create_record")
		return {
			"type":   "create_record",
			"model":  val["model"],
			"fields": val["fields"],
		}

	if key == "add_error":
		_require_dict(val, "add_error")
		_require_keys(val, {"field", "message"}, "add_error")
		return {
			"type":    "add_error",
			"field":   val["field"],
			"message": val["message"],
		}

	if key == "start_workflow":
		_require_dict(val, "start_workflow")
		_require_keys(val, {"process_definition"}, "start_workflow")
		result = {
			"type":               "start_workflow",
			"process_definition": val["process_definition"],
		}
		if "context" in val:
			result["context"] = val["context"]
		return result

	if key == "update_related":
		_require_dict(val, "update_related")
		_require_keys(val, {"fk_field", "model", "set"}, "update_related")
		return {
			"type":     "update_related",
			"fk_field": val["fk_field"],
			"model":    val["model"],
			"set":      val["set"],
		}

	raise ValueError(f"unknown action shorthand {key!r}")


def _require_dict(val: Any, name: str) -> None:
	if not isinstance(val, dict):
		raise ValueError(f"{name} value must be a mapping, got {type(val).__name__}")


def _require_keys(val: dict, required: set, name: str) -> None:
	missing = required - val.keys()
	if missing:
		raise ValueError(f"{name} missing required keys: {missing!r}")


# ---------------------------------------------------------------------------
# compile_yaml
# ---------------------------------------------------------------------------

def compile_yaml(yaml_text: str) -> dict[str, Any]:
	"""Compile a YAML rule definition into a dict ready for DB import.

	Returns
	-------
	{
	  "ruleset": {name, model_name, priority, stop_on_match, description?,
	              tenant_id?, schedule_cron?, yaml_source},
	  "rules":   [{name, trigger_event, conditions_json, actions_json,
	               order, enabled, trigger_type, stop_after_actions,
	               status}, ...]
	}

	Raises ValueError on malformed input.
	"""
	try:
		import yaml  # PyYAML
	except ImportError as exc:
		raise ImportError(
			"compile_yaml requires PyYAML — install it with: pip install pyyaml"
		) from exc

	doc = yaml.safe_load(yaml_text)
	if not isinstance(doc, dict):
		raise ValueError("YAML document must be a mapping at the top level")

	# ── ruleset section ──────────────────────────────────────────────────────
	rs_raw = doc.get("ruleset")
	if not isinstance(rs_raw, dict):
		raise ValueError("YAML document must contain a 'ruleset' mapping")

	if "name" not in rs_raw:
		raise ValueError("ruleset.name is required")
	if "model" not in rs_raw:
		raise ValueError("ruleset.model is required")

	ruleset: dict[str, Any] = {
		"name":          str(rs_raw["name"]),
		"model_name":    str(rs_raw["model"]),
		"priority":      int(rs_raw.get("priority", 100)),
		"stop_on_match": bool(rs_raw.get("stop_on_match", False)),
		"enabled":       bool(rs_raw.get("enabled", True)),
		"yaml_source":   yaml_text,
	}
	for optional in ("description", "tenant_id", "schedule_cron"):
		if optional in rs_raw:
			ruleset[optional] = rs_raw[optional]

	# ── rules section ────────────────────────────────────────────────────────
	rules_raw = doc.get("rules")
	if not isinstance(rules_raw, list):
		raise ValueError("YAML document must contain a 'rules' list")

	compiled_rules: list[dict[str, Any]] = []
	for idx, rule_raw in enumerate(rules_raw):
		if not isinstance(rule_raw, dict):
			raise ValueError(f"rules[{idx}] must be a mapping")

		name = rule_raw.get("name")
		if not name:
			raise ValueError(f"rules[{idx}].name is required")

		on_raw = rule_raw.get("on", "on_create")
		trigger_event = _normalise_event(str(on_raw))

		# Infer trigger_type from event string
		if trigger_event == "on_schedule":
			trigger_type = "schedule"
		elif trigger_event in ("form_submit",):
			trigger_type = "form_submit"
		elif trigger_event == "api":
			trigger_type = "api"
		else:
			trigger_type = "model_event"

		# conditions
		raw_when = rule_raw.get("when", [])
		if not isinstance(raw_when, list):
			raise ValueError(f"rules[{idx}].when must be a list")
		conditions_json = [_compile_condition(c) for c in raw_when]

		# actions
		raw_then = rule_raw.get("then", [])
		if not isinstance(raw_then, list):
			raise ValueError(f"rules[{idx}].then must be a list")
		actions_json = [_compile_action(a) for a in raw_then]

		compiled_rules.append({
			"name":              str(name),
			"trigger_event":     trigger_event,
			"trigger_type":      trigger_type,
			"conditions_json":   conditions_json,
			"actions_json":      actions_json,
			"order":             int(rule_raw.get("order", idx)),
			"enabled":           bool(rule_raw.get("enabled", True)),
			"stop_after_actions": bool(rule_raw.get("stop_after_actions", False)),
			"status":            str(rule_raw.get("status", "active")),
		})

	return {"ruleset": ruleset, "rules": compiled_rules}


# ---------------------------------------------------------------------------
# decompile_to_yaml
# ---------------------------------------------------------------------------

def decompile_to_yaml(ruleset_dict: dict[str, Any], rules_list: list[dict[str, Any]]) -> str:
	"""Convert a ruleset dict + rules list back to canonical YAML text.

	Parameters
	----------
	ruleset_dict:
	    Dict with at minimum {name, model_name, ...} — typically the ORM
	    model converted via __dict__ or a serialised mapping.
	rules_list:
	    List of rule dicts, each with {name, trigger_event, conditions_json,
	    actions_json, ...}.

	Returns
	-------
	YAML string suitable for round-tripping through compile_yaml().
	"""
	try:
		import yaml
	except ImportError as exc:
		raise ImportError(
			"decompile_to_yaml requires PyYAML — install it with: pip install pyyaml"
		) from exc

	# ── ruleset block ────────────────────────────────────────────────────────
	rs: dict[str, Any] = {
		"name":         ruleset_dict.get("name", ""),
		"model":        ruleset_dict.get("model_name", ruleset_dict.get("model", "")),
		"priority":     ruleset_dict.get("priority", 100),
		"stop_on_match": ruleset_dict.get("stop_on_match", False),
	}
	for optional in ("description", "tenant_id", "schedule_cron"):
		val = ruleset_dict.get(optional)
		if val is not None:
			rs[optional] = val

	# ── rules block ──────────────────────────────────────────────────────────
	rules_out: list[dict[str, Any]] = []
	for rule in rules_list:
		trigger = rule.get("trigger_event", "on_create")
		# Reverse-map canonical events to shorthand where possible
		_REVERSE_EVENTS = {
			"on_before_create": "before_create",
			"on_before_update": "before_update",
			"on_before_delete": "before_delete",
			"on_create":  "after_create",
			"on_update":  "after_update",
			"on_delete":  "after_delete",
		}
		on_val = _REVERSE_EVENTS.get(trigger, trigger)

		conditions_raw = rule.get("conditions_json") or []
		actions_raw    = rule.get("actions_json") or []

		# Ensure JSON-serialisable types (ORM objects may carry SA-specific state)
		try:
			conditions_raw = json.loads(json.dumps(conditions_raw, default=str))
			actions_raw    = json.loads(json.dumps(actions_raw,    default=str))
		except Exception:
			pass

		rule_out: dict[str, Any] = {
			"name": rule.get("name", ""),
			"on":   on_val,
		}
		if conditions_raw:
			rule_out["when"] = _decompile_conditions(conditions_raw)
		if actions_raw:
			rule_out["then"] = [_decompile_action(a) for a in actions_raw]
		if rule.get("stop_after_actions"):
			rule_out["stop_after_actions"] = True
		if not rule.get("enabled", True):
			rule_out["enabled"] = False

		rules_out.append(rule_out)

	doc = {"ruleset": rs, "rules": rules_out}
	return yaml.dump(doc, allow_unicode=True, default_flow_style=False, sort_keys=False)


def _decompile_conditions(conditions: list[dict]) -> list[Any]:
	"""Convert engine condition dicts back to compact YAML-ready structures."""
	out = []
	for cond in conditions:
		if cond.get("type") == "group":
			join = (cond.get("join") or "AND").upper()
			key = "any_of" if join == "OR" else "all_of"
			out.append({key: _decompile_conditions(cond.get("conditions", []))})
		else:
			node: dict[str, Any] = {
				"field": cond.get("field", ""),
				"op":    cond.get("op", "="),
			}
			if "value" in cond and cond.get("op") not in ("is_null", "is_not_null"):
				node["value"] = cond["value"]
			if cond.get("logic") and cond["logic"] != "AND":
				node["logic"] = cond["logic"]
			out.append(node)
	return out


def _decompile_action(action: dict[str, Any]) -> dict[str, Any]:
	"""Convert an engine action dict back to its YAML shorthand where possible."""
	atype = action.get("type", "")

	if atype == "block":
		return {"block": action.get("message", "")}

	if atype == "set_field":
		return {"set_field": {"field": action.get("field", ""), "value": action.get("value")}}

	if atype == "send_email":
		val: dict[str, Any] = {"to": action.get("to", ""), "subject": action.get("subject", "")}
		if action.get("body"):
			val["body"] = action["body"]
		return {"send_email": val}

	if atype == "notify_user":
		val = {"user_id": action.get("user_id"), "message": action.get("message", "")}
		if action.get("level"):
			val["level"] = action["level"]
		return {"notify_user": val}

	if atype == "call_webhook":
		val = {"url": action.get("url", "")}
		if action.get("payload"):
			val["payload"] = action["payload"]
		return {"call_webhook": val}

	if atype == "transform_value":
		return {"transform_value": {"field": action.get("field", ""), "transform": action.get("transform", "")}}

	if atype == "create_record":
		return {"create_record": {"model": action.get("model", ""), "fields": action.get("fields", {})}}

	if atype == "add_error":
		return {"add_error": {"field": action.get("field", ""), "message": action.get("message", "")}}

	if atype == "start_workflow":
		val = {"process_definition": action.get("process_definition", "")}
		if action.get("context"):
			val["context"] = action["context"]
		return {"start_workflow": val}

	if atype == "update_related":
		return {
			"update_related": {
				"fk_field": action.get("fk_field", ""),
				"model":    action.get("model", ""),
				"set":      action.get("set", {}),
			}
		}

	# Unknown — pass through as-is so nothing is silently lost
	return dict(action)
