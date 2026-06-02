"""
pgappforge/plugins/erp/crm/service/events.py

Domain events for the Service Cloud plugin.

All events extend DomainEvent from foundation.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from pgappforge.plugins.erp.foundation.events import DomainEvent


@dataclass
class CaseCreatedEvent(DomainEvent):
	"""Emitted when a new support case is opened."""
	event_type: str = "service.case.created"
	case_id: str = ""
	case_number: str = ""
	account_id: str = ""
	contact_id: str = ""
	priority: str = ""
	channel: str = ""
	owner_id: str = ""


@dataclass
class CaseEscalatedEvent(DomainEvent):
	"""Emitted when a case is escalated (status → ESCALATED)."""
	event_type: str = "service.case.escalated"
	case_id: str = ""
	case_number: str = ""
	escalated_to: str = ""
	priority: str = ""
	sla_breach_at: str = ""  # ISO datetime


@dataclass
class CaseResolvedEvent(DomainEvent):
	"""Emitted when a case transitions to RESOLVED."""
	event_type: str = "service.case.resolved"
	case_id: str = ""
	case_number: str = ""
	owner_id: str = ""
	resolved_at: str = ""  # ISO datetime
	resolution_minutes: int = 0


@dataclass
class CaseClosedEvent(DomainEvent):
	"""Emitted when a resolved case is closed (RESOLVED → CLOSED)."""
	event_type: str = "service.case.closed"
	case_id: str = ""
	case_number: str = ""
	csat_score: int = 0


@dataclass
class SLABreachedEvent(DomainEvent):
	"""Emitted when a case passes its sla_breach_at without resolution."""
	event_type: str = "service.sla.breached"
	case_id: str = ""
	case_number: str = ""
	priority: str = ""
	breached_at: str = ""  # ISO datetime
	owner_id: str = ""


@dataclass
class SurveySubmittedEvent(DomainEvent):
	"""Emitted when a CSAT/NPS/CES survey response is recorded."""
	event_type: str = "service.survey.submitted"
	survey_response_id: str = ""
	case_id: str = ""
	contact_id: str = ""
	survey_type: str = ""
	score: int = 0


@dataclass
class KnowledgeArticlePublishedEvent(DomainEvent):
	"""Emitted when a knowledge article moves to PUBLISHED status."""
	event_type: str = "service.knowledge.published"
	article_id: str = ""
	title: str = ""
	category: str = ""
	author_id: str = ""


__all__ = [
	"CaseCreatedEvent",
	"CaseEscalatedEvent",
	"CaseResolvedEvent",
	"CaseClosedEvent",
	"SLABreachedEvent",
	"SurveySubmittedEvent",
	"KnowledgeArticlePublishedEvent",
]
