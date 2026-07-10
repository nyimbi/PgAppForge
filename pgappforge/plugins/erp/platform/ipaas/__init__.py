"""iPaaS connector framework — open, extensible integration layer."""
from __future__ import annotations
from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority


class IPaaSPlugin(BasePlugin):
	name = "ipaas"
	domain = "platform"
	depends_on: list[str] = ["foundation"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="ipaas",
			version="1.0.0",
			description="Open iPaaS — connector registry, integration flows, field mapping transforms",
			author="PgAppForge Contributors",
			tags=["platform", "integration", "ipaas", "connectors", "etl"],
			priority=PluginPriority.NORMAL,
		)

	def initialize(self) -> None: pass
	def get_events(self) -> list[str]: return ["platform.ipaas.flow_executed", "platform.ipaas.flow_failed"]
	def subscribe_to(self) -> list[str]: return []
	def register_models(self) -> list: from pgappforge.plugins.erp.platform.ipaas import models; return [models.ConnectorDefinition, models.ConnectorInstance, models.IntegrationFlow, models.IntegrationRun]
	def register_views(self) -> None:
		from pgappforge.plugins.erp.platform.ipaas.views import (
			ConnectorDefinitionView,
			ConnectorInstanceView,
			IntegrationFlowView,
			IPaaSFlowsDashboardView,
		)
		cat = self.config.get("IPAAS_MENU_CATEGORY", "Platform")
		self.add_view(IPaaSFlowsDashboardView, "iPaaS Dashboard", icon="fa-exchange", category=cat)
		self.add_view(ConnectorDefinitionView, "Connector Definitions", icon="fa-plug", category=cat)
		self.add_view(ConnectorInstanceView, "Connector Instances", icon="fa-plug", category=cat)
		self.add_view(IntegrationFlowView, "Integration Flows", icon="fa-random", category=cat)


__all__ = ["IPaaSPlugin"]
