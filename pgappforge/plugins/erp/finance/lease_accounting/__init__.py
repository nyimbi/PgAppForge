"""IFRS 16 / ASC 842 Lease Accounting plugin."""
from __future__ import annotations
from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority


class LeaseAccountingPlugin(BasePlugin):
	name = "lease_accounting"
	domain = "finance"
	depends_on: list[str] = ["foundation", "gl"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="lease_accounting",
			version="1.0.0",
			description="IFRS 16 / ASC 842 lease accounting — ROU asset + liability schedules",
			author="PgAppForge Contributors",
			tags=["finance", "ifrs16", "asc842", "lease"],
			priority=PluginPriority.NORMAL,
		)

	def initialize(self) -> None: pass
	def get_events(self) -> list[str]: return ["finance.lease.period_processed", "finance.lease.modified"]
	def subscribe_to(self) -> list[str]: return []
	def register_models(self) -> list: from pgappforge.plugins.erp.finance.lease_accounting import models; return [models.Lease, models.LeasePaymentSchedule, models.LeaseModification]
	def register_views(self) -> None: pass


__all__ = ["LeaseAccountingPlugin"]
