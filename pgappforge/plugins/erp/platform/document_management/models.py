"""
pgappforge/plugins/erp/platform/document_management/models.py

SQLAlchemy model for lightweight ERP entity file attachments.
"""
from __future__ import annotations

from datetime import datetime, timezone
import uuid

import sqlalchemy as sa
from sqlalchemy import BigInteger, Column, DateTime, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID

from pgappforge.models.sqla import Model

try:
	from uuid_extensions import uuid7str
except ImportError:
	try:
		from uuid6 import uuid7
	except ImportError:
		def uuid7str() -> str:
			return str(uuid.uuid4())
	else:
		def uuid7str() -> str:
			return str(uuid7())


def _now() -> datetime:
	return datetime.now(timezone.utc)


class Attachment(Model):
	"""File attachment bound to any ERP entity by type and id."""

	__allow_unmapped__ = True
	__tablename__ = "erp_attachments"
	__table_args__ = (
		Index(
			"ix_erp_attachments_tenant_entity_uploaded",
			"tenant_id",
			"entity_type",
			"entity_id",
			"uploaded_at",
		),
		{"extend_existing": True},
	)

	id: str = Column(UUID(as_uuid=False), primary_key=True, default=uuid7str)
	tenant_id: str = Column(UUID(as_uuid=False), nullable=False, index=True)
	entity_type: str = Column(String(80), nullable=False)
	entity_id: str = Column(String(80), nullable=False)
	filename: str = Column(String(255), nullable=False)
	original_filename: str = Column(String(255), nullable=False)
	content_type: str = Column(String(120), nullable=False)
	file_size_bytes: int = Column(BigInteger, nullable=False)
	storage_path: str = Column(Text, nullable=False)
	uploaded_by: str = Column(String(80), nullable=False)
	uploaded_at: datetime = Column(
		DateTime(timezone=True),
		nullable=False,
		default=_now,
		server_default=sa.text("NOW()"),
	)
	description: str | None = Column(Text, nullable=True)

	def __repr__(self) -> str:
		return f"<Attachment {self.entity_type}:{self.entity_id} {self.original_filename}>"


__all__ = ["Attachment", "uuid7str"]
