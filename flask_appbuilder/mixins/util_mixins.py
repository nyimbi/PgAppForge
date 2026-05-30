"""
util_mixins.py

Utility mixins for Flask-AppBuilder models: versioned change tracking and
archival storage.

VersionMixin
    Attach to any model to record *what* changed, *when*, *by whom*, and
    the operation type (create/update/delete).  Uses ``declared_attr`` so
    SQLAlchemy maps the columns correctly on each concrete subclass table.

ArchivedVersion
    Concrete FAB Model table.  Stores full JSON snapshots of rows before
    hard deletion so data is recoverable without a backup restore.

SQLAlchemy compatibility
    Targets SA 2.x (``mapped_column``).  Falls back to ``Column`` on SA 1.x
    at import time; the mixin uses ``declared_attr`` throughout so neither
    path triggers the SA 2.x annotation-resolver at class-definition time.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from sqlalchemy.ext.declarative import declared_attr

# SA 2.x preferred API; graceful fallback to SA 1.x Column.
try:
	from sqlalchemy.orm import mapped_column
	from sqlalchemy import Integer, String, DateTime, ForeignKey, JSON
	_USE_MAPPED = True
except ImportError:
	from sqlalchemy import Column as mapped_column, Integer, String, DateTime, ForeignKey, JSON  # type: ignore[assignment]
	_USE_MAPPED = False

# Flask-AppBuilder declarative base (wired to FAB's SQLAlchemy db instance).
from flask_appbuilder import Model

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# VersionMixin
# ---------------------------------------------------------------------------

class VersionMixin:
	"""Mixin that records a single versioned change on any SQLAlchemy model.

	All columns are declared via ``declared_attr`` so SA maps them onto the
	concrete subclass table at mapper-configuration time, not at import time.
	This avoids the SA 2.x ``Mapped[...]`` string-annotation resolver issue
	that fires when ``from __future__ import annotations`` is active.

	Columns
	-------
	version        : monotonically increasing int; managed by caller.
	changed_by_id  : FK → ``ab_user.id``; nullable for system-initiated ops.
	changed_on     : timestamp; defaults to ``datetime.now`` at INSERT.
	change_type    : short op code (≤ 10 chars): ``'create'``, ``'update'``,
	                 ``'delete'``.
	_changes       : JSON blob ``{field: {old: …, new: …}}``.
	"""

	@declared_attr
	def version(cls) -> Any:
		return mapped_column(Integer, nullable=False)

	@declared_attr
	def changed_by_id(cls) -> Any:
		return mapped_column(Integer, ForeignKey("ab_user.id"), nullable=True)

	@declared_attr
	def changed_on(cls) -> Any:
		return mapped_column(DateTime, default=datetime.now, nullable=False)

	@declared_attr
	def change_type(cls) -> Any:
		return mapped_column(String(10), nullable=False)

	@declared_attr
	def _changes(cls) -> Any:
		# Column stored as "changes" in the DB; Python attr is _changes.
		return mapped_column("changes", JSON, nullable=True)

	# ------------------------------------------------------------------
	# Public interface
	# ------------------------------------------------------------------

	@property
	def changes(self) -> dict[str, Any]:
		"""The change dict, always a ``dict`` even when the column is NULL.

		Expected shape::

		    {"field_name": {"old": <prev>, "new": <curr>}, ...}
		"""
		return self._changes or {}

	def record_change(
		self,
		changed_fields: dict[str, tuple[Any, Any]],
		change_type: str,
		changed_by_id: int | None = None,
	) -> None:
		"""Populate all mixin columns in one call.

		Parameters
		----------
		changed_fields:
		    ``{field: (old_value, new_value)}`` pairs for every field that
		    changed in this operation.
		change_type:
		    Operation code; silently truncated to 10 chars.
		changed_by_id:
		    FK to ``ab_user.id``; ``None`` for automated / system changes.
		"""
		self._changes = {
			field: {"old": old, "new": new}
			for field, (old, new) in changed_fields.items()
		}
		self.change_type = change_type[:10]
		self.changed_by_id = changed_by_id
		self.changed_on = datetime.now()

	def changed_fields_list(self) -> list[str]:
		"""Sorted list of field names recorded in this change."""
		return sorted(self.changes.keys())

	def field_delta(self, field: str) -> tuple[Any, Any] | None:
		"""Return ``(old, new)`` for *field*, or ``None`` if not present."""
		entry = self.changes.get(field)
		if entry is None:
			return None
		return entry.get("old"), entry.get("new")


# ---------------------------------------------------------------------------
# ArchivedVersion  (concrete Model)
# ---------------------------------------------------------------------------

class ArchivedVersion(Model):
	"""Full JSON snapshot of a row captured immediately before hard deletion.

	The ``(item_type, item_id, version)`` triple uniquely identifies each
	archived state within the table.

	Columns
	-------
	id            : surrogate PK.
	item_type     : ``__tablename__`` of the originating model (≤ 100 chars).
	item_id       : PK value from the originating row (plain int; survives
	                table drops or renames on the source model).
	version       : version counter at archival time.
	data          : complete JSON snapshot of the archived row.
	deleted_at    : wall-clock timestamp of deletion.
	deleted_by_id : FK → ``ab_user.id``; nullable for system-initiated deletes.
	"""

	__tablename__ = "archived_versions"

	# Use mapped_column without Mapped[...] annotations.  SA 2.x accepts
	# this form; type-checkers infer Column[x] from the SA type argument.
	id = mapped_column(Integer, primary_key=True)
	item_type = mapped_column(String(100), nullable=False, index=True)
	item_id = mapped_column(Integer, nullable=False, index=True)
	version = mapped_column(Integer, nullable=False)
	data = mapped_column(JSON, nullable=False)
	deleted_at = mapped_column(DateTime, nullable=False)
	deleted_by_id = mapped_column(Integer, ForeignKey("ab_user.id"), nullable=True)

	# ------------------------------------------------------------------
	# Class-level helpers
	# ------------------------------------------------------------------

	@classmethod
	def from_instance(
		cls,
		instance: Any,
		version: int,
		deleted_by_id: int | None = None,
		deleted_at: datetime | None = None,
	) -> ArchivedVersion:
		"""Construct an ``ArchivedVersion`` from a live model instance.

		Calls ``instance.to_dict()`` when available; otherwise falls back to
		``instance.__dict__`` filtered to public SQLAlchemy instrumented attrs.

		Parameters
		----------
		instance:
		    The model row about to be hard-deleted.
		version:
		    Version number at deletion time (from ``VersionMixin.version`` if
		    present, else application-supplied).
		deleted_by_id:
		    FK to ``ab_user.id`` of the actor performing the delete.
		deleted_at:
		    Timestamp override; defaults to ``datetime.now()``.
		"""
		if hasattr(instance, "to_dict"):
			snapshot: dict[str, Any] = instance.to_dict()
		else:
			snapshot = {
				k: v
				for k, v in instance.__dict__.items()
				if not k.startswith("_")
			}

		return cls(
			item_type=instance.__tablename__,
			item_id=instance.id,
			version=version,
			data=_json_safe(snapshot),
			deleted_at=deleted_at or datetime.now(),
			deleted_by_id=deleted_by_id,
		)

	# ------------------------------------------------------------------
	# Instance helpers
	# ------------------------------------------------------------------

	def restore_data(self) -> dict[str, Any]:
		"""Return the snapshot dict ready for re-insertion.

		Strips the surrogate ``id`` so the caller decides whether to re-use
		the original PK or let the DB assign a new one.
		"""
		return {k: v for k, v in self.data.items() if k != "id"}

	def field_value(self, field: str, default: Any = None) -> Any:
		"""Read a single field from the archived snapshot."""
		return self.data.get(field, default)

	def __repr__(self) -> str:
		return (
			f"<ArchivedVersion {self.item_type}:{self.item_id}"
			f" v{self.version} deleted_at={self.deleted_at!s}>"
		)


# ---------------------------------------------------------------------------
# Serialisation helpers  (stdlib only — no pandas / numpy dependency)
# ---------------------------------------------------------------------------

def _json_safe(obj: Any) -> Any:
	"""Recursively coerce *obj* to JSON-serialisable types using stdlib only.

	* ``datetime`` → ISO-8601 string
	* ``dict`` / ``list`` / ``tuple`` → recurse
	* Unknown types → ``repr(obj)`` string
	* Primitives (str, int, float, bool, None) → pass through
	"""
	if isinstance(obj, dict):
		return {k: _json_safe(v) for k, v in obj.items()}
	if isinstance(obj, (list, tuple)):
		return [_json_safe(v) for v in obj]
	if isinstance(obj, datetime):
		return obj.isoformat()
	if not isinstance(obj, (str, int, float, bool, type(None))):
		return repr(obj)
	return obj
