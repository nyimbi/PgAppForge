"""
pgappforge/plugins/workflow/models.py

SQLAlchemy models for the BPM system.

Tables
------
bpm_process_definition  — authored workflow templates
bpm_process_step        — ordered steps within a definition
bpm_process_instance    — a running execution for a specific record
bpm_process_event       — every state change, handoff, comment, escalation
bpm_process_transition  — conditional edges between steps (XOR/AND gateways)
bpm_process_token       — parallel execution tokens (AND_SPLIT/AND_JOIN)
bpm_user_delegation     — out-of-office task delegation
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
	Boolean,
	Column,
	Date,
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

	# --- GAP 3: versioning ---
	version = Column(Integer, nullable=False, default=1)
	parent_definition_id = Column(
		Integer,
		ForeignKey("bpm_process_definition.id", ondelete="SET NULL"),
		nullable=True,
	)
	is_latest = Column(Boolean, nullable=False, default=True)

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

	# --- GAP 1: gateway type + timer columns ---
	step_type = Column(
		String(20),
		nullable=False,
		default="TASK",
		comment="TASK|AND_SPLIT|AND_JOIN|XOR_SPLIT|XOR_JOIN|TIMER|START|END",
	)
	auto_advance_hours = Column(
		Integer,
		nullable=True,
		comment="If set, auto-advance after this many hours (timer event)",
	)
	timer_action = Column(
		String(20),
		nullable=True,
		default="ADVANCE",
		comment="ADVANCE|REJECT|ESCALATE — what timer does on trigger",
	)
	role_expression = Column(
		String(256),
		nullable=True,
		comment="Python expression for dynamic role: e.g. record.requester.manager_role",
	)

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
	# --- GAP 3: snapshot definition version at start time ---
	definition_version = Column(
		Integer,
		nullable=False,
		default=1,
		comment="Snapshot of definition.version at start time",
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


class ProcessTransition(Model):
	"""
	A directed edge between two steps in a process definition.

	Supports conditional routing (XOR_SPLIT) and unconditional fan-out
	(AND_SPLIT).  ``conditions_json`` uses the same format as the rules engine
	so the same evaluator can be reused at runtime.
	"""

	__allow_unmapped__ = True
	__tablename__ = "bpm_process_transition"
	__table_args__ = (
		Index("ix_bpm_trans_definition", "definition_id"),
		Index("ix_bpm_trans_from_step", "from_step_id"),
		Index("ix_bpm_trans_to_step", "to_step_id"),
		{"extend_existing": True},
	)

	id            = Column(Integer, primary_key=True, autoincrement=True)
	definition_id = Column(
		Integer,
		ForeignKey("bpm_process_definition.id", ondelete="CASCADE"),
		nullable=False,
	)
	from_step_id  = Column(
		Integer,
		ForeignKey("bpm_process_step.id", ondelete="CASCADE"),
		nullable=True,
	)
	to_step_id    = Column(
		Integer,
		ForeignKey("bpm_process_step.id", ondelete="SET NULL"),
		nullable=True,
	)
	# human-readable label, e.g. "Amount > 1M" or "Approved"
	label: str | None = Column(String(128), nullable=True)
	# same condition format as rules engine — list of condition dicts
	conditions_json: list[dict[str, Any]] = Column(JSONB, nullable=False, default=list)
	# lower value fires first for XOR_SPLIT evaluation order
	priority      = Column(Integer, nullable=False, default=0)
	# fallback when no condition matches (XOR_SPLIT)
	is_default    = Column(Boolean, nullable=False, default=False)

	definition: ProcessDefinition = relationship("ProcessDefinition")
	from_step: ProcessStep | None = relationship(
		"ProcessStep", foreign_keys=[from_step_id], lazy="joined"
	)
	to_step: ProcessStep | None = relationship(
		"ProcessStep", foreign_keys=[to_step_id], lazy="joined"
	)

	def __repr__(self) -> str:
		return (
			f"<ProcessTransition #{self.id} "
			f"from={self.from_step_id} to={self.to_step_id} "
			f"priority={self.priority} default={self.is_default}>"
		)


class ProcessToken(Model):
	"""
	One parallel branch of execution within a process instance.

	When an AND_SPLIT fires, one token per outgoing branch is created.
	An AND_JOIN gate waits until every token for the join step is in
	``completed`` state before advancing the instance.
	"""

	__allow_unmapped__ = True
	__tablename__ = "bpm_process_token"
	__table_args__ = (
		Index("ix_bpm_token_instance_status", "instance_id", "status"),
		Index("ix_bpm_token_step", "step_id"),
		{"extend_existing": True},
	)

	id           = Column(Integer, primary_key=True, autoincrement=True)
	instance_id  = Column(
		Integer,
		ForeignKey("bpm_process_instance.id", ondelete="CASCADE"),
		nullable=False,
	)
	step_id      = Column(
		Integer,
		ForeignKey("bpm_process_step.id", ondelete="SET NULL"),
		nullable=True,
	)
	# active | completed | cancelled
	status       = Column(String(20), nullable=False, default="active")
	created_at   = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
	completed_at = Column(DateTime(timezone=True), nullable=True)

	instance: ProcessInstance = relationship("ProcessInstance")
	step: ProcessStep | None  = relationship("ProcessStep", foreign_keys=[step_id])

	def __repr__(self) -> str:
		return (
			f"<ProcessToken #{self.id} instance={self.instance_id} "
			f"step={self.step_id} status={self.status!r}>"
		)


class UserDelegation(Model):
	"""
	Out-of-office / authority delegation: tasks assigned to *delegator*
	are also visible and actionable by *delegate* during the active period.

	``roles_included`` — empty list means delegate ALL roles; non-empty list
	restricts delegation to those specific FAB role names.
	"""

	__allow_unmapped__ = True
	__tablename__ = "bpm_user_delegation"
	__table_args__ = (
		Index("ix_bpm_deleg_delegator_active", "delegator_id", "is_active"),
		Index("ix_bpm_deleg_delegate_active", "delegate_id", "is_active"),
		{"extend_existing": True},
	)

	id           = Column(Integer, primary_key=True, autoincrement=True)
	delegator_id = Column(
		Integer,
		ForeignKey("ab_user.id", ondelete="SET NULL"),
		nullable=True,
		comment="User who is delegating their tasks",
	)
	delegate_id  = Column(
		Integer,
		ForeignKey("ab_user.id", ondelete="SET NULL"),
		nullable=True,
		comment="User who receives the delegated tasks",
	)
	start_date   = Column(Date, nullable=False)
	end_date     = Column(Date, nullable=True, comment="None = indefinite delegation")
	is_active    = Column(Boolean, nullable=False, default=True)
	reason       = Column(Text, nullable=True)
	# empty = delegate ALL roles; non-empty = only these FAB role names
	roles_included: list[str] = Column(JSONB, nullable=False, default=list)
	created_at   = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

	def __repr__(self) -> str:
		return (
			f"<UserDelegation #{self.id} "
			f"delegator={self.delegator_id} delegate={self.delegate_id} "
			f"active={self.is_active}>"
		)


__all__ = [
	"ProcessDefinition",
	"ProcessStep",
	"ProcessInstance",
	"ProcessEvent",
	"ProcessTransition",
	"ProcessToken",
	"UserDelegation",
]
