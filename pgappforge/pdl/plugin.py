"""PDL platform plugin — registers the visual entity designer view."""
from __future__ import annotations

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority


class PDLPlugin(BasePlugin):
	"""PDL Visual Entity Designer — schema DSL + code generation UI."""

	name = "pdl"
	domain = "platform"
	depends_on: list[str] = ["foundation"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="pdl",
			version="1.0.0",
			description="PDL visual entity designer — draw schemas, import capability models, generate code",
			author="PgAppForge Contributors",
			tags=["platform", "pdl", "codegen", "designer", "developer_tools"],
			priority=PluginPriority.NORMAL,
		)

	def initialize(self) -> None:
		pass

	def get_events(self) -> list[str]:
		return []

	def subscribe_to(self) -> list[str]:
		return []

	def register_models(self) -> list:
		return []

	def register_views(self) -> None:
		from pgappforge.pdl.designer_view import PDLDesignerView
		self.add_view(
			PDLDesignerView,
			"Entity Designer",
			icon="fa-sitemap",
			category="Developer Tools",
		)


__all__ = ["PDLPlugin"]
