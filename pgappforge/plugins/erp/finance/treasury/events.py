"""
pgappforge/plugins/erp/finance/treasury/events.py

Domain events for the Treasury plugin.

Emitted events:
  treasury.bank_account_created   — new bank account registered
  treasury.fx_deal_booked         — FX deal entered
  treasury.fx_deal_settled        — FX deal settled on maturity
  treasury.bank_reconciliation_done — reconciliation complete for a statement
  treasury.cash_position_updated  — daily cash position recalculated

Subscribed events (upstream):
  exchange_rate.updated           — refresh MTM valuations on FX deals
  party.created                   — auto-register counterparty bank accounts
"""
from __future__ import annotations

from dataclasses import dataclass

from pgappforge.plugins.erp.foundation.events import DomainEvent, emit_event


@dataclass
class BankAccountCreatedEvent(DomainEvent):
	event_type: str = "treasury.bank_account_created"
	bank_account_id: str = ""
	account_number: str = ""
	currency_code: str = ""
	bank_name: str = ""


@dataclass
class FXDealBookedEvent(DomainEvent):
	event_type: str = "treasury.fx_deal_booked"
	deal_id: str = ""
	deal_reference: str = ""
	deal_type: str = ""
	buy_currency: str = ""
	sell_currency: str = ""
	buy_amount_cents: int = 0
	sell_amount_cents: int = 0
	contracted_rate: str = ""   # string — never float
	settlement_date: str = ""
	hedge_designation: str = "NONE"


@dataclass
class FXDealSettledEvent(DomainEvent):
	event_type: str = "treasury.fx_deal_settled"
	deal_id: str = ""
	deal_reference: str = ""
	settlement_date: str = ""
	buy_amount_cents: int = 0
	sell_amount_cents: int = 0


@dataclass
class BankReconciliationDoneEvent(DomainEvent):
	event_type: str = "treasury.bank_reconciliation_done"
	bank_account_id: str = ""
	statement_id: str = ""
	statement_date: str = ""
	matched_lines: int = 0
	exception_lines: int = 0


@dataclass
class CashPositionUpdatedEvent(DomainEvent):
	event_type: str = "treasury.cash_position_updated"
	bank_account_id: str = ""
	position_date: str = ""
	closing_balance_cents: int = 0
	forecast_balance_cents: int = 0
	currency_code: str = ""


__all__ = [
	"BankAccountCreatedEvent",
	"FXDealBookedEvent",
	"FXDealSettledEvent",
	"BankReconciliationDoneEvent",
	"CashPositionUpdatedEvent",
	"emit_event",
]
