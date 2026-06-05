"""
pgappforge/plugins/erp/industry/agritech/views.py

Flask views for the AgriTech plugin.

Registered views:
  FarmView             — CRUD for farms
  FieldView            — CRUD + MapWidget for field boundary polygons, CurrencyWidget for costs
  ObservationView      — CRUD + MapWidget for geo_point, file_widget for photos, Select2 for type
  WeatherDashboardView — AdvancedChartsWidget for climate trends, station listing
  FarmDashboardView    — MapWidget showing all fields with status overlay
  PlantingView         — CRUD + lifecycle advancement
  InputApplicationView — CRUD
  HarvestView          — CRUD
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import sqlalchemy as sa
from flask import abort, jsonify, make_response, request

from pgappforge import BaseView, expose
from pgappforge.security.decorators import has_access
from pgappforge.plugins.erp.foundation.commons import format_currency, status_badge
from pgappforge.plugins.erp.foundation.view_helpers import (
	currency_widget,
	map_widget,
	chart_widget,
	file_widget,
	select2_widget,
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
		'<style>body{padding:24px} .map-placeholder{background:#e8f5e9;border:1px solid #a5d6a7;'
		'border-radius:4px;padding:12px;color:#388e3c;font-size:.85em} '
		'.chart-placeholder{background:#e3f2fd;border:1px solid #90caf9;'
		'border-radius:4px;padding:12px;color:#1565c0;font-size:.85em}'
		'@media print{.noprint{display:none}}</style>'
		f'</head><body>{body}</body></html>'
	)


def _map_placeholder(label: str, geometry_wkt: str | None) -> str:
	"""Render a map placeholder div with widget config metadata."""
	cfg = map_widget(zoom=14)
	wkt_display = _he(geometry_wkt[:80] + "…" if geometry_wkt and len(geometry_wkt) > 80 else (geometry_wkt or "No geometry"))
	return (
		f'<div class="map-placeholder" data-widget="{_he(str(cfg))}">'
		f'<strong>{_he(label)}</strong><br>'
		f'<small>Widget: {cfg["type"]} | Geometry: {wkt_display}</small>'
		f'</div>'
	)


def _severity_label(severity: str | None) -> str:
	colors = {"LOW": "default", "MEDIUM": "warning", "HIGH": "danger", "CRITICAL": "danger"}
	color = colors.get((severity or "").upper(), "default")
	return f'<span class="label label-{color}">{_he(severity or "—")}</span>'


# ---------------------------------------------------------------------------
# FarmView
# ---------------------------------------------------------------------------

class FarmView(BaseView):
	"""Farm CRUD.

	GET  /agri/farms/        — list all farms
	GET  /agri/farms/<id>    — detail
	POST /agri/farms/        — create
	PUT  /agri/farms/<id>    — update
	"""

	route_base = "/agri/farms"
	default_view = "list"

	# Widget config metadata (consumed by form renderer)
	_widgets = {
		"location": map_widget(zoom=10),
		"address": json_widget(mode="form"),
		"certification": json_widget(mode="tree"),
	}

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.industry.agritech.models import Farm
		session = _get_session()
		q = sa.select(Farm).order_by(Farm.farm_name)
		if request.args.get("tenant_id"):
			q = q.where(Farm.tenant_id == request.args["tenant_id"])
		if request.args.get("farm_type"):
			q = q.where(Farm.farm_type == request.args["farm_type"])
		farms = session.execute(q.limit(500)).scalars().all()

		if request.args.get("format") == "json":
			return jsonify({"farms": [
				{
					"id": f.id, "farm_name": f.farm_name, "farm_type": f.farm_type,
					"total_area_ha": str(f.total_area_ha or ""),
					"soil_type": f.soil_type, "elevation_m": f.elevation_m,
				}
				for f in farms
			]})

		rows = "".join(
			f"<tr>"
			f"<td>{_he(f.farm_name)}</td>"
			f"<td><span class='label label-info'>{_he(f.farm_type)}</span></td>"
			f"<td>{_he(f.total_area_ha or '—')} ha</td>"
			f"<td>{_he(f.soil_type or '—')}</td>"
			f"<td>{_he(f.elevation_m or '—')} m</td>"
			f"<td><a href='/agri/farms/{_he(f.id)}' class='btn btn-xs btn-primary'>View</a></td>"
			f"</tr>"
			for f in farms
		)
		body = (
			'<h3>Farms</h3>'
			'<table class="table table-bordered table-condensed table-hover">'
			'<thead><tr><th>Name</th><th>Type</th><th>Area</th><th>Soil</th><th>Elevation</th><th></th></tr></thead>'
			f'<tbody>{rows}</tbody></table>'
		)
		return make_response(_page_html("Farms", body), 200)

	@expose("/<string:farm_id>")
	@has_access
	def detail(self, farm_id: str):
		from pgappforge.plugins.erp.industry.agritech.models import Farm
		session = _get_session()
		farm = session.get(Farm, farm_id)
		if farm is None:
			abort(404)
		fields_count = session.execute(
			sa.select(sa.func.count()).select_from(
				sa.select(sa.text("1")).where(
					sa.text(f"agri_field.farm_id = '{farm_id}'")
				).subquery()
			)
		).scalar() or len(farm.fields)
		body = (
			f'<h3>{_he(farm.farm_name)}</h3>'
			f'{_map_placeholder("Farm Location", farm.location)}'
			f'<dl class="dl-horizontal">'
			f'<dt>Type</dt><dd>{_he(farm.farm_type)}</dd>'
			f'<dt>Total Area</dt><dd>{_he(farm.total_area_ha or "—")} ha</dd>'
			f'<dt>Soil Type</dt><dd>{_he(farm.soil_type or "—")}</dd>'
			f'<dt>Elevation</dt><dd>{_he(farm.elevation_m or "—")} m</dd>'
			f'<dt>Fields</dt><dd>{_he(len(farm.fields))}</dd>'
			f'<dt>Created</dt><dd>{_he(farm.created_at)}</dd>'
			f'</dl>'
		)
		if request.args.get("format") == "json":
			return jsonify({
				"id": farm.id, "farm_name": farm.farm_name, "farm_type": farm.farm_type,
				"total_area_ha": str(farm.total_area_ha or ""), "location": farm.location,
				"address": farm.address, "certification": farm.certification,
				"soil_type": farm.soil_type, "elevation_m": farm.elevation_m,
				"party_id": farm.party_id,
			})
		return make_response(_page_html(farm.farm_name, body), 200)

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		from pgappforge.plugins.erp.industry.agritech.models import Farm
		from pgappforge.plugins.erp.industry.agritech.events import FarmCreatedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event
		session = _get_session()
		data = request.get_json(silent=True) or {}
		required = ("tenant_id", "farm_name")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"ok": False, "error": f"missing: {missing}"}), 400
		farm = Farm(
			tenant_id=data["tenant_id"],
			party_id=data.get("party_id"),
			farm_name=data["farm_name"],
			total_area_ha=data.get("total_area_ha"),
			location=data.get("location"),
			address=data.get("address") or {},
			farm_type=data.get("farm_type", "MIXED"),
			certification=data.get("certification") or {},
			soil_type=data.get("soil_type"),
			elevation_m=data.get("elevation_m"),
		)
		session.add(farm)
		session.flush()
		emit_event(
			FarmCreatedEvent(
				aggregate_id=farm.id, aggregate_type="Farm",
				tenant_id=farm.tenant_id, farm_id=farm.id,
				farm_name=farm.farm_name, farm_type=farm.farm_type,
				party_id=farm.party_id or "",
				total_area_ha=str(farm.total_area_ha or ""),
			),
			session,
		)
		session.commit()
		return jsonify({"ok": True, "id": farm.id}), 201

	@expose("/<string:farm_id>", methods=["PUT"])
	@has_access
	def update(self, farm_id: str):
		from pgappforge.plugins.erp.industry.agritech.models import Farm
		session = _get_session()
		farm = session.get(Farm, farm_id)
		if farm is None:
			abort(404)
		data = request.get_json(silent=True) or {}
		for fld in ("farm_name", "total_area_ha", "location", "address",
		             "farm_type", "certification", "soil_type", "elevation_m"):
			if fld in data:
				setattr(farm, fld, data[fld])
		farm.updated_at = datetime.now(timezone.utc)
		session.commit()
		return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# FieldView
# ---------------------------------------------------------------------------

class FieldView(BaseView):
	"""Field CRUD with map boundary display and cost currency widget.

	GET  /agri/fields/                      — list (filter by farm_id, irrigation_type)
	GET  /agri/fields/<id>                  — detail with boundary map placeholder
	POST /agri/fields/                      — create
	PUT  /agri/fields/<id>                  — update
	GET  /agri/fields/<id>/profitability    — profitability by season_year
	GET  /agri/fields/<id>/irrigation-plan  — irrigation schedule
	"""

	route_base = "/agri/fields"
	default_view = "list"

	_widgets = {
		"boundary": map_widget(zoom=15),            # GeoPointWidget for polygon boundary
		"seed_cost_cents": currency_widget("USD"),
	}

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.industry.agritech.models import Field
		session = _get_session()
		q = sa.select(Field).order_by(Field.field_name)
		for param, col in (
			("farm_id", Field.farm_id),
			("irrigation_type", Field.irrigation_type),
			("tenant_id", Field.tenant_id),
		):
			val = request.args.get(param)
			if val:
				q = q.where(col == val)
		fields = session.execute(q.limit(500)).scalars().all()

		if request.args.get("format") == "json":
			return jsonify({"fields": [
				{
					"id": f.id, "field_name": f.field_name, "farm_id": f.farm_id,
					"area_ha": str(f.area_ha or ""), "soil_type": f.soil_type,
					"irrigation_type": f.irrigation_type,
					"current_crop_id": f.current_crop_id,
				}
				for f in fields
			]})

		rows = "".join(
			f"<tr>"
			f"<td>{_he(f.field_name)}</td>"
			f"<td>{_he(f.area_ha or '—')} ha</td>"
			f"<td>{_he(f.soil_type or '—')}</td>"
			f"<td><span class='label label-default'>{_he(f.irrigation_type)}</span></td>"
			f"<td>{_he(f.current_crop.crop_name if f.current_crop else '—')}</td>"
			f"<td><a href='/agri/fields/{_he(f.id)}' class='btn btn-xs btn-primary'>View</a></td>"
			f"</tr>"
			for f in fields
		)
		body = (
			'<h3>Fields</h3>'
			'<table class="table table-bordered table-condensed table-hover">'
			'<thead><tr><th>Name</th><th>Area</th><th>Soil</th><th>Irrigation</th><th>Current Crop</th><th></th></tr></thead>'
			f'<tbody>{rows}</tbody></table>'
		)
		return make_response(_page_html("Fields", body), 200)

	@expose("/<string:field_id>")
	@has_access
	def detail(self, field_id: str):
		from pgappforge.plugins.erp.industry.agritech.models import Field
		session = _get_session()
		field = session.get(Field, field_id)
		if field is None:
			abort(404)
		if request.args.get("format") == "json":
			return jsonify({
				"id": field.id, "field_name": field.field_name, "farm_id": field.farm_id,
				"area_ha": str(field.area_ha or ""), "boundary": field.boundary,
				"soil_type": field.soil_type, "current_crop_id": field.current_crop_id,
				"irrigation_type": field.irrigation_type,
			})
		body = (
			f'<h3>Field: {_he(field.field_name)}</h3>'
			f'{_map_placeholder("Field Boundary", field.boundary)}'
			f'<dl class="dl-horizontal">'
			f'<dt>Area</dt><dd>{_he(field.area_ha or "—")} ha</dd>'
			f'<dt>Soil</dt><dd>{_he(field.soil_type or "—")}</dd>'
			f'<dt>Irrigation</dt><dd>{_he(field.irrigation_type)}</dd>'
			f'<dt>Current Crop</dt><dd>{_he(field.current_crop.crop_name if field.current_crop else "—")}</dd>'
			f'</dl>'
			f'<a href="/agri/fields/{_he(field_id)}/profitability?season_year=2025&format=json" class="btn btn-default noprint">Profitability</a> '
			f'<a href="/agri/fields/{_he(field_id)}/irrigation-plan?format=json" class="btn btn-default noprint">Irrigation Plan</a>'
		)
		return make_response(_page_html(f"Field: {field.field_name}", body), 200)

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		from pgappforge.plugins.erp.industry.agritech.models import Field
		session = _get_session()
		data = request.get_json(silent=True) or {}
		required = ("tenant_id", "farm_id", "field_name")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"ok": False, "error": f"missing: {missing}"}), 400
		field = Field(
			tenant_id=data["tenant_id"],
			farm_id=data["farm_id"],
			field_name=data["field_name"],
			area_ha=data.get("area_ha"),
			boundary=data.get("boundary"),
			soil_type=data.get("soil_type"),
			current_crop_id=data.get("current_crop_id"),
			irrigation_type=data.get("irrigation_type", "RAIN_FED"),
		)
		session.add(field)
		session.commit()
		return jsonify({"ok": True, "id": field.id}), 201

	@expose("/<string:field_id>", methods=["PUT"])
	@has_access
	def update(self, field_id: str):
		from pgappforge.plugins.erp.industry.agritech.models import Field
		session = _get_session()
		field = session.get(Field, field_id)
		if field is None:
			abort(404)
		data = request.get_json(silent=True) or {}
		for fld in ("field_name", "area_ha", "boundary", "soil_type", "current_crop_id", "irrigation_type"):
			if fld in data:
				setattr(field, fld, data[fld])
		field.updated_at = datetime.now(timezone.utc)
		session.commit()
		return jsonify({"ok": True})

	@expose("/<string:field_id>/profitability")
	@has_access
	def profitability(self, field_id: str):
		from pgappforge.plugins.erp.industry.agritech.services import AgriTechService, AgriServiceError
		session = _get_session()
		season_year = int(request.args.get("season_year", datetime.now().year))
		try:
			result = AgriTechService().calculate_field_profitability(field_id, season_year, session)
			if request.args.get("format") == "json":
				return jsonify(result)
			# HTML view with currency widgets
			margin_display = format_currency(result["gross_margin_cents"], "USD")
			body = (
				f'<h3>Field Profitability — {season_year}</h3>'
				f'<div class="row">'
				f'<div class="col-sm-4"><div class="panel panel-success"><div class="panel-heading">Revenue</div>'
				f'<div class="panel-body"><h4>{_he(format_currency(result["total_revenue_cents"], "USD"))}</h4></div></div></div>'
				f'<div class="col-sm-4"><div class="panel panel-warning"><div class="panel-heading">Total Cost</div>'
				f'<div class="panel-body"><h4>{_he(format_currency(result["total_cost_cents"], "USD"))}</h4></div></div></div>'
				f'<div class="col-sm-4"><div class="panel panel-info"><div class="panel-heading">Gross Margin</div>'
				f'<div class="panel-body"><h4>{_he(margin_display)}</h4></div></div></div>'
				f'</div>'
				f'<p>Area: {_he(result["area_ha"])} ha | Margin/ha: {_he(format_currency(result["margin_per_ha_cents"], "USD"))} | '
				f'Harvested: {_he(result["harvested_kg"])} kg</p>'
				f'<p data-widget="{_he(str(currency_widget("USD")))}" class="text-muted small">Currency widget: {currency_widget("USD")["type"]}</p>'
			)
			return make_response(_page_html(f"Field Profitability {season_year}", body), 200)
		except AgriServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 400

	@expose("/<string:field_id>/irrigation-plan")
	@has_access
	def irrigation_plan(self, field_id: str):
		from pgappforge.plugins.erp.industry.agritech.services import AgriTechService, AgriServiceError
		session = _get_session()
		forecast_days = int(request.args.get("forecast_days", 7))
		try:
			schedule = AgriTechService().plan_irrigation(field_id, session, forecast_days=forecast_days)
			return jsonify({"field_id": field_id, "forecast_days": forecast_days, "schedule": schedule})
		except AgriServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 400


# ---------------------------------------------------------------------------
# ObservationView
# ---------------------------------------------------------------------------

class ObservationView(BaseView):
	"""Field Observation CRUD.

	GET  /agri/observations/         — list (filter by field_id, type, severity)
	GET  /agri/observations/<id>     — detail with map point + photo gallery placeholder
	POST /agri/observations/         — create (may trigger CriticalObservationEvent)
	GET  /agri/observations/pest-risk — pest risk assessment for a field
	"""

	route_base = "/agri/observations"
	default_view = "list"

	# Widget metadata consumed by form renderer
	_widgets = {
		"geo_point": map_widget(zoom=16),
		"photos": file_widget(multiple=True, types=["jpg", "jpeg", "png", "heic"]),
		"observation_type": select2_widget(["PEST", "DISEASE", "GROWTH_STAGE", "SOIL_MOISTURE", "IRRIGATION_NEED"]),
		"severity": select2_widget(["LOW", "MEDIUM", "HIGH", "CRITICAL"]),
		"sensor_data": json_widget(mode="tree"),
	}

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.industry.agritech.models import FieldObservation
		session = _get_session()
		q = sa.select(FieldObservation).order_by(sa.desc(FieldObservation.observed_at))
		for param, col in (
			("field_id", FieldObservation.field_id),
			("observation_type", FieldObservation.observation_type),
			("severity", FieldObservation.severity),
		):
			val = request.args.get(param)
			if val:
				q = q.where(col == val)
		obs = session.execute(q.limit(200)).scalars().all()

		if request.args.get("format") == "json":
			return jsonify({"observations": [
				{
					"id": o.id, "field_id": o.field_id,
					"observed_at": o.observed_at.isoformat() if o.observed_at else None,
					"observation_type": o.observation_type, "severity": o.severity,
					"notes": o.notes,
				}
				for o in obs
			]})

		rows = "".join(
			f"<tr>"
			f"<td>{_he(o.observed_at.strftime('%Y-%m-%d %H:%M') if o.observed_at else '—')}</td>"
			f"<td>{_he(o.field_id)}</td>"
			f"<td>{_he(o.observation_type)}</td>"
			f"<td>{_severity_label(o.severity)}</td>"
			f"<td>{_he((o.notes or '')[:60])}{'…' if o.notes and len(o.notes) > 60 else ''}</td>"
			f"<td><a href='/agri/observations/{_he(o.id)}' class='btn btn-xs btn-primary'>View</a></td>"
			f"</tr>"
			for o in obs
		)
		body = (
			'<h3>Field Observations</h3>'
			'<table class="table table-bordered table-condensed table-hover">'
			'<thead><tr><th>Observed At</th><th>Field</th><th>Type</th><th>Severity</th><th>Notes</th><th></th></tr></thead>'
			f'<tbody>{rows}</tbody></table>'
		)
		return make_response(_page_html("Field Observations", body), 200)

	@expose("/<string:obs_id>")
	@has_access
	def detail(self, obs_id: str):
		from pgappforge.plugins.erp.industry.agritech.models import FieldObservation
		session = _get_session()
		obs = session.get(FieldObservation, obs_id)
		if obs is None:
			abort(404)
		if request.args.get("format") == "json":
			return jsonify({
				"id": obs.id, "field_id": obs.field_id,
				"observed_at": obs.observed_at.isoformat() if obs.observed_at else None,
				"observer_id": obs.observer_id,
				"observation_type": obs.observation_type, "severity": obs.severity,
				"notes": obs.notes, "photos": obs.photos,
				"geo_point": obs.geo_point, "sensor_data": obs.sensor_data,
			})
		photo_count = len(obs.photos) if isinstance(obs.photos, list) else 0
		body = (
			f'<h3>Observation: {_he(obs.observation_type)} {_severity_label(obs.severity)}</h3>'
			f'{_map_placeholder("Observation Location", obs.geo_point)}'
			f'<dl class="dl-horizontal">'
			f'<dt>Field</dt><dd>{_he(obs.field_id)}</dd>'
			f'<dt>Observed At</dt><dd>{_he(obs.observed_at)}</dd>'
			f'<dt>Type</dt><dd>{_he(obs.observation_type)}</dd>'
			f'<dt>Severity</dt><dd>{_severity_label(obs.severity)}</dd>'
			f'<dt>Notes</dt><dd>{_he(obs.notes or "—")}</dd>'
			f'<dt>Photos</dt><dd>{_he(photo_count)} photo(s) '
			f'<span class="text-muted small" data-widget="{_he(str(file_widget(multiple=True)))}">'
			f'[{file_widget(multiple=True)["type"]}]</span></dd>'
			f'</dl>'
		)
		return make_response(_page_html("Observation Detail", body), 200)

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		from pgappforge.plugins.erp.industry.agritech.models import FieldObservation, Field
		from pgappforge.plugins.erp.industry.agritech.events import FieldObservationCreatedEvent, CriticalObservationEvent
		from pgappforge.plugins.erp.foundation.events import emit_event
		session = _get_session()
		data = request.get_json(silent=True) or {}
		required = ("tenant_id", "field_id", "observation_type")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"ok": False, "error": f"missing: {missing}"}), 400

		obs = FieldObservation(
			tenant_id=data["tenant_id"],
			field_id=data["field_id"],
			observed_at=datetime.fromisoformat(data["observed_at"]) if data.get("observed_at") else datetime.now(timezone.utc),
			observer_id=data.get("observer_id"),
			observation_type=data["observation_type"],
			severity=data.get("severity"),
			notes=data.get("notes"),
			photos=data.get("photos") or [],
			geo_point=data.get("geo_point"),
			sensor_data=data.get("sensor_data") or {},
		)
		session.add(obs)
		session.flush()

		emit_event(
			FieldObservationCreatedEvent(
				aggregate_id=obs.id, aggregate_type="FieldObservation",
				tenant_id=obs.tenant_id, observation_id=obs.id,
				field_id=obs.field_id, observation_type=obs.observation_type,
				severity=obs.severity or "",
			),
			session,
		)

		if obs.severity == "CRITICAL":
			field = session.get(Field, obs.field_id)
			emit_event(
				CriticalObservationEvent(
					aggregate_id=obs.id, aggregate_type="FieldObservation",
					tenant_id=obs.tenant_id, observation_id=obs.id,
					field_id=obs.field_id, farm_id=field.farm_id if field else "",
					observation_type=obs.observation_type, notes=obs.notes or "",
				),
				session,
			)

		session.commit()
		return jsonify({"ok": True, "id": obs.id}), 201

	@expose("/pest-risk")
	@has_access
	def pest_risk(self):
		from pgappforge.plugins.erp.industry.agritech.services import AgriTechService, AgriServiceError
		session = _get_session()
		field_id = request.args.get("field_id")
		if not field_id:
			return jsonify({"ok": False, "error": "field_id required"}), 400
		weather = {
			"temperature_c": request.args.get("temperature_c", 22),
			"humidity_pct": request.args.get("humidity_pct", 65),
			"rainfall_mm": request.args.get("rainfall_mm", 10),
		}
		try:
			result = AgriTechService().detect_pest_risk(field_id, weather, session)
			return jsonify(result)
		except AgriServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 400


# ---------------------------------------------------------------------------
# WeatherDashboardView
# ---------------------------------------------------------------------------

class WeatherDashboardView(BaseView):
	"""Weather data and climate trends dashboard.

	GET /agri/weather/                 — recent weather records
	GET /agri/weather/trends           — chart data for temperature, rainfall, humidity
	GET /agri/weather/stations         — list active stations
	POST /agri/weather/               — ingest a weather record
	"""

	route_base = "/agri/weather"
	default_view = "dashboard"

	_widgets = {
		"temperature_trend": chart_widget("line"),
		"rainfall_bar": chart_widget("bar"),
		"humidity_gauge": chart_widget("doughnut"),
	}

	@expose("/")
	@has_access
	def dashboard(self):
		from pgappforge.plugins.erp.industry.agritech.models import WeatherRecord
		session = _get_session()
		station_id = request.args.get("station_id")
		q = sa.select(WeatherRecord).order_by(sa.desc(WeatherRecord.recorded_at))
		if station_id:
			q = q.where(WeatherRecord.station_id == station_id)
		records = session.execute(q.limit(100)).scalars().all()

		if request.args.get("format") == "json":
			return jsonify({"weather_records": [
				{
					"id": r.id, "station_id": r.station_id,
					"recorded_at": r.recorded_at.isoformat() if r.recorded_at else None,
					"temperature_c": str(r.temperature_c or ""),
					"humidity_pct": str(r.humidity_pct or ""),
					"rainfall_mm": str(r.rainfall_mm or ""),
					"wind_speed_kmh": str(r.wind_speed_kmh or ""),
					"solar_radiation_wm2": str(r.solar_radiation_wm2 or ""),
				}
				for r in records
			]})

		# Chart placeholders
		chart_temp_cfg = chart_widget("line")
		chart_rain_cfg = chart_widget("bar")
		rows = "".join(
			f"<tr>"
			f"<td>{_he(r.station_id)}</td>"
			f"<td>{_he(r.recorded_at.strftime('%Y-%m-%d %H:%M') if r.recorded_at else '—')}</td>"
			f"<td>{_he(r.temperature_c or '—')} °C</td>"
			f"<td>{_he(r.humidity_pct or '—')} %</td>"
			f"<td>{_he(r.rainfall_mm or '—')} mm</td>"
			f"<td>{_he(r.wind_speed_kmh or '—')} km/h</td>"
			f"</tr>"
			for r in records
		)
		body = (
			f'<h3>Weather Dashboard</h3>'
			f'<div class="chart-placeholder" data-widget="{_he(str(chart_temp_cfg))}">'
			f'Temperature Trend — Widget: {chart_temp_cfg["type"]} (chart_type={chart_temp_cfg["config"]["chart_type"]})</div>'
			f'<div class="chart-placeholder" data-widget="{_he(str(chart_rain_cfg))}" style="margin-top:8px">'
			f'Rainfall Bar Chart — Widget: {chart_rain_cfg["type"]} (chart_type={chart_rain_cfg["config"]["chart_type"]})</div>'
			f'<h4 style="margin-top:16px">Recent Records</h4>'
			f'<table class="table table-condensed table-bordered">'
			f'<thead><tr><th>Station</th><th>Time</th><th>Temp</th><th>Humidity</th><th>Rainfall</th><th>Wind</th></tr></thead>'
			f'<tbody>{rows}</tbody></table>'
		)
		return make_response(_page_html("Weather Dashboard", body), 200)

	@expose("/trends")
	@has_access
	def trends(self):
		"""Return chart-ready time-series data for a station."""
		from pgappforge.plugins.erp.industry.agritech.models import WeatherRecord
		session = _get_session()
		station_id = request.args.get("station_id")
		days = int(request.args.get("days", 30))
		q = (
			sa.select(WeatherRecord)
			.where(WeatherRecord.recorded_at >= sa.func.now() - sa.text(f"INTERVAL '{days} days'"))
			.order_by(WeatherRecord.recorded_at)
		)
		if station_id:
			q = q.where(WeatherRecord.station_id == station_id)
		records = session.execute(q.limit(1000)).scalars().all()
		return jsonify({
			"station_id": station_id,
			"days": days,
			"widget": chart_widget("line"),
			"labels": [r.recorded_at.isoformat() if r.recorded_at else None for r in records],
			"datasets": {
				"temperature_c": [str(r.temperature_c or "") for r in records],
				"humidity_pct": [str(r.humidity_pct or "") for r in records],
				"rainfall_mm": [str(r.rainfall_mm or "") for r in records],
				"solar_radiation_wm2": [str(r.solar_radiation_wm2 or "") for r in records],
			},
		})

	@expose("/", methods=["POST"])
	@has_access
	def ingest(self):
		from pgappforge.plugins.erp.industry.agritech.models import WeatherRecord
		session = _get_session()
		data = request.get_json(silent=True) or {}
		required = ("tenant_id", "station_id", "recorded_at")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"ok": False, "error": f"missing: {missing}"}), 400
		wr = WeatherRecord(
			tenant_id=data["tenant_id"],
			station_id=data["station_id"],
			recorded_at=datetime.fromisoformat(data["recorded_at"]),
			temperature_c=data.get("temperature_c"),
			humidity_pct=data.get("humidity_pct"),
			rainfall_mm=data.get("rainfall_mm"),
			wind_speed_kmh=data.get("wind_speed_kmh"),
			solar_radiation_wm2=data.get("solar_radiation_wm2"),
			location=data.get("location"),
		)
		session.add(wr)
		session.commit()
		return jsonify({"ok": True, "id": wr.id}), 201


# ---------------------------------------------------------------------------
# FarmDashboardView
# ---------------------------------------------------------------------------

class FarmDashboardView(BaseView):
	"""Farm overview dashboard with map showing all fields with status overlays.

	GET /agri/dashboard/              — farm selector
	GET /agri/dashboard/<farm_id>     — dashboard for a specific farm
	GET /agri/dashboard/<farm_id>/carbon — carbon sequestration estimate
	"""

	route_base = "/agri/dashboard"
	default_view = "index"

	_widgets = {
		"farm_map": map_widget(zoom=12),        # Shows all fields with colour-coded status overlays
		"yield_chart": chart_widget("bar"),
		"cost_chart": chart_widget("pie"),
	}

	@expose("/")
	@has_access
	def index(self):
		from pgappforge.plugins.erp.industry.agritech.models import Farm
		session = _get_session()
		farms = session.execute(sa.select(Farm).order_by(Farm.farm_name).limit(200)).scalars().all()
		links = "".join(
			f'<li><a href="/agri/dashboard/{_he(f.id)}">{_he(f.farm_name)}</a> '
			f'<small>({_he(f.farm_type)} · {_he(f.total_area_ha or "?")} ha)</small></li>'
			for f in farms
		)
		body = f'<h3>Farm Dashboard</h3><ul class="list-unstyled">{links}</ul>'
		return make_response(_page_html("Farm Dashboard", body), 200)

	@expose("/<string:farm_id>")
	@has_access
	def farm_dashboard(self, farm_id: str):
		from pgappforge.plugins.erp.industry.agritech.services import AgriTechService, AgriServiceError
		session = _get_session()
		try:
			data = AgriTechService().get_farm_dashboard(farm_id, session)
		except AgriServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 404

		if request.args.get("format") == "json":
			return jsonify(data)

		map_cfg = map_widget(zoom=12)
		alerts_html = "".join(
			f'<div class="alert alert-warning">{_he(a)}</div>'
			for a in data["alerts"]
		) or '<div class="alert alert-success">No active alerts</div>'

		crop_rows = "".join(
			f"<tr>"
			f"<td>{_he(c['field_name'])}</td>"
			f"<td>{_he(c['crop_name'])}</td>"
			f"<td><span class='label label-info'>{_he(c['status'])}</span></td>"
			f"<td>{_he(c.get('planted_date', '—'))}</td>"
			f"<td>{_he(c.get('expected_harvest', '—'))}</td>"
			f"</tr>"
			for c in data["active_crops"]
		) or "<tr><td colspan='5' class='text-muted'>No active crops</td></tr>"

		body = (
			f'<h3>Farm Dashboard: {_he(data["farm"]["name"])}</h3>'
			f'<div class="map-placeholder" data-widget="{_he(str(map_cfg))}">'
			f'Farm Map — all fields with status overlays | Widget: {map_cfg["type"]} zoom={map_cfg["config"]["default_zoom"]}'
			f'</div>'
			f'<div class="row" style="margin-top:16px">'
			f'<div class="col-sm-3"><div class="panel panel-default"><div class="panel-body">'
			f'<strong>{_he(data["total_fields"])}</strong><br><small>Total Fields</small></div></div></div>'
			f'<div class="col-sm-3"><div class="panel panel-success"><div class="panel-body">'
			f'<strong>{_he(len(data["active_crops"]))}</strong><br><small>Active Crops</small></div></div></div>'
			f'<div class="col-sm-3"><div class="panel panel-info"><div class="panel-body">'
			f'<strong>{_he(data["total_planted_area_ha"])} ha</strong><br><small>Planted Area</small></div></div></div>'
			f'<div class="col-sm-3"><div class="panel panel-{"danger" if data["pending_observations"] else "default"}"><div class="panel-body">'
			f'<strong>{_he(data["pending_observations"])}</strong><br><small>Pending Alerts</small></div></div></div>'
			f'</div>'
			f'{alerts_html}'
			f'<h4>Active Crops</h4>'
			f'<table class="table table-condensed table-bordered">'
			f'<thead><tr><th>Field</th><th>Crop</th><th>Status</th><th>Planted</th><th>Expected Harvest</th></tr></thead>'
			f'<tbody>{crop_rows}</tbody></table>'
		)
		return make_response(_page_html(f"Dashboard: {data['farm']['name']}", body), 200)

	@expose("/<string:farm_id>/carbon")
	@has_access
	def carbon(self, farm_id: str):
		from pgappforge.plugins.erp.industry.agritech.services import AgriTechService, AgriServiceError
		session = _get_session()
		year = int(request.args.get("year", datetime.now().year))
		try:
			result = AgriTechService().calculate_carbon_sequestration(farm_id, year, session)
			return jsonify(result)
		except AgriServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 400


# ---------------------------------------------------------------------------
# PlantingView
# ---------------------------------------------------------------------------

class PlantingView(BaseView):
	"""Planting Activity CRUD + lifecycle.

	GET  /agri/plantings/           — list
	GET  /agri/plantings/<id>       — detail
	POST /agri/plantings/           — create
	POST /agri/plantings/<id>/advance — advance status
	GET  /agri/plantings/<id>/report  — field season report
	"""

	route_base = "/agri/plantings"
	default_view = "list"

	_widgets = {
		"planting_date": date_widget(),
		"expected_harvest_date": date_widget(),
		"seed_cost_cents": currency_widget("USD"),
	}

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.industry.agritech.models import PlantingActivity
		session = _get_session()
		q = sa.select(PlantingActivity).order_by(sa.desc(PlantingActivity.planting_date))
		for param, col in (
			("field_id", PlantingActivity.field_id),
			("crop_id", PlantingActivity.crop_id),
			("status", PlantingActivity.status),
			("tenant_id", PlantingActivity.tenant_id),
		):
			val = request.args.get(param)
			if val:
				q = q.where(col == val)
		activities = session.execute(q.limit(300)).scalars().all()
		return jsonify({"plantings": [
			{
				"id": a.id, "field_id": a.field_id, "crop_id": a.crop_id,
				"planting_date": a.planting_date.isoformat() if a.planting_date else None,
				"variety": a.variety, "status": a.status,
				"expected_harvest_date": a.expected_harvest_date.isoformat() if a.expected_harvest_date else None,
				"actual_harvest_date": a.actual_harvest_date.isoformat() if a.actual_harvest_date else None,
				"yield_kg": str(a.yield_kg or ""),
				"seed_cost_cents": a.seed_cost_cents,
			}
			for a in activities
		]})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		from pgappforge.plugins.erp.industry.agritech.models import PlantingActivity
		from pgappforge.plugins.erp.industry.agritech.events import PlantingCreatedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event
		from datetime import date as date_type
		session = _get_session()
		data = request.get_json(silent=True) or {}
		required = ("tenant_id", "field_id", "crop_id", "planting_date")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"ok": False, "error": f"missing: {missing}"}), 400
		act = PlantingActivity(
			tenant_id=data["tenant_id"],
			field_id=data["field_id"],
			crop_id=data["crop_id"],
			planting_date=date_type.fromisoformat(data["planting_date"]),
			variety=data.get("variety"),
			seed_quantity_kg=data.get("seed_quantity_kg"),
			seed_cost_cents=data.get("seed_cost_cents"),
			expected_harvest_date=date_type.fromisoformat(data["expected_harvest_date"]) if data.get("expected_harvest_date") else None,
			status="PLANNED",
		)
		session.add(act)
		session.flush()
		emit_event(
			PlantingCreatedEvent(
				aggregate_id=act.id, aggregate_type="PlantingActivity",
				tenant_id=act.tenant_id, activity_id=act.id,
				field_id=act.field_id, crop_id=act.crop_id,
				planting_date=act.planting_date.isoformat(),
				expected_harvest_date=act.expected_harvest_date.isoformat() if act.expected_harvest_date else "",
			),
			session,
		)
		session.commit()
		return jsonify({"ok": True, "id": act.id}), 201

	@expose("/<string:activity_id>/advance", methods=["POST"])
	@has_access
	def advance(self, activity_id: str):
		from pgappforge.plugins.erp.industry.agritech.services import AgriTechService, AgriServiceError
		session = _get_session()
		try:
			act = AgriTechService().advance_planting_status(activity_id, session)
			session.commit()
			return jsonify({"ok": True, "status": act.status})
		except AgriServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 400

	@expose("/<string:activity_id>/report")
	@has_access
	def report(self, activity_id: str):
		from pgappforge.plugins.erp.industry.agritech.models import PlantingActivity
		from pgappforge.plugins.erp.industry.agritech.services import AgriTechService, AgriServiceError
		session = _get_session()
		act = session.get(PlantingActivity, activity_id)
		if act is None:
			abort(404)
		season_year = int(request.args.get("season_year",
			act.planting_date.year if act.planting_date else datetime.now().year))
		try:
			result = AgriTechService().generate_field_report(act.field_id, season_year, session)
			return jsonify(result)
		except AgriServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 400


__all__ = [
	"FarmView",
	"FieldView",
	"ObservationView",
	"WeatherDashboardView",
	"FarmDashboardView",
	"PlantingView",
]
