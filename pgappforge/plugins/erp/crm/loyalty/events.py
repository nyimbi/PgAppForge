"""
pgappforge/plugins/erp/crm/loyalty/events.py

Domain events for the Loyalty Engine plugin.
"""
from __future__ import annotations

from dataclasses import dataclass

from pgappforge.plugins.erp.foundation.events import DomainEvent

__all__ = [
	"CustomerEnrolledEvent",
	"PointsEarnedEvent",
	"PointsRedeemedEvent",
	"TierUpgradeEvent",
]


@dataclass
class CustomerEnrolledEvent(DomainEvent):
	"""Emitted when a customer is enrolled in a loyalty program."""
	event_type: str = "crm.loyalty.customer.enrolled"
	account_id: str = ""
	customer_id: str = ""
	program_id: str = ""
	tenant_id: str = ""


@dataclass
class PointsEarnedEvent(DomainEvent):
	"""Emitted when a customer earns points from a qualifying transaction."""
	event_type: str = "crm.loyalty.points.earned"
	account_id: str = ""
	customer_id: str = ""
	points: int = 0
	reference_id: str = ""
	balance_after: int = 0


@dataclass
class PointsRedeemedEvent(DomainEvent):
	"""Emitted when a customer redeems points."""
	event_type: str = "crm.loyalty.points.redeemed"
	account_id: str = ""
	customer_id: str = ""
	points: int = 0
	reference_id: str = ""
	balance_after: int = 0


@dataclass
class TierUpgradeEvent(DomainEvent):
	"""Emitted when a customer's loyalty tier is upgraded."""
	event_type: str = "crm.loyalty.tier.upgraded"
	account_id: str = ""
	customer_id: str = ""
	old_tier: str = ""
	new_tier: str = ""
