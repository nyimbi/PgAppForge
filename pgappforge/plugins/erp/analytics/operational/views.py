"""
pgappforge/plugins/erp/analytics/operational/views.py

Flask views for the Operational Analytics plugin.

Route summary
-------------
KPIDefinitionView    /analytics/kpis/
KPISnapshotView      /analytics/kpi-snapshots/
AnalyticsQueryView   /analytics/queries/
AnalyticsReportView  /analytics/reports/
  ├─ /kpi_dashboard    — KPI dashboard (HTML: on-track/at-risk/off-track counts)
  ├─ /trend/<kpi_id>   — KPI trend sparkline data (JSON)
  └─ /run/<report_id>  — Generate and return report payload (JSON)
"""
from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation

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
# KPIDefinitionView
# ---------------------------------------------------------------------------

class KPIDefinitionView(BaseView):
	"""KPI Definition CRUD.

	GET  /analytics/kpis/         — list (HTML)
	GET  /analytics/kpis/<id>     — detail (JSON)
	POST /analytics/kpis/         — create (JSON)
	PUT  /analytics/kpis/<id>     — update (JSON)
	"""

	route_base = "/analytics/kpis"
	default_view = "list"

	@expose("/", methods=["GET"])
	@has_access
	def list(self):
		session = _get_session()
		from pgappforge.plugins.erp.analytics.operational.models import KPIDefinition
		rows = session.execute(
			sa.select(KPIDefinition).order_by(KPIDefinition.domain, KPIDefinition.kpi_code)
		).scalars().all()
		items = [
			f"<tr><td>{_he(r.kpi_code)}</td><td>{_he(r.kpi_name)}</td>"
			f"<td>{_he(r.domain)}</td><td>{_he(r.frequency)}</td>"
			f"<td>{_he(r.target_direction)}</td><td>{'Active' if r.is_active else 'Inactive'}</td></tr>"
			for r in rows
		]
		html = (
			"<h2>KPI Definitions</h2>"
			"<table><thead><tr><th>Code</th><th>Name</th><th>Domain</th>"
			"<th>Frequency</th><th>Direction</th><th>Status</th></tr></thead>"
			f"<tbody>{''.join(items)}</tbody></table>"
		)
		return make_response(html, 200, {"Content-Type": "text/html; charset=utf-8"})

	@expose("/<string:kpi_id>", methods=["GET"])
	@has_access
	def detail(self, kpi_id: str):
		session = _get_session()
		from pgappforge.plugins.erp.analytics.operational.models import KPIDefinition
		row = session.execute(
			sa.select(KPIDefinition).where(KPIDefinition.id == kpi_id)
		).scalar_one_or_none()
		if row is None:
			abort(404)
		return jsonify({
			"id": row.id,
			"kpi_code": row.kpi_code,
			"kpi_name": row.kpi_name,
			"domain": row.domain,
			"formula": row.formula,
			"unit": row.unit,
			"frequency": row.frequency,
			"target_value": str(row.target_value) if row.target_value is not None else None,
			"target_direction": row.target_direction,
			"tags": row.tags or [],
			"is_active": row.is_active,
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		session = _get_session()
		data = request.get_json(force=True) or {}
		from pgappforge.plugins.erp.analytics.operational.models import KPIDefinition
		kpi = KPIDefinition(
			tenant_id=data["tenant_id"],
			kpi_code=data["kpi_code"],
			kpi_name=data["kpi_name"],
			domain=data["domain"],
			formula=data.get("formula"),
			unit=data.get("unit"),
			frequency=data.get("frequency", "MONTHLY"),
			target_value=data.get("target_value"),
			target_direction=data.get("target_direction", "HIGHER"),
			owner_id=data.get("owner_id"),
			tags=data.get("tags", []),
			is_active=data.get("is_active", True),
		)
		session.add(kpi)
		session.commit()
		return jsonify({"id": kpi.id, "kpi_code": kpi.kpi_code}), 201


# ---------------------------------------------------------------------------
# KPISnapshotView
# ---------------------------------------------------------------------------

class KPISnapshotView(BaseView):
	"""KPI Snapshot management.

	GET  /analytics/kpi-snapshots/                    — list (HTML)
	POST /analytics/kpi-snapshots/                    — record new snapshot (JSON)
	GET  /analytics/kpi-snapshots/trend/<kpi_id>      — trend data (JSON)
	"""

	route_base = "/analytics/kpi-snapshots"
	default_view = "list"

	@expose("/", methods=["GET"])
	@has_access
	def list(self):
		session = _get_session()
		from pgappforge.plugins.erp.analytics.operational.models import KPIDefinition, KPISnapshot
		rows = session.execute(
			sa.select(KPISnapshot, KPIDefinition.kpi_code)
			.join(KPIDefinition, KPIDefinition.id == KPISnapshot.kpi_id)
			.order_by(KPISnapshot.snapshot_date.desc())
			.limit(200)
		).all()
		items = [
			f"<tr><td>{_he(code)}</td><td>{_he(s.snapshot_date)}</td>"
			f"<td>{_he(s.actual_value)}</td><td>{_he(s.target_value or '—')}</td>"
			f"<td>{_he(s.variance_pct or '—')}%</td>"
			f"<td><span class='badge badge-{'success' if s.status == 'ON_TRACK' else 'warning' if s.status == 'AT_RISK' else 'danger'}'>"
			f"{_he(s.status)}</span></td></tr>"
			for s, code in rows
		]
		html = (
			"<h2>KPI Snapshots</h2>"
			"<table><thead><tr><th>KPI</th><th>Date</th><th>Actual</th>"
			"<th>Target</th><th>Variance</th><th>Status</th></tr></thead>"
			f"<tbody>{''.join(items)}</tbody></table>"
		)
		return make_response(html, 200, {"Content-Type": "text/html; charset=utf-8"})

	@expose("/", methods=["POST"])
	@has_access
	def record(self):
		session = _get_session()
		data = request.get_json(force=True) or {}
		from datetime import date
		from pgappforge.plugins.erp.analytics.operational.services import OperationalAnalyticsService
		snap = OperationalAnalyticsService.record_snapshot(
			kpi_id=data["kpi_id"],
			snapshot_date=date.fromisoformat(data["snapshot_date"]),
			actual_value=Decimal(str(data["actual_value"])),
			session=session,
			target_override=Decimal(str(data["target_value"])) if data.get("target_value") else None,
		)
		session.commit()
		return jsonify({"id": snap.id, "status": snap.status}), 201

	@expose("/trend/<string:kpi_id>", methods=["GET"])
	@has_access
	def trend(self, kpi_id: str):
		session = _get_session()
		periods = min(int(request.args.get("periods", 12)), 52)
		from pgappforge.plugins.erp.analytics.operational.services import OperationalAnalyticsService
		snaps = OperationalAnalyticsService.get_kpi_trend(kpi_id, periods, session)
		return jsonify([
			{
				"date": str(s.snapshot_date),
				"actual": str(s.actual_value),
				"target": str(s.target_value) if s.target_value else None,
				"variance_pct": str(s.variance_pct) if s.variance_pct else None,
				"status": s.status,
			}
			for s in snaps
		])


# ---------------------------------------------------------------------------
# AnalyticsQueryView
# ---------------------------------------------------------------------------

class AnalyticsQueryView(BaseView):
	"""Saved Query management.

	GET  /analytics/queries/          — list
	POST /analytics/queries/          — create
	POST /analytics/queries/<id>/run  — execute with params (JSON)
	"""

	route_base = "/analytics/queries"
	default_view = "list"

	@expose("/", methods=["GET"])
	@has_access
	def list(self):
		session = _get_session()
		from pgappforge.plugins.erp.analytics.operational.models import AnalyticsQuery
		rows = session.execute(
			sa.select(AnalyticsQuery).order_by(AnalyticsQuery.name)
		).scalars().all()
		items = [
			f"<tr><td>{_he(r.name)}</td><td>{'Public' if r.is_public else 'Private'}</td>"
			f"<td>{_he(r.last_run_at or 'Never')}</td>"
			f"<td>{_he(r.average_runtime_ms or '—')} ms</td></tr>"
			for r in rows
		]
		html = (
			"<h2>Saved Queries</h2>"
			"<table><thead><tr><th>Name</th><th>Visibility</th>"
			"<th>Last Run</th><th>Avg Runtime</th></tr></thead>"
			f"<tbody>{''.join(items)}</tbody></table>"
		)
		return make_response(html, 200, {"Content-Type": "text/html; charset=utf-8"})

	@expose("/<string:query_id>/run", methods=["POST"])
	@has_access
	def run(self, query_id: str):
		session = _get_session()
		params = request.get_json(force=True) or {}
		from pgappforge.plugins.erp.analytics.operational.services import (
			OperationalAnalyticsService,
			QueryExecutionError,
		)
		try:
			result = OperationalAnalyticsService.run_query(query_id, params, session)
			session.commit()
			return jsonify(result)
		except QueryExecutionError as exc:
			return jsonify({"error": str(exc)}), 422


# ---------------------------------------------------------------------------
# AnalyticsReportView  (report catalogue + 3 built-in report templates)
# ---------------------------------------------------------------------------

class AnalyticsReportView(BaseView):
	"""Analytics Report definitions and generation.

	GET  /analytics/reports/                        — report catalogue (HTML)
	GET  /analytics/reports/kpi_dashboard           — KPI dashboard (HTML)
	GET  /analytics/reports/kpi_status_summary      — ON_TRACK/AT_RISK/OFF_TRACK counts (JSON)
	POST /analytics/reports/<id>/generate           — generate report (JSON)
	"""

	route_base = "/analytics/reports"
	default_view = "catalogue"

	@expose("/", methods=["GET"])
	@has_access
	def catalogue(self):
		session = _get_session()
		from pgappforge.plugins.erp.analytics.operational.models import AnalyticsReport
		rows = session.execute(
			sa.select(AnalyticsReport).order_by(AnalyticsReport.category, AnalyticsReport.name)
		).scalars().all()
		items = [
			f"<tr><td>{_he(r.name)}</td><td>{_he(r.category)}</td>"
			f"<td>{'Scheduled' if r.is_scheduled else 'On-demand'}</td>"
			f"<td>{_he(r.last_generated_at or 'Never')}</td></tr>"
			for r in rows
		]
		html = (
			"<h2>Analytics Reports</h2>"
			"<table><thead><tr><th>Name</th><th>Category</th>"
			"<th>Schedule</th><th>Last Generated</th></tr></thead>"
			f"<tbody>{''.join(items)}</tbody></table>"
		)
		return make_response(html, 200, {"Content-Type": "text/html; charset=utf-8"})

	@expose("/kpi_dashboard", methods=["GET"])
	@has_access
	def kpi_dashboard(self):
		"""HTML KPI dashboard: latest snapshot per KPI with status badges."""
		session = _get_session()
		from pgappforge.plugins.erp.analytics.operational.models import KPIDefinition, KPISnapshot

		# Latest snapshot per KPI via subquery
		subq = (
			sa.select(
				KPISnapshot.kpi_id,
				sa.func.max(KPISnapshot.snapshot_date).label("max_date"),
			)
			.group_by(KPISnapshot.kpi_id)
			.subquery()
		)
		rows = session.execute(
			sa.select(KPISnapshot, KPIDefinition.kpi_code, KPIDefinition.kpi_name, KPIDefinition.domain)
			.join(KPIDefinition, KPIDefinition.id == KPISnapshot.kpi_id)
			.join(subq, sa.and_(
				subq.c.kpi_id == KPISnapshot.kpi_id,
				subq.c.max_date == KPISnapshot.snapshot_date,
			))
			.order_by(KPIDefinition.domain, KPIDefinition.kpi_code)
		).all()

		on_track = sum(1 for s, *_ in rows if s.status == "ON_TRACK")
		at_risk = sum(1 for s, *_ in rows if s.status == "AT_RISK")
		off_track = sum(1 for s, *_ in rows if s.status == "OFF_TRACK")

		cards = "".join(
			f"<div class='kpi-card status-{s.status.lower()}'>"
			f"<h4>{_he(name)}</h4><p class='domain'>{_he(domain)}</p>"
			f"<p class='actual'>{_he(s.actual_value)}</p>"
			f"<p class='variance'>{_he(s.variance_pct or '—')}%</p>"
			f"<span class='badge'>{_he(s.status)}</span></div>"
			for s, code, name, domain in rows
		)
		summary = (
			f"<div class='summary'>"
			f"<span class='on-track'>&#10003; {on_track} On Track</span> "
			f"<span class='at-risk'>&#9888; {at_risk} At Risk</span> "
			f"<span class='off-track'>&#10007; {off_track} Off Track</span>"
			f"</div>"
		)
		html = f"<h2>KPI Dashboard</h2>{summary}<div class='kpi-grid'>{cards}</div>"
		return make_response(html, 200, {"Content-Type": "text/html; charset=utf-8"})

	@expose("/kpi_status_summary", methods=["GET"])
	@has_access
	def kpi_status_summary(self):
		"""JSON: count of KPIs by status (latest snapshot per KPI)."""
		session = _get_session()
		from pgappforge.plugins.erp.analytics.operational.models import KPISnapshot

		subq = (
			sa.select(
				KPISnapshot.kpi_id,
				sa.func.max(KPISnapshot.snapshot_date).label("max_date"),
			)
			.group_by(KPISnapshot.kpi_id)
			.subquery()
		)
		rows = session.execute(
			sa.select(KPISnapshot.status, sa.func.count().label("cnt"))
			.join(subq, sa.and_(
				subq.c.kpi_id == KPISnapshot.kpi_id,
				subq.c.max_date == KPISnapshot.snapshot_date,
			))
			.group_by(KPISnapshot.status)
		).all()

		return jsonify({row.status: row.cnt for row in rows})

	@expose("/<string:report_id>/generate", methods=["POST"])
	@has_access
	def generate(self, report_id: str):
		session = _get_session()
		from pgappforge.plugins.erp.analytics.operational.services import (
			OperationalAnalyticsService,
			ReportNotFoundError,
		)
		try:
			payload = OperationalAnalyticsService.generate_report(report_id, session)
			session.commit()
			return jsonify(payload)
		except ReportNotFoundError as exc:
			return jsonify({"error": str(exc)}), 404


__all__ = [
	"KPIDefinitionView",
	"KPISnapshotView",
	"AnalyticsQueryView",
	"AnalyticsReportView",
]
