"""
pgappforge/plugins/fintech/regulatory/models.py

Regulatory Compliance models for Kenya fintech.

Covers:
  - AML transaction monitoring rules and alerts
  - Suspicious Activity Reports (SARs) to FRC Kenya
  - Basel III/IV capital adequacy reporting
  - IFRS 9 ECL provisioning runs
  - PEP (Politically Exposed Person) list management

Design invariants:
  - All PKs: UUID via gen_random_uuid() server-default
  - All timestamps: TIMESTAMPTZ DEFAULT NOW()
  - All models: tenant_id VARCHAR(64) NOT NULL
  - ALL monetary amounts: INTEGER cents — never Decimal/float in storage
  - Immutable models (SAR, CapitalAdequacyReport, IFRS9ProvisionRun): ImmutableRecordMixin

Table name convention: reg_<entity>
"""
from __future__ import annotations

import uuid
import logging
from datetime import datetime, date, timezone
from decimal import Decimal
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
from pgappforge.plugins.erp.foundation.commons import ImmutableRecordMixin

log = logging.getLogger(__name__)


def _uuid4() -> str:
	return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# AMLRule — configurable AML detection rules
# ---------------------------------------------------------------------------

class AMLRule(AuditMixin, Model):
	"""Configurable AML detection rule.

	rule_type discriminates evaluation logic in RegulatoryComplianceService:
	  THRESHOLD    — flag transactions above a monetary threshold
	                 params: {min_amount_cents, currency}
	  VELOCITY     — flag customers exceeding transaction frequency
	                 params: {max_transactions, period_hours}
	  STRUCTURING  — detect cash structuring (smurfing) below reporting threshold
	                 params: {threshold_cents, window_hours, min_count}
	  COUNTRY_RISK — flag transactions involving high-risk jurisdictions
	                 params: {risk_countries: [...], action: "ALERT|BLOCK"}
	  CUSTOMER_RISK— flag based on customer risk rating
	                 params: {min_risk_rating: 3}
	  PEP          — flag transactions involving politically exposed persons
	                 params: {pep_types: [...]}

	risk_score: 1 (low) to 100 (critical) — used to prioritise alert queues.
	regulatory_reference: free text e.g. "CBK AML Act s.24", "FATF R.20".
	"""

	__allow_unmapped__ = True
	__tablename__ = "reg_aml_rule"
	__table_args__ = (
		Index("ix_reg_aml_rule_code", "rule_code"),
		Index("ix_reg_aml_rule_type", "rule_type"),
		Index("ix_reg_aml_rule_active", "is_active"),
		Index("ix_reg_aml_rule_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(64), nullable=False, index=True, comment="Tenant identifier")

	rule_code = Column(String(30), unique=True, nullable=False, comment="Short unique rule code e.g. AML-TH-001")
	rule_name = Column(String(200), nullable=False)
	rule_type = Column(
		String(30),
		nullable=False,
		comment="THRESHOLD | VELOCITY | PATTERN | STRUCTURING | COUNTRY_RISK | CUSTOMER_RISK | PEP",
	)
	description = Column(Text, nullable=False)
	parameters: dict[str, Any] = Column(
		JSONB,
		nullable=False,
		default=dict,
		server_default="{}",
		comment=(
			"THRESHOLD: {min_amount_cents, currency} | "
			"VELOCITY: {max_transactions, period_hours} | "
			"STRUCTURING: {threshold_cents, window_hours, min_count}"
		),
	)
	risk_score = Column(Integer, nullable=False, comment="1 (low) to 100 (critical)")
	is_active = Column(Boolean, nullable=False, default=True)
	regulatory_reference = Column(
		String(100),
		nullable=True,
		comment="e.g. CBK AML Act s.24, FATF Recommendation 20",
	)
	# SLA tracking — HIGH gap
	investigation_sla_hours = Column(
		Integer,
		nullable=False,
		default=72,
		comment="Hours from alert creation to SLA breach; default 72 h (3 days, CBK SAR deadline)",
	)
	# Fraud score gating — HIGH gap
	require_fraud_score_above = Column(
		Integer,
		nullable=True,
		comment="When set, rule only fires if latest RegFraudSignal.score exceeds this value (0-1000)",
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

	alerts: list[AMLAlert] = relationship(
		"AMLAlert",
		back_populates="rule",
		lazy="select",
	)

	def __repr__(self) -> str:
		return f"<AMLRule {self.rule_code!r} type={self.rule_type!r} score={self.risk_score}>"


# ---------------------------------------------------------------------------
# AMLAlert — generated when a rule fires against a transaction/customer
# ---------------------------------------------------------------------------

class AMLAlert(AuditMixin, Model):
	"""AML alert generated by rule engine.

	alert_number: human-readable sequential reference e.g. AML-2026-000001.
	triggering_transaction_ids: JSONB list of transaction UUIDs that fired the rule.
	alert_detail: full rule evaluation context (amounts, dates, counterparties, etc.).

	Status flow:
	  OPEN → UNDER_REVIEW → ESCALATED → CLOSED_SAR_FILED
	                                  → CLOSED_FALSE_POSITIVE
	                                  → CLOSED_NO_ACTION
	"""

	__allow_unmapped__ = True
	__tablename__ = "reg_aml_alert"
	__table_args__ = (
		Index("ix_reg_aml_alert_number", "alert_number"),
		Index("ix_reg_aml_alert_rule", "rule_id"),
		Index("ix_reg_aml_alert_customer", "customer_id"),
		Index("ix_reg_aml_alert_account", "account_id"),
		Index("ix_reg_aml_alert_status", "status"),
		Index("ix_reg_aml_alert_due", "due_by"),
		Index("ix_reg_aml_alert_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(64), nullable=False, index=True, comment="Tenant identifier")

	alert_number = Column(String(30), unique=True, nullable=False, comment="e.g. AML-2026-000001")
	rule_id = Column(UUID(as_uuid=False), ForeignKey("reg_aml_rule.id"), nullable=False, index=True)
	customer_id = Column(UUID(as_uuid=False), ForeignKey("erp_party.id"), nullable=False, index=True)
	account_id = Column(UUID(as_uuid=False), ForeignKey("cb_account.id"), nullable=True, index=True)
	triggering_transaction_ids: list[str] = Column(
		JSONB,
		nullable=True,
		default=list,
		comment="List of transaction/ledger entry UUIDs that triggered this alert",
	)
	risk_score = Column(Integer, nullable=False, comment="Composite risk score at alert generation time")
	alert_detail: dict[str, Any] = Column(
		JSONB,
		nullable=False,
		default=dict,
		server_default="{}",
		comment="Full rule evaluation context: amounts, dates, counterparties, pattern data",
	)
	status = Column(
		String(30),
		nullable=False,
		default="OPEN",
		comment=(
			"OPEN | UNDER_REVIEW | ESCALATED | "
			"CLOSED_FALSE_POSITIVE | CLOSED_SAR_FILED | CLOSED_NO_ACTION"
		),
	)
	assigned_to = Column(UUID(as_uuid=False), nullable=True, comment="Analyst UUID (FK not enforced at DB level)")
	due_by = Column(DateTime(timezone=True), nullable=True, comment="SLA deadline for resolution")
	investigated_by = Column(UUID(as_uuid=False), nullable=True)
	investigation_notes = Column(Text, nullable=True)
	closed_at = Column(DateTime(timezone=True), nullable=True)
	# SLA tracking — HIGH gap
	sla_due_at = Column(
		DateTime(timezone=True),
		nullable=True,
		comment="Computed SLA deadline from AMLRule.investigation_sla_hours at alert creation",
	)
	sla_breached_at = Column(
		DateTime(timezone=True),
		nullable=True,
		comment="Stamped by SLAMonitor.check() when sla_due_at < now() AND closed_at IS NULL",
	)
	sar_filing_deadline = Column(
		DateTime(timezone=True),
		nullable=True,
		comment="CBK 3-day SAR filing deadline from suspicion formation (alert creation + 72 h)",
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

	rule: AMLRule = relationship("AMLRule", back_populates="alerts", lazy="select")
	sars: list[SuspiciousActivityReport] = relationship(
		"SuspiciousActivityReport",
		back_populates="alert",
		lazy="select",
	)

	def __repr__(self) -> str:
		return f"<AMLAlert {self.alert_number!r} status={self.status!r} score={self.risk_score}>"


# ---------------------------------------------------------------------------
# SuspiciousActivityReport — IMMUTABLE, filed with FRC Kenya
# ---------------------------------------------------------------------------

class SuspiciousActivityReport(ImmutableRecordMixin, AuditMixin, Model):
	"""Suspicious Activity Report (SAR) filed with Financial Reporting Centre Kenya.

	IMMUTABLE — once filed, rows are never updated.
	Corrections require a new SAR with amended data.

	regulator: FRC_KENYA (default) | CENTRAL_BANK | OTHER
	regulator_reference: acknowledgement number from FRC once received.
	total_amount_cents: aggregate of suspicious transactions in the period.

	Status flow (updated by regulator callbacks, not by bank staff):
	  FILED → ACKNOWLEDGED → UNDER_INVESTIGATION → CLOSED
	"""

	__allow_unmapped__ = True
	__tablename__ = "reg_sar"
	__table_args__ = (
		Index("ix_reg_sar_number", "sar_number"),
		Index("ix_reg_sar_alert", "alert_id"),
		Index("ix_reg_sar_subject", "subject_id"),
		Index("ix_reg_sar_filed_at", "filed_at"),
		Index("ix_reg_sar_status", "status"),
		Index("ix_reg_sar_tenant", "tenant_id"),
		UniqueConstraint("sar_number", name="uq_reg_sar_number"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(64), nullable=False, index=True, comment="Tenant identifier")

	sar_number = Column(String(30), unique=True, nullable=False, comment="e.g. SAR-2026-000001")
	alert_id = Column(UUID(as_uuid=False), ForeignKey("reg_aml_alert.id"), nullable=False, index=True)
	subject_id = Column(UUID(as_uuid=False), ForeignKey("erp_party.id"), nullable=False, index=True)
	account_ids: list[str] = Column(
		JSONB,
		nullable=False,
		default=list,
		comment="List of account UUIDs included in suspicious activity period",
	)
	activity_period_start = Column(Date, nullable=False)
	activity_period_end = Column(Date, nullable=False)
	suspicious_activity_description = Column(Text, nullable=False)
	total_amount_cents = Column(Integer, nullable=False, comment="Aggregate suspicious transaction total (cents)")
	currency_code = Column(String(3), nullable=False, default="KES")
	filed_by = Column(UUID(as_uuid=False), nullable=False, comment="Staff member UUID who filed this SAR")
	filed_at = Column(DateTime(timezone=True), nullable=False)
	regulator = Column(String(50), nullable=False, default="FRC_KENYA", comment="FRC_KENYA | CENTRAL_BANK | OTHER")
	regulator_reference = Column(String(100), nullable=True, comment="Acknowledgement reference from regulator")
	status = Column(
		String(30),
		nullable=False,
		default="FILED",
		comment="FILED | ACKNOWLEDGED | UNDER_INVESTIGATION | CLOSED",
	)
	# Reversal / supersession tracking — HIGH gap
	supersedes_id = Column(
		UUID(as_uuid=False),
		nullable=True,
		comment="UUID of the original SAR this record supersedes (reversal chain)",
	)
	superseded_by_id = Column(
		UUID(as_uuid=False),
		nullable=True,
		comment="UUID of the replacement SAR that supersedes this record",
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
		server_default=sa.text("NOW()"),
		comment="Set once at insert; UPDATE blocked by ImmutableRecordMixin",
	)

	alert: AMLAlert = relationship("AMLAlert", back_populates="sars", lazy="select")

	def __repr__(self) -> str:
		return f"<SAR {self.sar_number!r} subject={self.subject_id!r} status={self.status!r}>"


SuspiciousActivityReport._register_immutability()


# ---------------------------------------------------------------------------
# CapitalAdequacyReport — IMMUTABLE, Basel III/IV CBK prudential report
# ---------------------------------------------------------------------------

class CapitalAdequacyReport(ImmutableRecordMixin, AuditMixin, Model):
	"""Capital Adequacy Report (Basel III/IV standard approach).

	CBK minimum ratios (Prudential Guideline 3):
	  CET1 ratio    ≥ 7.0%
	  Tier 1 ratio  ≥ 8.5%
	  Total capital ≥ 10.5%  (including 2.5% capital conservation buffer)
	  Leverage ratio≥ 3.0%
	  LCR           ≥ 100%
	  NSFR          ≥ 100%

	All capital/RWA figures stored as INTEGER cents.
	Ratios stored as Numeric(6,2) — percentage points e.g. 12.50 = 12.50%.

	IMMUTABLE — each report_date+reporting_period combination is a point-in-time
	snapshot.  Amendments create a new row; old rows are never updated.
	"""

	__allow_unmapped__ = True
	__tablename__ = "reg_capital_adequacy"
	__table_args__ = (
		Index("ix_reg_car_date", "report_date"),
		Index("ix_reg_car_period", "reporting_period"),
		Index("ix_reg_car_submitted", "submitted_to_cbk"),
		Index("ix_reg_car_tenant", "tenant_id"),
		UniqueConstraint("tenant_id", "report_date", "reporting_period", name="uq_reg_car_date_period"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(64), nullable=False, index=True, comment="Tenant identifier")

	report_date = Column(Date, nullable=False, comment="As-of date for this capital calculation")
	reporting_period = Column(String(20), nullable=False, comment="DAILY | MONTHLY | QUARTERLY")

	# --- Tier 1 Capital ---
	core_capital_cents = Column(Integer, nullable=False, comment="Common Equity Tier 1 (CET1) in cents")
	additional_tier1_cents = Column(Integer, nullable=False, default=0, comment="AT1 instruments (cents)")
	tier1_capital_cents = Column(Integer, nullable=False, comment="CET1 + AT1 (cents)")

	# --- Tier 2 Capital ---
	tier2_capital_cents = Column(Integer, nullable=False, default=0, comment="Tier 2 instruments (cents)")
	total_capital_cents = Column(Integer, nullable=False, comment="Tier 1 + Tier 2 (cents)")

	# --- Risk-Weighted Assets ---
	credit_rwa_cents = Column(Integer, nullable=False, comment="Credit risk RWA (Basel III standardised approach)")
	market_rwa_cents = Column(Integer, nullable=False, default=0, comment="Market risk RWA (cents)")
	operational_rwa_cents = Column(Integer, nullable=False, default=0, comment="Operational risk RWA (cents)")
	total_rwa_cents = Column(Integer, nullable=False, comment="Sum of all RWA categories (cents)")

	# --- Ratios (stored as percentage points e.g. 12.50) ---
	cet1_ratio_pct = Column(Numeric(6, 2), nullable=False, comment="CET1 / Total RWA × 100; CBK min 7.0%")
	tier1_ratio_pct = Column(Numeric(6, 2), nullable=False, comment="Tier1 / Total RWA × 100; CBK min 8.5%")
	total_capital_ratio_pct = Column(Numeric(6, 2), nullable=False, comment="Total Capital / RWA × 100; CBK min 10.5%")
	leverage_ratio_pct = Column(Numeric(6, 2), nullable=False, comment="Tier1 / Total Exposure × 100; Basel III min 3.0%")
	liquidity_coverage_ratio_pct = Column(Numeric(6, 2), nullable=True, comment="LCR — HQLA / Net Cash Outflows × 100; min 100%")
	nsfr_pct = Column(Numeric(6, 2), nullable=True, comment="NSFR — Available Stable Funding / Required × 100; min 100%")

	meets_minimum = Column(Boolean, nullable=False, comment="True if ALL CBK minimum ratios are satisfied")
	submitted_to_cbk = Column(Boolean, nullable=False, default=False)
	submitted_at = Column(DateTime(timezone=True), nullable=True)
	# Stress test results — HIGH gap
	stress_results: dict[str, Any] = Column(
		JSONB,
		nullable=False,
		default=dict,
		server_default="{}",
		comment=(
			"Stress scenario results keyed by scenario_id: "
			"{scenario_id: {cet1_pct, tier1_pct, total_capital_pct, rwa_cents, passes_minimum}}"
		),
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
		server_default=sa.text("NOW()"),
		comment="Set once at insert; UPDATE blocked by ImmutableRecordMixin",
	)

	def __repr__(self) -> str:
		return (
			f"<CapitalAdequacyReport {self.report_date!r} "
			f"CAR={self.total_capital_ratio_pct}% "
			f"meets_min={self.meets_minimum}>"
		)


CapitalAdequacyReport._register_immutability()


# ---------------------------------------------------------------------------
# IFRS9ProvisionRun — IMMUTABLE, ECL provisioning snapshot
# ---------------------------------------------------------------------------

class IFRS9ProvisionRun(ImmutableRecordMixin, AuditMixin, Model):
	"""IFRS 9 Expected Credit Loss (ECL) provision run snapshot.

	Stage classification (IFRS 9 para 5.5.3):
	  Stage 1: 0–30 DPD   → 12-month ECL  = PD_12m × LGD × EAD
	  Stage 2: 31–90 DPD  → Lifetime ECL  = PD_life × LGD × EAD
	  Stage 3: >90 DPD    → Credit-impaired; ECL ≈ LGD × EAD (PD ≈ 1)

	provision_movement_cents: delta vs the prior run of the same run_type.
	Positive = provision increase (P&L charge); negative = release.

	IMMUTABLE — each run is a point-in-time snapshot; corrections create a
	new run marked run_type=ADJUSTMENT.
	"""

	__allow_unmapped__ = True
	__tablename__ = "reg_ifrs9_run"
	__table_args__ = (
		Index("ix_reg_ifrs9_run_date", "run_date"),
		Index("ix_reg_ifrs9_run_type", "run_type"),
		Index("ix_reg_ifrs9_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(64), nullable=False, index=True, comment="Tenant identifier")

	run_date = Column(Date, nullable=False, comment="As-of date of this ECL calculation")
	run_type = Column(String(20), nullable=False, default="MONTHLY", comment="DAILY | MONTHLY | YEAR_END | ADJUSTMENT")

	# --- Stage 1 ---
	stage1_loans_cents = Column(Integer, nullable=False, comment="Gross carrying amount of Stage 1 loans (cents)")
	stage1_ecl_cents = Column(Integer, nullable=False, comment="12-month ECL for Stage 1 (cents)")

	# --- Stage 2 ---
	stage2_loans_cents = Column(Integer, nullable=False, comment="Gross carrying amount of Stage 2 loans (cents)")
	stage2_ecl_cents = Column(Integer, nullable=False, comment="Lifetime ECL for Stage 2 (cents)")

	# --- Stage 3 ---
	stage3_loans_cents = Column(Integer, nullable=False, comment="Gross carrying amount of Stage 3 loans (cents)")
	stage3_ecl_cents = Column(Integer, nullable=False, comment="Lifetime ECL for Stage 3 (cents)")

	# --- Totals ---
	total_loans_outstanding_cents = Column(Integer, nullable=False, comment="Stage 1 + 2 + 3 gross carrying amount")
	total_ecl_cents = Column(Integer, nullable=False, comment="Total provision required (Stage 1+2+3 ECL)")
	total_provision_pct = Column(Numeric(5, 2), nullable=False, comment="total_ecl / total_loans × 100")
	coverage_ratio_pct = Column(Numeric(5, 2), nullable=False, comment="Stage 3 ECL / Stage 3 loans × 100")
	provision_movement_cents = Column(
		Integer,
		nullable=False,
		comment="ECL delta vs prior run (positive=charge, negative=release)",
	)

	approved_by = Column(UUID(as_uuid=False), nullable=True, comment="Approver UUID (CFO/Risk sign-off)")
	# GL double-entry tracking — CRITICAL gap
	gl_posted = Column(
		Boolean,
		nullable=False,
		default=False,
		comment=(
			"Two-phase commit flag: False until GL journal is confirmed posted. "
			"A crash between ECL write and GL post leaves this False for recovery on next startup."
		),
	)
	gl_journal_id = Column(
		UUID(as_uuid=False),
		nullable=True,
		comment="UUID of the GL JournalEntry created by post_ifrs9_gl_entries()",
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
		server_default=sa.text("NOW()"),
		comment="Set once at insert; UPDATE blocked by ImmutableRecordMixin",
	)

	def __repr__(self) -> str:
		return (
			f"<IFRS9ProvisionRun {self.run_date!r} "
			f"type={self.run_type!r} "
			f"total_ecl={self.total_ecl_cents}c "
			f"gl_posted={self.gl_posted}>"
		)


IFRS9ProvisionRun._register_immutability()


# ---------------------------------------------------------------------------
# PEPList — Politically Exposed Persons register
# ---------------------------------------------------------------------------

class PEPList(AuditMixin, Model):
	"""Politically Exposed Person (PEP) register entry.

	pep_type:
	  DOMESTIC_PEP              — senior domestic political figure
	  FOREIGN_PEP               — senior foreign political figure
	  INTERNATIONAL_ORGANIZATION_PEP — senior official of international body
	  CLOSE_ASSOCIATE           — known close associate of a PEP
	  FAMILY_MEMBER             — immediate family member of a PEP

	source: WORLD_CHECK | REFINITIV | MANUAL | GOVERNMENT
	review_date: next scheduled enhanced due diligence review.
	status: ACTIVE | INACTIVE (de-listed or deceased).
	"""

	__allow_unmapped__ = True
	__tablename__ = "reg_pep_list"
	__table_args__ = (
		Index("ix_reg_pep_party", "party_id"),
		Index("ix_reg_pep_type", "pep_type"),
		Index("ix_reg_pep_country", "country_code"),
		Index("ix_reg_pep_status", "status"),
		Index("ix_reg_pep_review", "review_date"),
		Index("ix_reg_pep_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(64), nullable=False, index=True, comment="Tenant identifier")

	party_id = Column(UUID(as_uuid=False), ForeignKey("erp_party.id"), nullable=False, index=True)
	pep_type = Column(
		String(40),
		nullable=False,
		comment=(
			"DOMESTIC_PEP | FOREIGN_PEP | INTERNATIONAL_ORGANIZATION_PEP | "
			"CLOSE_ASSOCIATE | FAMILY_MEMBER"
		),
	)
	position_held = Column(String(200), nullable=False, comment="e.g. Cabinet Secretary, Member of Parliament")
	country_code = Column(String(2), nullable=False, comment="ISO 3166-1 alpha-2 country code")
	source = Column(String(100), nullable=False, comment="WORLD_CHECK | REFINITIV | MANUAL | GOVERNMENT")
	added_at = Column(DateTime(timezone=True), nullable=False)
	review_date = Column(Date, nullable=False, comment="Next EDD review date")
	status = Column(String(20), nullable=False, default="ACTIVE", comment="ACTIVE | INACTIVE")

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
		return f"<PEPList {self.id!r} party={self.party_id!r} type={self.pep_type!r} status={self.status!r}>"


# ---------------------------------------------------------------------------
# SanctionsList — OFAC/UN/EU/HMT sanctions register  [CRITICAL]
# ---------------------------------------------------------------------------

class SanctionsList(AuditMixin, Model):
	"""Consolidated sanctions list entry.

	list_source: OFAC_SDN | UN_CONSOLIDATED | EU_CONSOLIDATED | HMT | CBK | MANUAL
	entity_type: INDIVIDUAL | ENTITY | VESSEL | AIRCRAFT
	aliases: JSONB list of known alternate names for fuzzy matching.
	delisted_at: NULL means currently listed.

	Bulk-loaded via SanctionsService.bulk_upsert(); queried by trigram similarity
	through screen_transaction() before AML rule evaluation.
	"""

	__allow_unmapped__ = True
	__tablename__ = "reg_sanctions_list"
	__table_args__ = (
		Index("ix_reg_sanctions_source", "list_source"),
		Index("ix_reg_sanctions_entity_type", "entity_type"),
		Index("ix_reg_sanctions_listed_at", "listed_at"),
		Index("ix_reg_sanctions_tenant", "tenant_id"),
		UniqueConstraint("list_source", "external_ref", name="uq_reg_sanctions_source_ref"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(64), nullable=False, index=True, comment="Tenant identifier")

	list_source = Column(String(30), nullable=False, comment="OFAC_SDN | UN_CONSOLIDATED | EU_CONSOLIDATED | HMT | CBK | MANUAL")
	external_ref = Column(String(100), nullable=False, comment="Unique reference within the source list (e.g. OFAC UID)")
	listed_name = Column(String(300), nullable=False, comment="Primary sanctioned name")
	aliases: list[str] = Column(
		JSONB,
		nullable=False,
		default=list,
		server_default="[]",
		comment="Known alternate names for fuzzy matching",
	)
	entity_type = Column(String(20), nullable=False, comment="INDIVIDUAL | ENTITY | VESSEL | AIRCRAFT")
	country_code = Column(String(2), nullable=True, comment="ISO 3166-1 alpha-2; NULL if stateless/unknown")
	listed_at = Column(Date, nullable=False, comment="Date first added to this list")
	delisted_at = Column(Date, nullable=True, comment="Date removed; NULL means currently active")
	sanctions_programs: list[str] = Column(
		JSONB,
		nullable=False,
		default=list,
		server_default="[]",
		comment="e.g. ['UKRAINE-EO13662', 'SDGT']",
	)
	additional_info: dict[str, Any] = Column(
		JSONB,
		nullable=False,
		default=dict,
		server_default="{}",
		comment="Arbitrary extra fields from source list",
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
			f"<SanctionsList {self.external_ref!r} "
			f"source={self.list_source!r} "
			f"name={self.listed_name!r}>"
		)


# ---------------------------------------------------------------------------
# RegulatorySchedule — automated periodic report scheduler  [CRITICAL]
# ---------------------------------------------------------------------------

class RegulatorySchedule(AuditMixin, Model):
	"""Periodic regulatory report schedule.

	Drives automated CBK return generation and submission.
	frequency: DAILY | WEEKLY | MONTHLY | QUARTERLY | ANNUAL
	submission_status: PENDING | SUBMITTED | FAILED | SKIPPED
	submission_log: JSONB array of {attempt, status, response, ts} objects — regulator response payloads.
	"""

	__allow_unmapped__ = True
	__tablename__ = "reg_schedule"
	__table_args__ = (
		Index("ix_reg_schedule_report_type", "report_type"),
		Index("ix_reg_schedule_next_run", "next_run_at"),
		Index("ix_reg_schedule_status", "submission_status"),
		Index("ix_reg_schedule_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(64), nullable=False, index=True, comment="Tenant identifier")

	report_type = Column(
		String(30),
		nullable=False,
		comment="BS1 | BS3 | BS6 | IFRS9 | CAPITAL | SAR_SUMMARY | LARGE_EXPOSURE",
	)
	frequency = Column(
		String(15),
		nullable=False,
		comment="DAILY | WEEKLY | MONTHLY | QUARTERLY | ANNUAL",
	)
	is_active = Column(Boolean, nullable=False, default=True)
	next_run_at = Column(DateTime(timezone=True), nullable=False, comment="Timestamp of next scheduled run")
	last_run_id = Column(
		UUID(as_uuid=False),
		nullable=True,
		comment="UUID of the last generated report or job record",
	)
	last_run_at = Column(DateTime(timezone=True), nullable=True)
	submission_status = Column(
		String(20),
		nullable=False,
		default="PENDING",
		comment="PENDING | SUBMITTED | FAILED | SKIPPED",
	)
	retry_count = Column(Integer, nullable=False, default=0)
	max_retries = Column(Integer, nullable=False, default=3)
	submission_log: list[dict] = Column(
		JSONB,
		nullable=False,
		default=list,
		server_default="[]",
		comment="List of {attempt, status, response_code, response_body, ts} submission attempt records",
	)
	regulator_endpoint = Column(
		String(500),
		nullable=True,
		comment="Regulator submission URL (NULL = local generation only)",
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
			f"<RegulatorySchedule {self.report_type!r} "
			f"freq={self.frequency!r} "
			f"next={self.next_run_at!r}>"
		)


# ---------------------------------------------------------------------------
# StressScenario — capital stress test scenario parameters  [HIGH]
# ---------------------------------------------------------------------------

class StressScenario(AuditMixin, Model):
	"""Capital adequacy stress test scenario.

	macro_shock_params: JSONB dict of macroeconomic shock inputs, e.g.
	  {"gdp_growth_pct": -3.5, "unemployment_rate_pct": 12.0, "property_price_decline_pct": 25.0}
	pd_multiplier: scale factor applied to all PD inputs (1.0 = no shock, 2.5 = stressed).
	lgd_multiplier: scale factor applied to all LGD inputs.
	haircut_pct: RWA haircut applied to collateral values (reduces collateral benefit).
	"""

	__allow_unmapped__ = True
	__tablename__ = "reg_stress_scenario"
	__table_args__ = (
		Index("ix_reg_stress_scenario_name", "scenario_name"),
		Index("ix_reg_stress_scenario_tenant", "tenant_id"),
		UniqueConstraint("tenant_id", "scenario_name", name="uq_reg_stress_scenario_name"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(64), nullable=False, index=True, comment="Tenant identifier")

	scenario_name = Column(String(100), nullable=False, comment="e.g. Adverse_2026, Severely_Adverse_2026")
	description = Column(Text, nullable=True)
	macro_shock_params: dict[str, Any] = Column(
		JSONB,
		nullable=False,
		default=dict,
		server_default="{}",
		comment="GDP growth, unemployment, property price, FX shock parameters",
	)
	pd_multiplier = Column(
		Numeric(8, 4),
		nullable=False,
		default=Decimal("1.0"),
		comment="Multiplier applied to all PD estimates (1.0 = base, 2.5 = stressed)",
	)
	lgd_multiplier = Column(
		Numeric(8, 4),
		nullable=False,
		default=Decimal("1.0"),
		comment="Multiplier applied to all LGD estimates",
	)
	haircut_pct = Column(
		Numeric(8, 4),
		nullable=False,
		default=Decimal("0.0"),
		comment="Additional RWA haircut on collateral (percent, e.g. 20.0 = 20%)",
	)
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
		return (
			f"<StressScenario {self.scenario_name!r} "
			f"pd_mult={self.pd_multiplier} "
			f"lgd_mult={self.lgd_multiplier}>"
		)


# ---------------------------------------------------------------------------
# ReversalRecord — audit trail for SAR/report corrections  [HIGH]
# ---------------------------------------------------------------------------

class ReversalRecord(AuditMixin, Model):
	"""Immutable audit record for regulatory document reversals.

	When a SAR, CapitalAdequacyReport, or IFRS9ProvisionRun must be corrected,
	the original record is superseded (never deleted/modified) and a ReversalRecord
	is created linking original → replacement.

	original_record_type: SAR | CAPITAL_REPORT | IFRS9_RUN
	reason_code: DATA_ERROR | SYSTEM_ERROR | REGULATORY_AMENDMENT | FRAUD_DETECTED
	"""

	__allow_unmapped__ = True
	__tablename__ = "reg_reversal_record"
	__table_args__ = (
		Index("ix_reg_reversal_original", "original_record_id"),
		Index("ix_reg_reversal_type", "original_record_type"),
		Index("ix_reg_reversal_reversed_at", "reversed_at"),
		Index("ix_reg_reversal_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(64), nullable=False, index=True, comment="Tenant identifier")

	original_record_id = Column(UUID(as_uuid=False), nullable=False, comment="UUID of the superseded record")
	original_record_type = Column(
		String(30),
		nullable=False,
		comment="SAR | CAPITAL_REPORT | IFRS9_RUN",
	)
	reason_code = Column(
		String(40),
		nullable=False,
		comment="DATA_ERROR | SYSTEM_ERROR | REGULATORY_AMENDMENT | FRAUD_DETECTED",
	)
	reason_detail = Column(Text, nullable=True, comment="Free-text explanation for audit log")
	reversed_by = Column(UUID(as_uuid=False), nullable=False, comment="Staff UUID who authorised the reversal")
	reversed_at = Column(DateTime(timezone=True), nullable=False)
	replacement_record_id = Column(
		UUID(as_uuid=False),
		nullable=True,
		comment="UUID of the new superseding record (NULL if reversal only, no replacement yet)",
	)
	replacement_record_type = Column(String(30), nullable=True)

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
			f"<ReversalRecord {self.original_record_type!r} "
			f"orig={self.original_record_id!r} "
			f"replaced_by={self.replacement_record_id!r}>"
		)


# ---------------------------------------------------------------------------
# RegFraudSignal — ML/behavioural anomaly scores for AML enrichment  [HIGH]
# ---------------------------------------------------------------------------

class RegFraudSignal(AuditMixin, Model):
	"""Fraud/ML behavioural anomaly signal from an external or internal model.

	score: 0 (clean) to 1000 (maximum risk) — integer centimilli scale.
	signal_source: INTERNAL_ML | REFINITIV | THREATMETRIX | CUSTOM
	features: JSONB snapshot of model input features at inference time.
	model_version: identifies exact model artefact for auditability.

	screen_transaction() queries the latest signal per customer and adds
	fraud_score_weight to the composite AML alert score.
	"""

	__allow_unmapped__ = True
	__tablename__ = "reg_fraud_signal"
	__table_args__ = (
		Index("ix_reg_fraud_signal_customer", "customer_id"),
		Index("ix_reg_fraud_signal_source", "signal_source"),
		Index("ix_reg_fraud_signal_created", "created_at"),
		Index("ix_reg_fraud_signal_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(64), nullable=False, index=True, comment="Tenant identifier")

	customer_id = Column(UUID(as_uuid=False), nullable=False, index=True, comment="Party UUID")
	signal_source = Column(
		String(60),
		nullable=False,
		comment="INTERNAL_ML | REFINITIV | THREATMETRIX | CUSTOM",
	)
	score = Column(Integer, nullable=False, comment="0 (clean) to 1000 (maximum risk)")
	features: dict[str, Any] = Column(
		JSONB,
		nullable=False,
		default=dict,
		server_default="{}",
		comment="Model input features snapshot at inference time",
	)
	model_version = Column(String(50), nullable=True, comment="Model artefact identifier for auditability")
	transaction_id = Column(UUID(as_uuid=False), nullable=True, comment="Optional linked transaction UUID")
	expires_at = Column(
		DateTime(timezone=True),
		nullable=True,
		comment="Signal validity window; NULL means indefinite",
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
			f"<RegFraudSignal customer={self.customer_id!r} "
			f"source={self.signal_source!r} "
			f"score={self.score}>"
		)


# ---------------------------------------------------------------------------
# RegOutboxEvent — transactional outbox for at-least-once event delivery  [HIGH]
# ---------------------------------------------------------------------------

class RegOutboxEvent(AuditMixin, Model):
	"""Transactional outbox entry for durable domain event delivery.

	Written in the same DB transaction as the business write.
	OutboxRelay polls for published_at IS NULL, publishes to broker, stamps published_at.
	Guarantees at-least-once delivery without two-phase commit.

	aggregate_type: the domain entity type e.g. AMLAlert, SAR, IFRS9ProvisionRun.
	event_type: the event string e.g. reg.aml.alert_generated.
	"""

	__allow_unmapped__ = True
	__tablename__ = "reg_outbox_event"
	__table_args__ = (
		Index("ix_reg_outbox_published", "published_at"),
		Index("ix_reg_outbox_event_type", "event_type"),
		Index("ix_reg_outbox_aggregate", "aggregate_id"),
		Index("ix_reg_outbox_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(64), nullable=False, index=True, comment="Tenant identifier")

	aggregate_id = Column(UUID(as_uuid=False), nullable=False, comment="UUID of the business entity that produced this event")
	aggregate_type = Column(String(60), nullable=False, comment="e.g. AMLAlert, SAR, IFRS9ProvisionRun")
	event_type = Column(String(100), nullable=False, comment="e.g. reg.aml.alert_generated")
	payload: dict[str, Any] = Column(
		JSONB,
		nullable=False,
		default=dict,
		server_default="{}",
		comment="Full event payload serialised as JSON",
	)
	published_at = Column(
		DateTime(timezone=True),
		nullable=True,
		comment="NULL = awaiting publication; stamped by OutboxRelay after broker ACK",
	)
	publish_attempts = Column(Integer, nullable=False, default=0, comment="Number of publish attempts")
	last_error = Column(Text, nullable=True, comment="Last broker error message for diagnostics")

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
			f"<RegOutboxEvent {self.event_type!r} "
			f"aggregate={self.aggregate_id!r} "
			f"published={self.published_at!r}>"
		)


# ---------------------------------------------------------------------------
# RegulatoryLimit — pre-transaction limit management engine  [HIGH]
# ---------------------------------------------------------------------------

class RegulatoryLimit(AuditMixin, Model):
	"""Regulatory exposure limit definition.

	limit_type:
	  SINGLE_BORROWER     — CBK 25% core capital limit (PG 3)
	  SECTOR_CONCENTRATION — concentration by economic sector
	  FX_OPEN_POSITION    — foreign exchange open position
	  INSIDER_LENDING     — lending to connected parties
	  LARGE_EXPOSURE      — aggregate of exposures > 10% core capital

	breach_action:
	  BLOCK  — raise LimitBreachException, prevent transaction
	  ALERT  — emit LimitBreachedEvent, allow transaction
	  REPORT — record for regulatory reporting only

	entity_id: the party/sector/currency being limited.
	effective_to: NULL means the limit is open-ended.
	"""

	__allow_unmapped__ = True
	__tablename__ = "reg_regulatory_limit"
	__table_args__ = (
		Index("ix_reg_limit_type", "limit_type"),
		Index("ix_reg_limit_entity", "entity_id"),
		Index("ix_reg_limit_effective", "effective_from", "effective_to"),
		Index("ix_reg_limit_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(64), nullable=False, index=True, comment="Tenant identifier")

	limit_type = Column(
		String(30),
		nullable=False,
		comment="SINGLE_BORROWER | SECTOR_CONCENTRATION | FX_OPEN_POSITION | INSIDER_LENDING | LARGE_EXPOSURE",
	)
	entity_id = Column(String(100), nullable=False, comment="Party UUID, sector code, or currency pair being limited")
	limit_amount_cents = Column(
		BigInteger,
		nullable=False,
		comment="Maximum allowed exposure in integer cents",
	)
	breach_action = Column(
		String(10),
		nullable=False,
		default="ALERT",
		comment="BLOCK | ALERT | REPORT",
	)
	effective_from = Column(Date, nullable=False)
	effective_to = Column(Date, nullable=True, comment="NULL = open-ended")
	regulatory_reference = Column(String(100), nullable=True, comment="e.g. CBK PG 3 s.4.2")
	notes = Column(Text, nullable=True)

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
			f"<RegulatoryLimit {self.limit_type!r} "
			f"entity={self.entity_id!r} "
			f"limit={self.limit_amount_cents}c "
			f"action={self.breach_action!r}>"
		)


# ---------------------------------------------------------------------------
# ReconciliationRun — GL vs regulatory report reconciliation  [HIGH]
# ---------------------------------------------------------------------------

class ReconciliationRun(AuditMixin, Model):
	"""Reconciliation between regulatory report figures and GL balances.

	status:
	  MATCHED — variance within configured tolerance
	  WARNED  — variance above warning threshold but below failure threshold
	  FAILED  — variance exceeds failure threshold; blocks CBK submission
	"""

	__allow_unmapped__ = True
	__tablename__ = "reg_reconciliation_run"
	__table_args__ = (
		Index("ix_reg_recon_report_type", "report_type"),
		Index("ix_reg_recon_period", "period"),
		Index("ix_reg_recon_status", "status"),
		Index("ix_reg_recon_run_at", "run_at"),
		Index("ix_reg_recon_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(64), nullable=False, index=True, comment="Tenant identifier")

	report_type = Column(String(30), nullable=False, comment="BS1 | BS3 | BS6 | IFRS9 | CAPITAL")
	period = Column(String(20), nullable=False, comment="Reporting period e.g. 2026-05")
	report_value_cents = Column(BigInteger, nullable=False, comment="Figure as submitted in the regulatory report")
	gl_value_cents = Column(BigInteger, nullable=False, comment="Corresponding GL trial-balance figure")
	variance_cents = Column(BigInteger, nullable=False, comment="report_value_cents minus gl_value_cents")
	variance_pct = Column(
		Numeric(10, 6),
		nullable=False,
		comment="Absolute percentage variance (|variance_cents| / gl_value_cents × 100)",
	)
	tolerance_pct = Column(
		Numeric(10, 6),
		nullable=False,
		default=Decimal("0.01"),
		comment="Configured tolerance threshold percentage",
	)
	status = Column(
		String(10),
		nullable=False,
		default="MATCHED",
		comment="MATCHED | WARNED | FAILED",
	)
	run_at = Column(DateTime(timezone=True), nullable=False)
	detail: dict[str, Any] = Column(
		JSONB,
		nullable=False,
		default=dict,
		server_default="{}",
		comment="Reconciliation line breakdown and diagnostic information",
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
			f"<ReconciliationRun {self.report_type!r} "
			f"period={self.period!r} "
			f"status={self.status!r} "
			f"variance={self.variance_cents}c>"
		)


# ---------------------------------------------------------------------------
# BaselIIICapitalReturn — structured Basel III capital adequacy return
# ---------------------------------------------------------------------------

class BaselIIICapitalReturn(ImmutableRecordMixin, AuditMixin, Model):
	"""Structured Basel III / CBK Form 5 capital adequacy return.

	status lifecycle: DRAFT → SUBMITTED → ACCEPTED
	Immutable: corrections require a new record (INSERT-only pattern).

	All monetary amounts in integer cents (KES).
	Ratios stored as Numeric(8,4): 14.5000 means 14.5%.
	"""

	__allow_unmapped__ = True
	__tablename__ = "reg_basel3_capital_return"
	__table_args__ = (
		Index("ix_reg_b3_tenant", "tenant_id"),
		Index("ix_reg_b3_reporting_date", "reporting_date"),
		Index("ix_reg_b3_period", "period"),
		Index("ix_reg_b3_status", "status"),
		UniqueConstraint("tenant_id", "period", name="uq_reg_b3_tenant_period"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(64), nullable=False, index=True, comment="Tenant identifier")

	reporting_date = Column(Date, nullable=False, comment="Date as of which ratios are computed")
	period = Column(
		String(10),
		nullable=False,
		comment="CBK reporting period e.g. '2026-Q1' or '2026-03'",
	)
	status = Column(
		String(10),
		nullable=False,
		default="DRAFT",
		comment="DRAFT | SUBMITTED | ACCEPTED",
	)

	# Capital components — cents
	cet1_capital_cents = Column(
		BigInteger,
		nullable=False,
		default=0,
		comment="Common Equity Tier 1 capital (paid-up + retained earnings) in KES cents",
	)
	tier1_capital_cents = Column(
		BigInteger,
		nullable=False,
		default=0,
		comment="Total Tier 1 capital (CET1 + Additional Tier 1) in KES cents",
	)
	tier2_capital_cents = Column(
		BigInteger,
		nullable=False,
		default=0,
		comment="Tier 2 capital (subordinated debt, loan loss reserves) in KES cents",
	)
	total_capital_cents = Column(
		BigInteger,
		nullable=False,
		default=0,
		comment="Total regulatory capital (Tier 1 + Tier 2) in KES cents",
	)
	risk_weighted_assets_cents = Column(
		BigInteger,
		nullable=False,
		default=0,
		comment="Total risk-weighted assets in KES cents",
	)

	# Ratios — Numeric(8,4); e.g. 14.5000 = 14.5%
	car_pct = Column(
		Numeric(8, 4),
		nullable=False,
		default=Decimal("0"),
		comment="Capital Adequacy Ratio: total_capital / RWA × 100",
	)
	tier1_ratio_pct = Column(
		Numeric(8, 4),
		nullable=False,
		default=Decimal("0"),
		comment="Tier 1 ratio: tier1_capital / RWA × 100",
	)
	cet1_ratio_pct = Column(
		Numeric(8, 4),
		nullable=False,
		default=Decimal("0"),
		comment="CET1 ratio: cet1_capital / RWA × 100",
	)
	lcr_pct = Column(
		Numeric(8, 4),
		nullable=True,
		comment="Liquidity Coverage Ratio: HQLA / Net30d outflows × 100",
	)
	nsfr_pct = Column(
		Numeric(8, 4),
		nullable=True,
		comment="Net Stable Funding Ratio: ASF / RSF × 100",
	)

	# Submission tracking
	submitted_at = Column(
		DateTime(timezone=True),
		nullable=True,
		comment="Timestamp when filed with CBK",
	)
	regulator_ref = Column(
		String(50),
		nullable=True,
		comment="CBK acknowledgement reference number",
	)

	# Breakdown and audit payload
	rwa_breakdown: dict[str, Any] = Column(
		JSONB,
		nullable=False,
		default=dict,
		server_default="{}",
		comment="Per-asset-class RWA breakdown {asset_class: {gross_cents, weight_pct, rwa_cents}}",
	)
	capital_shortfall_cents = Column(
		BigInteger,
		nullable=False,
		default=0,
		comment="Shortfall vs CBK minimum (0 if compliant); positive = shortfall",
	)
	cbk_minimums_snapshot: dict[str, Any] = Column(
		JSONB,
		nullable=False,
		default=dict,
		server_default="{}",
		comment="CBK minimum thresholds in force at reporting_date",
	)
	compliance_flags: dict[str, Any] = Column(
		JSONB,
		nullable=False,
		default=dict,
		server_default="{}",
		comment="Per-ratio compliance flags {ratio: {actual, minimum, compliant}}",
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

	# Relationship to RWA line items
	rwa_line_items: list[RWALineItem] = relationship(
		"RWALineItem",
		back_populates="capital_return",
		cascade="all, delete-orphan",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<BaselIIICapitalReturn period={self.period!r} "
			f"car={self.car_pct}% status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# RWALineItem — per-asset-class RWA breakdown line
# ---------------------------------------------------------------------------

class RWALineItem(AuditMixin, Model):
	"""Individual RWA line item within a BaselIIICapitalReturn.

	exposure_type:
	  ON_BALANCE  — on-balance-sheet loan/investment exposures
	  OFF_BALANCE — contingent liabilities, guarantees, commitments
	  MARKET      — market risk (FX, interest rate, equity position)

	rwa_cents is computed: gross_amount_cents × (risk_weight_pct / 100).
	Stored explicitly for auditability and regulatory drill-through.
	"""

	__allow_unmapped__ = True
	__tablename__ = "reg_rwa_line_item"
	__table_args__ = (
		Index("ix_reg_rwa_return_id", "return_id"),
		Index("ix_reg_rwa_tenant", "tenant_id"),
		Index("ix_reg_rwa_asset_class", "asset_class"),
		Index("ix_reg_rwa_exposure_type", "exposure_type"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(64), nullable=False, index=True, comment="Tenant identifier")

	return_id = Column(
		UUID(as_uuid=False),
		ForeignKey("reg_basel3_capital_return.id", ondelete="CASCADE"),
		nullable=False,
		comment="FK to BaselIIICapitalReturn",
	)
	asset_class = Column(
		String(50),
		nullable=False,
		comment="SOVEREIGN | BANK | CORPORATE | RETAIL | MORTGAGE | NPL | OFF_BALANCE | MARKET",
	)
	gross_amount_cents = Column(
		BigInteger,
		nullable=False,
		default=0,
		comment="Gross exposure before risk weighting in KES cents",
	)
	risk_weight_pct = Column(
		Numeric(6, 2),
		nullable=False,
		default=Decimal("100.00"),
		comment="Basel III risk weight percentage e.g. 35.00 for residential mortgage",
	)
	rwa_cents = Column(
		BigInteger,
		nullable=False,
		default=0,
		comment="Risk-weighted exposure: gross_amount_cents × risk_weight_pct / 100",
	)
	exposure_type = Column(
		String(30),
		nullable=False,
		default="ON_BALANCE",
		comment="ON_BALANCE | OFF_BALANCE | MARKET",
	)

	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	# Relationship back to the parent return
	capital_return: BaselIIICapitalReturn = relationship(
		"BaselIIICapitalReturn",
		back_populates="rwa_line_items",
	)

	def __repr__(self) -> str:
		return (
			f"<RWALineItem asset_class={self.asset_class!r} "
			f"gross={self.gross_amount_cents}c "
			f"weight={self.risk_weight_pct}% "
			f"rwa={self.rwa_cents}c>"
		)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"AMLRule",
	"AMLAlert",
	"SuspiciousActivityReport",
	"CapitalAdequacyReport",
	"IFRS9ProvisionRun",
	"PEPList",
	"SanctionsList",
	"RegulatorySchedule",
	"StressScenario",
	"ReversalRecord",
	"RegFraudSignal",
	"RegOutboxEvent",
	"RegulatoryLimit",
	"ReconciliationRun",
	"BaselIIICapitalReturn",
	"RWALineItem",
]
