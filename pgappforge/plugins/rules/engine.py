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
from datetime import datetime, timezone
from typing import Any, Callable

log = logging.getLogger(__name__)


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

	def __init__(self, session_factory: Callable | None = None) -> None:
		self._session_factory = session_factory

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

		from .models import RuleSet

		rule_sets = (
			session.query(RuleSet)
			.filter(
				RuleSet.model_name == model_name,
				RuleSet.enabled.is_(True),
			)
			.order_by(RuleSet.priority)
			.all()
		)

		ctx = self._record_to_dict(record)

		for rs in rule_sets:
			for rule in rs.rules:
				if not rule.enabled:
					continue
				if not self._event_matches(rule.trigger_event, event, record):
					continue

				conditions = rule.conditions_json or []
				if not self._evaluate_conditions(conditions, ctx):
					self._log_execution(rule, record, "skipped", session)
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

		for action in actions:
			atype = action.get("type", "")

			if atype == "set_field":
				field = action.get("field")
				value = action.get("value")
				if field:
					setattr(record, field, value)

			elif atype == "block":
				message = action.get("message", "Action blocked by business rule.")
				raise RulesValidationError(message)

			elif atype == "send_email":
				to      = action.get("to", "")
				subject = action.get("subject", "(no subject)")
				body    = action.get("body", "")
				log.info("Rules engine: send_email stub to=%r subject=%r", to, subject)

			elif atype == "call_webhook":
				url     = action.get("url", "")
				payload = action.get("payload", {})
				try:
					import requests  # type: ignore[import]
					resp = requests.post(url, json=payload, timeout=10)
					log.info(
						"Rules engine: webhook %r -> status %d", url, resp.status_code
					)
				except ImportError:
					log.warning(
						"Rules engine: call_webhook requires 'requests'; skipping url=%r", url
					)
				except Exception as exc:
					log.warning("Rules engine: webhook error url=%r err=%s", url, exc)

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
		"""Append a RuleExecution audit row."""
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
			session.add(exec_row)
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
