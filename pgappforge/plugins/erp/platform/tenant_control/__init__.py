"""
pgappforge/plugins/erp/platform/tenant_control/__init__.py

TenantControlPlugin — Multi-tenant SaaS control plane.

Domain:    platform
Depends:   foundation

Events emitted
--------------
  platform.tenant.provisioned
  platform.tenant.suspended
  platform.tenant.plan_limit_breach
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class TenantControlPlugin(BasePlugin):
	"""Multi-tenant SaaS Control Plane plugin.

	Covers tenant provisioning and lifecycle, feature flag management,
	metered usage recording, plan limit enforcement with breach events,
	billing charge computation (Hyperion-compatible), and usage dashboards.
	"""

	name = "tenant_control"
	domain = "platform"
	depends_on: list[str] = ["foundation"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="tenant_control",
			version="1.0.0",
			description=(
				"Tenant Control — multi-tenant provisioning, feature flags, metered usage, "
				"plan limit enforcement, billing computation, and usage dashboards."
			),
			author="PgAppForge Contributors",
			tags=["platform", "saas", "multi-tenant", "billing", "usage", "metering"],
			priority=PluginPriority.HIGH,
			permissions=[
				"can_tct_tenant_read",
				"can_tct_tenant_provision",
				"can_tct_tenant_suspend",
				"can_tct_usage_record",
				"can_tct_limits_check",
				"can_tct_billing_compute",
				"can_tct_dashboard_view",
				"can_tct_plan_limit_manage",
			],
			safe_mode_compatible=True,
		)

	def get_events(self) -> list[str]:
		return [
			"platform.tenant.provisioned",
			"platform.tenant.suspended",
			"platform.tenant.plan_limit_breach",
		]

	def subscribe_to(self) -> list[str]:
		return []

	def activate(self) -> None:
		self.initialize()

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"TENANT_DEFAULT_TRIAL_DAYS": 14,
			"TENANT_USAGE_PERIOD_DAYS": 30,
		}
		self.config = {**defaults, **self.config}
		log.info("TenantControlPlugin initialised")

	def register_models(self) -> list:
		from pgappforge.plugins.erp.platform.tenant_control.models import (
			TenantProfile,
			TenantUsageEvent,
			TenantPlanLimit,
		)
		return [TenantProfile, TenantUsageEvent, TenantPlanLimit]

	@staticmethod
	def seed_default_limits(session: Any) -> None:
		"""Seed default plan limits if not already present."""
		from pgappforge.plugins.erp.platform.tenant_control.models import TenantPlanLimit
		import sqlalchemy as sa

		DEFAULTS = [
			# STARTER limits
			("STARTER", "API_CALL", 10_000),
			("STARTER", "STORAGE_MB", 1_024),
			("STARTER", "ACTIVE_USER", 5),
			("STARTER", "WORKFLOW_RUN", 100),
			# GROWTH limits
			("GROWTH", "API_CALL", 100_000),
			("GROWTH", "STORAGE_MB", 10_240),
			("GROWTH", "ACTIVE_USER", 25),
			("GROWTH", "WORKFLOW_RUN", 1_000),
			# ENTERPRISE — unlimited (-1)
			("ENTERPRISE", "API_CALL", -1),
			("ENTERPRISE", "STORAGE_MB", -1),
			("ENTERPRISE", "ACTIVE_USER", -1),
			("ENTERPRISE", "WORKFLOW_RUN", -1),
		]
		import uuid as _uuid

		for plan_tier, resource, limit_value in DEFAULTS:
			existing = session.execute(
				sa.select(TenantPlanLimit).where(
					TenantPlanLimit.plan_tier == plan_tier,
					TenantPlanLimit.resource == resource,
				)
			).scalar_one_or_none()
			if existing is None:
				session.add(TenantPlanLimit(
					id=str(_uuid.uuid4()),
					plan_tier=plan_tier,
					resource=resource,
					limit_value=limit_value,
				))
		log.info("TenantControlPlugin: default plan limits seeded")


def create_plugin(
	appbuilder: Any,
	config: dict[str, Any] | None = None,
) -> TenantControlPlugin:
	return TenantControlPlugin(appbuilder, config=config or {})


from pgappforge.plugins.erp.platform.tenant_control.models import (  # noqa: E402
	TenantProfile,
	TenantUsageEvent,
	TenantPlanLimit,
)
from pgappforge.plugins.erp.platform.tenant_control.events import (  # noqa: E402
	TenantProvisionedEvent,
	TenantSuspendedEvent,
	PlanLimitBreachEvent,
)
from pgappforge.plugins.erp.platform.tenant_control.services import TenantControlService  # noqa: E402

__all__ = [
	"TenantControlPlugin",
	"create_plugin",
	"TenantProfile",
	"TenantUsageEvent",
	"TenantPlanLimit",
	"TenantProvisionedEvent",
	"TenantSuspendedEvent",
	"PlanLimitBreachEvent",
	"TenantControlService",
]
