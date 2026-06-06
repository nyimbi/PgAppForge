from __future__ import annotations

from dataclasses import dataclass, field

from pgappforge.plugins.erp.foundation.events import DomainEvent

__all__ = [
	"BenefitEnrolledEvent",
	"BenefitTerminatedEvent",
	"BenefitClaimSubmittedEvent",
	"BenefitClaimAdjudicatedEvent",
	"BenefitDeductionsGeneratedEvent",
	"OpenEnrollmentOpenedEvent",
]


@dataclass
class BenefitEnrolledEvent(DomainEvent):
	event_type: str = field(default="hcm.benefits.enrolled", init=False)
	enrollment_id: str = ""
	employee_id: str = ""
	plan_id: str = ""
	tenant_id: str = ""
	effective_date: str = ""  # ISO date string


@dataclass
class BenefitTerminatedEvent(DomainEvent):
	event_type: str = field(default="hcm.benefits.terminated", init=False)
	enrollment_id: str = ""
	employee_id: str = ""
	reason: str = ""
	termination_date: str = ""  # ISO date string


@dataclass
class BenefitClaimSubmittedEvent(DomainEvent):
	event_type: str = field(default="hcm.benefits.claim.submitted", init=False)
	claim_id: str = ""
	enrollment_id: str = ""
	employee_id: str = ""
	claimed_amount_cents: int = 0


@dataclass
class BenefitClaimAdjudicatedEvent(DomainEvent):
	event_type: str = field(default="hcm.benefits.claim.adjudicated", init=False)
	claim_id: str = ""
	decision: str = ""
	approved_amount_cents: int | None = None
	adjudicator_id: str = ""


@dataclass
class BenefitDeductionsGeneratedEvent(DomainEvent):
	event_type: str = field(default="hcm.benefits.deductions.generated", init=False)
	payrun_id: str = ""
	period: str = ""
	count: int = 0
	total_cents: int = 0


@dataclass
class OpenEnrollmentOpenedEvent(DomainEvent):
	event_type: str = field(default="hcm.benefits.open_enrollment.opened", init=False)
	window_id: str = ""
	start_date: str = ""  # ISO date string
	end_date: str = ""    # ISO date string
