"""
pgappforge/plugins/erp/finance/material_ledger/events.py

Domain events for the Material Ledger / Actual Costing plugin.

Emitted events:
  material_ledger.period_opened          — new costing period opened
  material_ledger.period_closed          — period closed, actual costs settled
  material_ledger.price_variance_posted  — purchase price variance captured
  material_ledger.cost_revalued          — material cost revalued to actual
  material_ledger.settlement_run         — multi-level cost settlement executed
"""
from __future__ import annotations

from dataclasses import dataclass

from pgappforge.plugins.erp.foundation.events import DomainEvent, emit_event


@dataclass
class MaterialPeriodOpenedEvent(DomainEvent):
	event_type: str = "material_ledger.period_opened"
	period_id: str = ""
	plant_id: str = ""
	fiscal_year: int = 0
	period_number: int = 0
	period_start: str = ""
	period_end: str = ""


@dataclass
class MaterialPeriodClosedEvent(DomainEvent):
	event_type: str = "material_ledger.period_closed"
	period_id: str = ""
	plant_id: str = ""
	fiscal_year: int = 0
	period_number: int = 0
	materials_settled: int = 0
	total_variance_cents: int = 0


@dataclass
class PriceVariancePostedEvent(DomainEvent):
	event_type: str = "material_ledger.price_variance_posted"
	movement_id: str = ""
	material_id: str = ""
	plant_id: str = ""
	variance_cents: int = 0
	variance_type: str = ""   # PURCHASE | PRODUCTION | EXCHANGE_RATE
	posting_date: str = ""


@dataclass
class MaterialCostRevaluedEvent(DomainEvent):
	event_type: str = "material_ledger.cost_revalued"
	material_id: str = ""
	plant_id: str = ""
	period_id: str = ""
	standard_price_cents: int = 0
	actual_price_cents: int = 0
	revaluation_cents: int = 0


@dataclass
class CostSettlementRunEvent(DomainEvent):
	event_type: str = "material_ledger.settlement_run"
	run_id: str = ""
	period_id: str = ""
	plant_id: str = ""
	levels_processed: int = 0
	materials_processed: int = 0
	run_at: str = ""


__all__ = [
	"MaterialPeriodOpenedEvent",
	"MaterialPeriodClosedEvent",
	"PriceVariancePostedEvent",
	"MaterialCostRevaluedEvent",
	"CostSettlementRunEvent",
	"emit_event",
]
