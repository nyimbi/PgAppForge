"""
pgappforge/plugins/erp/analytics/cdp/models.py

SQLAlchemy models for the Customer Data Platform (CDP) plugin.

Tables
------
analytics_unified_profile    — merged identity profile per party (LTV, churn prob, NBA)
analytics_identity_edge      — identity graph edges linking source IDs to canonical party
analytics_segment            — segment definitions (STATIC / DYNAMIC / AI)
analytics_segment_membership — party membership in a segment with score
analytics_event_stream       — high-volume clickstream / behavioural events (time-series)

Design rules
  - All PKs: UUID v4 via gen_random_uuid() + Python default_factory
  - All timestamps: TIMESTAMPTZ DEFAULT NOW()
  - tenant_id UUID NOT NULL on all mutable entities
  - lifetime_value_cents: INTEGER — never float, always cents
  - churn_probability, confidence_score, score: NUMERIC(5,4) — never float
  - EventStream uses BRIN index on occurred_at for efficient time-range scans
  - identity_graph, propensity_scores, matched_attributes, definition: JSONB
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import sqlalchemy as sa
from sqlalchemy import (
	Boolean,
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
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID

from pgappforge.models.sqla import Model
from pgappforge.plugins.audit import AuditMixin


def _uuid4() -> str:
	return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# UnifiedProfile
# ---------------------------------------------------------------------------

class UnifiedProfile(AuditMixin, Model):
	"""Merged 360° profile for a canonical Party.

	identity_graph JSONB: adjacency structure of all resolved identities
	  {"nodes": [...], "edges": [...]} — materialised from IdentityEdge rows.

	segments TEXT[]: cached list of segment names this party belongs to.
	  Refreshed by run_segmentation(); serves as a fast denormalised lookup.

	propensity_scores JSONB: keyed propensity values from ML models:
	  {"upsell": 0.73, "churn": 0.12, "nps_detractor": 0.05}

	lifetime_value_cents INTEGER: cumulative realised LTV in tenant currency minor units.
	  Never float. Updated by CDPService.compute_unified_profile().

	churn_probability NUMERIC(5,4): latest predicted churn probability 0–1.

	next_best_action TEXT: single recommended action code or narrative.

	last_computed_at: timestamp of last full profile recompute.
	"""

	__allow_unmapped__ = True
	__tablename__ = "analytics_unified_profile"
	__table_args__ = (
		UniqueConstraint("tenant_id", "party_id", name="uq_analytics_unified_profile_tenant_party"),
		Index("ix_analytics_profile_tenant", "tenant_id"),
		Index("ix_analytics_profile_last_computed", "last_computed_at"),
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
		ForeignKey("erp_party.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)
	identity_graph: dict[str, Any] = Column(
		JSONB,
		nullable=False,
		default=dict,
		comment='{"nodes": [...], "edges": [...]}',
	)
	segments: list[str] = Column(
		ARRAY(String),
		nullable=False,
		default=list,
		comment="Denormalised segment names for fast lookup",
	)
	propensity_scores: dict[str, Any] = Column(
		JSONB,
		nullable=False,
		default=dict,
		comment='{"upsell": 0.73, "churn": 0.12}',
	)
	lifetime_value_cents = Column(
		Integer,
		nullable=False,
		default=0,
		comment="Cumulative realised LTV in tenant currency minor units — never float",
	)
	churn_probability = Column(
		Numeric(5, 4),
		nullable=True,
		comment="Latest churn probability 0.0000–1.0000",
	)
	next_best_action = Column(
		Text,
		nullable=True,
		comment="Recommended action code or narrative",
	)
	last_computed_at = Column(DateTime(timezone=True), nullable=True)

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
			f"<UnifiedProfile {self.id!r} party={self.party_id!r} "
			f"ltv={self.lifetime_value_cents!r}>"
		)


# ---------------------------------------------------------------------------
# IdentityEdge
# ---------------------------------------------------------------------------

class IdentityEdge(AuditMixin, Model):
	"""Directed edge in the identity graph linking a source ID to a canonical Party.

	source_type: source system identifier e.g. "email", "cookie_id", "crm_contact_id",
	             "phone_e164", "loyalty_card".
	source_id:   the actual identifier value in the source system.
	target_party_id: the resolved canonical Party.

	match_method:
	  DETERMINISTIC — exact identifier match (email, phone)
	  PROBABILISTIC — fuzzy / ML-based match (name+address, device fingerprint)

	matched_attributes JSONB: which attributes were used to make the match and their
	  match scores e.g. {"email": 1.0, "name": 0.82, "postcode": 1.0}.

	confidence_score NUMERIC(5,4): overall match confidence 0–1.
	"""

	__allow_unmapped__ = True
	__tablename__ = "analytics_identity_edge"
	__table_args__ = (
		UniqueConstraint(
			"source_type", "source_id",
			name="uq_analytics_identity_edge_source",
		),
		Index("ix_analytics_identity_edge_target", "target_party_id"),
		Index("ix_analytics_identity_edge_method", "match_method"),
		Index("ix_analytics_identity_edge_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	source_type = Column(
		String(100),
		nullable=False,
		comment="e.g. email | cookie_id | crm_contact_id | phone_e164",
	)
	source_id = Column(String(500), nullable=False, comment="Identifier value in source system")
	target_party_id = Column(
		UUID(as_uuid=False),
		ForeignKey("erp_party.id", ondelete="CASCADE"),
		nullable=False,
	)
	confidence_score = Column(
		Numeric(5, 4),
		nullable=False,
		default=1,
		comment="Match confidence 0.0000–1.0000",
	)
	match_method = Column(
		String(20),
		nullable=False,
		default="DETERMINISTIC",
		comment="DETERMINISTIC | PROBABILISTIC",
	)
	matched_attributes: dict[str, Any] = Column(
		JSONB,
		nullable=False,
		default=dict,
		comment='{"email": 1.0, "name": 0.82}',
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

	target_party = sa.orm.relationship(
		"Party",
		foreign_keys=[target_party_id],
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<IdentityEdge {self.source_type!r}:{self.source_id!r} "
			f"→ {self.target_party_id!r} conf={self.confidence_score!r}>"
		)


# ---------------------------------------------------------------------------
# Segment
# ---------------------------------------------------------------------------

class Segment(AuditMixin, Model):
	"""Audience segment definition.

	segment_type:
	  STATIC   — manually curated membership list (no auto-recompute)
	  DYNAMIC  — SQL/rule-based definition recomputed on schedule
	  AI       — ML model-driven; members selected by propensity threshold

	definition JSONB: segment criteria depending on type:
	  DYNAMIC: {"sql": "SELECT party_id FROM ... WHERE ..."}
	  AI:      {"model_name": "churn_model", "threshold": 0.7, "direction": "gt"}
	  STATIC:  {} (membership managed via SegmentMembership inserts)

	member_count: denormalised count updated by run_segmentation().
	"""

	__allow_unmapped__ = True
	__tablename__ = "analytics_segment"
	__table_args__ = (
		UniqueConstraint("tenant_id", "segment_name", name="uq_analytics_segment_tenant_name"),
		Index("ix_analytics_segment_tenant", "tenant_id"),
		Index("ix_analytics_segment_type", "segment_type"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	segment_name = Column(String(500), nullable=False)
	segment_type = Column(
		String(20),
		nullable=False,
		default="STATIC",
		comment="STATIC | DYNAMIC | AI",
	)
	definition: dict[str, Any] = Column(
		JSONB,
		nullable=False,
		default=dict,
		comment="Segment criteria; structure depends on segment_type",
	)
	member_count = Column(
		Integer,
		nullable=False,
		default=0,
		comment="Denormalised count refreshed by run_segmentation()",
	)
	last_computed_at = Column(DateTime(timezone=True), nullable=True)
	tags: list[str] = Column(
		ARRAY(String),
		nullable=False,
		default=list,
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

	memberships: list[SegmentMembership] = sa.orm.relationship(
		"SegmentMembership",
		back_populates="segment",
		cascade="all, delete-orphan",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<Segment {self.segment_name!r} type={self.segment_type!r} "
			f"members={self.member_count!r}>"
		)


# ---------------------------------------------------------------------------
# SegmentMembership
# ---------------------------------------------------------------------------

class SegmentMembership(Model):
	"""Membership record linking a Party to a Segment.

	joined_at: when this party entered the segment.
	score NUMERIC(5,4): optional relevance/propensity score that caused membership
	  (e.g. churn probability for an AI segment).

	Immutable ledger: do NOT update existing rows. When a party leaves a segment,
	insert a compensating row with is_active=False or delete (service layer decides).
	"""

	__allow_unmapped__ = True
	__tablename__ = "analytics_segment_membership"
	__table_args__ = (
		UniqueConstraint(
			"segment_id", "party_id",
			name="uq_analytics_seg_member_seg_party",
		),
		Index("ix_analytics_seg_member_segment", "segment_id"),
		Index("ix_analytics_seg_member_party", "party_id"),
		Index("ix_analytics_seg_member_joined", "joined_at", postgresql_using="brin"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	segment_id = Column(
		UUID(as_uuid=False),
		ForeignKey("analytics_segment.id", ondelete="CASCADE"),
		nullable=False,
	)
	party_id = Column(
		UUID(as_uuid=False),
		ForeignKey("erp_party.id", ondelete="CASCADE"),
		nullable=False,
	)
	joined_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	score = Column(
		Numeric(5, 4),
		nullable=True,
		comment="Propensity/relevance score that triggered membership",
	)

	segment: Segment = sa.orm.relationship(
		"Segment",
		back_populates="memberships",
		lazy="select",
	)
	party = sa.orm.relationship(
		"Party",
		foreign_keys=[party_id],
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<SegmentMembership seg={self.segment_id!r} "
			f"party={self.party_id!r} score={self.score!r}>"
		)


# ---------------------------------------------------------------------------
# EventStream
# ---------------------------------------------------------------------------

class EventStream(Model):
	"""High-volume behavioural / clickstream event log.

	Designed for time-series write throughput. BRIN index on occurred_at
	provides efficient range scans without bloating index size.

	party_id: nullable — anonymous events before identity resolution.
	session_id: browser/app session token.
	event_type: dotted hierarchy e.g. "page.view", "product.click", "checkout.start".
	event_source: originating channel e.g. "web", "ios", "android", "pos", "api".
	properties JSONB: event-specific payload.
	processed BOOL: marks events consumed by CDP pipeline (segmentation, profile update).

	DO NOT add non-BRIN indexes on occurred_at — it kills write throughput on
	high-cardinality time-series tables. Use partitioning if scan latency becomes
	an issue (partition by RANGE on occurred_at).
	"""

	__allow_unmapped__ = True
	__tablename__ = "analytics_event_stream"
	__table_args__ = (
		Index("ix_analytics_event_stream_party", "party_id"),
		Index("ix_analytics_event_stream_session", "session_id"),
		Index("ix_analytics_event_stream_type", "event_type"),
		Index(
			"ix_analytics_event_stream_occurred_brin",
			"occurred_at",
			postgresql_using="brin",
		),
		Index("ix_analytics_event_stream_processed", "processed"),
		Index("ix_analytics_event_stream_tenant", "tenant_id"),
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
		comment="NULL for pre-identity-resolution anonymous events",
	)
	session_id = Column(String(200), nullable=True)
	event_type = Column(
		String(200),
		nullable=False,
		comment="Dotted hierarchy e.g. page.view | product.click",
	)
	event_source = Column(
		String(100),
		nullable=False,
		comment="Originating channel e.g. web | ios | android | pos | api",
	)
	properties: dict[str, Any] = Column(
		JSONB,
		nullable=False,
		default=dict,
		comment="Event-specific payload",
	)
	occurred_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	processed = Column(
		Boolean,
		nullable=False,
		default=False,
		comment="True after CDP pipeline has consumed this event",
	)

	party = sa.orm.relationship(
		"Party",
		foreign_keys=[party_id],
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<EventStream {self.id!r} type={self.event_type!r} "
			f"party={self.party_id!r} at={self.occurred_at!r}>"
		)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"UnifiedProfile",
	"IdentityEdge",
	"Segment",
	"SegmentMembership",
	"EventStream",
]
