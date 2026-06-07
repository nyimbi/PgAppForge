"""
pgappforge/plugins/erp/finance/joint_venture/__init__.py

Joint Venture Accounting plugin for PgAppForge ERP.

Entities:  JointVenture, JvPartner, JvBillingStatement,
           JvCashCall, JvCashCallLine, JvAuditQuery
Service:   JointVentureService
Events:    joint_venture.venture_created, .partner_added, .costs_allocated,
           .billing_statement_cut, .cash_call_issued, .audit_query_raised

Usage
-----
    PGAPPFORGE_PLUGINS = [
        "pgappforge.plugins.erp.foundation",
        "pgappforge.plugins.erp.finance.joint_venture",
    ]
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class JointVenturePlugin(BasePlugin):
	"""Joint Venture Accounting plugin (COPAS/JOA-aligned).

	Provides: JV registration, working interest partner management (WI
	validation to 100%), proportionate cost allocation, monthly JIB billing
	statement generation, advance cash call issuance and receipt tracking,
	and partner audit query lifecycle management.
	"""

	name = "joint_venture"
	domain = "finance"
	depends_on: list[str] = ["foundation"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="joint_venture",
			version="1.0.0",
			description=(
				"Joint Venture Accounting (COPAS/JOA-aligned) — JV and working interest "
				"partner management, proportionate cost allocation, monthly JIB billing "
				"statement generation, advance cash call issuance, payment receipt "
				"tracking, and partner audit query lifecycle management."
			),
			author="PgAppForge Contributors",
			tags=["erp", "finance", "joint_venture", "jv", "copas", "joa", "working_interest"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_jv_read",
				"can_jv_write",
				"can_jv_partner_manage",
				"can_jv_costs_allocate",
				"can_jv_billing_generate",
				"can_jv_cash_call_issue",
				"can_jv_audit_query",
				"can_jv_reports",
			],
			safe_mode_compatible=True,
		)

	def get_events(self) -> list[str]:
		return [
			"joint_venture.venture_created",
			"joint_venture.partner_added",
			"joint_venture.costs_allocated",
			"joint_venture.billing_statement_cut",
			"joint_venture.cash_call_issued",
			"joint_venture.audit_query_raised",
		]

	def subscribe_to(self) -> list[str]:
		return [
			"accounting_period.closing",   # trigger monthly JIB cut
			"party.created",               # auto-suggest as JV partner candidates
		]

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"JV_MENU_CATEGORY": "Joint Ventures",
			"JV_DEFAULT_CURRENCY": "USD",
			"JV_COPAS_OVERHEAD_PCT": "0",   # string Decimal for config safety
		}
		self.config = {**defaults, **self.config}
		log.info("JointVenturePlugin initialised")

	def register_models(self) -> list:
		from pgappforge.plugins.erp.finance.joint_venture.models import (
			JointVenture, JvPartner, JvBillingStatement,
			JvCashCall, JvCashCallLine, JvAuditQuery,
		)
		return [
			JointVenture, JvPartner, JvBillingStatement,
			JvCashCall, JvCashCallLine, JvAuditQuery,
		]


def create_plugin(appbuilder: Any, config: dict[str, Any] | None = None) -> JointVenturePlugin:
	return JointVenturePlugin(appbuilder, config=config or {})


# Public re-exports
from pgappforge.plugins.erp.finance.joint_venture.models import (  # noqa: E402
	JointVenture,
	JvPartner,
	JvBillingStatement,
	JvCashCall,
	JvCashCallLine,
	JvAuditQuery,
)
from pgappforge.plugins.erp.finance.joint_venture.services import (  # noqa: E402
	JointVentureService,
	JvServiceError,
	VentureNotFoundError,
	PartnerNotFoundError,
	WorkingInterestError,
	CashCallError,
	VentureDetails,
	PartnerDetails,
	CashCallDetails,
	AuditQueryDetails,
)
from pgappforge.plugins.erp.finance.joint_venture.events import (  # noqa: E402
	VentureCreatedEvent,
	PartnerAddedEvent,
	JvCostsAllocatedEvent,
	BillingStatementCutEvent,
	CashCallIssuedEvent,
	AuditQueryRaisedEvent,
)

__all__ = [
	"JointVenturePlugin",
	"create_plugin",
	# models
	"JointVenture",
	"JvPartner",
	"JvBillingStatement",
	"JvCashCall",
	"JvCashCallLine",
	"JvAuditQuery",
	# services
	"JointVentureService",
	"JvServiceError",
	"VentureNotFoundError",
	"PartnerNotFoundError",
	"WorkingInterestError",
	"CashCallError",
	"VentureDetails",
	"PartnerDetails",
	"CashCallDetails",
	"AuditQueryDetails",
	# events
	"VentureCreatedEvent",
	"PartnerAddedEvent",
	"JvCostsAllocatedEvent",
	"BillingStatementCutEvent",
	"CashCallIssuedEvent",
	"AuditQueryRaisedEvent",
]
