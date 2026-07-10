"""
pgappforge/plugins/erp/industry/__init__.py

Industry-vertical ERP plugins.
"""
from __future__ import annotations

from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority


INDUSTRY_MODULES = [
	"manufacturing",
	"consumer_goods",
	"public_sector",
	"nonprofit",
	"education",
	"energy",
	"life_sciences",
	"agritech",
	"water",
	"oil_gas",
	"financial_contracts",
	"financial_services",
	"health",
	"insurance",
	"intl_aid",
	"legal",
	"media",
	"procurement",
	"research",
	"smart_city",
	"track_trace",
	"utilities",
	"clubs",
	"real_estate",
]


class IndustryPlugin(BasePlugin):
	"""Aggregate marker plugin for industry vertical modules."""

	name = "industry"
	domain = "industry"
	depends_on: list[str] = ["foundation"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="industry",
			version="1.0.0",
			description="Industry vertical ERP plugin collection.",
			author="PgAppForge Contributors",
			tags=["erp", "industry"],
			priority=PluginPriority.NORMAL,
			safe_mode_compatible=True,
		)

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"INDUSTRY_MENU_CATEGORY": "Industry",
		}
		self.config = {**defaults, **self.config}

	def register_models(self) -> list[type]:
		return []

	def get_events(self) -> list[str]:
		return []

	def subscribe_to(self) -> list[str]:
		return []


def create_plugin(appbuilder: Any, config: dict[str, Any] | None = None) -> IndustryPlugin:
	"""Construct and return the aggregate industry plugin."""
	return IndustryPlugin(appbuilder, config=config or {})


__all__ = [
	"IndustryPlugin",
	"create_plugin",
	"INDUSTRY_MODULES",
	"manufacturing",
	"consumer_goods",
	"public_sector",
	"nonprofit",
	"education",
	"energy",
	"life_sciences",
	"agritech",
	"water",
	"oil_gas",
	"financial_contracts",
	"financial_services",
	"health",
	"insurance",
	"intl_aid",
	"legal",
	"media",
	"procurement",
	"research",
	"smart_city",
	"track_trace",
	"utilities",
	"clubs",
	"real_estate",
]
