"""
pgappforge/plugins/erp/finance/ar/__init__.py

ARPlugin — Accounts Receivable ERP plugin.

Depends on: foundation (Party, Currency, DomainEventLog)

Events emitted
--------------
  ar.invoice.issued       — invoice moved DRAFT → ISSUED
  ar.invoice.paid         — invoice fully paid
  ar.invoice.written_off  — bad debt write-off
  ar.invoice.disputed     — customer dispute raised
  ar.payment.received     — new payment record created
  ar.payment.allocated    — payment applied to invoices
  ar.customer.overdue     — customer has overdue invoices
  ar.customer.credit_hold_placed
  ar.customer.credit_hold_released
  ar.credit_note.issued
  ar.dunning.run_completed
  ar.aging.snapshot_created

Events consumed
---------------
  party.created    — auto-create ARCustomer shell when a Party gets CUSTOMER role
  party.updated    — sync billing address / contact from Party changes

Usage
-----
Add to app config::

    PGAPPFORGE_PLUGINS = [
        "pgappforge.plugins.erp.foundation",
        "pgappforge.plugins.erp.finance.ar",
    ]

Or instantiate directly::

    from pgappforge.plugins.erp.finance.ar import ARPlugin
    plugin = ARPlugin(appbuilder)
    plugin.activate()
"""
from __future__ import annotations

import logging
from typing import Any

