"""
pgappforge/plugins/erp/finance/period_close/models.py

SQLAlchemy 2.x models for Period Close Checklist.

Table prefix: pc_
  pc_template  — reusable close checklists (12 standard tasks seeded)
  pc_close     — a specific period-close run for a tenant/entity/period
  pc_task      — individual task instances within a close run
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship, Mapped, mapped_column

from pgappforge.models.sqla import Model


class PeriodCloseTemplate(Model):
	"""Reusable close checklist template.

	tasks column schema (JSONB array):
	  [{
	    "task_code": str,
	    "title": str,
	    "is_mandatory": bool,
	    "owner_role": str | null,
	    "depends_on": [task_code, ...],
	    "description": str | null
	  }]
	"""
	__tablename__ = "pc_template"
	__table_args__ = (
		sa.Index("ix_pc_template_tenant_default", "tenant_id", "is_default"),
	)

	id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
	tenant_id: Mapped[str | None] = mapped_column(sa.String(50), nullable=True, index=True)

	name: Mapped[str] = mapped_column(sa.String(200), nullable=False)
	description: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
	is_default: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False)
	tasks: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

	closes: Mapped[list[PeriodClose]] = relationship(
		"PeriodClose",
		back_populates="template",
		foreign_keys="PeriodClose.template_id",
	)

	def __repr__(self) -> str:
		return f"<PeriodCloseTemplate {self.name!r} default={self.is_default}>"


class PeriodClose(Model):
	"""A period-close run for a specific tenant/entity/period combination.

	status lifecycle: OPEN → IN_PROGRESS → CLOSED
	"""
	__tablename__ = "pc_close"
	__table_args__ = (
		sa.UniqueConstraint("tenant_id", "period", "entity_id", name="uq_pc_close_tenant_period_entity"),
		sa.Index("ix_pc_close_tenant_status_period", "tenant_id", "status", "period"),
	)

	id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
	tenant_id: Mapped[str | None] = mapped_column(sa.String(50), nullable=True, index=True)

	period: Mapped[str] = mapped_column(sa.String(20), nullable=False)
	entity_id: Mapped[str | None] = mapped_column(sa.String(50), nullable=True)
	template_id: Mapped[str | None] = mapped_column(
		sa.String(36),
		sa.ForeignKey("pc_template.id", ondelete="SET NULL"),
		nullable=True,
	)
	status: Mapped[str] = mapped_column(sa.String(20), nullable=False, default="OPEN")

	started_at: Mapped[sa.DateTime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
	closed_at: Mapped[sa.DateTime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
	started_by: Mapped[str | None] = mapped_column(sa.String(50), nullable=True)
	closed_by: Mapped[str | None] = mapped_column(sa.String(50), nullable=True)

	template: Mapped[PeriodCloseTemplate | None] = relationship(
		"PeriodCloseTemplate",
		back_populates="closes",
		foreign_keys=[template_id],
	)
	tasks: Mapped[list[PeriodCloseTask]] = relationship(
		"PeriodCloseTask",
		back_populates="close",
		cascade="all, delete-orphan",
	)

	def __repr__(self) -> str:
		return f"<PeriodClose {self.period!r} entity={self.entity_id!r} status={self.status!r}>"


class PeriodCloseTask(Model):
	"""A single checklist task instance within a PeriodClose run.

	depends_on — JSONB list of task_code strings that must be COMPLETE/SKIPPED
	             before this task can advance to IN_PROGRESS.

	status lifecycle: PENDING → IN_PROGRESS → COMPLETE | SKIPPED
	"""
	__tablename__ = "pc_task"
	__table_args__ = (
		sa.Index("ix_pc_task_close_status", "close_id", "status"),
		sa.Index("ix_pc_task_close_code", "close_id", "task_code"),
	)

	id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
	tenant_id: Mapped[str | None] = mapped_column(sa.String(50), nullable=True)

	close_id: Mapped[str] = mapped_column(
		sa.String(36),
		sa.ForeignKey("pc_close.id", ondelete="CASCADE"),
		nullable=False,
	)
	task_code: Mapped[str] = mapped_column(sa.String(50), nullable=False)
	title: Mapped[str] = mapped_column(sa.String(300), nullable=False)
	is_mandatory: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=True)
	owner_role: Mapped[str | None] = mapped_column(sa.String(100), nullable=True)
	depends_on: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

	status: Mapped[str] = mapped_column(sa.String(20), nullable=False, default="PENDING")
	owner_id: Mapped[str | None] = mapped_column(sa.String(50), nullable=True)
	completed_at: Mapped[sa.DateTime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
	notes: Mapped[str | None] = mapped_column(sa.Text, nullable=True)

	close: Mapped[PeriodClose] = relationship("PeriodClose", back_populates="tasks")

	def __repr__(self) -> str:
		return f"<PeriodCloseTask {self.task_code!r} status={self.status!r}>"


__all__ = [
	"PeriodCloseTemplate",
	"PeriodClose",
	"PeriodCloseTask",
]
