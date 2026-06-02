"""
pgappforge/plugins/erp/finance/ap/__init__.py

APPlugin — Accounts Payable ERP plugin.

Full procure-to-pay lifecycle:
  APSupplier → APPurchaseOrder / APPOLine → APGoodsReceipt / APGRNLine →
  APInvoice / APInvoiceLine → APApprovalWorkflow → APPaymentRun / APPayment

Domain: finance
Depends on: foundation

Events emitted:
  ap.invoice.matched
  ap.invoice.approved
  ap.invoice.posted_to_gl
  ap.invoice.disputed
  ap.payment.initiated
  ap.payment.confirmed
  ap.payment.failed
  ap.supplier.statement_reconciled
  ap.supplier.approved

Events consumed:
  (none — AP is driven by user actions and GRN confirmations)

Usage
-----
Add to your app config::

    PGAPPFORGE_PLUGINS = [
        "pgappforge.plugins.erp.foundation",
        "pgappforge.plugins.erp.finance.ap",
    ]

Or instantiate directly::

    from pgappforge.plugins.erp.finance.ap import APPlugin
    plugin = APPlugin(appbuilder)
    plugin.activate()
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class APPlugin(BasePlugin):
	"""Accounts Payable ERP plugin.

	Registers 6 view groups and 3 report endpoints.
	Pre-configures 5 Rules Engine rulesets on first run.
	"""

	name = "ap"
	domain = "finance"
	depends_on: list[str] = ["foundation"]

	# ------------------------------------------------------------------
	# Metadata
	# ------------------------------------------------------------------

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="ap",
			version="1.0.0",
			description=(
				"Accounts Payable — full procure-to-pay cycle: supplier master, "
				"purchase orders, goods receipts, 2-way/3-way invoice matching, "
				"multi-level approval workflows, ISO 20022 payment runs."
			),
			author="PgAppForge Contributors",
			tags=["erp", "finance", "ap", "procurement", "invoicing", "payments"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_ap_supplier_list",
				"can_ap_supplier_write",
				"can_ap_supplier_approve",
				"can_ap_po_list",
				"can_ap_po_write",
				"can_ap_po_approve",
				"can_ap_grn_list",
				"can_ap_grn_write",
				"can_ap_grn_post",
				"can_ap_invoice_list",
				"can_ap_invoice_write",
				"can_ap_invoice_match",
				"can_ap_invoice_approve",
				"can_ap_payment_run_list",
				"can_ap_payment_run_write",
				"can_ap_payment_run_approve",
				"can_ap_payment_run_transmit",
				"can_ap_reports",
			],
			safe_mode_compatible=True,
		)

	# ------------------------------------------------------------------
	# get_events / subscribe_to
	# ------------------------------------------------------------------

	def get_events(self) -> list[str]:
		return [
			"ap.invoice.matched",
			"ap.invoice.approved",
			"ap.invoice.posted_to_gl",
			"ap.invoice.disputed",
			"ap.payment.initiated",
			"ap.payment.confirmed",
			"ap.payment.failed",
			"ap.supplier.statement_reconciled",
			"ap.supplier.approved",
		]

	def subscribe_to(self) -> list[str]:
		"""AP consumes no upstream events at this layer.

		In a full ERP deployment, AP would subscribe to:
		  - inventory.goods_receipt.confirmed (from Inventory plugin)
		  - gl.account.created (from GL plugin)
		  - hr.employee.created (for requisitioner resolution)
		"""
		return []

	# ------------------------------------------------------------------
	# Lifecycle
	# ------------------------------------------------------------------

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"AP_MENU_CATEGORY": "Accounts Payable",
			"AP_MATCH_PRICE_TOLERANCE_PCT": 5,
			"AP_MATCH_PRICE_TOLERANCE_MIN_CENTS": 500,
			"AP_PAYMENT_RUN_XML_BLANK_AFTER_TRANSMIT": True,
		}
		self.config = {**defaults, **self.config}
		log.info("APPlugin initialised (config keys: %s)", list(self.config))

	def register_views(self) -> None:
		from pgappforge.plugins.erp.finance.ap.views import (
			APGoodsReceiptView,
			APInvoiceView,
			APPaymentRunView,
			APPurchaseOrderView,
			APReportView,
			APSupplierView,
		)

		cat = self.config.get("AP_MENU_CATEGORY", "Accounts Payable")

		self.add_view(APSupplierView, "Suppliers", icon="fa-truck", category=cat)
		self.add_view(APPurchaseOrderView, "Purchase Orders", icon="fa-shopping-cart", category=cat)
		self.add_view(APGoodsReceiptView, "Goods Receipts", icon="fa-inbox", category=cat)
		self.add_view(APInvoiceView, "Invoices", icon="fa-file-invoice", category=cat)
		self.add_view(APPaymentRunView, "Payment Runs", icon="fa-money", category=cat)
		self.add_view(APReportView, "AP Reports", icon="fa-bar-chart", category=cat)

		log.info("APPlugin: views registered under category %r", cat)

	def register_models(self) -> list:
		from pgappforge.plugins.erp.finance.ap.models import (
			APApprovalWorkflow,
			APGoodsReceipt,
			APGRNLine,
			APInvoice,
			APInvoiceLine,
			APPayment,
			APPaymentRun,
			APPOLine,
			APPurchaseOrder,
			APSupplier,
		)
		return [
			APSupplier,
			APPurchaseOrder,
			APPOLine,
			APGoodsReceipt,
			APGRNLine,
			APInvoice,
			APInvoiceLine,
			APApprovalWorkflow,
			APPaymentRun,
			APPayment,
		]

	# ------------------------------------------------------------------
	# Rules Engine pre-configuration
	# ------------------------------------------------------------------

	@staticmethod
	def setup_rules(session: Any) -> None:
		"""Pre-configure 5 Rules Engine rulesets for AP domain.

		Idempotent — skips rulesets that already exist.
		Call after tables are created (e.g. during app startup or migration).
		"""
		try:
			from pgappforge.plugins.rules.models import Rule, RuleSet
		except ImportError:
			log.debug("APPlugin.setup_rules: rules plugin not available, skipping")
			return

		import sqlalchemy as sa

		RULESETS = [
			{
				"name": "ap.supplier.require_bank_for_wire",
				"description": "Wire/ACH suppliers must have IBAN and BIC before approval",
				"model_name": "APSupplier",
				"stop_on_match": True,
				"rules": [
					{
						"name": "require_iban_for_wire",
						"trigger_event": "on_before_update",
						"conditions_json": [
							{"field": "payment_method", "op": "in", "value": ["WIRE", "ACH", "SEPA"]},
							{"field": "bank_account_iban", "op": "eq", "value": ""},
						],
						"actions_json": [
							{"type": "raise_error",
							 "message": "WIRE/ACH/SEPA suppliers must have bank_account_iban set before approval"}
						],
					},
				],
			},
			{
				"name": "ap.invoice.block_unapproved_supplier",
				"description": "Reject invoice creation for unapproved suppliers",
				"model_name": "APInvoice",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_unapproved_supplier_invoice",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "supplier.approved_supplier", "op": "eq", "value": False},
						],
						"actions_json": [
							{"type": "raise_error",
							 "message": "Cannot create invoice for unapproved supplier"}
						],
					},
				],
			},
			{
				"name": "ap.invoice.positive_amounts",
				"description": "Invoice total_cents must be positive",
				"model_name": "APInvoice",
				"stop_on_match": True,
				"rules": [
					{
						"name": "require_positive_total",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "total_cents", "op": "lte", "value": 0},
						],
						"actions_json": [
							{"type": "raise_error",
							 "message": "Invoice total_cents must be greater than zero"}
						],
					},
				],
			},
			{
				"name": "ap.purchase_order.quantity_positive",
				"description": "PO line quantities must be positive",
				"model_name": "APPOLine",
				"stop_on_match": True,
				"rules": [
					{
						"name": "require_positive_quantity",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "quantity", "op": "lte", "value": 0},
						],
						"actions_json": [
							{"type": "raise_error",
							 "message": "PO line quantity must be greater than zero"}
						],
					},
				],
			},
			{
				"name": "ap.payment_run.require_approval",
				"description": "Payment run must be APPROVED before transmission",
				"model_name": "APPaymentRun",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_unapproved_transmission",
						"trigger_event": "on_before_update",
						"conditions_json": [
							{"field": "_new_status", "op": "eq", "value": "TRANSMITTED"},
							{"field": "_old_status", "op": "neq", "value": "APPROVED"},
						],
						"actions_json": [
							{"type": "raise_error",
							 "message": "Payment run must be in APPROVED status before transmission"}
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
		log.info("APPlugin.setup_rules: %d rulesets configured", len(RULESETS))


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_plugin(
	appbuilder: Any,
	config: dict[str, Any] | None = None,
) -> APPlugin:
	"""Construct an APPlugin without activating it.

	    plugin = create_plugin(appbuilder)
	    plugin.activate()
	"""
	return APPlugin(appbuilder, config=config or {})


# ---------------------------------------------------------------------------
# Public re-exports
# ---------------------------------------------------------------------------

from pgappforge.plugins.erp.finance.ap.models import (  # noqa: E402
	APApprovalWorkflow,
	APGoodsReceipt,
	APGRNLine,
	APInvoice,
	APInvoiceLine,
	APPayment,
	APPaymentRun,
	APPOLine,
	APPurchaseOrder,
	APSupplier,
)
from pgappforge.plugins.erp.finance.ap.events import (  # noqa: E402
	InvoiceApprovedEvent,
	InvoiceDisputedEvent,
	InvoiceMatchedEvent,
	InvoicePostedToGLEvent,
	PaymentConfirmedEvent,
	PaymentFailedEvent,
	PaymentInitiatedEvent,
	SupplierApprovedEvent,
	SupplierStatementReconciledEvent,
)
from pgappforge.plugins.erp.finance.ap.services import (  # noqa: E402
	APService,
	APServiceError,
	APSupplierNotFoundError,
	APInvoiceNotFoundError,
	APMatchError,
	APWorkflowError,
	APPaymentError,
)

__all__ = [
	# plugin
	"APPlugin",
	"create_plugin",
	# models
	"APSupplier",
	"APPurchaseOrder",
	"APPOLine",
	"APGoodsReceipt",
	"APGRNLine",
	"APInvoice",
	"APInvoiceLine",
	"APApprovalWorkflow",
	"APPaymentRun",
	"APPayment",
	# events
	"InvoiceMatchedEvent",
	"InvoiceApprovedEvent",
	"InvoicePostedToGLEvent",
	"InvoiceDisputedEvent",
	"PaymentInitiatedEvent",
	"PaymentConfirmedEvent",
	"PaymentFailedEvent",
	"SupplierStatementReconciledEvent",
	"SupplierApprovedEvent",
	# services
	"APService",
	"APServiceError",
	"APSupplierNotFoundError",
	"APInvoiceNotFoundError",
	"APMatchError",
	"APWorkflowError",
	"APPaymentError",
]
