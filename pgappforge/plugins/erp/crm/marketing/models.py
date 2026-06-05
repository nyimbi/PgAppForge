"""
pgappforge/plugins/erp/crm/marketing/models.py

SQLAlchemy models for the Marketing plugin.

Design rules:
  - All PKs: UUID v4, server_default=gen_random_uuid()
  - All timestamps: TIMESTAMPTZ DEFAULT NOW()
  - All monetary amounts: INTEGER cents — never float
  - All models: tenant_id UUID NOT NULL
  - JSONB for target_audience, filter_criteria, config
  - ARRAY(String) for tags
  - lazy='select' throughout

Table prefix: mkt_
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
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import relationship

from pgappforge.models.sqla import Model
from pgappforge.plugins.audit import AuditMixin
from pgappforge.plugins.rules.mixin import RulesMixin


def _uuid4() -> str:
	return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

CAMPAIGN_TYPE = ("EMAIL", "SMS", "PAID_ADS", "EVENT", "WEBINAR", "SOCIAL", "CONTENT")
CAMPAIGN_STATUS = ("DRAFT", "SCHEDULED", "ACTIVE", "PAUSED", "COMPLETED", "CANCELLED", "ARCHIVED")
CAMPAIGN_GOAL_TYPE = ("AWARENESS", "LEADS", "PIPELINE", "RETENTION", "REVENUE")
MEMBER_TYPE = ("LEAD", "CONTACT")
MEMBER_STATUS = ("SENT", "DELIVERED", "OPENED", "CLICKED", "RESPONDED", "UNSUBSCRIBED")
LIST_TYPE = ("STATIC", "DYNAMIC")
LIST_MEMBER_STATUS = ("ACTIVE", "UNSUBSCRIBED", "BOUNCED")
STEP_TYPE = ("EMAIL", "SMS", "WAIT", "BRANCH", "SCORE")
ASSET_TYPE = ("EMAIL_TEMPLATE", "LANDING_PAGE", "SMS", "AD_COPY", "SOCIAL_POST")
ASSET_STATUS = ("DRAFT", "APPROVED", "SENT")
LEAD_STATUS = ("NEW", "CONTACTED", "QUALIFIED", "DISQUALIFIED", "CONVERTED")
LEAD_ACTIVITY_TYPE = ("EMAIL_OPEN", "EMAIL_CLICK", "FORM_SUBMIT", "PAGE_VIEW", "CALL", "MEETING", "DOWNLOAD")


# ---------------------------------------------------------------------------
# MarketingList
# ---------------------------------------------------------------------------

class MarketingList(AuditMixin, Model):
	"""Segmentation list — either STATIC (explicit members) or DYNAMIC (query-driven)."""

	__allow_unmapped__ = True
	__tablename__ = "mkt_list"
	__table_args__ = (
		UniqueConstraint("tenant_id", "name", name="uq_mkt_list_tenant_name"),
		Index("ix_mkt_list_tenant", "tenant_id"),
		Index("ix_mkt_list_type", "list_type"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	name = Column(String(200), nullable=False)
	description = Column(Text, nullable=True)
	list_type = Column(
		String(10),
		nullable=False,
		default="STATIC",
		comment="STATIC|DYNAMIC",
	)
	source = Column(String(50), nullable=True, comment="Origin channel e.g. IMPORT, WEBFORM, SYNC")
	filter_criteria: Any = Column(
		JSONB,
		nullable=True,
		comment="For DYNAMIC lists: query filter spec; null for STATIC",
	)
	member_count = Column(
		Integer,
		nullable=False,
		default=0,
		server_default="0",
		comment="Denormalised count; refreshed on add/remove or DYNAMIC re-evaluation",
	)
	last_synced_at = Column(
		DateTime(timezone=True),
		nullable=True,
		comment="Last time dynamic list was re-evaluated",
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

	list_members: list[MarketingListMember] = relationship(
		"MarketingListMember",
		back_populates="marketing_list",
		cascade="all, delete-orphan",
		lazy="select",
	)

	def __repr__(self) -> str:
		return f"<MarketingList {self.name!r} type={self.list_type!r} count={self.member_count}>"


# ---------------------------------------------------------------------------
# MarketingListMember
# ---------------------------------------------------------------------------

class MarketingListMember(Model):
	"""Membership row linking a Party (contact or lead) to a MarketingList."""

	__allow_unmapped__ = True
	__tablename__ = "mkt_list_member"
	__table_args__ = (
		UniqueConstraint("list_id", "party_id", name="uq_mkt_list_member_list_party"),
		Index("ix_mkt_list_member_list", "list_id"),
		Index("ix_mkt_list_member_party", "party_id"),
		Index("ix_mkt_list_member_tenant", "tenant_id"),
		Index("ix_mkt_list_member_status", "status"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	list_id = Column(
		UUID(as_uuid=False),
		ForeignKey("mkt_list.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)
	# Soft FK — cross-schema compatible with erp_party
	party_id = Column(
		UUID(as_uuid=False),
		nullable=False,
		index=True,
		comment="FK erp_party.id or mkt_lead.id",
	)
	added_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	status = Column(
		String(15),
		nullable=False,
		default="ACTIVE",
		server_default="ACTIVE",
		comment="ACTIVE|UNSUBSCRIBED|BOUNCED",
	)
	source = Column(
		String(50),
		nullable=True,
		comment="How this member was added: MANUAL, IMPORT, DYNAMIC, API",
	)

	marketing_list: MarketingList = relationship(
		"MarketingList",
		back_populates="list_members",
		lazy="select",
	)

	def __repr__(self) -> str:
		return f"<MarketingListMember list={self.list_id!r} party={self.party_id!r} status={self.status!r}>"


# ---------------------------------------------------------------------------
# Campaign
# ---------------------------------------------------------------------------

class Campaign(RulesMixin, AuditMixin, Model):
	"""Marketing campaign — container for budget, schedule, and member activity.

	All monetary amounts in integer cents.
	"""

	__allow_unmapped__ = True
	__tablename__ = "mkt_campaign"
	__table_args__ = (
		UniqueConstraint("tenant_id", "code", name="uq_mkt_campaign_tenant_code"),
		UniqueConstraint("tenant_id", "campaign_name", name="uq_mkt_campaign_tenant_name"),
		Index("ix_mkt_campaign_tenant", "tenant_id"),
		Index("ix_mkt_campaign_status", "status"),
		Index("ix_mkt_campaign_type", "campaign_type"),
		Index("ix_mkt_campaign_owner", "owner_id"),
		Index("ix_mkt_campaign_dates", "start_date", "end_date"),
		{"extend_existing": True},
	)

	_rules_mutable_fields: frozenset[str] = frozenset({
		"status", "actual_cost_cents", "actual_leads", "actual_revenue_cents",
	})
	__rules_context_fields__: list[str] = []

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	# Short human-readable identifier e.g. "Q1-2026-EMAIL"
	code = Column(
		String(20),
		nullable=True,
		comment="Short unique campaign code per tenant",
	)
	campaign_name = Column(String(200), nullable=False)
	campaign_type = Column(
		String(15),
		nullable=False,
		comment="EMAIL|SMS|PAID_ADS|EVENT|WEBINAR|SOCIAL|CONTENT",
	)
	status = Column(
		String(15),
		nullable=False,
		default="DRAFT",
		server_default="DRAFT",
		comment="DRAFT|SCHEDULED|ACTIVE|PAUSED|COMPLETED|CANCELLED|ARCHIVED",
	)
	goal_type = Column(
		String(15),
		nullable=True,
		comment="AWARENESS|LEADS|PIPELINE|RETENTION|REVENUE",
	)
	start_date = Column(Date, nullable=True)
	end_date = Column(Date, nullable=True)

	# Budget — integer cents
	budget_cents = Column(
		BigInteger,
		nullable=True,
		comment="Approved campaign budget in cents",
	)
	actual_cost_cents = Column(
		BigInteger,
		nullable=False,
		default=0,
		server_default="0",
		comment="Actual spend to date in cents",
	)

	# Audience
	target_audience: Any = Column(
		JSONB,
		nullable=False,
		default=dict,
		server_default="{}",
		comment='Audience definition e.g. {"industry": "tech", "region": "EMEA"}',
	)
	target_list_id = Column(
		UUID(as_uuid=False),
		ForeignKey("mkt_list.id", ondelete="SET NULL"),
		nullable=True,
		index=True,
		comment="Primary marketing list this campaign targets",
	)
	owner_id = Column(UUID(as_uuid=False), nullable=True, index=True, comment="FK Employee.id")

	# Performance targets
	target_leads = Column(Integer, nullable=True, comment="Desired lead count")
	target_revenue_cents = Column(BigInteger, nullable=True, comment="Desired revenue attribution in cents")

	# Actuals — kept for backward compat; canonical metrics live in CampaignMetrics
	expected_leads = Column(Integer, nullable=True)
	actual_leads = Column(Integer, nullable=False, default=0, server_default="0")
	expected_revenue_cents = Column(BigInteger, nullable=True, comment="Expected pipeline contribution in cents")
	actual_revenue_cents = Column(
		BigInteger,
		nullable=False,
		default=0,
		server_default="0",
		comment="Attributed revenue in cents — mirrored from CampaignMetrics",
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

	members: list[CampaignMember] = relationship(
		"CampaignMember",
		back_populates="campaign",
		cascade="all, delete-orphan",
		lazy="select",
	)
	assets: list[CampaignAsset] = relationship(
		"CampaignAsset",
		back_populates="campaign",
		cascade="all, delete-orphan",
		lazy="select",
	)
	metrics: CampaignMetrics | None = relationship(
		"CampaignMetrics",
		back_populates="campaign",
		uselist=False,
		cascade="all, delete-orphan",
		lazy="select",
	)
	target_list: MarketingList | None = relationship(
		"MarketingList",
		foreign_keys=[target_list_id],
		lazy="select",
	)

	def __repr__(self) -> str:
		return f"<Campaign {self.campaign_name!r} status={self.status!r}>"


# ---------------------------------------------------------------------------
# CampaignAsset
# ---------------------------------------------------------------------------

class CampaignAsset(AuditMixin, Model):
	"""An individual deliverable (email, SMS, ad copy, etc.) belonging to a campaign."""

	__allow_unmapped__ = True
	__tablename__ = "mkt_campaign_asset"
	__table_args__ = (
		Index("ix_mkt_asset_campaign", "campaign_id"),
		Index("ix_mkt_asset_tenant", "tenant_id"),
		Index("ix_mkt_asset_type", "asset_type"),
		Index("ix_mkt_asset_status", "status"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	campaign_id = Column(
		UUID(as_uuid=False),
		ForeignKey("mkt_campaign.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)
	asset_type = Column(
		String(20),
		nullable=False,
		comment="EMAIL_TEMPLATE|LANDING_PAGE|SMS|AD_COPY|SOCIAL_POST",
	)
	name = Column(String(200), nullable=False)
	content = Column(Text, nullable=False, default="", comment="HTML body, SMS text, or ad copy")
	subject_line = Column(String(200), nullable=True, comment="Email subject line")
	status = Column(
		String(10),
		nullable=False,
		default="DRAFT",
		server_default="DRAFT",
		comment="DRAFT|APPROVED|SENT",
	)
	send_at = Column(
		DateTime(timezone=True),
		nullable=True,
		comment="Scheduled send time; null = not yet scheduled",
	)
	sent_count = Column(
		Integer,
		nullable=False,
		default=0,
		server_default="0",
		comment="Number of recipients this asset was sent to",
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

	campaign: Campaign = relationship("Campaign", back_populates="assets", lazy="select")

	def __repr__(self) -> str:
		return f"<CampaignAsset {self.name!r} type={self.asset_type!r} status={self.status!r}>"


# ---------------------------------------------------------------------------
# CampaignMetrics
# ---------------------------------------------------------------------------

class CampaignMetrics(Model):
	"""Aggregated delivery and engagement metrics for a Campaign.

	One row per campaign (unique FK). Updated by record_campaign_activity().
	"""

	__allow_unmapped__ = True
	__tablename__ = "mkt_campaign_metrics"
	__table_args__ = (
		UniqueConstraint("campaign_id", name="uq_mkt_metrics_campaign"),
		Index("ix_mkt_metrics_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	campaign_id = Column(
		UUID(as_uuid=False),
		ForeignKey("mkt_campaign.id", ondelete="CASCADE"),
		nullable=False,
		unique=True,
	)
	sent_count = Column(Integer, nullable=False, default=0, server_default="0")
	delivered_count = Column(Integer, nullable=False, default=0, server_default="0")
	open_count = Column(Integer, nullable=False, default=0, server_default="0")
	click_count = Column(Integer, nullable=False, default=0, server_default="0")
	bounce_count = Column(Integer, nullable=False, default=0, server_default="0")
	unsubscribe_count = Column(Integer, nullable=False, default=0, server_default="0")
	conversion_count = Column(Integer, nullable=False, default=0, server_default="0")
	revenue_attributed_cents = Column(
		BigInteger,
		nullable=False,
		default=0,
		server_default="0",
	)
	cost_per_lead_cents = Column(
		BigInteger,
		nullable=True,
		comment="Computed: actual_cost_cents / conversion_count",
	)
	roi_pct = Column(
		Numeric(8, 2),
		nullable=True,
		comment="(revenue - cost) / cost * 100",
	)
	updated_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		onupdate=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	campaign: Campaign = relationship("Campaign", back_populates="metrics", lazy="select")

	def __repr__(self) -> str:
		return (
			f"<CampaignMetrics campaign={self.campaign_id!r} "
			f"sent={self.sent_count} opens={self.open_count} clicks={self.click_count}>"
		)


# ---------------------------------------------------------------------------
# EmailTemplate
# ---------------------------------------------------------------------------

class EmailTemplate(AuditMixin, Model):
	"""Reusable email template for campaign sends."""

	__allow_unmapped__ = True
	__tablename__ = "mkt_email_template"
	__table_args__ = (
		UniqueConstraint("tenant_id", "name", name="uq_mkt_email_template_tenant_name"),
		Index("ix_mkt_email_template_tenant", "tenant_id"),
		Index("ix_mkt_email_template_active", "is_active"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	name = Column(String(200), nullable=False)
	subject = Column(String(500), nullable=False)
	html_body = Column(Text, nullable=False)
	text_body = Column(Text, nullable=True, comment="Plain-text fallback")
	sender_name = Column(String(100), nullable=False)
	sender_email = Column(String(255), nullable=False)
	is_active = Column(
		Boolean,
		nullable=False,
		default=True,
		server_default="true",
	)
	tags = Column(
		ARRAY(String),
		nullable=False,
		default=list,
		server_default="{}",
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
		return f"<EmailTemplate {self.name!r} subject={self.subject!r}>"


# ---------------------------------------------------------------------------
# CampaignMember
# ---------------------------------------------------------------------------

class CampaignMember(Model):
	"""Junction: Party → Campaign with engagement status tracking.

	Append-only status progression — never delete, use UNSUBSCRIBED status.
	"""

	__allow_unmapped__ = True
	__tablename__ = "mkt_campaign_member"
	__table_args__ = (
		UniqueConstraint("campaign_id", "party_id", name="uq_mkt_member_campaign_party"),
		Index("ix_mkt_member_campaign", "campaign_id"),
		Index("ix_mkt_member_party", "party_id"),
		Index("ix_mkt_member_tenant", "tenant_id"),
		Index("ix_mkt_member_status", "status"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	campaign_id = Column(
		UUID(as_uuid=False),
		ForeignKey("mkt_campaign.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)
	# Soft FK to foundation.Party — no hard constraint to stay cross-schema compatible
	party_id = Column(
		UUID(as_uuid=False),
		nullable=False,
		index=True,
		comment="FK foundation.Party.id",
	)
	member_type = Column(
		String(10),
		nullable=False,
		comment="LEAD|CONTACT",
	)
	status = Column(
		String(15),
		nullable=False,
		default="SENT",
		server_default="SENT",
		comment="SENT|DELIVERED|OPENED|CLICKED|RESPONDED|UNSUBSCRIBED",
	)
	responded_at = Column(DateTime(timezone=True), nullable=True)
	source_campaign_id = Column(
		UUID(as_uuid=False),
		nullable=True,
		index=True,
		comment="Original campaign if member was forwarded/re-used",
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

	campaign: Campaign = relationship("Campaign", back_populates="members", lazy="select")

	def __repr__(self) -> str:
		return f"<CampaignMember campaign={self.campaign_id!r} party={self.party_id!r} status={self.status!r}>"


# ---------------------------------------------------------------------------
# MarketingLead
# ---------------------------------------------------------------------------

class MarketingLead(AuditMixin, Model):
	"""Marketing-qualified lead — pre-conversion prospect.

	Unique on (tenant_id, email) — one email address = one lead per tenant.
	On conversion, a Party/Contact record is created via convert_lead().
	"""

	__allow_unmapped__ = True
	__tablename__ = "mkt_lead"
	__table_args__ = (
		UniqueConstraint("tenant_id", "email", name="uq_mkt_lead_tenant_email"),
		Index("ix_mkt_lead_tenant", "tenant_id"),
		Index("ix_mkt_lead_status", "status"),
		Index("ix_mkt_lead_score", "lead_score"),
		Index("ix_mkt_lead_assigned", "assigned_to"),
		Index("ix_mkt_lead_source_campaign", "source_campaign_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	first_name = Column(String(100), nullable=False)
	last_name = Column(String(100), nullable=False)
	email = Column(String(200), nullable=False)
	phone = Column(String(50), nullable=True)
	company = Column(String(200), nullable=True)
	job_title = Column(String(200), nullable=True)
	source = Column(
		String(50),
		nullable=False,
		default="UNKNOWN",
		comment="WEBFORM|IMPORT|REFERRAL|PAID_AD|ORGANIC|EVENT|UNKNOWN",
	)
	source_campaign_id = Column(
		UUID(as_uuid=False),
		ForeignKey("mkt_campaign.id", ondelete="SET NULL"),
		nullable=True,
		index=True,
	)
	status = Column(
		String(15),
		nullable=False,
		default="NEW",
		server_default="NEW",
		comment="NEW|CONTACTED|QUALIFIED|DISQUALIFIED|CONVERTED",
	)
	lead_score = Column(
		Integer,
		nullable=False,
		default=0,
		server_default="0",
		comment="Computed engagement score; updated by score_lead()",
	)
	assigned_to = Column(
		UUID(as_uuid=False),
		nullable=True,
		index=True,
		comment="FK Employee.id — sales rep responsible for this lead",
	)
	converted_at = Column(DateTime(timezone=True), nullable=True)
	converted_contact_id = Column(
		UUID(as_uuid=False),
		nullable=True,
		comment="FK erp_party.id created on conversion",
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

	activities: list[LeadActivity] = relationship(
		"LeadActivity",
		back_populates="lead",
		cascade="all, delete-orphan",
		lazy="select",
		order_by="LeadActivity.occurred_at.desc()",
	)
	source_campaign: Campaign | None = relationship(
		"Campaign",
		foreign_keys=[source_campaign_id],
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<MarketingLead {self.first_name} {self.last_name} "
			f"email={self.email!r} score={self.lead_score} status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# LeadActivity
# ---------------------------------------------------------------------------

class LeadActivity(Model):
	"""Immutable audit trail of touchpoint events for a MarketingLead.

	Each row increments or decrements lead_score via score_delta.
	"""

	__allow_unmapped__ = True
	__tablename__ = "mkt_lead_activity"
	__table_args__ = (
		Index("ix_mkt_lead_activity_lead", "lead_id"),
		Index("ix_mkt_lead_activity_type", "activity_type"),
		Index("ix_mkt_lead_activity_occurred", "occurred_at"),
		Index("ix_mkt_lead_activity_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	lead_id = Column(
		UUID(as_uuid=False),
		ForeignKey("mkt_lead.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)
	activity_type = Column(
		String(20),
		nullable=False,
		comment="EMAIL_OPEN|EMAIL_CLICK|FORM_SUBMIT|PAGE_VIEW|CALL|MEETING|DOWNLOAD",
	)
	occurred_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	description = Column(Text, nullable=True)
	score_delta = Column(
		Integer,
		nullable=False,
		default=0,
		server_default="0",
		comment="Points added (positive) or decayed (negative) by this activity",
	)

	lead: MarketingLead = relationship("MarketingLead", back_populates="activities", lazy="select")

	def __repr__(self) -> str:
		return f"<LeadActivity lead={self.lead_id!r} type={self.activity_type!r} delta={self.score_delta:+d}>"


# ---------------------------------------------------------------------------
# JourneyStep
# ---------------------------------------------------------------------------

class JourneyStep(AuditMixin, Model):
	"""One step in a multi-step marketing automation journey.

	journey_id groups steps belonging to the same journey (no separate Journey
	table here — campaigns own journeys via journey_id linking back to campaign).

	next_step_id / branch_yes_id / branch_no_id form a DAG — null = terminal.
	"""

	__allow_unmapped__ = True
	__tablename__ = "mkt_journey_step"
	__table_args__ = (
		Index("ix_mkt_journey_step_journey", "journey_id"),
		Index("ix_mkt_journey_step_tenant", "tenant_id"),
		Index("ix_mkt_journey_step_type", "step_type"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	journey_id = Column(
		UUID(as_uuid=False),
		nullable=False,
		index=True,
		comment="Groups all steps for one journey (links to Campaign.id or standalone journey UUID)",
	)
	step_number = Column(Integer, nullable=False, comment="Ordering within the journey")
	step_type = Column(
		String(10),
		nullable=False,
		comment="EMAIL|SMS|WAIT|BRANCH|SCORE",
	)
	config: Any = Column(
		JSONB,
		nullable=False,
		default=dict,
		server_default="{}",
		comment='Step-specific config e.g. {"template_id": "...", "wait_hours": 48}',
	)

	# DAG edges
	next_step_id = Column(
		UUID(as_uuid=False),
		ForeignKey("mkt_journey_step.id", ondelete="SET NULL"),
		nullable=True,
		comment="Default next step (for non-BRANCH types)",
	)
	branch_yes_id = Column(
		UUID(as_uuid=False),
		ForeignKey("mkt_journey_step.id", ondelete="SET NULL"),
		nullable=True,
		comment="BRANCH: step taken when condition is true",
	)
	branch_no_id = Column(
		UUID(as_uuid=False),
		ForeignKey("mkt_journey_step.id", ondelete="SET NULL"),
		nullable=True,
		comment="BRANCH: step taken when condition is false",
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

	# Self-referential relationships
	next_step: JourneyStep = relationship(
		"JourneyStep",
		foreign_keys=[next_step_id],
		lazy="select",
		remote_side="JourneyStep.id",
	)
	branch_yes: JourneyStep = relationship(
		"JourneyStep",
		foreign_keys=[branch_yes_id],
		lazy="select",
		remote_side="JourneyStep.id",
	)
	branch_no: JourneyStep = relationship(
		"JourneyStep",
		foreign_keys=[branch_no_id],
		lazy="select",
		remote_side="JourneyStep.id",
	)

	def __repr__(self) -> str:
		return f"<JourneyStep journey={self.journey_id!r} step={self.step_number} type={self.step_type!r}>"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"Campaign",
	"CampaignAsset",
	"CampaignMember",
	"CampaignMetrics",
	"EmailTemplate",
	"JourneyStep",
	"MarketingLead",
	"LeadActivity",
	"MarketingList",
	"MarketingListMember",
	# Enum tuples (useful for validation in views/serialisers)
	"CAMPAIGN_TYPE",
	"CAMPAIGN_STATUS",
	"CAMPAIGN_GOAL_TYPE",
	"MEMBER_STATUS",
	"LIST_TYPE",
	"LIST_MEMBER_STATUS",
	"ASSET_TYPE",
	"ASSET_STATUS",
	"LEAD_STATUS",
	"LEAD_ACTIVITY_TYPE",
]
