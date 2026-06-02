"""
pgappforge/plugins/erp/analytics/cdp/services.py

CDPService — Customer Data Platform business logic.

All methods accept an explicit SQLAlchemy session (SA 2.x execute() pattern).
No session.commit() here — callers own transaction boundaries.

Key methods
-----------
  compute_unified_profile(party_id, session) -> UnifiedProfile
      Aggregates identity edges, event counts, order totals, ML scores
      into a UnifiedProfile row. Upserts (creates or updates) the profile.

  run_segmentation(segment_id, session) -> int
      Executes a DYNAMIC or AI segment's definition, updates membership
      table and member_count. Returns new member count.
      STATIC segments raise SegmentationError — use add/remove_member instead.

  activate_segment(segment_id, channel, session) -> dict
      Marks a segment as activated for a delivery channel; emits event.
      Returns {"segment_id", "channel", "member_count", "activated_at"}.

  resolve_identity(identifiers, tenant_id, session) -> str
      Given a dict of {source_type: source_id} identifiers, returns the
      canonical party_id by searching IdentityEdge rows.
      If multiple edges resolve to different parties, returns the highest-
      confidence match. If no match, raises IdentityNotFoundError.

  add_identity_edge(source_type, source_id, party_id, confidence,
                    match_method, matched_attributes, session) -> IdentityEdge
      Upserts an IdentityEdge row; emits IdentityResolvedEvent.

  ingest_events(events, tenant_id, session) -> int
      Bulk-inserts EventStream rows. Returns count inserted.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import sqlalchemy as sa

from pgappforge.plugins.erp.analytics.cdp.events import (
	EventStreamIngestedEvent,
	IdentityResolvedEvent,
	ProfileComputedEvent,
	SegmentActivatedEvent,
	SegmentComputedEvent,
	emit_event,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class CDPError(Exception):
	"""Base error for CDP service layer."""


class ProfileNotFoundError(CDPError):
	pass


class SegmentNotFoundError(CDPError):
	pass


class SegmentationError(CDPError):
	"""Raised when segmentation cannot be performed (e.g. STATIC segment)."""


class IdentityNotFoundError(CDPError):
	pass


class PartyNotFoundError(CDPError):
	pass


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class CDPService:
	"""Stateless Customer Data Platform service."""

	# ------------------------------------------------------------------
	# Unified Profile
	# ------------------------------------------------------------------

	@staticmethod
	def compute_unified_profile(party_id: str, session: Any) -> Any:
		"""Aggregate data across plugins into a UnifiedProfile for party_id.

		Pulls:
		  - IdentityEdge rows → identity_graph
		  - SegmentMembership rows → segments list
		  - ModelPrediction rows for churn model → churn_probability
		  - AR invoice totals → lifetime_value_cents (if AR plugin loaded)

		Creates the UnifiedProfile if it does not exist; updates it otherwise.
		Emits ProfileComputedEvent.
		"""
		from pgappforge.plugins.erp.analytics.cdp.models import (
			IdentityEdge,
			Segment,
			SegmentMembership,
			UnifiedProfile,
		)

		# Verify party exists
		try:
			from pgappforge.plugins.erp.foundation.models import Party
			party = session.execute(
				sa.select(Party).where(Party.id == party_id)
			).scalar_one_or_none()
			if party is None:
				raise PartyNotFoundError(f"Party {party_id!r} not found")
			tenant_id = party.tenant_id
		except ImportError:
			tenant_id = ""

		# Build identity graph from edges
		edges = session.execute(
			sa.select(IdentityEdge).where(IdentityEdge.target_party_id == party_id)
		).scalars().all()
		identity_graph: dict[str, Any] = {
			"nodes": [{"source_type": e.source_type, "source_id": e.source_id} for e in edges],
			"edges": [
				{
					"source_type": e.source_type,
					"source_id": e.source_id,
					"party_id": party_id,
					"confidence": float(e.confidence_score),
					"method": e.match_method,
				}
				for e in edges
			],
		}

		# Current segment names
		segment_rows = session.execute(
			sa.select(Segment.segment_name)
			.join(SegmentMembership, SegmentMembership.segment_id == Segment.id)
			.where(SegmentMembership.party_id == party_id)
		).scalars().all()
		segments = list(segment_rows)

		# Churn probability from most recent deployed churn model prediction
		churn_prob: Decimal | None = None
		try:
			from pgappforge.plugins.erp.analytics.predictive.models import (
				MLModel,
				ModelPrediction,
			)
			pred = session.execute(
				sa.select(ModelPrediction)
				.join(MLModel, MLModel.id == ModelPrediction.model_id)
				.where(ModelPrediction.entity_type == "Party")
				.where(ModelPrediction.entity_id == party_id)
				.where(MLModel.model_name.ilike("%churn%"))
				.order_by(ModelPrediction.predicted_at.desc())
				.limit(1)
			).scalar_one_or_none()
			if pred is not None and pred.confidence is not None:
				churn_prob = Decimal(str(pred.confidence))
		except Exception as exc:
			log.debug("compute_unified_profile: churn lookup skipped: %s", exc)

		# Lifetime value from AR invoices (best-effort)
		ltv_cents = 0
		try:
			from pgappforge.plugins.erp.finance.ar.models import ARInvoice
			ltv_row = session.execute(
				sa.select(sa.func.coalesce(sa.func.sum(ARInvoice.total_cents), 0))
				.where(ARInvoice.customer_id == party_id)
				.where(ARInvoice.status == "PAID")
			).scalar()
			ltv_cents = int(ltv_row or 0)
		except Exception as exc:
			log.debug("compute_unified_profile: AR LTV lookup skipped: %s", exc)

		# Upsert UnifiedProfile
		profile = session.execute(
			sa.select(UnifiedProfile)
			.where(UnifiedProfile.party_id == party_id)
		).scalar_one_or_none()

		now = datetime.now(timezone.utc)
		if profile is None:
			profile = UnifiedProfile(
				tenant_id=tenant_id,
				party_id=party_id,
				identity_graph=identity_graph,
				segments=segments,
				propensity_scores={},
				lifetime_value_cents=ltv_cents,
				churn_probability=churn_prob,
				last_computed_at=now,
			)
			session.add(profile)
		else:
			profile.identity_graph = identity_graph
			profile.segments = segments
			profile.lifetime_value_cents = ltv_cents
			if churn_prob is not None:
				profile.churn_probability = churn_prob
			profile.last_computed_at = now

		session.flush()

		emit_event(
			ProfileComputedEvent(
				aggregate_id=profile.id,
				aggregate_type="UnifiedProfile",
				tenant_id=tenant_id,
				profile_id=profile.id,
				party_id=party_id,
				lifetime_value_cents=ltv_cents,
				churn_probability=str(churn_prob) if churn_prob is not None else "",
				segment_count=len(segments),
			),
			session,
		)
		log.info(
			"compute_unified_profile: party=%s ltv=%d segments=%d churn=%s",
			party_id, ltv_cents, len(segments), churn_prob,
		)
		return profile

	# ------------------------------------------------------------------
	# Segmentation
	# ------------------------------------------------------------------

	@staticmethod
	def run_segmentation(segment_id: str, session: Any) -> int:
		"""Recompute segment membership for DYNAMIC and AI segments.

		For DYNAMIC segments: executes definition["sql"] and upserts membership rows.
		For AI segments: queries ModelPrediction with threshold from definition.
		For STATIC segments: raises SegmentationError.

		Returns the new member_count.
		"""
		from pgappforge.plugins.erp.analytics.cdp.models import (
			Segment,
			SegmentMembership,
		)

		segment = session.execute(
			sa.select(Segment).where(Segment.id == segment_id)
		).scalar_one_or_none()
		if segment is None:
			raise SegmentNotFoundError(f"Segment {segment_id!r} not found")
		if segment.segment_type == "STATIC":
			raise SegmentationError("Cannot run_segmentation on STATIC segment; manage membership directly")

		party_ids: list[str] = []

		if segment.segment_type == "DYNAMIC":
			sql = segment.definition.get("sql")
			if not sql:
				raise SegmentationError("DYNAMIC segment missing definition.sql")
			rows = session.execute(sa.text(sql)).fetchall()
			party_ids = [str(r[0]) for r in rows]

		elif segment.segment_type == "AI":
			model_name = segment.definition.get("model_name", "")
			threshold = Decimal(str(segment.definition.get("threshold", "0.5")))
			direction = segment.definition.get("direction", "gt")  # gt | lt

			try:
				from pgappforge.plugins.erp.analytics.predictive.models import (
					MLModel,
					ModelPrediction,
				)
				stmt = (
					sa.select(ModelPrediction.entity_id)
					.join(MLModel, MLModel.id == ModelPrediction.model_id)
					.where(MLModel.model_name == model_name)
					.where(MLModel.status == "DEPLOYED")
					.where(ModelPrediction.entity_type == "Party")
				)
				if direction == "gt":
					stmt = stmt.where(ModelPrediction.confidence >= threshold)
				else:
					stmt = stmt.where(ModelPrediction.confidence <= threshold)
				party_ids = [str(r) for r in session.execute(stmt).scalars().all()]
			except ImportError:
				raise SegmentationError("Predictive plugin not available for AI segment")

		# Delete stale memberships and re-insert
		session.execute(
			sa.delete(SegmentMembership).where(SegmentMembership.segment_id == segment_id)
		)
		now = datetime.now(timezone.utc)
		for pid in party_ids:
			session.add(SegmentMembership(
				segment_id=segment_id,
				party_id=pid,
				joined_at=now,
			))

		segment.member_count = len(party_ids)
		segment.last_computed_at = now

		emit_event(
			SegmentComputedEvent(
				aggregate_id=segment_id,
				aggregate_type="Segment",
				tenant_id=segment.tenant_id,
				segment_id=segment_id,
				segment_name=segment.segment_name,
				member_count=len(party_ids),
				segment_type=segment.segment_type,
			),
			session,
		)
		log.info("run_segmentation: segment=%s type=%s members=%d", segment_id, segment.segment_type, len(party_ids))
		return len(party_ids)

	@staticmethod
	def activate_segment(segment_id: str, channel: str, session: Any) -> dict[str, Any]:
		"""Mark segment as activated for a delivery channel.

		Returns activation summary dict.
		Actual delivery (email, push, ad platform) is handled by channel-specific adapters.
		"""
		from pgappforge.plugins.erp.analytics.cdp.models import Segment

		segment = session.execute(
			sa.select(Segment).where(Segment.id == segment_id)
		).scalar_one_or_none()
		if segment is None:
			raise SegmentNotFoundError(f"Segment {segment_id!r} not found")

		now = datetime.now(timezone.utc)
		emit_event(
			SegmentActivatedEvent(
				aggregate_id=segment_id,
				aggregate_type="Segment",
				tenant_id=segment.tenant_id,
				segment_id=segment_id,
				segment_name=segment.segment_name,
				channel=channel,
				member_count=segment.member_count,
			),
			session,
		)
		return {
			"segment_id": segment_id,
			"segment_name": segment.segment_name,
			"channel": channel,
			"member_count": segment.member_count,
			"activated_at": now.isoformat(),
		}

	# ------------------------------------------------------------------
	# Identity resolution
	# ------------------------------------------------------------------

	@staticmethod
	def resolve_identity(identifiers: dict[str, str], tenant_id: str, session: Any) -> str:
		"""Resolve {source_type: source_id} dict to a canonical party_id.

		Searches IdentityEdge for each identifier. If multiple edges match
		different parties, returns the party_id with the highest aggregate
		confidence score. Raises IdentityNotFoundError if no match.
		"""
		from pgappforge.plugins.erp.analytics.cdp.models import IdentityEdge

		candidates: dict[str, Decimal] = {}  # party_id -> aggregate confidence

		for source_type, source_id in identifiers.items():
			edges = session.execute(
				sa.select(IdentityEdge)
				.where(IdentityEdge.tenant_id == tenant_id)
				.where(IdentityEdge.source_type == source_type)
				.where(IdentityEdge.source_id == source_id)
			).scalars().all()
			for edge in edges:
				pid = edge.target_party_id
				candidates[pid] = candidates.get(pid, Decimal("0")) + Decimal(str(edge.confidence_score))

		if not candidates:
			raise IdentityNotFoundError(
				f"No identity edge found for identifiers: {identifiers!r}"
			)

		# Return party with highest aggregate confidence
		resolved_party_id = max(candidates, key=lambda p: candidates[p])
		log.debug(
			"resolve_identity: identifiers=%r resolved to party=%s (conf=%s)",
			identifiers, resolved_party_id, candidates[resolved_party_id],
		)
		return resolved_party_id

	@staticmethod
	def add_identity_edge(
		source_type: str,
		source_id: str,
		party_id: str,
		tenant_id: str,
		session: Any,
		confidence: Decimal = Decimal("1.0"),
		match_method: str = "DETERMINISTIC",
		matched_attributes: dict[str, Any] | None = None,
	) -> Any:
		"""Upsert an IdentityEdge linking source_type/source_id to party_id.

		If the source identifier already exists, updates confidence and attributes.
		Emits IdentityResolvedEvent.
		"""
		from pgappforge.plugins.erp.analytics.cdp.models import IdentityEdge

		existing = session.execute(
			sa.select(IdentityEdge)
			.where(IdentityEdge.source_type == source_type)
			.where(IdentityEdge.source_id == source_id)
		).scalar_one_or_none()

		if existing is not None:
			existing.target_party_id = party_id
			existing.confidence_score = confidence
			existing.match_method = match_method
			existing.matched_attributes = matched_attributes or {}
			edge = existing
		else:
			edge = IdentityEdge(
				tenant_id=tenant_id,
				source_type=source_type,
				source_id=source_id,
				target_party_id=party_id,
				confidence_score=confidence,
				match_method=match_method,
				matched_attributes=matched_attributes or {},
			)
			session.add(edge)
			session.flush()

		emit_event(
			IdentityResolvedEvent(
				aggregate_id=edge.id,
				aggregate_type="IdentityEdge",
				tenant_id=tenant_id,
				edge_id=edge.id,
				source_type=source_type,
				source_id=source_id,
				target_party_id=party_id,
				match_method=match_method,
				confidence_score=str(confidence),
			),
			session,
		)
		return edge

	# ------------------------------------------------------------------
	# Event stream ingestion
	# ------------------------------------------------------------------

	@staticmethod
	def ingest_events(
		events: list[dict[str, Any]],
		tenant_id: str,
		session: Any,
	) -> int:
		"""Bulk-insert EventStream rows.

		Each event dict must contain: event_type, event_source, properties.
		Optional: party_id, session_id, occurred_at.

		Returns count of rows inserted.
		"""
		from pgappforge.plugins.erp.analytics.cdp.models import EventStream

		now = datetime.now(timezone.utc)
		rows = []
		for ev in events:
			rows.append(EventStream(
				tenant_id=tenant_id,
				party_id=ev.get("party_id"),
				session_id=ev.get("session_id"),
				event_type=ev["event_type"],
				event_source=ev["event_source"],
				properties=ev.get("properties", {}),
				occurred_at=ev.get("occurred_at", now),
				processed=False,
			))
		session.add_all(rows)

		if rows:
			source = events[0].get("event_source", "unknown") if events else "unknown"
			emit_event(
				EventStreamIngestedEvent(
					aggregate_id=tenant_id,
					aggregate_type="EventStream",
					tenant_id=tenant_id,
					event_count=len(rows),
					source=source,
				),
				session,
			)

		log.info("ingest_events: tenant=%s count=%d", tenant_id, len(rows))
		return len(rows)


__all__ = [
	"CDPService",
	"CDPError",
	"ProfileNotFoundError",
	"SegmentNotFoundError",
	"SegmentationError",
	"IdentityNotFoundError",
	"PartyNotFoundError",
]
