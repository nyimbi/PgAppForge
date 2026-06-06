"""
pgappforge/plugins/erp/crm/subscriptions/events.py

Domain events for the Subscriptions Management plugin.

All monetary amounts are integer cents (never float).
All events inherit from DomainEvent and carry aggregate_id = sub_id
so DomainEventLog rows can be correlated by subscription.
"""
from __future__ import annotations

from dataclasses import dataclass

from pgappforge.plugins.erp.foundation.events import DomainEvent

__all__ = [
	"SubscriptionCreatedEvent",
	"SubscriptionActivatedEvent",
	"SubscriptionRenewedEvent",
	"SubscriptionUpgradedEvent",
	"SubscriptionDowngradedEvent",
	"SubscriptionCancelledEvent",
	"SubscriptionPastDueEvent",
	"InvoiceGeneratedEvent",
]


@dataclass
class SubscriptionCreatedEvent(DomainEvent):
	"""Emitted when a new subscription record is persisted for the first time.

	status will be TRIALING when a trial is configured, otherwise ACTIVE.
	"""
	event_type: str = "crm.subscriptions.created"
	sub_id: str = ""
	customer_id: str = ""
	plan_id: str = ""


@dataclass
class SubscriptionActivatedEvent(DomainEvent):
	"""Emitted when a subscription transitions TRIALING → ACTIVE.

	current_period_end is the ISO date string for the end of the first paid period.
	"""
	event_type: str = "crm.subscriptions.activated"
	sub_id: str = ""
	customer_id: str = ""
	current_period_end: str = ""


@dataclass
class SubscriptionRenewedEvent(DomainEvent):
	"""Emitted after a successful renewal — invoice created, period advanced."""
	event_type: str = "crm.subscriptions.renewed"
	sub_id: str = ""
	customer_id: str = ""
	amount_cents: int = 0
	period_end: str = ""


@dataclass
class SubscriptionUpgradedEvent(DomainEvent):
	"""Emitted when a subscription moves to a higher-value plan."""
	event_type: str = "crm.subscriptions.upgraded"
	sub_id: str = ""
	customer_id: str = ""
	old_plan_id: str = ""
	new_plan_id: str = ""


@dataclass
class SubscriptionDowngradedEvent(DomainEvent):
	"""Emitted when a subscription moves to a lower-value plan."""
	event_type: str = "crm.subscriptions.downgraded"
	sub_id: str = ""
	customer_id: str = ""
	old_plan_id: str = ""
	new_plan_id: str = ""


@dataclass
class SubscriptionCancelledEvent(DomainEvent):
	"""Emitted when a cancellation is requested (immediate or at period end)."""
	event_type: str = "crm.subscriptions.cancelled"
	sub_id: str = ""
	customer_id: str = ""
	cancel_reason: str = ""


@dataclass
class SubscriptionPastDueEvent(DomainEvent):
	"""Emitted when a renewal attempt fails and the subscription goes PAST_DUE."""
	event_type: str = "crm.subscriptions.past_due"
	sub_id: str = ""
	customer_id: str = ""
	amount_owed_cents: int = 0


@dataclass
class InvoiceGeneratedEvent(DomainEvent):
	"""Emitted when a SubscriptionInvoice row is created during renewal."""
	event_type: str = "crm.subscriptions.invoice.generated"
	invoice_id: str = ""
	sub_id: str = ""
	amount_cents: int = 0
	due_date: str = ""
