"""
pgappforge/plugins/erp/industry/smart_city/views.py

Flask views for the Smart City / IoT plugin.

Views:
  DeviceView          — IoT device registry with MapWidget, online toggle
  AlertView           — City alert management with heatmap + severity Select2
  ServiceRequestView  — Citizen service requests with map + camera + rich text
  CityDashboard       — Operational KPI dashboard with map + charts
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import sqlalchemy as sa
from flask import abort, jsonify, request

from pgappforge import BaseView, expose
from pgappforge.security.decorators import has_access
from pgappforge.plugins.erp.foundation.view_helpers import (
	chart_widget,
	date_widget,
	map_widget,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
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
	raise RuntimeError("Cannot obtain database session outside app context")


def _svc():
	from pgappforge.plugins.erp.industry.smart_city.services import SmartCityService
	return SmartCityService()


# ---------------------------------------------------------------------------
# DeviceView
# ---------------------------------------------------------------------------

class DeviceView(BaseView):
	"""IoT device registry.

	MapWidget for location display/edit.
	ToggleButton annotation for is_online field.

	GET  /smart-city/devices/               — list (filterable by type, online)
	POST /smart-city/devices/               — register device
	GET  /smart-city/devices/<id>           — detail
	POST /smart-city/devices/<id>/online    — force online=True
	POST /smart-city/devices/<id>/offline   — force online=False
	POST /smart-city/devices/<id>/telemetry — ingest readings batch
	"""

	route_base = "/smart-city/devices"
	default_view = "list"

	_field_widgets = {
		"location": map_widget(zoom=14),
		"is_online": {"widget": "ToggleButtonWidget", "on_label": "Online", "off_label": "Offline"},
		"installation_date": date_widget(),
		"last_seen_at": date_widget("YYYY-MM-DDTHH:MM:SSZ"),
		"device_type": {"widget": "Select2Widget", "choices": [
			"SENSOR", "ACTUATOR", "GATEWAY", "CAMERA", "METER",
		]},
		"protocol": {"widget": "Select2Widget", "choices": [
			"MQTT", "HTTP", "COAP", "MODBUS", "BACnet",
		]},
	}

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.industry.smart_city.models import IoTDevice
		session = _get_session()
		tenant_id = request.args.get("tenant_id")
		device_type = request.args.get("device_type")
		online = request.args.get("online")

		q = (
			sa.select(IoTDevice)
			.order_by(IoTDevice.device_name)
			.limit(500)
		)
		if tenant_id:
			q = q.where(IoTDevice.tenant_id == tenant_id)
		if device_type:
			q = q.where(IoTDevice.device_type == device_type)
		if online is not None:
			q = q.where(IoTDevice.is_online == (online.lower() == "true"))

		rows = session.execute(q).scalars().all()
		return jsonify([
			{
				"id": r.id,
				"device_id": r.device_id,
				"device_name": r.device_name,
				"device_type": r.device_type,
				"protocol": r.protocol,
				"is_online": r.is_online,
				"battery_level_pct": r.battery_level_pct,
				"last_seen_at": r.last_seen_at.isoformat() if r.last_seen_at else None,
				"location": r.location,
				"firmware_version": r.firmware_version,
				"tags": r.tags,
			}
			for r in rows
		])

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		from pgappforge.plugins.erp.industry.smart_city.models import IoTDevice
		from pgappforge.plugins.erp.industry.smart_city.events import (
			DeviceRegisteredEvent,
			emit_event,
		)
		session = _get_session()
		data = request.get_json(force=True) or {}
		required = ("tenant_id", "device_id", "device_name", "device_type", "protocol")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"error": f"Missing required fields: {missing}"}), 400

		device = IoTDevice(
			tenant_id=data["tenant_id"],
			device_id=data["device_id"],
			device_name=data["device_name"],
			device_type=data["device_type"],
			protocol=data["protocol"],
			location=data.get("location"),
			address=data.get("address"),
			installation_date=data.get("installation_date"),
			firmware_version=data.get("firmware_version"),
			battery_level_pct=data.get("battery_level_pct"),
			tags=data.get("tags", []),
			owner_id=data.get("owner_id"),
		)
		session.add(device)
		session.flush()
		emit_event(
			DeviceRegisteredEvent(
				device_id=device.id,
				device_type=device.device_type,
				protocol=device.protocol,
			),
			session,
		)
		session.commit()
		return jsonify({"id": device.id, "device_id": device.device_id}), 201

	@expose("/<string:device_id>")
	@has_access
	def detail(self, device_id: str):
		from pgappforge.plugins.erp.industry.smart_city.models import IoTDevice
		session = _get_session()
		device = session.get(IoTDevice, device_id)
		if device is None:
			abort(404)
		return jsonify({
			"id": device.id,
			"device_id": device.device_id,
			"device_name": device.device_name,
			"device_type": device.device_type,
			"protocol": device.protocol,
			"location": device.location,
			"address": device.address,
			"installation_date": device.installation_date.isoformat() if device.installation_date else None,
			"firmware_version": device.firmware_version,
			"battery_level_pct": device.battery_level_pct,
			"is_online": device.is_online,
			"last_seen_at": device.last_seen_at.isoformat() if device.last_seen_at else None,
			"tags": device.tags,
			"owner_id": device.owner_id,
		})

	@expose("/<string:device_id>/online", methods=["POST"])
	@has_access
	def set_online(self, device_id: str):
		from pgappforge.plugins.erp.industry.smart_city.models import IoTDevice
		from pgappforge.plugins.erp.industry.smart_city.events import (
			DeviceOnlineEvent,
			emit_event,
		)
		session = _get_session()
		device = session.get(IoTDevice, device_id)
		if device is None:
			abort(404)
		device.is_online = True
		device.last_seen_at = datetime.now(timezone.utc)
		session.flush()
		emit_event(
			DeviceOnlineEvent(device_id=device.id, device_type=device.device_type),
			session,
		)
		session.commit()
		return jsonify({"id": device.id, "is_online": True})

	@expose("/<string:device_id>/offline", methods=["POST"])
	@has_access
	def set_offline(self, device_id: str):
		from pgappforge.plugins.erp.industry.smart_city.models import IoTDevice
		from pgappforge.plugins.erp.industry.smart_city.events import (
			DeviceOfflineEvent,
			emit_event,
		)
		session = _get_session()
		device = session.get(IoTDevice, device_id)
		if device is None:
			abort(404)
		now = datetime.now(timezone.utc)
		device.is_online = False
		session.flush()
		emit_event(
			DeviceOfflineEvent(
				device_id=device.id,
				device_type=device.device_type,
				last_seen_at=device.last_seen_at.isoformat() if device.last_seen_at else "",
			),
			session,
		)
		session.commit()
		return jsonify({"id": device.id, "is_online": False})

	@expose("/<string:device_id>/telemetry", methods=["POST"])
	@has_access
	def ingest_telemetry(self, device_id: str):
		"""POST /smart-city/devices/<id>/telemetry  body: {tenant_id, readings: [...]}"""
		session = _get_session()
		data = request.get_json(force=True) or {}
		if not data.get("tenant_id") or not data.get("readings"):
			return jsonify({"error": "tenant_id and readings required"}), 400
		try:
			count = _svc().ingest_telemetry(
				device_id, data["readings"], data["tenant_id"], session
			)
			session.commit()
			return jsonify({"device_id": device_id, "ingested": count})
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422

	@expose("/<string:device_id>/anomalies")
	@has_access
	def anomalies(self, device_id: str):
		"""GET /smart-city/devices/<id>/anomalies?hours=24"""
		session = _get_session()
		hours = int(request.args.get("hours", 24))
		try:
			results = _svc().detect_anomalies(device_id, session, lookback_hours=hours)
			return jsonify({"device_id": device_id, "anomaly_count": len(results), "anomalies": results})
		except Exception as exc:
			return jsonify({"error": str(exc)}), 404


# ---------------------------------------------------------------------------
# AlertView
# ---------------------------------------------------------------------------

class AlertView(BaseView):
	"""City alert management.

	GeographicHeatmapWidget annotation for location-based alert density.
	Select2 for severity filter.

	GET  /smart-city/alerts/                  — list active alerts
	POST /smart-city/alerts/                  — create alert
	GET  /smart-city/alerts/<id>             — detail
	POST /smart-city/alerts/<id>/acknowledge  — acknowledge
	POST /smart-city/alerts/<id>/resolve      — resolve
	"""

	route_base = "/smart-city/alerts"
	default_view = "list"

	_field_widgets = {
		"location": {
			"widget": "GeographicHeatmapWidget",
			**map_widget(zoom=12),
			"heatmap": True,
		},
		"severity": {"widget": "Select2Widget", "choices": [
			"LOW", "MEDIUM", "HIGH", "CRITICAL",
		]},
		"issued_at": date_widget("YYYY-MM-DDTHH:MM:SSZ"),
		"expires_at": date_widget("YYYY-MM-DDTHH:MM:SSZ"),
	}

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.industry.smart_city.models import CityAlert
		session = _get_session()
		tenant_id = request.args.get("tenant_id")
		severity = request.args.get("severity")
		status = request.args.get("status", "ACTIVE")

		q = (
			sa.select(CityAlert)
			.order_by(
				sa.case(
					{"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3},
					value=CityAlert.severity,
					else_=4,
				),
				CityAlert.issued_at.desc(),
			)
			.limit(200)
		)
		if tenant_id:
			q = q.where(CityAlert.tenant_id == tenant_id)
		if severity:
			q = q.where(CityAlert.severity == severity)
		if status:
			q = q.where(CityAlert.status == status)

		rows = session.execute(q).scalars().all()
		return jsonify([
			{
				"id": r.id,
				"source_type": r.source_type,
				"source_id": r.source_id,
				"alert_type": r.alert_type,
				"severity": r.severity,
				"message": r.message,
				"location": r.location,
				"issued_at": r.issued_at.isoformat() if r.issued_at else None,
				"expires_at": r.expires_at.isoformat() if r.expires_at else None,
				"status": r.status,
			}
			for r in rows
		])

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		from pgappforge.plugins.erp.industry.smart_city.models import CityAlert
		from pgappforge.plugins.erp.industry.smart_city.events import (
			CityAlertIssuedEvent,
			emit_event,
		)
		session = _get_session()
		data = request.get_json(force=True) or {}
		required = ("tenant_id", "source_type", "source_id", "alert_type", "message")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"error": f"Missing: {missing}"}), 400

		now = datetime.now(timezone.utc)
		alert = CityAlert(
			tenant_id=data["tenant_id"],
			source_type=data["source_type"],
			source_id=data["source_id"],
			alert_type=data["alert_type"],
			severity=data.get("severity", "MEDIUM"),
			message=data["message"],
			location=data.get("location"),
			geo_area=data.get("geo_area"),
			issued_at=now,
			expires_at=data.get("expires_at"),
			status="ACTIVE",
		)
		session.add(alert)
		session.flush()
		emit_event(
			CityAlertIssuedEvent(
				alert_id=alert.id,
				alert_type=alert.alert_type,
				severity=alert.severity,
				source_type=alert.source_type,
			),
			session,
		)
		session.commit()
		return jsonify({"alert_id": alert.id, "status": "ACTIVE"}), 201

	@expose("/<string:alert_id>")
	@has_access
	def detail(self, alert_id: str):
		from pgappforge.plugins.erp.industry.smart_city.models import CityAlert
		session = _get_session()
		alert = session.get(CityAlert, alert_id)
		if alert is None:
			abort(404)
		return jsonify({
			"id": alert.id,
			"source_type": alert.source_type,
			"source_id": alert.source_id,
			"alert_type": alert.alert_type,
			"severity": alert.severity,
			"message": alert.message,
			"location": alert.location,
			"geo_area": alert.geo_area,
			"issued_at": alert.issued_at.isoformat() if alert.issued_at else None,
			"expires_at": alert.expires_at.isoformat() if alert.expires_at else None,
			"status": alert.status,
			"acknowledged_by": alert.acknowledged_by,
		})

	@expose("/<string:alert_id>/acknowledge", methods=["POST"])
	@has_access
	def acknowledge(self, alert_id: str):
		from pgappforge.plugins.erp.industry.smart_city.models import CityAlert
		from pgappforge.plugins.erp.industry.smart_city.events import (
			CityAlertAcknowledgedEvent,
			emit_event,
		)
		session = _get_session()
		alert = session.get(CityAlert, alert_id)
		if alert is None:
			abort(404)
		data = request.get_json(force=True) or {}
		alert.status = "ACKNOWLEDGED"
		alert.acknowledged_by = data.get("acknowledged_by")
		session.flush()
		emit_event(
			CityAlertAcknowledgedEvent(
				alert_id=alert.id,
				acknowledged_by=str(alert.acknowledged_by or ""),
			),
			session,
		)
		session.commit()
		return jsonify({"alert_id": alert.id, "status": "ACKNOWLEDGED"})

	@expose("/<string:alert_id>/resolve", methods=["POST"])
	@has_access
	def resolve(self, alert_id: str):
		from pgappforge.plugins.erp.industry.smart_city.models import CityAlert
		from pgappforge.plugins.erp.industry.smart_city.events import (
			CityAlertResolvedEvent,
			emit_event,
		)
		session = _get_session()
		alert = session.get(CityAlert, alert_id)
		if alert is None:
			abort(404)
		alert.status = "RESOLVED"
		session.flush()
		emit_event(CityAlertResolvedEvent(alert_id=alert.id), session)
		session.commit()
		return jsonify({"alert_id": alert.id, "status": "RESOLVED"})


# ---------------------------------------------------------------------------
# ServiceRequestView
# ---------------------------------------------------------------------------

class ServiceRequestView(BaseView):
	"""Citizen service request management.

	MapWidget for location.
	CameraWidget annotation for photos field.
	RichTextEditor for description.

	GET  /smart-city/service-requests/               — list
	POST /smart-city/service-requests/               — create
	GET  /smart-city/service-requests/<id>           — detail
	POST /smart-city/service-requests/<id>/route     — auto-route to department
	POST /smart-city/service-requests/<id>/resolve   — mark resolved
	"""

	route_base = "/smart-city/service-requests"
	default_view = "list"

	_field_widgets = {
		"location": map_widget(zoom=15),
		"photos": {"widget": "CameraWidget", "max_files": 5, "accept": "image/*"},
		"description": {"widget": "RichTextEditorWidget"},
		"channel": {"widget": "Select2Widget", "choices": ["APP", "WEB", "PHONE", "311"]},
		"status": {"widget": "Select2Widget", "choices": [
			"OPEN", "ASSIGNED", "IN_PROGRESS", "RESOLVED",
		]},
	}

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.industry.smart_city.models import CityServiceRequest
		session = _get_session()
		tenant_id = request.args.get("tenant_id")
		status = request.args.get("status")
		rtype = request.args.get("request_type")

		q = (
			sa.select(CityServiceRequest)
			.order_by(CityServiceRequest.created_at.desc())
			.limit(500)
		)
		if tenant_id:
			q = q.where(CityServiceRequest.tenant_id == tenant_id)
		if status:
			q = q.where(CityServiceRequest.status == status)
		if rtype:
			q = q.where(CityServiceRequest.request_type == rtype)

		rows = session.execute(q).scalars().all()
		return jsonify([
			{
				"id": r.id,
				"request_type": r.request_type,
				"channel": r.channel,
				"status": r.status,
				"location": r.location,
				"description": r.description[:120] + "…" if r.description and len(r.description) > 120 else r.description,
				"created_at": r.created_at.isoformat() if r.created_at else None,
				"resolved_at": r.resolved_at.isoformat() if r.resolved_at else None,
			}
			for r in rows
		])

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		from pgappforge.plugins.erp.industry.smart_city.models import CityServiceRequest
		from pgappforge.plugins.erp.industry.smart_city.events import (
			ServiceRequestCreatedEvent,
			emit_event,
		)
		session = _get_session()
		data = request.get_json(force=True) or {}
		required = ("tenant_id", "request_type", "description")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"error": f"Missing: {missing}"}), 400

		sr = CityServiceRequest(
			tenant_id=data["tenant_id"],
			constituent_id=data.get("constituent_id"),
			channel=data.get("channel", "WEB"),
			request_type=data["request_type"],
			location=data.get("location"),
			address=data.get("address"),
			description=data["description"],
			photos=data.get("photos", []),
			status="OPEN",
		)
		session.add(sr)
		session.flush()
		emit_event(
			ServiceRequestCreatedEvent(
				request_id=sr.id,
				request_type=sr.request_type,
				channel=sr.channel,
			),
			session,
		)
		session.commit()
		return jsonify({"request_id": sr.id, "status": "OPEN"}), 201

	@expose("/<string:request_id>")
	@has_access
	def detail(self, request_id: str):
		from pgappforge.plugins.erp.industry.smart_city.models import CityServiceRequest
		session = _get_session()
		sr = session.get(CityServiceRequest, request_id)
		if sr is None:
			abort(404)
		return jsonify({
			"id": sr.id,
			"constituent_id": sr.constituent_id,
			"channel": sr.channel,
			"request_type": sr.request_type,
			"location": sr.location,
			"address": sr.address,
			"description": sr.description,
			"photos": sr.photos,
			"status": sr.status,
			"assigned_to": sr.assigned_to,
			"created_at": sr.created_at.isoformat() if sr.created_at else None,
			"resolved_at": sr.resolved_at.isoformat() if sr.resolved_at else None,
		})

	@expose("/<string:request_id>/route", methods=["POST"])
	@has_access
	def route(self, request_id: str):
		session = _get_session()
		try:
			result = _svc().route_service_request(request_id, session)
			session.commit()
			return jsonify(result)
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422

	@expose("/<string:request_id>/resolve", methods=["POST"])
	@has_access
	def resolve(self, request_id: str):
		from pgappforge.plugins.erp.industry.smart_city.models import CityServiceRequest
		from pgappforge.plugins.erp.industry.smart_city.events import (
			ServiceRequestResolvedEvent,
			emit_event,
		)
		session = _get_session()
		sr = session.get(CityServiceRequest, request_id)
		if sr is None:
			abort(404)
		now = datetime.now(timezone.utc)
		sr.status = "RESOLVED"
		sr.resolved_at = now
		session.flush()
		emit_event(
			ServiceRequestResolvedEvent(
				request_id=sr.id,
				request_type=sr.request_type,
			),
			session,
		)
		session.commit()
		return jsonify({
			"request_id": sr.id,
			"status": "RESOLVED",
			"resolved_at": now.isoformat(),
		})


# ---------------------------------------------------------------------------
# CityDashboard
# ---------------------------------------------------------------------------

class CityDashboard(BaseView):
	"""City operations dashboard.

	MapWidget for geo-overview of devices and alerts.
	AdvancedChartsWidget for KPI trends.

	GET /smart-city/dashboard/                              — KPI summary
	GET /smart-city/dashboard/traffic?zone=<z>&minutes=<m> — traffic density
	GET /smart-city/dashboard/maintenance/<asset_id>        — dispatch maintenance
	"""

	route_base = "/smart-city/dashboard"
	default_view = "index"

	_chart_widgets = {
		"device_status": chart_widget("donut"),
		"alerts_by_severity": chart_widget("bar"),
		"readings_trend": chart_widget("line"),
		"service_requests_by_type": chart_widget("bar"),
	}
	_map_widget = map_widget(zoom=11)

	@expose("/")
	@has_access
	def index(self):
		tenant_id = request.args.get("tenant_id")
		zone = request.args.get("zone")
		if not tenant_id:
			return jsonify({
				"endpoints": {
					"dashboard": "/smart-city/dashboard/?tenant_id=<id>&zone=<optional>",
					"traffic": "/smart-city/dashboard/traffic?zone=<z>&tenant_id=<id>&minutes=15",
					"maintenance": "/smart-city/dashboard/maintenance/<asset_id>",
				}
			})
		session = _get_session()
		data = _svc().generate_city_dashboard(tenant_id, session, zone=zone)
		return jsonify(data)

	@expose("/traffic")
	@has_access
	def traffic(self):
		zone = request.args.get("zone")
		tenant_id = request.args.get("tenant_id")
		minutes = int(request.args.get("minutes", 15))
		if not zone or not tenant_id:
			return jsonify({"error": "zone and tenant_id required"}), 400
		session = _get_session()
		result = _svc().get_traffic_density(zone, tenant_id, session, time_window_minutes=minutes)
		return jsonify(result)

	@expose("/maintenance/<string:asset_id>", methods=["POST"])
	@has_access
	def dispatch_maintenance(self, asset_id: str):
		session = _get_session()
		data = request.get_json(force=True) or {}
		fault_description = data.get("fault_description", "Fault reported via dashboard")
		try:
			result = _svc().dispatch_maintenance(asset_id, fault_description, session)
			session.commit()
			return jsonify(result)
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"DeviceView",
	"AlertView",
	"ServiceRequestView",
	"CityDashboard",
]
