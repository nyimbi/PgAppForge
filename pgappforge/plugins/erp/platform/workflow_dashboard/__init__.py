"""
pgappforge/plugins/erp/platform/workflow_dashboard

Cross-domain workflow status dashboards for P2P and O2C.
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority
from pgappforge.plugins.erp.platform.workflow_dashboard.views import OTCStatusView, PTPStatusView

log = logging.getLogger(__name__)


class WorkflowDashboardPlugin(BasePlugin):
	"""Platform workflow dashboard plugin."""

	name = "workflow_dashboard"
	domain = "platform"
	depends_on: list[str] = ["foundation"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="workflow_dashboard",
			version="1.0.0",
			description="Cross-domain P2P and O2C workflow status dashboards.",
			author="PgAppForge Contributors",
			tags=["erp", "platform", "workflow", "p2p", "o2c"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_workflow_dashboard_ptp",
				"can_workflow_dashboard_otc",
			],
			safe_mode_compatible=True,
		)

	def register_views(self) -> None:
		register_views(self.appbuilder, category=self.config.get("WORKFLOW_DASHBOARD_MENU_CATEGORY", "Workflow Status"))


def register_views(appbuilder: Any, category: str = "Workflow Status") -> None:
	appbuilder.add_view(PTPStatusView, "P2P Status", icon="fa-random", category=category)
	appbuilder.add_view(OTCStatusView, "O2C Status", icon="fa-exchange", category=category)
	log.info("WorkflowDashboardPlugin: views registered under %r", category)


def create_plugin(appbuilder: Any, config: dict[str, Any] | None = None) -> WorkflowDashboardPlugin:
	return WorkflowDashboardPlugin(appbuilder, config=config or {})


__all__ = [
	"WorkflowDashboardPlugin",
	"create_plugin",
	"register_views",
	"PTPStatusView",
	"OTCStatusView",
]
