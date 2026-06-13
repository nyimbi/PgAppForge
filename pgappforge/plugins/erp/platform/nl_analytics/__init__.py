"""
pgappforge/plugins/erp/platform/nl_analytics/__init__.py

NLAnalyticsPlugin — natural language → SQL analytics for PgAppForge ERP.

Domain:   platform
Depends:  foundation, nlp

Capabilities
------------
  * Plain-English questions → PostgreSQL SELECT via LiteLLM proxy
  * Schema auto-discovery (introspects live DB schema)
  * Semantic layer integration (reads SemanticRegistry if available)
  * Result cache (pgaf_nl_query_cache, 1-hour TTL, SHA-256 dedup)
  * Browser-based query interface at /platform/nl-analytics/
  * JSON API at /platform/nl-analytics/api/query

Events emitted
--------------
  platform.nl_analytics.query.executed
  platform.nl_analytics.query.cache_hit

Usage in app config::

    PGAPPFORGE_PLUGINS = [
        "pgappforge.plugins.erp.foundation",
        "pgappforge.plugins.erp.platform.nlp",
        "pgappforge.plugins.erp.platform.nl_analytics",
    ]
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class NLAnalyticsPlugin(BasePlugin):
	"""NL-to-SQL analytics plugin."""

	name = "nl_analytics"
	domain = "platform"
	depends_on: list[str] = ["foundation", "nlp"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="nl_analytics",
			version="1.0.0",
			description=(
				"Natural language analytics: type a plain-English question and get "
				"a PostgreSQL query + results.  Backed by LiteLLM proxy; degrades "
				"gracefully when the LLM is unavailable."
			),
			author="PgAppForge Contributors",
			tags=[
				"platform", "analytics", "ai", "nlp", "nl-to-sql",
				"llm", "sql", "bi",
			],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_ai_query_data",
				"can_view_nl_schema",
				"can_nl_analytics_index",
				"can_nl_analytics_api_query",
				"can_nl_analytics_schema",
			],
			safe_mode_compatible=True,
		)

	def get_events(self) -> list[str]:
		return [
			"platform.nl_analytics.query.executed",
			"platform.nl_analytics.query.cache_hit",
		]

	def subscribe_to(self) -> list[str]:
		return []

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"NL_ANALYTICS_ENABLED": True,
			"NL_ANALYTICS_MAX_ROWS": 500,
			# LLM config is shared with the NLP plugin
			"LITELLM_URL": "http://84.247.181.100:4000/v1",
			"LITELLM_API_KEY": "sk-pjs-litellm-master-key",
			"LLM_MODEL": "gpt-4o",
		}
		try:
			from flask import current_app
			for key, val in defaults.items():
				current_app.config.setdefault(key, val)
		except RuntimeError:
			pass
		self.config = {**defaults, **self.config}
		log.info("NLAnalyticsPlugin initialised")

	def post_initialize(self) -> None:
		"""Ensure pgaf_nl_query_cache table exists."""
		super().post_initialize()
		self._ensure_cache_table()

	def _ensure_cache_table(self) -> None:
		try:
			from flask import current_app
			from pgappforge.plugins.erp.platform.nl_analytics.services import ensure_cache_table
			session = current_app.appbuilder.get_session()
			ensure_cache_table(session)
		except Exception as exc:
			log.debug("NLAnalyticsPlugin: cache table ensure skipped — %s", exc)

	def register_views(self) -> None:
		from pgappforge.plugins.erp.platform.nl_analytics.views import NLAnalyticsDashboardView
		cat = self.config.get("NL_ANALYTICS_MENU_CATEGORY", "Analytics")
		self.add_view(
			NLAnalyticsDashboardView,
			"NL Analytics",
			icon="fa-magic",
			category=cat,
		)
		log.info("NLAnalyticsPlugin: view registered under %r", cat)

	def register_models(self) -> list[type]:
		# No ORM models — cache table is managed via raw DDL (see services.py)
		return []


def create_plugin(
	appbuilder: Any,
	config: dict[str, Any] | None = None,
) -> NLAnalyticsPlugin:
	return NLAnalyticsPlugin(appbuilder, config=config or {})


from pgappforge.plugins.erp.platform.nl_analytics.services import (  # noqa: E402
	NLAnalyticsService,
	create_cache_table_ddl,
	ensure_cache_table,
)
from pgappforge.plugins.erp.platform.nl_analytics.views import (  # noqa: E402
	NLAnalyticsDashboardView,
)

__all__ = [
	"NLAnalyticsPlugin",
	"create_plugin",
	"NLAnalyticsService",
	"NLAnalyticsDashboardView",
	"create_cache_table_ddl",
	"ensure_cache_table",
]
