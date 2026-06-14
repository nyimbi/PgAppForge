"""Ethics hotline / whistleblower case management plugin."""
from __future__ import annotations
from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority


class EthicsPlugin(BasePlugin):
	name = "ethics"
	domain = "grc"
	depends_on: list[str] = ["foundation"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="ethics",
			version="1.0.0",
			description="Anonymous ethics hotline and whistleblower case management",
			author="PgAppForge Contributors",
			tags=["grc", "ethics", "whistleblower", "compliance"],
			priority=PluginPriority.HIGH,
		)

	def initialize(self) -> None: pass
	def get_events(self) -> list[str]: return ["grc.ethics.report_submitted", "grc.ethics.case_opened", "grc.ethics.case_resolved"]
	def subscribe_to(self) -> list[str]: return []
	def register_models(self) -> list: from pgappforge.plugins.erp.grc.ethics import models; return [models.EthicsReport, models.EthicsCase]
	def register_views(self) -> None: pass


__all__ = ["EthicsPlugin"]
