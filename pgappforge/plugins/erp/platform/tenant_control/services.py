"""Tenant control plane service."""
from __future__ import annotations
import uuid
from decimal import Decimal
from typing import Any

import sqlalchemy as sa

from pgappforge.plugins.erp.platform.tenant_control.models import TenantProfile, TenantUsageEvent, TenantPlanLimit

_DEFAULT_LIMITS = [
	("STARTER", "api_calls_per_month", 10_000),
	("STARTER", "storage_gb", 5),
	("STARTER", "users", 5),
	("GROWTH", "api_calls_per_month", 100_000),
	("GROWTH", "storage_gb", 50),
	("GROWTH", "users", 25),
	("ENTERPRISE", "api_calls_per_month", 10_000_000),
	("ENTERPRISE", "storage_gb", 1000),
	("ENTERPRISE", "users", 10_000),
]


def _uuid() -> str:
	return str(uuid.uuid4())


class TenantControlService:
	def seed_plan_limits(self, session: Any) -> None:
		for tier, resource, limit in _DEFAULT_LIMITS:
			existing = session.execute(
				sa.select(TenantPlanLimit).where(TenantPlanLimit.plan_tier == tier, TenantPlanLimit.resource == resource)
			).scalar_one_or_none()
			if not existing:
				session.add(TenantPlanLimit(id=_uuid(), plan_tier=tier, resource=resource, limit_value=limit))

	def provision_tenant(self, tenant_id: str, name: str, plan_tier: str = "STARTER", session: Any = None) -> TenantProfile:
		profile = TenantProfile(id=tenant_id, name=name, plan_tier=plan_tier, status="TRIAL")
		if session:
			session.add(profile)
		return profile

	def suspend_tenant(self, tenant_id: str, session: Any) -> None:
		session.execute(sa.update(TenantProfile).where(TenantProfile.id == tenant_id).values(status="SUSPENDED"))

	def record_usage(self, tenant_id: str, event_type: str, quantity: float, session: Any) -> None:
		session.add(TenantUsageEvent(id=_uuid(), tenant_id=tenant_id, event_type=event_type, quantity=quantity))

	def check_plan_limits(self, tenant_id: str, resource: str, session: Any) -> bool:
		profile = session.get(TenantProfile, tenant_id)
		if not profile or profile.status == "SUSPENDED":
			return False
		limit_row = session.execute(
			sa.select(TenantPlanLimit).where(TenantPlanLimit.plan_tier == profile.plan_tier, TenantPlanLimit.resource == resource)
		).scalar_one_or_none()
		if not limit_row:
			return True
		usage = session.execute(
			sa.select(sa.func.sum(TenantUsageEvent.quantity)).where(TenantUsageEvent.tenant_id == tenant_id, TenantUsageEvent.event_type == resource)
		).scalar() or 0
		return Decimal(str(usage)) < limit_row.limit_value


__all__ = ["TenantControlService"]
