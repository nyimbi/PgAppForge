"""
pgappforge/plugins/rules/event_rules.py

Event-triggered rules engine — enables cross-model / cross-plugin business rules.

An *event rule* is triggered by a domain event (fired via pgappforge.events.emit)
rather than by a model lifecycle hook.  This lets you write rules like:

    "When finance.loan.application.created fires AND the payload shows
     insurance_status == 'LAPSED' → emit finance.loan.application.blocked"

Conditions and actions share the same syntax as the existing RulesEngine so
rule YAML is portable across both engines.

Public surface
--------------
EventRuleEngine
    .load_rules_from_yaml(yaml_text)  — parse and register a YAML rule list
    .load_rule(rule_dict)             — add a single rule dict
    .subscribe_to_router(router)      — wire handlers into an EventRouter
    .list_rules()                     — return registered rule dicts
    .dry_run(event_type, payload, tenant_id) -> dict — simulate without side effects
"""
from __future__ import annotations

import logging
from typing import Any

import yaml

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Re-use condition + action primitives from the existing engine
# ---------------------------------------------------------------------------
from .engine import (
	_OPS,
	_PROTECTED_FIELDS,
	_ALLOWED_WEBHOOK_SCHEMES,
	_resolve_value,
	RulesValidationError,
	RulesFieldError,
)


# Human-friendly op aliases → canonical _OPS keys
_OP_ALIASES: dict[str, str] = {
	"eq": "=", "ne": "!=", "neq": "!=",
	"gt": ">", "lt": "<", "gte": ">=", "lte": "<=",
}

# ---------------------------------------------------------------------------
# Condition evaluation (standalone — no model/session dependency)
# ---------------------------------------------------------------------------

def _evaluate_conditions(
	conditions: list[dict[str, Any]],
	ctx: dict[str, Any],
) -> bool:
	"""Evaluate a condition list (AND/OR) against an arbitrary dict context.

	Identical semantics to RulesEngine._evaluate_conditions but extracted as a
	module-level function so EventRuleEngine can call it without a session.

	Each condition: {field, op, value, logic}
	  logic = "AND" (default) | "OR"
	"""
	if not conditions:
		return True

	result = True
	or_group: list[bool] = []

	for cond in conditions:
		field  = cond.get("field", "")
		op     = cond.get("op", "=")
		value  = _resolve_value(cond.get("value"), ctx)
		logic  = (cond.get("logic") or "AND").upper()

		actual = ctx.get(field)
		fn = _OPS.get(_OP_ALIASES.get(op, op))
		try:
			match = fn(actual, value) if fn is not None else False
		except Exception:
			match = False

		if logic == "OR":
			or_group.append(match)
		else:
			result = result and match

	if or_group:
		result = result and any(or_group)

	return result


# ---------------------------------------------------------------------------
# Action execution (standalone — operates on payload dict, no ORM record)
# ---------------------------------------------------------------------------

