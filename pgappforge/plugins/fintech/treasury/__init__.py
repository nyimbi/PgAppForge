"""
pgappforge/plugins/fintech/treasury/__init__.py

TreasuryPlugin — FX dealing, open position management, EOD revaluation, P&L.

Registers
---------
  - FXRateView        (Treasury menu)
  - FXDealView        (Treasury menu)
  - FXPositionView    (Treasury menu)
  - TreasuryLimitView (Treasury menu, admin-only)

Events emitted
--------------
  fx.deal.booked, fx.deal.settled, fx.position.revalued, fx.limit.breached

Depends on
----------
  core_banking (for GL posting, GLAccountMapping resolution)

Scheduler jobs
--------------
  treasury_eod_revaluation — daily at 18:00 (after CBK rate upload)
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class TreasuryPlugin(BasePlugin):
	"""Treasury management plugin — FX dealing and position management.

	Class-level attributes:
	    name       = "treasury"
	    domain     = "fintech"
	    depends_on = ["core_banking"]
	"""

	name = "treasury"
	domain = "fintech"
	depends_on: list[str] = ["core_banking"]

	# ------------------------------------------------------------------
	# BasePlugin.metadata
	# ------------------------------------------------------------------

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="treasury",
			version="1.0.0",
			description=(
				"FX & Treasury — buy/sell foreign exchange, manage open FX positions, "
				"daily MTM revaluation with P&L posting, treasury risk limits, "
				"and realised/unrealised P&L reporting."
			),
			author="PgAppForge Contributors",
			tags=["fintech", "treasury", "fx", "forex", "positions", "revaluation", "pnl"],
			priority=PluginPriority.HIGH,
			permissions=[
				"can_fx_rate_list",
				"can_fx_rate_write",
				"can_fx_deal_list",
				"can_fx_deal_book",
				"can_fx_deal_settle",
				"can_fx_position_view",
				"can_fx_limit_list",
				"can_fx_limit_write",
				"can_treasury_pnl_report",
			],
			safe_mode_compatible=True,
		)

	# ------------------------------------------------------------------
	# Events
	# ------------------------------------------------------------------

	def get_events(self) -> list[str]:
		from pgappforge.plugins.fintech.treasury.events import ALL_TREASURY_EVENT_TYPES
		return ALL_TREASURY_EVENT_TYPES

	def subscribe_to(self) -> list[str]:
		# No cross-plugin subscriptions required at this time.
		return []

	def on_event(self, event_type: str, payload: dict, session: Any = None) -> None:
		# Treasury does not consume external events in this release.
		pass

	# ------------------------------------------------------------------
	# Lifecycle
	# ------------------------------------------------------------------

	def initialize(self) -> None:
		"""Merge default config values."""
		defaults: dict[str, Any] = {
			"TREASURY_MENU_CATEGORY": "Treasury",
			"TREASURY_DEFAULT_FUNCTIONAL_CURRENCY": "KES",
			"TREASURY_SCHEDULER_ENABLED": True,
			"TREASURY_EOD_REVALUATION_HOUR": 18,
			"TREASURY_EOD_REVALUATION_MINUTE": 0,
			"TREASURY_DEFAULT_RATE_SOURCE": "CBK",
			# GL overrides (None = use _FX_GL defaults)
			"TREASURY_GL_REVALUATION_PNL": None,
			"TREASURY_GL_REVALUATION_SUSPENSE": None,
		}
		self.config = {**defaults, **self.config}
		log.info("TreasuryPlugin initialised (config: %s)", list(self.config))

	def register_views(self) -> None:
		"""Register treasury views under the configured menu category."""
		from pgappforge.plugins.fintech.treasury.views import (
			FXDealView,
			FXPositionView,
			FXRateView,
			TreasuryLimitView,
		)

		cat = self.config.get("TREASURY_MENU_CATEGORY", "Treasury")

		self.add_view(
			FXRateView,
			"FX Rates",
			icon="fa-exchange",
			category=cat,
		)
		self.add_view(
			FXDealView,
			"FX Deals",
			icon="fa-handshake-o",
			category=cat,
		)
		self.add_view(
			FXPositionView,
			"Open Positions",
			icon="fa-bar-chart",
			category=cat,
		)
		self.add_view(
			TreasuryLimitView,
			"Treasury Limits",
			icon="fa-shield",
			category=cat,
		)

		log.info("TreasuryPlugin: views registered under category %r", cat)

	def register_schedules(self) -> None:
		"""Register APScheduler job for EOD revaluation.

		Skipped if TREASURY_SCHEDULER_ENABLED=False or APScheduler not installed.
		"""
		if not self.config.get("TREASURY_SCHEDULER_ENABLED", True):
			log.info("TreasuryPlugin: TREASURY_SCHEDULER_ENABLED=False — skipping scheduler")
			return

		try:
			from apscheduler.schedulers.background import BackgroundScheduler  # type: ignore
			from apscheduler.triggers.cron import CronTrigger  # type: ignore
		except ImportError:
			log.warning(
				"TreasuryPlugin.register_schedules: APScheduler not installed — "
				"EOD revaluation will not run automatically. "
				"Install apscheduler>=3.10 to enable."
			)
			return

		try:
			from flask import current_app
			app = current_app._get_current_object()  # type: ignore[attr-defined]
		except RuntimeError:
			log.warning("TreasuryPlugin.register_schedules: no app context — skipping")
			return

		scheduler: BackgroundScheduler = getattr(app, "_treasury_scheduler", None)  # type: ignore
		if scheduler is None:
			scheduler = BackgroundScheduler(daemon=True)
			app._treasury_scheduler = scheduler  # type: ignore

		hour = self.config.get("TREASURY_EOD_REVALUATION_HOUR", 18)
		minute = self.config.get("TREASURY_EOD_REVALUATION_MINUTE", 0)
		functional_ccy = self.config.get("TREASURY_DEFAULT_FUNCTIONAL_CURRENCY", "KES")
		rate_source = self.config.get("TREASURY_DEFAULT_RATE_SOURCE", "CBK")

		def _run_revaluation() -> None:
			import datetime as _dt
			with app.app_context():
				ab = app.extensions.get("appbuilder")
				if ab is None:
					log.warning("treasury_eod_revaluation: no appbuilder — skipping")
					return
				session = ab.get_session
				try:
					from pgappforge.plugins.fintech.treasury.services import TreasuryService
					# Revalue positions for all tenants (simplified: single default tenant)
					# Production: iterate over all active tenants from a tenants table.
					tenant_id = self.config.get("TREASURY_DEFAULT_TENANT_ID", "default")
					svc = TreasuryService(session=session, tenant_id=tenant_id)
					result = svc.revalue_positions(
						revaluation_date=_dt.date.today(),
						rate_source=rate_source,
						functional_currency=functional_ccy,
					)
					session.commit()
					log.info("treasury_eod_revaluation completed: %s", result)
				except Exception as exc:
					log.error("treasury_eod_revaluation failed: %s", exc, exc_info=True)
					try:
						session.rollback()
					except Exception:
						pass

		scheduler.add_job(
			_run_revaluation,
			CronTrigger(hour=hour, minute=minute),
			id="treasury_eod_revaluation",
			replace_existing=True,
		)

		if not scheduler.running:
			scheduler.start()
			log.info("TreasuryPlugin: APScheduler started with EOD revaluation job")
		else:
			log.info("TreasuryPlugin: EOD revaluation job registered (scheduler already running)")

	def register_models(self) -> list:
		"""Model classes for Alembic autogenerate discovery."""
		from pgappforge.plugins.fintech.treasury.models import (
			FintechFXDeal,
			FXPosition,
			FXRate,
			TreasuryLimit,
		)
		return [FXRate, FintechFXDeal, FXPosition, TreasuryLimit]


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_plugin(
	appbuilder: Any,
	config: dict[str, Any] | None = None,
) -> TreasuryPlugin:
	"""Construct and return a TreasuryPlugin bound to *appbuilder*.

	Does NOT call activate()::

	    plugin = create_plugin(appbuilder)
	    plugin.activate()
	"""
	return TreasuryPlugin(appbuilder, config=config or {})


# ---------------------------------------------------------------------------
# Public API re-exports
# ---------------------------------------------------------------------------

from pgappforge.plugins.fintech.treasury.models import (  # noqa: E402
	FintechFXDeal,
	FXPosition,
	FXRate,
	TreasuryLimit,
)
from pgappforge.plugins.fintech.treasury.events import (  # noqa: E402
	ALL_TREASURY_EVENT_TYPES,
	FX_DEAL_BOOKED,
	FX_DEAL_SETTLED,
	FX_LIMIT_BREACHED,
	FX_POSITION_REVALUED,
	FXDealBookedEvent,
	FXDealSettledEvent,
	FXLimitBreachedEvent,
	FXPositionRevaluedEvent,
)
from pgappforge.plugins.fintech.treasury.services import (  # noqa: E402
	FXDealNotFoundError,
	FXDealStatusError,
	FXRateNotFoundError,
	TreasuryError,
	TreasuryLimitBreachError,
	TreasuryService,
)

__all__ = [
	# plugin
	"TreasuryPlugin",
	"create_plugin",
	# models
	"FXRate",
	"FintechFXDeal",
	"FXPosition",
	"TreasuryLimit",
	# events — classes
	"FXDealBookedEvent",
	"FXDealSettledEvent",
	"FXPositionRevaluedEvent",
	"FXLimitBreachedEvent",
	# events — constants
	"FX_DEAL_BOOKED",
	"FX_DEAL_SETTLED",
	"FX_POSITION_REVALUED",
	"FX_LIMIT_BREACHED",
	"ALL_TREASURY_EVENT_TYPES",
	# services
	"TreasuryService",
	"TreasuryError",
	"FXDealNotFoundError",
	"FXRateNotFoundError",
	"FXDealStatusError",
	"TreasuryLimitBreachError",
]
