from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import (
	BigInteger,
	Boolean,
	Column,
	Date,
	DateTime,
	ForeignKey,
	Index,
	Numeric,
	Text,
	UniqueConstraint,
	VARCHAR,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from pgappforge.models.sqla import Model
from pgappforge.plugins.audit import AuditMixin

__all__ = [
	"StaffingAgency",
	"ContingentWorker",
	"StatementOfWork",
	"ContingentTimesheet",
]


def _uuid4() -> str:
	return str(uuid.uuid4())


def _now_utc() -> datetime:
	return datetime.now(tz=__import__("datetime").timezone.utc)


class StaffingAgency(AuditMixin, Model):
	"""External staffing agencies that supply contingent workers."""
	__tablename__ = "cw_agency"

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
		nullable=False,
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False)

	name = Column(VARCHAR(300), nullable=False)
	contact_email = Column(VARCHAR(320), nullable=True)
	contact_phone = Column(VARCHAR(30), nullable=True)
	default_markup_pct = Column(Numeric(6, 2), nullable=False, default=0)
	is_active = Column(Boolean, nullable=False, default=True)
	contract_ref = Column(VARCHAR(100), nullable=True)

	workers = relationship(
		"ContingentWorker",
		back_populates="agency",
		lazy="select",
	)

	__table_args__ = (
		Index("ix_cw_agency_tenant_active", "tenant_id", "is_active"),
	)


class ContingentWorker(AuditMixin, Model):
	"""
	A non-permanent worker engaged via an agency, as SOW, or directly.

	worker_type: CONTRACTOR / FREELANCER / SOW / TEMP / INTERN
	rate_unit:   HOURLY / DAILY / WEEKLY / FIXED
	status:      ACTIVE / COMPLETED / CANCELLED
	"""
	__tablename__ = "cw_worker"

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
		nullable=False,
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False)

	first_name = Column(VARCHAR(100), nullable=False)
	last_name = Column(VARCHAR(100), nullable=False)
	email = Column(VARCHAR(320), nullable=True)
	# CONTRACTOR / FREELANCER / SOW / TEMP / INTERN
	worker_type = Column(VARCHAR(20), nullable=False)
	agency_id = Column(
		UUID(as_uuid=False),
		ForeignKey("cw_agency.id", ondelete="SET NULL"),
		nullable=True,
	)
	rate_cents = Column(BigInteger, nullable=False)
	# HOURLY / DAILY / WEEKLY / FIXED
	rate_unit = Column(VARCHAR(20), nullable=False, default="DAILY")
	start_date = Column(Date, nullable=True)
	end_date = Column(Date, nullable=True)
	# soft FK to org entity
	entity_id = Column(VARCHAR(50), nullable=True)
	# ACTIVE / COMPLETED / CANCELLED
	status = Column(VARCHAR(20), nullable=False, default="ACTIVE")

	agency = relationship("StaffingAgency", back_populates="workers", lazy="select")
	sows = relationship(
		"StatementOfWork",
		back_populates="worker",
		cascade="all, delete-orphan",
		lazy="select",
	)
	timesheets = relationship(
		"ContingentTimesheet",
		back_populates="worker",
		cascade="all, delete-orphan",
		lazy="select",
	)

	__table_args__ = (
		Index("ix_cw_worker_tenant_status", "tenant_id", "status"),
		Index("ix_cw_worker_entity_tenant", "entity_id", "tenant_id"),
	)


class StatementOfWork(AuditMixin, Model):
	"""
	A scoped deliverable engagement with a contingent worker.

	milestones JSONB: [{title, due_date, amount_cents, status}, ...]
	status: DRAFT / ACTIVE / COMPLETED / CANCELLED
	"""
	__tablename__ = "cw_sow"

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
		nullable=False,
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False)

	worker_id = Column(
		UUID(as_uuid=False),
		ForeignKey("cw_worker.id", ondelete="CASCADE"),
		nullable=False,
	)
	title = Column(VARCHAR(300), nullable=False)
	description = Column(Text, nullable=True)
	budget_cents = Column(BigInteger, nullable=False)
	actual_spend_cents = Column(BigInteger, nullable=False, default=0)
	start_date = Column(Date, nullable=False)
	end_date = Column(Date, nullable=False)
	# DRAFT / ACTIVE / COMPLETED / CANCELLED
	status = Column(VARCHAR(20), nullable=False, default="DRAFT")
	# [{title, due_date, amount_cents, status}]
	milestones = Column(JSONB, nullable=False, default=list)
	deliverables = Column(Text, nullable=True)
	approved_by = Column(VARCHAR(50), nullable=True)

	worker = relationship("ContingentWorker", back_populates="sows", lazy="select")
	timesheets = relationship(
		"ContingentTimesheet",
		back_populates="sow",
		lazy="select",
	)

	__table_args__ = (
		Index("ix_cw_sow_worker_status", "worker_id", "status"),
		Index("ix_cw_sow_tenant_status", "tenant_id", "status"),
	)


class ContingentTimesheet(AuditMixin, Model):
	"""
	Weekly/monthly time record for a contingent worker.

	period: YYYY-MM format
	amount_cents: hours × rate_at_time_cents (computed at submission)
	status: SUBMITTED / APPROVED / REJECTED / PAID
	"""
	__tablename__ = "cw_timesheet"

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
		nullable=False,
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False)

	worker_id = Column(
		UUID(as_uuid=False),
		ForeignKey("cw_worker.id", ondelete="CASCADE"),
		nullable=False,
	)
	sow_id = Column(
		UUID(as_uuid=False),
		ForeignKey("cw_sow.id", ondelete="SET NULL"),
		nullable=True,
	)
	# YYYY-MM
	period = Column(VARCHAR(20), nullable=False)
	hours = Column(Numeric(8, 2), nullable=False)
	# snapshot of worker.rate_cents at time of submission
	rate_at_time_cents = Column(BigInteger, nullable=False)
	# hours × rate_at_time_cents, rounded HALF_UP
	amount_cents = Column(BigInteger, nullable=False)
	# SUBMITTED / APPROVED / REJECTED / PAID
	status = Column(VARCHAR(20), nullable=False, default="SUBMITTED")
	approved_by = Column(VARCHAR(50), nullable=True)
	approved_at = Column(DateTime(timezone=True), nullable=True)
	notes = Column(Text, nullable=True)

	worker = relationship("ContingentWorker", back_populates="timesheets", lazy="select")
	sow = relationship("StatementOfWork", back_populates="timesheets", lazy="select")

	__table_args__ = (
		UniqueConstraint(
			"worker_id", "sow_id", "period",
			name="uq_cw_timesheet_worker_sow_period",
		),
		Index("ix_cw_timesheet_worker_period", "worker_id", "period"),
		Index("ix_cw_timesheet_tenant_status", "tenant_id", "status"),
	)
