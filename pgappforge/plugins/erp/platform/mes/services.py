"""MES service — telemetry ingestion, OEE, OPC-UA stub."""
from __future__ import annotations
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import sqlalchemy as sa

from pgappforge.plugins.erp.platform.mes.models import MachineDefinition, MachineReading, ProductionAlert

_THRESHOLDS = {"temp_c": 90, "rejects": 5}


def _uuid() -> str:
	return str(uuid.uuid4())


class MESService:
	def register_machine(self, tenant_id: str, machine_code: str, work_center_id: str | None = None, opc_ua_endpoint: str | None = None, session: Any = None) -> MachineDefinition:
		machine = MachineDefinition(id=_uuid(), tenant_id=tenant_id, machine_code=machine_code, work_center_id=work_center_id, opc_ua_endpoint=opc_ua_endpoint)
		if session:
			session.add(machine)
		return machine

	def ingest_telemetry(self, machine_id: str, readings_dict: dict[str, Any], session: Any) -> MachineReading:
		reading = MachineReading(id=_uuid(), machine_id=machine_id, reading_at=datetime.now(timezone.utc), readings=readings_dict)
		session.add(reading)
		for metric, threshold in _THRESHOLDS.items():
			if readings_dict.get(metric, 0) > threshold:
				alert = ProductionAlert(
					id=_uuid(),
					machine_id=machine_id,
					alert_type="QUALITY" if metric == "rejects" else "DOWNTIME",
					severity="HIGH",
					started_at=datetime.now(timezone.utc),
					description=f"{metric}={readings_dict[metric]} > threshold {threshold}",
				)
				session.add(alert)
		return reading

	def get_oee(self, machine_id: str, date: Any, session: Any) -> dict[str, Any]:
		from datetime import date as date_type, datetime, timezone as tz
		if isinstance(date, date_type) and not isinstance(date, datetime):
			day_start = datetime(date.year, date.month, date.day, tzinfo=tz.utc)
			day_end = datetime(date.year, date.month, date.day, 23, 59, 59, tzinfo=tz.utc)
		else:
			day_start = day_end = date

		readings = session.execute(
			sa.select(MachineReading).where(
				MachineReading.machine_id == machine_id,
				MachineReading.reading_at >= day_start,
				MachineReading.reading_at <= day_end,
			)
		).scalars().all()
		if not readings:
			return {"availability": 0, "performance": None, "quality": 0, "oee": 0, "note": "no readings for date"}

		total_pieces = sum(r.readings.get("pieces_produced", 0) for r in readings)
		total_rejects = sum(r.readings.get("rejects", 0) for r in readings)
		quality = (total_pieces - total_rejects) / total_pieces if total_pieces else 0

		# Availability: (readings with no downtime alert) / total reading slots
		alert_periods = session.execute(
			sa.select(ProductionAlert).where(
				ProductionAlert.machine_id == machine_id,
				ProductionAlert.alert_type == "DOWNTIME",
				ProductionAlert.started_at >= day_start,
				ProductionAlert.started_at <= day_end,
				ProductionAlert.resolved_at.isnot(None),
			)
		).scalars().all()
		downtime_hours = sum(
			(a.resolved_at - a.started_at).total_seconds() / 3600
			for a in alert_periods
		)
		planned_hours = 8.0  # default shift; override via WorkCenter.capacity_hours_per_day
		availability = max(0.0, min(1.0, (planned_hours - downtime_hours) / planned_hours))

		# Performance: unavailable without ideal cycle time — return None rather than fabricate
		oee = availability * quality  # conservative: excludes performance factor
		return {
			"availability": round(availability, 3),
			"performance": None,  # requires ideal_cycle_time per product — not yet configured
			"quality": round(quality, 3),
			"oee": round(oee, 3),
			"oee_note": "OEE = availability × quality; performance excluded (ideal_cycle_time not configured)",
		}

	def poll_opcua(self, machine_id: str, session: Any) -> None:
		machine = session.get(MachineDefinition, machine_id)
		if not machine or not machine.opc_ua_endpoint:
			return
		try:
			from asyncua import Client  # type: ignore[import]
		except ImportError:
			pass


__all__ = ["MESService"]
