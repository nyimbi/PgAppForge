from __future__ import annotations

from dataclasses import dataclass

from pgappforge.plugins.erp.foundation.events import DomainEvent

__all__ = [
	"SurveyPublishedEvent",
	"SurveyResponseSubmittedEvent",
	"SurveyClosedEvent",
	"SurveyAnalysisGeneratedEvent",
]


@dataclass
class SurveyPublishedEvent(DomainEvent):
	event_type: str = "platform.surveys.published"
	survey_id: str = ""
	title: str = ""
	tenant_id: str = ""


@dataclass
class SurveyResponseSubmittedEvent(DomainEvent):
	event_type: str = "platform.surveys.response.submitted"
	response_id: str = ""
	survey_id: str = ""
	respondent_id: str = ""


@dataclass
class SurveyClosedEvent(DomainEvent):
	event_type: str = "platform.surveys.closed"
	survey_id: str = ""
	response_count: int = 0


@dataclass
class SurveyAnalysisGeneratedEvent(DomainEvent):
	event_type: str = "platform.surveys.analysis.generated"
	survey_id: str = ""
	nps_score: float | None = None
