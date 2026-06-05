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
	bank_account_iban = Column(String(34), nullable=True, comment="Snapshot IBAN at calculation time — used for SWIFT/international transfers")
	# Kenya local bank fields (domestic EFT — mutually exclusive with IBAN path)
	bank_account_number = Column(String(30), nullable=True, comment="Local bank account number (Kenya EFT)")
	bank_name = Column(String(60), nullable=True, comment="Bank name e.g. KCB, Equity, Stanbic")
	bank_branch_code = Column(String(10), nullable=True, comment="Bank branch sort/routing code")
	currency_code = Column(String(3), nullable=False, default="KES")
	payment_reference = Column(String(100), nullable=True, comment="End-to-end bank reference")
	dispatched_at = Column(DateTime(timezone=True), nullable=True, comment="Set by dispatch_payslips() after PDF/email delivery")

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


# ---------------------------------------------------------------------------
# PayrollYTD — year-to-date accumulator per employee per tax year
# ---------------------------------------------------------------------------

class PayrollYTD(AuditMixin, Model):
	"""Year-to-date payroll accumulator per employee per tax year.

	One row per (tenant_id, employee_id, tax_year, month).
	Written as an INSERT-only side effect of calculate_payrun().
	Used by NITA cap enforcement, P9 generation, and PAYE cumulative method.

	month: 1–12 (calendar month of the pay period).
	"""

	__allow_unmapped__ = True
	__tablename__ = "pay_ytd"
	__table_args__ = (
		Index("ix_pay_ytd_tenant", "tenant_id"),
		Index("ix_pay_ytd_employee_year", "tenant_id", "employee_id", "tax_year"),
		UniqueConstraint(
			"tenant_id", "employee_id", "tax_year", "month",
			name="uq_pay_ytd_emp_year_month",
		),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	employee_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	payrun_id = Column(UUID(as_uuid=False), ForeignKey("pay_run.id"), nullable=False, index=True)

	tax_year = Column(Integer, nullable=False, comment="Calendar / tax year e.g. 2025")
	month = Column(Integer, nullable=False, comment="1–12")

	# Snapshot amounts for this specific month (integer cents)
	gross_cents = Column(Integer, nullable=False, default=0)
	taxable_gross_cents = Column(Integer, nullable=False, default=0)
	paye_cents = Column(Integer, nullable=False, default=0)
	nssf_tier1_cents = Column(Integer, nullable=False, default=0)
	nssf_tier2_cents = Column(Integer, nullable=False, default=0)
	shif_cents = Column(Integer, nullable=False, default=0)
	housing_levy_cents = Column(Integer, nullable=False, default=0)
	nita_cents = Column(Integer, nullable=False, default=0)
	net_cents = Column(Integer, nullable=False, default=0)

	# Benefits-in-kind included in taxable_gross (informational)
	bik_cents = Column(Integer, nullable=False, default=0)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	def __repr__(self) -> str:
		return (
			f"<PayrollYTD employee={self.employee_id!r} "
			f"year={self.tax_year} month={self.month} gross={self.gross_cents}¢>"
		)


# ---------------------------------------------------------------------------
# BenefitInKind — non-cash benefits for taxable income computation
# ---------------------------------------------------------------------------

class BenefitInKind(AuditMixin, Model):
	"""Non-cash employee benefit that forms part of taxable income.

	Loaded during calculate_payrun() to add to taxable_gross before PAYE.
	Excluded from pensionable_pay (NSSF) per KRA rules.

	benefit_type: CAR | HOUSING | MEDICAL | OTHER
	is_taxable: False means informational-only (still appears on payslip).
	"""

	__allow_unmapped__ = True
	__tablename__ = "pay_bik"
	__table_args__ = (
		Index("ix_pay_bik_tenant", "tenant_id"),
		Index("ix_pay_bik_employee", "employee_id"),
		Index("ix_pay_bik_effective", "employee_id", "effective_from"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	employee_id = Column(UUID(as_uuid=False), nullable=False, index=True, comment="Soft FK to HCM employee master")

	benefit_type = Column(
		String(20),
		nullable=False,
		comment="CAR | HOUSING | MEDICAL | OTHER",
	)
	description = Column(String(255), nullable=False)
	monthly_value_cents = Column(Integer, nullable=False, default=0, comment="Monthly BIK value in KES cents")
	is_taxable = Column(Boolean, nullable=False, default=True, comment="False = informational only, not added to taxable gross")
	effective_from = Column(Date, nullable=False, comment="BIK active from this date")
	effective_to = Column(Date, nullable=True, comment="BIK ends on this date (NULL = current)")

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	def __repr__(self) -> str:
		return (
			f"<BenefitInKind employee={self.employee_id!r} "
			f"type={self.benefit_type!r} value={self.monthly_value_cents}¢>"
		)


# ---------------------------------------------------------------------------
# PayslipAccessLog — audit trail for payslip downloads (Kenya DPA 2019)
# ---------------------------------------------------------------------------

class PayslipAccessLog(AuditMixin, Model):
	"""Immutable access log for payslip retrieval events.

	Required under Kenya Data Protection Act 2019 for personal financial data.
	access_type: VIEW | DOWNLOAD | EMAIL
	"""

	__allow_unmapped__ = True
	__tablename__ = "pay_payslip_access_log"
	__table_args__ = (
		Index("ix_pay_access_log_tenant", "tenant_id"),
		Index("ix_pay_access_log_payslip", "payslip_id"),
		Index("ix_pay_access_log_accessed_by", "accessed_by"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	payslip_id = Column(UUID(as_uuid=False), ForeignKey("pay_payslip.id"), nullable=False, index=True)
	accessed_by = Column(UUID(as_uuid=False), nullable=False, comment="ab_user UUID who performed the access")
	access_type = Column(String(10), nullable=False, comment="VIEW | DOWNLOAD | EMAIL")
	ip_address = Column(String(45), nullable=True, comment="IPv4 or IPv6 address of requester")
	accessed_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	def __repr__(self) -> str:
		return (
			f"<PayslipAccessLog payslip={self.payslip_id!r} "
			f"by={self.accessed_by!r} type={self.access_type!r}>"
		)


__all__ = [
	"PayrollCalendar",
	"PayrollRun",
	"Payslip",
	"PayslipLine",
	"TaxWithholding",
	"PayrollYTD",
	"BenefitInKind",
	"PayslipAccessLog",
]
