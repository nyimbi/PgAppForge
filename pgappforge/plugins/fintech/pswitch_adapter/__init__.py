"""
pgappforge/plugins/fintech/pswitch_adapter/__init__.py

PswitchAdapterPlugin — bridges pgappforge core banking accounts to the
Hyperion-X ISO 8583 / ISO 20022 payment switch for card authorization
and settlement.

Depends on:
  - pgappforge.plugins.fintech.core_banking
  - pgappforge.plugins.erp.foundation

Sub-modules:
  models   — CardTransaction, CardSettlementFile
  services — PswitchAdapterService
  events   — CardAuthorizedEvent, CardDeclinedEvent, CardSettledEvent,
             CardReversedEvent, SettlementFileProcessedEvent

Usage::

	from pgappforge.plugins.fintech.pswitch_adapter import PswitchAdapterPlugin

	plugin = PswitchAdapterPlugin(appbuilder)
	plugin.activate()

Or import the components directly::

	from pgappforge.plugins.fintech.pswitch_adapter import (
		CardTransaction,
		CardSettlementFile,
		PswitchAdapterService,
		CardAuthorizedEvent,
		CardDeclinedEvent,
		CardSettledEvent,
		CardReversedEvent,
		SettlementFileProcessedEvent,
	)

Configuration
-------------
  PSWITCH_BASE_URL   URL of the Hyperion-X REST API (default: http://localhost:8583)

The adapter is resilient to pswitch unavailability: authorization falls
back to offline approval (hold placed locally), reversal is marked locally
and retried asynchronously.
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority
from pgappforge.plugins.fintech.pswitch_adapter.events import (
	ALL_PSWITCH_EVENT_TYPES,
	CardAuthorizedEvent,
	CardDeclinedEvent,
	CardReversedEvent,
	CardSettledEvent,
	SettlementFileProcessedEvent,
)
from pgappforge.plugins.fintech.pswitch_adapter.models import (
	CardSettlementFile,
	CardTransaction,
)
from pgappforge.plugins.fintech.pswitch_adapter.services import (
	CardTransactionNotFoundError,
	DuplicateTransactionError,
	PswitchAdapterError,
	PswitchAdapterService,
	SettlementFileNotFoundError,
)

log = logging.getLogger(__name__)

__all__ = [
	# Plugin class
	"PswitchAdapterPlugin",
	# Models
	"CardTransaction",
	"CardSettlementFile",
	# Service
	"PswitchAdapterService",
	"PswitchAdapterError",
	"CardTransactionNotFoundError",
	"SettlementFileNotFoundError",
	"DuplicateTransactionError",
	# Events
	"CardAuthorizedEvent",
	"CardDeclinedEvent",
	"CardSettledEvent",
	"CardReversedEvent",
	"SettlementFileProcessedEvent",
	"ALL_PSWITCH_EVENT_TYPES",
]


class PswitchAdapterPlugin(BasePlugin):
	"""Pswitch adapter plugin — card authorization and settlement bridge.

	Registers the CardTransaction and CardSettlementFile models with the
	SQLAlchemy metadata so that Alembic migrations pick them up automatically.

	Class-level attributes used by the plugin registry:
	    name       = "pswitch_adapter"
	    domain     = "fintech"
	    depends_on = ["core_banking"]
	"""

	name = "pswitch_adapter"
	domain = "fintech"
	depends_on: list[str] = ["core_banking"]

	# ------------------------------------------------------------------
	# BasePlugin.metadata (required abstract property)
	# ------------------------------------------------------------------

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="pswitch_adapter",
			version="1.0.0",
			description=(
				"Bridges pgappforge core banking accounts to Hyperion-X "
				"(pswitch) ISO 8583 / ISO 20022 payment switch for card "
				"authorization and settlement."
			),
			domain="fintech",
			author="PgAppForge",
			depends_on=["core_banking"],
			priority=PluginPriority.NORMAL,
			tags=["fintech", "card", "iso8583", "iso20022", "pswitch", "settlement"],
		)

	# ------------------------------------------------------------------
	# BasePlugin hooks
	# ------------------------------------------------------------------

	def register_models(self) -> list[Any]:
		"""Return SQLAlchemy model classes for Alembic autogenerate."""
		return [CardTransaction, CardSettlementFile]

	def get_events(self) -> list[str]:
		"""Return the list of domain event type strings emitted by this plugin."""
		return list(ALL_PSWITCH_EVENT_TYPES)

	def activate(self) -> None:
		"""Register views, permissions, and menu items with AppBuilder."""
		super().activate()
		log.info(
			"pswitch_adapter: plugin activated — PSWITCH_BASE_URL=%s",
			self._resolve_base_url(),
		)

	# ------------------------------------------------------------------
	# Private helpers
	# ------------------------------------------------------------------

	def _resolve_base_url(self) -> str:
		try:
			from flask import current_app
			return current_app.config.get("PSWITCH_BASE_URL", "http://localhost:8583")
		except RuntimeError:
			return "http://localhost:8583"
