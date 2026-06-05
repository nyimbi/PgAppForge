"""
pgappforge/plugins/erp/platform/social/models.py

Federated Social (ActivityPub) models.

Entities:
  Actor        — local and remote ActivityPub actors (Person/Group/Service/Application)
  SocialActivity     — append-only activity log (Create/Update/Delete/Follow/Like/Announce/Block/Undo)
  Post         — content object extending SocialActivity with rich text + media
  Follow       — directed follow relationship with lifecycle state
  Reaction     — Like/Boost/Bookmark on a Post
  Notification — per-actor notification queue

Design notes:
  - All PKs: UUID v4 strings
  - All timestamps: TIMESTAMPTZ DEFAULT NOW()
  - Monetary amounts: N/A for this domain
  - actor_id on Actor is a unique VARCHAR(200) ActivityPub IRI; the PK id is
    the internal surrogate key used for FK references.
  - private_key_pem_encrypted is only set for local actors; NULL for remote.
  - tags/mentions stored as PostgreSQL ARRAY(Text) / ARRAY(UUID-as-string).
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
	Integer,
	String,
	Text,
	UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import relationship

from pgappforge.models.sqla import Model
from pgappforge.plugins.audit import AuditMixin


def _uuid4() -> str:
	return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Actor
# ---------------------------------------------------------------------------

class Actor(AuditMixin, Model):
	"""ActivityPub actor — local or federated remote.

	actor_id: globally unique ActivityPub IRI (e.g. https://example.com/users/alice).
	For local actors, private_key_pem_encrypted holds the encrypted RSA private key.
	party_id links to foundation.Party for enterprise identity bridging.
	"""

	__allow_unmapped__ = True
	__tablename__ = "erp_social_actor"
	__table_args__ = (
		UniqueConstraint("actor_id", name="uq_erp_social_actor_actor_id"),
		UniqueConstraint("inbox_url", name="uq_erp_social_actor_inbox"),
		UniqueConstraint("outbox_url", name="uq_erp_social_actor_outbox"),
		Index("ix_erp_social_actor_tenant", "tenant_id"),
		Index("ix_erp_social_actor_local", "is_local"),
		Index("ix_erp_social_actor_domain", "domain"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	# ActivityPub identity
	actor_id = Column(
		String(200),
		nullable=False,
		unique=True,
		comment="Globally unique ActivityPub actor IRI",
	)
	username = Column(String(100), nullable=False)
	display_name = Column(String(255), nullable=True)
	actor_type = Column(
		String(15),
		nullable=False,
		default="PERSON",
		comment="PERSON | GROUP | SERVICE | APPLICATION",
	)

	# Endpoint URLs
	inbox_url = Column(Text, nullable=True, unique=True)
	outbox_url = Column(Text, nullable=True, unique=True)
	followers_url = Column(Text, nullable=True)
	following_url = Column(Text, nullable=True)
	profile_url = Column(Text, nullable=True)

	# Profile media
	avatar_url = Column(Text, nullable=True)
	banner_url = Column(Text, nullable=True)
	bio = Column(Text, nullable=True)

	# Federation
	is_local = Column(Boolean, nullable=False, default=True)
	domain = Column(String(255), nullable=True, comment="NULL for local actors")
	public_key_pem = Column(Text, nullable=True)
	private_key_pem_encrypted = Column(
		Text, nullable=True,
		comment="KMS-encrypted RSA private key; NULL for remote actors",
	)

	# Social counters (denormalised)
	is_verified = Column(Boolean, nullable=False, default=False)
	follower_count = Column(Integer, nullable=False, default=0)
	following_count = Column(Integer, nullable=False, default=0)

	# Foundation bridge
	party_id = Column(
		UUID(as_uuid=False),
		nullable=True,
		comment="FK to foundation Party; NULL for purely federated actors",
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

	def __repr__(self) -> str:
		return (
			f"<Actor {self.id!r} username={self.username!r}"
			f" type={self.actor_type!r} local={self.is_local}>"
		)


# ---------------------------------------------------------------------------
# SocialActivity
# ---------------------------------------------------------------------------

class SocialActivity(Model):
	"""Append-only ActivityPub activity log.

	activity_id: globally unique ActivityPub activity IRI.
	object_content: full JSON representation of the object payload.
	"""

	__allow_unmapped__ = True
	__tablename__ = "erp_social_activity"
	__table_args__ = (
		UniqueConstraint("activity_id", name="uq_erp_social_activity_activity_id"),
		Index("ix_erp_social_activity_actor", "actor_id"),
		Index("ix_erp_social_activity_target", "target_actor_id"),
		Index("ix_erp_social_activity_tenant", "tenant_id"),
		Index("ix_erp_social_activity_type", "activity_type"),
		Index("ix_erp_social_activity_published", "published_at"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	activity_id = Column(
		String(200),
		nullable=False,
		unique=True,
		comment="Globally unique ActivityPub activity IRI",
	)
	actor_id = Column(
		UUID(as_uuid=False),
		ForeignKey("erp_social_actor.id", ondelete="CASCADE"),
		nullable=False,
	)
	activity_type = Column(
		String(15),
		nullable=False,
		comment="CREATE | UPDATE | DELETE | FOLLOW | LIKE | ANNOUNCE | BLOCK | UNDO",
	)
	object_type = Column(String(100), nullable=True)
	object_id = Column(Text, nullable=True, comment="ActivityPub IRI of the object")
	object_content: dict[str, Any] = Column(
		JSONB, nullable=True,
		comment="Full JSON-LD object payload",
	)
	target_actor_id = Column(
		UUID(as_uuid=False),
		ForeignKey("erp_social_actor.id", ondelete="SET NULL"),
		nullable=True,
	)
	published_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	visibility = Column(
		String(10),
		nullable=False,
		default="PUBLIC",
		comment="PUBLIC | UNLISTED | FOLLOWERS | DIRECT",
	)
	is_local = Column(Boolean, nullable=False, default=True)

	actor = relationship("Actor", foreign_keys=[actor_id], backref="activities")
	target_actor = relationship("Actor", foreign_keys=[target_actor_id])

	def __repr__(self) -> str:
		return (
			f"<SocialActivity {self.id!r} type={self.activity_type!r}"
			f" actor={self.actor_id!r}>"
		)


# ---------------------------------------------------------------------------
# Post
# ---------------------------------------------------------------------------

class Post(Model):
	"""Rich-text content object bound to an SocialActivity.

	Extends SocialActivity with content, media attachments, threading, and counters.
	in_reply_to_id enables threaded conversations (self-referential FK).
	mentions stores actor UUIDs (internal surrogate keys).
	"""

	__allow_unmapped__ = True
	__tablename__ = "erp_social_post"
	__table_args__ = (
		Index("ix_erp_social_post_activity", "activity_id"),
		Index("ix_erp_social_post_reply", "in_reply_to_id"),
		Index("ix_erp_social_post_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	activity_id = Column(
		UUID(as_uuid=False),
		ForeignKey("erp_social_activity.id", ondelete="CASCADE"),
		nullable=False,
		unique=True,
	)
	content = Column(Text, nullable=True, comment="Plain-text content body")
	content_html = Column(Text, nullable=True, comment="Rendered HTML body")
	attachments: list[dict] = Column(
		JSONB, nullable=True, default=list,
		comment="Array of ActivityStreams Document/Image objects",
	)
	tags = Column(
		ARRAY(Text), nullable=True, default=list,
		comment="Hashtag strings e.g. ARRAY['#python','#opensource']",
	)
	mentions = Column(
		ARRAY(Text), nullable=True, default=list,
		comment="Internal actor UUIDs (surrogate keys) mentioned in post",
	)
	sensitive = Column(Boolean, nullable=False, default=False)
	spoiler_text = Column(Text, nullable=True, comment="Content warning text")
	in_reply_to_id = Column(
		UUID(as_uuid=False),
		ForeignKey("erp_social_post.id", ondelete="SET NULL"),
		nullable=True,
	)

	# Counters (denormalised)
	boost_count = Column(Integer, nullable=False, default=0)
	reaction_count = Column(Integer, nullable=False, default=0)
	reply_count = Column(Integer, nullable=False, default=0)
	language = Column(
		String(5), nullable=False, default="en",
		comment="BCP 47 language tag",
	)

	activity = relationship("SocialActivity", backref="post")
	replies = relationship("Post", backref=sa.orm.backref("parent", remote_side=[id]))

	def __repr__(self) -> str:
		return (
			f"<Post {self.id!r} lang={self.language!r}"
			f" boosts={self.boost_count}>"
		)


# ---------------------------------------------------------------------------
# Follow
# ---------------------------------------------------------------------------

class Follow(Model):
	"""Directed follow relationship between two actors.

	status: PENDING (awaiting Accept), ACCEPTED, REJECTED.
	UniqueConstraint prevents duplicate follow rows for the same pair.
	"""

	__allow_unmapped__ = True
	__tablename__ = "erp_social_follow"
	__table_args__ = (
		UniqueConstraint(
			"follower_id", "following_id",
			name="uq_erp_social_follow_pair",
		),
		Index("ix_erp_social_follow_follower", "follower_id"),
		Index("ix_erp_social_follow_following", "following_id"),
		Index("ix_erp_social_follow_tenant", "tenant_id"),
		Index("ix_erp_social_follow_status", "status"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	follower_id = Column(
		UUID(as_uuid=False),
		ForeignKey("erp_social_actor.id", ondelete="CASCADE"),
		nullable=False,
	)
	following_id = Column(
		UUID(as_uuid=False),
		ForeignKey("erp_social_actor.id", ondelete="CASCADE"),
		nullable=False,
	)
	status = Column(
		String(10),
		nullable=False,
		default="PENDING",
		comment="PENDING | ACCEPTED | REJECTED",
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

	follower = relationship("Actor", foreign_keys=[follower_id])
	following = relationship("Actor", foreign_keys=[following_id])

	def __repr__(self) -> str:
		return (
			f"<Follow {self.id!r} {self.follower_id!r}"
			f" → {self.following_id!r} status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# Reaction
# ---------------------------------------------------------------------------

class Reaction(Model):
	"""Actor reaction (Like/Boost/Bookmark) on a Post.

	UniqueConstraint enforces one reaction of each type per (post, actor) pair.
	"""

	__allow_unmapped__ = True
	__tablename__ = "erp_social_reaction"
	__table_args__ = (
		UniqueConstraint(
			"post_id", "actor_id", "reaction_type",
			name="uq_erp_social_reaction_unique",
		),
		Index("ix_erp_social_reaction_post", "post_id"),
		Index("ix_erp_social_reaction_actor", "actor_id"),
		Index("ix_erp_social_reaction_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	post_id = Column(
		UUID(as_uuid=False),
		ForeignKey("erp_social_post.id", ondelete="CASCADE"),
		nullable=False,
	)
	actor_id = Column(
		UUID(as_uuid=False),
		ForeignKey("erp_social_actor.id", ondelete="CASCADE"),
		nullable=False,
	)
	reaction_type = Column(
		String(10),
		nullable=False,
		comment="LIKE | BOOST | BOOKMARK",
	)
	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	post = relationship("Post", backref="reactions")
	actor = relationship("Actor", backref="reactions")

	def __repr__(self) -> str:
		return (
			f"<Reaction {self.id!r} type={self.reaction_type!r}"
			f" post={self.post_id!r} actor={self.actor_id!r}>"
		)


# ---------------------------------------------------------------------------
# Notification
# ---------------------------------------------------------------------------

class Notification(Model):
	"""Per-actor notification for social events.

	notification_type: FOLLOW / MENTION / BOOST / REACTION / REPLY / DIRECT.
	"""

	__allow_unmapped__ = True
	__tablename__ = "erp_social_notification"
	__table_args__ = (
		Index("ix_erp_social_notif_recipient", "recipient_id"),
		Index("ix_erp_social_notif_activity", "activity_id"),
		Index("ix_erp_social_notif_tenant", "tenant_id"),
		Index("ix_erp_social_notif_unread", "recipient_id", "is_read"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	recipient_id = Column(
		UUID(as_uuid=False),
		ForeignKey("erp_social_actor.id", ondelete="CASCADE"),
		nullable=False,
	)
	activity_id = Column(
		UUID(as_uuid=False),
		ForeignKey("erp_social_activity.id", ondelete="CASCADE"),
		nullable=False,
	)
	notification_type = Column(
		String(10),
		nullable=False,
		comment="FOLLOW | MENTION | BOOST | REACTION | REPLY | DIRECT",
	)
	is_read = Column(Boolean, nullable=False, default=False)
	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	recipient = relationship("Actor", foreign_keys=[recipient_id], backref="notifications")
	activity = relationship("SocialActivity", backref="notifications")

	def __repr__(self) -> str:
		return (
			f"<Notification {self.id!r} type={self.notification_type!r}"
			f" recipient={self.recipient_id!r} read={self.is_read}>"
		)


__all__ = [
	"Actor",
	"SocialActivity",
	"Post",
	"Follow",
	"Reaction",
	"Notification",
]
