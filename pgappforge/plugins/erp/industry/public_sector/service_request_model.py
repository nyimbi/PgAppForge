"""
pgappforge/plugins/erp/industry/public_sector/service_request_model.py

ServiceRequest SQLAlchemy model for the Public Sector plugin.

Tracks multi-channel citizen service requests (web, phone, walk-in, email, app).
Table prefix: ps_
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy import (
	Column,
	DateTime,
	ForeignKey,
	Index,
	Integer,
	String,
	Text,
	UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from pgappforge.models.sqla import Model
from pgappforge.plugins.audit import AuditMixin


def _uuid4() -> str:
	return str(uuid.uuid4())


class ServiceRequest(AuditMixin, Model):
	"""Citizen service request — multi-channel inbound request tracking.

	Channels: WEB|PHONE|WALK_IN|EMAIL|MOBILE_APP
	Priority: LOW|NORMAL|HIGH|URGENT
	Service types: INFO_REQUEST|DOCUMENT_REQUEST|COMPLAINT|APPEAL|GENERAL

	attachments JSONB: [{url, filename, content_type, uploaded_at}]
	"""

	__allow_unmapped__ = True
	__tablename__ = "ps_service_request"
	__table_args__ = (
		Index("ix_ps_sr_tenant", "tenant_id"),
		Index("ix_ps_sr_constituent", "constituent_id"),
		Index("ix_ps_sr_tenant_status", "tenant_id", "status"),
		Index("ix_ps_sr_assigned_to", "assigned_to_id"),
		UniqueConstraint("tenant_id", "request_number", name="uq_ps_sr_tenant_number"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	request_number = Column(String(50), nullable=False, comment="Unique request reference per tenant")
	constituent_id = Column(UUID(as_uuid=False), ForeignKey("ps_constituent.id"), nullable=True, index=True)

	service_type = Column(
		String(30),
		nullable=False,
		default="GENERAL",
		comment="INFO_REQUEST|DOCUMENT_REQUEST|COMPLAINT|APPEAL|GENERAL",
	)
	channel = Column(
		String(20),
		nullable=False,
		default="WEB",
		comment="WEB|PHONE|WALK_IN|EMAIL|MOBILE_APP",
	)
	priority = Column(
		String(10),
		nullable=False,
		default="NORMAL",
		comment="LOW|NORMAL|HIGH|URGENT",
	)

	subject = Column(String(255), nullable=False)
	description = Column(Text, nullable=True)
	attachments = Column(JSONB, nullable=False, default=list, comment="[{url, filename, content_type, uploaded_at}]")

	assigned_to_id = Column(UUID(as_uuid=False), nullable=True, index=True, comment="FK to ab_user")
	resolved_at = Column(DateTime(timezone=True), nullable=True)
	resolution_notes = Column(Text, nullable=True)

	status = Column(
		String(20),
		nullable=False,
		default="OPEN",
		comment="OPEN|IN_PROGRESS|RESOLVED|CLOSED|ESCALATED",
	)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	def __repr__(self) -> str:
		return f"<ServiceRequest {self.request_number!r} type={self.service_type!r} status={self.status!r}>"


__all__ = ["ServiceRequest"]
