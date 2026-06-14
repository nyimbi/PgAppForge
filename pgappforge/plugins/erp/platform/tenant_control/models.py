"""Tenant control plane models."""
from __future__ import annotations
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from pgappforge.models.sqla import Model


class TenantProfile(Model):
	__tablename__ = "platform_tenant_profile"
	__table_args__ = ({"extend_existing": True},)

	id = sa.Column(sa.String(36), primary_key=True, comment="Same as tenant_id everywhere")
	name = sa.Column(sa.String(200), nullable=False)
	plan_tier = sa.Column(sa.String(15), nullable=False, default="STARTER", comment="STARTER, GROWTH, ENTERPRISE")
	status = sa.Column(sa.String(15), nullable=False, default="TRIAL", comment="TRIAL, ACTIVE, SUSPENDED")
	feature_flags = sa.Column(JSONB, nullable=True)
	usage_stats = sa.Column(JSONB, nullable=True)
	billing_customer_id = sa.Column(sa.String(100), nullable=True, comment="Hyperion-X customer ID")
	created_at = sa.Column(sa.DateTime(timezone=True), server_default=sa.text("NOW()"))


class TenantUsageEvent(Model):
	__tablename__ = "platform_tenant_usage_event"
	__table_args__ = ({"extend_existing": True},)

	id = sa.Column(sa.String(36), primary_key=True)
	tenant_id = sa.Column(sa.String(36), nullable=False, index=True)
	event_type = sa.Column(sa.String(30), nullable=False, comment="API_CALL, STORAGE_MB, ACTIVE_USER")
	quantity = sa.Column(sa.Numeric(18, 4), nullable=False)
	recorded_at = sa.Column(sa.DateTime(timezone=True), server_default=sa.text("NOW()"))


class TenantPlanLimit(Model):
	__tablename__ = "platform_tenant_plan_limit"
	__table_args__ = ({"extend_existing": True},)

	id = sa.Column(sa.String(36), primary_key=True)
	plan_tier = sa.Column(sa.String(15), nullable=False, index=True)
	resource = sa.Column(sa.String(50), nullable=False, comment="api_calls_per_month, storage_gb, users")
	limit_value = sa.Column(sa.Numeric(18, 4), nullable=False)