import sqlalchemy as sa

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class ARPlugin(BasePlugin):
	"""Accounts Receivable ERP plugin.

	Registers AR CRUD views, report views, and the dunning interface.
	Pre-configures 5 Rules Engine rulesets for credit, dunning, and invoice controls.

	Class-level attributes for dependency resolution:
	    name       = "ar"
	    domain     = "finance"
	    depends_on = ["foundation"]
	"""

	name = "ar"
	domain = "finance"
	depends_on: list[str] = ["foundation"]

	# ------------------------------------------------------------------
	# BasePlugin.metadata
	# ------------------------------------------------------------------

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="ar",
			version="1.0.0",
			description=(
				"Accounts Receivable — full AR lifecycle: customers, invoices, payments, "
				"allocations, credit notes, dunning runs, aging snapshots, and GL integration."
			),
			author="PgAppForge Contributors",
			tags=["erp", "finance", "ar", "receivables", "invoicing", "dunning"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_ar_customer_list",
				"can_ar_customer_write",
				"can_ar_customer_credit_hold",
				"can_ar_invoice_list",
				"can_ar_invoice_write",
				"can_ar_invoice_issue",
				"can_ar_invoice_write_off",
				"can_ar_payment_list",
				"can_ar_payment_write",
				"can_ar_payment_allocate",
				"can_ar_credit_note_write",
				"can_ar_dunning_run",
				"can_ar_reports",
			],
			safe_mode_compatible=True,
		)

	# ------------------------------------------------------------------
	# ERP plugin contract
	# ------------------------------------------------------------------

	def get_events(self) -> list[str]:
		"""Events this plugin emits."""
		return [
			"ar.invoice.issued",
			"ar.invoice.paid",
			"ar.invoice.written_off",
			"ar.invoice.disputed",
			"ar.payment.received",
			"ar.payment.allocated",
			"ar.customer.overdue",
			"ar.customer.credit_hold_placed",
			"ar.customer.credit_hold_released",
			"ar.credit_note.issued",
			"ar.dunning.run_completed",
			"ar.aging.snapshot_created",
		]

	def subscribe_to(self) -> list[str]:
		"""Events this plugin consumes from upstream plugins."""
		return [
			"party.created",   # auto-create ARCustomer shell
			"party.updated",   # sync billing contact changes
		]

	# ------------------------------------------------------------------
	# Lifecycle
	# ------------------------------------------------------------------

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"AR_MENU_CATEGORY": "Accounts Receivable",
			"AR_DEFAULT_CURRENCY": "USD",
			"AR_DEFAULT_PAYMENT_TERMS_DAYS": 30,
			"AR_DUNNING_LEVELS": 4,
			"AR_AGING_BUCKETS": [30, 60, 90, 120],
		}
		self.config = {**defaults, **self.config}
		log.info("ARPlugin initialised (config keys: %s)", list(self.config))

	def post_initialize(self) -> None:
		"""Wire event subscriptions after init."""
		self._subscribe_to_foundation_events()

	def register_views(self) -> None:
		"""Register all AR views under the configured menu category."""
		from pgappforge.plugins.erp.finance.ar.views import (
			ARCustomerView,
			ARCreditNoteView,
			ARDashboardView,
			ARDunningView,
			ARInvoiceView,
			ARPaymentView,
			ARReportView,
		)

		from pgappforge.plugins.erp.finance.ar.api import (
			ARCustomerRestApi,
			ARInvoiceRestApi,
			ARInvoiceLineRestApi,
			ARPaymentRestApi,
			ARAllocationRestApi,
			ARCreditNoteRestApi,
			ARDunningRunRestApi,
			ARDunningEventRestApi,
			ARAgingRestApi,
		)

		cat = self.config.get("AR_MENU_CATEGORY", "Accounts Receivable")

		for api_class in (
			ARCustomerRestApi,
			ARInvoiceRestApi,
			ARInvoiceLineRestApi,
			ARPaymentRestApi,
			ARAllocationRestApi,
			ARCreditNoteRestApi,
			ARDunningRunRestApi,
			ARDunningEventRestApi,
			ARAgingRestApi,
		):
			self.appbuilder.add_api(api_class)

		self.add_view(
			ARDashboardView,
			"AR Dashboard",
			icon="fa-dashboard",
			category=cat,
		)
		self.add_view(
			ARCustomerView,
			"Customers",
			icon="fa-user-tie",
			category=cat,
		)
		self.add_view(
			ARInvoiceView,
			"Invoices",
			icon="fa-file-invoice",
			category=cat,
		)
		self.add_view(
			ARPaymentView,
			"Payments",
			icon="fa-money",
			category=cat,
		)
		self.add_view(
			ARCreditNoteView,
			"Credit Notes",
			icon="fa-file-minus",
			category=cat,
		)
		self.add_view(
			ARDunningView,
			"Dunning",
			icon="fa-bell",
			category=cat,
		)
		self.add_view(
			ARReportView,
			"AR Reports",
			icon="fa-chart-bar",
			category=cat,
		)

		log.info("ARPlugin: views registered under category %r", cat)

	def register_models(self) -> list:
		"""Model classes for Alembic autogenerate."""
		from pgappforge.plugins.erp.finance.ar.models import (
			ARAllocation,
			ARAging,
			ARCreditNote,
			ARCustomer,
			ARDunningEvent,
			ARDunningRun,
			ARInvoice,
			ARInvoiceLine,
			ARPayment,
		)
		return [
			ARCustomer,
			ARInvoice,
			ARInvoiceLine,
			ARPayment,
			ARAllocation,
			ARCreditNote,
			ARDunningRun,
			ARDunningEvent,
			ARAging,
		]

	# ------------------------------------------------------------------
	# Rules Engine pre-configuration
	# ------------------------------------------------------------------

	@staticmethod
	def setup_rules(session: Any) -> None:
		"""Pre-configure 5 Rules Engine rulesets for AR business controls.

		Idempotent — skips rulesets that already exist.
		"""
		try:
			from pgappforge.plugins.rules.models import Rule, RuleSet
		except ImportError:
			log.debug("ARPlugin.setup_rules: rules plugin not available, skipping")
			return

		RULESETS = [
			# 1. Credit limit enforcement on invoice issue
			{
				"name": "ar.invoice.credit_limit",
				"description": "Block invoice issue when customer is on credit hold",
				"model_name": "ARInvoice",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_credit_hold_issue",
						"trigger_event": "on_before_update",
						"conditions_json": [
							{"field": "_new_status", "op": "eq", "value": "ISSUED"},
							{"field": "customer.credit_hold", "op": "eq", "value": True},
						],
						"actions_json": [
							{
								"type": "raise_error",
								"message": "Cannot issue invoice: customer is on credit hold",
							}
						],
					},
				],
			},
			# 2. Invoice immutability after issue
			{
				"name": "ar.invoice.immutability",
				"description": "Block amount changes on non-DRAFT invoices",
				"model_name": "ARInvoice",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_amount_change_post_issue",
						"trigger_event": "on_before_update",
						"conditions_json": [
							{"field": "status", "op": "not_in", "value": ["DRAFT", "CANCELLED"]},
							{"field": "_new_total_cents", "op": "neq", "value": "{{_old_total_cents}}"},
						],
						"actions_json": [
							{
								"type": "raise_error",
								"message": "Issued invoice amounts are immutable; use a credit note",
							}
						],
					},
				],
			},
			# 3. Payment amount validation
			{
				"name": "ar.payment.positive_amount",
				"description": "Payment amount must be positive",
				"model_name": "ARPayment",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_zero_payment",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "amount_cents", "op": "lte", "value": 0},
						],
						"actions_json": [
							{
								"type": "raise_error",
								"message": "Payment amount must be greater than zero",
							}
						],
					},
				],
			},
			# 4. Dunning block guard
			{
				"name": "ar.customer.dunning_block",
				"description": "Customers marked dunning_blocked are excluded from automated escalation",
				"model_name": "ARCustomer",
				"stop_on_match": False,
				"rules": [
					{
						"name": "log_dunning_blocked_skip",
						"trigger_event": "on_update",
						"conditions_json": [
							{"field": "dunning_blocked", "op": "eq", "value": True},
							{"field": "_new_dunning_level", "op": "gt", "value": "{{_old_dunning_level}}"},
						],
						"actions_json": [
							{
								"type": "log_warning",
								"message": "Dunning level escalated on a blocked customer — review manually",
							}
						],
					},
				],
			},
			# 5. Write-off threshold alert
			{
				"name": "ar.invoice.write_off_threshold",
				"description": "Flag large write-offs (>500,000 cents / ~5,000 USD) for review",
				"model_name": "ARInvoice",
				"stop_on_match": False,
				"rules": [
					{
						"name": "flag_large_write_off",
						"trigger_event": "on_before_update",
						"conditions_json": [
							{"field": "_new_status", "op": "eq", "value": "WRITTEN_OFF"},
							{"field": "_new_write_off_cents", "op": "gt", "value": 500_000},
						],
						"actions_json": [
							{
								"type": "log_warning",
								"message": "Large write-off exceeds threshold — requires senior approval",
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
		log.info("ARPlugin.setup_rules: %d rulesets configured", len(RULESETS))

	# ------------------------------------------------------------------
	# Foundation event subscriptions
	# ------------------------------------------------------------------

	def _subscribe_to_foundation_events(self) -> None:
		"""Subscribe to party.created and party.updated events."""
		try:
			from pgappforge.plugins.erp.foundation.events import subscribe

			subscribe("party.created", self._on_party_created)
			subscribe("party.updated", self._on_party_updated)
			log.debug("ARPlugin: subscribed to party.created and party.updated")
		except Exception as exc:
			log.warning("ARPlugin._subscribe_to_foundation_events failed: %s", exc)

	def _on_party_created(self, event: Any) -> None:
		"""No-op: ARCustomer is created explicitly via ARCustomerView.create.

		Real-world implementations could auto-create a shell ARCustomer here
		when the party.created event carries role_type=CUSTOMER in the payload.
		"""
		log.debug("ARPlugin._on_party_created: party=%s (no auto-create)", event.aggregate_id)

	def _on_party_updated(self, event: Any) -> None:
		"""No-op: billing address sync from Party updates.

		Extend this to sync contact_email / billing_address from Party when
		changed_fields includes contact or address fields.
		"""
		log.debug("ARPlugin._on_party_updated: party=%s fields=%s", event.aggregate_id,
		          getattr(event, "changed_fields", []))


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_plugin(
	appbuilder: Any,
	config: dict[str, Any] | None = None,
) -> ARPlugin:
	"""Construct and return an ARPlugin bound to *appbuilder*.

	Does NOT call activate()::

	    plugin = create_plugin(appbuilder)
	    plugin.activate()
	"""
	return ARPlugin(appbuilder, config=config or {})


# ---------------------------------------------------------------------------
# Public API re-exports
# ---------------------------------------------------------------------------

from pgappforge.plugins.erp.finance.ar.models import (  # noqa: E402
	ARAging,
	ARAllocation,
	ARCreditNote,
	ARCustomer,
	ARDunningEvent,
	ARDunningRun,
	ARInvoice,
	ARInvoiceLine,
	ARPayment,
)
from pgappforge.plugins.erp.finance.ar.events import (  # noqa: E402
	AgingSnapshotCreatedEvent,
	CreditHoldPlacedEvent,
	CreditHoldReleasedEvent,
	CreditNoteIssuedEvent,
	CustomerOverdueEvent,
	DunningRunCompletedEvent,
	InvoiceDisputedEvent,
	InvoiceIssuedEvent,
	InvoicePaidEvent,
	InvoiceWrittenOffEvent,
	PaymentAllocatedEvent,
	PaymentReceivedEvent,
)
from pgappforge.plugins.erp.finance.ar.services import (  # noqa: E402
	ARCreditNoteNotFoundError,
	ARCustomerNotFoundError,
	ARInvoiceNotFoundError,
	ARPaymentNotFoundError,
	ARService,
	ARServiceError,
	ARValidationError,
)

__all__ = [
	# plugin
	"ARPlugin",
	"create_plugin",
	# models
	"ARCustomer",
	"ARInvoice",
	"ARInvoiceLine",
	"ARPayment",
	"ARAllocation",
	"ARCreditNote",
	"ARDunningRun",
	"ARDunningEvent",
	"ARAging",
	# events
	"InvoiceIssuedEvent",
	"InvoicePaidEvent",
	"InvoiceWrittenOffEvent",
	"InvoiceDisputedEvent",
	"PaymentReceivedEvent",
	"PaymentAllocatedEvent",
	"CustomerOverdueEvent",
	"CreditHoldPlacedEvent",
	"CreditHoldReleasedEvent",
	"CreditNoteIssuedEvent",
	"DunningRunCompletedEvent",
	"AgingSnapshotCreatedEvent",
	# services
	"ARService",
	"ARServiceError",
	"ARInvoiceNotFoundError",
	"ARCustomerNotFoundError",
	"ARPaymentNotFoundError",
	"ARValidationError",
	"ARCreditNoteNotFoundError",
]
