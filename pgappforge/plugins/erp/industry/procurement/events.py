"""
pgappforge/plugins/erp/industry/procurement/events.py

Domain events for the Public Procurement plugin.

Events emitted:
  procurement.tender.published       — tender notice made public
  procurement.bid.submitted          — supplier bid received
  procurement.bid.evaluated          — bids scored and ranked
  procurement.contract.awarded       — contract created from winning bid
  procurement.contract.milestone.met — milestone marked achieved
  procurement.contract.payment.made  — payment recorded (immutable)
"""
from __future__ import annotations

from dataclasses import dataclass

from pgappforge.plugins.erp.foundation.events import DomainEvent


@dataclass
class TenderPublishedEvent(DomainEvent):
	event_type: str = "procurement.tender.published"
	tender_id: str = ""
	ocid: str = ""
	procuring_entity_id: str = ""
	procurement_method: str = ""
	main_procurement_category: str = ""
	tender_value_estimate_cents: int = 0
	currency_code: str = ""
	deadline_date: str = ""  # ISO datetime string


@dataclass
class BidSubmittedEvent(DomainEvent):
	event_type: str = "procurement.bid.submitted"
	bid_id: str = ""
	tender_id: str = ""
	bidder_id: str = ""
	bid_price_cents: int = 0
	currency_code: str = ""
	submission_date: str = ""  # ISO datetime string


@dataclass
class BidsEvaluatedEvent(DomainEvent):
	event_type: str = "procurement.bid.evaluated"
	tender_id: str = ""
	ocid: str = ""
	bid_count: int = 0
	ranked_bids: list = None  # list of {bid_id, overall_score, rank}

	def __post_init__(self):
		if self.ranked_bids is None:
			self.ranked_bids = []


@dataclass
class ContractAwardedEvent(DomainEvent):
	event_type: str = "procurement.contract.awarded"
	contract_id: str = ""
	tender_id: str = ""
	ocid: str = ""
	bid_id: str = ""
	supplier_id: str = ""
	contract_value_cents: int = 0
	currency_code: str = ""
	award_id: str = ""


@dataclass
class MilestoneMet(DomainEvent):
	event_type: str = "procurement.contract.milestone.met"
	milestone_id: str = ""
	contract_id: str = ""
	title: str = ""
	milestone_type: str = ""
	achieved_date: str = ""  # ISO date string
	payment_pct: str = ""    # Decimal string


@dataclass
class ContractPaymentMadeEvent(DomainEvent):
	event_type: str = "procurement.contract.payment.made"
	payment_id: str = ""
	contract_id: str = ""
	milestone_id: str = ""
	payment_date: str = ""   # ISO date string
	amount_cents: int = 0
	invoice_reference: str = ""


__all__ = [
	"TenderPublishedEvent",
	"BidSubmittedEvent",
	"BidsEvaluatedEvent",
	"ContractAwardedEvent",
	"MilestoneMet",
	"ContractPaymentMadeEvent",
]
