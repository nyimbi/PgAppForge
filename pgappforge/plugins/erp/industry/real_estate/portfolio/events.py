"""
pgappforge/plugins/erp/industry/real_estate/portfolio/events.py

Domain events for the Real Estate Portfolio Analytics sub-plugin.

All monetary fields are integer cents — never float.

Events emitted
--------------
  re_portfolio.distribution.paid      — distribution paid out to investors
  re_portfolio.capex.recorded         — capital expenditure recorded against a property
  re_portfolio.property.acquired      — property added to a portfolio
  re_portfolio.investor.exited        — investor holding transitioned to EXITED
"""
from __future__ import annotations

from dataclasses import dataclass

from pgappforge.plugins.erp.foundation.events import DomainEvent


# ---------------------------------------------------------------------------
# Distribution events
# ---------------------------------------------------------------------------

@dataclass
class DistributionPaidEvent(DomainEvent):
	"""Emitted when a DistributionRecord transitions from DRAFT to PAID."""
	event_type: str = "re_portfolio.distribution.paid"
	portfolio_id: str = ""
	period: str = ""          # "YYYY-MM"
	total_cents: int = 0


# ---------------------------------------------------------------------------
# CapEx events
# ---------------------------------------------------------------------------

@dataclass
class CapExRecordedEvent(DomainEvent):
	"""Emitted when a new CapExRecord is persisted."""
	event_type: str = "re_portfolio.capex.recorded"
	property_id: str = ""
	capex_cents: int = 0
	category: str = ""        # IMPROVEMENT/REPAIR/REPLACEMENT/MAINTENANCE


# ---------------------------------------------------------------------------
# Property acquisition events
# ---------------------------------------------------------------------------

@dataclass
class PropertyAcquiredEvent(DomainEvent):
	"""Emitted when a property is added to a portfolio via add_property()."""
	event_type: str = "re_portfolio.property.acquired"
	portfolio_id: str = ""
	property_id: str = ""
	acquisition_cost_cents: int = 0


# ---------------------------------------------------------------------------
# Investor events
# ---------------------------------------------------------------------------

@dataclass
class InvestorExitedEvent(DomainEvent):
	"""Emitted when an InvestorHolding status transitions to EXITED."""
	event_type: str = "re_portfolio.investor.exited"
	portfolio_id: str = ""
	investor_party_id: str = ""


__all__ = [
	"DistributionPaidEvent",
	"CapExRecordedEvent",
	"PropertyAcquiredEvent",
	"InvestorExitedEvent",
]
