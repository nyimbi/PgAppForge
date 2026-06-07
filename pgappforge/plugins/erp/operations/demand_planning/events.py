"""
pgappforge/plugins/erp/operations/demand_planning/events.py

Domain events for the Demand Planning plugin.

Quantities are Decimal-compatible strings — never float.
Events emitted:
  ops.demand_planning.forecast.created   — new demand forecast generated
  ops.demand_planning.forecast.approved  — forecast approved by planner
  ops.demand_planning.consensus.reached  — consensus demand planning cycle closed
  ops.demand_planning.accuracy.computed  — forecast accuracy KPIs computed
"""
from __future__ import annotations

from dataclasses import dataclass, field

from pgappforge.plugins.erp.foundation.events import DomainEvent


@dataclass
class ForecastCreatedEvent(DomainEvent):
	"""Emitted when a new demand forecast is generated for a product."""
	event_type: str = "ops.demand_planning.forecast.created"
	forecast_id: str = ""
	product_id: str = ""
	periods: int = 0		# horizon_periods count
	forecast_method: str = ""
	base_period: str = ""
	tenant_id: str = ""


@dataclass
class ForecastApprovedEvent(DomainEvent):
	"""Emitted when a planner approves a demand forecast."""
	event_type: str = "ops.demand_planning.forecast.approved"
	forecast_id: str = ""
	approved_by: str = ""
	product_id: str = ""
	base_period: str = ""


@dataclass
class ConsensusReachedEvent(DomainEvent):
	"""Emitted when a consensus demand planning cycle is closed."""
	event_type: str = "ops.demand_planning.consensus.reached"
	cycle_id: str = ""
	product_count: int = 0
	total_demand: str = ""		# Decimal string — sum of all approved forecast qtys
	period: str = ""


@dataclass
class ForecastAccuracyComputedEvent(DomainEvent):
	"""Emitted when forecast accuracy KPIs are computed for a product and period range."""
	event_type: str = "ops.demand_planning.accuracy.computed"
	product_id: str = ""
	mape_pct: str = ""		# Decimal string — Mean Absolute Percentage Error
	bias_pct: str = ""		# Decimal string — signed bias
	period: str = ""		# from_period / to_period range label
	periods_evaluated: int = 0


__all__ = [
	"ForecastCreatedEvent",
	"ForecastApprovedEvent",
	"ConsensusReachedEvent",
	"ForecastAccuracyComputedEvent",
]
