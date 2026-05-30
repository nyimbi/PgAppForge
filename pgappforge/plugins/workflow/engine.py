"""
pgappforge/plugins/workflow/engine.py

WorkflowEngine — the core BPM state machine.

Responsibilities
----------------
- Start / advance / reject / complete process instances
- Record every transition as a ProcessEvent (full audit trail)
- Escalate overdue instances (call from APScheduler or Celery beat)
- Provide queue and timeline queries
- Log form-time telemetry events

All mutations are performed within the caller's SQLAlchemy session; the engine
does NOT commit — that remains the caller's responsibility, which keeps it
composable with larger transactions.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, and_, func

from .models import ProcessDefinition, ProcessEvent, ProcessInstance, ProcessStep

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = lambda: datetime.now(timezone.utc)  # noqa: E731


def _record_event(
	session,
	*,
	instance_id: int,
	event_type: str,
	actor_id: int | None = None,
	from_step_id: int | None = None,
	to_step_id: int | None = None,
	comment: str = "",
	data: dict[str, Any] | None = None,
	duration_seconds: int | None = None,
) -> ProcessEvent:
	evt = ProcessEvent(
		instance_id=instance_id,
		event_type=event_type,
		actor_id=actor_id,
		from_step_id=from_step_id,
		to_step_id=to_step_id,
		comment=comment or "",
		data=data or {},
		occurred_at=_NOW(),
		duration_seconds=duration_seconds,
	)
	session.add(evt)
	return evt


# ---------------------------------------------------------------------------
# WorkflowEngine
# ---------------------------------------------------------------------------


class WorkflowEngine:
	"""
	Stateless engine — all state lives in the database.

	Instantiate once per request / task with the current SQLAlchemy session.
	"""

	def __init__(self, session) -> None:
		self.session = session

	# ------------------------------------------------------------------
	# Start
	# ------------------------------------------------------------------

	def start_process(
		self,
		definition_id: int,
		model_name: str,
		record_id: int,
		started_by_id: int | None = None,
	) -> ProcessInstance:
		"""
		Create a new ProcessInstance for *record_id* and advance it to the
		first step.  Raises ValueError if the definition is inactive or has
		no steps.
		"""
		defn = self.session.get(ProcessDefinition, definition_id)
		if defn is None:
			raise ValueError(f"ProcessDefinition #{definition_id} not found")
		if not defn.is_active:
			raise ValueError(f"ProcessDefinition {defn.name!r} is not active")
		if not defn.steps:
			raise ValueError(f"ProcessDefinition {defn.name!r} has no steps")

		first_step: ProcessStep = defn.steps[0]
		now = _NOW()

		inst = ProcessInstance(
			definition_id=definition_id,
			model_name=model_name,
			record_id=record_id,
			current_step_id=first_step.id,
			status="active",
			started_at=now,
			started_by_id=started_by_id,
			step_entered_at=now,
		)
		self.session.add(inst)
		self.session.flush()  # populate inst.id

		_record_event(
			self.session,
			instance_id=inst.id,
			event_type="start",
			actor_id=started_by_id,
			to_step_id=first_step.id,
			comment=f"Started process '{defn.name}' at step '{first_step.name}'",
		)

		log.info(
			"WorkflowEngine: started ProcessInstance #%d for %s#%d (def=%s, step='%s')",
			inst.id, model_name, record_id, defn.name, first_step.name,
		)
		return inst

	# ------------------------------------------------------------------
	# Advance
	# ------------------------------------------------------------------

	def advance(
		self,
		instance_id: int,
		actor_id: int | None = None,
		comment: str = "",
	) -> ProcessEvent:
		"""
		Move *instance* to the next step.  If the current step is the last one,
		delegates to :meth:`complete`.  Returns the transition ProcessEvent.
		"""
		inst = self._get_active_instance(instance_id)
		defn = inst.definition
		steps: list[ProcessStep] = defn.steps  # already ordered by order_num

		current_idx = next(
			(i for i, s in enumerate(steps) if s.id == inst.current_step_id), None
		)
		if current_idx is None:
			raise ValueError(
				f"ProcessInstance #{instance_id}: current_step_id={inst.current_step_id!r} "
				"not found in definition steps"
			)

		from_step = steps[current_idx]

		if current_idx + 1 >= len(steps) or from_step.is_final:
			# Last step — complete the process
			return self._complete_with_event(inst, actor_id=actor_id, comment=comment)

		to_step = steps[current_idx + 1]
		now = _NOW()

		evt = _record_event(
			self.session,
			instance_id=inst.id,
			event_type="transition",
			actor_id=actor_id,
			from_step_id=from_step.id,
			to_step_id=to_step.id,
			comment=comment,
			data={
				"from_step_name": from_step.name,
				"to_step_name": to_step.name,
				"hours_at_step": inst.hours_at_current_step,
			},
		)

		inst.current_step_id = to_step.id
		inst.step_entered_at = now

		log.info(
			"WorkflowEngine: advanced instance #%d '%s'→'%s' (actor=%s)",
			inst.id, from_step.name, to_step.name, actor_id,
		)
		return evt

	# ------------------------------------------------------------------
	# Reject
	# ------------------------------------------------------------------

	def reject(
		self,
		instance_id: int,
		actor_id: int | None = None,
		comment: str = "",
	) -> ProcessEvent:
		"""
		Send the instance back to the previous step.  If already at step 0,
		reset to step 0 (stays at Draft / first step) and record a rejection event.
		"""
		inst = self._get_active_instance(instance_id)
		steps: list[ProcessStep] = inst.definition.steps

		current_idx = next(
			(i for i, s in enumerate(steps) if s.id == inst.current_step_id), None
		)
		from_step = steps[current_idx] if current_idx is not None else None
		to_step = steps[max(0, (current_idx or 0) - 1)]
		now = _NOW()

		evt = _record_event(
			self.session,
			instance_id=inst.id,
			event_type="reject",
			actor_id=actor_id,
			from_step_id=from_step.id if from_step else None,
			to_step_id=to_step.id,
			comment=comment,
			data={
				"from_step_name": from_step.name if from_step else None,
				"to_step_name": to_step.name,
				"hours_at_step": inst.hours_at_current_step,
			},
		)

		inst.current_step_id = to_step.id
		inst.step_entered_at = now

		log.info(
			"WorkflowEngine: rejected instance #%d to step '%s' (actor=%s)",
			inst.id, to_step.name, actor_id,
		)
		return evt

	# ------------------------------------------------------------------
	# Complete
	# ------------------------------------------------------------------

	def complete(
		self,
		instance_id: int,
		actor_id: int | None = None,
	) -> ProcessInstance:
		"""Mark the process instance as completed."""
		inst = self._get_active_instance(instance_id)
		return self._complete_with_event(inst, actor_id=actor_id, comment="Manually completed")

	# ------------------------------------------------------------------
	# Cancel
	# ------------------------------------------------------------------

	def cancel(
		self,
		instance_id: int,
		actor_id: int | None = None,
		comment: str = "",
	) -> ProcessInstance:
		"""Cancel an active process instance."""
		inst = self._get_active_instance(instance_id)
		inst.status = "cancelled"
		inst.completed_at = _NOW()

		_record_event(
			self.session,
			instance_id=inst.id,
			event_type="cancel",
			actor_id=actor_id,
			from_step_id=inst.current_step_id,
			comment=comment or "Cancelled",
		)
		log.info("WorkflowEngine: cancelled instance #%d (actor=%s)", inst.id, actor_id)
		return inst

	# ------------------------------------------------------------------
	# Escalation
	# ------------------------------------------------------------------

	def escalate_overdue(self) -> list[ProcessEvent]:
		"""
		Scan all active instances.  For any whose elapsed time at the current
		step exceeds that step's timeout_hours, emit an 'escalation' event and
		optionally log the escalate_to_role.

		Call this from a scheduled task (APScheduler / Celery beat).
		Returns the list of escalation events created.
		"""
		stmt = (
			select(ProcessInstance)
			.where(ProcessInstance.status == "active")
			.where(ProcessInstance.current_step_id.isnot(None))
			.where(ProcessInstance.step_entered_at.isnot(None))
		)
		instances: list[ProcessInstance] = list(self.session.execute(stmt).scalars())

		events: list[ProcessEvent] = []
		now = _NOW()

		for inst in instances:
			step = inst.current_step
			if step is None:
				continue
			if inst.step_entered_at is None:
				continue

			entered = inst.step_entered_at
			if entered.tzinfo is None:
				entered = entered.replace(tzinfo=timezone.utc)
			elapsed_hours = (now - entered).total_seconds() / 3600.0

			if elapsed_hours <= step.timeout_hours:
				continue

			# Check: was an escalation already recorded for this step entry?
			already_escalated = self.session.execute(
				select(ProcessEvent)
				.where(ProcessEvent.instance_id == inst.id)
				.where(ProcessEvent.event_type == "escalation")
				.where(ProcessEvent.from_step_id == step.id)
				.where(ProcessEvent.occurred_at >= inst.step_entered_at)
				.limit(1)
			).scalar_one_or_none()

			if already_escalated is not None:
				continue

			evt = _record_event(
				self.session,
				instance_id=inst.id,
				event_type="escalation",
				from_step_id=step.id,
				comment=(
					f"Step '{step.name}' exceeded timeout of {step.timeout_hours}h "
					f"(elapsed {elapsed_hours:.1f}h). "
					f"Escalating to role: {step.escalate_to_role or 'unset'}."
				),
				data={
					"elapsed_hours": elapsed_hours,
					"timeout_hours": step.timeout_hours,
					"assigned_role": step.assigned_role,
					"escalate_to_role": step.escalate_to_role,
				},
			)
			events.append(evt)
			log.warning(
				"WorkflowEngine: escalation for instance #%d step '%s' "
				"(%.1f h / %d h limit)",
				inst.id, step.name, elapsed_hours, step.timeout_hours,
			)

		return events

	# ------------------------------------------------------------------
	# Queries
	# ------------------------------------------------------------------

	def get_instance_for_record(
		self,
		model_name: str,
		record_id: int,
	) -> ProcessInstance | None:
		"""Return the most recent active instance for a record, or None."""
		return self.session.execute(
			select(ProcessInstance)
			.where(ProcessInstance.model_name == model_name)
			.where(ProcessInstance.record_id == record_id)
			.where(ProcessInstance.status == "active")
			.order_by(ProcessInstance.started_at.desc())
			.limit(1)
		).scalar_one_or_none()

	def get_queue(self, role_name: str) -> list[ProcessInstance]:
		"""
		Return all active instances whose current step is assigned to *role_name*.
		"""
		return list(
			self.session.execute(
				select(ProcessInstance)
				.join(ProcessStep, ProcessInstance.current_step_id == ProcessStep.id)
				.where(ProcessInstance.status == "active")
				.where(ProcessStep.assigned_role == role_name)
				.order_by(ProcessInstance.step_entered_at.asc())
			).scalars()
		)

	def form_time_event(
		self,
		instance_id: int,
		actor_id: int | None,
		seconds: int,
	) -> ProcessEvent:
		"""Log how long the user spent on the form (JS telemetry)."""
		inst = self.session.get(ProcessInstance, instance_id)
		if inst is None:
			raise ValueError(f"ProcessInstance #{instance_id} not found")

		evt = _record_event(
			self.session,
			instance_id=instance_id,
			event_type="form_time",
			actor_id=actor_id,
			from_step_id=inst.current_step_id,
			duration_seconds=seconds,
			data={"seconds": seconds},
		)
		log.debug(
			"WorkflowEngine: form_time %ds for instance #%d actor=%s",
			seconds, instance_id, actor_id,
		)
		return evt

	def timeline(self, instance_id: int) -> list[dict[str, Any]]:
		"""
		Return the full ordered timeline of events with inter-event durations.

		Each dict:
		  {
		    "id": int,
		    "event_type": str,
		    "occurred_at": str (ISO-8601),
		    "actor_id": int | None,
		    "from_step": str | None,
		    "to_step": str | None,
		    "comment": str,
		    "duration_seconds": int | None,   # form_time events
		    "step_duration_seconds": int | None,  # time since previous event
		    "data": dict,
		  }
		"""
		events: list[ProcessEvent] = list(
			self.session.execute(
				select(ProcessEvent)
				.where(ProcessEvent.instance_id == instance_id)
				.order_by(ProcessEvent.occurred_at.asc())
			).scalars()
		)

		result: list[dict[str, Any]] = []
		prev_at: datetime | None = None

		for evt in events:
			at = evt.occurred_at
			if at is not None and at.tzinfo is None:
				at = at.replace(tzinfo=timezone.utc)

			step_duration: int | None = None
			if prev_at is not None and at is not None:
				step_duration = int((at - prev_at).total_seconds())

			result.append({
				"id": evt.id,
				"event_type": evt.event_type,
				"occurred_at": at.isoformat() if at else None,
				"actor_id": evt.actor_id,
				"from_step": evt.from_step.name if evt.from_step else None,
				"to_step": evt.to_step.name if evt.to_step else None,
				"comment": evt.comment or "",
				"duration_seconds": evt.duration_seconds,
				"step_duration_seconds": step_duration,
				"data": evt.data or {},
			})
			if at is not None:
				prev_at = at

		return result

	def dashboard_stats(self) -> dict[str, Any]:
		"""
		Aggregate counts for the dashboard.

		Returns:
		  active_count, overdue_count, completed_today, total_definitions
		"""
		now = _NOW()
		today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

		active_count: int = self.session.execute(
			select(func.count()).select_from(ProcessInstance)
			.where(ProcessInstance.status == "active")
		).scalar_one()

		completed_today: int = self.session.execute(
			select(func.count()).select_from(ProcessInstance)
			.where(ProcessInstance.status == "completed")
			.where(ProcessInstance.completed_at >= today_start)
		).scalar_one()

		total_definitions: int = self.session.execute(
			select(func.count()).select_from(ProcessDefinition)
			.where(ProcessDefinition.is_active.is_(True))
		).scalar_one()

		# Overdue: active instances where step_entered_at is beyond timeout
		# We load all active and filter in Python to avoid a complex SQL join
		active_instances: list[ProcessInstance] = list(
			self.session.execute(
				select(ProcessInstance)
				.where(ProcessInstance.status == "active")
			).scalars()
		)
		overdue_count = sum(1 for i in active_instances if i.is_overdue)

		return {
			"active_count": active_count,
			"overdue_count": overdue_count,
			"completed_today": completed_today,
			"total_definitions": total_definitions,
		}

	# ------------------------------------------------------------------
	# Internals
	# ------------------------------------------------------------------

	def _get_active_instance(self, instance_id: int) -> ProcessInstance:
		inst = self.session.get(ProcessInstance, instance_id)
		if inst is None:
			raise ValueError(f"ProcessInstance #{instance_id} not found")
		if inst.status != "active":
			raise ValueError(
				f"ProcessInstance #{instance_id} is not active (status={inst.status!r})"
			)
		return inst

	def _complete_with_event(
		self,
		inst: ProcessInstance,
		actor_id: int | None,
		comment: str,
	) -> ProcessEvent:
		now = _NOW()
		from_step_id = inst.current_step_id
		from_step_name = inst.current_step.name if inst.current_step else None

		inst.status = "completed"
		inst.completed_at = now

		evt = _record_event(
			self.session,
			instance_id=inst.id,
			event_type="complete",
			actor_id=actor_id,
			from_step_id=from_step_id,
			comment=comment or "Process completed",
			data={
				"final_step": from_step_name,
				"total_hours": inst.total_elapsed_hours,
			},
		)
		log.info(
			"WorkflowEngine: completed instance #%d (actor=%s, %.1f h total)",
			inst.id, actor_id, inst.total_elapsed_hours,
		)
		return evt


__all__ = ["WorkflowEngine"]
