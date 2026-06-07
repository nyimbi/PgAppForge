"""
pgappforge/plugins/erp/finance/consolidation/__init__.py

ConsolidationPlugin — Group Consolidation ERP plugin.

Provides:
  - ConsolidationGroup: define which legal entities consolidate, with ownership %
    and method (FULL/EQUITY/PROPORTIONAL) per member.
  - ConsolidationRun: execute a consolidation for a group + period.
  - IntercompanyElimination: AR/AP, investment-equity, IC-revenue, dividend
    eliminations generated per run.
  - MinorityInterest: computed NCI equity per subsidiary below 100% ownership.

Business rules enforced:
  - All amounts: integer cents (BigInteger) — never float
  - FX translation follows IAS 21:
      Income/expense → period average rate
      Balance sheet  → closing rate
      Equity         → historical rate
  - Intercompany detection: matching AR on entity A vs AP on entity B
  - Minority interest = (100 - ownership_pct) / 100 × subsidiary_equity
  - Members' ownership_pct sum must not exceed 100%

Events emitted:
  - finance.consolidation.run.started
  - finance.consolidation.elimination.posted
  - finance.consolidation.fx.applied
  - finance.consolidation.run.completed
  - finance.consolidation.minority.computed

Events consumed:
  - gl.period.closed  (future: trigger automatic consolidation run)

BPM actions registered:
  - finance.consolidation.run
  - finance.consolidation.get_trial_balance

Usage
-----
    PGAPPFORGE_PLUGINS = [
        "pgappforge.plugins.erp.foundation",
        "pgappforge.plugins.erp.finance.gl",
        "pgappforge.plugins.erp.finance.consolidation",
    ]
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class ConsolidationPlugin(BasePlugin):
	"""Group Consolidation ERP plugin.

	Class-level routing metadata:
	    name       = "consolidation"
	    domain     = "finance"
	    depends_on = ["foundation", "gl"]
	"""

	name = "consolidation"
	domain = "finance"
	depends_on: list[str] = ["foundation", "gl"]

	# ------------------------------------------------------------------
	# BasePlugin.metadata
	# ------------------------------------------------------------------

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="consolidation",
			version="1.0.0",
			description=(
				"Group Consolidation — multi-entity financial consolidation with "
				"intercompany elimination, FX translation (IAS 21), and minority "
				"interest computation (IFRS 10)."
			),
			author="PgAppForge Contributors",
			tags=[
				"finance", "consolidation", "group-reporting",
				"intercompany", "ifrs10", "ias21", "minority-interest",
			],
			priority=PluginPriority.HIGH,
			permissions=[
				"can_consolidation_group_read",
				"can_consolidation_group_write",
				"can_consolidation_run_read",
				"can_consolidation_run_execute",
				"can_consolidation_elimination_read",
				"can_consolidation_minority_read",
				"can_consolidation_reports",
			],
			safe_mode_compatible=True,
		)

	# ------------------------------------------------------------------
	# ERP plugin contract
	# ------------------------------------------------------------------

	def get_events(self) -> list[str]:
		return [
			"finance.consolidation.run.started",
			"finance.consolidation.elimination.posted",
			"finance.consolidation.fx.applied",
			"finance.consolidation.run.completed",
			"finance.consolidation.minority.computed",
		]

	def subscribe_to(self) -> list[str]:
		"""gl.period.closed — future: auto-trigger consolidation run."""
		return ["gl.period.closed"]

	# ------------------------------------------------------------------
	# Lifecycle
	# ------------------------------------------------------------------

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"CONSOLIDATION_MENU_CATEGORY": "Consolidation",
			"CONSOLIDATION_REPORTING_CURRENCY": "USD",
			"CONSOLIDATION_AUTO_RUN_ON_PERIOD_CLOSE": False,
			"CONSOLIDATION_SEED_RULES_ON_INIT": True,
		}
		self.config = {**defaults, **self.config}
		log.info("ConsolidationPlugin initialised (config keys: %s)", list(self.config))

	def post_initialize(self) -> None:
		if self.config.get("CONSOLIDATION_SEED_RULES_ON_INIT", True):
			self._try_setup_rules()

	def register_views(self) -> None:
		"""Register consolidation views — guard import for optional views module."""
		try:
			from pgappforge.plugins.erp.finance.consolidation.views import (
				ConsolidationGroupView,
				ConsolidationRunView,
				IntercompanyEliminationView,
				MinorityInterestView,
			)
		except ImportError:
			log.warning(
				"ConsolidationPlugin.register_views: views module not available — skipping."
			)
			return

		cat = self.config.get("CONSOLIDATION_MENU_CATEGORY", "Consolidation")
		self.add_view(ConsolidationGroupView, "Consolidation Groups", icon="fa-sitemap", category=cat)
		self.add_view(ConsolidationRunView, "Consolidation Runs", icon="fa-play-circle", category=cat)
		self.add_view(
			IntercompanyEliminationView, "IC Eliminations", icon="fa-exchange", category=cat
		)
		self.add_view(
			MinorityInterestView, "Minority Interest", icon="fa-pie-chart", category=cat
		)
		log.info("ConsolidationPlugin: views registered under category %r", cat)

	def register_models(self) -> list:
		from pgappforge.plugins.erp.finance.consolidation.models import (
			ConsolidationGroup,
			ConsolidationRun,
			IntercompanyElimination,
			MinorityInterest,
		)
		return [ConsolidationGroup, ConsolidationRun, IntercompanyElimination, MinorityInterest]

	# ------------------------------------------------------------------
	# Rules Engine pre-configuration
	# ------------------------------------------------------------------

	@staticmethod
	def setup_rules(session: Any) -> None:
		"""Pre-configure idempotent rulesets for consolidation scenarios."""
		try:
			from pgappforge.plugins.rules.models import Rule, RuleSet
		except ImportError:
			log.debug("ConsolidationPlugin.setup_rules: rules plugin not available, skipping")
			return

		import sqlalchemy as sa

		RULESETS = [
			{
				"name": "consolidation.run.only_active_groups",
				"description": "Block consolidation runs on inactive groups",
				"model_name": "ConsolidationRun",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_inactive_group_run",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "group.is_active", "op": "eq", "value": False},
						],
						"actions_json": [
							{
								"type": "raise_error",
								"message": (
									"Cannot run consolidation for an inactive group. "
									"Activate the group first."
								),
							}
						],
					},
				],
			},
			{
				"name": "consolidation.group.ownership_sum_check",
				"description": "Warn if sum of ownership percentages exceeds 100%",
				"model_name": "ConsolidationGroup",
				"stop_on_match": True,
				"rules": [
					{
						"name": "ownership_sum_over_100",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "members_total_pct", "op": "gt", "value": 100},
						],
						"actions_json": [
							{
								"type": "raise_error",
								"message": (
									"Sum of member ownership percentages exceeds 100%. "
									"The remainder represents minority interest."
								),
							}
						],
					},
				],
			},
			{
				"name": "consolidation.run.no_rerun_completed",
				"description": "Prevent re-running a COMPLETED consolidation for the same period",
				"model_name": "ConsolidationRun",
				"stop_on_match": False,
				"rules": [
					{
						"name": "warn_duplicate_run",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "_existing_completed_run", "op": "eq", "value": True},
						],
						"actions_json": [
							{
								"type": "log",
								"level": "WARNING",
								"message": (
									"A COMPLETED consolidation run already exists for "
									"group {{group_id}} period {{period}}. "
									"This run will create a new snapshot."
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
			"ConsolidationPlugin.setup_rules: %d rulesets configured", len(RULESETS)
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
				"ConsolidationPlugin._try_setup_rules failed (non-fatal): %s", exc
			)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_plugin(
	appbuilder: Any,
	config: dict[str, Any] | None = None,
) -> ConsolidationPlugin:
	"""Construct and return a ConsolidationPlugin bound to *appbuilder*."""
	return ConsolidationPlugin(appbuilder, config=config or {})


# ---------------------------------------------------------------------------
# Public API re-exports
# ---------------------------------------------------------------------------

from pgappforge.plugins.erp.finance.consolidation.models import (  # noqa: E402
	ConsolidationGroup,
	ConsolidationRun,
	IntercompanyElimination,
	MinorityInterest,
)
from pgappforge.plugins.erp.finance.consolidation.events import (  # noqa: E402
	ConsolidationRunStartedEvent,
	IntercompanyEliminationPostedEvent,
	FXTranslationAppliedEvent,
	ConsolidationRunCompletedEvent,
	MinorityInterestComputedEvent,
	emit_event,
)
from pgappforge.plugins.erp.finance.consolidation.services import (  # noqa: E402
	ConsolidationService,
	ConsolidationServiceError,
	GroupNotFoundError,
	RunNotFoundError,
	InvalidMembersError,
)

__all__ = [
	# plugin
	"ConsolidationPlugin",
	"create_plugin",
	# models
	"ConsolidationGroup",
	"ConsolidationRun",
	"IntercompanyElimination",
	"MinorityInterest",
	# events
	"ConsolidationRunStartedEvent",
	"IntercompanyEliminationPostedEvent",
	"FXTranslationAppliedEvent",
	"ConsolidationRunCompletedEvent",
	"MinorityInterestComputedEvent",
	"emit_event",
	# services
	"ConsolidationService",
	"ConsolidationServiceError",
	"GroupNotFoundError",
	"RunNotFoundError",
	"InvalidMembersError",
]
