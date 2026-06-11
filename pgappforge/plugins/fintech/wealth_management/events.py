"""
pgappforge/plugins/fintech/wealth_management/events.py

Wealth Management domain events.

All events extend DomainEvent from erp.foundation.events.
They are emitted by WealthManagementService and should be persisted
atomically within the same SQLAlchemy session via emit_event().

Event catalogue
---------------
  wealth.client.onboarded          — new wealth client onboarded
  wealth.portfolio.created         — new portfolio created for a client
  wealth.order.placed              — buy/sell order placed on portfolio
  wealth.order.filled              — order fully or partially filled
  wealth.rebalance.recommended     — rebalance suggested due to drift > 5%
  wealth.performance.report.generated — monthly performance report computed
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pgappforge.plugins.erp.foundation.events import DomainEvent


# ---------------------------------------------------------------------------
# Client events
# ---------------------------------------------------------------------------

@dataclass
class WealthClientOnboardedEvent(DomainEvent):
	"""Emitted when a new wealth client is onboarded."""
	event_type: str = "wealth.client.onboarded"
	client_id: str = ""
	customer_id: str = ""
	full_name: str = ""
	risk_profile: str = ""
	suitability_score: int = 0
	tenant_id: str = ""


# ---------------------------------------------------------------------------
# Portfolio events
# ---------------------------------------------------------------------------

@dataclass
class PortfolioCreatedEvent(DomainEvent):
	"""Emitted when a new portfolio is created for a wealth client."""
	event_type: str = "wealth.portfolio.created"
	portfolio_id: str = ""
	client_id: str = ""
	name: str = ""
	mandate_type: str = ""
	base_currency: str = ""
	tenant_id: str = ""


# ---------------------------------------------------------------------------
# Order events
# ---------------------------------------------------------------------------

@dataclass
class OrderPlacedEvent(DomainEvent):
	"""Emitted when a buy/sell order is placed."""
	event_type: str = "wealth.order.placed"
	order_id: str = ""
	portfolio_id: str = ""
	asset_code: str = ""
	order_side: str = ""
	order_type: str = ""
	quantity: str = ""    # Decimal serialised as string
	amount_cents: int = 0
	tenant_id: str = ""


@dataclass
class OrderFilledEvent(DomainEvent):
	"""Emitted when an order is fully or partially filled."""
	event_type: str = "wealth.order.filled"
	order_id: str = ""
	portfolio_id: str = ""
	asset_code: str = ""
	order_side: str = ""
	executed_quantity: str = ""   # Decimal serialised as string
	executed_price_cents: int = 0
	executed_amount_cents: int = 0
	broker_reference: str = ""
	new_status: str = ""
	tenant_id: str = ""


# ---------------------------------------------------------------------------
# Rebalance events
# ---------------------------------------------------------------------------

@dataclass
class RebalanceRecommendedEvent(DomainEvent):
	"""Emitted when portfolio drift exceeds the 5% threshold."""
	event_type: str = "wealth.rebalance.recommended"
	portfolio_id: str = ""
	drift_summary: list[dict[str, Any]] = field(default_factory=list)
	max_drift_pct: float = 0.0
	tenant_id: str = ""


# ---------------------------------------------------------------------------
# Performance events
# ---------------------------------------------------------------------------

@dataclass
class PerformanceReportGeneratedEvent(DomainEvent):
	"""Emitted when a monthly performance report is generated."""
	event_type: str = "wealth.performance.report.generated"
	report_id: str = ""
	portfolio_id: str = ""
	period: str = ""
	return_pct: str = ""    # Decimal serialised as string
	benchmark_return_pct: str = ""
	tenant_id: str = ""


# ---------------------------------------------------------------------------
# Event type constants
# ---------------------------------------------------------------------------

WLTH_CLIENT_ONBOARDED = "wealth.client.onboarded"
WLTH_PORTFOLIO_CREATED = "wealth.portfolio.created"
WLTH_ORDER_PLACED = "wealth.order.placed"
WLTH_ORDER_FILLED = "wealth.order.filled"
WLTH_REBALANCE_RECOMMENDED = "wealth.rebalance.recommended"
WLTH_PERFORMANCE_REPORT_GENERATED = "wealth.performance.report.generated"

ALL_WLTH_EVENT_TYPES: list[str] = [
	WLTH_CLIENT_ONBOARDED,
	WLTH_PORTFOLIO_CREATED,
	WLTH_ORDER_PLACED,
	WLTH_ORDER_FILLED,
	WLTH_REBALANCE_RECOMMENDED,
	WLTH_PERFORMANCE_REPORT_GENERATED,
]


__all__ = [
	# event classes
	"WealthClientOnboardedEvent",
	"PortfolioCreatedEvent",
	"OrderPlacedEvent",
	"OrderFilledEvent",
	"RebalanceRecommendedEvent",
	"PerformanceReportGeneratedEvent",
	# constants
	"WLTH_CLIENT_ONBOARDED",
	"WLTH_PORTFOLIO_CREATED",
	"WLTH_ORDER_PLACED",
	"WLTH_ORDER_FILLED",
	"WLTH_REBALANCE_RECOMMENDED",
	"WLTH_PERFORMANCE_REPORT_GENERATED",
	"ALL_WLTH_EVENT_TYPES",
]
