"""
pgappforge/plugins/fintech/swift/__init__.py

SWIFT correspondent banking plugin for pgappforge fintech suite.

Provides SWIFT FIN message handling for Kenyan correspondent banking:
  - MT103: Single Customer Credit Transfer (international retail payments)
  - MT202: Financial Institution Transfer (bank-to-bank cover payments)
  - MT900: Confirmation of Debit (nostro debit confirmation)
  - MT910: Confirmation of Credit (nostro credit confirmation)
  - gpi:   UETR lifecycle tracking via SWIFTGpiStatus

Lazy cross-plugin imports (non-fatal if unavailable):
  - pgappforge.plugins.erp.finance.gl         (GL journal posting)
  - pgappforge.plugins.fintech.core_banking   (beneficiary deposit on inbound MT103)

East Africa context:
  - Kenyan banks using Standard Chartered, Citibank, JP Morgan as USD correspondents
  - KES ↔ USD / EUR / GBP remittance via SWIFT
  - Nostro reconciliation for CBK statutory reporting
  - gpi mandatory for all MT103 (SWIFT mandate since Nov 2020)

Usage::

    from pgappforge.plugins.fintech.swift import SWIFTService, SWIFTMessage, SWIFTGpiStatus

    svc = SWIFTService(session=db.session, tenant_id="KCB_NAIROBI")
    msg = svc.create_mt103(
        sender_bic="KCBLKENAXXX",
        receiver_bic="CITIUS33XXX",
        ordering_customer_name="Wanjiku Kamau",
        ordering_account="KE12KCBL0000000000001234",
        beneficiary_name="Acme Corp Ltd",
        beneficiary_account="US12CITI0000000000005678",
        beneficiary_bank_bic="CITIUS33XXX",
        amount_cents=500_000_00,      # USD 500,000.00
        currency_code="USD",
        value_date=date(2026, 6, 10),
        remittance_info="INV-2026-4521",
    )
    db.session.commit()
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority
from pgappforge.plugins.fintech.swift.models import (
	SWIFTGpiStatus,
	SWIFTMessage,
)
from pgappforge.plugins.fintech.swift.events import (
	SWIFTGpiUpdatedEvent,
	SWIFTMessageReceivedEvent,
	SWIFTMessageSentEvent,
	SWIFTNostroCreditConfirmedEvent,
	SWIFTNostroDebitConfirmedEvent,
	# event type constants
	ALL_SWIFT_EVENT_TYPES,
	SWIFT_GPI_UPDATED,
	SWIFT_MESSAGE_RECEIVED,
	SWIFT_MESSAGE_SENT,
	SWIFT_NOSTRO_CREDIT_CONFIRMED,
	SWIFT_NOSTRO_DEBIT_CONFIRMED,
)
from pgappforge.plugins.fintech.swift.services import SWIFTService

_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# SWIFTPlugin — registration interface for the pgappforge plugin registry
# ---------------------------------------------------------------------------

class SWIFTPlugin(BasePlugin):
	"""Lifecycle hook for the SWIFT plugin within the pgappforge plugin registry.

	Called by the registry's install_all() / register_all() methods.
	Extends BasePlugin to satisfy PluginProtocol and the standard lifecycle.
	"""

	name = "swift"
	label = "SWIFT Correspondent Banking"
	version = "1.0.0"
	domain = "fintech"
	depends_on: list[str] = ["foundation"]

	# ------------------------------------------------------------------
	# Metadata (BasePlugin abstract property)
	# ------------------------------------------------------------------

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="swift",
			version="1.0.0",
			description=(
				"SWIFT FIN message handling (MT103/MT202/MT900/MT910) "
				"with gpi UETR tracking and nostro reconciliation."
			),
			author="PgAppForge Contributors",
			tags=["fintech", "swift", "correspondent-banking", "gpi", "mt103", "nostro"],
			priority=PluginPriority.HIGH,
			permissions=[
				"can_swift_message_list",
				"can_swift_message_send",
				"can_swift_gpi_view",
				"can_swift_nostro_reconcile",
			],
		)

	# ------------------------------------------------------------------
	# Plugin protocol methods
	# ------------------------------------------------------------------

	def register_models(self) -> list[type]:
		"""Return SQLAlchemy model classes for Alembic / create_all discovery."""
		return [SWIFTMessage, SWIFTGpiStatus]

	def get_events(self) -> list[str]:
		"""Return dotted event-name strings emitted by this plugin."""
		return list(ALL_SWIFT_EVENT_TYPES)

	def subscribe_to(self) -> list[str]:
		"""Cross-plugin event subscriptions — SWIFT has no upstream dependencies.

		Returns empty list; the plugin is purely a producer of payment events.
		Downstream plugins (treasury, GL, compliance) subscribe to SWIFT events.
		"""
		return []

	# ------------------------------------------------------------------
	# Lifecycle
	# ------------------------------------------------------------------

	def initialize(self) -> None:
		"""Set plugin defaults and log activation."""
		defaults: dict[str, Any] = {
			"SWIFT_MENU_CATEGORY": "Payments",
			"SWIFT_GPI_ENABLED": True,
			"SWIFT_MT103_DAILY_LIMIT_CENTS": 0,  # 0 = no limit
		}
		self.config = {**defaults, **self.config}
		_log.info("SWIFTPlugin initialised (config keys: %s)", list(self.config))

	def activate(self, app: Any = None, db: Any = None, appbuilder: Any = None, **kwargs: Any) -> bool:  # type: ignore[override]
		"""Activate the plugin.

		Accepts optional app/db/appbuilder kwargs for compatibility with the
		ERP install_all() calling convention in addition to the standard
		BasePlugin.activate() path (which uses self.appbuilder).
		"""
		if appbuilder is not None and self.appbuilder is None:
			self.appbuilder = appbuilder
		return super().activate()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	# models
	"SWIFTMessage",
	"SWIFTGpiStatus",
	# service
	"SWIFTService",
	# plugin class
	"SWIFTPlugin",
	# events
	"SWIFTMessageSentEvent",
	"SWIFTMessageReceivedEvent",
	"SWIFTGpiUpdatedEvent",
	"SWIFTNostroDebitConfirmedEvent",
	"SWIFTNostroCreditConfirmedEvent",
	# event type constants
	"ALL_SWIFT_EVENT_TYPES",
	"SWIFT_MESSAGE_SENT",
	"SWIFT_MESSAGE_RECEIVED",
	"SWIFT_GPI_UPDATED",
	"SWIFT_NOSTRO_DEBIT_CONFIRMED",
	"SWIFT_NOSTRO_CREDIT_CONFIRMED",
]
