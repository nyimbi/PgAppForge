from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy import (
	Boolean,
	Column,
	DateTime,
	ForeignKey,
	Index,
	Integer,
	Text,
	UniqueConstraint,
	VARCHAR,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from pgappforge.models.sqla import Model
from pgappforge.plugins.audit import AuditMixin

__all__ = [
	"DiscussChannel",
	"DiscussChannelMember",
	"DiscussMessage",
]

_uuid4 = sa.text("gen_random_uuid()")


class DiscussChannel(AuditMixin, Model):
	"""Team/direct messaging channel. Supports PUBLIC, PRIVATE, DIRECT and SYSTEM types.

	linked_module + linked_record_id allow BPM workflows to bind a notification
	channel directly to a domain record (e.g. a workflow instance).
	"""

	__allow_unmapped__ = True
	__tablename__ = "dsc_channel"
	__table_args__ = (
		Index("ix_dsc_channel_tenant_type", "tenant_id", "channel_type"),
		Index("ix_dsc_channel_linked", "tenant_id", "linked_module", "linked_record_id"),
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=lambda: __import__("uuid").uuid4().hex,
		server_default=_uuid4,
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	name = Column(VARCHAR(200), nullable=False)
	description = Column(Text, nullable=True)
	channel_type = Column(VARCHAR(20), nullable=False, default="PUBLIC")
	created_by = Column(VARCHAR(50), nullable=False)
	is_archived = Column(Boolean, nullable=False, default=False, server_default="false")
	linked_module = Column(VARCHAR(100), nullable=True)
	linked_record_id = Column(VARCHAR(50), nullable=True)
	avatar_url = Column(Text, nullable=True)

	members: list[DiscussChannelMember] = relationship(
		"DiscussChannelMember",
		back_populates="channel",
		cascade="all, delete-orphan",
		lazy="select",
	)
	messages: list[DiscussMessage] = relationship(
		"DiscussMessage",
		back_populates="channel",
		cascade="all, delete-orphan",
		lazy="select",
		primaryjoin="and_(DiscussMessage.channel_id == DiscussChannel.id, DiscussMessage.parent_message_id == None)",
		foreign_keys="[DiscussMessage.channel_id]",
		overlaps="all_messages",
	)
	all_messages: list[DiscussMessage] = relationship(
		"DiscussMessage",
		back_populates="channel",
		cascade="all, delete-orphan",
		lazy="select",
		foreign_keys="[DiscussMessage.channel_id]",
		overlaps="messages",
	)


class DiscussChannelMember(Model):
	"""Membership record binding a user to a channel with role and read state."""

	__allow_unmapped__ = True
	__tablename__ = "dsc_member"
	__table_args__ = (
		UniqueConstraint("channel_id", "member_id", name="uq_dsc_member_channel_user"),
		Index("ix_dsc_member_user_channel", "member_id", "channel_id"),
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=lambda: __import__("uuid").uuid4().hex,
		server_default=_uuid4,
	)
	channel_id = Column(
		UUID(as_uuid=False),
		ForeignKey("dsc_channel.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)
	member_id = Column(VARCHAR(50), nullable=False)
	role = Column(VARCHAR(20), nullable=False, default="MEMBER")
	joined_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: __import__("datetime").datetime.now(__import__("datetime").timezone.utc),
		server_default=sa.text("now()"),
	)
	last_read_message_id = Column(VARCHAR(50), nullable=True)
	is_muted = Column(Boolean, nullable=False, default=False, server_default="false")

	channel: DiscussChannel = relationship(
		"DiscussChannel",
		back_populates="members",
		lazy="select",
	)


class DiscussMessage(AuditMixin, Model):
	"""A message posted to a channel. Supports flat messages and threaded replies.

	reactions JSONB shape: {emoji: [user_id, ...]}
	attachments JSONB shape: [{url, filename, mime_type, size_bytes}, ...]
	metadata_ JSONB: arbitrary structured payload (used by SYSTEM/NOTIFICATION messages).

	created_at (from AuditMixin) is the primary ordering column.
	"""

	__allow_unmapped__ = True
	__tablename__ = "dsc_message"
	__table_args__ = (
		Index("ix_dsc_message_channel_ts", "channel_id", "created_at"),
		Index("ix_dsc_message_author_channel", "author_id", "channel_id"),
		Index("ix_dsc_message_parent", "parent_message_id"),
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=lambda: __import__("uuid").uuid4().hex,
		server_default=_uuid4,
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: __import__("datetime").datetime.now(__import__("datetime").timezone.utc),
		server_default=sa.text("now()"),
	)
	channel_id = Column(
		UUID(as_uuid=False),
		ForeignKey("dsc_channel.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)
	author_id = Column(VARCHAR(50), nullable=False)
	body = Column(Text, nullable=False)
	message_type = Column(VARCHAR(20), nullable=False, default="TEXT")
	parent_message_id = Column(
		UUID(as_uuid=False),
		ForeignKey("dsc_message.id", ondelete="SET NULL"),
		nullable=True,
	)
	reply_count = Column(Integer, nullable=False, default=0, server_default="0")
	attachments = Column(JSONB, nullable=False, default=list, server_default="[]")
	reactions = Column(JSONB, nullable=False, default=dict, server_default="{}")
	is_edited = Column(Boolean, nullable=False, default=False, server_default="false")
	edited_at = Column(DateTime(timezone=True), nullable=True)
	is_deleted = Column(Boolean, nullable=False, default=False, server_default="false")
	metadata_ = Column("metadata", JSONB, nullable=False, default=dict, server_default="{}")

	channel: DiscussChannel = relationship(
		"DiscussChannel",
		back_populates="all_messages",
		lazy="select",
		foreign_keys=[channel_id],
		overlaps="messages",
	)
	replies: list[DiscussMessage] = relationship(
		"DiscussMessage",
		foreign_keys=[parent_message_id],
		lazy="select",
		backref=sa.orm.backref("parent_message", remote_side=[id], lazy="select"),
	)
