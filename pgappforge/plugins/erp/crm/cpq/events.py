"""
pgappforge/plugins/erp/crm/cpq/events.py

Domain events for the Configure-Price-Quote (CPQ) plugin.

All monetary fields are integer cents — never float.

Events emitted
--------------
  crm.quote.created         — new quote created (DRAFT)
  crm.quote.sent            — quote sent to customer (DRAFT → SENT)
  crm.quote.accepted        — customer accepted quote (SENT → ACCEPTED)
  crm.quote.rejected        — customer rejected quote (SENT → REJECTED)
  crm.quote.expired         — quote passed valid_until date
  crm.quote.approval_requested — quote submitted for internal approval
  crm.quote.approved        — quote approved by approver
  crm.quote.approval_rejected — quote rejected by approver
"""
from __future__ import annotations

from dataclasses import dataclass, field

from pgappforge.plugins.erp.foundation.events import DomainEvent


# ---------------------------------------------------------------------------
# Quote events
# ---------------------------------------------------------------------------

@dataclass
class QuoteCreatedEvent(DomainEvent):
	"""Emitted when a new quote is created in DRAFT status."""
	event_type: str = "crm.quote.created"
	quote_id: str = ""
	quote_number: str = ""
	account_id: str = ""
	opportunity_id: str = ""
	owner_id: str = ""
	total_cents: int = 0
	currency_code: str = ""


@dataclass
class QuoteSentEvent(DomainEvent):
	"""Emitted when a quote is sent to the customer (DRAFT → SENT)."""
	event_type: str = "crm.quote.sent"
	quote_id: str = ""
	quote_number: str = ""
	account_id: str = ""
	opportunity_id: str = ""
	total_cents: int = 0
	currency_code: str = ""
	valid_until: str = ""     # ISO date string


@dataclass
class QuoteAcceptedEvent(DomainEvent):
	"""Emitted when a customer accepts a quote (SENT → ACCEPTED).

	Consumed by: SalesPlugin (advance opportunity to CLOSED_WON),
	             ARPlugin (create invoice from accepted quote).
	"""
	event_type: str = "crm.quote.accepted"
	quote_id: str = ""
	quote_number: str = ""
	account_id: str = ""
	opportunity_id: str = ""
	total_cents: int = 0
	currency_code: str = ""
	accepted_at: str = ""     # ISO datetime string


@dataclass
class QuoteRejectedEvent(DomainEvent):
	"""Emitted when a customer rejects a quote."""
	event_type: str = "crm.quote.rejected"
	quote_id: str = ""
	quote_number: str = ""
	account_id: str = ""
	opportunity_id: str = ""
	total_cents: int = 0
	reason: str = ""


@dataclass
class QuoteExpiredEvent(DomainEvent):
	"""Emitted when a quote passes its valid_until date without a response."""
	event_type: str = "crm.quote.expired"
	quote_id: str = ""
	quote_number: str = ""
	account_id: str = ""
	opportunity_id: str = ""
	total_cents: int = 0
	valid_until: str = ""     # ISO date string


# ---------------------------------------------------------------------------
# Approval events
# ---------------------------------------------------------------------------

@dataclass
class QuoteApprovalRequestedEvent(DomainEvent):
	"""Emitted when a quote is submitted for internal approval."""
	event_type: str = "crm.quote.approval_requested"
	quote_id: str = ""
	quote_number: str = ""
	owner_id: str = ""
	total_cents: int = 0
	currency_code: str = ""
	discount_cents: int = 0


@dataclass
class QuoteApprovedEvent(DomainEvent):
	"""Emitted when an approver approves a quote."""
	event_type: str = "crm.quote.approved"
	quote_id: str = ""
	quote_number: str = ""
	approved_by: str = ""
	approved_at: str = ""     # ISO datetime string


@dataclass
class QuoteApprovalRejectedEvent(DomainEvent):
	"""Emitted when an approver rejects a quote."""
	event_type: str = "crm.quote.approval_rejected"
	quote_id: str = ""
	quote_number: str = ""
	rejected_by: str = ""
	reason: str = ""


__all__ = [
	"QuoteCreatedEvent",
	"QuoteSentEvent",
	"QuoteAcceptedEvent",
	"QuoteRejectedEvent",
	"QuoteExpiredEvent",
	"QuoteApprovalRequestedEvent",
	"QuoteApprovedEvent",
	"QuoteApprovalRejectedEvent",
]
