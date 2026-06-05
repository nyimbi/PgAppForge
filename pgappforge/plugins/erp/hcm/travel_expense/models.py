"""
pgappforge/plugins/erp/hcm/travel_expense/models.py

SQLAlchemy models for the HCM Travel & Expense plugin.

Design invariants:
  - ALL PKs: UUID v4 string — gen_random_uuid() server default
  - ALL timestamps: DateTime(timezone=True) / TIMESTAMPTZ DEFAULT NOW()
  - ALL monetary amounts: Integer cents (NEVER Numeric/float for money)
  - ALL models: tenant_id UUID NOT NULL + AuditMixin
  - lazy='select' throughout (SA 2.x)
  - JSONB for semi-structured metadata
  - Composite indexes for tenant + status hot paths

Table prefix: te_
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
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
# ExpensePolicy
# ---------------------------------------------------------------------------

class ExpensePolicy(AuditMixin, Model):
	"""Per-category / per-grade expense policy limits.

	policy_type controls how the limit is enforced:
	  CATEGORY_LIMIT  — single_limit_cents cap per expense line
	  DAILY_LIMIT     — single_limit_cents cap per day across category
	  PER_DIEM        — references PerDiemRate table (limit from rates)
	  MILEAGE         — per-km rate; single_limit_cents = max km × rate

	grade_code=None means policy applies to ALL grades (catch-all).
	"""

	__allow_unmapped__ = True
	__tablename__ = "te_expense_policy"
	__table_args__ = (
		Index("ix_te_policy_tenant", "tenant_id"),
		Index("ix_te_policy_tenant_active", "tenant_id", "is_active"),
		Index("ix_te_policy_category_grade", "expense_category", "grade_code"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	name = Column(String(120), nullable=False, comment="Human-readable policy name")
	policy_type = Column(
		String(20),
		nullable=False,
		comment="CATEGORY_LIMIT | DAILY_LIMIT | PER_DIEM | MILEAGE",
	)
	grade_code = Column(
		String(20),
		nullable=True,
		comment="Employee grade code this policy targets; NULL = all grades",
	)
	expense_category = Column(
		String(50),
		nullable=False,
		comment="Matches ExpenseLine.expense_category",
	)
	single_limit_cents = Column(
		BigInteger,
		nullable=True,
		comment="Max allowed cents per line (or per day for DAILY_LIMIT)",
	)
	requires_receipt_above_cents = Column(
		BigInteger,
		nullable=False,
		default=0,
		comment="Receipt mandatory when line amount exceeds this threshold",
	)
	requires_approval_above_cents = Column(
		BigInteger,
		nullable=False,
		default=0,
		comment="Manager approval required when line amount exceeds this threshold",
	)
	currency_code = Column(String(3), nullable=False, default="KES")
	is_active = Column(Boolean, nullable=False, default=True)

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

	def __repr__(self) -> str:
		return f"<ExpensePolicy {self.name!r} type={self.policy_type} cat={self.expense_category}>"


# ---------------------------------------------------------------------------
# PerDiemRate
# ---------------------------------------------------------------------------

class PerDiemRate(AuditMixin, Model):
	"""Per diem subsistence rates by country/city and effective date range.

	City-level rows take precedence over country-level rows (NULL city_code).
	to_date=NULL means the rate is open-ended (current).
	All amounts in integer cents of currency_code.
	"""

	__allow_unmapped__ = True
	__tablename__ = "te_per_diem_rate"
	__table_args__ = (
		Index("ix_te_perdiem_tenant", "tenant_id"),
		Index("ix_te_perdiem_country_date", "country_code", "from_date"),
		UniqueConstraint(
			"tenant_id", "country_code", "city_code", "from_date",
			name="uq_te_perdiem_tenant_country_city_from",
		),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	country_code = Column(String(3), nullable=False, comment="ISO 3166-1 alpha-3")
	city_code = Column(
		String(10),
		nullable=True,
		comment="Optional city/zone code; NULL = country-wide rate",
	)
	from_date = Column(Date, nullable=False, comment="Effective from (inclusive)")
	to_date = Column(Date, nullable=True, comment="Effective to (inclusive); NULL = open-ended")

	breakfast_cents = Column(BigInteger, nullable=False, default=0)
	lunch_cents = Column(BigInteger, nullable=False, default=0)
	dinner_cents = Column(BigInteger, nullable=False, default=0)
	accommodation_cents = Column(BigInteger, nullable=False, default=0)
	incidentals_cents = Column(BigInteger, nullable=False, default=0)
	currency_code = Column(String(3), nullable=False, default="KES")

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

	def __repr__(self) -> str:
		return (
			f"<PerDiemRate {self.country_code}/{self.city_code or '*'} "
			f"from={self.from_date}>"
		)


# ---------------------------------------------------------------------------
# ExpenseReport
# ---------------------------------------------------------------------------

class ExpenseReport(AuditMixin, Model):
	"""Employee expense report — header record for a trip or expense claim.

	Lifecycle: DRAFT → SUBMITTED → UNDER_REVIEW → APPROVED → PAID
	           DRAFT | SUBMITTED | UNDER_REVIEW → REJECTED
	           Any non-terminal → CANCELLED

	reimbursement_due_cents is computed on submission:
	  reimbursement_due = total_claimed - advance_received
	  (can be negative if advance exceeds claim — employee owes refund)
	"""

	__allow_unmapped__ = True
	__tablename__ = "te_expense_report"
	__table_args__ = (
		Index("ix_te_report_tenant", "tenant_id"),
		Index("ix_te_report_employee", "employee_id"),
		Index("ix_te_report_tenant_status", "tenant_id", "status"),
		Index("ix_te_report_submitted_at", "submitted_at"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	employee_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	title = Column(String(200), nullable=False, comment="Short descriptive title")
	trip_purpose = Column(Text, nullable=True, comment="Business purpose narrative")
	destination = Column(String(200), nullable=True)
	trip_start = Column(Date, nullable=True)
	trip_end = Column(Date, nullable=True)

	currency_code = Column(String(3), nullable=False, default="KES")
	total_claimed_cents = Column(
		BigInteger, nullable=False, default=0,
		comment="Sum of ExpenseLine.amount_cents (in base currency after FX)",
	)
	total_approved_cents = Column(BigInteger, nullable=False, default=0)
	advance_received_cents = Column(BigInteger, nullable=False, default=0)
	reimbursement_due_cents = Column(
		BigInteger, nullable=False, default=0,
		comment="Computed: total_claimed - advance_received; negative = employee refund",
	)

	status = Column(
		String(20),
		nullable=False,
		default="DRAFT",
		comment="DRAFT | SUBMITTED | UNDER_REVIEW | APPROVED | REJECTED | PAID | CANCELLED",
	)
	submitted_at = Column(DateTime(timezone=True), nullable=True)
	approved_by = Column(UUID(as_uuid=False), nullable=True, comment="User ID of approver")
	approved_at = Column(DateTime(timezone=True), nullable=True)
	paid_at = Column(DateTime(timezone=True), nullable=True)
	payment_ref = Column(String(100), nullable=True, comment="Bank or payment reference")

	metadata_ = Column(
		"metadata",
		JSONB,
		nullable=False,
		default=dict,
		comment="Arbitrary extra fields (attachments list, GL refs, etc.)",
	)

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

	lines: list[ExpenseLine] = relationship(
		"ExpenseLine", back_populates="report", lazy="select",
		cascade="all, delete-orphan",
	)
	advances: list[CashAdvance] = relationship(
		"CashAdvance", foreign_keys="CashAdvance.linked_report_id",
		back_populates="linked_report", lazy="select",
	)

	def __repr__(self) -> str:
		return f"<ExpenseReport {self.id} emp={self.employee_id} status={self.status}>"


# ---------------------------------------------------------------------------
# ExpenseLine
# ---------------------------------------------------------------------------

class ExpenseLine(AuditMixin, Model):
	"""Individual expense line item within an ExpenseReport.

	base_amount_cents = amount_cents × exchange_rate (rounded half-up).
	Amounts are stored in both original and base (report) currency.

	Policy breach fields are populated by ExpenseService.check_policy()
	during submit_report().
	"""

	__allow_unmapped__ = True
	__tablename__ = "te_expense_line"
	__table_args__ = (
		Index("ix_te_line_report", "report_id"),
		Index("ix_te_line_tenant", "tenant_id"),
		Index("ix_te_line_category", "expense_category"),
		Index("ix_te_line_bik", "is_paye_bik"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	report_id = Column(
		UUID(as_uuid=False),
		ForeignKey("te_expense_report.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)

	expense_date = Column(Date, nullable=False)
	expense_category = Column(
		String(30),
		nullable=False,
		comment=(
			"MEALS | ACCOMMODATION | TRANSPORT | MILEAGE | CONFERENCE | "
			"FUEL | ENTERTAINMENT | COMMUNICATION | OTHER"
		),
	)
	description = Column(String(500), nullable=False)
	merchant_name = Column(String(200), nullable=True)

	amount_cents = Column(
		BigInteger, nullable=False,
		comment="Amount in original (line) currency",
	)
	currency_code = Column(String(3), nullable=False, default="KES")
	exchange_rate = Column(
		Numeric(12, 6),
		nullable=False,
		default=1,
		comment="FX rate to report base currency (1.0 if same currency)",
	)
	base_amount_cents = Column(
		BigInteger, nullable=False,
		comment="amount_cents × exchange_rate in report base currency",
	)

	is_billable_to_client = Column(Boolean, nullable=False, default=False)
	project_id = Column(UUID(as_uuid=False), nullable=True, index=True)

	is_paye_bik = Column(
		Boolean, nullable=False, default=False,
		comment="True when this benefit-in-kind must flow to payroll PAYE",
	)
	receipt_url = Column(String(500), nullable=True, comment="Storage URL of attached receipt")

	policy_breach = Column(Boolean, nullable=False, default=False)
	breach_reason = Column(Text, nullable=True)
	approved_amount_cents = Column(
		BigInteger, nullable=True,
		comment="Approver override; NULL means full amount approved",
	)

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

	report: ExpenseReport = relationship("ExpenseReport", back_populates="lines", lazy="select")

	def __repr__(self) -> str:
		return (
			f"<ExpenseLine {self.id} cat={self.expense_category} "
			f"amt={self.amount_cents} {self.currency_code}>"
		)


# ---------------------------------------------------------------------------
# CashAdvance
# ---------------------------------------------------------------------------

class CashAdvance(AuditMixin, Model):
	"""Cash advance request and lifecycle tracking.

	outstanding_cents starts at amount_cents on disbursement.
	settle_advance() sets outstanding_cents to 0 (or residual if overspent).

	Status lifecycle:
	  REQUESTED → APPROVED → DISBURSED → SETTLED
	  REQUESTED | APPROVED → CANCELLED
	"""

	__allow_unmapped__ = True
	__tablename__ = "te_cash_advance"
	__table_args__ = (
		Index("ix_te_advance_tenant", "tenant_id"),
		Index("ix_te_advance_employee", "employee_id"),
		Index("ix_te_advance_status", "status"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	employee_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	request_date = Column(Date, nullable=False)
	trip_purpose = Column(Text, nullable=False)
	amount_cents = Column(BigInteger, nullable=False)
	currency_code = Column(String(3), nullable=False, default="KES")

	status = Column(
		String(20),
		nullable=False,
		default="REQUESTED",
		comment="REQUESTED | APPROVED | DISBURSED | SETTLED | CANCELLED",
	)
	disbursed_at = Column(DateTime(timezone=True), nullable=True)
	disbursement_ref = Column(String(100), nullable=True)

	linked_report_id = Column(
		UUID(as_uuid=False),
		ForeignKey("te_expense_report.id", ondelete="SET NULL"),
		nullable=True,
		index=True,
	)
	outstanding_cents = Column(
		BigInteger, nullable=False, default=0,
		comment="Remaining unreconciled balance; 0 when fully settled",
	)

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

	linked_report: ExpenseReport | None = relationship(
		"ExpenseReport",
		foreign_keys=[linked_report_id],
		back_populates="advances",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<CashAdvance {self.id} emp={self.employee_id} "
			f"amt={self.amount_cents} status={self.status}>"
		)


# ---------------------------------------------------------------------------
# MileageLog
# ---------------------------------------------------------------------------

class MileageLog(AuditMixin, Model):
	"""Mileage claim record — can be standalone or linked to an ExpenseReport.

	total_cents = distance_km × rate_per_km_cents (rounded half-up).
	When report_id is set, log_mileage() also creates a matching MILEAGE
	ExpenseLine on that report.
	"""

	__allow_unmapped__ = True
	__tablename__ = "te_mileage_log"
	__table_args__ = (
		Index("ix_te_mileage_tenant", "tenant_id"),
		Index("ix_te_mileage_employee", "employee_id"),
		Index("ix_te_mileage_report", "report_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	employee_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	log_date = Column(Date, nullable=False)
	from_location = Column(String(100), nullable=False)
	to_location = Column(String(100), nullable=False)
	purpose = Column(String(300), nullable=False)

	distance_km = Column(Numeric(8, 2), nullable=False)
	rate_per_km_cents = Column(
		BigInteger, nullable=False,
		comment="Applicable rate in integer cents per km",
	)
	total_cents = Column(
		BigInteger, nullable=False,
		comment="distance_km × rate_per_km_cents, rounded half-up",
	)

	project_id = Column(UUID(as_uuid=False), nullable=True, index=True)
	report_id = Column(
		UUID(as_uuid=False),
		ForeignKey("te_expense_report.id", ondelete="SET NULL"),
		nullable=True,
		index=True,
	)

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

	def __repr__(self) -> str:
		return (
			f"<MileageLog {self.id} emp={self.employee_id} "
			f"{self.distance_km}km={self.total_cents}c>"
		)


__all__ = [
	"ExpensePolicy",
	"PerDiemRate",
	"ExpenseReport",
	"ExpenseLine",
	"CashAdvance",
	"MileageLog",
]
