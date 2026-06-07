"""
pgappforge/plugins/erp/hcm/journeys/services.py

JourneyService — stateless business logic for the HCM Employee Journeys plugin.

All methods receive an explicit SQLAlchemy session; no Flask context assumed.
Transaction boundaries are owned by the caller.

Public methods:
  start_journey(...)            -> Journey
  complete_task(...)            -> JourneyTask
  skip_task(...)                -> JourneyTask
  get_employee_journey(...)     -> dict | None
  check_overdue_tasks(...)      -> list[dict]
  seed_onboarding_template(...) -> JourneyTemplate
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

import sqlalchemy as sa

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class JourneyServiceError(Exception):
	"""Base domain error for journey operations."""


class JourneyNotFoundError(JourneyServiceError):
	pass


class JourneyTaskNotFoundError(JourneyServiceError):
	pass


class JourneyStateError(JourneyServiceError):
	"""Invalid state transition."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _today() -> date:
	return datetime.now(timezone.utc).date()


def _emit(event: Any, session: Any = None) -> None:
	try:
		from pgappforge.plugins.erp.foundation.events import emit_event
		emit_event(event, session)
	except Exception as exc:
		log.debug("JourneyService._emit: could not emit %s: %s", type(event).__name__, exc)


# ---------------------------------------------------------------------------
# BPM process registration
# ---------------------------------------------------------------------------

def _register_bpm() -> None:
	try:
		from pgappforge.plugins.bpm import register

		@register("hcm.journeys.start", "Start employee journey (onboarding/offboarding)")
		def _bpm_start_journey(
			employee_id: str,
			journey_type: str,
			trigger_date: str,
			tenant_id: str,
			session: Any,
			template_id: str | None = None,
		) -> dict:
			svc = JourneyService()
			d = date.fromisoformat(trigger_date)
			journey = svc.start_journey(
				employee_id, journey_type, d, tenant_id, session,
				template_id=template_id,
			)
			return {"journey_id": journey.id}

		@register("hcm.journeys.complete_task", "Complete journey task")
		def _bpm_complete_task(
			task_id: str,
			owner_id: str,
			session: Any,
			notes: str | None = None,
		) -> dict:
			svc = JourneyService()
			task = svc.complete_task(task_id, owner_id, session, notes=notes)
			return {"task_id": task.id, "status": task.status}

	except ImportError:
		log.debug("JourneyService: BPM plugin not available, skipping process registration")


# ---------------------------------------------------------------------------
# Default onboarding template definition
# ---------------------------------------------------------------------------

