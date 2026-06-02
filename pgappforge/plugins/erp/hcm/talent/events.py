"""
pgappforge/plugins/erp/hcm/talent/events.py

Domain events for the HCM Talent Management plugin.

All monetary amounts are integer cents — never float.

Events emitted:
  hcm.talent.requisition.approved    — requisition approved, triggers posting
  hcm.talent.requisition.filled      — headcount filled, closes requisition
  hcm.talent.application.stage_changed — pipeline stage transition
  hcm.talent.offer.sent              — offer letter dispatched to candidate
  hcm.talent.offer.accepted          — candidate accepted; triggers onboarding
  hcm.talent.offer.declined          — candidate declined
  hcm.talent.review.finalised        — performance review locked as FINAL
  hcm.talent.training.completed      — employee completed a training course

Events consumed:
  hcm.employee.created               — auto-creates probation review
  hcm.payroll.run.paid               — can trigger merit raise review window
"""
from __future__ import annotations

from dataclasses import dataclass

from pgappforge.plugins.erp.foundation.events import DomainEvent


# ---------------------------------------------------------------------------
# Requisition events
# ---------------------------------------------------------------------------

@dataclass
class RequisitionApprovedEvent(DomainEvent):
	"""Emitted when a requisition is approved and ready to post."""
	event_type: str = "hcm.talent.requisition.approved"
	requisition_id: str = ""
	requisition_number: str = ""
	position_id: str = ""
	hiring_manager_id: str = ""
	headcount: int = 1
	salary_range_min_cents: int = 0
	salary_range_max_cents: int = 0
	currency: str = ""


@dataclass
class RequisitionFilledEvent(DomainEvent):
	"""Emitted when all headcount seats are filled."""
	event_type: str = "hcm.talent.requisition.filled"
	requisition_id: str = ""
	requisition_number: str = ""
	filled_headcount: int = 0
	days_to_fill: int = 0


# ---------------------------------------------------------------------------
# Application events
# ---------------------------------------------------------------------------

@dataclass
class ApplicationStageChangedEvent(DomainEvent):
	"""Emitted on every pipeline stage transition for an application."""
	event_type: str = "hcm.talent.application.stage_changed"
	application_id: str = ""
	requisition_id: str = ""
	candidate_id: str = ""
	old_stage: str = ""
	new_stage: str = ""
	rejection_reason: str = ""


# ---------------------------------------------------------------------------
# Offer events
# ---------------------------------------------------------------------------

@dataclass
class OfferSentEvent(DomainEvent):
	"""Emitted when an offer letter is dispatched to the candidate."""
	event_type: str = "hcm.talent.offer.sent"
	offer_id: str = ""
	application_id: str = ""
	candidate_id: str = ""
	base_salary_cents: int = 0
	signing_bonus_cents: int = 0
	currency: str = ""
	start_date: str = ""
	expiry_date: str = ""


@dataclass
class OfferAcceptedEvent(DomainEvent):
	"""Emitted when a candidate accepts an offer — triggers onboarding flow."""
	event_type: str = "hcm.talent.offer.accepted"
	offer_id: str = ""
	application_id: str = ""
	candidate_id: str = ""
	requisition_id: str = ""
	base_salary_cents: int = 0
	currency: str = ""
	start_date: str = ""


@dataclass
class OfferDeclinedEvent(DomainEvent):
	"""Emitted when a candidate declines an offer."""
	event_type: str = "hcm.talent.offer.declined"
	offer_id: str = ""
	application_id: str = ""
	candidate_id: str = ""
	decline_reason: str = ""


# ---------------------------------------------------------------------------
# Performance review events
# ---------------------------------------------------------------------------

@dataclass
class PerformanceReviewFinalisedEvent(DomainEvent):
	"""Emitted when a performance review is locked as FINAL."""
	event_type: str = "hcm.talent.review.finalised"
	review_id: str = ""
	employee_id: str = ""
	reviewer_id: str = ""
	review_cycle: str = ""
	period_end: str = ""
	overall_rating: str = ""     # string from Decimal to avoid float
	rating_label: str = ""


# ---------------------------------------------------------------------------
# Training events
# ---------------------------------------------------------------------------

@dataclass
class TrainingCompletedEvent(DomainEvent):
	"""Emitted when an employee completes a training course."""
	event_type: str = "hcm.talent.training.completed"
	enrollment_id: str = ""
	employee_id: str = ""
	course_id: str = ""
	course_code: str = ""
	score: str = ""              # string from Decimal to avoid float
	certificate_url: str = ""
	duration_hours: str = ""     # string from Decimal


__all__ = [
	"RequisitionApprovedEvent",
	"RequisitionFilledEvent",
	"ApplicationStageChangedEvent",
	"OfferSentEvent",
	"OfferAcceptedEvent",
	"OfferDeclinedEvent",
	"PerformanceReviewFinalisedEvent",
	"TrainingCompletedEvent",
]
