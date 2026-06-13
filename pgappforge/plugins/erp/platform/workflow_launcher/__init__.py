"""
pgappforge/plugins/erp/platform/workflow_launcher/__init__.py

Workflow Launcher sub-plugin.

Exposes WorkflowLauncherView, which provides:
  GET  /platform/launch                                          — searchable grid of all workflows
  GET  /platform/launch/wizard/<capability>/<workflow_id>       — start/show a wizard
  GET  /platform/launch/wizard/<capability>/<workflow_id>/step/<step_id>  — render a step
  POST /platform/launch/wizard/<capability>/<workflow_id>/step/<step_id>  — validate + advance
"""
from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority
from pgappforge.plugins.erp.platform.workflow_launcher.views import WorkflowLauncherView


class WorkflowLauncherPlugin(BasePlugin):
	"""Workflow Launcher — searchable grid of all registered guided workflows."""

	name = "workflow_launcher"
	domain = "platform"
	depends_on: list[str] = ["foundation"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="workflow_launcher",
			version="1.0.0",
			description="Guided workflow launcher — browse, search, and start any registered workflow wizard",
			author="PgAppForge Contributors",
			tags=["workflow", "wizard", "ux", "guided"],
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
		from pgappforge.ui.capability_workflows import register_all_capability_workflows
		register_all_capability_workflows()
		cat = self.config.get("WORKFLOW_MENU_CATEGORY", "Workflows")
		self.add_view(WorkflowLauncherView, "All Workflows", icon="fa-magic", category=cat)


__all__ = ["WorkflowLauncherPlugin", "WorkflowLauncherView"]
