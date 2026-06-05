"""
pgappforge/plugins/erp/industry/smart_city/services.py

Business logic for the Smart City / IoT plugin.

SmartCityService is stateless — all methods accept a SQLAlchemy session
so callers control transaction boundaries.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import sqlalchemy as sa

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class SmartCityServiceError(Exception):
	"""Base exception for SmartCityService."""


class DeviceNotFoundError(SmartCityServiceError):
	"""Raised when an IoTDevice row cannot be found."""


class AssetNotFoundError(SmartCityServiceError):
	"""Raised when a SmartAsset row cannot be found."""


class ServiceRequestNotFoundError(SmartCityServiceError):
	"""Raised when a CityServiceRequest row cannot be found."""


# ---------------------------------------------------------------------------
# SmartCityService
# ---------------------------------------------------------------------------

class SmartCityService:
	"""Smart City / IoT platform service.

	Covers telemetry ingestion, anomaly detection, maintenance dispatch,
	dashboard aggregation, service request routing, and traffic density.
	"""

	# SLA hours per request type — real deployments load from config/DB
	_SLA_TABLE: dict[str, int] = {
		"pothole": 72,
		"streetlight": 48,
		"graffiti": 96,
		"waste": 24,
		"flooding": 4,
		"noise": 48,
		"default": 72,
	}

	# ------------------------------------------------------------------
	# ingest_telemetry
	# ------------------------------------------------------------------

	def ingest_telemetry(
		self,
		device_id: str,
		readings: list[dict[str, Any]],
		tenant_id: str,
		session: Any,
	) -> int:
		"""Persist a batch of sensor readings for a device.

		Each reading dict must contain: parameter, value, unit, measured_at.
		Optional: quality, raw_payload.

		Updates IoTDevice.is_online and last_seen_at as a side effect.

		Args:
			device_id: UUID of the IoTDevice.
			readings: List of reading dicts.
			tenant_id: Tenant UUID.
			session: SQLAlchemy session.

		Returns:
			Count of persisted readings.

		Raises:
			DeviceNotFoundError: If device does not exist.
		"""
		from pgappforge.plugins.erp.industry.smart_city.models import (
			IoTDevice,
			SensorReading,
		)
		from pgappforge.plugins.erp.industry.smart_city.events import (
			TelemetryIngestedEvent,
			emit_event,
		)

		device = session.get(IoTDevice, device_id)
		if device is None:
			raise DeviceNotFoundError(f"IoTDevice {device_id!r} not found")

		now = datetime.now(timezone.utc)
		count = 0

		for r in readings:
			if not r.get("parameter") or r.get("value") is None:
				log.warning("ingest_telemetry: skipping malformed reading %r", r)
				continue

			measured_at = r.get("measured_at")
			if isinstance(measured_at, str):
				try:
					measured_at = datetime.fromisoformat(measured_at)
				except ValueError:
					measured_at = now
			elif not isinstance(measured_at, datetime):
				measured_at = now

			row = SensorReading(
				tenant_id=tenant_id,
				device_id=device_id,
				measured_at=measured_at,
				parameter=r["parameter"],
				value=r["value"],
				unit=r.get("unit", ""),
				quality=r.get("quality", "GOOD"),
				raw_payload=r.get("raw_payload"),
			)
			session.add(row)
			count += 1

		# Update device heartbeat
		device.is_online = True
		device.last_seen_at = now
		session.flush()

		emit_event(
			TelemetryIngestedEvent(
				device_id=device_id,
				reading_count=count,
				parameter=readings[0].get("parameter", "") if readings else "",
			),
			session,
		)

		log.info("ingest_telemetry: device=%s persisted=%d", device_id, count)
		return count

	# ------------------------------------------------------------------
	# detect_anomalies
	# ------------------------------------------------------------------

	def detect_anomalies(
		self,
		device_id: str,
		session: Any,
		*,
		lookback_hours: int = 24,
	) -> list[dict[str, Any]]:
		"""Detect statistical anomalies in recent device telemetry.

		Uses a simple z-score approach (|value - mean| / stddev > 3) per
		parameter over the lookback window.  Returns anomalous readings.

		Args:
			device_id: UUID of the IoTDevice.
			session: SQLAlchemy session.
			lookback_hours: History window for baseline statistics.

		Returns:
			List of anomaly dicts with reading metadata and z-score.

		Raises:
			DeviceNotFoundError: If device does not exist.
		"""
		from pgappforge.plugins.erp.industry.smart_city.models import (
			IoTDevice,
			SensorReading,
		)
		from pgappforge.plugins.erp.industry.smart_city.events import (
			AnomalyDetectedEvent,
			emit_event,
		)

		device = session.get(IoTDevice, device_id)
		if device is None:
			raise DeviceNotFoundError(f"IoTDevice {device_id!r} not found")

		cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)

		# Aggregate stats per parameter
		stats_q = session.execute(
			sa.select(
				SensorReading.parameter,
				sa.func.avg(SensorReading.value).label("mean"),
				sa.func.stddev_pop(SensorReading.value).label("stddev"),
			)
			.where(
				SensorReading.device_id == device_id,
				SensorReading.measured_at >= cutoff,
			)
			.group_by(SensorReading.parameter)
		).all()

		stats = {
			row.parameter: {"mean": float(row.mean or 0), "stddev": float(row.stddev or 0)}
			for row in stats_q
		}

		# Fetch all readings in window
		readings = session.execute(
			sa.select(SensorReading)
			.where(
				SensorReading.device_id == device_id,
				SensorReading.measured_at >= cutoff,
			)
			.order_by(SensorReading.measured_at.desc())
		).scalars().all()

		anomalies = []
		for reading in readings:
			s = stats.get(reading.parameter, {})
			mean = s.get("mean", 0)
			stddev = s.get("stddev", 0)
			if stddev < 1e-9:
				continue
			z = abs(float(reading.value) - mean) / stddev
			if z > 3.0:
				anomalies.append({
					"reading_id": reading.id,
					"device_id": device_id,
					"parameter": reading.parameter,
					"value": float(reading.value),
					"unit": reading.unit,
					"measured_at": reading.measured_at.isoformat(),
					"z_score": round(z, 3),
					"mean": round(mean, 6),
					"stddev": round(stddev, 6),
					"quality": reading.quality,
				})

		if anomalies:
			emit_event(
				AnomalyDetectedEvent(
					device_id=device_id,
					parameter=anomalies[0]["parameter"],
					anomaly_count=len(anomalies),
					lookback_hours=lookback_hours,
				),
				session,
			)

		log.info(
			"detect_anomalies: device=%s window=%dh anomalies=%d",
			device_id, lookback_hours, len(anomalies),
		)
		return anomalies

	# ------------------------------------------------------------------
	# dispatch_maintenance
	# ------------------------------------------------------------------

	def dispatch_maintenance(
		self,
		asset_id: str,
		fault_description: str,
		session: Any,
	) -> dict[str, Any]:
		"""Mark a SmartAsset as MAINTENANCE and log a dispatch record.

		Emits MaintenanceDispatchedEvent and CityAlertIssuedEvent (severity=HIGH).

		Args:
			asset_id: UUID of the SmartAsset.
			fault_description: Human-readable fault description.
			session: SQLAlchemy session.

		Returns:
			Dict with asset metadata and dispatch timestamp.

		Raises:
			AssetNotFoundError: If asset does not exist.
		"""
		from pgappforge.plugins.erp.industry.smart_city.models import (
			CityAlert,
			SmartAsset,
		)
		from pgappforge.plugins.erp.industry.smart_city.events import (
			CityAlertIssuedEvent,
			MaintenanceDispatchedEvent,
			emit_event,
		)

		asset = session.get(SmartAsset, asset_id)
		if asset is None:
			raise AssetNotFoundError(f"SmartAsset {asset_id!r} not found")

		now = datetime.now(timezone.utc)
		asset.status = "MAINTENANCE"
		session.flush()

		# Create a city alert for the fault
		alert = CityAlert(
			tenant_id=asset.tenant_id,
			source_type="SYSTEM",
			source_id=asset_id,
			alert_type=f"asset_fault:{asset.asset_type}",
			severity="HIGH",
			message=fault_description,
			location=asset.location,
			issued_at=now,
			status="ACTIVE",
		)
		session.add(alert)
		session.flush()

		emit_event(
			MaintenanceDispatchedEvent(
				asset_id=asset_id,
				asset_type=asset.asset_type,
				fault_description=fault_description,
			),
			session,
		)
		emit_event(
			CityAlertIssuedEvent(
				alert_id=alert.id,
				alert_type=alert.alert_type,
				severity="HIGH",
				source_type="SYSTEM",
			),
			session,
		)

		log.info(
			"dispatch_maintenance: asset=%s type=%s alert=%s",
			asset_id, asset.asset_type, alert.id,
		)
		return {
			"asset_id": asset_id,
			"asset_name": asset.asset_name,
			"asset_type": asset.asset_type,
			"status": "MAINTENANCE",
			"alert_id": alert.id,
			"dispatched_at": now.isoformat(),
			"fault_description": fault_description,
		}

	# ------------------------------------------------------------------
	# generate_city_dashboard
	# ------------------------------------------------------------------

	def generate_city_dashboard(
		self,
		tenant_id: str,
		session: Any,
		*,
		zone: str | None = None,
	) -> dict[str, Any]:
		"""Aggregate KPIs for the city operations dashboard.

		Args:
			tenant_id: Tenant UUID.
			session: SQLAlchemy session.
			zone: Optional zone/district filter.

		Returns:
			Dict with device_online_count, active_alert_count, asset_fault_count,
			open_service_requests, energy_kwh_today, readings_today.
		"""
		from pgappforge.plugins.erp.industry.smart_city.models import (
			CityAlert,
			CityServiceRequest,
			IoTDevice,
			SensorReading,
			SmartAsset,
		)

		today_start = datetime.now(timezone.utc).replace(
			hour=0, minute=0, second=0, microsecond=0
		)

		# Devices online
		device_q = sa.select(sa.func.count(IoTDevice.id)).where(
			IoTDevice.tenant_id == tenant_id,
			IoTDevice.is_online == True,  # noqa: E712
		)
		device_online = session.execute(device_q).scalar_one()

		# Active alerts
		alert_q = sa.select(sa.func.count(CityAlert.id)).where(
			CityAlert.tenant_id == tenant_id,
			CityAlert.status == "ACTIVE",
		)
		active_alerts = session.execute(alert_q).scalar_one()

		# Faulted assets
		asset_q = sa.select(sa.func.count(SmartAsset.id)).where(
			SmartAsset.tenant_id == tenant_id,
			SmartAsset.status == "FAULT",
		)
		if zone:
			asset_q = asset_q.where(SmartAsset.zone == zone)
		faulted_assets = session.execute(asset_q).scalar_one()

		# Open service requests
		sr_q = sa.select(sa.func.count(CityServiceRequest.id)).where(
			CityServiceRequest.tenant_id == tenant_id,
			CityServiceRequest.status.in_(["OPEN", "ASSIGNED", "IN_PROGRESS"]),
		)
		open_sr = session.execute(sr_q).scalar_one()

		# Energy consumption today (sum of readings with parameter=energy_kwh)
		energy_q = sa.select(
			sa.func.coalesce(sa.func.sum(SensorReading.value), 0)
		).where(
			SensorReading.tenant_id == tenant_id,
			SensorReading.parameter == "energy_kwh",
			SensorReading.measured_at >= today_start,
		)
		energy_kwh = float(session.execute(energy_q).scalar_one() or 0)

		# Total readings today
		readings_q = sa.select(sa.func.count(SensorReading.id)).where(
			SensorReading.tenant_id == tenant_id,
			SensorReading.measured_at >= today_start,
		)
		readings_today = session.execute(readings_q).scalar_one()

		return {
			"tenant_id": tenant_id,
			"zone": zone,
			"devices_online": device_online,
			"active_alerts": active_alerts,
			"faulted_assets": faulted_assets,
			"open_service_requests": open_sr,
			"energy_kwh_today": round(energy_kwh, 3),
			"readings_today": readings_today,
			"generated_at": datetime.now(timezone.utc).isoformat(),
		}

	# ------------------------------------------------------------------
	# route_service_request
	# ------------------------------------------------------------------

	def route_service_request(
		self,
		request_id: str,
		session: Any,
	) -> dict[str, Any]:
		"""Assign a CityServiceRequest to the appropriate department.

		Uses request_type keywords to determine the responsible department and
		compute the SLA deadline.  Transitions status to ASSIGNED.
		Emits ServiceRequestRoutedEvent.

		Args:
			request_id: UUID of the CityServiceRequest.
			session: SQLAlchemy session.

		Returns:
			Dict with assigned_department, sla_hours, deadline_at.

		Raises:
			ServiceRequestNotFoundError: If request does not exist.
		"""
		from pgappforge.plugins.erp.industry.smart_city.models import CityServiceRequest
		from pgappforge.plugins.erp.industry.smart_city.events import (
			ServiceRequestRoutedEvent,
			emit_event,
		)

		sr = session.get(CityServiceRequest, request_id)
		if sr is None:
			raise ServiceRequestNotFoundError(f"CityServiceRequest {request_id!r} not found")

		_dept_map = {
			"pothole": "Roads & Highways",
			"streetlight": "Electrical Services",
			"graffiti": "Parks & Environment",
			"waste": "Waste Management",
			"flooding": "Stormwater Management",
			"noise": "Environmental Health",
			"parking": "Parking Authority",
			"tree": "Parks & Environment",
		}

		rtype_lower = (sr.request_type or "").lower()
		department = next(
			(dept for kw, dept in _dept_map.items() if kw in rtype_lower),
			"General Services",
		)
		sla_hours = next(
			(h for kw, h in self._SLA_TABLE.items() if kw in rtype_lower),
			self._SLA_TABLE["default"],
		)

		now = datetime.now(timezone.utc)
		deadline_at = now + timedelta(hours=sla_hours)

		sr.status = "ASSIGNED"
		session.flush()

		emit_event(
			ServiceRequestRoutedEvent(
				request_id=request_id,
				assigned_to=department,
				sla_hours=sla_hours,
			),
			session,
		)

		log.info(
			"route_service_request: request=%s dept=%s sla=%dh",
			request_id, department, sla_hours,
		)
		return {
			"request_id": request_id,
			"assigned_department": department,
			"sla_hours": sla_hours,
			"deadline_at": deadline_at.isoformat(),
		}

	# ------------------------------------------------------------------
	# get_traffic_density
	# ------------------------------------------------------------------

	def get_traffic_density(
		self,
		zone: str,
		tenant_id: str,
		session: Any,
		*,
		time_window_minutes: int = 15,
	) -> dict[str, Any]:
		"""Compute traffic density metrics for a zone over a recent time window.

		Aggregates SensorReading rows where parameter IN
		('vehicle_count', 'occupancy', 'average_speed') across all devices
		in the specified zone.

		Args:
			zone: City zone/district identifier.
			tenant_id: Tenant UUID.
			session: SQLAlchemy session.
			time_window_minutes: Look-back window in minutes.

		Returns:
			Dict with total_vehicle_count, avg_occupancy, avg_speed_kmh,
			sensor_count, congestion_level.
		"""
		from pgappforge.plugins.erp.industry.smart_city.models import (
			IoTDevice,
			SensorReading,
			SmartAsset,
		)

		cutoff = datetime.now(timezone.utc) - timedelta(minutes=time_window_minutes)

		# Devices in zone (via SmartAsset relationship)
		zone_device_ids = session.execute(
			sa.select(SmartAsset.device_id)
			.where(
				SmartAsset.tenant_id == tenant_id,
				SmartAsset.zone == zone,
				SmartAsset.device_id.isnot(None),
			)
		).scalars().all()

		if not zone_device_ids:
			return {
				"zone": zone,
				"time_window_minutes": time_window_minutes,
				"total_vehicle_count": 0,
				"avg_occupancy": 0.0,
				"avg_speed_kmh": 0.0,
				"sensor_count": 0,
				"congestion_level": "unknown",
			}

		agg = session.execute(
			sa.select(
				SensorReading.parameter,
				sa.func.sum(SensorReading.value).label("total"),
				sa.func.avg(SensorReading.value).label("avg"),
				sa.func.count(SensorReading.id).label("cnt"),
			)
			.where(
				SensorReading.device_id.in_(zone_device_ids),
				SensorReading.measured_at >= cutoff,
				SensorReading.parameter.in_(
					["vehicle_count", "occupancy", "average_speed"]
				),
			)
			.group_by(SensorReading.parameter)
		).all()

		stats = {row.parameter: row for row in agg}
		vc_row = stats.get("vehicle_count")
		occ_row = stats.get("occupancy")
		spd_row = stats.get("average_speed")

		total_vc = int(vc_row.total or 0) if vc_row else 0
		avg_occ = float(occ_row.avg or 0) if occ_row else 0.0
		avg_spd = float(spd_row.avg or 0) if spd_row else 0.0

		# Congestion classification
		if avg_occ >= 0.8 or avg_spd < 15:
			congestion = "heavy"
		elif avg_occ >= 0.5 or avg_spd < 40:
			congestion = "moderate"
		elif avg_occ >= 0.2:
			congestion = "light"
		else:
			congestion = "free_flow"

		return {
			"zone": zone,
			"time_window_minutes": time_window_minutes,
			"total_vehicle_count": total_vc,
			"avg_occupancy": round(avg_occ, 4),
			"avg_speed_kmh": round(avg_spd, 2),
			"sensor_count": len(zone_device_ids),
			"congestion_level": congestion,
		}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"SmartCityService",
	"SmartCityServiceError",
	"DeviceNotFoundError",
	"AssetNotFoundError",
	"ServiceRequestNotFoundError",
]
