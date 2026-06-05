"""
pgappforge/plugins/erp/hcm/personnel/events.py

Domain events for the HCM Personnel Administration plugin.

All monetary amounts are integer cents — never float.

Events emitted:
  hcm.personnel.employee.hired              — new employee record created
  hcm.personnel.employee.assigned           — position/org_unit assignment changed
  hcm.personnel.employee.transferred        — cross-entity/org move
  hcm.personnel.employee.terminated         — employment ended
  hcm.personnel.employee.rehired            — rehire of previous employee
  hcm.personnel.employee.probation_confirmed — probation confirmed/extended/failed
  hcm.personnel.employee.on_leave           — employee placed on leave
  hcm.personnel.employee.returned_from_leave — employee returned from leave
  hcm.personnel.employee.entitlements_init  — leave entitlement seeding on hire
  hcm.personnel.employee.background_check   — background check status updated
  hcm.personnel.contract.issued             — contract offered to employee
  hcm.personnel.contract.accepted           — employee accepted contract
  hcm.personnel.contract.confirmed          — probation confirmed, contract activated
  hcm.personnel.contract.terminated         — contract terminated
  hcm.personnel.compensation.changed        — new EmployeeCompensation row inserted
  hcm.personnel.compensation.approved       — compensation record approved
  hcm.personnel.document.verified           — EmployeeDocument marked is_verified=True
  hcm.personnel.document.expiring           — document expiry < 30 days away
  hcm.personnel.disciplinary.case_opened    — disciplinary case opened
  hcm.personnel.disciplinary.outcome_recorded — hearing outcome recorded
  hcm.personnel.grievance.filed             — grievance filed by employee
  hcm.personnel.grievance.resolved          — grievance resolved
  hcm.personnel.grievance.escalated         — grievance escalated
  hcm.personnel.onboarding.completed        — all onboarding tasks done
  hcm.personnel.exit.initiated              — exit/offboarding initiated
  hcm.personnel.exit.cleared                — all clearance items cleared
  hcm.personnel.exit.closed                 — exit record closed, final settlement done

Events consumed:
  hcm.org.position.created             — can pre-load position catalog
"""
from __future__ import annotations

from dataclasses import dataclass, field

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
	prior_employee_id: str = ""
	prior_service_years: float = 0.0


@dataclass
class ProbationConfirmedEvent(DomainEvent):
	"""Emitted when probation outcome is recorded (confirmed, extended, or failed)."""
	event_type: str = "hcm.personnel.employee.probation_confirmed"
	employee_id: str = ""
	employee_number: str = ""
	outcome: str = ""  # CONFIRMED | EXTENDED | FAILED
	new_probation_end_date: str = ""  # ISO date, set on extension
	confirmed_date: str = ""  # ISO date


@dataclass
class EmployeeOnLeaveEvent(DomainEvent):
	"""Emitted when employee status transitions to ON_LEAVE."""
	event_type: str = "hcm.personnel.employee.on_leave"
	employee_id: str = ""
	leave_type: str = ""
	start_date: str = ""  # ISO date
	expected_return_date: str = ""  # ISO date


@dataclass
class EmployeeReturnedFromLeaveEvent(DomainEvent):
	"""Emitted when employee returns from leave."""
	event_type: str = "hcm.personnel.employee.returned_from_leave"
	employee_id: str = ""
	actual_return_date: str = ""  # ISO date


@dataclass
class EmployeeEntitlementsInitEvent(DomainEvent):
	"""Emitted on hire so leave plugin can seed statutory balances.

	Kenya Employment Act ss.28-30:
	  annual_leave_days = 21
	  maternity_leave_days = 90
	  paternity_leave_days = 14
	"""
	event_type: str = "hcm.personnel.employee.entitlements_init"
	employee_id: str = ""
	employee_number: str = ""
	entity_id: str = ""
	start_date: str = ""  # ISO date
	employment_type: str = ""
	annual_leave_days: int = 21
	maternity_leave_days: int = 90
	paternity_leave_days: int = 14


@dataclass
class BackgroundCheckUpdatedEvent(DomainEvent):
	"""Emitted when background check status is updated."""
	event_type: str = "hcm.personnel.employee.background_check"
	employee_id: str = ""
	status: str = ""  # NOT_REQUIRED | PENDING | PASSED | FAILED | WAIVED
	provider_ref: str = ""


# ---------------------------------------------------------------------------
# Contract events
# ---------------------------------------------------------------------------

@dataclass
class ContractIssuedEvent(DomainEvent):
	"""Emitted when a contract is offered to an employee."""
	event_type: str = "hcm.personnel.contract.issued"
	contract_id: str = ""
	employee_id: str = ""
	contract_type: str = ""
	offer_date: str = ""  # ISO date


@dataclass
class ContractAcceptedEvent(DomainEvent):
	"""Emitted when an employee accepts their contract."""
	event_type: str = "hcm.personnel.contract.accepted"
	contract_id: str = ""
	employee_id: str = ""
	accepted_date: str = ""  # ISO date


