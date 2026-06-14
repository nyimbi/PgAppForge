"""EDI framework plugin — X12, EDIFACT, Peppol, KE eTIMS."""
from __future__ import annotations
from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority


class EDIPlugin(BasePlugin):
	name = "edi"
	domain = "platform"
	depends_on: list[str] = ["foundation"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="edi",
			version="1.0.0",
			description="Open EDI framework — X12, EDIFACT, Peppol BIS3, KE eTIMS message handling",
			author="PgAppForge Contributors",
			tags=["platform", "edi", "x12", "edifact", "peppol", "integration"],
			priority=PluginPriority.NORMAL,
		)

	def initialize(self) -> None: pass
	def get_events(self) -> list[str]: return ["platform.edi.message_sent", "platform.edi.message_received", "platform.edi.message_error"]
	def subscribe_to(self) -> list[str]: return []
	def register_models(self) -> list: from pgappforge.plugins.erp.platform.edi import models; return [models.EDIPartner, models.EDIMessage]
	def register_views(self) -> None: pass


__all__ = ["EDIPlugin"]
