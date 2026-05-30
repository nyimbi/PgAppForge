"""
scheduling_mixin.py: Advanced Scheduling System for PgAppForge

Provides an enterprise-grade scheduling engine with:
- Complex recurrence patterns (RRULE) with per-instance exceptions
- Multi-timezone support with DST-safe handling via pytz
- Dependency tracking and conflict detection (sync + async paths)
- Resource allocation encoded as JSON
- Priority-based scheduling (1–5 scale)
- iCalendar (RFC 5545) import/export via icalendar
- Audit fields (created/updated at, by)
- Calendar query helper returning FullCalendar-compatible dicts

SQLAlchemy 2.x (mapped_column / Mapped) used when available; falls back to
Column-based declarations for SQLAlchemy 1.4 compatibility.

Dependencies:
	flask-appbuilder>=4.0.0
	sqlalchemy>=1.4
	python-dateutil>=2.8.2
	pytz>=2022.1
	icalendar>=4.0.9

Author: Nyimbi Odero
Version: 2.1 (SQLAlchemy 2.x, Python 3.12+)
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

import pytz
from dateutil.parser import parse as dateutil_parse
from dateutil.rrule import (
	DAILY,
	HOURLY,
	MINUTELY,
	MONTHLY,
	WEEKLY,
	YEARLY,
	rrule,
)
from sqlalchemy import (
	JSON,
	Boolean,
	Column,
	DateTime,
	Enum,
	ForeignKey,
	Index,
	Integer,
	String,
	Text,
	UniqueConstraint,
	and_,
	or_,
)
from sqlalchemy.ext.declarative import declared_attr
from sqlalchemy.orm import relationship, validates

# ---------------------------------------------------------------------------
# Optional: icalendar
# ---------------------------------------------------------------------------
try:
	from icalendar import Calendar, Event as ICalEvent

	_ICALENDAR_AVAILABLE = True
except ImportError:
	_ICALENDAR_AVAILABLE = False
	Calendar = None  # type: ignore[assignment,misc]
	ICalEvent = None  # type: ignore[assignment,misc]

# ---------------------------------------------------------------------------
# Optional: PostgreSQL JSONB / UUID — fall back to cross-DB types
# ---------------------------------------------------------------------------
try:
	from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID

	_PG_AVAILABLE = True
except ImportError:
	_PG_AVAILABLE = False
	JSONB = JSON  # type: ignore[misc,assignment]
	PG_UUID = String  # type: ignore[misc,assignment]

# ---------------------------------------------------------------------------
# SQLAlchemy 2.x mapped_column / Mapped — degrade to Column for 1.4
# ---------------------------------------------------------------------------
try:
	from sqlalchemy.orm import Mapped, mapped_column

	_SA2 = True
except ImportError:
	_SA2 = False

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Frequency name → dateutil constant
# ---------------------------------------------------------------------------
_FREQ_MAP: dict[str, int] = {
	"YEARLY": YEARLY,
	"MONTHLY": MONTHLY,
	"WEEKLY": WEEKLY,
	"DAILY": DAILY,
	"HOURLY": HOURLY,
	"MINUTELY": MINUTELY,
}

_VALID_STATUSES = ("active", "cancelled", "completed", "draft")


# ===========================================================================
# SchedulingMixin
# ===========================================================================
class SchedulingMixin:
	"""
	SQLAlchemy declared-attr mixin that adds a full scheduling subsystem
	to any PgAppForge Model subclass.

	Usage::

		class Meeting(SchedulingMixin, Model):
			__tablename__ = "meetings"
			id = Column(Integer, primary_key=True)
			team_id = Column(Integer, ForeignKey("teams.id"), nullable=False)
	"""

	# ------------------------------------------------------------------
	# Columns
	# ------------------------------------------------------------------

	@declared_attr
	def schedule_uuid(cls) -> Column:
		"""Stable external identifier (UUID string)."""
		if _PG_AVAILABLE:
			return Column(PG_UUID, default=uuid4, unique=True, nullable=False)
		return Column(String(36), default=lambda: str(uuid4()), unique=True, nullable=False)

	@declared_attr
	def start_time(cls) -> Column:
		return Column(DateTime(timezone=True), nullable=False, index=True)

	@declared_attr
	def end_time(cls) -> Column:
		return Column(DateTime(timezone=True), nullable=False, index=True)

	@declared_attr
	def timezone_name(cls) -> Column:
		"""IANA timezone name, e.g. 'America/New_York'."""
		return Column(String(64), default="UTC", nullable=False)

	@declared_attr
	def title(cls) -> Column:
		return Column(String(200), nullable=False)

	@declared_attr
	def description(cls) -> Column:
		return Column(Text)

	@declared_attr
	def location(cls) -> Column:
		return Column(String(200))

	@declared_attr
	def recurrence_pattern(cls) -> Column:
		"""RRULE parameters stored as JSON dict."""
		return Column(JSONB if _PG_AVAILABLE else JSON, default=dict)

	@declared_attr
	def is_recurring(cls) -> Column:
		return Column(Boolean, default=False, nullable=False)

	@declared_attr
	def schedule_status(cls) -> Column:
		return Column(
			Enum(*_VALID_STATUSES, name="schedule_status_enum"),
			default="active",
			nullable=False,
		)

	@declared_attr
	def priority(cls) -> Column:
		"""1 (highest) – 5 (lowest)."""
		return Column(Integer, default=3, nullable=False)

	@declared_attr
	def resources(cls) -> Column:
		"""Arbitrary resource requirements, e.g. {"room": "A", "equipment": ["projector"]}."""
		return Column(JSONB if _PG_AVAILABLE else JSON, default=dict)

	@declared_attr
	def dependencies(cls) -> Column:
		"""IDs of schedules this one depends on, stored as a JSON list."""
		return Column(JSONB if _PG_AVAILABLE else JSON, default=list)

	@declared_attr
	def schedule_metadata(cls) -> Column:
		"""Freeform extension data."""
		return Column(JSONB if _PG_AVAILABLE else JSON, default=dict)

	@declared_attr
	def notifications(cls) -> Column:
		"""Notification configuration, e.g. {"email": {"remind_before": 15}}."""
		return Column(JSONB if _PG_AVAILABLE else JSON, default=dict)

	@declared_attr
	def created_by_fk(cls) -> Column:
		return Column(Integer, ForeignKey("ab_user.id"), nullable=False)

	@declared_attr
	def updated_by_fk(cls) -> Column:
		return Column(Integer, ForeignKey("ab_user.id"), nullable=True)

	@declared_attr
	def created_at(cls) -> Column:
		return Column(
			DateTime(timezone=True),
			default=lambda: datetime.now(timezone.utc),
			nullable=False,
		)

	@declared_attr
	def updated_at(cls) -> Column:
		return Column(
			DateTime(timezone=True),
			onupdate=lambda: datetime.now(timezone.utc),
		)

	# ------------------------------------------------------------------
	# Relationships
	# ------------------------------------------------------------------

	@declared_attr
	def schedule_exceptions(cls):
		"""One-to-many relationship to ScheduleException rows."""
		return relationship(
			"ScheduleException",
			primaryjoin=lambda: (
				cls.id == ScheduleException.scheduled_item_id  # type: ignore[attr-defined]
			),
			foreign_keys="[ScheduleException.scheduled_item_id]",
			cascade="all, delete-orphan",
			lazy="select",
			overlaps="scheduled_item",
		)

	@declared_attr
	def created_by(cls):
		return relationship(
			"User",
			foreign_keys=lambda: [cls.created_by_fk],
			overlaps="updated_by",
		)

	@declared_attr
	def updated_by(cls):
		return relationship(
			"User",
			foreign_keys=lambda: [cls.updated_by_fk],
			overlaps="created_by",
		)

	# ------------------------------------------------------------------
	# Init
	# ------------------------------------------------------------------

	def __init__(self, **kwargs: Any) -> None:
		"""Localise naive start_time / end_time to the declared timezone."""
		tz_name = kwargs.get("timezone_name", "UTC")
		try:
			tz = pytz.timezone(tz_name)
		except pytz.UnknownTimeZoneError:
			logger.warning("Unknown timezone %r, falling back to UTC", tz_name)
			tz = pytz.UTC

		for key in ("start_time", "end_time"):
			dt: datetime | None = kwargs.get(key)
			if dt is not None and dt.tzinfo is None:
				kwargs[key] = tz.localize(dt)

		super().__init__(**kwargs)

	# ------------------------------------------------------------------
	# Validators
	# ------------------------------------------------------------------

	@validates("priority")
	def validate_priority(self, key: str, value: int) -> int:
		if not 1 <= value <= 5:
			raise ValueError(f"priority must be 1–5, got {value!r}")
		return value

	@validates("schedule_status")
	def validate_status(self, key: str, value: str) -> str:
		if value not in _VALID_STATUSES:
			raise ValueError(f"schedule_status must be one of {_VALID_STATUSES}, got {value!r}")
		return value

	@validates("timezone_name")
	def validate_timezone(self, key: str, value: str) -> str:
		try:
			pytz.timezone(value)
		except pytz.UnknownTimeZoneError:
			raise ValueError(f"Unknown IANA timezone: {value!r}")
		return value

	# ------------------------------------------------------------------
	# Recurrence helpers
	# ------------------------------------------------------------------

	def set_recurrence(
		self,
		freq: str,
		interval: int = 1,
		count: int | None = None,
		until: datetime | None = None,
		byday: list[str] | None = None,
		bymonthday: list[int] | None = None,
		byyearday: list[int] | None = None,
		byweekno: list[int] | None = None,
		bymonth: list[int] | None = None,
		byhour: list[int] | None = None,
		byminute: list[int] | None = None,
	) -> None:
		"""
		Set a recurrence rule from discrete parameters.

		freq must be one of: YEARLY MONTHLY WEEKLY DAILY HOURLY MINUTELY
		"""
		if freq.upper() not in _FREQ_MAP:
			raise ValueError(f"freq must be one of {list(_FREQ_MAP)}, got {freq!r}")

		pattern: dict[str, Any] = {
			"freq": freq.upper(),
			"interval": interval,
		}
		if count is not None:
			pattern["count"] = count
		if until is not None:
			pattern["until"] = until.isoformat()
		if byday is not None:
			pattern["byday"] = byday
		if bymonthday is not None:
			pattern["bymonthday"] = bymonthday
		if byyearday is not None:
			pattern["byyearday"] = byyearday
		if byweekno is not None:
			pattern["byweekno"] = byweekno
		if bymonth is not None:
			pattern["bymonth"] = bymonth
		if byhour is not None:
			pattern["byhour"] = byhour
		if byminute is not None:
			pattern["byminute"] = byminute

		self.recurrence_pattern = pattern
		self.is_recurring = True

	def _build_rrule(self, window_end: datetime) -> rrule:
		"""Construct a dateutil rrule from stored recurrence_pattern."""
		pattern = self.recurrence_pattern or {}
		freq_key = pattern.get("freq", "DAILY")
		freq = _FREQ_MAP.get(freq_key.upper(), DAILY)

		kwargs: dict[str, Any] = {
			"dtstart": self.start_time,
			"freq": freq,
			"interval": pattern.get("interval", 1),
		}

		if "until" in pattern:
			kwargs["until"] = dateutil_parse(pattern["until"])
		elif "count" not in pattern:
			kwargs["until"] = window_end

		for key in ("count", "byday", "bymonthday", "byyearday", "byweekno", "bymonth", "byhour", "byminute"):
			if key in pattern:
				kwargs[key] = pattern[key]

		return rrule(**kwargs)

	def add_exception(self, exception_date: datetime, reason: str = "", created_by_fk: int | None = None) -> "ScheduleException":
		"""
		Add a date to be excluded from the recurrence sequence.

		Returns the new ScheduleException instance (not yet flushed to DB).
		"""
		exc = ScheduleException(
			scheduled_item_id=self.id,  # type: ignore[attr-defined]
			exception_date=exception_date,
			reason=reason,
			created_by_fk=created_by_fk,
		)
		self.schedule_exceptions.append(exc)
		return exc

	def get_occurrences(
		self,
		start: datetime,
		end: datetime,
		include_exceptions: bool = True,
	) -> list[datetime]:
		"""
		Return all occurrence datetimes in [start, end].

		For non-recurring schedules returns [start_time] if it falls in window.
		Exception dates (stored as ScheduleException rows) are removed when
		include_exceptions=True.
		"""
		if not self.is_recurring:
			return [self.start_time] if start <= self.start_time <= end else []

		rule = self._build_rrule(end)
		occurrences: list[datetime] = list(rule)

		if include_exceptions and self.schedule_exceptions:
			# Normalise exception dates to naive for comparison
			exception_dates: set[datetime] = {
				e.exception_date.replace(tzinfo=None)
				if e.exception_date.tzinfo is not None
				else e.exception_date
				for e in self.schedule_exceptions
			}
			occurrences = [
				occ for occ in occurrences
				if occ.replace(tzinfo=None) not in exception_dates
			]

		return [occ for occ in occurrences if start <= occ <= end]

	# ------------------------------------------------------------------
	# Conflict detection
	# ------------------------------------------------------------------

	def find_conflicts(
		self,
		session: Any,
		margin_minutes: int = 0,
	) -> list["SchedulingMixin"]:
		"""
		Query the DB for active schedules whose time windows overlap this one.

		margin_minutes adds a buffer on each side (useful for back-to-back
		room booking rules).  Returns a deduplicated list.
		"""
		margin = timedelta(minutes=margin_minutes)
		duration = self.end_time - self.start_time
		occurrences = self.get_occurrences(
			self.start_time - margin,
			self.end_time + margin,
		)

		conflicts: list[Any] = []
		cls = self.__class__

		for occurrence in occurrences:
			win_start = occurrence - margin
			win_end = occurrence + duration + margin

			stmt = (
				session.query(cls)
				.filter(
					cls.id != self.id,  # type: ignore[attr-defined]
					cls.schedule_status == "active",
					or_(
						and_(cls.start_time <= win_start, cls.end_time > win_start),
						and_(cls.start_time < win_end, cls.end_time >= win_end),
						and_(cls.start_time >= win_start, cls.end_time <= win_end),
					),
				)
			)
			conflicts.extend(stmt.all())

		# Deduplicate while preserving order
		seen: set[int] = set()
		unique: list[Any] = []
		for c in conflicts:
			if c.id not in seen:
				seen.add(c.id)
				unique.append(c)
		return unique

	async def get_conflicts_async(
		self,
		session: Any,
		margin_minutes: int = 0,
	) -> list["SchedulingMixin"]:
		"""
		Async wrapper around find_conflicts for use in async Flask contexts.

		Note: this delegates to the sync path via run_in_executor if the
		session is a standard SQLAlchemy session, or can be overridden for
		async SQLAlchemy sessions.
		"""
		import asyncio

		loop = asyncio.get_event_loop()
		return await loop.run_in_executor(
			None, self.find_conflicts, session, margin_minutes
		)

	# ------------------------------------------------------------------
	# iCalendar support
	# ------------------------------------------------------------------

	def to_ical(self) -> str:
		"""
		Serialize this schedule to an RFC 5545 iCalendar string.

		Raises RuntimeError if the icalendar package is not installed.
		"""
		if not _ICALENDAR_AVAILABLE:
			raise RuntimeError("icalendar package is required for iCal support: pip install icalendar")

		cal = Calendar()
		cal.add("prodid", "-//PgAppForge SchedulingMixin//EN")
		cal.add("version", "2.0")

		event = ICalEvent()
		event.add("uid", str(self.schedule_uuid))  # type: ignore[attr-defined]
		event.add("summary", self.title)
		event.add("dtstart", self.start_time)
		event.add("dtend", self.end_time)

		if self.description:
			event.add("description", self.description)
		if self.location:
			event.add("location", self.location)
		if self.priority:
			# iCal priority: 1=highest, 9=lowest; map our 1-5 to 1-9
			ical_priority = int((self.priority - 1) * 2 + 1)
			event.add("priority", ical_priority)

		if self.is_recurring and self.recurrence_pattern:
			event.add("rrule", self.recurrence_pattern)

		for exc in self.schedule_exceptions:
			event.add("exdate", exc.exception_date)

		cal.add_component(event)
		return cal.to_ical().decode("utf-8")

	def from_ical(self, ical_data: str) -> None:
		"""
		Update this instance's fields from an RFC 5545 VEVENT block.

		Only the first VEVENT is processed. Raises RuntimeError if icalendar
		is not installed.
		"""
		if not _ICALENDAR_AVAILABLE:
			raise RuntimeError("icalendar package is required for iCal support: pip install icalendar")

		cal = Calendar.from_ical(ical_data)
		for component in cal.walk():
			if component.name != "VEVENT":
				continue

			dtstart = component.get("dtstart")
			dtend = component.get("dtend")
			if dtstart:
				self.start_time = dtstart.dt
			if dtend:
				self.end_time = dtend.dt

			self.title = str(component.get("summary", self.title or ""))
			self.description = str(component.get("description", self.description or ""))
			self.location = str(component.get("location", self.location or ""))

			rrule_prop = component.get("rrule")
			if rrule_prop:
				self.recurrence_pattern = dict(rrule_prop)
				self.is_recurring = True

			exdate_prop = component.get("exdate")
			if exdate_prop:
				# exdate may be a single vDDDLists or a list of them
				dates = exdate_prop if isinstance(exdate_prop, list) else [exdate_prop]
				for vddd in dates:
					for dt in vddd.dts:
						self.add_exception(dt.dt)

			# Only process first VEVENT
			break

	# ------------------------------------------------------------------
	# Calendar query helper
	# ------------------------------------------------------------------

	@classmethod
	def get_calendar_data(
		cls,
		session: Any,
		start: datetime,
		end: datetime,
		user_id: int | None = None,
	) -> list[dict[str, Any]]:
		"""
		Return a list of FullCalendar-compatible event dicts for [start, end].

		Recurring schedules are expanded into individual occurrence dicts.
		user_id filters to schedules created by that user.
		"""
		query = session.query(cls).filter(
			or_(
				and_(cls.start_time >= start, cls.start_time <= end),
				and_(cls.end_time >= start, cls.end_time <= end),
				and_(cls.start_time <= start, cls.end_time >= end),
			)
		)
		if user_id is not None:
			query = query.filter(cls.created_by_fk == user_id)

		schedules = query.all()
		result: list[dict[str, Any]] = []

		for schedule in schedules:
			base = {
				"status": schedule.schedule_status,
				"priority": schedule.priority,
				"location": schedule.location,
				"metadata": schedule.schedule_metadata,
			}
			if schedule.is_recurring:
				duration = schedule.end_time - schedule.start_time
				for occurrence in schedule.get_occurrences(start, end):
					result.append({
						**base,
						"id": f"{schedule.id}_{occurrence.isoformat()}",
						"title": schedule.title,
						"start": occurrence.isoformat(),
						"end": (occurrence + duration).isoformat(),
						"recurring": True,
					})
			else:
				result.append({
					**base,
					"id": str(schedule.id),
					"title": schedule.title,
					"start": schedule.start_time.isoformat(),
					"end": schedule.end_time.isoformat(),
					"recurring": False,
				})

		return result

	# ------------------------------------------------------------------
	# Utility
	# ------------------------------------------------------------------

	def duration(self) -> timedelta:
		"""Wall-clock duration of one occurrence."""
		return self.end_time - self.start_time

	def is_active(self) -> bool:
		return self.schedule_status == "active"

	def cancel(self) -> None:
		self.schedule_status = "cancelled"

	def complete(self) -> None:
		self.schedule_status = "completed"

	def to_dict(self) -> dict[str, Any]:
		"""Serialise scheduling fields to a plain dict (JSON-safe)."""
		return {
			"schedule_uuid": str(self.schedule_uuid),  # type: ignore[attr-defined]
			"title": self.title,
			"description": self.description,
			"location": self.location,
			"start_time": self.start_time.isoformat() if self.start_time else None,
			"end_time": self.end_time.isoformat() if self.end_time else None,
			"timezone_name": self.timezone_name,
			"is_recurring": self.is_recurring,
			"recurrence_pattern": self.recurrence_pattern,
			"schedule_status": self.schedule_status,
			"priority": self.priority,
			"resources": self.resources,
			"dependencies": self.dependencies,
			"notifications": self.notifications,
			"schedule_metadata": self.schedule_metadata,
		}


# ===========================================================================
# ScheduleException — concrete Model for exception dates
# ===========================================================================

try:
	from pgappforge import Model as _FABModel

	_ModelBase = _FABModel
except ImportError:
	from sqlalchemy.orm import DeclarativeBase

	class _ModelBase(DeclarativeBase):  # type: ignore[no-redef]
		pass


class ScheduleException(_ModelBase):
	"""
	One excluded date for a recurring schedule.

	The scheduled_item_id foreign key references whatever table the mixin is
	applied to via the generic "scheduled_items" name; override
	__tablename__ on your model if needed, or use a concrete FK per model.
	"""

	__tablename__ = "fab_schedule_exceptions"

	__table_args__ = (
		Index("ix_fab_sched_exc_item_date", "scheduled_item_id", "exception_date"),
		UniqueConstraint(
			"scheduled_item_id",
			"exception_date",
			name="uq_fab_sched_exc_item_date",
		),
	)

	id = Column(Integer, primary_key=True, autoincrement=True)

	if _PG_AVAILABLE:
		uuid = Column(PG_UUID, default=uuid4, unique=True, nullable=False)
	else:
		uuid = Column(String(36), default=lambda: str(uuid4()), unique=True, nullable=False)

	# Generic FK — works when there is exactly one scheduling table.
	# For multi-table deployments add a polymorphic type discriminator.
	scheduled_item_id = Column(Integer, nullable=False, index=True)

	exception_date = Column(DateTime(timezone=True), nullable=False)
	reason = Column(String(200))
	created_by_fk = Column(Integer, ForeignKey("ab_user.id"), nullable=True)
	created_at = Column(
		DateTime(timezone=True),
		default=lambda: datetime.now(timezone.utc),
		nullable=False,
	)
	exception_metadata = Column(
		JSONB if _PG_AVAILABLE else JSON,
		default=dict,
	)

	created_by = relationship("User", foreign_keys=[created_by_fk])
