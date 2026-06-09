"""
pgappforge/plugins/erp/industry/real_estate/property_management/models.py

SQLAlchemy models for the Property Management sub-plugin.

Design rules:
  - All PKs: UUID v4, server_default=gen_random_uuid()
  - All timestamps: TIMESTAMPTZ DEFAULT NOW()
  - All models: tenant_id UUID NOT NULL
  - Monetary amounts: INTEGER cents ONLY (BigInteger)
  - Statuses as VARCHAR strings

Table name convention: pm_<entity>
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any

import sqlalchemy as sa
from sqlalchemy import (
	BigInteger,
	Boolean,
	Column,
	Date,
	DateTime,
	ForeignKey,
	Index,
	Integer,
	Numeric,
	String,
	Text,
	UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from pgappforge.models.sqla import Model
from pgappforge.plugins.audit import AuditMixin


def _uuid4() -> str:
	return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Enumerations (documentation only — enforced at service layer)
# ---------------------------------------------------------------------------

UNIT_STATUS       = ("VACANT", "OCCUPIED", "MAINTENANCE", "OFFLINE")
LEASE_TYPE        = ("FIXED", "MONTH_TO_MONTH")
LEASE_STATUS      = ("DRAFT", "ACTIVE", "EXPIRED", "TERMINATED")
ESCALATION_TYPE   = ("NONE", "FIXED_PCT", "CPI")
PAYMENT_STATUS    = ("PENDING", "PAID", "LATE", "PARTIAL", "WAIVED")
PAYMENT_METHOD    = ("MPESA", "BANK", "CASH", "CARD")
MAINTENANCE_CAT   = ("PLUMBING", "ELECTRICAL", "HVAC", "STRUCTURAL", "APPLIANCE", "OTHER")
MAINTENANCE_PRI   = ("LOW", "MEDIUM", "HIGH", "EMERGENCY")
MAINTENANCE_ST    = ("OPEN", "ASSIGNED", "IN_PROGRESS", "RESOLVED", "CLOSED")
WORK_ORDER_STATUS = ("PENDING", "SCHEDULED", "IN_PROGRESS", "COMPLETED", "CANCELLED")
MOVE_TYPE         = ("IN", "OUT")
RENEWAL_STATUS    = ("SENT", "ACCEPTED", "DECLINED", "EXPIRED")


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class PropertyUnit(AuditMixin, Model):
	"""A rentable unit within a property (apartment, office, etc.)."""

	__tablename__ = "pm_unit"

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		server_default=sa.text("gen_random_uuid()"),
		default=_uuid4,
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	property_id = Column(
		UUID(as_uuid=False),
		ForeignKey("re_property.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)
	unit_number = Column(String(20), nullable=False)
	floor       = Column(Integer, nullable=True)
	sqft        = Column(Integer, nullable=True)
	bedrooms    = Column(Integer, nullable=True)
	bathrooms   = Column(Numeric(4, 1), nullable=True)
	status      = Column(String(20), nullable=False, default="VACANT", server_default="VACANT")

	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		server_default=sa.text("NOW()"),
		default=lambda: datetime.now(timezone.utc),
	)
	updated_at = Column(
		DateTime(timezone=True),
		nullable=False,
		server_default=sa.text("NOW()"),
		default=lambda: datetime.now(timezone.utc),
		onupdate=lambda: datetime.now(timezone.utc),
	)

	# Relationships
	leases               = relationship("TenantLease", back_populates="unit", lazy="dynamic")
	maintenance_requests = relationship("MaintenanceRequest", back_populates="unit", lazy="dynamic")

	__table_args__ = (
		UniqueConstraint("property_id", "unit_number", name="uq_pm_unit_property_number"),
		Index("ix_pm_unit_tenant_status", "tenant_id", "status"),
	)

	def __repr__(self) -> str:
		return f"<PropertyUnit {self.unit_number} status={self.status}>"


class TenantLease(AuditMixin, Model):
	"""Lease agreement between a tenant party and a landlord for a unit."""

	__tablename__ = "pm_tenant_lease"

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		server_default=sa.text("gen_random_uuid()"),
		default=_uuid4,
	)
	tenant_id       = Column(UUID(as_uuid=False), nullable=False, index=True)
	unit_id         = Column(
		UUID(as_uuid=False),
		ForeignKey("pm_unit.id", ondelete="RESTRICT"),
		nullable=False,
		index=True,
	)
	# Soft FK to foundation.Party
	tenant_party_id = Column(UUID(as_uuid=False), nullable=True, index=True)
	landlord_id     = Column(UUID(as_uuid=False), nullable=True)

	lease_start = Column(Date, nullable=False)
	lease_end   = Column(Date, nullable=True)  # NULL = month-to-month

	monthly_rent_cents      = Column(BigInteger, nullable=False)
	security_deposit_cents  = Column(BigInteger, nullable=False, default=0, server_default="0")

	lease_type      = Column(String(20), nullable=False, default="FIXED",       server_default="FIXED")
	escalation_type = Column(String(10), nullable=False, default="NONE",        server_default="NONE")
	escalation_pct  = Column(Numeric(5, 2), nullable=True)
	status          = Column(String(15), nullable=False, default="DRAFT",       server_default="DRAFT")
	renewal_option  = Column(Boolean, nullable=False, default=False,            server_default="false")

	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		server_default=sa.text("NOW()"),
		default=lambda: datetime.now(timezone.utc),
	)
	updated_at = Column(
		DateTime(timezone=True),
		nullable=False,
		server_default=sa.text("NOW()"),
		default=lambda: datetime.now(timezone.utc),
		onupdate=lambda: datetime.now(timezone.utc),
	)

	# Relationships
	unit             = relationship("PropertyUnit", back_populates="leases")
	rent_payments    = relationship("RentPayment",  back_populates="lease", lazy="dynamic")
	late_fees        = relationship("LateFeeRecord", back_populates="lease", lazy="dynamic")
	move_records     = relationship("MoveRecord",    back_populates="lease", lazy="dynamic")
	renewal_offers   = relationship("LeaseRenewalOffer", back_populates="lease", lazy="dynamic")

	__table_args__ = (
		Index("ix_pm_lease_tenant_status", "tenant_id", "status"),
		Index("ix_pm_lease_unit_active",   "unit_id", "status"),
	)

	def __repr__(self) -> str:
		return f"<TenantLease unit={self.unit_id} status={self.status}>"


class RentPayment(Model):
	"""Record of a rent payment for a specific lease period."""

	__tablename__ = "pm_rent_payment"

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		server_default=sa.text("gen_random_uuid()"),
		default=_uuid4,
	)
	tenant_id    = Column(UUID(as_uuid=False), nullable=False, index=True)
	lease_id     = Column(
		UUID(as_uuid=False),
		ForeignKey("pm_tenant_lease.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)
	period_month    = Column(String(7),  nullable=False)           # "YYYY-MM"
	due_date        = Column(Date,       nullable=False)
	paid_date       = Column(Date,       nullable=True)
	amount_cents    = Column(BigInteger, nullable=False)
	status          = Column(String(10), nullable=False, default="PENDING", server_default="PENDING")
	payment_method  = Column(String(20), nullable=True)
	reference       = Column(String(100), nullable=True)

	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		server_default=sa.text("NOW()"),
		default=lambda: datetime.now(timezone.utc),
	)

	# Relationships
	lease = relationship("TenantLease", back_populates="rent_payments")

	__table_args__ = (
		Index("ix_pm_payment_lease_period", "lease_id", "period_month"),
		Index("ix_pm_payment_tenant_status", "tenant_id", "status"),
	)

	def __repr__(self) -> str:
		return f"<RentPayment lease={self.lease_id} period={self.period_month} status={self.status}>"


class LateFeeRecord(Model):
	"""Late fee applied to a lease for a missed/partial payment period."""

	__tablename__ = "pm_late_fee"

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		server_default=sa.text("gen_random_uuid()"),
		default=_uuid4,
	)
	tenant_id    = Column(UUID(as_uuid=False), nullable=False, index=True)
	lease_id     = Column(
		UUID(as_uuid=False),
		ForeignKey("pm_tenant_lease.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)
	period_month = Column(String(7),  nullable=False)
	fee_cents    = Column(BigInteger, nullable=False)
	applied_at   = Column(
		DateTime(timezone=True),
		nullable=False,
		server_default=sa.text("NOW()"),
		default=lambda: datetime.now(timezone.utc),
	)
	waived    = Column(Boolean, nullable=False, default=False, server_default="false")
	waived_by = Column(UUID(as_uuid=False), nullable=True)

	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		server_default=sa.text("NOW()"),
		default=lambda: datetime.now(timezone.utc),
	)

	# Relationships
	lease = relationship("TenantLease", back_populates="late_fees")

	__table_args__ = (
		UniqueConstraint("lease_id", "period_month", name="uq_pm_late_fee_lease_period"),
		Index("ix_pm_late_fee_tenant", "tenant_id"),
	)

	def __repr__(self) -> str:
		return f"<LateFeeRecord lease={self.lease_id} period={self.period_month} cents={self.fee_cents}>"


class MaintenanceRequest(AuditMixin, Model):
	"""Tenant or manager-submitted maintenance request for a unit."""

	__tablename__ = "pm_maintenance_request"

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		server_default=sa.text("gen_random_uuid()"),
		default=_uuid4,
	)
	tenant_id   = Column(UUID(as_uuid=False), nullable=False, index=True)
	unit_id     = Column(
		UUID(as_uuid=False),
		ForeignKey("pm_unit.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)
	reported_by = Column(UUID(as_uuid=False), nullable=True)

	category    = Column(String(50), nullable=False)
	description = Column(Text,       nullable=False)
	priority    = Column(String(10), nullable=False, default="MEDIUM", server_default="MEDIUM")
	status      = Column(String(15), nullable=False, default="OPEN",   server_default="OPEN")

	estimated_cost_cents = Column(BigInteger, nullable=True)
	actual_cost_cents    = Column(BigInteger, nullable=True)
	resolved_at          = Column(DateTime(timezone=True), nullable=True)

	photos = Column(JSONB, nullable=False, default=list, server_default="[]")
	# photos schema: [{url: str, caption: str}]

	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		server_default=sa.text("NOW()"),
		default=lambda: datetime.now(timezone.utc),
	)
	updated_at = Column(
		DateTime(timezone=True),
		nullable=False,
		server_default=sa.text("NOW()"),
		default=lambda: datetime.now(timezone.utc),
		onupdate=lambda: datetime.now(timezone.utc),
	)

	# Relationships
	unit        = relationship("PropertyUnit", back_populates="maintenance_requests")
	work_orders = relationship("WorkOrder", back_populates="request", lazy="dynamic")

	__table_args__ = (
		Index("ix_pm_maint_tenant_status",   "tenant_id", "status"),
		Index("ix_pm_maint_unit_priority",   "unit_id",   "priority"),
	)

	def __repr__(self) -> str:
		return f"<MaintenanceRequest unit={self.unit_id} cat={self.category} pri={self.priority} status={self.status}>"


class WorkOrder(Model):
	"""Vendor work order generated from a maintenance request."""

	__tablename__ = "pm_work_order"

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		server_default=sa.text("gen_random_uuid()"),
		default=_uuid4,
	)
	tenant_id  = Column(UUID(as_uuid=False), nullable=False, index=True)
	request_id = Column(
		UUID(as_uuid=False),
		ForeignKey("pm_maintenance_request.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)
	vendor_id   = Column(UUID(as_uuid=False), nullable=True)

	work_description  = Column(Text,       nullable=False)
	scheduled_date    = Column(Date,        nullable=True)
	completed_date    = Column(Date,        nullable=True)
	quoted_cost_cents = Column(BigInteger,  nullable=True)
	actual_cost_cents = Column(BigInteger,  nullable=True)
	status            = Column(String(15),  nullable=False, default="PENDING", server_default="PENDING")
	notes             = Column(Text,        nullable=True)

	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		server_default=sa.text("NOW()"),
		default=lambda: datetime.now(timezone.utc),
	)

	# Relationships
	request = relationship("MaintenanceRequest", back_populates="work_orders")

	__table_args__ = (
		Index("ix_pm_wo_tenant_status", "tenant_id", "status"),
	)

	def __repr__(self) -> str:
		return f"<WorkOrder request={self.request_id} status={self.status}>"


class MoveRecord(Model):
	"""Record of a tenant move-in or move-out event."""

	__tablename__ = "pm_move_record"

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		server_default=sa.text("gen_random_uuid()"),
		default=_uuid4,
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	lease_id  = Column(
		UUID(as_uuid=False),
		ForeignKey("pm_tenant_lease.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)
	move_type      = Column(String(3),   nullable=False)           # IN / OUT
	scheduled_date = Column(Date,        nullable=False)
	completed_date = Column(Date,        nullable=True)

	# checklist schema: [{item: str, checked: bool, notes: str|null}]
	checklist    = Column(JSONB, nullable=False, default=list, server_default="[]")
	completed_by = Column(UUID(as_uuid=False), nullable=True)

	condition_notes                  = Column(Text,       nullable=True)
	security_deposit_returned_cents  = Column(BigInteger, nullable=True)

	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		server_default=sa.text("NOW()"),
		default=lambda: datetime.now(timezone.utc),
	)

	# Relationships
	lease = relationship("TenantLease", back_populates="move_records")

	__table_args__ = (
		Index("ix_pm_move_tenant_type", "tenant_id", "move_type"),
	)

	def __repr__(self) -> str:
		return f"<MoveRecord lease={self.lease_id} type={self.move_type} scheduled={self.scheduled_date}>"


class LeaseRenewalOffer(Model):
	"""Renewal offer sent to a tenant before their lease expires."""

	__tablename__ = "pm_lease_renewal"

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		server_default=sa.text("gen_random_uuid()"),
		default=_uuid4,
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	lease_id  = Column(
		UUID(as_uuid=False),
		ForeignKey("pm_tenant_lease.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)
	new_rent_cents   = Column(BigInteger, nullable=False)
	new_lease_start  = Column(Date,       nullable=False)
	new_lease_end    = Column(Date,       nullable=True)

	offered_at  = Column(
		DateTime(timezone=True),
		nullable=False,
		server_default=sa.text("NOW()"),
		default=lambda: datetime.now(timezone.utc),
	)
	expires_at  = Column(DateTime(timezone=True), nullable=False)
	status      = Column(String(10), nullable=False, default="SENT", server_default="SENT")
	notes       = Column(Text, nullable=True)

	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		server_default=sa.text("NOW()"),
		default=lambda: datetime.now(timezone.utc),
	)

	# Relationships
	lease = relationship("TenantLease", back_populates="renewal_offers")

	__table_args__ = (
		Index("ix_pm_renewal_lease_status", "lease_id", "status"),
	)

	def __repr__(self) -> str:
		return f"<LeaseRenewalOffer lease={self.lease_id} status={self.status}>"


__all__ = [
	"PropertyUnit",
	"TenantLease",
	"RentPayment",
	"LateFeeRecord",
	"MaintenanceRequest",
	"WorkOrder",
	"MoveRecord",
	"LeaseRenewalOffer",
]
