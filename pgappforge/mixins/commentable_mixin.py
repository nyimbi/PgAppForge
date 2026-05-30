"""
commentable_mixin.py

CommentableMixin — hierarchical commenting for SQLAlchemy/FAB models.

New in v3.0:
  - Unlimited nesting via closure-table adjacency (depth + path columns)
  - @mention extraction and storage (parsed from content at insert time)
  - Emoji reactions (distinct from up/down votes)
  - Moderation queue with bulk-approve helpers and soft-delete / restore
  - Full-text search on comment body via PostgreSQL tsvector/GIN or
    SQLite FTS5 fallback using a hybrid search helper
  - Per-comment edit history ledger (CommentRevision)
  - Structured indexes: GIN on tsvector, BTREE on (parent_type, parent_id),
    GIN on mentions JSONB array

Author: Nyimbi Odero
Version: 3.0
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from flask import current_app
from pgappforge import Model
from sqlalchemy import (
	Boolean,
	DateTime,
	ForeignKey,
	Index,
	Integer,
	String,
	Text,
	UniqueConstraint,
	func,
	select,
	text,
)
from sqlalchemy.ext.mutable import MutableDict, MutableList
from sqlalchemy.orm import backref, declared_attr, relationship

# SQLAlchemy 2.x mapped_column / Mapped — required, no 1.x fallback
from sqlalchemy.orm import Mapped, mapped_column

# JSONB is PostgreSQL-specific; fall back to JSON for SQLite/MySQL
try:
	from sqlalchemy.dialects.postgresql import JSONB as _JSONType
	from sqlalchemy.dialects.postgresql import TSVECTOR as _TSVector
	_PG = True
except ImportError:
	from sqlalchemy import JSON as _JSONType  # type: ignore[assignment]
	_TSVector = None  # type: ignore[assignment]
	_PG = False

from sqlalchemy.ext.mutable import MutableDict

if TYPE_CHECKING:
	pass

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Mention regex: matches @username tokens (alphanumeric + underscores, 1-64 chars)
# ---------------------------------------------------------------------------
_MENTION_RE = re.compile(r"@([A-Za-z0-9_]{1,64})")

# ---------------------------------------------------------------------------
# Reaction emoji whitelist (keeps the reactions column bounded)
# ---------------------------------------------------------------------------
_ALLOWED_REACTIONS: frozenset[str] = frozenset(
	["👍", "👎", "❤️", "😂", "😮", "😢", "🎉", "🚀", "👀", "🔥"]
)

_MAX_CONTENT_LEN = 10_000


def _utcnow() -> datetime:
	"""Timezone-aware UTC timestamp."""
	return datetime.now(timezone.utc)


def _extract_mentions(content: str) -> list[str]:
	"""Return de-duplicated list of @mention usernames found in *content*."""
	return list(dict.fromkeys(m.lower() for m in _MENTION_RE.findall(content)))


class CommentableMixin:
	"""
	Mixin that adds a full-featured threaded comment system to any FAB model.

	Usage
	-----
	.. code-block:: python

	    class Article(Model, CommentableMixin):
	        __tablename__ = "articles"
	        id = Column(Integer, primary_key=True)
	        title = Column(String(255))

	Class-level knobs (set on the host model)
	------------------------------------------
	__commentable__          bool   Master on/off switch (default True).
	__comment_moderation__   bool   Require moderator approval before comments
	                                appear to non-moderators (default False).
	__max_comment_depth__    int    Maximum reply nesting depth; 0 = flat
	                                (default 10, practical max ~50).
	__comment_reactions__    bool   Enable emoji reactions (default True).

	What's new in v3.0 vs v2.0
	---------------------------
	* @mention extraction — stored as JSONB array, queryable, indexed.
	* Emoji reactions — separate CommentReaction table, per-user-per-emoji unique.
	* Soft-delete / restore — ``is_deleted`` flag; content replaced with
	  tombstone text; replies are preserved.
	* Edit history — every content change appended to CommentRevision ledger.
	* Full-text search — ``search_comments()`` uses PostgreSQL tsvector GIN
	  index when available; falls back to SQL LIKE on other backends.
	* Moderation helpers — ``reject_comment()``, ``bulk_approve()``.
	* Computed ``path`` column — slash-delimited ancestor-id chain enabling
	  efficient subtree queries without recursive CTEs.
	* ``get_thread()`` — returns a flat list ordered for threaded display
	  (DFS pre-order by path).
	* Reaction aggregates — ``get_reaction_counts()`` on any comment instance.
	"""

	__commentable__: bool = True
	__comment_moderation__: bool = False
	__max_comment_depth__: int = 10
	__comment_reactions__: bool = True

	# ------------------------------------------------------------------ #
	# Relationship (declared_attr so it binds to each concrete model)     #
	# ------------------------------------------------------------------ #

	@declared_attr
	def comments(cls):  # noqa: N805
		"""
		Dynamic relationship to Comment filtered by parent_type == cls.__name__.
		Use .add_comment() / .get_comments() rather than accessing this directly.
		"""
		return relationship(
			"Comment",
			primaryjoin=(
				f"and_("
				f"foreign(Comment.parent_id)==cast({cls.__name__}.id, String),"
				f"Comment.parent_type=='{cls.__name__}'"
				f")"
			),
			order_by="Comment.path.asc()",
			lazy="dynamic",
			viewonly=True,
			overlaps="comments",
		)

	# ------------------------------------------------------------------ #
	# Core mutating methods                                               #
	# ------------------------------------------------------------------ #

	def add_comment(
		self,
		content: str,
		user=None,
		parent_comment_id: int | None = None,
		extra: dict[str, Any] | None = None,
	) -> "Comment":
		"""
		Create and persist a new comment (or threaded reply) on this instance.

		Args:
		    content:           Comment body; stripped; max 10 000 chars.
		    user:              Author; defaults to flask_login current_user.
		    parent_comment_id: Attach as reply to this comment id.
		    extra:             Arbitrary JSONB payload stored alongside the comment.

		Returns:
		    The newly persisted Comment instance.

		Raises:
		    ValueError:      Commenting disabled / bad content / depth exceeded.
		    PermissionError: Unauthenticated caller.
		"""
		if not self.__commentable__:
			raise ValueError("Commenting is disabled for this model")

		content = (content or "").strip()
		if not content:
			raise ValueError("Comment content cannot be empty")
		if len(content) > _MAX_CONTENT_LEN:
			raise ValueError(f"Comment exceeds {_MAX_CONTENT_LEN} characters")

		user = _resolve_user(user)

		session = current_app.db.session

		try:
			depth = 0
			path_prefix = ""

			if parent_comment_id is not None:
				parent_comment = session.get(Comment, parent_comment_id)
				if parent_comment is None:
					raise ValueError(f"Parent comment {parent_comment_id} not found")
				if parent_comment.parent_id != str(self.id) or parent_comment.parent_type != self.__class__.__name__:
					raise ValueError("Parent comment belongs to a different object")
				if parent_comment.depth >= self.__max_comment_depth__:
					raise ValueError(
						f"Maximum comment depth of {self.__max_comment_depth__} exceeded"
					)
				depth = parent_comment.depth + 1
				path_prefix = parent_comment.path + "/"

			mentions = _extract_mentions(content)

			comment = Comment(
				content=content,
				user_id=user.id,
				parent_id=str(self.id),
				parent_type=self.__class__.__name__,
				parent_comment_id=parent_comment_id,
				is_approved=not self.__comment_moderation__,
				depth=depth,
				mentions=mentions,
				extra=extra or {},
				# path is set after flush so we have the PK
			)

			session.add(comment)
			session.flush()  # assign comment.id without committing

			# Build path: root comment → "42", reply → "42/99"
			comment.path = path_prefix + str(comment.id)

			# Update tsvector if PostgreSQL
			if _PG:
				comment.search_vector = func.to_tsvector("english", content)

			session.commit()

			self._on_comment_create(comment, mentions)

			logger.info(
				"comment.added id=%s user=%s target=%s:%s depth=%s mentions=%s",
				comment.id, user.id, self.__class__.__name__, self.id, depth, mentions,
			)
			return comment

		except Exception:
			session.rollback()
			raise

	def get_comments(
		self,
		*,
		include_unapproved: bool = False,
		include_deleted: bool = False,
		limit: int | None = None,
		offset: int | None = None,
		top_level_only: bool = False,
		author_id: int | None = None,
		sort_by: str = "path",
		sort_dir: str = "asc",
	) -> list["Comment"]:
		"""
		Return comments for this instance.

		Args:
		    include_unapproved: Include comments pending moderation.
		    include_deleted:    Include soft-deleted comments.
		    limit:              Cap on results.
		    offset:             Skip this many results.
		    top_level_only:     Only root-level comments (no replies).
		    author_id:          Filter by a specific author user id.
		    sort_by:            Column name; 'path' gives correct threaded order.
		    sort_dir:           'asc' or 'desc'.

		Returns:
		    List of Comment rows; empty list on error.
		"""
		try:
			q = self.comments
			if not include_unapproved:
				q = q.filter(Comment.is_approved.is_(True))
			if not include_deleted:
				q = q.filter(Comment.is_deleted.is_(False))
			if top_level_only:
				q = q.filter(Comment.parent_comment_id.is_(None))
			if author_id is not None:
				q = q.filter(Comment.user_id == author_id)

			sort_col = getattr(Comment, sort_by, Comment.path)
			q = q.order_by(sort_col.desc() if sort_dir == "desc" else sort_col.asc())

			if offset:
				q = q.offset(offset)
			if limit:
				q = q.limit(limit)

			return q.all()

		except Exception:
			logger.exception("get_comments failed for %s:%s", self.__class__.__name__, self.id)
			return []

	def get_thread(self, root_comment_id: int) -> list["Comment"]:
		"""
		Return all comments in the subtree rooted at *root_comment_id*, in
		DFS pre-order (path ASC).  Efficient: single query using path prefix.

		Args:
		    root_comment_id: ID of the comment whose subtree to fetch.

		Returns:
		    Ordered flat list suitable for threaded rendering.
		"""
		session = current_app.db.session
		root = session.get(Comment, root_comment_id)
		if root is None or root.parent_id != str(self.id):
			return []

		stmt = (
			select(Comment)
			.where(
				Comment.parent_type == self.__class__.__name__,
				Comment.parent_id == str(self.id),
				Comment.path.like(root.path + "%"),
			)
			.order_by(Comment.path.asc())
		)
		return list(session.execute(stmt).scalars())

	def search_comments(
		self,
		query: str,
		*,
		include_deleted: bool = False,
		limit: int = 50,
	) -> list["Comment"]:
		"""
		Full-text search on comment content scoped to this instance.

		On PostgreSQL: uses the tsvector GIN index via ``to_tsquery``.
		On other backends: falls back to ``LIKE %query%`` (no stemming).

		Args:
		    query:           Search string.
		    include_deleted: Include soft-deleted tombstones.
		    limit:           Maximum results.

		Returns:
		    List of matching Comment rows ordered by relevance (PG) or
		    creation time (fallback).
		"""
		session = current_app.db.session
		if not query or not query.strip():
			return []

		base = (
			select(Comment)
			.where(
				Comment.parent_type == self.__class__.__name__,
				Comment.parent_id == str(self.id),
			)
		)
		if not include_deleted:
			base = base.where(Comment.is_deleted.is_(False))

		if _PG:
			ts_query = func.plainto_tsquery("english", query)
			stmt = (
				base
				.where(Comment.search_vector.op("@@")(ts_query))
				.order_by(
					func.ts_rank(Comment.search_vector, ts_query).desc()
				)
				.limit(limit)
			)
		else:
			pattern = f"%{query}%"
			stmt = (
				base
				.where(Comment.content.ilike(pattern))
				.order_by(Comment.created_at.desc())
				.limit(limit)
			)

		try:
			return list(session.execute(stmt).scalars())
		except Exception:
			logger.exception("search_comments failed")
			return []

	def search_by_mention(self, username: str, *, limit: int = 50) -> list["Comment"]:
		"""
		Return comments mentioning *username* (case-insensitive) on this instance.

		On PostgreSQL uses the GIN index on the mentions JSONB column.
		On other backends iterates via LIKE on the serialised text (slow on
		large tables — add a generated column if performance matters).

		Args:
		    username: The mention handle to search (without the @ prefix).
		    limit:    Maximum results.

		Returns:
		    List of Comment rows.
		"""
		session = current_app.db.session
		username = username.lower().strip("@")

		try:
			if _PG:
				# JSONB @> operator: very fast with GIN index
				stmt = (
					select(Comment)
					.where(
						Comment.parent_type == self.__class__.__name__,
						Comment.parent_id == str(self.id),
						Comment.is_deleted.is_(False),
						Comment.mentions.cast(_JSONType).op("@>")(f'["{username}"]'),
					)
					.order_by(Comment.created_at.desc())
					.limit(limit)
				)
			else:
				stmt = (
					select(Comment)
					.where(
						Comment.parent_type == self.__class__.__name__,
						Comment.parent_id == str(self.id),
						Comment.is_deleted.is_(False),
						Comment.content.ilike(f"%@{username}%"),
					)
					.order_by(Comment.created_at.desc())
					.limit(limit)
				)
			return list(session.execute(stmt).scalars())
		except Exception:
			logger.exception("search_by_mention failed")
			return []

	def delete_comment(
		self,
		comment_id: int,
		user=None,
		*,
		hard: bool = False,
	) -> bool:
		"""
		Soft-delete (default) or hard-delete a comment.

		Soft-delete replaces content with a tombstone and sets ``is_deleted``
		while preserving the row so child replies keep their path intact.
		Hard-delete cascades to all descendants.

		Permission rules (both modes):
		  - Comment owner may delete their own comment.
		  - Moderator role may delete any comment.
		  - Admin role + hard=True performs an immediate hard delete.

		Returns:
		    True on success, False if comment not found / wrong parent.

		Raises:
		    PermissionError: Caller lacks deletion rights.
		"""
		session = current_app.db.session
		user = _resolve_user(user)

		try:
			comment = session.get(Comment, comment_id)
			if not _belongs_to(comment, self):
				return False

			can_delete = (
				user.id == comment.user_id
				or _has_role(user, "Moderator")
				or _has_role(user, "Admin")
			)
			if not can_delete:
				raise PermissionError("Insufficient permissions to delete this comment")

			if hard and _has_role(user, "Admin"):
				session.delete(comment)
			else:
				comment.is_deleted = True
				comment.content = "[deleted]"
				comment.deleted_at = _utcnow()
				comment.deleted_by_id = user.id

			session.commit()
			self._on_comment_delete(comment, hard=hard)
			logger.info("comment.deleted id=%s by=%s hard=%s", comment_id, user.id, hard)
			return True

		except Exception:
			session.rollback()
			raise

	def restore_comment(self, comment_id: int, original_content: str, user=None) -> bool:
		"""
		Restore a soft-deleted comment.  Requires Moderator or Admin role.

		Args:
		    comment_id:       Comment to restore.
		    original_content: Content to restore (must be supplied by caller
		                      — the mixin does not store content on soft-delete
		                      to avoid retaining flagged material).
		    user:             Actor; defaults to current_user.

		Returns:
		    True on success, False if not found / already active.
		"""
		session = current_app.db.session
		user = _resolve_user(user)

		if not (_has_role(user, "Moderator") or _has_role(user, "Admin")):
			raise PermissionError("Only moderators may restore deleted comments")

		try:
			comment = session.get(Comment, comment_id)
			if not _belongs_to(comment, self) or not comment.is_deleted:
				return False

			comment.is_deleted = False
			comment.content = original_content.strip()
			comment.deleted_at = None
			comment.deleted_by_id = None
			session.commit()
			logger.info("comment.restored id=%s by=%s", comment_id, user.id)
			return True

		except Exception:
			session.rollback()
			raise

	def update_comment(
		self,
		comment_id: int,
		new_content: str,
		user=None,
		extra: dict[str, Any] | None = None,
	) -> bool:
		"""
		Edit a comment's content.  The old content is appended to the
		CommentRevision ledger before the update is applied.

		Only the comment owner or an Admin may edit.

		Returns:
		    True on success, False if not found / wrong parent.

		Raises:
		    ValueError:      Empty or oversized content.
		    PermissionError: Caller lacks edit rights.
		"""
		new_content = (new_content or "").strip()
		if not new_content:
			raise ValueError("Comment content cannot be empty")
		if len(new_content) > _MAX_CONTENT_LEN:
			raise ValueError(f"Comment exceeds {_MAX_CONTENT_LEN} characters")

		session = current_app.db.session
		user = _resolve_user(user)

		try:
			comment = session.get(Comment, comment_id)
			if not _belongs_to(comment, self):
				return False
			if not (user.id == comment.user_id or _has_role(user, "Admin")):
				raise PermissionError("Insufficient permissions to edit this comment")

			# Persist revision before mutating
			revision = CommentRevision(
				comment_id=comment.id,
				content=comment.content,
				edited_by_id=user.id,
			)
			session.add(revision)

			comment.content = new_content
			comment.updated_at = _utcnow()
			comment.mentions = _extract_mentions(new_content)
			comment.edit_count = (comment.edit_count or 0) + 1

			if extra:
				comment.extra.update(extra)

			if _PG:
				comment.search_vector = func.to_tsvector("english", new_content)

			session.commit()
			self._on_comment_update(comment, revision.content)
			logger.info("comment.edited id=%s by=%s revision=%s", comment_id, user.id, revision.id)
			return True

		except Exception:
			session.rollback()
			raise

	# ------------------------------------------------------------------ #
	# Moderation                                                          #
	# ------------------------------------------------------------------ #

	def approve_comment(self, comment_id: int, user=None) -> bool:
		"""
		Approve a single pending comment.

		Requires the Moderator role.  No-op (returns True) if already approved.

		Returns:
		    True on success, False if not found / wrong parent.
		"""
		if not self.__comment_moderation__:
			return False

		session = current_app.db.session
		user = _resolve_user(user)

		if not (_has_role(user, "Moderator") or _has_role(user, "Admin")):
			raise PermissionError("Must hold Moderator role to approve comments")

		try:
			comment = session.get(Comment, comment_id)
			if not _belongs_to(comment, self):
				return False
			if comment.is_approved:
				return True

			comment.is_approved = True
			comment.approved_by_id = user.id
			comment.approved_at = _utcnow()
			session.commit()
			self._on_comment_approve(comment)
			logger.info("comment.approved id=%s by=%s", comment_id, user.id)
			return True

		except Exception:
			session.rollback()
			raise

	def reject_comment(self, comment_id: int, reason: str = "", user=None) -> bool:
		"""
		Reject (and soft-delete) a pending or approved comment.

		Stores the rejection reason in ``comment.extra['rejection_reason']``.
		Requires the Moderator role.

		Returns:
		    True on success, False if not found.
		"""
		session = current_app.db.session
		user = _resolve_user(user)

		if not (_has_role(user, "Moderator") or _has_role(user, "Admin")):
			raise PermissionError("Must hold Moderator role to reject comments")

		try:
			comment = session.get(Comment, comment_id)
			if not _belongs_to(comment, self):
				return False

			comment.is_approved = False
			comment.is_deleted = True
			comment.deleted_at = _utcnow()
			comment.deleted_by_id = user.id
			comment.extra["rejection_reason"] = reason
			comment.content = "[removed]"
			session.commit()
			self._on_comment_reject(comment, reason)
			logger.info("comment.rejected id=%s by=%s reason=%r", comment_id, user.id, reason)
			return True

		except Exception:
			session.rollback()
			raise

	def bulk_approve(self, user=None) -> int:
		"""
		Approve all pending comments for this instance in one query.

		Returns:
		    Number of comments approved.
		"""
		if not self.__comment_moderation__:
			return 0

		session = current_app.db.session
		user = _resolve_user(user)

		if not (_has_role(user, "Moderator") or _has_role(user, "Admin")):
			raise PermissionError("Must hold Moderator role for bulk approve")

		try:
			from sqlalchemy import update as sa_update

			result = session.execute(
				sa_update(Comment)
				.where(
					Comment.parent_type == self.__class__.__name__,
					Comment.parent_id == str(self.id),
					Comment.is_approved.is_(False),
					Comment.is_deleted.is_(False),
				)
				.values(
					is_approved=True,
					approved_by_id=user.id,
					approved_at=_utcnow(),
				)
			)
			session.commit()
			n = result.rowcount
			logger.info("comment.bulk_approved n=%s target=%s:%s by=%s", n, self.__class__.__name__, self.id, user.id)
			return n

		except Exception:
			session.rollback()
			raise

	# ------------------------------------------------------------------ #
	# Reactions                                                           #
	# ------------------------------------------------------------------ #

	def add_reaction(self, comment_id: int, emoji: str, user=None) -> bool:
		"""
		Add or toggle an emoji reaction on a comment.

		Adding the same emoji twice removes it (toggle).  Users may react
		to their own comments.  Reactions are capped to ``_ALLOWED_REACTIONS``.

		Args:
		    comment_id: Target comment.
		    emoji:      One of the allowed emoji strings.
		    user:       Actor; defaults to current_user.

		Returns:
		    True if reaction was added, False if it was removed (toggled off).

		Raises:
		    ValueError:      Reactions disabled or emoji not in whitelist.
		    PermissionError: Unauthenticated caller.
		"""
		if not self.__comment_reactions__:
			raise ValueError("Reactions are disabled for this model")
		if emoji not in _ALLOWED_REACTIONS:
			raise ValueError(f"Emoji '{emoji}' not allowed; choose from {_ALLOWED_REACTIONS}")

		session = current_app.db.session
		user = _resolve_user(user)

		try:
			comment = session.get(Comment, comment_id)
			if not _belongs_to(comment, self):
				raise ValueError(f"Comment {comment_id} not found on this object")

			existing = session.execute(
				select(CommentReaction).where(
					CommentReaction.comment_id == comment_id,
					CommentReaction.user_id == user.id,
					CommentReaction.emoji == emoji,
				)
			).scalar_one_or_none()

			if existing:
				session.delete(existing)
				session.commit()
				return False
			else:
				session.add(CommentReaction(comment_id=comment_id, user_id=user.id, emoji=emoji))
				session.commit()
				return True

		except Exception:
			session.rollback()
			raise

	# ------------------------------------------------------------------ #
	# Voting (up/down — kept from v2, separated from reactions)           #
	# ------------------------------------------------------------------ #

	def vote_comment(
		self,
		comment_id: int,
		vote_type: str,
		user=None,
	) -> bool:
		"""
		Record an upvote or downvote on a comment.

		Toggle behaviour: voting the same type twice removes the vote.
		Changing type flips it.  Users cannot vote on their own comments.

		Args:
		    comment_id: Target comment.
		    vote_type:  'up' or 'down'.
		    user:       Voter; defaults to current_user.

		Returns:
		    True on success, False if comment not found / wrong parent.

		Raises:
		    ValueError:      Invalid vote_type.
		    PermissionError: Self-vote or unauthenticated caller.
		"""
		if vote_type not in ("up", "down"):
			raise ValueError("vote_type must be 'up' or 'down'")

		session = current_app.db.session
		user = _resolve_user(user)

		try:
			comment = session.get(Comment, comment_id)
			if not _belongs_to(comment, self):
				return False
			if user.id == comment.user_id:
				raise PermissionError("Cannot vote on your own comment")

			vote = session.execute(
				select(CommentVote).where(
					CommentVote.comment_id == comment_id,
					CommentVote.user_id == user.id,
				)
			).scalar_one_or_none()

			if vote is not None:
				if vote.vote_type == vote_type:
					session.delete(vote)
				else:
					vote.vote_type = vote_type
			else:
				session.add(CommentVote(comment_id=comment_id, user_id=user.id, vote_type=vote_type))

			session.commit()
			logger.debug("comment.vote type=%s id=%s by=%s", vote_type, comment_id, user.id)
			return True

		except Exception:
			session.rollback()
			raise

	# ------------------------------------------------------------------ #
	# Class-level analytics                                               #
	# ------------------------------------------------------------------ #

	@classmethod
	def get_most_commented(
		cls,
		limit: int = 10,
		*,
		include_unapproved: bool = False,
		since: datetime | None = None,
	) -> list[tuple]:
		"""
		Return the most-commented instances, ordered by comment count descending.

		Returns:
		    List of (model_instance, comment_count) tuples.
		"""
		try:
			session = current_app.db.session
			stmt = (
				select(cls, func.count(Comment.id).label("comment_count"))
				.join(
					Comment,
					(Comment.parent_id == func.cast(cls.id, String))
					& (Comment.parent_type == cls.__name__)
					& Comment.is_deleted.is_(False),
				)
			)
			if not include_unapproved:
				stmt = stmt.where(Comment.is_approved.is_(True))
			if since is not None:
				stmt = stmt.where(Comment.created_at >= since)

			stmt = (
				stmt.group_by(cls)
				.order_by(text("comment_count DESC"))
				.limit(limit)
			)
			return list(session.execute(stmt).all())

		except Exception:
			logger.exception("get_most_commented failed for %s", cls.__name__)
			return []

	@classmethod
	def get_recently_commented(
		cls,
		limit: int = 10,
		*,
		include_unapproved: bool = False,
	) -> list[tuple]:
		"""
		Return instances ordered by their most recent comment timestamp.

		Returns:
		    List of (model_instance, most_recent_comment_datetime) tuples.
		"""
		try:
			session = current_app.db.session

			subq = (
				select(
					Comment.parent_id,
					func.max(Comment.created_at).label("max_ts"),
				)
				.where(
					Comment.parent_type == cls.__name__,
					Comment.is_deleted.is_(False),
				)
			)
			if not include_unapproved:
				subq = subq.where(Comment.is_approved.is_(True))
			subq = subq.group_by(Comment.parent_id).subquery()

			stmt = (
				select(cls, subq.c.max_ts)
				.join(subq, func.cast(cls.id, String) == subq.c.parent_id)
				.order_by(subq.c.max_ts.desc())
				.limit(limit)
			)
			return list(session.execute(stmt).all())

		except Exception:
			logger.exception("get_recently_commented failed for %s", cls.__name__)
			return []

	@classmethod
	def pending_moderation_count(cls) -> int:
		"""Total pending (unapproved, undeleted) comments across all instances of this model."""
		try:
			session = current_app.db.session
			return session.execute(
				select(func.count(Comment.id)).where(
					Comment.parent_type == cls.__name__,
					Comment.is_approved.is_(False),
					Comment.is_deleted.is_(False),
				)
			).scalar_one()
		except Exception:
			logger.exception("pending_moderation_count failed")
			return 0

	# ------------------------------------------------------------------ #
	# Override hooks                                                      #
	# ------------------------------------------------------------------ #

	def _on_comment_create(self, comment: "Comment", mentions: list[str]) -> None:
		"""Called after a comment is committed.  Override to send notifications."""

	def _on_comment_update(self, comment: "Comment", old_content: str) -> None:
		"""Called after a comment edit is committed.  ``old_content`` = previous text."""

	def _on_comment_delete(self, comment: "Comment", *, hard: bool) -> None:
		"""Called after a comment is deleted.  ``hard`` indicates hard vs soft delete."""

	def _on_comment_approve(self, comment: "Comment") -> None:
		"""Called after a comment is approved.  Override for notification logic."""

	def _on_comment_reject(self, comment: "Comment", reason: str) -> None:
		"""Called after a comment is rejected.  Override for notification logic."""


# ======================================================================= #
# Module-level helpers (private)                                           #
# ======================================================================= #

def _resolve_user(user):
	"""Return *user* if supplied, else flask_login current_user; raise if unauth."""
	if user is None:
		try:
			from flask_login import current_user
			user = current_user
		except ImportError:
			raise PermissionError("flask_login not installed; supply user explicitly")

	if not getattr(user, "is_authenticated", False):
		raise PermissionError("Must be authenticated")
	return user


def _belongs_to(comment: "Comment | None", owner) -> bool:
	"""Return True iff *comment* exists and belongs to *owner*."""
	return (
		comment is not None
		and comment.parent_id == str(owner.id)
		and comment.parent_type == owner.__class__.__name__
	)


def _has_role(user, role_name: str) -> bool:
	"""Safe role check; returns False if the user object lacks has_role()."""
	try:
		return bool(user.has_role(role_name))
	except AttributeError:
		return False


# ======================================================================= #
# Supporting models                                                         #
# ======================================================================= #

class Comment(Model):
	"""
	Polymorphic comment row.

	``parent_id`` + ``parent_type`` implement polymorphic ownership without
	requiring a separate join table per host model.

	``path`` stores the slash-delimited chain of ancestor primary keys
	(e.g. "42/99/134") enabling O(1) subtree queries via LIKE prefix.

	``mentions``       — JSONB array of @mentioned usernames (lowercased).
	``search_vector``  — PostgreSQL tsvector; NULL on other backends.
	``edit_count``     — incremented on every successful update_comment().
	``extra``          — arbitrary caller-supplied JSONB payload.
	"""

	__tablename__ = "nx_comments"

	# Primary key
	id: Mapped[int] = mapped_column(Integer, primary_key=True)

	# Content
	content: Mapped[str] = mapped_column(Text, nullable=False)
	path: Mapped[str] = mapped_column(Text, nullable=False, default="", index=True)
	depth: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
	edit_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

	# Timestamps
	created_at: Mapped[datetime] = mapped_column(
		DateTime(timezone=True), nullable=False, default=_utcnow
	)
	updated_at: Mapped[datetime] = mapped_column(
		DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
	)

	# Soft-delete
	is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
	deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
	deleted_by_id: Mapped[int | None] = mapped_column(
		Integer, ForeignKey("ab_user.id"), nullable=True
	)

	# Author
	user_id: Mapped[int] = mapped_column(
		Integer, ForeignKey("ab_user.id"), nullable=False
	)

	# Polymorphic parent
	parent_id: Mapped[str] = mapped_column(Text, nullable=False)
	parent_type: Mapped[str] = mapped_column(String(100), nullable=False)

	# Reply chain
	parent_comment_id: Mapped[int | None] = mapped_column(
		Integer, ForeignKey("nx_comments.id", ondelete="CASCADE"), nullable=True
	)

	# Moderation
	is_approved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
	approved_by_id: Mapped[int | None] = mapped_column(
		Integer, ForeignKey("ab_user.id"), nullable=True
	)
	approved_at: Mapped[datetime | None] = mapped_column(
		DateTime(timezone=True), nullable=True
	)

	# @mentions — JSONB array of lowercased username strings
	mentions: Mapped[list[str]] = mapped_column(
		MutableList.as_mutable(_JSONType),
		nullable=False,
		default=list,
	)

	# Caller-supplied payload
	extra: Mapped[dict[str, Any]] = mapped_column(
		MutableDict.as_mutable(_JSONType),
		nullable=False,
		default=dict,
	)

	# Full-text search (PostgreSQL only; NULL on other engines)
	search_vector = mapped_column(
		_TSVector if _PG else Text,
		nullable=True,
	)

	# Relationships
	author = relationship("User", foreign_keys=[user_id])
	approved_by = relationship("User", foreign_keys=[approved_by_id])
	deleted_by = relationship("User", foreign_keys=[deleted_by_id])

	replies = relationship(
		"Comment",
		backref=backref("parent_comment", remote_side="Comment.id"),
		cascade="all, delete-orphan",
		foreign_keys=[parent_comment_id],
	)
	votes = relationship("CommentVote", back_populates="comment", cascade="all, delete-orphan")
	reactions = relationship("CommentReaction", back_populates="comment", cascade="all, delete-orphan")
	revisions = relationship(
		"CommentRevision",
		back_populates="comment",
		cascade="all, delete-orphan",
		order_by="CommentRevision.created_at.asc()",
	)

	__table_args__ = (
		# Fast lookup of all comments on a given parent object
		Index(
			"ix_nx_comments_parent",
			"parent_type",
			"parent_id",
		),
		# GIN on mentions JSONB for @mention search (PostgreSQL)
		*(
			[Index("ix_nx_comments_mentions_gin", "mentions", postgresql_using="gin")]
			if _PG else []
		),
		# GIN on tsvector for full-text search (PostgreSQL)
		*(
			[Index("ix_nx_comments_fts_gin", "search_vector", postgresql_using="gin")]
			if _PG else []
		),
	)

	# ------------------------------------------------------------------ #
	# Computed properties                                                  #
	# ------------------------------------------------------------------ #

	@property
	def vote_score(self) -> int:
		"""Net vote score: upvotes minus downvotes."""
		return sum(1 if v.vote_type == "up" else -1 for v in self.votes)

	@property
	def upvotes(self) -> int:
		return sum(1 for v in self.votes if v.vote_type == "up")

	@property
	def downvotes(self) -> int:
		return sum(1 for v in self.votes if v.vote_type == "down")

	def get_reaction_counts(self) -> dict[str, int]:
		"""
		Aggregate reaction counts per emoji.

		Returns:
		    Dict mapping emoji → count, sorted by count descending.
		    e.g. {'👍': 12, '❤️': 3}
		"""
		counts: dict[str, int] = {}
		for r in self.reactions:
			counts[r.emoji] = counts.get(r.emoji, 0) + 1
		return dict(sorted(counts.items(), key=lambda kv: kv[1], reverse=True))

	def is_reply(self) -> bool:
		"""True if this comment is a reply to another comment."""
		return self.parent_comment_id is not None

	def ancestor_ids(self) -> list[int]:
		"""Return ordered list of ancestor comment IDs from root down."""
		if not self.path:
			return []
		parts = self.path.split("/")
		# Last element is self; return everything before it
		try:
			return [int(p) for p in parts[:-1]]
		except ValueError:
			return []

	def __repr__(self) -> str:
		return (
			f"<Comment id={self.id} depth={self.depth}"
			f" user={self.user_id} on {self.parent_type}:{self.parent_id}>"
		)


class CommentVote(Model):
	"""
	Single user up/down vote on a comment.

	UniqueConstraint on (comment_id, user_id) enforces one active vote per user.
	Toggling and flipping are handled by CommentableMixin.vote_comment().
	"""

	__tablename__ = "nx_comment_votes"

	id: Mapped[int] = mapped_column(Integer, primary_key=True)
	comment_id: Mapped[int] = mapped_column(
		Integer, ForeignKey("nx_comments.id", ondelete="CASCADE"), nullable=False
	)
	user_id: Mapped[int] = mapped_column(
		Integer, ForeignKey("ab_user.id"), nullable=False
	)
	vote_type: Mapped[str] = mapped_column(String(4), nullable=False)  # 'up' | 'down'
	created_at: Mapped[datetime] = mapped_column(
		DateTime(timezone=True), nullable=False, default=_utcnow
	)

	comment = relationship("Comment", back_populates="votes")

	__table_args__ = (
		UniqueConstraint("comment_id", "user_id", name="uq_nx_comment_vote"),
	)

	def __repr__(self) -> str:
		return f"<CommentVote [{self.vote_type}] user={self.user_id} comment={self.comment_id}>"


class CommentReaction(Model):
	"""
	Single emoji reaction by one user on one comment.

	Unique on (comment_id, user_id, emoji) — a user may place at most one
	reaction of each type per comment.  Toggle by calling add_reaction() twice.
	"""

	__tablename__ = "nx_comment_reactions"

	id: Mapped[int] = mapped_column(Integer, primary_key=True)
	comment_id: Mapped[int] = mapped_column(
		Integer, ForeignKey("nx_comments.id", ondelete="CASCADE"), nullable=False
	)
	user_id: Mapped[int] = mapped_column(
		Integer, ForeignKey("ab_user.id"), nullable=False
	)
	emoji: Mapped[str] = mapped_column(String(12), nullable=False)
	created_at: Mapped[datetime] = mapped_column(
		DateTime(timezone=True), nullable=False, default=_utcnow
	)

	comment = relationship("Comment", back_populates="reactions")

	__table_args__ = (
		UniqueConstraint("comment_id", "user_id", "emoji", name="uq_nx_comment_reaction"),
		Index("ix_nx_comment_reactions_comment", "comment_id"),
	)

	def __repr__(self) -> str:
		return f"<CommentReaction {self.emoji} user={self.user_id} comment={self.comment_id}>"


class CommentRevision(Model):
	"""
	Immutable edit history entry.  One row is appended per successful
	update_comment() call, preserving the *previous* content.

	The revision chain for a comment is ordered by created_at ascending;
	the first row is the original content, the most recent row is the
	content immediately before the current live version.
	"""

	__tablename__ = "nx_comment_revisions"

	id: Mapped[int] = mapped_column(Integer, primary_key=True)
	comment_id: Mapped[int] = mapped_column(
		Integer, ForeignKey("nx_comments.id", ondelete="CASCADE"), nullable=False
	)
	content: Mapped[str] = mapped_column(Text, nullable=False)
	edited_by_id: Mapped[int] = mapped_column(
		Integer, ForeignKey("ab_user.id"), nullable=False
	)
	created_at: Mapped[datetime] = mapped_column(
		DateTime(timezone=True), nullable=False, default=_utcnow
	)

	comment = relationship("Comment", back_populates="revisions")
	editor = relationship("User", foreign_keys=[edited_by_id])

	__table_args__ = (
		Index("ix_nx_comment_revisions_comment", "comment_id"),
	)

	def __repr__(self) -> str:
		return f"<CommentRevision id={self.id} comment={self.comment_id} by={self.edited_by_id}>"
