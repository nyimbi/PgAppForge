"""
pgappforge/plugins/erp/procurement/spend_analytics/__init__.py

Spend Analytics plugin — procurement spend cube, tail-spend analysis,
and savings opportunity identification.

Data sources:
  pgappforge.plugins.erp.finance.ap.models.APInvoice
  pgappforge.plugins.erp.procurement.trade_compliance.models.HSCodeMapping (optional)

Events emitted:
  procurement.spend.cube.computed
  procurement.spend.savings.identified

Usage
-----
    PGAPPFORGE_PLUGINS = ["pgappforge.plugins.erp.procurement.spend_analytics"]
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class SpendAnalyticsPlugin(BasePlugin):
	"""Spend Analytics — spend cube, tail-spend, and savings opportunity engine."""

	name = "spend_analytics"
	domain = "procurement"
	depends_on: list[str] = ["foundation", "finance.ap"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="spend_analytics",
			version="1.0.0",
			description=(
				"Spend Analytics — compute spend cubes from AP invoices, identify "
				"tail-spend consolidation opportunities, and flag suppliers priced "
				">20% above category peers for savings capture."
			),
			author="PgAppForge Contributors",
			tags=[
				"procurement", "spend", "analytics", "savings",
				"tail-spend", "category-management",
			],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_spend_cube_read",
				"can_spend_cube_compute",
				"can_spend_tail_read",
				"can_spend_savings_read",
			],
			safe_mode_compatible=True,
		)

	def get_events(self) -> list[str]:
		return [
			"procurement.spend.cube.computed",
			"procurement.spend.savings.identified",
		]

	def subscribe_to(self) -> list[str]:
		return []

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"SPEND_TAIL_THRESHOLD_PCT": 2.0,
			"SPEND_SAVINGS_OUTLIER_PCT": 20.0,
			"SPEND_TOP_SUPPLIERS_LIMIT": 20,
		}
		self.config = {**defaults, **self.config}
		log.info("SpendAnalyticsPlugin initialised")

	def register_views(self) -> None:
		try:
			from pgappforge.plugins.erp.procurement.spend_analytics.views import SpendSnapshotView
		except ImportError:
			log.warning("SpendAnalyticsPlugin.register_views: views module not available — skipping.")
			return
		cat = self.config.get("SPEND_ANALYTICS_MENU_CATEGORY", "Procurement")
		self.add_view(SpendSnapshotView, "Spend Analytics", icon="fa-pie-chart", category=cat)
		log.info("SpendAnalyticsPlugin: views registered under %r", cat)

	def register_models(self) -> list:
		from pgappforge.plugins.erp.procurement.spend_analytics.models import SpendSnapshot
		return [SpendSnapshot]


def create_plugin(
	appbuilder: Any, config: dict[str, Any] | None = None
) -> SpendAnalyticsPlugin:
	return SpendAnalyticsPlugin(appbuilder, config=config or {})


from pgappforge.plugins.erp.procurement.spend_analytics.models import SpendSnapshot  # noqa: E402
from pgappforge.plugins.erp.procurement.spend_analytics.services import (  # noqa: E402
	SpendAnalyticsService,
)

__all__ = [
	"SpendAnalyticsPlugin",
	"create_plugin",
	"SpendSnapshot",
	"SpendAnalyticsService",
]
