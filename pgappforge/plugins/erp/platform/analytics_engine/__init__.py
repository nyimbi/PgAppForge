"""Embedded analytics engine — PostgreSQL materialized views + optional DuckDB."""
from __future__ import annotations
from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority


class AnalyticsEnginePlugin(BasePlugin):
	name = "analytics_engine"
	domain = "platform"
	depends_on: list[str] = ["foundation"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="analytics_engine",
			version="1.0.0",
			description="Embedded analytics — tenant-definable cubes, materialized views, DuckDB fallback",
			author="PgAppForge Contributors",
			tags=["platform", "analytics", "olap", "reporting"],
			priority=PluginPriority.NORMAL,
		)

	def initialize(self) -> None: pass
	def get_events(self) -> list[str]: return ["platform.analytics.cube_refreshed"]
	def subscribe_to(self) -> list[str]: return []
	def register_models(self) -> list: from pgappforge.plugins.erp.platform.analytics_engine import models; return [models.AnalyticsCube, models.AnalyticsReport, models.ReportCache]
	def register_views(self) -> None: pass


__all__ = ["AnalyticsEnginePlugin"]
