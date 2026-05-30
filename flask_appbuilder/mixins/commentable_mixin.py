"""
commentable_mixin.py

Comprehensive CommentableMixin for hierarchical commenting on SQLAlchemy models
in Flask-AppBuilder applications.

Supports hierarchical comments, editing, moderation, voting, and advanced queries.
Compatible with SQLAlchemy 2.x (mapped_column/Mapped) with 1.x fallback.

Author: Nyimbi Odero
Date: 25/08/2024
Version: 2.0
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from flask import current_app
from flask_appbuilder import Model
from flask_login import current_user
from sqlalchemy import (
	Boolean,
	DateTime,
	ForeignKey,
	Integer,
	String,
	Text,
	UniqueConstraint,
	event,
	func,
	select,
	text,
)
from sqlalchemy.ext.mutable import MutableDict

# SQLAlchemy 2.x mapped_column/Mapped with 1.x fallback
try:
	from sqlalchemy.orm import Mapped, mapped_column
	_SA2 = True
except ImportError:
	_SA2 = False

# JSONB is PostgreSQL-specific; fall back to JSON for other backends
try:
	from sqlalchemy.dialects.postgresql import JSONB as _JSONType
except ImportError:
	from sqlalchemy import JSON as _JSONType  # type: ignore[assignment]

from sqlalchemy.orm import backref, declared_attr, relationship

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
	"""Timezone-aware UTC timestamp."""
	return datetime.now(timezone.utc)


class CommentableMixin:
	"""
	Mixin that adds hierarchical commenting to any SQLAlchemy/FAB model.

	Class-level knobs:
	    __commentable__        – master on/off switch (default True)
	    __comment_moderation__ – require moderator approval before comments appear
	    __max_comment_depth__  – maximum reply nesting depth (default 3)
	"""

	__commentable__: bool = True
	__comment_moderation__: bool = False
	__max_comment_depth__: int = 3

	# ------------------------------------------------------------------ #
	# Relationship                                                         #
	# ------------------------------------------------------------------ #

	@declared_attr
	def comments(cls):  # noqa: N805
		return relationship(
			"Comment",
			back_populates="parent",
			cascade="all, delete-orphan",
			primaryjoin=(
				f"and_("
				f"Comment.parent_id==cast({cls.__name__}.id, String), "
				f"Comment.parent_type=='{cls.__name__}'"
				f")"
			),
			order_by="Comment.created_at.desc()",
			lazy="dynamic",
		)

	# ------------------------------------------------------------------ #
	# Instance methods                                                     #
	# ------------------------------------------------------------------ #

	def add_comment(
		self,
		content: str,
		user=None,
		parent_comment_id: int | None = None,
		metadata: dict[str, Any] | None = None,
	) -> "Comment":
		"""
		Add a comment (or threaded reply) to this instance.

		Args:
		    content:           Comment body (max 10 000 chars).
		    user:              Author; defaults to flask_login current_user.
		    parent_comment_id: Non-null makes this a reply to that comment.
		    metadata:          Arbitrary JSON payload stored alongside the comment.

		Returns:
		    The newly persisted Comment instance.

		Raises:
		    ValueError:      Commenting disabled, empty/oversized content, depth exceeded.
		    PermissionError: Unauthenticated caller.
		"""
		if not self.__commentable__:
			raise ValueError("Commenting is not enabled for this model")

		if not content or not content.strip():
			raise ValueError("Comment content cannot be empty")

		if len(content) > 10_000:
			raise ValueError("Comment exceeds maximum length of 10 000 characters")

		if user is None:
			user = current_user
		if not user or not user.is_authenticated:
			raise PermissionError("Must be authenticated to comment")

		session = current_app.db.session

		try:
			depth = 0
			if parent_comment_id is not None:
				parent_comment = session.get(Comment, parent_comment_id)
				if parent_comment is None:
					raise ValueError("Parent comment not found")
				if parent_comment.depth >= self.__max_comment_depth__:
					raise ValueError(
						f"Maximum comment depth of {self.__max_comment_depth__} exceeded"
					)
				if parent_comment.parent_id != str(self.id):
					raise ValueError("Parent comment belongs to a different parent object")
				depth = parent_comment.depth + 1

			comment = Comment(
				content=content.strip(),
				user_id=user.id,
				parent_id=str(self.id),
				parent_type=self.__class__.__name__,
				parent_comment_id=parent_comment_id,
				is_approved=not self.__comment_moderation__,
				depth=depth,
				comment_metadata=metadata or {},
			)

			event.listen(Comment, "before_insert", self._on_comment_create)

			session.add(comment)
			session.commit()

			logger.info(
				"Comment added: %s by user %s on %s:%s",
				comment.id,
				user.id,
				self.__class__.__name__,
				self.id,
			)
			return comment

		except Exception:
			session.rollback()
			logger.exception("Error adding comment")
			raise

	def get_comments(
		self,
		include_unapproved: bool = False,
		limit: int | None = None,
		offset: int | None = None,
		include_replies: bool = True,
		user=None,
		sort_by: str = "created_at",
		sort_dir: str = "desc",
	) -> list["Comment"]:
		"""
		Return comments for this instance.

		Args:
		    include_unapproved: Include comments pending moderation.
		    limit:              Cap on results (applied after offset).
		    offset:             Skip this many results.
		    include_replies:    When False, only top-level comments are returned.
		    user:               Restrict to a single author.
		    sort_by:            Comment attribute name to sort by.
		    sort_dir:           'asc' or 'desc'.

		Returns:
		    List of Comment instances.
		"""
		try:
			query = self.comments

			if not include_unapproved:
				query = query.filter(Comment.is_approved.is_(True))
			if not include_replies:
				query = query.filter(Comment.parent_comment_id.is_(None))
			if user is not None:
				query = query.filter(Comment.user_id == user.id)

			sort_col = getattr(Comment, sort_by, Comment.created_at)
			query = (
				query.order_by(sort_col.desc())
				if sort_dir.lower() == "desc"
				else query.order_by(sort_col.asc())
			)

			if offset is not None:
				query = query.offset(offset)
			if limit is not None:
				query = query.limit(limit)

			return query.all()

		except Exception:
			logger.exception("Error retrieving comments")
			return []

	def delete_comment(
		self,
		comment_id: int,
		user=None,
		force: bool = False,
	) -> bool:
		"""
		Delete a comment owned by this instance.

		Permission rules:
		    - Comment owner may always delete their own comment.
		    - Moderator role may delete any comment.
		    - Admin role may delete any comment when ``force=True``.

		Returns:
		    True on success, False if the comment was not found / doesn't belong here.

		Raises:
		    PermissionError: Caller lacks deletion rights.
		"""
		session = current_app.db.session

		try:
			comment = session.get(Comment, comment_id)
			if (
				comment is None
				or comment.parent_id != str(self.id)
				or comment.parent_type != self.__class__.__name__
			):
				return False

			if user is None:
				user = current_user
			if not user or not user.is_authenticated:
				raise PermissionError("Must be authenticated to delete comments")

			can_delete = (
				user.id == comment.user_id
				or user.has_role("Moderator")
				or (force and user.has_role("Admin"))
			)
			if not can_delete:
				raise PermissionError("Insufficient permissions to delete this comment")

			event.listen(Comment, "before_delete", self._on_comment_delete)

			session.delete(comment)
			session.commit()

			logger.info("Comment %s deleted by user %s", comment_id, user.id)
			return True

		except Exception:
			session.rollback()
			logger.exception("Error deleting comment %s", comment_id)
			raise

	def update_comment(
		self,
		comment_id: int,
		new_content: str,
		user=None,
		metadata: dict[str, Any] | None = None,
	) -> bool:
		"""
		Replace the content of an existing comment.

		Only the comment owner or an Admin may update a comment.

		Returns:
		    True on success, False if the comment was not found / doesn't belong here.

		Raises:
		    ValueError:      Empty or oversized content.
		    PermissionError: Caller lacks update rights.
		"""
		if not new_content or not new_content.strip():
			raise ValueError("Comment content cannot be empty")
		if len(new_content) > 10_000:
			raise ValueError("Comment exceeds maximum length of 10 000 characters")

		session = current_app.db.session

		try:
			comment = session.get(Comment, comment_id)
			if (
				comment is None
				or comment.parent_id != str(self.id)
				or comment.parent_type != self.__class__.__name__
			):
				return False

			if user is None:
				user = current_user
			if not user or not user.is_authenticated:
				raise PermissionError("Must be authenticated to update comments")
			if not (user.id == comment.user_id or user.has_role("Admin")):
				raise PermissionError("Insufficient permissions to update this comment")

			original_content = comment.content

			comment.content = new_content.strip()
			comment.updated_at = _utcnow()
			if metadata:
				comment.comment_metadata.update(metadata)

			event.listen(
				Comment,
				"before_update",
				lambda target, value, oldvalue, initiator: self._on_comment_update(
					target, original_content
				),
			)

			session.commit()

			logger.info("Comment %s updated by user %s", comment_id, user.id)
			return True

		except Exception:
			session.rollback()
			logger.exception("Error updating comment %s", comment_id)
			raise

	def approve_comment(self, comment_id: int, user=None) -> bool:
		"""
		Approve a pending comment (only meaningful when moderation is enabled).

		Requires the caller to hold the Moderator role.

		Returns:
		    True on success (or if already approved), False if comment not found.

		Raises:
		    PermissionError: Caller is not a moderator.
		"""
		if not self.__comment_moderation__:
			return False

		session = current_app.db.session

		try:
			comment = session.get(Comment, comment_id)
			if (
				comment is None
				or comment.parent_id != str(self.id)
				or comment.parent_type != self.__class__.__name__
			):
				return False

			if user is None:
				user = current_user
			if not user or not user.is_authenticated or not user.has_role("Moderator"):
				raise PermissionError("Must be a moderator to approve comments")

			if comment.is_approved:
				return True

			comment.is_approved = True
			comment.approved_by_id = user.id
			comment.approved_at = _utcnow()

			event.listen(Comment, "before_update", self._on_comment_approve)

			session.commit()

			logger.info("Comment %s approved by user %s", comment_id, user.id)
			return True

		except Exception:
			session.rollback()
			logger.exception("Error approving comment %s", comment_id)
			raise

	def vote_comment(
		self,
		comment_id: int,
		vote_type: str,
		user=None,
	) -> bool:
		"""
		Record an upvote or downvote on a comment.

		Voting on the same comment twice with the same ``vote_type`` removes the vote
		(toggle behaviour).  Changing vote type flips it.  Users cannot vote on
		their own comments.

		Args:
		    comment_id: Target comment.
		    vote_type:  'up' or 'down'.
		    user:       Voter; defaults to current_user.

		Returns:
		    True on success, False if comment not found / doesn't belong here.

		Raises:
		    ValueError:      Invalid vote_type.
		    PermissionError: Unauthenticated caller or self-vote attempt.
		"""
		if vote_type not in ("up", "down"):
			raise ValueError("vote_type must be 'up' or 'down'")

		session = current_app.db.session

		try:
			comment = session.get(Comment, comment_id)
			if (
				comment is None
				or comment.parent_id != str(self.id)
				or comment.parent_type != self.__class__.__name__
			):
				return False

			if user is None:
				user = current_user
			if not user or not user.is_authenticated:
				raise PermissionError("Must be authenticated to vote")
			if user.id == comment.user_id:
				raise PermissionError("Cannot vote on your own comments")

			vote = session.execute(
				select(CommentVote).where(
					CommentVote.comment_id == comment_id,
					CommentVote.user_id == user.id,
				)
			).scalar_one_or_none()

			if vote is not None:
				if vote.vote_type == vote_type:
					# Toggle off
					session.delete(vote)
				else:
					vote.vote_type = vote_type
			else:
				session.add(
					CommentVote(
						comment_id=comment_id,
						user_id=user.id,
						vote_type=vote_type,
					)
				)

			session.commit()

			logger.info("Vote '%s' recorded on comment %s by user %s", vote_type, comment_id, user.id)
			return True

		except Exception:
			session.rollback()
			logger.exception("Error recording vote on comment %s", comment_id)
			raise

	# ------------------------------------------------------------------ #
	# Class methods                                                        #
	# ------------------------------------------------------------------ #

	@classmethod
	def get_most_commented(
		cls,
		limit: int = 10,
		include_unapproved: bool = False,
		since: datetime | None = None,
	) -> list[tuple]:
		"""
		Return the most-commented instances of this model, ordered by comment count desc.

		Args:
		    limit:             Maximum results.
		    include_unapproved: Count pending comments too.
		    since:             Only count comments created on/after this timestamp.

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
					& (Comment.parent_type == cls.__name__),
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
			logger.exception("Error fetching most-commented %s instances", cls.__name__)
			return []

	@classmethod
	def get_recently_commented(
		cls,
		limit: int = 10,
		include_unapproved: bool = False,
	) -> list[tuple]:
		"""
		Return instances ordered by the timestamp of their most recent comment.

		Args:
		    limit:             Maximum results.
		    include_unapproved: Include pending comments in recency calculation.

		Returns:
		    List of (model_instance, most_recent_comment) tuples.
		"""
		try:
			session = current_app.db.session

			latest_sq = (
				select(
					Comment.parent_id,
					func.max(Comment.created_at).label("max_created_at"),
				)
				.where(Comment.parent_type == cls.__name__)
			)
			if not include_unapproved:
				latest_sq = latest_sq.where(Comment.is_approved.is_(True))
			latest_sq = latest_sq.group_by(Comment.parent_id).subquery()

			stmt = (
				select(cls, Comment)
				.join(latest_sq, func.cast(cls.id, String) == latest_sq.c.parent_id)
				.join(
					Comment,
					(Comment.parent_id == latest_sq.c.parent_id)
					& (Comment.created_at == latest_sq.c.max_created_at),
				)
				.order_by(latest_sq.c.max_created_at.desc())
				.limit(limit)
			)

			return list(session.execute(stmt).all())

		except Exception:
			logger.exception("Error fetching recently-commented %s instances", cls.__name__)
			return []

	# ------------------------------------------------------------------ #
	# Event hooks (override in subclasses)                                #
	# ------------------------------------------------------------------ #

	def _on_comment_create(self, mapper, connection, target) -> None:
		"""Called before a new Comment is inserted.  Override to add side-effects."""

	def _on_comment_update(self, target, original_content: str) -> None:
		"""Called before a Comment is updated.  ``original_content`` is the old text."""

	def _on_comment_delete(self, mapper, connection, target) -> None:
		"""Called before a Comment is deleted.  Override for cleanup logic."""

	def _on_comment_approve(self, mapper, connection, target) -> None:
		"""Called before a Comment is approved.  Override for notification logic."""


