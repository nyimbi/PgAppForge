"""
pgappforge/plugins/workflow/mixin.py

WorkflowMixin — attach to any SQLAlchemy Model to make it workflow-aware.

Usage
-----
    class Invoice(Model, WorkflowMixin):
        WORKFLOW_DEFINITION = 'invoice_approval'   # auto-starts this workflow
        __tablename__ = 'invoices'
        ...

    # Later:
    invoice.start_workflow(user_id=3)
    invoice.advance_workflow(user_id=3, comment="Looks good")
    print(invoice.workflow_status)   # → 'Finance Approval'
    print(invoice.is_workflow_overdue)  # → False

The mixin is deliberately dependency-light: it resolves the engine and session
lazily so it can be mixed in before pgappforge is fully initialised.
"""
from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


def _get_engine(session=None):
	"""Return a WorkflowEngine bound to *session* (or the app default session)."""
	from pgappforge.plugins.workflow.engine import WorkflowEngine

	if session is None:
		# Try Flask-SQLAlchemy db.session
		try:
			from pgappforge import db  # type: ignore[attr-defined]
			session = db.session
		except Exception as exc:
			raise RuntimeError(
				"WorkflowMixin: could not obtain a SQLAlchemy session. "
				"Either pass session= explicitly or ensure Flask-SQLAlchemy is configured."
			) from exc

	return WorkflowEngine(session)


