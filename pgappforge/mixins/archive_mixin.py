"""
archive_mixin.py

ArchiveMixin for SQLAlchemy models in PgForge applications.
Provides soft-archiving: records are hidden without permanent deletion,
with cascading operations, timestamps, bulk archiving, and statistics.

Author: Nyimbi Odero
Version: 2.0 (SQLAlchemy 2.x, Python 3.12+)
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import Boolean, DateTime, Integer, event, select, func
from sqlalchemy.ext.declarative import declared_attr

# ---------------------------------------------------------------------------
# SQLAlchemy 2.x Mapped / mapped_column — fall back to Column for 1.x
# ---------------------------------------------------------------------------
try:
	from sqlalchemy.orm import Mapped, mapped_column
	_SA2 = True
except ImportError:
	from sqlalchemy import Column
	_SA2 = False

# ---------------------------------------------------------------------------
# Flask-SQLAlchemy session accessor — works with both FSA 2.x and 3.x
# ---------------------------------------------------------------------------
try:
	from flask_sqlalchemy import SQLAlchemy as _FSA
	def _get_session():
		from flask import current_app
		ext = current_app.extensions.get("sqlalchemy")
		if ext is None:
			raise RuntimeError("No Flask-SQLAlchemy extension found on current_app")
		# FSA 3.x stores the db object directly; FSA 2.x wraps it in a namedtuple
		db = ext if isinstance(ext, _FSA) else getattr(ext, "db", ext)
		return db.session
except ImportError:
	def _get_session():  # type: ignore[misc]
		raise RuntimeError("flask_sqlalchemy is required")

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helper: tz-aware utcnow
# ---------------------------------------------------------------------------
def _utcnow() -> datetime:
	return datetime.now(tz=timezone.utc)


# ---------------------------------------------------------------------------
# ArchiveMixin
# ---------------------------------------------------------------------------

class ArchiveMixin:
	"""
	Mixin that adds soft-archive semantics to any PgForge model.

	Features:
	- is_archived / archived_at / archived_by_id columns (SQLAlchemy 2.x or 1.x)
	- archive() / unarchive() with optional cascading to related objects
	- archive_old_records() bulk operation keyed off a created_on column
	- get_archive_stats() summary dict
	- get_archived() / get_active() convenience Select helpers
	- SQLAlchemy event hook that blocks writes to archived rows

	Class-level knobs:
	    __archive_cascade__      (list[str])  — relationship attr names to cascade into
	    __allow_archive_update__ (bool)       — allow writes to archived rows (default False)
	    __archive_on_delete__    (bool)       — intercept ORM delete → archive (default True)
	    __created_on_column__    (str)        — column name used by archive_old_records
	                                           (default "created_on")
	"""

	__archive_cascade__: list[str] = []
	__allow_archive_update__: bool = False
	__archive_on_delete__: bool = True
	__created_on_column__: str = "created_on"

	# ------------------------------------------------------------------
	# Columns
	# ------------------------------------------------------------------

	if _SA2:
		@declared_attr
		def is_archived(cls) -> Mapped[bool]:
			return mapped_column(
				Boolean,
				nullable=False,
				default=False,
				index=True,
				server_default="false",
				comment="Indicates if the record is archived",
			)

		@declared_attr
		def archived_at(cls) -> Mapped[datetime | None]:
			return mapped_column(
				DateTime(timezone=True),
				nullable=True,
				index=True,
				comment="Timestamp when record was archived",
			)

		@declared_attr
		def archived_by_id(cls) -> Mapped[int | None]:
			return mapped_column(
				Integer,
				nullable=True,
				index=True,
				comment="ID of user who archived the record",
			)
	else:
		from sqlalchemy import Column as _Column  # noqa: F811

		@declared_attr
		def is_archived(cls):
			return _Column(
				"is_archived",
				Boolean,
				nullable=False,
				default=False,
				index=True,
				server_default="false",
				comment="Indicates if the record is archived",
			)

		@declared_attr
		def archived_at(cls):
			return _Column(
				"archived_at",
				DateTime(timezone=True),
				nullable=True,
				index=True,
				comment="Timestamp when record was archived",
			)

		@declared_attr
		def archived_by_id(cls):
			return _Column(
				"archived_by_id",
				Integer,
				nullable=True,
				index=True,
				comment="ID of user who archived the record",
			)

	# ------------------------------------------------------------------
	# Instance operations
	# ------------------------------------------------------------------

	def archive(self, *, cascade: bool = True, user_id: int | None = None) -> bool:
		"""
		Mark this record as archived.

		Args:
			cascade:  Propagate to related objects listed in __archive_cascade__.
			user_id:  ID of the acting user; stored in archived_by_id.

		Returns:
			True if archived now, False if it was already archived.

		Raises:
			ValueError: On unexpected error during archiving.
		"""
		if self.is_archived:
			return False

		try:
			self.is_archived = True
			self.archived_at = _utcnow()
			self.archived_by_id = user_id

			if cascade:
				self._cascade_archive(action="archive", user_id=user_id)

			return True
		except Exception as exc:
			logger.error("Error archiving %s pk=%s: %s", type(self).__name__, getattr(self, "id", "?"), exc)
			raise ValueError(f"Failed to archive record: {exc}") from exc

	def unarchive(self, *, cascade: bool = True, user_id: int | None = None) -> bool:
		"""
		Restore this record from the archive.

		Args:
			cascade:  Propagate to related objects listed in __archive_cascade__.
			user_id:  ID of the acting user (informational only).

		Returns:
			True if unarchived now, False if it was not archived.

		Raises:
			ValueError: On unexpected error during unarchiving.
		"""
		if not self.is_archived:
			return False

		try:
			self.is_archived = False
			self.archived_at = None
			self.archived_by_id = None

			if cascade:
				self._cascade_archive(action="unarchive", user_id=user_id)

			return True
		except Exception as exc:
			logger.error("Error unarchiving %s pk=%s: %s", type(self).__name__, getattr(self, "id", "?"), exc)
			raise ValueError(f"Failed to unarchive record: {exc}") from exc

	def _cascade_archive(self, *, action: str, user_id: int | None) -> None:
		"""Walk __archive_cascade__ relationships and call archive/unarchive on each."""
		for attr_name in self.__archive_cascade__:
			related = getattr(self, attr_name, None)
			if related is None:
				continue
			targets = related if isinstance(related, list) else [related]
			for obj in targets:
				method = getattr(obj, action, None)
				if callable(method):
					method(cascade=True, user_id=user_id)

	# ------------------------------------------------------------------
	# Class-level queries  (return SQLAlchemy 2.x Select objects)
	# ------------------------------------------------------------------

	@classmethod
	def get_archived(cls):
		"""Return a Select for archived rows of this model."""
		return select(cls).where(cls.is_archived.is_(True))

	@classmethod
	def get_active(cls):
		"""Return a Select for active (non-archived) rows of this model."""
		return select(cls).where(cls.is_archived.is_(False))

	# ------------------------------------------------------------------
	# Bulk operations
	# ------------------------------------------------------------------

	@classmethod
	def archive_old_records(
		cls,
		age_days: int,
		*,
		cascade: bool = True,
		user_id: int | None = None,
	) -> int:
		"""
		Archive records whose creation timestamp is older than age_days.

		Requires the model to have a column named by __created_on_column__
		(default "created_on"). Commits are left to the caller.

		Args:
			age_days:  Records older than this many days are archived.
			cascade:   Cascade the archive operation.
			user_id:   Acting user ID.

		Returns:
			Number of records newly archived.

		Raises:
			AttributeError: If the model lacks the expected timestamp column.
			ValueError:      On unexpected ORM error.
		"""
		created_col = getattr(cls, cls.__created_on_column__, None)
		if created_col is None:
			raise AttributeError(
				f"{cls.__name__} has no column '{cls.__created_on_column__}'. "
				"Set __created_on_column__ to the correct attribute name."
			)

		try:
			session = _get_session()
			cutoff = _utcnow() - timedelta(days=age_days)
			stmt = select(cls).where(
				created_col <= cutoff,
				cls.is_archived.is_(False),
			)
			records = session.execute(stmt).scalars().all()

			count = 0
			for record in records:
				if record.archive(cascade=cascade, user_id=user_id):
					count += 1

			logger.info("Bulk-archived %d %s record(s) older than %d days", count, cls.__name__, age_days)
			return count
		except Exception as exc:
			logger.error("Bulk archive failed for %s: %s", cls.__name__, exc)
			raise ValueError(f"Failed to archive old records: {exc}") from exc

	# ------------------------------------------------------------------
	# Statistics
	# ------------------------------------------------------------------

	@classmethod
	def get_archive_stats(cls) -> dict[str, Any]:
		"""
		Return a summary dict with counts, percentages, and the latest archive event.

		Returns:
			{
			    "total_records": int,
			    "active_records": int,
			    "archived_records": int,
			    "archive_percentage": float,
			    "latest_archive_date": datetime | None,
			    "latest_archive_by": int | None,
			}

		Raises:
			ValueError: On ORM error.
		"""
		try:
			session = _get_session()

			total: int = session.execute(
				select(func.count()).select_from(cls)
			).scalar_one()

			archived: int = session.execute(
				select(func.count()).select_from(cls).where(cls.is_archived.is_(True))
			).scalar_one()

			active = total - archived

			latest_row = session.execute(
				select(cls)
				.where(cls.is_archived.is_(True))
				.order_by(cls.archived_at.desc())
				.limit(1)
			).scalars().first()

			return {
				"total_records": total,
				"active_records": active,
				"archived_records": archived,
				"archive_percentage": round(archived / total * 100, 2) if total else 0.0,
				"latest_archive_date": latest_row.archived_at if latest_row else None,
				"latest_archive_by": latest_row.archived_by_id if latest_row else None,
			}
		except Exception as exc:
			logger.error("get_archive_stats failed for %s: %s", cls.__name__, exc)
			raise ValueError(f"Failed to get archive statistics: {exc}") from exc


# ---------------------------------------------------------------------------
# SQLAlchemy event: block writes to archived rows
# ---------------------------------------------------------------------------

@event.listens_for(ArchiveMixin, "before_update", propagate=True)
def _prevent_update_of_archived_record(mapper, connection, target) -> None:
	"""
	Raise ValueError when any field other than the archive flags themselves
	is modified on an archived row, unless __allow_archive_update__ is True.
	"""
	if not target.is_archived:
		return
	if getattr(target, "__allow_archive_update__", False):
		return

	# Allow the mixin's own archive/unarchive columns to be written
	# (needed so unarchive() can flip is_archived back to False).
	inspection = target.__class__.__mapper__.attrs
	archive_keys = {"is_archived", "archived_at", "archived_by_id"}
	history = {
		key: target.__mapper__.attrs[key].impl.get_history(target, None)
		for key in inspection.keys()
		if key not in archive_keys
	}
	if any(h.deleted for h in history.values()):
		raise ValueError(
			f"Cannot update archived {type(target).__name__} record. "
			"Set __allow_archive_update__ = True to override."
		)
