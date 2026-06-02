"""
pgappforge/plugins/erp/analytics/cdp/views.py

Flask views for the Customer Data Platform plugin.

Route summary
-------------
UnifiedProfileView    /analytics/cdp/profiles/
  ├─ GET  /                         — profile list (HTML)
  ├─ GET  /<party_id>               — profile detail (JSON)
  └─ POST /<party_id>/compute       — trigger recompute (JSON)
SegmentView           /analytics/cdp/segments/
  ├─ GET  /                         — segment list (HTML)
  ├─ POST /                         — create segment (JSON)
  ├─ POST /<id>/compute             — run segmentation (JSON)
  └─ POST /<id>/activate            — activate to channel (JSON)
IdentityView          /analytics/cdp/identity/
  ├─ POST /resolve                  — resolve identifiers → party_id (JSON)
  └─ POST /edge                     — add identity edge (JSON)
CDPReportView         /analytics/cdp/reports/
  ├─ GET  /segment_summary          — segment membership counts (HTML)
  └─ GET  /ltv_distribution         — LTV bucket distribution (JSON)
"""
from __future__ import annotations

import logging
from decimal import Decimal

import sqlalchemy as sa
from flask import abort, jsonify, make_response, request

from pgappforge import BaseView, expose
from pgappforge.security.decorators import has_access

log = logging.getLogger(__name__)


def _get_session():
	try:
		from flask import current_app
		ab = current_app.extensions.get("appbuilder")
		if ab and hasattr(ab, "get_session"):
			return ab.get_session
		db = current_app.extensions.get("sqlalchemy")
		if db:
			return db.session
	except RuntimeError:
		pass
	raise RuntimeError("Cannot obtain database session")


def _he(s: object) -> str:
	return (
		str(s)
		.replace("&", "&amp;")
		.replace("<", "&lt;")
		.replace(">", "&gt;")
		.replace('"', "&quot;")
	)


# ---------------------------------------------------------------------------
# UnifiedProfileView
# ---------------------------------------------------------------------------

class UnifiedProfileView(BaseView):
	route_base = "/analytics/cdp/profiles"
	default_view = "list"

	@expose("/", methods=["GET"])
	@has_access
	def list(self):
		session = _get_session()
		from pgappforge.plugins.erp.analytics.cdp.models import UnifiedProfile
		rows = session.execute(
			sa.select(UnifiedProfile)
			.order_by(UnifiedProfile.lifetime_value_cents.desc())
			.limit(100)
		).scalars().all()

		def _ltv(cents: int) -> str:
			major = cents // 100
			minor = cents % 100
			return f"{major:,}.{minor:02d}"

		items = [
			f"<tr><td>{_he(r.party_id)}</td>"
			f"<td>{_ltv(r.lifetime_value_cents)}</td>"
			f"<td>{_he(r.churn_probability or '—')}</td>"
			f"<td>{_he(len(r.segments or []))}</td>"
			f"<td>{_he(r.next_best_action or '—')}</td>"
			f"<td>{_he(r.last_computed_at.strftime('%Y-%m-%d %H:%M') if r.last_computed_at else 'Never')}</td></tr>"
			for r in rows
		]
		html = (
			"<h2>Unified Customer Profiles</h2>"
			"<table><thead><tr><th>Party ID</th><th>LTV</th><th>Churn Prob</th>"
			"<th>Segments</th><th>Next Best Action</th><th>Last Computed</th></tr></thead>"
			f"<tbody>{''.join(items)}</tbody></table>"
		)
		return make_response(html, 200, {"Content-Type": "text/html; charset=utf-8"})

	@expose("/<string:party_id>", methods=["GET"])
	@has_access
	def detail(self, party_id: str):
		session = _get_session()
		from pgappforge.plugins.erp.analytics.cdp.models import UnifiedProfile
		row = session.execute(
			sa.select(UnifiedProfile).where(UnifiedProfile.party_id == party_id)
		).scalar_one_or_none()
		if row is None:
			abort(404)
		return jsonify({
			"id": row.id,
			"party_id": row.party_id,
			"identity_graph": row.identity_graph,
			"segments": row.segments,
			"propensity_scores": row.propensity_scores,
			"lifetime_value_cents": row.lifetime_value_cents,
			"churn_probability": str(row.churn_probability) if row.churn_probability else None,
			"next_best_action": row.next_best_action,
			"last_computed_at": row.last_computed_at.isoformat() if row.last_computed_at else None,
		})

	@expose("/<string:party_id>/compute", methods=["POST"])
	@has_access
	def compute(self, party_id: str):
		session = _get_session()
		from pgappforge.plugins.erp.analytics.cdp.services import CDPService, PartyNotFoundError
		try:
			profile = CDPService.compute_unified_profile(party_id, session)
			session.commit()
			return jsonify({
				"id": profile.id,
				"lifetime_value_cents": profile.lifetime_value_cents,
				"segment_count": len(profile.segments or []),
				"last_computed_at": profile.last_computed_at.isoformat(),
			})
		except PartyNotFoundError as exc:
			return jsonify({"error": str(exc)}), 404


