"""
pgappforge/plugins/erp/platform/analytics_engine/__init__.py

AnalyticsEnginePlugin — OLAP cubes, materialized views, financial dashboards.

Domain:    platform
Depends:   foundation

Events emitted
--------------
  platform.analytics.cube.defined
  platform.analytics.cube.refreshed
  platform.analytics.report.run
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class AnalyticsEnginePlugin(BasePlugin):
	"""Analytics Engine plugin.

	Provides OLAP-style analytics cubes backed by PostgreSQL materialized views,
	saved report definitions with filter/group-by, cached query results,
	and pre-built financial dashboard queries.
	"""

	name = "analytics_engine"
	domain = "platform"
	depends_on: list[str] = ["foundation"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="analytics_engine",
			version="1.0.0",
			description=(
				"Analytics Engine — OLAP cubes, PostgreSQL materialized views, "
				"parameterised reports, result caching, and financial dashboards."
			),
			author="PgAppForge Contributors",
			tags=["platform", "analytics", "bi", "cubes", "materialized-views", "dashboards"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_anl_cube_read",
				"can_anl_cube_write",
				"can_anl_cube_refresh",
				"can_anl_report_read",
				"can_anl_report_write",
				"can_anl_report_run",
				"can_anl_dashboard_view",
			],
			safe_mode_compatible=True,
		)

	def get_events(self) -> list[str]:
		return [
			"platform.analytics.cube.defined",
			"platform.analytics.cube.refreshed",
			"platform.analytics.report.run",
		]

	def subscribe_to(self) -> list[str]:
		return []

	def activate(self) -> None:
		self.initialize()

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"ANALYTICS_DEFAULT_LIMIT": 1000,
			"ANALYTICS_CACHE_TTL_MINUTES": 60,
		}
		self.config = {**defaults, **self.config}
		log.info("AnalyticsEnginePlugin initialised")

	def register_views(self) -> None:
		from pgappforge.plugins.erp.platform.analytics_engine.views import (
			AnalyticsDashboardView,
			AnalyticsCubeView,
			AnalyticsReportView,
		)
		cat = self.config.get("ANALYTICS_MENU_CATEGORY", "Analytics")
		self.add_view(AnalyticsDashboardView, "Analytics Dashboard", icon="fa-tachometer", category=cat)
		self.add_view(AnalyticsCubeView, "Cubes", icon="fa-database", category=cat)
		self.add_view(AnalyticsReportView, "Reports", icon="fa-bar-chart", category=cat)
		log.info("AnalyticsEnginePlugin: views registered under %r", cat)

	def register_models(self) -> list:
		from pgappforge.plugins.erp.platform.analytics_engine.models import (
			AnalyticsCube,
			AnalyticsReport,
			ReportCache,
		)
		return [AnalyticsCube, AnalyticsReport, ReportCache]


def create_plugin(
	appbuilder: Any,
	config: dict[str, Any] | None = None,
) -> AnalyticsEnginePlugin:
	return AnalyticsEnginePlugin(appbuilder, config=config or {})


from pgappforge.plugins.erp.platform.analytics_engine.models import (  # noqa: E402
	AnalyticsCube,
	AnalyticsReport,
	ReportCache,
)
from pgappforge.plugins.erp.platform.analytics_engine.events import (  # noqa: E402
	CubeDefinedEvent,
	CubeRefreshedEvent,
	ReportRunEvent,
)
from pgappforge.plugins.erp.platform.analytics_engine.services import (  # noqa: E402
	AnalyticsEngineService,
)

__all__ = [
	"AnalyticsEnginePlugin",
	"create_plugin",
	"AnalyticsCube",
	"AnalyticsReport",
	"ReportCache",
	"CubeDefinedEvent",
	"CubeRefreshedEvent",
	"ReportRunEvent",
	"AnalyticsEngineService",
]
