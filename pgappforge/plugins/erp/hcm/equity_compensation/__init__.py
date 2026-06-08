"""
pgappforge/plugins/erp/hcm/equity_compensation/__init__.py

EquityCompensationPlugin — HCM Equity Compensation ERP plugin.

Full equity lifecycle:
  EquityPlan → EquityGrant → VestingEvent → EquityExercise

Domain: hcm
Depends on: foundation

Events emitted:
  hcm.equity.plan.created
  hcm.equity.grant.created
  hcm.equity.vested
  hcm.equity.exercised
  hcm.equity.forfeited
  hcm.equity.summary.updated

Usage
-----
Add to your app config::

    PGAPPFORGE_PLUGINS = [
        "pgappforge.plugins.erp.foundation",
        "pgappforge.plugins.erp.hcm.equity_compensation",
    ]

Or instantiate directly::

    from pgappforge.plugins.erp.hcm.equity_compensation import EquityCompensationPlugin
    plugin = EquityCompensationPlugin(appbuilder)
    plugin.activate()
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class EquityCompensationPlugin(BasePlugin):
	"""HCM Equity Compensation ERP plugin.

	Manages stock options, RSUs, ESPPs, and SARs with full vesting schedules,
	exercise tracking, and withholding tax computation.
	"""

	name = "equity_compensation"
	domain = "hcm"
	depends_on: list[str] = ["foundation"]

	# ------------------------------------------------------------------
	# Metadata
	# ------------------------------------------------------------------

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="equity_compensation",
			version="1.0.0",
			description=(
				"HCM Equity Compensation — full equity lifecycle: plan management, "
				"grant issuance, graded/cliff/immediate vesting schedules, "
				"option exercise with withholding tax, grant forfeiture, "
				"and equity portfolio summaries."
			),
			author="PgAppForge Contributors",
			tags=["hcm", "equity", "stock-options", "rsu", "espp", "vesting", "compensation"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_equity_plan_list",
				"can_equity_plan_write",
				"can_equity_grant_list",
				"can_equity_grant_write",
				"can_equity_grant_approve",
				"can_equity_vesting_process",
				"can_equity_exercise_create",
				"can_equity_forfeit",
				"can_equity_summary_view",
				"can_equity_reports",
			],
			safe_mode_compatible=True,
		)

	# ------------------------------------------------------------------
	# get_events / subscribe_to
	# ------------------------------------------------------------------

	def get_events(self) -> list[str]:
		return [
			"hcm.equity.plan.created",
			"hcm.equity.grant.created",
			"hcm.equity.vested",
			"hcm.equity.exercised",
			"hcm.equity.forfeited",
			"hcm.equity.summary.updated",
		]

	def subscribe_to(self) -> list[str]:
		return []

	# ------------------------------------------------------------------
	# Lifecycle
	# ------------------------------------------------------------------

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"EQUITY_MENU_CATEGORY": "Equity",
			"EQUITY_DEFAULT_CURRENCY": "USD",
			"EQUITY_DEFAULT_WITHHOLDING_RATE": "0.30",
			"EQUITY_DEFAULT_VESTING_PERIOD_MONTHS": 48,
			"EQUITY_DEFAULT_CLIFF_MONTHS": 12,
			"EQUITY_DEFAULT_EXPIRY_YEARS": 10,
		}
		self.config = {**defaults, **self.config}
		log.info("EquityCompensationPlugin initialised (config keys: %s)", list(self.config))

	def register_models(self) -> list:
		from pgappforge.plugins.erp.hcm.equity_compensation.models import (
			EquityPlan,
			EquityGrant,
			VestingEvent,
			EquityExercise,
		)
		return [EquityPlan, EquityGrant, VestingEvent, EquityExercise]

	def register_views(self) -> None:
		from pgappforge.plugins.erp.hcm.equity_compensation.views import (
			EquityDashboardView,
			EquityGrantView,
			EquityPlanView,
			VestingEventView,
		)
		cat = self.config.get("EQUITY_MENU_CATEGORY", "Equity")
		self.add_view(EquityDashboardView, "Dashboard", icon="fa-tachometer", category=cat)
		self.add_view(EquityPlanView, "Equity Plans", icon="fa-chart-pie", category=cat)
		self.add_view(EquityGrantView, "Grants", icon="fa-gift", category=cat)
		self.add_view(VestingEventView, "Vesting Events", icon="fa-unlock", category=cat)
		log.info("EquityCompensationPlugin: views registered under %r", cat)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_plugin(
	appbuilder: Any,
	config: dict[str, Any] | None = None,
) -> EquityCompensationPlugin:
	return EquityCompensationPlugin(appbuilder, config=config or {})


# ---------------------------------------------------------------------------
# Public re-exports
# ---------------------------------------------------------------------------

from pgappforge.plugins.erp.hcm.equity_compensation.models import (  # noqa: E402
	EquityPlan,
	EquityGrant,
	VestingEvent,
	EquityExercise,
)
from pgappforge.plugins.erp.hcm.equity_compensation.events import (  # noqa: E402
	EquityPlanCreatedEvent,
	EquityGrantCreatedEvent,
	SharesVestedEvent,
	OptionsExercisedEvent,
	GrantForfeitedEvent,
	EquitySummaryUpdatedEvent,
)
from pgappforge.plugins.erp.hcm.equity_compensation.services import (  # noqa: E402
	EquityService,
	EquityServiceError,
	EquityPlanNotFoundError,
	EquityGrantNotFoundError,
	EquityStateError,
	EquityCalculationError,
)

__all__ = [
	# plugin
	"EquityCompensationPlugin",
	"create_plugin",
	# models
	"EquityPlan",
	"EquityGrant",
	"VestingEvent",
	"EquityExercise",
	# events
	"EquityPlanCreatedEvent",
	"EquityGrantCreatedEvent",
	"SharesVestedEvent",
	"OptionsExercisedEvent",
	"GrantForfeitedEvent",
	"EquitySummaryUpdatedEvent",
	# services
	"EquityService",
	"EquityServiceError",
	"EquityPlanNotFoundError",
	"EquityGrantNotFoundError",
	"EquityStateError",
	"EquityCalculationError",
]
