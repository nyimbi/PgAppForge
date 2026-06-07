"""
pgappforge/plugins/erp/procurement/sourcing/events.py

Domain events for the Strategic Sourcing plugin.

All monetary amounts are integer cents — never float.

Events emitted:
  procurement.sourcing.rfq.created    — RFQ row created in DRAFT status
  procurement.sourcing.rfq.published  — RFQ sent to invited suppliers
  procurement.sourcing.bid.submitted  — supplier bid received
  procurement.sourcing.bid.evaluated  — scoring complete, winning bid identified
  procurement.sourcing.po.awarded     — purchase order raised from winning bid
  procurement.sourcing.rfq.cancelled  — RFQ cancelled before award
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pgappforge.plugins.erp.foundation.events import DomainEvent


# ---------------------------------------------------------------------------
# RFQ events
# ---------------------------------------------------------------------------

@dataclass
class RFQCreatedEvent(DomainEvent):
	"""Emitted when a new RFQ is created in DRAFT status."""
	event_type: str = "procurement.sourcing.rfq.created"
	rfq_id: str = ""
	title: str = ""
	items: list[dict[str, Any]] = field(default_factory=list)
	tenant_id: str = ""


@dataclass
class RFQPublishedEvent(DomainEvent):
	"""Emitted when an RFQ is published and suppliers are notified."""
	event_type: str = "procurement.sourcing.rfq.published"
	rfq_id: str = ""
	invited_supplier_count: int = 0


@dataclass
class RFQCancelledEvent(DomainEvent):
	"""Emitted when an RFQ is cancelled before award."""
	event_type: str = "procurement.sourcing.rfq.cancelled"
	rfq_id: str = ""
	reason: str = ""


# ---------------------------------------------------------------------------
# Bid events
# ---------------------------------------------------------------------------

@dataclass
class BidSubmittedEvent(DomainEvent):
	"""Emitted when a supplier submits a bid against an RFQ."""
	event_type: str = "procurement.sourcing.bid.submitted"
	rfq_id: str = ""
	supplier_id: str = ""
	bid_id: str = ""
	total_cents: int = 0


@dataclass
class BidEvaluatedEvent(DomainEvent):
	"""Emitted after all bids are scored and the best bid is identified."""
	event_type: str = "procurement.sourcing.bid.evaluated"
	rfq_id: str = ""
	winning_bid_id: str = ""
	supplier_id: str = ""
	award_cents: int = 0


# ---------------------------------------------------------------------------
# Award event
# ---------------------------------------------------------------------------

@dataclass
class PurchaseOrderAwardedEvent(DomainEvent):
	"""Emitted when a PO is raised from the winning bid."""
	event_type: str = "procurement.sourcing.po.awarded"
	rfq_id: str = ""
	po_id: str = ""
	supplier_id: str = ""
	total_cents: int = 0


__all__ = [
	"RFQCreatedEvent",
	"RFQPublishedEvent",
	"BidSubmittedEvent",
	"BidEvaluatedEvent",
	"PurchaseOrderAwardedEvent",
	"RFQCancelledEvent",
]
