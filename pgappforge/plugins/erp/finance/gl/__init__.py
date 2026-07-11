"""
pgappforge/plugins/erp/finance/gl/__init__.py

GLPlugin — General Ledger ERP plugin.

Provides:
  - Chart of Accounts (GLAccount) with IFRS/GAAP concept mapping
  - Fiscal years and accounting periods (GLFiscalYear, GLPeriod)
  - Double-entry journal batches, entries, and lines (GLJournalBatch,
    GLJournalEntry, GLJournalLine)
  - Period account balance snapshots (GLAccountBalance)
  - Budget vs actual tracking (GLBudget)
  - Cost centre dimension (GLCostCenter)

Business rules enforced:
  - All amounts: integer cents (BigInteger) — never float
  - Posting to closed/locked periods is blocked
  - Imbalanced batches cannot be posted
  - Posting to inactive or summary accounts is blocked
  - Posted journal lines are immutable (correction via reversal)

Events emitted:
  - gl.journal.posted  (per line)
  - gl.batch.posted
  - gl.journal.reversed
  - gl.period.closed

Events consumed:
  - (none in v1; future: ap.invoice.approved, ar.payment.received)

Usage
-----
    PGAPPFORGE_PLUGINS = [
        "pgappforge.plugins.erp.foundation",
        "pgappforge.plugins.erp.finance.gl",
    ]
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class GLPlugin(BasePlugin):
	"""General Ledger ERP plugin.

	Class-level routing metadata:
	    name       = "gl"
	    domain     = "finance"
	    depends_on = ["foundation"]
	"""

	name = "gl"
	domain = "finance"
	depends_on: list[str] = ["foundation"]

	# ------------------------------------------------------------------
	# BasePlugin.metadata
	# ------------------------------------------------------------------

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="gl",
			version="1.0.0",
			description=(
				"General Ledger — double-entry bookkeeping with chart of accounts, "
				"fiscal periods, journal batches/entries/lines, account balances, "
				"budget vs actual, and IFRS/GAAP concept mapping."
			),
			author="PgAppForge Contributors",
			tags=["erp", "finance", "gl", "accounting", "ifrs", "gaap"],
			priority=PluginPriority.HIGH,
			permissions=[
				"can_gl_account_read",
				"can_gl_account_write",
				"can_gl_period_read",
				"can_gl_period_close",
				"can_gl_batch_read",
				"can_gl_batch_write",
				"can_gl_batch_post",
				"can_gl_batch_approve",
				"can_gl_entry_read",
				"can_gl_entry_reverse",
				"can_gl_budget_read",
				"can_gl_budget_write",
				"can_gl_reports",
			],
			safe_mode_compatible=True,
		)

	# ------------------------------------------------------------------
	# ERP plugin contract
	# ------------------------------------------------------------------

	def get_events(self) -> list[str]:
		"""Events this plugin emits."""
		return [
			"gl.journal.posted",
			"gl.batch.posted",
			"gl.journal.reversed",
			"gl.period.closed",
		]

	def subscribe_to(self) -> list[str]:
		"""Events this plugin consumes.

		v1: none.  Future subscribers:
		  ap.invoice.approved  → auto-generate GL entries
		  ar.payment.received  → auto-generate GL entries
		"""
		return []

	# ------------------------------------------------------------------
	# Lifecycle
	# ------------------------------------------------------------------

	def initialize(self) -> None:
		"""Merge config defaults."""
		defaults: dict[str, Any] = {
			"GL_MENU_CATEGORY": "General Ledger",
			"GL_FUNCTIONAL_CURRENCY": "USD",
			"GL_SEED_RULES_ON_INIT": True,
		}
		self.config = {**defaults, **self.config}
		log.info("GLPlugin initialised (config keys: %s)", list(self.config))

	def post_initialize(self) -> None:
		"""Seed rules after tables exist."""
		if self.config.get("GL_SEED_RULES_ON_INIT", True):
			self._try_setup_rules()

	def register_views(self) -> None:
		"""Register GL views under the configured menu category."""
		from pgappforge.plugins.erp.finance.gl.views import (
			BalanceSheetView,
			COAView,
			GLDashboardView,
			GLAccountView,
			GLBudgetView,
			GLJournalBatchView,
			GLJournalEntryView,
			GLPeriodView,
			GLReportView,
			IncomeStatementView,
			TrialBalanceView,
		)

		from pgappforge.plugins.erp.finance.gl.api import (
			GLAccountRestApi,
			GLCostCenterRestApi,
			GLFiscalYearRestApi,
			GLPeriodRestApi,
			GLJournalBatchRestApi,
			GLJournalEntryRestApi,
			GLJournalLineRestApi,
			GLAccountBalanceRestApi,
			GLBudgetRestApi,
			GLDimensionDefinitionRestApi,
		)

		cat = self.config.get("GL_MENU_CATEGORY", "General Ledger")

		for api_class in (
			GLAccountRestApi,
			GLCostCenterRestApi,
			GLFiscalYearRestApi,
			GLPeriodRestApi,
			GLJournalBatchRestApi,
			GLJournalEntryRestApi,
			GLJournalLineRestApi,
			GLAccountBalanceRestApi,
			GLBudgetRestApi,
			GLDimensionDefinitionRestApi,
		):
			self.appbuilder.add_api(api_class)

		self.add_view(
			GLDashboardView,
			"GL Dashboard",
			icon="fa-dashboard",
			category=cat,
		)
		self.add_view(
			COAView,
			"Chart of Accounts",
			icon="fa-list-ol",
			category=cat,
		)
		self.add_view(
			TrialBalanceView,
			"Trial Balance",
			icon="fa-balance-scale",
			category=cat,
		)
		self.add_view(
			IncomeStatementView,
			"Income Statement",
			icon="fa-line-chart",
			category=cat,
		)
		self.add_view(
			BalanceSheetView,
			"Balance Sheet",
			icon="fa-columns",
			category=cat,
		)
		self.add_view(
			GLPeriodView,
			"Periods",
			icon="fa-calendar",
			category=cat,
		)
		self.add_view(
			GLJournalBatchView,
			"Journal Batches",
			icon="fa-book",
			category=cat,
		)
		self.add_view(
			GLBudgetView,
			"Budgets",
			icon="fa-bar-chart",
			category=cat,
		)
		self.add_view(
			GLReportView,
			"GL Reports",
			icon="fa-file-text-o",
			category=cat,
		)
		self.add_view_no_menu(GLAccountView)
		self.add_view_no_menu(GLJournalEntryView)

		log.info("GLPlugin: views registered under category %r", cat)

	def register_models(self) -> list:
		"""Model classes for Alembic autogenerate discovery."""
		from pgappforge.plugins.erp.finance.gl.models import (
			GLAccount,
			GLAccountBalance,
			GLBudget,
			GLCostCenter,
			GLFiscalYear,
			GLJournalBatch,
			GLJournalEntry,
			GLJournalLine,
			GLPeriod,
		)
		return [
			GLAccount,
			GLCostCenter,
			GLFiscalYear,
			GLPeriod,
			GLJournalBatch,
			GLJournalEntry,
			GLJournalLine,
			GLAccountBalance,
			GLBudget,
		]

	# ------------------------------------------------------------------
	# Rules Engine pre-configuration
	# ------------------------------------------------------------------

	@staticmethod
	def setup_rules(session: Any) -> None:
		"""Pre-configure 5 rulesets in the Rules Engine for GL scenarios.

		Idempotent — skips rulesets that already exist.
		"""
		try:
			from pgappforge.plugins.rules.models import Rule, RuleSet
		except ImportError:
			log.debug("GLPlugin.setup_rules: rules plugin not available, skipping")
			return

		import sqlalchemy as sa

		RULESETS = [
			{
				"name": "gl.journal_batch.balance_check",
				"description": "Block posting if journal batch is not balanced",
				"model_name": "GLJournalBatch",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_imbalanced_batch",
						"trigger_event": "on_before_update",
						"conditions_json": [
							{"field": "_new_status", "op": "eq", "value": "POSTED"},
							{"field": "is_balanced", "op": "eq", "value": False},
						],
						"actions_json": [
							{
								"type": "raise_error",
								"message": (
									"Cannot post journal batch: total debits do not equal "
									"total credits. Correct the entries before posting."
								),
							}
						],
					},
				],
			},
			{
				"name": "gl.journal_entry.no_post_to_closed_period",
				"description": "Block posting journal entries to closed or locked periods",
				"model_name": "GLJournalEntry",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_posting_closed_period",
						"trigger_event": "on_before_update",
						"conditions_json": [
							{"field": "_new_status", "op": "eq", "value": "POSTED"},
						],
						# Service layer enforces period check; this is a belt-and-suspenders
						# guard at the model level via the rules engine
						"actions_json": [],  # Service raises PeriodClosedError before this fires
					},
				],
			},
			{
				"name": "gl.account.warn_inactive_posting",
				"description": "Warn when a journal line targets an inactive account",
				"model_name": "GLJournalLine",
				"stop_on_match": False,
				"rules": [
					{
						"name": "warn_inactive_account",
						"trigger_event": "on_before_create",
						"conditions_json": [
							# Evaluated via context enrichment in the rules engine
							{"field": "account_code", "op": "is_not_null", "value": None},
						],
						# Actual inactive-account block is in GLService.post_journal;
						# this rule logs a warning via the rules audit log
						"actions_json": [
							{"type": "log", "level": "WARNING",
							 "message": "Posting to account {{account_code}} — verify it is active"}
						],
					},
				],
			},
			{
				"name": "gl.journal_batch.no_draft_modification",
				"description": "Prevent status regression from POSTED back to DRAFT",
				"model_name": "GLJournalBatch",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_status_regression",
						"trigger_event": "on_before_update",
						"conditions_json": [
							{"field": "_old_status", "op": "eq", "value": "POSTED"},
							{"field": "_new_status", "op": "in", "value": ["DRAFT", "SUBMITTED"]},
						],
						"actions_json": [
							{
								"type": "raise_error",
								"message": (
									"Cannot move a POSTED batch back to DRAFT or SUBMITTED. "
									"Create a reversal entry instead."
								),
							}
						],
					},
				],
			},
			{
				"name": "gl.period.no_open_after_lock",
				"description": "Prevent re-opening a LOCKED period",
				"model_name": "GLPeriod",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_period_reopen",
						"trigger_event": "on_before_update",
						"conditions_json": [
							{"field": "_old_status", "op": "eq", "value": "LOCKED"},
							{"field": "_new_status", "op": "eq", "value": "OPEN"},
						],
						"actions_json": [
							{
								"type": "raise_error",
								"message": (
									"Cannot re-open a LOCKED period. "
									"Contact your system administrator."
								),
							}
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
		log.info("GLPlugin.setup_rules: %d rulesets configured", len(RULESETS))

	# ------------------------------------------------------------------
	# Internal helpers
	# ------------------------------------------------------------------

	def _try_setup_rules(self) -> None:
		"""Attempt to seed rules; log failures, never raise."""
		try:
			from flask import current_app
			ab = current_app.extensions.get("appbuilder")
			if ab is None:
				return
			session = ab.get_session
			self.setup_rules(session)
			session.commit()
		except RuntimeError:
			pass
		except Exception as exc:
			log.warning("GLPlugin._try_setup_rules failed (non-fatal): %s", exc)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_plugin(
	appbuilder: Any,
	config: dict[str, Any] | None = None,
) -> GLPlugin:
	"""Construct and return a GLPlugin bound to *appbuilder*.

	Does NOT call activate()::

	    plugin = create_plugin(appbuilder)
	    plugin.activate()
	"""
	return GLPlugin(appbuilder, config=config or {})


# ---------------------------------------------------------------------------
# Public API re-exports
# ---------------------------------------------------------------------------

from pgappforge.plugins.erp.finance.gl.models import (  # noqa: E402
	GLAccount,
	GLAccountBalance,
	GLBudget,
	GLCostCenter,
	GLFiscalYear,
	GLJournalBatch,
	GLJournalEntry,
	GLJournalLine,
	GLPeriod,
)
from pgappforge.plugins.erp.finance.gl.events import (  # noqa: E402
	BatchPostedEvent,
	JournalPostedEvent,
	JournalReversedEvent,
	PeriodClosedEvent,
	emit_event,
)
from pgappforge.plugins.erp.finance.gl.services import (  # noqa: E402
	GLService,
	GLServiceError,
	JournalImbalancedError,
	PeriodClosedError,
	PeriodHasOpenBatchesError,
	BatchNotFoundError,
	EntryNotFoundError,
	PeriodNotFoundError,
)

__all__ = [
	# plugin
	"GLPlugin",
	"create_plugin",
	# models
	"GLAccount",
	"GLCostCenter",
	"GLFiscalYear",
	"GLPeriod",
	"GLJournalBatch",
	"GLJournalEntry",
	"GLJournalLine",
	"GLAccountBalance",
	"GLBudget",
	# events
	"JournalPostedEvent",
	"BatchPostedEvent",
	"JournalReversedEvent",
	"PeriodClosedEvent",
	"emit_event",
	# services
	"GLService",
	"GLServiceError",
	"JournalImbalancedError",
	"PeriodClosedError",
	"PeriodHasOpenBatchesError",
	"BatchNotFoundError",
	"EntryNotFoundError",
	"PeriodNotFoundError",
]
