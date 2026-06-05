"""
pgappforge/plugins/erp/platform/education_platform/events.py

Education Platform plugin domain events.

Events emitted:
  education.lms_tool.registered
  education.learner_activity.started
  education.learner_activity.completed
  education.credential.issued
  education.credential.revoked
  education.learning_path.assigned
"""
from __future__ import annotations

from dataclasses import dataclass, field

from pgappforge.plugins.erp.foundation.events import DomainEvent


@dataclass
class LMSToolRegisteredEvent(DomainEvent):
	event_type: str = "education.lms_tool.registered"
	tool_id: str = ""
	tool_name: str = ""
	tool_type: str = ""
	launch_url: str = ""


@dataclass
class LearnerActivityStartedEvent(DomainEvent):
	event_type: str = "education.learner_activity.started"
	activity_id: str = ""
	learner_id: str = ""
	lo_id: str = ""
	started_at: str = ""


@dataclass
class LearnerActivityCompletedEvent(DomainEvent):
	event_type: str = "education.learner_activity.completed"
	activity_id: str = ""
	learner_id: str = ""
	lo_id: str = ""
	score: float = 0.0
	passed: bool = False
	time_spent_seconds: int = 0


@dataclass
class CredentialIssuedEvent(DomainEvent):
	event_type: str = "education.credential.issued"
	issued_credential_id: str = ""
	credential_id: str = ""
	recipient_id: str = ""
	verification_url: str = ""
	issued_at: str = ""


@dataclass
class CredentialRevokedEvent(DomainEvent):
	event_type: str = "education.credential.revoked"
	issued_credential_id: str = ""
	credential_id: str = ""
	recipient_id: str = ""
	revocation_reason: str = ""


@dataclass
class LearningPathAssignedEvent(DomainEvent):
	event_type: str = "education.learning_path.assigned"
	path_id: str = ""
	learner_id: str = ""
	assigned_by: str = ""


__all__ = [
	"LMSToolRegisteredEvent",
	"LearnerActivityStartedEvent",
	"LearnerActivityCompletedEvent",
	"CredentialIssuedEvent",
	"CredentialRevokedEvent",
	"LearningPathAssignedEvent",
]
