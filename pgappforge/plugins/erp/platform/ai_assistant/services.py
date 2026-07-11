"""
pgappforge/plugins/erp/platform/ai_assistant/services.py

Session persistence service for AI assistant conversations.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import sqlalchemy as sa

from .models import ConversationMessage, ConversationSession


def _utcnow() -> datetime:
	return datetime.now(timezone.utc)


class AIAssistantService:
	"""Persistence facade for conversation sessions and messages."""

	def __init__(self, session: Any):
		self.session = session

	def create_session(self, user_id: str, tenant_id: str) -> ConversationSession | None:
		try:
			conversation = ConversationSession(user_id=user_id, tenant_id=tenant_id)
			self.session.add(conversation)
			self.session.commit()
			return conversation
		except Exception:
			try:
				self.session.rollback()
			except Exception:
				pass
			return None

	def append_message(
		self,
		session_id: str,
		role: str,
		content: str,
	) -> ConversationMessage | None:
		try:
			conversation = self.session.execute(
				sa.select(ConversationSession).where(
					ConversationSession.session_id == session_id
				)
			).scalar_one_or_none()
			if conversation is None:
				return None
			message = ConversationMessage(
				session_id=session_id,
				role=role,
				content=content,
			)
			conversation.message_count = int(conversation.message_count or 0) + 1
			conversation.last_active_at = _utcnow()
			self.session.add(message)
			self.session.commit()
			return message
		except Exception:
			try:
				self.session.rollback()
			except Exception:
				pass
			return None

	def get_session_history(self, session_id: str, limit: int = 20) -> list[dict[str, Any]]:
		"""Return recent non-archived messages for a conversation session."""
		try:
			limit = max(1, min(int(limit), 200))
			rows = self.session.execute(
				sa.select(ConversationMessage)
				.where(
					ConversationMessage.session_id == session_id,
					ConversationMessage.archived_at.is_(None),
				)
				.order_by(ConversationMessage.created_at.desc())
				.limit(limit)
			).scalars().all()
			return [
				{
					"id": row.id,
					"session_id": row.session_id,
					"role": row.role,
					"content": row.content,
					"created_at": row.created_at.isoformat() if row.created_at else None,
				}
				for row in reversed(rows)
			]
		except Exception:
			return []

	def clear_session(self, session_id: str) -> bool:
		"""Archive all messages in a session and reset its active message count."""
		try:
			now = _utcnow()
			self.session.execute(
				sa.update(ConversationMessage)
				.where(
					ConversationMessage.session_id == session_id,
					ConversationMessage.archived_at.is_(None),
				)
				.values(archived_at=now)
			)
			result = self.session.execute(
				sa.update(ConversationSession)
				.where(ConversationSession.session_id == session_id)
				.values(message_count=0, last_active_at=now)
			)
			self.session.commit()
			return result.rowcount > 0
		except Exception:
			try:
				self.session.rollback()
			except Exception:
				pass
			return False


__all__ = ["AIAssistantService"]
