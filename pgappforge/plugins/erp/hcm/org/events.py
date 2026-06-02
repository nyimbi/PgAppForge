"""
pgappforge/plugins/erp/hcm/org/events.py

Domain events for the HCM Org Management plugin.

Events emitted:
  hcm.org.legal_entity.created
  hcm.org.legal_entity.deactivated
  hcm.org.unit.created
  hcm.org.unit.restructured       — parent_id or manager changed
  hcm.org.position.created
  hcm.org.position.filled         — is_filled → True (employee assigned)
  hcm.org.position.vacated        — is_filled → False (employee departed)
  hcm.org.job_catalog.created
  hcm.org.compensation_grade.published

Events consumed:
  hcm.personnel.employee.assigned  — to mark position as filled
  hcm.personnel.employee.terminated — to vacate position
"""
from __future__ import annotations

from dataclasses import dataclass

from pgappforge.plugins.erp.foundation.events import DomainEvent


# ---------------------------------------------------------------------------
# LegalEntity events
# ---------------------------------------------------------------------------

@dataclass
class LegalEntityCreatedEvent(DomainEvent):
	"""Emitted when a new LegalEntity is created."""
	event_type: str = "hcm.org.legal_entity.created"
	entity_id: str = ""
	entity_code: str = ""
	entity_name: str = ""
	country_code: str = ""
	payroll_currency: str = ""


@dataclass
class LegalEntityDeactivatedEvent(DomainEvent):
	"""Emitted when a LegalEntity is deactivated."""
	event_type: str = "hcm.org.legal_entity.deactivated"
	entity_id: str = ""
	entity_code: str = ""


# ---------------------------------------------------------------------------
# OrgUnit events
# ---------------------------------------------------------------------------

@dataclass
class OrgUnitCreatedEvent(DomainEvent):
	"""Emitted when a new OrgUnit is created."""
	event_type: str = "hcm.org.unit.created"
	org_unit_id: str = ""
	org_code: str = ""
	org_type: str = ""
	entity_id: str = ""
	parent_id: str = ""


@dataclass
class OrgUnitRestructuredEvent(DomainEvent):
	"""Emitted when an OrgUnit's parent or manager changes."""
	event_type: str = "hcm.org.unit.restructured"
	org_unit_id: str = ""
	old_parent_id: str = ""
	new_parent_id: str = ""
	old_manager_id: str = ""
	new_manager_id: str = ""


# ---------------------------------------------------------------------------
# Position events
# ---------------------------------------------------------------------------

@dataclass
class PositionCreatedEvent(DomainEvent):
	"""Emitted when a new Position is budgeted."""
	event_type: str = "hcm.org.position.created"
	position_id: str = ""
	position_code: str = ""
	org_unit_id: str = ""
	entity_id: str = ""
	employment_type: str = ""


@dataclass
class PositionFilledEvent(DomainEvent):
	"""Emitted when an employee is assigned to a position (is_filled → True)."""
	event_type: str = "hcm.org.position.filled"
	position_id: str = ""
	position_code: str = ""
	employee_id: str = ""


@dataclass
class PositionVacatedEvent(DomainEvent):
	"""Emitted when a position becomes vacant (is_filled → False)."""
	event_type: str = "hcm.org.position.vacated"
	position_id: str = ""
	position_code: str = ""
	vacated_by_employee_id: str = ""


# ---------------------------------------------------------------------------
# JobCatalog / CompensationGrade events
# ---------------------------------------------------------------------------

@dataclass
class JobCatalogCreatedEvent(DomainEvent):
	"""Emitted when a new job is added to the catalog."""
	event_type: str = "hcm.org.job_catalog.created"
	job_catalog_id: str = ""
	job_code: str = ""
	job_title: str = ""
	job_family: str = ""


@dataclass
class CompensationGradePublishedEvent(DomainEvent):
	"""Emitted when a new CompensationGrade band is published."""
	event_type: str = "hcm.org.compensation_grade.published"
	grade_id: str = ""
	grade_code: str = ""
	min_cents: int = 0
	mid_cents: int = 0
	max_cents: int = 0
	currency_code: str = ""
	effective_from: str = ""  # ISO date string


__all__ = [
	"LegalEntityCreatedEvent",
	"LegalEntityDeactivatedEvent",
	"OrgUnitCreatedEvent",
	"OrgUnitRestructuredEvent",
	"PositionCreatedEvent",
	"PositionFilledEvent",
	"PositionVacatedEvent",
	"JobCatalogCreatedEvent",
	"CompensationGradePublishedEvent",
]
