"""Joint venture accounting plugin."""
from __future__ import annotations
from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority


class JointVenturePlugin(BasePlugin):
	name = "joint_venture"
	domain = "finance"
	depends_on: list[str] = ["foundation", "gl", "ar"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="joint_venture",
			version="1.0.0",
			description="Joint venture accounting — expense distribution by ownership % and cash calls",
			author="PgAppForge Contributors",
			tags=["finance", "jv", "joint_venture", "oil_gas"],
			priority=PluginPriority.NORMAL,
		)

	def initialize(self) -> None: pass
	def get_events(self) -> list[str]: return ["finance.jv.cash_call_issued", "finance.jv.expense_distributed"]
	def subscribe_to(self) -> list[str]: return []
	def register_models(self) -> list: from pgappforge.plugins.erp.finance.joint_venture import models; return [models.JointVenture, models.JVCashCall, models.JVBilling]
	def register_views(self) -> None: pass


__all__ = ["JointVenturePlugin"]
