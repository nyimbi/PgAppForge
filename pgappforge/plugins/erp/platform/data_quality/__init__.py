"""
pgappforge/plugins/erp/platform/data_quality/__init__.py

Platform data-quality plugin.
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

from .services import DataQualityService, QualityModelSpec

log = logging.getLogger(__name__)

DATA_QUALITY_MENU_CATEGORY = "Platform"


class DataQualityPlugin(BasePlugin):
	"""Cross-domain data-quality monitoring plugin."""

	name = "platform.data_quality"
	domain = "platform"
	depends_on: list[str] = ["foundation"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="platform.data_quality",
			version="1.0.0",
			description=(
				"Cross-domain data-quality monitoring for completeness, duplicate "
				"detection, and stale-record review."
			),
			author="PgAppForge Contributors",
			tags=["platform", "data-quality", "completeness", "duplicates", "stale-records"],
			priority=PluginPriority.NORMAL,
			permissions=["can_data_quality_dashboard"],
			safe_mode_compatible=True,
		)

	def get_events(self) -> list[str]:
		return []

	def subscribe_to(self) -> list[str]:
		return []

	def initialize(self) -> None:
		log.info("DataQualityPlugin initialised")

	def register_views(self) -> None:
		from pgappforge.plugins.erp.platform.data_quality.views import DataQualityDashboardView
		cat = self.config.get("DATA_QUALITY_MENU_CATEGORY", DATA_QUALITY_MENU_CATEGORY)
		self.add_view(
			DataQualityDashboardView,
			"Data Quality",
			icon="fa-check-square-o",
			category=cat,
		)
		log.info("DataQualityPlugin: views registered under %r", cat)

	def register_models(self) -> list[type]:
		return []


def create_plugin(appbuilder: Any, config: dict[str, Any] | None = None) -> DataQualityPlugin:
	return DataQualityPlugin(appbuilder, config=config or {})


__all__ = [
	"DataQualityPlugin",
	"DataQualityService",
	"QualityModelSpec",
	"create_plugin",
]
