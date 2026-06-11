"""
pgappforge/plugins/fintech/agency/__init__.py

AgencyPlugin — agency banking plugin.

Registers
---------
  - AgencyOutletView     (Agency Banking > Outlets)
  - AgencyAgentView      (Agency Banking > Agents)
  - AgencyTransactionView (Agency Banking > Transactions, read-only)
  - AgencyDashboardView  (Agency Banking > Dashboard)

Events emitted
--------------
  agency.agent.accredited, agency.float.topped_up, agency.transaction,
  agency.commission.settled, agency.outlet.suspended

Depends on
----------
  foundation, core_banking
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class AgencyPlugin(BasePlugin):
	"""Agency banking plugin.

	Manages agent outlets, agent accreditation, float lifecycle,
	transaction processing, and commission settlement.
	"""

	name = "agency_banking"
	domain = "fintech"
	depends_on: list[str] = ["foundation", "core_banking"]

	# ------------------------------------------------------------------
	# BasePlugin.metadata (required abstract property)
	# ------------------------------------------------------------------

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="agency_banking",
			version="1.0.0",
			description=(
				"Agency Banking — outlet onboarding, agent KYC and accreditation, "
				"float management, transaction processing (CASH_IN / CASH_OUT / "
				"BILL_PAYMENT / REMITTANCE / etc.), and periodic commission settlement."
			),
			author="PgAppForge Contributors",
			tags=["fintech", "agency-banking", "float", "agents", "commissions"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_agency_outlet_list",
				"can_agency_outlet_write",
				"can_agency_agent_list",
				"can_agency_agent_write",
				"can_agency_transaction_list",
				"can_agency_float_manage",
				"can_agency_commission_settle",
				"can_agency_dashboard",
			],
			safe_mode_compatible=True,
		)

	# ------------------------------------------------------------------
	# Events
	# ------------------------------------------------------------------

	def get_events(self) -> list[str]:
		from pgappforge.plugins.fintech.agency.events import ALL_AGENCY_EVENT_TYPES
		return ALL_AGENCY_EVENT_TYPES

	def subscribe_to(self) -> list[str]:
		return []

	# ------------------------------------------------------------------
	# Lifecycle
	# ------------------------------------------------------------------

	def initialize(self) -> None:
		"""Merge config defaults."""
		defaults: dict[str, Any] = {
			"AGENCY_MENU_CATEGORY": "Agency Banking",
			"AGENCY_SCHEDULER_ENABLED": True,
			"AGENCY_DEFAULT_CURRENCY": "KES",
			# Withholding tax on agent commissions (%)
			"AGENCY_WHT_RATE": "15",
			# Override per service — dict[str, str] (Decimal-parseable)
			"AGENCY_COMMISSION_RATES": None,
		}
		self.config = {**defaults, **self.config}
		log.info("AgencyPlugin initialised (config: %s)", list(self.config))

	def post_initialize(self) -> None:
		"""Register AgencyTransaction immutability after all models are loaded."""
		from pgappforge.plugins.fintech.agency.models import AgencyTransaction
		AgencyTransaction._register_immutability()

	def register_views(self) -> None:
		from pgappforge.plugins.fintech.agency.views import (
			AgencyAgentView,
			AgencyDashboardView,
			AgencyOutletView,
			AgencyTransactionView,
		)

		cat = self.config.get("AGENCY_MENU_CATEGORY", "Agency Banking")

		self.add_view(
			AgencyOutletView,
			"Outlets",
			icon="fa-store",
			category=cat,
		)
		self.add_view(
			AgencyAgentView,
			"Agents",
			icon="fa-user-tie",
			category=cat,
		)
		self.add_view(
			AgencyTransactionView,
			"Transactions",
			icon="fa-exchange-alt",
			category=cat,
		)
		self.add_view(
			AgencyDashboardView,
			"Dashboard",
			icon="fa-tachometer-alt",
			category=cat,
		)

		log.info("AgencyPlugin: views registered under category %r", cat)

	def register_models(self) -> list:
		from pgappforge.plugins.fintech.agency.models import (
			AgencyAgent,
			AgencyCommission,
			AgencyFloat,
			AgencyOutlet,
			AgencyTransaction,
		)
		return [
			AgencyOutlet,
			AgencyAgent,
			AgencyTransaction,
			AgencyFloat,
			AgencyCommission,
		]

	def register_schedules(self) -> None:
		"""Register monthly commission settlement job.

		Skipped if AGENCY_SCHEDULER_ENABLED=False or APScheduler not installed.
		"""
		if not self.config.get("AGENCY_SCHEDULER_ENABLED", True):
			log.info("AgencyPlugin: AGENCY_SCHEDULER_ENABLED=False — skipping scheduler")
			return

		try:
			from apscheduler.schedulers.background import BackgroundScheduler  # type: ignore
			from apscheduler.triggers.cron import CronTrigger  # type: ignore
		except ImportError:
			log.warning(
				"AgencyPlugin.register_schedules: APScheduler not installed — "
				"commission settlement job will not run automatically."
			)
			return

		try:
			from flask import current_app
			app = current_app._get_current_object()  # type: ignore[attr-defined]
		except RuntimeError:
			log.warning("AgencyPlugin.register_schedules: no app context — skipping")
			return

		scheduler: BackgroundScheduler = getattr(app, "_agency_scheduler", None)  # type: ignore
		if scheduler is None:
			scheduler = BackgroundScheduler(daemon=True)
			app._agency_scheduler = scheduler  # type: ignore

		def _settle_commissions() -> None:
			import datetime as _dt
			period = _dt.date.today().replace(day=1) - _dt.timedelta(days=1)
			period_str = period.strftime("%Y-%m")
			with app.app_context():
				ab = app.extensions.get("appbuilder")
				if ab is None:
					return
				session = ab.get_session
				try:
					from pgappforge.plugins.fintech.agency.services import AgencyService
					svc = AgencyService(self.config)
					# Settle for all tenants — production: iterate known tenant IDs
					tenant_id = self.config.get("AGENCY_DEFAULT_TENANT_ID", "default")
					records = svc.settle_commissions(period_str, tenant_id, session)
					session.commit()
					log.info(
						"AgencyPlugin: commission settlement %s — %d records",
						period_str,
						len(records),
					)
				except Exception as exc:
					log.error("AgencyPlugin: commission settlement failed: %s", exc, exc_info=True)
					try:
						session.rollback()
					except Exception:
						pass

		scheduler.add_job(
			_settle_commissions,
			CronTrigger(day=2, hour=3, minute=0),
			id="agency_settle_commissions",
			replace_existing=True,
		)

		if not scheduler.running:
			scheduler.start()
			log.info("AgencyPlugin: APScheduler started with commission settlement job")
		else:
			log.info("AgencyPlugin: commission settlement job registered (scheduler already running)")
