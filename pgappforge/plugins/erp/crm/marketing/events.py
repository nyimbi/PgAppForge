"""
pgappforge/plugins/erp/crm/marketing/events.py

Domain events for the Marketing plugin.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from pgappforge.plugins.erp.foundation.events import DomainEvent


@dataclass
class CampaignActivatedEvent(DomainEvent):
	"""Emitted when a campaign transitions PLANNING → ACTIVE."""
	event_type: str = "marketing.campaign.activated"
	campaign_id: str = ""
	campaign_name: str = ""
	campaign_type: str = ""
	budget_cents: int = 0
	start_date: str = ""  # ISO date


@dataclass
class CampaignCompletedEvent(DomainEvent):
	"""Emitted when a campaign is marked COMPLETED."""
	event_type: str = "marketing.campaign.completed"
	campaign_id: str = ""
	campaign_name: str = ""
	actual_cost_cents: int = 0
	actual_leads: int = 0
	actual_revenue_cents: int = 0


@dataclass
class LeadRespondedEvent(DomainEvent):
	"""Emitted when a campaign member's status reaches RESPONDED."""
	event_type: str = "marketing.lead.responded"
	campaign_member_id: str = ""
	campaign_id: str = ""
	party_id: str = ""
	member_type: str = ""
	responded_at: str = ""  # ISO datetime


@dataclass
class MemberUnsubscribedEvent(DomainEvent):
	"""Emitted when a contact opts out of a campaign."""
	event_type: str = "marketing.member.unsubscribed"
	campaign_member_id: str = ""
	campaign_id: str = ""
	party_id: str = ""


@dataclass
class JourneyStepExecutedEvent(DomainEvent):
	"""Emitted when an automation journey step is executed for a contact."""
	event_type: str = "marketing.journey.step_executed"
	journey_id: str = ""
	step_id: str = ""
	step_type: str = ""
	party_id: str = ""
	outcome: str = ""  # SENT, WAITED, BRANCHED_YES, BRANCHED_NO, SCORED


__all__ = [
	"CampaignActivatedEvent",
	"CampaignCompletedEvent",
	"LeadRespondedEvent",
	"MemberUnsubscribedEvent",
	"JourneyStepExecutedEvent",
]
