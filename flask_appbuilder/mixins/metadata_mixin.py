"""
metadata_mixin.py

Flexible, schema-less metadata storage for SQLAlchemy models in Flask-AppBuilder.

Stores additional non-structured data with model instances via a JSONB/JSON column,
with optional field validation, versioning, audit tracking, type coercion, computed
fields, and bulk search — all without altering the base model schema.

Author: Nyimbi Odero
Date: 25/08/2024 (modernized 2026-05-30)
Version: 2.0
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Callable

from flask_appbuilder import Model
from sqlalchemy import JSON, Column, and_, event, or_, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.types import TypeDecorator

try:
	from sqlalchemy.orm import declared_attr
except ImportError:
	from sqlalchemy.ext.declarative import declared_attr  # type: ignore[no-redef]

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Custom column type
# ---------------------------------------------------------------------------

class JSONBType(TypeDecorator):
	"""JSONB on PostgreSQL, plain JSON elsewhere — transparent to application code."""

	impl = JSONB
	cache_ok = True

	def load_dialect_impl(self, dialect):
		if dialect.name == "postgresql":
			return dialect.type_descriptor(JSONB())
		return dialect.type_descriptor(JSON())


# ---------------------------------------------------------------------------
# Core mixin
# ---------------------------------------------------------------------------

class MetadataMixin:
	"""
	Adds a flexible ``metadata`` JSONB/JSON column to any SQLAlchemy model.

	Class-level configuration attributes (all optional):

	``__metadata_fields__``
		``list[str]`` — whitelist of allowed keys; empty means unrestricted.

	``__metadata_types__``
		``dict[str, type]`` — callable used to coerce/validate a value on
		``get_metadata`` and during ``validate_metadata``.

	``__metadata_defaults__``
		``dict[str, Any]`` — initial values written to new instances.

	``__metadata_required__``
		``list[str]`` — keys that must be present; cannot be deleted.

	``__metadata_computed__``
		``dict[str, Callable[[model], Any]]`` — callables that receive the
		model instance and return a derived value on ``compute_metadata()``.

	``__metadata_validators__``
		``dict[str, Callable[[Any], bool]]`` — per-field predicates; must
		return ``True`` to pass.

	``__track_metadata__``
		``bool`` — accumulate per-field change records in
		``_metadata_changes`` (in-memory only).

	``__metadata_version__``
		``bool`` — maintain ``_version`` (int) and ``_updated_at`` (ISO
		string) system keys inside the JSON blob.
	"""

	__metadata_fields__: list[str] = []
	__metadata_types__: dict[str, type] = {}
	__metadata_defaults__: dict[str, Any] = {}
	__metadata_required__: list[str] = []
	__metadata_computed__: dict[str, Callable] = {}
	__metadata_validators__: dict[str, Callable] = {}
	__track_metadata__: bool = False
	__metadata_version__: bool = False

	# ------------------------------------------------------------------
	# Column declaration
	# ------------------------------------------------------------------

	@declared_attr
	def metadata(cls):
		"""JSONB/JSON column, defaulting to a copy of ``__metadata_defaults__``."""
		return Column(
			MutableDict.as_mutable(JSONBType),
			default=lambda: cls.__metadata_defaults__.copy(),
			nullable=False,
		)

	# ------------------------------------------------------------------
	# Lifecycle
	# ------------------------------------------------------------------

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		# Ensure metadata dict is initialised even when ORM skips __init__
		if self.metadata is None:
			self.metadata = self.__metadata_defaults__.copy()
		self._original_metadata: dict[str, Any] = dict(self.metadata)
		if self.__metadata_version__:
			self.metadata.setdefault("_version", 1)
			self.metadata.setdefault("_updated_at", _utcnow_iso())

	# ------------------------------------------------------------------
	# Public write API
	# ------------------------------------------------------------------

	def set_metadata(self, key: str, value: Any, validate: bool = True) -> None:
		"""Set a single metadata key, with optional validation.

		Raises:
			ValueError: key not in ``__metadata_fields__`` whitelist.
			TypeError: value fails type coercion.
			ValueError: value fails custom validator.
		"""
		if self.__metadata_fields__ and key not in self.__metadata_fields__:
			raise ValueError(f"Invalid metadata key: {key!r}")

		if validate:
			self._validate_field(key, value)

		if self.__track_metadata__:
			self._track_change(key, value)

		self.metadata[key] = value
		self._bump_version()

	def update_metadata(self, data: dict[str, Any], validate: bool = True) -> None:
		"""Set multiple keys atomically.

		Raises:
			ValueError: any key not in whitelist.
			TypeError/ValueError: any value fails its validator.
		"""
		if self.__metadata_fields__:
			invalid = set(data) - set(self.__metadata_fields__)
			if invalid:
				raise ValueError(f"Invalid metadata keys: {', '.join(sorted(invalid))}")

		if validate:
			for key, value in data.items():
				self._validate_field(key, value)

		if self.__track_metadata__:
			for key, value in data.items():
				self._track_change(key, value)

		self.metadata.update(data)
		self._bump_version()

	def delete_metadata(self, key: str) -> bool:
		"""Remove a key.  Returns ``True`` if it existed.

		Raises:
			ValueError: key is listed in ``__metadata_required__``.
		"""
		if key in self.__metadata_required__:
			raise ValueError(f"Cannot delete required metadata field: {key!r}")

		existed = key in self.metadata
		if existed:
			if self.__track_metadata__:
				self._track_change(key, None)
			del self.metadata[key]
			self._bump_version()
		return existed

	def clear_metadata(self, keep_required: bool = True) -> None:
		"""Clear all user-defined keys.

		Args:
			keep_required: When ``True`` (default), values for
				``__metadata_required__`` keys are preserved.
		"""
		if keep_required:
			preserved = {k: v for k, v in self.metadata.items() if k in self.__metadata_required__}
			self.metadata.clear()
			self.metadata.update(preserved)
		else:
			self.metadata.clear()
			self.metadata.update(self.__metadata_defaults__)

	# ------------------------------------------------------------------
	# Public read API
	# ------------------------------------------------------------------

	def get_metadata(self, key: str, default: Any = None) -> Any:
		"""Return value for *key*, coercing via ``__metadata_types__`` if defined."""
		value = self.metadata.get(key, default)
		coerce = self.__metadata_types__.get(key)
		if coerce is not None:
			try:
				return coerce(value)
			except (ValueError, TypeError):
				return default
		return value

	def get_all_metadata(self, include_system: bool = False) -> dict[str, Any]:
		"""Return a shallow copy of the metadata dict.

		Args:
			include_system: When ``False`` (default), keys prefixed with
				``_`` (version, updated_at) are omitted.
		"""
		if include_system:
			return dict(self.metadata)
		return {k: v for k, v in self.metadata.items() if not k.startswith("_")}

	# ------------------------------------------------------------------
	# Validation
	# ------------------------------------------------------------------

	def validate_metadata(self, raise_error: bool = True) -> bool | list[str]:
		"""Validate all metadata against schema constraints.

		Returns:
			``True`` when valid.  When *raise_error* is ``False`` and
			validation fails, returns a list of human-readable error strings.

		Raises:
			ValueError: on first failure when *raise_error* is ``True``.
		"""
		errors: list[str] = []

		missing = set(self.__metadata_required__) - set(self.metadata)
		if missing:
			errors.append(f"Missing required fields: {', '.join(sorted(missing))}")

		if self.__metadata_fields__:
			# Exclude system keys from the "invalid field" check
			user_keys = {k for k in self.metadata if not k.startswith("_")}
			invalid = user_keys - set(self.__metadata_fields__)
			if invalid:
				errors.append(f"Invalid fields: {', '.join(sorted(invalid))}")

		for key, value in self.metadata.items():
			coerce = self.__metadata_types__.get(key)
			if coerce is not None:
				try:
					coerce(value)
				except (ValueError, TypeError):
					errors.append(
						f"Invalid type for {key!r}: expected {coerce.__name__}"
					)

		for key, validator in self.__metadata_validators__.items():
			if key in self.metadata:
				try:
					if not validator(self.metadata[key]):
						errors.append(f"Validation failed for {key!r}")
				except Exception as exc:
					errors.append(f"Validator error for {key!r}: {exc}")

		if errors and raise_error:
			raise ValueError("\n".join(errors))

		return True if not errors else errors

	# ------------------------------------------------------------------
	# Computed fields
	# ------------------------------------------------------------------

	def compute_metadata(self) -> None:
		"""Recompute all fields listed in ``__metadata_computed__`` and write results."""
		for key, computer in self.__metadata_computed__.items():
			try:
				self.metadata[key] = computer(self)
			except Exception as exc:
				logger.error("Error computing metadata field %r: %s", key, exc)
		if self.__metadata_computed__:
			self._bump_version()

	# ------------------------------------------------------------------
	# Class-level search (SQLAlchemy 2.x select() patterns)
	# ------------------------------------------------------------------

	@classmethod
	def search_by_metadata(
		cls,
		session: Any,
		operator: str = "and_",
		**kwargs,
	):
		"""Query instances by metadata key-value pairs.

		Uses ``select()`` (SQLAlchemy 2.x) with an ORM fallback.

		Args:
			session: Active SQLAlchemy session.
			operator: ``"and_"`` (default) or ``"or_"``.
			**kwargs: Metadata keys and the values they must match.  A list
				or tuple triggers an IN-style check.

		Returns:
			``ScalarResult`` of matching instances.
		"""
		conditions = []
		for key, value in kwargs.items():
			if isinstance(value, (list, tuple)):
				conditions.append(
					cls.metadata[key].astext.in_([json.dumps(v) for v in value])
				)
			else:
				conditions.append(cls.metadata[key].astext == json.dumps(value))

		combine = or_ if operator == "or_" else and_
		stmt = select(cls).where(combine(*conditions))
		return session.execute(stmt).scalars()

	@classmethod
	def get_unique_metadata_keys(cls, session: Any) -> list[str]:
		"""Return a sorted list of every metadata key present across all rows."""
		stmt = select(cls.metadata)
		rows = session.execute(stmt).all()
		keys: set[str] = set()
		for (blob,) in rows:
			if blob:
				keys.update(blob.keys())
		# Strip internal system keys from the public result
		return sorted(k for k in keys if not k.startswith("_"))

	# ------------------------------------------------------------------
	# Schema introspection
	# ------------------------------------------------------------------

	@classmethod
	def get_metadata_schema(cls) -> dict[str, Any] | None:
		"""Return a JSON-serialisable schema dict, or ``None`` if unconfigured."""
		all_fields = set(cls.__metadata_fields__) | set(cls.__metadata_types__)
		if not all_fields:
			return None

		return {
			field: {
				"type": getattr(cls.__metadata_types__.get(field), "__name__", "any"),
				"required": field in cls.__metadata_required__,
				"default": cls.__metadata_defaults__.get(field),
				"computed": field in cls.__metadata_computed__,
				"has_validator": bool(cls.__metadata_validators__.get(field)),
			}
			for field in sorted(all_fields)
		}

	# ------------------------------------------------------------------
	# Internal helpers
	# ------------------------------------------------------------------

	def _bump_version(self) -> None:
		"""Increment ``_version`` and refresh ``_updated_at`` when versioning is on."""
		if self.__metadata_version__:
			self.metadata["_version"] = self.metadata.get("_version", 0) + 1
			self.metadata["_updated_at"] = _utcnow_iso()

	def _validate_field(self, key: str, value: Any) -> None:
		coerce = self.__metadata_types__.get(key)
		if coerce is not None:
			try:
				coerce(value)
			except (ValueError, TypeError):
				raise TypeError(
					f"Invalid type for {key!r}: expected {coerce.__name__}"
				)

		validator = self.__metadata_validators__.get(key)
		if validator is not None and not validator(value):
			raise ValueError(f"Validation failed for {key!r}")

	def _track_change(self, key: str, value: Any) -> None:
		if not hasattr(self, "_metadata_changes"):
			self._metadata_changes: list[dict[str, Any]] = []
		self._metadata_changes.append(
			{
				"field": key,
				"old_value": self._original_metadata.get(key),
				"new_value": value,
				"timestamp": _utcnow_iso(),
			}
		)


# ---------------------------------------------------------------------------
# Timezone-aware UTC helper
# ---------------------------------------------------------------------------

def _utcnow_iso() -> str:
	"""Return current UTC time as an ISO-8601 string (timezone-aware)."""
	return datetime.now(tz=timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# SQLAlchemy event listeners — validate on INSERT and UPDATE
# ---------------------------------------------------------------------------

@event.listens_for(MetadataMixin, "before_insert", propagate=True)
def _validate_before_insert(mapper, connection, target):
	target.validate_metadata()


@event.listens_for(MetadataMixin, "before_update", propagate=True)
def _validate_before_update(mapper, connection, target):
	target.validate_metadata()
