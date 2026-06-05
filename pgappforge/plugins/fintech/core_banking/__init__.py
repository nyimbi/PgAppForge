"""
pgappforge/plugins/fintech/core_banking/__init__.py

CoreBankingPlugin — foundational fintech plugin.

All other fintech plugins (payments, loans, treasury, etc.) declare
depends_on = ["core_banking"].

Registers
---------
  - ProductView       (Bank Products menu)
  - AccountView       (Accounts menu)
  - LedgerView        (Ledger menu, admin-only)
  - InterestAccrualDashboard  (/core-banking/interest/)
  - BalanceSheetView          (/core-banking/balance-sheet/)

Events emitted
--------------
  cb.account.opened, cb.account.credited, cb.account.debited,
  cb.account.transferred, cb.interest.accrued, cb.interest.capitalized,
  cb.account.closed, cb.account.dormant, cb.hold.placed, cb.hold.released

Seed data helpers
-----------------
  CoreBankingPlugin.seed_default_products(session) — inserts 5 common
  product types (SAVINGS, CURRENT, FIXED_DEPOSIT, SME_LOAN, CONSUMER_LOAN)
  if they don't already exist.  Idempotent.
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class CoreBankingPlugin(BasePlugin):
	"""Foundational core banking plugin.

	Class-level attributes used by dependent plugins for dependency resolution:
	    name       = "core_banking"
	    domain     = "fintech"
	    depends_on = ["foundation"]
	"""

	name = "core_banking"
	domain = "fintech"
	depends_on: list[str] = ["foundation"]

	# ------------------------------------------------------------------
	# BasePlugin.metadata (required abstract property)
	# ------------------------------------------------------------------

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="core_banking",
			version="1.0.0",
			description=(
				"Core Banking engine — customer accounts, T-account ledger, "
				"interest accrual and capitalisation, product catalogue, "
				"account holds, and statement generation.  "
				"All other fintech plugins depend on this plugin."
			),
			author="PgAppForge Contributors",
			tags=["fintech", "core-banking", "ledger", "accounts", "interest"],
			priority=PluginPriority.HIGH,
			permissions=[
				"can_cb_product_list",
				"can_cb_product_write",
				"can_cb_account_list",
				"can_cb_account_write",
				"can_cb_account_transact",
				"can_cb_ledger_read",
				"can_cb_interest_dashboard",
				"can_cb_balance_sheet",
			],
			safe_mode_compatible=True,
		)

	# ------------------------------------------------------------------
	# get_events / subscribe_to
	# ------------------------------------------------------------------

	def get_events(self) -> list[str]:
		"""Events this plugin emits."""
		from pgappforge.plugins.fintech.core_banking.events import ALL_CB_EVENT_TYPES
		return ALL_CB_EVENT_TYPES

	def subscribe_to(self) -> list[str]:
		"""Events this plugin consumes."""
		# Cross-plugin: listen for party.created to support customer onboarding
		return ["party.created"]

	def on_event(self, event_type: str, payload: dict, session: Any = None) -> None:
		"""Handle inbound cross-plugin events.

		Currently handled:
		  party.created — optionally auto-open a default savings account if
		    CB_AUTO_OPEN_PRODUCT is configured.  Non-fatal: any error is logged
		    and swallowed so one bad onboarding event cannot crash the bus.
		"""
		if event_type != "party.created":
			return

		product_code = self.config.get("CB_AUTO_OPEN_PRODUCT")
		if not product_code:
			# Auto-open disabled — nothing to do.
			return

		customer_id = payload.get("party_id") or payload.get("id") or payload.get("customer_id")
		if not customer_id:
			log.warning("on_event party.created: no customer_id in payload %r", payload)
			return

		customer_type = payload.get("party_type") or payload.get("customer_type", "")
		eligible_types = {"INDIVIDUAL", "SME", "CORPORATE"}
		if customer_type.upper() not in eligible_types:
			log.debug(
				"on_event party.created: customer_type %r not eligible for auto-open",
				customer_type,
			)
			return

		try:
			from pgappforge.plugins.fintech.core_banking.services import CoreBankingService

			svc = CoreBankingService()
			tenant_id = payload.get("tenant_id", self.config.get("CB_DEFAULT_TENANT_ID", "default"))

			# Use caller-provided session if available; otherwise attempt to get
			# one from the Flask app context.
			_session = session
			if _session is None:
				try:
					from flask import current_app
					ab = current_app.extensions.get("appbuilder")
					_session = ab.get_session if ab else None
				except RuntimeError:
					_session = None

			if _session is None:
				log.warning(
					"on_event party.created: no session available for auto-open, skipping"
				)
				return

			account = svc.open_account(
				session=_session,
				customer_id=customer_id,
				product_code=product_code,
				opening_deposit_cents=0,
				tenant_id=tenant_id,
			)
			_session.flush()
			log.info(
				"on_event party.created: auto-opened account %s for customer %s",
				account.account_number,
				customer_id,
			)
		except Exception as exc:
			log.warning(
				"on_event party.created: auto-open failed for customer %s (non-fatal): %s",
				customer_id,
				exc,
			)

	# ------------------------------------------------------------------
	# Lifecycle
	# ------------------------------------------------------------------

	def initialize(self) -> None:
		"""Merge config defaults."""
		defaults: dict[str, Any] = {
			"CB_MENU_CATEGORY": "Core Banking",
			"CB_SEED_DEFAULT_PRODUCTS": True,
			"CB_DEFAULT_CURRENCY": "KES",
			"CB_DORMANCY_THRESHOLD_DAYS": 365,
			# Tenant-configurable GL: set CB_AUTO_OPEN_PRODUCT to a product_code
			# to auto-open a default account when a party.created event is received.
			# None = disabled (safe default for multi-tenant deployments).
			"CB_AUTO_OPEN_PRODUCT": None,
			# IBAN generation config
			"CB_BANK_CODE": "000000",
			"CB_COUNTRY_CODE": "KE",
			"CB_AUTO_GENERATE_IBAN": False,
			# Scheduler: set False to disable all batch job registration
			"CB_SCHEDULER_ENABLED": True,
		}
		self.config = {**defaults, **self.config}
		log.info("CoreBankingPlugin initialised (config: %s)", list(self.config))

	def post_initialize(self) -> None:
		"""Seed default products if configured."""
		if self.config.get("CB_SEED_DEFAULT_PRODUCTS", True):
			self._try_seed_products()

	def register_views(self) -> None:
		"""Register views under the configured menu category."""
		from pgappforge.plugins.fintech.core_banking.views import (
			AccountActionsView,
			AccountView,
			BalanceSheetView,
			GLAccountMappingView,
			InterestAccrualDashboard,
			LedgerView,
			ProductView,
		)

		cat = self.config.get("CB_MENU_CATEGORY", "Core Banking")

		self.add_view(
			ProductView,
			"Products",
			icon="fa-list-alt",
			category=cat,
		)
		self.add_view(
			AccountView,
			"Accounts",
			icon="fa-university",
			category=cat,
		)
		self.add_view(
			LedgerView,
			"Ledger",
			icon="fa-book",
			category=cat,
		)
		self.add_view(
			InterestAccrualDashboard,
			"Interest Accrual",
			icon="fa-percent",
			category=cat,
		)
		self.add_view(
			BalanceSheetView,
			"Balance Sheet",
			icon="fa-balance-scale",
			category=cat,
		)
		self.add_view(
			AccountActionsView,
			"Account Actions",
			icon="fa-exchange",
			category=cat,
		)
		self.add_view(
			GLAccountMappingView,
			"GL Mappings",
			icon="fa-sitemap",
			category=cat,
		)

		log.info("CoreBankingPlugin: views registered under category %r", cat)

	def register_schedules(self) -> None:
		"""Register APScheduler batch jobs for interest accrual, dormancy,
		hold expiry, and maintenance fees.

		Skipped if CB_SCHEDULER_ENABLED=False or APScheduler is not installed.

		Jobs registered:
		  cb_accrue_interest       — daily at 23:55 (cron)
		  cb_dormancy_check        — daily at 02:00 (cron)
		  cb_expire_stale_holds    — every 15 minutes (interval)
		  cb_maintenance_fee_batch — monthly, 1st day at 01:00 (cron)
		"""
		if not self.config.get("CB_SCHEDULER_ENABLED", True):
			log.info("CoreBankingPlugin: CB_SCHEDULER_ENABLED=False — skipping scheduler registration")
			return

		try:
			from apscheduler.schedulers.background import BackgroundScheduler  # type: ignore
			from apscheduler.triggers.cron import CronTrigger  # type: ignore
			from apscheduler.triggers.interval import IntervalTrigger  # type: ignore
		except ImportError:
			log.warning(
				"CoreBankingPlugin.register_schedules: APScheduler not installed — "
				"batch jobs (interest, dormancy, holds, fees) will not run automatically. "
				"Install apscheduler>=3.10 to enable."
			)
			return

		try:
			from flask import current_app
			app = current_app._get_current_object()  # type: ignore[attr-defined]
		except RuntimeError:
			log.warning("CoreBankingPlugin.register_schedules: no app context — skipping")
			return

		scheduler: BackgroundScheduler = getattr(app, "_cb_scheduler", None)  # type: ignore
		if scheduler is None:
			scheduler = BackgroundScheduler(daemon=True)
			app._cb_scheduler = scheduler  # type: ignore

		def _with_session(fn_name: str, **kwargs: Any) -> None:
			"""Run a CoreBankingService method inside a fresh app context + session."""
			with app.app_context():
				ab = app.extensions.get("appbuilder")
				if ab is None:
					log.warning("cb_job %s: no appbuilder — skipping", fn_name)
					return
				session = ab.get_session
				try:
					from pgappforge.plugins.fintech.core_banking.services import CoreBankingService
					svc = CoreBankingService()
					result = getattr(svc, fn_name)(session=session, **kwargs)
					session.commit()
					log.info("cb_job %s completed: %s", fn_name, result)
				except Exception as exc:
					log.error("cb_job %s failed: %s", fn_name, exc, exc_info=True)
					try:
						session.rollback()
					except Exception:
						pass

		import datetime as _dt

		# Daily interest accrual at 23:55
		scheduler.add_job(
			lambda: _with_session("accrue_interest", accrual_date=_dt.date.today()),
			CronTrigger(hour=23, minute=55),
			id="cb_accrue_interest",
			replace_existing=True,
		)

		# Dormancy check at 02:00 daily
		scheduler.add_job(
			lambda: _with_session(
				"run_dormancy_check",
				threshold_days=self.config.get("CB_DORMANCY_THRESHOLD_DAYS", 365),
			),
			CronTrigger(hour=2, minute=0),
			id="cb_dormancy_check",
			replace_existing=True,
		)

		# Hold expiry every 15 minutes
		scheduler.add_job(
			lambda: _with_session("expire_stale_holds"),
			IntervalTrigger(minutes=15),
			id="cb_expire_stale_holds",
			replace_existing=True,
		)

		# Maintenance fee batch: 1st of month at 01:00
		scheduler.add_job(
			lambda: _with_session("run_maintenance_fee_batch", fee_date=_dt.date.today()),
			CronTrigger(day=1, hour=1, minute=0),
			id="cb_maintenance_fee_batch",
			replace_existing=True,
		)

		if not scheduler.running:
			scheduler.start()
			log.info("CoreBankingPlugin: APScheduler started with 4 batch jobs")
		else:
			log.info("CoreBankingPlugin: batch jobs registered (scheduler already running)")

	def register_models(self) -> list:
		"""Model classes for Alembic autogenerate discovery."""
		from pgappforge.plugins.fintech.core_banking.models import (
			Account,
			AccountHold,
			AccountStatement,
			AMLScreeningResult,
			BankProduct,
			GLAccountMapping,
			InterestAccrual,
			LedgerEntry,
		)
		return [
			BankProduct,
			Account,
			LedgerEntry,
			InterestAccrual,
			AccountHold,
			AccountStatement,
			AMLScreeningResult,
			GLAccountMapping,
		]

	# ------------------------------------------------------------------
	# Seed helper (public — can be called from migrations / CLI)
	# ------------------------------------------------------------------

	@staticmethod
	def seed_default_products(session: Any, tenant_id: str = "default") -> int:
		"""Insert 5 standard product types if they don't already exist.

		Returns the count of newly inserted products.  Idempotent.

		Products seeded:
		  1. SAV001   — Standard Savings Account
		  2. CUR001   — Current Account
		  3. FXD90D   — 90-Day Fixed Deposit
		  4. SME001   — SME Business Loan
		  5. CON001   — Consumer Personal Loan
		"""
		from sqlalchemy import select as _select
		from pgappforge.plugins.fintech.core_banking.models import BankProduct

		DEFAULT_PRODUCTS = [
			{
				"tenant_id": tenant_id,
				"product_code": "SAV001",
				"product_name": "Standard Savings Account",
				"product_type": "SAVINGS",
				"currency_code": "KES",
				"min_balance_cents": 100_00,         # KES 100
				"min_opening_balance_cents": 500_00,  # KES 500
				"interest_rate_pa": "3.000000",
				"interest_calculation": "DAILY_BALANCE",
				"interest_crediting_frequency": "MONTHLY",
				"penalty_rate_pa": "0",
				"dormancy_threshold_days": 365,
				"is_islamic": False,
				"is_active": True,
			},
			{
				"tenant_id": tenant_id,
				"product_code": "CUR001",
				"product_name": "Current Account",
				"product_type": "CURRENT",
				"currency_code": "KES",
				"min_balance_cents": 0,
				"min_opening_balance_cents": 1_000_00,  # KES 1,000
				"interest_rate_pa": "0",
				"interest_calculation": "DAILY_BALANCE",
				"interest_crediting_frequency": "MONTHLY",
				"penalty_rate_pa": "0",
				"dormancy_threshold_days": 730,
				"is_islamic": False,
				"is_active": True,
			},
			{
				"tenant_id": tenant_id,
				"product_code": "FXD90D",
				"product_name": "90-Day Fixed Deposit",
				"product_type": "FIXED_DEPOSIT",
				"currency_code": "KES",
				"min_balance_cents": 50_000_00,          # KES 50,000
				"min_opening_balance_cents": 50_000_00,
				"interest_rate_pa": "8.500000",
				"interest_calculation": "DAILY_BALANCE",
				"interest_crediting_frequency": "QUARTERLY",
				"penalty_rate_pa": "2.000000",
				"dormancy_threshold_days": 180,
				"is_islamic": False,
				"is_active": True,
			},
			{
				"tenant_id": tenant_id,
				"product_code": "SME001",
				"product_name": "SME Business Loan",
				"product_type": "SME_LOAN",
				"currency_code": "KES",
				"min_balance_cents": 0,
				"min_opening_balance_cents": 0,
				"interest_rate_pa": "14.000000",
				"interest_calculation": "DAILY_BALANCE",
				"interest_crediting_frequency": "MONTHLY",
				"penalty_rate_pa": "3.000000",
				"dormancy_threshold_days": 365,
				"is_islamic": False,
				"is_active": True,
			},
			{
				"tenant_id": tenant_id,
				"product_code": "CON001",
				"product_name": "Consumer Personal Loan",
				"product_type": "CONSUMER_LOAN",
				"currency_code": "KES",
				"min_balance_cents": 0,
				"min_opening_balance_cents": 0,
				"interest_rate_pa": "18.000000",
				"interest_calculation": "FLAT",
				"interest_crediting_frequency": "MONTHLY",
				"penalty_rate_pa": "5.000000",
				"dormancy_threshold_days": 365,
				"is_islamic": False,
				"is_active": True,
			},
		]

		inserted = 0
		for pd in DEFAULT_PRODUCTS:
			existing = session.execute(
				_select(BankProduct).where(BankProduct.product_code == pd["product_code"])
			).scalar_one_or_none()
			if existing is not None:
				continue

			from decimal import Decimal
			product = BankProduct(
				tenant_id=pd["tenant_id"],
				product_code=pd["product_code"],
				product_name=pd["product_name"],
				product_type=pd["product_type"],
				currency_code=pd["currency_code"],
				min_balance_cents=pd["min_balance_cents"],
				min_opening_balance_cents=pd["min_opening_balance_cents"],
				interest_rate_pa=Decimal(pd["interest_rate_pa"]),
				interest_calculation=pd["interest_calculation"],
				interest_crediting_frequency=pd["interest_crediting_frequency"],
				penalty_rate_pa=Decimal(pd["penalty_rate_pa"]),
				dormancy_threshold_days=pd["dormancy_threshold_days"],
				is_islamic=pd["is_islamic"],
				is_active=pd["is_active"],
				fees={},
			)
			session.add(product)
			inserted += 1

		if inserted:
			session.flush()
			log.info("CoreBankingPlugin.seed_default_products: inserted %d products", inserted)
		return inserted

	# ------------------------------------------------------------------
	# Internal seed helper
	# ------------------------------------------------------------------

	def _try_seed_products(self) -> None:
		"""Attempt product seeding; log failures, never raise."""
		try:
			from flask import current_app
			ab = current_app.extensions.get("appbuilder")
			if ab is None:
				return
			session = ab.get_session
			tenant_id = self.config.get("CB_DEFAULT_TENANT_ID", "default")
			n = self.seed_default_products(session, tenant_id=tenant_id)
			if n:
				session.commit()
				log.info("CoreBankingPlugin: seeded %d default products", n)
		except RuntimeError:
			# No app context yet — skip silently
			pass
		except Exception as exc:
			log.warning("CoreBankingPlugin._try_seed_products failed (non-fatal): %s", exc)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_plugin(
	appbuilder: Any,
	config: dict[str, Any] | None = None,
) -> CoreBankingPlugin:
	"""Construct and return a CoreBankingPlugin bound to *appbuilder*.

	Does NOT call activate()::

	    plugin = create_plugin(appbuilder)
	    plugin.activate()
	"""
	return CoreBankingPlugin(appbuilder, config=config or {})


# ---------------------------------------------------------------------------
# Public API re-exports
# ---------------------------------------------------------------------------

from pgappforge.plugins.fintech.core_banking.models import (  # noqa: E402
	Account,
	AccountHold,
	AccountStatement,
	AMLScreeningResult,
	BankProduct,
	CB_ACCOUNT_SEQ,
	GLAccountMapping,
	InterestAccrual,
	LedgerEntry,
)
from pgappforge.plugins.fintech.core_banking.events import (  # noqa: E402
	AccountClosedEvent,
	AccountCreditedEvent,
	AccountDebitedEvent,
	AccountDormantEvent,
	AccountFrozenEvent,
	AccountOpenedEvent,
	AccountTransferredEvent,
	AccountUnfrozenEvent,
	ALL_CB_EVENT_TYPES,
	AMLBlockedEvent,
	AMLFlaggedEvent,
	CB_ACCOUNT_CLOSED,
	CB_ACCOUNT_CREDITED,
	CB_ACCOUNT_DEBITED,
	CB_ACCOUNT_DORMANT,
	CB_ACCOUNT_FROZEN,
	CB_ACCOUNT_OPENED,
	CB_ACCOUNT_TRANSFERRED,
	CB_ACCOUNT_UNFROZEN,
	CB_AML_BLOCKED,
	CB_AML_FLAGGED,
	CB_FEE_CHARGED,
	CB_HOLD_EXPIRED,
	CB_HOLD_PLACED,
	CB_HOLD_RELEASED,
	CB_INTEREST_ACCRUED,
	CB_INTEREST_CAPITALIZED,
	CB_STATEMENT_DELIVERED,
	CB_TRANSACTION_REVERSED,
	FeeChargedEvent,
	HoldExpiredEvent,
	HoldPlacedEvent,
	HoldReleasedEvent,
	InterestAccruedEvent,
	InterestCapitalizedEvent,
	StatementDeliveredEvent,
	TransactionReversedEvent,
)
from pgappforge.plugins.fintech.core_banking.services import (  # noqa: E402
	AccountNotFoundError,
	AccountStatusError,
	AMLBlockedError,
	CoreBankingError,
	CoreBankingService,
	DailyLimitExceededError,
	HoldNotFoundError,
	IBANValidationError,
	InsufficientFundsError,
	ProductNotFoundError,
	TransactionAlreadyReversedError,
)
from pgappforge.plugins.fintech.core_banking.views import (  # noqa: E402
	AccountActionsView,
	AccountView,
	BalanceSheetView,
	GLAccountMappingView,
	InterestAccrualDashboard,
	LedgerView,
	ProductView,
)

__all__ = [
	# plugin
	"CoreBankingPlugin",
	"create_plugin",
	# models
	"BankProduct",
	"Account",
	"LedgerEntry",
	"InterestAccrual",
	"AccountHold",
	"AccountStatement",
	"AMLScreeningResult",
	"GLAccountMapping",
	"CB_ACCOUNT_SEQ",
	# events — classes
	"AccountOpenedEvent",
	"AccountCreditedEvent",
	"AccountDebitedEvent",
	"AccountTransferredEvent",
	"AccountClosedEvent",
	"AccountDormantEvent",
	"AccountFrozenEvent",
	"AccountUnfrozenEvent",
	"InterestAccruedEvent",
	"InterestCapitalizedEvent",
	"HoldPlacedEvent",
	"HoldReleasedEvent",
	"TransactionReversedEvent",
	"FeeChargedEvent",
	"HoldExpiredEvent",
	"AMLFlaggedEvent",
	"AMLBlockedEvent",
	"StatementDeliveredEvent",
	# events — type constants
	"CB_ACCOUNT_OPENED",
	"CB_ACCOUNT_CREDITED",
	"CB_ACCOUNT_DEBITED",
	"CB_ACCOUNT_TRANSFERRED",
	"CB_ACCOUNT_CLOSED",
	"CB_ACCOUNT_DORMANT",
	"CB_ACCOUNT_FROZEN",
	"CB_ACCOUNT_UNFROZEN",
	"CB_INTEREST_ACCRUED",
	"CB_INTEREST_CAPITALIZED",
	"CB_HOLD_PLACED",
	"CB_HOLD_RELEASED",
	"CB_TRANSACTION_REVERSED",
	"CB_FEE_CHARGED",
	"CB_HOLD_EXPIRED",
	"CB_AML_FLAGGED",
	"CB_AML_BLOCKED",
	"CB_STATEMENT_DELIVERED",
	"ALL_CB_EVENT_TYPES",
	# services
	"CoreBankingService",
	"CoreBankingError",
	"AccountNotFoundError",
	"ProductNotFoundError",
	"InsufficientFundsError",
	"AccountStatusError",
	"DailyLimitExceededError",
	"HoldNotFoundError",
	"TransactionAlreadyReversedError",
	"AMLBlockedError",
	"IBANValidationError",
	# views
	"ProductView",
	"AccountView",
	"LedgerView",
	"InterestAccrualDashboard",
	"BalanceSheetView",
	"AccountActionsView",
	"GLAccountMappingView",
]
