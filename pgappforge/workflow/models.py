"""
pgappforge/workflow/models.py

Workflow instance data models.

These are plain Python dataclasses (not SQLAlchemy models) used as in-memory
state by PgAppForgeWorkflowEngine.  Persistence to PostgreSQL is handled by
raw SQL in the engine (create_workflow_tables).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class WorkflowDefinition:
	"""A parsed workflow definition (from YAML or dict)."""

	name: str
	steps: list[dict[str, Any]]
	trigger: dict[str, Any] = field(default_factory=dict)
	description: str = ""
	yaml_source: str = ""
	on_complete: dict[str, Any] = field(default_factory=dict)
	on_decline: dict[str, Any] = field(default_factory=dict)
	on_error: dict[str, Any] = field(default_factory=dict)

	def __post_init__(self) -> None:
		if not self.name:
			raise ValueError("WorkflowDefinition.name must not be empty")
		if not isinstance(self.steps, list):
			raise TypeError("WorkflowDefinition.steps must be a list")

	def step_by_id(self, step_id: str) -> dict[str, Any] | None:
		for s in self.steps:
			if s.get("id") == step_id:
				return s
		return None

	def __repr__(self) -> str:
		return f"WorkflowDefinition(name={self.name!r}, steps={len(self.steps)})"


@dataclass
class WorkflowInstance:
	"""A running instance of a workflow."""

	definition: WorkflowDefinition
	data: dict[str, Any]
	tenant_id: str
	id: str = field(default_factory=lambda: str(uuid.uuid4()))
	current_step_index: int = 0
	# RUNNING | WAITING | COMPLETED | CANCELLED | FAILED
	status: str = "RUNNING"
	created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
	step_history: list[dict[str, Any]] = field(default_factory=list)

	def current_step(self) -> dict[str, Any] | None:
		"""Return the step dict at current_step_index, or None if exhausted."""
		if self.current_step_index < len(self.definition.steps):
			return self.definition.steps[self.current_step_index]
		return None

	def is_terminal(self) -> bool:
		return self.status in ("COMPLETED", "CANCELLED", "FAILED")

	def __repr__(self) -> str:
		return (
			f"WorkflowInstance(id={self.id[:8]!r}, "
			f"workflow={self.definition.name!r}, "
			f"status={self.status!r}, "
			f"step={self.current_step_index})"
		)


__all__ = ["WorkflowDefinition", "WorkflowInstance"]
