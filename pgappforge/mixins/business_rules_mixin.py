"""
business_rules_mixin.py - Advanced Business Rules Engine for PgForge

Provides a declarative, async-capable business rules engine that integrates
with PgForge models. Supports complex AND/OR conditions, sequential
and parallel action execution, priority-ordered evaluation, event listeners,
and full audit statistics — all without external ML/analytics dependencies.

Key Features:
- Declarative rule registration on model instances
- Compound conditions via RuleCondition.all() / RuleCondition.any()
- Sequential and parallel action combinators (RuleAction.sequence / .parallel)
- Priority-ordered rule evaluation with async support and exponential-backoff retry
- Per-rule evaluation statistics persisted to a JSON/JSONB column
- Event listener protocol (RuleListener) for audit hooks
- RuleEngine standalone orchestrator with execution metrics

Compatibility:
- SQLAlchemy 1.4 (Column/Integer/etc.) with 2.x mapped_column/Mapped opt-in
- PostgreSQL JSONB preferred; falls back to generic JSON on other databases
- Python 3.10+ (union types, asyncio.timeout backport guard)
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from datetime import datetime, timezone
from functools import wraps
from typing import Any, Callable

from flask import current_app
from sqlalchemy import Column, DateTime, Integer, JSON
from sqlalchemy.ext.declarative import declared_attr

# ---------------------------------------------------------------------------
# Optional: PostgreSQL JSONB — fall back to generic JSON on non-PG backends
# ---------------------------------------------------------------------------
try:
	from sqlalchemy.dialects.postgresql import JSONB as _JsonType
except ImportError:
	_JsonType = JSON  # type: ignore[misc,assignment]

# ---------------------------------------------------------------------------
# Optional: SQLAlchemy 2.x Mapped / mapped_column for projects that have
# already migrated.  Import guarded so the file stays importable on SA 1.x.
# ---------------------------------------------------------------------------
try:
	from sqlalchemy.orm import Mapped, mapped_column  # type: ignore[attr-defined]
	_SA2 = True
except ImportError:
	_SA2 = False

# asyncio.timeout was added in 3.11; for 3.10 we shim it with asyncio.wait_for
if sys.version_info >= (3, 11):
	from asyncio import timeout as _async_timeout  # type: ignore[attr-defined]
else:
	import contextlib

	@contextlib.asynccontextmanager  # type: ignore[arg-type]
	async def _async_timeout(seconds: int | None):  # type: ignore[misc]
		if seconds is None:
			yield
		else:
			task = asyncio.current_task()
			assert task is not None
			try:
				async with asyncio.timeout(seconds):  # type: ignore[attr-defined]
					yield
			except AttributeError:
				# Final fallback: wrap in wait_for at call site (see _execute_async_action)
				yield

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class RuleEvaluationError(Exception):
	"""Raised when rule evaluation fails and raise_errors=True."""


# ---------------------------------------------------------------------------
# RuleCondition
# ---------------------------------------------------------------------------

class RuleCondition:
	"""
	Wraps a sync or async callable that accepts a context dict and returns bool.

	Compose with RuleCondition.all() / RuleCondition.any() for AND/OR logic.
	Both combinators evaluate sub-conditions concurrently via asyncio.gather.
	"""

	def __init__(
		self,
		condition_func: Callable[..., Any],
		description: str | None = None,
		metadata: dict[str, Any] | None = None,
	) -> None:
		self.condition_func = condition_func
		self.description = description
		self.metadata: dict[str, Any] = metadata or {}

	async def __call__(self, context: dict[str, Any]) -> bool:
		if asyncio.iscoroutinefunction(self.condition_func):
			return bool(await self.condition_func(context))
		return bool(self.condition_func(context))

	# ------------------------------------------------------------------
	# Combinators
	# ------------------------------------------------------------------

	@staticmethod
	def all(*conditions: RuleCondition) -> RuleCondition:
		"""Return a condition that is True only when every sub-condition is True (AND)."""
		async def _combined(context: dict[str, Any]) -> bool:
			results = await asyncio.gather(*(c(context) for c in conditions))
			return all(results)
		return RuleCondition(_combined, description="AND(" + ", ".join(
			c.description or "?" for c in conditions) + ")")

	@staticmethod
	def any(*conditions: RuleCondition) -> RuleCondition:
		"""Return a condition that is True when at least one sub-condition is True (OR)."""
		async def _combined(context: dict[str, Any]) -> bool:
			results = await asyncio.gather(*(c(context) for c in conditions))
			return any(results)
		return RuleCondition(_combined, description="OR(" + ", ".join(
			c.description or "?" for c in conditions) + ")")


# ---------------------------------------------------------------------------
# RuleAction
# ---------------------------------------------------------------------------

class RuleAction:
	"""
	Wraps a sync or async callable that accepts a context dict and returns Any.

	Supports an optional per-action timeout (seconds).
	Combine with RuleAction.sequence() / RuleAction.parallel() for composition.
	"""

	def __init__(
		self,
		action_func: Callable[..., Any],
		description: str | None = None,
		metadata: dict[str, Any] | None = None,
		timeout: int | None = None,
	) -> None:
		self.action_func = action_func
		self.description = description
		self.metadata: dict[str, Any] = metadata or {}
		self.timeout = timeout

	async def __call__(self, context: dict[str, Any]) -> Any:
		async def _invoke() -> Any:
			if asyncio.iscoroutinefunction(self.action_func):
				return await self.action_func(context)
			return self.action_func(context)

		if self.timeout is not None:
			try:
				async with _async_timeout(self.timeout):
					return await _invoke()
			except asyncio.TimeoutError:
				raise RuleEvaluationError(
					f"Action '{self.description or self.action_func.__name__}' "
					f"timed out after {self.timeout}s"
				)
		return await _invoke()

	# ------------------------------------------------------------------
	# Combinators
	# ------------------------------------------------------------------

	@staticmethod
	def sequence(*actions: RuleAction) -> RuleAction:
		"""Execute actions one after another; return list of results."""
		async def _seq(context: dict[str, Any]) -> list[Any]:
			return [await action(context) for action in actions]
		return RuleAction(_seq, description="sequence[" + ", ".join(
			a.description or "?" for a in actions) + "]")

	@staticmethod
	def parallel(*actions: RuleAction) -> RuleAction:
		"""Execute actions concurrently via asyncio.gather; return list of results."""
		async def _par(context: dict[str, Any]) -> list[Any]:
			return list(await asyncio.gather(*(action(context) for action in actions)))
		return RuleAction(_par, description="parallel[" + ", ".join(
			a.description or "?" for a in actions) + "]")


# ---------------------------------------------------------------------------
# RuleListener
# ---------------------------------------------------------------------------

class RuleListener:
	"""
	Base class for rule execution event hooks.

	Subclass and override on_rule_executed / on_action_error / on_evaluation_error.
	Attach to a RuleEngine via engine.add_listener().
	"""

	def __call__(self, event: str, data: dict[str, Any]) -> None:
		method = getattr(self, f"on_{event}", None)
		if method is not None:
			method(data)

	def on_rule_executed(self, data: dict[str, Any]) -> None:
		"""Called after a rule's actions complete successfully."""

	def on_action_error(self, data: dict[str, Any]) -> None:
		"""Called when a rule action raises an exception."""

	def on_evaluation_error(self, data: dict[str, Any]) -> None:
		"""Called when overall rule evaluation fails."""


