"""
pgappforge/plugins/erp/finance/fpa/__init__.py

FP&A — budget cycles, driver-based budgeting, rolling forecasts, scenario
modeling, variance analysis.

Provides:
  - BudgetCycle: named planning rounds (ANNUAL / QUARTERLY / ROLLING_12M)
  - BudgetVersion: ORIGINAL, REVISED, FORECAST, WORKING snapshots per cycle
  - BudgetLine: per-account × cost-centre × period-month budget amounts
  - BudgetDriver: reusable formulas (HEADCOUNT, VOLUME, RATE, PERCENTAGE, FORMULA)
  - ScenarioModel: what-if overlays (OPTIMISTIC / BASE / PESSIMISTIC / STRESS / CUSTOM)
  - ForecastSnapshot: immutable actuals-vs-budget point-in-time records
  - KPITarget: per-period KPI tracking with auto-status (ON_TRACK / AT_RISK / OFF_TRACK)

Business rules enforced:
  - All amounts: integer cents (BigInteger) — never float
  - Locked BudgetVersion rows are immutable
  - Scenario adjustment uses longest-prefix matching on gl_account_code
  - KPI auto-status: ≤5% ON_TRACK, 5–15% AT_RISK, >15% OFF_TRACK
  - ForecastSnapshot rows are never updated — each call inserts new rows

Events emitted:
  - fpa.budget_cycle.opened
  - fpa.budget.approved
  - fpa.forecast_snapshot.taken
  - fpa.scenario.generated
  - fpa.kpi.status_changed
  - fpa.variance.alert

Events consumed:
  - gl.period.closed  (trigger: offer re-seeding / snapshot refresh)

Usage
-----
    PGAPPFORGE_PLUGINS = [
        "pgappforge.plugins.erp.foundation",
        "pgappforge.plugins.erp.finance.gl",
        "pgappforge.plugins.erp.finance.fpa",
    ]
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class FPAPlugin(BasePlugin):
	"""FP&A ERP plugin — budgeting, forecasting, variance analysis.

	Class-level routing metadata:
	    name       = "fpa"
	    domain     = "finance"
	    depends_on = ["foundation", "gl"]
	"""

	name = "fpa"
	domain = "finance"
	depends_on: list[str] = ["foundation", "gl"]

	# ------------------------------------------------------------------
	# BasePlugin.metadata
	# ------------------------------------------------------------------

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="fpa",
			version="1.0.0",
			description=(
				"FP&A — budget cycles, driver-based budgeting, rolling forecasts, "
				"scenario modeling, and variance analysis."
			),
			author="PgAppForge Contributors",
			tags=["erp", "finance", "fpa", "budgeting", "forecasting", "planning"],
			priority=PluginPriority.HIGH,
			permissions=[
				"can_fpa_cycle_read",
				"can_fpa_cycle_write",
				"can_fpa_cycle_approve",
				"can_fpa_version_read",
				"can_fpa_version_write",
				"can_fpa_line_read",
				"can_fpa_line_write",
				"can_fpa_driver_read",
				"can_fpa_driver_write",
				"can_fpa_scenario_read",
				"can_fpa_scenario_write",
				"can_fpa_scenario_generate",
				"can_fpa_snapshot_read",
				"can_fpa_snapshot_take",
				"can_fpa_kpi_read",
				"can_fpa_kpi_write",
				"can_fpa_reports",
			],
			safe_mode_compatible=True,
		)

	# ------------------------------------------------------------------
	# ERP plugin contract
	# ------------------------------------------------------------------

	def get_events(self) -> list[str]:
		"""Events this plugin emits."""
		return [
			"fpa.budget_cycle.opened",
			"fpa.budget.approved",
			"fpa.forecast_snapshot.taken",
			"fpa.scenario.generated",
			"fpa.kpi.status_changed",
			"fpa.variance.alert",
		]

	def subscribe_to(self) -> list[str]:
		"""Events this plugin consumes.

		gl.period.closed — when a GL period closes, offer to refresh forecast
		snapshots and re-seed any open budget versions that are still in DRAFT.
		"""
		return ["gl.period.closed"]

	# ------------------------------------------------------------------
	# Lifecycle
	# ------------------------------------------------------------------

	def initialize(self) -> None:
		"""Merge config defaults and register gl.period.closed handler."""
		defaults: dict[str, Any] = {
			"FPA_MENU_CATEGORY": "FP&A",
			"FPA_DEFAULT_GROWTH_PCT": 5.0,
			"FPA_VARIANCE_ALERT_PCT": 15.0,
			"FPA_KPI_AT_RISK_PCT": 5.0,
			"FPA_KPI_OFF_TRACK_PCT": 15.0,
			"FPA_AUTO_SNAPSHOT_ON_PERIOD_CLOSE": False,
		}
		self.config = {**defaults, **self.config}
		log.info("FPAPlugin initialised (config keys: %s)", list(self.config))

		# Wire up in-process GL event handler
		self._register_gl_handler()

	def post_initialize(self) -> None:
		"""No post-init seeds required for FP&A (data-driven, not rule-seeded)."""
		pass

	def register_views(self) -> None:
		"""Register FP&A views under the configured menu category."""
		# Views are defined in views.py (generated separately).
		# Guard import so the plugin can load even before views exist.
		try:
			from pgappforge.plugins.erp.finance.fpa.views import (
				BudgetCycleView,
				BudgetDriverView,
				BudgetLineView,
				BudgetVersionView,
				FPADashboardView,
				ForecastSnapshotView,
				KPITargetView,
				ScenarioView,
				FPAReportView,
			)
		except ImportError:
			log.warning("FPAPlugin.register_views: views module not available — skipping.")
			return

		cat = self.config.get("FPA_MENU_CATEGORY", "FP&A")

		self.add_view(
			FPADashboardView,
			"FP&A Dashboard",
			icon="fa-dashboard",
			category=cat,
		)
		self.add_view(
			BudgetCycleView,
			"Budget Cycles",
			icon="fa-calendar-check-o",
			category=cat,
		)
		self.add_view(
			BudgetVersionView,
			"Budget Versions",
			icon="fa-code-fork",
			category=cat,
		)
		self.add_view(
			BudgetLineView,
			"Budget Lines",
			icon="fa-table",
			category=cat,
		)
		self.add_view(
			BudgetDriverView,
			"Budget Drivers",
			icon="fa-cogs",
			category=cat,
		)
		self.add_view(
			ScenarioView,
			"Scenarios",
			icon="fa-random",
			category=cat,
		)
		self.add_view(
			ForecastSnapshotView,
			"Forecast Snapshots",
			icon="fa-history",
			category=cat,
		)
		self.add_view(
			KPITargetView,
			"KPI Targets",
			icon="fa-bullseye",
			category=cat,
		)
		self.add_view(
			FPAReportView,
			"FP&A Reports",
			icon="fa-bar-chart",
			category=cat,
		)
		log.info("FPAPlugin: views registered under category %r", cat)

	def register_models(self) -> list:
		"""Model classes for Alembic autogenerate discovery."""
		from pgappforge.plugins.erp.finance.fpa.models import (
			BudgetCycle,
			BudgetDriver,
			BudgetLine,
			BudgetVersion,
			ForecastSnapshot,
			KPITarget,
			ScenarioModel,
		)
		return [
			BudgetCycle,
			BudgetVersion,
			BudgetLine,
			BudgetDriver,
			ScenarioModel,
			ForecastSnapshot,
			KPITarget,
		]

	def activate(self) -> None:
		"""Activate the plugin: calls initialize() then register_models()."""
		self.initialize()
		log.info("FPAPlugin activated.")

	# ------------------------------------------------------------------
	# GL event integration
	# ------------------------------------------------------------------

	def _register_gl_handler(self) -> None:
		"""Subscribe to gl.period.closed in the in-process event bus."""
		try:
			from pgappforge.plugins.erp.foundation.events import subscribe
			subscribe("gl.period.closed", self._on_gl_period_closed)
			log.debug("FPAPlugin: subscribed to gl.period.closed")
		except ImportError:
			log.debug("FPAPlugin._register_gl_handler: foundation events not available.")

	def _on_gl_period_closed(self, event: Any) -> None:
		"""Handle gl.period.closed: optionally auto-take a forecast snapshot.

		Only fires if FPA_AUTO_SNAPSHOT_ON_PERIOD_CLOSE=True and a Flask
		app context is available.  Non-fatal — logs warnings on any failure.
		"""
		if not self.config.get("FPA_AUTO_SNAPSHOT_ON_PERIOD_CLOSE", False):
			return

		try:
			from flask import current_app
			from datetime import date as _date

			ab = current_app.extensions.get("appbuilder")
			if ab is None:
				return

			session = ab.get_session
			tenant_id = getattr(event, "tenant_id", "")
			if not tenant_id:
				return

			from pgappforge.plugins.erp.finance.fpa.models import BudgetCycle
			from pgappforge.plugins.erp.finance.fpa.services import FPAService

			# Find all open cycles for this tenant
			open_cycles = session.execute(
				__import__("sqlalchemy").select(BudgetCycle).where(
					BudgetCycle.tenant_id == tenant_id,
					BudgetCycle.status.in_(["INPUT_OPEN", "UNDER_REVIEW", "APPROVED"]),
				)
			).scalars().all()

			svc = FPAService()
			today = _date.today()
			for cycle in open_cycles:
				try:
					svc.take_forecast_snapshot(session, cycle.id, today, tenant_id)
					session.commit()
					log.info(
						"FPAPlugin._on_gl_period_closed: auto-snapshot taken "
						"for cycle=%r", cycle.id,
					)
				except Exception as exc:
					session.rollback()
					log.warning(
						"FPAPlugin._on_gl_period_closed: snapshot failed for "
						"cycle=%r: %s", cycle.id, exc,
					)
		except RuntimeError:
			pass  # No Flask app context
		except Exception as exc:
			log.warning("FPAPlugin._on_gl_period_closed: non-fatal error: %s", exc)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_plugin(
	appbuilder: Any,
	config: dict[str, Any] | None = None,
) -> FPAPlugin:
	"""Construct and return an FPAPlugin bound to *appbuilder*.

	Does NOT call activate()::

	    plugin = create_plugin(appbuilder)
	    plugin.activate()
	"""
	return FPAPlugin(appbuilder, config=config or {})


# ---------------------------------------------------------------------------
# Public API re-exports
# ---------------------------------------------------------------------------

from pgappforge.plugins.erp.finance.fpa.models import (  # noqa: E402
	BudgetCycle,
	BudgetDriver,
	BudgetLine,
	BudgetVersion,
	ForecastSnapshot,
	KPITarget,
	ScenarioModel,
)
from pgappforge.plugins.erp.finance.fpa.events import (  # noqa: E402
	BudgetApprovedEvent,
	BudgetCycleOpenedEvent,
	ForecastSnapshotTakenEvent,
	KPIStatusChangedEvent,
	ScenarioGeneratedEvent,
	VarianceAlertEvent,
	emit_event,
)
from pgappforge.plugins.erp.finance.fpa.services import (  # noqa: E402
	FPAService,
	FPAServiceError,
	CycleNotFoundError,
	VersionNotFoundError,
	DriverNotFoundError,
	ScenarioNotFoundError,
	VersionLockedError,
	CycleStatusError,
)

__all__ = [
	# plugin
	"FPAPlugin",
	"create_plugin",
	# models
	"BudgetCycle",
	"BudgetVersion",
	"BudgetLine",
	"BudgetDriver",
	"ScenarioModel",
	"ForecastSnapshot",
	"KPITarget",
	# events
	"BudgetCycleOpenedEvent",
	"BudgetApprovedEvent",
	"ForecastSnapshotTakenEvent",
	"ScenarioGeneratedEvent",
	"KPIStatusChangedEvent",
	"VarianceAlertEvent",
	"emit_event",
	# services
	"FPAService",
	"FPAServiceError",
	"CycleNotFoundError",
	"VersionNotFoundError",
	"DriverNotFoundError",
	"ScenarioNotFoundError",
	"VersionLockedError",
	"CycleStatusError",
]
