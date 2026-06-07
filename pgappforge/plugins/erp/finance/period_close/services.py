"""
pgappforge/plugins/erp/finance/period_close/services.py

PeriodCloseService — orchestrates the month-end/period-close checklist lifecycle.

BPM actions registered
----------------------
  finance.period_close.complete_task  — mark a task complete
  finance.period_close.finalize       — finalize / seal the period
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import sqlalchemy as sa

from pgappforge.plugins.erp.foundation.events import emit_event
from pgappforge.plugins.erp.finance.period_close.events import (
	PeriodCloseBlockedEvent,
	PeriodCloseFinalizedEvent,
	PeriodCloseStartedEvent,
	PeriodCloseTaskCompletedEvent,
	PeriodCloseTaskSkippedEvent,
)
from pgappforge.plugins.erp.finance.period_close.models import (
	PeriodClose,
	PeriodCloseTask,
	PeriodCloseTemplate,
)
from pgappforge.plugins.workflow.engine import BPMActionRegistry

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class PeriodCloseError(Exception):
	"""Base error for period close operations."""


class PeriodCloseNotFoundError(PeriodCloseError):
	"""Raised when a PeriodClose record cannot be found."""


class PeriodCloseTaskNotFoundError(PeriodCloseError):
	"""Raised when a PeriodCloseTask record cannot be found."""


class PeriodCloseValidationError(PeriodCloseError):
	"""Raised for invalid state transitions or constraint violations."""


# ---------------------------------------------------------------------------
# Default template task definitions
# ---------------------------------------------------------------------------

_DEFAULT_TASKS: list[dict[str, Any]] = [
	{
		"task_code": "AR_RECONCILE",
		"title": "Accounts Receivable Reconciliation",
		"is_mandatory": True,
		"owner_role": "AR_MANAGER",
		"depends_on": [],
		"description": "Reconcile AR subledger to GL control account.",
	},
	{
		"task_code": "AP_RECONCILE",
		"title": "Accounts Payable Reconciliation",
		"is_mandatory": True,
		"owner_role": "AP_MANAGER",
		"depends_on": [],
		"description": "Reconcile AP subledger to GL control account.",
	},
	{
		"task_code": "BANK_RECONCILE",
		"title": "Bank Reconciliation",
		"is_mandatory": True,
		"owner_role": "TREASURY",
		"depends_on": [],
		"description": "Reconcile all bank accounts to bank statements.",
	},
	{
		"task_code": "INVENTORY_COUNT",
		"title": "Inventory Count & Valuation",
		"is_mandatory": True,
		"owner_role": "WAREHOUSE_MGR",
		"depends_on": [],
		"description": "Confirm physical inventory matches system quantities; post adjustments.",
	},
	{
		"task_code": "ACCRUALS_POST",
		"title": "Post Accruals",
		"is_mandatory": True,
		"owner_role": "ACCOUNTANT",
		"depends_on": ["AR_RECONCILE", "AP_RECONCILE"],
		"description": "Post period-end accrual journals for unrecorded liabilities and revenues.",
	},
	{
		"task_code": "PREPAYMENTS_POST",
		"title": "Post Prepayment Amortisation",
		"is_mandatory": True,
		"owner_role": "ACCOUNTANT",
		"depends_on": ["AR_RECONCILE", "AP_RECONCILE"],
		"description": "Amortise prepaid expenses and unearned revenues for the period.",
	},
	{
		"task_code": "DEPRECIATION_RUN",
		"title": "Run Depreciation",
		"is_mandatory": True,
		"owner_role": "ACCOUNTANT",
		"depends_on": [],
		"description": "Execute fixed asset depreciation run and post journals.",
	},
	{
		"task_code": "PAYROLL_CLOSE",
		"title": "Payroll Period Close",
		"is_mandatory": True,
		"owner_role": "PAYROLL_MGR",
		"depends_on": [],
		"description": "Confirm payroll journals are posted and payroll subledger is balanced.",
	},
	{
		"task_code": "INTERCOMPANY_ELIMINATE",
		"title": "Intercompany Elimination",
		"is_mandatory": False,
		"owner_role": "GROUP_ACCOUNTANT",
		"depends_on": ["AR_RECONCILE", "AP_RECONCILE"],
		"description": "Eliminate intercompany balances for consolidation. Optional for standalone entities.",
	},
	{
		"task_code": "REVENUE_RECOGNIZE",
		"title": "Revenue Recognition",
		"is_mandatory": True,
		"owner_role": "ACCOUNTANT",
		"depends_on": ["AR_RECONCILE"],
		"description": "Apply revenue recognition rules; post deferred/recognised revenue adjustments.",
	},
	{
		"task_code": "TAX_ACCRUE",
		"title": "Tax Accrual",
		"is_mandatory": True,
		"owner_role": "TAX_ACCOUNTANT",
		"depends_on": ["ACCRUALS_POST"],
		"description": "Calculate and post current-period tax accruals (VAT, corporate tax, withholding).",
	},
	{
		"task_code": "TRIAL_BALANCE_REVIEW",
		"title": "Trial Balance Review",
		"is_mandatory": True,
		"owner_role": "CFO",
		"depends_on": [
			"AR_RECONCILE",
			"AP_RECONCILE",
			"BANK_RECONCILE",
			"INVENTORY_COUNT",
			"ACCRUALS_POST",
			"PREPAYMENTS_POST",
			"DEPRECIATION_RUN",
			"PAYROLL_CLOSE",
			"INTERCOMPANY_ELIMINATE",
			"REVENUE_RECOGNIZE",
			"TAX_ACCRUE",
		],
		"description": "CFO sign-off: review trial balance for completeness and accuracy before seal.",
	},
]


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _now() -> datetime:
	return datetime.now(tz=timezone.utc)


def _emit(event: Any, session: Any = None) -> None:
	try:
		emit_event(event, session)
	except Exception as exc:
		log.debug("_emit suppressed: %s", exc)


def _new_id() -> str:
	return str(uuid4())


def _terminal(status: str) -> bool:
	return status in ("COMPLETE", "SKIPPED")


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class PeriodCloseService:
	"""Orchestrates period-close checklist lifecycle.

	All methods accept a SQLAlchemy Session as *session* and expect the caller
	to manage transaction boundaries (commit / rollback).
	"""

	# ------------------------------------------------------------------
	# Template seeding
	# ------------------------------------------------------------------

	def seed_default_template(self, tenant_id: str, session: Any) -> PeriodCloseTemplate:
		"""Return the default template for *tenant_id*, creating it if absent.

		Idempotent — safe to call on every app start.
		"""
		existing = session.execute(
			sa.select(PeriodCloseTemplate).where(
				PeriodCloseTemplate.tenant_id == tenant_id,
				PeriodCloseTemplate.is_default.is_(True),
			)
		).scalar_one_or_none()
		if existing is not None:
			return existing

		tpl = PeriodCloseTemplate(
			id=_new_id(),
			tenant_id=tenant_id,
			name="Standard Period Close Checklist",
			description=(
				"12-step month-end close covering AR, AP, bank, inventory, "
				"accruals, depreciation, payroll, intercompany, revenue, tax, "
				"and CFO trial balance sign-off."
			),
			is_default=True,
			tasks=_DEFAULT_TASKS,
		)
		session.add(tpl)
		session.flush()
		log.info("PeriodCloseService: seeded default template id=%s tenant=%s", tpl.id, tenant_id)
		return tpl

	# ------------------------------------------------------------------
	# Start close
	# ------------------------------------------------------------------

	def start_close(
		self,
		period: str,
		tenant_id: str,
		session: Any,
		*,
		entity_id: str | None = None,
		template_id: str | None = None,
		started_by: str | None = None,
	) -> PeriodClose:
		"""Create a PeriodClose (IN_PROGRESS) and instantiate all tasks.

		If no *template_id* is supplied the tenant's default template is used,
		seeding it if it does not yet exist.
		"""
		# Resolve template
		if template_id:
			tpl = session.execute(
				sa.select(PeriodCloseTemplate).where(PeriodCloseTemplate.id == template_id)
			).scalar_one_or_none()
			if tpl is None:
				raise PeriodCloseNotFoundError(f"Template {template_id!r} not found")
		else:
			tpl = self.seed_default_template(tenant_id, session)

		# Create close record
		close = PeriodClose(
			id=_new_id(),
			tenant_id=tenant_id,
			period=period,
			entity_id=entity_id,
			template_id=tpl.id,
			status="IN_PROGRESS",
			started_at=_now(),
			started_by=started_by,
		)
		session.add(close)
		session.flush()

		# Determine which task_codes have no dependencies (start immediately)
		all_codes: set[str] = {t["task_code"] for t in tpl.tasks}
		for task_def in tpl.tasks:
			# Filter depends_on to only valid codes within this template
			valid_deps = [d for d in task_def.get("depends_on", []) if d in all_codes]
			initial_status = "IN_PROGRESS" if not valid_deps else "PENDING"
			task = PeriodCloseTask(
				id=_new_id(),
				tenant_id=tenant_id,
				close_id=close.id,
				task_code=task_def["task_code"],
				title=task_def["title"],
				is_mandatory=task_def.get("is_mandatory", True),
				owner_role=task_def.get("owner_role"),
				depends_on=valid_deps,
				status=initial_status,
			)
			session.add(task)

		session.flush()

		_emit(
			PeriodCloseStartedEvent(
				aggregate_id=close.id,
				aggregate_type="PeriodClose",
				tenant_id=tenant_id,
				close_id=close.id,
				period=period,
				entity_id=entity_id or "",
			),
			session,
		)
		log.info(
			"PeriodCloseService.start_close: close=%s period=%s tenant=%s",
			close.id, period, tenant_id,
		)
		return close

	# ------------------------------------------------------------------
	# Task completion
	# ------------------------------------------------------------------

	def complete_task(
		self,
		task_id: str,
		owner_id: str,
		session: Any,
		*,
		notes: str | None = None,
	) -> PeriodCloseTask:
		"""Mark *task_id* COMPLETE and advance any newly-unblocked dependents."""
		task = session.execute(
			sa.select(PeriodCloseTask).where(PeriodCloseTask.id == task_id)
		).scalar_one_or_none()
		if task is None:
			raise PeriodCloseTaskNotFoundError(f"Task {task_id!r} not found")

		assert task.status in ("PENDING", "IN_PROGRESS"), (
			f"Cannot complete task in status {task.status!r}"
		)

		task.status = "COMPLETE"
		task.completed_at = _now()
		task.owner_id = owner_id
		if notes:
			task.notes = notes
		session.flush()

		self._advance_dependents(task.close_id, task.task_code, session)

		_emit(
			PeriodCloseTaskCompletedEvent(
				aggregate_id=task.id,
				aggregate_type="PeriodCloseTask",
				tenant_id=task.tenant_id or "",
				task_id=task.id,
				close_id=task.close_id,
				task_code=task.task_code,
				completed_by=owner_id,
			),
			session,
		)
		return task

	# ------------------------------------------------------------------
	# Task skipping
	# ------------------------------------------------------------------

	def skip_task(
		self,
		task_id: str,
		owner_id: str,
		reason: str,
		session: Any,
		*,
		force: bool = False,
	) -> PeriodCloseTask:
		"""Mark *task_id* SKIPPED.

		Mandatory tasks require *force=True* to skip.
		"""
		task = session.execute(
			sa.select(PeriodCloseTask).where(PeriodCloseTask.id == task_id)
		).scalar_one_or_none()
		if task is None:
			raise PeriodCloseTaskNotFoundError(f"Task {task_id!r} not found")

		assert task.status != "COMPLETE", (
			f"Cannot skip already-completed task {task.task_code!r}"
		)
		if task.is_mandatory and not force:
			raise PeriodCloseValidationError(
				f"Task {task.task_code!r} is mandatory; pass force=True to skip"
			)

		task.status = "SKIPPED"
		task.owner_id = owner_id
		task.notes = reason
		task.completed_at = _now()
		session.flush()

		self._advance_dependents(task.close_id, task.task_code, session)

		_emit(
			PeriodCloseTaskSkippedEvent(
				aggregate_id=task.id,
				aggregate_type="PeriodCloseTask",
				tenant_id=task.tenant_id or "",
				task_id=task.id,
				close_id=task.close_id,
				task_code=task.task_code,
				reason=reason,
			),
			session,
		)
		return task

	# ------------------------------------------------------------------
	# Check / finalize
	# ------------------------------------------------------------------

	def check_can_close(self, close_id: str, session: Any) -> dict[str, Any]:
		"""Return blocking mandatory tasks that prevent finalization.

		Returns:
		    {
		        "can_close": bool,
		        "blocking_tasks": [{"task_code": str, "title": str, "status": str}]
		    }
		"""
		tasks: list[PeriodCloseTask] = list(
			session.execute(
				sa.select(PeriodCloseTask).where(PeriodCloseTask.close_id == close_id)
			).scalars()
		)
		blocking = [
			{"task_code": t.task_code, "title": t.title, "status": t.status}
			for t in tasks
			if t.is_mandatory and not _terminal(t.status)
		]
		return {"can_close": len(blocking) == 0, "blocking_tasks": blocking}

	def finalize_close(self, close_id: str, closed_by: str, session: Any) -> PeriodClose:
		"""Seal the period.

		Raises PeriodCloseValidationError (and emits PeriodCloseBlockedEvent) if
		any mandatory task is still PENDING or IN_PROGRESS.
		"""
		close = session.execute(
			sa.select(PeriodClose).where(PeriodClose.id == close_id)
		).scalar_one_or_none()
		if close is None:
			raise PeriodCloseNotFoundError(f"PeriodClose {close_id!r} not found")

		result = self.check_can_close(close_id, session)
		if not result["can_close"]:
			blocking_codes = [t["task_code"] for t in result["blocking_tasks"]]
			_emit(
				PeriodCloseBlockedEvent(
					aggregate_id=close_id,
					aggregate_type="PeriodClose",
					tenant_id=close.tenant_id or "",
					close_id=close_id,
					period=close.period,
					blocking_task_codes=blocking_codes,
				),
				session,
			)
			raise PeriodCloseValidationError(
				f"Cannot finalize period {close.period!r}: "
				f"{len(blocking_codes)} mandatory task(s) outstanding: {blocking_codes}"
			)

		close.status = "CLOSED"
		close.closed_at = _now()
		close.closed_by = closed_by
		session.flush()

		# Lock the matching GLPeriod(s) so post_journal rejects new postings.
		# GLPeriod.post_journal() already raises ClosedPeriodError when status != 'OPEN'.
		try:
			from pgappforge.plugins.erp.finance.gl.models import GLPeriod
			from datetime import date as _date
			year_str, month_str = close.period.split("-")
			year, month = int(year_str), int(month_str)
			period_start = _date(year, month, 1)
			next_month = month + 1 if month < 12 else 1
			next_year = year if month < 12 else year + 1
			period_end_exclusive = _date(next_year, next_month, 1)

			gl_periods = session.execute(
				sa.select(GLPeriod).where(
					GLPeriod.tenant_id == close.tenant_id,
					GLPeriod.start_date >= period_start,
					GLPeriod.start_date < period_end_exclusive,
					GLPeriod.status == "OPEN",
				)
			).scalars().all()

			for gp in gl_periods:
				gp.status = "CLOSED"
				gp.closed_by = closed_by
				gp.closed_at = close.closed_at
				log.info(
					"PeriodCloseService: GL period %s locked (period_name=%r)",
					gp.id, gp.period_name,
				)
			if gl_periods:
				session.flush()
		except ImportError:
			log.debug("finalize_close: GL plugin not available; GL period not locked")
		except ValueError:
			log.warning("finalize_close: period %r not parseable as YYYY-MM; GL period not locked", close.period)

		_emit(
			PeriodCloseFinalizedEvent(
				aggregate_id=close_id,
				aggregate_type="PeriodClose",
				tenant_id=close.tenant_id or "",
				close_id=close_id,
				period=close.period,
				entity_id=close.entity_id or "",
				closed_by=closed_by,
			),
			session,
		)
		log.info(
			"PeriodCloseService.finalize_close: close=%s period=%s closed_by=%s",
			close_id, close.period, closed_by,
		)
		return close

	# ------------------------------------------------------------------
	# Internal helpers
	# ------------------------------------------------------------------

	def _advance_dependents(self, close_id: str, completed_code: str, session: Any) -> None:
		"""Set IN_PROGRESS on tasks whose full dependency set is now terminal."""
		# Load all tasks for this close in one query
		all_tasks: list[PeriodCloseTask] = list(
			session.execute(
				sa.select(PeriodCloseTask).where(PeriodCloseTask.close_id == close_id)
			).scalars()
		)
		terminal_codes: set[str] = {t.task_code for t in all_tasks if _terminal(t.status)}

		for t in all_tasks:
			if t.status != "PENDING":
				continue
			if completed_code not in (t.depends_on or []):
				continue
			# All deps must be terminal
			if all(dep in terminal_codes for dep in (t.depends_on or [])):
				t.status = "IN_PROGRESS"
				log.debug(
					"_advance_dependents: task %s → IN_PROGRESS (unblocked by %s)",
					t.task_code, completed_code,
				)
		session.flush()


# ---------------------------------------------------------------------------
# BPM action registrations
# ---------------------------------------------------------------------------

@BPMActionRegistry.register(
	"finance.period_close.complete_task",
	"Mark period close task complete",
)
def _bpm_complete_task(
	record_ctx: dict,
	session: Any,
	task_id: str = "",
	owner_id: str = "",
	notes: str | None = None,
	**kw: Any,
) -> dict:
	try:
		svc = PeriodCloseService()
		task = svc.complete_task(task_id, owner_id, session, notes=notes)
		return {"status": "ok", "task_id": task.id, "task_status": task.status}
	except Exception as exc:
		return {"status": "error", "message": str(exc)}


@BPMActionRegistry.register(
	"finance.period_close.finalize",
	"Finalize period close",
)
def _bpm_finalize(
	record_ctx: dict,
	session: Any,
	close_id: str = "",
	closed_by: str = "",
	**kw: Any,
) -> dict:
	try:
		svc = PeriodCloseService()
		close = svc.finalize_close(close_id, closed_by, session)
		return {"status": "ok", "close_id": close.id, "close_status": close.status}
	except Exception as exc:
		return {"status": "error", "message": str(exc)}


__all__ = [
	"PeriodCloseService",
	"PeriodCloseError",
	"PeriodCloseNotFoundError",
	"PeriodCloseTaskNotFoundError",
	"PeriodCloseValidationError",
]
