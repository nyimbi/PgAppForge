"""
project_mixin.py

Enterprise-grade project management mixin for PgAppForge models.

Provides a full project lifecycle system with Gantt chart generation, team
assignment, deliverable tracking, equipment inventory, and structured step
sequencing — all via dynamically created per-model satellite tables.

Author: Nyimbi Odero
Date: 2026-05-30
Version: 2.0
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from pgappforge import Model
from pgappforge.models.mixins import AuditMixin
from sqlalchemy import (
	JSON,
	Column,
	DateTime,
	Float,
	ForeignKey,
	Index,
	Integer,
	String,
	Table,
	Text,
	select,
)
from sqlalchemy.sql import func

try:
	from sqlalchemy.orm import declared_attr, relationship
except ImportError:
	from sqlalchemy.ext.declarative import declared_attr  # type: ignore[no-redef]
	from sqlalchemy.orm import relationship  # type: ignore[no-redef]

try:
	from sqlalchemy.ext.hybrid import hybrid_property
except ImportError:
	# Fallback: make hybrid_property a plain property decorator
	hybrid_property = property  # type: ignore[assignment,misc]

# PostgreSQL-specific types with fallback to portable equivalents
try:
	from sqlalchemy.dialects.postgresql import ARRAY, JSONB

	def _jsonb_col(**kw: Any) -> Column:
		"""JSONB on PostgreSQL, JSON elsewhere."""
		from sqlalchemy import JSON as _JSON
		from sqlalchemy.types import TypeDecorator

		class _PortableJSONB(TypeDecorator):
			impl = JSONB
			cache_ok = True

			def load_dialect_impl(self, dialect):
				if dialect.name == "postgresql":
					return dialect.type_descriptor(JSONB())
				return dialect.type_descriptor(_JSON())

		return Column(_PortableJSONB, **kw)

	def _array_col(inner_type: Any, **kw: Any) -> Column:
		"""ARRAY on PostgreSQL, JSON-as-list elsewhere."""
		from sqlalchemy import JSON as _JSON
		from sqlalchemy.types import TypeDecorator

		class _PortableArray(TypeDecorator):
			impl = ARRAY(inner_type)
			cache_ok = True

			def load_dialect_impl(self, dialect):
				if dialect.name == "postgresql":
					return dialect.type_descriptor(ARRAY(inner_type))
				return dialect.type_descriptor(_JSON())

		return Column(_PortableArray, **kw)

except ImportError:
	# Non-PostgreSQL environment
	ARRAY = None  # type: ignore[assignment]
	JSONB = None  # type: ignore[assignment]

	def _jsonb_col(**kw: Any) -> Column:
		return Column(JSON, **kw)

	def _array_col(inner_type: Any, **kw: Any) -> Column:
		return Column(JSON, **kw)


logger = logging.getLogger(__name__)


class ProjectMixin:
	"""
	ProjectMixin: enterprise project management for PgAppForge models.

	Attaches five satellite tables to whatever model class uses this mixin:

	- ``nx_pj_{tablename}_projects``      — the project header
	- ``nx_pj_{tablename}_steps``         — ordered work steps / schedule bars
	- ``nx_pj_{tablename}_deliverables``  — milestone/acceptance items
	- ``nx_pj_{tablename}_equipment``     — physical or virtual resources
	- ``nx_pj_{tablename}_assignments``   — user ↔ project role bindings
	- ``nx_pj_{tablename}_project_equipment`` — M2M equipment allocation

	All satellite classes are stored on the mixin subclass as class attributes
	(``cls.Project``, ``cls.ProjectStep``, etc.) so they are directly accessible
	from anywhere that holds a reference to the host model class.

	Usage::

		class MyItem(ProjectMixin, Model):
			__tablename__ = "my_items"
			id = Column(Integer, primary_key=True)
			name = Column(String(50), nullable=False)

		# Gantt Mermaid string for project 3
		mermaid_str = MyItem.render_mermaid(3)

		# Assign a user
		assignment = MyItem.assign_user_to_project(
			project_id=3, user_id=7, role="Lead", start_date=datetime.now()
		)
	"""

	# ------------------------------------------------------------------
	# Subclass hook — wire up satellite tables on first subclass creation
	# ------------------------------------------------------------------

	@classmethod
	def __init_subclass__(cls, **kwargs: Any) -> None:
		super().__init_subclass__(**kwargs)
		# Only create tables for concrete model classes that declare __tablename__
		if hasattr(cls, "__tablename__") and not cls.__dict__.get("_project_tables_created"):
			cls._project_tables_created = True
			cls.create_project_tables()

	# ------------------------------------------------------------------
	# Satellite table factory
	# ------------------------------------------------------------------

	@classmethod
	def create_project_tables(cls) -> None:
		"""Dynamically build and attach the five satellite ORM classes."""

		tn = cls.__tablename__  # host table name used as namespace

		# ------------------------------------------------------------------ #
		# Project                                                              #
		# ------------------------------------------------------------------ #
		class Project(Model, AuditMixin):
			__tablename__ = f"nx_pj_{tn}_projects"
			__table_args__ = (
				Index(f"idx_{tn}_project_status", "status"),
				Index(f"idx_{tn}_project_dates", "start_date", "end_date"),
			)

			id = Column(Integer, primary_key=True)
			name = Column(String(100), nullable=False)
			description = Column(Text)
			start_date = Column(DateTime, default=func.now(), nullable=False)
			end_date = Column(DateTime)
			status = Column(String(50), default="Planning")
			priority = Column(Integer, default=1)
			budget = Column(Float, default=0.0)
			project_metadata = _jsonb_col(default=dict)
			tags = _array_col(String(50), default=list)

			@hybrid_property
			def duration(self) -> int | None:
				if self.end_date and self.start_date:
					return (self.end_date - self.start_date).days
				return None

			@hybrid_property
			def is_active(self) -> bool:
				return self.status not in ("Completed", "Cancelled")

			def __repr__(self) -> str:
				return f"<Project {self.name}>"

		# ------------------------------------------------------------------ #
		# ProjectStep                                                          #
		# ------------------------------------------------------------------ #
		class ProjectStep(Model, AuditMixin):
			__tablename__ = f"nx_pj_{tn}_steps"
			__table_args__ = (
				Index(f"idx_{tn}_step_project", "project_id"),
				Index(f"idx_{tn}_step_dates", "start_date", "end_date"),
			)

			id = Column(Integer, primary_key=True)
			project_id = Column(
				Integer,
				ForeignKey(f"{Project.__tablename__}.id", ondelete="CASCADE"),
				nullable=False,
			)
			name = Column(String(100), nullable=False)
			description = Column(Text)
			sequence = Column(Integer)
			start_date = Column(DateTime)
			end_date = Column(DateTime)
			early_start = Column(DateTime)
			late_end = Column(DateTime)
			status = Column(String(50), default="Not Started")
			# stored as JSON list of step IDs on non-PG backends
			dependencies = _array_col(Integer, default=list)
			completion_percentage = Column(Float, default=0.0)
			step_metadata = _jsonb_col(default=dict)

			project = relationship(
				"Project",
				foreign_keys=[project_id],
				backref=f"{tn}_steps",
			)

			@hybrid_property
			def duration(self) -> int | None:
				if self.end_date and self.start_date:
					return (self.end_date - self.start_date).days
				return None

			def __repr__(self) -> str:
				return f"<ProjectStep {self.name}>"

		# ------------------------------------------------------------------ #
		# Deliverable                                                          #
		# ------------------------------------------------------------------ #
		class Deliverable(Model, AuditMixin):
			__tablename__ = f"nx_pj_{tn}_deliverables"
			__table_args__ = (
				Index(f"idx_{tn}_deliverable_project", "project_id"),
				Index(f"idx_{tn}_deliverable_status", "status"),
			)

			id = Column(Integer, primary_key=True)
			project_id = Column(
				Integer,
				ForeignKey(f"{Project.__tablename__}.id", ondelete="CASCADE"),
				nullable=False,
			)
			name = Column(String(100), nullable=False)
			description = Column(Text)
			due_date = Column(DateTime, nullable=False)
			status = Column(String(50), default="Pending")
			priority = Column(Integer, default=1)
			acceptance_criteria = Column(Text)
			review_status = Column(String(50))
			deliverable_metadata = _jsonb_col(default=dict)

			project = relationship(
				"Project",
				foreign_keys=[project_id],
				backref=f"{tn}_deliverables",
			)

			def __repr__(self) -> str:
				return f"<Deliverable {self.name}>"

		# ------------------------------------------------------------------ #
		# Equipment                                                            #
		# ------------------------------------------------------------------ #
		class Equipment(Model, AuditMixin):
			__tablename__ = f"nx_pj_{tn}_equipment"

			id = Column(Integer, primary_key=True)
			name = Column(String(100), nullable=False)
			description = Column(Text)
			quantity = Column(Integer, default=1)
			availability_status = Column(String(50), default="Available")
			maintenance_schedule = _jsonb_col(default=dict)
			last_maintenance = Column(DateTime)
			next_maintenance = Column(DateTime)
			specifications = _jsonb_col(default=dict)
			location = Column(String(100))
			equipment_metadata = _jsonb_col(default=dict)

			def __repr__(self) -> str:
				return f"<Equipment {self.name}>"

		# ------------------------------------------------------------------ #
		# Association table: Project ↔ Equipment                              #
		# ------------------------------------------------------------------ #
		project_equipment_table = Table(
			f"nx_pj_{tn}_project_equipment",
			Model.metadata,
			Column(
				"project_id",
				Integer,
				ForeignKey(f"{Project.__tablename__}.id", ondelete="CASCADE"),
				primary_key=True,
			),
			Column(
				"equipment_id",
				Integer,
				ForeignKey(f"{Equipment.__tablename__}.id", ondelete="CASCADE"),
				primary_key=True,
			),
			Column("quantity_required", Integer, default=1),
			Column("allocation_start", DateTime),
			Column("allocation_end", DateTime),
			Column("status", String(50)),
			Column("notes", Text),
			Index(f"idx_{tn}_pe_project", "project_id"),
			Index(f"idx_{tn}_pe_equipment", "equipment_id"),
		)

		# Wire the M2M relationship now that the association table exists
		Project.equipment = relationship(
			Equipment,
			secondary=project_equipment_table,
			backref=f"{tn}_projects",
			lazy="select",
		)

		# ------------------------------------------------------------------ #
		# ProjectAssignment                                                    #
		# ------------------------------------------------------------------ #
		class ProjectAssignment(Model, AuditMixin):
			__tablename__ = f"nx_pj_{tn}_assignments"
			__table_args__ = (
				Index(f"idx_{tn}_assignment_project", "project_id"),
				Index(f"idx_{tn}_assignment_user", "user_id"),
			)

			id = Column(Integer, primary_key=True)
			project_id = Column(
				Integer,
				ForeignKey(f"{Project.__tablename__}.id", ondelete="CASCADE"),
				nullable=False,
			)
			user_id = Column(Integer, ForeignKey("ab_user.id"), nullable=False)
			role = Column(String(50), nullable=False)
			start_date = Column(DateTime, nullable=False)
			end_date = Column(DateTime)
			hours_allocated = Column(Float, default=0.0)
			hours_used = Column(Float, default=0.0)
			status = Column(String(50), default="Active")
			permissions = _jsonb_col(default=dict)
			assignment_metadata = _jsonb_col(default=dict)

			project = relationship(
				"Project",
				foreign_keys=[project_id],
				backref=f"{tn}_assignments",
			)
			user = relationship("User", backref=f"{tn}_project_assignments")

			def __repr__(self) -> str:
				return f"<ProjectAssignment {self.user.username} — {self.role}>"

		# Attach satellite classes to the host model class
		cls.Project = Project
		cls.ProjectStep = ProjectStep
		cls.Deliverable = Deliverable
		cls.Equipment = Equipment
		cls.ProjectAssignment = ProjectAssignment
		cls._project_equipment_table = project_equipment_table

	# ------------------------------------------------------------------
	# declared_attr columns — appear on the host model rows
	# ------------------------------------------------------------------

	@declared_attr
	def project_id(cls) -> Column:
		"""FK from host model row to its associated Project."""
		return Column(
			Integer,
			ForeignKey(f"nx_pj_{cls.__tablename__}_projects.id", ondelete="SET NULL"),
			nullable=True,
		)

	@declared_attr
	def project(cls):
		"""Relationship from host model row to Project."""
		return relationship(
			f"Project",  # resolved by mapper name at runtime
			foreign_keys=[cls.__dict__["project_id"]],
			backref=cls.__tablename__,
		)

	# ------------------------------------------------------------------
	# Query helpers — SQLAlchemy 2.x (session.execute + select)
	# ------------------------------------------------------------------

	@classmethod
	def _get_session(cls):
		"""Return the SQLAlchemy session bound to the Model's scoped_session."""
		from flask import current_app
		return current_app.extensions["sqlalchemy"].session

	@classmethod
	def get_project_items(cls, project_id: int) -> list:
		"""All host-model rows belonging to *project_id*."""
		session = cls._get_session()
		stmt = select(cls).where(cls.project_id == project_id)
		return list(session.execute(stmt).scalars())

	@classmethod
	def get_active_projects(cls) -> list:
		"""Projects that are not Completed or Cancelled."""
		session = cls._get_session()
		stmt = select(cls.Project).where(
			cls.Project.status.notin_(["Completed", "Cancelled"])
		)
		return list(session.execute(stmt).scalars())

	@classmethod
	def assign_user_to_project(
		cls,
		project_id: int,
		user_id: int,
		role: str,
		start_date: datetime | None = None,
		end_date: datetime | None = None,
	) -> Any:
		"""Build (but do not flush) a ProjectAssignment instance."""
		return cls.ProjectAssignment(
			project_id=project_id,
			user_id=user_id,
			role=role,
			start_date=start_date or datetime.now(),
			end_date=end_date,
		)

	@classmethod
	def add_equipment_to_project(
		cls, project_id: int, equipment_id: int, quantity_required: int
	) -> bool:
		"""
		Append *equipment_id* to *project_id* via the M2M association table.

		Updates ``quantity_required`` on the association row.  Returns True on
		success, False if either the project or equipment row is missing.
		"""
		session = cls._get_session()
		project = session.get(cls.Project, project_id)
		equipment = session.get(cls.Equipment, equipment_id)
		if not (project and equipment):
			return False

		project.equipment.append(equipment)
		session.flush()  # populate association row so we can update it

		# Locate the newly created association row and set quantity
		assoc_tbl = cls._project_equipment_table
		session.execute(
			assoc_tbl.update()
			.where(
				(assoc_tbl.c.project_id == project_id)
				& (assoc_tbl.c.equipment_id == equipment_id)
			)
			.values(quantity_required=quantity_required)
		)
		return True

	@classmethod
	def get_project_timeline(cls, project_id: int) -> dict | None:
		"""
		Structured timeline dict for *project_id*.

		Returns ``None`` when the project does not exist.
		"""
		session = cls._get_session()
		project = session.get(cls.Project, project_id)
		if not project:
			return None

		steps_stmt = (
			select(cls.ProjectStep)
			.where(cls.ProjectStep.project_id == project_id)
			.order_by(cls.ProjectStep.sequence)
		)
		steps = list(session.execute(steps_stmt).scalars())

		return {
			"project_start": project.start_date,
			"project_end": project.end_date,
			"steps": [
				{
					"name": s.name,
					"start": s.start_date,
					"end": s.end_date,
					"early_start": s.early_start,
					"late_end": s.late_end,
					"sequence": s.sequence,
					"completion_percentage": s.completion_percentage,
				}
				for s in steps
			],
		}

	@classmethod
	def update_project_status(cls, project_id: int, new_status: str) -> bool:
		"""Set *new_status* on *project_id*.  Returns True on success."""
		session = cls._get_session()
		project = session.get(cls.Project, project_id)
		if not project:
			return False
		project.status = new_status
		return True

	@classmethod
	def get_project_resources(cls, project_id: int) -> dict | None:
		"""
		Team and equipment resource summary for *project_id*.

		Returns ``None`` when the project does not exist.
		"""
		session = cls._get_session()
		project = session.get(cls.Project, project_id)
		if not project:
			return None

		assignments_stmt = select(cls.ProjectAssignment).where(
			cls.ProjectAssignment.project_id == project_id
		)
		assignments = list(session.execute(assignments_stmt).scalars())

		assoc_tbl = cls._project_equipment_table
		equip_rows = session.execute(
			select(cls.Equipment, assoc_tbl.c.quantity_required)
			.join(assoc_tbl, cls.Equipment.id == assoc_tbl.c.equipment_id)
			.where(assoc_tbl.c.project_id == project_id)
		).all()

		return {
			"team": [
				{
					"user": a.user.username,
					"role": a.role,
					"start_date": a.start_date,
					"end_date": a.end_date,
					"hours_allocated": a.hours_allocated,
					"hours_used": a.hours_used,
				}
				for a in assignments
			],
			"equipment": [
				{"name": eq.name, "quantity_required": qty}
				for eq, qty in equip_rows
			],
		}

	# ------------------------------------------------------------------
	# Mermaid Gantt chart renderer
	# ------------------------------------------------------------------

	@classmethod
	def render_mermaid(cls, project_id: int) -> str:
		"""
		Produce a Mermaid.js ``gantt`` diagram for *project_id*.

		Sections:
		- Project bar
		- One section per step, with optional crit bars for early_start / late_end float
		- Deliverable milestones
		- Resource allocation bars
		"""
		session = cls._get_session()
		project = session.get(cls.Project, project_id)
		if not project:
			return "Error: Project not found"

		lines: list[str] = [
			"gantt",
			f"    title {project.name}",
			"    dateFormat  YYYY-MM-DD",
			"    axisFormat %Y-%m-%d",
			"    section Project",
			(
				f"    {project.name}: "
				f"{project.start_date.strftime('%Y-%m-%d')}, "
				f"{project.end_date.strftime('%Y-%m-%d')}"
			)
			if project.end_date
			else f"    {project.name}: {project.start_date.strftime('%Y-%m-%d')}, 1d",
		]

		# Steps
		steps_stmt = (
			select(cls.ProjectStep)
			.where(cls.ProjectStep.project_id == project_id)
			.order_by(cls.ProjectStep.sequence)
		)
		for step in session.execute(steps_stmt).scalars():
			step_start = step.start_date or project.start_date
			step_end = step.end_date or project.end_date or step_start
			duration = max((step_end - step_start).days, 1)

			lines.extend([
				f"    section {step.name}",
				f"    {step.name}: {step_start.strftime('%Y-%m-%d')}, {duration}d",
			])

			if step.early_start:
				early_days = abs((step.early_start - step_start).days) or 1
				lines.append(
					f"    Early Start: crit, {step.early_start.strftime('%Y-%m-%d')}, {early_days}d"
				)

			if step.late_end:
				late_days = abs((step.late_end - step_end).days) or 1
				lines.append(
					f"    Late End: crit, {step_end.strftime('%Y-%m-%d')}, {late_days}d"
				)

		# Deliverable milestones
		deliverables_stmt = select(cls.Deliverable).where(
			cls.Deliverable.project_id == project_id
		)
		deliverables = list(session.execute(deliverables_stmt).scalars())
		if deliverables:
			lines.append("    section Deliverables")
			for d in deliverables:
				lines.append(
					f"    {d.name}: milestone, {d.due_date.strftime('%Y-%m-%d')}, 0d"
				)

		# Resource allocation
		assignments_stmt = select(cls.ProjectAssignment).where(
			cls.ProjectAssignment.project_id == project_id
		)
		assignments = list(session.execute(assignments_stmt).scalars())
		if assignments:
			lines.append("    section Resource Allocation")
			for a in assignments:
				a_start = a.start_date or project.start_date
				a_end = a.end_date or project.end_date or a_start
				duration = max((a_end - a_start).days, 1)
				lines.append(
					f"    {a.user.username} ({a.role}): "
					f"{a_start.strftime('%Y-%m-%d')}, {duration}d"
				)

		return "\n".join(lines)

	# ------------------------------------------------------------------
	# Instance helper
	# ------------------------------------------------------------------

	def to_dict(self) -> dict[str, Any]:
		"""Serialise host-model row with its linked project summary."""
		proj = self.project
		return {
			"id": self.id,
			"project_id": self.project_id,
			"project_name": proj.name if proj else None,
			"status": proj.status if proj else None,
			"start_date": proj.start_date.isoformat() if proj and proj.start_date else None,
			"end_date": proj.end_date.isoformat() if proj and proj.end_date else None,
			"duration": proj.duration if proj else None,
			"is_active": proj.is_active if proj else None,
		}
