"""
pgappforge/plugins/erp/finance/tax/__init__.py

Tax Management plugin for the PgAppForge ERP.

Entities:  TaxJurisdiction, TaxCode, TaxReturn, TaxTransaction
Service:   TaxService
Events:    tax.transaction_posted, tax.return_generated, tax.return_filed,
           tax.return_paid, tax.rate_expired
Consumes:  invoice.posted (AR/AP), payment.posted (WHT), exchange_rate.updated

Usage
-----
    PGAPPFORGE_PLUGINS = [
        "pgappforge.plugins.erp.foundation",
        "pgappforge.plugins.erp.finance.tax",
    ]

Reports
-------
  /tax/reports/vat-return/<id>    — VAT Return printable detail
  /tax/reports/tax-liability      — Outstanding tax liabilities by jurisdiction
  /tax/reports/input-tax-credit   — Input tax credit analysis
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class TaxPlugin(BasePlugin):
	"""Tax Management plugin.

	Provides: multi-jurisdiction tax configuration (VAT/GST/SALES_TAX/WHT),
	time-effective rate management, tax transaction posting (immutable ledger),
	VAT return generation and lifecycle (DRAFT→FILED→PAID), input tax credit
	analysis, and multicurrency tax restatement.
	"""

	name = "tax"
	domain = "finance"
	depends_on: list[str] = ["foundation"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="tax",
			version="1.0.0",
			description=(
				"Tax Management — multi-jurisdiction tax rates (VAT/GST/SALES_TAX/WHT), "
				"time-effective rate management, immutable tax transaction ledger, "
				"VAT return generation (DRAFT→FILED→PAID), input tax credit analysis, "
				"withholding tax, multicurrency restatement."
			),
			author="PgAppForge Contributors",
			tags=["erp", "finance", "tax", "vat", "gst", "wht", "compliance"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_tax_jurisdiction_read",
				"can_tax_jurisdiction_write",
				"can_tax_code_read",
				"can_tax_code_write",
				"can_tax_transaction_read",
				"can_tax_transaction_post",
				"can_tax_return_read",
				"can_tax_return_generate",
				"can_tax_return_file",
				"can_tax_return_pay",
				"can_tax_reports",
			],
			safe_mode_compatible=True,
		)

	def get_events(self) -> list[str]:
		return [
			"tax.transaction_posted",
			"tax.return_generated",
			"tax.return_filed",
			"tax.return_paid",
			"tax.rate_expired",
		]

	def subscribe_to(self) -> list[str]:
		return [
			"invoice.posted",        # AR/AP plugin emits this; triggers tax calc
			"payment.posted",        # for WHT deduction on payments
			"exchange_rate.updated", # for multicurrency tax amount restatement
		]

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"TAX_MENU_CATEGORY": "Tax",
			"TAX_DEFAULT_CURRENCY": "NGN",
			"TAX_AUTO_POST_ON_INVOICE": False,
		}
		self.config = {**defaults, **self.config}
		self._wire_event_subscriptions()
		log.info("TaxPlugin initialised")

	def _wire_event_subscriptions(self) -> None:
		"""Wire in-process handlers for upstream document events."""
		from pgappforge.plugins.erp.foundation.events import subscribe

		if self.config.get("TAX_AUTO_POST_ON_INVOICE"):
			def _on_invoice_posted(event):
				log.info(
					"TaxPlugin: invoice.posted from %s/%s — auto-tax calc scheduled",
					event.payload.get("document_type"), event.aggregate_id,
				)
				# Production: dispatch to task queue for async tax line creation

			subscribe("invoice.posted", _on_invoice_posted)

	def register_views(self) -> None:
		from pgappforge.plugins.erp.finance.tax.views import (
			TaxCodeView,
			TaxJurisdictionView,
			TaxReportView,
			TaxReturnSummaryView,
			TaxReturnView,
			TaxTransactionView,
		)
		cat = self.config.get("TAX_MENU_CATEGORY", "Tax")
		self.add_view(TaxReturnSummaryView, "Tax Return Summary", icon="fa-dashboard", category=cat)
		self.add_view(TaxJurisdictionView, "Tax Jurisdictions", icon="fa-globe", category=cat)
		self.add_view(TaxCodeView, "Tax Codes", icon="fa-percent", category=cat)
		self.add_view(TaxTransactionView, "Tax Transactions", icon="fa-list", category=cat)
		self.add_view(TaxReturnView, "Tax Returns", icon="fa-file-text", category=cat)
		self.add_view(TaxReportView, "Tax Reports", icon="fa-bar-chart", category=cat)
		log.info("TaxPlugin: views registered under %r", cat)

	def register_models(self) -> list:
		from pgappforge.plugins.erp.finance.tax.models import (
			TaxCode,
			TaxJurisdiction,
			TaxReturn,
			TaxTransaction,
		)
		return [TaxJurisdiction, TaxCode, TaxReturn, TaxTransaction]

	@staticmethod
	def setup_rules(session: Any) -> None:
		"""Pre-configure 5 Rules Engine rulesets for Tax domain validation."""
		try:
			from pgappforge.plugins.rules.models import Rule, RuleSet
		except ImportError:
			log.debug("TaxPlugin.setup_rules: rules plugin not available, skipping")
			return

		import sqlalchemy as sa

		RULESETS = [
			{
				"name": "tax_code.positive_rate",
				"description": "Tax rate must be between 0 and 100",
				"model_name": "TaxCode",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_negative_rate",
						"trigger_event": "on_before_create",
						"conditions_json": [{"field": "rate", "op": "lt", "value": 0}],
						"actions_json": [
							{"type": "raise_error", "message": "Tax rate must be >= 0"}
						],
					},
					{
						"name": "block_rate_over_100",
						"trigger_event": "on_before_create",
						"conditions_json": [{"field": "rate", "op": "gt", "value": 100}],
						"actions_json": [
							{"type": "raise_error", "message": "Tax rate cannot exceed 100%"}
						],
					},
				],
			},
			{
				"name": "tax_code.exempt_and_zero_rated_exclusive",
				"description": "A tax code cannot be both exempt and zero-rated",
				"model_name": "TaxCode",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_exempt_and_zero",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "is_exempt", "op": "eq", "value": True},
							{"field": "is_zero_rated", "op": "eq", "value": True},
						],
						"actions_json": [
							{"type": "raise_error",
							 "message": "A tax code cannot be both exempt and zero-rated"}
						],
					},
				],
			},
			{
				"name": "tax_code.effective_date_order",
				"description": "effective_to must be after effective_from",
				"model_name": "TaxCode",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_invalid_date_range",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "effective_to", "op": "lt", "value": "{{effective_from}}"},
						],
						"actions_json": [
							{"type": "raise_error",
							 "message": "effective_to must be after effective_from"}
						],
					},
				],
			},
			{
				"name": "tax_transaction.positive_taxable_amount",
				"description": "Taxable amount must be non-negative for non-reversal transactions",
				"model_name": "TaxTransaction",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_negative_taxable",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "is_reversal", "op": "eq", "value": False},
							{"field": "taxable_amount_cents", "op": "lt", "value": 0},
						],
						"actions_json": [
							{"type": "raise_error",
							 "message": "taxable_amount_cents must be non-negative for non-reversal transactions"}
						],
					},
				],
			},
			{
				"name": "tax_return.no_amend_paid",
				"description": "Cannot amend a PAID tax return; create a new return",
				"model_name": "TaxReturn",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_amend_paid",
						"trigger_event": "on_before_update",
						"conditions_json": [
							{"field": "_old_status", "op": "eq", "value": "PAID"},
						],
						"actions_json": [
							{"type": "raise_error",
							 "message": "Cannot modify a PAID tax return. Create an amended return instead."}
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
		log.info("TaxPlugin.setup_rules: %d rulesets configured", len(RULESETS))


def create_plugin(appbuilder: Any, config: dict[str, Any] | None = None) -> TaxPlugin:
	return TaxPlugin(appbuilder, config=config or {})


# Public re-exports
from pgappforge.plugins.erp.finance.tax.models import (  # noqa: E402
	TaxCode,
	TaxJurisdiction,
	TaxReturn,
	TaxTransaction,
)
from pgappforge.plugins.erp.finance.tax.services import (  # noqa: E402
	TaxService,
	TaxServiceError,
	TaxCodeNotFoundError,
	TaxReturnNotFoundError,
	TaxReturnStatusError,
	TaxTransactionDetails,
)
from pgappforge.plugins.erp.finance.tax.events import (  # noqa: E402
	TaxTransactionPostedEvent,
	TaxReturnGeneratedEvent,
	TaxReturnFiledEvent,
	TaxReturnPaidEvent,
	TaxRateExpiredEvent,
)

__all__ = [
	"TaxPlugin",
	"create_plugin",
	# models
	"TaxJurisdiction",
	"TaxCode",
	"TaxReturn",
	"TaxTransaction",
	# services
	"TaxService",
	"TaxServiceError",
	"TaxCodeNotFoundError",
	"TaxReturnNotFoundError",
	"TaxReturnStatusError",
	"TaxTransactionDetails",
	# events
	"TaxTransactionPostedEvent",
	"TaxReturnGeneratedEvent",
	"TaxReturnFiledEvent",
	"TaxReturnPaidEvent",
	"TaxRateExpiredEvent",
]
