"""
pgappforge/plugins/erp/hcm/personnel/events.py

Domain events for the HCM Personnel Administration plugin.

All monetary amounts are integer cents — never float.

Events emitted:
  hcm.personnel.employee.hired         — new employee record created
  hcm.personnel.employee.assigned      — position/org_unit assignment changed
  hcm.personnel.employee.transferred   — cross-entity/org move
  hcm.personnel.employee.terminated    — employment ended
  hcm.personnel.employee.rehired       — rehire of previous employee
  hcm.personnel.compensation.changed   — new EmployeeCompensation row inserted
  hcm.personnel.document.verified      — EmployeeDocument marked is_verified=True
  hcm.personnel.document.expiring      — document expiry < 30 days away

Events consumed:
  hcm.org.position.created             — can pre-load position catalog
"""
from __future__ import annotations

from dataclasses import dataclass

from pgappforge.plugins.erp.foundation.events import DomainEvent


# ---------------------------------------------------------------------------
# Employee lifecycle events
# ---------------------------------------------------------------------------

@dataclass
class EmployeeHiredEvent(DomainEvent):
	"""Emitted when a new employee record is created."""
	event_type: str = "hcm.personnel.employee.hired"
	employee_id: str = ""
	employee_number: str = ""
	entity_id: str = ""
	position_id: str = ""
	org_unit_id: str = ""
	employment_type: str = ""
	start_date: str = ""  # ISO date


@dataclass
class EmployeeAssignedEvent(DomainEvent):
	"""Emitted when an employee's position or org unit changes."""
	event_type: str = "hcm.personnel.employee.assigned"
	employee_id: str = ""
	old_position_id: str = ""
	new_position_id: str = ""
	old_org_unit_id: str = ""
	new_org_unit_id: str = ""
	effective_date: str = ""  # ISO date


@dataclass
class EmployeeTransferredEvent(DomainEvent):
	"""Emitted when an employee moves between legal entities."""
	event_type: str = "hcm.personnel.employee.transferred"
	employee_id: str = ""
	old_entity_id: str = ""
	new_entity_id: str = ""
	effective_date: str = ""  # ISO date


@dataclass
class EmployeeTerminatedEvent(DomainEvent):
	"""Emitted when employment ends."""
	event_type: str = "hcm.personnel.employee.terminated"
	employee_id: str = ""
	employee_number: str = ""
	entity_id: str = ""
	position_id: str = ""
	termination_date: str = ""  # ISO date
	termination_type: str = ""
	termination_reason: str = ""
	rehire_eligible: bool = True


@dataclass
class EmployeeRehiredEvent(DomainEvent):
	"""Emitted when a previously terminated employee is rehired."""
	event_type: str = "hcm.personnel.employee.rehired"
	employee_id: str = ""
	employee_number: str = ""
	entity_id: str = ""
	rehire_date: str = ""  # ISO date


# ---------------------------------------------------------------------------
# Compensation events
# ---------------------------------------------------------------------------

@dataclass
class CompensationChangedEvent(DomainEvent):
	"""Emitted when a new EmployeeCompensation row is inserted.

	amount_cents is always integer — never float.
	"""
	event_type: str = "hcm.personnel.compensation.changed"
	compensation_id: str = ""
	employee_id: str = ""
	effective_date: str = ""  # ISO date
	pay_type: str = ""
	amount_cents: int = 0
	currency_code: str = ""
	frequency: str = ""
	reason: str = ""


# ---------------------------------------------------------------------------
# Document events
# ---------------------------------------------------------------------------

@dataclass
class DocumentVerifiedEvent(DomainEvent):
	"""Emitted when an EmployeeDocument is marked is_verified=True."""
	event_type: str = "hcm.personnel.document.verified"
	document_id: str = ""
	employee_id: str = ""
	document_type: str = ""


@dataclass
class DocumentExpiringEvent(DomainEvent):
	"""Emitted when a document's expiry is within 30 days."""
	event_type: str = "hcm.personnel.document.expiring"
	document_id: str = ""
	employee_id: str = ""
	document_type: str = ""
	expiry_date: str = ""  # ISO date
	days_remaining: int = 0


__all__ = [
	"EmployeeHiredEvent",
	"EmployeeAssignedEvent",
	"EmployeeTransferredEvent",
	"EmployeeTerminatedEvent",
	"EmployeeRehiredEvent",
	"CompensationChangedEvent",
	"DocumentVerifiedEvent",
	"DocumentExpiringEvent",
]
