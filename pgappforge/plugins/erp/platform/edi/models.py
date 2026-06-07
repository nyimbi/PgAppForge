"""
pgappforge/plugins/erp/platform/edi/models.py

EDI Framework models.

Tables:
  edi_partner  — trading partner registry (X12/EDIFACT/PEPPOL/ETIMS/GENERIC_REST)
  edi_message  — inbound/outbound EDI message log with parse results
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import sqlalchemy as sa
from sqlalchemy import (
	Boolean,
	Column,
	DateTime,
	ForeignKey,
	Index,
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
# EDIPartner
# ---------------------------------------------------------------------------

class EDIPartner(AuditMixin, Model):
	"""Trading partner registry.

	protocol: X12 | EDIFACT | PEPPOL | ETIMS | GENERIC_REST
	direction: INBOUND | OUTBOUND | BOTH
	message_types: e.g. ["850","810","856"] for X12
	connectivity: {transport: "AS2"|"SFTP"|"HTTPS", endpoint: url, auth: {}}
	"""

	__allow_unmapped__ = True
	__tablename__ = "edi_partner"
	__table_args__ = (
		UniqueConstraint("tenant_id", "code", name="uq_edi_partner_tenant_code"),
		Index("ix_edi_partner_protocol_active", "tenant_id", "protocol", "is_active"),
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
	code = Column(String(50), nullable=False, comment="Unique partner code within tenant")
	protocol = Column(
		String(20),
		nullable=False,
		comment="X12 | EDIFACT | PEPPOL | ETIMS | GENERIC_REST",
	)
	direction = Column(
		String(20),
		nullable=False,
		default="BOTH",
		comment="INBOUND | OUTBOUND | BOTH",
	)
	message_types: list[Any] = Column(
		JSONB,
		nullable=False,
		default=list,
		comment='e.g. ["850","810","856"]',
	)
	connectivity: dict[str, Any] = Column(
		JSONB,
		nullable=False,
		default=dict,
		comment="{transport, endpoint, auth}",
	)
	is_active = Column(Boolean, nullable=False, default=True)

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

	messages: list[EDIMessage] = relationship(
		"EDIMessage",
		back_populates="partner",
		cascade="all, delete-orphan",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<EDIPartner {self.code!r} protocol={self.protocol!r}"
			f" direction={self.direction!r}>"
		)


# ---------------------------------------------------------------------------
# EDIMessage
# ---------------------------------------------------------------------------

class EDIMessage(AuditMixin, Model):
	"""Inbound/outbound EDI message log.

	status lifecycle:
	  PENDING → SENT / ACKED (outbound)
	  PENDING → PARSED / ERROR (inbound)
	"""

	__allow_unmapped__ = True
	__tablename__ = "edi_message"
	__table_args__ = (
		Index("ix_edi_message_dir_status", "tenant_id", "direction", "status"),
		Index("ix_edi_message_partner_type", "partner_id", "message_type"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	partner_id = Column(
		UUID(as_uuid=False),
		ForeignKey("edi_partner.id", ondelete="CASCADE"),
		nullable=False,
	)
	message_type = Column(
		String(50),
		nullable=False,
		comment="850, ORDERS, peppol_invoice, etims_invoice …",
	)
	direction = Column(
		String(10),
		nullable=False,
		comment="INBOUND | OUTBOUND",
	)
	payload = Column(Text, nullable=False)
	parsed_data: dict[str, Any] | None = Column(
		JSONB,
		nullable=True,
		comment="Structured result after parse",
	)
	status = Column(
		String(20),
		nullable=False,
		default="PENDING",
		comment="PENDING | SENT | ACKED | PARSED | ERROR",
	)
	error_log = Column(Text, nullable=True)
	reference_id = Column(
		String(100),
		nullable=True,
		comment="Linked PO/Invoice ID",
	)

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

	partner: EDIPartner = relationship(
		"EDIPartner",
		back_populates="messages",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<EDIMessage type={self.message_type!r} dir={self.direction!r}"
			f" status={self.status!r}>"
		)


__all__ = ["EDIPartner", "EDIMessage"]
