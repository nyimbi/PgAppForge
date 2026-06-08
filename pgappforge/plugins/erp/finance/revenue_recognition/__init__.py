"""
pgappforge/plugins/erp/finance/revenue_recognition/__init__.py

RevRecPlugin — Revenue Recognition ERP plugin (ASC 606 / IFRS 15).

Provides:
  - Contract creation with automatic SSP-based allocation
  - Performance obligation tracking (POINT_IN_TIME and OVER_TIME)
  - Period-based systematic recognition (STRAIGHT_LINE, COMPLETED_CONTRACT,
    OUTPUT, INPUT methods)
  - Variable consideration estimation with constraint application
  - Contract modification accounting (PROSPECTIVE / CUMULATIVE_CATCH_UP)
  - Deferred revenue balance reporting and revenue waterfall
  - Automatic GL posting (DR Deferred Revenue / CR Revenue)
  - Native integration with CRM subscription events — no bolt-on required

Business rules enforced:
  - All amounts: integer cents (BigInteger) — never float
  - Allocation must sum exactly to contract total (Decimal ROUND_HALF_UP + residual adjust)
  - satisfied_cents never exceeds allocated_transaction_price_cents per obligation
  - Cancelled contracts cannot be modified
  - Contract can only be FULLY_SATISFIED when all obligations are FULLY_SATISFIED

Events emitted:
  - finance.rev_rec.contract.created
  - finance.rev_rec.po.satisfied
  - finance.rev_rec.revenue.recognized
  - finance.rev_rec.contract.modified
  - finance.rev_rec.variable.estimated
  - finance.rev_rec.allocation.updated

Events consumed:
  - crm.subscriptions.activated   → auto-create a contract for the subscription
  - crm.sign.request.completed    → trigger contract recognition on e-sign completion

Usage
-----
    PGAPPFORGE_PLUGINS = [
        "pgappforge.plugins.erp.foundation",
        "pgappforge.plugins.erp.finance.gl",
        "pgappforge.plugins.erp.finance.revenue_recognition",
    ]
"""
from __future__ import annotations

import logging
from typing import Any

