"""
pgappforge/plugins/erp/crm/sales/events.py

Domain events for the Sales Force Automation plugin.

All monetary fields are integer cents — never float.

Events emitted
--------------
  crm.lead.created          — new lead ingested
  crm.lead.scored           — lead score recomputed
  crm.lead.qualified        — lead status → QUALIFIED
  crm.lead.converted        — lead converted to account/contact/opportunity
  crm.lead.disqualified     — lead marked DISQUALIFIED
  crm.opportunity.created   — new opportunity created
  crm.opportunity.stage_advanced — stage changed
  crm.opportunity.won       — stage → CLOSED_WON
  crm.opportunity.lost      — stage → CLOSED_LOST
  crm.activity.logged       — activity completed
  crm.forecast.submitted    — forecast submitted for a period
"""
from __future__ import annotations

from dataclasses import dataclass, field

from pgappforge.plugins.erp.foundation.events import DomainEvent


# ---------------------------------------------------------------------------
# Lead events
# ---------------------------------------------------------------------------

@dataclass
class LeadCreatedEvent(DomainEvent):
	"""Emitted when a new lead is created."""
	event_type: str = "crm.lead.created"
	lead_id: str = ""
	source: str = ""
	email: str = ""
	assigned_to: str = ""
	tenant_id: str = ""


@dataclass
class LeadScoredEvent(DomainEvent):
	"""Emitted when a lead score is recomputed."""
	event_type: str = "crm.lead.scored"
	lead_id: str = ""
	old_score: int = 0
	new_score: int = 0
	old_grade: str = ""
	new_grade: str = ""


@dataclass
class LeadQualifiedEvent(DomainEvent):
	"""Emitted when a lead is moved to QUALIFIED status.

	Triggers routing to sales queue and optional Opportunity creation.
	"""
	event_type: str = "crm.lead.qualified"
	lead_id: str = ""
	score: int = 0
	grade: str = ""
	assigned_to: str = ""
	company: str = ""


@dataclass
class LeadConvertedEvent(DomainEvent):
	"""Emitted when a lead is converted to account/contact/opportunity."""
	event_type: str = "crm.lead.converted"
	lead_id: str = ""
	converted_account_id: str = ""
	converted_contact_id: str = ""
	converted_opportunity_id: str = ""


@dataclass
class LeadDisqualifiedEvent(DomainEvent):
	"""Emitted when a lead is marked DISQUALIFIED."""
	event_type: str = "crm.lead.disqualified"
	lead_id: str = ""
	reason: str = ""


# ---------------------------------------------------------------------------
# Opportunity events
# ---------------------------------------------------------------------------

@dataclass
class OpportunityCreatedEvent(DomainEvent):
	"""Emitted when a new opportunity is created."""
	event_type: str = "crm.opportunity.created"
	opportunity_id: str = ""
	account_id: str = ""
	opportunity_name: str = ""
	amount_cents: int = 0
	currency_code: str = ""
	stage: str = ""
	owner_id: str = ""


@dataclass
class OpportunityStageAdvancedEvent(DomainEvent):
	"""Emitted on any stage transition."""
	event_type: str = "crm.opportunity.stage_advanced"
	opportunity_id: str = ""
	opportunity_name: str = ""
	account_id: str = ""
	old_stage: str = ""
	new_stage: str = ""
	amount_cents: int = 0
	currency_code: str = ""
	probability: int = 0


@dataclass
class OpportunityWonEvent(DomainEvent):
	"""Emitted when stage transitions to CLOSED_WON.

	Consumed by: CPQ (finalise quote), AR (create invoice), SalesTarget (update achieved).
	"""
	event_type: str = "crm.opportunity.won"
	opportunity_id: str = ""
	opportunity_name: str = ""
	account_id: str = ""
	amount_cents: int = 0
	currency_code: str = ""
	owner_id: str = ""
	reason_won: str = ""
	closed_at: str = ""       # ISO datetime string


@dataclass
class OpportunityLostEvent(DomainEvent):
	"""Emitted when stage transitions to CLOSED_LOST."""
	event_type: str = "crm.opportunity.lost"
	opportunity_id: str = ""
	opportunity_name: str = ""
	account_id: str = ""
	amount_cents: int = 0
	currency_code: str = ""
	reason_lost: str = ""
	competitor: str = ""
	closed_at: str = ""       # ISO datetime string


# ---------------------------------------------------------------------------
# Activity events
# ---------------------------------------------------------------------------

@dataclass
class ActivityLoggedEvent(DomainEvent):
	"""Emitted when a sales activity is marked COMPLETED."""
	event_type: str = "crm.activity.logged"
	activity_id: str = ""
	activity_type: str = ""
	contact_id: str = ""
	account_id: str = ""
	opportunity_id: str = ""
	owner_id: str = ""
	outcome: str = ""


# ---------------------------------------------------------------------------
# Forecast events
# ---------------------------------------------------------------------------

@dataclass
class ForecastSubmittedEvent(DomainEvent):
	"""Emitted when a rep or manager submits a forecast."""
	event_type: str = "crm.forecast.submitted"
	forecast_id: str = ""
	period_id: str = ""
	owner_id: str = ""
	commit_cents: int = 0
	best_case_cents: int = 0
	pipeline_cents: int = 0


__all__ = [
	"LeadCreatedEvent",
	"LeadScoredEvent",
	"LeadQualifiedEvent",
	"LeadConvertedEvent",
	"LeadDisqualifiedEvent",
	"OpportunityCreatedEvent",
	"OpportunityStageAdvancedEvent",
	"OpportunityWonEvent",
	"OpportunityLostEvent",
	"ActivityLoggedEvent",
	"ForecastSubmittedEvent",
]
