"""
pgappforge/plugins/fintech/banking_api/__init__.py

BankingAPIPlugin — consumer banking REST API plugin.

Registers the ``/api/v1/banking`` Flask Blueprint that backs mobile banking
apps and internet banking front-ends.  Authentication is via Bearer JWT token
(validated against FAB user session or API key) or X-API-Key header.

Depends on ``core_banking`` for models and ``CoreBankingService``.  Does NOT
introduce new SQLAlchemy models.

Configuration keys (set in Flask app.config or plugin config dict):
  BANKING_API_KEYS        dict  {api_key: {tenant_id, customer_id}}
  BANKING_API_MASTER_KEY  str   single master key for admin/testing (empty = disabled)
  BANKING_API_RATE_LIMIT  int   requests per minute per key (default 100; enforcement
                                is left to the caller / reverse-proxy layer)

Endpoints:
  GET  /api/v1/banking/health
  GET  /api/v1/banking/accounts/<account_number>/balance
  GET  /api/v1/banking/accounts/<account_number>/statement
  GET  /api/v1/banking/accounts/<account_number>/mini-statement
  POST /api/v1/banking/transfers
  GET  /api/v1/banking/products
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class BankingAPIPlugin(BasePlugin):
	"""Consumer Banking REST API plugin.

	Class-level attributes:
	    name       = "banking_api"
	    domain     = "fintech"
	    depends_on = ["foundation", "core_banking"]
	"""

	name = "banking_api"
	domain = "fintech"
	depends_on: list[str] = ["foundation", "core_banking"]

	# ------------------------------------------------------------------
	# BasePlugin.metadata (required abstract property)
	# ------------------------------------------------------------------

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="banking_api",
			version="1.0.0",
			description=(
				"Consumer Banking REST API — mobile banking and internet banking "
				"endpoints.  Exposes account balance, statement, mini-statement, "
				"fund transfer, and product catalogue under /api/v1/banking.  "
				"Authentication via Bearer token or X-API-Key."
			),
			author="PgAppForge Contributors",
			tags=["fintech", "banking", "rest-api", "mobile-banking", "internet-banking"],
			priority=PluginPriority.HIGH,
			permissions=[
				"can_banking_api_balance",
				"can_banking_api_statement",
				"can_banking_api_transfer",
				"can_banking_api_products",
			],
			safe_mode_compatible=True,
		)

	# ------------------------------------------------------------------
	# get_events / subscribe_to
	# ------------------------------------------------------------------

	def get_events(self) -> list[str]:
		"""This plugin emits no domain events of its own."""
		return []

	def subscribe_to(self) -> list[str]:
		"""This plugin does not subscribe to cross-plugin events."""
		return []

	# ------------------------------------------------------------------
	# Lifecycle
	# ------------------------------------------------------------------

	def initialize(self) -> None:
		"""Merge config defaults and propagate API keys to Flask app.config."""
		defaults: dict[str, Any] = {
			"BANKING_API_KEYS": {},       # {api_key: {tenant_id, customer_id}}
			"BANKING_API_MASTER_KEY": "", # empty = disabled
			"BANKING_API_RATE_LIMIT": 100,
		}
		self.config = {**defaults, **self.config}

		# Propagate to Flask app.config so the auth middleware can read them
		# without importing the plugin instance.
		try:
			from flask import current_app
			app = current_app._get_current_object()
			for key in ("BANKING_API_KEYS", "BANKING_API_MASTER_KEY", "BANKING_API_RATE_LIMIT"):
				# Only write if not already set so callers can pre-configure.
				if key not in app.config:
					app.config[key] = self.config[key]
		except RuntimeError:
			# No app context during unit tests — skip silently.
			pass
		except Exception as exc:
			log.warning("BankingAPIPlugin.initialize: could not propagate config: %s", exc)

		log.info("BankingAPIPlugin initialized")

	def register_views(self) -> None:
		"""Register the Banking API blueprint and FAB nav link with the Flask app.

		Idempotent: skips registration if the blueprint is already present
		(e.g. when the plugin is activated more than once in tests).
		"""
		try:
			from flask import current_app
			from pgappforge.plugins.fintech.banking_api.api import BANKING_API_BP

			app = current_app._get_current_object()
			if "banking_api" not in app.blueprints:
				app.register_blueprint(BANKING_API_BP)
				self._registered_blueprints.append("banking_api")
				log.info(
					"BankingAPIPlugin: registered blueprint at %s",
					BANKING_API_BP.url_prefix,
				)
			else:
				log.debug("BankingAPIPlugin: blueprint 'banking_api' already registered — skipping")

		except RuntimeError:
			# No app context — acceptable during test/import time.
			log.debug("BankingAPIPlugin.register_views: no app context, deferred")
		except Exception as exc:
			log.warning("BankingAPIPlugin.register_views failed: %s", exc)

		try:
			from pgappforge.plugins.erp.base_view import BaseERPView
			from pgappforge import expose
			from pgappforge.security.decorators import has_access
			from flask import redirect

			class BankingAPIDocsView(BaseERPView):
				route_base = "/fintech/banking-api-docs"

				@expose("/")
				@has_access
				def index(self):
					from flask import redirect
					return redirect("/api/v1/banking/docs")

			self.add_view(BankingAPIDocsView, "Banking API Docs", icon="fa-code", category="Fintech")
		except Exception as exc:
			import logging
			logging.getLogger(__name__).debug("BankingAPIPlugin.register_views: %s", exc)

	def register_models(self) -> list:
		"""No new models — this plugin reuses core_banking models."""
		return []


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_plugin(
	appbuilder: Any,
	config: dict[str, Any] | None = None,
) -> BankingAPIPlugin:
	"""Construct and return a BankingAPIPlugin bound to *appbuilder*.

	Does NOT call activate()::

	    plugin = create_plugin(appbuilder, config={"BANKING_API_MASTER_KEY": "secret"})
	    plugin.activate()
	"""
	return BankingAPIPlugin(appbuilder, config=config or {})


# ---------------------------------------------------------------------------
# Public re-exports
# ---------------------------------------------------------------------------

from pgappforge.plugins.fintech.banking_api.api import BANKING_API_BP  # noqa: E402

__all__ = [
	"BankingAPIPlugin",
	"create_plugin",
	"BANKING_API_BP",
]
