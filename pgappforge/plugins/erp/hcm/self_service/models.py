from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from pgappforge.models.sqla import Model
from pgappforge.plugins.audit import AuditMixin

__all__ = [
	"LeaveRequest",
	"LeaveBalance",
	"ProfileUpdateRequest",
	"EssDocument",
	"Announcement",
]


def _uuid4() -> str:
	import uuid
	return str(uuid.uuid4())


class LeaveRequest(AuditMixin, Model):
	__tablename__ = "ess_leave_request"

	id: Mapped[str] = mapped_column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id: Mapped[str] = mapped_column(
		UUID(as_uuid=False),
		nullable=False,
		index=True,
	)
	employee_id: Mapped[str] = mapped_column(
		sa.String(50),
		nullable=False,
	)
	leave_type: Mapped[str] = mapped_column(
		sa.String(30),
		nullable=False,
	)
	start_date: Mapped[sa.Date] = mapped_column(
		sa.Date,
		nullable=False,
	)
	end_date: Mapped[sa.Date] = mapped_column(
		sa.Date,
		nullable=False,
	)
	days_requested: Mapped[float] = mapped_column(
		sa.Numeric(5, 1),
		nullable=False,
	)
	status: Mapped[str] = mapped_column(
		sa.String(20),
		nullable=False,
		default="PENDING",
		server_default="PENDING",
	)
	reason: Mapped[str | None] = mapped_column(
		sa.Text,
		nullable=True,
	)
	approved_by: Mapped[str | None] = mapped_column(
		sa.String(50),
		nullable=True,
	)
	approved_at: Mapped[sa.DateTime | None] = mapped_column(
		sa.DateTime(timezone=True),
		nullable=True,
	)
	rejected_by: Mapped[str | None] = mapped_column(
		sa.String(50),
		nullable=True,
	)
	rejection_reason: Mapped[str | None] = mapped_column(
		sa.Text,
		nullable=True,
	)
	handover_notes: Mapped[str | None] = mapped_column(
		sa.Text,
		nullable=True,
	)
	entity_id: Mapped[str | None] = mapped_column(
		sa.String(50),
		nullable=True,
	)

	__table_args__ = (
		sa.Index("ix_ess_leave_request_emp_status", "employee_id", "status"),
		sa.Index("ix_ess_leave_request_tenant_status_start", "tenant_id", "status", "start_date"),
	)

	VALID_LEAVE_TYPES = frozenset({
		"ANNUAL", "SICK", "MATERNITY", "PATERNITY",
		"COMPASSIONATE", "STUDY", "UNPAID",
	})
	VALID_STATUSES = frozenset({"PENDING", "APPROVED", "REJECTED", "CANCELLED"})

	def __repr__(self) -> str:
		return f"<LeaveRequest id={self.id} employee={self.employee_id} type={self.leave_type} status={self.status}>"


class LeaveBalance(AuditMixin, Model):
	__tablename__ = "ess_leave_balance"

	id: Mapped[str] = mapped_column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id: Mapped[str] = mapped_column(
		UUID(as_uuid=False),
		nullable=False,
		index=True,
	)
	employee_id: Mapped[str] = mapped_column(
		sa.String(50),
		nullable=False,
	)
	leave_type: Mapped[str] = mapped_column(
		sa.String(30),
		nullable=False,
	)
	year: Mapped[int] = mapped_column(
		sa.Integer,
		nullable=False,
	)
	entitled_days: Mapped[float] = mapped_column(
		sa.Numeric(5, 1),
		nullable=False,
		default=0,
		server_default="0",
	)
	used_days: Mapped[float] = mapped_column(
		sa.Numeric(5, 1),
		nullable=False,
		default=0,
		server_default="0",
	)
	carried_over_days: Mapped[float] = mapped_column(
		sa.Numeric(5, 1),
		nullable=False,
		default=0,
		server_default="0",
	)
	# Stored computed balance for query performance
	balance_days: Mapped[float] = mapped_column(
		sa.Numeric(5, 1),
		nullable=False,
		default=0,
		server_default="0",
	)

	__table_args__ = (
		sa.UniqueConstraint(
			"tenant_id", "employee_id", "leave_type", "year",
			name="uq_ess_leave_balance_tenant_emp_type_year",
		),
	)

	def recompute_balance(self) -> None:
		"""Recompute and store balance_days from component fields."""
		self.balance_days = float(self.entitled_days) + float(self.carried_over_days) - float(self.used_days)

	def __repr__(self) -> str:
		return (
			f"<LeaveBalance employee={self.employee_id} type={self.leave_type} "
			f"year={self.year} balance={self.balance_days}>"
		)


