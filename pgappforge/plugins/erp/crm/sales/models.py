"""
pgappforge/plugins/erp/crm/sales/models.py

SQLAlchemy models for the Sales Force Automation (SFA) plugin.

Design rules enforced:
  - All PKs: UUID v4, server_default=gen_random_uuid()
  - All timestamps: TIMESTAMPTZ (DateTime(timezone=True)) DEFAULT NOW()
  - All models: tenant_id UUID NOT NULL
  - Monetary amounts: INTEGER cents ONLY — never Numeric/float for money
  - AuditMixin on all mutable entities
  - RulesMixin on Opportunity, Lead, Quote for rules engine integration
  - lazy='select' throughout (SA 2.x)
  - JSONB for semi-structured data
  - Financial records immutable; corrections via new rows

Table name convention: crm_<entity>
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
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
from pgappforge.plugins.rules.mixin import RulesMixin


def _uuid4() -> str:
	return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Enumerations (VARCHAR with comment — no SA Enum, stays PG-only)
# ---------------------------------------------------------------------------

ACCOUNT_TYPE = ("PROSPECT", "CUSTOMER", "PARTNER", "COMPETITOR", "OTHER")
SENIORITY = ("C_LEVEL", "VP", "DIRECTOR", "MANAGER", "INDIVIDUAL", "OTHER")
LEAD_SOURCE = ("WEB", "REFERRAL", "CAMPAIGN", "SOCIAL", "TRADE_SHOW", "COLD_OUTREACH", "OTHER")
LEAD_STATUS = ("NEW", "CONTACTED", "WORKING", "QUALIFIED", "DISQUALIFIED", "CONVERTED")
LEAD_GRADE = ("A", "B", "C", "D")
OPP_STAGE = (
	"PROSPECTING", "QUALIFICATION", "DEMO", "PROPOSAL",
	"NEGOTIATION", "CLOSED_WON", "CLOSED_LOST",
)
FORECAST_CATEGORY = ("PIPELINE", "BEST_CASE", "COMMIT", "CLOSED")
OPP_TYPE = ("NEW_BUSINESS", "EXISTING_BUSINESS", "RENEWAL")
ACTIVITY_TYPE = ("CALL", "EMAIL", "MEETING", "DEMO", "NOTE", "LINKEDIN", "OTHER")
ACTIVITY_STATUS = ("PLANNED", "COMPLETED", "CANCELLED")
DIRECTION = ("INBOUND", "OUTBOUND")
TARGET_TYPE = ("REVENUE", "UNITS", "DEALS")


# ---------------------------------------------------------------------------
# SalesAccount
# ---------------------------------------------------------------------------

class SalesAccount(RulesMixin, AuditMixin, Model):
	"""Enterprise sales account — extends CRM account with scoring and hierarchy.

	parent_account_id enables account hierarchies (subsidiaries, divisions).
	All monetary fields are integer cents.
	"""

	__allow_unmapped__ = True
	__tablename__ = "crm_sales_account"
	__table_args__ = (
		UniqueConstraint("tenant_id", "account_number", name="uq_crm_sales_account_tenant_num"),
		Index("ix_crm_sales_account_tenant", "tenant_id"),
		Index("ix_crm_sales_account_owner", "owner_id"),
		Index("ix_crm_sales_account_parent", "parent_account_id"),
		Index("ix_crm_sales_account_type", "account_type"),
		Index("ix_crm_sales_account_health", "health_score"),
		{"extend_existing": True},
	)

	_rules_mutable_fields: frozenset[str] = frozenset({
		"account_type", "health_score", "churn_risk_score",
		"lifetime_value_cents", "nps_score", "owner_id",
	})
	__rules_context_fields__: list[str] = []

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	# Foundation Party link — name/address/contact lives there
	party_id = Column(
		UUID(as_uuid=False),
		ForeignKey("erp_party.id", ondelete="RESTRICT"),
		nullable=True,
		index=True,
		comment="Optional link to Foundation Party",
	)

	# Identity
	account_number = Column(String(30), nullable=True, comment="Human-readable account code; unique per tenant")
	name = Column(String(255), nullable=False)
	account_type = Column(
		String(30),
		nullable=False,
		default="PROSPECT",
		server_default="PROSPECT",
		comment="PROSPECT/CUSTOMER/PARTNER/COMPETITOR/OTHER",
	)
	industry = Column(String(100), nullable=True)
	website = Column(String(500), nullable=True)
	phone = Column(String(50), nullable=True)
	email = Column(String(255), nullable=True)

	# Financials — integer cents
	annual_revenue_cents = Column(
		Integer,
		nullable=True,
		comment="Annual revenue in cents; NULL = unknown",
	)
	employee_count = Column(Integer, nullable=True)

	# Hierarchy
	parent_account_id = Column(
		UUID(as_uuid=False),
		ForeignKey("crm_sales_account.id", ondelete="SET NULL"),
		nullable=True,
		index=True,
		comment="Parent account for subsidiary/division hierarchies",
	)

	# Ownership
	owner_id = Column(
		UUID(as_uuid=False),
		nullable=True,
		index=True,
		comment="FK to Employee / ab_user who owns this account",
	)

	# Scoring
	health_score = Column(
		Numeric(3, 1),
		nullable=True,
		comment="0.0–10.0 account health score",
	)
	churn_risk_score = Column(
		Numeric(3, 1),
		nullable=True,
		comment="0.0–10.0 churn risk; higher = more at risk",
	)
	lifetime_value_cents = Column(
		Integer,
		nullable=True,
		comment="Computed customer lifetime value in cents",
	)
	nps_score = Column(
		Integer,
		nullable=True,
		comment="Net Promoter Score (-100 to 100)",
	)

	# Address snapshot
	billing_address: dict[str, Any] = Column(
		JSONB,
		nullable=False,
		default=dict,
		server_default="{}",
	)
	shipping_address: dict[str, Any] = Column(
		JSONB,
		nullable=False,
		default=dict,
		server_default="{}",
	)
	description = Column(Text, nullable=True)
	status = Column(
		String(20),
		nullable=False,
		default="ACTIVE",
		server_default="ACTIVE",
		comment="ACTIVE/INACTIVE/ARCHIVED",
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

	# Relationships
	contacts: list[SalesContact] = relationship(
		"SalesContact",
		back_populates="account",
		cascade="all, delete-orphan",
		lazy="select",
	)
	opportunities: list[Opportunity] = relationship(
		"Opportunity",
		back_populates="account",
		cascade="all, delete-orphan",
		lazy="select",
	)
	activities: list[Activity] = relationship(
		"Activity",
		back_populates="account",
		lazy="select",
	)
	child_accounts: list[SalesAccount] = relationship(
		"SalesAccount",
		back_populates="parent_account",
		lazy="select",
	)
	parent_account: SalesAccount = relationship(
		"SalesAccount",
		back_populates="child_accounts",
		remote_side="SalesAccount.id",
		foreign_keys=[parent_account_id],
		lazy="select",
	)

	def __repr__(self) -> str:
		return f"<SalesAccount {self.name!r} type={self.account_type!r} id={self.id!r}>"


# ---------------------------------------------------------------------------
# SalesContact
# ---------------------------------------------------------------------------

class SalesContact(AuditMixin, Model):
	"""Contact at a sales account.

	Tracks role, seniority, and engagement for multi-threaded selling.
	"""

	__allow_unmapped__ = True
	__tablename__ = "crm_sales_contact"
	__table_args__ = (
		Index("ix_crm_sales_contact_tenant", "tenant_id"),
		Index("ix_crm_sales_contact_account", "account_id"),
		Index("ix_crm_sales_contact_owner", "owner_id"),
		Index("ix_crm_sales_contact_email", "email"),
		Index("ix_crm_sales_contact_engagement", "engagement_score"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	party_id = Column(
		UUID(as_uuid=False),
		ForeignKey("erp_party.id", ondelete="SET NULL"),
		nullable=True,
		index=True,
	)
	account_id = Column(
		UUID(as_uuid=False),
		ForeignKey("crm_sales_account.id", ondelete="CASCADE"),
		nullable=True,
		index=True,
	)

	# Identity
	first_name = Column(String(100), nullable=False)
	last_name = Column(String(100), nullable=False)
	salutation = Column(String(20), nullable=True)
	title = Column(String(100), nullable=True)
	department = Column(String(100), nullable=True)
	email = Column(String(255), nullable=True, index=True)
	phone = Column(String(50), nullable=True)
	mobile = Column(String(50), nullable=True)
	linkedin_url = Column(String(500), nullable=True)

	# Influence profile
	seniority = Column(
		String(20),
		nullable=True,
		comment="C_LEVEL/VP/DIRECTOR/MANAGER/INDIVIDUAL/OTHER",
	)
	is_decision_maker = Column(Boolean, nullable=False, default=False, server_default="false")
	is_influencer = Column(Boolean, nullable=False, default=False, server_default="false")
	opted_out_email = Column(Boolean, nullable=False, default=False, server_default="false")
	opted_out_phone = Column(Boolean, nullable=False, default=False, server_default="false")

	# Ownership & engagement
	owner_id = Column(UUID(as_uuid=False), nullable=True, index=True)
	last_activity_at = Column(DateTime(timezone=True), nullable=True)
	engagement_score = Column(
		Numeric(3, 1),
		nullable=True,
		comment="0.0–10.0 engagement score computed from activity frequency",
	)
	status = Column(
		String(20),
		nullable=False,
		default="ACTIVE",
		server_default="ACTIVE",
		comment="ACTIVE/INACTIVE/ARCHIVED",
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

	account: SalesAccount = relationship("SalesAccount", back_populates="contacts", lazy="select")
	activities: list[Activity] = relationship(
		"Activity",
		back_populates="contact",
		lazy="select",
	)

	def __repr__(self) -> str:
		return f"<SalesContact {self.first_name!r} {self.last_name!r} id={self.id!r}>"


# ---------------------------------------------------------------------------
# Lead
# ---------------------------------------------------------------------------

class Lead(RulesMixin, AuditMixin, Model):
	"""Top-of-funnel lead — converts to Account + Contact + Opportunity.

	score: 0–100 Einstein-style lead score.
	grade: A/B/C/D derived from score bands.
	UTM fields for marketing attribution.
	"""

	__allow_unmapped__ = True
	__tablename__ = "crm_lead"
	__table_args__ = (
		Index("ix_crm_lead_tenant", "tenant_id"),
		Index("ix_crm_lead_assigned", "assigned_to"),
		Index("ix_crm_lead_status", "status"),
		Index("ix_crm_lead_score", "score"),
		Index("ix_crm_lead_email", "email"),
		Index("ix_crm_lead_campaign", "campaign_id"),
		{"extend_existing": True},
	)

	_rules_mutable_fields: frozenset[str] = frozenset({
		"status", "score", "grade", "assigned_to",
	})
	__rules_context_fields__: list[str] = []

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	# Identity
	first_name = Column(String(100), nullable=True)
	last_name = Column(String(100), nullable=True)
	company = Column(String(255), nullable=True)
	title = Column(String(100), nullable=True)
	email = Column(String(255), nullable=True, index=True)
	phone = Column(String(50), nullable=True)

	# Attribution
	source = Column(
		String(50),
		nullable=True,
		comment="WEB/REFERRAL/CAMPAIGN/SOCIAL/TRADE_SHOW/COLD_OUTREACH/OTHER",
	)
	campaign_id = Column(UUID(as_uuid=False), nullable=True, index=True)
	utm_source = Column(String(100), nullable=True)
	utm_medium = Column(String(100), nullable=True)
	utm_campaign = Column(String(200), nullable=True)

	# Scoring
	score = Column(Integer, nullable=False, default=0, server_default="0", comment="0–100 lead score")
	grade = Column(
		String(1),
		nullable=True,
		comment="A=90-100, B=70-89, C=50-69, D=<50",
	)

	# Lifecycle
	status = Column(
		String(30),
		nullable=False,
		default="NEW",
		server_default="NEW",
		comment="NEW/CONTACTED/WORKING/QUALIFIED/DISQUALIFIED/CONVERTED",
	)
	assigned_to = Column(UUID(as_uuid=False), nullable=True, index=True)

	# Conversion references (set when status=CONVERTED)
	converted_at = Column(DateTime(timezone=True), nullable=True)
	converted_account_id = Column(
		UUID(as_uuid=False),
		ForeignKey("crm_sales_account.id", ondelete="SET NULL"),
		nullable=True,
		index=True,
	)
	converted_contact_id = Column(
		UUID(as_uuid=False),
		ForeignKey("crm_sales_contact.id", ondelete="SET NULL"),
		nullable=True,
		index=True,
	)
	converted_opportunity_id = Column(
		UUID(as_uuid=False),
		nullable=True,
		index=True,
		comment="FK to crm_opportunity; not enforced to avoid circular dep",
	)

	description = Column(Text, nullable=True)

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

	converted_account: SalesAccount = relationship(
		"SalesAccount",
		foreign_keys=[converted_account_id],
		lazy="select",
	)
	converted_contact: SalesContact = relationship(
		"SalesContact",
		foreign_keys=[converted_contact_id],
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<Lead {self.first_name!r} {self.last_name!r} "
			f"status={self.status!r} score={self.score}>"
		)


# ---------------------------------------------------------------------------
# Opportunity
# ---------------------------------------------------------------------------

class Opportunity(RulesMixin, AuditMixin, Model):
	"""Sales opportunity — tracks deal progression through pipeline stages.

	amount_cents: deal size in cents (never float).
	probability: 0–100 integer percent.
	einstein_score: ML-predicted win probability (stored, computed externally).
	"""

	__allow_unmapped__ = True
	__tablename__ = "crm_opportunity"
	__table_args__ = (
		Index("ix_crm_opp_tenant", "tenant_id"),
		Index("ix_crm_opp_account", "account_id"),
		Index("ix_crm_opp_owner", "owner_id"),
		Index("ix_crm_opp_stage", "stage"),
		Index("ix_crm_opp_close_date", "expected_close_date"),
		Index("ix_crm_opp_forecast", "forecast_category"),
		{"extend_existing": True},
	)

	_rules_mutable_fields: frozenset[str] = frozenset({
		"stage", "probability", "forecast_category",
		"amount_cents", "owner_id", "expected_close_date",
	})
	__rules_context_fields__: list[str] = [
		"account.health_score",
		"account.account_type",
	]

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	# Relationships
	account_id = Column(
		UUID(as_uuid=False),
		ForeignKey("crm_sales_account.id", ondelete="RESTRICT"),
		nullable=False,
		index=True,
	)
	contact_id = Column(
		UUID(as_uuid=False),
		ForeignKey("crm_sales_contact.id", ondelete="SET NULL"),
		nullable=True,
		index=True,
	)

	# Core fields
	opportunity_name = Column(String(255), nullable=False)
	stage = Column(
		String(50),
		nullable=False,
		default="PROSPECTING",
		server_default="PROSPECTING",
		comment="PROSPECTING/QUALIFICATION/DEMO/PROPOSAL/NEGOTIATION/CLOSED_WON/CLOSED_LOST",
	)

	# Financials — integer cents
	amount_cents = Column(
		Integer,
		nullable=True,
		comment="Expected deal value in cents",
	)
	currency_code = Column(String(3), nullable=False, default="USD", comment="ISO 4217")

	# Probability & forecast
	probability = Column(
		Integer,
		nullable=False,
		default=0,
		server_default="0",
		comment="0–100 integer percent win probability",
	)
	forecast_category = Column(
		String(20),
		nullable=True,
		comment="PIPELINE/BEST_CASE/COMMIT/CLOSED",
	)

	# Dates
	expected_close_date = Column(Date, nullable=True)

	# Ownership
	owner_id = Column(UUID(as_uuid=False), nullable=True, index=True)

	# Classification
	lead_source = Column(String(50), nullable=True)
	type = Column(
		String(30),
		nullable=True,
		comment="NEW_BUSINESS/EXISTING_BUSINESS/RENEWAL",
	)

	# Outcome (set on close)
	reason_won = Column(Text, nullable=True)
	reason_lost = Column(Text, nullable=True)
	competitor = Column(String(200), nullable=True)
	closed_at = Column(DateTime(timezone=True), nullable=True)

	# AI scoring
	einstein_score = Column(
		Numeric(3, 1),
		nullable=True,
		comment="0.0–10.0 AI-predicted win probability (stored, not computed in DB)",
	)
	next_step = Column(Text, nullable=True)
	description = Column(Text, nullable=True)

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

	account: SalesAccount = relationship("SalesAccount", back_populates="opportunities", lazy="select")
	contact: SalesContact = relationship("SalesContact", lazy="select")
	activities: list[Activity] = relationship(
		"Activity",
		back_populates="opportunity",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<Opportunity {self.opportunity_name!r} stage={self.stage!r} "
			f"amount={self.amount_cents}¢>"
		)


# ---------------------------------------------------------------------------
# Activity
# ---------------------------------------------------------------------------

class Activity(AuditMixin, Model):
	"""Sales activity log — calls, emails, meetings, demos, notes.

	Polymorphic: links to contact and/or account and/or opportunity.
	direction: INBOUND (customer reached out) / OUTBOUND (we reached out).
	"""

	__allow_unmapped__ = True
	__tablename__ = "crm_activity"
	__table_args__ = (
		Index("ix_crm_activity_tenant", "tenant_id"),
		Index("ix_crm_activity_contact", "contact_id"),
		Index("ix_crm_activity_account", "account_id"),
		Index("ix_crm_activity_opportunity", "opportunity_id"),
		Index("ix_crm_activity_owner", "owner_id"),
		Index("ix_crm_activity_date", "activity_date"),
		Index("ix_crm_activity_type", "activity_type"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	activity_type = Column(
		String(30),
		nullable=False,
		comment="CALL/EMAIL/MEETING/DEMO/NOTE/LINKEDIN/OTHER",
	)
	subject = Column(String(255), nullable=False)
	description = Column(Text, nullable=True)
	status = Column(
		String(20),
		nullable=False,
		default="PLANNED",
		server_default="PLANNED",
		comment="PLANNED/COMPLETED/CANCELLED",
	)
	direction = Column(
		String(10),
		nullable=True,
		comment="INBOUND/OUTBOUND",
	)
	outcome = Column(String(200), nullable=True)
	duration_minutes = Column(Integer, nullable=True)
	activity_date = Column(DateTime(timezone=True), nullable=False)

	# Polymorphic links
	contact_id = Column(
		UUID(as_uuid=False),
		ForeignKey("crm_sales_contact.id", ondelete="SET NULL"),
		nullable=True,
		index=True,
	)
	account_id = Column(
		UUID(as_uuid=False),
		ForeignKey("crm_sales_account.id", ondelete="SET NULL"),
		nullable=True,
		index=True,
	)
	opportunity_id = Column(
		UUID(as_uuid=False),
		ForeignKey("crm_opportunity.id", ondelete="SET NULL"),
		nullable=True,
		index=True,
	)
	owner_id = Column(UUID(as_uuid=False), nullable=True, index=True)

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

	contact: SalesContact = relationship("SalesContact", back_populates="activities", lazy="select")
	account: SalesAccount = relationship("SalesAccount", back_populates="activities", lazy="select")
	opportunity: Opportunity = relationship("Opportunity", back_populates="activities", lazy="select")

	def __repr__(self) -> str:
		return (
			f"<Activity {self.activity_type!r} {self.subject!r} "
			f"status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# SalesTarget
# ---------------------------------------------------------------------------

class SalesTarget(AuditMixin, Model):
	"""Quota / target for a sales rep over a period.

	Append-only for target_amount changes — do not update, insert new row.
	achieved_amount_cents is updated by the service as deals close.
	"""

	__allow_unmapped__ = True
	__tablename__ = "crm_sales_target"
	__table_args__ = (
		UniqueConstraint("tenant_id", "owner_id", "period_id", "target_type",
		                 name="uq_crm_sales_target_owner_period_type"),
		Index("ix_crm_sales_target_tenant", "tenant_id"),
		Index("ix_crm_sales_target_owner", "owner_id"),
		Index("ix_crm_sales_target_period", "period_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	owner_id = Column(UUID(as_uuid=False), nullable=False, index=True, comment="FK to Employee/ab_user")
	period_id = Column(UUID(as_uuid=False), nullable=False, index=True, comment="FK to fiscal period")

	target_type = Column(
		String(20),
		nullable=False,
		default="REVENUE",
		comment="REVENUE/UNITS/DEALS",
	)
	product_id = Column(UUID(as_uuid=False), nullable=True, index=True, comment="NULL = all products")

	# Amounts — integer cents for REVENUE type; integer count for UNITS/DEALS
	target_amount_cents = Column(Integer, nullable=False, comment="Target in cents (REVENUE) or count (UNITS/DEALS)")
	achieved_amount_cents = Column(Integer, nullable=False, default=0, server_default="0")

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
			f"<SalesTarget owner={self.owner_id!r} type={self.target_type!r} "
			f"target={self.target_amount_cents} achieved={self.achieved_amount_cents}>"
		)


# ---------------------------------------------------------------------------
# SalesForecast
# ---------------------------------------------------------------------------

class SalesForecast(AuditMixin, Model):
	"""Period-level sales forecast submitted by a rep or manager.

	Immutable once submitted — corrections create a new row.
	ai_forecast_cents is computed externally and stored here.
	"""

	__allow_unmapped__ = True
	__tablename__ = "crm_sales_forecast"
	__table_args__ = (
		Index("ix_crm_forecast_tenant", "tenant_id"),
		Index("ix_crm_forecast_owner_period", "owner_id", "period_id"),
		Index("ix_crm_forecast_period", "period_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	period_id = Column(UUID(as_uuid=False), nullable=False, index=True, comment="FK to fiscal period")
	owner_id = Column(UUID(as_uuid=False), nullable=False, index=True, comment="FK to Employee/ab_user")

	# Forecast buckets — integer cents
	pipeline_cents = Column(Integer, nullable=False, default=0, comment="PIPELINE category total")
	best_case_cents = Column(Integer, nullable=False, default=0, comment="BEST_CASE category total")
	commit_cents = Column(Integer, nullable=False, default=0, comment="COMMIT category total")
	closed_cents = Column(Integer, nullable=False, default=0, comment="CLOSED category total (actuals)")
	ai_forecast_cents = Column(Integer, nullable=True, comment="AI-computed forecast; NULL until computed")

	submitted_at = Column(DateTime(timezone=True), nullable=True, comment="NULL = draft, set = submitted")

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
			f"<SalesForecast owner={self.owner_id!r} period={self.period_id!r} "
			f"commit={self.commit_cents}¢>"
		)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"SalesAccount",
	"SalesContact",
	"Lead",
	"Opportunity",
	"Activity",
	"SalesTarget",
	"SalesForecast",
]
