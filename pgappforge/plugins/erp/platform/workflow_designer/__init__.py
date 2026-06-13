"""
pgappforge/plugins/erp/platform/workflow_designer/__init__.py

Workflow Designer plugin — Phase 2 of the PgAppForge workflow engine.

Provides a visual drag-and-drop BPMN-lite designer (Drawflow, MIT) and a
task inbox for reviewing/completing pending workflow steps.

Phase 1 (YAML DSL + engine) lives at pgappforge/workflow/.
This phase adds the UI layer on top.
"""
from __future__ import annotations

import logging

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

from .views import WorkflowDesignerView

log = logging.getLogger(__name__)

_MENU_CATEGORY = "Workflow"


class WorkflowDesignerPlugin(BasePlugin):
	"""Visual workflow designer — drag-and-drop canvas + task inbox."""

	name	   = "workflow_designer"
	domain	   = "platform"
	depends_on: list[str] = ["foundation"]

	metadata = PluginMetadata(
		name="workflow_designer",
		version="2.0.0",
		description=(
			"Visual drag-and-drop workflow designer (Phase 2). "
			"Drawflow canvas, YAML save/load, task inbox with SLA timers."
		),
		author="PgAppForge Contributors",
		tags=["platform", "workflow", "bpmn", "designer", "tasks"],
		priority=PluginPriority.NORMAL,
	)

	def get_events(self) -> list[str]:
		return [
			"workflow.designer.saved",
			"workflow.designer.instance.started",
		]

	def subscribe_to(self) -> list[str]:
		return []

	def initialize(self, app=None) -> None:
		log.info("WorkflowDesignerPlugin initialised")

	def register_views(self) -> None:
		cat = self.config.get("WORKFLOW_MENU_CATEGORY", _MENU_CATEGORY)
		self.add_view(
			WorkflowDesignerView,
			"Workflow Designer",
			icon="fa-sitemap",
			category=cat,
		)
		# Task inbox — registered as a separate menu entry under same category
		# (same view class, different method exposed via route)
		log.info("WorkflowDesignerPlugin: views registered under %r", cat)

	def register_models(self) -> list[type]:
		# Persistence tables are raw SQL created by create_workflow_tables()
		# in pgappforge.workflow.engine — no SQLAlchemy models to register here.
		return []


__all__ = ["WorkflowDesignerPlugin", "WorkflowDesignerView"]
