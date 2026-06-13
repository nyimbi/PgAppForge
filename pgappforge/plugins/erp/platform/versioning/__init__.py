"""
pgappforge/plugins/erp/platform/versioning/__init__.py

VersioningPlugin — Git-backed configuration versioning UI for PgAppForge.

Domain:   platform
Depends:  (none — optional gitpython at runtime)

Provides a visual git history browser for configuration files:
  custom_fields/*.yaml, workflows/*.yaml, pgappforge.yaml, semantic.yaml

Routes registered
-----------------
  GET  /platform/versioning/          — dashboard
  GET  /platform/versioning/diff      — JSON diff between two SHAs
  GET  /platform/versioning/file      — file content at a SHA
  POST /platform/versioning/revert    — admin-only revert to SHA

Config keys
-----------
  VERSIONING_REPO_PATH   str   — filesystem path to the git repo (default: cwd)
  VERSIONING_MENU_CATEGORY str — FAB menu category (default: "Platform")
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class VersioningPlugin(BasePlugin):
	"""Git-backed configuration versioning UI plugin.

	Shows a visual timeline of changes to configuration YAML files with
	inline diffs, per-file history, and one-click revert capability for
	admins.  Requires GitPython (``pip install gitpython``); degrades
	gracefully when the package is absent.
	"""

	name = "versioning"
	domain = "platform"
	depends_on: list[str] = []

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="versioning",
			version="1.0.0",
			description=(
				"Git-backed configuration versioning — visual history, inline diffs, "
				"and one-click revert for custom_fields, workflows, and environment YAML."
			),
			author="PgAppForge Contributors",
			tags=["platform", "versioning", "git", "config", "audit", "history"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_versioning_view",
				"can_versioning_diff",
				"can_versioning_revert",
			],
			safe_mode_compatible=True,
		)

	def get_events(self) -> list[str]:
		return []

	def subscribe_to(self) -> list[str]:
		return []

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"VERSIONING_REPO_PATH": ".",
			"VERSIONING_MENU_CATEGORY": "Platform",
		}
		self.config = {**defaults, **self.config}
		log.info("VersioningPlugin initialised (repo: %s)", self.config["VERSIONING_REPO_PATH"])

	def register_views(self) -> None:
		from pgappforge.plugins.erp.platform.versioning.views import VersioningDashboardView

		cat = self.config.get("VERSIONING_MENU_CATEGORY", "Platform")
		self.add_view(
			VersioningDashboardView,
			"Config Versioning",
			icon="fa-code-fork",
			category=cat,
		)
		log.info("VersioningPlugin: views registered under %r", cat)

	def register_models(self) -> list:
		# No database models — all data comes from git
		return []


def create_plugin(
	appbuilder: Any,
	config: dict[str, Any] | None = None,
) -> VersioningPlugin:
	"""Factory for plugin loader."""
	return VersioningPlugin(appbuilder, config=config or {})


from pgappforge.plugins.erp.platform.versioning.services import VersioningService  # noqa: E402
from pgappforge.plugins.erp.platform.versioning.views import VersioningDashboardView  # noqa: E402

__all__ = [
	"VersioningPlugin",
	"create_plugin",
	"VersioningService",
	"VersioningDashboardView",
]
