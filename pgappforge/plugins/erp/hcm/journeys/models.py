"""
pgappforge/plugins/erp/hcm/journeys/models.py

SQLAlchemy models for the HCM Employee Journeys plugin.

Design invariants:
  - ALL PKs: UUID v4 — gen_random_uuid() server default
  - ALL timestamps: DateTime(timezone=True) / TIMESTAMPTZ DEFAULT NOW()
  - ALL models: tenant_id NOT NULL + AuditMixin
  - tasks JSONB column stores template task definitions (not normalised rows)
    — allows flexible per-template task shapes without schema migration
  - depends_on JSONB: list of task_codes that must complete before this task
    becomes IN_PROGRESS
  - lazy='select' throughout (SA 2.x)
  - Composite indexes for tenant + status hot paths

Table prefix: jrn_
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy import (
	Boolean,
	Column,
	Date,
	DateTime,
	ForeignKey,
	Index,
	String,
	Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from pgappforge.models.sqla import Model
from pgappforge.plugins.audit import AuditMixin


def _uuid4() -> str:
	return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# JourneyTemplate
# ---------------------------------------------------------------------------

class JourneyTemplate(AuditMixin, Model):
	"""Reusable template defining tasks for a journey type.

	tasks JSONB format:
	  [{
	    "task_code": str,
	    "title": str,
	    "owner_role": str,       # HR | IT_ADMIN | MANAGER | PAYROLL | FACILITIES | COMPLIANCE
	    "due_days_offset": int,  # days from journey trigger_date
	    "category": str,         # HR | IT | FINANCE | MANAGER | COMPLIANCE
	    "is_mandatory": bool,
	    "depends_on": [str],     # list of task_codes; [] = immediately IN_PROGRESS
	  }, ...]

	is_default: if True, this template is auto-selected for journey_type when
	no template_id is passed to start_journey().
	Only one default per (tenant_id, journey_type).
	"""

	__allow_unmapped__ = True
	__tablename__ = "jrn_template"
	__table_args__ = (
		Index("ix_jrn_template_tenant_type_default", "tenant_id", "journey_type", "is_default"),
		Index("ix_jrn_template_tenant_active", "tenant_id", "is_active"),
		Index("ix_jrn_template_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	name = Column(String(200), nullable=False)
	journey_type = Column(
		String(30),
		nullable=False,
		comment="ONBOARDING | OFFBOARDING | TRANSFER | ROLE_CHANGE | PROMOTION",
	)
	description = Column(Text, nullable=True)
	is_default = Column(
		Boolean,
		nullable=False,
		default=False,
		comment="Auto-selected for this journey_type when no template_id supplied",
	)
	is_active = Column(Boolean, nullable=False, default=True)
	tasks = Column(
		JSONB,
		nullable=False,
		default=list,
		comment="[{task_code, title, owner_role, due_days_offset, category, is_mandatory, depends_on:[]}]",
	)
	metadata_ = Column("metadata", JSONB, nullable=False, default=dict)

	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	updated_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		onupdate=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	# Relationships
	journeys: list[Journey] = relationship(
		"Journey", back_populates="template", lazy="select"
	)

	def __repr__(self) -> str:
		return (
			f"<JourneyTemplate {self.name!r} type={self.journey_type!r} "
			f"default={self.is_default} active={self.is_active}>"
		)


# ---------------------------------------------------------------------------
# Journey
# ---------------------------------------------------------------------------

class Journey(AuditMixin, Model):
	"""Active employee journey instance.

	trigger_date: the date that anchors task due-date calculations
	  (e.g. hire date for ONBOARDING, last day for OFFBOARDING).

	Status machine:
	  ACTIVE → COMPLETED  (all mandatory tasks done)
	  ACTIVE → CANCELLED  (manually cancelled)
	"""

	__allow_unmapped__ = True
	__tablename__ = "jrn_journey"
	__table_args__ = (
		Index("ix_jrn_journey_tenant_employee_status", "tenant_id", "employee_id", "status"),
		Index("ix_jrn_journey_tenant_status", "tenant_id", "status"),
		Index("ix_jrn_journey_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	employee_id = Column(
		String(50),
		nullable=False,
		index=True,
		comment="Soft FK to HCM employee master",
	)
	template_id = Column(
		UUID(as_uuid=False),
		ForeignKey("jrn_template.id", ondelete="SET NULL"),
		nullable=True,
		index=True,
		comment="Template used to seed tasks; SET NULL on template deletion",
	)

	journey_type = Column(
		String(30),
		nullable=False,
		comment="ONBOARDING | OFFBOARDING | TRANSFER | ROLE_CHANGE | PROMOTION",
	)
	trigger_date = Column(
		Date,
		nullable=False,
		comment="Anchor date for task due-date offsets (e.g. hire date, last day)",
	)
	status = Column(
		String(20),
		nullable=False,
		default="ACTIVE",
		comment="ACTIVE | COMPLETED | CANCELLED",
	)
	completed_at = Column(DateTime(timezone=True), nullable=True)
	metadata_ = Column("metadata", JSONB, nullable=False, default=dict)

	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	updated_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		onupdate=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	# Relationships
	template: JourneyTemplate | None = relationship(
		"JourneyTemplate", back_populates="journeys", lazy="select"
	)
	tasks: list[JourneyTask] = relationship(
		"JourneyTask", back_populates="journey", cascade="all, delete-orphan", lazy="select"
	)

	def __repr__(self) -> str:
		return (
			f"<Journey employee={self.employee_id!r} "
			f"type={self.journey_type!r} status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# JourneyTask
# ---------------------------------------------------------------------------

class JourneyTask(AuditMixin, Model):
	"""Individual task within a journey instance.

	depends_on JSONB: list of task_codes.  A task becomes IN_PROGRESS only
	when all tasks in depends_on are COMPLETE or SKIPPED.

	owner_id: set to the actual user/employee who will execute the task
	(may differ from owner_role which is the role class).

	Status machine:
	  PENDING → IN_PROGRESS (when depends_on tasks all complete)
	  IN_PROGRESS → COMPLETE (complete_task())
	  IN_PROGRESS → SKIPPED  (skip_task() — only for is_mandatory=False)
	"""

	__allow_unmapped__ = True
	__tablename__ = "jrn_task"
	__table_args__ = (
		Index("ix_jrn_task_journey_status", "journey_id", "status"),
		Index("ix_jrn_task_journey_code", "journey_id", "task_code"),
		Index("ix_jrn_task_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	journey_id = Column(
		UUID(as_uuid=False),
		ForeignKey("jrn_journey.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)

	task_code = Column(String(50), nullable=False, comment="Short code matching template task definitions")
	title = Column(String(300), nullable=False)
	category = Column(
		String(100),
		nullable=True,
		comment="HR | IT | FINANCE | MANAGER | COMPLIANCE",
	)
	is_mandatory = Column(Boolean, nullable=False, default=True)
	owner_role = Column(String(100), nullable=True, comment="Role class responsible for this task")
	owner_id = Column(String(50), nullable=True, comment="Specific user assigned to complete this task")
	due_date = Column(Date, nullable=True, comment="trigger_date + due_days_offset from template")
	depends_on = Column(
		JSONB,
		nullable=False,
		default=list,
		comment="List of task_codes that must be COMPLETE/SKIPPED before this becomes IN_PROGRESS",
	)

	status = Column(
		String(20),
		nullable=False,
		default="PENDING",
		comment="PENDING | IN_PROGRESS | COMPLETE | SKIPPED",
	)
	completed_at = Column(DateTime(timezone=True), nullable=True)
	notes = Column(Text, nullable=True)
	metadata_ = Column("metadata", JSONB, nullable=False, default=dict)

	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	updated_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		onupdate=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	# Relationships
	journey: Journey = relationship("Journey", back_populates="tasks", lazy="select")

	def __repr__(self) -> str:
		return (
			f"<JourneyTask {self.task_code!r} journey={self.journey_id!r} "
			f"status={self.status!r} mandatory={self.is_mandatory}>"
		)


__all__ = [
	"JourneyTemplate",
	"Journey",
	"JourneyTask",
]
