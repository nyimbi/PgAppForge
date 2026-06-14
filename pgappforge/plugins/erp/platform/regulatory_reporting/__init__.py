"""Regulatory reporting — SAF-T, CSRD/ESG, Peppol BIS3 export."""
from __future__ import annotations
from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority


class RegulatoryReportingPlugin(BasePlugin):
	name = "regulatory_reporting"
	domain = "platform"
	depends_on: list[str] = ["foundation", "gl"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="regulatory_reporting",
			version="1.0.0",
			description="Regulatory reporting — SAF-T/OECD GL export, CSRD/ESRS sustainability, Peppol",
			author="PgAppForge Contributors",
			tags=["platform", "compliance", "saft", "csrd", "esg", "peppol"],
			priority=PluginPriority.NORMAL,
		)

	def initialize(self) -> None: pass
	def get_events(self) -> list[str]: return []
	def subscribe_to(self) -> list[str]: return []
	def register_models(self) -> list: return []
	def register_views(self) -> None: pass


__all__ = ["RegulatoryReportingPlugin"]
