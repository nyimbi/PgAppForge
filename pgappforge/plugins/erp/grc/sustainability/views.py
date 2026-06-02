"""
pgappforge/plugins/erp/grc/sustainability/views.py

Flask views for the GRC Sustainability plugin.

Endpoints:
  EmissionSourceView  GET/POST /sustainability/emission-sources/
  EmissionRecordView  GET/POST /sustainability/emission-records/
                      POST     /sustainability/emission-records/<id>/verify
  ESGMetricView       GET/POST /sustainability/esg-metrics/
  ESGSnapshotView     GET/POST /sustainability/esg-snapshots/
  SustainabilityReportView
    GET /sustainability/reports/ghg-scope-rollup
    GET /sustainability/reports/esg-dashboard
    GET /sustainability/reports/emission-trend
"""
from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal

import sqlalchemy as sa
from flask import abort, jsonify, request

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
	raise RuntimeError("Cannot obtain database session outside app context")


def _svc():
	from pgappforge.plugins.erp.grc.sustainability.services import SustainabilityService
	return SustainabilityService()


# ---------------------------------------------------------------------------
# EmissionSourceView
# ---------------------------------------------------------------------------

class EmissionSourceView(BaseView):
	route_base = "/sustainability/emission-sources"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.grc.sustainability.models import EmissionSource
		session = _get_session()
		tenant_id = request.args.get("tenant_id")
		scope_filter = request.args.get("scope")
		q = sa.select(EmissionSource).order_by(
			EmissionSource.scope, EmissionSource.source_name
		)
		if tenant_id:
			q = q.where(EmissionSource.tenant_id == tenant_id)
		if scope_filter:
			q = q.where(EmissionSource.scope == int(scope_filter))
		rows = session.execute(q).scalars().all()
		return jsonify([
			{
				"id": r.id,
				"source_name": r.source_name,
				"scope": r.scope,
				"emission_category": r.emission_category,
				"activity_type": r.activity_type,
				"unit_of_measure": r.unit_of_measure,
				"emission_factor": str(r.emission_factor),
				"emission_factor_source": r.emission_factor_source,
				"effective_from": r.effective_from.isoformat() if r.effective_from else None,
			}
			for r in rows
		])

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		session = _get_session()
		data = request.get_json(force=True) or {}
		required = (
			"tenant_id", "source_name", "scope", "emission_category",
			"activity_type", "unit_of_measure", "emission_factor",
			"emission_factor_source", "effective_from",
		)
		missing = [f for f in required if data.get(f) is None]
		if missing:
			return jsonify({"error": f"Missing: {missing}"}), 400
		try:
			result = _svc().create_emission_source(
				session=session,
				tenant_id=data["tenant_id"],
				source_name=data["source_name"],
				scope=int(data["scope"]),
				emission_category=data["emission_category"],
				activity_type=data["activity_type"],
				unit_of_measure=data["unit_of_measure"],
				emission_factor=Decimal(str(data["emission_factor"])),
				emission_factor_source=data["emission_factor_source"],
				effective_from=date.fromisoformat(data["effective_from"]),
			)
			session.commit()
			return jsonify(result), 201
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422


# ---------------------------------------------------------------------------
# EmissionRecordView
# ---------------------------------------------------------------------------

