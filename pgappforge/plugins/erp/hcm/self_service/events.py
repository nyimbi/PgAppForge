from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pgappforge.plugins.erp.foundation.events import DomainEvent

__all__ = [
	"LeaveRequestSubmittedEvent",
	"LeaveRequestApprovedEvent",
	"LeaveRequestRejectedEvent",
	"ProfileUpdateRequestedEvent",
	"ExpenseSubmittedEvent",
	"AnnouncementPublishedEvent",
]


@dataclass
class LeaveRequestSubmittedEvent(DomainEvent):
	event_type: str = "hcm.self_service.leave.submitted"
	request_id: str = ""
	employee_id: str = ""
	leave_type: str = ""
	start_date: str = ""
	end_date: str = ""
	days: float = 0.0

	def __post_init__(self) -> None:
		if not self.request_id:
			raise ValueError("request_id is required")
		if not self.employee_id:
			raise ValueError("employee_id is required")
		if not self.leave_type:
			raise ValueError("leave_type is required")
		if not self.start_date:
			raise ValueError("start_date is required")
		if not self.end_date:
			raise ValueError("end_date is required")
		if self.days <= 0:
			raise ValueError("days must be positive")


@dataclass
class LeaveRequestApprovedEvent(DomainEvent):
	event_type: str = "hcm.self_service.leave.approved"
	request_id: str = ""
	employee_id: str = ""
	approved_by: str = ""

	def __post_init__(self) -> None:
		if not self.request_id:
			raise ValueError("request_id is required")
		if not self.employee_id:
			raise ValueError("employee_id is required")
		if not self.approved_by:
			raise ValueError("approved_by is required")


@dataclass
class LeaveRequestRejectedEvent(DomainEvent):
	event_type: str = "hcm.self_service.leave.rejected"
	request_id: str = ""
	employee_id: str = ""
	rejected_by: str = ""
	reason: str = ""

	def __post_init__(self) -> None:
		if not self.request_id:
			raise ValueError("request_id is required")
		if not self.employee_id:
			raise ValueError("employee_id is required")
		if not self.rejected_by:
			raise ValueError("rejected_by is required")


@dataclass
class ProfileUpdateRequestedEvent(DomainEvent):
	event_type: str = "hcm.self_service.profile.update_requested"
	request_id: str = ""
	employee_id: str = ""
	fields_changed: list[str] = field(default_factory=list)

	def __post_init__(self) -> None:
		if not self.request_id:
			raise ValueError("request_id is required")
		if not self.employee_id:
			raise ValueError("employee_id is required")


@dataclass
class ExpenseSubmittedEvent(DomainEvent):
	event_type: str = "hcm.self_service.expense.submitted"
	request_id: str = ""
	employee_id: str = ""
	total_cents: int = 0

	def __post_init__(self) -> None:
		if not self.request_id:
			raise ValueError("request_id is required")
		if not self.employee_id:
			raise ValueError("employee_id is required")
		if self.total_cents < 0:
			raise ValueError("total_cents must be non-negative")


@dataclass
class AnnouncementPublishedEvent(DomainEvent):
	event_type: str = "hcm.self_service.announcement.published"
	announcement_id: str = ""
	title: str = ""
	audience_roles: list[str] = field(default_factory=list)

	def __post_init__(self) -> None:
		if not self.announcement_id:
			raise ValueError("announcement_id is required")
		if not self.title:
			raise ValueError("title is required")
