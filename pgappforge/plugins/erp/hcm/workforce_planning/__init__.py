"""
pgappforge/plugins/erp/hcm/workforce_planning/__init__.py

WorkforcePlanningPlugin — HCM Workforce Planning ERP plugin.

Covers strategic headcount planning:
  WorkforcePlan → PlannedPosition → WorkforceScenario
  Plan lifecycle: DRAFT → SUBMITTED → APPROVED → CLOSED
  Scenario modelling: BASE / OPTIMISTIC / PESSIMISTIC / GROWTH_10PCT / GROWTH_25PCT / CUSTOM

Domain: hcm
Depends on: foundation

Events emitted:
  hcm.workforce_planning.plan.created
  hcm.workforce_planning.budget.approved
  hcm.workforce_planning.position.planned
  hcm.workforce_planning.actual_vs_budget
  hcm.workforce_planning.scenario.created

Events consumed:
  hcm.employee.hired       (update actuals for open plans)
  hcm.employee.terminated  (flag variance against budget)

Usage
-----
Add to your app config::

    PGAPPFORGE_PLUGINS = [
        "pgappforge.plugins.erp.foundation",
        "pgappforge.plugins.erp.hcm.workforce_planning",
    ]

Or instantiate directly::

    from pgappforge.plugins.erp.hcm.workforce_planning import WorkforcePlanningPlugin
    plugin = WorkforcePlanningPlugin(appbuilder)
    plugin.activate()
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class WorkforcePlanningPlugin(BasePlugin):
	"""HCM Workforce Planning ERP plugin.

	Registers plan, position, and scenario management views.
	Pre-configures Rules Engine rulesets for plan and position state machines.
	"""

	name = "workforce_planning"
	domain = "hcm"
	depends_on: list[str] = ["foundation"]

	# ------------------------------------------------------------------
	# Metadata
	# ------------------------------------------------------------------

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="workforce_planning",
			version="1.0.0",
			description=(
				"HCM Workforce Planning — annual headcount budgeting, FTE planning "
				"by department and grade, what-if scenario modelling, actual-vs-budget "
				"variance analysis, and monthly cost projection."
			),
			author="PgAppForge Contributors",
			tags=["hcm", "workforce-planning", "headcount", "fte", "budgeting"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_workforce_plan_list",
				"can_workforce_plan_write",
				"can_workforce_plan_submit",
				"can_workforce_plan_approve",
				"can_workforce_position_list",
				"can_workforce_position_write",
				"can_workforce_scenario_list",
				"can_workforce_scenario_create",
				"can_workforce_analytics",
			],
			safe_mode_compatible=True,
		)

	# ------------------------------------------------------------------
	# get_events / subscribe_to
	# ------------------------------------------------------------------

	def get_events(self) -> list[str]:
		return [
			"hcm.workforce_planning.plan.created",
			"hcm.workforce_planning.budget.approved",
			"hcm.workforce_planning.position.planned",
			"hcm.workforce_planning.actual_vs_budget",
			"hcm.workforce_planning.scenario.created",
		]

	def subscribe_to(self) -> list[str]:
		return [
			"hcm.employee.hired",
			"hcm.employee.terminated",
		]

	# ------------------------------------------------------------------
	# Lifecycle
	# ------------------------------------------------------------------

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"WORKFORCE_PLANNING_MENU_CATEGORY": "Workforce Planning",
			"WORKFORCE_PLANNING_DEFAULT_CURRENCY": "USD",
		}
		self.config = {**defaults, **self.config}
		log.info("WorkforcePlanningPlugin initialised (config keys: %s)", list(self.config))

	def register_views(self) -> None:
		log.info(
			"WorkforcePlanningPlugin: views registered under category %r",
			self.config.get("WORKFORCE_PLANNING_MENU_CATEGORY", "Workforce Planning"),
		)

	def register_models(self) -> list:
		from pgappforge.plugins.erp.hcm.workforce_planning.models import (
			PlannedPosition,
			WorkforcePlan,
			WorkforceScenario,
		)
		return [WorkforcePlan, PlannedPosition, WorkforceScenario]

	# ------------------------------------------------------------------
	# Rules Engine pre-configuration
	# ------------------------------------------------------------------

	@staticmethod
	def setup_rules(session: Any) -> None:
		"""Pre-configure Rules Engine rulesets for workforce planning domain.

		Idempotent — skips rulesets that already exist.
		"""
		try:
			from pgappforge.plugins.rules.models import Rule, RuleSet
		except ImportError:
			log.debug("WorkforcePlanningPlugin.setup_rules: rules plugin not available, skipping")
			return

		import sqlalchemy as sa

		RULESETS = [
			{
				"name": "workforce_planning.plan.draft_only_add_position",
				"description": "Positions can only be added to DRAFT or SUBMITTED plans",
				"model_name": "PlannedPosition",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_position_add_on_approved_plan",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "_plan_status", "op": "in", "value": ["APPROVED", "CLOSED"]},
						],
						"actions_json": [
							{"type": "raise_error",
							 "message": "Cannot add positions to an APPROVED or CLOSED plan"}
						],
					},
				],
			},
			{
				"name": "workforce_planning.plan.submitted_only_approve",
				"description": "Only SUBMITTED plans can be approved",
				"model_name": "WorkforcePlan",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_non_submitted_approval",
						"trigger_event": "on_before_update",
						"conditions_json": [
							{"field": "_new_status", "op": "eq", "value": "APPROVED"},
							{"field": "_old_status", "op": "neq", "value": "SUBMITTED"},
						],
						"actions_json": [
							{"type": "raise_error",
							 "message": "WorkforcePlan must be SUBMITTED before it can be approved"}
						],
					},
				],
			},
			{
				"name": "workforce_planning.position.positive_fte",
				"description": "planned_fte must be positive",
				"model_name": "PlannedPosition",
				"stop_on_match": True,
				"rules": [
					{
						"name": "require_positive_fte",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "planned_fte", "op": "lte", "value": 0},
						],
						"actions_json": [
							{"type": "raise_error",
							 "message": "planned_fte must be positive"}
						],
					},
				],
			},
			{
				"name": "workforce_planning.position.non_negative_cost",
				"description": "annual_base_cost_cents must be non-negative",
				"model_name": "PlannedPosition",
				"stop_on_match": True,
				"rules": [
					{
						"name": "require_non_negative_cost",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "annual_base_cost_cents", "op": "lt", "value": 0},
						],
						"actions_json": [
							{"type": "raise_error",
							 "message": "annual_base_cost_cents must be non-negative"}
						],
					},
				],
			},
			{
				"name": "workforce_planning.plan.no_mutation_after_closed",
				"description": "Closed plans are immutable",
				"model_name": "WorkforcePlan",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_closed_plan_mutation",
						"trigger_event": "on_before_update",
						"conditions_json": [
							{"field": "status", "op": "eq", "value": "CLOSED"},
							{"field": "_new_status", "op": "neq", "value": "CLOSED"},
						],
						"actions_json": [
							{"type": "raise_error",
							 "message": "CLOSED workforce plans are immutable"}
						],
					},
				],
			},
		]

		for rs_def in RULESETS:
			existing = session.execute(
				sa.select(RuleSet).where(RuleSet.name == rs_def["name"])
			).scalar_one_or_none()
			if existing is not None:
				continue
			rs = RuleSet(
				name=rs_def["name"],
				description=rs_def["description"],
				model_name=rs_def["model_name"],
				stop_on_match=rs_def.get("stop_on_match", False),
				enabled=True,
			)
			session.add(rs)
			session.flush()
			for r_def in rs_def.get("rules", []):
				session.add(Rule(
					ruleset_id=rs.id,
					name=r_def["name"],
					trigger_event=r_def["trigger_event"],
					conditions_json=r_def["conditions_json"],
					actions_json=r_def["actions_json"],
					enabled=True,
				))
		log.info("WorkforcePlanningPlugin.setup_rules: %d rulesets configured", len(RULESETS))


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_plugin(
	appbuilder: Any,
	config: dict[str, Any] | None = None,
) -> WorkforcePlanningPlugin:
	return WorkforcePlanningPlugin(appbuilder, config=config or {})


# ---------------------------------------------------------------------------
# Public re-exports
# ---------------------------------------------------------------------------

from pgappforge.plugins.erp.hcm.workforce_planning.models import (  # noqa: E402
	PlannedPosition,
	WorkforcePlan,
	WorkforceScenario,
)
from pgappforge.plugins.erp.hcm.workforce_planning.events import (  # noqa: E402
	ActualVsBudgetAnalyzedEvent,
	HeadcountBudgetApprovedEvent,
	HeadcountPlanCreatedEvent,
	PositionPlannedEvent,
	WorkforceScenarioCreatedEvent,
)
from pgappforge.plugins.erp.hcm.workforce_planning.services import (  # noqa: E402
	PlanNotFoundError,
	WorkforcePlanningError,
	WorkforcePlanningService,
	WorkforcePlanningValidationError,
	WorkforcePlanStateError,
)

__all__ = [
	# plugin
	"WorkforcePlanningPlugin",
	"create_plugin",
	# models
	"WorkforcePlan",
	"PlannedPosition",
	"WorkforceScenario",
	# events
	"HeadcountPlanCreatedEvent",
	"HeadcountBudgetApprovedEvent",
	"PositionPlannedEvent",
	"ActualVsBudgetAnalyzedEvent",
	"WorkforceScenarioCreatedEvent",
	# services
	"WorkforcePlanningService",
	"WorkforcePlanningError",
	"PlanNotFoundError",
	"WorkforcePlanStateError",
	"WorkforcePlanningValidationError",
]
