"""
pgappforge/plugins/erp/finance/grants/events.py

Domain events for the Grant/Fund Accounting plugin.

All monetary amounts are integer cents — never float.
Downstream plugins subscribe via emit_event / subscribe() from foundation.

Events emitted:
  finance.grants.fund.created          — new fund registered
  finance.grants.grant.awarded         — grant awarded to a fund
  finance.grants.expenditure.recorded  — expenditure posted against a grant
  finance.grants.balance.updated       — fund balance updated for a period
  finance.grants.closed_out            — grant closed out
  finance.grants.report.generated      — utilization report produced
"""
from __future__ import annotations

from dataclasses import dataclass

from pgappforge.plugins.erp.foundation.events import DomainEvent


@dataclass
class FundCreatedEvent(DomainEvent):
	"""Emitted when a new Fund is registered."""
	event_type: str = "finance.grants.fund.created"
	fund_id: str = ""
	name: str = ""
	fund_type: str = ""
	tenant_id: str = ""


@dataclass
class GrantAwardedEvent(DomainEvent):
	"""Emitted when a grant is awarded and linked to a fund."""
	event_type: str = "finance.grants.grant.awarded"
	grant_id: str = ""
	fund_id: str = ""
	grantor: str = ""
	amount_cents: int = 0


@dataclass
class GrantExpenditureRecordedEvent(DomainEvent):
	"""Emitted when an expenditure is recorded against a grant."""
	event_type: str = "finance.grants.expenditure.recorded"
	expenditure_id: str = ""
	grant_id: str = ""
	amount_cents: int = 0
	purpose: str = ""


@dataclass
class FundBalanceUpdatedEvent(DomainEvent):
	"""Emitted after a fund balance is updated for a period."""
	event_type: str = "finance.grants.balance.updated"
	fund_id: str = ""
	period: str = ""
	closing_cents: int = 0


@dataclass
class GrantCloseOutEvent(DomainEvent):
	"""Emitted when a grant is formally closed out."""
	event_type: str = "finance.grants.closed_out"
	grant_id: str = ""
	total_spent_cents: int = 0
	remaining_cents: int = 0


@dataclass
class GrantReportGeneratedEvent(DomainEvent):
	"""Emitted when a utilization report is generated for a grant."""
	event_type: str = "finance.grants.report.generated"
	grant_id: str = ""
	period: str = ""
	utilization_pct: float = 0.0


__all__ = [
	"FundCreatedEvent",
	"GrantAwardedEvent",
	"GrantExpenditureRecordedEvent",
	"FundBalanceUpdatedEvent",
	"GrantCloseOutEvent",
	"GrantReportGeneratedEvent",
]
