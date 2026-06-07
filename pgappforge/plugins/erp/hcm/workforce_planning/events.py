"""
pgappforge/plugins/erp/hcm/workforce_planning/events.py

Domain events for the HCM Workforce Planning plugin.

All monetary amounts are integer cents — never float.
FTE values are float (e.g. 2.5 = 2.5 full-time equivalents).

Events emitted:
  hcm.workforce_planning.plan.created        — new headcount plan created
  hcm.workforce_planning.budget.approved     — plan budget approved by authorised user
  hcm.workforce_planning.position.planned    — position added to a plan
  hcm.workforce_planning.actual_vs_budget    — actual vs budget analysis completed
  hcm.workforce_planning.scenario.created    — what-if scenario generated from plan

Events consumed:
  hcm.employee.hired       — update actuals for active plans
  hcm.employee.terminated  — update actuals / flag variance
"""
from __future__ import annotations

from dataclasses import dataclass

from pgappforge.plugins.erp.foundation.events import DomainEvent


@dataclass
class HeadcountPlanCreatedEvent(DomainEvent):
	"""Emitted when a new workforce headcount plan is created."""
	event_type: str = "hcm.workforce_planning.plan.created"
	plan_id: str = ""
	entity_id: str = ""
	period: str = ""
	tenant_id: str = ""


@dataclass
class HeadcountBudgetApprovedEvent(DomainEvent):
	"""Emitted when a headcount plan budget is approved."""
	event_type: str = "hcm.workforce_planning.budget.approved"
	plan_id: str = ""
	approved_by: str = ""
	total_fte: float = 0.0
	total_cost_cents: int = 0


@dataclass
class PositionPlannedEvent(DomainEvent):
	"""Emitted when a planned position is added to a workforce plan."""
	event_type: str = "hcm.workforce_planning.position.planned"
	plan_id: str = ""
	position_code: str = ""
	fte_count: float = 0.0
	cost_cents: int = 0


@dataclass
class ActualVsBudgetAnalyzedEvent(DomainEvent):
	"""Emitted after actual-vs-budget analysis completes for a plan period."""
	event_type: str = "hcm.workforce_planning.actual_vs_budget"
	plan_id: str = ""
	period: str = ""
	variance_fte: float = 0.0
	variance_cost_cents: int = 0


@dataclass
class WorkforceScenarioCreatedEvent(DomainEvent):
	"""Emitted when a what-if scenario is generated from a workforce plan."""
	event_type: str = "hcm.workforce_planning.scenario.created"
	scenario_id: str = ""
	plan_id: str = ""
	scenario_type: str = ""


__all__ = [
	"HeadcountPlanCreatedEvent",
	"HeadcountBudgetApprovedEvent",
	"PositionPlannedEvent",
	"ActualVsBudgetAnalyzedEvent",
	"WorkforceScenarioCreatedEvent",
]
