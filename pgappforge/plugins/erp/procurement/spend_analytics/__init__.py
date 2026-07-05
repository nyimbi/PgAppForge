"""Spend analytics plugin — mine AP/PO data for consolidation opportunities."""
from __future__ import annotations
from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority


class SpendAnalyticsPlugin(BasePlugin):
	name = "spend_analytics"
	domain = "procurement"
	depends_on: list[str] = ["foundation", "ap"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="spend_analytics",
			version="1.0.0",
			description="Spend analytics — supplier concentration, tail spend, savings opportunities",
			author="PgAppForge Contributors",
			tags=["procurement", "spend", "analytics", "sourcing"],
			priority=PluginPriority.NORMAL,
		)

	def initialize(self) -> None: pass
	def get_events(self) -> list[str]: return []
	def subscribe_to(self) -> list[str]: return []
	def register_models(self) -> list:
		from pgappforge.plugins.erp.procurement.spend_analytics.models import SpendSnapshot
		return [SpendSnapshot]

	def register_views(self) -> None:
		from pgappforge.plugins.erp.procurement.spend_analytics.views import SpendSnapshotView
		self.add_view(SpendSnapshotView, "Spend Analytics", icon="fa-bar-chart", category="Procurement")


__all__ = ["SpendAnalyticsPlugin"]
