"""
pgappforge/plugins/erp/platform/mes/services.py

MESService — machine registration, telemetry ingestion, OEE computation,
production order linking, and optional OPC-UA polling.
"""
from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import sqlalchemy as sa

log = logging.getLogger(__name__)


def _uuid4() -> str:
	return str(uuid.uuid4())


def _now() -> datetime:
	return datetime.now(timezone.utc)


def _emit(event: Any, session: Any = None) -> None:
	try:
		from pgappforge.plugins.erp.foundation.events import emit_event as _emit_event
		_emit_event(event, session)
	except Exception as exc:
		log.debug("MES event emit failed: %s", exc)


# ---------------------------------------------------------------------------
# BPM registrations
# ---------------------------------------------------------------------------

try:
	from pgappforge.plugins.workflow.engine import BPMActionRegistry as _BPMReg

	@_BPMReg.register("mes.ingest_telemetry")
	def _bpm_ingest(ctx: dict[str, Any]) -> dict[str, Any]:
		return {"action": "mes.ingest_telemetry", "params": ctx}

	@_BPMReg.register("mes.compute_oee")
	def _bpm_oee(ctx: dict[str, Any]) -> dict[str, Any]:
		return {"action": "mes.compute_oee", "params": ctx}

except (ImportError, Exception):
	log.debug("BPMActionRegistry not available — MES BPM actions not registered")


# ---------------------------------------------------------------------------
# MESService
# ---------------------------------------------------------------------------