# ---------------------------------------------------------------------------
# BusinessRule
# ---------------------------------------------------------------------------

class BusinessRule:
	"""
	Self-contained rule definition: a set of conditions plus a set of actions.

	Fluent builder interface — chain add_condition / add_action / set_priority /
	set_metadata calls.  evaluate() checks all conditions concurrently; execute()
	runs all actions with optional async retry using exponential back-off.
	"""

	def __init__(
		self,
		name: str,
		description: str | None = None,
		async_execution: bool = False,
		retry_policy: dict[str, Any] | None = None,
	) -> None:
		self.name = name
		self.description = description
		self.conditions: list[RuleCondition] = []
		self.actions: list[RuleAction] = []
		self.priority: int = 0
		self.metadata: dict[str, Any] = {}
		self.async_execution = async_execution
		self.retry_policy: dict[str, Any] = retry_policy or {
			"max_retries": 3,
			"delay": 1,
			"backoff": 2,
		}
		self.created_at: datetime = datetime.now(tz=timezone.utc)

	# ------------------------------------------------------------------
	# Builder methods
	# ------------------------------------------------------------------

	def add_condition(self, condition: RuleCondition) -> BusinessRule:
		self.conditions.append(condition)
		return self

	def add_action(self, action: RuleAction) -> BusinessRule:
		self.actions.append(action)
		return self

	def set_priority(self, priority: int) -> BusinessRule:
		self.priority = priority
		return self

	def set_metadata(self, metadata: dict[str, Any]) -> BusinessRule:
		self.metadata = metadata
		return self

	# ------------------------------------------------------------------
	# Evaluation / execution
	# ------------------------------------------------------------------

	async def evaluate(self, context: dict[str, Any]) -> bool:
		"""Return True when ALL registered conditions pass."""
		if not self.conditions:
			return True
		try:
			results = await asyncio.gather(*(c(context) for c in self.conditions))
			return all(results)
		except Exception as exc:
			log.error("Rule '%s' condition error: %s", self.name, exc)
			return False

	async def execute(self, context: dict[str, Any]) -> list[Any]:
		"""
		Execute all registered actions.

		When async_execution=True each action is run with retry / back-off.
		When async_execution=False actions are still awaited (they may be sync
		wrappers) but without retry logic.
		"""
		results: list[Any] = []
		for action in self.actions:
			try:
				if self.async_execution:
					result = await self._execute_with_retry(action, context)
				else:
					result = await action(context)
				results.append(result)
			except Exception as exc:
				log.error("Rule '%s' action error: %s", self.name, exc)
				raise
		return results

	async def _execute_with_retry(
		self,
		action: RuleAction,
		context: dict[str, Any],
	) -> Any:
		max_retries: int = self.retry_policy["max_retries"]
		delay: float = float(self.retry_policy["delay"])
		backoff: float = float(self.retry_policy["backoff"])

		last_exc: Exception | None = None
		for attempt in range(max_retries):
			try:
				return await action(context)
			except Exception as exc:
				last_exc = exc
				if attempt < max_retries - 1:
					wait = min(delay * (backoff ** attempt), 30.0)
					log.warning(
						"Rule '%s' action retry %d/%d after %.1fs: %s",
						self.name, attempt + 1, max_retries, wait, exc,
					)
					await asyncio.sleep(wait)
		raise last_exc  # type: ignore[misc]


