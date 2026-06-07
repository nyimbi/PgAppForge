"""
pgappforge/plugins/erp/platform/tenant_control/models.py

SQLAlchemy models for the Tenant Control plugin.

Table prefix: tct_
PostgreSQL ONLY — JSONB for feature flags.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy import (
	BigInteger,
	Boolean,
	Column,
	DateTime,
	Index,
	Integer,
	Numeric,
	String,
	UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from pgappforge.models.sqla import Model
from pgappforge.plugins.audit import AuditMixin


def _uuid4() -> str:
	return str(uuid.uuid4())


def _now() -> datetime:
	return datetime.now(timezone.utc)


PLAN_TIER = ("STARTER", "GROWTH", "ENTERPRISE")
TENANT_STATUS = ("ACTIVE", "SUSPENDED", "TRIAL", "CANCELLED")
USAGE_EVENT_TYPE = ("API_CALL", "STORAGE_MB", "ACTIVE_USER", "WORKFLOW_RUN", "REPORT_RUN")


class TenantProfile(AuditMixin, Model):
	"""Master record for a tenant in a multi-tenant SaaS deployment."""

	__tablename__ = "tct_tenant"

	id = Column(String(36), primary_key=True, default=_uuid4)

	# Canonical tenant identifier — matches the tenant_id used in all other tables
	tenant_id = Column(String(36), nullable=False, unique=True, index=True)

	name = Column(String(300), nullable=False)
	plan_tier = Column(String(20), nullable=False, default="STARTER")
	status = Column(String(20), nullable=False, default="TRIAL")

	# Per-tenant feature flag overrides: {"feature_name": true/false}
	feature_flags = Column(JSONB, nullable=False, default=dict)

	# Billing integration reference
	billing_hyperion_customer_id = Column(String(50), nullable=True)

	trial_ends_at = Column(DateTime(timezone=True), nullable=True)

	__table_args__ = (
		Index("ix_tct_tenant_plan_status", "plan_tier", "status"),
	)

	def __repr__(self) -> str:
		return f"<TenantProfile {self.name!r} [{self.plan_tier}/{self.status}]>"


class TenantUsageEvent(AuditMixin, Model):
	"""Records a metered usage event for a tenant (for billing and limit enforcement)."""

	__tablename__ = "tct_usage_event"

	id = Column(String(36), primary_key=True, default=_uuid4)
	tenant_id = Column(String(36), nullable=False, index=True)

	event_type = Column(String(30), nullable=False)  # API_CALL/STORAGE_MB/ACTIVE_USER/...
	quantity = Column(BigInteger, nullable=False, default=1)
	recorded_at = Column(DateTime(timezone=True), nullable=False, default=_now)

	__table_args__ = (
		Index("ix_tct_usage_tenant_type_time", "tenant_id", "event_type", "recorded_at"),
	)

	def __repr__(self) -> str:
		return f"<TenantUsageEvent {self.event_type} qty={self.quantity}>"


class TenantPlanLimit(AuditMixin, Model):
	"""Defines resource limits per plan tier (e.g. STARTER: API_CALL = 10000/month)."""

	__tablename__ = "tct_plan_limit"

	id = Column(String(36), primary_key=True, default=_uuid4)

	plan_tier = Column(String(20), nullable=False)
	resource = Column(String(50), nullable=False)   # API_CALL/STORAGE_MB/ACTIVE_USER/...
	limit_value = Column(BigInteger, nullable=False)  # -1 = unlimited

	__table_args__ = (
		UniqueConstraint("plan_tier", "resource", name="uq_tct_plan_limit_tier_resource"),
		Index("ix_tct_plan_limit_tier", "plan_tier"),
	)

	def __repr__(self) -> str:
		return f"<TenantPlanLimit {self.plan_tier}.{self.resource}={self.limit_value}>"