def _execute_actions(
	actions: list[dict[str, Any]],
	ctx: dict[str, Any],
	*,
	dry_run: bool = False,
	tenant_id: str = "",
	triggering_event_type: str = "",
) -> tuple[str, list[dict]]:
	"""Execute an action list against a payload context dict.

	Parameters
	----------
	actions:
	    List of action dicts (same schema as RulesEngine action dicts).
	ctx:
	    Event payload dict, used for $field/${{template}} resolution.
	dry_run:
	    When True, skip all side-effects; return what WOULD happen.
	tenant_id:
	    Forwarded to emit_event calls.

	Returns
	-------
	(outcome, dry_run_items)
	    outcome      — "executed" | "blocked" | "webhook_error"
	    dry_run_items — non-empty only when dry_run=True; list of action dicts
	                    that would have been executed.
	"""
	outcome = "executed"
	dry_items: list[dict] = []

	# block actions execute first so they short-circuit set_field mutations
	block_actions = [a for a in actions if a.get("type") == "block"]
	other_actions  = [a for a in actions if a.get("type") != "block"]

	for action in block_actions + other_actions:
		atype = action.get("type", "")

		# ---- block --------------------------------------------------------
		if atype == "block":
			message = action.get("message", "Action blocked by business rule.")
			if dry_run:
				dry_items.append({"type": "block", "message": message})
				return "blocked", dry_items
			raise RulesValidationError(message)

		# ---- add_error ----------------------------------------------------
		elif atype == "add_error":
			field   = action.get("field", "")
			message = action.get("message", "Validation error.")
			if dry_run:
				dry_items.append({"type": "add_error", "field": field, "message": message})
				return "blocked", dry_items
			raise RulesFieldError(field, message)

		# ---- set_field (payload mutation) ---------------------------------
		elif atype == "set_field":
			field = action.get("field", "")
			value = _resolve_value(action.get("value"), ctx)
			if not field:
				continue
			if field in _PROTECTED_FIELDS:
				log.error(
					"EventRuleEngine: set_field refused — %r is a protected field", field
				)
				continue
			if dry_run:
				dry_items.append({"type": "set_field", "field": field, "value": value})
			else:
				ctx[field] = value

		# ---- send_email ---------------------------------------------------
		elif atype == "send_email":
			to      = action.get("to", "")
			subject = action.get("subject", "(no subject)")
			if dry_run:
				dry_items.append(dict(action))
			else:
				log.info("EventRuleEngine: send_email stub to=%r subject=%r", to, subject)

		# ---- call_webhook -------------------------------------------------
		elif atype == "call_webhook":
			url = action.get("url", "")
			if not url:
				continue
			if dry_run:
				dry_items.append(dict(action))
				continue
			try:
				from flask import current_app
				allowlist = set(current_app.config.get("FAB_RULES_WEBHOOK_ALLOWLIST", []))
			except RuntimeError:
				allowlist = set()
			if not allowlist:
				log.warning(
					"EventRuleEngine: call_webhook skipped — FAB_RULES_WEBHOOK_ALLOWLIST is empty"
				)
				continue
			try:
				import ipaddress
				import socket
				from urllib.parse import urlparse

				parsed = urlparse(url)
				if parsed.scheme not in _ALLOWED_WEBHOOK_SCHEMES:
					raise ValueError(f"scheme {parsed.scheme!r} not allowed")
				host = (parsed.hostname or "").lower()
				if host not in allowlist:
					raise ValueError(f"host {host!r} not in FAB_RULES_WEBHOOK_ALLOWLIST")
				for info in socket.getaddrinfo(host, None):
					ip = ipaddress.ip_address(info[4][0])
					if ip.is_private or ip.is_loopback or ip.is_link_local:
						raise ValueError(f"refused private/loopback IP {ip}")
				import requests  # type: ignore[import]
				payload = action.get("payload", ctx.copy())
				resp = requests.post(
					url,
					json=payload,
					timeout=(2, 5),
					allow_redirects=False,
					headers={"User-Agent": "pgappforge-rules/1"},
				)
				log.info("EventRuleEngine: webhook %r -> %d", url, resp.status_code)
			except ImportError:
				log.warning("EventRuleEngine: call_webhook requires 'requests'")
			except Exception as exc:
				log.warning("EventRuleEngine: webhook refused url=%r err=%s", url, exc)
				outcome = "webhook_error"

		# ---- start_workflow -----------------------------------------------
		elif atype == "start_workflow":
			if dry_run:
				dry_items.append(dict(action))
			else:
				workflow_name = action.get("workflow", "")
				if not workflow_name:
					log.warning("EventRuleEngine: start_workflow action missing 'workflow' field — skipping")
					continue
				try:
					from pgappforge.workflow import get_yaml_engine
					engine = get_yaml_engine()
					input_data: dict[str, Any] = {
						k: _resolve_value(v, ctx) for k, v in (action.get("inputs") or {}).items()
					}
					input_data.update(ctx)
					instance = engine.start(workflow_name, input_data, tenant_id=ctx.get("tenant_id", ""))
					log.debug("EventRuleEngine: started workflow %r → instance %s", workflow_name, instance.id)
				except Exception as exc:
					log.warning("EventRuleEngine: start_workflow %r failed: %s", workflow_name, exc)

		# ---- emit_event ---------------------------------------------------
		elif atype == "emit_event":
			event_type = action.get("event", "")
			if not event_type:
				log.warning(
					"EventRuleEngine: emit_event action missing 'event' field — skipping"
				)
				continue
			raw_payload: dict[str, Any] = action.get("payload") or {}
			resolved_payload: dict[str, Any] = {
				k: _resolve_value(v, ctx) for k, v in raw_payload.items()
			}
			if dry_run:
				dry_items.append(
					{"type": "emit_event", "event": event_type, "payload": resolved_payload}
				)
			else:
				log.debug(
					"EventRuleEngine: emit_event %r tenant=%r payload_keys=%s",
					event_type, tenant_id, list(resolved_payload.keys()),
				)
				try:
					from pgappforge.events import emit as _emit
					_emit(event_type, resolved_payload, tenant_id=tenant_id)
				except ImportError:
					log.debug(
						"EventRuleEngine: emit_event skipped — pgappforge.events not available"
					)
				except Exception as exc:
					log.warning("EventRuleEngine: emit_event %r failed: %s", event_type, exc)

		elif atype == "callback":
			fn = action.get("fn")
			if callable(fn):
				if dry_run:
					dry_items.append({"type": "callback"})
				else:
					try:
						fn(triggering_event_type, ctx)
					except Exception as exc:
						log.warning("EventRuleEngine: callback failed: %s", exc)
			else:
				log.warning("EventRuleEngine: callback action missing callable 'fn'")

		else:
			log.warning("EventRuleEngine: unknown action type %r — skipping", atype)

	return outcome, dry_items


