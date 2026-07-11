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
- Conditional transitions via rules engine (XOR_SPLIT / AND_SPLIT gateways)
- Parallel execution tokens (AND_SPLIT / AND_JOIN)
- Process definition versioning
- Timer-driven auto-advance / auto-reject / escalation
- Dynamic role assignment via role_expression
- User delegation — tasks assigned to a delegator are also visible to delegate
- Bulk advance / reject

All mutations are performed within the caller's SQLAlchemy session; the engine
does NOT commit — that remains the caller's responsibility, which keeps it
composable with larger transactions.
"""
from __future__ import annotations

import ast
import logging
import re as _re
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import select, and_, func

from .models import (
	ProcessDefinition,
	ProcessEvent,
	ProcessInstance,
	ProcessStep,
	ProcessToken,
	ProcessTransition,
	UserDelegation,
)

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
		record_ctx: dict[str, Any] | None = None,
	) -> ProcessInstance:
		"""
		Create a new ProcessInstance for *record_id* and advance it to the
		first step.  Raises ValueError if the definition is inactive or has
		no steps.

		*record_ctx* is an optional plain-dict of record fields used for
		dynamic role resolution (GAP 5).
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

		# GAP 5: resolve dynamic role for the first step
		resolved_role = self._resolve_role(first_step, record_ctx or {}, self.session)

		inst = ProcessInstance(
			definition_id=definition_id,
			model_name=model_name,
			record_id=record_id,
			current_step_id=first_step.id,
			status="active",
			started_at=now,
			started_by_id=started_by_id,
			step_entered_at=now,
			# GAP 3: snapshot version at start time
			definition_version=defn.version,
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
			data={"resolved_role": resolved_role},
		)

		log.info(
			"WorkflowEngine: started ProcessInstance #%d for %s#%d (def=%s v%d, step='%s', role='%s')",
			inst.id, model_name, record_id, defn.name, defn.version, first_step.name, resolved_role,
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
		record_ctx: dict[str, Any] | None = None,
	) -> ProcessEvent:
		"""
		Move *instance* to the next step.

		Logic (GAP 1 + GAP 2):
		  1. Load transitions from bpm_process_transition for the current step.
		  2. If transitions exist, evaluate in priority order using the rules
		     engine condition evaluator.
		     - XOR_SPLIT: pick exactly the first matching transition (or default).
		     - AND_SPLIT:  fan out into parallel tokens via split_tokens().
		  3. If no transitions exist: fall back to order_num+1 linear advance.
		  4. If current step is final / last step: delegate to _complete_with_event.

		*record_ctx* is a plain dict of record fields for condition evaluation.
		Returns the transition ProcessEvent (or the completion event).
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
		ctx = record_ctx or {}

		# ---- GAP 2: AND_SPLIT gateway ----
		if from_step.step_type == "AND_SPLIT":
			return self.split_tokens(instance_id, actor_id=actor_id, comment=comment)

		# ---- GAP 1: look up explicit transitions ----
		transitions = self._load_transitions(from_step.id, defn.id)

		if transitions:
			if from_step.step_type == "XOR_SPLIT":
				# Pick exactly one matching transition
				chosen = self._pick_xor_transition(transitions, ctx)
				if chosen is None:
					raise ValueError(
						f"ProcessInstance #{instance_id}: XOR_SPLIT at step "
						f"'{from_step.name}' — no condition matched and no default transition."
					)
				to_step = self.session.get(ProcessStep, chosen.to_step_id)
				if to_step is None:
					raise ValueError(
						f"ProcessTransition #{chosen.id} references missing step #{chosen.to_step_id}"
					)
			else:
				# Non-split step with explicit transitions — treat as XOR for single-successor
				chosen = self._pick_xor_transition(transitions, ctx)
				if chosen is None:
					# Fall through to linear order
					to_step = None
				else:
					to_step = self.session.get(ProcessStep, chosen.to_step_id)
		else:
			chosen = None
			to_step = None

		# ---- Fall back to linear order_num+1 ----
		if to_step is None:
			if current_idx + 1 >= len(steps) or from_step.is_final:
				return self._complete_with_event(inst, actor_id=actor_id, comment=comment)
			to_step = steps[current_idx + 1]

		# Check if to_step is a final step
		if to_step.is_final:
			inst.current_step_id = to_step.id
			inst.step_entered_at = _NOW()
			return self._complete_with_event(inst, actor_id=actor_id, comment=comment)

		now = _NOW()
		# GAP 5: resolve dynamic role for the next step
		resolved_role = self._resolve_role(to_step, ctx, self.session)

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
				"via_transition": chosen.id if chosen else None,
				"resolved_role": resolved_role,
			},
		)

		inst.current_step_id = to_step.id
		inst.step_entered_at = now

		log.info(
			"WorkflowEngine: advanced instance #%d '%s'→'%s' (actor=%s, role='%s')",
			inst.id, from_step.name, to_step.name, actor_id, resolved_role,
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

		# GAP 2: if at an AND_JOIN step, delegate join logic
		if inst.current_step and inst.current_step.step_type == "AND_JOIN":
			return self.join_token(
				instance_id=instance_id,
				step_id=inst.current_step_id,
				actor_id=actor_id,
				session=self.session,
			)

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
	# GAP 2: Parallel gateway — AND_SPLIT / AND_JOIN
	# ------------------------------------------------------------------

	def split_tokens(
		self,
		instance_id: int,
		actor_id: int | None = None,
		comment: str = "",
	) -> ProcessEvent:
		"""
		Fan out an AND_SPLIT step into one ProcessToken per outgoing transition.

		Sets instance.current_step_id = None (waiting for join).
		Emits a 'split' ProcessEvent.
		"""
		inst = self._get_active_instance(instance_id)
		from_step = inst.current_step
		if from_step is None:
			raise ValueError(f"ProcessInstance #{instance_id}: no current step")

		transitions = self._load_transitions(from_step.id, inst.definition_id)
		if not transitions:
			raise ValueError(
				f"ProcessInstance #{instance_id}: AND_SPLIT step '{from_step.name}' "
				"has no outgoing transitions — cannot split."
			)

		now = _NOW()
		for trans in transitions:
			token = ProcessToken(
				instance_id=instance_id,
				step_id=trans.to_step_id,
				status="active",
				created_at=now,
			)
			self.session.add(token)

		# Instance waits at None — all branches must converge
		inst.current_step_id = None
		inst.step_entered_at = now

		evt = _record_event(
			self.session,
			instance_id=inst.id,
			event_type="split",
			actor_id=actor_id,
			from_step_id=from_step.id,
			comment=comment or f"AND_SPLIT: forked into {len(transitions)} parallel branch(es)",
			data={
				"from_step_name": from_step.name,
				"branch_step_ids": [t.to_step_id for t in transitions],
				"branch_count": len(transitions),
			},
		)

		log.info(
			"WorkflowEngine: split instance #%d at '%s' into %d branches (actor=%s)",
			inst.id, from_step.name, len(transitions), actor_id,
		)
		return evt

	def join_token(
		self,
		instance_id: int,
		step_id: int | None,
		actor_id: int | None = None,
		session=None,
	) -> ProcessInstance:
		"""
		Mark the token for *step_id* as completed.

		If all tokens for this instance are now completed, advance the instance
		to the AND_JOIN step's next step (linear order_num+1 logic).

		Returns the ProcessInstance (possibly now completed / advanced).
		"""
		session = session or self.session
		inst = self._get_active_instance(instance_id)

		# Mark this branch's token as done
		if step_id is not None:
			token: ProcessToken | None = session.execute(
				select(ProcessToken)
				.where(ProcessToken.instance_id == instance_id)
				.where(ProcessToken.step_id == step_id)
				.where(ProcessToken.status == "active")
				.limit(1)
			).scalar_one_or_none()

			if token is not None:
				token.status = "completed"
				token.completed_at = _NOW()

		# Count remaining active tokens
		active_count: int = session.execute(
			select(func.count())
			.select_from(ProcessToken)
			.where(ProcessToken.instance_id == instance_id)
			.where(ProcessToken.status == "active")
		).scalar_one()

		if active_count > 0:
			log.info(
				"WorkflowEngine: join_token instance #%d — %d branch(es) still active",
				instance_id, active_count,
			)
			return inst

		# All branches complete — find the AND_JOIN step and advance past it
		join_step: ProcessStep | None = None
		if step_id is not None:
			join_step = session.execute(
				select(ProcessStep)
				.where(ProcessStep.definition_id == inst.definition_id)
				.where(ProcessStep.step_type == "AND_JOIN")
				.order_by(ProcessStep.order_num.asc())
				.limit(1)
			).scalar_one_or_none()

		steps: list[ProcessStep] = inst.definition.steps
		join_idx = next(
			(i for i, s in enumerate(steps) if join_step and s.id == join_step.id), None
		)

		now = _NOW()

		if join_idx is not None and join_idx + 1 < len(steps):
			next_step = steps[join_idx + 1]
			inst.current_step_id = next_step.id
			inst.step_entered_at = now

			_record_event(
				session,
				instance_id=inst.id,
				event_type="join",
				actor_id=actor_id,
				from_step_id=join_step.id if join_step else None,
				to_step_id=next_step.id,
				comment="AND_JOIN: all branches completed — advancing",
				data={"to_step_name": next_step.name},
			)

			log.info(
				"WorkflowEngine: join complete for instance #%d — advancing to '%s'",
				inst.id, next_step.name,
			)
		else:
			# AND_JOIN is the final step
			_record_event(
				session,
				instance_id=inst.id,
				event_type="join",
				actor_id=actor_id,
				from_step_id=join_step.id if join_step else None,
				comment="AND_JOIN: all branches completed — process complete",
			)
			self._complete_with_event(inst, actor_id=actor_id, comment="AND_JOIN: all branches completed")

		return inst

	# ------------------------------------------------------------------
	# GAP 3: Process versioning
	# ------------------------------------------------------------------

	def create_new_version(
		self,
		definition_id: int,
		session=None,
	) -> ProcessDefinition:
		"""
		Clone *definition_id* as a new version.

		- Old definition: is_latest = False
		- New definition: version = old.version + 1, is_latest = True,
		  parent_definition_id = old.id
		- All ProcessStep rows are cloned for the new definition.

		Returns the new ProcessDefinition (not yet committed).
		"""
		session = session or self.session
		old_defn = session.get(ProcessDefinition, definition_id)
		if old_defn is None:
			raise ValueError(f"ProcessDefinition #{definition_id} not found")

		old_defn.is_latest = False

		new_defn = ProcessDefinition(
			name=old_defn.name,
			description=old_defn.description,
			is_active=old_defn.is_active,
			config=dict(old_defn.config or {}),
			created_by_id=old_defn.created_by_id,
			version=old_defn.version + 1,
			is_latest=True,
			parent_definition_id=old_defn.id,
		)
		session.add(new_defn)
		session.flush()  # populate new_defn.id

		# Clone all steps
		for step in old_defn.steps:
			new_step = ProcessStep(
				definition_id=new_defn.id,
				name=step.name,
				order_num=step.order_num,
				assigned_role=step.assigned_role,
				timeout_hours=step.timeout_hours,
				escalate_to_role=step.escalate_to_role,
				actions=dict(step.actions or {}),
				step_type=step.step_type,
				auto_advance_hours=step.auto_advance_hours,
				timer_action=step.timer_action,
				role_expression=step.role_expression,
			)
			session.add(new_step)

		session.flush()

		log.info(
			"WorkflowEngine: created version %d of definition '%s' (new id=#%d)",
			new_defn.version, new_defn.name, new_defn.id,
		)
		return new_defn

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
	# GAP 4: Timer events
	# ------------------------------------------------------------------

	def process_timers(self, session=None) -> dict[str, Any]:
		"""
		Called by a scheduler (APScheduler / Celery beat) to fire timer-driven
		step transitions.

		For each active instance whose current step has ``auto_advance_hours``
		set and whose elapsed time at that step has exceeded the threshold:

		  - timer_action='ADVANCE'  → call advance()
		  - timer_action='REJECT'   → call reject()
		  - timer_action='ESCALATE' → emit an escalation event, log escalate_to_role

		Returns counts: {triggered, advanced, rejected, escalated, errors}
		"""
		session = session or self.session

		stmt = (
			select(ProcessInstance)
			.where(ProcessInstance.status == "active")
			.where(ProcessInstance.current_step_id.isnot(None))
			.where(ProcessInstance.step_entered_at.isnot(None))
		)
		instances: list[ProcessInstance] = list(session.execute(stmt).scalars())

		now = _NOW()
		triggered = advanced = rejected = escalated = errors = 0

		for inst in instances:
			step = inst.current_step
			if step is None or step.auto_advance_hours is None:
				continue

			entered = inst.step_entered_at
			if entered is None:
				continue
			if entered.tzinfo is None:
				entered = entered.replace(tzinfo=timezone.utc)

			elapsed_hours = (now - entered).total_seconds() / 3600.0
			if elapsed_hours < step.auto_advance_hours:
				continue

			# Idempotency: skip if a timer event already fired for this step entry
			already_fired = session.execute(
				select(ProcessEvent)
				.where(ProcessEvent.instance_id == inst.id)
				.where(ProcessEvent.event_type == "timer")
				.where(ProcessEvent.from_step_id == step.id)
				.where(ProcessEvent.occurred_at >= inst.step_entered_at)
				.limit(1)
			).scalar_one_or_none()
			if already_fired is not None:
				continue

			triggered += 1
			action = (step.timer_action or "ADVANCE").upper()

			try:
				if action == "ADVANCE":
					self.advance(inst.id, actor_id=None, comment="Timer auto-advance")
					advanced += 1
					log.info(
						"WorkflowEngine: timer ADVANCE instance #%d step '%s' (%.1fh elapsed)",
						inst.id, step.name, elapsed_hours,
					)
				elif action == "REJECT":
					self.reject(inst.id, actor_id=None, comment="Timer auto-reject")
					rejected += 1
					log.info(
						"WorkflowEngine: timer REJECT instance #%d step '%s' (%.1fh elapsed)",
						inst.id, step.name, elapsed_hours,
					)
				elif action == "ESCALATE":
					_record_event(
						session,
						instance_id=inst.id,
						event_type="timer",
						from_step_id=step.id,
						comment=(
							f"Timer ESCALATE: step '{step.name}' exceeded "
							f"{step.auto_advance_hours}h (elapsed {elapsed_hours:.1f}h). "
							f"Escalating to role: {step.escalate_to_role or 'unset'}."
						),
						data={
							"elapsed_hours": elapsed_hours,
							"auto_advance_hours": step.auto_advance_hours,
							"escalate_to_role": step.escalate_to_role,
							"timer_action": action,
						},
					)
					escalated += 1
					log.warning(
						"WorkflowEngine: timer ESCALATE instance #%d step '%s' "
						"(%.1fh / %dh) → role '%s'",
						inst.id, step.name, elapsed_hours,
						step.auto_advance_hours, step.escalate_to_role,
					)
				else:
					log.warning(
						"WorkflowEngine: unknown timer_action %r for step '%s'",
						action, step.name,
					)
					errors += 1
			except Exception as exc:
				log.exception(
					"WorkflowEngine: timer error on instance #%d step '%s': %s",
					inst.id, step.name, exc,
				)
				errors += 1

		return {
			"triggered": triggered,
			"advanced": advanced,
			"rejected": rejected,
			"escalated": escalated,
			"errors": errors,
		}

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

	def get_queue(self, role_name: str, user_id: int | None = None) -> list[ProcessInstance]:
		"""
		Return all active instances whose current step is assigned to *role_name*.

		GAP 6 — Delegation: if *user_id* is supplied, also include instances
		where the user is an active delegate for a user who holds *role_name*
		(i.e. the delegator's queue is visible to the delegate).
		"""
		# Primary: instances directly assigned to the role
		direct = list(
			self.session.execute(
				select(ProcessInstance)
				.join(ProcessStep, ProcessInstance.current_step_id == ProcessStep.id)
				.where(ProcessInstance.status == "active")
				.where(ProcessStep.assigned_role == role_name)
				.order_by(ProcessInstance.step_entered_at.asc())
			).scalars()
		)

		if user_id is None:
			return direct

		# GAP 6: find instances delegated to user_id
		today = date.today()
		delegations: list[UserDelegation] = list(
			self.session.execute(
				select(UserDelegation)
				.where(UserDelegation.delegate_id == user_id)
				.where(UserDelegation.is_active.is_(True))
				.where(UserDelegation.start_date <= today)
				.where(
					(UserDelegation.end_date.is_(None)) |
					(UserDelegation.end_date >= today)
				)
			).scalars()
		)

		# Filter delegations to those that cover role_name
		relevant_delegator_ids: list[int] = []
		for deleg in delegations:
			roles_inc: list[str] = deleg.roles_included or []
			if not roles_inc or role_name in roles_inc:
				if deleg.delegator_id is not None:
					relevant_delegator_ids.append(deleg.delegator_id)

		if not relevant_delegator_ids:
			return direct

		# Find instances assigned to delegators via their role — need user→role join
		# We use the ab_user_role association table directly via text SQL join
		from sqlalchemy import text
		delegated_instance_ids_row = self.session.execute(
			select(ProcessInstance.id)
			.join(ProcessStep, ProcessInstance.current_step_id == ProcessStep.id)
			.where(ProcessInstance.status == "active")
			.where(ProcessStep.assigned_role == role_name)
			.where(ProcessInstance.started_by_id.in_(relevant_delegator_ids))
		).scalars().all()

		direct_ids = {i.id for i in direct}
		extra: list[ProcessInstance] = []
		for inst_id in delegated_instance_ids_row:
			if inst_id not in direct_ids:
				inst = self.session.get(ProcessInstance, inst_id)
				if inst:
					extra.append(inst)

		return direct + extra

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
	# GAP 7: Bulk actions
	# ------------------------------------------------------------------

	def bulk_advance(
		self,
		instance_ids: list[int],
		actor_id: int,
		comment: str = "",
		session=None,
		record_ctx: dict[str, Any] | None = None,
	) -> dict[str, Any]:
		"""
		Advance multiple instances in a single call.

		Returns:
		  {
		    "succeeded": [instance_id, ...],
		    "failed": {instance_id: error_message, ...}
		  }
		"""
		session = session or self.session
		succeeded: list[int] = []
		failed: dict[int, str] = {}

		for inst_id in instance_ids:
			try:
				self.advance(inst_id, actor_id=actor_id, comment=comment, record_ctx=record_ctx)
				succeeded.append(inst_id)
			except Exception as exc:
				log.warning(
					"WorkflowEngine: bulk_advance failed for instance #%d: %s",
					inst_id, exc,
				)
				failed[inst_id] = str(exc)

		return {"succeeded": succeeded, "failed": failed}

	def bulk_reject(
		self,
		instance_ids: list[int],
		actor_id: int,
		comment: str = "",
		session=None,
	) -> dict[str, Any]:
		"""
		Reject multiple instances in a single call.

		Returns:
		  {
		    "succeeded": [instance_id, ...],
		    "failed": {instance_id: error_message, ...}
		  }
		"""
		session = session or self.session
		succeeded: list[int] = []
		failed: dict[int, str] = {}

		for inst_id in instance_ids:
			try:
				self.reject(inst_id, actor_id=actor_id, comment=comment)
				succeeded.append(inst_id)
			except Exception as exc:
				log.warning(
					"WorkflowEngine: bulk_reject failed for instance #%d: %s",
					inst_id, exc,
				)
				failed[inst_id] = str(exc)

		return {"succeeded": succeeded, "failed": failed}

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

	# ------------------------------------------------------------------
	# GAP 1: Conditional transitions — helpers
	# ------------------------------------------------------------------

	def _load_transitions(
		self,
		from_step_id: int,
		definition_id: int,
	) -> list[ProcessTransition]:
		"""Return all transitions from *from_step_id*, ordered by priority asc."""
		return list(
			self.session.execute(
				select(ProcessTransition)
				.where(ProcessTransition.from_step_id == from_step_id)
				.where(ProcessTransition.definition_id == definition_id)
				.order_by(ProcessTransition.priority.asc())
			).scalars()
		)

	def _pick_xor_transition(
		self,
		transitions: list[ProcessTransition],
		ctx: dict[str, Any],
	) -> ProcessTransition | None:
		"""
		Evaluate transitions in priority order.

		Returns the first transition whose conditions evaluate to True.
		Falls back to a transition with is_default=True if no condition matches.
		Returns None if nothing matches.
		"""
		from pgappforge.plugins.rules.engine import _resolve_value

		default_trans: ProcessTransition | None = None

		for trans in transitions:
			if trans.is_default:
				default_trans = trans
				continue  # evaluate non-default first; fall back later

			conditions = trans.conditions_json or []
			if self._evaluate_transition_conditions(conditions, ctx):
				return trans

		return default_trans

	def _evaluate_transition_conditions(
		self,
		conditions: list[dict[str, Any]],
		ctx: dict[str, Any],
	) -> bool:
		"""
		Delegate to the rules engine's _evaluate_conditions logic.

		Inline reimplementation to avoid importing the private function;
		semantics are identical to RulesEngine._evaluate_conditions.
		"""
		if not conditions:
			return True  # no conditions = unconditional match

		from pgappforge.plugins.rules.engine import _resolve_value, _OPS

		result = True
		or_group: list[bool] = []

		for cond in conditions:
			field  = cond.get("field", "")
			op     = cond.get("op", "=")
			value  = _resolve_value(cond.get("value"), ctx)
			logic  = (cond.get("logic") or "AND").upper()
			actual = ctx.get(field)
			fn     = _OPS.get(op)
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

	# ------------------------------------------------------------------
	# GAP 5: Dynamic role resolution
	# ------------------------------------------------------------------

	def _resolve_role(
		self,
		step: ProcessStep,
		record_ctx: dict[str, Any],
		session,
	) -> str | None:
		"""
		Resolve the assigned role for a step.

		If ``step.role_expression`` is None: return ``step.assigned_role``.

		Otherwise evaluate the expression against *record_ctx*:

		  - ``'$requester_role'``
		      → record_ctx.get('requester_role')

		  - ``'SENIOR_MGR if amount_cents > 50000000 else LINE_MGR'``
		      → eval() with a restricted namespace containing record_ctx values

		Falls back to ``step.assigned_role`` on any error.
		"""
		role_expression = getattr(step, "role_expression", None)
		if not role_expression:
			return getattr(step, "assigned_role", None)

		expr = role_expression.strip()

		# Simple $field reference
		if expr.startswith("$"):
			field = expr[1:]
			resolved = record_ctx.get(field)
			if resolved is not None:
				return str(resolved)
			log.warning(
				"WorkflowEngine: role_expression '%s' → field '%s' not in record_ctx; "
				"falling back to assigned_role '%s'",
				expr, field, step.assigned_role,
			)
			return step.assigned_role

		# Safe AST-based expression — whitelist of node types only
		# Supports: ternary (IfExp), comparisons, string/int constants, name lookups
		_SAFE_NODES = (
			ast.Expression, ast.IfExp, ast.Compare, ast.BoolOp,
			ast.And, ast.Or, ast.Not, ast.UnaryOp,
			ast.Constant, ast.Name, ast.Load,
			ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE,
			ast.In, ast.NotIn,
		)
		try:
			tree = ast.parse(expr, mode="eval")
			for node in ast.walk(tree):
				if not isinstance(node, _SAFE_NODES):
					raise ValueError(f"Disallowed node type {type(node).__name__!r} in role_expression")
			safe_ns: dict[str, Any] = {k: v for k, v in record_ctx.items()}
			result = eval(compile(tree, "<role_expr>", "eval"), {"__builtins__": {}}, safe_ns)  # noqa: S307
			if result is not None:
				return str(result)
		except Exception as exc:
			log.warning(
				"WorkflowEngine: role_expression eval failed for step '%s' expr=%r: %s; "
				"falling back to assigned_role '%s'",
				step.name, expr, exc, step.assigned_role,
			)

		return step.assigned_role

	# ------------------------------------------------------------------
	# GAP 6: Delegation — assignee resolution
	# ------------------------------------------------------------------

	def _resolve_assignees(self, role: str, session=None) -> list[int]:
		"""
		Return the list of user IDs who can act on a step assigned to *role*.

		1. Find all users who hold the given FAB role (via ab_user_role join).
		2. Find active UserDelegation rows where delegator_id is in that user list
		   AND today is within [start_date, end_date]
		   AND (roles_included is empty OR role in roles_included).
		3. Add delegate_id values to the list.
		4. Return the combined, deduplicated list.
		"""
		session = session or self.session
		today = date.today()

		# Import FAB SQLA models inline to avoid circular imports
		from pgappforge.security.sqla.models import Role, User

		# Step 1: users with this role
		role_row: Role | None = session.execute(
			select(Role).where(Role.name == role).limit(1)
		).scalar_one_or_none()

		if role_row is None:
			return []

		# Roles → users via relationship (roles is on User)
		users_with_role: list[User] = list(
			session.execute(
				select(User).where(User.roles.any(Role.name == role))
			).scalars()
		)
		user_ids: set[int] = {u.id for u in users_with_role if u.id is not None}

		if not user_ids:
			return []

		# Step 2: active delegations for these delegators
		delegations: list[UserDelegation] = list(
			session.execute(
				select(UserDelegation)
				.where(UserDelegation.delegator_id.in_(list(user_ids)))
				.where(UserDelegation.is_active.is_(True))
				.where(UserDelegation.start_date <= today)
				.where(
					(UserDelegation.end_date.is_(None)) |
					(UserDelegation.end_date >= today)
				)
			).scalars()
		)

		# Step 3: add delegates whose delegation covers this role
		for deleg in delegations:
			roles_inc: list[str] = deleg.roles_included or []
			if not roles_inc or role in roles_inc:
				if deleg.delegate_id is not None:
					user_ids.add(deleg.delegate_id)

		return sorted(user_ids)


# ---------------------------------------------------------------------------
# BPMActionRegistry — open capability registry for workflow step actions
# ---------------------------------------------------------------------------


class BPMActionRegistry:
	"""Global registry of callable BPM actions.

	Any plugin can register named actions at import time. Workflow step
	on_enter/on_exit lists reference them as:
	  {"type": "call_capability", "capability": "fintech.payments.initiate",
	   "params": {"amount_cents": "$amount_cents", "account": "$debtor_account"}}

	Parameter values support the same $field / {{template}} syntax as the
	rules engine (resolved via _resolve_value before the call).

	Registration (in plugin __init__ or a dedicated bpm_actions.py):
	  from pgappforge.plugins.workflow.engine import BPMActionRegistry

	  @BPMActionRegistry.register("erp.finance.gl.post_journal", "Post GL entry")
	  def _bpm_post_journal(record_ctx, session, lines, description, **kw):
	      from pgappforge.plugins.erp.finance.gl.services import GLService
	      GLService().post_simple_journal(lines, session=session, ...)
	"""

	_registry: dict[str, dict[str, Any]] = {}

	@classmethod
	def register(cls, name: str, description: str = "") -> Any:
		"""Decorator: register a function as a callable BPM capability.

		Raises ValueError if the name is already registered by a different function
		so that silent capability shadowing is caught at import time.
		"""
		def decorator(fn: Any) -> Any:
			existing = cls._registry.get(name)
			if existing is not None:
				existing_fn = existing["fn"]
				if existing_fn.__qualname__ == fn.__qualname__:
					return fn
				raise ValueError(
					f"BPMActionRegistry: capability {name!r} already registered by "
					f"{existing_fn.__module__}.{existing_fn.__qualname__}. "
					f"Cannot override with {fn.__module__}.{fn.__qualname__}."
				)
			cls._registry[name] = {"fn": fn, "name": name, "description": description}
			return fn
		return decorator

	@classmethod
	def call(
		cls,
		capability_name: str,
		record_ctx: dict[str, Any],
		params: dict[str, Any] | None,
		session: Any,
	) -> Any:
		"""Resolve param values then call the registered capability."""
		entry = cls._registry.get(capability_name)
		if entry is None:
			raise ValueError(
				f"BPM: unknown capability {capability_name!r}. "
				f"Registered: {sorted(cls._registry)}"
			)
		try:
			from pgappforge.plugins.rules.engine import _resolve_value
		except ImportError:
			def _resolve_value(v: Any, ctx: Any) -> Any:  # type: ignore[misc]
				return v
		resolved = {
			k: _resolve_value(v, record_ctx) for k, v in (params or {}).items()
		}
		return entry["fn"](record_ctx=record_ctx, session=session, **resolved)

	@classmethod
	def list_capabilities(cls) -> list[dict[str, str]]:
		"""Return all registered capabilities for the designer picker."""
		return sorted(
			[{"name": e["name"], "description": e["description"]} for e in cls._registry.values()],
			key=lambda x: x["name"],
		)


# ── Built-in capabilities ────────────────────────────────────────────────────

@BPMActionRegistry.register("bpm.rules.evaluate", "Evaluate rules engine for a model/event")
def _bpm_rules_evaluate(record_ctx: dict, session: Any, model: str = "", event: str = "on_create", **kw: Any) -> dict:
	try:
		from pgappforge.plugins.rules.engine import get_rules_engine
		engine = get_rules_engine()
		engine.evaluate(model, event, type("R", (), record_ctx)(), session=session)
		return {"status": "ok"}
	except Exception as exc:
		return {"status": "blocked", "message": str(exc)}


@BPMActionRegistry.register("bpm.rules.dry_run", "Dry-run rules engine and return result")
def _bpm_rules_dry_run(record_ctx: dict, session: Any, model: str = "", event: str = "on_create", **kw: Any) -> dict:
	try:
		from pgappforge.plugins.rules.engine import get_rules_engine
		engine = get_rules_engine()
		return engine.evaluate_dry(model, event, type("R", (), record_ctx)(), session=session)
	except Exception as exc:
		return {"error": str(exc)}


@BPMActionRegistry.register("bpm.record.set_field", "Set a field on the workflow record")
def _bpm_set_field(record_ctx: dict, session: Any, model: str = "", record_id: Any = None, field: str = "", value: Any = None, **kw: Any) -> dict:
	if not model or not record_id or not field:
		return {"status": "skipped", "reason": "model/record_id/field required"}
	try:
		import importlib
		mod = importlib.import_module(f"pgappforge.plugins")
		# Attempt generic SQLAlchemy lookup via string model name
		from pgappforge.models.sqla import Model
		for cls in Model.__subclasses__():
			if getattr(cls, "__name__", "") == model:
				obj = session.get(cls, record_id)
				if obj is not None:
					setattr(obj, field, value)
					session.flush()
				return {"status": "ok", "field": field, "value": value}
		return {"status": "not_found", "model": model}
	except Exception as exc:
		return {"status": "error", "message": str(exc)}


@BPMActionRegistry.register("bpm.notify.email", "Send an email notification")
def _bpm_notify_email(record_ctx: dict, session: Any, to: str = "", subject: str = "", body: str = "", **kw: Any) -> dict:
	"""Default email implementation — logs the notification.
	Override by re-registering 'bpm.notify.email' with a real email provider
	(e.g. SendGrid, SES, or the app's existing notification service).
	"""
	log.info("BPM email notification: to=%r subject=%r (wire bpm.notify.email to a real provider)", to, subject)
	return {"status": "logged", "to": to, "subject": subject}


@BPMActionRegistry.register("bpm.notify.webhook", "Call a webhook URL")
def _bpm_notify_webhook(record_ctx: dict, session: Any, url: str = "", payload: dict | None = None, **kw: Any) -> dict:
	try:
		import httpx  # type: ignore[import]
		resp = httpx.post(url, json=payload or record_ctx, timeout=10)
		return {"status": "ok", "http_status": resp.status_code}
	except ImportError:
		log.warning("BPM webhook: httpx not installed")
		return {"status": "skipped", "reason": "httpx not available"}
	except Exception as exc:
		log.warning("BPM webhook error: %s", exc)
		return {"status": "error", "message": str(exc)}


def execute_step_action(action: dict[str, Any], record_ctx: dict[str, Any], session: Any) -> Any:
	"""Execute a single step action dict from on_enter / on_exit.

	Handles the "call_capability" type by dispatching to BPMActionRegistry.
	All other legacy action types are handled inline.
	"""
	atype = action.get("type", "")
	if atype == "call_capability":
		capability = action.get("capability", "")
		params = action.get("params") or {}
		return BPMActionRegistry.call(capability, record_ctx, params, session)
	elif atype in ("notify_role", "notify_email"):
		to = action.get("to") or action.get("role") or ""
		subj = action.get("subject", "Workflow notification")
		log.info("BPM step action %r: to=%r subject=%r", atype, to, subj)
	else:
		log.debug("BPM: unhandled step action type %r", atype)
	return None


__all__ = [
	"WorkflowEngine",
	"BPMActionRegistry",
	"execute_step_action",
]
