"""
pgappforge/plugins/erp/platform/ai_assistant/models.py

SQLAlchemy models for platform AI assistant audit and session persistence.
"""
from __future__ import annotations

from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, Text

from pgappforge.models.sqla import Model


def _uuid7() -> str:
	from uuid6 import uuid7
	return str(uuid7())


def _utcnow() -> datetime:
	return datetime.now(timezone.utc)


class AuditLog(Model):
	"""Audit log for AI tool calls."""

	__allow_unmapped__ = True
	__tablename__ = "ai_assistant_audit_log"
	__table_args__ = (
		Index("ix_ai_audit_timestamp", "timestamp"),
		Index("ix_ai_audit_tool", "tool_name"),
		Index("ix_ai_audit_user", "user_id"),
		{"extend_existing": True},
	)

	id = Column(String(36), primary_key=True, default=_uuid7)
	timestamp = Column(
		DateTime(timezone=True),
		nullable=False,
		default=_utcnow,
		server_default=sa.text("NOW()"),
	)
	action = Column(String(50), nullable=False)
	tool_name = Column(String(120), nullable=False)
	user_id = Column(String(100), nullable=True)
	user_display = Column(String(255), nullable=True)
	tenant_id = Column(String(100), nullable=True, index=True)
	input_summary = Column(Text, nullable=False, default="")
	result_summary = Column(Text, nullable=False, default="")

	def __repr__(self) -> str:
		return f"<AuditLog tool={self.tool_name!r} action={self.action!r}>"


class ConversationSession(Model):
	"""Persisted AI assistant conversation session."""

	__allow_unmapped__ = True
	__tablename__ = "ai_assistant_conversation_session"
	__table_args__ = (
		Index("ix_ai_session_user_active", "user_id", "last_active_at"),
		Index("ix_ai_session_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	session_id = Column(String(36), primary_key=True, default=_uuid7)
	user_id = Column(String(100), nullable=False, index=True)
	tenant_id = Column(String(100), nullable=False, index=True)
	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=_utcnow,
		server_default=sa.text("NOW()"),
	)
	last_active_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=_utcnow,
		onupdate=_utcnow,
		server_default=sa.text("NOW()"),
	)
	message_count = Column(Integer, nullable=False, default=0, server_default=sa.text("0"))

	def __repr__(self) -> str:
		return f"<ConversationSession {self.session_id!r} user={self.user_id!r}>"


class ConversationMessage(Model):
	"""Append-only message row for an AI assistant conversation session."""

	__allow_unmapped__ = True
	__tablename__ = "ai_assistant_conversation_message"
	__table_args__ = (
		Index("ix_ai_message_session_created", "session_id", "created_at"),
		{"extend_existing": True},
	)

	id = Column(String(36), primary_key=True, default=_uuid7)
	session_id = Column(
		String(36),
		ForeignKey("ai_assistant_conversation_session.session_id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)
	role = Column(String(20), nullable=False)
	content = Column(Text, nullable=False, default="")
	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=_utcnow,
		server_default=sa.text("NOW()"),
	)
	archived_at = Column(DateTime(timezone=True), nullable=True)

	def __repr__(self) -> str:
		return f"<ConversationMessage session={self.session_id!r} role={self.role!r}>"


def ensure_schema(bind) -> bool:
	"""Create AI assistant tables from in-code models when migrations are absent."""
	try:
		engine = bind
		if hasattr(bind, "get_bind"):
			engine = bind.get_bind()
		Model.metadata.create_all(
			bind=engine,
			tables=[
				AuditLog.__table__,
				ConversationSession.__table__,
				ConversationMessage.__table__,
			],
		)
		return True
	except Exception:
		return False


__all__ = [
	"AuditLog",
	"ConversationSession",
	"ConversationMessage",
	"ensure_schema",
]