# ---------------------------------------------------------------------------
# EventRuleEngine
# ---------------------------------------------------------------------------

class EventRuleEngine:
	"""Rules evaluated when domain events fire — enables cross-model/cross-plugin rules.

	An event rule has:
	- trigger: on_event pattern (e.g. 'finance.loan.application.created')
	- conditions: evaluated against the event payload dict (same syntax as existing rules)
	- actions: same action types as existing rules (emit_event, start_workflow,
	           call_webhook, send_email, set_field, block, add_error)

	Example YAML rule definition::

	    - name: block_loan_if_insurance_lapsed
	      trigger:
	        on_event: 'finance.loan.application.created'
	      conditions:
	        - field: insurance_status
	          op: eq
	          value: LAPSED
	      actions:
	        - type: emit_event
	          event: finance.loan.application.blocked
	          payload:
	            reason: Insurance policy lapsed — loan blocked
	            loan_id: '{{loan_id}}'

	Usage::

	    engine = EventRuleEngine()
	    engine.load_rules_from_yaml(yaml_text)
	    engine.subscribe_to_router(get_router())
	    # Now when events fire, matching rules run automatically
	"""

	def __init__(self) -> None:
		# list of normalised rule dicts
		self._rules: list[dict[str, Any]] = []
		self._subscribed_patterns: set[str] = set()

	# ------------------------------------------------------------------
	# Loading
	# ------------------------------------------------------------------

	def load_rules_from_yaml(self, yaml_text: str) -> int:
		"""Parse *yaml_text* as a YAML list of event-rule dicts and register them.

		Returns the number of rules successfully loaded.

		Raises ValueError if the top-level structure is not a list.
		"""
		data = yaml.safe_load(yaml_text)
		if not isinstance(data, list):
			raise ValueError(
				f"EventRuleEngine.load_rules_from_yaml: expected a YAML list, got {type(data).__name__}"
			)
		loaded = 0
		for item in data:
			if not isinstance(item, dict):
				log.warning("EventRuleEngine: skipping non-dict rule entry: %r", item)
				continue
			try:
				self.load_rule(item)
				loaded += 1
			except Exception as exc:
				log.warning("EventRuleEngine: failed to load rule %r: %s", item.get("name"), exc)
		return loaded

	def load_rule(self, rule_dict: dict[str, Any]) -> None:
		"""Add a single rule dict.

		Required keys:
		  name      — str, unique human identifier
		  trigger   — dict with key 'on_event': glob pattern string
		  actions   — list of action dicts

		Optional keys:
		  conditions       — list of condition dicts (default: always match)
		  stop_after_match — bool, stop processing further rules after this one matches
		  enabled          — bool (default: True)

		Raises ValueError for missing/invalid required keys.
		"""
		name = rule_dict.get("name")
		if not name:
			raise ValueError("rule_dict must have a 'name' key")

		trigger = rule_dict.get("trigger")
		# Accept trigger as a plain string (glob pattern) or as a dict with 'on_event' key
		if isinstance(trigger, str):
			on_event = trigger
		elif isinstance(trigger, dict):
			on_event = trigger.get("on_event", "")
		else:
			on_event = ""
		if not on_event:
			raise ValueError(
				f"rule {name!r}: 'trigger' must be a glob string or dict with 'on_event' key"
			)

		actions = rule_dict.get("actions")
		if not isinstance(actions, list):
			raise ValueError(f"rule {name!r}: 'actions' must be a list")

		normalised: dict[str, Any] = {
			"name":             str(name),
			"on_event":         str(on_event),
			"conditions":       list(rule_dict.get("conditions") or []),
			"actions":          actions,
			"stop_after_match": bool(rule_dict.get("stop_after_match", False)),
			"enabled":          bool(rule_dict.get("enabled", True)),
		}
		self._rules.append(normalised)
		log.debug(
			"EventRuleEngine: loaded rule %r (trigger=%r)", name, normalised["on_event"]
		)

	# ------------------------------------------------------------------
	# Router integration
	# ------------------------------------------------------------------

	def subscribe_to_router(self, router: Any) -> None:
		"""Subscribe _handle_event to *router* for every registered rule's on_event pattern.

		Patterns are de-duplicated so each distinct glob is subscribed at most once.
		Safe to call multiple times (e.g. after loading additional rules) — each call
		registers a new subscription for newly-seen patterns only.
		"""
		seen: set[str] = set(
			getattr(self, "_subscribed_patterns", set())
		)
		for rule in self._rules:
			pattern = rule["on_event"]
			if pattern in seen:
				continue
			router.subscribe(pattern, self._handle_event)
			seen.add(pattern)
			log.debug(
				"EventRuleEngine: subscribed to router pattern %r", pattern
			)
		self._subscribed_patterns: set[str] = seen

	# ------------------------------------------------------------------
	# Event handler
	# ------------------------------------------------------------------

	def _handle_event(
		self,
		event_type: str,
		payload: dict[str, Any],
		tenant_id: str,
	) -> None:
		"""Called by EventRouter when a matching event fires.

		Evaluates each enabled rule whose on_event pattern matches *event_type*,
		then executes its actions against the payload.
		"""
		import fnmatch

		ctx = dict(payload)  # shallow copy — actions may mutate via set_field
		ctx.setdefault("tenant_id", tenant_id)

		for rule in self._rules:
			if not rule.get("enabled", True):
				continue
			if not fnmatch.fnmatch(event_type, rule["on_event"]):
				continue
			if not _evaluate_conditions(rule["conditions"], ctx):
				continue

			log.debug(
				"EventRuleEngine: rule %r matched event %r tenant=%r",
				rule["name"], event_type, tenant_id,
			)
			try:
				outcome, _ = _execute_actions(
					rule["actions"],
					ctx,
					dry_run=False,
					tenant_id=tenant_id,
					triggering_event_type=event_type,
				)
			except RulesValidationError as exc:
				log.info(
					"EventRuleEngine: rule %r blocked event %r: %s",
					rule["name"], event_type, exc,
				)
				raise
			except Exception as exc:
				log.exception(
					"EventRuleEngine: action error in rule %r for event %r",
					rule["name"], event_type,
				)
				continue

			if rule.get("stop_after_match"):
				break

	def handle_event(
		self,
		event_type: str,
		payload: dict[str, Any],
		tenant_id: str = "",
	) -> None:
		"""Public alias for _handle_event — called directly in tests and service code."""
		self._handle_event(event_type, payload, tenant_id)

	# ------------------------------------------------------------------
	# Introspection
	# ------------------------------------------------------------------

	def list_rules(self) -> list[dict[str, Any]]:
		"""Return a shallow-copy list of all registered rule dicts."""
		return [dict(r) for r in self._rules]

	# ------------------------------------------------------------------
	# Dry-run simulation
	# ------------------------------------------------------------------

	def dry_run(
		self,
		event_type: str,
		payload: dict[str, Any],
		tenant_id: str = "",
	) -> dict[str, Any]:
		"""Simulate rule evaluation without executing any side effects.

		Returns a summary dict:
		  rules_matched        — list of rule names that matched
		  would_block          — True if any block/add_error would fire
		  block_message        — message for the first blocking action
		  block_field          — field name for add_error, None for block
		  would_set            — {field: value} for set_field actions
		  would_send_emails    — list of send_email action dicts
		  would_call_webhooks  — list of call_webhook action dicts
		  would_start_workflows— list of start_workflow action dicts
		  would_emit_events    — list of emit_event action dicts
		"""
		import fnmatch

		result: dict[str, Any] = {
			"rules_matched":         [],
			"would_block":           False,
			"block_message":         "",
			"block_field":           None,
			"would_set":             {},
			"would_send_emails":     [],
			"would_call_webhooks":   [],
			"would_start_workflows": [],
			"would_emit_events":     [],
		}

		ctx = dict(payload)
		ctx.setdefault("tenant_id", tenant_id)

		for rule in self._rules:
			if not rule.get("enabled", True):
				continue
			if not fnmatch.fnmatch(event_type, rule["on_event"]):
				continue
			if not _evaluate_conditions(rule["conditions"], ctx):
				continue

			result["rules_matched"].append(rule["name"])

			_outcome, dry_items = _execute_actions(
				rule["actions"],
				ctx,
				dry_run=True,
				tenant_id=tenant_id,
			)

			for item in dry_items:
				atype = item.get("type", "")
				if atype == "block":
					result["would_block"]   = True
					result["block_message"] = item.get("message", "")
					result["block_field"]   = None
					return result  # first block short-circuits
				elif atype == "add_error":
					result["would_block"]   = True
					result["block_field"]   = item.get("field", "")
					result["block_message"] = item.get("message", "")
					return result
				elif atype == "set_field":
					result["would_set"][item["field"]] = item["value"]
				elif atype == "send_email":
					result["would_send_emails"].append(item)
				elif atype == "call_webhook":
					result["would_call_webhooks"].append(item)
				elif atype == "start_workflow":
					result["would_start_workflows"].append(item)
				elif atype == "emit_event":
					result["would_emit_events"].append(item)
				elif atype == "callback":
					result.setdefault("would_callbacks", []).append(item)

			if rule.get("stop_after_match"):
				break

		return result
