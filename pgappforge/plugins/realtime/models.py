"""Real-Time Collaboration models.

Provides lightweight presence and advisory field-lock tables that back the
PG LISTEN/NOTIFY collaboration layer.  These are separate from the heavier
CollaborationSession / CollaborationEvent models in __init__.py which are
session-scoped and audit-focused.

Tables
------
pgaf_presence   — who is viewing / editing which record right now
pgaf_field_lock — advisory per-field edit locks with expiry
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
	Column,
	DateTime,
	ForeignKey,
	Integer,
	String,
	UniqueConstraint,
)
from pgappforge.models.sqla import Model


class PresenceSession(Model):
	"""Tracks who is viewing or editing which record.

	One row per (user, model_name, entity_id) tuple.  Kept fresh by the
	client heartbeat (POST /realtime/api/presence every
	FAB_REALTIME_HEARTBEAT_INTERVAL seconds).  Rows older than
	heartbeat_interval × 3 are treated as stale and excluded from presence
	queries.
	"""

	__tablename__ = "pgaf_presence"
	__table_args__ = (
		UniqueConstraint("user_id", "model_name", "entity_id",
		                 name="uq_pgaf_presence_user_model_entity"),
		{"extend_existing": True},
	)

	id = Column(Integer, primary_key=True)
	user_id = Column(
		Integer,
		ForeignKey("ab_user.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)
	# 256-bit random token issued on first heartbeat; re-used by the client
	# on subsequent pings to identify its own session row.
	session_token = Column(String(64), nullable=False, unique=True)
	# Dotted or simple model class name, e.g. "Invoice"
	model_name = Column(String(255), index=True)
	# String representation of the record PK
	entity_id = Column(String(64), index=True)
	# Which form field the user currently has focused (nullable)
	editing_field = Column(String(255))
	last_seen = Column(
		DateTime(timezone=True),
		default=lambda: datetime.now(timezone.utc),
		nullable=False,
		index=True,
	)

	def __repr__(self) -> str:
		return (
			f"<PresenceSession id={self.id} user={self.user_id} "
			f"model={self.model_name} entity={self.entity_id}>"
		)


class FieldLock(Model):
	"""Advisory lock on a specific field for a record.

	At most one lock row per (model_name, entity_id, field_name).  Locks
	expire automatically after FAB_REALTIME_LOCK_TIMEOUT seconds; an
	expired lock is treated as unowned and can be taken by any user.
	"""

	__tablename__ = "pgaf_field_lock"
	__table_args__ = (
		UniqueConstraint("model_name", "entity_id", "field_name",
		                 name="uq_pgaf_field_lock_model_entity_field"),
		{"extend_existing": True},
	)

	id = Column(Integer, primary_key=True)
	model_name = Column(String(255), nullable=False)
	entity_id = Column(String(64), nullable=False)
	field_name = Column(String(255), nullable=False)
	user_id = Column(
		Integer,
		ForeignKey("ab_user.id", ondelete="CASCADE"),
		nullable=False,
	)
	locked_at = Column(
		DateTime(timezone=True),
		default=lambda: datetime.now(timezone.utc),
	)
	# Indexed — used by sweep queries and expiry checks
	expires_at = Column(DateTime(timezone=True), nullable=False, index=True)

	def __repr__(self) -> str:
		return (
			f"<FieldLock id={self.id} model={self.model_name} "
			f"entity={self.entity_id} field={self.field_name} user={self.user_id}>"
		)
