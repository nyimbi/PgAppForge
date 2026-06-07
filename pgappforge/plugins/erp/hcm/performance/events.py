"""
pgappforge/plugins/erp/hcm/performance/events.py

Domain events for the HCM Performance Review plugin.

Events emitted:
  hcm.performance.cycle.started    — review cycle activated
  hcm.performance.review.submitted — individual review submitted
  hcm.performance.goal.created     — goal / OKR created
  hcm.performance.goal.progress    — goal progress updated
  hcm.performance.feedback.given   — continuous feedback submitted
"""
from __future__ import annotations

from dataclasses import dataclass, field

from pgappforge.plugins.erp.foundation.events import DomainEvent


@dataclass
class PerformanceCycleStartedEvent(DomainEvent):
	"""Emitted when a performance review cycle is activated."""
	event_type: str = "hcm.performance.cycle.started"
	cycle_id: str = ""
	cycle_type: str = ""
	tenant_id: str = ""


@dataclass
class ReviewSubmittedEvent(DomainEvent):
	"""Emitted when an individual performance review is submitted."""
	event_type: str = "hcm.performance.review.submitted"
	review_id: str = ""
	employee_id: str = ""
	reviewer_id: str = ""
	review_type: str = ""
	rating: float = 0.0


@dataclass
class GoalCreatedEvent(DomainEvent):
	"""Emitted when a goal or OKR is created for an employee."""
	event_type: str = "hcm.performance.goal.created"
	goal_id: str = ""
	employee_id: str = ""
	type: str = ""
	period: str = ""


@dataclass
class GoalProgressUpdatedEvent(DomainEvent):
	"""Emitted when progress on a goal is recorded."""
	event_type: str = "hcm.performance.goal.progress"
	goal_id: str = ""
	employee_id: str = ""
	progress_pct: float = 0.0


@dataclass
class FeedbackGivenEvent(DomainEvent):
	"""Emitted when continuous feedback is submitted."""
	event_type: str = "hcm.performance.feedback.given"
	from_id: str = ""
	to_id: str = ""
	tags: list[str] = field(default_factory=list)


__all__ = [
	"PerformanceCycleStartedEvent",
	"ReviewSubmittedEvent",
	"GoalCreatedEvent",
	"GoalProgressUpdatedEvent",
	"FeedbackGivenEvent",
]