# ---------------------------------------------------------------------------
# SegmentView
# ---------------------------------------------------------------------------

class SegmentView(BaseView):
	route_base = "/analytics/cdp/segments"
	default_view = "list"

	@expose("/", methods=["GET"])
	@has_access
	def list(self):
		session = _get_session()
		from pgappforge.plugins.erp.analytics.cdp.models import Segment
		rows = session.execute(
			sa.select(Segment).order_by(Segment.member_count.desc())
		).scalars().all()
		items = [
			f"<tr><td>{_he(r.segment_name)}</td><td>{_he(r.segment_type)}</td>"
			f"<td>{_he(r.member_count)}</td>"
			f"<td>{_he(r.last_computed_at.strftime('%Y-%m-%d') if r.last_computed_at else 'Never')}</td></tr>"
			for r in rows
		]
		html = (
			"<h2>Segments</h2>"
			"<table><thead><tr><th>Name</th><th>Type</th>"
			"<th>Members</th><th>Last Computed</th></tr></thead>"
			f"<tbody>{''.join(items)}</tbody></table>"
		)
		return make_response(html, 200, {"Content-Type": "text/html; charset=utf-8"})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		session = _get_session()
		data = request.get_json(force=True) or {}
		from pgappforge.plugins.erp.analytics.cdp.models import Segment
		seg = Segment(
			tenant_id=data["tenant_id"],
			segment_name=data["segment_name"],
			segment_type=data.get("segment_type", "STATIC"),
			definition=data.get("definition", {}),
			tags=data.get("tags", []),
		)
		session.add(seg)
		session.commit()
		return jsonify({"id": seg.id, "segment_name": seg.segment_name}), 201

	@expose("/<string:segment_id>/compute", methods=["POST"])
	@has_access
	def compute(self, segment_id: str):
		session = _get_session()
		from pgappforge.plugins.erp.analytics.cdp.services import (
			CDPService,
			SegmentationError,
			SegmentNotFoundError,
		)
		try:
			count = CDPService.run_segmentation(segment_id, session)
			session.commit()
			return jsonify({"segment_id": segment_id, "member_count": count})
		except SegmentNotFoundError as exc:
			return jsonify({"error": str(exc)}), 404
		except SegmentationError as exc:
			return jsonify({"error": str(exc)}), 422

	@expose("/<string:segment_id>/activate", methods=["POST"])
	@has_access
	def activate(self, segment_id: str):
		session = _get_session()
		data = request.get_json(force=True) or {}
		channel = data.get("channel", "email")
		from pgappforge.plugins.erp.analytics.cdp.services import CDPService, SegmentNotFoundError
		try:
			result = CDPService.activate_segment(segment_id, channel, session)
			session.commit()
			return jsonify(result)
		except SegmentNotFoundError as exc:
			return jsonify({"error": str(exc)}), 404


# ---------------------------------------------------------------------------
# IdentityView
# ---------------------------------------------------------------------------

