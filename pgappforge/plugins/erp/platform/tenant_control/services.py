"""Tenant control plane service."""
from __future__ import annotations
import uuid
from decimal import Decimal
from datetime import datetime, timezone
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
_VALID_PLAN_TIERS = frozenset(tier for tier, _, _ in _DEFAULT_LIMITS)


def _uuid() -> str:
	return str(uuid.uuid4())


def _month_start(now: datetime | None = None) -> datetime:
	value = now or datetime.now(timezone.utc)
	if value.tzinfo is None:
		value = value.replace(tzinfo=timezone.utc)
	return value.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


class TenantControlService:
	def seed_plan_limits(self, session: Any) -> None:
		for tier, resource, limit in _DEFAULT_LIMITS:
			existing = session.execute(
				sa.select(TenantPlanLimit).where(TenantPlanLimit.plan_tier == tier, TenantPlanLimit.resource == resource)
			).scalar_one_or_none()
			if not existing:
				session.add(TenantPlanLimit(id=_uuid(), plan_tier=tier, resource=resource, limit_value=limit))

	def provision_tenant(self, tenant_id: str, name: str, plan_tier: str = "STARTER", session: Any = None) -> TenantProfile:
		self._validate_plan_tier(plan_tier)
		profile = TenantProfile(id=tenant_id, name=name, plan_tier=plan_tier, status="TRIAL")
		if session:
			session.add(profile)
		return profile

	def activate_tenant(self, tenant_id: str, session: Any) -> None:
		session.execute(sa.update(TenantProfile).where(TenantProfile.id == tenant_id).values(status="ACTIVE"))

	def suspend_tenant(self, tenant_id: str, session: Any) -> None:
		session.execute(sa.update(TenantProfile).where(TenantProfile.id == tenant_id).values(status="SUSPENDED"))

	def record_usage(self, tenant_id: str, event_type: str, quantity: float, session: Any) -> None:
		self._validate_resource(event_type, session=session, tenant_id=tenant_id)
		amount = Decimal(str(quantity))
		if amount < 0:
			raise ValueError("usage quantity cannot be negative")
		session.add(TenantUsageEvent(id=_uuid(), tenant_id=tenant_id, event_type=event_type, quantity=quantity))

	def check_plan_limits(self, tenant_id: str, resource: str, session: Any) -> bool:
		profile = session.get(TenantProfile, tenant_id)
		if not profile or profile.status == "SUSPENDED":
			return False
		limit_row = self._get_plan_limit(resource, session=session, tenant_id=tenant_id, profile=profile)
		usage = session.execute(
			sa.select(sa.func.sum(TenantUsageEvent.quantity)).where(
				TenantUsageEvent.tenant_id == tenant_id,
				TenantUsageEvent.event_type == resource,
				TenantUsageEvent.recorded_at >= _month_start(),
			)
		).scalar() or 0
		return Decimal(str(usage)) < limit_row.limit_value

	def enforce_plan_limit(self, tenant_id: str, resource: str, session: Any) -> None:
		if not self.check_plan_limits(tenant_id, resource, session):
			raise ValueError(f"Tenant {tenant_id!r} exceeded plan limit for {resource!r}")

	def get_usage_summary(self, tenant_id: str, session: Any, *, current_month_only: bool = True) -> dict[str, Any]:
		profile = session.get(TenantProfile, tenant_id)
		if profile is None:
			raise ValueError(f"Tenant {tenant_id!r} not found")
		q = sa.select(
			TenantUsageEvent.event_type,
			sa.func.sum(TenantUsageEvent.quantity).label("quantity"),
		).where(TenantUsageEvent.tenant_id == tenant_id)
		if current_month_only:
			q = q.where(TenantUsageEvent.recorded_at >= _month_start())
		q = q.group_by(TenantUsageEvent.event_type)
		usage = {row.event_type: Decimal(str(row.quantity or 0)) for row in session.execute(q).all()}
		limits = session.execute(
			sa.select(TenantPlanLimit).where(TenantPlanLimit.plan_tier == profile.plan_tier)
		).scalars().all()
		return {
			"tenant_id": tenant_id,
			"status": profile.status,
			"plan_tier": profile.plan_tier,
			"usage": usage,
			"limits": {row.resource: row.limit_value for row in limits},
		}

	def _validate_plan_tier(self, plan_tier: str) -> None:
		if plan_tier not in _VALID_PLAN_TIERS:
			raise ValueError(f"Unknown plan tier {plan_tier!r}; allowed: {sorted(_VALID_PLAN_TIERS)}")

	def _validate_resource(
		self,
		resource: str,
		*,
		session: Any,
		tenant_id: str,
		profile: TenantProfile | None = None,
	) -> None:
		profile = profile or session.get(TenantProfile, tenant_id)
		if profile is None:
			raise ValueError(f"Tenant {tenant_id!r} not found")
		self._get_plan_limit(resource, session=session, tenant_id=tenant_id, profile=profile)

	def _get_plan_limit(
		self,
		resource: str,
		*,
		session: Any,
		tenant_id: str,
		profile: TenantProfile,
	) -> TenantPlanLimit:
		row = session.execute(
			sa.select(TenantPlanLimit).where(
				TenantPlanLimit.plan_tier == profile.plan_tier,
				TenantPlanLimit.resource == resource,
			)
		).scalar_one_or_none()
		if row is None:
			raise ValueError(f"Unknown plan resource {resource!r} for tier {profile.plan_tier!r}")
		return row


__all__ = ["TenantControlService"]
