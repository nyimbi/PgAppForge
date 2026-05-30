"""
pgappforge/plugins/billing/__init__.py

SaaS Billing Plugin for PgAppForge.

Provides full subscription lifecycle management, invoicing, usage metering,
dunning, and Stripe integration as a self-contained plugin.

Enable
------
Add to ``PGAPPFORGE_PLUGINS`` in your app config::

    PGAPPFORGE_PLUGINS = [
        "pgappforge.plugins.billing.BillingPlugin",
    ]

Or instantiate manually::

    from pgappforge.plugins.billing import create_plugin
    plugin = create_plugin(appbuilder, config={...})
    plugin.activate()

Config keys
-----------
``PGAF_BILLING_STRIPE_SECRET_KEY``
    Stripe secret key (``sk_live_…`` or ``sk_test_…``).
    Optional — omit to operate in local-only mode.

``PGAF_BILLING_STRIPE_WEBHOOK_SECRET``
    Stripe webhook signing secret (``whsec_…``).
    Required for ``POST /billing/webhooks/stripe`` to validate signatures.

``PGAF_BILLING_CURRENCY``
    ISO-4217 default currency code (default: ``"USD"``).

``PGAF_BILLING_TRIAL_DAYS``
    Default trial length when a plan does not specify its own (default: ``14``).

``PGAF_BILLING_TRIAL_WARN_DAYS``
    Days before trial expiry at which to emit warnings in ``on_user_login``
    (default: ``3``).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

# Optional Stripe — guard at import time so the plugin loads even without it
try:
	import stripe as _stripe_mod
	_HAS_STRIPE = True
except ImportError:
	_stripe_mod = None  # type: ignore[assignment]
	_HAS_STRIPE = False

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy model / view imports (deferred so SQLAlchemy metadata is not touched
# before the Flask app context is ready)
# ---------------------------------------------------------------------------


def _import_models():
	from .models import (
		Plan,
		Subscription,
		Invoice,
		InvoiceItem,
		Payment,
		UsageRecord,
		DunningAttempt,
		Coupon,
	)
	return [Plan, Subscription, Invoice, InvoiceItem, Payment, UsageRecord, DunningAttempt, Coupon]


def _import_views():
	from .views import (
		BillingDashboardView,
		SubscriptionListView,
		InvoiceView,
		UsageView,
		DunningView,
		BillingApiView,
		InvoicePdfApiView,
		StripeWebhookView,
	)
	return (
		BillingDashboardView,
		SubscriptionListView,
		InvoiceView,
		UsageView,
		DunningView,
		BillingApiView,
		InvoicePdfApiView,
		StripeWebhookView,
	)


def _import_engine():
	from .engine import BillingEngine
	return BillingEngine


# ---------------------------------------------------------------------------
# BillingPlugin
# ---------------------------------------------------------------------------

class BillingPlugin(BasePlugin):
	"""
	PgAppForge plugin: comprehensive SaaS billing.

	Lifecycle
	---------
	1. ``initialize()``   — validate config, optionally init Stripe client,
	                        store BillingEngine on the Flask app.
	2. ``register_views()`` — mount dashboard, subscriptions, invoices, usage,
	                          dunning, REST API, and Stripe webhook views.
	3. ``register_models()`` — expose all billing models for Alembic.
	4. Hook overrides:
	   - ``on_user_login``  — check active subscription; warn if trial expiring.
	   - ``on_app_ready``   — attach BillingEngine to ``app._billing_engine``.

	Depends on ``pgappforge.plugins.tenancy.TenancyPlugin`` being registered
	first so that ``tenancy_tenant`` exists when billing FKs are resolved.
	"""

	# ------------------------------------------------------------------
	# Metadata
	# ------------------------------------------------------------------

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="billing",
			version="1.0.0",
			description=(
				"Full SaaS billing: plans, subscriptions, invoicing, "
				"usage metering, dunning, coupons, and Stripe integration."
			),
			author="PgAppForge Contributors",
			tags=[
				"billing", "saas", "stripe", "subscriptions",
				"invoicing", "usage", "dunning", "coupons",
			],
			priority=PluginPriority.HIGH,
			permissions=[
				"can_view_billing_dashboard",
				"can_list_subscriptions",
				"can_view_invoices",
				"can_download_invoice_pdf",
				"can_view_usage",
				"can_manage_dunning",
				"can_use_billing_api",
			],
			safe_mode_compatible=False,
			example_config={
				"PGAF_BILLING_STRIPE_SECRET_KEY": "sk_test_...",
				"PGAF_BILLING_STRIPE_WEBHOOK_SECRET": "whsec_...",
				"PGAF_BILLING_CURRENCY": "USD",
				"PGAF_BILLING_TRIAL_DAYS": 14,
				"PGAF_BILLING_TRIAL_WARN_DAYS": 3,
			},
		)

	# ------------------------------------------------------------------
	# Lifecycle
	# ------------------------------------------------------------------

	def initialize(self) -> None:
		"""
		Validate config and initialise the BillingEngine.

		Stores the engine on ``self._engine`` so ``register_views`` and hook
		methods can access it without re-parsing config.
		"""
		app_config: dict[str, Any] = {}
		if self.appbuilder is not None:
			try:
				app_config = self.appbuilder.get_app.config
			except Exception:
				pass

		def _cfg(key: str, default: Any = None) -> Any:
			return self.config.get(key) or app_config.get(key) or default

		stripe_key: str | None = _cfg("PGAF_BILLING_STRIPE_SECRET_KEY")
		self._currency: str = str(_cfg("PGAF_BILLING_CURRENCY", "USD")).upper()
		self._default_trial_days: int = int(_cfg("PGAF_BILLING_TRIAL_DAYS", 14))
		self._trial_warn_days: int = int(_cfg("PGAF_BILLING_TRIAL_WARN_DAYS", 3))

		if stripe_key and not _HAS_STRIPE:
			log.warning(
				"BillingPlugin: PGAF_BILLING_STRIPE_SECRET_KEY is set but the "
				"`stripe` package is not installed — Stripe features disabled. "
				"Install with: pip install stripe"
			)
			stripe_key = None
		elif stripe_key:
			log.info("BillingPlugin: Stripe client configured")
		else:
			log.info("BillingPlugin: no Stripe key — operating in local-only mode")

		BillingEngine = _import_engine()
		self._engine = BillingEngine(
			stripe_secret_key=stripe_key,
			default_currency=self._currency,
		)

	def on_app_ready(self, app) -> None:
		"""Attach the BillingEngine to the Flask app for view-layer access."""
		app._billing_engine = self._engine
		log.debug("BillingPlugin: engine attached to app")

	# ------------------------------------------------------------------
	# Views
	# ------------------------------------------------------------------

	def register_views(self) -> None:
		"""Register all billing views and REST endpoints."""
		(
			BillingDashboardView,
			SubscriptionListView,
			InvoiceView,
			UsageView,
			DunningView,
			BillingApiView,
			InvoicePdfApiView,
			StripeWebhookView,
		) = _import_views()

		_CATEGORY = "Billing"
		_CATEGORY_ICON = "fa-credit-card"

		self.add_view(
			BillingDashboardView,
			"Dashboard",
			icon="fa-tachometer",
			category=_CATEGORY,
			category_icon=_CATEGORY_ICON,
		)
		self.add_view(
			SubscriptionListView,
			"Subscriptions",
			icon="fa-users",
			category=_CATEGORY,
		)
		self.add_view(
			InvoiceView,
			"Invoices",
			icon="fa-file-text-o",
			category=_CATEGORY,
		)
		self.add_view(
			UsageView,
			"Usage Metrics",
			icon="fa-bar-chart",
			category=_CATEGORY,
		)
		self.add_view(
			DunningView,
			"Dunning",
			icon="fa-exclamation-triangle",
			category=_CATEGORY,
		)

		# REST + webhook endpoints — no menu entries
		self.add_view_no_menu(BillingApiView)
		self.add_view_no_menu(InvoicePdfApiView)
		self.add_view_no_menu(StripeWebhookView)

		log.debug("BillingPlugin: %d views registered", 8)

	# ------------------------------------------------------------------
	# Models
	# ------------------------------------------------------------------

	def register_models(self) -> list:
		"""Return all billing model classes for Alembic autogenerate."""
		return _import_models()

	# ------------------------------------------------------------------
	# Hook overrides
	# ------------------------------------------------------------------

	def on_user_login(self, user) -> None:
		"""
		After login:
		  1. Verify the user has an active (or trialing) subscription.
		  2. Warn in the flash queue if the trial is expiring soon.

		Reads ``user.tenant_id`` — set by TenancyPlugin before this hook fires.
		Silently skips users without a tenant (platform admins).
		"""
		tenant_id: int | None = getattr(user, "tenant_id", None)
		if tenant_id is None:
			return

		try:
			from flask import flash
			from sqlalchemy import select
			from .models import Subscription, SubscriptionStatus

			session = self.appbuilder.get_session

			# Find any active/trialing subscription for this tenant
			sub = session.execute(
				select(Subscription).where(
					Subscription.tenant_id == tenant_id,
					Subscription.status.in_([
						SubscriptionStatus.ACTIVE.value,
						SubscriptionStatus.TRIALING.value,
					]),
				).order_by(Subscription.id.desc())
			).scalar_one_or_none()

			if sub is None:
				# No active subscription — past-due or canceled
				past_due = session.execute(
					select(Subscription).where(
						Subscription.tenant_id == tenant_id,
						Subscription.status == SubscriptionStatus.PAST_DUE.value,
					)
				).scalar_one_or_none()
				if past_due:
					flash(
						"Your subscription is past due. "
						"Please update your payment method to avoid service interruption.",
						"danger",
					)
				else:
					flash(
						"No active subscription found. "
						"Please subscribe to a plan to continue using the service.",
						"warning",
					)
				return

			# Trial expiry warning
			if sub.status == SubscriptionStatus.TRIALING.value and sub.trial_end:
				now = datetime.now(timezone.utc)
				days_left = (sub.trial_end - now).days
				if 0 <= days_left <= self._trial_warn_days:
					flash(
						f"Your trial expires in {days_left} day(s). "
						"Add a payment method to keep access after the trial ends.",
						"warning",
					)

		except Exception as exc:
			# Never block login due to billing check failure
			log.exception("BillingPlugin.on_user_login: error checking subscription: %s", exc)

	# ------------------------------------------------------------------
	# Config schema
	# ------------------------------------------------------------------

	def get_config_schema(self) -> dict:
		"""JSON Schema for the admin UI plugin settings form."""
		return {
			"$schema": "http://json-schema.org/draft-07/schema#",
			"title": "BillingPlugin configuration",
			"type": "object",
			"properties": {
				"PGAF_BILLING_STRIPE_SECRET_KEY": {
					"type": "string",
					"description": "Stripe secret key (sk_live_… or sk_test_…).",
					"pattern": "^sk_(live|test)_[A-Za-z0-9]+$",
				},
				"PGAF_BILLING_STRIPE_WEBHOOK_SECRET": {
					"type": "string",
					"description": "Stripe webhook signing secret (whsec_…).",
					"pattern": "^whsec_",
				},
				"PGAF_BILLING_CURRENCY": {
					"type": "string",
					"description": "ISO-4217 default billing currency.",
					"default": "USD",
					"minLength": 3,
					"maxLength": 3,
				},
				"PGAF_BILLING_TRIAL_DAYS": {
					"type": "integer",
					"description": "Default trial period in days when not set on a plan.",
					"default": 14,
					"minimum": 0,
					"maximum": 365,
				},
				"PGAF_BILLING_TRIAL_WARN_DAYS": {
					"type": "integer",
					"description": "Days before trial expiry at which to show login warning.",
					"default": 3,
					"minimum": 0,
					"maximum": 30,
				},
			},
			"additionalProperties": False,
		}


# ---------------------------------------------------------------------------
# Factory function
# ---------------------------------------------------------------------------

def create_plugin(
	appbuilder,
	config: dict[str, Any] | None = None,
) -> BillingPlugin:
	"""
	Instantiate and return a :class:`BillingPlugin`.

	Args:
		appbuilder: PgAppForge / AppBuilder instance.
		config: Optional plugin config dict.  Keys are the ``PGAF_BILLING_*``
		        names but passed directly here rather than read from
		        ``app.config``.  Values take precedence over app config.

	Returns:
		A :class:`BillingPlugin` ready for :meth:`~BillingPlugin.activate`.

	Example::

		plugin = create_plugin(appbuilder, config={
		    "PGAF_BILLING_CURRENCY": "EUR",
		    "PGAF_BILLING_TRIAL_DAYS": 30,
		})
		plugin.activate()
	"""
	return BillingPlugin(appbuilder, config=config or {})


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	# Plugin
	"BillingPlugin",
	"create_plugin",
	# Models (re-exported for convenience)
	"Plan",
	"Subscription",
	"Invoice",
	"InvoiceItem",
	"Payment",
	"UsageRecord",
	"DunningAttempt",
	"Coupon",
	# Engine
	"BillingEngine",
]

# Lazy re-exports — only resolved when accessed, keeping import-time overhead
# near zero for apps that don't use the billing plugin.
def __getattr__(name: str):
	_model_names = {
		"Plan", "Subscription", "Invoice", "InvoiceItem",
		"Payment", "UsageRecord", "DunningAttempt", "Coupon",
	}
	if name in _model_names:
		for model in _import_models():
			if model.__name__ == name:
				return model
		raise AttributeError(name)

	if name == "BillingEngine":
		return _import_engine()

	raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
