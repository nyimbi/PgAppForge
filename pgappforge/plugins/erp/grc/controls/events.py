"""
pgappforge/plugins/erp/grc/controls/events.py

GRC Controls plugin domain events.

Events emitted:
  grc.control.created
  grc.control.status_changed
  grc.control_test.completed
  grc.control_test.deficiency_noted
  grc.sod.conflict_detected

Events consumed:
  identity.policy.changed   — trigger SoD re-evaluation on role change
  party.created             — pre-populate control ownership candidates
"""
from __future__ import annotations

from dataclasses import dataclass, field

from pgappforge.plugins.erp.foundation.events import DomainEvent


@dataclass
class ControlCreatedEvent(DomainEvent):
	event_type: str = "grc.control.created"
	control_id: str = ""
	control_code: str = ""
	framework_id: str = ""
	control_type: str = ""
	frequency: str = ""


@dataclass
class ControlStatusChangedEvent(DomainEvent):
	event_type: str = "grc.control.status_changed"
	control_id: str = ""
	control_code: str = ""
	old_status: str = ""
	new_status: str = ""


@dataclass
class ControlTestCompletedEvent(DomainEvent):
	event_type: str = "grc.control_test.completed"
	test_id: str = ""
	control_id: str = ""
	control_code: str = ""
	test_date: str = ""
	test_result: str = ""  # EFFECTIVE | INEFFECTIVE | NOT_TESTED


@dataclass
class ControlDeficiencyNotedEvent(DomainEvent):
	event_type: str = "grc.control_test.deficiency_noted"
	test_id: str = ""
	control_id: str = ""
	control_code: str = ""
	deficiency_summary: str = ""
	remediation_due: str = ""


@dataclass
class SoDConflictDetectedEvent(DomainEvent):
	event_type: str = "grc.sod.conflict_detected"
	user_id: int = 0
	role_a: str = ""
	role_b: str = ""
	risk_level: str = ""
	conflict_type: str = ""


__all__ = [
	"ControlCreatedEvent",
	"ControlStatusChangedEvent",
	"ControlTestCompletedEvent",
	"ControlDeficiencyNotedEvent",
	"SoDConflictDetectedEvent",
]
