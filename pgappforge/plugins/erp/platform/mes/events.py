"""
pgappforge/plugins/erp/platform/mes/events.py

Domain events for the Manufacturing Execution System (MES) plugin.
"""
from __future__ import annotations

from dataclasses import dataclass

from pgappforge.plugins.erp.foundation.events import DomainEvent

__all__ = [
	"MachineRegisteredEvent",
	"TelemetryIngestedEvent",
	"ProductionAlertRaisedEvent",
	"OEEComputedEvent",
]


@dataclass
class MachineRegisteredEvent(DomainEvent):
	"""Emitted when a machine is registered in the MES."""
	event_type: str = "platform.mes.machine.registered"
	machine_id: str = ""
	machine_code: str = ""
	work_center_id: str = ""
	tenant_id: str = ""


@dataclass
class TelemetryIngestedEvent(DomainEvent):
	"""Emitted when telemetry readings are successfully ingested for a machine."""
	event_type: str = "platform.mes.telemetry.ingested"
	machine_id: str = ""
	machine_code: str = ""
	reading_id: str = ""
	tenant_id: str = ""


@dataclass
class ProductionAlertRaisedEvent(DomainEvent):
	"""Emitted when a production alert is triggered by threshold breach."""
	event_type: str = "platform.mes.alert.raised"
	alert_id: str = ""
	machine_id: str = ""
	alert_type: str = ""
	severity: str = ""
	tenant_id: str = ""


@dataclass
class OEEComputedEvent(DomainEvent):
	"""Emitted when Overall Equipment Effectiveness is computed for a machine."""
	event_type: str = "platform.mes.oee.computed"
	machine_id: str = ""
	date: str = ""
	oee_pct: float = 0.0
	availability_pct: float = 0.0
	performance_pct: float = 0.0
	quality_pct: float = 0.0