class EmissionRecordView(BaseView):
	route_base = "/sustainability/emission-records"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.grc.sustainability.models import EmissionRecord
		session = _get_session()
		tenant_id = request.args.get("tenant_id")
		verified_filter = request.args.get("verified")
		limit = min(int(request.args.get("limit", 100)), 500)

		q = sa.select(EmissionRecord).order_by(
			EmissionRecord.period_date.desc()
		).limit(limit)
		if tenant_id:
			q = q.where(EmissionRecord.tenant_id == tenant_id)
		if verified_filter is not None:
			q = q.where(EmissionRecord.verified == (verified_filter.lower() == "true"))
		rows = session.execute(q).scalars().all()
		return jsonify([
			{
				"id": r.id,
				"source_id": str(r.source_id),
				"period_date": r.period_date.isoformat() if r.period_date else None,
				"activity_quantity": str(r.activity_quantity),
				"uom": r.uom,
				"co2e_tonnes": str(r.co2e_tonnes),
				"method": r.method,
				"verified": r.verified,
				"data_quality": r.data_quality,
			}
			for r in rows
		])

	@expose("/", methods=["POST"])
	@has_access
	def record(self):
		session = _get_session()
		data = request.get_json(force=True) or {}
		required = ("tenant_id", "source_id", "period_date", "activity_quantity")
		missing = [f for f in required if data.get(f) is None]
		if missing:
			return jsonify({"error": f"Missing: {missing}"}), 400
		try:
			result = _svc().record_emission(
				session=session,
				tenant_id=data["tenant_id"],
				source_id=data["source_id"],
				period_date=date.fromisoformat(data["period_date"]),
				activity_quantity=Decimal(str(data["activity_quantity"])),
				method=data.get("method", "CALCULATED"),
				data_quality=data.get("data_quality", "MEDIUM"),
				notes=data.get("notes"),
			)
			session.commit()
			return jsonify(result), 201
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422

	@expose("/<string:record_id>/verify", methods=["POST"])
	@has_access
	def verify(self, record_id: str):
		session = _get_session()
		data = request.get_json(force=True) or {}
		if not data.get("verified_by"):
			return jsonify({"error": "verified_by required"}), 400
		try:
			result = _svc().verify_emission_record(
				session, record_id=record_id, verified_by=data["verified_by"]
			)
			session.commit()
			return jsonify(result)
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422


# ---------------------------------------------------------------------------
# ESGMetricView
# ---------------------------------------------------------------------------

class ESGMetricView(BaseView):
	route_base = "/sustainability/esg-metrics"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.grc.sustainability.models import ESGMetric
		session = _get_session()
		tenant_id = request.args.get("tenant_id")
		pillar = request.args.get("pillar")
		q = sa.select(ESGMetric).order_by(ESGMetric.pillar, ESGMetric.metric_code)
		if tenant_id:
			q = q.where(ESGMetric.tenant_id == tenant_id)
		if pillar:
			q = q.where(ESGMetric.pillar == pillar)
		rows = session.execute(q).scalars().all()
		return jsonify([
			{
				"id": r.id,
				"metric_code": r.metric_code,
				"metric_name": r.metric_name,
				"pillar": r.pillar,
				"unit": r.unit,
				"reporting_framework": r.reporting_framework,
				"target_value": str(r.target_value) if r.target_value is not None else None,
				"target_year": r.target_year,
			}
			for r in rows
		])

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		session = _get_session()
		data = request.get_json(force=True) or {}
		required = (
			"tenant_id", "metric_code", "metric_name",
			"pillar", "unit", "reporting_framework",
		)
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"error": f"Missing: {missing}"}), 400
		try:
			result = _svc().create_metric(
				session=session,
				tenant_id=data["tenant_id"],
				metric_code=data["metric_code"],
				metric_name=data["metric_name"],
				pillar=data["pillar"],
				unit=data["unit"],
				reporting_framework=data["reporting_framework"],
				target_value=(
					Decimal(str(data["target_value"]))
					if data.get("target_value") is not None else None
				),
				target_year=data.get("target_year"),
				description=data.get("description"),
			)
			session.commit()
			return jsonify(result), 201
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422


# ---------------------------------------------------------------------------
# ESGSnapshotView
# ---------------------------------------------------------------------------

