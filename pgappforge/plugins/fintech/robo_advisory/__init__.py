"""
pgappforge/plugins/fintech/robo_advisory/__init__.py

RoboAdvisoryPlugin — automated goal-based investing with drift detection.

Registers
---------
  - ModelPortfolioView   (Model Portfolios menu)
  - RoboGoalView         (Goals menu)
  - RoboDashboardView    (/robo/dashboard/)

Events emitted
--------------
  robo.goal.created, robo.goal.achieved,
  robo.rebalance.triggered, robo.auto_investment.executed,
  robo.drift.detected

BPM actions
-----------
  robo.create_goal, robo.execute_auto_investment, robo.detect_drift

Depends on
----------
  foundation, core_banking

post_initialize
---------------
  Calls _try_seed_portfolios() to create 5 default model portfolios if none exist.
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class RoboAdvisoryPlugin(BasePlugin):
	"""Robo Advisory fintech plugin.

	Provides automated goal-based investing, model portfolio assignment,
	drift detection, rebalance recommendations, and auto-investment execution.
	"""

	name = "robo_advisory"
	domain = "fintech"
	depends_on: list[str] = ["foundation", "core_banking"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="robo_advisory",
			version="1.0.0",
			description=(
				"Robo Advisory — automated goal-based investing. "
				"Investor profiles, model portfolio assignment, contribution scheduling, "
				"drift detection with 5%-threshold rebalancing, compound-interest projections, "
				"and automated investment execution."
			),
			author="PgAppForge Contributors",
			tags=["fintech", "robo", "advisory", "goals", "investment", "automation", "drift"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_robo_profile_list",
				"can_robo_profile_write",
				"can_robo_goal_list",
				"can_robo_goal_write",
				"can_robo_model_portfolio_list",
				"can_robo_model_portfolio_write",
				"can_robo_dashboard",
			],
			safe_mode_compatible=True,
		)

	def get_events(self) -> list[str]:
		from pgappforge.plugins.fintech.robo_advisory.events import ALL_ROBO_EVENT_TYPES
		return ALL_ROBO_EVENT_TYPES

	def subscribe_to(self) -> list[str]:
		# Listen for wealth management order fills to update goal current_amount
		return ["wealth.order.filled", "cb.account.credited"]

	def on_event(self, event_type: str, payload: dict, session: Any = None) -> None:
		"""Handle cross-plugin events.

		wealth.order.filled / cb.account.credited — no-op hook for future
		goal balance reconciliation.
		"""
		pass

	# ------------------------------------------------------------------
	# Lifecycle
	# ------------------------------------------------------------------

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"ROBO_MENU_CATEGORY": "Robo Advisory",
			"ROBO_DRIFT_THRESHOLD_PCT": 5.0,
			"ROBO_DEFAULT_CURRENCY": "KES",
			"ROBO_SEED_MODEL_PORTFOLIOS": True,
			"ROBO_SCHEDULER_ENABLED": True,
		}
		self.config = {**defaults, **self.config}
		log.info("RoboAdvisoryPlugin initialised (config: %s)", list(self.config))

	def post_initialize(self) -> None:
		"""Seed default model portfolios if configured."""
		if self.config.get("ROBO_SEED_MODEL_PORTFOLIOS", True):
			self._try_seed_portfolios()

	def register_views(self) -> None:
		from pgappforge.plugins.fintech.robo_advisory.views import (
			ModelPortfolioView,
			RoboDashboardView,
			RoboGoalView,
		)

		cat = self.config.get("ROBO_MENU_CATEGORY", "Robo Advisory")

		self.add_view(
			ModelPortfolioView,
			"Model Portfolios",
			icon="fa-pie-chart",
			category=cat,
		)
		self.add_view(
			RoboGoalView,
			"Investment Goals",
			icon="fa-flag",
			category=cat,
		)
		self.add_view(
			RoboDashboardView,
			"Dashboard",
			icon="fa-dashboard",
			category=cat,
		)

		log.info("RoboAdvisoryPlugin: views registered under category %r", cat)

	def register_models(self) -> list:
		from pgappforge.plugins.fintech.robo_advisory.models import (
			ModelPortfolio,
			RoboDriftReport,
			RoboGoal,
			RoboInvestorProfile,
		)
		return [RoboInvestorProfile, RoboGoal, ModelPortfolio, RoboDriftReport]

	# ------------------------------------------------------------------
	# Seed helpers
	# ------------------------------------------------------------------

	def _try_seed_portfolios(self) -> None:
		"""Attempt to seed default model portfolios; log failures, never raise."""
		try:
			from flask import current_app
			ab = current_app.extensions.get("appbuilder")
			if ab is None:
				return
			session = ab.get_session
			tenant_id = self.config.get("ROBO_DEFAULT_TENANT_ID", "default")

			from pgappforge.plugins.fintech.robo_advisory.services import RoboAdvisoryService
			svc = RoboAdvisoryService()
			n = svc.seed_model_portfolios(tenant_id=tenant_id, session=session)
			if n:
				session.commit()
				log.info("RoboAdvisoryPlugin: seeded %d model portfolios", n)
		except RuntimeError:
			# No app context yet — skip silently
			pass
		except Exception as exc:
			log.warning("RoboAdvisoryPlugin._try_seed_portfolios failed (non-fatal): %s", exc)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_plugin(
	appbuilder: Any,
	config: dict[str, Any] | None = None,
) -> RoboAdvisoryPlugin:
	"""Construct and return a RoboAdvisoryPlugin bound to *appbuilder*."""
	return RoboAdvisoryPlugin(appbuilder, config=config or {})


# ---------------------------------------------------------------------------
# Public API re-exports
# ---------------------------------------------------------------------------

from pgappforge.plugins.fintech.robo_advisory.models import (  # noqa: E402
	ModelPortfolio,
	RoboDriftReport,
	RoboGoal,
	RoboInvestorProfile,
)
from pgappforge.plugins.fintech.robo_advisory.events import (  # noqa: E402
	ALL_ROBO_EVENT_TYPES,
	AutoInvestmentExecutedEvent,
	DriftDetectedEvent,
	GoalAchievedEvent,
	GoalCreatedEvent,
	RebalanceTriggeredEvent,
	ROBO_AUTO_INVESTMENT_EXECUTED,
	ROBO_DRIFT_DETECTED,
	ROBO_GOAL_ACHIEVED,
	ROBO_GOAL_CREATED,
	ROBO_REBALANCE_TRIGGERED,
)
from pgappforge.plugins.fintech.robo_advisory.services import (  # noqa: E402
	GoalNotFoundError,
	ProfileNotFoundError,
	RoboAdvisoryError,
	RoboAdvisoryService,
	SuitabilityError,
)
from pgappforge.plugins.fintech.robo_advisory.views import (  # noqa: E402
	ModelPortfolioView,
	RoboDashboardView,
	RoboGoalView,
)

__all__ = [
	# plugin
	"RoboAdvisoryPlugin",
	"create_plugin",
	# models
	"RoboInvestorProfile",
	"RoboGoal",
	"ModelPortfolio",
	"RoboDriftReport",
	# events — classes
	"GoalCreatedEvent",
	"GoalAchievedEvent",
	"RebalanceTriggeredEvent",
	"AutoInvestmentExecutedEvent",
	"DriftDetectedEvent",
	# events — constants
	"ROBO_GOAL_CREATED",
	"ROBO_GOAL_ACHIEVED",
	"ROBO_REBALANCE_TRIGGERED",
	"ROBO_AUTO_INVESTMENT_EXECUTED",
	"ROBO_DRIFT_DETECTED",
	"ALL_ROBO_EVENT_TYPES",
	# services
	"RoboAdvisoryService",
	"RoboAdvisoryError",
	"ProfileNotFoundError",
	"GoalNotFoundError",
	"SuitabilityError",
	# views
	"ModelPortfolioView",
	"RoboGoalView",
	"RoboDashboardView",
]
