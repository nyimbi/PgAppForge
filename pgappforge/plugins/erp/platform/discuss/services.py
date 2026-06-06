from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from pgappforge.plugins.erp.foundation.events import emit_event
from pgappforge.plugins.erp.platform.discuss.events import (
	ChannelCreatedEvent,
	ChannelMemberAddedEvent,
	MessagePostedEvent,
	MessageReactedEvent,
	SystemNotificationPostedEvent,
	ThreadCreatedEvent,
)
from pgappforge.plugins.erp.platform.discuss.models import (
	DiscussChannel,
	DiscussChannelMember,
	DiscussMessage,
)

log = logging.getLogger(__name__)

__all__ = [
	"DiscussServiceError",
	"DiscussNotFoundError",
	"DiscussStateError",
	"DiscussService",
]


class DiscussServiceError(Exception):
	"""Base error for discuss service."""


class DiscussNotFoundError(DiscussServiceError):
	"""Raised when a requested resource does not exist."""


class DiscussStateError(DiscussServiceError):
	"""Raised when an operation is invalid for the current state."""


class DiscussService:
	"""All business logic for the Team Chat / Discuss module.

	Every method is synchronous and accepts an explicit SQLAlchemy Session so
	callers control transaction boundaries.  Callers are responsible for
	session.commit() / session.rollback().
	"""

	# ── Channel management ───────────────────────────────────────────────────

	def create_channel(
		self,
		name: str,
		created_by: str,
		tenant_id: str,
		session: Session,
		*,
		description: str | None = None,
		channel_type: str = "PUBLIC",
		member_ids: list[str] | None = None,
	) -> DiscussChannel:
		"""Create a channel, add creator as OWNER, optionally bulk-add members.

		Emits ChannelCreatedEvent and ChannelMemberAddedEvent per extra member.
		"""
		assert name, "name is required"
		assert created_by, "created_by is required"
		assert tenant_id, "tenant_id is required"
		assert channel_type in ("PUBLIC", "PRIVATE", "DIRECT", "SYSTEM"), (
			f"invalid channel_type: {channel_type}"
		)

		channel = DiscussChannel(
			name=name,
			description=description,
			channel_type=channel_type,
			created_by=created_by,
			tenant_id=tenant_id,
		)
		session.add(channel)
		session.flush()  # materialise id

		# creator is always OWNER
		owner = DiscussChannelMember(
			channel_id=channel.id,
			member_id=created_by,
			role="OWNER",
		)
		session.add(owner)

		# optional extra members
		for mid in (member_ids or []):
			if mid == created_by:
				continue
			member = DiscussChannelMember(
				channel_id=channel.id,
				member_id=mid,
				role="MEMBER",
			)
			session.add(member)

		session.flush()

		emit_event(
			ChannelCreatedEvent(
				aggregate_id=channel.id,
				aggregate_type="DiscussChannel",
				channel_id=channel.id,
				name=channel.name,
				created_by=created_by,
				tenant_id=tenant_id,
			),
			session,
		)

		for mid in (member_ids or []):
			if mid == created_by:
				continue
			emit_event(
				ChannelMemberAddedEvent(
					aggregate_id=channel.id,
					aggregate_type="DiscussChannel",
					channel_id=channel.id,
					member_id=mid,
					added_by=created_by,
				),
				session,
			)

		return channel

	# ── Messaging ────────────────────────────────────────────────────────────

	def post_message(
		self,
		channel_id: str,
		author_id: str,
		body: str,
		session: Session,
		*,
		message_type: str = "TEXT",
		parent_message_id: str | None = None,
		attachments: list[dict[str, Any]] | None = None,
		metadata: dict[str, Any] | None = None,
	) -> DiscussMessage:
		"""Post a message.  If parent_message_id is set this is a thread reply
		and the parent's reply_count is incremented atomically.

		Emits MessagePostedEvent and (for new threads) ThreadCreatedEvent.
		Marks the author's last_read_message_id to the new message.
		"""
		assert channel_id, "channel_id required"
		assert author_id, "author_id required"
		assert body, "body required"

		channel = session.execute(
			sa.select(DiscussChannel).where(DiscussChannel.id == channel_id)
		).scalar_one_or_none()
		if channel is None:
			raise DiscussNotFoundError(f"Channel {channel_id} not found")

		is_new_thread = False
		if parent_message_id:
			parent = session.execute(
				sa.select(DiscussMessage).where(DiscussMessage.id == parent_message_id)
			).scalar_one_or_none()
			if parent is None:
				raise DiscussNotFoundError(f"Parent message {parent_message_id} not found")
			if parent.parent_message_id is not None:
				raise DiscussStateError("Cannot reply to a reply — only one level of threading supported")
			is_new_thread = parent.reply_count == 0
			parent.reply_count += 1

		msg = DiscussMessage(
			channel_id=channel_id,
			author_id=author_id,
			body=body,
			message_type=message_type,
			parent_message_id=parent_message_id,
			attachments=attachments or [],
			metadata_=metadata or {},
			tenant_id=channel.tenant_id,
		)
		session.add(msg)
		session.flush()

		# advance author's read pointer
		self._update_last_read(channel_id, author_id, msg.id, session)

		emit_event(
			MessagePostedEvent(
				aggregate_id=msg.id,
				aggregate_type="DiscussMessage",
				message_id=msg.id,
				channel_id=channel_id,
				author_id=author_id,
				tenant_id=channel.tenant_id,
				preview=body[:100],
			),
			session,
		)

		if parent_message_id and is_new_thread:
			emit_event(
				ThreadCreatedEvent(
					aggregate_id=msg.id,
					aggregate_type="DiscussMessage",
					thread_id=msg.id,
					parent_message_id=parent_message_id,
					author_id=author_id,
				),
				session,
			)

		return msg

	# ── Reactions ────────────────────────────────────────────────────────────

	def add_reaction(
		self,
		message_id: str,
		reactor_id: str,
		emoji: str,
		session: Session,
	) -> DiscussMessage:
		"""Add emoji reaction.  Deduplicates; no-ops if already reacted."""
		msg = self._get_message(message_id, session)
		reactions: dict[str, list[str]] = dict(msg.reactions or {})
		users = reactions.get(emoji, [])
		if reactor_id not in users:
			users = [*users, reactor_id]
		reactions[emoji] = users
		msg.reactions = reactions
		session.flush()

		emit_event(
			MessageReactedEvent(
				aggregate_id=message_id,
				aggregate_type="DiscussMessage",
				message_id=message_id,
				reactor_id=reactor_id,
				emoji=emoji,
			),
			session,
		)
		return msg

	def remove_reaction(
		self,
		message_id: str,
		reactor_id: str,
		emoji: str,
		session: Session,
	) -> None:
		"""Remove emoji reaction.  Deletes the emoji key if no reactors remain."""
		msg = self._get_message(message_id, session)
		reactions: dict[str, list[str]] = dict(msg.reactions or {})
		users = [u for u in reactions.get(emoji, []) if u != reactor_id]
		if users:
			reactions[emoji] = users
		else:
			reactions.pop(emoji, None)
		msg.reactions = reactions
		session.flush()

	# ── Membership ───────────────────────────────────────────────────────────

	def add_member(
		self,
		channel_id: str,
		member_id: str,
		added_by: str,
		session: Session,
	) -> DiscussChannelMember:
		"""Add a user to a channel.  Idempotent — returns existing member if present."""
		existing = session.execute(
			sa.select(DiscussChannelMember).where(
				DiscussChannelMember.channel_id == channel_id,
				DiscussChannelMember.member_id == member_id,
			)
		).scalar_one_or_none()
		if existing is not None:
			return existing

		member = DiscussChannelMember(
			channel_id=channel_id,
			member_id=member_id,
			role="MEMBER",
		)
		session.add(member)
		session.flush()

		emit_event(
			ChannelMemberAddedEvent(
				aggregate_id=channel_id,
				aggregate_type="DiscussChannel",
				channel_id=channel_id,
				member_id=member_id,
				added_by=added_by,
			),
			session,
		)
		return member

	# ── Read state ───────────────────────────────────────────────────────────

	def mark_read(
		self,
		channel_id: str,
		member_id: str,
		message_id: str,
		session: Session,
	) -> None:
		"""Advance the member's read pointer to message_id."""
		self._update_last_read(channel_id, member_id, message_id, session)

	def get_unread_count(
		self,
		channel_id: str,
		member_id: str,
		session: Session,
	) -> int:
		"""Count messages posted after the member's last read pointer."""
		membership = session.execute(
			sa.select(DiscussChannelMember).where(
				DiscussChannelMember.channel_id == channel_id,
				DiscussChannelMember.member_id == member_id,
			)
		).scalar_one_or_none()
		if membership is None:
			return 0

		last_read_id = membership.last_read_message_id
		if last_read_id is None:
			# never read — count all non-deleted, non-thread-reply messages
			return session.execute(
				sa.select(sa.func.count(DiscussMessage.id)).where(
					DiscussMessage.channel_id == channel_id,
					DiscussMessage.is_deleted.is_(False),
					DiscussMessage.parent_message_id.is_(None),
				)
			).scalar_one()

		# find created_at of the last read message
		last_read_ts = session.execute(
			sa.select(DiscussMessage.created_at).where(DiscussMessage.id == last_read_id)
		).scalar_one_or_none()
		if last_read_ts is None:
			return 0

		return session.execute(
			sa.select(sa.func.count(DiscussMessage.id)).where(
				DiscussMessage.channel_id == channel_id,
				DiscussMessage.is_deleted.is_(False),
				DiscussMessage.parent_message_id.is_(None),
				DiscussMessage.created_at > last_read_ts,
			)
		).scalar_one()

	# ── System notifications (BPM integration) ───────────────────────────────

	def post_system_notification(
		self,
		tenant_id: str,
		notification_type: str,
		payload: dict[str, Any],
		session: Session,
		*,
		channel_name: str | None = None,
		linked_module: str | None = None,
		linked_record_id: str | None = None,
	) -> DiscussMessage:
		"""Find or create a SYSTEM channel and post a notification message.

		BPM workflow engine calls this to fan notifications into channels tied
		to workflow instances or to a default tenant-level system channel.
		"""
		channel = self._find_or_create_system_channel(
			tenant_id=tenant_id,
			session=session,
			channel_name=channel_name or "System Notifications",
			linked_module=linked_module,
			linked_record_id=linked_record_id,
		)

		import json
		body = json.dumps({"notification_type": notification_type, **payload}, default=str)

		msg = DiscussMessage(
			channel_id=channel.id,
			author_id="system",
			body=body,
			message_type="SYSTEM",
			metadata_={"notification_type": notification_type, **payload},
			tenant_id=tenant_id,
		)
		session.add(msg)
		session.flush()

		emit_event(
			SystemNotificationPostedEvent(
				aggregate_id=channel.id,
				aggregate_type="DiscussChannel",
				channel_id=channel.id,
				notification_type=notification_type,
				payload=payload,
			),
			session,
		)
		return msg

	# ── History ──────────────────────────────────────────────────────────────

	def get_channel_history(
		self,
		channel_id: str,
		session: Session,
		*,
		before_id: str | None = None,
		limit: int = 50,
	) -> list[DiscussMessage]:
		"""Return top-level (non-reply) messages ordered by created_at desc.

		Cursor-based pagination: pass before_id to get messages older than that id.
		"""
		assert 1 <= limit <= 200, "limit must be between 1 and 200"

		q = (
			sa.select(DiscussMessage)
			.where(
				DiscussMessage.channel_id == channel_id,
				DiscussMessage.is_deleted.is_(False),
				DiscussMessage.parent_message_id.is_(None),
			)
			.order_by(DiscussMessage.created_at.desc())
			.limit(limit)
		)

		if before_id is not None:
			cursor_ts = session.execute(
				sa.select(DiscussMessage.created_at).where(DiscussMessage.id == before_id)
			).scalar_one_or_none()
			if cursor_ts is not None:
				q = q.where(DiscussMessage.created_at < cursor_ts)

		return list(session.execute(q).scalars())

	# ── Internal helpers ─────────────────────────────────────────────────────

	def _get_message(self, message_id: str, session: Session) -> DiscussMessage:
		msg = session.execute(
			sa.select(DiscussMessage).where(DiscussMessage.id == message_id)
		).scalar_one_or_none()
		if msg is None:
			raise DiscussNotFoundError(f"Message {message_id} not found")
		return msg

	def _update_last_read(
		self,
		channel_id: str,
		member_id: str,
		message_id: str,
		session: Session,
	) -> None:
		membership = session.execute(
			sa.select(DiscussChannelMember).where(
				DiscussChannelMember.channel_id == channel_id,
				DiscussChannelMember.member_id == member_id,
			)
		).scalar_one_or_none()
		if membership is not None:
			membership.last_read_message_id = message_id
			session.flush()

	def _find_or_create_system_channel(
		self,
		tenant_id: str,
		session: Session,
		channel_name: str,
		linked_module: str | None,
		linked_record_id: str | None,
	) -> DiscussChannel:
		"""Return existing SYSTEM channel matching the criteria, or create one."""
		filters = [
			DiscussChannel.tenant_id == tenant_id,
			DiscussChannel.channel_type == "SYSTEM",
		]
		if linked_module and linked_record_id:
			filters += [
				DiscussChannel.linked_module == linked_module,
				DiscussChannel.linked_record_id == linked_record_id,
			]
		else:
			filters += [
				DiscussChannel.linked_module.is_(None),
				DiscussChannel.linked_record_id.is_(None),
			]

		channel = session.execute(
			sa.select(DiscussChannel).where(*filters)
		).scalar_one_or_none()

		if channel is None:
			channel = DiscussChannel(
				name=channel_name,
				channel_type="SYSTEM",
				created_by="system",
				tenant_id=tenant_id,
				linked_module=linked_module,
				linked_record_id=linked_record_id,
			)
			session.add(channel)
			session.flush()

		return channel


