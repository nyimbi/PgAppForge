"""
pgappforge/plugins/erp/hcm/equity_compensation/events.py

Domain events for the HCM Equity Compensation plugin.

All monetary amounts are integer cents — never float.

Events emitted:
  hcm.equity.plan.created       — equity plan created
  hcm.equity.grant.created      — equity grant issued to employee
  hcm.equity.vested             — shares vested for employee
  hcm.equity.exercised          — stock options exercised
  hcm.equity.forfeited          — unvested grant forfeited
  hcm.equity.summary.updated    — equity summary recalculated
"""
from __future__ import annotations

from dataclasses import dataclass

from pgappforge.plugins.erp.foundation.events import DomainEvent


# ---------------------------------------------------------------------------
# Plan events
# ---------------------------------------------------------------------------

@dataclass
class EquityPlanCreatedEvent(DomainEvent):
	"""Emitted when a new equity plan is created."""
	event_type: str = "hcm.equity.plan.created"
	plan_id: str = ""
	plan_type: str = ""          # STOCK_OPTION | RSU | ESPP | SAR


# ---------------------------------------------------------------------------
# Grant events
# ---------------------------------------------------------------------------

@dataclass
class EquityGrantCreatedEvent(DomainEvent):
	"""Emitted when an equity grant is issued to an employee."""
	event_type: str = "hcm.equity.grant.created"
	grant_id: str = ""
	employee_id: str = ""
	shares: int = 0
	plan_type: str = ""          # STOCK_OPTION | RSU | ESPP | SAR


@dataclass
class SharesVestedEvent(DomainEvent):
	"""Emitted for each vesting event processed."""
	event_type: str = "hcm.equity.vested"
	grant_id: str = ""
	employee_id: str = ""
	shares_vested: int = 0
	vest_date: str = ""          # ISO date


@dataclass
class OptionsExercisedEvent(DomainEvent):
	"""Emitted when stock options are exercised."""
	event_type: str = "hcm.equity.exercised"
	exercise_id: str = ""
	grant_id: str = ""
	employee_id: str = ""
	shares: int = 0
	gain_cents: int = 0          # (fmv - exercise_price) × shares


@dataclass
class GrantForfeitedEvent(DomainEvent):
	"""Emitted when an unvested grant is forfeited."""
	event_type: str = "hcm.equity.forfeited"
	grant_id: str = ""
	employee_id: str = ""
	unvested_shares: int = 0


# ---------------------------------------------------------------------------
# Summary events
# ---------------------------------------------------------------------------

@dataclass
class EquitySummaryUpdatedEvent(DomainEvent):
	"""Emitted after equity summary is recalculated for an employee."""
	event_type: str = "hcm.equity.summary.updated"
	employee_id: str = ""
	total_vested_cents: int = 0
	total_unvested_cents: int = 0


__all__ = [
	"EquityPlanCreatedEvent",
	"EquityGrantCreatedEvent",
	"SharesVestedEvent",
	"OptionsExercisedEvent",
	"GrantForfeitedEvent",
	"EquitySummaryUpdatedEvent",
]
