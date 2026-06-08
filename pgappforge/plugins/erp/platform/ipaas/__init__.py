"""
pgappforge/plugins/erp/platform/ipaas/__init__.py

IPaaSPlugin — Integration Platform as a Service.

Domain:    platform
Depends:   foundation

Events emitted
--------------
  platform.ipaas.connector.registered
  platform.ipaas.flow.executed
  platform.ipaas.integration.error
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class IPaaSPlugin(BasePlugin):
	"""Integration Platform as a Service plugin.

	Provides connector definitions (REST, DB, FILE, EMAIL, QUEUE), connector
	instances with encrypted config, integration flow definitions with field
	mapping and transform support, execution runs with full audit trail, and
	MuleSoft-style flow history.
	"""

	name = "ipaas"
	domain = "platform"
	depends_on: list[str] = ["foundation"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="ipaas",
			version="1.0.0",
			description=(
				"iPaaS — connector registry, integration flows with field mapping/transforms, "
				"execution runs, and flow history. MuleSoft-alternative for PgAppForge."
			),
			author="PgAppForge Contributors",
			tags=["platform", "integration", "ipaas", "connectors", "etl", "mulesoft-alternative"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_ips_connector_read",
				"can_ips_connector_write",
				"can_ips_flow_read",
				"can_ips_flow_write",
				"can_ips_flow_execute",
				"can_ips_run_read",
			],
			safe_mode_compatible=True,
		)

	def get_events(self) -> list[str]:
		return [
			"platform.ipaas.connector.registered",
			"platform.ipaas.flow.executed",
			"platform.ipaas.integration.error",
		]

	def subscribe_to(self) -> list[str]:
		return []

	def activate(self) -> None:
		self.initialize()

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"IPAAS_MAX_RUN_HISTORY": 500,
		}
		self.config = {**defaults, **self.config}
		log.info("IPaaSPlugin initialised")

	def register_views(self) -> None:
		from pgappforge.plugins.erp.platform.ipaas.views import (
			IPaaSFlowsDashboardView,
			ConnectorDefinitionView,
			ConnectorInstanceView,
			IntegrationFlowView,
		)
		cat = self.config.get("IPAAS_MENU_CATEGORY", "Integrations")
		self.add_view(IPaaSFlowsDashboardView, "iPaaS Dashboard", icon="fa-exchange", category=cat)
		self.add_view(ConnectorDefinitionView, "Connector Definitions", icon="fa-plug", category=cat)
		self.add_view(ConnectorInstanceView, "Connector Instances", icon="fa-link", category=cat)
		self.add_view(IntegrationFlowView, "Integration Flows", icon="fa-random", category=cat)
		log.info("IPaaSPlugin: views registered under %r", cat)

	def register_models(self) -> list:
		from pgappforge.plugins.erp.platform.ipaas.models import (
			ConnectorDefinition,
			ConnectorInstance,
			IntegrationFlow,
			IntegrationRun,
		)
		return [ConnectorDefinition, ConnectorInstance, IntegrationFlow, IntegrationRun]


def create_plugin(
	appbuilder: Any,
	config: dict[str, Any] | None = None,
) -> IPaaSPlugin:
	return IPaaSPlugin(appbuilder, config=config or {})


from pgappforge.plugins.erp.platform.ipaas.models import (  # noqa: E402
	ConnectorDefinition,
	ConnectorInstance,
	IntegrationFlow,
	IntegrationRun,
)
from pgappforge.plugins.erp.platform.ipaas.events import (  # noqa: E402
	FlowExecutedEvent,
	ConnectorRegisteredEvent,
	IntegrationErrorEvent,
)
from pgappforge.plugins.erp.platform.ipaas.services import IntegrationService  # noqa: E402

__all__ = [
	"IPaaSPlugin",
	"create_plugin",
	"ConnectorDefinition",
	"ConnectorInstance",
	"IntegrationFlow",
	"IntegrationRun",
	"FlowExecutedEvent",
	"ConnectorRegisteredEvent",
	"IntegrationErrorEvent",
	"IntegrationService",
]
