"""
pgappforge/plugins/fintech/embedded_finance/events.py

Embedded Finance domain events.

All events extend DomainEvent and are emitted by EmbeddedFinanceService.
Emission failures are swallowed — they never roll back business transactions.

Event catalogue
---------------
  embedded.partner.onboarded     — new partner registered and API key issued
  embedded.consent.granted       — customer granted consent to a partner
  embedded.transaction           — embedded payment/account action completed
  embedded.rev_share.calculated  — revenue share record computed for a period
"""
from __future__ import annotations

from dataclasses import dataclass

from pgappforge.plugins.erp.foundation.events import DomainEvent


# ---------------------------------------------------------------------------
# Event classes
# ---------------------------------------------------------------------------

@dataclass
class PartnerOnboardedEvent(DomainEvent):
	"""Emitted when a new embedded finance partner is registered."""
	event_type: str = "embedded.partner.onboarded"
	partner_id: str = ""
	partner_name: str = ""
	partner_type: str = ""
	sandbox_mode: bool = True


@dataclass
class ConsentGrantedEvent(DomainEvent):
	"""Emitted when a customer grants consent to a partner for specific products."""
	event_type: str = "embedded.consent.granted"
	consent_id: str = ""
	customer_id: str = ""
	partner_id: str = ""
	products_consented: list = None  # type: ignore[assignment]

	def __post_init__(self):
		if self.products_consented is None:
			self.products_consented = []


@dataclass
class EmbeddedTransactionEvent(DomainEvent):
	"""Emitted when an embedded financial transaction is processed."""
	event_type: str = "embedded.transaction"
	partner_id: str = ""
	customer_id: str = ""
	transaction_type: str = ""
	amount_cents: int = 0
	currency: str = ""
	reference: str = ""
	status: str = ""


@dataclass
class RevShareCalculatedEvent(DomainEvent):
	"""Emitted when a revenue share record is created for a partner."""
	event_type: str = "embedded.rev_share.calculated"
	rev_share_id: str = ""
	partner_id: str = ""
	period: str = ""
	product_type: str = ""
	gross_revenue_cents: int = 0
	partner_share_cents: int = 0
	net_cents: int = 0


# ---------------------------------------------------------------------------
# Event type constants
# ---------------------------------------------------------------------------

EMBEDDED_PARTNER_ONBOARDED = "embedded.partner.onboarded"
EMBEDDED_CONSENT_GRANTED = "embedded.consent.granted"
EMBEDDED_TRANSACTION = "embedded.transaction"
EMBEDDED_REV_SHARE_CALCULATED = "embedded.rev_share.calculated"

ALL_EMBEDDED_EVENT_TYPES: list[str] = [
	EMBEDDED_PARTNER_ONBOARDED,
	EMBEDDED_CONSENT_GRANTED,
	EMBEDDED_TRANSACTION,
	EMBEDDED_REV_SHARE_CALCULATED,
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"PartnerOnboardedEvent",
	"ConsentGrantedEvent",
	"EmbeddedTransactionEvent",
	"RevShareCalculatedEvent",
	"EMBEDDED_PARTNER_ONBOARDED",
	"EMBEDDED_CONSENT_GRANTED",
	"EMBEDDED_TRANSACTION",
	"EMBEDDED_REV_SHARE_CALCULATED",
	"ALL_EMBEDDED_EVENT_TYPES",
]
