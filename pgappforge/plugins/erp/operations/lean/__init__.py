"""Lean / Kanban manufacturing plugin."""
from __future__ import annotations
from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority


class LeanPlugin(BasePlugin):
	name = "lean"
	domain = "operations"
	depends_on: list[str] = ["foundation"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="lean",
			version="1.0.0",
			description="Lean manufacturing — Kanban boards, WIP limits, pull signals, cycle time",
			author="PgAppForge Contributors",
			tags=["operations", "lean", "kanban", "manufacturing"],
			priority=PluginPriority.NORMAL,
		)

	def initialize(self) -> None: pass
	def get_events(self) -> list[str]: return ["ops.lean.pull_signal_triggered", "ops.lean.card_moved"]
	def subscribe_to(self) -> list[str]: return []
	def register_models(self) -> list: from pgappforge.plugins.erp.operations.lean import models; return [models.KanbanBoard, models.KanbanColumn, models.KanbanCard, models.PullSignal]
	def register_views(self) -> None: pass


__all__ = ["LeanPlugin"]
