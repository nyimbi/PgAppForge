"""Enterprise Risk Management (ERM) plugin."""
from __future__ import annotations
from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority


class ERMPlugin(BasePlugin):
	name = "erm"
	domain = "grc"
	depends_on: list[str] = ["foundation"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="erm",
			version="1.0.0",
			description="Enterprise Risk Management — risk register, KRI monitoring, heat map",
			author="PgAppForge Contributors",
			tags=["grc", "erm", "risk", "kri"],
			priority=PluginPriority.NORMAL,
		)

	def initialize(self) -> None: pass
	def get_events(self) -> list[str]: return ["grc.erm.risk_breach", "grc.erm.risk_created"]
	def subscribe_to(self) -> list[str]: return []
	def register_models(self) -> list: from pgappforge.plugins.erp.grc.erm import models; return [models.RiskRegister, models.RiskMitigationAction, models.KRI]
	def register_views(self) -> None: pass


__all__ = ["ERMPlugin"]
