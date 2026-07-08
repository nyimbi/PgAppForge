from __future__ import annotations

import json
import logging
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
	"DiscussValidationError",
	"DiscussService",
]


class DiscussServiceError(Exception):
	"""Base error for discuss service."""


class DiscussNotFoundError(DiscussServiceError):
	"""Raised when a requested resource does not exist."""


class DiscussStateError(DiscussServiceError):
	"""Raised when an operation is invalid for the current state."""


class DiscussValidationError(DiscussServiceError, ValueError):
	"""Raised when caller-supplied inputs violate the discuss service contract."""


_CHANNEL_TYPES = {"PUBLIC", "PRIVATE", "DIRECT", "SYSTEM"}
_MAX_MEMBERS_PER_CREATE = 200
_MAX_ATTACHMENTS = 20


def _require_text(
	value: Any,
	field_name: str,
	*,
	max_length: int,
	uppercase: bool = False,
) -> str:
	if not isinstance(value, str):
		raise DiscussValidationError(f"{field_name} must be a string")
	text = value.strip()
	if not text:
		raise DiscussValidationError(f"{field_name} is required")
	if "\x00" in text:
		raise DiscussValidationError(f"{field_name} cannot contain NUL bytes")
	if len(text) > max_length:
		raise DiscussValidationError(f"{field_name} cannot exceed {max_length} characters")
	return text.upper() if uppercase else text


def _optional_text(
	value: Any,
	field_name: str,
	*,
	max_length: int,
	uppercase: bool = False,
) -> str | None:
	if value is None:
		return None
	return _require_text(value, field_name, max_length=max_length, uppercase=uppercase)


def _normalize_channel_type(value: Any) -> str:
	channel_type = _require_text(value, "channel_type", max_length=20, uppercase=True)
	if channel_type not in _CHANNEL_TYPES:
		raise DiscussValidationError(f"invalid channel_type: {channel_type}")
	return channel_type


def _normalize_member_ids(member_ids: Any) -> list[str]:
	if member_ids is None:
		return []
	if not isinstance(member_ids, list):
		raise DiscussValidationError("member_ids must be a list")
	if len(member_ids) > _MAX_MEMBERS_PER_CREATE:
		raise DiscussValidationError(
			f"member_ids cannot contain more than {_MAX_MEMBERS_PER_CREATE} entries"
		)
	normalized: list[str] = []
	seen: set[str] = set()
	for item in member_ids:
		member_id = _require_text(item, "member_id", max_length=50)
		key = member_id.casefold()
		if key in seen:
			continue
		seen.add(key)
		normalized.append(member_id)
	return normalized


def _normalize_message_type(value: Any) -> str:
	return _require_text(value, "message_type", max_length=20, uppercase=True)


def _normalize_json_object(value: Any, field_name: str) -> dict[str, Any]:
	if value is None:
		return {}
	if not isinstance(value, dict):
		raise DiscussValidationError(f"{field_name} must be an object")
	try:
		return json.loads(json.dumps(value, default=str))
	except (TypeError, ValueError) as exc:
		raise DiscussValidationError(f"{field_name} must be JSON serializable") from exc


def _normalize_attachments(value: Any) -> list[dict[str, Any]]:
	if value is None:
		return []
	if not isinstance(value, list):
		raise DiscussValidationError("attachments must be a list")
	if len(value) > _MAX_ATTACHMENTS:
		raise DiscussValidationError(
			f"attachments cannot contain more than {_MAX_ATTACHMENTS} entries"
		)
	attachments: list[dict[str, Any]] = []
	for item in value:
		if not isinstance(item, dict):
			raise DiscussValidationError("attachments must contain objects")
		attachments.append(_normalize_json_object(item, "attachment"))
	return attachments


def _normalize_limit(value: Any) -> int:
	if isinstance(value, bool) or not isinstance(value, int):
		raise DiscussValidationError("limit must be an integer")
	if value < 1 or value > 200:
		raise DiscussValidationError("limit must be between 1 and 200")
	return value


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
		name = _require_text(name, "name", max_length=200)
		created_by = _require_text(created_by, "created_by", max_length=50)
		tenant_id = _require_text(tenant_id, "tenant_id", max_length=64)
		description = _optional_text(description, "description", max_length=5000)
		channel_type = _normalize_channel_type(channel_type)
		member_ids = _normalize_member_ids(member_ids)

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
		for mid in member_ids:
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

		for mid in member_ids:
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
		channel_id = _require_text(channel_id, "channel_id", max_length=64)
		author_id = _require_text(author_id, "author_id", max_length=50)
		body = _require_text(body, "body", max_length=100_000)
		message_type = _normalize_message_type(message_type)
		parent_message_id = _optional_text(
			parent_message_id, "parent_message_id", max_length=64
		)
		attachments = _normalize_attachments(attachments)
		metadata = _normalize_json_object(metadata, "metadata")

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
			attachments=attachments,
			metadata_=metadata,
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
		message_id = _require_text(message_id, "message_id", max_length=64)
		reactor_id = _require_text(reactor_id, "reactor_id", max_length=50)
		emoji = _require_text(emoji, "emoji", max_length=32)
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
		message_id = _require_text(message_id, "message_id", max_length=64)
		reactor_id = _require_text(reactor_id, "reactor_id", max_length=50)
		emoji = _require_text(emoji, "emoji", max_length=32)
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
		channel_id = _require_text(channel_id, "channel_id", max_length=64)
		member_id = _require_text(member_id, "member_id", max_length=50)
		added_by = _require_text(added_by, "added_by", max_length=50)

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
		channel_id = _require_text(channel_id, "channel_id", max_length=64)
		member_id = _require_text(member_id, "member_id", max_length=50)
		message_id = _require_text(message_id, "message_id", max_length=64)
		self._update_last_read(channel_id, member_id, message_id, session)

	def get_unread_count(
		self,
		channel_id: str,
		member_id: str,
		session: Session,
	) -> int:
		"""Count messages posted after the member's last read pointer."""
		channel_id = _require_text(channel_id, "channel_id", max_length=64)
		member_id = _require_text(member_id, "member_id", max_length=50)

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
		tenant_id = _require_text(tenant_id, "tenant_id", max_length=64)
		notification_type = _require_text(
			notification_type, "notification_type", max_length=100
		)
		payload = _normalize_json_object(payload, "payload")
		channel_name = _optional_text(channel_name, "channel_name", max_length=200)
		linked_module = _optional_text(linked_module, "linked_module", max_length=100)
		linked_record_id = _optional_text(
			linked_record_id, "linked_record_id", max_length=50
		)
		channel = self._find_or_create_system_channel(
			tenant_id=tenant_id,
			session=session,
			channel_name=channel_name or "System Notifications",
			linked_module=linked_module,
			linked_record_id=linked_record_id,
		)

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
		channel_id = _require_text(channel_id, "channel_id", max_length=64)
		before_id = _optional_text(before_id, "before_id", max_length=64)
		limit = _normalize_limit(limit)

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
		message_id = _require_text(message_id, "message_id", max_length=64)
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
		channel_id = _require_text(channel_id, "channel_id", max_length=64)
		member_id = _require_text(member_id, "member_id", max_length=50)
		message_id = _require_text(message_id, "message_id", max_length=64)
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
		tenant_id = _require_text(tenant_id, "tenant_id", max_length=64)
		channel_name = _require_text(channel_name, "channel_name", max_length=200)
		linked_module = _optional_text(linked_module, "linked_module", max_length=100)
		linked_record_id = _optional_text(
			linked_record_id, "linked_record_id", max_length=50
		)
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
