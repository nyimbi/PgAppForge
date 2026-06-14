"""Multi-tenant SaaS control plane."""
from __future__ import annotations
from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority


class TenantControlPlugin(BasePlugin):
	name = "tenant_control"
	domain = "platform"
	depends_on: list[str] = ["foundation"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="tenant_control",
			version="1.0.0",
			description="SaaS control plane — tenant lifecycle, usage tracking, plan limits enforcement",
			author="PgAppForge Contributors",
			tags=["platform", "saas", "multitenancy", "billing"],
			priority=PluginPriority.HIGH,
		)

	def initialize(self) -> None: pass
	def get_events(self) -> list[str]: return ["platform.tenant.provisioned", "platform.tenant.suspended", "platform.tenant.limit_breached"]
	def subscribe_to(self) -> list[str]: return []
	def register_models(self) -> list: from pgappforge.plugins.erp.platform.tenant_control import models; return [models.TenantProfile, models.TenantUsageEvent, models.TenantPlanLimit]
	def register_views(self) -> None: pass


__all__ = ["TenantControlPlugin"]
