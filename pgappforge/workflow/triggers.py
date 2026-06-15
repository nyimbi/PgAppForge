"""
pgappforge/workflow/triggers.py

WorkflowTriggerRegistry — maps event patterns to workflow definitions that
auto-start when matching events fire.

Usage in workflow YAML::

    name: process_invoice_payment
    trigger:
      on_event: 'finance.ar.invoice.approved'
      filter_field: amount_cents
      filter_op: '>='
      filter_value: 100000
    steps: [...]

Registration::

    registry = get_trigger_registry()
    registry.register_from_definition(workflow_def)
    # wire to EventRouter:
    router.subscribe('finance.ar.*', registry.handle_event)
"""
from __future__ import annotations

import fnmatch
import logging
import operator
from typing import Any

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Filter operator resolution
# ---------------------------------------------------------------------------

_OPS: dict[str, Any] = {
	"==": operator.eq,
	"!=": operator.ne,
	">":  operator.gt,
	">=": operator.ge,
	"<":  operator.lt,
	"<=": operator.le,
	"in": lambda a, b: a in b,
	"not_in": lambda a, b: a not in b,
	"contains": lambda a, b: b in a,
}


def _op_fn(op_str: str):
	fn = _OPS.get(op_str)
	if fn is None:
		raise ValueError(
			f"Unknown filter_op {op_str!r}. Valid ops: {sorted(_OPS)}"
		)
	return fn


# ---------------------------------------------------------------------------
# Core registry
# ---------------------------------------------------------------------------