class MESService:
	"""Service layer for Manufacturing Execution System operations."""

	def register_machine(
		self,
		machine_code: str,
		tenant_id: str,
		session: Any,
		*,
		work_center_id: str | None = None,
		opc_ua_endpoint: str | None = None,
		telemetry_schema: dict[str, Any] | None = None,
		downtime_threshold_minutes: int = 30,
		quality_threshold_pct: float = 95.0,
	) -> Any:
		"""Register a new machine in the MES.

		Emits MachineRegisteredEvent.
		"""
		from pgappforge.plugins.erp.platform.mes.models import MachineDefinition
		from pgappforge.plugins.erp.platform.mes.events import MachineRegisteredEvent

		machine = MachineDefinition(
			id=_uuid4(),
			tenant_id=tenant_id,
			machine_code=machine_code,
			work_center_id=work_center_id,
			opc_ua_endpoint=opc_ua_endpoint,
			telemetry_schema=telemetry_schema or {},
			downtime_threshold_minutes=downtime_threshold_minutes,
			quality_threshold_pct=Decimal(str(quality_threshold_pct)),
			is_active=True,
		)
		session.add(machine)
		session.flush()

		_emit(
			MachineRegisteredEvent(
				aggregate_id=machine.id,
				aggregate_type="MachineDefinition",
				tenant_id=tenant_id,
				machine_id=machine.id,
				machine_code=machine_code,
				work_center_id=work_center_id or "",
			),
			session,
		)
		log.info("MES: registered machine %r", machine_code)
		return machine

	def ingest_telemetry(
		self,
		machine_code: str,
		readings_dict: dict[str, Any],
		session: Any,
		*,
		production_order_id: str | None = None,
	) -> Any:
		"""Ingest a telemetry snapshot for a machine identified by machine_code.

		Checks configured thresholds and raises ProductionAlerts as needed.
		Emits TelemetryIngestedEvent; emits ProductionAlertRaisedEvent for each alert.
		"""
		from pgappforge.plugins.erp.platform.mes.models import (
			MachineDefinition, MachineReading, ProductionAlert,
		)
		from pgappforge.plugins.erp.platform.mes.events import (
			TelemetryIngestedEvent, ProductionAlertRaisedEvent,
		)

		machine = session.execute(
			sa.select(MachineDefinition).where(
				MachineDefinition.machine_code == machine_code,
			)
		).scalar_one_or_none()
		if machine is None:
			raise ValueError(f"Machine {machine_code!r} not found")

		reading = MachineReading(
			id=_uuid4(),
			tenant_id=machine.tenant_id,
			machine_id=machine.id,
			reading_at=_now(),
			readings=readings_dict,
			production_order_id=production_order_id,
		)
		session.add(reading)
		session.flush()

		_emit(
			TelemetryIngestedEvent(
				aggregate_id=machine.id,
				aggregate_type="MachineDefinition",
				tenant_id=machine.tenant_id,
				machine_id=machine.id,
				machine_code=machine_code,
				reading_id=reading.id,
			),
			session,
		)

		# Threshold checks
		self._check_quality_threshold(machine, readings_dict, session)
		self._check_downtime_threshold(machine, session)

		return reading

	def _check_quality_threshold(
		self,
		machine: Any,
		readings_dict: dict[str, Any],
		session: Any,
	) -> None:
		"""Raise a QUALITY alert if good_parts/total_parts < threshold."""
		from pgappforge.plugins.erp.platform.mes.models import ProductionAlert
		from pgappforge.plugins.erp.platform.mes.events import ProductionAlertRaisedEvent

		good = readings_dict.get("good_parts")
		total = readings_dict.get("total_parts")
		if good is None or total is None or total == 0:
			return

		quality_pct = Decimal(str(good)) / Decimal(str(total)) * 100
		threshold = Decimal(str(machine.quality_threshold_pct or 95))
		if quality_pct < threshold:
			alert = ProductionAlert(
				id=_uuid4(),
				tenant_id=machine.tenant_id,
				machine_id=machine.id,
				alert_type="QUALITY",
				severity="HIGH",
				started_at=_now(),
			)
			session.add(alert)
			session.flush()
			_emit(
				ProductionAlertRaisedEvent(
					aggregate_id=machine.id,
					aggregate_type="MachineDefinition",
					tenant_id=machine.tenant_id,
					alert_id=alert.id,
					machine_id=machine.id,
					alert_type="QUALITY",
					severity="HIGH",
				),
				session,
			)

	def _check_downtime_threshold(self, machine: Any, session: Any) -> None:
		"""Raise a DOWNTIME alert if no readings in the last threshold minutes."""
		from pgappforge.plugins.erp.platform.mes.models import MachineReading, ProductionAlert
		from pgappforge.plugins.erp.platform.mes.events import ProductionAlertRaisedEvent

		threshold_minutes = machine.downtime_threshold_minutes or 30
		cutoff = _now() - timedelta(minutes=threshold_minutes)

		recent = session.execute(
			sa.select(MachineReading.id)
			.where(
				MachineReading.machine_id == machine.id,
				MachineReading.reading_at >= cutoff,
			)
			.limit(1)
		).scalar_one_or_none()

		if recent is not None:
			return  # machine is reporting normally

		# Check if DOWNTIME alert already open
		open_alert = session.execute(
			sa.select(ProductionAlert.id).where(
				ProductionAlert.machine_id == machine.id,
				ProductionAlert.alert_type == "DOWNTIME",
				ProductionAlert.resolved_at.is_(None),
			)
		).scalar_one_or_none()
		if open_alert is not None:
			return

		alert = ProductionAlert(
			id=_uuid4(),
			tenant_id=machine.tenant_id,
			machine_id=machine.id,
			alert_type="DOWNTIME",
			severity="CRITICAL",
			started_at=_now(),
		)
		session.add(alert)
		session.flush()
		_emit(
			ProductionAlertRaisedEvent(
				aggregate_id=machine.id,
				aggregate_type="MachineDefinition",
				tenant_id=machine.tenant_id,
				alert_id=alert.id,
				machine_id=machine.id,
				alert_type="DOWNTIME",
				severity="CRITICAL",
			),
			session,
		)

	def get_oee(
		self,
		machine_id: str,
		target_date: date,
		session: Any,
	) -> dict[str, Any]:
		"""Compute Overall Equipment Effectiveness for a machine on a given date.

		OEE = Availability × Performance × Quality (all as 0-1 fractions).

		Derives from MachineReading rows for the date:
		  - Availability: fraction of hourly slots with at least one reading (24 slots)
		  - Performance: avg(speed_rpm / rated_speed_rpm) clamped to [0,1] if present
		  - Quality: avg(good_parts / total_parts) clamped to [0,1] if present

		Emits OEEComputedEvent.
		"""
		from pgappforge.plugins.erp.platform.mes.models import MachineDefinition, MachineReading
		from pgappforge.plugins.erp.platform.mes.events import OEEComputedEvent

		machine = session.execute(
			sa.select(MachineDefinition).where(MachineDefinition.id == machine_id)
		).scalar_one_or_none()
		if machine is None:
			raise ValueError(f"Machine {machine_id} not found")

		day_start = datetime.combine(target_date, datetime.min.time()).replace(tzinfo=timezone.utc)
		day_end = day_start + timedelta(days=1)

		readings = session.execute(
			sa.select(MachineReading)
			.where(
				MachineReading.machine_id == machine_id,
				MachineReading.reading_at >= day_start,
				MachineReading.reading_at < day_end,
			)
		).scalars().all()

		# Availability — fraction of 24 hourly slots with ≥1 reading
		slots_with_reading: set[int] = set()
		for r in readings:
			slots_with_reading.add(r.reading_at.hour)
		availability = len(slots_with_reading) / 24.0

		# Performance — avg speed ratio if present
		perf_values: list[float] = []
		quality_values: list[float] = []
		for r in readings:
			d = r.readings or {}
			if d.get("speed_rpm") and d.get("rated_speed_rpm"):
				perf_values.append(
					min(1.0, float(d["speed_rpm"]) / float(d["rated_speed_rpm"]))
				)
			if d.get("total_parts") and d["total_parts"] > 0:
				quality_values.append(
					min(1.0, float(d.get("good_parts", 0)) / float(d["total_parts"]))
				)

		performance = sum(perf_values) / len(perf_values) if perf_values else 1.0
		quality = sum(quality_values) / len(quality_values) if quality_values else 1.0

		oee = availability * performance * quality

		_emit(
			OEEComputedEvent(
				aggregate_id=machine_id,
				aggregate_type="MachineDefinition",
				tenant_id=machine.tenant_id,
				machine_id=machine_id,
				date=str(target_date),
				oee_pct=round(oee * 100, 2),
				availability_pct=round(availability * 100, 2),
				performance_pct=round(performance * 100, 2),
				quality_pct=round(quality * 100, 2),
			),
			session,
		)

		return {
			"machine_id": machine_id,
			"date": str(target_date),
			"oee_pct": round(oee * 100, 2),
			"availability_pct": round(availability * 100, 2),
			"performance_pct": round(performance * 100, 2),
			"quality_pct": round(quality * 100, 2),
			"readings_count": len(readings),
		}

	def link_to_production_order(
		self,
		machine_id: str,
		production_order_id: str,
		reading_id: str,
		session: Any,
	) -> Any:
		"""Link a MachineReading to a production order."""
		from pgappforge.plugins.erp.platform.mes.models import MachineReading

		reading = session.execute(
			sa.select(MachineReading).where(MachineReading.id == reading_id)
		).scalar_one_or_none()
		if reading is None:
			raise ValueError(f"MachineReading {reading_id} not found")
		reading.production_order_id = production_order_id
		session.flush()
		return reading

	def poll_opcua(self, machine_id: str, session: Any) -> dict[str, Any]:
		"""Poll an OPC-UA endpoint for live telemetry.

		Requires the `opcua` or `asyncua` package. Returns a stub if not installed.
		"""
		try:
			import opcua  # type: ignore  # noqa: F401
		except ImportError:
			try:
				import asyncua  # type: ignore  # noqa: F401
			except ImportError:
				log.debug(
					"MES: OPC-UA polling unavailable — "
					"install 'opcua' or 'asyncua' package to enable"
				)
				return {"status": "unavailable", "reason": "opcua package not installed"}

		from pgappforge.plugins.erp.platform.mes.models import MachineDefinition

		machine = session.execute(
			sa.select(MachineDefinition).where(MachineDefinition.id == machine_id)
		).scalar_one_or_none()
		if machine is None or not machine.opc_ua_endpoint:
			return {"status": "no_endpoint"}

		# Actual OPC-UA read would go here
		log.info("MES: OPC-UA poll for machine %s at %s", machine_id, machine.opc_ua_endpoint)
		return {"status": "not_implemented", "endpoint": machine.opc_ua_endpoint}