class IdentityView(BaseView):
	route_base = "/analytics/cdp/identity"
	default_view = "resolve"

	@expose("/resolve", methods=["POST"])
	@has_access
	def resolve(self):
		session = _get_session()
		data = request.get_json(force=True) or {}
		tenant_id = data.get("tenant_id", "")
		identifiers = data.get("identifiers", {})
		from pgappforge.plugins.erp.analytics.cdp.services import CDPService, IdentityNotFoundError
		try:
			party_id = CDPService.resolve_identity(identifiers, tenant_id, session)
			return jsonify({"party_id": party_id})
		except IdentityNotFoundError as exc:
			return jsonify({"error": str(exc)}), 404

	@expose("/edge", methods=["POST"])
	@has_access
	def add_edge(self):
		session = _get_session()
		data = request.get_json(force=True) or {}
		from pgappforge.plugins.erp.analytics.cdp.services import CDPService
		edge = CDPService.add_identity_edge(
			source_type=data["source_type"],
			source_id=data["source_id"],
			party_id=data["party_id"],
			tenant_id=data["tenant_id"],
			session=session,
			confidence=Decimal(str(data.get("confidence", "1.0"))),
			match_method=data.get("match_method", "DETERMINISTIC"),
			matched_attributes=data.get("matched_attributes"),
		)
		session.commit()
		return jsonify({"id": edge.id, "target_party_id": edge.target_party_id}), 201


# ---------------------------------------------------------------------------
# CDPReportView
# ---------------------------------------------------------------------------

class CDPReportView(BaseView):
	"""CDP analytics reports.

	GET /analytics/cdp/reports/segment_summary   — segment membership counts (HTML)
	GET /analytics/cdp/reports/ltv_distribution  — LTV bucket distribution (JSON)
	"""

	route_base = "/analytics/cdp/reports"
	default_view = "segment_summary"

	@expose("/segment_summary", methods=["GET"])
	@has_access
	def segment_summary(self):
		"""All segments with member count — segment performance overview."""
		session = _get_session()
		from pgappforge.plugins.erp.analytics.cdp.models import Segment
		rows = session.execute(
			sa.select(Segment)
			.order_by(Segment.member_count.desc())
		).scalars().all()
		total = sum(r.member_count for r in rows)
		items = [
			f"<tr><td>{_he(r.segment_name)}</td><td>{_he(r.segment_type)}</td>"
			f"<td>{_he(r.member_count)}</td>"
			f"<td>{round(r.member_count / total * 100, 1) if total else 0}%</td>"
			f"<td>{_he(r.last_computed_at.strftime('%Y-%m-%d') if r.last_computed_at else '—')}</td></tr>"
			for r in rows
		]
		html = (
			f"<h2>Segment Summary (total profiles: {total})</h2>"
			"<table><thead><tr><th>Segment</th><th>Type</th>"
			"<th>Members</th><th>Share</th><th>Last Computed</th></tr></thead>"
			f"<tbody>{''.join(items)}</tbody></table>"
		)
		return make_response(html, 200, {"Content-Type": "text/html; charset=utf-8"})

	@expose("/ltv_distribution", methods=["GET"])
	@has_access
	def ltv_distribution(self):
		"""LTV bucket distribution across all unified profiles."""
		session = _get_session()
		from pgappforge.plugins.erp.analytics.cdp.models import UnifiedProfile

		# Bucket into 5 tiers by LTV cents
		buckets = [
			("0-1K", 0, 100_000),
			("1K-10K", 100_000, 1_000_000),
			("10K-50K", 1_000_000, 5_000_000),
			("50K-250K", 5_000_000, 25_000_000),
			("250K+", 25_000_000, None),
		]
		result = {}
		for label, low, high in buckets:
			stmt = sa.select(sa.func.count()).where(UnifiedProfile.lifetime_value_cents >= low)
			if high is not None:
				stmt = stmt.where(UnifiedProfile.lifetime_value_cents < high)
			count = session.execute(stmt).scalar() or 0
			result[label] = count

		return jsonify(result)


__all__ = [
	"UnifiedProfileView",
	"SegmentView",
	"IdentityView",
	"CDPReportView",
]
