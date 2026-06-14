"""MES integration framework — OPC-UA adapter + OEE computation."""
from __future__ import annotations
from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority


class MESPlugin(BasePlugin):
	name = "mes"
	domain = "platform"
	depends_on: list[str] = ["foundation"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="mes",
			version="1.0.0",
			description="MES integration — machine telemetry, OEE, OPC-UA stub, production alerts",
			author="PgAppForge Contributors",
			tags=["platform", "mes", "opc_ua", "oee", "manufacturing"],
			priority=PluginPriority.NORMAL,
		)

	def initialize(self) -> None: pass
	def get_events(self) -> list[str]: return ["platform.mes.alert_created", "platform.mes.telemetry_received"]
	def subscribe_to(self) -> list[str]: return []
	def register_models(self) -> list: from pgappforge.plugins.erp.platform.mes import models; return [models.MachineDefinition, models.MachineReading, models.ProductionAlert]
	def register_views(self) -> None: pass


__all__ = ["MESPlugin"]
