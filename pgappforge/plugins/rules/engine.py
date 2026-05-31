"""
pgappforge/plugins/rules/engine.py

Rules evaluation engine.

Public surface
--------------
RulesValidationError   — raised by a "block" action
RulesEngine            — evaluates rule sets against model events
get_rules_engine()     — module-level singleton accessor
"""
from __future__ import annotations

import logging
import operator
import re as _re
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# TTL cache for ruleset lookups (avoids a DB round-trip on every write event)
# ---------------------------------------------------------------------------

_SIMPLE_CACHE: dict[str, tuple[float, list]] = {}
_CACHE_TTL: float = 30.0
_CACHE_LOCK = threading.Lock()

# Protected fields that set_field must never overwrite
_PROTECTED_FIELDS = frozenset({
	"id", "password", "password_hash", "is_admin", "tenant_id", "owner_id", "created_by_id",
})

# URL scheme allowlist for webhooks (configurable via FAB_RULES_WEBHOOK_ALLOWLIST)
_ALLOWED_WEBHOOK_SCHEMES = frozenset({"https"})


# ---------------------------------------------------------------------------
# Condition operators
# ---------------------------------------------------------------------------

_OPS: dict[str, Callable[[Any, Any], bool]] = {
	"=":            operator.eq,
	"!=":           operator.ne,
	">":            operator.gt,
	"<":            operator.lt,
	">=":           operator.ge,
	"<=":           operator.le,
	"contains":     lambda a, b: b in str(a),
	"in":           lambda a, b: a in (b if isinstance(b, list) else [b]),
	"is_null":      lambda a, b: a is None,
	"is_not_null":  lambda a, b: a is not None,
	"starts_with":  lambda a, b: str(a).startswith(str(b)),
}


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class RulesValidationError(Exception):
	"""Raised when a 'block' action fires; message is user-facing."""


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class RulesEngine:
	"""
	Evaluate rule sets for a given (model_name, event, record) triple.

	Parameters
	----------
	session_factory:
	    Zero-arg callable that returns a SQLAlchemy session.
	    If None the engine will try Flask-SQLAlchemy db.session at call time.
	"""

	def __init__(self, session_factory: Callable | None = None, cache_ttl: float = _CACHE_TTL) -> None:
		self._session_factory = session_factory
		self._cache_ttl = cache_ttl

	# ------------------------------------------------------------------
	# Cache management
	# ------------------------------------------------------------------

	def _load_rules(self, session, model_name: str) -> list:
		"""Return active rules for model_name, using TTL cache to avoid N+1 per event."""
		now = time.monotonic()
		with _CACHE_LOCK:
			cached = _SIMPLE_CACHE.get(model_name)
		if cached is not None and (now - cached[0]) < self._cache_ttl:
			return cached[1]
		from .models import RuleSet, Rule
		from sqlalchemy import select as sa_select
		from sqlalchemy.orm import selectinload
		rules = session.execute(
			sa_select(Rule)
			.join(RuleSet, RuleSet.id == Rule.ruleset_id)
			.filter(
				RuleSet.model_name == model_name,
				RuleSet.enabled.is_(True),
				Rule.enabled.is_(True),
			)
			.order_by(RuleSet.priority, Rule.order)
		).scalars().all()
		with _CACHE_LOCK:
			_SIMPLE_CACHE[model_name] = (now, rules)
		return rules

	def invalidate(self, model_name: str | None = None) -> None:
		"""Evict a model's rule cache (or all models if model_name is None)."""
		with _CACHE_LOCK:
			if model_name is None:
				_SIMPLE_CACHE.clear()
			else:
				_SIMPLE_CACHE.pop(model_name, None)

	# ------------------------------------------------------------------
	# Public API
	# ------------------------------------------------------------------

	def evaluate(
		self,
		model_name: str,
		event: str,
		record: Any,
		session=None,
	) -> None:
		"""
		Fire all enabled rules that match *event* for *model_name*.

		Raises RulesValidationError if any 'block' action triggers.
		"""
		if session is None:
			session = self._get_session()

		ctx = self._record_to_dict(record)
		rules = self._load_rules(session, model_name)

		for rule in rules:
			if not self._event_matches(rule.trigger_event, event, record):
				continue
			conditions = rule.conditions_json or []
			if not self._evaluate_conditions(conditions, ctx):
				continue
			try:
				outcome = self._execute_actions(
					rule.actions_json or [], ctx, record, session
				)
			except RulesValidationError:
				self._log_execution(rule, record, "blocked", session)
				raise
			except Exception as exc:
				log.exception("Rules engine: action error in rule %r", rule.name)
				self._log_execution(rule, record, "error", session, error=str(exc))
				continue
			self._log_execution(rule, record, outcome, session)

	# ------------------------------------------------------------------
	# Internal helpers
	# ------------------------------------------------------------------

	def _get_session(self):
		if self._session_factory is not None:
			return self._session_factory()
		try:
			from pgappforge import db  # type: ignore[attr-defined]
			return db.session
		except Exception as exc:
			raise RuntimeError(
				"RulesEngine: no session available — pass session= or configure Flask-SQLAlchemy."
			) from exc

	def _event_matches(self, trigger: str, event: str, record: Any) -> bool:
		"""
		Returns True if *trigger* matches the fired *event*.

		Supports:
		  "on_create", "on_update", "on_delete"   — exact match
		  "on_field_change:<field>"               — checks SQLAlchemy attribute history
		"""
		if ":" not in trigger:
			return trigger == event

		prefix, field = trigger.split(":", 1)
		if prefix != "on_field_change":
			return trigger == event

		# Inspect SQLAlchemy attribute history
		try:
			from sqlalchemy import inspect as sa_inspect
			state = sa_inspect(record)
			hist = state.attrs[field].history
			# history.added/deleted are non-empty when field changed
			return bool(hist.added or hist.deleted)
		except Exception:
			return False

	def _record_to_dict(self, record: Any) -> dict[str, Any]:
		"""Extract column values from a SQLAlchemy model instance into a plain dict."""
		try:
			from sqlalchemy import inspect as sa_inspect
			mapper = sa_inspect(type(record))
			return {
				col.key: getattr(record, col.key, None)
				for col in mapper.mapper.column_attrs
			}
		except Exception:
			# Fallback: use __dict__ minus SQLAlchemy internals
			return {
				k: v
				for k, v in vars(record).items()
				if not k.startswith("_")
			}

	def _evaluate_conditions(
		self,
		conditions: list[dict[str, Any]],
		ctx: dict[str, Any],
	) -> bool:
		"""
		Evaluate a list of conditions with AND/OR logic.

		Each condition dict: {field, op, value, logic}
		  logic = "AND" (default) | "OR"

		OR conditions are collected into groups; the overall result is:
		  AND of all AND-conditions, plus (OR-group is True if any OR-cond matches).
		"""
		if not conditions:
			return True

		result = True
		or_group: list[bool] = []

		for cond in conditions:
			field   = cond.get("field", "")
			op      = cond.get("op", "=")
			value   = cond.get("value")
			logic   = (cond.get("logic") or "AND").upper()

			actual = ctx.get(field)
			fn = _OPS.get(op)
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

	def _execute_actions(
		self,
		actions: list[dict[str, Any]],
		ctx: dict[str, Any],
		record: Any,
		session,
	) -> str:
		"""
		Execute action list.  Returns outcome string.

		Action types
		------------
		set_field   — {type, field, value}
		block       — {type, message}
		send_email  — {type, to, subject, body}  (stubbed — logs only)
		call_webhook — {type, url, payload}
		"""
		outcome = "executed"

		# Run block actions first — prevents set_field mutations on a blocked record
		block_actions = [a for a in actions if a.get("type") == "block"]
		other_actions = [a for a in actions if a.get("type") != "block"]

		for action in block_actions + other_actions:
			atype = action.get("type", "")

			if atype == "set_field":
				field = action.get("field", "")
				value = action.get("value")
				if not field:
					continue
				if field in _PROTECTED_FIELDS:
					log.error("Rules engine: set_field refused — %r is a protected field", field)
					continue
				# Subclasses may declare _rules_mutable_fields to allowlist columns
				mutable = getattr(type(record), "_rules_mutable_fields", frozenset())
				if mutable and field not in mutable:
					log.warning(
						"Rules engine: set_field refused — %r not in _rules_mutable_fields for %s",
						field, type(record).__name__,
					)
					continue
				if hasattr(record, field):
					setattr(record, field, value)

			elif atype == "block":
				message = action.get("message", "Action blocked by business rule.")
				raise RulesValidationError(message)

			elif atype == "send_email":
				to      = action.get("to", "")
				subject = action.get("subject", "(no subject)")
				log.info("Rules engine: send_email stub to=%r subject=%r", to, subject)

			elif atype == "call_webhook":
				url = action.get("url", "")
				if not url:
					continue
				try:
					from flask import current_app
					allowlist = set(current_app.config.get("FAB_RULES_WEBHOOK_ALLOWLIST", []))
				except RuntimeError:
					allowlist = set()
				if not allowlist:
					log.warning("Rules engine: call_webhook skipped — FAB_RULES_WEBHOOK_ALLOWLIST is empty")
					continue
				try:
					import ipaddress, socket
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
					resp = requests.post(url, json=payload, timeout=(2, 5), allow_redirects=False,
					                     headers={"User-Agent": "pgappforge-rules/1"})
					log.info("Rules engine: webhook %r -> %d", url, resp.status_code)
				except ImportError:
					log.warning("Rules engine: call_webhook requires 'requests'")
				except Exception as exc:
					log.warning("Rules engine: webhook refused url=%r err=%s", url, exc)
					outcome = "webhook_error"

			else:
				log.warning("Rules engine: unknown action type %r — skipping", atype)

		return outcome

	def _log_execution(
		self,
		rule: Any,
		record: Any,
		outcome: str,
		session,
		error: str | None = None,
	) -> None:
		"""Append a RuleExecution audit row. Skipped outcomes are not persisted."""
		if outcome == "skipped":
			return
		from .models import RuleExecution

		record_id = None
		try:
			record_id = str(getattr(record, "id", None))
		except Exception:
			pass

		exec_row = RuleExecution(
			rule_id=rule.id,
			triggered_at=datetime.now(timezone.utc),
			record_id=record_id,
			outcome=outcome,
			error=error,
		)
		try:
			# Use a separate session so a rollback on the business session
			# does not lose the audit record (e.g. when a 'block' fires).
			bind = session.get_bind()
			from sqlalchemy.orm import Session as SASession
			with SASession(bind) as audit_session:
				audit_session.add(exec_row)
				audit_session.commit()
		except Exception as exc:
			log.warning("Rules engine: could not persist RuleExecution: %s", exc)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_engine: RulesEngine | None = None


def get_rules_engine() -> RulesEngine:
	"""Return the module-level RulesEngine singleton, creating it if needed."""
	global _engine
	if _engine is None:
		_engine = RulesEngine()
	return _engine