@dataclass
class ContractConfirmedEvent(DomainEvent):
	"""Emitted when probation is confirmed and contract activated."""
	event_type: str = "hcm.personnel.contract.confirmed"
	contract_id: str = ""
	employee_id: str = ""
	confirmed_date: str = ""  # ISO date


@dataclass
class ContractTerminatedEvent(DomainEvent):
	"""Emitted when a contract is terminated."""
	event_type: str = "hcm.personnel.contract.terminated"
	contract_id: str = ""
	employee_id: str = ""
	terminated_date: str = ""  # ISO date


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


@dataclass
class CompensationApprovedEvent(DomainEvent):
	"""Emitted when a pending compensation record is approved."""
	event_type: str = "hcm.personnel.compensation.approved"
	compensation_id: str = ""
	employee_id: str = ""
	approved_by: str = ""
	amount_cents: int = 0


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


# ---------------------------------------------------------------------------
# Disciplinary events
# ---------------------------------------------------------------------------

@dataclass
class DisciplinaryCaseOpenedEvent(DomainEvent):
	"""Emitted when a disciplinary case is opened."""
	event_type: str = "hcm.personnel.disciplinary.case_opened"
	case_id: str = ""
	case_number: str = ""
	employee_id: str = ""
	case_type: str = ""


@dataclass
class DisciplinaryOutcomeRecordedEvent(DomainEvent):
	"""Emitted when a hearing outcome is recorded."""
	event_type: str = "hcm.personnel.disciplinary.outcome_recorded"
	case_id: str = ""
	employee_id: str = ""
	outcome: str = ""
	outcome_date: str = ""  # ISO date


# ---------------------------------------------------------------------------
# Grievance events
# ---------------------------------------------------------------------------

@dataclass
class GrievanceFiledEvent(DomainEvent):
	"""Emitted when a grievance is filed."""
	event_type: str = "hcm.personnel.grievance.filed"
	case_id: str = ""
	case_number: str = ""
	employee_id: str = ""
	grievance_type: str = ""
	filed_date: str = ""  # ISO date


@dataclass
class GrievanceResolvedEvent(DomainEvent):
	"""Emitted when a grievance is resolved."""
	event_type: str = "hcm.personnel.grievance.resolved"
	case_id: str = ""
	employee_id: str = ""
	resolved_date: str = ""  # ISO date


@dataclass
class GrievanceEscalatedEvent(DomainEvent):
	"""Emitted when a grievance is escalated."""
	event_type: str = "hcm.personnel.grievance.escalated"
	case_id: str = ""
	employee_id: str = ""
	escalated_to_id: str = ""


# ---------------------------------------------------------------------------
# Onboarding events
# ---------------------------------------------------------------------------

@dataclass
class OnboardingCompletedEvent(DomainEvent):
	"""Emitted when all onboarding checklist items are completed."""
	event_type: str = "hcm.personnel.onboarding.completed"
	plan_id: str = ""
	employee_id: str = ""
	completed_date: str = ""  # ISO date


# ---------------------------------------------------------------------------
# Exit events
# ---------------------------------------------------------------------------

@dataclass
class ExitInitiatedEvent(DomainEvent):
	"""Emitted when an exit record is created."""
	event_type: str = "hcm.personnel.exit.initiated"
	exit_id: str = ""
	employee_id: str = ""
	exit_type: str = ""
	last_working_day: str = ""  # ISO date


@dataclass
class ExitClearedEvent(DomainEvent):
	"""Emitted when all clearance items are cleared."""
	event_type: str = "hcm.personnel.exit.cleared"
	exit_id: str = ""
	employee_id: str = ""
	cleared_date: str = ""  # ISO date


@dataclass
class ExitClosedEvent(DomainEvent):
	"""Emitted when exit is closed and final settlement processed."""
	event_type: str = "hcm.personnel.exit.closed"
	exit_id: str = ""
	employee_id: str = ""
	final_settlement_amount_cents: int = 0
	closed_date: str = ""  # ISO date


__all__ = [
	# Employee lifecycle
	"EmployeeHiredEvent",
	"EmployeeAssignedEvent",
	"EmployeeTransferredEvent",
	"EmployeeTerminatedEvent",
	"EmployeeRehiredEvent",
	"ProbationConfirmedEvent",
	"EmployeeOnLeaveEvent",
	"EmployeeReturnedFromLeaveEvent",
	"EmployeeEntitlementsInitEvent",
	"BackgroundCheckUpdatedEvent",
	# Contract
	"ContractIssuedEvent",
	"ContractAcceptedEvent",
	"ContractConfirmedEvent",
	"ContractTerminatedEvent",
	# Compensation
	"CompensationChangedEvent",
	"CompensationApprovedEvent",
	# Documents
	"DocumentVerifiedEvent",
	"DocumentExpiringEvent",
	# Disciplinary
	"DisciplinaryCaseOpenedEvent",
	"DisciplinaryOutcomeRecordedEvent",
	# Grievance
	"GrievanceFiledEvent",
	"GrievanceResolvedEvent",
	"GrievanceEscalatedEvent",
	# Onboarding
	"OnboardingCompletedEvent",
	# Exit
	"ExitInitiatedEvent",
	"ExitClearedEvent",
	"ExitClosedEvent",
]
