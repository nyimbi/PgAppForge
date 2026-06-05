"""
pgappforge/plugins/erp/crm/contracts/__init__.py

CLMPlugin — Contract Lifecycle Management plugin.

Contract Lifecycle Management — templates, negotiation, e-signature,
obligations, IFRS 16 lease accounting.

Depends on: foundation

Events emitted
--------------
  clm.contract.created
  clm.contract.approved
  clm.contract.signed
  clm.obligation.fulfilled
  clm.obligation.overdue
  clm.contract.renewal_alert
  clm.contract.terminated
  clm.lease.recognised

Events consumed
---------------
  (none by default — subscribers added via subscribe_to() return value)
"""
from __future__ import annotations

import logging
from typing import Any

import sqlalchemy as sa

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class CLMPlugin(BasePlugin):
	"""Contract Lifecycle Management plugin.

	Covers the full contract lifecycle: authoring from templates, clause library,
	multi-role approval workflows, e-signature dispatch, obligation tracking with
	alerting, auto-renewal processing, and IFRS 16 lease accounting with GL entries.
	"""

	name = "clm"
	domain = "crm"
	depends_on: list[str] = ["foundation"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="clm",
			version="1.0.0",
			description=(
				"Contract Lifecycle Management — templates, negotiation, e-signature, "
				"obligations, IFRS 16 lease accounting."
			),
			author="PgAppForge Contributors",
			tags=["erp", "crm", "contracts", "clm", "legal", "ifrs16", "esignature", "lease"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_clm_template_read",
				"can_clm_template_write",
				"can_clm_clause_read",
				"can_clm_clause_write",
				"can_clm_contract_list",
				"can_clm_contract_write",
				"can_clm_contract_approve",
				"can_clm_contract_sign",
				"can_clm_obligation_write",
				"can_clm_lease_accounting",
				"can_clm_reports",
			],
			safe_mode_compatible=True,
		)

	def get_events(self) -> list[str]:
		return [
			"clm.contract.created",
			"clm.contract.approved",
			"clm.contract.signed",
			"clm.obligation.fulfilled",
			"clm.obligation.overdue",
			"clm.contract.renewal_alert",
			"clm.contract.terminated",
			"clm.lease.recognised",
		]

	def subscribe_to(self) -> list[str]:
		return []

	def activate(self) -> None:
		"""Alias for initialize() — satisfies plugin protocol variants."""
		self.initialize()

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"CLM_MENU_CATEGORY": "Contracts",
			"CLM_DEFAULT_JURISDICTION": "KE",
			"CLM_DEFAULT_CURRENCY": "KES",
			"CLM_RENEWAL_CHECK_DAYS": 90,
		}
		self.config = {**defaults, **self.config}
		log.info("CLMPlugin initialised")

	def register_models(self) -> list:
		from pgappforge.plugins.erp.crm.contracts.models import (
			ContractTemplate,
			ClauseLibrary,
			Contract,
			ContractVersion,
			ContractObligation,
			ContractApproval,
			ESignatureRequest,
			LeaseSchedule,
		)
		return [
			ContractTemplate,
			ClauseLibrary,
			Contract,
			ContractVersion,
			ContractObligation,
			ContractApproval,
			ESignatureRequest,
			LeaseSchedule,
		]

	def register_views(self) -> None:
		# Views intentionally deferred to a views.py module added in a future sprint.
		# Registering the plugin without views is valid — API routes suffice for now.
		log.info("CLMPlugin: no views registered (views.py not yet implemented)")

	@staticmethod
	def setup_rules(session: Any) -> None:
		"""Pre-configure Rules Engine rulesets for CLM business controls."""
		try:
			from pgappforge.plugins.rules.models import Rule, RuleSet
		except ImportError:
			log.debug("CLMPlugin.setup_rules: rules plugin not available, skipping")
			return

		RULESETS = [
			# 1. Prevent signing a contract that is not PENDING_SIGNATURE
			{
				"name": "clm.contract.sign_requires_pending_signature",
				"description": "Contract must be in PENDING_SIGNATURE status before recording a signature",
				"model_name": "ESignatureRequest",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_sign_wrong_status",
						"trigger_event": "on_before_insert",
						"conditions_json": [
							{"field": "_contract_status", "op": "neq", "value": "PENDING_SIGNATURE"},
						],
						"actions_json": [
							{
								"type": "raise_error",
								"message": "Cannot record signature: contract is not PENDING_SIGNATURE",
							}
						],
					},
				],
			},
			# 2. Obligations on TERMINATED contracts cannot be created
			{
				"name": "clm.obligation.no_new_on_terminated",
				"description": "New obligations cannot be added to a TERMINATED or CANCELLED contract",
				"model_name": "ContractObligation",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_obligation_terminated",
						"trigger_event": "on_before_insert",
						"conditions_json": [
							{
								"field": "_contract_status",
								"op": "in",
								"value": ["TERMINATED", "CANCELLED"],
							},
						],
						"actions_json": [
							{
								"type": "raise_error",
								"message": "Cannot add obligations to a TERMINATED or CANCELLED contract",
							}
						],
					},
				],
			},
			# 3. Lease accounting only valid for LEASE-type contracts
			{
				"name": "clm.lease.type_check",
				"description": "LeaseSchedule rows may only be created for LEASE-type contracts",
				"model_name": "LeaseSchedule",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_non_lease_schedule",
						"trigger_event": "on_before_insert",
						"conditions_json": [
							{"field": "_contract_type", "op": "neq", "value": "LEASE"},
						],
						"actions_json": [
							{
								"type": "raise_error",
								"message": "LeaseSchedule can only be created for contracts of type LEASE",
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
		log.info("CLMPlugin.setup_rules: %d rulesets configured", len(RULESETS))


def create_plugin(appbuilder: Any, config: dict[str, Any] | None = None) -> CLMPlugin:
	return CLMPlugin(appbuilder, config=config or {})


# ---------------------------------------------------------------------------
# Convenience re-exports
# ---------------------------------------------------------------------------

from pgappforge.plugins.erp.crm.contracts.models import (  # noqa: E402
	ContractTemplate,
	ClauseLibrary,
	Contract,
	ContractVersion,
	ContractObligation,
	ContractApproval,
	ESignatureRequest,
	LeaseSchedule,
)
from pgappforge.plugins.erp.crm.contracts.events import (  # noqa: E402
	ContractCreatedEvent,
	ContractApprovedEvent,
	ContractSignedEvent,
	ObligationFulfilledEvent,
	ObligationOverdueEvent,
	ContractRenewalAlertEvent,
	ContractTerminatedEvent,
	LeaseRecognisedEvent,
)
from pgappforge.plugins.erp.crm.contracts.services import (  # noqa: E402
	CLMService,
	CLMError,
	ContractNotFoundError,
	ObligationNotFoundError,
	SignatureRequestNotFoundError,
	CLMValidationError,
)

__all__ = [
	# Plugin
	"CLMPlugin",
	"create_plugin",
	# Models
	"ContractTemplate",
	"ClauseLibrary",
	"Contract",
	"ContractVersion",
	"ContractObligation",
	"ContractApproval",
	"ESignatureRequest",
	"LeaseSchedule",
	# Events
	"ContractCreatedEvent",
	"ContractApprovedEvent",
	"ContractSignedEvent",
	"ObligationFulfilledEvent",
	"ObligationOverdueEvent",
	"ContractRenewalAlertEvent",
	"ContractTerminatedEvent",
	"LeaseRecognisedEvent",
	# Services / Exceptions
	"CLMService",
	"CLMError",
	"ContractNotFoundError",
	"ObligationNotFoundError",
	"SignatureRequestNotFoundError",
	"CLMValidationError",
]
