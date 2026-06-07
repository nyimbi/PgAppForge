"""
pgappforge/plugins/erp/procurement/trade_compliance/events.py

Trade Compliance domain events.

Events emitted:
  procurement.trade.screened       — entity screened against denied-party lists
  procurement.trade.blocked        — entity matched a sanctions list (MATCH result)
  procurement.trade.hs_lookup      — HS code classified for a product
  procurement.trade.list_refreshed — restriction list downloaded and refreshed
"""
from __future__ import annotations

from dataclasses import dataclass

from pgappforge.plugins.erp.foundation.events import DomainEvent


@dataclass
class EntityScreenedEvent(DomainEvent):
	event_type: str = "procurement.trade.screened"
	entity_name: str = ""
	result: str = ""       # CLEAR / MATCH / POSSIBLE_MATCH
	hit_count: int = 0
	tenant_id: str = ""


@dataclass
class EntityBlockedEvent(DomainEvent):
	event_type: str = "procurement.trade.blocked"
	entity_name: str = ""
	matched_list: str = ""
	matched_entry: str = ""


@dataclass
class HSCodeLookedUpEvent(DomainEvent):
	event_type: str = "procurement.trade.hs_lookup"
	product_code: str = ""
	hs_code: str = ""
	duty_rate_pct: float = 0.0


@dataclass
class TradeListRefreshedEvent(DomainEvent):
	event_type: str = "procurement.trade.list_refreshed"
	list_name: str = ""
	entry_count: int = 0


__all__ = [
	"EntityScreenedEvent",
	"EntityBlockedEvent",
	"HSCodeLookedUpEvent",
	"TradeListRefreshedEvent",
]
