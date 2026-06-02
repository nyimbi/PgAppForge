"""
pgappforge/plugins/erp/crm/commerce/events.py

Domain events for the Commerce plugin.

All monetary fields are integer cents — never float.
"""
from __future__ import annotations

from dataclasses import dataclass

from pgappforge.plugins.erp.foundation.events import DomainEvent


@dataclass
class SubscriptionActivatedEvent(DomainEvent):
	"""Emitted when a new subscription becomes ACTIVE (or trial starts)."""
	event_type: str = "commerce.subscription.activated"
	subscription_id: str = ""
	customer_id: str = ""
	plan_id: str = ""
	plan_name: str = ""
	amount_cents: int = 0
	currency_code: str = ""
	billing_interval: str = ""
	start_date: str = ""         # ISO date
	next_billing_date: str = ""  # ISO date


@dataclass
class SubscriptionRenewedEvent(DomainEvent):
	"""Emitted when a subscription billing cycle renews successfully."""
	event_type: str = "commerce.subscription.renewed"
	subscription_id: str = ""
	customer_id: str = ""
	plan_id: str = ""
	amount_cents: int = 0
	currency_code: str = ""
	billed_date: str = ""        # ISO date
	next_billing_date: str = ""  # ISO date


@dataclass
class SubscriptionCancelledEvent(DomainEvent):
	"""Emitted when a subscription is cancelled."""
	event_type: str = "commerce.subscription.cancelled"
	subscription_id: str = ""
	customer_id: str = ""
	plan_id: str = ""
	cancelled_at: str = ""       # ISO datetime
	cancellation_reason: str = ""


@dataclass
class SubscriptionPastDueEvent(DomainEvent):
	"""Emitted when a billing attempt fails and subscription enters PAST_DUE."""
	event_type: str = "commerce.subscription.past_due"
	subscription_id: str = ""
	customer_id: str = ""
	plan_id: str = ""
	amount_cents: int = 0
	currency_code: str = ""
	failed_billing_date: str = ""  # ISO date


__all__ = [
	"SubscriptionActivatedEvent",
	"SubscriptionRenewedEvent",
	"SubscriptionCancelledEvent",
	"SubscriptionPastDueEvent",
]
