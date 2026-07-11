"""
pgappforge/plugins/erp/finance/currency/__init__.py

CurrencyPlugin — tenant-scoped exchange-rate management for finance.
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority
from pgappforge.plugins.erp.finance.currency.models import ExchangeRate
from pgappforge.plugins.erp.finance.currency.services import (
	CurrencyRateNotFoundError,
	CurrencyServiceError,
	ExchangeRateService,
)

log = logging.getLogger(__name__)


class CurrencyPlugin(BasePlugin):
	name = "currency"
	domain = "finance"
	depends_on: list[str] = ["foundation"]

	metadata = PluginMetadata(
		name="currency",
		version="1.0.0",
		description="Multi-currency exchange-rate management and tenant-scoped conversion utilities.",
		author="PgAppForge Contributors",
		tags=["finance", "currency", "fx", "exchange-rates", "multi-currency"],
		priority=PluginPriority.NORMAL,
		permissions=[
			"can_currency_dashboard",
			"can_exchange_rate_list",
			"can_exchange_rate_write",
		],
		safe_mode_compatible=True,
	)

	def initialize(self) -> None:
		self.config.setdefault("CURRENCY_MENU_CATEGORY", "Currency Management")

	def get_events(self) -> list[str]:
		return ["exchange_rate.updated"]

	def subscribe_to(self) -> list[str]:
		return []

	def register_models(self) -> list:
		return [ExchangeRate]

	def register_views(self) -> None:
		from pgappforge.plugins.erp.finance.currency.views import (
			CurrencyDashboardView,
			ExchangeRateView,
		)

		cat = self.config.get("CURRENCY_MENU_CATEGORY", "Currency Management")
		self.add_view(CurrencyDashboardView, "Currency Dashboard", icon="fa-dashboard", category=cat)
		self.add_view(ExchangeRateView, "Exchange Rates", icon="fa-exchange", category=cat)
		log.info("CurrencyPlugin: views registered under category %r", cat)

	def setup_rules(self, session: Any) -> None:
		pass


def create_plugin(appbuilder, config=None) -> CurrencyPlugin:
	return CurrencyPlugin(appbuilder, config=config or {})


__all__ = [
	"CurrencyPlugin",
	"CurrencyRateNotFoundError",
	"CurrencyServiceError",
	"ExchangeRate",
	"ExchangeRateService",
	"create_plugin",
]
