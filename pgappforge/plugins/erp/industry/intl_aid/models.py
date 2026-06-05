"""
pgappforge/plugins/erp/industry/intl_aid/models.py

SQLAlchemy models for the International Aid plugin (IATI 2.03-compliant).

Design invariants:
  - ALL PKs: UUID v4 via gen_random_uuid()
  - ALL monetary amounts: Integer cents (NEVER float)
  - ALL models: tenant_id UUID NOT NULL + AuditMixin
  - ProjectTransaction records are IMMUTABLE (insert-only ledger)
  - ALL timestamps: DateTime(timezone=True) — TIMESTAMPTZ
  - lazy='select' throughout
  - Table prefix: aid_

IATI alignment:
  AidOrganization   → iati_organisation
  AidProject        → iati_activity (+ budget aggregates)
  ProjectTransaction → iati_transaction (IMMUTABLE)
  ResultIndicator   → iati_result/indicator (flattened for ease of use)
  BeneficiaryCount  → custom extension for M&E beneficiary tracking
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

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
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import relationship

from pgappforge.models.sqla import Model
from pgappforge.plugins.audit import AuditMixin
from pgappforge.plugins.erp.foundation.commons import ImmutableRecordMixin


def _uuid4() -> str:
	return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# AidOrganization
# ---------------------------------------------------------------------------

class AidOrganization(AuditMixin, Model):
	"""Publishing organisation — donor, implementer, NGO, or multilateral.

	Links to foundation.Party for shared contact/address data.
	iati_identifier is the globally unique IATI org-ref (e.g. GB-CHC-1068839).
	Aggregate fields are updated by IntlAidService as transactions are recorded.
	"""

	__allow_unmapped__ = True
	__tablename__ = "aid_organization"
	__table_args__ = (
		Index("ix_aid_org_tenant", "tenant_id"),
		Index("ix_aid_org_party", "party_id"),
		UniqueConstraint("iati_identifier", name="uq_aid_org_iati_identifier"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	party_id = Column(UUID(as_uuid=False), nullable=True, index=True, comment="FK to foundation.Party (soft)")

	iati_identifier = Column(String(100), nullable=False, unique=True, comment="IATI org-ref e.g. GB-CHC-1068839")
	org_type = Column(
		String(20),
		nullable=False,
		default="NGO",
		comment="GOVERNMENT|NGO|MULTILATERAL|BILATERAL|PRIVATE",
	)

	# Running aggregates — updated by service
	total_disbursements_cents = Column(Integer, nullable=False, default=0, comment="Cumulative disbursements in cents")
	active_projects = Column(Integer, nullable=False, default=0, comment="Count of currently active projects")

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	implementing_projects: list[AidProject] = relationship(
		"AidProject",
		foreign_keys="AidProject.implementing_org_id",
		back_populates="implementing_org",
		lazy="select",
	)
	funding_projects: list[AidProject] = relationship(
		"AidProject",
		foreign_keys="AidProject.funding_org_id",
		back_populates="funding_org",
		lazy="select",
	)

	def __repr__(self) -> str:
		return f"<AidOrganization {self.iati_identifier!r} type={self.org_type!r}>"


# ---------------------------------------------------------------------------
# AidProject
# ---------------------------------------------------------------------------

class AidProject(AuditMixin, Model):
	"""Core IATI activity record — a funded development/humanitarian project.

	iati_identifier: globally unique IATI activity ID (e.g. GB-1-201820).
	sectors JSONB: [{vocabulary, code, percentage, name}] — DAC5 or IATI sector codes.
	sdg_targets: PostgreSQL text array of SDG target codes (e.g. ['1.1', '2.3']).
	Financial aggregates are updated as ProjectTransactions are recorded.
	"""

	__allow_unmapped__ = True
	__tablename__ = "aid_project"
	__table_args__ = (
		Index("ix_aid_project_tenant", "tenant_id"),
		Index("ix_aid_project_implementing", "implementing_org_id"),
		Index("ix_aid_project_funding", "funding_org_id"),
		Index("ix_aid_project_status", "status"),
		Index("ix_aid_project_country", "recipient_country_code"),
		UniqueConstraint("iati_identifier", name="uq_aid_project_iati_identifier"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	iati_identifier = Column(String(200), nullable=False, unique=True, comment="IATI activity ID e.g. GB-1-201820")
	title = Column(String(1024), nullable=False)
	description = Column(Text, nullable=True)

	implementing_org_id = Column(UUID(as_uuid=False), ForeignKey("aid_organization.id"), nullable=False, index=True)
	funding_org_id = Column(UUID(as_uuid=False), ForeignKey("aid_organization.id"), nullable=False, index=True)

	# Geography
	recipient_country_code = Column(String(2), nullable=False, comment="ISO 3166-1 alpha-2 recipient country")
	recipient_region = Column(String(100), nullable=True)

	# Classification
	sectors = Column(JSONB, nullable=False, default=list, comment="[{vocabulary, code, percentage, name}]")
	sdg_targets = Column(ARRAY(Text), nullable=False, default=list, comment="SDG target codes e.g. ['1.1', '2.3']")

	# Timeline
	start_date = Column(Date, nullable=True)
	end_date = Column(Date, nullable=True)
	status = Column(
		String(20),
		nullable=False,
		default="PIPELINE",
		comment="PIPELINE|IMPLEMENTATION|COMPLETION|CLOSED",
	)

	# Financial aggregates — updated by service
	total_budget_cents = Column(Integer, nullable=False, default=0, comment="Total approved budget in cents")
	total_committed_cents = Column(Integer, nullable=False, default=0, comment="Running commitment total; add-only")
	total_disbursed_cents = Column(Integer, nullable=False, default=0, comment="Running disbursement total; add-only")

	humanitarian = Column(Boolean, nullable=False, default=False, comment="IATI humanitarian flag")
	tied_status = Column(
		String(20),
		nullable=False,
		default="FREE",
		comment="FREE|PARTIALLY_TIED|TIED — OECD DAC tied-aid classification",
	)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	implementing_org: AidOrganization = relationship("AidOrganization", foreign_keys=[implementing_org_id], back_populates="implementing_projects", lazy="select")
	funding_org: AidOrganization = relationship("AidOrganization", foreign_keys=[funding_org_id], back_populates="funding_projects", lazy="select")
	transactions: list[ProjectTransaction] = relationship("ProjectTransaction", back_populates="project", lazy="select")
	result_indicators: list[ResultIndicator] = relationship("ResultIndicator", back_populates="project", lazy="select")
	beneficiary_counts: list[BeneficiaryCount] = relationship("BeneficiaryCount", back_populates="project", lazy="select")

	def __repr__(self) -> str:
		return f"<AidProject {self.iati_identifier!r} status={self.status!r}>"


# ---------------------------------------------------------------------------
# ProjectTransaction — IMMUTABLE
# ---------------------------------------------------------------------------

class ProjectTransaction(ImmutableRecordMixin, AuditMixin, Model):
	"""Immutable IATI financial transaction record.

	Insert-only ledger — never update or delete.
	Covers: COMMITMENT, DISBURSEMENT, EXPENDITURE, REPAYMENT.
	usd_value_cents is pre-computed at recording time using exchange_rate.
	"""

	__allow_unmapped__ = True
	__tablename__ = "aid_project_transaction"
	__table_args__ = (
		Index("ix_aid_txn_project", "project_id"),
		Index("ix_aid_txn_tenant", "tenant_id"),
		Index("ix_aid_txn_type", "transaction_type"),
		Index("ix_aid_txn_date", "transaction_date"),
		Index("ix_aid_txn_provider", "provider_id"),
		Index("ix_aid_txn_receiver", "receiver_id"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	project_id = Column(UUID(as_uuid=False), ForeignKey("aid_project.id"), nullable=False, index=True)

	transaction_type = Column(
		String(20),
		nullable=False,
		comment="COMMITMENT|DISBURSEMENT|EXPENDITURE|REPAYMENT",
	)
	transaction_date = Column(Date, nullable=False)
	value_cents = Column(Integer, nullable=False, comment="Transaction amount in cents (original currency)")
	currency_code = Column(String(3), nullable=False, default="USD")
	exchange_rate = Column(Numeric(15, 8), nullable=False, default=1, comment="Rate to USD at transaction date")
	usd_value_cents = Column(Integer, nullable=False, default=0, comment="value_cents × exchange_rate, rounded")

	provider_id = Column(UUID(as_uuid=False), nullable=False, index=True, comment="FK to foundation.Party (soft)")
	receiver_id = Column(UUID(as_uuid=False), nullable=False, index=True, comment="FK to foundation.Party (soft)")
	description = Column(Text, nullable=True)
	reference = Column(String(100), nullable=True, comment="Donor reference / voucher number")

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	# No updated_at — immutable record

	project: AidProject = relationship("AidProject", back_populates="transactions", lazy="select")

	def __repr__(self) -> str:
		return f"<ProjectTransaction {self.transaction_type!r} project={self.project_id!r} amount={self.value_cents}¢>"


# Register immutability hook
ProjectTransaction._register_immutability()


# ---------------------------------------------------------------------------
# ResultIndicator
# ---------------------------------------------------------------------------

class ResultIndicator(AuditMixin, Model):
	"""IATI result framework indicator for a project.

	One row per indicator per project.
	current_value is updated by IntlAidService.update_results().
	Flattened from IATI's nested result/indicator/period structure for
	simpler querying — use last_updated to know when re-assessed.
	"""

	__allow_unmapped__ = True
	__tablename__ = "aid_result_indicator"
	__table_args__ = (
		Index("ix_aid_result_project", "project_id"),
		Index("ix_aid_result_tenant", "tenant_id"),
		Index("ix_aid_result_type", "indicator_type"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	project_id = Column(UUID(as_uuid=False), ForeignKey("aid_project.id"), nullable=False, index=True)

	indicator_name = Column(String(512), nullable=False)
	indicator_type = Column(
		String(20),
		nullable=False,
		default="OUTPUT",
		comment="OUTPUT|OUTCOME|IMPACT",
	)
	unit_of_measure = Column(String(100), nullable=True)

	# Baseline
	baseline_value = Column(Numeric(15, 4), nullable=False, default=0)
	baseline_year = Column(Integer, nullable=False)

	# Target
	target_value = Column(Numeric(15, 4), nullable=False)
	target_year = Column(Integer, nullable=False)

	# Actual — updated periodically
	current_value = Column(Numeric(15, 4), nullable=False, default=0)
	last_updated = Column(Date, nullable=True)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	project: AidProject = relationship("AidProject", back_populates="result_indicators", lazy="select")

	def __repr__(self) -> str:
		return f"<ResultIndicator {self.indicator_name!r} type={self.indicator_type!r} current={self.current_value}>"


# ---------------------------------------------------------------------------
# BeneficiaryCount
# ---------------------------------------------------------------------------

class BeneficiaryCount(AuditMixin, Model):
	"""Periodic beneficiary count measurement for a project.

	One row per measurement date. Used for M&E reporting and dashboard KPIs.
	Disaggregated by gender and age where available.
	"""

	__allow_unmapped__ = True
	__tablename__ = "aid_beneficiary_count"
	__table_args__ = (
		Index("ix_aid_bene_project", "project_id"),
		Index("ix_aid_bene_tenant", "tenant_id"),
		Index("ix_aid_bene_date", "measurement_date"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	project_id = Column(UUID(as_uuid=False), ForeignKey("aid_project.id"), nullable=False, index=True)

	measurement_date = Column(Date, nullable=False)
	total_beneficiaries = Column(Integer, nullable=False)
	female_beneficiaries = Column(Integer, nullable=True)
	male_beneficiaries = Column(Integer, nullable=True)
	children_beneficiaries = Column(Integer, nullable=True, comment="Beneficiaries aged under 18")
	location_detail = Column(Text, nullable=True, comment="Free-text location description for this count")

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	project: AidProject = relationship("AidProject", back_populates="beneficiary_counts", lazy="select")

	def __repr__(self) -> str:
		return f"<BeneficiaryCount project={self.project_id!r} total={self.total_beneficiaries} date={self.measurement_date!r}>"


__all__ = [
	"AidOrganization",
	"AidProject",
	"ProjectTransaction",
	"ResultIndicator",
	"BeneficiaryCount",
]