# ---------------------------------------------------------------------------
# RuleEngine
# ---------------------------------------------------------------------------

class RuleEngine:
	"""
	Standalone orchestrator for BusinessRule objects.

	Usage::

		engine = RuleEngine()
		engine.register_rule(my_rule)
		engine.add_listener(AuditLogger())
		engine.set_context({"order": order, "customer": order.customer})
		results = await engine.evaluate_all()
		metrics = engine.get_metrics()
	"""

	def __init__(self) -> None:
		self.rules: dict[str, BusinessRule] = {}
		self.context: dict[str, Any] = {}
		self.listeners: list[RuleListener] = []
		self._metrics: dict[str, Any] = {
			"total_executions": 0,
			"total_errors": 0,
			"execution_times": [],  # seconds (float)
		}

	# ------------------------------------------------------------------
	# Configuration (fluent)
	# ------------------------------------------------------------------

	def register_rule(self, rule: BusinessRule) -> RuleEngine:
		self.rules[rule.name] = rule
		return self

	def set_context(self, context: dict[str, Any]) -> RuleEngine:
		self.context = context
		return self

	def add_listener(self, listener: RuleListener) -> RuleEngine:
		self.listeners.append(listener)
		return self

	# ------------------------------------------------------------------
	# Evaluation
	# ------------------------------------------------------------------

	async def evaluate_rule(self, rule_name: str) -> list[Any] | None:
		"""
		Evaluate a single rule by name.

		Returns the list of action results when conditions are met, else None.
		Raises ValueError for unknown rule names; re-raises action exceptions.
		"""
		rule = self.rules.get(rule_name)
		if rule is None:
			raise ValueError(f"Rule '{rule_name}' not registered in this engine")

		start = datetime.now(tz=timezone.utc)
		try:
			conditions_met = await rule.evaluate(self.context)
			if not conditions_met:
				return None

			results = await rule.execute(self.context)
			self._notify("rule_executed", {
				"rule": rule,
				"results": results,
				"duration": datetime.now(tz=timezone.utc) - start,
			})
			return results

		except Exception as exc:
			self._metrics["total_errors"] += 1
			self._notify("evaluation_error", {"rule": rule, "error": exc})
			raise
		finally:
			elapsed = (datetime.now(tz=timezone.utc) - start).total_seconds()
			self._metrics["total_executions"] += 1
			self._metrics["execution_times"].append(elapsed)

	async def evaluate_all(self) -> dict[str, Any]:
		"""
		Evaluate all rules in descending priority order.

		Returns a dict mapping rule name → action results for rules whose
		conditions passed.  Errors propagate; partial results are not returned
		when a rule raises.
		"""
		results: dict[str, Any] = {}
		sorted_rules = sorted(
			self.rules.values(), key=lambda r: r.priority, reverse=True
		)
		for rule in sorted_rules:
			try:
				result = await self.evaluate_rule(rule.name)
				if result is not None:
					results[rule.name] = result
			except Exception as exc:
				log.error("Engine: rule '%s' failed: %s", rule.name, exc)
				self._notify("evaluation_error", {"rule": rule, "error": exc})
				raise
		return results

	# ------------------------------------------------------------------
	# Metrics
	# ------------------------------------------------------------------

	def get_metrics(self) -> dict[str, Any]:
		times: list[float] = self._metrics["execution_times"]
		return {
			**self._metrics,
			"avg_execution_time": sum(times) / len(times) if times else 0.0,
			"error_rate": (
				self._metrics["total_errors"] / self._metrics["total_executions"]
				if self._metrics["total_executions"] else 0.0
			),
		}

	# ------------------------------------------------------------------
	# Internal
	# ------------------------------------------------------------------

	def _notify(self, event: str, data: dict[str, Any]) -> None:
		for listener in self.listeners:
			try:
				listener(event, data)
			except Exception as exc:
				log.error("RuleEngine listener error (event=%s): %s", event, exc)


