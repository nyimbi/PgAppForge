"""
pgappforge/plugins/erp/platform/approvals/models.py

SQLAlchemy models for configurable ERP approval workflows.

PostgreSQL only: UUID columns use the PostgreSQL UUID type and timestamps use
TIMESTAMPTZ.
"""
from __future__ import annotations

from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from pgappforge.models.sqla import Model

try:
	from uuid_extensions import uuid7str
except ImportError:
	from uuid6 import uuid7

	def uuid7str() -> str:
		return str(uuid7())


def _now() -> datetime:
	return datetime.now(timezone.utc)


class ApprovalRequest(Model):
	"""Document approval request header."""

	__allow_unmapped__ = True
	__tablename__ = "erp_approval_requests"
	__table_args__ = (
		Index("ix_erp_approval_req_tenant_status_step", "tenant_id", "status", "current_step"),
		Index("ix_erp_approval_req_document", "document_type", "document_id"),
		{"extend_existing": True},
	)

	id: str = Column(UUID(as_uuid=False), primary_key=True, default=uuid7str)
	tenant_id: str = Column(UUID(as_uuid=False), nullable=False, index=True)
	document_type: str = Column(String(50), nullable=False)
	document_id: str = Column(String(64), nullable=False)
	current_step: int = Column(Integer, nullable=False, default=1, server_default="1")
	total_steps: int = Column(Integer, nullable=False)
	status: str = Column(String(20), nullable=False, default="pending", server_default="pending")
	requester_id: str = Column(String(64), nullable=False)
	amount_cents: int = Column(BigInteger, nullable=False, default=0, server_default="0")
	created_at: datetime = Column(DateTime(timezone=True), nullable=False, default=_now, server_default=sa.text("NOW()"))
	updated_at: datetime = Column(
		DateTime(timezone=True),
		nullable=False,
		default=_now,
		onupdate=_now,
		server_default=sa.text("NOW()"),
	)

	steps: list["ApprovalStep"] = relationship(
		"ApprovalStep",
		back_populates="request",
		lazy="select",
		cascade="all, delete-orphan",
		order_by="ApprovalStep.step_number",
	)

	def __repr__(self) -> str:
		return f"<ApprovalRequest {self.document_type}:{self.document_id} status={self.status}>"


class ApprovalStep(Model):
	"""Single approval step within an ApprovalRequest."""

	__allow_unmapped__ = True
	__tablename__ = "erp_approval_steps"
	__table_args__ = (
		Index("ix_erp_approval_step_request_number", "request_id", "step_number"),
		Index("ix_erp_approval_step_role_status", "approver_role", "status"),
		{"extend_existing": True},
	)

	id: str = Column(UUID(as_uuid=False), primary_key=True, default=uuid7str)
	request_id: str = Column(
		UUID(as_uuid=False),
		ForeignKey("erp_approval_requests.id", ondelete="CASCADE"),
		nullable=False,
	)
	step_number: int = Column(Integer, nullable=False)
	approver_role: str = Column(String(80), nullable=False)
	approver_id: str | None = Column(String(64), nullable=True)
	status: str = Column(String(20), nullable=False, default="pending", server_default="pending")
	decision_at: datetime | None = Column(DateTime(timezone=True), nullable=True)
	comments: str | None = Column(Text, nullable=True)

	request: ApprovalRequest = relationship("ApprovalRequest", back_populates="steps", lazy="select")

	def __repr__(self) -> str:
		return f"<ApprovalStep request={self.request_id} step={self.step_number} status={self.status}>"


__all__ = ["ApprovalRequest", "ApprovalStep", "uuid7str"]
