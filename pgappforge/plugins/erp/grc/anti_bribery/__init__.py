"""Anti-bribery / FCPA tracking plugin."""
from __future__ import annotations
from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority


class AntiBriberyPlugin(BasePlugin):
	name = "anti_bribery"
	domain = "grc"
	depends_on: list[str] = ["foundation"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="anti_bribery",
			version="1.0.0",
			description="FCPA/UK Bribery Act compliance — gift/entertainment log, conflict of interest declarations",
			author="PgAppForge Contributors",
			tags=["grc", "fcpa", "anti_bribery", "compliance"],
			priority=PluginPriority.NORMAL,
		)

	def initialize(self) -> None: pass
	def get_events(self) -> list[str]: return ["grc.anti_bribery.gift_flagged", "grc.anti_bribery.coi_submitted"]
	def subscribe_to(self) -> list[str]: return []
	def register_models(self) -> list: from pgappforge.plugins.erp.grc.anti_bribery import models; return [models.GiftEntertainmentLog, models.ConflictOfInterestDeclaration]
	def register_views(self) -> None: pass


__all__ = ["AntiBriberyPlugin"]