class ProfileUpdateRequest(AuditMixin, Model):
	__tablename__ = "ess_profile_update"

	id: Mapped[str] = mapped_column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id: Mapped[str] = mapped_column(
		UUID(as_uuid=False),
		nullable=False,
		index=True,
	)
	employee_id: Mapped[str] = mapped_column(
		sa.String(50),
		nullable=False,
	)
	requested_changes: Mapped[dict] = mapped_column(
		JSONB,
		nullable=False,
	)
	status: Mapped[str] = mapped_column(
		sa.String(20),
		nullable=False,
		default="PENDING",
		server_default="PENDING",
	)
	submitted_at: Mapped[sa.DateTime] = mapped_column(
		sa.DateTime(timezone=True),
		nullable=False,
		server_default=sa.text("now()"),
	)
	reviewed_by: Mapped[str | None] = mapped_column(
		sa.String(50),
		nullable=True,
	)
	reviewed_at: Mapped[sa.DateTime | None] = mapped_column(
		sa.DateTime(timezone=True),
		nullable=True,
	)
	notes: Mapped[str | None] = mapped_column(
		sa.Text,
		nullable=True,
	)

	__table_args__ = (
		sa.Index("ix_ess_profile_update_emp_status", "employee_id", "status"),
	)

	VALID_STATUSES = frozenset({"PENDING", "APPROVED", "REJECTED"})

	def __repr__(self) -> str:
		return f"<ProfileUpdateRequest id={self.id} employee={self.employee_id} status={self.status}>"


class EssDocument(AuditMixin, Model):
	__tablename__ = "ess_document"

	id: Mapped[str] = mapped_column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id: Mapped[str] = mapped_column(
		UUID(as_uuid=False),
		nullable=False,
		index=True,
	)
	employee_id: Mapped[str] = mapped_column(
		sa.String(50),
		nullable=False,
	)
	document_type: Mapped[str] = mapped_column(
		sa.String(50),
		nullable=False,
	)
	title: Mapped[str] = mapped_column(
		sa.String(300),
		nullable=False,
	)
	file_path: Mapped[str | None] = mapped_column(
		sa.Text,
		nullable=True,
	)
	file_size_bytes: Mapped[int | None] = mapped_column(
		sa.Integer,
		nullable=True,
	)
	mime_type: Mapped[str | None] = mapped_column(
		sa.String(100),
		nullable=True,
	)
	period: Mapped[str | None] = mapped_column(
		sa.String(20),
		nullable=True,
		comment="e.g. '2025-01' for monthly payslip",
	)
	is_visible: Mapped[bool] = mapped_column(
		sa.Boolean,
		nullable=False,
		default=True,
		server_default=sa.true(),
	)
	metadata_: Mapped[dict] = mapped_column(
		"metadata",
		JSONB,
		nullable=False,
		default=dict,
		server_default=sa.text("'{}'::jsonb"),
	)

	__table_args__ = (
		sa.Index("ix_ess_document_emp_type", "employee_id", "document_type"),
		sa.Index("ix_ess_document_emp_period", "employee_id", "period"),
	)

	VALID_DOCUMENT_TYPES = frozenset({
		"PAYSLIP", "CONTRACT", "CERTIFICATE", "POLICY", "OTHER",
	})

	def __repr__(self) -> str:
		return f"<EssDocument id={self.id} employee={self.employee_id} type={self.document_type} title={self.title!r}>"


class Announcement(AuditMixin, Model):
	__tablename__ = "ess_announcement"

	id: Mapped[str] = mapped_column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id: Mapped[str] = mapped_column(
		UUID(as_uuid=False),
		nullable=False,
		index=True,
	)
	title: Mapped[str] = mapped_column(
		sa.String(300),
		nullable=False,
	)
	body: Mapped[str] = mapped_column(
		sa.Text,
		nullable=False,
	)
	author_id: Mapped[str | None] = mapped_column(
		sa.String(50),
		nullable=True,
	)
	published_at: Mapped[sa.DateTime | None] = mapped_column(
		sa.DateTime(timezone=True),
		nullable=True,
	)
	expires_at: Mapped[sa.DateTime | None] = mapped_column(
		sa.DateTime(timezone=True),
		nullable=True,
	)
	# empty list = all employees
	audience_roles: Mapped[list] = mapped_column(
		JSONB,
		nullable=False,
		default=list,
		server_default=sa.text("'[]'::jsonb"),
	)
	is_pinned: Mapped[bool] = mapped_column(
		sa.Boolean,
		nullable=False,
		default=False,
		server_default=sa.false(),
	)
	priority: Mapped[str] = mapped_column(
		sa.String(20),
		nullable=False,
		default="NORMAL",
		server_default="NORMAL",
	)
	entity_id: Mapped[str | None] = mapped_column(
		sa.String(50),
		nullable=True,
	)

	__table_args__ = (
		sa.Index("ix_ess_announcement_tenant_published", "tenant_id", "published_at"),
		sa.Index("ix_ess_announcement_tenant_expires", "tenant_id", "expires_at"),
	)

	VALID_PRIORITIES = frozenset({"LOW", "NORMAL", "HIGH", "URGENT"})

	def __repr__(self) -> str:
		return f"<Announcement id={self.id} title={self.title!r} priority={self.priority}>"
