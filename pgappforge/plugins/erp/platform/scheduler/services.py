"""
pgappforge/plugins/erp/platform/scheduler/services.py

BatchSchedulerService — finds and executes due scheduled jobs.

Intended call pattern
---------------------
  Invoke run_due_jobs() from any periodic trigger:
    - APScheduler / Celery beat (e.g. every minute)
    - OS cron calling a Flask CLI command: ``flask scheduler run-due``
    - A lightweight thread started at app startup

The service is entirely synchronous.  No Celery tasks are created here;
Celery / APScheduler are treated as external triggers, not dependencies.
"""
from __future__ import annotations

import importlib
import inspect
import logging
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import sqlalchemy as sa
from sqlalchemy import select, and_

from pgappforge.plugins.erp.platform.scheduler.models import JobRunLog, ScheduledJob

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _uuid4() -> str:
	return str(uuid.uuid4())


def _now() -> datetime:
	return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# BatchSchedulerService
# ---------------------------------------------------------------------------

class BatchSchedulerService:
	"""Runs due scheduled jobs sequentially within the caller's session.

	Designed to be stateless — instantiate once per tick, or reuse a singleton.

	Thread-safety note: SQLAlchemy sessions are NOT thread-safe.  The caller
	is responsible for providing a properly scoped session (e.g. a Flask
	request-scoped session or a manually opened session from the engine).
	"""

	# ------------------------------------------------------------------
	# Public API
	# ------------------------------------------------------------------

	def run_due_jobs(self, tenant_id: str, session: Any) -> dict[str, Any]:
		"""Find and execute all jobs due for execution for a given tenant.

		A job is *due* when:
		  is_active = TRUE
		  AND (next_run_at IS NULL OR next_run_at <= now())
		  AND last_run_status IS NULL OR last_run_status != 'RUNNING'

		Jobs are executed sequentially ordered by next_run_at ASC NULLS FIRST
		(oldest-due first).  Each job updates its own status and schedules the
		next run before moving on; a failure in one job does not abort others.

		Returns:
		  {"ran": int, "succeeded": int, "failed": int, "results": [...]}
		"""
		now = _now()
		due_jobs = session.execute(
			select(ScheduledJob).where(
				and_(
					ScheduledJob.tenant_id == tenant_id,
					ScheduledJob.is_active.is_(True),
					sa.or_(
						ScheduledJob.next_run_at.is_(None),
						ScheduledJob.next_run_at <= now,
					),
					sa.or_(
						ScheduledJob.last_run_status.is_(None),
						ScheduledJob.last_run_status != "RUNNING",
					),
				)
			).order_by(ScheduledJob.next_run_at.asc().nulls_first())
		).scalars().all()

		results: list[dict] = []
		succeeded = failed = 0

		for job in due_jobs:
			result = self._run_job(job, tenant_id, session)
			results.append(result)
			if result["status"] == "SUCCESS":
				succeeded += 1
			else:
				failed += 1

		return {
			"ran": len(due_jobs),
			"succeeded": succeeded,
			"failed": failed,
			"results": results,
		}

	def register_job(
		self,
		name: str,
		description: str,
		frequency: str,
		plugin_path: str,
		service_class: str,
		method_name: str,
		tenant_id: str,
		session: Any,
		*,
		method_kwargs: dict | None = None,
		cron_expression: str | None = None,
	) -> ScheduledJob:
		"""Register a scheduled job, idempotent — returns existing row if found.

		Args:
		    name:            Unique dotted key e.g. "core_banking.daily_interest".
		    description:     Human-readable summary shown in the admin UI.
		    frequency:       DAILY / WEEKLY / MONTHLY / HOURLY / ONCE.
		    plugin_path:     Fully-qualified module path to import.
		    service_class:   Class name inside that module.
		    method_name:     Method to call on an instantiated service.
		    tenant_id:       Tenant scope.
		    session:         Active SQLAlchemy session.
		    method_kwargs:   Extra kwargs forwarded to the method (excluding
		                     session / tenant_id which are auto-injected).
		    cron_expression: Optional cron string for documentation purposes.

		Returns:
		    The existing or newly-created ScheduledJob instance.
		"""
		existing = session.execute(
			select(ScheduledJob).where(
				ScheduledJob.name == name,
				ScheduledJob.tenant_id == tenant_id,
			)
		).scalar_one_or_none()
		if existing:
			return existing

		job = ScheduledJob(
			id=_uuid4(),
			tenant_id=tenant_id,
			name=name,
			description=description,
			frequency=frequency,
			plugin_path=plugin_path,
			service_class=service_class,
			method_name=method_name,
			method_kwargs=method_kwargs or {},
			cron_expression=cron_expression,
			is_active=True,
		)
		session.add(job)
		session.flush()
		log.debug("SchedulerService: registered job %r for tenant %r", name, tenant_id)
		return job

	def seed_standard_jobs(self, tenant_id: str, session: Any) -> int:
		"""Register the standard bank/SACCO/mobile-money batch jobs.

		Idempotent — skips jobs that already exist.  Returns count registered
		(0 if all already present).

		Standard job set:
		  core_banking.daily_interest     — daily interest accrual
		  core_banking.dormancy_check     — mark dormant accounts (180-day threshold)
		  core_banking.expire_holds       — expire stale account holds
		  lending.daily_aging             — loan aging + NPA classification
		  lending.standing_orders         — execute loan standing order repayments
		  mobile_money.dormancy           — mark dormant mobile wallets
		  mobile_money.eod_reconciliation — end-of-day reconciliation
		  clubs.monthly_statements        — club member monthly statement generation
		"""
		STANDARD_JOBS: list[dict] = [
			{
				"name": "core_banking.daily_interest",
				"description": "Daily interest accrual on all accounts",
				"frequency": "DAILY",
				"plugin_path": "pgappforge.plugins.fintech.core_banking.services",
				"service_class": "CoreBankingService",
				"method_name": "run_maintenance_fee_batch",
			},
			{
				"name": "core_banking.dormancy_check",
				"description": "Mark dormant accounts (180-day inactivity threshold)",
				"frequency": "DAILY",
				"plugin_path": "pgappforge.plugins.fintech.core_banking.services",
				"service_class": "CoreBankingService",
				"method_name": "run_dormancy_check",
				"method_kwargs": {"dormancy_threshold_days": 180},
			},
			{
				"name": "core_banking.expire_holds",
				"description": "Expire stale account holds",
				"frequency": "DAILY",
				"plugin_path": "pgappforge.plugins.fintech.core_banking.services",
				"service_class": "CoreBankingService",
				"method_name": "expire_stale_holds",
			},
			{
				"name": "lending.daily_aging",
				"description": "Loan daily aging and NPA classification",
				"frequency": "DAILY",
				"plugin_path": "pgappforge.plugins.fintech.lending.services",
				"service_class": "LoanManagementService",
				"method_name": "run_daily_aging",
			},
			{
				"name": "lending.standing_orders",
				"description": "Execute loan standing order repayments",
				"frequency": "DAILY",
				"plugin_path": "pgappforge.plugins.fintech.lending.services",
				"service_class": "LoanManagementService",
				"method_name": "execute_standing_orders",
			},
			{
				"name": "mobile_money.dormancy",
				"description": "Mark dormant mobile wallets",
				"frequency": "DAILY",
				"plugin_path": "pgappforge.plugins.fintech.mobile_money.services",
				"service_class": "MobileMoneyService",
				"method_name": "mark_dormant_wallets",
			},
			{
				"name": "mobile_money.eod_reconciliation",
				"description": "Mobile money end-of-day reconciliation",
				"frequency": "DAILY",
				"plugin_path": "pgappforge.plugins.fintech.mobile_money.services",
				"service_class": "MobileMoneyService",
				"method_name": "run_eod_reconciliation",
				# None → service resolves to today; avoids hard-coding a date at seed time
				"method_kwargs": {"run_date": None},
			},
			{
				"name": "clubs.monthly_statements",
				"description": "Generate club member monthly statements",
				"frequency": "MONTHLY",
				"plugin_path": "pgappforge.plugins.erp.industry.clubs.services",
				"service_class": "MemberAccountService",
				"method_name": "run_monthly_statements",
			},
		]

		registered = 0
		for job_def in STANDARD_JOBS:
			kwargs = job_def.pop("method_kwargs", {})
			self.register_job(**job_def, tenant_id=tenant_id, session=session, method_kwargs=kwargs)
			registered += 1
		return registered

	# ------------------------------------------------------------------
	# Internal
	# ------------------------------------------------------------------

	def _run_job(self, job: ScheduledJob, tenant_id: str, session: Any) -> dict[str, Any]:
		"""Execute a single scheduled job, update its status, create run log.

		Uses raw sa.update() for status transitions on ScheduledJob (ORM-safe
		because AuditMixin tracks field changes via SessionEvents, not mapper
		events).  The JobRunLog row transitions are also via raw SQL so the
		ImmutableRecordMixin guard is not triggered on a brand-new row that
		has not yet been committed.
		"""
		started_at = _now()

		# Insert run log in RUNNING state
		run_log = JobRunLog(
			id=_uuid4(),
			tenant_id=tenant_id,
			job_id=job.id,
			started_at=started_at,
			status="RUNNING",
		)
		session.add(run_log)

		# Mark job RUNNING to prevent concurrent re-entrant execution
		session.execute(
			sa.update(ScheduledJob)
			.where(ScheduledJob.id == job.id)
			.values(last_run_status="RUNNING")
		)
		session.flush()

		t0 = time.monotonic()
		try:
			mod = importlib.import_module(job.plugin_path)
			cls = getattr(mod, job.service_class)
			svc = cls()
			method = getattr(svc, job.method_name)

			# Inject session / tenant_id only when the method signature accepts them
			kwargs: dict[str, Any] = dict(job.method_kwargs or {})
			sig = inspect.signature(method)
			if "session" in sig.parameters:
				kwargs["session"] = session
			if "tenant_id" in sig.parameters:
				kwargs["tenant_id"] = tenant_id

			result = method(**kwargs)
			duration_ms = int((time.monotonic() - t0) * 1000)

			next_run = self._compute_next_run(job)
			session.execute(
				sa.update(ScheduledJob)
				.where(ScheduledJob.id == job.id)
				.values(
					last_run_at=started_at,
					last_run_status="SUCCESS",
					last_run_error=None,
					next_run_at=next_run,
					run_count=ScheduledJob.run_count + 1,
				)
			)
			session.execute(
				sa.update(JobRunLog)
				.where(JobRunLog.id == run_log.id)
				.values(
					finished_at=_now(),
					status="SUCCESS",
					duration_ms=duration_ms,
					records_processed=result if isinstance(result, int) else None,
				)
			)
			session.flush()

			log.info(
				"SchedulerService: job %r SUCCESS in %dms (next=%s)",
				job.name, duration_ms, next_run.isoformat(),
			)
			return {"job": job.name, "status": "SUCCESS", "duration_ms": duration_ms}

		except Exception as exc:
			duration_ms = int((time.monotonic() - t0) * 1000)
			err = str(exc)[:500]

			session.execute(
				sa.update(ScheduledJob)
				.where(ScheduledJob.id == job.id)
				.values(
					last_run_at=started_at,
					last_run_status="FAILED",
					last_run_error=err,
					failure_count=ScheduledJob.failure_count + 1,
				)
			)
			session.execute(
				sa.update(JobRunLog)
				.where(JobRunLog.id == run_log.id)
				.values(
					finished_at=_now(),
					status="FAILED",
					error_message=err,
					duration_ms=duration_ms,
				)
			)
			session.flush()

			log.error("SchedulerService: job %r FAILED: %s", job.name, err)
			return {"job": job.name, "status": "FAILED", "error": err}

	def _compute_next_run(self, job: ScheduledJob) -> datetime:
		"""Compute the next scheduled run time from now based on job.frequency.

		HOURLY  → now + 1 hour
		DAILY   → next calendar day at 01:00 UTC
		WEEKLY  → now + 7 days
		MONTHLY → first day of next calendar month at 01:00 UTC
		ONCE    → far future (effectively disabled after first run)
		"""
		now = _now()
		freq = (job.frequency or "DAILY").upper()

		if freq == "HOURLY":
			return now + timedelta(hours=1)

		if freq == "DAILY":
			tomorrow = (now + timedelta(days=1)).replace(
				hour=1, minute=0, second=0, microsecond=0
			)
			return tomorrow

		if freq == "WEEKLY":
			return now + timedelta(weeks=1)

		if freq == "MONTHLY":
			if now.month == 12:
				next_year, next_month = now.year + 1, 1
			else:
				next_year, next_month = now.year, now.month + 1
			return now.replace(
				year=next_year, month=next_month, day=1,
				hour=1, minute=0, second=0, microsecond=0,
			)

		# ONCE — schedule so far ahead it effectively never re-runs
		return now.replace(year=now.year + 100)


__all__ = ["BatchSchedulerService"]