class ESGSnapshotView(BaseView):
	route_base = "/sustainability/esg-snapshots"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.grc.sustainability.models import ESGSnapshot, ESGMetric
		session = _get_session()
		tenant_id = request.args.get("tenant_id")
		metric_id = request.args.get("metric_id")
		q = (
			sa.select(ESGSnapshot, ESGMetric.metric_code, ESGMetric.pillar)
			.join(ESGMetric, ESGMetric.id == ESGSnapshot.metric_id)
			.order_by(ESGSnapshot.snapshot_year.desc(), ESGMetric.metric_code)
		)
		if tenant_id:
			q = q.where(ESGSnapshot.tenant_id == tenant_id)
		if metric_id:
			q = q.where(ESGSnapshot.metric_id == metric_id)
		rows = session.execute(q).all()
		return jsonify([
			{
				"id": r.ESGSnapshot.id,
				"metric_id": str(r.ESGSnapshot.metric_id),
				"metric_code": r.metric_code,
				"pillar": r.pillar,
				"snapshot_year": r.ESGSnapshot.snapshot_year,
				"actual_value": str(r.ESGSnapshot.actual_value),
				"target_value": (
					str(r.ESGSnapshot.target_value)
					if r.ESGSnapshot.target_value is not None else None
				),
				"improvement_pct": (
					str(r.ESGSnapshot.improvement_pct)
					if r.ESGSnapshot.improvement_pct is not None else None
				),
				"verified_by": r.ESGSnapshot.verified_by,
			}
			for r in rows
		])

	@expose("/", methods=["POST"])
	@has_access
	def capture(self):
		session = _get_session()
		data = request.get_json(force=True) or {}
		required = ("tenant_id", "metric_id", "snapshot_year", "actual_value")
		missing = [f for f in required if data.get(f) is None]
		if missing:
			return jsonify({"error": f"Missing: {missing}"}), 400
		try:
			result = _svc().capture_snapshot(
				session=session,
				tenant_id=data["tenant_id"],
				metric_id=data["metric_id"],
				snapshot_year=int(data["snapshot_year"]),
				actual_value=Decimal(str(data["actual_value"])),
				target_value=(
					Decimal(str(data["target_value"]))
					if data.get("target_value") is not None else None
				),
				notes=data.get("notes"),
				verified_by=data.get("verified_by"),
			)
			session.commit()
			return jsonify(result), 201
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422


# ---------------------------------------------------------------------------
# SustainabilityReportView
# ---------------------------------------------------------------------------

