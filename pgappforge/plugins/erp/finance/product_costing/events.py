"""
pgappforge/plugins/erp/finance/product_costing/events.py

Domain events for the Product Costing plugin.

All monetary fields are integer cents — never float.

Events emitted
--------------
  finance.costing.rollup.completed   — standard cost rollup finished for a product
  finance.costing.actual.computed    — actual vs standard cost computed for a production order
  finance.costing.variance.posted    — cost variance posted to GL
  finance.costing.version.created    — new cost version created (DRAFT)
  finance.costing.standard.released  — standard cost activated and released
"""
from __future__ import annotations

from dataclasses import dataclass

from pgappforge.plugins.erp.foundation.events import DomainEvent


@dataclass
class CostRollUpCompletedEvent(DomainEvent):
	"""Emitted when standard cost rollup completes for a product/version.

	Triggers downstream: inventory revaluation, margin recalculation.
	"""
	event_type: str = "finance.costing.rollup.completed"
	product_id: str = ""
	tenant_id: str = ""
	standard_cost_cents: int = 0
	period: str = ""                # e.g. "2026-Q2" or "2026-06"


@dataclass
class ActualCostComputedEvent(DomainEvent):
	"""Emitted when actual cost for a production order is computed.

	Carries both actual and variance so consumers need not query DB.
	"""
	event_type: str = "finance.costing.actual.computed"
	production_order_id: str = ""
	actual_cost_cents: int = 0
	variance_cents: int = 0         # actual - standard (positive = unfavourable)


@dataclass
class CostVariancePostedEvent(DomainEvent):
	"""Emitted when a cost variance entry is posted to the GL.

	variance_type: PRICE | QTY | TOTAL
	"""
	event_type: str = "finance.costing.variance.posted"
	order_id: str = ""
	variance_cents: int = 0
	variance_type: str = ""         # PRICE | QTY | TOTAL


@dataclass
class CostVersionCreatedEvent(DomainEvent):
	"""Emitted when a new CostVersion record is created in DRAFT status."""
	event_type: str = "finance.costing.version.created"
	version_id: str = ""
	product_id: str = ""
	effective_from: str = ""        # ISO date string


@dataclass
class StandardCostReleasedEvent(DomainEvent):
	"""Emitted when a cost version is set ACTIVE and its standard cost published.

	Triggers: inventory revaluation at new standard, prior version archived.
	"""
	event_type: str = "finance.costing.standard.released"
	product_id: str = ""
	standard_cost_cents: int = 0
	effective_from: str = ""        # ISO date string


__all__ = [
	"CostRollUpCompletedEvent",
	"ActualCostComputedEvent",
	"CostVariancePostedEvent",
	"CostVersionCreatedEvent",
	"StandardCostReleasedEvent",
]
