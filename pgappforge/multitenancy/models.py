"""
pgappforge/multitenancy/models.py

SQLAlchemy Tenant model — the registry of every organisation using
PgAppForge as a multi-tenant service.

Design rules
------------
- PK: UUID7 string (time-ordered, sortable, no collision risk).
- All monetary amounts in INTEGER cents (currency_code drives display).
- ``features`` JSONB stores plan-gated capability flags; checked at runtime
  via :meth:`Tenant.has_feature`.
- ``status`` state machine: TRIAL → ACTIVE → SUSPENDED → CANCELLED.
- ``pgaf_tenant`` is intentionally excluded from RLS (it is the source of
  truth for all tenant IDs — you cannot RLS-restrict the RLS registry).

Usage
-----
::

    # In your app factory, after db.create_all() or Alembic migrations:
    from pgappforge.multitenancy.models import Tenant

    tenant = Tenant(
        name="Acme SACCO",
        slug="acme-sacco",
        plan="STARTER",
        admin_email="admin@acmesacco.co.ke",
        country_code="KE",
        currency_code="KES",
    )
    db.session.add(tenant)
    db.session.commit()
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

log = logging.getLogger(__name__)


def _uuid() -> str:
	try:
		from uuid6 import uuid7
		return str(uuid7())
	except ImportError:
		import uuid
		return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Import base model + AuditMixin with graceful fallback for tests
# ---------------------------------------------------------------------------

try:
	from pgappforge.models.sqla import Model
	from pgappforge.plugins.audit import AuditMixin
	_BASES = (AuditMixin, Model)
except ImportError:
	# Fallback: plain DeclarativeBase for unit tests without full FAB install
	from sqlalchemy.orm import DeclarativeBase

	class _FallbackBase(DeclarativeBase):
		pass

	class _NullAudit:
		pass

	Model = _FallbackBase	# type: ignore[misc,assignment]
	AuditMixin = _NullAudit	# type: ignore[assignment,misc]
	_BASES = (Model,)


# ---------------------------------------------------------------------------
# Plan constants
# ---------------------------------------------------------------------------

PLAN_FREE		= "FREE"
PLAN_STARTER	= "STARTER"
PLAN_GROWTH		= "GROWTH"
PLAN_ENTERPRISE	= "ENTERPRISE"

VALID_PLANS = frozenset([PLAN_FREE, PLAN_STARTER, PLAN_GROWTH, PLAN_ENTERPRISE])

STATUS_TRIAL		= "TRIAL"
STATUS_ACTIVE		= "ACTIVE"
STATUS_SUSPENDED	= "SUSPENDED"
STATUS_CANCELLED	= "CANCELLED"

VALID_STATUSES = frozenset([STATUS_TRIAL, STATUS_ACTIVE, STATUS_SUSPENDED, STATUS_CANCELLED])

# Default feature flags by plan
_PLAN_DEFAULT_FEATURES: dict[str, dict[str, bool]] = {
	PLAN_FREE:		{"citizen_dev": False, "api_access": False, "rls": True, "analytics": False},
	PLAN_STARTER:	{"citizen_dev": True,  "api_access": True,  "rls": True, "analytics": False},
	PLAN_GROWTH:	{"citizen_dev": True,  "api_access": True,  "rls": True, "analytics": True},
	PLAN_ENTERPRISE:{"citizen_dev": True,  "api_access": True,  "rls": True, "analytics": True,
					 "white_label": True,  "sla_99_9": True},
}


# ---------------------------------------------------------------------------
# Tenant model
# ---------------------------------------------------------------------------

class Tenant(*_BASES):	# type: ignore[misc]
	"""SaaS tenant — one row per organisation subscribed to PgAppForge."""

	__tablename__ = "pgaf_tenant"
	__table_args__ = ({"extend_existing": True},)

	# Primary key
	id = sa.Column(sa.String(36), primary_key=True, default=_uuid)

	# Identity
	name = sa.Column(sa.String(200), nullable=False)
	slug = sa.Column(sa.String(100), nullable=False, unique=True, index=True)

	# Subscription
	plan	= sa.Column(sa.String(20), nullable=False, default=PLAN_FREE)
	status	= sa.Column(sa.String(15), nullable=False, default=STATUS_TRIAL)

	# Contact
	admin_email		= sa.Column(sa.String(255), nullable=False)
	country_code	= sa.Column(sa.String(2), nullable=True)	# ISO 3166-1 alpha-2
	currency_code	= sa.Column(sa.String(3), nullable=False, default="USD")

	# Feature flags (overrides on top of plan defaults)
	features = sa.Column(
		JSONB, nullable=False, default=dict, server_default=sa.text("'{}'::jsonb")
	)

	# Lifecycle timestamps
	trial_ends_at	= sa.Column(sa.DateTime(timezone=True), nullable=True)
	created_at		= sa.Column(
		sa.DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	updated_at		= sa.Column(
		sa.DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		onupdate=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	# Billing reference (Stripe customer ID etc.)
	billing_ref = sa.Column(sa.String(100), nullable=True, index=True)

	# White-label branding (stored as JSONB for flexibility)
	branding = sa.Column(
		JSONB, nullable=False, default=dict, server_default=sa.text("'{}'::jsonb")
	)

	# ---------------------------------------------------------------------------
	# Class methods
	# ---------------------------------------------------------------------------

	@classmethod
	def create(
		cls,
		name: str,
		slug: str,
		admin_email: str,
		plan: str = PLAN_FREE,
		trial_days: int = 14,
		country_code: str | None = None,
		currency_code: str = "USD",
	) -> "Tenant":
		"""Factory method with sensible defaults.

		Automatically sets ``trial_ends_at`` for TRIAL status and seeds
		``features`` from plan defaults.
		"""
		if plan not in VALID_PLANS:
			raise ValueError(f"Invalid plan {plan!r}. Valid: {sorted(VALID_PLANS)}")

		now = datetime.now(timezone.utc)
		features = dict(_PLAN_DEFAULT_FEATURES.get(plan, {}))

		return cls(
			name=name,
			slug=slug,
			admin_email=admin_email,
			plan=plan,
			status=STATUS_TRIAL,
			trial_ends_at=now + timedelta(days=trial_days),
			country_code=country_code,
			currency_code=currency_code,
			features=features,
		)

	# ---------------------------------------------------------------------------
	# Instance helpers
	# ---------------------------------------------------------------------------

	def has_feature(self, flag: str) -> bool:
		"""Check whether a feature flag is enabled for this tenant.

		Merges plan defaults with tenant-specific overrides.
		``features`` JSONB takes precedence over plan defaults.
		"""
		plan_defaults = _PLAN_DEFAULT_FEATURES.get(self.plan, {})
		return bool(
			self.features.get(flag, plan_defaults.get(flag, False))
		)

	def enable_feature(self, flag: str) -> None:
		"""Enable a feature flag (creates a tenant-level override)."""
		self.features = {**self.features, flag: True}

	def disable_feature(self, flag: str) -> None:
		"""Disable a feature flag (tenant-level override)."""
		self.features = {**self.features, flag: False}

	@property
	def is_active(self) -> bool:
		return self.status == STATUS_ACTIVE

	@property
	def is_trial(self) -> bool:
		return self.status == STATUS_TRIAL

	@property
	def trial_expired(self) -> bool:
		if self.trial_ends_at is None:
			return False
		return datetime.now(timezone.utc) > self.trial_ends_at

	def activate(self) -> None:
		"""Transition to ACTIVE (e.g. after payment confirmed)."""
		self.status = STATUS_ACTIVE
		self.updated_at = datetime.now(timezone.utc)

	def suspend(self) -> None:
		"""Transition to SUSPENDED (e.g. payment failure)."""
		self.status = STATUS_SUSPENDED
		self.updated_at = datetime.now(timezone.utc)

	def upgrade_plan(self, new_plan: str) -> None:
		"""Change plan and refresh feature flag defaults."""
		if new_plan not in VALID_PLANS:
			raise ValueError(f"Invalid plan {new_plan!r}")
		self.plan = new_plan
		# Merge in new defaults without overwriting explicit overrides
		defaults = _PLAN_DEFAULT_FEATURES.get(new_plan, {})
		merged = {**defaults, **self.features}
		self.features = merged
		self.updated_at = datetime.now(timezone.utc)

	def __repr__(self) -> str:
		return f"<Tenant {self.slug!r} plan={self.plan} status={self.status}>"


__all__ = [
	"Tenant",
	"PLAN_FREE", "PLAN_STARTER", "PLAN_GROWTH", "PLAN_ENTERPRISE",
	"VALID_PLANS",
	"STATUS_TRIAL", "STATUS_ACTIVE", "STATUS_SUSPENDED", "STATUS_CANCELLED",
	"VALID_STATUSES",
]
