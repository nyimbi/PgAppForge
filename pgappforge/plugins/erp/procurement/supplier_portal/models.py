"""
pgappforge/plugins/erp/procurement/supplier_portal/models.py

SQLAlchemy 2.x models for the Supplier Portal plugin.

Design invariants:
  - ALL PKs: UUID(as_uuid=False) — gen_random_uuid() server default + Python default
  - ALL timestamps: DateTime(timezone=True) / TIMESTAMPTZ
  - Monetary amounts: BigInteger cents (never Numeric/float for money)
  - ALL models: tenant_id UUID NOT NULL
  - AuditMixin on every mutable entity
  - Table prefix: sup_
  - JSONB for structured arrays (PostgreSQL only)
  - Composite indexes for tenant + status hot paths

KYC statuses: PENDING / APPROVED / REJECTED / SUSPENDED
Primary categories: GOODS / SERVICES / WORKS
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import sqlalchemy as sa
from sqlalchemy import (
	Boolean,
	CheckConstraint,
	Column,
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
# Enum constant sets
# ---------------------------------------------------------------------------

KYC_STATUSES = {"PENDING", "APPROVED", "REJECTED", "SUSPENDED"}
PRIMARY_CATEGORIES = {"GOODS", "SERVICES", "WORKS"}


# ---------------------------------------------------------------------------
# SupplierProfile
# ---------------------------------------------------------------------------

class SupplierProfile(AuditMixin, Model):
	"""Registered supplier / vendor record.

	supplier_ref is auto-generated as SUP-YYYYMMDD-NNNNN, unique per tenant.
	kyc_documents is a JSONB array: [{doc_type, url, uploaded_at}].
	bank_verified is set True by verify_bank_details(); bank_verified_at records when.
	overall_score is a rolling average of SupplierPerformanceCard.composite_score.
	is_preferred is a manual flag set by procurement staff.
	"""

	__allow_unmapped__ = True
	__tablename__ = "sup_profile"
	__table_args__ = (
		UniqueConstraint("tenant_id", "supplier_ref", name="uq_sup_profile_tenant_ref"),
		CheckConstraint(
			"kyc_status IN ('PENDING','APPROVED','REJECTED','SUSPENDED')",
			name="ck_sup_profile_kyc_status",
		),
		Index("ix_sup_profile_tenant_kyc", "tenant_id", "kyc_status"),
		Index("ix_sup_profile_tenant_category", "tenant_id", "primary_category"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False)

	company_name = Column(String(300), nullable=False)
	supplier_ref = Column(String(50), nullable=False, comment="Auto-generated, unique per tenant")
	company_reg_number = Column(String(100), nullable=True)
	tax_id = Column(String(100), nullable=True)
	country_code = Column(String(3), nullable=False)
	contact_email = Column(String(320), nullable=False)
	contact_phone = Column(String(30), nullable=True)
	primary_category = Column(
		String(100), nullable=True,
		comment="GOODS / SERVICES / WORKS — primary commodity category",
	)

	# KYC
	kyc_status = Column(String(20), nullable=False, default="PENDING")
	kyc_approved_by = Column(String(50), nullable=True, comment="Advisory FK to user/employee")
	kyc_approved_at = Column(DateTime(timezone=True), nullable=True)
	kyc_documents = Column(
		JSONB, nullable=False,
		server_default=sa.text("'[]'::jsonb"),
		default=list,
		comment="[{doc_type, url, uploaded_at}]",
	)

	# Bank details
	bank_name = Column(String(200), nullable=True)
	bank_account_number = Column(String(100), nullable=True)
	bank_branch = Column(String(200), nullable=True)
	bank_swift = Column(String(20), nullable=True)
	bank_verified = Column(Boolean, nullable=False, default=False)
	bank_verified_at = Column(DateTime(timezone=True), nullable=True)

	# Scoring
	overall_score = Column(
		Numeric(6, 2), nullable=True,
		comment="Rolling average of SupplierPerformanceCard.composite_score (0-100)",
	)
	is_preferred = Column(Boolean, nullable=False, default=False)

	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	updated_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		onupdate=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	performance_cards: list[SupplierPerformanceCard] = relationship(
		"SupplierPerformanceCard",
		back_populates="supplier",
		lazy="select",
		cascade="all, delete-orphan",
	)

	def __repr__(self) -> str:
		return f"<SupplierProfile {self.supplier_ref} [{self.kyc_status}] {self.company_name!r}>"


# ---------------------------------------------------------------------------
# SupplierPerformanceCard
# ---------------------------------------------------------------------------

class SupplierPerformanceCard(AuditMixin, Model):
	"""Quarterly/periodic performance scorecard for a supplier.

	UniqueConstraint(supplier_id, period) — one card per supplier per period.
	composite_score = 0.4*on_time + 0.3*quality + 0.2*invoice_accuracy + 0.1*responsiveness.
	po_count / grn_count provide the data sample size for the period.
	"""

	__allow_unmapped__ = True
	__tablename__ = "sup_performance"
	__table_args__ = (
		UniqueConstraint("supplier_id", "period", name="uq_sup_perf_supplier_period"),
		Index(
			"ix_sup_perf_tenant_period_score",
			"tenant_id", "period",
			# PostgreSQL DESC index for composite_score stored ascending;
			# descending ordering handled at query time
		),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False)
	supplier_id = Column(
		UUID(as_uuid=False),
		ForeignKey("sup_profile.id", ondelete="CASCADE"),
		nullable=False,
	)

	period = Column(String(20), nullable=False, comment="e.g. '2025-Q1' or '2025-05'")

	on_time_delivery_pct = Column(Numeric(6, 2), nullable=False, default=0, comment="0-100")
	quality_acceptance_pct = Column(Numeric(6, 2), nullable=False, default=0, comment="0-100")
	invoice_accuracy_pct = Column(Numeric(6, 2), nullable=False, default=0, comment="0-100")
	responsiveness_score = Column(Numeric(6, 2), nullable=False, default=0, comment="0-100")
	composite_score = Column(
		Numeric(6, 2), nullable=False, default=0,
		comment="0.4*on_time + 0.3*quality + 0.2*invoice_accuracy + 0.1*responsiveness",
	)

	po_count = Column(Integer, nullable=False, default=0, comment="PO lines evaluated in this period")
	grn_count = Column(Integer, nullable=False, default=0, comment="GRN lines evaluated in this period")

	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	updated_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		onupdate=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	supplier: SupplierProfile = relationship(
		"SupplierProfile", back_populates="performance_cards", lazy="select"
	)

	def __repr__(self) -> str:
		return (
			f"<SupplierPerformanceCard supplier={self.supplier_id} "
			f"period={self.period} score={self.composite_score}>"
		)


__all__ = [
	"SupplierProfile",
	"SupplierPerformanceCard",
	# enum sets
	"KYC_STATUSES",
	"PRIMARY_CATEGORIES",
]
