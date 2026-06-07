"""
pgappforge/plugins/erp/platform/tenant_control/services.py

TenantControlService — provisioning, suspension, usage metering, plan limit
enforcement, and billing charge computation.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import sqlalchemy as sa

log = logging.getLogger(__name__)


def _uuid4() -> str:
	return str(uuid.uuid4())


def _now() -> datetime:
	return datetime.now(timezone.utc)


def _emit(event: Any, session: Any = None) -> None:
	try:
		from pgappforge.plugins.erp.foundation.events import emit_event as _emit_event
		_emit_event(event, session)
	except Exception as exc:
		log.debug("TenantControl event emit failed: %s", exc)


# ---------------------------------------------------------------------------
# BPM registrations
# ---------------------------------------------------------------------------

try:
	from pgappforge.plugins.workflow.engine import BPMActionRegistry as _BPMReg

	@_BPMReg.register("tenant.provision")
	def _bpm_provision(ctx: dict[str, Any]) -> dict[str, Any]:
		return {"action": "tenant.provision", "params": ctx}

	@_BPMReg.register("tenant.suspend")
	def _bpm_suspend(ctx: dict[str, Any]) -> dict[str, Any]:
		return {"action": "tenant.suspend", "params": ctx}

	@_BPMReg.register("tenant.check_limits")
	def _bpm_check_limits(ctx: dict[str, Any]) -> dict[str, Any]:
		return {"action": "tenant.check_limits", "params": ctx}

except (ImportError, Exception):
	log.debug("BPMActionRegistry not available — TenantControl BPM actions not registered")


# ---------------------------------------------------------------------------
# TenantControlService
# ---------------------------------------------------------------------------

class TenantControlService:
	"""Service layer for multi-tenant control plane operations."""

	def provision_tenant(
		self,
		tenant_id: str,
		name: str,
		plan_tier: str,
		session: Any,
		*,
		trial_days: int = 14,
		feature_flags: dict[str, Any] | None = None,
		billing_hyperion_customer_id: str | None = None,
	) -> Any:
		"""Provision a new tenant, setting up profile and trial period.

		Emits TenantProvisionedEvent.
		"""
		from pgappforge.plugins.erp.platform.tenant_control.models import TenantProfile
		from pgappforge.plugins.erp.platform.tenant_control.events import TenantProvisionedEvent

		existing = session.execute(
			sa.select(TenantProfile).where(TenantProfile.tenant_id == tenant_id)
		).scalar_one_or_none()
		if existing is not None:
			log.info("TenantControl: tenant %s already provisioned — skipping", tenant_id)
			return existing

		profile = TenantProfile(
			id=_uuid4(),
			tenant_id=tenant_id,
			name=name,
			plan_tier=plan_tier.upper(),
			status="TRIAL",
			feature_flags=feature_flags or {},
			billing_hyperion_customer_id=billing_hyperion_customer_id,
			trial_ends_at=_now() + timedelta(days=trial_days),
		)
		session.add(profile)
		session.flush()

		_emit(
			TenantProvisionedEvent(
				aggregate_id=tenant_id,
				aggregate_type="TenantProfile",
				tenant_id=tenant_id,
				name=name,
				plan_tier=plan_tier.upper(),
			),
			session,
		)
		log.info("TenantControl: provisioned tenant %s [%s]", tenant_id, plan_tier)
		return profile

	def suspend_tenant(
		self,
		tenant_id: str,
		reason: str,
		session: Any,
	) -> Any:
		"""Suspend a tenant account.

		Emits TenantSuspendedEvent.
		"""
		from pgappforge.plugins.erp.platform.tenant_control.models import TenantProfile
		from pgappforge.plugins.erp.platform.tenant_control.events import TenantSuspendedEvent

		profile = session.execute(
			sa.select(TenantProfile).where(TenantProfile.tenant_id == tenant_id)
		).scalar_one_or_none()
		if profile is None:
			raise ValueError(f"Tenant {tenant_id} not found")

		profile.status = "SUSPENDED"
		session.flush()

		_emit(
			TenantSuspendedEvent(
				aggregate_id=tenant_id,
				aggregate_type="TenantProfile",
				tenant_id=tenant_id,
				reason=reason,
			),
			session,
		)
		log.info("TenantControl: suspended tenant %s — %s", tenant_id, reason)
		return profile

	def record_usage(
		self,
		tenant_id: str,
		event_type: str,
		quantity: int,
		session: Any,
	) -> Any:
		"""Record a metered usage event for billing and limit tracking."""
		from pgappforge.plugins.erp.platform.tenant_control.models import TenantUsageEvent

		usage = TenantUsageEvent(
			id=_uuid4(),
			tenant_id=tenant_id,
			event_type=event_type.upper(),
			quantity=quantity,
			recorded_at=_now(),
		)
		session.add(usage)
		session.flush()
		return usage

	def check_plan_limits(
		self,
		tenant_id: str,
		session: Any,
		*,
		period_days: int = 30,
	) -> dict[str, Any]:
		"""Check current usage against plan limits for the past period_days.

		Returns: {within_limits: bool, breaches: [{resource, limit, actual}]}
		"""
		from pgappforge.plugins.erp.platform.tenant_control.models import (
			TenantProfile, TenantUsageEvent, TenantPlanLimit,
		)

		profile = session.execute(
			sa.select(TenantProfile).where(TenantProfile.tenant_id == tenant_id)
		).scalar_one_or_none()
		if profile is None:
			return {"within_limits": True, "breaches": []}

		cutoff = _now() - timedelta(days=period_days)

		# Aggregate usage by event_type
		usage_rows = session.execute(
			sa.select(
				TenantUsageEvent.event_type,
				sa.func.sum(TenantUsageEvent.quantity).label("total"),
			)
			.where(
				TenantUsageEvent.tenant_id == tenant_id,
				TenantUsageEvent.recorded_at >= cutoff,
			)
			.group_by(TenantUsageEvent.event_type)
		).all()
		usage_by_type = {row.event_type: row.total or 0 for row in usage_rows}

		# Load limits for this plan
		limit_rows = session.execute(
			sa.select(TenantPlanLimit).where(TenantPlanLimit.plan_tier == profile.plan_tier)
		).scalars().all()

		breaches: list[dict[str, Any]] = []
		for limit_row in limit_rows:
			if limit_row.limit_value == -1:
				continue  # Unlimited
			actual = usage_by_type.get(limit_row.resource, 0)
			if actual > limit_row.limit_value:
				breaches.append({
					"resource": limit_row.resource,
					"limit": limit_row.limit_value,
					"actual": actual,
				})

		return {"within_limits": len(breaches) == 0, "breaches": breaches}

	def enforce_limits(
		self,
		tenant_id: str,
		session: Any,
	) -> list[dict[str, Any]]:
		"""Check limits and emit PlanLimitBreachEvent for each breach found.

		Returns the list of breaches.
		"""
		from pgappforge.plugins.erp.platform.tenant_control.events import PlanLimitBreachEvent

		result = self.check_plan_limits(tenant_id, session)
		for breach in result["breaches"]:
			_emit(
				PlanLimitBreachEvent(
					aggregate_id=tenant_id,
					aggregate_type="TenantProfile",
					tenant_id=tenant_id,
					resource=breach["resource"],
					limit_value=breach["limit"],
					actual_value=breach["actual"],
				),
				session,
			)
		return result["breaches"]

	def compute_billing(
		self,
		tenant_id: str,
		period: str,
		session: Any,
	) -> dict[str, Any]:
		"""Compute a billing summary for a tenant for a given period (YYYY-MM).

		Aggregates usage events for the period and applies per-plan pricing.
		Returns a Hyperion-compatible charge dict.
		"""
		from pgappforge.plugins.erp.platform.tenant_control.models import (
			TenantProfile, TenantUsageEvent,
		)

		try:
			year, month = int(period[:4]), int(period[5:7])
		except (ValueError, IndexError):
			raise ValueError(f"Invalid period format {period!r} — expected YYYY-MM")

		period_start = datetime(year, month, 1, tzinfo=timezone.utc)
		if month == 12:
			period_end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
		else:
			period_end = datetime(year, month + 1, 1, tzinfo=timezone.utc)

		profile = session.execute(
			sa.select(TenantProfile).where(TenantProfile.tenant_id == tenant_id)
		).scalar_one_or_none()
		if profile is None:
			return {"tenant_id": tenant_id, "period": period, "line_items": [], "total_cents": 0}

		usage_rows = session.execute(
			sa.select(
				TenantUsageEvent.event_type,
				sa.func.sum(TenantUsageEvent.quantity).label("total"),
			)
			.where(
				TenantUsageEvent.tenant_id == tenant_id,
				TenantUsageEvent.recorded_at >= period_start,
				TenantUsageEvent.recorded_at < period_end,
			)
			.group_by(TenantUsageEvent.event_type)
		).all()

		# Simple per-unit pricing (cents) — would come from plan config in production
		UNIT_PRICE_CENTS: dict[str, int] = {
			"API_CALL": 0,         # Included in plan
			"STORAGE_MB": 1,       # 1 cent/MB overage
			"ACTIVE_USER": 500,    # 5.00 USD/user/month
			"WORKFLOW_RUN": 2,     # 2 cents/run overage
			"REPORT_RUN": 5,       # 5 cents/report
		}

		line_items: list[dict[str, Any]] = []
		total_cents = 0
		for row in usage_rows:
			unit_price = UNIT_PRICE_CENTS.get(row.event_type, 0)
			amount = (row.total or 0) * unit_price
			total_cents += amount
			line_items.append({
				"resource": row.event_type,
				"quantity": row.total or 0,
				"unit_price_cents": unit_price,
				"amount_cents": amount,
			})

		return {
			"tenant_id": tenant_id,
			"plan_tier": profile.plan_tier,
			"period": period,
			"billing_hyperion_customer_id": profile.billing_hyperion_customer_id,
			"line_items": line_items,
			"total_cents": total_cents,
		}

	def get_usage_dashboard(
		self,
		tenant_id: str,
		session: Any,
		*,
		period_days: int = 30,
	) -> dict[str, Any]:
		"""Return a usage summary dashboard for a tenant."""
		from pgappforge.plugins.erp.platform.tenant_control.models import (
			TenantProfile, TenantUsageEvent,
		)

		profile = session.execute(
			sa.select(TenantProfile).where(TenantProfile.tenant_id == tenant_id)
		).scalar_one_or_none()

		cutoff = _now() - timedelta(days=period_days)
		usage_rows = session.execute(
			sa.select(
				TenantUsageEvent.event_type,
				sa.func.sum(TenantUsageEvent.quantity).label("total"),
				sa.func.count().label("events"),
			)
			.where(
				TenantUsageEvent.tenant_id == tenant_id,
				TenantUsageEvent.recorded_at >= cutoff,
			)
			.group_by(TenantUsageEvent.event_type)
		).all()

		limits_result = self.check_plan_limits(tenant_id, session, period_days=period_days)

		return {
			"tenant_id": tenant_id,
			"plan_tier": profile.plan_tier if profile else "UNKNOWN",
			"status": profile.status if profile else "UNKNOWN",
			"period_days": period_days,
			"usage": {row.event_type: row.total or 0 for row in usage_rows},
			"within_limits": limits_result["within_limits"],
			"breaches": limits_result["breaches"],
		}
