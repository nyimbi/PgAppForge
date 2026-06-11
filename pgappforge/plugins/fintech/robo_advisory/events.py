"""
pgappforge/plugins/fintech/robo_advisory/events.py

Robo Advisory domain events.

All events extend DomainEvent from erp.foundation.events.
Emitted by RoboAdvisoryService; should be persisted atomically within
the same SQLAlchemy session via emit_event().

Event catalogue
---------------
  robo.goal.created               — new investment goal created
  robo.rebalance.triggered        — rebalance recommended and triggered
  robo.goal.achieved              — goal current_amount reached target_amount
  robo.auto_investment.executed   — recurring auto-investment executed for a goal
  robo.drift.detected             — drift threshold exceeded for a goal
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pgappforge.plugins.erp.foundation.events import DomainEvent


# ---------------------------------------------------------------------------
# Goal events
# ---------------------------------------------------------------------------

@dataclass
class GoalCreatedEvent(DomainEvent):
	"""Emitted when a new investment goal is created for a profile."""
	event_type: str = "robo.goal.created"
	goal_id: str = ""
	profile_id: str = ""
	goal_type: str = ""
	goal_name: str = ""
	target_amount_cents: int = 0
	monthly_contribution_cents: int = 0
	model_portfolio_id: str = ""
	tenant_id: str = ""


@dataclass
class GoalAchievedEvent(DomainEvent):
	"""Emitted when current_amount_cents reaches or exceeds target_amount_cents."""
	event_type: str = "robo.goal.achieved"
	goal_id: str = ""
	profile_id: str = ""
	goal_name: str = ""
	target_amount_cents: int = 0
	achieved_amount_cents: int = 0
	tenant_id: str = ""


# ---------------------------------------------------------------------------
# Rebalance events
# ---------------------------------------------------------------------------

@dataclass
class RebalanceTriggeredEvent(DomainEvent):
	"""Emitted when a rebalance is triggered for a goal (post drift detection)."""
	event_type: str = "robo.rebalance.triggered"
	goal_id: str = ""
	drift_report_id: str = ""
	max_drift_pct: float = 0.0
	tenant_id: str = ""


# ---------------------------------------------------------------------------
# Auto-investment events
# ---------------------------------------------------------------------------

@dataclass
class AutoInvestmentExecutedEvent(DomainEvent):
	"""Emitted for each goal that receives an automated investment."""
	event_type: str = "robo.auto_investment.executed"
	profile_id: str = ""
	goal_id: str = ""
	goal_name: str = ""
	amount_cents: int = 0
	method: str = ""    # "wealth_management" | "core_banking_transfer"
	tenant_id: str = ""


# ---------------------------------------------------------------------------
# Drift events
# ---------------------------------------------------------------------------

@dataclass
class DriftDetectedEvent(DomainEvent):
	"""Emitted when drift > 5% is detected for a goal's allocated portfolio."""
	event_type: str = "robo.drift.detected"
	goal_id: str = ""
	drift_report_id: str = ""
	max_drift_pct: float = 0.0
	rebalance_recommended: bool = True
	tenant_id: str = ""


# ---------------------------------------------------------------------------
# Event type constants
# ---------------------------------------------------------------------------

ROBO_GOAL_CREATED = "robo.goal.created"
ROBO_GOAL_ACHIEVED = "robo.goal.achieved"
ROBO_REBALANCE_TRIGGERED = "robo.rebalance.triggered"
ROBO_AUTO_INVESTMENT_EXECUTED = "robo.auto_investment.executed"
ROBO_DRIFT_DETECTED = "robo.drift.detected"

ALL_ROBO_EVENT_TYPES: list[str] = [
	ROBO_GOAL_CREATED,
	ROBO_GOAL_ACHIEVED,
	ROBO_REBALANCE_TRIGGERED,
	ROBO_AUTO_INVESTMENT_EXECUTED,
	ROBO_DRIFT_DETECTED,
]


__all__ = [
	# event classes
	"GoalCreatedEvent",
	"GoalAchievedEvent",
	"RebalanceTriggeredEvent",
	"AutoInvestmentExecutedEvent",
	"DriftDetectedEvent",
	# constants
	"ROBO_GOAL_CREATED",
	"ROBO_GOAL_ACHIEVED",
	"ROBO_REBALANCE_TRIGGERED",
	"ROBO_AUTO_INVESTMENT_EXECUTED",
	"ROBO_DRIFT_DETECTED",
	"ALL_ROBO_EVENT_TYPES",
]
