"""
pgappforge/plugins/erp/industry/procurement/__init__.py

ProcurementPlugin — Public Procurement ERP plugin (OCDS-compliant).

Provides:
  - ProcuringEntity   (government/SOE/international buyer profile)
  - TenderNotice      (OCDS-compliant tender from planning through award)
  - Bid               (supplier bids with weighted evaluation scoring)
  - ProcurementContract          (awarded contract with milestones and amendments)
  - ContractMilestone (delivery/payment/performance checkpoints)
  - ContractPayment   (IMMUTABLE payment ledger, insert-only)

Business rules enforced:
  - TenderNotice must be ACTIVE before bids can be evaluated
  - ProcurementContract may only be awarded from a SUBMITTED/EVALUATED/SHORTLISTED bid
  - ContractPayments are IMMUTABLE — no update or delete permitted
  - Awarding a contract auto-rejects all other bids for the same tender
  - Tender status set to COMPLETE upon contract award

OCDS alignment:
  - generate_ocds_release() produces spec-compliant OCDS 1.1 JSON
  - procurement_method maps: OPEN→open, LIMITED→selective, DIRECT→direct
  - main_procurement_category maps: GOODS→goods, WORKS→works, SERVICES→services

Events emitted:
  procurement.tender.published
  procurement.bid.submitted
  procurement.bid.evaluated
  procurement.contract.awarded
  procurement.contract.milestone.met
  procurement.contract.payment.made

Events consumed:
  finance.ap.payment.processed  (contract payment cleared via AP)
  grc.audit.trail.required      (procurement records retained for audit)

Usage
-----
    PGAPPFORGE_PLUGINS = [
        "pgappforge.plugins.erp.foundation",
        "pgappforge.plugins.erp.crm.sales",
        "pgappforge.plugins.erp.finance.ap",
        "pgappforge.plugins.erp.industry.procurement",
    ]
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class ProcurementPlugin(BasePlugin):
	"""Public Procurement ERP plugin (OCDS 1.1-compliant).

	Class-level routing metadata:
	    name       = "procurement"
	    domain     = "industry"
	    depends_on = ["foundation", "crm.sales", "finance.ap"]
	"""

	name = "procurement"
	domain = "industry"
	depends_on: list[str] = ["foundation", "crm.sales", "finance.ap"]

	# ------------------------------------------------------------------
	# BasePlugin.metadata
	# ------------------------------------------------------------------

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="procurement",
			version="1.0.0",
			description=(
				"Public Procurement Cloud — OCDS-compliant tender management, "
				"weighted bid evaluation, contract award, milestone tracking, "
				"immutable payment ledger, spend analytics, and OCDS 1.1 release export. "
				"Designed for government agencies, SOEs, and international organisations."
			),
			author="PgAppForge Contributors",
			tags=["erp", "industry", "procurement", "ocds", "government", "transparency"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_proc_entity_read",
				"can_proc_entity_write",
				"can_proc_tender_read",
				"can_proc_tender_write",
				"can_proc_tender_publish",
				"can_proc_bid_read",
				"can_proc_bid_submit",
				"can_proc_bid_evaluate",
				"can_proc_bid_award",
				"can_proc_contract_read",
				"can_proc_contract_write",
				"can_proc_milestone_read",
				"can_proc_milestone_write",
				"can_proc_milestone_mark_met",
				"can_proc_payment_read",
				"can_proc_payment_record",
				"can_proc_analytics_read",
				"can_proc_ocds_export",
			],
			safe_mode_compatible=True,
		)

	# ------------------------------------------------------------------
	# ERP plugin contract
	# ------------------------------------------------------------------

	def get_events(self) -> list[str]:
		"""Events this plugin emits."""
		return [
			"procurement.tender.published",
			"procurement.bid.submitted",
			"procurement.bid.evaluated",
			"procurement.contract.awarded",
			"procurement.contract.milestone.met",
			"procurement.contract.payment.made",
		]

	def subscribe_to(self) -> list[str]:
		"""Events this plugin consumes."""
		return [
			"finance.ap.payment.processed",  # ProcurementContract payment cleared via AP
			"grc.audit.trail.required",       # Procurement records retained for audit
		]

	# ------------------------------------------------------------------
	# Lifecycle
	# ------------------------------------------------------------------

	def initialize(self) -> None:
		"""Merge config defaults."""
		defaults: dict[str, Any] = {
			"PROCUREMENT_MENU_CATEGORY": "Procurement",
			"PROCUREMENT_SEED_RULES_ON_INIT": True,
			"PROCUREMENT_DEFAULT_CURRENCY": "USD",
			"PROCUREMENT_OPEN_THRESHOLD_CENTS": 10_000_00,   # $10,000
			"PROCUREMENT_DIRECT_THRESHOLD_CENTS": 1_000_00,  # $1,000
		}
		self.config = {**defaults, **self.config}
		log.info("ProcurementPlugin initialised (config keys: %s)", list(self.config))

	def post_initialize(self) -> None:
		"""Seed rules after tables exist."""
		if self.config.get("PROCUREMENT_SEED_RULES_ON_INIT", True):
			self._try_setup_rules()

	def register_views(self) -> None:
		"""Register Procurement views under the configured menu category."""
		from pgappforge.plugins.erp.industry.procurement.views import (
			BidView,
			ContractMilestoneView,
			ContractPaymentView,
			ContractView,
			ProcurementDashboard,
			TenderNoticeView,
		)

		cat = self.config.get("PROCUREMENT_MENU_CATEGORY", "Procurement")

		self.add_view(TenderNoticeView, "Tender Notices", icon="fa-gavel", category=cat)
		self.add_view(BidView, "Bids", icon="fa-envelope-o", category=cat)
		self.add_view(ContractView, "Contracts", icon="fa-file-text-o", category=cat)
		self.add_view(ContractMilestoneView, "Milestones", icon="fa-flag", category=cat)
		self.add_view(ContractPaymentView, "Payments", icon="fa-money", category=cat)
		self.add_view(ProcurementDashboard, "Analytics Dashboard", icon="fa-bar-chart", category=cat)

		log.info("ProcurementPlugin: views registered under category %r", cat)

	def register_models(self) -> list:
		"""Model classes for Alembic autogenerate discovery."""
		from pgappforge.plugins.erp.industry.procurement.models import (
			Bid,
			ProcurementContract,
			ContractMilestone,
			ContractPayment,
			ProcuringEntity,
			TenderNotice,
		)
		return [ProcuringEntity, TenderNotice, Bid, ProcurementContract, ContractMilestone, ContractPayment]

	# ------------------------------------------------------------------
	# Rules Engine pre-configuration
	# ------------------------------------------------------------------

	@staticmethod
	def setup_rules(session: Any) -> None:
		"""Pre-configure rulesets for Procurement domain rules.

		Pre-built rules:
		  1. Block bid evaluation when tender is not ACTIVE
		  2. Block contract award from a REJECTED bid
		  3. Block ContractPayment update (immutability guard)
		  4. Warn when tender deadline has passed but status is still ACTIVE

		Idempotent — skips rulesets that already exist.
		"""
		try:
			from pgappforge.plugins.rules.models import Rule, RuleSet
		except ImportError:
			log.debug("ProcurementPlugin.setup_rules: rules plugin not available, skipping")
			return

		import sqlalchemy as sa

		RULESETS = [
			{
				"name": "procurement.tender.evaluate_requires_active",
				"description": "Block bid evaluation when tender status is not ACTIVE",
				"model_name": "TenderNotice",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_evaluate_inactive_tender",
						"trigger_event": "on_before_update",
						"conditions_json": [
							{"field": "_action", "op": "eq", "value": "evaluate_bids"},
							{"field": "status", "op": "ne", "value": "ACTIVE"},
						],
						"actions_json": [
							{
								"type": "raise_error",
								"message": (
									"Cannot evaluate bids: TenderNotice {{ocid}} has status={{status}}. "
									"Tender must be ACTIVE to evaluate bids."
								),
							}
						],
					},
				],
			},
			{
				"name": "procurement.bid.award_requires_valid_status",
				"description": "Block contract award from a REJECTED bid",
				"model_name": "Bid",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_award_rejected_bid",
						"trigger_event": "on_before_update",
						"conditions_json": [
							{"field": "_action", "op": "eq", "value": "award_contract"},
							{"field": "status", "op": "eq", "value": "REJECTED"},
						],
						"actions_json": [
							{
								"type": "raise_error",
								"message": (
									"Cannot award contract: bid {{id}} has status=REJECTED. "
									"Only SUBMITTED, EVALUATED, or SHORTLISTED bids can be awarded."
								),
							}
						],
					},
				],
			},
			{
				"name": "procurement.payment.immutable",
				"description": "Block any update to ContractPayment (immutable ledger)",
				"model_name": "ContractPayment",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_payment_update",
						"trigger_event": "on_before_update",
						"conditions_json": [],  # always fires on update
						"actions_json": [
							{
								"type": "raise_error",
								"message": (
									"ContractPayment {{id}} is an immutable ledger record. "
									"Create a correction payment entry instead of updating."
								),
							}
						],
					},
				],
			},
			{
				"name": "procurement.tender.deadline_passed_warning",
				"description": "Warn when tender deadline passed but status is still ACTIVE",
				"model_name": "TenderNotice",
				"stop_on_match": False,
				"rules": [
					{
						"name": "warn_deadline_passed",
						"trigger_event": "on_before_update",
						"conditions_json": [
							{"field": "status", "op": "eq", "value": "ACTIVE"},
							{"field": "_deadline_passed", "op": "eq", "value": True},
						],
						"actions_json": [
							{
								"type": "log",
								"level": "WARNING",
								"message": (
									"TenderNotice {{ocid}}: deadline_date has passed but status is "
									"still ACTIVE. Consider closing or marking COMPLETE."
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
		log.info("ProcurementPlugin.setup_rules: %d rulesets configured", len(RULESETS))

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
			log.warning("ProcurementPlugin._try_setup_rules failed (non-fatal): %s", exc)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_plugin(
	appbuilder: Any,
	config: dict[str, Any] | None = None,
) -> ProcurementPlugin:
	return ProcurementPlugin(appbuilder, config=config or {})


# ---------------------------------------------------------------------------
# Public API re-exports
# ---------------------------------------------------------------------------

from pgappforge.plugins.erp.industry.procurement.models import (  # noqa: E402
	Bid,
	ProcurementContract,
	ContractMilestone,
	ContractPayment,
	ProcuringEntity,
	TenderNotice,
)
from pgappforge.plugins.erp.industry.procurement.events import (  # noqa: E402
	BidSubmittedEvent,
	BidsEvaluatedEvent,
	ContractAwardedEvent,
	ContractPaymentMadeEvent,
	MilestoneMet,
	TenderPublishedEvent,
)
from pgappforge.plugins.erp.industry.procurement.services import (  # noqa: E402
	BidNotFoundError,
	ContractNotFoundError,
	EntityNotFoundError,
	InvalidBidStatusError,
	ProcurementService,
	ProcurementServiceError,
	TenderNotActiveError,
	TenderNotFoundError,
)

__all__ = [
	# plugin
	"ProcurementPlugin",
	"create_plugin",
	# models
	"ProcuringEntity",
	"TenderNotice",
	"Bid",
	"ProcurementContract",
	"ContractMilestone",
	"ContractPayment",
	# events
	"TenderPublishedEvent",
	"BidSubmittedEvent",
	"BidsEvaluatedEvent",
	"ContractAwardedEvent",
	"MilestoneMet",
	"ContractPaymentMadeEvent",
	# services
	"ProcurementService",
	"ProcurementServiceError",
	"TenderNotFoundError",
	"BidNotFoundError",
	"ContractNotFoundError",
	"EntityNotFoundError",
	"TenderNotActiveError",
	"InvalidBidStatusError",
]
