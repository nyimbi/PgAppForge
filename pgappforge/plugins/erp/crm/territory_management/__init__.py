"""Territory management — rule-based assignment."""
from __future__ import annotations
from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority


class TerritoryManagementPlugin(BasePlugin):
	name = "territory_management"
	domain = "crm"
	depends_on: list[str] = ["foundation"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="territory_management",
			version="1.0.0",
			description="Sales territory management — rule-based assignment, rep reassignment",
			author="PgAppForge Contributors",
			tags=["crm", "territory", "sales"],
			priority=PluginPriority.NORMAL,
		)

	def initialize(self) -> None: pass
	def get_events(self) -> list[str]: return []
	def subscribe_to(self) -> list[str]: return []
	def register_models(self) -> list: from pgappforge.plugins.erp.crm.territory_management import models; return [models.SalesTerritory, models.TerritoryAssignment]
	def register_views(self) -> None: pass


__all__ = ["TerritoryManagementPlugin"]
