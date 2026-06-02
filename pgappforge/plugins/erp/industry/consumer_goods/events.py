"""
pgappforge/plugins/erp/industry/consumer_goods/events.py

Domain events for the Consumer Goods plugin.

Events emitted:
  consumer_goods.promotion.approved       — trade promo approved for execution
  consumer_goods.promotion.claim_submitted — retailer submits a claim
  consumer_goods.promotion.claim_paid     — claim settled
  consumer_goods.retail.visit_submitted   — field visit audit submitted
  consumer_goods.planogram.updated        — planogram version changed
"""
from __future__ import annotations

from dataclasses import dataclass

from pgappforge.plugins.erp.foundation.events import DomainEvent


@dataclass
class PromotionApprovedEvent(DomainEvent):
	event_type: str = "consumer_goods.promotion.approved"
	promo_id: str = ""
	promo_number: str = ""
	promo_type: str = ""
	budget_cents: int = 0
	currency: str = ""
	retailer_id: str = ""


@dataclass
class PromotionClaimSubmittedEvent(DomainEvent):
	event_type: str = "consumer_goods.promotion.claim_submitted"
	claim_id: str = ""
	promo_id: str = ""
	retailer_id: str = ""
	actual_spend_cents: int = 0
	currency: str = ""


@dataclass
class PromotionClaimPaidEvent(DomainEvent):
	event_type: str = "consumer_goods.promotion.claim_paid"
	claim_id: str = ""
	promo_id: str = ""
	paid_cents: int = 0
	currency: str = ""


@dataclass
class RetailVisitSubmittedEvent(DomainEvent):
	event_type: str = "consumer_goods.retail.visit_submitted"
	visit_id: str = ""
	store_id: str = ""
	auditor_id: str = ""
	visit_date: str = ""   # ISO date
	overall_score: str = ""  # Decimal string


@dataclass
class PlanoGramUpdatedEvent(DomainEvent):
	event_type: str = "consumer_goods.planogram.updated"
	planogram_id: str = ""
	product_id: str = ""
	store_type: str = ""
	facing_count: int = 0


__all__ = [
	"PromotionApprovedEvent",
	"PromotionClaimSubmittedEvent",
	"PromotionClaimPaidEvent",
	"RetailVisitSubmittedEvent",
	"PlanoGramUpdatedEvent",
]
