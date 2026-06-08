"""
pgappforge/plugins/erp/crm/customer_portal/__init__.py

CustomerPortalPlugin — B2B customer self-service portal for CRM/AR.

Events emitted
--------------
  crm.customer_portal.registered          — new portal user registered
  crm.customer_portal.login               — successful portal login
  crm.customer_portal.payment.initiated   — payment submitted from portal
  crm.customer_portal.statement.downloaded — account statement downloaded
  crm.customer_portal.password.reset      — password reset completed

Security highlights
-------------------
- bcrypt passwords with SHA-256 fallback
- SHA-256 session token hashing (raw token returned once, never stored)
- 5-strike account lockout (30-minute window)
- Session TTL: 8 hours; explicit logout revokes immediately

Usage
-----
Add to app config::

    PGAPPFORGE_PLUGINS = [
        "pgappforge.plugins.erp.foundation",
        "pgappforge.plugins.erp.finance.ar",          # optional: live AR data
        "pgappforge.plugins.erp.crm.customer_portal",
    ]

Or instantiate directly::

    from pgappforge.plugins.erp.crm.customer_portal import CustomerPortalPlugin
    plugin = CustomerPortalPlugin(appbuilder)
    plugin.activate()
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class CustomerPortalPlugin(BasePlugin):
	"""Customer self-service portal plugin.

	Provides portal user registration, token-based session management,
	invoice browsing, statement download, and payment initiation — all
	scoped per tenant with bcrypt-protected credentials and account lockout.

	Class-level attributes for dependency resolution:
	    name       = "customer_portal"
	    domain     = "crm"
	    depends_on = ["foundation"]
	"""

	name = "customer_portal"
	domain = "crm"
	depends_on: list[str] = ["foundation"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="customer_portal",
			version="1.0.0",
			description=(
				"Customer Self-Service Portal — B2B portal enabling AR customers to "
				"view invoices, download statements, initiate payments (mobile money, "
				"bank transfer, card), and manage their own credentials with account "
				"lockout protection."
			),
			author="PgAppForge Contributors",
			tags=["crm", "portal", "self-service", "b2b", "customer", "invoices", "payments"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_portal_register",
				"can_portal_login",
				"can_portal_view_invoices",
				"can_portal_download_statement",
				"can_portal_initiate_payment",
				"can_portal_admin_users",
				"can_portal_admin_sessions",
			],
			safe_mode_compatible=True,
		)

	def get_events(self) -> list[str]:
		return [
			"crm.customer_portal.registered",
			"crm.customer_portal.login",
			"crm.customer_portal.payment.initiated",
			"crm.customer_portal.statement.downloaded",
			"crm.customer_portal.password.reset",
		]

	def subscribe_to(self) -> list[str]:
		# Optionally subscribe to AR events when that plugin is loaded
		return [
			"ar.customer.credit_hold_placed",   # could lock portal payment initiation
		]

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"PORTAL_MENU_CATEGORY": "Customer Portal",
			"PORTAL_SESSION_TTL_HOURS": 8,
			"PORTAL_MAX_FAILED_LOGINS": 5,
			"PORTAL_LOCKOUT_MINUTES": 30,
		}
		self.config = {**defaults, **self.config}
		log.info("CustomerPortalPlugin initialised (config keys: %s)", list(self.config))

	def register_views(self) -> None:
		from pgappforge.plugins.erp.crm.customer_portal.views import (
			CustomerPortalUserView,
			PortalPaymentView,
			CustomerPortalDashboardView,
		)
		cat = self.config.get("PORTAL_MENU_CATEGORY", "Customer Portal")
		self.add_view(CustomerPortalDashboardView, "Portal Dashboard", icon="fa-tachometer", category=cat)
		self.add_view(CustomerPortalUserView, "Portal Users", icon="fa-users", category=cat)
		self.add_view(PortalPaymentView, "Payments", icon="fa-credit-card", category=cat)
		log.info("CustomerPortalPlugin: views registered under %r", cat)

	def register_models(self) -> list:
		from pgappforge.plugins.erp.crm.customer_portal.models import (
			CustomerPortalUser,
			PortalPayment,
			PortalSession,
		)
		return [CustomerPortalUser, PortalSession, PortalPayment]


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_plugin(
	appbuilder: Any,
	config: dict[str, Any] | None = None,
) -> CustomerPortalPlugin:
	"""Construct and return a CustomerPortalPlugin bound to *appbuilder*.

	Does NOT call activate()::

	    plugin = create_plugin(appbuilder)
	    plugin.activate()
	"""
	return CustomerPortalPlugin(appbuilder, config=config or {})


# ---------------------------------------------------------------------------
# Public API re-exports
# ---------------------------------------------------------------------------

from pgappforge.plugins.erp.crm.customer_portal.models import (  # noqa: E402
	CustomerPortalUser,
	PortalPayment,
	PortalSession,
)
from pgappforge.plugins.erp.crm.customer_portal.events import (  # noqa: E402
	CustomerPortalLoginEvent,
	CustomerPortalRegisteredEvent,
	PortalPasswordResetEvent,
	PortalPaymentInitiatedEvent,
	PortalStatementDownloadedEvent,
)
from pgappforge.plugins.erp.crm.customer_portal.services import (  # noqa: E402
	CustomerPortalAuthError,
	CustomerPortalError,
	CustomerPortalNotFoundError,
	CustomerPortalService,
	CustomerPortalValidationError,
)

__all__ = [
	# plugin
	"CustomerPortalPlugin",
	"create_plugin",
	# models
	"CustomerPortalUser",
	"PortalSession",
	"PortalPayment",
	# events
	"CustomerPortalRegisteredEvent",
	"CustomerPortalLoginEvent",
	"PortalPaymentInitiatedEvent",
	"PortalStatementDownloadedEvent",
	"PortalPasswordResetEvent",
	# services
	"CustomerPortalService",
	"CustomerPortalError",
	"CustomerPortalNotFoundError",
	"CustomerPortalAuthError",
	"CustomerPortalValidationError",
]
