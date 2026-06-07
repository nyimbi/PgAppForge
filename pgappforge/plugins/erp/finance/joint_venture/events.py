"""
pgappforge/plugins/erp/finance/joint_venture/events.py

Domain events for the Joint Venture Accounting plugin.

Emitted events:
  joint_venture.venture_created       — new JV registered
  joint_venture.partner_added         — partner / working interest added
  joint_venture.costs_allocated       — JV costs allocated to partners
  joint_venture.billing_statement_cut — monthly billing statement generated
  joint_venture.cash_call_issued      — cash call notice sent to partners
  joint_venture.audit_query_raised    — partner audit query registered
"""
from __future__ import annotations

from dataclasses import dataclass

from pgappforge.plugins.erp.foundation.events import DomainEvent, emit_event


@dataclass
class VentureCreatedEvent(DomainEvent):
	event_type: str = "joint_venture.venture_created"
	venture_id: str = ""
	venture_code: str = ""
	venture_name: str = ""
	operator_party_id: str = ""
	effective_date: str = ""


@dataclass
class PartnerAddedEvent(DomainEvent):
	event_type: str = "joint_venture.partner_added"
	venture_id: str = ""
	partner_id: str = ""
	party_id: str = ""
	working_interest_pct: str = ""   # Decimal as string
	effective_date: str = ""


@dataclass
class JvCostsAllocatedEvent(DomainEvent):
	event_type: str = "joint_venture.costs_allocated"
	allocation_id: str = ""
	venture_id: str = ""
	period_date: str = ""
	total_costs_cents: int = 0
	partners_allocated: int = 0


@dataclass
class BillingStatementCutEvent(DomainEvent):
	event_type: str = "joint_venture.billing_statement_cut"
	statement_id: str = ""
	venture_id: str = ""
	billing_period: str = ""
	total_billed_cents: int = 0
	partners_billed: int = 0


@dataclass
class CashCallIssuedEvent(DomainEvent):
	event_type: str = "joint_venture.cash_call_issued"
	cash_call_id: str = ""
	venture_id: str = ""
	due_date: str = ""
	total_amount_cents: int = 0
	partners_notified: int = 0


@dataclass
class AuditQueryRaisedEvent(DomainEvent):
	event_type: str = "joint_venture.audit_query_raised"
	query_id: str = ""
	venture_id: str = ""
	partner_id: str = ""
	query_reference: str = ""
	amount_disputed_cents: int = 0


__all__ = [
	"VentureCreatedEvent",
	"PartnerAddedEvent",
	"JvCostsAllocatedEvent",
	"BillingStatementCutEvent",
	"CashCallIssuedEvent",
	"AuditQueryRaisedEvent",
	"emit_event",
]