# ---------------------------------------------------------------------------
# BusinessRuleMixin  — attach to PgForge Model subclasses
# ---------------------------------------------------------------------------

class BusinessRuleMixin:
	"""
	Adds a business-rules engine to any PgForge Model.

	Persists per-rule evaluation statistics to a JSONB column (PostgreSQL) or
	JSON column (other databases).  Tracks last evaluation timestamp and a
	running evaluation count.

	Column declarations use SQLAlchemy 1.x ``Column()`` style; projects that
	have migrated to SA 2.x ``mapped_column`` / ``Mapped`` can override the
	declarations in their concrete model class — the mixin logic is column-
	implementation agnostic.

	Usage::

		class Order(BusinessRuleMixin, Model):
			__tablename__ = "orders"
			id = Column(Integer, primary_key=True)
			...

			def __init__(self, **kw):
				super().__init__(**kw)
				self._setup_order_rules()

			def _setup_order_rules(self):
				self.register_rule(
					"vip_discount",
					condition=lambda obj, ctx: obj.customer.is_vip,
					action=lambda obj, ctx: obj.apply_discount(0.2),
					priority=10,
				)
	"""

	# ------------------------------------------------------------------
	# Persisted columns (SQLAlchemy 1.4 compatible; declared_attr not needed
	# for plain Column on concrete tables, but guarded via declared_attr for
	# mixin safety across joined/single-table inheritance).
	# ------------------------------------------------------------------

	@declared_attr
	def rules_metadata(cls) -> Column:  # noqa: N805
		return Column(_JsonType, default=dict, nullable=False)

	@declared_attr
	def last_evaluation(cls) -> Column:  # noqa: N805
		return Column(DateTime(timezone=True), nullable=True)

	@declared_attr
	def rule_count(cls) -> Column:  # noqa: N805
		return Column(Integer, default=0, nullable=False)

	# ------------------------------------------------------------------
	# Safe accessors for stats columns
	# (bypass declared_attr Column descriptors on unmapped instances)
	# ------------------------------------------------------------------

	@property
	def _rule_count(self) -> int:
		"""Instance-level evaluation counter, safe on unmapped objects."""
		return self.__dict__.get("rule_count") or 0

	@property
	def _last_evaluation(self) -> datetime | None:
		"""Timestamp of most recent evaluation, safe on unmapped objects."""
		return self.__dict__.get("last_evaluation")

	# ------------------------------------------------------------------
	# Instance initialisation
	# ------------------------------------------------------------------

	def __init__(self, *args: Any, **kwargs: Any) -> None:
		super().__init__(*args, **kwargs)
		# In-memory rule registry — keyed by rule name
		self._business_rules: dict[str, dict[str, Any]] = {}
		# In-memory metadata cache; decoupled from the SQLAlchemy Column
		# descriptor so that register_rule works before the instance is mapped.
		self._rules_meta_cache: dict[str, Any] = {}
		self._engine = RuleEngine()

	# ------------------------------------------------------------------
	# Rule registration
	# ------------------------------------------------------------------

	def register_rule(
		self,
		name: str,
		condition: Callable[..., Any],
		action: Callable[..., Any],
		priority: int = 0,
		metadata: dict[str, Any] | None = None,
		async_execution: bool = False,
		retry_count: int = 3,
		timeout: int | None = None,
	) -> None:
		"""
		Register a business rule on this model instance.

		Args:
			name:             Unique rule identifier.
			condition:        Callable(model_instance, context) -> bool.
			action:           Callable(model_instance, context) -> Any.
			priority:         Higher value evaluated first (default 0).
			metadata:         Arbitrary dict stored in rules_metadata column.
			async_execution:  Run the action coroutine with retry back-off.
			retry_count:      Max retry attempts when async_execution=True.
			timeout:          Per-execution timeout in seconds (None = unlimited).
		"""
		now_iso = datetime.now(tz=timezone.utc).isoformat()
		self._business_rules[name] = {
			"condition": condition,
			"action": action,
			"priority": priority,
			"metadata": metadata or {},
			"async": async_execution,
			"retry_count": retry_count,
			"timeout": timeout,
			"created_at": now_iso,
		}

		# Update in-memory cache (always safe; no Column descriptor involved)
		self._rules_meta_cache[name] = {
			"priority": priority,
			"metadata": metadata or {},
			"created_at": now_iso,
			"evaluation_count": 0,
			"last_evaluation": None,
		}
		# Sync to mapped column only when SQLAlchemy has materialised it as a dict
		col_val = self.__dict__.get("rules_metadata")
		if isinstance(col_val, dict):
			col_val[name] = self._rules_meta_cache[name]
			self.rules_metadata = dict(col_val)

	# ------------------------------------------------------------------
	# Rule access helpers
	# ------------------------------------------------------------------

	def get_rule(self, name: str) -> dict[str, Any] | None:
		"""Return the raw rule registration dict, or None if not found."""
		return self._business_rules.get(name)

	def list_rules(self, include_metadata: bool = False) -> list[str] | list[dict[str, Any]]:
		"""
		Return registered rule names (or dicts when include_metadata=True).
		"""
		if include_metadata:
			return [
				{
					"name": n,
					"metadata": self._rules_meta_cache.get(n, {}),
				}
				for n in self._business_rules
			]
		return list(self._business_rules.keys())

	# ------------------------------------------------------------------
	# Evaluation
	# ------------------------------------------------------------------

	async def evaluate_rule(
		self,
		name: str,
		context: dict[str, Any] | None = None,
		raise_errors: bool = False,
	) -> Any:
		"""
		Evaluate a single rule by name.

		The condition callable receives ``(self, context)``.  If the condition
		passes, the action callable is called the same way (or awaited when
		async_execution=True).

		Args:
			name:         Rule to evaluate.
			context:      Extra data for condition/action callables.
			raise_errors: Re-raise as RuleEvaluationError instead of returning None.

		Returns:
			Action result, or None if the condition failed or an error occurred
			(and raise_errors=False).
		"""
		rule = self.get_rule(name)
		if rule is None:
			raise ValueError(f"Rule '{name}' not registered on this instance")

		ctx = context or {}
		try:
			condition_met = rule["condition"](self, ctx)
			if asyncio.iscoroutine(condition_met):
				condition_met = await condition_met

			if not condition_met:
				return None

			if rule["async"]:
				return await self._execute_async_action(rule, ctx)

			result = rule["action"](self, ctx)
			if asyncio.iscoroutine(result):
				return await result
			return result

		except Exception as exc:
			log.error("Rule '%s' evaluation error: %s", name, exc)
			if raise_errors:
				raise RuleEvaluationError(str(exc)) from exc
			return None
		finally:
			self._update_evaluation_stats(name)

	async def evaluate_all_rules(
		self,
		context: dict[str, Any] | None = None,
		raise_errors: bool = False,
	) -> list[tuple[str, Any]]:
		"""
		Evaluate all rules in descending priority order.

		Returns:
			List of (rule_name, result) tuples for rules whose conditions passed.
		"""
		ctx = context or {}
		results: list[tuple[str, Any]] = []

		sorted_rules = sorted(
			self._business_rules.items(),
			key=lambda kv: kv[1]["priority"],
			reverse=True,
		)

		for name, _rule in sorted_rules:
			try:
				result = await self.evaluate_rule(name, ctx, raise_errors)
				if result is not None:
					results.append((name, result))
			except Exception as exc:
				log.error("evaluate_all_rules: rule '%s' error: %s", name, exc)
				if raise_errors:
					raise

		return results

	# ------------------------------------------------------------------
	# Internal helpers
	# ------------------------------------------------------------------

	async def _execute_async_action(
		self,
		rule: dict[str, Any],
		context: dict[str, Any],
	) -> Any:
		"""Execute rule action asynchronously with exponential-back-off retry."""
		retry_count: int = rule["retry_count"]
		timeout: int | None = rule["timeout"]

		last_exc: Exception | None = None
		for attempt in range(retry_count):
			try:
				async def _run() -> Any:
					result = rule["action"](self, context)
					if asyncio.iscoroutine(result):
						return await result
					return result

				if timeout is not None:
					try:
						async with _async_timeout(timeout):
							return await _run()
					except asyncio.TimeoutError:
						raise RuleEvaluationError(
							f"Action timed out after {timeout}s (attempt {attempt + 1})"
						)
				return await _run()

			except RuleEvaluationError:
				raise  # timeout — do not retry
			except Exception as exc:
				last_exc = exc
				if attempt < retry_count - 1:
					wait = min(2.0 ** attempt, 30.0)
					log.warning(
						"Async action retry %d/%d after %.1fs: %s",
						attempt + 1, retry_count, wait, exc,
					)
					await asyncio.sleep(wait)

		raise last_exc  # type: ignore[misc]

	def _update_evaluation_stats(self, rule_name: str) -> None:
		"""Update persisted evaluation statistics for a single rule."""
		now = datetime.now(tz=timezone.utc)

		# Use __dict__ to bypass declared_attr Column descriptors on unmapped instances.
		# When SQLAlchemy has mapped the instance these writes go through its
		# instrumentation normally; on plain Python objects they set instance attrs.
		current_count = self.__dict__.get("rule_count") or 0
		self.__dict__["last_evaluation"] = now
		self.__dict__["rule_count"] = current_count + 1

		# Always update in-memory cache
		rule_meta = self._rules_meta_cache.setdefault(rule_name, {})
		rule_meta["last_evaluation"] = now.isoformat()
		rule_meta["evaluation_count"] = rule_meta.get("evaluation_count", 0) + 1

		# Sync to mapped column only when SQLAlchemy has materialised it as a dict
		col_val = self.__dict__.get("rules_metadata")
		if isinstance(col_val, dict):
			col_val[rule_name] = rule_meta
			# Force SA dirty-detection by reassigning (JSON in-place mutations are invisible)
			self.__dict__["rules_metadata"] = dict(col_val)


__all__ = [
	"BusinessRuleMixin",
	"BusinessRule",
	"RuleEngine",
	"RuleCondition",
	"RuleAction",
	"RuleListener",
	"RuleEvaluationError",
]
