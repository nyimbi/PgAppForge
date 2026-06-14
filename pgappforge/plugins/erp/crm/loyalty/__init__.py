"""Loyalty engine — points, cashback, tier management."""
from __future__ import annotations
from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority


class LoyaltyPlugin(BasePlugin):
	name = "loyalty"
	domain = "crm"
	depends_on: list[str] = ["foundation"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="loyalty",
			version="1.0.0",
			description="Loyalty engine — earn/redeem/expire points, tier upgrades, liability reporting",
			author="PgAppForge Contributors",
			tags=["crm", "loyalty", "rewards", "retail"],
			priority=PluginPriority.NORMAL,
		)

	def initialize(self) -> None: pass
	def get_events(self) -> list[str]: return ["crm.loyalty.points_earned", "crm.loyalty.tier_upgraded"]
	def subscribe_to(self) -> list[str]: return []
	def register_models(self) -> list: from pgappforge.plugins.erp.crm.loyalty import models; return [models.LoyaltyProgram, models.LoyaltyAccount, models.LoyaltyTransaction]
	def register_views(self) -> None: pass


__all__ = ["LoyaltyPlugin"]
