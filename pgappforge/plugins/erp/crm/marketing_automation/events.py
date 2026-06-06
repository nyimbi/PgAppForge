"""
pgappforge/plugins/erp/crm/marketing_automation/events.py

Domain events emitted by the Marketing Automation plugin.

All monetary amounts are integer cents. Never floats.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pgappforge.plugins.erp.foundation.events import DomainEvent


@dataclass
class CampaignActivatedEvent(DomainEvent):
	"""Emitted when a campaign transitions DRAFT → ACTIVE."""
	event_type: str = "crm.marketing.campaign.activated"
	campaign_id: str = ""
	tenant_id: str = ""


@dataclass
class CampaignEmailSentEvent(DomainEvent):
	"""Emitted when an email is dispatched to a contact within a campaign sequence."""
	event_type: str = "crm.marketing.email.sent"
	campaign_id: str = ""
	contact_id: str = ""
	email: str = ""


@dataclass
class LeadScoredEvent(DomainEvent):
	"""Emitted when a lead score changes (grade boundary or any delta)."""
	event_type: str = "crm.marketing.lead.scored"
	lead_id: str = ""
	old_score: int = 0
	new_score: int = 0
	triggers: list = field(default_factory=list)


@dataclass
class ABTestVariantWonEvent(DomainEvent):
	"""Emitted when statistical confidence determines a winning A/B variant."""
	event_type: str = "crm.marketing.ab_test.winner"
	campaign_id: str = ""
	winning_variant: str = ""
	confidence_pct: int = 0


@dataclass
class RevenueAttributedEvent(DomainEvent):
	"""Emitted when revenue from an opportunity is attributed to a campaign."""
	event_type: str = "crm.marketing.revenue.attributed"
	campaign_id: str = ""
	opportunity_id: str = ""
	amount_cents: int = 0


__all__ = [
	"CampaignActivatedEvent",
	"CampaignEmailSentEvent",
	"LeadScoredEvent",
	"ABTestVariantWonEvent",
	"RevenueAttributedEvent",
]
