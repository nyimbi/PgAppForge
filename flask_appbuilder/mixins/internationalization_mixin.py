"""
internationalization_mixin.py

Field-level translation support for SQLAlchemy models in Flask-AppBuilder
applications, backed by a JSONB/JSON column with automatic locale fallback,
optional version history, cache integration, and bulk operations.

Key Features:
    - Field-level translations stored in a single JSONB/JSON column
    - Automatic locale fallback chain
    - Per-field translation validators
    - Versioned translation history with checksum
    - Optional Flask-Caching integration
    - Bulk translate / import / export / coverage-stats helpers
    - SQLAlchemy 2.x compatible (session.execute + select); degrades
      gracefully on 1.x via legacy session.query fallback

Author: Nyimbi Odero
Date: 25/08/2024 (modernized 2026-05-30)
Version: 2.0
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any, Callable

from flask import current_app, g
from flask_appbuilder import Model
from flask_babel import get_locale
from sqlalchemy import JSON, Column, event, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.ext.mutable import MutableDict, MutableList
from sqlalchemy.types import TypeDecorator

try:
	from sqlalchemy.orm import declared_attr, Session
except ImportError:
	from sqlalchemy.ext.declarative import declared_attr  # type: ignore[no-redef]
	from sqlalchemy.orm import Session  # type: ignore[assignment]

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Storage type
# ---------------------------------------------------------------------------

class TranslationJSONType(TypeDecorator):
	"""JSONB on PostgreSQL, plain JSON elsewhere.

	Validates that the stored value is always a dict, defaulting to ``{}``
	on null so callers never have to guard against None.
	"""

	impl = JSONB
	cache_ok = True

	def load_dialect_impl(self, dialect):
		if dialect.name == "postgresql":
			return dialect.type_descriptor(JSONB())
		return dialect.type_descriptor(JSON())

	def process_bind_param(self, value: Any, dialect) -> dict:
		if value is None:
			return {}
		if not isinstance(value, dict):
			raise ValueError("Translation data must be a plain dict")
		return value

	def process_result_value(self, value: Any, dialect) -> dict:
		return value if isinstance(value, dict) else {}


# ---------------------------------------------------------------------------
# Mixin
# ---------------------------------------------------------------------------

class InternationalizationMixin:
	"""
	Adds field-level multi-language support to any SQLAlchemy model.

	Declare on the subclass::

	    class Product(InternationalizationMixin, Model):
	        __tablename__ = "products"
	        id          = Column(Integer, primary_key=True)
	        name        = Column(String(100), nullable=False)
	        description = Column(String(500))

	        __translatable__              = ["name", "description"]
	        __fallback_locale__           = "en"
	        __translation_versioning__    = True
	        __translation_cache_enabled__ = True
	        __translation_cache_timeout__ = 300
	        __translation_validators__    = {
	            "name": lambda v: len(v) <= 100,
	            "description": lambda v: len(v) <= 500,
	        }

	Class Attributes:
	    __translatable__              (list[str]): Fields that carry translations.
	    __fallback_locale__           (str):       Locale used when the active
	                                               locale has no entry.
	    __translation_versioning__    (bool):      Append a version record on
	                                               every write.
	    __translation_cache_enabled__ (bool):      Cache reads via Flask-Caching.
	    __translation_cache_timeout__ (int):       Cache TTL in seconds.
	    __translation_validators__    (dict):      ``{field: callable(value)->bool}``.
	"""

	__translatable__: list[str] = []
	__fallback_locale__: str = "en"
	__translation_versioning__: bool = False
	__translation_cache_enabled__: bool = False
	__translation_cache_timeout__: int = 300
	__translation_validators__: dict[str, Callable[[str], bool]] = {}

	# ------------------------------------------------------------------
	# Declared columns
	# ------------------------------------------------------------------

	@declared_attr
	def translations(cls):
		"""JSONB/JSON column: ``{field: {locale: value}}``."""
		return Column(
			MutableDict.as_mutable(TranslationJSONType),
			default=dict,
			nullable=False,
			server_default="{}",
			comment="Field translations — {field: {locale: value}}",
		)

	@declared_attr
	def translation_versions(cls):
		"""JSONB/JSON column for version history (only when versioning enabled)."""
		return Column(
			MutableList.as_mutable(JSON),
			default=list,
			nullable=False,
			server_default="[]",
			comment="Translation version history",
		)

	# ------------------------------------------------------------------
	# Class initialisation hook
	# ------------------------------------------------------------------

	@classmethod
	def __declare_last__(cls) -> None:
		"""Wire up hybrid properties and event listeners after mapping."""
		if not cls.__translatable__:
			raise ValueError(
				f"{cls.__name__}.__translatable__ must be a non-empty list"
			)

		for field in cls.__translatable__:
			setattr(
				cls,
				f"{field}_translations",
				hybrid_property(
					fget=lambda self, f=field: self._get_translation(f),
					fset=lambda self, value, f=field: self._set_translation(f, value),
				),
			)

		event.listen(cls, "before_insert", cls._before_save)
		event.listen(cls, "before_update", cls._before_save)

		if cls.__translation_cache_enabled__:
			# Defer actual cache check to first use so app context is available.
			logger.debug(
				"%s: translation caching enabled (TTL=%ds)",
				cls.__name__,
				cls.__translation_cache_timeout__,
			)

	# ------------------------------------------------------------------
	# Internal helpers
	# ------------------------------------------------------------------

	def _cache_key(self, field: str, locale: str) -> str:
		return f"i18n_{self.__class__.__name__}_{self.id}_{field}_{locale}"

	def _get_translation(self, field: str) -> str:
		"""Return translated value for *field* in the active locale."""
		locale = str(get_locale())

		if self.__translation_cache_enabled__:
			cache = getattr(current_app, "cache", None)
			if cache is not None:
				cached = cache.get(self._cache_key(field, locale))
				if cached is not None:
					return cached

		translations: dict = (self.translations or {}).get(field, {})

		if locale in translations:
			value = translations[locale]
		elif self.__fallback_locale__ in translations:
			value = translations[self.__fallback_locale__]
		else:
			value = getattr(self, field, None)

		if self.__translation_cache_enabled__:
			cache = getattr(current_app, "cache", None)
			if cache is not None:
				cache.set(
					self._cache_key(field, locale),
					value,
					timeout=self.__translation_cache_timeout__,
				)

		return value

	def _set_translation(
		self, field: str, value: str | dict[str, str]
	) -> None:
		"""Validate and store one or many locale translations for *field*."""
		if field not in self.__translatable__:
			raise ValueError(f"Field '{field}' is not in __translatable__")

		if isinstance(value, str):
			locale = str(get_locale())
			new_translations: dict[str, str] = {locale: value}
		elif isinstance(value, dict):
			new_translations = value
		else:
			raise TypeError("Translation value must be str or dict[locale, str]")

		# Per-field validation
		validator = self.__translation_validators__.get(field)
		if validator is not None:
			for loc, text in new_translations.items():
				if not validator(text):
					raise ValueError(
						f"Validation failed for {field!r} locale {loc!r}"
					)

		# Version history
		if self.__translation_versioning__:
			user_id: Any = None
			user = getattr(g, "user", None)
			if isinstance(user, dict):
				user_id = user.get("id")
			elif user is not None:
				user_id = getattr(user, "id", None)

			version_record = {
				"timestamp": datetime.now(timezone.utc).isoformat(),
				"user_id": user_id,
				"field": field,
				"translations": new_translations,
				"checksum": hashlib.sha256(
					json.dumps(new_translations, sort_keys=True).encode()
				).hexdigest(),
			}
			versions = self.translation_versions
			if not isinstance(versions, list):
				self.translation_versions = []
			self.translation_versions.append(version_record)

		# Merge into the translations dict
		if self.translations is None:
			self.translations = {}
		if field not in self.translations:
			self.translations[field] = {}
		self.translations[field].update(new_translations)

		# Cache invalidation
		if self.__translation_cache_enabled__:
			cache = getattr(current_app, "cache", None)
			if cache is not None:
				for loc in new_translations:
					cache.delete(self._cache_key(field, loc))

	# ------------------------------------------------------------------
	# SQLAlchemy event listener
	# ------------------------------------------------------------------

	@classmethod
	def _before_save(cls, mapper, connection, target) -> None:
		"""Validate translation structure before INSERT/UPDATE."""
		trans = target.translations
		if trans is None:
			target.translations = {}
			return
		if not isinstance(trans, dict):
			raise ValueError("translations column must be a dict")

		for field, locale_map in trans.items():
			if field not in cls.__translatable__:
				raise ValueError(
					f"Field '{field}' found in translations but not in __translatable__"
				)
			if not isinstance(locale_map, dict):
				raise ValueError(
					f"translations['{field}'] must be a locale→value dict"
				)
			validator = cls.__translation_validators__.get(field)
			if validator is not None:
				for loc, val in locale_map.items():
					if not validator(val):
						raise ValueError(
							f"Validation failed for {field!r} locale {loc!r} before save"
						)

	# ------------------------------------------------------------------
	# Public API
	# ------------------------------------------------------------------

	def set_translation(self, field: str, locale: str, value: str) -> None:
		"""Set a single locale translation for *field*.

		Args:
		    field:  Translatable field name.
		    locale: BCP-47 locale string (e.g. ``"es"``, ``"pt_BR"``).
		    value:  Translated string.
		"""
		self._set_translation(field, {locale: value})

	def get_translation(self, field: str, locale: str | None = None) -> str:
		"""Return the translation for *field* in *locale*.

		Falls back to ``__fallback_locale__`` then the raw column value.

		Args:
		    field:  Translatable field name.
		    locale: Target locale; defaults to the active Flask-Babel locale.

		Returns:
		    Translated string, fallback translation, or raw field value.
		"""
		if field not in self.__translatable__:
			raise ValueError(f"Field '{field}' is not in __translatable__")

		if locale is None:
			locale = str(get_locale())

		locale_map: dict = (self.translations or {}).get(field, {})
		if locale in locale_map:
			return locale_map[locale]
		if self.__fallback_locale__ in locale_map:
			return locale_map[self.__fallback_locale__]
		return getattr(self, field, "")

	# ------------------------------------------------------------------
	# Class-level / session operations
	# ------------------------------------------------------------------

	@classmethod
	def _iter_all(cls, session: Session):
		"""Yield all instances using SA2 execute+select with SA1 fallback."""
		try:
			result = session.execute(select(cls))
			yield from (row[0] for row in result)
		except TypeError:
			# SQLAlchemy 1.x
			yield from session.query(cls).all()

	@classmethod
	def _get_by_pk(cls, session: Session, pk: Any):
		"""Fetch a single instance by primary key (SA2 + SA1 compatible)."""
		try:
			result = session.execute(select(cls).where(cls.id == pk))
			row = result.first()
			return row[0] if row else None
		except Exception:
			return session.query(cls).get(pk)

	@classmethod
	def export_translations(cls, session: Session) -> dict[int, dict]:
		"""Dump all translations with metadata.

		Returns:
		    ``{instance_id: {"translations": {...}, "metadata": {...}}}``
		    with ``"versions"`` appended when ``__translation_versioning__``
		    is enabled.
		"""
		out: dict[int, dict] = {}
		for instance in cls._iter_all(session):
			entry: dict[str, Any] = {
				"translations": dict(instance.translations or {}),
				"metadata": {
					"exported_at": datetime.now(timezone.utc).isoformat(),
					"version": "2.0",
				},
			}
			if cls.__translation_versioning__:
				entry["versions"] = list(instance.translation_versions or [])
			out[instance.id] = entry
		return out

	@classmethod
	def import_translations(
		cls,
		session: Session,
		translations_data: dict[int, dict],
		overwrite: bool = False,
	) -> dict[str, int]:
		"""Import translations with optional merge or overwrite semantics.

		Args:
		    session:           Active SQLAlchemy session.
		    translations_data: Output of :meth:`export_translations`.
		    overwrite:         Replace existing locales when ``True``; merge
		                       when ``False`` (default).

		Returns:
		    ``{"updated": N, "failed": N, "skipped": N}``
		"""
		stats: dict[str, int] = {"updated": 0, "failed": 0, "skipped": 0}

		for pk, data in translations_data.items():
			try:
				instance = cls._get_by_pk(session, pk)
				if instance is None:
					stats["failed"] += 1
					continue

				incoming: dict = data.get("translations", {})

				if overwrite:
					instance.translations = dict(incoming)
				else:
					if instance.translations is None:
						instance.translations = {}
					for field, locale_map in incoming.items():
						if field not in instance.translations:
							instance.translations[field] = {}
						instance.translations[field].update(locale_map)

				if cls.__translation_versioning__:
					versions = data.get("versions")
					if versions:
						instance.translation_versions = list(versions)

				stats["updated"] += 1

			except Exception as exc:
				logger.error("import_translations failed for pk=%s: %s", pk, exc)
				stats["failed"] += 1

		session.commit()
		return stats

	@classmethod
	def get_missing_translations(
		cls, session: Session, locales: list[str]
	) -> dict[int, dict[str, list[str]]]:
		"""Report which locales are missing per field per instance.

		Args:
		    session: Active SQLAlchemy session.
		    locales: Locale codes to audit.

		Returns:
		    ``{instance_id: {field: [missing_locale, ...]}}`` — only records
		    with at least one gap are included.
		"""
		missing: dict[int, dict[str, list[str]]] = {}
		for instance in cls._iter_all(session):
			gaps: dict[str, list[str]] = {}
			for field in cls.__translatable__:
				locale_map = (instance.translations or {}).get(field, {})
				absent = [loc for loc in locales if loc not in locale_map]
				if absent:
					gaps[field] = absent
			if gaps:
				missing[instance.id] = gaps
		return missing

	@classmethod
	def bulk_translate(
		cls,
		session: Session,
		translations: dict[int, dict[str, dict[str, str]]],
		validate: bool = True,
	) -> dict[str, int]:
		"""Apply translations for many instances in one pass.

		Args:
		    session:      Active SQLAlchemy session.
		    translations: ``{instance_id: {field: {locale: value}}}``.
		    validate:     Run per-field validators when ``True`` (default).

		Returns:
		    ``{"updated": N, "failed": N}``
		"""
		stats: dict[str, int] = {"updated": 0, "failed": 0}

		for pk, fields in translations.items():
			try:
				instance = cls._get_by_pk(session, pk)
				if instance is None:
					stats["failed"] += 1
					continue

				for field, locale_map in fields.items():
					if validate and field in cls.__translation_validators__:
						validator = cls.__translation_validators__[field]
						for loc, val in locale_map.items():
							if not validator(val):
								raise ValueError(
									f"Validation failed: {field!r} locale {loc!r}"
								)
					instance._set_translation(field, locale_map)

				stats["updated"] += 1

			except Exception as exc:
				logger.error("bulk_translate failed for pk=%s: %s", pk, exc)
				stats["failed"] += 1

		session.commit()
		return stats

	@classmethod
	def get_translation_stats(
		cls,
		session: Session,
		locales: list[str] | None = None,
	) -> dict[str, Any]:
		"""Compute translation coverage across all instances.

		Args:
		    session: Active SQLAlchemy session.
		    locales: Locale codes to inspect; auto-discovered when ``None``.

		Returns:
		    Coverage statistics keyed by locale and field, with top-level
		    ``complete`` / ``partial`` / ``missing`` counts.
		"""
		all_instances = list(cls._iter_all(session))

		if locales is None:
			locale_set: set[str] = set()
			for instance in all_instances:
				for field in cls.__translatable__:
					locale_set.update((instance.translations or {}).get(field, {}).keys())
			locales = sorted(locale_set)

		stats: dict[str, Any] = {
			"total_records": len(all_instances),
			"total_fields": len(cls.__translatable__),
			"locales_checked": locales,
			"by_locale": {loc: 0 for loc in locales},
			"by_field": {},
			"complete": 0,
			"partial": 0,
			"missing": 0,
		}

		for instance in all_instances:
			has_any = False
			missing_any = False

			for field in cls.__translatable__:
				locale_map = (instance.translations or {}).get(field, {})

				if field not in stats["by_field"]:
					stats["by_field"][field] = {
						"total": 0,
						"by_locale": {loc: 0 for loc in locales},
					}

				for loc in locales:
					if loc in locale_map:
						has_any = True
						stats["by_locale"][loc] += 1
						stats["by_field"][field]["by_locale"][loc] += 1
						stats["by_field"][field]["total"] += 1
					else:
						missing_any = True

			if has_any and missing_any:
				stats["partial"] += 1
			elif has_any:
				stats["complete"] += 1
			else:
				stats["missing"] += 1

		return stats
