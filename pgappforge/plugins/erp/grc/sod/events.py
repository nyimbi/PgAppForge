"""
pgappforge/plugins/erp/grc/sod/events.py

SoD Analyzer domain events.

Events emitted:
  grc.sod.violation.detected   — user holds conflicting roles
  grc.sod.risk.accepted        — violation acknowledged with mitigating control
  grc.sod.bulk_scan.completed  — tenant-wide scan finished
  grc.sod.simulation.run       — hypothetical role-grant checked
"""
from __future__ import annotations

from dataclasses import dataclass, field

from pgappforge.plugins.erp.foundation.events import DomainEvent


@dataclass
class SodViolationDetectedEvent(DomainEvent):
	event_type: str = "grc.sod.violation.detected"
	violation_id: str = ""
	user_id: str = ""
	conflict_name: str = ""
	risk_level: str = ""


@dataclass
class SodRiskAcceptedEvent(DomainEvent):
	event_type: str = "grc.sod.risk.accepted"
	violation_id: str = ""
	accepted_by: str = ""
	mitigating_control: str = ""


@dataclass
class SodBulkScanCompletedEvent(DomainEvent):
	event_type: str = "grc.sod.bulk_scan.completed"
	violations_found: int = 0
	users_scanned: int = 0


@dataclass
class SodSimulationRunEvent(DomainEvent):
	event_type: str = "grc.sod.simulation.run"
	user_id: str = ""
	new_role: str = ""
	would_create_violations: list = field(default_factory=list)


__all__ = [
	"SodViolationDetectedEvent",
	"SodRiskAcceptedEvent",
	"SodBulkScanCompletedEvent",
	"SodSimulationRunEvent",
]
