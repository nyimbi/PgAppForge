"""Hedge accounting plugin (IFRS 9 / ASC 815)."""
from __future__ import annotations
from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority


class HedgeAccountingPlugin(BasePlugin):
	name = "hedge_accounting"
	domain = "finance"
	depends_on: list[str] = ["foundation", "gl"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="hedge_accounting",
			version="1.0.0",
			description="IFRS 9 hedge accounting — cash flow, fair value, and net investment hedges",
			author="PgAppForge Contributors",
			tags=["finance", "ifrs9", "hedge", "derivatives"],
			priority=PluginPriority.NORMAL,
		)

	def initialize(self) -> None: pass
	def get_events(self) -> list[str]: return ["finance.hedge.designated", "finance.hedge.effectiveness_tested"]
	def subscribe_to(self) -> list[str]: return []
	def register_models(self) -> list: from pgappforge.plugins.erp.finance.hedge_accounting import models; return [models.HedgeRelationship, models.HedgeJournalEntry]
	def register_views(self) -> None: pass


__all__ = ["HedgeAccountingPlugin"]