class WorkflowMixin:
	"""
	Mixin that gives any SQLAlchemy Model awareness of the BPM workflow system.

	Class-level attributes (set on your subclass):
	  WORKFLOW_DEFINITION : str | None
	      Name of the ProcessDefinition to auto-start when start_workflow()
	      is called without an explicit definition_name.  If None, the caller
	      must always supply definition_name.

	Instance-level attributes populated by the mixin (all lazy / cached):
	  _wf_instance_cache : ProcessInstance | None | sentinel
	      Internal cache; invalidated by any mutating method.
	"""

	#: Override on your model class, e.g. WORKFLOW_DEFINITION = 'invoice_approval'
	WORKFLOW_DEFINITION: str | None = None

	# sentinel distinguishes "not yet looked up" from "looked up and found None"
	_WF_NOT_LOADED = object()

	def __init_subclass__(cls, **kwargs: Any) -> None:
		super().__init_subclass__(**kwargs)
		# Inject per-instance cache slot
		cls._wf_instance_cache = WorkflowMixin._WF_NOT_LOADED

	# ------------------------------------------------------------------
	# Properties
	# ------------------------------------------------------------------

	@property
	def workflow_instance(self):
		"""
		Active ProcessInstance for this record, or None.
		Result is cached for the lifetime of this Python object.
		"""
		if self._wf_instance_cache is WorkflowMixin._WF_NOT_LOADED:
			self._wf_instance_cache = _get_engine().get_instance_for_record(
				type(self).__name__, self.id  # type: ignore[attr-defined]
			)
		return self._wf_instance_cache

	@property
	def workflow_status(self) -> str:
		"""
		Human-readable step name, or a lifecycle status string.
		Returns 'No Workflow' when no active instance exists.
		"""
		inst = self.workflow_instance
		if inst is None:
			return "No Workflow"
		if inst.status == "completed":
			return "Completed"
		if inst.status == "cancelled":
			return "Cancelled"
		if inst.current_step:
			return inst.current_step.name
		return inst.status.title()

	@property
	def workflow_step_name(self) -> str | None:
		"""Current step name, or None."""
		inst = self.workflow_instance
		if inst and inst.current_step:
			return inst.current_step.name
		return None

	@property
	def workflow_assigned_role(self) -> str | None:
		"""FAB role name responsible for the current step, or None."""
		inst = self.workflow_instance
		if inst and inst.current_step:
			return inst.current_step.assigned_role
		return None

	@property
	def is_workflow_overdue(self) -> bool:
		"""True when the active instance has exceeded its step timeout."""
		inst = self.workflow_instance
		return bool(inst and inst.is_overdue)

	@property
	def workflow_hours_at_step(self) -> float:
		"""Hours elapsed at the current step (0.0 if no active instance)."""
		inst = self.workflow_instance
		return inst.hours_at_current_step if inst else 0.0

	# ------------------------------------------------------------------
	# Mutating methods — always invalidate cache
	# ------------------------------------------------------------------

	def start_workflow(
		self,
		user_id: int | None = None,
		definition_name: str | None = None,
		session=None,
	):
		"""
		Start a new workflow instance for this record.

		Args:
			user_id:         ID of the user initiating the process.
			definition_name: Override WORKFLOW_DEFINITION for one-off starts.
			session:         SQLAlchemy session (uses app default if omitted).

		Returns:
			ProcessInstance
		"""
		name = definition_name or self.WORKFLOW_DEFINITION
		if not name:
			raise ValueError(
				f"{type(self).__name__}.WORKFLOW_DEFINITION is not set and "
				"definition_name was not supplied to start_workflow()."
			)

		engine = _get_engine(session)

		# Resolve definition by name
		from pgappforge.plugins.workflow.models import ProcessDefinition
		from sqlalchemy import select
		defn = engine.session.execute(
			select(ProcessDefinition).where(ProcessDefinition.name == name)
		).scalar_one_or_none()
		if defn is None:
			raise ValueError(f"ProcessDefinition {name!r} not found")

		record_id = getattr(self, "id", None)
		if record_id is None:
			raise ValueError(
				f"{type(self).__name__} has no 'id' — flush/commit the record first."
			)

		inst = engine.start_process(
			definition_id=defn.id,
			model_name=type(self).__name__,
			record_id=record_id,
			started_by_id=user_id,
		)
		self._wf_instance_cache = inst
		return inst

	def advance_workflow(
		self,
		user_id: int | None = None,
		comment: str = "",
		session=None,
	):
		"""
		Move the active workflow instance to the next step.

		Returns:
			ProcessEvent (the transition event)
		"""
		inst = self._require_active_instance(session)
		engine = _get_engine(session)
		evt = engine.advance(inst.id, actor_id=user_id, comment=comment)
		self._wf_instance_cache = WorkflowMixin._WF_NOT_LOADED  # invalidate
		return evt

	def reject_workflow(
		self,
		user_id: int | None = None,
		comment: str = "",
		session=None,
	):
		"""
		Send the active workflow instance back to the previous step.

		Returns:
			ProcessEvent (the rejection event)
		"""
		inst = self._require_active_instance(session)
		engine = _get_engine(session)
		evt = engine.reject(inst.id, actor_id=user_id, comment=comment)
		self._wf_instance_cache = WorkflowMixin._WF_NOT_LOADED
		return evt

	def cancel_workflow(
		self,
		user_id: int | None = None,
		comment: str = "",
		session=None,
	):
		"""Cancel the active workflow instance."""
		inst = self._require_active_instance(session)
		engine = _get_engine(session)
		result = engine.cancel(inst.id, actor_id=user_id, comment=comment)
		self._wf_instance_cache = WorkflowMixin._WF_NOT_LOADED
		return result

	def workflow_timeline(self, session=None) -> list[dict]:
		"""Return the full timeline of events for the active instance."""
		inst = self.workflow_instance
		if inst is None:
			return []
		return _get_engine(session).timeline(inst.id)

	# ------------------------------------------------------------------
	# Internal
	# ------------------------------------------------------------------

	def _require_active_instance(self, session=None):
		engine = _get_engine(session)
		inst = engine.get_instance_for_record(type(self).__name__, self.id)  # type: ignore[attr-defined]
		if inst is None:
			raise ValueError(
				f"{type(self).__name__}#{self.id} has no active workflow instance. "  # type: ignore[attr-defined]
				"Call start_workflow() first."
			)
		return inst


__all__ = ["WorkflowMixin"]