class SustainabilityReportView(BaseView):
	"""ESG and GHG reports.

	GET /sustainability/reports/ghg-scope-rollup  — tCO2e by scope for a period
	GET /sustainability/reports/esg-dashboard      — all metrics, latest snapshot
	GET /sustainability/reports/emission-trend     — monthly CO2e trend
	"""

	route_base = "/sustainability/reports"
	default_view = "index"

	@expose("/")
	@has_access
	def index(self):
		return jsonify({
			"reports": [
				{"name": "GHG Scope Rollup",
				 "endpoint": "/sustainability/reports/ghg-scope-rollup"},
				{"name": "ESG Dashboard",
				 "endpoint": "/sustainability/reports/esg-dashboard"},
				{"name": "Emission Trend",
				 "endpoint": "/sustainability/reports/emission-trend"},
			]
		})

	@expose("/ghg-scope-rollup")
	@has_access
	def ghg_scope_rollup(self):
		"""Query params: tenant_id, period_from, period_to, verified_only."""
		session = _get_session()
		args = request.args
		required = ("tenant_id", "period_from", "period_to")
		missing = [f for f in required if not args.get(f)]
		if missing:
			return jsonify({"error": f"Missing: {missing}"}), 400
		result = _svc().get_scope_rollup(
			session,
			tenant_id=args["tenant_id"],
			period_from=date.fromisoformat(args["period_from"]),
			period_to=date.fromisoformat(args["period_to"]),
			verified_only=args.get("verified_only", "false").lower() == "true",
		)
		result["period_from"] = args["period_from"]
		result["period_to"] = args["period_to"]
		return jsonify(result)

	@expose("/esg-dashboard")
	@has_access
	def esg_dashboard(self):
		"""All ESG metrics with their most recent snapshot."""
		from pgappforge.plugins.erp.grc.sustainability.models import ESGMetric, ESGSnapshot
		from sqlalchemy import func as F
		session = _get_session()
		tenant_id = request.args.get("tenant_id", "")

		# Subquery: latest snapshot year per metric
		latest_year_sub = (
			sa.select(
				ESGSnapshot.metric_id,
				F.max(ESGSnapshot.snapshot_year).label("max_year"),
			)
			.where(ESGSnapshot.tenant_id == tenant_id)
			.group_by(ESGSnapshot.metric_id)
			.subquery()
		)

		rows = session.execute(
			sa.select(
				ESGMetric.id.label("metric_id"),
				ESGMetric.metric_code,
				ESGMetric.metric_name,
				ESGMetric.pillar,
				ESGMetric.unit,
				ESGMetric.reporting_framework,
				ESGMetric.target_value.label("metric_target"),
				ESGMetric.target_year,
				ESGSnapshot.snapshot_year,
				ESGSnapshot.actual_value,
				ESGSnapshot.target_value.label("snapshot_target"),
				ESGSnapshot.improvement_pct,
			)
			.outerjoin(
				latest_year_sub,
				latest_year_sub.c.metric_id == ESGMetric.id,
			)
			.outerjoin(
				ESGSnapshot,
				sa.and_(
					ESGSnapshot.metric_id == ESGMetric.id,
					ESGSnapshot.snapshot_year == latest_year_sub.c.max_year,
					ESGSnapshot.tenant_id == tenant_id,
				),
			)
			.where(ESGMetric.tenant_id == tenant_id)
			.order_by(ESGMetric.pillar, ESGMetric.metric_code)
		).all()

		return jsonify([
			{
				"metric_id": str(r.metric_id),
				"metric_code": r.metric_code,
				"metric_name": r.metric_name,
				"pillar": r.pillar,
				"unit": r.unit,
				"reporting_framework": r.reporting_framework,
				"target_value": str(r.metric_target) if r.metric_target is not None else None,
				"target_year": r.target_year,
				"latest_year": r.snapshot_year,
				"actual_value": str(r.actual_value) if r.actual_value is not None else None,
				"improvement_pct": str(r.improvement_pct) if r.improvement_pct is not None else None,
			}
			for r in rows
		])

	@expose("/emission-trend")
	@has_access
	def emission_trend(self):
		"""Monthly CO2e trend for a tenant. Query params: tenant_id, months (default 12)."""
		from pgappforge.plugins.erp.grc.sustainability.models import EmissionRecord, EmissionSource
		from sqlalchemy import func as F, extract
		session = _get_session()
		tenant_id = request.args.get("tenant_id", "")
		months = min(int(request.args.get("months", 12)), 60)

		rows = session.execute(
			sa.select(
				extract("year", EmissionRecord.period_date).label("year"),
				extract("month", EmissionRecord.period_date).label("month"),
				EmissionSource.scope,
				F.sum(EmissionRecord.co2e_tonnes).label("total_co2e"),
			)
			.join(EmissionSource, EmissionSource.id == EmissionRecord.source_id)
			.where(EmissionRecord.tenant_id == tenant_id)
			.group_by(
				extract("year", EmissionRecord.period_date),
				extract("month", EmissionRecord.period_date),
				EmissionSource.scope,
			)
			.order_by(
				sa.desc(extract("year", EmissionRecord.period_date)),
				sa.desc(extract("month", EmissionRecord.period_date)),
			)
			.limit(months * 3)  # 3 scopes × months
		).all()

		return jsonify([
			{
				"year": int(r.year),
				"month": int(r.month),
				"scope": r.scope,
				"total_co2e": str(r.total_co2e),
			}
			for r in rows
		])


__all__ = [
	"EmissionSourceView",
	"EmissionRecordView",
	"ESGMetricView",
	"ESGSnapshotView",
	"SustainabilityReportView",
]
