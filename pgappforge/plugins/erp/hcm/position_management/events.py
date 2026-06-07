"""
pgappforge/plugins/erp/hcm/position_management/events.py

Domain events for the HCM Position Management plugin.

Events emitted:
  hcm.positions.created              — new position approved and created
  hcm.positions.filled               — position assigned to an employee
  hcm.positions.vacated              — position vacated (resignation / termination / transfer)
  hcm.positions.headcount.variance   — actual headcount deviates from budget
"""
from __future__ import annotations

from dataclasses import dataclass

from pgappforge.plugins.erp.foundation.events import DomainEvent


@dataclass
class PositionCreatedEvent(DomainEvent):
	"""Emitted when a new organisational position is created."""
	event_type: str = "hcm.positions.created"
	position_id: str = ""
	position_code: str = ""
	entity_id: str = ""
	tenant_id: str = ""


@dataclass
class PositionFilledEvent(DomainEvent):
	"""Emitted when a position is assigned to an employee."""
	event_type: str = "hcm.positions.filled"
	position_id: str = ""
	employee_id: str = ""
	previous_incumbent: str = ""


@dataclass
class PositionVacatedEvent(DomainEvent):
	"""Emitted when a position becomes vacant."""
	event_type: str = "hcm.positions.vacated"
	position_id: str = ""
	vacated_by: str = ""
	trigger: str = ""   # RESIGNATION | TERMINATION | TRANSFER


@dataclass
class HeadcountVarianceAlertEvent(DomainEvent):
	"""Emitted when actual headcount diverges from the budgeted FTE."""
	event_type: str = "hcm.positions.headcount.variance"
	entity_id: str = ""
	budgeted: float = 0.0
	actual: int = 0
	variance: float = 0.0


__all__ = [
	"PositionCreatedEvent",
	"PositionFilledEvent",
	"PositionVacatedEvent",
	"HeadcountVarianceAlertEvent",
]
