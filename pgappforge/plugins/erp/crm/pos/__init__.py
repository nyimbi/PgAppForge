"""
pgappforge/plugins/erp/crm/pos/__init__.py

Point of Sale — till management, sales transactions, payment splitting,
shift reconciliation, inventory sync.

Entities:  POSTill, POSTransaction, POSTransactionLine, POSPayment,
           POSShiftReconciliation
Service:   POSService
Events:    pos.till.opened, pos.sale.completed, pos.transaction.voided,
           pos.return.processed, pos.till.closed

Usage
-----
Add to app config::

    PGAPPFORGE_PLUGINS = [
        "pgappforge.plugins.erp.foundation",
        "pgappforge.plugins.erp.crm.pos",
    ]

GL accounts used
----------------
  1011  Cash
  1012  Card receipts clearing
  1013  POS float / M-PESA clearing
  1014  Voucher liability
  1200  Debtor (credit sales)
  2300  VAT payable
  4000  Sales revenue
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class POSPlugin(BasePlugin):
	"""Point of Sale ERP plugin.

	Provides: till lifecycle, SALE/RETURN/VOID transactions, split payments,
	shift reconciliation, and per-shift sales reporting.
	All GL postings are best-effort — runs without the GL plugin loaded.
	"""

	name = "pos"
	domain = "crm"
	depends_on: list[str] = ["foundation"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="pos",
			version="1.0.0",
			description=(
				"Point of Sale — till management, SALE/RETURN/VOID transactions, "
				"split payments (CASH/CARD/MPESA/VOUCHER/CREDIT), shift reconciliation, "
				"and aggregated sales reporting."
			),
			author="PgAppForge Contributors",
			tags=["erp", "crm", "pos", "retail", "till", "payments"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_pos_till_open",
				"can_pos_till_close",
				"can_pos_till_read",
				"can_pos_sale_create",
				"can_pos_transaction_void",
				"can_pos_return_process",
				"can_pos_reconciliation_read",
				"can_pos_reports",
			],
			safe_mode_compatible=True,
		)

	def get_events(self) -> list[str]:
		return [
			"pos.till.opened",
			"pos.sale.completed",
			"pos.transaction.voided",
			"pos.return.processed",
			"pos.till.closed",
		]

	def subscribe_to(self) -> list[str]:
		return []

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"POS_MENU_CATEGORY": "Point of Sale",
			"POS_DEFAULT_CURRENCY": "KES",
			"POS_RECEIPT_PREFIX": "RCP",
			"POS_DISCREPANCY_THRESHOLD_CENTS": 100,
		}
		self.config = {**defaults, **self.config}
		log.info("POSPlugin initialised")

	def register_models(self) -> list:
		from pgappforge.plugins.erp.crm.pos.models import (
			POSPayment,
			POSShiftReconciliation,
			POSTill,
			POSTransaction,
			POSTransactionLine,
		)
		return [POSTill, POSTransaction, POSTransactionLine, POSPayment, POSShiftReconciliation]

	def register_views(self) -> None:
		# Views intentionally deferred — add POSTillView, POSTransactionView, etc.
		# when the views.py module is scaffolded.
		log.info("POSPlugin: view registration deferred (views.py not yet scaffolded)")


def create_plugin(appbuilder: Any, config: dict[str, Any] | None = None) -> POSPlugin:
	return POSPlugin(appbuilder, config=config or {})


# Public re-exports
from pgappforge.plugins.erp.crm.pos.models import (  # noqa: E402
	POSPayment,
	POSShiftReconciliation,
	POSTill,
	POSTransaction,
	POSTransactionLine,
)
from pgappforge.plugins.erp.crm.pos.services import (  # noqa: E402
	POSService,
	POSServiceError,
	TillNotFoundError,
	TillStatusError,
	TransactionNotFoundError,
	TransactionStatusError,
	PaymentMismatchError,
)
from pgappforge.plugins.erp.crm.pos.events import (  # noqa: E402
	TillOpenedEvent,
	SaleCompletedEvent,
	TransactionVoidedEvent,
	ReturnProcessedEvent,
	TillClosedEvent,
)

__all__ = [
	"POSPlugin",
	"create_plugin",
	# models
	"POSTill",
	"POSTransaction",
	"POSTransactionLine",
	"POSPayment",
	"POSShiftReconciliation",
	# service
	"POSService",
	"POSServiceError",
	"TillNotFoundError",
	"TillStatusError",
	"TransactionNotFoundError",
	"TransactionStatusError",
	"PaymentMismatchError",
	# events
	"TillOpenedEvent",
	"SaleCompletedEvent",
	"TransactionVoidedEvent",
	"ReturnProcessedEvent",
	"TillClosedEvent",
]
