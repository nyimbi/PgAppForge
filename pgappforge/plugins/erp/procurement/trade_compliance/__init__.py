"""
pgappforge/plugins/erp/procurement/trade_compliance/__init__.py

Trade Compliance plugin — denied-party screening, HS code classification,
duty calculation, and OFAC SDN list management.

Screening thresholds (Jaro-Winkler similarity):
  >= 0.95  → MATCH     (entity blocked)
  >= 0.85  → POSSIBLE_MATCH (manual review required)
  < 0.85   → CLEAR

Events emitted:
  procurement.trade.screened
  procurement.trade.blocked
  procurement.trade.hs_lookup
  procurement.trade.list_refreshed

Usage
-----
    PGAPPFORGE_PLUGINS = ["pgappforge.plugins.erp.procurement.trade_compliance"]
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class TradeCompliancePlugin(BasePlugin):
	"""Trade Compliance — denied-party screening and HS code classification."""

	name = "trade_compliance"
	domain = "procurement"
	depends_on: list[str] = ["foundation"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="trade_compliance",
			version="1.0.0",
			description=(
				"Trade Compliance — Jaro-Winkler fuzzy screening against OFAC SDN, "
				"UN Consolidated, EU/UK Sanctions lists. HS code classification with "
				"country-specific duty rates and export-control flags."
			),
			author="PgAppForge Contributors",
			tags=[
				"procurement", "trade", "compliance", "ofac", "sanctions",
				"hs-codes", "export-controls",
			],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_trade_lists_read",
				"can_trade_lists_write",
				"can_trade_screen",
				"can_trade_hs_read",
				"can_trade_hs_write",
				"can_trade_duty_calculate",
			],
			safe_mode_compatible=True,
		)

	def get_events(self) -> list[str]:
		return [
			"procurement.trade.screened",
			"procurement.trade.blocked",
			"procurement.trade.hs_lookup",
			"procurement.trade.list_refreshed",
		]

	def subscribe_to(self) -> list[str]:
		return []

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"TRADE_MATCH_THRESHOLD": 0.95,
			"TRADE_POSSIBLE_MATCH_THRESHOLD": 0.85,
			"TRADE_OFAC_AUTO_REFRESH_DAYS": 7,
		}
		self.config = {**defaults, **self.config}
		log.info("TradeCompliancePlugin initialised")

	def register_views(self) -> None:
		try:
			from pgappforge.plugins.erp.procurement.trade_compliance.views import (
				TradeRestrictionListView,
				TradeScreeningResultView,
				HSCodeMappingView,
			)
		except ImportError:
			log.warning("TradeCompliancePlugin.register_views: views module not available — skipping.")
			return
		cat = self.config.get("TRADE_MENU_CATEGORY", "Procurement")
		self.add_view(TradeRestrictionListView, "Restriction Lists", icon="fa-ban", category=cat)
		self.add_view(TradeScreeningResultView, "Screening Results", icon="fa-search", category=cat)
		self.add_view(HSCodeMappingView, "HS Codes", icon="fa-barcode", category=cat)
		log.info("TradeCompliancePlugin: views registered under %r", cat)

	def register_models(self) -> list:
		from pgappforge.plugins.erp.procurement.trade_compliance.models import (
			TradeRestrictionList,
			TradeScreeningResult,
			HSCodeMapping,
		)
		return [TradeRestrictionList, TradeScreeningResult, HSCodeMapping]


def create_plugin(
	appbuilder: Any, config: dict[str, Any] | None = None
) -> TradeCompliancePlugin:
	return TradeCompliancePlugin(appbuilder, config=config or {})


from pgappforge.plugins.erp.procurement.trade_compliance.models import (  # noqa: E402
	TradeRestrictionList,
	TradeScreeningResult,
	HSCodeMapping,
)
from pgappforge.plugins.erp.procurement.trade_compliance.services import (  # noqa: E402
	TradeComplianceService,
)

__all__ = [
	"TradeCompliancePlugin",
	"create_plugin",
	"TradeRestrictionList",
	"TradeScreeningResult",
	"HSCodeMapping",
	"TradeComplianceService",
]
