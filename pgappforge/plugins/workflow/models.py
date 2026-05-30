"""
pgappforge/plugins/workflow/models.py

SQLAlchemy models for the BPM system.

Tables
------
bpm_process_definition  — authored workflow templates
bpm_process_step        — ordered steps within a definition
bpm_process_instance    — a running execution for a specific record
bpm_process_event       — every state change, handoff, comment, escalation
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
	Boolean,
	Column,
	DateTime,
	ForeignKey,
	Index,
	Integer,
	String,
	Text,
	func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from pgappforge.models.sqla import Model

log = logging.getLogger(__name__)


class ProcessDefinition(Model):
	"""Defines a workflow: name, description, ordered steps, escalation config."""

	__allow_unmapped__ = True
	__tablename__ = "bpm_process_definition"
	__table_args__ = (
		Index("ix_bpm_procdef_name", "name"),
		Index("ix_bpm_procdef_active", "is_active"),
		{"extend_existing": True},
	)

	id          = Column(Integer, primary_key=True, autoincrement=True)
	name        = Column(String(128), nullable=False, unique=True)
	description = Column(Text, nullable=True)
	is_active   = Column(Boolean, nullable=False, default=True)
	# {escalation_hours, notify_emails, sla_hours, auto_complete_on_final_step, ...}
	config: dict[str, Any] = Column(JSONB, nullable=False, default=dict)
	created_at  = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
	created_by_id = Column(Integer, ForeignKey("ab_user.id"), nullable=True)

	steps: list[ProcessStep] = relationship(
		"ProcessStep",
		order_by="ProcessStep.order_num",
		back_populates="definition",
		cascade="all, delete-orphan",
		lazy="select",
	)
	instances: list[ProcessInstance] = relationship(
		"ProcessInstance",
		back_populates="definition",
		cascade="all, delete-orphan",
		lazy="select",
	)

	def __repr__(self) -> str:
		return f"<ProcessDefinition {self.name!r} active={self.is_active}>"

	@property
	def active_step_count(self) -> int:
		return len(self.steps)

	@property
	def escalation_hours(self) -> int:
		return self.config.get("escalation_hours", 24) if self.config else 24

	@property
	def notify_emails(self) -> list[str]:
		return self.config.get("notify_emails", []) if self.config else []


class ProcessStep(Model):
	"""One step in a process definition."""

	__allow_unmapped__ = True
	__tablename__ = "bpm_process_step"
	__table_args__ = (
		Index("ix_bpm_step_def", "definition_id"),
		Index("ix_bpm_step_order", "definition_id", "order_num"),
		{"extend_existing": True},
	)

	id               = Column(Integer, primary_key=True, autoincrement=True)
	definition_id    = Column(
		Integer, ForeignKey("bpm_process_definition.id", ondelete="CASCADE"), nullable=False
	)
	name             = Column(String(128), nullable=False)
	order_num        = Column(Integer, nullable=False)
	assigned_role    = Column(String(64), nullable=True)     # FAB role name
	timeout_hours    = Column(Integer, nullable=False, default=24)
	escalate_to_role = Column(String(64), nullable=True)     # role on timeout
	# {on_enter: ["notify_role", ...], on_exit: [...], is_final: bool, auto_advance: bool}
	actions: dict[str, Any] = Column(JSONB, nullable=False, default=dict)

	definition: ProcessDefinition = relationship("ProcessDefinition", back_populates="steps")

	def __repr__(self) -> str:
		return f"<ProcessStep #{self.order_num} {self.name!r} role={self.assigned_role!r}>"

	@property
	def is_final(self) -> bool:
		return bool(self.actions.get("is_final", False)) if self.actions else False

	@property
	def on_enter_actions(self) -> list[str]:
		return self.actions.get("on_enter", []) if self.actions else []

	@property
	def on_exit_actions(self) -> list[str]:
		return self.actions.get("on_exit", []) if self.actions else []


class ProcessInstance(Model):
	"""A running instance of a process for a specific record."""

	__allow_unmapped__ = True
	__tablename__ = "bpm_process_instance"
	__table_args__ = (
		Index("ix_bpm_inst_def", "definition_id"),
		Index("ix_bpm_inst_model_record", "model_name", "record_id"),
		Index("ix_bpm_inst_status", "status"),
		Index("ix_bpm_inst_current_step", "current_step_id"),
		{"extend_existing": True},
	)

	id              = Column(Integer, primary_key=True, autoincrement=True)
	definition_id   = Column(
		Integer, ForeignKey("bpm_process_definition.id", ondelete="CASCADE"), nullable=False
	)
	model_name      = Column(String(128), nullable=False)   # e.g. 'Invoice'
	record_id       = Column(Integer, nullable=False)
	current_step_id = Column(
		Integer, ForeignKey("bpm_process_step.id", ondelete="SET NULL"), nullable=True
	)
	# active | completed | cancelled | error
	status          = Column(String(32), nullable=False, default="active")
	started_at      = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
	completed_at    = Column(DateTime(timezone=True), nullable=True)
	started_by_id   = Column(Integer, ForeignKey("ab_user.id"), nullable=True)
	step_entered_at = Column(
		DateTime(timezone=True), nullable=True,
		comment="Timestamp when current_step_id was last set — used to compute age",
	)

	definition: ProcessDefinition = relationship("ProcessDefinition", back_populates="instances")
	current_step: ProcessStep | None = relationship("ProcessStep", foreign_keys=[current_step_id])
	history: list[ProcessEvent] = relationship(
		"ProcessEvent",
		back_populates="instance",
		order_by="ProcessEvent.occurred_at",
		cascade="all, delete-orphan",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<ProcessInstance #{self.id} {self.model_name}#{self.record_id} "
			f"status={self.status!r}>"
		)

	@property
	def hours_at_current_step(self) -> float:
		"""Elapsed hours since the instance entered the current step."""
		if self.step_entered_at is None:
			return 0.0
		entered = self.step_entered_at
		if entered.tzinfo is None:
			entered = entered.replace(tzinfo=timezone.utc)
		now = datetime.now(timezone.utc)
		return (now - entered).total_seconds() / 3600.0

	@property
	def is_overdue(self) -> bool:
		"""True when elapsed time at current step exceeds step.timeout_hours."""
		step = self.current_step
		if step is None:
			return False
		return self.hours_at_current_step > step.timeout_hours

	@property
	def total_elapsed_hours(self) -> float:
		started = self.started_at
		if started is None:
			return 0.0
		if started.tzinfo is None:
			started = started.replace(tzinfo=timezone.utc)
		end = self.completed_at or datetime.now(timezone.utc)
		if end.tzinfo is None:
			end = end.replace(tzinfo=timezone.utc)
		return (end - started).total_seconds() / 3600.0


class ProcessEvent(Model):
	"""Every state change, handoff, comment, escalation, or form-time record."""

	__allow_unmapped__ = True
	__tablename__ = "bpm_process_event"
	__table_args__ = (
		Index("ix_bpm_event_instance", "instance_id"),
		Index("ix_bpm_event_type", "event_type"),
		Index("ix_bpm_event_actor", "actor_id"),
		Index("ix_bpm_event_occurred", "occurred_at"),
		{"extend_existing": True},
	)

	id               = Column(Integer, primary_key=True, autoincrement=True)
	instance_id      = Column(
		Integer, ForeignKey("bpm_process_instance.id", ondelete="CASCADE"), nullable=False
	)
	# transition | comment | escalation | form_time | start | complete | reject | cancel
	event_type       = Column(String(32), nullable=False)
	from_step_id     = Column(
		Integer, ForeignKey("bpm_process_step.id", ondelete="SET NULL"), nullable=True
	)
	to_step_id       = Column(
		Integer, ForeignKey("bpm_process_step.id", ondelete="SET NULL"), nullable=True
	)
	actor_id         = Column(Integer, ForeignKey("ab_user.id"), nullable=True)
	comment          = Column(Text, nullable=True)
	# arbitrary event payload: diff snapshots, ML scores, form field values, etc.
	data: dict[str, Any] = Column(JSONB, nullable=False, default=dict)
	occurred_at      = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
	# For form_time events: seconds the user had the form open
	duration_seconds = Column(Integer, nullable=True)

	instance: ProcessInstance = relationship("ProcessInstance", back_populates="history")
	from_step: ProcessStep | None = relationship(
		"ProcessStep", foreign_keys=[from_step_id], lazy="joined"
	)
	to_step: ProcessStep | None = relationship(
		"ProcessStep", foreign_keys=[to_step_id], lazy="joined"
	)

	def __repr__(self) -> str:
		return (
			f"<ProcessEvent #{self.id} type={self.event_type!r} "
			f"instance={self.instance_id} actor={self.actor_id}>"
		)


__all__ = [
	"ProcessDefinition",
	"ProcessStep",
	"ProcessInstance",
	"ProcessEvent",
]