_ONBOARDING_TASKS: list[dict[str, Any]] = [
	{"task_code": "IT_SETUP", "title": "Set up laptop + email", "owner_role": "IT_ADMIN", "due_days_offset": 1, "category": "IT", "is_mandatory": True, "depends_on": []},
	{"task_code": "HR_PAPERWORK", "title": "Complete employment contracts and tax forms", "owner_role": "HR", "due_days_offset": 1, "category": "HR", "is_mandatory": True, "depends_on": []},
	{"task_code": "BENEFITS_ENROLLMENT", "title": "Enroll in health and pension benefits", "owner_role": "HR", "due_days_offset": 3, "category": "HR", "is_mandatory": True, "depends_on": []},
	{"task_code": "PAYROLL_SETUP", "title": "Verify bank details and payroll profile", "owner_role": "PAYROLL", "due_days_offset": 2, "category": "FINANCE", "is_mandatory": True, "depends_on": []},
	{"task_code": "SECURITY_ACCESS", "title": "Set up VPN and system access", "owner_role": "IT_ADMIN", "due_days_offset": 1, "category": "IT", "is_mandatory": True, "depends_on": []},
	{"task_code": "MANAGER_INTRO", "title": "Manager introduction and 30-60-90 day plan", "owner_role": "MANAGER", "due_days_offset": 2, "category": "HR", "is_mandatory": True, "depends_on": []},
	{"task_code": "TEAM_INTRO", "title": "Introduction to team members", "owner_role": "MANAGER", "due_days_offset": 3, "category": "HR", "is_mandatory": False, "depends_on": []},
	{"task_code": "TRAINING_ASSIGN", "title": "Assign mandatory compliance training", "owner_role": "HR", "due_days_offset": 3, "category": "COMPLIANCE", "is_mandatory": True, "depends_on": []},
	{"task_code": "SAFETY_TRAINING", "title": "Complete workplace safety training", "owner_role": "HR", "due_days_offset": 7, "category": "COMPLIANCE", "is_mandatory": True, "depends_on": ["TRAINING_ASSIGN"]},
	{"task_code": "EQUIPMENT_ISSUE", "title": "Issue office equipment and access card", "owner_role": "FACILITIES", "due_days_offset": 1, "category": "IT", "is_mandatory": True, "depends_on": []},
	{"task_code": "POLICIES_SIGN", "title": "Sign company policies and code of conduct", "owner_role": "HR", "due_days_offset": 5, "category": "COMPLIANCE", "is_mandatory": True, "depends_on": []},
	{"task_code": "PROBATION_BRIEF", "title": "Brief on probation period and KPIs", "owner_role": "MANAGER", "due_days_offset": 5, "category": "HR", "is_mandatory": True, "depends_on": []},
	{"task_code": "BUDDY_ASSIGN", "title": "Assign onboarding buddy", "owner_role": "HR", "due_days_offset": 2, "category": "HR", "is_mandatory": False, "depends_on": []},
	{"task_code": "FIRST_WEEK_CHECK", "title": "First week check-in with manager", "owner_role": "MANAGER", "due_days_offset": 7, "category": "HR", "is_mandatory": True, "depends_on": ["MANAGER_INTRO"]},
	{"task_code": "ONBOARDING_COMPLETE", "title": "Mark onboarding complete in HRIS", "owner_role": "HR", "due_days_offset": 30, "category": "HR", "is_mandatory": True, "depends_on": []},
]


# ---------------------------------------------------------------------------
# JourneyService
# ---------------------------------------------------------------------------

