"""
pgappforge/plugins/erp/finance/intercompany/events.py

Domain events for the Intercompany Posting plugin.

All monetary amounts are integer cents — never float.

Events emitted:
  finance.intercompany.sent                — IC transaction sent from source to target entity
  finance.intercompany.accepted            — target entity accepted and posted the transaction
  finance.intercompany.rejected            — target entity rejected the transaction
  finance.intercompany.reconciliation.run  — reconciliation run completed between two entities
  finance.intercompany.divergence          — IC balances diverge between entity pair
"""
from __future__ import annotations

from dataclasses import dataclass

from pgappforge.plugins.erp.foundation.events import DomainEvent


# ---------------------------------------------------------------------------
# Intercompany transaction lifecycle events
# ---------------------------------------------------------------------------

@dataclass
class ICTransactionSentEvent(DomainEvent):
	"""Emitted when an IC transaction is created and sent to the target entity."""
	event_type: str = "finance.intercompany.sent"
	outbox_id: str = ""
	source_entity_id: str = ""
	target_entity_id: str = ""
	transaction_type: str = ""  # PO_MIRROR / SO_MIRROR / JOURNAL_MIRROR / PAYMENT_MIRROR
	tenant_id: str = ""


@dataclass
class ICTransactionAcceptedEvent(DomainEvent):
	"""Emitted when the target entity accepts and posts a mirror document."""
	event_type: str = "finance.intercompany.accepted"
	inbox_id: str = ""
	outbox_id: str = ""
	created_document_id: str = ""  # ID of the mirror document created at target


@dataclass
class ICTransactionRejectedEvent(DomainEvent):
	"""Emitted when the target entity rejects an incoming IC transaction."""
	event_type: str = "finance.intercompany.rejected"
	outbox_id: str = ""
	reason: str = ""


@dataclass
class ICReconciliationRunEvent(DomainEvent):
	"""Emitted after a reconciliation pass between two IC entities."""
	event_type: str = "finance.intercompany.reconciliation.run"
	entity_id: str = ""
	matched_count: int = 0
	unmatched_count: int = 0


@dataclass
class ICDivergenceDetectedEvent(DomainEvent):
	"""Emitted when IC balances between entity_a and entity_b do not agree."""
	event_type: str = "finance.intercompany.divergence"
	entity_a: str = ""
	entity_b: str = ""
	amount_a_cents: int = 0   # A's receivable from B in cents
	amount_b_cents: int = 0   # B's payable to A in cents (should match amount_a_cents)


__all__ = [
	"ICTransactionSentEvent",
	"ICTransactionAcceptedEvent",
	"ICTransactionRejectedEvent",
	"ICReconciliationRunEvent",
	"ICDivergenceDetectedEvent",
]
