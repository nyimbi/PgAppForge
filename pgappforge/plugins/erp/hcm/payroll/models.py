"""
pgappforge/plugins/erp/hcm/payroll/models.py

SQLAlchemy models for the HCM Payroll plugin.

Design invariants:
  - ALL PKs: UUID v4 — gen_random_uuid() server default
  - ALL timestamps: DateTime(timezone=True) / TIMESTAMPTZ DEFAULT NOW()
  - ALL monetary amounts: Integer cents (NEVER Numeric/float for money)
  - ALL models: tenant_id UUID NOT NULL + AuditMixin
  - Financial records (PayrollRun, Payslip, PayslipLine): NEVER UPDATE amounts
    directly — insert correction entries only (immutable ledger)
  - lazy='select' throughout (SA 2.x removed lazy='dynamic')
  - JSONB for semi-structured fields (periods, metadata)
  - Composite indexes for tenant + status hot paths

Table prefix: pay_
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import sqlalchemy as sa
from sqlalchemy import (
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
# PayrollCalendar
# ---------------------------------------------------------------------------

class PayrollCalendar(AuditMixin, Model):
	"""Payroll calendar — defines pay schedule for an entity.

	pay_frequency drives how often runs are created:
	  WEEKLY (52/yr), BIWEEKLY (26/yr), SEMIMONTHLY (24/yr), MONTHLY (12/yr)

	periods JSONB: list of {period_start, period_end, pay_date, label} dicts,
	pre-generated for the fiscal year by PayrollService.generate_calendar().
	"""

	__allow_unmapped__ = True
	__tablename__ = "pay_calendar"
	__table_args__ = (
		Index("ix_pay_calendar_tenant", "tenant_id"),
		Index("ix_pay_calendar_entity", "entity_id"),
		UniqueConstraint("tenant_id", "entity_id", "name", name="uq_pay_calendar_tenant_entity_name"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	entity_id = Column(
		UUID(as_uuid=False),
		nullable=False,
		index=True,
		comment="Legal entity / cost centre this calendar belongs to",
	)
	name = Column(String(100), nullable=False, comment="Human-readable calendar name e.g. 'Monthly 2026'")
	pay_frequency = Column(
		String(20),
		nullable=False,
		comment="WEEKLY | BIWEEKLY | SEMIMONTHLY | MONTHLY",
	)
	periods = Column(
		JSONB,
		nullable=False,
		default=list,
		comment="[{period_start, period_end, pay_date, label}, ...]",
	)
	fiscal_year = Column(Integer, nullable=False, comment="Calendar year this schedule covers")
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

	# Relationships
	payroll_runs: list[PayrollRun] = relationship(
		"PayrollRun", back_populates="calendar", lazy="select"
	)

	def __repr__(self) -> str:
		return f"<PayrollCalendar {self.name!r} freq={self.pay_frequency!r}>"


# ---------------------------------------------------------------------------
# PayrollRun
# ---------------------------------------------------------------------------

class PayrollRun(AuditMixin, Model):
	"""Payroll run header — one per pay period per entity.

	Status machine:
	  DRAFT → CALCULATED → APPROVED → PAID

	IMMUTABLE LEDGER: once status=PAID, amounts must not be changed.
	To correct a paid run, create a new run with payroll_type=OFF_CYCLE
	containing correction Payslips with negative/adjustment amounts.

	Aggregate counters are set by PayrollService.calculate_payrun() and
	must never be hand-edited after APPROVED.
	"""

	__allow_unmapped__ = True
	__tablename__ = "pay_run"
	__table_args__ = (
		Index("ix_pay_run_tenant", "tenant_id"),
		Index("ix_pay_run_entity", "entity_id"),
		Index("ix_pay_run_calendar", "calendar_id"),
		Index("ix_pay_run_tenant_status", "tenant_id", "status"),
		Index("ix_pay_run_period_start", "period_start"),
		UniqueConstraint(
			"tenant_id", "entity_id", "period_start", "period_end", "payroll_type",
			name="uq_pay_run_period",
		),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	entity_id = Column(UUID(as_uuid=False), nullable=False, index=True, comment="Legal entity")
	calendar_id = Column(UUID(as_uuid=False), ForeignKey("pay_calendar.id"), nullable=True, index=True)

	period_start = Column(Date, nullable=False)
	period_end = Column(Date, nullable=False)
	pay_date = Column(Date, nullable=False, comment="Bank value date for net pay transfer")
	payroll_type = Column(
		String(20),
		nullable=False,
		default="REGULAR",
		comment="REGULAR | OFF_CYCLE | BONUS | TERMINATION",
	)
	status = Column(
		String(20),
		nullable=False,
		default="DRAFT",
		comment="DRAFT | CALCULATED | APPROVED | PAID",
	)

	# Aggregate counts — set by calculate_payrun(), integer cents
	employee_count = Column(Integer, nullable=False, default=0)
	total_gross_cents = Column(Integer, nullable=False, default=0)
	total_employee_tax_cents = Column(Integer, nullable=False, default=0)
	total_employer_tax_cents = Column(Integer, nullable=False, default=0)
	total_net_cents = Column(Integer, nullable=False, default=0)

	# Workflow stamps
	calculated_at = Column(DateTime(timezone=True), nullable=True)
	approved_by = Column(UUID(as_uuid=False), nullable=True, comment="FK to ab_user — payroll approver")
	approved_at = Column(DateTime(timezone=True), nullable=True)
	paid_at = Column(DateTime(timezone=True), nullable=True)

	# GL posting reference
	gl_journal_id = Column(String(50), nullable=True, comment="GL journal ID after post_to_gl()")
	notes = Column(Text, nullable=True)
	metadata_ = Column("metadata", JSONB, nullable=False, default=dict)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	# Relationships
	calendar: PayrollCalendar | None = relationship("PayrollCalendar", back_populates="payroll_runs", lazy="select")
	payslips: list[Payslip] = relationship("Payslip", back_populates="payroll_run", cascade="all, delete-orphan", lazy="select")

	def __repr__(self) -> str:
		return (
			f"<PayrollRun {self.period_start}→{self.period_end} "
			f"type={self.payroll_type!r} status={self.status!r} "
			f"net={self.total_net_cents}¢>"
		)


# ---------------------------------------------------------------------------
# Payslip
# ---------------------------------------------------------------------------

class Payslip(AuditMixin, Model):
	"""Individual employee payslip within a payroll run.

	IMMUTABLE after status=PAID.  Reversals are Payslips with status=REVERSED
	and negative amounts in PayslipLines.

	bank_account_iban: sourced from employee master at calculation time (snapshot).
	payment_reference: used in ISO 20022 end-to-end ID.
	"""

	__allow_unmapped__ = True
	__tablename__ = "pay_payslip"
	__table_args__ = (
		Index("ix_pay_payslip_run", "payrun_id"),
		Index("ix_pay_payslip_employee", "employee_id"),
		Index("ix_pay_payslip_tenant", "tenant_id"),
		Index("ix_pay_payslip_tenant_status", "tenant_id", "status"),
		UniqueConstraint("payrun_id", "employee_id", name="uq_pay_payslip_run_employee"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	payrun_id = Column(UUID(as_uuid=False), ForeignKey("pay_run.id", ondelete="CASCADE"), nullable=False, index=True)
	employee_id = Column(
		UUID(as_uuid=False),
		nullable=False,
		index=True,
		comment="FK to HCM employee master (soft — no DB constraint for cross-plugin safety)",
	)

	# Snapshot amounts — integer cents (NEVER float)
	gross_pay_cents = Column(Integer, nullable=False, default=0)
	income_tax_cents = Column(Integer, nullable=False, default=0)
	national_insurance_cents = Column(Integer, nullable=False, default=0, comment="NI / social security employee share")
	pension_employee_cents = Column(Integer, nullable=False, default=0)
	pension_employer_cents = Column(Integer, nullable=False, default=0, comment="Employer pension contribution; employer cost")
	other_deductions_cents = Column(Integer, nullable=False, default=0, comment="Loan repayments, garnishments, etc.")
	net_pay_cents = Column(Integer, nullable=False, default=0,
		comment="gross - income_tax - ni_employee - pension_employee - other_deductions")

	# Payment details (snapshot at calculation time)
	bank_account_iban = Column(String(34), nullable=True, comment="Snapshot IBAN at calculation time")
	currency_code = Column(String(3), nullable=False, default="USD")
	payment_reference = Column(String(100), nullable=True, comment="End-to-end bank reference")

	status = Column(
		String(20),
		nullable=False,
		default="CALCULATED",
		comment="CALCULATED | APPROVED | PAID | REVERSED",
	)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	# Relationships
	payroll_run: PayrollRun = relationship("PayrollRun", back_populates="payslips", lazy="select")
	lines: list[PayslipLine] = relationship("PayslipLine", back_populates="payslip", cascade="all, delete-orphan", lazy="select")

	def __repr__(self) -> str:
		return (
			f"<Payslip employee={self.employee_id!r} "
			f"gross={self.gross_pay_cents}¢ net={self.net_pay_cents}¢ "
			f"status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# PayslipLine
# ---------------------------------------------------------------------------

class PayslipLine(AuditMixin, Model):
	"""Detailed earnings/deduction line on a payslip.

	amount_cents: positive = earnings/employer cost, negative = deduction.
	units × rate_cents = amount_cents (rounded half-up).
	is_employer_cost: True for pension_employer, NI employer — not deducted
	from net_pay_cents but visible for cost-centre reporting.
	"""

	__allow_unmapped__ = True
	__tablename__ = "pay_payslip_line"
	__table_args__ = (
		Index("ix_pay_psline_payslip", "payslip_id"),
		Index("ix_pay_psline_tenant", "tenant_id"),
		Index("ix_pay_psline_gl_account", "gl_account"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	payslip_id = Column(UUID(as_uuid=False), ForeignKey("pay_payslip.id", ondelete="CASCADE"), nullable=False, index=True)

	line_type = Column(
		String(20),
		nullable=False,
		comment="BASIC | OVERTIME | BONUS | COMMISSION | ALLOWANCE | DEDUCTION | TAX",
	)
	description = Column(String(255), nullable=False)

	# Quantity × rate model — NUMERIC for quantity (e.g. 160.00 hrs)
	units = Column(Numeric(10, 4), nullable=False, default=1, comment="Hours, days, or 1 for lump sums")
	rate_cents = Column(Integer, nullable=False, default=0, comment="Per-unit rate in cents")
	amount_cents = Column(Integer, nullable=False, comment="units × rate_cents (rounded); negative for deductions")

	is_employer_cost = Column(
		Boolean,
		nullable=False,
		default=False,
		comment="True for employer-side NI/pension; excluded from employee net pay",
	)

	# GL coding
	gl_account = Column(String(20), nullable=True, index=True, comment="GL expense/liability account")
	cost_center = Column(String(20), nullable=True)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	# Relationships
	payslip: Payslip = relationship("Payslip", back_populates="lines", lazy="select")

	def __repr__(self) -> str:
		return f"<PayslipLine {self.line_type!r} {self.description!r} {self.amount_cents}¢>"


# ---------------------------------------------------------------------------
# TaxWithholding
# ---------------------------------------------------------------------------

class TaxWithholding(AuditMixin, Model):
	"""Employee tax withholding configuration per jurisdiction.

	One row per employee per jurisdiction per effective date.
	The row with the latest effective_from <= pay_period_end is active.

	filing_status: SINGLE | MARRIED | MARRIED_FILING_SEPARATELY | HEAD_OF_HOUSEHOLD
	allowances: W-4 allowances (US) or equivalent
	additional_withholding_cents: flat extra amount per period
	"""

	__allow_unmapped__ = True
	__tablename__ = "pay_tax_withholding"
	__table_args__ = (
		Index("ix_pay_taxwh_employee", "employee_id"),
		Index("ix_pay_taxwh_tenant", "tenant_id"),
		Index("ix_pay_taxwh_jurisdiction", "jurisdiction_code"),
		Index("ix_pay_taxwh_effective", "employee_id", "jurisdiction_code", "effective_from"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	employee_id = Column(UUID(as_uuid=False), nullable=False, index=True, comment="Soft FK to HCM employee master")
	jurisdiction_code = Column(
		String(20),
		nullable=False,
		comment="ISO 3166-2 or local tax code e.g. US-CA, GB, NG-LA",
	)
	filing_status = Column(
		String(40),
		nullable=True,
		comment="SINGLE | MARRIED | MARRIED_FILING_SEPARATELY | HEAD_OF_HOUSEHOLD",
	)
	allowances = Column(Integer, nullable=False, default=0, comment="W-4 allowances (US) or equivalent exemptions")
	additional_withholding_cents = Column(
		Integer,
		nullable=False,
		default=0,
		comment="Flat additional withholding per period in cents",
	)
	effective_from = Column(Date, nullable=False, comment="Row effective from this date; supersedes prior rows")
	notes = Column(Text, nullable=True)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	def __repr__(self) -> str:
		return (
			f"<TaxWithholding employee={self.employee_id!r} "
			f"jurisdiction={self.jurisdiction_code!r} from={self.effective_from}>"
		)


__all__ = [
	"PayrollCalendar",
	"PayrollRun",
	"Payslip",
	"PayslipLine",
	"TaxWithholding",
]
