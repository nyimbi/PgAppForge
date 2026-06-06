"""
pgappforge/plugins/erp/crm/marketing_automation/models.py

SQLAlchemy models for the Marketing Automation plugin.

Design rules enforced:
  - All PKs: UUID v4, server_default=gen_random_uuid()
  - All timestamps: TIMESTAMPTZ (DateTime(timezone=True)) DEFAULT NOW()
  - All models: tenant_id UUID NOT NULL
  - Monetary amounts: INTEGER cents ONLY — never Numeric/float for money
  - AuditMixin on all mutable entities
  - lazy='select' throughout (SA 2.x)
  - JSONB for semi-structured data (target_segment, ab_variants, utm_params, goals, metadata_)
  - PostgreSQL only — JSONB, UUID, DateTime(timezone=True)

Table name convention: mkt_<entity>
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
# Enumerations (VARCHAR — no SA Enum, stays PG-only)
# ---------------------------------------------------------------------------

CAMPAIGN_TYPE = ("EMAIL", "DRIP", "SMS", "PUSH", "SOCIAL", "EVENT", "MIXED")
CAMPAIGN_STATUS = ("DRAFT", "ACTIVE", "PAUSED", "COMPLETED", "CANCELLED")
SEQUENCE_STEP_TYPE = ("EMAIL", "SMS", "WAIT", "CONDITION", "WEBHOOK")
CONTACT_STATUS = ("ENROLLED", "ACTIVE", "COMPLETED", "UNSUBSCRIBED", "BOUNCED")
LEAD_GRADE = ("A+", "A", "B", "C", "D")
ATTRIBUTION_MODEL = ("FIRST_TOUCH", "LAST_TOUCH", "LINEAR", "TIME_DECAY")


# ---------------------------------------------------------------------------
# MarketingCampaign
# ---------------------------------------------------------------------------

class MarketingCampaign(AuditMixin, Model):
	"""Top-level campaign entity.

	ab_variants JSONB schema: list of {id, name, percentage, subject_line, body_template}
	target_segment JSONB schema: rules-engine conditions array — same format as
	  RulesEngine.conditions_json so the same evaluator can filter contacts.
	goals JSONB schema: {conversions: int, revenue_cents: int}
	utm_params JSONB schema: {source, medium, campaign, content}
	"""

	__tablename__ = "mkt_campaign"
	__table_args__ = (
		Index("ix_mkt_campaign_tenant_status", "tenant_id", "status"),
		Index("ix_mkt_campaign_tenant_type", "tenant_id", "campaign_type"),
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False)

	name = Column(String(300), nullable=False)
	description = Column(Text, nullable=True)
	campaign_type = Column(String(30), nullable=False, default="EMAIL")
	status = Column(String(20), nullable=False, default="DRAFT")

	entity_id = Column(String(50), nullable=True)

	start_date = Column(Date, nullable=True)
	end_date = Column(Date, nullable=True)

	budget_cents = Column(BigInteger, nullable=False, default=0)
	spent_cents = Column(BigInteger, nullable=False, default=0)

	target_segment = Column(JSONB, nullable=False, default=dict, server_default=sa.text("'{}'::jsonb"))
	ab_test_enabled = Column(Boolean, nullable=False, default=False)
	ab_variants = Column(JSONB, nullable=False, default=list, server_default=sa.text("'[]'::jsonb"))
	utm_params = Column(JSONB, nullable=False, default=dict, server_default=sa.text("'{}'::jsonb"))
	goals = Column(JSONB, nullable=False, default=dict, server_default=sa.text("'{}'::jsonb"))

	# Relationships
	sequences = relationship("MarketingSequence", back_populates="campaign", lazy="select", cascade="all, delete-orphan")
	contacts = relationship("CampaignContact", back_populates="campaign", lazy="select", cascade="all, delete-orphan")
	attributions = relationship("CampaignAttribution", back_populates="campaign", lazy="select", cascade="all, delete-orphan")

	def __repr__(self) -> str:
		return f"<MarketingCampaign id={self.id} name={self.name!r} status={self.status}>"


# ---------------------------------------------------------------------------
# MarketingSequence
# ---------------------------------------------------------------------------

class MarketingSequence(AuditMixin, Model):
	"""Ordered drip sequence step within a campaign.

	conditions_json: rules-engine conditions array — step fires only when all
	  conditions evaluate True against the contact context.
	delay_hours=0 means immediate execution after the previous step (or trigger).
	"""

	__tablename__ = "mkt_sequence"
	__table_args__ = (
		Index("ix_mkt_sequence_campaign_step", "campaign_id", "step_number"),
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False)

	campaign_id = Column(
		UUID(as_uuid=False),
		ForeignKey("mkt_campaign.id", ondelete="CASCADE"),
		nullable=False,
	)
	step_number = Column(Integer, nullable=False)
	step_type = Column(String(30), nullable=False, default="EMAIL")
	delay_hours = Column(Integer, nullable=False, default=0)
	conditions_json = Column(JSONB, nullable=False, default=list, server_default=sa.text("'[]'::jsonb"))

	template_id = Column(String(50), nullable=True)
	subject_line = Column(String(500), nullable=True)
	body_text = Column(Text, nullable=True)
	webhook_url = Column(Text, nullable=True)

	# Relationships
	campaign = relationship("MarketingCampaign", back_populates="sequences", lazy="select")

	def __repr__(self) -> str:
		return f"<MarketingSequence campaign={self.campaign_id} step={self.step_number} type={self.step_type}>"


# ---------------------------------------------------------------------------
# CampaignContact
# ---------------------------------------------------------------------------

class CampaignContact(AuditMixin, Model):
	"""Enrollment of a contact into a campaign.

	metadata_ JSONB: arbitrary key-value bag for channel-specific data
	  (e.g. phone country code, preference flags, custom merge fields).
	ab_variant: id of the assigned variant from MarketingCampaign.ab_variants,
	  null if campaign.ab_test_enabled is False.
	"""

	__tablename__ = "mkt_contact"
	__table_args__ = (
		UniqueConstraint("campaign_id", "contact_id", name="uq_mkt_contact_campaign_contact"),
		Index("ix_mkt_contact_campaign_status", "campaign_id", "status"),
		Index("ix_mkt_contact_tenant_contact", "tenant_id", "contact_id"),
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False)

	campaign_id = Column(
		UUID(as_uuid=False),
		ForeignKey("mkt_campaign.id", ondelete="CASCADE"),
		nullable=False,
	)
	contact_id = Column(String(50), nullable=False)
	email = Column(String(320), nullable=True)
	phone = Column(String(30), nullable=True)

	status = Column(String(20), nullable=False, default="ENROLLED")
	ab_variant = Column(String(50), nullable=True)

	enrolled_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	current_step = Column(Integer, nullable=False, default=0)
	next_action_at = Column(DateTime(timezone=True), nullable=True)
	metadata_ = Column("metadata_", JSONB, nullable=False, default=dict, server_default=sa.text("'{}'::jsonb"))

	# Relationships
	campaign = relationship("MarketingCampaign", back_populates="contacts", lazy="select")

	def __repr__(self) -> str:
		return f"<CampaignContact campaign={self.campaign_id} contact={self.contact_id} status={self.status}>"


# ---------------------------------------------------------------------------
# LeadScore
# ---------------------------------------------------------------------------

class LeadScore(AuditMixin, Model):
	"""Aggregated lead score per contact per tenant.

	scoring_factors JSONB: list of {factor: str, delta: int, ts: ISO-string}
	grade is derived from score:
	  A+: 90+  A: 70-89  B: 50-69  C: 30-49  D: 0-29
	"""

	__tablename__ = "mkt_lead_score"
	__table_args__ = (
		UniqueConstraint("tenant_id", "contact_id", name="uq_mkt_lead_score_tenant_contact"),
		Index("ix_mkt_lead_score_tenant_score", "tenant_id", sa.text("score DESC")),
		Index("ix_mkt_lead_score_tenant_grade", "tenant_id", "grade"),
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False)

	contact_id = Column(String(50), nullable=False)
	score = Column(Integer, nullable=False, default=0)
	grade = Column(String(5), nullable=False, default="D")
	scoring_factors = Column(JSONB, nullable=False, default=list, server_default=sa.text("'[]'::jsonb"))
	last_activity_at = Column(DateTime(timezone=True), nullable=True)
	converted = Column(Boolean, nullable=False, default=False)

	def __repr__(self) -> str:
		return f"<LeadScore contact={self.contact_id} score={self.score} grade={self.grade}>"


# ---------------------------------------------------------------------------
# CampaignAttribution
# ---------------------------------------------------------------------------

class CampaignAttribution(AuditMixin, Model):
	"""Revenue attribution record linking a campaign to an opportunity.

	Supports multi-touch attribution models.  One row per attribution event
	(a single opportunity may have multiple rows for LINEAR/TIME_DECAY models).
	"""

	__tablename__ = "mkt_attribution"
	__table_args__ = (
		Index("ix_mkt_attribution_campaign_at", "campaign_id", "attributed_at"),
		Index("ix_mkt_attribution_tenant_at", "tenant_id", "attributed_at"),
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False)

	campaign_id = Column(
		UUID(as_uuid=False),
		ForeignKey("mkt_campaign.id", ondelete="CASCADE"),
		nullable=False,
	)
	contact_id = Column(String(50), nullable=False)
	opportunity_id = Column(String(50), nullable=True)
	revenue_cents = Column(BigInteger, nullable=False, default=0)
	attribution_model = Column(String(30), nullable=False, default="LAST_TOUCH")
	attributed_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	# Relationships
	campaign = relationship("MarketingCampaign", back_populates="attributions", lazy="select")

	def __repr__(self) -> str:
		return (
			f"<CampaignAttribution campaign={self.campaign_id} "
			f"contact={self.contact_id} revenue_cents={self.revenue_cents}>"
		)


__all__ = [
	"MarketingCampaign",
	"MarketingSequence",
	"CampaignContact",
	"LeadScore",
	"CampaignAttribution",
	"CAMPAIGN_TYPE",
	"CAMPAIGN_STATUS",
	"SEQUENCE_STEP_TYPE",
	"CONTACT_STATUS",
	"LEAD_GRADE",
	"ATTRIBUTION_MODEL",
]
