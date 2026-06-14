"""Position management — headcount budget control."""
from __future__ import annotations
from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority


class PositionManagementPlugin(BasePlugin):
	name = "position_management"
	domain = "hcm"
	depends_on: list[str] = ["foundation"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="position_management",
			version="1.0.0",
			description="Position-based org design — every employee occupies a budgeted Position",
			author="PgAppForge Contributors",
			tags=["hcm", "position", "headcount", "org_design"],
			priority=PluginPriority.NORMAL,
		)

	def initialize(self) -> None: pass
	def get_events(self) -> list[str]: return ["hcm.position.vacated", "hcm.position.filled"]
	def subscribe_to(self) -> list[str]: return []
	def register_models(self) -> list: from pgappforge.plugins.erp.hcm.position_management import models; return [models.Position, models.HeadcountRequest]
	def register_views(self) -> None: pass


__all__ = ["PositionManagementPlugin"]
