"""
pgappforge/plugins/fintech/bnpl/__init__.py

BNPLPlugin — Buy-Now-Pay-Later plugin.

Depends on foundation, core_banking, and lending (for CRB affordability checks).
The lending dependency is soft: affordability assessment falls back to a simple
heuristic when the lending plugin is not installed.

Registers
---------
  - BNPLMerchantView      (BNPL → Merchants)
  - BNPLApplicationView   (BNPL → Applications)
  - BNPLDashboardView     (BNPL → Dashboard)

Events emitted
--------------
  bnpl.application.approved
  bnpl.application.declined
  bnpl.installment.due
  bnpl.installment.paid
  bnpl.installment.overdue
  bnpl.settlement.paid

BPM actions
-----------
  bnpl.apply
  bnpl.process_installment
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority
from pgappforge.plugins.workflow.engine import BPMActionRegistry

log = logging.getLogger(__name__)


class BNPLPlugin(BasePlugin):
	"""Buy-Now-Pay-Later plugin.

	Class-level attributes:
	    name       = "bnpl"
	    domain     = "fintech"
	    depends_on = ["foundation", "core_banking", "lending"]
	"""

	name = "bnpl"
	domain = "fintech"
	depends_on: list[str] = ["foundation", "core_banking", "lending"]

	# ------------------------------------------------------------------
	# BasePlugin.metadata
	# ------------------------------------------------------------------

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="bnpl",
			version="1.0.0",
			description=(
				"Buy-Now-Pay-Later plugin — merchant onboarding, credit-scored "
				"applications, instalment plan generation (PAY_IN_3/4/MONTHLY/"
				"INVOICE_SPLIT), overdue detection with penalties, and monthly "
				"merchant settlement."
			),
			author="PgAppForge Contributors",
			tags=["fintech", "bnpl", "credit", "installments", "merchant"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_bnpl_merchant_list",
				"can_bnpl_merchant_write",
				"can_bnpl_application_list",
				"can_bnpl_application_show",
				"can_bnpl_dashboard",
			],
			safe_mode_compatible=True,
		)

	# ------------------------------------------------------------------
	# Event bus
	# ------------------------------------------------------------------

	def get_events(self) -> list[str]:
		from pgappforge.plugins.fintech.bnpl.events import ALL_BNPL_EVENT_TYPES
		return ALL_BNPL_EVENT_TYPES

	def subscribe_to(self) -> list[str]:
		return []

	# ------------------------------------------------------------------
	# Lifecycle
	# ------------------------------------------------------------------

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"BNPL_MENU_CATEGORY": "BNPL",
			"BNPL_DEFAULT_TENANT_ID": "default",
			# Number of instalments for MONTHLY plan type
			"BNPL_MONTHLY_INSTALLMENTS": 6,
			"BNPL_SCHEDULER_ENABLED": True,
		}
		self.config = {**defaults, **self.config}
		log.info("BNPLPlugin initialised (config keys: %s)", list(self.config))

	def post_initialize(self) -> None:
		"""No seed data required for BNPL in v1.0."""
		pass

	def register_views(self) -> None:
		from pgappforge.plugins.fintech.bnpl.views import (
			BNPLApplicationView,
			BNPLDashboardView,
			BNPLMerchantView,
		)

		cat = self.config.get("BNPL_MENU_CATEGORY", "BNPL")

		self.add_view(
			BNPLMerchantView,
			"Merchants",
			icon="fa-store",
			category=cat,
		)
		self.add_view(
			BNPLApplicationView,
			"Applications",
			icon="fa-file-alt",
			category=cat,
		)
		self.add_view(
			BNPLDashboardView,
			"Dashboard",
			icon="fa-tachometer-alt",
			category=cat,
		)

		log.info("BNPLPlugin: views registered under category %r", cat)

	def register_models(self) -> list:
		from pgappforge.plugins.fintech.bnpl.models import (
			BNPLApplication,
			BNPLInstallment,
			BNPLMerchant,
			BNPLMerchantSettlement,
			BNPLPlan,
		)
		return [
			BNPLMerchant,
			BNPLApplication,
			BNPLPlan,
			BNPLInstallment,
			BNPLMerchantSettlement,
		]

	def register_schedules(self) -> None:
		"""Register the daily overdue instalment check batch job.

		Skipped if BNPL_SCHEDULER_ENABLED=False or APScheduler not installed.
		"""
		if not self.config.get("BNPL_SCHEDULER_ENABLED", True):
			log.info("BNPLPlugin: BNPL_SCHEDULER_ENABLED=False — skipping scheduler registration")
			return

		try:
			from apscheduler.schedulers.background import BackgroundScheduler  # type: ignore
			from apscheduler.triggers.cron import CronTrigger  # type: ignore
		except ImportError:
			log.warning(
				"BNPLPlugin.register_schedules: APScheduler not installed — "
				"overdue check will not run automatically."
			)
			return

		try:
			from flask import current_app
			app = current_app._get_current_object()  # type: ignore[attr-defined]
		except RuntimeError:
			log.warning("BNPLPlugin.register_schedules: no app context — skipping")
			return

		scheduler: BackgroundScheduler = getattr(app, "_bnpl_scheduler", None)  # type: ignore
		if scheduler is None:
			scheduler = BackgroundScheduler(daemon=True)
			app._bnpl_scheduler = scheduler  # type: ignore

		def _run_overdue(tenant_id: str) -> None:
			with app.app_context():
				ab = app.extensions.get("appbuilder")
				if ab is None:
					return
				session = ab.get_session
				try:
					from pgappforge.plugins.fintech.bnpl.services import BNPLService
					svc = BNPLService()
					n = svc.run_overdue_check(tenant_id=tenant_id, session=session)
					session.commit()
					log.info("bnpl_overdue_check: marked %d instalments OVERDUE", n)
				except Exception as exc:
					log.error("bnpl_overdue_check failed: %s", exc, exc_info=True)
					try:
						session.rollback()
					except Exception:
						pass

		tenant_id = self.config.get("BNPL_DEFAULT_TENANT_ID", "default")

		scheduler.add_job(
			lambda: _run_overdue(tenant_id),
			CronTrigger(hour=6, minute=0),
			id="bnpl_overdue_check",
			replace_existing=True,
		)

		if not scheduler.running:
			scheduler.start()
			log.info("BNPLPlugin: APScheduler started with overdue check job (daily 06:00)")
		else:
			log.info("BNPLPlugin: overdue check job registered (scheduler already running)")


# ---------------------------------------------------------------------------
# BPM action registrations
# ---------------------------------------------------------------------------

@BPMActionRegistry.register("bnpl.apply", "Submit a BNPL application for a merchant order")
def _bpm_bnpl_apply(
	record_ctx: dict,
	session: Any,
	customer_id: str = "",
	merchant_id: str = "",
	order_amount_cents: int = 0,
	plan_type: str = "PAY_IN_3",
	tenant_id: str = "",
	**kw: Any,
) -> dict:
	try:
		from pgappforge.plugins.fintech.bnpl.services import BNPLService
	except ImportError:
		return {"status": "error", "message": "bnpl plugin not installed"}
	_tenant_id = tenant_id or record_ctx.get("tenant_id", "")
	try:
		svc = BNPLService()
		app = svc.apply(
			customer_id=customer_id,
			merchant_id=merchant_id,
			order_amount_cents=order_amount_cents,
			plan_type=plan_type,
			tenant_id=_tenant_id,
			session=session,
		)
		return {
			"status": "ok",
			"application_id": app.id,
			"application_status": app.status,
			"credit_score": app.credit_score,
			"affordability_score": app.affordability_score,
		}
	except Exception as exc:
		log.warning("bpm bnpl.apply failed: %s", exc)
		return {"status": "error", "message": str(exc)}


@BPMActionRegistry.register("bnpl.process_installment", "Process a BNPL instalment payment")
def _bpm_bnpl_process_installment(
	record_ctx: dict,
	session: Any,
	installment_id: str = "",
	paid_amount_cents: int = 0,
	tenant_id: str = "",
	**kw: Any,
) -> dict:
	try:
		from pgappforge.plugins.fintech.bnpl.services import BNPLService
	except ImportError:
		return {"status": "error", "message": "bnpl plugin not installed"}
	_tenant_id = tenant_id or record_ctx.get("tenant_id", "")
	try:
		svc = BNPLService()
		inst = svc.process_installment(
			installment_id=installment_id,
			paid_amount_cents=paid_amount_cents,
			tenant_id=_tenant_id,
			session=session,
		)
		return {
			"status": "ok",
			"installment_id": inst.id,
			"installment_status": inst.status,
			"paid_amount_cents": inst.paid_amount_cents,
		}
	except Exception as exc:
		log.warning("bpm bnpl.process_installment failed: %s", exc)
		return {"status": "error", "message": str(exc)}


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_plugin(
	appbuilder: Any,
	config: dict[str, Any] | None = None,
) -> BNPLPlugin:
	"""Construct and return a BNPLPlugin.  Does NOT call activate()."""
	return BNPLPlugin(appbuilder, config=config or {})


# ---------------------------------------------------------------------------
# Public API re-exports
# ---------------------------------------------------------------------------

from pgappforge.plugins.fintech.bnpl.models import (  # noqa: E402
	BNPLApplication,
	BNPLInstallment,
	BNPLMerchant,
	BNPLMerchantSettlement,
	BNPLPlan,
)
from pgappforge.plugins.fintech.bnpl.events import (  # noqa: E402
	ALL_BNPL_EVENT_TYPES,
	BNPL_APPLICATION_APPROVED,
	BNPL_APPLICATION_DECLINED,
	BNPL_INSTALLMENT_DUE,
	BNPL_INSTALLMENT_OVERDUE,
	BNPL_INSTALLMENT_PAID,
	BNPL_SETTLEMENT_PAID,
	BNPLApprovedEvent,
	BNPLDeclinedEvent,
	InstallmentDueEvent,
	InstallmentOverdueEvent,
	InstallmentPaidEvent,
	MerchantSettledEvent,
)
from pgappforge.plugins.fintech.bnpl.services import (  # noqa: E402
	ApplicationNotFoundError,
	BNPLError,
	BNPLService,
	InstallmentNotFoundError,
	InvalidApplicationStatusError,
	MerchantNotFoundError,
	SettlementAlreadyExistsError,
)
from pgappforge.plugins.fintech.bnpl.views import (  # noqa: E402
	BNPLApplicationView,
	BNPLDashboardView,
	BNPLMerchantView,
)

__all__ = [
	# plugin
	"BNPLPlugin",
	"create_plugin",
	# models
	"BNPLMerchant",
	"BNPLApplication",
	"BNPLPlan",
	"BNPLInstallment",
	"BNPLMerchantSettlement",
	# events — classes
	"BNPLApprovedEvent",
	"BNPLDeclinedEvent",
	"InstallmentDueEvent",
	"InstallmentPaidEvent",
	"InstallmentOverdueEvent",
	"MerchantSettledEvent",
	# events — constants
	"BNPL_APPLICATION_APPROVED",
	"BNPL_APPLICATION_DECLINED",
	"BNPL_INSTALLMENT_DUE",
	"BNPL_INSTALLMENT_PAID",
	"BNPL_INSTALLMENT_OVERDUE",
	"BNPL_SETTLEMENT_PAID",
	"ALL_BNPL_EVENT_TYPES",
	# services
	"BNPLService",
	"BNPLError",
	"MerchantNotFoundError",
	"ApplicationNotFoundError",
	"InstallmentNotFoundError",
	"InvalidApplicationStatusError",
	"SettlementAlreadyExistsError",
	# views
	"BNPLMerchantView",
	"BNPLApplicationView",
	"BNPLDashboardView",
]
