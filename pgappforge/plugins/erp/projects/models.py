"""
pgappforge/plugins/erp/projects/models.py

SQLAlchemy models for the Project Management / PSA plugin.

Design invariants:
  - ALL PKs: UUID v4 — gen_random_uuid() server default
  - ALL timestamps: DateTime(timezone=True) / TIMESTAMPTZ DEFAULT NOW()
  - ALL monetary amounts: Integer cents (NEVER Numeric/float for money)
  - ALL models: tenant_id UUID NOT NULL + AuditMixin
  - lazy='select' throughout (SA 2.x)
  - JSONB for semi-structured fields (predecessor_ids, metadata)
  - Composite indexes for tenant + status hot paths
  - risk_score: stored column, updated by service layer (not a DB computed column
    to stay portable across PG versions and keep migration diffs minimal)

Table prefix: proj_
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
	Integer,
	Numeric,
	String,
	Text,
	UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from pgappforge.models.sqla import Model
from pgappforge.plugins.audit import AuditMixin


def _uuid4() -> str:
	return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Program
# ---------------------------------------------------------------------------

class Program(AuditMixin, Model):
	"""Portfolio program — a collection of related projects sharing a budget.

	status: ACTIVE | COMPLETED | CANCELLED
	budget_cents: approved program-level budget ceiling in cents.
	currency_code: ISO 4217 (default KES).
	"""

	__allow_unmapped__ = True
	__tablename__ = "proj_program"
	__table_args__ = (
		Index("ix_proj_program_tenant", "tenant_id"),
		Index("ix_proj_program_owner", "owner_id"),
		Index("ix_proj_program_tenant_status", "tenant_id", "status"),
		UniqueConstraint("tenant_id", "code", name="uq_proj_program_tenant_code"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	code = Column(String(30), nullable=False, comment="Short unique programme code e.g. PRG-001")
	name = Column(String(200), nullable=False)
	owner_id = Column(UUID(as_uuid=False), nullable=False, index=True, comment="Soft FK to HCM employee / ab_user")
	status = Column(
		String(20),
		nullable=False,
		default="ACTIVE",
		comment="ACTIVE | COMPLETED | CANCELLED",
	)
	budget_cents = Column(Integer, nullable=False, default=0, comment="Approved programme budget ceiling in cents")
	currency_code = Column(String(3), nullable=False, default="KES")
	description = Column(Text, nullable=True)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	# Relationships
	projects: list[Project] = relationship("Project", back_populates="program", lazy="select")

	def __repr__(self) -> str:
		return f"<Program {self.code!r} {self.name!r} status={self.status!r}>"


# ---------------------------------------------------------------------------
# Project
# ---------------------------------------------------------------------------

class Project(AuditMixin, Model):
	"""Project header — the central aggregate for PM / PSA.

	project_type:
	  FIXED_FEE  — lump sum; revenue recognised by POC or milestones (IFRS 15 §35b)
	  T_AND_M    — time & materials; revenue = hours × rate; recognised as billed
	  RETAINER   — fixed monthly fee; recognised straight-line
	  MILESTONE  — recognised only when milestones are achieved and invoiced

	percent_complete: set by PM; drives EVM PV/EV calculations and POC revenue recognition.
	forecast_at_completion_cents: latest EAC estimate; updated by calculate_evm().
	billed_to_date_cents: running total of all SENT+PAID invoice totals.
	"""

	__allow_unmapped__ = True
	__tablename__ = "proj_project"
	__table_args__ = (
		Index("ix_proj_project_tenant", "tenant_id"),
		Index("ix_proj_project_program", "program_id"),
		Index("ix_proj_project_owner", "owner_id"),
		Index("ix_proj_project_customer", "customer_id"),
		Index("ix_proj_project_tenant_status", "tenant_id", "status"),
		UniqueConstraint("tenant_id", "code", name="uq_proj_project_tenant_code"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	program_id = Column(
		UUID(as_uuid=False),
		ForeignKey("proj_program.id"),
		nullable=True,
		index=True,
		comment="Optional parent programme",
	)
	code = Column(String(30), nullable=False, comment="Unique project code e.g. PRJ-2026-042")
	name = Column(String(200), nullable=False)
	project_type = Column(
		String(20),
		nullable=False,
		default="T_AND_M",
		comment="FIXED_FEE | T_AND_M | RETAINER | MILESTONE",
	)
	customer_id = Column(UUID(as_uuid=False), nullable=False, index=True, comment="Soft FK to CRM / party master")
	owner_id = Column(UUID(as_uuid=False), nullable=False, index=True, comment="Project manager — soft FK to HCM employee")

	start_date = Column(Date, nullable=False)
	end_date = Column(Date, nullable=False)

	status = Column(
		String(20),
		nullable=False,
		default="DRAFT",
		comment="DRAFT | PLANNING | ACTIVE | ON_HOLD | COMPLETED | CANCELLED",
	)

	# Budget & EVM columns — integer cents throughout
	original_budget_cents = Column(Integer, nullable=False, default=0, comment="Approved baseline budget (BAC) in cents")
	revised_budget_cents = Column(Integer, nullable=False, default=0, comment="Budget after approved change orders")
	forecast_at_completion_cents = Column(Integer, nullable=False, default=0, comment="EAC — latest cost forecast at completion")
	billed_to_date_cents = Column(Integer, nullable=False, default=0, comment="Sum of SENT+PAID invoice totals")
	recognised_revenue_cents = Column(Integer, nullable=False, default=0, comment="Cumulative IFRS 15 revenue recognised to date")

	percent_complete = Column(Numeric(5, 2), nullable=False, default=0, comment="0.00–100.00 PM-entered progress %")
	risk_level = Column(
		String(10),
		nullable=False,
		default="LOW",
		comment="LOW | MEDIUM | HIGH | CRITICAL",
	)
	currency_code = Column(String(3), nullable=False, default="KES")
	description = Column(Text, nullable=True)
	metadata_ = Column("metadata", JSONB, nullable=False, default=dict)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	# Relationships
	program: Program | None = relationship("Program", back_populates="projects", lazy="select")
	wbs_elements: list[WBSElement] = relationship("WBSElement", back_populates="project", cascade="all, delete-orphan", lazy="select")
	resources: list[ProjectResource] = relationship("ProjectResource", back_populates="project", cascade="all, delete-orphan", lazy="select")
	timesheets: list[ProjectTimesheet] = relationship("ProjectTimesheet", back_populates="project", cascade="all, delete-orphan", lazy="select")
	milestones: list[ProjectMilestone] = relationship("ProjectMilestone", back_populates="project", cascade="all, delete-orphan", lazy="select")
	risks: list[ProjectRisk] = relationship("ProjectRisk", back_populates="project", cascade="all, delete-orphan", lazy="select")
	change_orders: list[ChangeOrder] = relationship("ChangeOrder", back_populates="project", cascade="all, delete-orphan", lazy="select")
	invoices: list[ProjectInvoice] = relationship("ProjectInvoice", back_populates="project", cascade="all, delete-orphan", lazy="select")

	def __repr__(self) -> str:
		return (
			f"<Project {self.code!r} {self.name!r} "
			f"type={self.project_type!r} status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# WBSElement
# ---------------------------------------------------------------------------

class WBSElement(AuditMixin, Model):
	"""Work Breakdown Structure element — hierarchical decomposition of project scope.

	element_type:
	  PHASE       — top-level grouping (e.g. Phase 1: Inception)
	  DELIVERABLE — output within a phase
	  TASK        — atomic unit of work; carries planned/actual hours and cost
	  MILESTONE   — zero-duration marker; planned_hours/cost may be 0

	predecessor_ids: JSONB list of WBSElement UUIDs that must be COMPLETED
	before this element can start (finish-to-start dependency).

	EVM note: PV and EV are computed from planned_cost_cents × progress ratio
	by ProjectService.calculate_evm(). actual_cost_cents is the running
	accumulator of approved timesheet costs for this element.
	"""

	__allow_unmapped__ = True
	__tablename__ = "proj_wbs_element"
	__table_args__ = (
		Index("ix_proj_wbs_project", "project_id"),
		Index("ix_proj_wbs_parent", "parent_id"),
		Index("ix_proj_wbs_tenant", "tenant_id"),
		Index("ix_proj_wbs_tenant_status", "tenant_id", "status"),
		UniqueConstraint("project_id", "code", name="uq_proj_wbs_project_code"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	project_id = Column(UUID(as_uuid=False), ForeignKey("proj_project.id", ondelete="CASCADE"), nullable=False, index=True)
	parent_id = Column(
		UUID(as_uuid=False),
		ForeignKey("proj_wbs_element.id"),
		nullable=True,
		index=True,
		comment="Self-referential parent; NULL = root element",
	)

	code = Column(String(20), nullable=False, comment="Hierarchical code e.g. 1.2.3")
	name = Column(String(255), nullable=False)
	element_type = Column(
		String(15),
		nullable=False,
		default="TASK",
		comment="PHASE | DELIVERABLE | TASK | MILESTONE",
	)

	planned_start = Column(Date, nullable=False)
	planned_end = Column(Date, nullable=False)
	actual_start = Column(Date, nullable=True)
	actual_end = Column(Date, nullable=True)

	# Effort and cost — Numeric for hours, Integer cents for money
	planned_hours = Column(Numeric(8, 2), nullable=False, default=0)
	actual_hours = Column(Numeric(8, 2), nullable=False, default=0)
	planned_cost_cents = Column(Integer, nullable=False, default=0)
	actual_cost_cents = Column(Integer, nullable=False, default=0)

	status = Column(
		String(15),
		nullable=False,
		default="NOT_STARTED",
		comment="NOT_STARTED | IN_PROGRESS | COMPLETED | CANCELLED",
	)
	predecessor_ids = Column(
		JSONB,
		nullable=False,
		default=list,
		comment="[uuid, ...] — finish-to-start predecessor WBSElement IDs",
	)
	notes = Column(Text, nullable=True)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	# Relationships
	project: Project = relationship("Project", back_populates="wbs_elements", lazy="select")
	parent: WBSElement | None = relationship("WBSElement", remote_side="WBSElement.id", lazy="select", foreign_keys="[WBSElement.parent_id]")
	children: list[WBSElement] = relationship("WBSElement", back_populates="parent", lazy="select", foreign_keys="[WBSElement.parent_id]")
	timesheets: list[ProjectTimesheet] = relationship("ProjectTimesheet", back_populates="wbs_element", lazy="select")

	def __repr__(self) -> str:
		return f"<WBSElement {self.code!r} {self.name!r} type={self.element_type!r} status={self.status!r}>"


# ---------------------------------------------------------------------------
# ProjectResource
# ---------------------------------------------------------------------------

class ProjectResource(AuditMixin, Model):
	"""Planned resource allocation on a project.

	One row per employee per project.  Multiple roles on the same project
	require multiple rows (e.g. an employee acting as both PM and DEVELOPER).

	bill_rate_cents_per_hour: rate charged to the customer on T&M invoices.
	cost_rate_cents_per_hour: internal cost rate for margin analysis and EVM.
	Stored as integer cents-per-hour (e.g. 5000 = KES 50.00/hr).
	"""

	__allow_unmapped__ = True
	__tablename__ = "proj_resource"
	__table_args__ = (
		Index("ix_proj_resource_project", "project_id"),
		Index("ix_proj_resource_employee", "employee_id"),
		Index("ix_proj_resource_tenant", "tenant_id"),
		UniqueConstraint("project_id", "employee_id", "role", name="uq_proj_resource_project_emp_role"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	project_id = Column(UUID(as_uuid=False), ForeignKey("proj_project.id", ondelete="CASCADE"), nullable=False, index=True)
	employee_id = Column(UUID(as_uuid=False), nullable=False, index=True, comment="Soft FK to HCM employee master")

	role = Column(
		String(20),
		nullable=False,
		default="DEVELOPER",
		comment="PM | ANALYST | DEVELOPER | DESIGNER | QA",
	)
	allocated_hours = Column(Numeric(8, 2), nullable=False, default=0, comment="Planned allocation for this resource on this project")
	actual_hours = Column(Numeric(8, 2), nullable=False, default=0, comment="Running total from approved timesheets")
	bill_rate_cents_per_hour = Column(Integer, nullable=False, default=0, comment="T&M bill rate in cents per hour")
	cost_rate_cents_per_hour = Column(Integer, nullable=False, default=0, comment="Internal cost rate in cents per hour")

	start_date = Column(Date, nullable=False)
	end_date = Column(Date, nullable=False)
	is_active = Column(Boolean, nullable=False, default=True)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	# Relationships
	project: Project = relationship("Project", back_populates="resources", lazy="select")

	def __repr__(self) -> str:
		return (
			f"<ProjectResource project={self.project_id!r} "
			f"employee={self.employee_id!r} role={self.role!r}>"
		)


# ---------------------------------------------------------------------------
# ProjectTimesheet
# ---------------------------------------------------------------------------

class ProjectTimesheet(AuditMixin, Model):
	"""Daily timesheet entry for a project.

	Status machine:
	  DRAFT → SUBMITTED → APPROVED → BILLED
	                    ↘ REJECTED → DRAFT (resubmit)

	Once BILLED, the row is immutable (it's been included in a ProjectInvoice).
	hours: stored as Numeric(5,2) — max 999.99 hours per entry (sanity guard).
	cost_cents: computed by service as hours × resource.cost_rate_cents_per_hour;
	            stored for audit.  NULL until approved.
	bill_amount_cents: computed as hours × resource.bill_rate_cents_per_hour;
	                   stored on approval for invoice generation.
	"""

	__allow_unmapped__ = True
	__tablename__ = "proj_timesheet"
	__table_args__ = (
		Index("ix_proj_ts_project", "project_id"),
		Index("ix_proj_ts_employee", "employee_id"),
		Index("ix_proj_ts_wbs", "wbs_element_id"),
		Index("ix_proj_ts_tenant", "tenant_id"),
		Index("ix_proj_ts_tenant_status", "tenant_id", "status"),
		Index("ix_proj_ts_work_date", "work_date"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	project_id = Column(UUID(as_uuid=False), ForeignKey("proj_project.id", ondelete="CASCADE"), nullable=False, index=True)
	wbs_element_id = Column(
		UUID(as_uuid=False),
		ForeignKey("proj_wbs_element.id"),
		nullable=True,
		index=True,
		comment="Optional WBS task this time is charged to",
	)
	employee_id = Column(UUID(as_uuid=False), nullable=False, index=True, comment="Soft FK to HCM employee master")

	work_date = Column(Date, nullable=False)
	hours = Column(Numeric(5, 2), nullable=False, comment="Hours worked — max 999.99")
	description = Column(Text, nullable=False, default="")

	status = Column(
		String(10),
		nullable=False,
		default="DRAFT",
		comment="DRAFT | SUBMITTED | APPROVED | REJECTED | BILLED",
	)

	# Computed on approval by service layer — stored for audit/invoicing
	cost_cents = Column(Integer, nullable=True, comment="hours × cost_rate_cents_per_hour; set on approval")
	bill_amount_cents = Column(Integer, nullable=True, comment="hours × bill_rate_cents_per_hour; set on approval")

	approved_by = Column(UUID(as_uuid=False), nullable=True, comment="Soft FK to ab_user who approved")
	approved_at = Column(DateTime(timezone=True), nullable=True)
	invoice_id = Column(UUID(as_uuid=False), nullable=True, index=True, comment="Set when timesheet is included in a ProjectInvoice")

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	# Relationships
	project: Project = relationship("Project", back_populates="timesheets", lazy="select")
	wbs_element: WBSElement | None = relationship("WBSElement", back_populates="timesheets", lazy="select")

	def __repr__(self) -> str:
		return (
			f"<ProjectTimesheet project={self.project_id!r} "
			f"employee={self.employee_id!r} date={self.work_date} "
			f"hours={self.hours} status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# ProjectMilestone
# ---------------------------------------------------------------------------

class ProjectMilestone(AuditMixin, Model):
	"""Contractual milestone for milestone-billing and IFRS 15 recognition.

	For MILESTONE-type projects, revenue is recognised when status=ACHIEVED
	and an invoice has been raised (status=INVOICED).
	amount_cents is the contractual milestone value (invoice amount excl. tax).
	"""

	__allow_unmapped__ = True
	__tablename__ = "proj_milestone"
	__table_args__ = (
		Index("ix_proj_milestone_project", "project_id"),
		Index("ix_proj_milestone_tenant", "tenant_id"),
		Index("ix_proj_milestone_tenant_status", "tenant_id", "status"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	project_id = Column(UUID(as_uuid=False), ForeignKey("proj_project.id", ondelete="CASCADE"), nullable=False, index=True)

	name = Column(String(255), nullable=False)
	due_date = Column(Date, nullable=False)
	achieved_date = Column(Date, nullable=True)
	amount_cents = Column(Integer, nullable=False, default=0, comment="Contractual milestone value in cents (excl. tax)")

	status = Column(
		String(10),
		nullable=False,
		default="PENDING",
		comment="PENDING | ACHIEVED | INVOICED | PAID",
	)
	invoice_id = Column(
		UUID(as_uuid=False),
		nullable=True,
		index=True,
		comment="ProjectInvoice.id once invoiced",
	)
	notes = Column(Text, nullable=True)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	# Relationships
	project: Project = relationship("Project", back_populates="milestones", lazy="select")

	def __repr__(self) -> str:
		return f"<ProjectMilestone {self.name!r} due={self.due_date} status={self.status!r}>"


# ---------------------------------------------------------------------------
# ProjectRisk
# ---------------------------------------------------------------------------

class ProjectRisk(AuditMixin, Model):
	"""Project risk register entry.

	risk_score = probability × impact (1–25 scale).
	Stored explicitly (not a DB computed column) so the service can enforce
	business rules (e.g. auto-escalate project.risk_level when score >= 15).

	probability / impact: 1=Very Low, 2=Low, 3=Medium, 4=High, 5=Critical
	"""

	__allow_unmapped__ = True
	__tablename__ = "proj_risk"
	__table_args__ = (
		Index("ix_proj_risk_project", "project_id"),
		Index("ix_proj_risk_tenant", "tenant_id"),
		Index("ix_proj_risk_tenant_status", "tenant_id", "status"),
		Index("ix_proj_risk_owner", "risk_owner_id"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	project_id = Column(UUID(as_uuid=False), ForeignKey("proj_project.id", ondelete="CASCADE"), nullable=False, index=True)

	title = Column(String(255), nullable=False)
	description = Column(Text, nullable=False, default="")
	probability = Column(Integer, nullable=False, comment="1 (Very Low) – 5 (Critical)")
	impact = Column(Integer, nullable=False, comment="1 (Very Low) – 5 (Critical)")
	risk_score = Column(Integer, nullable=False, comment="probability × impact (1–25); maintained by service layer")
	mitigation = Column(Text, nullable=False, default="")
	risk_owner_id = Column(UUID(as_uuid=False), nullable=False, index=True, comment="Soft FK to HCM employee / ab_user")

	status = Column(
		String(10),
		nullable=False,
		default="OPEN",
		comment="OPEN | MITIGATED | ACCEPTED | CLOSED",
	)
	review_date = Column(Date, nullable=True)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	# Relationships
	project: Project = relationship("Project", back_populates="risks", lazy="select")

	def __repr__(self) -> str:
		return (
			f"<ProjectRisk {self.title!r} "
			f"score={self.risk_score} status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# ChangeOrder
# ---------------------------------------------------------------------------

class ChangeOrder(AuditMixin, Model):
	"""Scope / budget / schedule change request on a project.

	Status machine: DRAFT → SUBMITTED → APPROVED | REJECTED

	On approval by ProjectService.approve_change_order():
	  project.revised_budget_cents += budget_delta_cents
	  project.end_date += timedelta(days=schedule_delta_days)

	budget_delta_cents: positive = increase, negative = decrease.
	schedule_delta_days: positive = extension, negative = compression.
	"""

	__allow_unmapped__ = True
	__tablename__ = "proj_change_order"
	__table_args__ = (
		Index("ix_proj_co_project", "project_id"),
		Index("ix_proj_co_tenant", "tenant_id"),
		Index("ix_proj_co_tenant_status", "tenant_id", "status"),
		UniqueConstraint("project_id", "co_number", name="uq_proj_co_project_number"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	project_id = Column(UUID(as_uuid=False), ForeignKey("proj_project.id", ondelete="CASCADE"), nullable=False, index=True)

	co_number = Column(String(20), nullable=False, comment="Sequential CO reference e.g. CO-001")
	description = Column(Text, nullable=False, default="")
	budget_delta_cents = Column(Integer, nullable=False, default=0, comment="+ve = budget increase; -ve = reduction")
	schedule_delta_days = Column(Integer, nullable=False, default=0, comment="+ve = extension; -ve = compression")

	status = Column(
		String(10),
		nullable=False,
		default="DRAFT",
		comment="DRAFT | SUBMITTED | APPROVED | REJECTED",
	)
	submitted_by = Column(UUID(as_uuid=False), nullable=True, comment="Soft FK to ab_user who submitted")
	submitted_at = Column(DateTime(timezone=True), nullable=True)
	approved_by = Column(UUID(as_uuid=False), nullable=True, comment="Soft FK to ab_user who approved/rejected")
	approved_at = Column(DateTime(timezone=True), nullable=True)
	rejection_reason = Column(Text, nullable=True)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	# Relationships
	project: Project = relationship("Project", back_populates="change_orders", lazy="select")

	def __repr__(self) -> str:
		return (
			f"<ChangeOrder {self.co_number!r} project={self.project_id!r} "
			f"delta={self.budget_delta_cents:+}¢ status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# ProjectInvoice
# ---------------------------------------------------------------------------

class ProjectInvoice(AuditMixin, Model):
	"""Project invoice header.

	invoice_type:
	  MILESTONE  — single milestone payment (references ProjectMilestone)
	  T_AND_M    — unbilled approved timesheets × bill rate
	  RETAINER   — flat monthly retainer amount
	  ADVANCE    — advance payment / mobilisation fee

	Status machine: DRAFT → SENT → PAID | CANCELLED
	total_cents = amount_cents + tax_cents

	On generate_invoice() for T&M: approved timesheets are marked BILLED
	and their bill_amount_cents are summed into amount_cents.

	GL posting: DR AR 1200 / CR Revenue 4000 (done in service layer).
	"""

	__allow_unmapped__ = True
	__tablename__ = "proj_invoice"
	__table_args__ = (
		Index("ix_proj_invoice_project", "project_id"),
		Index("ix_proj_invoice_tenant", "tenant_id"),
		Index("ix_proj_invoice_tenant_status", "tenant_id", "status"),
		UniqueConstraint("tenant_id", "invoice_number", name="uq_proj_invoice_tenant_number"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	project_id = Column(UUID(as_uuid=False), ForeignKey("proj_project.id", ondelete="CASCADE"), nullable=False, index=True)

	invoice_number = Column(String(50), nullable=False, comment="Human-readable invoice reference e.g. INV-2026-001")
	invoice_type = Column(
		String(10),
		nullable=False,
		default="T_AND_M",
		comment="MILESTONE | T_AND_M | RETAINER | ADVANCE",
	)
	invoice_date = Column(Date, nullable=False)
	due_date = Column(Date, nullable=False)

	# Monetary — integer cents
	amount_cents = Column(Integer, nullable=False, default=0, comment="Net amount before tax")
	tax_cents = Column(Integer, nullable=False, default=0, comment="VAT / withholding tax")
	total_cents = Column(Integer, nullable=False, default=0, comment="amount_cents + tax_cents")

	status = Column(
		String(10),
		nullable=False,
		default="DRAFT",
		comment="DRAFT | SENT | PAID | CANCELLED",
	)
	paid_at = Column(DateTime(timezone=True), nullable=True)
	gl_journal_id = Column(String(50), nullable=True, comment="GL journal reference after posting")
	notes = Column(Text, nullable=True)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	# Relationships
	project: Project = relationship("Project", back_populates="invoices", lazy="select")

	def __repr__(self) -> str:
		return (
			f"<ProjectInvoice {self.invoice_number!r} "
			f"type={self.invoice_type!r} total={self.total_cents}¢ "
			f"status={self.status!r}>"
		)


__all__ = [
	"Program",
	"Project",
	"WBSElement",
	"ProjectResource",
	"ProjectTimesheet",
	"ProjectMilestone",
	"ProjectRisk",
	"ChangeOrder",
	"ProjectInvoice",
]
