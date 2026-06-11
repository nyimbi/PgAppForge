"""
pgappforge/plugins/erp/platform/scheduler/models.py

SQLAlchemy models for the Batch Scheduler plugin.

Table prefix: plat_
PostgreSQL ONLY — JSONB method_kwargs, timezone-aware DateTimes.

ScheduledJob  — persistent job definition with last-run metadata.
JobRunLog     — append-only execution record per job invocation.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import sqlalchemy as sa
from sqlalchemy import (
	Boolean,
	Column,
	DateTime,
	ForeignKey,
	Index,
	Integer,
	String,
	Text,
	UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from pgappforge.models.sqla import Model
from pgappforge.plugins.audit import AuditMixin
from pgappforge.plugins.erp.foundation.commons import ImmutableRecordMixin


def _uuid4() -> str:
	return str(uuid.uuid4())


def _now() -> datetime:
	return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# ScheduledJob
# ---------------------------------------------------------------------------

class ScheduledJob(AuditMixin, Model):
	"""Persistent scheduled-job definition.

	Stores what to run (plugin_path / service_class / method_name), how often
	(frequency / cron_expression), and a running summary of execution history
	(last_run_at, last_run_status, run_count, failure_count).

	The scheduler calls run_due_jobs() which selects rows where
	  is_active = TRUE AND (next_run_at IS NULL OR next_run_at <= now())
	and skips rows already RUNNING (guard against concurrent ticks).
	"""

	__tablename__ = "plat_scheduled_job"

	id = Column(String(36), primary_key=True, default=_uuid4)
	tenant_id = Column(String(36), nullable=False, index=True)

	# Human-readable dotted key — acts as idempotent registration key per tenant
	name = Column(String(100), nullable=False)
	description = Column(String(300), nullable=True)

	# DAILY / WEEKLY / MONTHLY / HOURLY / ONCE
	frequency = Column(String(10), nullable=False)
	# Optional cron expression for display / future cron-aware scheduler
	cron_expression = Column(String(50), nullable=True)

	# Fully-qualified module + class + method that the scheduler will invoke
	plugin_path = Column(String(200), nullable=False)
	service_class = Column(String(100), nullable=False)
	method_name = Column(String(100), nullable=False)
	# Extra kwargs forwarded to method (session + tenant_id injected automatically)
	method_kwargs = Column(JSONB, nullable=False, default=dict)

	is_active = Column(Boolean, nullable=False, default=True)

	# Runtime bookkeeping — updated by BatchSchedulerService after each run
	last_run_at = Column(DateTime(timezone=True), nullable=True)
	last_run_status = Column(String(10), nullable=True)   # SUCCESS / FAILED / RUNNING
	last_run_error = Column(Text, nullable=True)
	next_run_at = Column(DateTime(timezone=True), nullable=True)

	run_count = Column(Integer, nullable=False, default=0)
	failure_count = Column(Integer, nullable=False, default=0)

	# Relationships
	run_logs = relationship(
		"JobRunLog",
		back_populates="job",
		lazy="select",
		cascade="all, delete-orphan",
	)

	__table_args__ = (
		UniqueConstraint("tenant_id", "name", name="uq_plat_job_tenant_name"),
		Index("ix_plat_job_tenant_active_next", "tenant_id", "is_active", "next_run_at"),
	)

	def __repr__(self) -> str:
		return (
			f"<ScheduledJob {self.name!r} freq={self.frequency} "
			f"status={self.last_run_status!r}>"
		)


# ---------------------------------------------------------------------------
# JobRunLog — append-only execution record
# ---------------------------------------------------------------------------

class JobRunLog(ImmutableRecordMixin, Model):
	"""One row per job invocation — insert-only ledger.

	ImmutableRecordMixin blocks any ORM UPDATE after insertion.  Status
	transitions are applied via ``sa.update()`` (raw SQL) within
	BatchSchedulerService._run_job() before the ORM session is flushed,
	which is safe because the row was just added in the same unit of work
	and has not yet been committed.
	"""

	__tablename__ = "plat_job_run_log"

	id = Column(String(36), primary_key=True, default=_uuid4)
	tenant_id = Column(String(36), nullable=False, index=True)

	job_id = Column(
		String(36),
		ForeignKey("plat_scheduled_job.id", ondelete="CASCADE"),
		nullable=False,
	)

	started_at = Column(DateTime(timezone=True), nullable=False)
	finished_at = Column(DateTime(timezone=True), nullable=True)

	status = Column(String(10), nullable=False)      # RUNNING / SUCCESS / FAILED
	records_processed = Column(Integer, nullable=True)
	error_message = Column(Text, nullable=True)
	duration_ms = Column(Integer, nullable=True)

	# Relationships
	job = relationship("ScheduledJob", back_populates="run_logs", lazy="select")

	__table_args__ = (
		Index("ix_plat_run_log_job_started", "job_id", "started_at"),
		Index("ix_plat_run_log_tenant_status", "tenant_id", "status"),
	)

	def __repr__(self) -> str:
		return (
			f"<JobRunLog job={self.job_id} status={self.status!r} "
			f"started={self.started_at}>"
		)


# Register immutability guard — raises RuntimeError on any ORM before_update
JobRunLog._register_immutability()


__all__ = ["ScheduledJob", "JobRunLog"]
