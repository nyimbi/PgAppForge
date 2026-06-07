from __future__ import annotations

from dataclasses import dataclass, field

from pgappforge.plugins.erp.foundation.events import DomainEvent

__all__ = [
	"ContingentWorkerOnboardedEvent",
	"SowCreatedEvent",
	"TimesheetApprovedEvent",
	"ContingentSpendEvent",
	"SowCompletedEvent",
]


@dataclass
class ContingentWorkerOnboardedEvent(DomainEvent):
	event_type: str = field(default="hcm.contingent.onboarded", init=False)
	worker_id: str = ""
	worker_type: str = ""
	agency_id: str = ""
	tenant_id: str = ""


@dataclass
class SowCreatedEvent(DomainEvent):
	event_type: str = field(default="hcm.contingent.sow.created", init=False)
	sow_id: str = ""
	worker_id: str = ""
	budget_cents: int = 0


@dataclass
class TimesheetApprovedEvent(DomainEvent):
	event_type: str = field(default="hcm.contingent.timesheet.approved", init=False)
	timesheet_id: str = ""
	worker_id: str = ""
	hours: str = ""
	period: str = ""


@dataclass
class ContingentSpendEvent(DomainEvent):
	event_type: str = field(default="hcm.contingent.spend.recorded", init=False)
	tenant_id: str = ""
	period: str = ""
	total_cents: int = 0


@dataclass
class SowCompletedEvent(DomainEvent):
	event_type: str = field(default="hcm.contingent.sow.completed", init=False)
	sow_id: str = ""
	actual_spend_cents: int = 0
	status: str = ""
