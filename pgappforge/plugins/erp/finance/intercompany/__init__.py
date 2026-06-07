"""
pgappforge/plugins/erp/finance/intercompany/__init__.py

IntercompanyPlugin — Intercompany Posting ERP plugin.

Domain: finance
Depends on: foundation

Full intercompany transaction lifecycle:
  ICOutboxTransaction (PENDING → SENT → ACCEPTED | REJECTED) — source entity
  ICInboxTransaction  (PENDING → ACCEPTED | REJECTED)         — target entity

  send_transaction()         → create outbox + inbox atomically
  accept_transaction()       → create mirror document at target entity
  reject_transaction()       → mark rejected, update outbox
  get_inbox()                → list pending inbox items
  reconcile_ic_balances()    → compare A↔B balances, detect divergences

Events emitted:
  finance.intercompany.sent
  finance.intercompany.accepted
  finance.intercompany.rejected
  finance.intercompany.reconciliation.run
  finance.intercompany.divergence

Events consumed:
  ops.scm.purchase_order.created  — auto-send IC mirror when PO crosses entity boundaries

Usage
-----
Add to your app config::

    PGAPPFORGE_PLUGINS = [
        "pgappforge.plugins.erp.foundation",
        "pgappforge.plugins.erp.finance.intercompany",
    ]

Or instantiate directly::

    from pgappforge.plugins.erp.finance.intercompany import IntercompanyPlugin
    plugin = IntercompanyPlugin(appbuilder)
    plugin.activate()
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class IntercompanyPlugin(BasePlugin):
	"""Intercompany Posting ERP plugin.

	Manages IC transaction flow between legal entities within the same tenant:
	PO/SO mirroring, journal mirroring, payment mirroring, and balance reconciliation.

	Integrates with:
	  - SCM plugin (create_sales_order_from_ic, create_purchase_order_from_ic)
	  - GL plugin (post_journal) for JOURNAL_MIRROR
	  - AR plugin (post_ic_payment) for PAYMENT_MIRROR
	"""

	name = "intercompany"
	domain = "finance"
	depends_on: list[str] = ["foundation"]

	# ------------------------------------------------------------------
	# Metadata
	# ------------------------------------------------------------------

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="intercompany",
			version="1.0.0",
			description=(
				"Intercompany Posting — outbox/inbox transaction flow between legal "
				"entities, PO/SO/journal/payment mirroring, balance reconciliation, "
				"and divergence detection."
			),
			author="PgAppForge Contributors",
			tags=["finance", "intercompany", "group", "multi-entity", "ic-posting"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_ic_outbox_list",
				"can_ic_outbox_send",
				"can_ic_inbox_list",
				"can_ic_inbox_accept",
				"can_ic_inbox_reject",
				"can_ic_reconcile",
				"can_ic_reports",
			],
			safe_mode_compatible=True,
		)

	# ------------------------------------------------------------------
	# get_events / subscribe_to
	# ------------------------------------------------------------------

	def get_events(self) -> list[str]:
		return [
			"finance.intercompany.sent",
			"finance.intercompany.accepted",
			"finance.intercompany.rejected",
			"finance.intercompany.reconciliation.run",
			"finance.intercompany.divergence",
		]

	def subscribe_to(self) -> list[str]:
		"""Consume SCM PO events to trigger IC mirroring when PO crosses entity boundary."""
		return [
			"ops.scm.purchase_order.created",
		]

	# ------------------------------------------------------------------
	# Lifecycle
	# ------------------------------------------------------------------

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"IC_MENU_CATEGORY": "Intercompany",
			"IC_AUTO_MIRROR_PO": False,   # set True to auto-send IC on PO creation
			"IC_RECONCILIATION_TOLERANCE_CENTS": 0,
		}
		self.config = {**defaults, **self.config}
		log.info("IntercompanyPlugin initialised (config keys: %s)", list(self.config))

	def register_views(self) -> None:
		try:
			from pgappforge.plugins.erp.finance.intercompany.views import (
				ICOutboxView,
				ICInboxView,
			)
			cat = self.config.get("IC_MENU_CATEGORY", "Intercompany")
			self.add_view(ICOutboxView, "IC Outbox", icon="fa-paper-plane", category=cat)
			self.add_view(ICInboxView, "IC Inbox", icon="fa-inbox", category=cat)
			log.info("IntercompanyPlugin: views registered under category %r", cat)
		except ImportError:
			log.debug("IntercompanyPlugin: views module not available, skipping view registration")

	def register_models(self) -> list:
		from pgappforge.plugins.erp.finance.intercompany.models import (
			ICOutboxTransaction,
			ICInboxTransaction,
		)
		return [ICOutboxTransaction, ICInboxTransaction]


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_plugin(
	appbuilder: Any,
	config: dict[str, Any] | None = None,
) -> IntercompanyPlugin:
	"""Construct an IntercompanyPlugin without activating it."""
	return IntercompanyPlugin(appbuilder, config=config or {})


# ---------------------------------------------------------------------------
# Public re-exports
# ---------------------------------------------------------------------------

from pgappforge.plugins.erp.finance.intercompany.models import (  # noqa: E402
	ICOutboxTransaction,
	ICInboxTransaction,
)
from pgappforge.plugins.erp.finance.intercompany.events import (  # noqa: E402
	ICTransactionSentEvent,
	ICTransactionAcceptedEvent,
	ICTransactionRejectedEvent,
	ICReconciliationRunEvent,
	ICDivergenceDetectedEvent,
)
from pgappforge.plugins.erp.finance.intercompany.services import (  # noqa: E402
	IntercompanyService,
	IntercompanyServiceError,
	ICTransactionNotFoundError,
	ICInvalidStatusError,
	ICUnsupportedTransactionTypeError,
)

__all__ = [
	# plugin
	"IntercompanyPlugin",
	"create_plugin",
	# models
	"ICOutboxTransaction",
	"ICInboxTransaction",
	# events
	"ICTransactionSentEvent",
	"ICTransactionAcceptedEvent",
	"ICTransactionRejectedEvent",
	"ICReconciliationRunEvent",
	"ICDivergenceDetectedEvent",
	# services
	"IntercompanyService",
	"IntercompanyServiceError",
	"ICTransactionNotFoundError",
	"ICInvalidStatusError",
	"ICUnsupportedTransactionTypeError",
]
