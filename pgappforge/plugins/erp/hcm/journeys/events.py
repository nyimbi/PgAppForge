"""
pgappforge/plugins/erp/hcm/journeys/events.py

Domain events for the HCM Employee Journeys plugin.

Events emitted:
  hcm.journeys.started          — employee journey started (onboarding / offboarding / etc.)
  hcm.journeys.task.completed   — journey task completed
  hcm.journeys.task.skipped     — journey task skipped
  hcm.journeys.completed        — all mandatory tasks done; journey complete
  hcm.journeys.overdue          — a journey task has passed its due date

Events consumed:
  hcm.employee.hired            — triggers ONBOARDING journey
  hcm.employee.terminated       — triggers OFFBOARDING journey
"""
from __future__ import annotations

from dataclasses import dataclass

from pgappforge.plugins.erp.foundation.events import DomainEvent


# ---------------------------------------------------------------------------
# Journey lifecycle events
# ---------------------------------------------------------------------------

@dataclass
class JourneyStartedEvent(DomainEvent):
	"""Emitted when an employee journey is started."""
	event_type: str = "hcm.journeys.started"
	journey_id: str = ""
	employee_id: str = ""
	journey_type: str = ""       # ONBOARDING | OFFBOARDING | TRANSFER | ROLE_CHANGE | PROMOTION


@dataclass
class JourneyTaskCompletedEvent(DomainEvent):
	"""Emitted when a journey task is marked complete."""
	event_type: str = "hcm.journeys.task.completed"
	task_id: str = ""
	journey_id: str = ""
	task_code: str = ""
	completed_by: str = ""


@dataclass
class JourneyTaskSkippedEvent(DomainEvent):
	"""Emitted when a non-mandatory journey task is skipped."""
	event_type: str = "hcm.journeys.task.skipped"
	task_id: str = ""
	journey_id: str = ""
	task_code: str = ""
	reason: str = ""


@dataclass
class JourneyCompletedEvent(DomainEvent):
	"""Emitted when all mandatory tasks are complete and the journey closes."""
	event_type: str = "hcm.journeys.completed"
	journey_id: str = ""
	employee_id: str = ""
	journey_type: str = ""
	duration_days: int = 0


@dataclass
class JourneyOverdueTaskEvent(DomainEvent):
	"""Emitted when a journey task is past its due date."""
	event_type: str = "hcm.journeys.overdue"
	task_id: str = ""
	journey_id: str = ""
	task_code: str = ""
	days_overdue: int = 0


__all__ = [
	"JourneyStartedEvent",
	"JourneyTaskCompletedEvent",
	"JourneyTaskSkippedEvent",
	"JourneyCompletedEvent",
	"JourneyOverdueTaskEvent",
]
