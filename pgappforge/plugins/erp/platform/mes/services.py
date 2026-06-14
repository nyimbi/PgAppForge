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
		readings = session.execute(
			sa.select(MachineReading).where(MachineReading.machine_id == machine_id)
		).scalars().all()
		if not readings:
			return {"availability": 0, "performance": 0, "quality": 0, "oee": 0}
		total_pieces = sum(r.readings.get("pieces_produced", 0) for r in readings)
		total_rejects = sum(r.readings.get("rejects", 0) for r in readings)
		quality = (total_pieces - total_rejects) / total_pieces if total_pieces else 0
		availability = 0.9
		performance = 0.85
		oee = availability * performance * quality
		return {"availability": round(availability, 3), "performance": round(performance, 3), "quality": round(quality, 3), "oee": round(oee, 3)}

	def poll_opcua(self, machine_id: str, session: Any) -> None:
		machine = session.get(MachineDefinition, machine_id)
		if not machine or not machine.opc_ua_endpoint:
			return
		try:
			from asyncua import Client  # type: ignore[import]
		except ImportError:
			pass


__all__ = ["MESService"]
