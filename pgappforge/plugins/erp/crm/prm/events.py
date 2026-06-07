"""
pgappforge/plugins/erp/crm/prm/events.py

Domain events for the Partner Relationship Management (PRM) plugin.

All monetary amounts are integer cents (never float).
"""
from __future__ import annotations

from dataclasses import dataclass

from pgappforge.plugins.erp.foundation.events import DomainEvent

__all__ = [
	"PartnerRegisteredEvent",
	"DealRegisteredEvent",
	"MDFApprovedEvent",
	"DealWonEvent",
]


@dataclass
class PartnerRegisteredEvent(DomainEvent):
	"""Emitted when a new partner account is created."""
	event_type: str = "crm.prm.partner.registered"
	partner_id: str = ""
	company_name: str = ""
	tier: str = ""
	tenant_id: str = ""


@dataclass
class DealRegisteredEvent(DomainEvent):
	"""Emitted when a partner submits a new deal registration."""
	event_type: str = "crm.prm.deal.registered"
	deal_id: str = ""
	partner_id: str = ""
	customer_name: str = ""
	estimated_value_cents: int = 0


@dataclass
class MDFApprovedEvent(DomainEvent):
	"""Emitted when a Market Development Fund request is approved."""
	event_type: str = "crm.prm.mdf.approved"
	request_id: str = ""
	partner_id: str = ""
	approved_cents: int = 0


@dataclass
class DealWonEvent(DomainEvent):
	"""Emitted when a registered deal is closed as won."""
	event_type: str = "crm.prm.deal.won"
	deal_id: str = ""
	partner_id: str = ""
	actual_value_cents: int = 0
