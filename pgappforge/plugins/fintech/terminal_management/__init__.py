"""
pgappforge/plugins/fintech/terminal_management/__init__.py

TerminalManagementPlugin — POS/ATM terminal lifecycle, key injection,
parameter deployment, health monitoring, and batch settlement.

Depends on: foundation, core_banking

Registers
---------
  - TerminalView             (Terminal Mgmt menu)
  - TerminalHealthView       (Terminal Mgmt menu — read-only)
  - TerminalDashboardView    (/fintech/terminals-dashboard/)

Events emitted
--------------
  terminal.provisioned, terminal.activated, terminal.key_injected,
  terminal.tamper_alert, terminal.batch_closed

BPM processes
-------------
  terminal.provision, terminal.record_health_event

Config keys
-----------
  TM_MENU_CATEGORY  — menu category label (default: "Terminal Management")
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class TerminalManagementPlugin(BasePlugin):
	"""POS/ATM terminal lifecycle management plugin.

	Class-level attributes used by the plugin registry:
	    name       = "terminal_management"
	    domain     = "fintech"
	    depends_on = ["foundation", "core_banking"]
	"""

	name = "terminal_management"
	domain = "fintech"
	depends_on: list[str] = ["foundation", "core_banking"]

	# ------------------------------------------------------------------
	# BasePlugin.metadata (required abstract property)
	# ------------------------------------------------------------------

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="terminal_management",
			version="1.0.0",
			description=(
				"Terminal Management — full POS/ATM/mPOS terminal lifecycle, "
				"AES-256 cryptographic key injection (TMK/TPK/TAK/ZMK/ZPK/DUKPT_BDK), "
				"versioned parameter deployment, health event monitoring with tamper "
				"detection, heartbeat tracking, and end-of-day batch settlement. "
				"Depends on core_banking for merchant/account linkage."
			),
			author="PgAppForge Contributors",
			tags=[
				"fintech", "terminal", "pos", "atm", "mpos",
				"key-injection", "pci-dss", "batch-settlement",
			],
			priority=PluginPriority.HIGH,
			permissions=[
				"can_tm_terminal_list",
				"can_tm_terminal_write",
				"can_tm_health_list",
				"can_tm_dashboard",
			],
			safe_mode_compatible=True,
		)

	# ------------------------------------------------------------------
	# Lifecycle
	# ------------------------------------------------------------------

	def initialize(self) -> None:
		"""Merge config defaults."""
		defaults: dict[str, Any] = {
			"TM_MENU_CATEGORY": "Terminal Management",
		}
		self.config = {**defaults, **self.config}
		log.info("TerminalManagementPlugin initialised (config keys: %s)", list(self.config))

	def register_models(self) -> list:
		"""Model classes for Alembic autogenerate discovery."""
		from pgappforge.plugins.fintech.terminal_management.models import (
			Terminal,
			TerminalBatch,
			TerminalHealthEvent,
			TerminalKey,
			TerminalParameter,
		)
		return [Terminal, TerminalKey, TerminalParameter, TerminalHealthEvent, TerminalBatch]

	def register_views(self) -> None:
		"""Register views under the configured menu category."""
		from pgappforge.plugins.fintech.terminal_management.views import (
			TerminalDashboardView,
			TerminalHealthView,
			TerminalView,
		)

		cat = self.config.get("TM_MENU_CATEGORY", "Terminal Management")

		self.add_view(
			TerminalView,
			"Terminals",
			icon="fa-desktop",
			category=cat,
		)
		self.add_view(
			TerminalHealthView,
			"Health Events",
			icon="fa-heartbeat",
			category=cat,
		)
		self.add_view(
			TerminalDashboardView,
			"Dashboard",
			icon="fa-tachometer-alt",
			category=cat,
		)

		log.info("TerminalManagementPlugin: views registered under category %r", cat)

	# ------------------------------------------------------------------
	# Events
	# ------------------------------------------------------------------

	def get_events(self) -> list[str]:
		"""Event types this plugin emits."""
		from pgappforge.plugins.fintech.terminal_management.events import ALL_TM_EVENT_TYPES
		return ALL_TM_EVENT_TYPES

	def subscribe_to(self) -> list[str]:
		"""Events this plugin consumes (none currently)."""
		return []


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_plugin(
	appbuilder: Any,
	config: dict[str, Any] | None = None,
) -> TerminalManagementPlugin:
	"""Construct and return a TerminalManagementPlugin bound to *appbuilder*.

	Does NOT call activate()::

	    plugin = create_plugin(appbuilder)
	    plugin.activate()
	"""
	return TerminalManagementPlugin(appbuilder, config=config or {})


# ---------------------------------------------------------------------------
# Public API re-exports
# ---------------------------------------------------------------------------

from pgappforge.plugins.fintech.terminal_management.models import (  # noqa: E402
	Terminal,
	TerminalBatch,
	TerminalHealthEvent,
	TerminalKey,
	TerminalParameter,
)
from pgappforge.plugins.fintech.terminal_management.events import (  # noqa: E402
	ALL_TM_EVENT_TYPES,
	BatchClosedEvent,
	KeyInjectedEvent,
	TerminalActivatedEvent,
	TerminalProvisionedEvent,
	TerminalTamperEvent,
	TM_BATCH_CLOSED,
	TM_KEY_INJECTED,
	TM_TAMPER_ALERT,
	TM_TERMINAL_ACTIVATED,
	TM_TERMINAL_PROVISIONED,
)
from pgappforge.plugins.fintech.terminal_management.services import (  # noqa: E402
	BatchError,
	TerminalManagementError,
	TerminalManagementService,
	TerminalNotFoundError,
	TerminalStateError,
	TerminalValidationError,
)
from pgappforge.plugins.fintech.terminal_management.views import (  # noqa: E402
	TerminalDashboardView,
	TerminalHealthView,
	TerminalView,
)

__all__ = [
	# plugin
	"TerminalManagementPlugin",
	"create_plugin",
	# models
	"Terminal",
	"TerminalKey",
	"TerminalParameter",
	"TerminalHealthEvent",
	"TerminalBatch",
	# events — classes
	"TerminalProvisionedEvent",
	"TerminalActivatedEvent",
	"KeyInjectedEvent",
	"TerminalTamperEvent",
	"BatchClosedEvent",
	# events — type constants
	"TM_TERMINAL_PROVISIONED",
	"TM_TERMINAL_ACTIVATED",
	"TM_KEY_INJECTED",
	"TM_TAMPER_ALERT",
	"TM_BATCH_CLOSED",
	"ALL_TM_EVENT_TYPES",
	# services
	"TerminalManagementService",
	"TerminalManagementError",
	"TerminalNotFoundError",
	"TerminalStateError",
	"TerminalValidationError",
	"BatchError",
	# views
	"TerminalView",
	"TerminalHealthView",
	"TerminalDashboardView",
]
