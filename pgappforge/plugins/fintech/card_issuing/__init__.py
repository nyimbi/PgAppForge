"""
pgappforge/plugins/fintech/card_issuing/__init__.py

CardIssuingPlugin — virtual card issuance, PIN management, and authorization.

Depends on: foundation, core_banking

Registers
---------
  - CardBINView             (Card Issuing menu)
  - IssuedCardView          (Card Issuing menu)
  - CardAuthorizationLogView (Card Issuing menu)
  - CardIssuingDashboardView (/fintech/cards/)

Events emitted
--------------
  card.issued, card.activated, card.blocked,
  card.pin_set, card.authorized, card.replaced

Config keys
-----------
  CARD_PIN_MASTER_KEY  — required for PIN operations; read from app.config then os.environ
  CI_MENU_CATEGORY     — menu category label (default: "Card Issuing")
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class CardIssuingPlugin(BasePlugin):
	"""Virtual card issuance, PIN management, 3DS OTP, and authorization plugin.

	Class-level attributes used by the plugin registry:
	    name       = "card_issuing"
	    domain     = "fintech"
	    depends_on = ["foundation", "core_banking"]
	"""

	name = "card_issuing"
	domain = "fintech"
	depends_on: list[str] = ["foundation", "core_banking"]

	# ------------------------------------------------------------------
	# BasePlugin.metadata (required abstract property)
	# ------------------------------------------------------------------

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="card_issuing",
			version="1.0.0",
			description=(
				"Card Issuing engine — virtual card issuance, BIN registry, "
				"AES-256-GCM PIN management, HMAC-TOTP 3DS OTP generation, "
				"and per-card authorization with daily spend limits. "
				"Depends on core_banking for account linkage."
			),
			author="PgAppForge Contributors",
			tags=["fintech", "card-issuing", "payments", "pin", "3ds", "virtual-card"],
			priority=PluginPriority.HIGH,
			permissions=[
				"can_ci_bin_list",
				"can_ci_bin_write",
				"can_ci_card_list",
				"can_ci_card_show",
				"can_ci_auth_log_list",
				"can_ci_dashboard",
			],
			safe_mode_compatible=True,
		)

	# ------------------------------------------------------------------
	# Lifecycle
	# ------------------------------------------------------------------

	def initialize(self) -> None:
		"""Merge config defaults."""
		defaults: dict[str, Any] = {
			"CI_MENU_CATEGORY": "Card Issuing",
			"CI_DEFAULT_EXPIRY_MONTHS": 36,
			"CI_DEFAULT_CURRENCY": "KES",
			"CI_MAX_PIN_ATTEMPTS": 3,
		}
		self.config = {**defaults, **self.config}
		log.info("CardIssuingPlugin initialised (config keys: %s)", list(self.config))

	def register_models(self) -> list:
		"""Model classes for Alembic autogenerate discovery."""
		from pgappforge.plugins.fintech.card_issuing.models import (
			CardAuthorizationLog,
			CardBIN,
			IssuedCard,
			PINBlock,
		)
		return [CardBIN, IssuedCard, PINBlock, CardAuthorizationLog]

	def register_views(self) -> None:
		"""Register views under the configured menu category."""
		from pgappforge.plugins.fintech.card_issuing.views import (
			CardAuthorizationLogView,
			CardBINView,
			CardIssuingDashboardView,
			IssuedCardView,
		)

		cat = self.config.get("CI_MENU_CATEGORY", "Card Issuing")

		self.add_view(
			CardBINView,
			"Card BINs",
			icon="fa-database",
			category=cat,
		)
		self.add_view(
			IssuedCardView,
			"Issued Cards",
			icon="fa-credit-card",
			category=cat,
		)
		self.add_view(
			CardAuthorizationLogView,
			"Authorization Log",
			icon="fa-list-alt",
			category=cat,
		)
		self.add_view(
			CardIssuingDashboardView,
			"Dashboard",
			icon="fa-tachometer-alt",
			category=cat,
		)

		log.info("CardIssuingPlugin: views registered under category %r", cat)

	# ------------------------------------------------------------------
	# Events
	# ------------------------------------------------------------------

	def get_events(self) -> list[str]:
		"""Event types this plugin emits."""
		from pgappforge.plugins.fintech.card_issuing.events import ALL_CI_EVENT_TYPES
		return ALL_CI_EVENT_TYPES

	def subscribe_to(self) -> list[str]:
		"""Events this plugin consumes (none currently)."""
		return []


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_plugin(
	appbuilder: Any,
	config: dict[str, Any] | None = None,
) -> CardIssuingPlugin:
	"""Construct and return a CardIssuingPlugin bound to *appbuilder*.

	Does NOT call activate()::

	    plugin = create_plugin(appbuilder)
	    plugin.activate()
	"""
	return CardIssuingPlugin(appbuilder, config=config or {})


# ---------------------------------------------------------------------------
# Public API re-exports
# ---------------------------------------------------------------------------

from pgappforge.plugins.fintech.card_issuing.models import (  # noqa: E402
	CardAuthorizationLog,
	CardBIN,
	IssuedCard,
	PINBlock,
)
from pgappforge.plugins.fintech.card_issuing.events import (  # noqa: E402
	ALL_CI_EVENT_TYPES,
	CardActivatedEvent,
	CardAuthorizationEvent,
	CardBlockedEvent,
	CardIssuedEvent,
	CardPINSetEvent,
	CardReplacedEvent,
	CI_CARD_ACTIVATED,
	CI_CARD_AUTHORIZED,
	CI_CARD_BLOCKED,
	CI_CARD_ISSUED,
	CI_CARD_PIN_SET,
	CI_CARD_REPLACED,
)
from pgappforge.plugins.fintech.card_issuing.services import (  # noqa: E402
	CardIssuingError,
	CardIssuingService,
	CardNotFoundError,
	CardStatusError,
	PINError,
	PINMasterKeyNotConfiguredError,
)
from pgappforge.plugins.fintech.card_issuing.views import (  # noqa: E402
	CardAuthorizationLogView,
	CardBINView,
	CardIssuingDashboardView,
	IssuedCardView,
)

__all__ = [
	# plugin
	"CardIssuingPlugin",
	"create_plugin",
	# models
	"CardBIN",
	"IssuedCard",
	"PINBlock",
	"CardAuthorizationLog",
	# events — classes
	"CardIssuedEvent",
	"CardActivatedEvent",
	"CardBlockedEvent",
	"CardPINSetEvent",
	"CardAuthorizationEvent",
	"CardReplacedEvent",
	# events — type constants
	"CI_CARD_ISSUED",
	"CI_CARD_ACTIVATED",
	"CI_CARD_BLOCKED",
	"CI_CARD_PIN_SET",
	"CI_CARD_AUTHORIZED",
	"CI_CARD_REPLACED",
	"ALL_CI_EVENT_TYPES",
	# services
	"CardIssuingService",
	"CardIssuingError",
	"CardNotFoundError",
	"CardStatusError",
	"PINError",
	"PINMasterKeyNotConfiguredError",
	# views
	"CardBINView",
	"IssuedCardView",
	"CardAuthorizationLogView",
	"CardIssuingDashboardView",
]