# ── BPM Action registrations ─────────────────────────────────────────────────

def _register_bpm_actions() -> None:
	try:
		from pgappforge.plugins.workflow.engine import BPMActionRegistry
	except ImportError:
		return

	@BPMActionRegistry.register(
		"platform.discuss.post_notification",
		"Post system notification to discuss channel",
	)
	def _bpm_post_notification(
		record_ctx: dict,
		session: Any,
		notification_type: str = "",
		payload: dict | None = None,
		channel_name: str | None = None,
		linked_module: str | None = None,
		linked_record_id: str | None = None,
		**kw: Any,
	) -> dict:
		tenant_id = record_ctx.get("tenant_id", "")
		try:
			svc = DiscussService()
			msg = svc.post_system_notification(
				tenant_id=tenant_id,
				notification_type=notification_type,
				payload=payload or {},
				session=session,
				channel_name=channel_name,
				linked_module=linked_module,
				linked_record_id=linked_record_id,
			)
			return {"status": "ok", "message_id": msg.id, "channel_id": msg.channel_id}
		except Exception as exc:
			log.warning("bpm discuss.post_notification failed: %s", exc)
			return {"status": "error", "message": str(exc)}

	@BPMActionRegistry.register(
		"platform.discuss.create_channel",
		"Create discuss channel for workflow instance",
	)
	def _bpm_create_channel(
		record_ctx: dict,
		session: Any,
		name: str = "",
		created_by: str = "system",
		channel_type: str = "SYSTEM",
		member_ids: list | None = None,
		linked_module: str | None = None,
		linked_record_id: str | None = None,
		**kw: Any,
	) -> dict:
		tenant_id = record_ctx.get("tenant_id", "")
		try:
			svc = DiscussService()
			channel = svc.create_channel(
				name=name,
				created_by=created_by,
				tenant_id=tenant_id,
				session=session,
				channel_type=channel_type,
				member_ids=member_ids,
			)
			if linked_module:
				channel.linked_module = linked_module
			if linked_record_id:
				channel.linked_record_id = linked_record_id
			session.flush()
			return {"status": "ok", "channel_id": channel.id, "channel_name": channel.name}
		except Exception as exc:
			log.warning("bpm discuss.create_channel failed: %s", exc)
			return {"status": "error", "message": str(exc)}


_register_bpm_actions()
