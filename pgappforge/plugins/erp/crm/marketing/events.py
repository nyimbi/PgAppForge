"""
pgappforge/plugins/erp/crm/marketing/events.py

Domain events for the Marketing plugin.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from pgappforge.plugins.erp.foundation.events import DomainEvent


@dataclass
class CampaignActivatedEvent(DomainEvent):
	"""Emitted when a campaign transitions DRAFT/SCHEDULED → ACTIVE."""
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


@dataclass
class CampaignAssetSentEvent(DomainEvent):
	"""Emitted when a CampaignAsset is dispatched."""
	event_type: str = "marketing.campaign_asset.sent"
	asset_id: str = ""
	campaign_id: str = ""
	asset_type: str = ""
	sent_count: int = 0


@dataclass
class LeadQualifiedEvent(DomainEvent):
	"""Emitted when a Lead is moved to QUALIFIED status."""
	event_type: str = "marketing.lead.qualified"
	lead_id: str = ""
	email: str = ""
	lead_score: int = 0
	qualified_by: str = ""  # employee UUID


@dataclass
class LeadConvertedEvent(DomainEvent):
	"""Emitted when a Lead is converted to a Party contact record."""
	event_type: str = "marketing.lead.converted"
	lead_id: str = ""
	email: str = ""
	converted_contact_id: str = ""
	source_campaign_id: str = ""


__all__ = [
	"CampaignActivatedEvent",
	"CampaignAssetSentEvent",
	"CampaignCompletedEvent",
	"JourneyStepExecutedEvent",
	"LeadConvertedEvent",
	"LeadQualifiedEvent",
	"LeadRespondedEvent",
	"MemberUnsubscribedEvent",
]
