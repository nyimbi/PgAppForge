"""
pgappforge/plugins/erp/finance/credit_management/events.py

Domain events for the Credit Management plugin.

All monetary fields are integer cents — never float.

Events emitted
--------------
  finance.credit.limit.set        — credit limit set or updated for a customer
  finance.credit.exposure.updated — live exposure recomputed
  finance.credit.hold.placed      — customer placed on credit hold
  finance.credit.hold.released    — credit hold lifted
  finance.credit.breach           — exposure exceeds approved limit
"""
from __future__ import annotations

from dataclasses import dataclass

from pgappforge.plugins.erp.foundation.events import DomainEvent


@dataclass
class CreditLimitSetEvent(DomainEvent):
	"""Emitted when a credit limit is created or updated for a customer."""
	event_type: str = "finance.credit.limit.set"
	customer_id: str = ""
	limit_cents: int = 0
	currency: str = "USD"
	tenant_id: str = ""


@dataclass
class CreditExposureUpdatedEvent(DomainEvent):
	"""Emitted after exposure is recomputed from open AR + unshipped orders."""
	event_type: str = "finance.credit.exposure.updated"
	customer_id: str = ""
	exposure_cents: int = 0
	available_cents: int = 0        # limit - exposure (may be negative)


@dataclass
class CreditHoldPlacedEvent(DomainEvent):
	"""Emitted when a credit hold is placed on a customer account."""
	event_type: str = "finance.credit.hold.placed"
	customer_id: str = ""
	reason: str = ""
	placed_by: str = ""


@dataclass
class CreditHoldReleasedEvent(DomainEvent):
	"""Emitted when a credit hold is released."""
	event_type: str = "finance.credit.hold.released"
	customer_id: str = ""
	released_by: str = ""


@dataclass
class CreditLimitBreachEvent(DomainEvent):
	"""Emitted when exposure exceeds the approved credit limit.

	overage_cents = exposure_cents - limit_cents
	Triggers: auto-hold workflow, risk escalation, collections alert.
	"""
	event_type: str = "finance.credit.breach"
	customer_id: str = ""
	exposure_cents: int = 0
	limit_cents: int = 0
	overage_cents: int = 0          # exposure - limit


__all__ = [
	"CreditLimitSetEvent",
	"CreditExposureUpdatedEvent",
	"CreditHoldPlacedEvent",
	"CreditHoldReleasedEvent",
	"CreditLimitBreachEvent",
]
