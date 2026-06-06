from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pgappforge.plugins.erp.foundation.events import DomainEvent

__all__ = [
	"WellnessProgramEnrolledEvent",
	"WellnessCheckInEvent",
	"EapReferralCreatedEvent",
	"WellnessReportGeneratedEvent",
]


@dataclass
class WellnessProgramEnrolledEvent(DomainEvent):
	event_type: str = field(default="hcm.wellness.enrolled", init=False)
	enrollment_id: str = ""
	employee_id: str = ""
	program_id: str = ""


@dataclass
class WellnessCheckInEvent(DomainEvent):
	event_type: str = field(default="hcm.wellness.checkin", init=False)
	checkin_id: str = ""
	employee_id: str = ""
	wellbeing_score: int = 0
	flags: list[str] = field(default_factory=list)


@dataclass
class EapReferralCreatedEvent(DomainEvent):
	event_type: str = field(default="hcm.wellness.eap.referral", init=False)
	referral_id: str = ""
	employee_id: str = ""
	category: str = ""


@dataclass
class WellnessReportGeneratedEvent(DomainEvent):
	event_type: str = field(default="hcm.wellness.report.generated", init=False)
	tenant_id: str = ""
	period: str = ""  # e.g. "2025-Q1" or "2025-05"
	summary: dict[str, Any] = field(default_factory=dict)