class JourneyService:
	"""Stateless employee journey domain service.

	Instantiate once per application (no instance state).
	All public methods accept a SQLAlchemy Session as an explicit argument.
	"""

	# ------------------------------------------------------------------
	# start_journey
	# ------------------------------------------------------------------

	def start_journey(
		self,
		employee_id: str,
		journey_type: str,
		trigger_date: date,
		tenant_id: str,
		session: Any,
		*,
		template_id: str | None = None,
	) -> Any:
		"""Start an employee journey and seed tasks from a template.

		If template_id is None, looks for the default template for journey_type.
		If no default template exists, calls seed_onboarding_template for
		ONBOARDING; other types get an empty journey (tasks can be added manually).

		Tasks with empty depends_on lists are immediately advanced to IN_PROGRESS.

		Args:
			employee_id: Employee identifier.
			journey_type: ONBOARDING | OFFBOARDING | TRANSFER | ROLE_CHANGE | PROMOTION.
			trigger_date: Anchor date for task due-date calculations.
			tenant_id: Tenant UUID.
			session: SQLAlchemy session.
			template_id: Optional explicit template UUID.

		Returns:
			Persisted Journey with tasks flushed.
		"""
		from pgappforge.plugins.erp.hcm.journeys.models import Journey, JourneyTask, JourneyTemplate
		from pgappforge.plugins.erp.hcm.journeys.events import JourneyStartedEvent

		template: Any = None

		if template_id:
			template = session.get(JourneyTemplate, template_id)
			if template is None:
				raise JourneyNotFoundError(f"JourneyTemplate {template_id!r} not found")
		else:
			# Find default template for this journey_type + tenant
			template = session.execute(
				sa.select(JourneyTemplate)
				.where(JourneyTemplate.tenant_id == tenant_id)
				.where(JourneyTemplate.journey_type == journey_type)
				.where(JourneyTemplate.is_default == True)  # noqa: E712
				.where(JourneyTemplate.is_active == True)   # noqa: E712
				.limit(1)
			).scalar_one_or_none()

			if template is None and journey_type == "ONBOARDING":
				template = self.seed_onboarding_template(tenant_id, session)

		journey = Journey(
			tenant_id=tenant_id,
			employee_id=employee_id,
			template_id=template.id if template else None,
			journey_type=journey_type,
			trigger_date=trigger_date,
			status="ACTIVE",
		)
		session.add(journey)
		session.flush()

		# Seed tasks from template
		task_defs: list[dict[str, Any]] = (template.tasks or []) if template else []
		for task_def in task_defs:
			due_offset = int(task_def.get("due_days_offset", 0))
			due_date = trigger_date + timedelta(days=due_offset) if due_offset >= 0 else None
			depends_on: list[str] = task_def.get("depends_on", []) or []

			# Tasks with no dependencies start immediately IN_PROGRESS
			initial_status = "IN_PROGRESS" if not depends_on else "PENDING"

			session.add(JourneyTask(
				tenant_id=tenant_id,
				journey_id=journey.id,
				task_code=task_def["task_code"],
				title=task_def["title"],
				category=task_def.get("category"),
				is_mandatory=task_def.get("is_mandatory", True),
				owner_role=task_def.get("owner_role"),
				due_date=due_date,
				depends_on=depends_on,
				status=initial_status,
			))

		session.flush()

		_emit(
			JourneyStartedEvent(
				aggregate_id=journey.id,
				aggregate_type="Journey",
				tenant_id=tenant_id,
				journey_id=journey.id,
				employee_id=employee_id,
				journey_type=journey_type,
			),
			session,
		)
		log.info(
			"JourneyService.start_journey: journey=%s employee=%s type=%s tasks=%d",
			journey.id, employee_id, journey_type, len(task_defs),
		)
		return journey

	# ------------------------------------------------------------------
	# complete_task
	# ------------------------------------------------------------------

	def complete_task(
		self,
		task_id: str,
		owner_id: str,
		session: Any,
		*,
		notes: str | None = None,
	) -> Any:
		"""Mark a journey task as COMPLETE and advance dependent tasks.

		After marking complete, checks whether all mandatory tasks are done and
		calls _check_journey_completion() to potentially close the journey.

		Args:
			task_id: UUID of the JourneyTask.
			owner_id: User who completed the task.
			session: SQLAlchemy session.
			notes: Optional completion notes.

		Returns:
			Updated JourneyTask.

		Raises:
			JourneyTaskNotFoundError: Task not found.
			JourneyStateError: Task already COMPLETE or SKIPPED.
		"""
		from pgappforge.plugins.erp.hcm.journeys.models import JourneyTask
		from pgappforge.plugins.erp.hcm.journeys.events import JourneyTaskCompletedEvent

		task: Any = session.get(JourneyTask, task_id)
		if task is None:
			raise JourneyTaskNotFoundError(f"JourneyTask {task_id!r} not found")
		if task.status == "COMPLETE":
			raise JourneyStateError(f"JourneyTask {task_id!r} is already COMPLETE")
		if task.status == "SKIPPED":
			raise JourneyStateError(f"JourneyTask {task_id!r} is SKIPPED; cannot complete")

		now = datetime.now(timezone.utc)
		task.status = "COMPLETE"
		task.completed_at = now
		task.owner_id = owner_id
		task.updated_at = now
		if notes:
			task.notes = (task.notes or "") + f"\n{notes}"

		session.flush()

		# Auto-advance dependent tasks
		self._advance_dependents(task.task_code, task.journey_id, session)

		_emit(
			JourneyTaskCompletedEvent(
				aggregate_id=task.journey_id,
				aggregate_type="Journey",
				tenant_id=task.tenant_id,
				task_id=task_id,
				journey_id=task.journey_id,
				task_code=task.task_code,
				completed_by=owner_id,
			),
			session,
		)

		# Check if journey can be completed
		self._check_journey_completion(task.journey_id, session)

		log.info(
			"JourneyService.complete_task: task=%s code=%r journey=%s by=%s",
			task_id, task.task_code, task.journey_id, owner_id,
		)
		return task

	# ------------------------------------------------------------------
	# skip_task
	# ------------------------------------------------------------------

	def skip_task(
		self,
		task_id: str,
		owner_id: str,
		reason: str,
		session: Any,
	) -> Any:
		"""Skip a non-mandatory journey task and advance dependent tasks.

		Only tasks with is_mandatory=False may be skipped.

		Args:
			task_id: UUID of the JourneyTask.
			owner_id: User skipping the task.
			reason: Reason for skipping.
			session: SQLAlchemy session.

		Returns:
			Updated JourneyTask.

		Raises:
			JourneyTaskNotFoundError: Task not found.
			JourneyStateError: Task is mandatory or already terminal.
		"""
		from pgappforge.plugins.erp.hcm.journeys.models import JourneyTask
		from pgappforge.plugins.erp.hcm.journeys.events import JourneyTaskSkippedEvent

		task: Any = session.get(JourneyTask, task_id)
		if task is None:
			raise JourneyTaskNotFoundError(f"JourneyTask {task_id!r} not found")
		if task.is_mandatory:
			raise JourneyStateError(
				f"JourneyTask {task_id!r} ({task.task_code!r}) is mandatory and cannot be skipped"
			)
		if task.status in ("COMPLETE", "SKIPPED"):
			raise JourneyStateError(
				f"JourneyTask {task_id!r} is already {task.status!r}"
			)

		now = datetime.now(timezone.utc)
		task.status = "SKIPPED"
		task.owner_id = owner_id
		task.updated_at = now
		task.notes = (task.notes or "") + f"\n[SKIPPED] {reason}"

		session.flush()

		# Advance dependents — skipped tasks unblock downstream tasks
		self._advance_dependents(task.task_code, task.journey_id, session)

		_emit(
			JourneyTaskSkippedEvent(
				aggregate_id=task.journey_id,
				aggregate_type="Journey",
				tenant_id=task.tenant_id,
				task_id=task_id,
				journey_id=task.journey_id,
				task_code=task.task_code,
				reason=reason,
			),
			session,
		)

		# Check journey completion
		self._check_journey_completion(task.journey_id, session)

		log.info(
			"JourneyService.skip_task: task=%s code=%r journey=%s by=%s reason=%r",
			task_id, task.task_code, task.journey_id, owner_id, reason,
		)
		return task

	# ------------------------------------------------------------------
	# _advance_dependents
	# ------------------------------------------------------------------

	def _advance_dependents(
		self,
		completed_task_code: str,
		journey_id: str,
		session: Any,
	) -> None:
		"""Advance PENDING tasks whose dependencies are now all COMPLETE/SKIPPED.

		Called after any task transitions to COMPLETE or SKIPPED.
		"""
		from pgappforge.plugins.erp.hcm.journeys.models import JourneyTask

		# Load all tasks for this journey to evaluate dependencies in-process
		all_tasks: list[Any] = session.execute(
			sa.select(JourneyTask).where(JourneyTask.journey_id == journey_id)
		).scalars().all()

		done_codes: set[str] = {
			t.task_code for t in all_tasks
			if t.status in ("COMPLETE", "SKIPPED")
		}

		now = datetime.now(timezone.utc)
		for t in all_tasks:
			if t.status != "PENDING":
				continue
			deps: list[str] = t.depends_on or []
			if deps and all(dep in done_codes for dep in deps):
				t.status = "IN_PROGRESS"
				t.updated_at = now
				log.debug(
					"JourneyService._advance_dependents: task %s (%r) -> IN_PROGRESS",
					t.id, t.task_code,
				)

		session.flush()

	# ------------------------------------------------------------------
	# _check_journey_completion
	# ------------------------------------------------------------------

	def _check_journey_completion(self, journey_id: str, session: Any) -> None:
		"""Complete the journey if all mandatory tasks are COMPLETE or SKIPPED."""
		from pgappforge.plugins.erp.hcm.journeys.models import Journey, JourneyTask
		from pgappforge.plugins.erp.hcm.journeys.events import JourneyCompletedEvent

		journey: Any = session.get(Journey, journey_id)
		if journey is None or journey.status != "ACTIVE":
			return

		all_tasks: list[Any] = session.execute(
			sa.select(JourneyTask).where(JourneyTask.journey_id == journey_id)
		).scalars().all()

		mandatory_tasks = [t for t in all_tasks if t.is_mandatory]
		if not mandatory_tasks:
			return

		all_done = all(t.status in ("COMPLETE", "SKIPPED") for t in mandatory_tasks)
		if not all_done:
			return

		now = datetime.now(timezone.utc)
		journey.status = "COMPLETED"
		journey.completed_at = now
		journey.updated_at = now

		duration_days = (now.date() - journey.trigger_date).days if journey.trigger_date else 0

		session.flush()

		_emit(
			JourneyCompletedEvent(
				aggregate_id=journey_id,
				aggregate_type="Journey",
				tenant_id=journey.tenant_id,
				journey_id=journey_id,
				employee_id=journey.employee_id,
				journey_type=journey.journey_type,
				duration_days=duration_days,
			),
			session,
		)
		log.info(
			"JourneyService._check_journey_completion: journey=%s employee=%s completed in %d days",
			journey_id, journey.employee_id, duration_days,
		)

	# ------------------------------------------------------------------
	# get_employee_journey
	# ------------------------------------------------------------------

	def get_employee_journey(
		self,
		employee_id: str,
		tenant_id: str,
		session: Any,
		*,
		journey_type: str | None = None,
	) -> dict[str, Any] | None:
		"""Return the active journey + task summary for an employee.

		If journey_type is supplied, filters to that type.

		Returns:
		  {
		    journey: {id, journey_type, trigger_date, status},
		    tasks: [{id, task_code, title, status, due_date, is_mandatory, owner_role}],
		    completion_pct: float,   # % of all tasks that are COMPLETE or SKIPPED
		    overdue_tasks: [...]     # tasks that are IN_PROGRESS and past due_date
		  }
		  or None if no active journey found.
		"""
		from pgappforge.plugins.erp.hcm.journeys.models import Journey, JourneyTask

		q = (
			sa.select(Journey)
			.where(Journey.tenant_id == tenant_id)
			.where(Journey.employee_id == employee_id)
			.where(Journey.status == "ACTIVE")
		)
		if journey_type:
			q = q.where(Journey.journey_type == journey_type)
		q = q.order_by(Journey.created_at.desc()).limit(1)

		journey: Any = session.execute(q).scalar_one_or_none()
		if journey is None:
			return None

		tasks: list[Any] = session.execute(
			sa.select(JourneyTask)
			.where(JourneyTask.journey_id == journey.id)
			.order_by(JourneyTask.due_date.nulls_last(), JourneyTask.task_code)
		).scalars().all()

		today = _today()
		overdue: list[dict[str, Any]] = []
		terminal = 0

		task_summaries: list[dict[str, Any]] = []
		for t in tasks:
			if t.status in ("COMPLETE", "SKIPPED"):
				terminal += 1
			if (
				t.status == "IN_PROGRESS"
				and t.due_date is not None
				and t.due_date < today
			):
				days_over = (today - t.due_date).days
				overdue.append({
					"task_id": t.id,
					"task_code": t.task_code,
					"title": t.title,
					"due_date": t.due_date.isoformat(),
					"days_overdue": days_over,
					"owner_role": t.owner_role,
				})
			task_summaries.append({
				"id": t.id,
				"task_code": t.task_code,
				"title": t.title,
				"status": t.status,
				"is_mandatory": t.is_mandatory,
				"category": t.category,
				"due_date": t.due_date.isoformat() if t.due_date else None,
				"owner_role": t.owner_role,
				"owner_id": t.owner_id,
				"depends_on": t.depends_on or [],
			})

		total = len(tasks)
		completion_pct = (terminal / total * 100.0) if total > 0 else 0.0

		return {
			"journey": {
				"id": journey.id,
				"journey_type": journey.journey_type,
				"trigger_date": journey.trigger_date.isoformat() if journey.trigger_date else None,
				"status": journey.status,
				"template_id": journey.template_id,
			},
			"tasks": task_summaries,
			"completion_pct": round(completion_pct, 1),
			"overdue_tasks": overdue,
		}

	# ------------------------------------------------------------------
	# check_overdue_tasks
	# ------------------------------------------------------------------

	def check_overdue_tasks(
		self,
		tenant_id: str,
		session: Any,
	) -> list[dict[str, Any]]:
		"""Find all IN_PROGRESS tasks past their due_date and emit overdue events.

		Args:
			tenant_id: Tenant UUID.
			session: SQLAlchemy session.

		Returns:
			List of overdue task dicts with days_overdue.
		"""
		from pgappforge.plugins.erp.hcm.journeys.models import Journey, JourneyTask
		from pgappforge.plugins.erp.hcm.journeys.events import JourneyOverdueTaskEvent

		today = _today()

		overdue_tasks: list[Any] = session.execute(
			sa.select(JourneyTask)
			.join(Journey, JourneyTask.journey_id == Journey.id)
			.where(JourneyTask.tenant_id == tenant_id)
			.where(Journey.status == "ACTIVE")
			.where(JourneyTask.status == "IN_PROGRESS")
			.where(JourneyTask.due_date < today)
			.order_by(JourneyTask.due_date)
		).scalars().all()

		results: list[dict[str, Any]] = []
		for task in overdue_tasks:
			days_overdue = (today - task.due_date).days
			_emit(
				JourneyOverdueTaskEvent(
					aggregate_id=task.journey_id,
					aggregate_type="Journey",
					tenant_id=task.tenant_id,
					task_id=task.id,
					journey_id=task.journey_id,
					task_code=task.task_code,
					days_overdue=days_overdue,
				),
				session,
			)
			results.append({
				"task_id": task.id,
				"journey_id": task.journey_id,
				"task_code": task.task_code,
				"title": task.title,
				"due_date": task.due_date.isoformat(),
				"days_overdue": days_overdue,
				"owner_role": task.owner_role,
				"owner_id": task.owner_id,
				"is_mandatory": task.is_mandatory,
			})

		log.info(
			"JourneyService.check_overdue_tasks: tenant=%s overdue=%d",
			tenant_id, len(results),
		)
		return results

	# ------------------------------------------------------------------
	# seed_onboarding_template
	# ------------------------------------------------------------------

	def seed_onboarding_template(
		self,
		tenant_id: str,
		session: Any,
	) -> Any:
		"""Idempotently create the default 15-task ONBOARDING template.

		Safe to call multiple times — returns existing template if one already
		exists for (tenant_id, ONBOARDING, is_default=True).

		Args:
			tenant_id: Tenant UUID.
			session: SQLAlchemy session.

		Returns:
			JourneyTemplate (existing or newly created).
		"""
		from pgappforge.plugins.erp.hcm.journeys.models import JourneyTemplate

		existing: Any = session.execute(
			sa.select(JourneyTemplate)
			.where(JourneyTemplate.tenant_id == tenant_id)
			.where(JourneyTemplate.journey_type == "ONBOARDING")
			.where(JourneyTemplate.is_default == True)  # noqa: E712
			.limit(1)
		).scalar_one_or_none()

		if existing is not None:
			log.debug(
				"JourneyService.seed_onboarding_template: template %s already exists for tenant %s",
				existing.id, tenant_id,
			)
			return existing

		template = JourneyTemplate(
			tenant_id=tenant_id,
			name="Default Onboarding",
			journey_type="ONBOARDING",
			description="Standard 15-task employee onboarding journey covering IT, HR, compliance, and manager introduction.",
			is_default=True,
			is_active=True,
			tasks=_ONBOARDING_TASKS,
		)
		session.add(template)
		session.flush()

		log.info(
			"JourneyService.seed_onboarding_template: created template=%s tenant=%s tasks=%d",
			template.id, tenant_id, len(_ONBOARDING_TASKS),
		)
		return template


# Attempt BPM registration at import time (best-effort)
try:
	_register_bpm()
except Exception as _exc:
	log.debug("JourneyService: BPM registration failed: %s", _exc)


__all__ = [
	"JourneyService",
	"JourneyServiceError",
	"JourneyNotFoundError",
	"JourneyTaskNotFoundError",
	"JourneyStateError",
]
