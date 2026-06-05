"""
pgappforge/plugins/erp/industry/water/views.py

Flask views for the Water Management plugin.

Registered views:
  WaterBodyView      — CRUD for water bodies
  MonitoringView     — CRUD + MapWidget for station positions,
                       AdvancedChartsWidget for parameter trends
  FloodWarningView   — CRUD + issue/cancel actions + MapWidget
  AllocationView     — CRUD + CurrencyWidget equiv (usage % RangeSlider),
                       usage tracking endpoint
  WaterQualityView   — Measurements list + report endpoint
  WaterDashboardView — Overview dashboard per water body
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone

import sqlalchemy as sa
from flask import abort, jsonify, make_response, request

from pgappforge import BaseView, expose
from pgappforge.security.decorators import has_access
from pgappforge.plugins.erp.foundation.commons import status_badge
from pgappforge.plugins.erp.foundation.view_helpers import (
	map_widget,
	chart_widget,
	select2_widget,
	rich_text_widget,
	progress_widget,
	json_widget,
	date_widget,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

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


def _page_html(title: str, body: str) -> str:
	return (
		f'<!DOCTYPE html><html><head><meta charset="utf-8"><title>{title}</title>'
		'<link rel="stylesheet" href="https://maxcdn.bootstrapcdn.com/bootstrap/3.3.7/css/bootstrap.min.css">'
		'<style>body{padding:24px} .map-placeholder{background:#e3f2fd;border:1px solid #90caf9;'
		'border-radius:4px;padding:12px;color:#1565c0;font-size:.85em} '
		'.chart-placeholder{background:#e8f5e9;border:1px solid #a5d6a7;'
		'border-radius:4px;padding:12px;color:#2e7d32;font-size:.85em} '
		'.usage-bar{height:20px;border-radius:3px}'
		'@media print{.noprint{display:none}}</style>'
		f'</head><body>{body}</body></html>'
	)


def _map_placeholder(label: str, geometry_wkt: str | None, zoom: int = 12) -> str:
	cfg = map_widget(zoom=zoom)
	wkt_display = _he(geometry_wkt[:80] + "…" if geometry_wkt and len(geometry_wkt) > 80 else (geometry_wkt or "No geometry"))
	return (
		f'<div class="map-placeholder" data-widget="{_he(str(cfg))}">'
		f'<strong>{_he(label)}</strong><br>'
		f'<small>Widget: {cfg["type"]} | Geometry: {wkt_display}</small>'
		f'</div>'
	)


def _warning_badge(level: str) -> str:
	colors = {"ADVISORY": "info", "WATCH": "warning", "WARNING": "danger", "EMERGENCY": "danger"}
	color = colors.get((level or "").upper(), "default")
	bold = "EMERGENCY" in (level or "").upper()
	tag = "strong" if bold else "span"
	return f'<{tag} class="label label-{color}">{_he(level or "—")}</{tag}>'


def _status_badge(status: str) -> str:
	colors = {"GOOD": "success", "MODERATE": "warning", "POOR": "danger", "BAD": "danger",
	          "ACTIVE": "success", "SUSPENDED": "warning", "EXPIRED": "default", "CANCELLED": "default"}
	color = colors.get((status or "").upper(), "default")
	return f'<span class="label label-{color}">{_he(status or "—")}</span>'


def _usage_bar(usage_pct: float) -> str:
	color = "success" if usage_pct < 60 else ("warning" if usage_pct < 85 else "danger")
	pct = min(100, max(0, usage_pct))
	cfg = progress_widget(max_value=100)
	return (
		f'<div class="progress" data-widget="{_he(str(cfg))}" style="margin-bottom:0">'
		f'<div class="progress-bar progress-bar-{color}" style="width:{pct:.0f}%">'
		f'{pct:.1f}%</div></div>'
	)


# ---------------------------------------------------------------------------
# WaterBodyView
# ---------------------------------------------------------------------------

class WaterBodyView(BaseView):
	"""Water Body CRUD.

	GET  /water/bodies/        — list
	GET  /water/bodies/<id>    — detail
	POST /water/bodies/        — create
	PUT  /water/bodies/<id>    — update
	"""

	route_base = "/water/bodies"
	default_view = "list"

	_widgets = {
		"location": map_widget(zoom=9),
		"body_type": select2_widget(["RIVER", "LAKE", "RESERVOIR", "GROUNDWATER", "WETLAND"]),
		"status": select2_widget(["GOOD", "MODERATE", "POOR", "BAD"]),
	}

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.industry.water.models import WaterBody
		session = _get_session()
		q = sa.select(WaterBody).order_by(WaterBody.name)
		for param, col in (
			("body_type", WaterBody.body_type),
			("status", WaterBody.status),
			("tenant_id", WaterBody.tenant_id),
		):
			val = request.args.get(param)
			if val:
				q = q.where(col == val)
		bodies = session.execute(q.limit(300)).scalars().all()

		if request.args.get("format") == "json":
			return jsonify({"water_bodies": [
				{
					"id": b.id, "name": b.name, "body_type": b.body_type,
					"status": b.status, "catchment_area_km2": str(b.catchment_area_km2 or ""),
					"monitoring_authority": b.monitoring_authority,
				}
				for b in bodies
			]})

		rows = "".join(
			f"<tr>"
			f"<td>{_he(b.name)}</td>"
			f"<td><span class='label label-info'>{_he(b.body_type)}</span></td>"
			f"<td>{_status_badge(b.status)}</td>"
			f"<td>{_he(b.catchment_area_km2 or '—')} km²</td>"
			f"<td>{_he(b.monitoring_authority or '—')}</td>"
			f"<td><a href='/water/bodies/{_he(b.id)}' class='btn btn-xs btn-primary'>View</a></td>"
			f"</tr>"
			for b in bodies
		)
		body_html = (
			'<h3>Water Bodies</h3>'
			'<table class="table table-bordered table-condensed table-hover">'
			'<thead><tr><th>Name</th><th>Type</th><th>Status</th><th>Catchment</th><th>Authority</th><th></th></tr></thead>'
			f'<tbody>{rows}</tbody></table>'
		)
		return make_response(_page_html("Water Bodies", body_html), 200)

	@expose("/<string:body_id>")
	@has_access
	def detail(self, body_id: str):
		from pgappforge.plugins.erp.industry.water.models import WaterBody
		session = _get_session()
		wb = session.get(WaterBody, body_id)
		if wb is None:
			abort(404)
		if request.args.get("format") == "json":
			return jsonify({
				"id": wb.id, "name": wb.name, "body_type": wb.body_type,
				"location": wb.location, "catchment_area_km2": str(wb.catchment_area_km2 or ""),
				"monitoring_authority": wb.monitoring_authority, "status": wb.status,
			})
		body_html = (
			f'<h3>{_he(wb.name)} {_status_badge(wb.status)}</h3>'
			f'{_map_placeholder("Water Body Extent", wb.location, zoom=9)}'
			f'<dl class="dl-horizontal">'
			f'<dt>Type</dt><dd>{_he(wb.body_type)}</dd>'
			f'<dt>Catchment</dt><dd>{_he(wb.catchment_area_km2 or "—")} km²</dd>'
			f'<dt>Authority</dt><dd>{_he(wb.monitoring_authority or "—")}</dd>'
			f'<dt>Stations</dt><dd>{_he(len(wb.stations))}</dd>'
			f'<dt>Active Warnings</dt><dd>{_he(sum(1 for w in wb.flood_warnings if w.status == "ACTIVE"))}</dd>'
			f'</dl>'
			f'<a href="/water/dashboard/{_he(body_id)}" class="btn btn-primary noprint">Dashboard</a> '
			f'<a href="/water/bodies/{_he(body_id)}/quality-report?format=json" class="btn btn-default noprint">Quality Report</a>'
		)
		return make_response(_page_html(wb.name, body_html), 200)

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		from pgappforge.plugins.erp.industry.water.models import WaterBody
		session = _get_session()
		data = request.get_json(silent=True) or {}
		required = ("tenant_id", "name", "body_type")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"ok": False, "error": f"missing: {missing}"}), 400
		wb = WaterBody(
			tenant_id=data["tenant_id"],
			name=data["name"],
			body_type=data["body_type"],
			location=data.get("location"),
			catchment_area_km2=data.get("catchment_area_km2"),
			monitoring_authority=data.get("monitoring_authority"),
			status=data.get("status", "MODERATE"),
		)
		session.add(wb)
		session.commit()
		return jsonify({"ok": True, "id": wb.id}), 201

	@expose("/<string:body_id>", methods=["PUT"])
	@has_access
	def update(self, body_id: str):
		from pgappforge.plugins.erp.industry.water.models import WaterBody
		session = _get_session()
		wb = session.get(WaterBody, body_id)
		if wb is None:
			abort(404)
		data = request.get_json(silent=True) or {}
		for fld in ("name", "body_type", "location", "catchment_area_km2", "monitoring_authority", "status"):
			if fld in data:
				setattr(wb, fld, data[fld])
		wb.updated_at = datetime.now(timezone.utc)
		session.commit()
		return jsonify({"ok": True})

	@expose("/<string:body_id>/quality-report")
	@has_access
	def quality_report(self, body_id: str):
		from pgappforge.plugins.erp.industry.water.services import WaterService, WaterServiceError
		session = _get_session()
		start_str = request.args.get("start", date.today().replace(month=1, day=1).isoformat())
		end_str = request.args.get("end", date.today().isoformat())
		try:
			report = WaterService().generate_water_quality_report(
				body_id,
				date.fromisoformat(start_str),
				date.fromisoformat(end_str),
				session,
			)
			return jsonify(report)
		except WaterServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 400


# ---------------------------------------------------------------------------
# MonitoringView
# ---------------------------------------------------------------------------

class MonitoringView(BaseView):
	"""Monitoring Station CRUD + quality data.

	GET  /water/stations/                   — list (filter by water_body_id, is_active)
	GET  /water/stations/<id>               — detail with map position
	POST /water/stations/                   — create
	GET  /water/stations/<id>/quality       — latest quality check
	GET  /water/stations/<id>/trends        — chart data for parameters
	POST /water/stations/<id>/measurements  — ingest measurement
	POST /water/stations/<id>/flow          — ingest flow record
	"""

	route_base = "/water/stations"
	default_view = "list"

	_widgets = {
		"location": map_widget(zoom=14),
		"parameters_monitored": select2_widget(["PH", "DO", "TURBIDITY", "CONDUCTIVITY", "NITRATE", "PHOSPHATE", "ECOLI"]),
		"parameter_chart": chart_widget("line"),
	}

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.industry.water.models import MonitoringStation
		session = _get_session()
		q = sa.select(MonitoringStation).order_by(MonitoringStation.station_code)
		for param, col in (
			("water_body_id", MonitoringStation.water_body_id),
			("tenant_id", MonitoringStation.tenant_id),
		):
			val = request.args.get(param)
			if val:
				q = q.where(col == val)
		if request.args.get("active") == "1":
			q = q.where(MonitoringStation.is_active == True)
		stations = session.execute(q.limit(300)).scalars().all()

		if request.args.get("format") == "json":
			return jsonify({"stations": [
				{
					"id": s.id, "station_code": s.station_code, "name": s.name,
					"water_body_id": s.water_body_id, "is_active": s.is_active,
					"parameters_monitored": s.parameters_monitored,
				}
				for s in stations
			]})

		rows = "".join(
			f"<tr>"
			f"<td><code>{_he(s.station_code)}</code></td>"
			f"<td>{_he(s.name)}</td>"
			f"<td>{'<span class=\'label label-success\'>Active</span>' if s.is_active else '<span class=\'label label-default\'>Inactive</span>'}</td>"
			f"<td>{_he(', '.join(s.parameters_monitored or []))}</td>"
			f"<td><a href='/water/stations/{_he(s.id)}' class='btn btn-xs btn-primary'>View</a></td>"
			f"</tr>"
			for s in stations
		)
		body = (
			'<h3>Monitoring Stations</h3>'
			'<table class="table table-bordered table-condensed table-hover">'
			'<thead><tr><th>Code</th><th>Name</th><th>Status</th><th>Parameters</th><th></th></tr></thead>'
			f'<tbody>{rows}</tbody></table>'
		)
		return make_response(_page_html("Monitoring Stations", body), 200)

	@expose("/<string:station_id>")
	@has_access
	def detail(self, station_id: str):
		from pgappforge.plugins.erp.industry.water.models import MonitoringStation
		session = _get_session()
		station = session.get(MonitoringStation, station_id)
		if station is None:
			abort(404)
		if request.args.get("format") == "json":
			return jsonify({
				"id": station.id, "station_code": station.station_code, "name": station.name,
				"water_body_id": station.water_body_id, "location": station.location,
				"installation_date": station.installation_date.isoformat() if station.installation_date else None,
				"parameters_monitored": station.parameters_monitored,
				"is_active": station.is_active, "operator_id": station.operator_id,
			})
		chart_cfg = chart_widget("line")
		body = (
			f'<h3>Station: {_he(station.station_code)} — {_he(station.name)}</h3>'
			f'{_map_placeholder("Station Location", station.location, zoom=14)}'
			f'<div class="chart-placeholder" data-widget="{_he(str(chart_cfg))}" style="margin-top:8px">'
			f'Parameter Trends — Widget: {chart_cfg["type"]} (chart_type={chart_cfg["config"]["chart_type"]})</div>'
			f'<dl class="dl-horizontal">'
			f'<dt>Water Body</dt><dd>{_he(station.water_body_id)}</dd>'
			f'<dt>Installed</dt><dd>{_he(station.installation_date or "—")}</dd>'
			f'<dt>Parameters</dt><dd>{_he(", ".join(station.parameters_monitored or []))}</dd>'
			f'<dt>Active</dt><dd>{"Yes" if station.is_active else "No"}</dd>'
			f'</dl>'
			f'<a href="/water/stations/{_he(station_id)}/quality?format=json" class="btn btn-default noprint">Check Quality</a> '
			f'<a href="/water/stations/{_he(station_id)}/trends?format=json" class="btn btn-default noprint">Trends</a>'
		)
		return make_response(_page_html(f"Station: {station.station_code}", body), 200)

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		from pgappforge.plugins.erp.industry.water.models import MonitoringStation
		session = _get_session()
		data = request.get_json(silent=True) or {}
		required = ("tenant_id", "station_code", "water_body_id", "name")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"ok": False, "error": f"missing: {missing}"}), 400
		station = MonitoringStation(
			tenant_id=data["tenant_id"],
			station_code=data["station_code"],
			water_body_id=data["water_body_id"],
			name=data["name"],
			location=data.get("location"),
			installation_date=date.fromisoformat(data["installation_date"]) if data.get("installation_date") else None,
			parameters_monitored=data.get("parameters_monitored") or [],
			is_active=bool(data.get("is_active", True)),
			operator_id=data.get("operator_id"),
		)
		session.add(station)
		session.commit()
		return jsonify({"ok": True, "id": station.id}), 201

	@expose("/<string:station_id>/quality")
	@has_access
	def quality(self, station_id: str):
		from pgappforge.plugins.erp.industry.water.services import WaterService, WaterServiceError
		session = _get_session()
		params = request.args.getlist("parameter") or None
		try:
			result = WaterService().check_water_quality(station_id, session, parameters=params)
			return jsonify(result)
		except WaterServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 400

	@expose("/<string:station_id>/trends")
	@has_access
	def trends(self, station_id: str):
		from pgappforge.plugins.erp.industry.water.models import WaterQualityMeasurement, MonitoringStation
		session = _get_session()
		station = session.get(MonitoringStation, station_id)
		if station is None:
			abort(404)
		days = int(request.args.get("days", 30))
		parameter = request.args.get("parameter", "PH")
		records = session.execute(
			sa.select(WaterQualityMeasurement).where(
				WaterQualityMeasurement.station_id == station_id,
				WaterQualityMeasurement.parameter == parameter,
				WaterQualityMeasurement.measured_at >= sa.func.now() - sa.text(f"INTERVAL '{days} days'"),
			).order_by(WaterQualityMeasurement.measured_at).limit(1000)
		).scalars().all()
		return jsonify({
			"station_id": station_id,
			"parameter": parameter,
			"days": days,
			"widget": chart_widget("line"),
			"labels": [r.measured_at.isoformat() if r.measured_at else None for r in records],
			"values": [str(r.value) for r in records],
			"quality_flags": [r.quality_flag for r in records],
		})

	@expose("/<string:station_id>/measurements", methods=["POST"])
	@has_access
	def ingest_measurement(self, station_id: str):
		from pgappforge.plugins.erp.industry.water.models import WaterQualityMeasurement, MonitoringStation
		from pgappforge.plugins.erp.industry.water.events import WaterQualityViolationEvent
		from pgappforge.plugins.erp.foundation.events import emit_event
		from pgappforge.plugins.erp.industry.water.services import DEFAULT_THRESHOLDS
		from decimal import Decimal
		session = _get_session()
		station = session.get(MonitoringStation, station_id)
		if station is None:
			abort(404)
		data = request.get_json(silent=True) or {}
		required = ("tenant_id", "parameter", "value", "measured_at")
		missing = [f for f in required if f not in data]
		if missing:
			return jsonify({"ok": False, "error": f"missing: {missing}"}), 400

		val = Decimal(str(data["value"]))
		param = data["parameter"]
		thr = DEFAULT_THRESHOLDS.get(param, {})
		quality_flag = "GOOD"
		if (thr.get("max") is not None and val > Decimal(str(thr["max"]))) or \
		   (thr.get("min") is not None and val < Decimal(str(thr["min"]))):
			quality_flag = "SUSPECT"

		m = WaterQualityMeasurement(
			tenant_id=data["tenant_id"],
			station_id=station_id,
			measured_at=datetime.fromisoformat(data["measured_at"]),
			parameter=param,
			value=val,
			unit=data.get("unit", thr.get("unit", "mg/L")),
			quality_flag=data.get("quality_flag", quality_flag),
			method=data.get("method"),
		)
		session.add(m)
		session.flush()

		if quality_flag == "SUSPECT":
			threshold_val = str(thr.get("max") or thr.get("min") or "")
			emit_event(
				WaterQualityViolationEvent(
					aggregate_id=m.id, aggregate_type="WaterQualityMeasurement",
					tenant_id=m.tenant_id, station_id=station_id,
					water_body_id=station.water_body_id,
					parameter=param, value=str(val), unit=m.unit,
					threshold=threshold_val, quality_flag=quality_flag,
				),
				session,
			)

		session.commit()
		return jsonify({"ok": True, "id": m.id, "quality_flag": m.quality_flag}), 201

	@expose("/<string:station_id>/flow", methods=["POST"])
	@has_access
	def ingest_flow(self, station_id: str):
		from pgappforge.plugins.erp.industry.water.models import WaterFlowRecord
		session = _get_session()
		data = request.get_json(silent=True) or {}
		required = ("tenant_id", "measured_at")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"ok": False, "error": f"missing: {missing}"}), 400
		fr = WaterFlowRecord(
			tenant_id=data["tenant_id"],
			station_id=station_id,
			measured_at=datetime.fromisoformat(data["measured_at"]),
			flow_m3_per_s=data.get("flow_m3_per_s"),
			water_level_m=data.get("water_level_m"),
			quality_flag=data.get("quality_flag", "GOOD"),
		)
		session.add(fr)
		session.commit()
		return jsonify({"ok": True, "id": fr.id}), 201


# ---------------------------------------------------------------------------
# FloodWarningView
# ---------------------------------------------------------------------------

class FloodWarningView(BaseView):
	"""Flood Warning CRUD + issue/cancel actions.

	GET  /water/warnings/             — list (filter by water_body_id, status, level)
	GET  /water/warnings/<id>         — detail with affected areas map
	POST /water/warnings/issue        — issue a new flood warning
	POST /water/warnings/<id>/cancel  — cancel active warning
	GET  /water/warnings/forecast     — flood risk forecast for a water body
	"""

	route_base = "/water/warnings"
	default_view = "list"

	_widgets = {
		"affected_areas": json_widget(mode="tree"),  # [{name, population, geometry_wkt}]
		"notes": rich_text_widget(height=150),
		"warning_level": select2_widget(["ADVISORY", "WATCH", "WARNING", "EMERGENCY"]),
		"location_map": map_widget(zoom=9),
	}

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.industry.water.models import FloodWarning
		session = _get_session()
		q = sa.select(FloodWarning).order_by(sa.desc(FloodWarning.issued_at))
		for param, col in (
			("water_body_id", FloodWarning.water_body_id),
			("status", FloodWarning.status),
			("warning_level", FloodWarning.warning_level),
			("tenant_id", FloodWarning.tenant_id),
		):
			val = request.args.get(param)
			if val:
				q = q.where(col == val)
		warnings = session.execute(q.limit(300)).scalars().all()

		if request.args.get("format") == "json":
			return jsonify({"flood_warnings": [
				{
					"id": w.id, "water_body_id": w.water_body_id,
					"warning_level": w.warning_level,
					"issued_at": w.issued_at.isoformat() if w.issued_at else None,
					"forecast_peak_level_m": str(w.forecast_peak_level_m or ""),
					"forecast_peak_at": w.forecast_peak_at.isoformat() if w.forecast_peak_at else None,
					"status": w.status,
				}
				for w in warnings
			]})

		rows = "".join(
			f"<tr>"
			f"<td>{_he(w.issued_at.strftime('%Y-%m-%d %H:%M') if w.issued_at else '—')}</td>"
			f"<td>{_he(w.water_body_id)}</td>"
			f"<td>{_warning_badge(w.warning_level)}</td>"
			f"<td>{_he(w.forecast_peak_level_m or '—')} m</td>"
			f"<td>{_status_badge(w.status)}</td>"
			f"<td><a href='/water/warnings/{_he(w.id)}' class='btn btn-xs btn-primary'>View</a></td>"
			f"</tr>"
			for w in warnings
		)
		body = (
			'<h3>Flood Warnings</h3>'
			'<table class="table table-bordered table-condensed table-hover">'
			'<thead><tr><th>Issued</th><th>Water Body</th><th>Level</th><th>Peak</th><th>Status</th><th></th></tr></thead>'
			f'<tbody>{rows}</tbody></table>'
		)
		return make_response(_page_html("Flood Warnings", body), 200)

	@expose("/<string:warning_id>")
	@has_access
	def detail(self, warning_id: str):
		from pgappforge.plugins.erp.industry.water.models import FloodWarning
		session = _get_session()
		w = session.get(FloodWarning, warning_id)
		if w is None:
			abort(404)
		if request.args.get("format") == "json":
			return jsonify({
				"id": w.id, "water_body_id": w.water_body_id,
				"warning_level": w.warning_level,
				"issued_at": w.issued_at.isoformat() if w.issued_at else None,
				"forecast_peak_level_m": str(w.forecast_peak_level_m or ""),
				"forecast_peak_at": w.forecast_peak_at.isoformat() if w.forecast_peak_at else None,
				"affected_areas": w.affected_areas, "status": w.status, "notes": w.notes,
			})
		# Render map placeholder for each affected area geometry
		area_items = "".join(
			f"<li>{_he(a.get('name', 'Unknown'))} "
			f"(pop. {_he(a.get('population', '?'))})</li>"
			for a in (w.affected_areas or [])
		) or "<li class='text-muted'>No affected areas specified</li>"

		body = (
			f'<h3>Flood Warning: {_warning_badge(w.warning_level)}</h3>'
			f'{_map_placeholder("Affected Area", None, zoom=9)}'
			f'<dl class="dl-horizontal">'
			f'<dt>Water Body</dt><dd>{_he(w.water_body_id)}</dd>'
			f'<dt>Level</dt><dd>{_warning_badge(w.warning_level)}</dd>'
			f'<dt>Issued At</dt><dd>{_he(w.issued_at)}</dd>'
			f'<dt>Peak Level</dt><dd>{_he(w.forecast_peak_level_m or "—")} m</dd>'
			f'<dt>Peak Time</dt><dd>{_he(w.forecast_peak_at or "—")}</dd>'
			f'<dt>Status</dt><dd>{_status_badge(w.status)}</dd>'
			f'<dt>Notes</dt><dd>{_he(w.notes or "—")}</dd>'
			f'</dl>'
			f'<h4>Affected Areas</h4><ul>{area_items}</ul>'
			f'{"<form method=post action=/water/warnings/" + _he(warning_id) + "/cancel>" if w.status == "ACTIVE" else ""}'
			f'{"<button class=btn btn-warning type=submit>Cancel Warning</button></form>" if w.status == "ACTIVE" else ""}'
		)
		return make_response(_page_html("Flood Warning", body), 200)

	@expose("/issue", methods=["POST"])
	@has_access
	def issue(self):
		from pgappforge.plugins.erp.industry.water.services import WaterService, WaterServiceError
		from flask_login import current_user
		session = _get_session()
		data = request.get_json(silent=True) or {}
		required = ("water_body_id", "warning_level")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"ok": False, "error": f"missing: {missing}"}), 400
		try:
			issued_by = getattr(current_user, "id", None) or data.get("issued_by")
			warning = WaterService().issue_flood_warning(
				water_body_id=data["water_body_id"],
				level=data["warning_level"],
				forecast_details={
					"peak_level_m": data.get("forecast_peak_level_m"),
					"peak_at": data.get("forecast_peak_at"),
					"affected_areas": data.get("affected_areas") or [],
					"notes": data.get("notes"),
				},
				session=session,
				issued_by=str(issued_by) if issued_by else None,
			)
			session.commit()
			return jsonify({"ok": True, "id": warning.id, "status": warning.status}), 201
		except WaterServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 400

	@expose("/<string:warning_id>/cancel", methods=["POST"])
	@has_access
	def cancel(self, warning_id: str):
		from pgappforge.plugins.erp.industry.water.services import WaterService, WaterServiceError
		from flask_login import current_user
		session = _get_session()
		data = request.get_json(silent=True) or {}
		cancelled_by = str(getattr(current_user, "id", "")) or data.get("cancelled_by", "")
		try:
			warning = WaterService().cancel_flood_warning(
				warning_id, data.get("reason", ""), cancelled_by, session,
			)
			session.commit()
			return jsonify({"ok": True, "status": warning.status})
		except WaterServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 400

	@expose("/forecast")
	@has_access
	def forecast(self):
		from pgappforge.plugins.erp.industry.water.services import WaterService, WaterServiceError
		session = _get_session()
		water_body_id = request.args.get("water_body_id")
		if not water_body_id:
			return jsonify({"ok": False, "error": "water_body_id required"}), 400
		forecast_hours = int(request.args.get("forecast_hours", 72))
		try:
			result = WaterService().forecast_flood_risk(water_body_id, session, forecast_hours=forecast_hours)
			return jsonify(result)
		except WaterServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 400


# ---------------------------------------------------------------------------
# AllocationView
# ---------------------------------------------------------------------------

class AllocationView(BaseView):
	"""Water Allocation CRUD + usage tracking.

	GET  /water/allocations/                    — list (filter by holder, type, status)
	GET  /water/allocations/<id>                — detail with usage bar (RangeSlider)
	POST /water/allocations/                    — create
	PUT  /water/allocations/<id>                — update
	GET  /water/allocations/<id>/usage          — track usage stats
	POST /water/allocations/<id>/record-abstraction — record water abstraction volume
	"""

	route_base = "/water/allocations"
	default_view = "list"

	_widgets = {
		"usage_pct": progress_widget(max_value=100),        # RangeSliderWidget for % display
		"allocation_type": select2_widget(["AGRICULTURAL", "MUNICIPAL", "INDUSTRIAL", "ENVIRONMENTAL"]),
		"valid_from": date_widget(),
		"valid_to": date_widget(),
	}

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.industry.water.models import WaterAllocation
		session = _get_session()
		q = sa.select(WaterAllocation).order_by(WaterAllocation.permit_number)
		for param, col in (
			("holder_id", WaterAllocation.holder_id),
			("allocation_type", WaterAllocation.allocation_type),
			("status", WaterAllocation.status),
			("water_body_id", WaterAllocation.water_body_id),
		):
			val = request.args.get(param)
			if val:
				q = q.where(col == val)
		allocs = session.execute(q.limit(300)).scalars().all()

		if request.args.get("format") == "json":
			return jsonify({"allocations": [
				{
					"id": a.id, "permit_number": a.permit_number, "holder_id": a.holder_id,
					"allocation_type": a.allocation_type,
					"allocated_m3_per_year": str(a.allocated_m3_per_year),
					"used_m3_this_year": str(a.used_m3_this_year),
					"status": a.status,
				}
				for a in allocs
			]})

		rows = "".join(
			f"<tr>"
			f"<td><code>{_he(a.permit_number)}</code></td>"
			f"<td><span class='label label-default'>{_he(a.allocation_type)}</span></td>"
			f"<td>{_he(a.allocated_m3_per_year)} m³/yr</td>"
			f"<td>{_usage_bar(float(a.used_m3_this_year or 0) / max(float(a.allocated_m3_per_year or 1), 1) * 100)}</td>"
			f"<td>{_status_badge(a.status)}</td>"
			f"<td><a href='/water/allocations/{_he(a.id)}' class='btn btn-xs btn-primary'>View</a></td>"
			f"</tr>"
			for a in allocs
		)
		body = (
			'<h3>Water Allocations</h3>'
			'<table class="table table-bordered table-condensed table-hover">'
			'<thead><tr><th>Permit</th><th>Type</th><th>Allocated</th><th>Usage</th><th>Status</th><th></th></tr></thead>'
			f'<tbody>{rows}</tbody></table>'
			f'<p class="text-muted small">Usage bar: {progress_widget(100)["type"]}</p>'
		)
		return make_response(_page_html("Water Allocations", body), 200)

	@expose("/<string:alloc_id>")
	@has_access
	def detail(self, alloc_id: str):
		from pgappforge.plugins.erp.industry.water.models import WaterAllocation
		session = _get_session()
		alloc = session.get(WaterAllocation, alloc_id)
		if alloc is None:
			abort(404)
		if request.args.get("format") == "json":
			return jsonify({
				"id": alloc.id, "permit_number": alloc.permit_number,
				"holder_id": alloc.holder_id, "water_body_id": alloc.water_body_id,
				"allocation_type": alloc.allocation_type,
				"allocated_m3_per_year": str(alloc.allocated_m3_per_year),
				"used_m3_this_year": str(alloc.used_m3_this_year),
				"valid_from": alloc.valid_from.isoformat() if alloc.valid_from else None,
				"valid_to": alloc.valid_to.isoformat() if alloc.valid_to else None,
				"status": alloc.status,
			})
		usage_pct = float(alloc.used_m3_this_year or 0) / max(float(alloc.allocated_m3_per_year or 1), 1) * 100
		body = (
			f'<h3>Allocation: <code>{_he(alloc.permit_number)}</code></h3>'
			f'<dl class="dl-horizontal">'
			f'<dt>Type</dt><dd>{_he(alloc.allocation_type)}</dd>'
			f'<dt>Allocated</dt><dd>{_he(alloc.allocated_m3_per_year)} m³/yr</dd>'
			f'<dt>Used This Year</dt><dd>{_he(alloc.used_m3_this_year)} m³</dd>'
			f'<dt>Usage</dt><dd>{_usage_bar(usage_pct)}</dd>'
			f'<dt>Valid</dt><dd>{_he(alloc.valid_from)} → {_he(alloc.valid_to or "Open")}</dd>'
			f'<dt>Status</dt><dd>{_status_badge(alloc.status)}</dd>'
			f'</dl>'
			f'<a href="/water/allocations/{_he(alloc_id)}/usage?format=json" class="btn btn-default noprint">Usage Stats</a>'
		)
		return make_response(_page_html(f"Allocation: {alloc.permit_number}", body), 200)

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		from pgappforge.plugins.erp.industry.water.models import WaterAllocation
		from pgappforge.plugins.erp.industry.water.events import WaterAllocationCreatedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event
		session = _get_session()
		data = request.get_json(silent=True) or {}
		required = ("tenant_id", "holder_id", "water_body_id", "allocation_type",
		            "allocated_m3_per_year", "valid_from", "permit_number")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"ok": False, "error": f"missing: {missing}"}), 400
		alloc = WaterAllocation(
			tenant_id=data["tenant_id"],
			holder_id=data["holder_id"],
			water_body_id=data["water_body_id"],
			allocation_type=data["allocation_type"],
			allocated_m3_per_year=data["allocated_m3_per_year"],
			used_m3_this_year=data.get("used_m3_this_year", 0),
			valid_from=date.fromisoformat(data["valid_from"]),
			valid_to=date.fromisoformat(data["valid_to"]) if data.get("valid_to") else None,
			permit_number=data["permit_number"],
			status=data.get("status", "ACTIVE"),
		)
		session.add(alloc)
		session.flush()
		emit_event(
			WaterAllocationCreatedEvent(
				aggregate_id=alloc.id, aggregate_type="WaterAllocation",
				tenant_id=alloc.tenant_id, allocation_id=alloc.id,
				holder_id=str(alloc.holder_id), water_body_id=alloc.water_body_id,
				allocation_type=alloc.allocation_type,
				allocated_m3_per_year=str(alloc.allocated_m3_per_year),
				permit_number=alloc.permit_number,
			),
			session,
		)
		session.commit()
		return jsonify({"ok": True, "id": alloc.id}), 201

	@expose("/<string:alloc_id>", methods=["PUT"])
	@has_access
	def update(self, alloc_id: str):
		from pgappforge.plugins.erp.industry.water.models import WaterAllocation
		session = _get_session()
		alloc = session.get(WaterAllocation, alloc_id)
		if alloc is None:
			abort(404)
		data = request.get_json(silent=True) or {}
		for fld in ("allocation_type", "allocated_m3_per_year", "valid_from", "valid_to", "status"):
			if fld in data:
				setattr(alloc, fld, data[fld])
		alloc.updated_at = datetime.now(timezone.utc)
		session.commit()
		return jsonify({"ok": True})

	@expose("/<string:alloc_id>/usage")
	@has_access
	def usage(self, alloc_id: str):
		from pgappforge.plugins.erp.industry.water.services import WaterService, WaterServiceError
		session = _get_session()
		try:
			result = WaterService().track_allocation_usage(alloc_id, session)
			session.commit()  # AllocationExceededEvent may have been added to session
			return jsonify(result)
		except WaterServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 400

	@expose("/<string:alloc_id>/record-abstraction", methods=["POST"])
	@has_access
	def record_abstraction(self, alloc_id: str):
		from pgappforge.plugins.erp.industry.water.services import WaterService, WaterServiceError
		from decimal import Decimal
		session = _get_session()
		data = request.get_json(silent=True) or {}
		volume_str = data.get("volume_m3")
		if not volume_str:
			return jsonify({"ok": False, "error": "volume_m3 required"}), 400
		try:
			alloc = WaterService().record_abstraction(alloc_id, Decimal(str(volume_str)), session)
			session.commit()
			return jsonify({
				"ok": True,
				"used_m3_this_year": str(alloc.used_m3_this_year),
				"allocated_m3_per_year": str(alloc.allocated_m3_per_year),
			})
		except WaterServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 400


# ---------------------------------------------------------------------------
# WaterDashboardView
# ---------------------------------------------------------------------------

class WaterDashboardView(BaseView):
	"""Water management overview dashboard.

	GET /water/dashboard/             — water body selector
	GET /water/dashboard/<body_id>    — dashboard for a water body
	GET /water/dashboard/<body_id>/contamination — contamination scan
	"""

	route_base = "/water/dashboard"
	default_view = "index"

	_widgets = {
		"body_map": map_widget(zoom=9),
		"quality_trend": chart_widget("line"),
		"flow_chart": chart_widget("area"),
	}

	@expose("/")
	@has_access
	def index(self):
		from pgappforge.plugins.erp.industry.water.models import WaterBody
		session = _get_session()
		bodies = session.execute(sa.select(WaterBody).order_by(WaterBody.name).limit(200)).scalars().all()
		links = "".join(
			f'<li><a href="/water/dashboard/{_he(b.id)}">{_he(b.name)}</a> '
			f'{_status_badge(b.status)} '
			f'<small>({_he(b.body_type)})</small></li>'
			for b in bodies
		)
		body = f'<h3>Water Management Dashboard</h3><ul class="list-unstyled">{links}</ul>'
		return make_response(_page_html("Water Dashboard", body), 200)

	@expose("/<string:body_id>")
	@has_access
	def body_dashboard(self, body_id: str):
		from pgappforge.plugins.erp.industry.water.models import WaterBody, MonitoringStation, FloodWarning
		from pgappforge.plugins.erp.industry.water.services import WaterService, WaterServiceError
		session = _get_session()
		wb = session.get(WaterBody, body_id)
		if wb is None:
			abort(404)

		# Flood risk forecast
		try:
			flood_risk = WaterService().forecast_flood_risk(body_id, session, forecast_hours=48)
		except WaterServiceError:
			flood_risk = {"risk_level": "UNKNOWN", "trend": "UNKNOWN", "recommendation": "Insufficient data"}

		active_warnings = session.execute(
			sa.select(FloodWarning).where(
				FloodWarning.water_body_id == body_id,
				FloodWarning.status == "ACTIVE",
			).order_by(sa.desc(FloodWarning.issued_at))
		).scalars().all()

		stations = session.execute(
			sa.select(MonitoringStation).where(
				MonitoringStation.water_body_id == body_id,
				MonitoringStation.is_active == True,
			)
		).scalars().all()

		if request.args.get("format") == "json":
			return jsonify({
				"water_body": {"id": wb.id, "name": wb.name, "type": wb.body_type, "status": wb.status},
				"active_stations": len(stations),
				"active_warnings": len(active_warnings),
				"flood_risk": flood_risk,
			})

		map_cfg = map_widget(zoom=9)
		chart_cfg = chart_widget("line")

		risk_color = {
			"LOW": "success", "MEDIUM": "warning", "HIGH": "danger", "CRITICAL": "danger"
		}.get(flood_risk.get("risk_level", "LOW"), "default")

		warning_rows = "".join(
			f'<div class="alert alert-{"danger" if w.warning_level in ("WARNING","EMERGENCY") else "warning"}">'
			f'{_warning_badge(w.warning_level)} — {_he(wb.name)} — issued {_he(w.issued_at.strftime("%Y-%m-%d %H:%M") if w.issued_at else "—")}'
			f'</div>'
			for w in active_warnings
		) or '<div class="alert alert-success">No active flood warnings</div>'

		body_html = (
			f'<h3>{_he(wb.name)} {_status_badge(wb.status)}</h3>'
			f'<div class="map-placeholder" data-widget="{_he(str(map_cfg))}">'
			f'Water Body Map — station locations overlay | Widget: {map_cfg["type"]}</div>'
			f'<div class="chart-placeholder" data-widget="{_he(str(chart_cfg))}" style="margin-top:8px">'
			f'Flow/Quality Trends — Widget: {chart_cfg["type"]}</div>'
			f'<div class="row" style="margin-top:16px">'
			f'<div class="col-sm-3"><div class="panel panel-default"><div class="panel-body">'
			f'<strong>{_he(len(stations))}</strong><br><small>Active Stations</small></div></div></div>'
			f'<div class="col-sm-3"><div class="panel panel-{"danger" if active_warnings else "success"}"><div class="panel-body">'
			f'<strong>{_he(len(active_warnings))}</strong><br><small>Active Warnings</small></div></div></div>'
			f'<div class="col-sm-3"><div class="panel panel-{risk_color}"><div class="panel-body">'
			f'<strong>{_he(flood_risk.get("risk_level", "?"))}</strong><br><small>Flood Risk (48h)</small></div></div></div>'
			f'<div class="col-sm-3"><div class="panel panel-info"><div class="panel-body">'
			f'<strong>{_he(flood_risk.get("trend", "?"))}</strong><br><small>Flow Trend</small></div></div></div>'
			f'</div>'
			f'<p class="text-muted"><em>{_he(flood_risk.get("recommendation", ""))}</em></p>'
			f'<h4>Active Warnings</h4>{warning_rows}'
		)
		return make_response(_page_html(f"Dashboard: {wb.name}", body_html), 200)

	@expose("/<string:body_id>/contamination")
	@has_access
	def contamination(self, body_id: str):
		from pgappforge.plugins.erp.industry.water.services import WaterService, WaterServiceError
		session = _get_session()
		threshold_violations = int(request.args.get("threshold_violations", 2))
		try:
			events = WaterService().detect_contamination_events(body_id, session, threshold_violations=threshold_violations)
			session.commit()
			return jsonify({
				"water_body_id": body_id,
				"threshold_violations": threshold_violations,
				"events_detected": len(events),
				"events": events,
			})
		except WaterServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 400


__all__ = [
	"WaterBodyView",
	"MonitoringView",
	"FloodWarningView",
	"AllocationView",
	"WaterDashboardView",
]
