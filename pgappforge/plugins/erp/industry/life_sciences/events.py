"""
pgappforge/plugins/erp/industry/life_sciences/events.py

Domain events for the Life Sciences plugin.

Events emitted:
  life_sciences.trial.subject_enrolled   — subject enrolled into trial arm
  life_sciences.trial.sae_reported       — SAE reported to authority
  life_sciences.submission.approved      — regulatory submission approved
  life_sciences.trial.completed          — trial reached completion
"""
from __future__ import annotations

from dataclasses import dataclass

from pgappforge.plugins.erp.foundation.events import DomainEvent


@dataclass
class TrialSubjectEnrolledEvent(DomainEvent):
	event_type: str = "life_sciences.trial.subject_enrolled"
	subject_id: str = ""
	subject_number: str = ""
	trial_id: str = ""
	arm: str = ""
	consent_date: str = ""  # ISO date


@dataclass
class SAEReportedEvent(DomainEvent):
	"""Emitted when a Serious Adverse Event is reported to a regulatory authority."""
	event_type: str = "life_sciences.trial.sae_reported"
	event_id: str = ""
	subject_id: str = ""
	trial_id: str = ""
	event_date: str = ""       # ISO datetime
	authority_reference: str = ""
	reported_by_id: str = ""
	serious_criteria: list = None  # CTCAE criteria list

	def __post_init__(self) -> None:
		if self.serious_criteria is None:
			self.serious_criteria = []


@dataclass
class RegulatorySubmissionApprovedEvent(DomainEvent):
	event_type: str = "life_sciences.submission.approved"
	submission_record_id: str = ""
	submission_id: str = ""
	trial_id: str = ""
	authority: str = ""
	submission_type: str = ""
	approval_date: str = ""   # ISO date
	approval_reference: str = ""


@dataclass
class ClinicalTrialCompletedEvent(DomainEvent):
	event_type: str = "life_sciences.trial.completed"
	trial_id: str = ""
	trial_ref: str = ""        # internal trial_id field
	phase: str = ""
	enrolled_count: int = 0
	actual_completion_date: str = ""  # ISO date


__all__ = [
	"TrialSubjectEnrolledEvent",
	"SAEReportedEvent",
	"RegulatorySubmissionApprovedEvent",
	"ClinicalTrialCompletedEvent",
]
