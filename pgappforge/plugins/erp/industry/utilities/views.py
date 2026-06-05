"""
pgappforge/plugins/erp/industry/utilities/views.py

Flask views for the Utilities / Smart Grid plugin.

Endpoints:
  GridView           GET /utilities/grid/assets
                     GET /utilities/grid/topology
  MeterView          GET /utilities/meters/
                     POST /utilities/meters/<id>/ingest
                     GET  /utilities/meters/<id>/data
  OutageView         GET/POST /utilities/outages/
                     POST /utilities/outages/<id>/restore
  LoadForecastView   GET /utilities/forecast
  DemandResponseView GET/POST /utilities/dr/
  ReliabilityView    GET /utilities/reliability/indices
  GreenButtonView    GET /utilities/greenbutton/<meter_id>
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import sqlalchemy as sa
from flask import abort, jsonify, request, Response

from pgappforge import BaseView, expose
from pgappforge.security.decorators import has_access
from pgappforge.plugins.erp.foundation.view_helpers import (
	map_widget,
	chart_widget,
	heatmap_widget,
	date_range_widget,
	star_widget,
	select2_widget,
	json_widget,
	progress_widget,
)

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
	from pgappforge.plugins.erp.industry.utilities.services import UtilitiesService
	return UtilitiesService()


# ---------------------------------------------------------------------------
# GridView
# ---------------------------------------------------------------------------

class GridView(BaseView):
	"""Smart grid asset map and topology browser.

	Widget config:
	  location    → GeoPointWidget (MapWidget) — asset map overlay
	  load_chart  → AdvancedChartsWidget (line) — real-time load trend
	  status      → Select2Widget (filter)
	"""

	route_base = "/utilities/grid"
	default_view = "assets"

	field_widgets = {
		"location": map_widget(zoom=12),
		"load_chart": chart_widget("line"),
		"status": select2_widget([
			"IN_SERVICE", "OUT_OF_SERVICE", "MAINTENANCE",
		]),
	}
	label_columns = {
		"asset_id": "Asset ID",
		"asset_type": "Type",
		"name": "Name",
		"voltage_kv": "Voltage (kV)",
		"capacity_mva": "Capacity (MVA)",
		"status": "Status",
		"installation_date": "Installed",
		"age_years": "Age (years)",
	}

	@expose("/assets")
	@has_access
	def assets(self):
		from pgappforge.plugins.erp.industry.utilities.models import GridAsset
		session = _get_session()
		tenant_id = request.args.get("tenant_id")
		asset_type = request.args.get("asset_type")
		status = request.args.get("status")

		q = sa.select(GridAsset).order_by(GridAsset.name)
		if tenant_id:
			q = q.where(GridAsset.tenant_id == tenant_id)
		if asset_type:
			q = q.where(GridAsset.asset_type == asset_type)
		if status:
			q = q.where(GridAsset.status == status)

		rows = session.execute(q).scalars().all()
		return jsonify([
			{
				"id": r.id,
				"asset_id": r.asset_id,
				"asset_type": r.asset_type,
				"name": r.name,
				"voltage_kv": float(r.voltage_kv) if r.voltage_kv is not None else None,
				"capacity_mva": float(r.capacity_mva) if r.capacity_mva is not None else None,
				"status": r.status,
				"installation_date": r.installation_date.isoformat() if r.installation_date else None,
				"age_years": r.age_years,
				"owner_id": r.owner_id,
			}
			for r in rows
		])

	@expose("/topology")
	@has_access
	def topology(self):
		from pgappforge.plugins.erp.industry.utilities.models import GridTopology
		session = _get_session()
		tenant_id = request.args.get("tenant_id")
		from_asset = request.args.get("from_asset_id")

		q = sa.select(GridTopology).where(
			GridTopology.is_active.is_(True)
		).order_by(GridTopology.connection_type)
		if tenant_id:
			q = q.where(GridTopology.tenant_id == tenant_id)
		if from_asset:
			q = q.where(GridTopology.from_asset_id == from_asset)

		rows = session.execute(q).scalars().all()
		return jsonify([
			{
				"id": r.id,
				"from_asset_id": r.from_asset_id,
				"to_asset_id": r.to_asset_id,
				"connection_type": r.connection_type,
				"impedance_ohm": float(r.impedance_ohm) if r.impedance_ohm is not None else None,
				"is_normally_open": r.is_normally_open,
				"is_active": r.is_active,
			}
			for r in rows
		])


# ---------------------------------------------------------------------------
# MeterView
# ---------------------------------------------------------------------------

class MeterView(BaseView):
	"""AMI meter management and interval data ingestion.

	Widget config:
	  consumption_chart  → AdvancedChartsWidget (area) — kWh over time
	  date_range         → DateTimeRangeWidget — query range selector
	  service_address    → JSONEditorWidget
	"""

	route_base = "/utilities/meters"
	default_view = "list"

	field_widgets = {
		"consumption_chart": chart_widget("area"),
		"date_range": date_range_widget(),
		"service_address": json_widget(mode="tree"),
		"meter_type": select2_widget(["ANALOG", "SMART", "AMI"]),
	}
	label_columns = {
		"meter_id": "Meter Number",
		"customer_id": "Customer",
		"meter_type": "Type",
		"tariff_code": "Tariff",
		"time_of_use_enabled": "TOU Enabled",
		"installed_date": "Installed",
		"last_read_date": "Last Read",
	}

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.industry.utilities.models import EnergyMeter
		session = _get_session()
		tenant_id = request.args.get("tenant_id")
		customer_id = request.args.get("customer_id")

		q = sa.select(EnergyMeter).order_by(EnergyMeter.meter_id)
		if tenant_id:
			q = q.where(EnergyMeter.tenant_id == tenant_id)
		if customer_id:
			q = q.where(EnergyMeter.customer_id == customer_id)

		rows = session.execute(q).scalars().all()
		return jsonify([
			{
				"id": r.id,
				"meter_id": r.meter_id,
				"customer_id": r.customer_id,
				"meter_type": r.meter_type,
				"tariff_code": r.tariff_code,
				"time_of_use_enabled": r.time_of_use_enabled,
				"installed_date": r.installed_date.isoformat() if r.installed_date else None,
				"last_read_date": r.last_read_date.isoformat() if r.last_read_date else None,
				"grid_asset_id": r.grid_asset_id,
			}
			for r in rows
		])

	@expose("/<string:meter_id>/ingest", methods=["POST"])
	@has_access
	def ingest(self, meter_id: str):
		"""POST AMI interval data for a meter.

		Body: {"tenant_id": "...", "intervals": [{interval_start, interval_end,
		  consumption_kwh, demand_kw?, power_factor?, quality_code?}, ...]}
		"""
		session = _get_session()
		data = request.get_json(force=True) or {}
		if not data.get("intervals"):
			return jsonify({"error": "intervals array required"}), 400
		try:
			count = _svc().ingest_ami_data(
				session=session,
				meter_id=meter_id,
				interval_data=data["intervals"],
				tenant_id=data.get("tenant_id", ""),
			)
			session.commit()
			return jsonify({"meter_id": meter_id, "inserted": count, "status": "ok"})
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422

	@expose("/<string:meter_id>/data")
	@has_access
	def data(self, meter_id: str):
		"""GET interval data. Query params: start, end, limit (default 1000)."""
		from pgappforge.plugins.erp.industry.utilities.models import IntervalData
		session = _get_session()
		limit = int(request.args.get("limit", 1000))
		start_str = request.args.get("start")
		end_str = request.args.get("end")

		q = (
			sa.select(IntervalData)
			.where(IntervalData.meter_id == meter_id)
			.order_by(IntervalData.interval_start)
			.limit(limit)
		)
		if start_str:
			q = q.where(
				IntervalData.interval_start >= datetime.fromisoformat(start_str)
			)
		if end_str:
			q = q.where(
				IntervalData.interval_end <= datetime.fromisoformat(end_str)
			)

		rows = session.execute(q).scalars().all()
		return jsonify([
			{
				"interval_start": r.interval_start.isoformat(),
				"interval_end": r.interval_end.isoformat(),
				"consumption_kwh": float(r.consumption_kwh),
				"demand_kw": float(r.demand_kw) if r.demand_kw is not None else None,
				"power_factor": float(r.power_factor) if r.power_factor is not None else None,
				"quality_code": r.quality_code,
			}
			for r in rows
		])


# ---------------------------------------------------------------------------
# OutageView
# ---------------------------------------------------------------------------

class OutageView(BaseView):
	"""Outage lifecycle management.

	Widget config:
	  heatmap     → GeographicHeatmapWidget — outage density by location
	  severity    → StarRatingWidget (readonly, max=5, maps from outage_type)
	  status      → Select2Widget (filter)
	"""

	route_base = "/utilities/outages"
	default_view = "list"

	field_widgets = {
		"outage_density": heatmap_widget(),
		"severity": star_widget(max_rating=5, readonly=True),
		"status": select2_widget([
			"REPORTED", "DISPATCHED", "IN_RESTORATION", "RESTORED",
		]),
		"outage_type": select2_widget(["PLANNED", "UNPLANNED", "EMERGENCY"]),
	}
	label_columns = {
		"outage_id": "Outage #",
		"outage_type": "Type",
		"cause": "Cause",
		"affected_customers": "Customers Affected",
		"reported_at": "Reported",
		"started_at": "Started",
		"restored_at": "Restored",
		"saidi_minutes": "SAIDI (min)",
		"saifi_occurrences": "SAIFI",
		"status": "Status",
	}

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.industry.utilities.models import OutageEvent
		session = _get_session()
		tenant_id = request.args.get("tenant_id")
		status = request.args.get("status")
		outage_type = request.args.get("outage_type")

		q = (
			sa.select(OutageEvent)
			.order_by(OutageEvent.reported_at.desc())
			.limit(500)
		)
		if tenant_id:
			q = q.where(OutageEvent.tenant_id == tenant_id)
		if status:
			q = q.where(OutageEvent.status == status)
		if outage_type:
			q = q.where(OutageEvent.outage_type == outage_type)

		rows = session.execute(q).scalars().all()
		return jsonify([
			{
				"id": r.id,
				"outage_id": r.outage_id,
				"outage_type": r.outage_type,
				"cause": r.cause,
				"affected_customers": r.affected_customers,
				"reported_at": r.reported_at.isoformat() if r.reported_at else None,
				"started_at": r.started_at.isoformat() if r.started_at else None,
				"restored_at": r.restored_at.isoformat() if r.restored_at else None,
				"saidi_minutes": float(r.saidi_minutes),
				"saifi_occurrences": float(r.saifi_occurrences),
				"status": r.status,
			}
			for r in rows
		])

	@expose("/", methods=["POST"])
	@has_access
	def detect(self):
		"""POST to create an outage record.

		Body: {affected_assets: [...], cause, outage_type?, affected_customers?, tenant_id?}
		"""
		session = _get_session()
		data = request.get_json(force=True) or {}
		if not data.get("affected_assets") or not data.get("cause"):
			return jsonify({"error": "affected_assets and cause required"}), 400
		try:
			event = _svc().detect_outage(
				session=session,
				affected_assets=data["affected_assets"],
				cause=data["cause"],
				outage_type=data.get("outage_type", "UNPLANNED"),
				tenant_id=data.get("tenant_id", ""),
				affected_customers=data.get("affected_customers", 0),
			)
			session.commit()
			return jsonify({
				"outage_event_id": event.id,
				"outage_id": event.outage_id,
				"status": event.status,
			}), 201
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422

	@expose("/<string:outage_id>/restore", methods=["POST"])
	@has_access
	def restore(self, outage_id: str):
		"""Mark an outage as restored and record final SAIDI/SAIFI."""
		from pgappforge.plugins.erp.industry.utilities.models import OutageEvent
		from pgappforge.plugins.erp.industry.utilities.events import OutageRestoredEvent
		from pgappforge.plugins.erp.foundation.events import emit_event as _emit

		session = _get_session()
		data = request.get_json(force=True) or {}
		event = session.get(OutageEvent, outage_id)
		if event is None:
			return jsonify({"error": "outage not found"}), 404
		now = datetime.now(timezone.utc)
		event.restored_at = now
		event.status = "RESTORED"
		if data.get("saidi_minutes") is not None:
			from decimal import Decimal
			event.saidi_minutes = Decimal(str(data["saidi_minutes"]))
		if data.get("saifi_occurrences") is not None:
			from decimal import Decimal
			event.saifi_occurrences = Decimal(str(data["saifi_occurrences"]))
		session.flush()

		_emit(OutageRestoredEvent(
			aggregate_id=outage_id,
			aggregate_type="OutageEvent",
			tenant_id=str(event.tenant_id),
			outage_id=outage_id,
			restored_at=now.isoformat(),
			saidi_minutes=float(event.saidi_minutes),
			saifi_occurrences=float(event.saifi_occurrences),
		), session)

		session.commit()
		return jsonify({
			"outage_id": event.outage_id,
			"restored_at": now.isoformat(),
			"status": "RESTORED",
		})


# ---------------------------------------------------------------------------
# LoadForecastView
# ---------------------------------------------------------------------------

class LoadForecastView(BaseView):
	"""Hour-ahead and day-ahead load forecasts by grid area.

	Widget config:
	  forecast_chart → AdvancedChartsWidget (line with confidence band)
	"""

	route_base = "/utilities/forecast"
	default_view = "index"

	field_widgets = {
		"forecast_chart": chart_widget("line"),
	}

	@expose("/")
	@has_access
	def index(self):
		"""GET /utilities/forecast?area_id=<uuid>&hours=24&tenant_id=..."""
		area_id = request.args.get("area_id")
		if not area_id:
			return jsonify({"error": "area_id required"}), 400
		hours = int(request.args.get("hours", 24))
		tenant_id = request.args.get("tenant_id", "")
		session = _get_session()
		try:
			forecast = _svc().model_load_forecast(
				session=session,
				area_id=area_id,
				hours_ahead=hours,
				tenant_id=tenant_id,
			)
			return jsonify({
				"area_id": area_id,
				"hours_ahead": hours,
				"forecast": forecast,
				"_chart_config": chart_widget("line"),
			})
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422


# ---------------------------------------------------------------------------
# DemandResponseView
# ---------------------------------------------------------------------------

class DemandResponseView(BaseView):
	"""Demand response program event management."""

	route_base = "/utilities/dr"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.industry.utilities.models import DemandResponseEvent
		session = _get_session()
		tenant_id = request.args.get("tenant_id")
		status = request.args.get("status")

		q = sa.select(DemandResponseEvent).order_by(
			DemandResponseEvent.event_start.desc()
		).limit(200)
		if tenant_id:
			q = q.where(DemandResponseEvent.tenant_id == tenant_id)
		if status:
			q = q.where(DemandResponseEvent.status == status)

		rows = session.execute(q).scalars().all()
		return jsonify([
			{
				"id": r.id,
				"program_name": r.program_name,
				"event_start": r.event_start.isoformat() if r.event_start else None,
				"event_end": r.event_end.isoformat() if r.event_end else None,
				"target_reduction_kw": float(r.target_reduction_kw),
				"achieved_reduction_kw": float(r.achieved_reduction_kw),
				"enrolled_customers": r.enrolled_customers,
				"status": r.status,
			}
			for r in rows
		])

	@expose("/", methods=["POST"])
	@has_access
	def dispatch(self):
		session = _get_session()
		data = request.get_json(force=True) or {}
		required = ("program_name", "target_reduction_kw")
		missing = [f for f in required if data.get(f) is None]
		if missing:
			return jsonify({"error": f"Missing: {missing}"}), 400
		try:
			dr = _svc().dispatch_demand_response(
				session=session,
				program_name=data["program_name"],
				target_reduction_kw=float(data["target_reduction_kw"]),
				event_start=(
					datetime.fromisoformat(data["event_start"])
					if data.get("event_start") else None
				),
				event_end=(
					datetime.fromisoformat(data["event_end"])
					if data.get("event_end") else None
				),
				enrolled_customers=int(data.get("enrolled_customers", 0)),
				tenant_id=data.get("tenant_id", ""),
			)
			session.commit()
			return jsonify({
				"dr_event_id": dr.id,
				"program_name": dr.program_name,
				"status": dr.status,
			}), 201
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422


# ---------------------------------------------------------------------------
# ReliabilityView
# ---------------------------------------------------------------------------

class ReliabilityView(BaseView):
	"""SAIDI / SAIFI / CAIDI reliability indices reporting.

	Widget: AdvancedChartsWidget (grouped bar — SAIDI/SAIFI trend by month).
	"""

	route_base = "/utilities/reliability"
	default_view = "indices"

	field_widgets = {
		"reliability_chart": chart_widget("bar"),
	}

	@expose("/indices")
	@has_access
	def indices(self):
		"""GET /utilities/reliability/indices?start=<iso>&end=<iso>&customers=N&tenant_id=..."""
		start_str = request.args.get("start")
		end_str = request.args.get("end")
		if not start_str or not end_str:
			return jsonify({"error": "start and end ISO timestamps required"}), 400
		total_customers = int(request.args.get("customers", 1))
		tenant_id = request.args.get("tenant_id", "")
		session = _get_session()
		try:
			result = _svc().calculate_reliability_indices(
				session=session,
				period_start=datetime.fromisoformat(start_str),
				period_end=datetime.fromisoformat(end_str),
				tenant_id=tenant_id,
				total_customers=total_customers,
			)
			result["_chart_config"] = chart_widget("bar")
			return jsonify(result)
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422


# ---------------------------------------------------------------------------
# GreenButtonView
# ---------------------------------------------------------------------------

class GreenButtonView(BaseView):
	"""Green Button ESPI XML export for a meter + date range.

	GET /utilities/greenbutton/<meter_id>?start=<iso>&end=<iso>
	Returns: application/atom+xml
	"""

	route_base = "/utilities/greenbutton"
	default_view = "export"

	@expose("/<string:meter_id>")
	@has_access
	def export(self, meter_id: str):
		start_str = request.args.get("start")
		end_str = request.args.get("end")
		if not start_str or not end_str:
			return jsonify({"error": "start and end ISO timestamps required"}), 400
		session = _get_session()
		try:
			xml_str = _svc().generate_green_button_export(
				session=session,
				meter_id=meter_id,
				start_date=datetime.fromisoformat(start_str),
				end_date=datetime.fromisoformat(end_str),
			)
			return Response(
				xml_str,
				mimetype="application/atom+xml",
				headers={
					"Content-Disposition": (
						f'attachment; filename="greenbutton-{meter_id}.xml"'
					),
				},
			)
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422


__all__ = [
	"GridView",
	"MeterView",
	"OutageView",
	"LoadForecastView",
	"DemandResponseView",
	"ReliabilityView",
	"GreenButtonView",
]