class WorkflowTriggerRegistry:
	"""Maps event patterns to workflow definitions that auto-start when events fire.

	Each registration stores:
	- event_pattern: glob-style pattern (e.g. ``'finance.ar.*'``)
	- workflow_name:  name of the workflow to start
	- filter_conditions: list of dicts with keys field, op, value
	- input_mapping:  dict mapping workflow input keys to event payload keys
	"""

	def __init__(self) -> None:
		# List of trigger dicts:
		# {event_pattern, workflow_name, filter_conditions, input_mapping}
		self._triggers: list[dict[str, Any]] = []

	# ------------------------------------------------------------------
	# Registration
	# ------------------------------------------------------------------

	def register(
		self,
		event_pattern: str | None = None,
		workflow_name: str = "",
		filter_conditions: list[dict[str, Any]] | None = None,
		input_mapping: dict[str, str] | None = None,
		# Aliases for ergonomic test/caller use
		pattern: str | None = None,
		filter_condition: dict[str, Any] | None = None,
	) -> None:
		"""Register a workflow to start when a matching event fires.

		Args:
			event_pattern:    Glob pattern against event_type strings. ``pattern`` is an alias.
			workflow_name:    Name of a loaded workflow definition.
			filter_conditions: Optional list of filter dicts (``field``, ``op``, ``value``).
			                   ``filter_condition`` (singular dict) is also accepted.
			input_mapping:    Optional mapping from workflow input key to payload key.
		"""
		resolved_pattern = event_pattern or pattern or ""
		resolved_filters: list[dict[str, Any]] = list(filter_conditions or [])
		if filter_condition and not resolved_filters:
			resolved_filters = [{"field": k, "op": "==", "value": v} for k, v in filter_condition.items()]
		self._triggers.append({
			"event_pattern": resolved_pattern,
			"pattern": resolved_pattern,         # keep both keys for compatibility
			"workflow_name": workflow_name,
			"filter_conditions": resolved_filters,
			"input_mapping": input_mapping or {},
		})
		log.info(
			"TriggerRegistry: registered %r → workflow %r",
			event_pattern, workflow_name,
		)

	def register_from_definition(self, workflow_def_dict: dict[str, Any]) -> bool:
		"""Parse a workflow definition dict and register any trigger block it contains.

		Expects the dict shape produced by the YAML DSL::

		    name: process_invoice_payment
		    trigger:
		      on_event: 'finance.ar.invoice.approved'
		      filter_field: amount_cents
		      filter_op: '>='
		      filter_value: 100000
		      # optional:
		      input_mapping:
		        invoice_id: id
		        amount: amount_cents

		Returns True if a trigger was registered, False if the definition has no
		trigger block or no ``on_event`` key.
		"""
		trigger = workflow_def_dict.get("trigger") or {}
		event_pattern = trigger.get("on_event", "")
		if not event_pattern:
			return False

		workflow_name = workflow_def_dict.get("name", "")
		if not workflow_name:
			raise ValueError("workflow definition is missing 'name'")

		# Build filter_conditions from flat shorthand keys
		filter_conditions: list[dict[str, Any]] = []
		filter_field = trigger.get("filter_field")
		filter_op = trigger.get("filter_op")
		filter_value = trigger.get("filter_value")
		if filter_field and filter_op:
			filter_conditions.append({
				"field": filter_field,
				"op": filter_op,
				"value": filter_value,
			})

		# Support a list of filters under 'filters:' key as well
		for fc in (trigger.get("filters") or []):
			filter_conditions.append(fc)

		input_mapping: dict[str, str] = trigger.get("input_mapping") or {}

		self.register(
			event_pattern=event_pattern,
			workflow_name=workflow_name,
			filter_conditions=filter_conditions,
			input_mapping=input_mapping,
		)
		return True

	# ------------------------------------------------------------------
	# Event handling
	# ------------------------------------------------------------------

	def handle_event(
		self,
		event_type: str,
		payload: dict[str, Any],
		tenant_id: str,
		engine=None,
		session=None,
	) -> list[dict[str, Any]]:
		"""Check filters and start all workflows whose trigger matches.

		Returns:
			List of dicts with keys ``workflow_name`` and ``instance_id`` for each started workflow.
		"""
		if engine is None:
			try:
				from pgappforge.workflow import yaml_engine as _engine
				engine = _engine
			except Exception:
				log.warning("handle_event: no engine available — event %r ignored", event_type)
				return []

		started: list[dict[str, Any]] = []

		for trigger in self._triggers:
			if not fnmatch.fnmatch(event_type, trigger["event_pattern"]):
				continue

			if not self._check_filters(trigger["filter_conditions"], payload):
				log.debug(
					"TriggerRegistry: filters failed for %r → %r",
					event_type, trigger["workflow_name"],
				)
				continue

			input_data = self._resolve_input_mapping(
				trigger["input_mapping"], payload
			)

			instance_id: str | None = None
			try:
				instance = engine.start(
					trigger["workflow_name"],
					input_data,
					tenant_id,
					session=session,
				)
				instance_id = instance.id
				log.info(
					"TriggerRegistry: started %r (instance=%s) for event %r",
					trigger["workflow_name"], instance.id[:8], event_type,
				)
			except Exception as exc:
				log.warning(
					"TriggerRegistry: failed to start %r for event %r: %s",
					trigger["workflow_name"], event_type, exc,
				)
			started.append({"workflow_name": trigger["workflow_name"], "instance_id": instance_id})

		return started

	# ------------------------------------------------------------------
	# Introspection
	# ------------------------------------------------------------------

	def list_triggers(self) -> list[dict[str, Any]]:
		"""Return a copy of all registered trigger records.

		Each record has keys: event_pattern, workflow_name, filter_conditions,
		input_mapping.
		"""
		return [dict(t) for t in self._triggers]

	def clear(self) -> None:
		"""Remove all registered triggers (useful in tests)."""
		self._triggers.clear()

	# ------------------------------------------------------------------
	# Internal helpers
	# ------------------------------------------------------------------

	def _check_filters(
		self,
		filter_conditions: list[dict[str, Any]],
		payload: dict[str, Any],
	) -> bool:
		"""Return True only if ALL filter conditions pass."""
		for fc in filter_conditions:
			field = fc.get("field", "")
			op_str = fc.get("op", "==")
			expected = fc.get("value")

			actual = payload.get(field)
			if actual is None:
				log.debug("Filter: field %r not in payload — condition fails", field)
				return False

			try:
				fn = _op_fn(op_str)
				# coerce types when comparing numeric strings vs ints
				try:
					if isinstance(expected, (int, float)) and not isinstance(actual, (int, float)):
						actual = type(expected)(actual)
					elif isinstance(actual, (int, float)) and not isinstance(expected, (int, float)):
						expected = type(actual)(expected)
				except (TypeError, ValueError):
					pass
				if not fn(actual, expected):
					return False
			except Exception as exc:
				log.debug("Filter eval error field=%r op=%r: %s", field, op_str, exc)
				return False

		return True

	def _resolve_input_mapping(
		self,
		input_mapping: dict[str, str],
		payload: dict[str, Any],
	) -> dict[str, Any]:
		"""Map payload fields into workflow input keys.

		If input_mapping is empty, return the full payload as-is.
		"""
		if not input_mapping:
			return dict(payload)
		return {
			wf_key: payload.get(payload_key)
			for wf_key, payload_key in input_mapping.items()
		}


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_registry: WorkflowTriggerRegistry | None = None


def get_trigger_registry() -> WorkflowTriggerRegistry:
	"""Return the process-wide WorkflowTriggerRegistry singleton."""
	global _registry
	if _registry is None:
		_registry = WorkflowTriggerRegistry()
	return _registry


__all__ = [
	"WorkflowTriggerRegistry",
	"get_trigger_registry",
]
