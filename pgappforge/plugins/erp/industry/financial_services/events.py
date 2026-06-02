"""
pgappforge/plugins/erp/industry/financial_services/events.py

Domain events for the Financial Services Cloud plugin.

All monetary amounts are INTEGER cents — never float.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from pgappforge.plugins.erp.foundation.events import DomainEvent, emit_event  # noqa: F401


# ---------------------------------------------------------------------------
# Client lifecycle events
# ---------------------------------------------------------------------------

@dataclass
class ClientOnboardedEvent(DomainEvent):
	"""Emitted when a FinancialClient is fully onboarded (KYC approved)."""
	event_type: str = "finserv.client.onboarded"
	client_id: str = ""
	party_id: str = ""
	client_number: str = ""
	client_type: str = ""
	risk_profile: str = ""


@dataclass
class ClientKYCStatusChangedEvent(DomainEvent):
	"""KYC status transition (e.g. PENDING → APPROVED, APPROVED → EXPIRED)."""
	event_type: str = "finserv.client.kyc_status_changed"
	client_id: str = ""
	client_number: str = ""
	old_status: str = ""
	new_status: str = ""
	changed_by: str = ""


@dataclass
class ClientRiskProfileChangedEvent(DomainEvent):
	"""Risk profile reclassification."""
	event_type: str = "finserv.client.risk_profile_changed"
	client_id: str = ""
	client_number: str = ""
	old_profile: str = ""
	new_profile: str = ""
	rationale: str = ""


# ---------------------------------------------------------------------------
# Account events
# ---------------------------------------------------------------------------

@dataclass
class AccountOpenedEvent(DomainEvent):
	"""Emitted when a PortfolioAccount is opened."""
	event_type: str = "finserv.account.opened"
	account_id: str = ""
	account_number: str = ""
	client_id: str = ""
	account_type: str = ""
	currency_code: str = ""


@dataclass
class AccountStatusChangedEvent(DomainEvent):
	"""Account status change: ACTIVE ↔ DORMANT / FROZEN / CLOSED."""
	event_type: str = "finserv.account.status_changed"
	account_id: str = ""
	account_number: str = ""
	old_status: str = ""
	new_status: str = ""
	changed_by: str = ""


@dataclass
class AccountBalanceUpdatedEvent(DomainEvent):
	"""Balance update after a transaction is posted — amounts in cents."""
	event_type: str = "finserv.account.balance_updated"
	account_id: str = ""
	account_number: str = ""
	delta_cents: int = 0          # positive = credit, negative = debit
	new_balance_cents: int = 0
	transaction_ref: str = ""


# ---------------------------------------------------------------------------
# Holdings / portfolio events
# ---------------------------------------------------------------------------

@dataclass
class HoldingRevaluedEvent(DomainEvent):
	"""Portfolio holding revalued at current market prices."""
	event_type: str = "finserv.holding.revalued"
	holding_id: str = ""
	client_id: str = ""
	instrument_isin: str = ""
	current_value_cents: int = 0
	unrealized_pnl_cents: int = 0
	as_of_date: str = ""          # ISO date string


# ---------------------------------------------------------------------------
# Sanctions / AML events
# ---------------------------------------------------------------------------

@dataclass
class SanctionsScreeningCompletedEvent(DomainEvent):
	"""Sanctions screening run completed."""
	event_type: str = "finserv.sanctions.screening_completed"
	screening_id: str = ""
	party_id: str = ""
	list_type: str = ""
	match_found: bool = False
	status: str = ""              # CLEAR | POTENTIAL_MATCH | CONFIRMED_MATCH


@dataclass
class SanctionsMatchClearedEvent(DomainEvent):
	"""A POTENTIAL_MATCH was reviewed and cleared by a compliance officer."""
	event_type: str = "finserv.sanctions.match_cleared"
	screening_id: str = ""
	party_id: str = ""
	cleared_by: str = ""


__all__ = [
	"emit_event",
	"ClientOnboardedEvent",
	"ClientKYCStatusChangedEvent",
	"ClientRiskProfileChangedEvent",
	"AccountOpenedEvent",
	"AccountStatusChangedEvent",
	"AccountBalanceUpdatedEvent",
	"HoldingRevaluedEvent",
	"SanctionsScreeningCompletedEvent",
	"SanctionsMatchClearedEvent",
]