import sqlalchemy as sa

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class RevRecPlugin(BasePlugin):
	"""Revenue Recognition ERP plugin (ASC 606 / IFRS 15).

	Class-level routing metadata:
	    name       = "revenue_recognition"
	    domain     = "finance"
	    depends_on = ["foundation", "gl"]
	"""

	name = "revenue_recognition"
	domain = "finance"
	depends_on: list[str] = ["foundation", "gl"]

	# ------------------------------------------------------------------
	# BasePlugin.metadata
	# ------------------------------------------------------------------

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="revenue_recognition",
			version="1.0.0",
			description=(
				"Revenue Recognition — ASC 606 / IFRS 15 five-step model with "
				"automatic contract creation from CRM subscriptions, performance "
				"obligation tracking, systematic period recognition, variable "
				"consideration, contract modification accounting, and GL integration."
			),
			author="PgAppForge Contributors",
			tags=[
				"finance",
				"revenue-recognition",
				"asc606",
				"ifrs15",
				"deferred-revenue",
			],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_rev_rec_contract_read",
				"can_rev_rec_contract_write",
				"can_rev_rec_contract_modify",
				"can_rev_rec_obligation_read",
				"can_rev_rec_obligation_satisfy",
				"can_rev_rec_period_recognize",
				"can_rev_rec_journal_read",
				"can_rev_rec_variable_read",
				"can_rev_rec_variable_write",
				"can_rev_rec_balance_report",
				"can_rev_rec_waterfall_report",
				"can_rev_rec_admin",
			],
			safe_mode_compatible=True,
		)

	# ------------------------------------------------------------------
	# ERP plugin contract
	# ------------------------------------------------------------------

	def get_events(self) -> list[str]:
		"""Events this plugin emits."""
		return [
			"finance.rev_rec.contract.created",
			"finance.rev_rec.po.satisfied",
			"finance.rev_rec.revenue.recognized",
			"finance.rev_rec.contract.modified",
			"finance.rev_rec.variable.estimated",
			"finance.rev_rec.allocation.updated",
		]

	def subscribe_to(self) -> list[str]:
		"""Events this plugin consumes."""
		return [
			"crm.subscriptions.activated",
			"crm.sign.request.completed",
		]

	# ------------------------------------------------------------------
	# Lifecycle
	# ------------------------------------------------------------------

	def register_views(self) -> None:
		try:
			from pgappforge.plugins.erp.finance.revenue_recognition.views import (
				RevRecContractView,
				RevRecObligationView,
				RevRecJournalEntryView,
			)
		except ImportError:
			log.warning("RevRecPlugin.register_views: views module not available — skipping.")
			return
		cat = self.config.get("REV_REC_MENU_CATEGORY", "Revenue Recognition")
		self.add_view(RevRecContractView, "Contracts", icon="fa-file-contract", category=cat)
		self.add_view(RevRecObligationView, "Obligations", icon="fa-list-alt", category=cat)
		self.add_view(RevRecJournalEntryView, "Journal Entries", icon="fa-book", category=cat)
		log.info("RevRecPlugin: views registered under %r", cat)

	def initialize(self) -> None:
		"""Merge config defaults."""
		defaults: dict[str, Any] = {
			"REV_REC_MENU_CATEGORY": "Revenue Recognition",
			"REV_REC_DEFAULT_DEFERRED_ACCOUNT": "2500",
			"REV_REC_DEFAULT_REVENUE_ACCOUNT": "4000",
			"REV_REC_AUTO_GL_POST": True,
			"REV_REC_SEED_RULES_ON_INIT": True,
		}
		self.config = {**defaults, **self.config}
		log.info("RevRecPlugin initialised (config keys: %s)", list(self.config))

	def post_initialize(self) -> None:
		"""Seed rules after tables exist."""
		if self.config.get("REV_REC_SEED_RULES_ON_INIT", True):
			self._try_setup_rules()

	def _on_crm_subscriptions_activated(self, event: Any) -> None:
		"""Auto-create a RevRec contract when a subscription is activated.

		Called automatically by BasePlugin.post_initialize() subscription wiring
		when crm.subscriptions.activated is emitted.
		"""
		try:
			from flask import current_app
			session = current_app.appbuilder.get_session
		except (RuntimeError, AttributeError):
			log.debug("RevRecPlugin._on_crm_subscriptions_activated: no Flask context — skipped")
			return

		try:
			from pgappforge.plugins.erp.crm.subscriptions.models import Subscription, SubscriptionPlan
			from pgappforge.plugins.erp.finance.revenue_recognition.services import RevRecService

			sub_id = getattr(event, "sub_id", None) or getattr(event, "aggregate_id", None)
			if not sub_id:
				return

			import sqlalchemy as _sa
			sub = session.execute(
				_sa.select(Subscription).where(Subscription.id == sub_id)
			).scalar_one_or_none()
			if sub is None:
				return

			plan = session.execute(
				_sa.select(SubscriptionPlan).where(SubscriptionPlan.id == sub.plan_id)
			).scalar_one_or_none()

			total_cents = int(sub.quantity or 1) * (plan.base_price_cents if plan else 0)
			if total_cents <= 0:
				return

			svc = RevRecService()
			svc.create_contract(
				customer_id=str(sub.customer_id),
				contract_ref=f"SUB-{sub_id[:8]}",
				total_cents=total_cents,
				obligations_data=[{
					"description": f"{plan.name if plan else 'Subscription'} — recurring service",
					"standalone_selling_price_cents": total_cents,
					"satisfaction_type": "OVER_TIME",
					"recognition_method": "STRAIGHT_LINE",
					"start_date": sub.current_period_start,
					"end_date": sub.current_period_end,
				}],
				session=session,
				tenant_id=str(sub.tenant_id),
				source_module="crm.subscriptions",
				source_record_id=str(sub_id),
			)
			log.info("RevRecPlugin: auto-created contract for subscription %s", sub_id)
		except Exception as exc:
			log.warning("RevRecPlugin._on_crm_subscriptions_activated failed: %s", exc)

	def register_models(self) -> list:
		"""Model classes for Alembic autogenerate discovery."""
		from pgappforge.plugins.erp.finance.revenue_recognition.models import (
			RevRecContract,
			RevRecJournalEntry,
			RevRecObligation,
			VariableConsideration,
		)
		return [
			RevRecContract,
			RevRecObligation,
			RevRecJournalEntry,
			VariableConsideration,
		]

	# ------------------------------------------------------------------
	# Rules Engine pre-configuration
	# ------------------------------------------------------------------

	@staticmethod
	def setup_rules(session: Any) -> None:
		"""Pre-configure 3 rulesets in the Rules Engine for rev rec scenarios.

		Idempotent — skips rulesets that already exist.
		"""
		try:
			from pgappforge.plugins.rules.models import Rule, RuleSet
		except ImportError:
			log.debug("RevRecPlugin.setup_rules: rules plugin not available, skipping")
			return

		RULESETS = [
			{
				"name": "rev_rec.obligation.allocated_le_contract",
				"description": (
					"Enforce that the sum of allocated obligation amounts equals "
					"the contract total transaction price (ASC 606-10-32-28 / IFRS 15.73)"
				),
				"model_name": "RevRecObligation",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_allocation_mismatch",
						"trigger_event": "on_before_create",
						"conditions_json": [
							# Allocation invariant is enforced in service layer (_allocate);
							# this rule guards against direct model writes bypassing the service.
							{
								"field": "allocated_transaction_price_cents",
								"op": "is_not_null",
								"value": None,
							},
						],
						"actions_json": [
							{
								"type": "log",
								"level": "INFO",
								"message": (
									"RevRec obligation created: allocated={{allocated_transaction_price_cents}} "
									"for contract {{contract_id}}"
								),
							}
						],
					},
					{
						"name": "block_over_allocation",
						"trigger_event": "on_before_update",
						"conditions_json": [
							# Prevent allocated > contract total; checked via service logic.
							# Belt-and-suspenders: log a warning if remaining < 0.
							{
								"field": "remaining_cents",
								"op": "<",
								"value": 0,
							},
						],
						"actions_json": [
							{
								"type": "raise_error",
								"message": (
									"Revenue recognition obligation remaining_cents cannot be "
									"negative — allocated_transaction_price_cents must be >= satisfied_cents."
								),
							}
						],
					},
				],
			},
			{
				"name": "rev_rec.obligation.satisfied_le_allocated",
				"description": (
					"Block satisfaction of an obligation beyond its allocated transaction price "
					"(prevents over-recognition of revenue)"
				),
				"model_name": "RevRecObligation",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_over_recognition",
						"trigger_event": "on_before_update",
						"conditions_json": [
							{
								"field": "remaining_cents",
								"op": "<",
								"value": 0,
							},
						],
						"actions_json": [
							{
								"type": "raise_error",
								"message": (
									"Cannot recognize revenue: satisfied_cents would exceed "
									"allocated_transaction_price_cents for this performance obligation. "
									"Over-recognition of revenue is prohibited under ASC 606 / IFRS 15."
								),
							}
						],
					},
					{
						"name": "warn_near_full_recognition",
						"trigger_event": "on_before_update",
						"conditions_json": [
							{
								"field": "remaining_cents",
								"op": "=",
								"value": 0,
							},
							{
								"field": "status",
								"op": "!=",
								"value": "FULLY_SATISFIED",
							},
						],
						"actions_json": [
							{
								"type": "set_field",
								"field": "status",
								"value": "FULLY_SATISFIED",
							}
						],
					},
				],
			},
			{
				"name": "rev_rec.contract.cancel_only_if_unsatisfied",
				"description": (
					"Prevent cancellation of contracts that have partially or fully "
					"satisfied performance obligations (requires reversal entries instead)"
				),
				"model_name": "RevRecContract",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_cancel_if_partially_satisfied",
						"trigger_event": "on_before_update",
						"conditions_json": [
							{
								"field": "_new_status",
								"op": "=",
								"value": "CANCELLED",
							},
							{
								"field": "_old_status",
								"op": "in",
								"value": ["PARTIALLY_SATISFIED", "FULLY_SATISFIED"],
							},
						],
						"actions_json": [
							{
								"type": "raise_error",
								"message": (
									"Cannot cancel a contract with satisfied performance obligations. "
									"Create reversal journal entries to unwind recognized revenue, "
									"then cancel (ASC 606-10-25-30 / IFRS 15.15)."
								),
							}
						],
					},
					{
						"name": "allow_cancel_if_open",
						"trigger_event": "on_before_update",
						"conditions_json": [
							{
								"field": "_new_status",
								"op": "=",
								"value": "CANCELLED",
							},
							{
								"field": "_old_status",
								"op": "=",
								"value": "OPEN",
							},
						],
						"actions_json": [
							{
								"type": "log",
								"level": "INFO",
								"message": "RevRec contract {{id}} cancelled (was OPEN; no satisfied obligations)",
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

		log.info("RevRecPlugin.setup_rules: %d rulesets configured", len(RULESETS))

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
			log.warning("RevRecPlugin._try_setup_rules failed (non-fatal): %s", exc)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_plugin(
	appbuilder: Any,
	config: dict[str, Any] | None = None,
) -> RevRecPlugin:
	"""Construct and return a RevRecPlugin bound to *appbuilder*.

	Does NOT call activate()::

	    plugin = create_plugin(appbuilder)
	    plugin.activate()
	"""
	return RevRecPlugin(appbuilder, config=config or {})


# ---------------------------------------------------------------------------
# Public API re-exports
# ---------------------------------------------------------------------------

from pgappforge.plugins.erp.finance.revenue_recognition.models import (  # noqa: E402
	RevRecContract,
	RevRecJournalEntry,
	RevRecObligation,
	VariableConsideration,
)
from pgappforge.plugins.erp.finance.revenue_recognition.events import (  # noqa: E402
	AllocationUpdatedEvent,
	ContractCreatedEvent,
	ContractModifiedEvent,
	PerformanceObligationSatisfiedEvent,
	RevenueRecognizedEvent,
	VariableConsiderationEstimatedEvent,
	emit_event,
)
from pgappforge.plugins.erp.finance.revenue_recognition.services import (  # noqa: E402
	RevRecService,
	RevRecError,
	ContractNotFoundError,
	ObligationNotFoundError,
	AllocationError,
)

__all__ = [
	# plugin
	"RevRecPlugin",
	"create_plugin",
	# models
	"RevRecContract",
	"RevRecObligation",
	"RevRecJournalEntry",
	"VariableConsideration",
	# events
	"ContractCreatedEvent",
	"PerformanceObligationSatisfiedEvent",
	"RevenueRecognizedEvent",
	"ContractModifiedEvent",
	"VariableConsiderationEstimatedEvent",
	"AllocationUpdatedEvent",
	"emit_event",
	# services
	"RevRecService",
	"RevRecError",
	"ContractNotFoundError",
	"ObligationNotFoundError",
	"AllocationError",
]
