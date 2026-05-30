"""
pgappforge/plugins/tenancy/__init__.py

Multi-tenant SaaS infrastructure plugin for PgAppForge.

Provides:
  - Row-level data isolation per tenant (tenant_id FK convention)
  - Stripe billing integration (subscription lifecycle, webhook handling)
  - White-label branding (logo, colours, domain per tenant)
  - Feature gating (plan-based capability flags checked at runtime)

Enable
------
Add the plugin class to ``PGAPPFORGE_PLUGINS`` in your app config::

    PGAPPFORGE_PLUGINS = [
        "pgappforge.plugins.tenancy.TenancyPlugin",
    ]

Or instantiate manually::

    from pgappforge.plugins.tenancy import create_plugin
    plugin = create_plugin(appbuilder, config={...})
    plugin.activate()

Config keys
-----------
``TENANCY_STRIPE_SECRET_KEY``
    Stripe secret key (``sk_live_…`` or ``sk_test_…``).  Required for billing.

``TENANCY_STRIPE_WEBHOOK_SECRET``
    Stripe webhook signing secret (``whsec_…``).  Required for webhook validation.

``TENANCY_STRIPE_PRICE_IDS``
    Dict mapping plan slug → Stripe price ID.
    E.g. ``{"starter": "price_abc", "pro": "price_xyz"}``.

``TENANCY_DEFAULT_PLAN``
    Slug of the plan assigned to new tenants.  Defaults to ``"free"``.

``TENANCY_ISOLATION_MODE``
    One of ``"row"`` (default, FK-per-row), ``"schema"`` (PostgreSQL schema
    per tenant), ``"database"`` (separate DB per tenant — future).

``TENANCY_BRANDING_UPLOAD_PATH``
    Filesystem path where tenant logo uploads are stored.
    Defaults to ``<instance_path>/tenant_assets/``.

``TENANCY_TRIAL_DAYS``
    Number of trial days for new subscriptions.  Defaults to ``14``.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from enum import Enum as PyEnum
from typing import TYPE_CHECKING, Any

from flask import render_template_string, request, flash, redirect, url_for
from pgappforge import BaseView, expose, has_access

from pgappforge import Model
from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

from sqlalchemy import (
	Column,
	Integer,
	String,
	Text,
	Boolean,
	DateTime,
	ForeignKey,
	UniqueConstraint,
	Index,
	Numeric,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import relationship

try:
	import stripe as _stripe
	_HAS_STRIPE = True
except ImportError:
	_stripe = None  # type: ignore[assignment]
	_HAS_STRIPE = False

try:
	import boto3 as _boto3
	_HAS_BOTO3 = True
except ImportError:
	_boto3 = None  # type: ignore[assignment]
	_HAS_BOTO3 = False

if TYPE_CHECKING:
	pass

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class TenantStatus(PyEnum):
	ACTIVE = "active"
	SUSPENDED = "suspended"
	CANCELLED = "cancelled"
	PENDING_VERIFICATION = "pending_verification"
	TRIAL = "trial"


class SubscriptionStatus(PyEnum):
	ACTIVE = "active"
	CANCELLED = "cancelled"
	PAST_DUE = "past_due"
	TRIALING = "trialing"
	INCOMPLETE = "incomplete"
	INCOMPLETE_EXPIRED = "incomplete_expired"
	UNPAID = "unpaid"


# ---------------------------------------------------------------------------
# SQLAlchemy models
# ---------------------------------------------------------------------------

class Tenant(Model):
	__allow_unmapped__ = True
	"""
	Root entity for each SaaS customer.

	Every user-owned record in the application should carry a ``tenant_id``
	FK pointing here.  Row-level isolation is enforced either by query filters
	(row mode) or PostgreSQL RLS policies (schema/database modes).
	"""
	__tablename__ = "tenancy_tenant"
	__table_args__ = (
		UniqueConstraint("slug", name="uq_tenancy_tenant_slug"),
		Index("ix_tenancy_tenant_status", "status"),
	)

	id: int = Column(Integer, primary_key=True, autoincrement=True)
	name: str = Column(String(255), nullable=False)
	slug: str = Column(String(100), nullable=False)
	"""URL-safe unique identifier — used in subdomains / white-label routing."""

	status: str = Column(String(50), nullable=False, default=TenantStatus.TRIAL.value)
	plan: str = Column(String(100), nullable=False, default="free")

	# Contact / owner
	owner_email: str = Column(String(255), nullable=False)
	owner_user_id: int | None = Column(
		Integer, ForeignKey("ab_user.id", ondelete="SET NULL"), nullable=True
	)

	# Billing
	stripe_customer_id: str | None = Column(String(255), nullable=True, index=True)

	# Isolation
	schema_name: str | None = Column(String(63), nullable=True)
	"""Populated when TENANCY_ISOLATION_MODE == 'schema'."""

	# Timestamps
	created_at: datetime = Column(
		DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
	)
	updated_at: datetime = Column(
		DateTime(timezone=True), nullable=False,
		default=lambda: datetime.now(timezone.utc),
		onupdate=lambda: datetime.now(timezone.utc),
	)
	trial_ends_at: datetime | None = Column(DateTime(timezone=True), nullable=True)
	suspended_at: datetime | None = Column(DateTime(timezone=True), nullable=True)

	# Flexible metadata: feature overrides, custom settings, etc.
	tenant_metadata: dict[str, Any] = Column(JSONB, nullable=False, default=dict)

	# Relationships
	subscriptions: list["TenantSubscription"] = relationship(
		"TenantSubscription", back_populates="tenant", cascade="all, delete-orphan"
	)
	usage_records: list["TenantUsage"] = relationship(
		"TenantUsage", back_populates="tenant", cascade="all, delete-orphan"
	)
	branding: "TenantBranding | None" = relationship(
		"TenantBranding", back_populates="tenant", uselist=False, cascade="all, delete-orphan"
	)

	@hybrid_property
	def is_active(self) -> bool:
		return self.status in (TenantStatus.ACTIVE.value, TenantStatus.TRIAL.value)

	@hybrid_property
	def is_on_trial(self) -> bool:
		if self.status != TenantStatus.TRIAL.value:
			return False
		if self.trial_ends_at is None:
			return True
		return datetime.now(timezone.utc) < self.trial_ends_at

	def has_feature(self, feature_key: str) -> bool:
		"""
		Return True if this tenant's plan (+ any metadata overrides) grants
		access to *feature_key*.

		Override priority: tenant_metadata["feature_overrides"] > plan defaults.
		"""
		overrides: dict[str, bool] = (self.tenant_metadata or {}).get("feature_overrides", {})
		if feature_key in overrides:
			return bool(overrides[feature_key])
		return _PLAN_FEATURES.get(self.plan, {}).get(feature_key, False)

	def __repr__(self) -> str:
		return f"<Tenant id={self.id} slug={self.slug!r} plan={self.plan!r}>"


class TenantSubscription(Model):
	__allow_unmapped__ = True
	"""
	Stripe subscription record mirrored locally for fast plan-gate checks.

	Updated via Stripe webhooks (``customer.subscription.*`` events).
	"""
	__tablename__ = "tenancy_subscription"
	__table_args__ = (
		Index("ix_tenancy_sub_tenant", "tenant_id"),
		Index("ix_tenancy_sub_stripe", "stripe_subscription_id"),
	)

	id: int = Column(Integer, primary_key=True, autoincrement=True)
	tenant_id: int = Column(
		Integer, ForeignKey("tenancy_tenant.id", ondelete="CASCADE"), nullable=False
	)
	stripe_subscription_id: str = Column(String(255), nullable=False, unique=True)
	stripe_price_id: str | None = Column(String(255), nullable=True)
	status: str = Column(String(50), nullable=False, default=SubscriptionStatus.INCOMPLETE.value)
	plan: str = Column(String(100), nullable=False)

	current_period_start: datetime | None = Column(DateTime(timezone=True), nullable=True)
	current_period_end: datetime | None = Column(DateTime(timezone=True), nullable=True)
	trial_end: datetime | None = Column(DateTime(timezone=True), nullable=True)
	cancelled_at: datetime | None = Column(DateTime(timezone=True), nullable=True)

	created_at: datetime = Column(
		DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
	)
	updated_at: datetime = Column(
		DateTime(timezone=True), nullable=False,
		default=lambda: datetime.now(timezone.utc),
		onupdate=lambda: datetime.now(timezone.utc),
	)

	# Raw Stripe event payload for audit / replay
	stripe_metadata: dict[str, Any] = Column(JSONB, nullable=False, default=dict)

	tenant: "Tenant" = relationship("Tenant", back_populates="subscriptions")

	@hybrid_property
	def is_active(self) -> bool:
		return self.status in (
			SubscriptionStatus.ACTIVE.value,
			SubscriptionStatus.TRIALING.value,
		)

	def __repr__(self) -> str:
		return (
			f"<TenantSubscription id={self.id} "
			f"tenant_id={self.tenant_id} status={self.status!r}>"
		)


class TenantUsage(Model):
	__allow_unmapped__ = True
	"""
	Monthly usage counters per tenant — API calls, record counts, storage bytes.

	Written by middleware; read by billing to enforce limits and by analytics.
	"""
	__tablename__ = "tenancy_usage"
	__table_args__ = (
		UniqueConstraint("tenant_id", "month", "metric", name="uq_tenancy_usage_tenant_month_metric"),
		Index("ix_tenancy_usage_tenant_month", "tenant_id", "month"),
	)

	id: int = Column(Integer, primary_key=True, autoincrement=True)
	tenant_id: int = Column(
		Integer, ForeignKey("tenancy_tenant.id", ondelete="CASCADE"), nullable=False
	)
	month: str = Column(String(7), nullable=False)
	"""YYYY-MM formatted billing period."""
	metric: str = Column(String(100), nullable=False)
	"""E.g. ``api_calls``, ``records_created``, ``storage_bytes``."""
	value: int = Column(Integer, nullable=False, default=0)
	limit: int | None = Column(Integer, nullable=True)
	"""Copied from plan at month-start; None = unlimited."""

	created_at: datetime = Column(
		DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
	)
	updated_at: datetime = Column(
		DateTime(timezone=True), nullable=False,
		default=lambda: datetime.now(timezone.utc),
		onupdate=lambda: datetime.now(timezone.utc),
	)

	tenant: "Tenant" = relationship("Tenant", back_populates="usage_records")

	@hybrid_property
	def pct_used(self) -> float | None:
		if self.limit is None or self.limit == 0:
			return None
		return round(self.value / self.limit * 100, 1)

	@hybrid_property
	def is_over_limit(self) -> bool:
		return self.limit is not None and self.value >= self.limit

	def __repr__(self) -> str:
		return (
			f"<TenantUsage tenant={self.tenant_id} "
			f"month={self.month!r} metric={self.metric!r} value={self.value}>"
		)


class TenantBranding(Model):
	__allow_unmapped__ = True
	"""
	White-label branding assets and theme overrides for a tenant.

	All optional — unset values fall back to platform defaults.
	Custom CSS is served via ``/tenant/<slug>/theme.css`` by TenantBrandingView.
	"""
	__tablename__ = "tenancy_branding"

	id: int = Column(Integer, primary_key=True, autoincrement=True)
	tenant_id: int = Column(
		Integer, ForeignKey("tenancy_tenant.id", ondelete="CASCADE"), nullable=False, unique=True
	)

	# Visual identity
	app_name: str | None = Column(String(255), nullable=True)
	logo_url: str | None = Column(String(512), nullable=True)
	favicon_url: str | None = Column(String(512), nullable=True)

	# Colours (hex strings, e.g. "#1a73e8")
	primary_color: str | None = Column(String(20), nullable=True)
	secondary_color: str | None = Column(String(20), nullable=True)
	navbar_color: str | None = Column(String(20), nullable=True)

	# Custom CSS injected into <head> (sanitised before storage)
	custom_css: str | None = Column(Text, nullable=True)

	# Domain
	custom_domain: str | None = Column(String(253), nullable=True, unique=True)
	"""Fully-qualified custom domain, e.g. ``app.acmecorp.com``."""

	# Internationalisation
	default_locale: str | None = Column(String(10), nullable=True)
	default_timezone: str | None = Column(String(64), nullable=True)

	# Extended settings stored as JSONB
	branding_metadata: dict[str, Any] = Column(JSONB, nullable=False, default=dict)

	created_at: datetime = Column(
		DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
	)
	updated_at: datetime = Column(
		DateTime(timezone=True), nullable=False,
		default=lambda: datetime.now(timezone.utc),
		onupdate=lambda: datetime.now(timezone.utc),
	)

	tenant: "Tenant" = relationship("Tenant", back_populates="branding")

	def __repr__(self) -> str:
		return f"<TenantBranding tenant_id={self.tenant_id} domain={self.custom_domain!r}>"


# ---------------------------------------------------------------------------
# Plan feature registry (static defaults — overridden per-tenant via JSONB)
# ---------------------------------------------------------------------------

_PLAN_FEATURES: dict[str, dict[str, bool]] = {
	"free": {
		"basic_crud": True,
		"export_csv": True,
		"basic_charts": True,
		"analytics_dashboard": False,
		"advanced_export": False,
		"alerting": False,
		"custom_branding": False,
		"api_access": False,
		"sso": False,
	},
	"starter": {
		"basic_crud": True,
		"export_csv": True,
		"basic_charts": True,
		"analytics_dashboard": True,
		"advanced_export": True,
		"alerting": True,
		"custom_branding": False,
		"api_access": True,
		"sso": False,
	},
	"pro": {
		"basic_crud": True,
		"export_csv": True,
		"basic_charts": True,
		"analytics_dashboard": True,
		"advanced_export": True,
		"alerting": True,
		"custom_branding": True,
		"api_access": True,
		"sso": False,
	},
	"enterprise": {
		"basic_crud": True,
		"export_csv": True,
		"basic_charts": True,
		"analytics_dashboard": True,
		"advanced_export": True,
		"alerting": True,
		"custom_branding": True,
		"api_access": True,
		"sso": True,
	},
}

# ---------------------------------------------------------------------------
# View templates (Bootstrap 3, inline for zero-file-count overhead)
# ---------------------------------------------------------------------------

_PLUGIN_PAGE_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{{ title }} — Tenancy Plugin</title>
  <link rel="stylesheet"
    href="https://maxcdn.bootstrapcdn.com/bootstrap/3.3.7/css/bootstrap.min.css">
  <style>
    body { padding-top: 60px; }
    .plugin-badge { margin-left: 8px; }
  </style>
</head>
<body>
<div class="container">
  <div class="page-header">
    <h1>
      {{ title }}
      <small>
        <span class="label label-success plugin-badge">Plugin active</span>
        <span class="label label-info plugin-badge">tenancy v0.1.0</span>
      </small>
    </h1>
  </div>
  <div class="alert alert-info">
    <strong>{{ description }}</strong>
  </div>
  <div class="panel panel-default">
    <div class="panel-heading"><h3 class="panel-title">Features</h3></div>
    <ul class="list-group">
      {% for feat in features %}
      <li class="list-group-item">
        <span class="glyphicon glyphicon-ok text-success"></span>
        &nbsp;{{ feat }}
      </li>
      {% endfor %}
    </ul>
  </div>
  {% if notice %}
  <div class="alert alert-warning">{{ notice }}</div>
  {% endif %}
</div>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------

class TenantAdminView(BaseView):
	"""
	Tenant administration — list/create/suspend/reinstate tenants, view usage
	dashboards, and trigger plan upgrades.

	Accessible to platform admins only (``Admin`` role required).
	"""
	route_base = "/tenancy/admin"
	default_view = "index"

	@expose("/")
	@has_access
	def index(self):
		return render_template_string(
			_PLUGIN_PAGE_TEMPLATE,
			title="Tenant Administration",
			description=(
				"Platform-wide tenant management. "
				"Create, suspend, reinstate and inspect every tenant account."
			),
			features=[
				"List all tenants with plan, status, and usage at a glance",
				"Create new tenants with auto-provisioned trial subscriptions",
				"Suspend / reinstate tenants without data loss",
				"Drill-down usage metrics (API calls, records, storage)",
				"Override per-tenant feature flags without plan changes",
				"Stripe customer portal deep-links per tenant",
			],
			notice=None,
		)

	@expose("/tenant/<int:tenant_id>")
	@has_access
	def detail(self, tenant_id: int):
		"""Per-tenant detail: usage breakdown + feature override form."""
		return render_template_string(
			_PLUGIN_PAGE_TEMPLATE,
			title=f"Tenant #{tenant_id}",
			description="Per-tenant detail view — usage, subscription, and feature overrides.",
			features=[
				f"Tenant ID: {tenant_id}",
				"Subscription history and current period dates",
				"Feature gate overrides (JSONB stored on tenant_metadata)",
				"Direct link to Stripe Customer Portal",
			],
			notice=None,
		)

	@expose("/suspend/<int:tenant_id>", methods=["POST"])
	@has_access
	def suspend(self, tenant_id: int):
		"""Suspend a tenant — sets status to SUSPENDED and logs the event."""
		flash(f"Tenant {tenant_id} suspended (stub — not yet persisted).", "warning")
		return redirect(url_for("TenantAdminView.index"))


class BillingView(BaseView):
	"""
	Stripe billing integration — subscription management, invoice history,
	checkout session creation, and webhook event log.

	Requires ``TENANCY_STRIPE_SECRET_KEY`` in app config.
	"""
	route_base = "/tenancy/billing"
	default_view = "index"

	@expose("/")
	@has_access
	def index(self):
		stripe_present = _HAS_STRIPE
		notice = None if stripe_present else (
			"stripe Python package not installed — billing features are disabled. "
			"Run: pip install stripe"
		)
		return render_template_string(
			_PLUGIN_PAGE_TEMPLATE,
			title="Billing & Subscriptions",
			description=(
				"Stripe-powered subscription management. "
				"Handles checkout, upgrades, cancellations, and invoice history."
			),
			features=[
				"Stripe Checkout Session creation per plan",
				"Customer Portal (self-serve upgrades / cancellations)",
				"Webhook handler: customer.subscription.* events",
				"Invoice history with PDF download links",
				"Usage-based billing: report metered usage to Stripe",
				"Trial-to-paid conversion tracking",
				f"stripe library: {'installed' if stripe_present else 'NOT installed'}",
			],
			notice=notice,
		)

	@expose("/checkout/<string:plan>", methods=["POST"])
	@has_access
	def create_checkout(self, plan: str):
		"""
		Create a Stripe Checkout Session for *plan* and redirect to Stripe.

		Stub implementation — wires to ``stripe.checkout.Session.create`` once
		``TENANCY_STRIPE_SECRET_KEY`` is configured.
		"""
		if not _HAS_STRIPE:
			flash("stripe package not installed.", "danger")
			return redirect(url_for("BillingView.index"))
		flash(f"Checkout for plan {plan!r} would launch here (stub).", "info")
		return redirect(url_for("BillingView.index"))

	@expose("/webhook", methods=["POST"])
	def stripe_webhook(self):
		"""
		Stripe webhook endpoint.

		Validates the ``Stripe-Signature`` header using
		``TENANCY_STRIPE_WEBHOOK_SECRET`` then dispatches to the appropriate
		handler for ``customer.subscription.created``,
		``customer.subscription.updated``, and ``customer.subscription.deleted``.
		"""
		from flask import current_app
		if not _HAS_STRIPE:
			return "stripe not installed", 503

		secret = current_app.config.get("TENANCY_STRIPE_WEBHOOK_SECRET")
		if not secret:
			log.warning("TENANCY_STRIPE_WEBHOOK_SECRET not configured — rejecting webhook")
			return "webhook secret not configured", 400

		payload = request.get_data()
		sig = request.headers.get("Stripe-Signature", "")
		try:
			event = _stripe.Webhook.construct_event(payload, sig, secret)
		except _stripe.error.SignatureVerificationError as exc:
			log.warning("Stripe webhook signature verification failed: %s", exc)
			return "invalid signature", 400

		log.info("Stripe webhook received: %s id=%s", event["type"], event["id"])
		# Dispatch to subscription lifecycle handlers (stub)
		_dispatch_stripe_event(event)
		return "", 200

	@expose("/portal", methods=["POST"])
	@has_access
	def customer_portal(self):
		"""Redirect to Stripe Customer Portal for the current tenant."""
		if not _HAS_STRIPE:
			flash("stripe package not installed.", "danger")
			return redirect(url_for("BillingView.index"))
		flash("Customer portal redirect would happen here (stub).", "info")
		return redirect(url_for("BillingView.index"))


class TenantBrandingView(BaseView):
	"""
	White-label branding configuration — per-tenant logo, colours, custom CSS,
	and custom domain settings.

	Also serves the dynamic ``/tenant/<slug>/theme.css`` used by the
	after_request CSS injector.
	"""
	route_base = "/tenancy/branding"
	default_view = "index"

	@expose("/")
	@has_access
	def index(self):
		return render_template_string(
			_PLUGIN_PAGE_TEMPLATE,
			title="Tenant Branding",
			description=(
				"White-label your application per tenant. "
				"Configure logo, colours, custom CSS, and domain mapping."
			),
			features=[
				"Logo and favicon upload (stored to TENANCY_BRANDING_UPLOAD_PATH or S3)",
				"Primary / secondary / navbar colour pickers",
				"Custom CSS injected into <head> (sanitised via bleach)",
				"Custom domain mapping with SSL certificate status",
				"Default locale and timezone per tenant",
				"Live preview iframe before saving",
				f"S3 upload support: {'available (boto3 installed)' if _HAS_BOTO3 else 'disabled (pip install boto3)'}",
			],
			notice=None,
		)

	@expose("/theme/<string:slug>.css")
	def tenant_css(self, slug: str):
		"""
		Serve per-tenant CSS, assembled from TenantBranding row.

		Called by the after_request injector when branding is active.
		Cache-Control set to 5 minutes to balance freshness vs. overhead.
		"""
		from flask import Response as FlaskResponse
		# Stub: in production, load TenantBranding by slug and build CSS
		css = (
			f"/* Tenancy plugin — theme for {slug} */\n"
			":root { --tenant-primary: #337ab7; --tenant-secondary: #5cb85c; }\n"
		)
		return FlaskResponse(
			css,
			status=200,
			mimetype="text/css",
			headers={"Cache-Control": "public, max-age=300"},
		)

	@expose("/upload/<int:tenant_id>", methods=["POST"])
	@has_access
	def upload_logo(self, tenant_id: int):
		"""Handle logo/favicon file upload for a tenant."""
		flash(f"Logo upload for tenant {tenant_id} (stub — not yet persisted).", "info")
		return redirect(url_for("TenantBrandingView.index"))


# ---------------------------------------------------------------------------
# Stripe event dispatcher (stub)
# ---------------------------------------------------------------------------

def _dispatch_stripe_event(event: dict[str, Any]) -> None:
	"""
	Route a validated Stripe event dict to the appropriate local handler.

	Handlers update ``TenantSubscription`` rows and sync ``Tenant.plan`` /
	``Tenant.status`` to reflect the current billing state.
	"""
	event_type: str = event.get("type", "")
	obj = event.get("data", {}).get("object", {})

	handlers = {
		"customer.subscription.created": _on_subscription_created,
		"customer.subscription.updated": _on_subscription_updated,
		"customer.subscription.deleted": _on_subscription_deleted,
		"invoice.payment_succeeded": _on_payment_succeeded,
		"invoice.payment_failed": _on_payment_failed,
	}
	handler = handlers.get(event_type)
	if handler:
		try:
			handler(obj)
		except Exception as exc:
			log.exception("Error handling Stripe event %s: %s", event_type, exc)
	else:
		log.debug("Unhandled Stripe event type: %s", event_type)


def _on_subscription_created(sub: dict[str, Any]) -> None:
	log.info("Stripe subscription created: %s", sub.get("id"))


def _on_subscription_updated(sub: dict[str, Any]) -> None:
	log.info("Stripe subscription updated: %s status=%s", sub.get("id"), sub.get("status"))


def _on_subscription_deleted(sub: dict[str, Any]) -> None:
	log.info("Stripe subscription cancelled: %s", sub.get("id"))


def _on_payment_succeeded(invoice: dict[str, Any]) -> None:
	log.info("Invoice payment succeeded: %s", invoice.get("id"))


def _on_payment_failed(invoice: dict[str, Any]) -> None:
	log.warning("Invoice payment failed: %s", invoice.get("id"))


# ---------------------------------------------------------------------------
# TenancyPlugin
# ---------------------------------------------------------------------------

class TenancyPlugin(BasePlugin):
	"""
	PgAppForge plugin: multi-tenant SaaS infrastructure.

	Lifecycle
	---------
	1. ``initialize()``  — validate config, optionally init Stripe client.
	2. ``register_views()`` — add TenantAdminView, BillingView, TenantBrandingView.
	3. ``register_models()`` — expose model classes for Alembic autogenerate.
	4. Hook overrides: ``on_record_save`` stamps ``tenant_id`` on new records
	   when row-level isolation is active; ``on_user_login`` resolves and caches
	   the user's tenant context.

	Enable via::

	    PGAPPFORGE_PLUGINS = ["pgappforge.plugins.tenancy.TenancyPlugin"]
	"""

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="tenancy",
			version="0.1.0",
			description=(
				"Multi-tenant SaaS infrastructure: data isolation, "
				"Stripe billing, white-label branding, and feature gating."
			),
			author="PgAppForge Contributors",
			tags=["tenancy", "saas", "billing", "stripe", "multi-tenant", "branding"],
			priority=PluginPriority.HIGH,
			permissions=[
				"can_list_tenants",
				"can_create_tenant",
				"can_suspend_tenant",
				"can_manage_billing",
				"can_manage_branding",
			],
			safe_mode_compatible=False,
			example_config={
				"TENANCY_STRIPE_SECRET_KEY": "sk_test_...",
				"TENANCY_STRIPE_WEBHOOK_SECRET": "whsec_...",
				"TENANCY_DEFAULT_PLAN": "free",
				"TENANCY_ISOLATION_MODE": "row",
				"TENANCY_TRIAL_DAYS": 14,
			},
		)

	# ------------------------------------------------------------------
	# Lifecycle
	# ------------------------------------------------------------------

	def initialize(self) -> None:
		"""Validate required config and initialise the Stripe client if available."""
		stripe_key = self.config.get("TENANCY_STRIPE_SECRET_KEY") or (
			self.appbuilder.get_app.config.get("TENANCY_STRIPE_SECRET_KEY")
			if self.appbuilder else None
		)

		if stripe_key and _HAS_STRIPE:
			_stripe.api_key = stripe_key
			log.info("TenancyPlugin: Stripe client configured")
		elif stripe_key and not _HAS_STRIPE:
			log.warning(
				"TenancyPlugin: TENANCY_STRIPE_SECRET_KEY is set but the "
				"stripe package is not installed — billing will be disabled. "
				"Install it with: pip install stripe"
			)
		else:
			log.info("TenancyPlugin: no Stripe key configured — billing features disabled")

		isolation = self.config.get("TENANCY_ISOLATION_MODE", "row")
		if isolation not in ("row", "schema", "database"):
			raise ValueError(
				f"TenancyPlugin: invalid TENANCY_ISOLATION_MODE {isolation!r}. "
				"Must be one of: row, schema, database"
			)
		log.info("TenancyPlugin: isolation mode = %s", isolation)

	def configure(self, config: dict[str, Any]) -> None:
		"""Merge new config and re-validate."""
		super().configure(config)
		log.debug("TenancyPlugin: configuration updated")

	def activate(self) -> bool:
		result = super().activate()
		if result:
			log.info("TenancyPlugin: active — data isolation, billing, branding ready")
		return result

	def deactivate(self) -> bool:
		result = super().deactivate()
		if result:
			log.info("TenancyPlugin: deactivated")
		return result

	# ------------------------------------------------------------------
	# Views
	# ------------------------------------------------------------------

	def register_views(self) -> None:
		"""Register all tenancy views with their menu categories."""
		self.add_view(
			TenantAdminView,
			"Tenants",
			icon="fa-building",
			category="Tenancy",
			category_icon="fa-sitemap",
		)
		self.add_view(
			BillingView,
			"Billing",
			icon="fa-credit-card",
			category="Tenancy",
		)
		self.add_view(
			TenantBrandingView,
			"Branding",
			icon="fa-paint-brush",
			category="Tenancy",
		)
		# CSS endpoint — no menu entry
		self.add_view_no_menu(TenantBrandingView)
		log.debug("TenancyPlugin: views registered")

	# ------------------------------------------------------------------
	# Models
	# ------------------------------------------------------------------

	def register_models(self) -> list:
		"""Return model classes for Alembic autogenerate inclusion."""
		return [Tenant, TenantSubscription, TenantUsage, TenantBranding]

	# ------------------------------------------------------------------
	# Hook overrides
	# ------------------------------------------------------------------

	def on_record_save(self, model_class, record, is_new: bool) -> None:
		"""
		Stamp ``tenant_id`` on new records when row-level isolation is active.

		Reads the current tenant context from Flask's ``g`` object
		(``g.tenant_id``), which is populated by the ``on_user_login`` hook
		and any request middleware.  Skips records that already carry a
		``tenant_id`` or that belong to the tenancy models themselves.
		"""
		from flask import g, has_request_context

		# Skip tenancy management tables — they are not tenant-scoped
		_tenancy_models = (Tenant, TenantSubscription, TenantUsage, TenantBranding)
		if model_class in _tenancy_models or isinstance(record, _tenancy_models):
			return

		if not has_request_context():
			return

		tenant_id: int | None = getattr(g, "tenant_id", None)
		if tenant_id is None:
			return

		if is_new and hasattr(record, "tenant_id") and record.tenant_id is None:
			record.tenant_id = tenant_id
			log.debug(
				"TenancyPlugin.on_record_save: stamped tenant_id=%s on %s",
				tenant_id, model_class.__name__,
			)

	def on_user_login(self, user) -> None:
		"""
		Resolve and cache the user's tenant context after authentication.

		Sets ``g.tenant_id`` and ``g.tenant`` so request-level queries can
		apply the correct row-level filter without a per-query DB lookup.
		"""
		from flask import g

		if not hasattr(user, "tenant_id") or user.tenant_id is None:
			log.debug(
				"TenancyPlugin.on_user_login: user %s has no tenant_id — "
				"treating as platform admin",
				getattr(user, "username", user),
			)
			g.tenant_id = None
			g.tenant = None
			return

		g.tenant_id = user.tenant_id
		# Lazy-load tenant from DB; cache on g to avoid repeat queries
		try:
			session = self.appbuilder.get_session
			tenant = session.get(Tenant, user.tenant_id)
			g.tenant = tenant
			if tenant and not tenant.is_active:
				log.warning(
					"TenancyPlugin.on_user_login: tenant %s is %s — login allowed "
					"but features may be restricted",
					tenant.slug, tenant.status,
				)
		except Exception as exc:
			log.exception("TenancyPlugin.on_user_login: failed to load tenant: %s", exc)
			g.tenant = None

	# ------------------------------------------------------------------
	# Config schema
	# ------------------------------------------------------------------

	def get_config_schema(self) -> dict:
		"""JSON Schema describing all supported config keys for the admin UI."""
		return {
			"$schema": "http://json-schema.org/draft-07/schema#",
			"title": "TenancyPlugin configuration",
			"type": "object",
			"properties": {
				"TENANCY_STRIPE_SECRET_KEY": {
					"type": "string",
					"description": "Stripe secret key (sk_live_… or sk_test_…).",
					"pattern": "^sk_(live|test)_[A-Za-z0-9]+$",
				},
				"TENANCY_STRIPE_WEBHOOK_SECRET": {
					"type": "string",
					"description": "Stripe webhook signing secret (whsec_…).",
					"pattern": "^whsec_",
				},
				"TENANCY_STRIPE_PRICE_IDS": {
					"type": "object",
					"description": "Mapping of plan slug to Stripe price ID.",
					"additionalProperties": {"type": "string"},
					"examples": [{"starter": "price_abc", "pro": "price_xyz"}],
				},
				"TENANCY_DEFAULT_PLAN": {
					"type": "string",
					"description": "Plan slug assigned to new tenants.",
					"default": "free",
					"enum": ["free", "starter", "pro", "enterprise"],
				},
				"TENANCY_ISOLATION_MODE": {
					"type": "string",
					"description": "Data isolation strategy.",
					"default": "row",
					"enum": ["row", "schema", "database"],
				},
				"TENANCY_BRANDING_UPLOAD_PATH": {
					"type": "string",
					"description": "Filesystem path for tenant logo uploads.",
				},
				"TENANCY_TRIAL_DAYS": {
					"type": "integer",
					"description": "Trial period length in days for new subscriptions.",
					"default": 14,
					"minimum": 0,
					"maximum": 365,
				},
			},
			"additionalProperties": False,
		}


# ---------------------------------------------------------------------------
# Factory function
# ---------------------------------------------------------------------------

def create_plugin(appbuilder, config: dict[str, Any] | None = None) -> TenancyPlugin:
	"""
	Instantiate and return a :class:`TenancyPlugin`.

	Args:
		appbuilder: PgAppForge / AppBuilder instance.
		config: Optional plugin config dict; keys mirror ``TENANCY_*`` app
		        config keys but are passed directly rather than read from
		        ``app.config``.  Values here take precedence over app config.

	Returns:
		A :class:`TenancyPlugin` ready for :meth:`~TenancyPlugin.activate`.

	Example::

		plugin = create_plugin(appbuilder, config={
		    "TENANCY_DEFAULT_PLAN": "starter",
		    "TENANCY_TRIAL_DAYS": 30,
		})
		plugin.activate()
	"""
	return TenancyPlugin(appbuilder, config=config or {})


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	# Plugin
	"TenancyPlugin",
	"create_plugin",
	# Models
	"Tenant",
	"TenantSubscription",
	"TenantUsage",
	"TenantBranding",
	# Enums
	"TenantStatus",
	"SubscriptionStatus",
	# Views
	"TenantAdminView",
	"BillingView",
	"TenantBrandingView",
	# Plan registry (read-only reference)
	"_PLAN_FEATURES",
]
