from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from pgappforge.plugins.erp.foundation.events import DomainEvent

__all__ = [
	"CompensationPackageCreatedEvent",
	"CompensationPackageRevisedEvent",
	"AllowanceAssignedEvent",
	"AllowanceRevokedEvent",
	"DeductionAssignedEvent",
	"ReviewCycleApprovedEvent",
]


@dataclass
class CompensationPackageCreatedEvent(DomainEvent):
	event_type: str = field(default="hcm.compensation.package.created", init=False)
	employee_id: str = ""
	package_id: str = ""
	base_salary_cents: int = 0
	currency_code: str = "KES"
	effective_from: date | None = None


@dataclass
class CompensationPackageRevisedEvent(DomainEvent):
	event_type: str = field(default="hcm.compensation.package.revised", init=False)
	employee_id: str = ""
	package_id: str = ""
	old_salary_cents: int = 0
	new_salary_cents: int = 0
	change_reason: str = ""


@dataclass
class AllowanceAssignedEvent(DomainEvent):
	event_type: str = field(default="hcm.compensation.allowance.assigned", init=False)
	employee_id: str = ""
	allowance_def_id: str = ""
	amount_cents: int = 0


@dataclass
class AllowanceRevokedEvent(DomainEvent):
	event_type: str = field(default="hcm.compensation.allowance.revoked", init=False)
	employee_id: str = ""
	employee_allowance_id: str = ""
	effective_to: date | None = None


@dataclass
class DeductionAssignedEvent(DomainEvent):
	event_type: str = field(default="hcm.compensation.deduction.assigned", init=False)
	employee_id: str = ""
	deduction_def_id: str = ""
	amount_cents: int = 0


@dataclass
class ReviewCycleApprovedEvent(DomainEvent):
	event_type: str = field(default="hcm.compensation.review.approved", init=False)
	cycle_id: str = ""
	approver_id: str = ""
	committed_cents: int = 0
