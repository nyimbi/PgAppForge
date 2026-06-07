"""
pgappforge/plugins/erp/finance/profit_center/__init__.py

ProfitCenterPlugin — Profit Center Accounting ERP plugin.

Provides:
  - ProfitCenter: segment master with self-referential hierarchy, budget target,
    cost center linkage, and entity scoping.
  - ProfitCenterJournal: debit/credit postings per GL account, period, and PC.
  - ProfitCenterAllocationRule: FIXED_PERCENTAGE / HEADCOUNT / REVENUE allocation
    of costs between profit centers.

Business rules enforced:
  - All amounts: integer cents (BigInteger) — never float
  - post_to_profit_center: exactly one of debit_cents / credit_cents is non-zero
  - Revenue accounts: GL code prefix 4xxx (credit normal balance)
  - Cost of sales: GL code prefix 5xxx; operating expenses: 6xxx (debit normal)
  - FIXED_PERCENTAGE targets must sum to exactly 100%
  - HEADCOUNT / REVENUE methods normalise weights dynamically

Events emitted:
  - finance.profit_center.created
  - finance.profit_center.journal.posted
  - finance.profit_center.report.generated
  - finance.profit_center.allocation.done

Events consumed:
  - (none in v1; future: gl.journal.posted to auto-tag PC from GL dimension)

BPM actions registered:
  - finance.profit_center.post_journal
  - finance.profit_center.run_allocation

Usage
-----
    PGAPPFORGE_PLUGINS = [
        "pgappforge.plugins.erp.foundation",
        "pgappforge.plugins.erp.finance.gl",
        "pgappforge.plugins.erp.finance.profit_center",
    ]
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class ProfitCenterPlugin(BasePlugin):
	"""Profit Center Accounting ERP plugin.

	Class-level routing metadata:
	    name       = "profit_center"
	    domain     = "finance"
	    depends_on = ["foundation", "gl"]
	"""

	name = "profit_center"
	domain = "finance"
	depends_on: list[str] = ["foundation", "gl"]

	# ------------------------------------------------------------------
	# BasePlugin.metadata
	# ------------------------------------------------------------------

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="profit_center",
			version="1.0.0",
			description=(
				"Profit Center Accounting — segment-level P&L reporting, "
				"cost allocation (FIXED/HEADCOUNT/REVENUE), hierarchy roll-ups, "
				"and budget variance analysis at profit center granularity."
			),
			author="PgAppForge Contributors",
			tags=[
				"finance", "profit-center", "segment-reporting",
				"cost-center", "management-accounting", "allocation",
			],
			priority=PluginPriority.HIGH,
			permissions=[
				"can_profit_center_read",
				"can_profit_center_write",
				"can_profit_center_journal_read",
				"can_profit_center_journal_write",
				"can_profit_center_allocation_read",
				"can_profit_center_allocation_write",
				"can_profit_center_allocation_run",
				"can_profit_center_reports",
			],
			safe_mode_compatible=True,
		)

	# ------------------------------------------------------------------
	# ERP plugin contract
	# ------------------------------------------------------------------

	def get_events(self) -> list[str]:
		return [
			"finance.profit_center.created",
			"finance.profit_center.journal.posted",
			"finance.profit_center.report.generated",
			"finance.profit_center.allocation.done",
		]

	def subscribe_to(self) -> list[str]:
		"""v1: none. Future: gl.journal.posted → auto-tag PC from GL dimension."""
		return []

	# ------------------------------------------------------------------
	# Lifecycle
	# ------------------------------------------------------------------

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"PROFIT_CENTER_MENU_CATEGORY": "Profit Centers",
			"PROFIT_CENTER_REVENUE_PREFIXES": ["4"],
			"PROFIT_CENTER_COGS_PREFIXES": ["5"],
			"PROFIT_CENTER_OPEX_PREFIXES": ["6"],
			"PROFIT_CENTER_SEED_RULES_ON_INIT": True,
		}
		self.config = {**defaults, **self.config}
		log.info("ProfitCenterPlugin initialised (config keys: %s)", list(self.config))

	def post_initialize(self) -> None:
		if self.config.get("PROFIT_CENTER_SEED_RULES_ON_INIT", True):
			self._try_setup_rules()

	def register_views(self) -> None:
		"""Register profit center views — guard import for optional views module."""
		try:
			from pgappforge.plugins.erp.finance.profit_center.views import (
				ProfitCenterView,
				ProfitCenterJournalView,
				ProfitCenterAllocationRuleView,
				ProfitCenterReportView,
			)
		except ImportError:
			log.warning(
				"ProfitCenterPlugin.register_views: views module not available — skipping."
			)
			return

		cat = self.config.get("PROFIT_CENTER_MENU_CATEGORY", "Profit Centers")
		self.add_view(
			ProfitCenterView, "Profit Centers", icon="fa-building-o", category=cat
		)
		self.add_view(
			ProfitCenterJournalView, "PC Journals", icon="fa-book", category=cat
		)
		self.add_view(
			ProfitCenterAllocationRuleView,
			"Allocation Rules",
			icon="fa-share-alt",
			category=cat,
		)
		self.add_view(
			ProfitCenterReportView, "PC Reports", icon="fa-bar-chart", category=cat
		)
		log.info("ProfitCenterPlugin: views registered under category %r", cat)

	def register_models(self) -> list:
		from pgappforge.plugins.erp.finance.profit_center.models import (
			ProfitCenter,
			ProfitCenterJournal,
			ProfitCenterAllocationRule,
		)
		return [ProfitCenter, ProfitCenterJournal, ProfitCenterAllocationRule]

	# ------------------------------------------------------------------
	# Rules Engine pre-configuration
	# ------------------------------------------------------------------

	@staticmethod
	def setup_rules(session: Any) -> None:
		"""Pre-configure idempotent rulesets for profit center scenarios."""
		try:
			from pgappforge.plugins.rules.models import Rule, RuleSet
		except ImportError:
			log.debug("ProfitCenterPlugin.setup_rules: rules plugin not available, skipping")
			return

		import sqlalchemy as sa

		RULESETS = [
			{
				"name": "profit_center.journal.no_both_sides",
				"description": "Block journals where both debit and credit are non-zero",
				"model_name": "ProfitCenterJournal",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_double_sided_journal",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "debit_cents", "op": "gt", "value": 0},
							{"field": "credit_cents", "op": "gt", "value": 0},
						],
						"actions_json": [
							{
								"type": "raise_error",
								"message": (
									"A profit center journal line cannot have both "
									"debit_cents and credit_cents non-zero."
								),
							}
						],
					},
				],
			},
			{
				"name": "profit_center.journal.no_zero_amount",
				"description": "Block journals where both sides are zero",
				"model_name": "ProfitCenterJournal",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_zero_journal",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "debit_cents", "op": "eq", "value": 0},
							{"field": "credit_cents", "op": "eq", "value": 0},
						],
						"actions_json": [
							{
								"type": "raise_error",
								"message": (
									"A profit center journal line must have a non-zero "
									"debit or credit amount."
								),
							}
						],
					},
				],
			},
			{
				"name": "profit_center.allocation.percentage_sum_check",
				"description": "Enforce FIXED_PERCENTAGE targets sum to 100%",
				"model_name": "ProfitCenterAllocationRule",
				"stop_on_match": True,
				"rules": [
					{
						"name": "fixed_pct_must_sum_100",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "allocation_method", "op": "eq", "value": "FIXED_PERCENTAGE"},
							{"field": "targets_sum_pct", "op": "ne", "value": 100},
						],
						"actions_json": [
							{
								"type": "raise_error",
								"message": (
									"FIXED_PERCENTAGE allocation targets must sum to exactly 100%. "
									"Check the target percentages and retry."
								),
							}
						],
					},
				],
			},
			{
				"name": "profit_center.no_posting_to_inactive",
				"description": "Block journal posting to an inactive profit center",
				"model_name": "ProfitCenterJournal",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_inactive_pc_post",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "profit_center.is_active", "op": "eq", "value": False},
						],
						"actions_json": [
							{
								"type": "raise_error",
								"message": (
									"Cannot post to an inactive profit center. "
									"Activate the profit center first."
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
		log.info(
			"ProfitCenterPlugin.setup_rules: %d rulesets configured", len(RULESETS)
		)

	# ------------------------------------------------------------------
	# Internal helpers
	# ------------------------------------------------------------------

	def _try_setup_rules(self) -> None:
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
			log.warning(
				"ProfitCenterPlugin._try_setup_rules failed (non-fatal): %s", exc
			)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_plugin(
	appbuilder: Any,
	config: dict[str, Any] | None = None,
) -> ProfitCenterPlugin:
	"""Construct and return a ProfitCenterPlugin bound to *appbuilder*."""
	return ProfitCenterPlugin(appbuilder, config=config or {})


# ---------------------------------------------------------------------------
# Public API re-exports
# ---------------------------------------------------------------------------

from pgappforge.plugins.erp.finance.profit_center.models import (  # noqa: E402
	ProfitCenter,
	ProfitCenterJournal,
	ProfitCenterAllocationRule,
)
from pgappforge.plugins.erp.finance.profit_center.events import (  # noqa: E402
	ProfitCenterCreatedEvent,
	ProfitCenterJournalPostedEvent,
	ProfitCenterReportGeneratedEvent,
	ProfitCenterAllocationDoneEvent,
	emit_event,
)
from pgappforge.plugins.erp.finance.profit_center.services import (  # noqa: E402
	ProfitCenterService,
	ProfitCenterServiceError,
	ProfitCenterNotFoundError,
	AllocationRuleNotFoundError,
	InvalidJournalError,
	InvalidAllocationError,
)

__all__ = [
	# plugin
	"ProfitCenterPlugin",
	"create_plugin",
	# models
	"ProfitCenter",
	"ProfitCenterJournal",
	"ProfitCenterAllocationRule",
	# events
	"ProfitCenterCreatedEvent",
	"ProfitCenterJournalPostedEvent",
	"ProfitCenterReportGeneratedEvent",
	"ProfitCenterAllocationDoneEvent",
	"emit_event",
	# services
	"ProfitCenterService",
	"ProfitCenterServiceError",
	"ProfitCenterNotFoundError",
	"AllocationRuleNotFoundError",
	"InvalidJournalError",
	"InvalidAllocationError",
]