# ======================================================================= #
# Supporting models                                                        #
# ======================================================================= #

class Comment(Model):
	"""
	Polymorphic comment record.  ``parent_id`` / ``parent_type`` identify the
	owning model instance; ``parent_comment_id`` creates the reply tree.

	Columns use the ``nx_comments`` table so they don't collide with any
	application-defined "comments" table.
	"""

	__tablename__ = "nx_comments"

	id = Column(Integer, primary_key=True)
	content = Column(Text, nullable=False)
	created_at = Column(
		DateTime(timezone=True),
		default=_utcnow,
		nullable=False,
	)
	updated_at = Column(
		DateTime(timezone=True),
		default=_utcnow,
		onupdate=_utcnow,
		nullable=False,
	)
	user_id = Column(Integer, ForeignKey("ab_user.id"), nullable=False)
	parent_id = Column(String, nullable=False)
	parent_type = Column(String(100), nullable=False)
	parent_comment_id = Column(Integer, ForeignKey("nx_comments.id"), nullable=True)
	is_approved = Column(Boolean, default=True, nullable=False)
	depth = Column(Integer, default=0, nullable=False)
	# Column renamed from 'metadata' to avoid collision with SQLAlchemy's
	# internal .metadata attribute on declarative base classes.
	comment_metadata = Column(
		MutableDict.as_mutable(_JSONType),
		default=dict,
		nullable=False,
	)
	approved_by_id = Column(Integer, ForeignKey("ab_user.id"), nullable=True)
	approved_at = Column(DateTime(timezone=True), nullable=True)

	# Relationships
	user = relationship("User", foreign_keys=[user_id], backref="comments")
	approved_by = relationship(
		"User", foreign_keys=[approved_by_id], backref="approved_comments"
	)
	replies = relationship(
		"Comment",
		backref=backref("parent_comment", remote_side=[id]),
		cascade="all, delete-orphan",
	)
	votes = relationship(
		"CommentVote",
		backref="comment",
		cascade="all, delete-orphan",
	)

	__table_args__ = (
		UniqueConstraint(
			"parent_id",
			"parent_type",
			"parent_comment_id",
			name="uq_comment_parent",
		),
	)

	# ------------------------------------------------------------------ #
	# Computed properties                                                  #
	# ------------------------------------------------------------------ #

	@property
	def vote_count(self) -> int:
		"""Net score: upvotes minus downvotes."""
		return sum(1 if v.vote_type == "up" else -1 for v in self.votes)

	@property
	def upvotes(self) -> int:
		"""Raw upvote count."""
		return sum(1 for v in self.votes if v.vote_type == "up")

	@property
	def downvotes(self) -> int:
		"""Raw downvote count."""
		return sum(1 for v in self.votes if v.vote_type == "down")

	def __repr__(self) -> str:
		return (
			f"<Comment {self.id} by User {self.user_id}"
			f" on {self.parent_type}:{self.parent_id}>"
		)


class CommentVote(Model):
	"""
	Single user vote on a comment.  Unique constraint on (comment_id, user_id)
	enforces one-vote-per-user; toggling is handled in CommentableMixin.vote_comment.
	"""

	__tablename__ = "nx_comment_votes"

	id = Column(Integer, primary_key=True)
	comment_id = Column(Integer, ForeignKey("nx_comments.id"), nullable=False)
	user_id = Column(Integer, ForeignKey("ab_user.id"), nullable=False)
	vote_type = Column(String(4), nullable=False)  # 'up' | 'down'
	created_at = Column(
		DateTime(timezone=True),
		default=_utcnow,
		nullable=False,
	)
	vote_metadata = Column(
		MutableDict.as_mutable(_JSONType),
		default=dict,
		nullable=False,
	)

	__table_args__ = (
		UniqueConstraint("comment_id", "user_id", name="uq_comment_vote"),
	)

	def __repr__(self) -> str:
		return (
			f"<CommentVote {self.id} [{self.vote_type}]"
			f" by User {self.user_id} on Comment {self.comment_id}>"
		)
