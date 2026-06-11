"""
pgappforge/plugins/erp/platform/apg_bridge/__init__.py

APGBridgePlugin — bidirectional interoperability with APG capability platform.

Domain:    platform
Depends:   foundation, ipaas

Events consumed (via event bridge)
------------------------------------
  finance.ap.invoice.created
  hcm.payroll.run.finalized
  lending.loan.approved
  club.member.approved
  sacco.member.approved
  remittance.transfer.initiated
  bnpl.application.approved

Config keys
-----------
  APG_BASE_URL         str   APG main Flask-AppBuilder app (default: http://localhost:5000)
  APG_MARKETPLACE_URL  str   APG FastAPI marketplace (default: http://localhost:8000)
  APG_AUTH_EMAIL       str   Login email for JWT auth (default: "")
  APG_AUTH_PASSWORD    str   Login password for JWT auth (default: "")
  APG_STATIC_TOKEN     str   Pre-issued JWT token; skips login if set (default: "")
  APG_ENABLED          bool  Must be explicitly True to activate (default: False)
  APG_TIMEOUT          int   HTTP timeout in seconds (default: 15)
  APG_EVENT_FORWARD    bool  Forward PgAppForge events to APG streams (default: True)
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)

_CONFIG_DEFAULTS: dict[str, Any] = {
	"APG_BASE_URL":        "http://localhost:5000",
	"APG_MARKETPLACE_URL": "http://localhost:8000",
	"APG_AUTH_EMAIL":      "",
	"APG_AUTH_PASSWORD":   "",
	"APG_STATIC_TOKEN":    "",
	"APG_ENABLED":         False,
	"APG_TIMEOUT":         15,
	"APG_EVENT_FORWARD":   True,
}


class APGBridgePlugin(BasePlugin):
	"""Bidirectional integration bridge between PgAppForge and APG.

	Calls APG capabilities from PgAppForge workflows via the /evaluate endpoint;
	forwards PgAppForge domain events to APG Bytewax streams; syncs APG
	marketplace capabilities as iPaaS ConnectorDefinitions.
	"""

	name = "apg_bridge"
	domain = "platform"
	depends_on: list[str] = ["foundation", "ipaas"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="apg_bridge",
			version="1.0.0",
			description=(
				"Bidirectional integration with APG capability platform. "
				"Calls APG capabilities from PgAppForge workflows; "
				"forwards domain events to APG Bytewax streams."
			),
			author="PgAppForge Contributors",
			tags=[
				"platform",
				"integration",
				"apg",
				"bridge",
				"interoperability",
				"bytewax",
			],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_apg_bridge_read",
				"can_apg_bridge_sync",
				"can_apg_capability_read",
			],
			safe_mode_compatible=True,
		)

	def get_events(self) -> list[str]:
		return [
			"platform.apg.capability.synced",
			"platform.apg.event.forwarded",
		]

	def subscribe_to(self) -> list[str]:
		# Event bridge subscriptions are wired in post_initialize() via
		# APGBridgeService.register_event_bridge(), not through the standard
		# post_initialize() auto-wire, because the handler needs APGBridgeService
		# rather than a plugin method.
		return []

	def initialize(self) -> None:
		"""Apply config defaults — APG_ENABLED stays False until explicitly set."""
		try:
			from flask import current_app
			for key, default in _CONFIG_DEFAULTS.items():
				current_app.config.setdefault(key, default)
		except RuntimeError:
			# Outside app context (test import, CLI) — store in plugin config dict
			for key, default in _CONFIG_DEFAULTS.items():
				self.config.setdefault(key, default)
		log.info("APGBridgePlugin: initialised (APG_ENABLED=%s)", self.config.get("APG_ENABLED", False))

	def post_initialize(self) -> None:
		"""Wire the event bridge if APG is enabled; warn loudly if not."""
		# Run base class auto-wire first (handles subscribe_to() entries)
		super().post_initialize()

		try:
			from flask import current_app
			enabled = current_app.config.get("APG_ENABLED", False)
		except RuntimeError:
			enabled = self.config.get("APG_ENABLED", False)

		if enabled:
			try:
				from pgappforge.plugins.erp.platform.apg_bridge.services import APGBridgeService
				n = APGBridgeService().register_event_bridge()
				log.info("APGBridgePlugin: event bridge active — %d subscriptions registered", n)
			except Exception as exc:
				log.warning("APGBridgePlugin: event bridge registration failed: %s", exc)
		else:
			log.warning(
				"APGBridgePlugin: APG_ENABLED=False — bridge is passive. "
				"Set APG_ENABLED=True in app config to activate."
			)

	def register_views(self) -> None:
		from pgappforge.plugins.erp.platform.apg_bridge.views import (
			APGBridgeDashboardView,
			APGCapabilityCacheView,
		)
		cat = self.config.get("APG_MENU_CATEGORY", "Integrations")
		self.add_view(
			APGBridgeDashboardView,
			"APG Bridge",
			icon="fa-exchange",
			category=cat,
		)
		self.add_view(
			APGCapabilityCacheView,
			"APG Capabilities",
			icon="fa-cubes",
			category=cat,
		)
		log.info("APGBridgePlugin: views registered under %r", cat)

	def register_models(self) -> list:
		from pgappforge.plugins.erp.platform.apg_bridge.models import (
			APGCapabilityCache,
			APGEventBridgeLog,
		)
		return [APGCapabilityCache, APGEventBridgeLog]

	def activate(self, app: Any = None, db: Any = None, appbuilder: Any = None) -> None:
		"""PluginProtocol.activate — delegates to BasePlugin.activate()."""
		super().activate()


def create_plugin(
	appbuilder: Any,
	config: dict[str, Any] | None = None,
) -> APGBridgePlugin:
	"""Factory function for plugin registry auto-discovery."""
	return APGBridgePlugin(appbuilder, config=config or {})


# Public re-exports
from pgappforge.plugins.erp.platform.apg_bridge.client import (  # noqa: E402
	APGClient,
	APGError,
	APGAuthError,
	APGCapabilityError,
)
from pgappforge.plugins.erp.platform.apg_bridge.models import (  # noqa: E402
	APGCapabilityCache,
	APGEventBridgeLog,
)
from pgappforge.plugins.erp.platform.apg_bridge.services import APGBridgeService  # noqa: E402

__all__ = [
	# Plugin
	"APGBridgePlugin",
	"create_plugin",
	# Client
	"APGClient",
	"APGError",
	"APGAuthError",
	"APGCapabilityError",
	# Models
	"APGCapabilityCache",
	"APGEventBridgeLog",
	# Service
	"APGBridgeService",
]
