"""
pgappforge/plugins/erp/platform/__init__.py

Platform domain — top-level package for platform sub-plugins.
Sub-plugins: events, identity, social, credentials
"""
from __future__ import annotations

import logging

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class PlatformGlobalSearchPlugin(BasePlugin):
	"""Register cross-ERP global search views."""

	name = "global_search"
	domain = "platform"
	depends_on: list[str] = ["foundation"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="global_search",
			version="1.0.0",
			description="Global ERP search across projects, risks, invoices, suppliers, employees, and opportunities.",
			author="PgAppForge Contributors",
			tags=["erp", "platform", "search"],
			priority=PluginPriority.NORMAL,
			permissions=["can_erp_global_search"],
			safe_mode_compatible=True,
		)

	def initialize(self) -> None:
		self.config = {"GLOBAL_SEARCH_MENU_CATEGORY": "Platform", **self.config}
		log.info("PlatformGlobalSearchPlugin initialised")

	def register_views(self) -> None:
		from pgappforge.plugins.erp.platform.global_search import GlobalSearchView
		cat = self.config.get("GLOBAL_SEARCH_MENU_CATEGORY", "Platform")
		self.add_view(GlobalSearchView, "Global Search", icon="fa-search", category=cat)
		log.info("PlatformGlobalSearchPlugin: views registered under category %r", cat)

	def register_models(self) -> list:
		return []

	def get_events(self) -> list[str]:
		return []

	def subscribe_to(self) -> list[str]:
		return []


__all__ = ["PlatformGlobalSearchPlugin"]
