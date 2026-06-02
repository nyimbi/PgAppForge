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
	Boolean,
	Column,
	Date,
	DateTime,
	ForeignKey,
	Index,
	Integer,
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

CAMPAIGN_TYPE = ("EMAIL", "SMS", "PAID", "EVENT", "WEBINAR", "SOCIAL")
CAMPAIGN_STATUS = ("PLANNING", "ACTIVE", "PAUSED", "COMPLETED", "ARCHIVED")
MEMBER_TYPE = ("LEAD", "CONTACT")
MEMBER_STATUS = ("SENT", "DELIVERED", "OPENED", "CLICKED", "RESPONDED", "UNSUBSCRIBED")
LIST_TYPE = ("STATIC", "DYNAMIC")
STEP_TYPE = ("EMAIL", "SMS", "WAIT", "BRANCH", "SCORE")


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
	campaign_name = Column(String(200), nullable=False)
	campaign_type = Column(
		String(15),
		nullable=False,
		comment="EMAIL|SMS|PAID|EVENT|WEBINAR|SOCIAL",
	)
	status = Column(
		String(15),
		nullable=False,
		default="PLANNING",
		server_default="PLANNING",
		comment="PLANNING|ACTIVE|PAUSED|COMPLETED|ARCHIVED",
	)
	start_date = Column(Date, nullable=True)
	end_date = Column(Date, nullable=True)

	# Budget — integer cents
	budget_cents = Column(
		Integer,
		nullable=True,
		comment="Approved campaign budget in cents",
	)
	actual_cost_cents = Column(
		Integer,
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
	owner_id = Column(UUID(as_uuid=False), nullable=True, index=True, comment="FK Employee.id")

	# Performance targets and actuals
	expected_leads = Column(Integer, nullable=True)
	actual_leads = Column(Integer, nullable=False, default=0, server_default="0")
	expected_revenue_cents = Column(Integer, nullable=True, comment="Expected pipeline contribution in cents")
	actual_revenue_cents = Column(
		Integer,
		nullable=False,
		default=0,
		server_default="0",
		comment="Attributed revenue in cents",
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

	def __repr__(self) -> str:
		return f"<Campaign {self.campaign_name!r} status={self.status!r}>"


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
	list_type = Column(
		String(10),
		nullable=False,
		default="STATIC",
		comment="STATIC|DYNAMIC",
	)
	filter_criteria: Any = Column(
		JSONB,
		nullable=False,
		default=dict,
		server_default="{}",
		comment="For DYNAMIC lists: query filter spec; empty for STATIC",
	)
	member_count = Column(
		Integer,
		nullable=False,
		default=0,
		server_default="0",
		comment="Denormalised count; refreshed on add/remove or DYNAMIC re-evaluation",
	)
	last_updated_at = Column(
		DateTime(timezone=True),
		nullable=True,
		comment="Last time member_count was refreshed",
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
		return f"<MarketingList {self.name!r} type={self.list_type!r} count={self.member_count}>"


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
	"EmailTemplate",
	"CampaignMember",
	"MarketingList",
	"JourneyStep",
]
