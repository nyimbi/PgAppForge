"""
pgappforge/plugins/fintech/agency/events.py

Agency Banking domain events.

All events extend DomainEvent from erp.foundation.events and are emitted
by AgencyService. Event emission is non-fatal — failures are swallowed so
they never roll back business transactions.

Event catalogue
---------------
  agency.agent.accredited    — agent KYC passed and status set to ACCREDITED
  agency.float.topped_up     — outlet float balance increased
  agency.transaction         — agency service transaction completed/reversed/failed
  agency.commission.settled  — period commission aggregated and marked PAID
  agency.outlet.suspended    — outlet status set to SUSPENDED
"""
from __future__ import annotations

from dataclasses import dataclass

from pgappforge.plugins.erp.foundation.events import DomainEvent


# ---------------------------------------------------------------------------
# Event classes
# ---------------------------------------------------------------------------

@dataclass
class AgentAccreditedEvent(DomainEvent):
	"""Emitted when an agent passes KYC and transitions to ACCREDITED status."""
	event_type: str = "agency.agent.accredited"
	agent_id: str = ""
	agent_name: str = ""
	outlet_id: str = ""
	msisdn: str = ""
	national_id: str = ""
	kyc_tier: int = 1


@dataclass
class FloatToppedUpEvent(DomainEvent):
	"""Emitted when an outlet's float is topped up."""
	event_type: str = "agency.float.topped_up"
	outlet_id: str = ""
	outlet_name: str = ""
	amount_cents: int = 0
	new_balance_cents: int = 0
	previous_balance_cents: int = 0


@dataclass
class AgencyTransactionEvent(DomainEvent):
	"""Emitted for each agency service transaction (completed, reversed, failed)."""
	event_type: str = "agency.transaction"
	transaction_id: str = ""
	agent_id: str = ""
	outlet_id: str = ""
	service_type: str = ""
	customer_msisdn: str = ""
	amount_cents: int = 0
	fee_cents: int = 0
	agent_commission_cents: int = 0
	status: str = ""
	reference: str = ""


@dataclass
class CommissionSettledEvent(DomainEvent):
	"""Emitted when a period's commissions are aggregated and settled."""
	event_type: str = "agency.commission.settled"
	period: str = ""
	records_count: int = 0
	total_gross_cents: int = 0
	total_net_cents: int = 0


@dataclass
class OutletSuspendedEvent(DomainEvent):
	"""Emitted when an outlet is suspended by an operator."""
	event_type: str = "agency.outlet.suspended"
	outlet_id: str = ""
	outlet_name: str = ""
	reason: str = ""


# ---------------------------------------------------------------------------
# Event type constants
# ---------------------------------------------------------------------------

AGENCY_AGENT_ACCREDITED = "agency.agent.accredited"
AGENCY_FLOAT_TOPPED_UP = "agency.float.topped_up"
AGENCY_TRANSACTION = "agency.transaction"
AGENCY_COMMISSION_SETTLED = "agency.commission.settled"
AGENCY_OUTLET_SUSPENDED = "agency.outlet.suspended"

ALL_AGENCY_EVENT_TYPES: list[str] = [
	AGENCY_AGENT_ACCREDITED,
	AGENCY_FLOAT_TOPPED_UP,
	AGENCY_TRANSACTION,
	AGENCY_COMMISSION_SETTLED,
	AGENCY_OUTLET_SUSPENDED,
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"AgentAccreditedEvent",
	"FloatToppedUpEvent",
	"AgencyTransactionEvent",
	"CommissionSettledEvent",
	"OutletSuspendedEvent",
	"AGENCY_AGENT_ACCREDITED",
	"AGENCY_FLOAT_TOPPED_UP",
	"AGENCY_TRANSACTION",
	"AGENCY_COMMISSION_SETTLED",
	"AGENCY_OUTLET_SUSPENDED",
	"ALL_AGENCY_EVENT_TYPES",
]
