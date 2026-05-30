"""
cache_mixin.py

Caching mixin for SQLAlchemy models in PgAppForge applications.

Provides instance-level caching, query-level caching, method result caching,
and automatic cache invalidation on model mutation — backed by Flask-Caching.

Dependencies:
	- SQLAlchemy 2.x (compatible with 1.x via try/except)
	- Flask-Caching
	- pickle (stdlib serialization)

Author: Nyimbi Odero
Date: 25/08/2024
Version: 2.0
"""

from __future__ import annotations

import logging
import pickle
from functools import wraps
from typing import Any, Callable, TypeVar

from flask import current_app
from sqlalchemy import event

try:
	# SQLAlchemy 2.x
	from sqlalchemy.orm import DeclarativeBase, Session
	from sqlalchemy.orm import declared_attr
	_SA2 = True
except ImportError:
	# SQLAlchemy 1.x fallback
	from sqlalchemy.ext.declarative import declared_attr  # type: ignore[no-redef]
	_SA2 = False

try:
	from sqlalchemy.orm import Query
except ImportError:
	Query = object  # type: ignore[misc,assignment]

from pgappforge.models.mixins import AuditMixin

log = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


def _get_cache():
	"""Retrieve the Flask-Caching extension; raises RuntimeError outside app context."""
	ext = current_app.extensions.get("cache")
	if ext is None:
		raise RuntimeError(
			"Flask-Caching extension not found. "
			"Install flask-caching and call cache.init_app(app)."
		)
	return ext


class CachedQuery(Query):
	"""
	Legacy SQLAlchemy 1.x-style query class with transparent caching.

	Usage::

		results = MyModel.query.cache(timeout=300).filter(...).all()

	Under SQLAlchemy 2.x the .query interface still works via Flask-SQLAlchemy's
	compatibility shim, so this class remains useful as long as that shim is present.
	"""

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		self._cache_key: str | None = None
		self._cache_timeout: int | None = None

	def cache(self, key: str | None = None, timeout: int | None = None) -> CachedQuery:
		"""
		Mark this query for caching.

		Args:
			key: Explicit cache key; auto-generated from SQL if omitted.
			timeout: TTL in seconds; falls back to the model's __cache_timeout__.

		Returns:
			self — enables method chaining.
		"""
		self._cache_key = key
		self._cache_timeout = timeout
		return self

	def _resolve_cache_key(self) -> str:
		if self._cache_key is None:
			try:
				sql = str(self.statement.compile(compile_kwargs={"literal_binds": True}))
			except Exception:
				sql = str(self.statement)
			self._cache_key = f"fabcache:query:{hash(sql)}"
		return self._cache_key

	def __iter__(self):
		if self._cache_key is None:
			return super().__iter__()

		cache = _get_cache()
		key = self._resolve_cache_key()
		blob = cache.get(key)

		if blob is None:
			result = list(super().__iter__())
			cache.set(key, pickle.dumps(result, protocol=pickle.HIGHEST_PROTOCOL),
					  timeout=self._cache_timeout)
		else:
			result = pickle.loads(blob)

		return iter(result)


class CacheMixin(AuditMixin):
	"""
	Mixin that adds instance-level, query-level, and method-level caching to
	any PgAppForge / SQLAlchemy model.

	Class attributes
	----------------
	__cache_timeout__ : int
		Default TTL in seconds (default 3 600 = 1 hour).  Override per model::

			class Product(CacheMixin, Model):
				__cache_timeout__ = 900  # 15 minutes

	query_class : type
		Points CacheMixin-derived models at CachedQuery for .query.cache() support.

	Event hooks
	-----------
	``after_update`` and ``after_delete`` SQLAlchemy events automatically
	invalidate the per-instance cache key so stale data is never served.

	Example
	-------
	::

		from pgappforge import Model
		from pgappforge.mixins.cache_mixin import CacheMixin
		from sqlalchemy import Column, Integer, String

		class User(CacheMixin, Model):
			__tablename__ = "app_user"
			__cache_timeout__ = 1800

			id = Column(Integer, primary_key=True)
			username = Column(String(80), unique=True, nullable=False)

			@CacheMixin.cached_method(timeout=600)
			def expensive_profile(self):
				return {"username": self.username}

		# Cache / retrieve
		user = db.session.get(User, 1)
		User.cache_instance(user)
		same_user = User.get_cached(1)

		# Cached query
		recent = User.cached_query().filter(...).all()

		# Bulk cache
		User.bulk_cache(db.session.scalars(select(User).limit(100)).all())

		# Manual invalidation
		User.clear_cache()
	"""

	__cache_timeout__: int = 3600
	query_class = CachedQuery

	# ------------------------------------------------------------------
	# SQLAlchemy lifecycle hooks
	# ------------------------------------------------------------------

	@classmethod
	def __declare_last__(cls) -> None:
		"""Register after-mutation listeners for automatic cache invalidation."""
		event.listen(cls, "after_update", cls._invalidate_instance_cache)
		event.listen(cls, "after_delete", cls._invalidate_instance_cache)

	# ------------------------------------------------------------------
	# Cache key helpers
	# ------------------------------------------------------------------

	@classmethod
	def _get_instance_cache_key(cls, instance_id: Any) -> str:
		return f"fabcache:{cls.__name__}:{instance_id}"

	@classmethod
	def _get_method_cache_key(
		cls,
		instance_id: Any,
		method_name: str,
		args: tuple,
		kwargs: dict,
	) -> str:
		return (
			f"fabcache:{cls.__name__}:{instance_id}"
			f":{method_name}:{hash((args, tuple(sorted(kwargs.items()))))}"
		)

	# ------------------------------------------------------------------
	# Event callbacks
	# ------------------------------------------------------------------

	@classmethod
	def _invalidate_instance_cache(cls, mapper, connection, target) -> None:
		"""SQLAlchemy event callback — delete the cached instance on mutation."""
		try:
			cache = _get_cache()
			cache.delete(cls._get_instance_cache_key(target.id))
			log.debug("Cache invalidated for %s id=%s", cls.__name__, target.id)
		except Exception:
			log.warning(
				"Failed to invalidate cache for %s id=%s",
				cls.__name__,
				getattr(target, "id", "?"),
				exc_info=True,
			)

	# ------------------------------------------------------------------
	# Instance caching
	# ------------------------------------------------------------------

	@classmethod
	def cache_instance(cls, instance) -> None:
		"""
		Serialise and store a model instance in the cache.

		Args:
			instance: A model object that has an ``id`` attribute.
		"""
		cache = _get_cache()
		key = cls._get_instance_cache_key(instance.id)
		cache.set(
			key,
			pickle.dumps(instance, protocol=pickle.HIGHEST_PROTOCOL),
			timeout=cls.__cache_timeout__,
		)
		log.debug("Cached %s id=%s (ttl=%ss)", cls.__name__, instance.id, cls.__cache_timeout__)

	@classmethod
	def get_cached(cls, instance_id: Any):
		"""
		Return a cached model instance, or ``None`` on cache miss.

		Args:
			instance_id: Primary-key value of the desired instance.

		Returns:
			Deserialized model instance or None.
		"""
		cache = _get_cache()
		blob = cache.get(cls._get_instance_cache_key(instance_id))
		if blob is None:
			return None
		try:
			return pickle.loads(blob)
		except Exception:
			log.warning("Corrupt cache entry for %s id=%s; evicting.", cls.__name__, instance_id)
			cache.delete(cls._get_instance_cache_key(instance_id))
			return None

	@classmethod
	def get_or_query(cls, instance_id: Any, session=None):
		"""
		Return a cached instance, falling back to a DB lookup on cache miss.

		The fetched instance is automatically re-cached on a miss.

		Args:
			instance_id: Primary-key value.
			session: SQLAlchemy Session (optional, used only on cache miss).

		Returns:
			Model instance or None if not found.
		"""
		cached = cls.get_cached(instance_id)
		if cached is not None:
			return cached

		if session is None:
			# Try the legacy .query interface when no session is passed
			if hasattr(cls, "query"):
				instance = cls.query.get(instance_id)
			else:
				log.warning("No session provided and .query unavailable; returning None.")
				return None
		else:
			instance = session.get(cls, instance_id)

		if instance is not None:
			cls.cache_instance(instance)
		return instance

	# ------------------------------------------------------------------
	# Bulk caching
	# ------------------------------------------------------------------

	@classmethod
	def bulk_cache(cls, instances: list) -> None:
		"""
		Cache multiple instances in a single pass.

		Attempts to use ``cache.set_many`` for backends that support it;
		falls back to individual ``cache.set`` calls otherwise.

		Args:
			instances: Iterable of model instances, each with an ``id`` attribute.
		"""
		cache = _get_cache()
		mapping: dict[str, bytes] = {
			cls._get_instance_cache_key(inst.id): pickle.dumps(
				inst, protocol=pickle.HIGHEST_PROTOCOL
			)
			for inst in instances
		}

		if hasattr(cache, "set_many"):
			try:
				cache.set_many(mapping, timeout=cls.__cache_timeout__)
				log.debug("bulk_cache: stored %d %s instances", len(mapping), cls.__name__)
				return
			except Exception:
				log.debug("set_many failed; falling back to individual set calls", exc_info=True)

		for key, blob in mapping.items():
			cache.set(key, blob, timeout=cls.__cache_timeout__)
		log.debug("bulk_cache: stored %d %s instances (individual)", len(mapping), cls.__name__)

	# ------------------------------------------------------------------
	# Query-level caching
	# ------------------------------------------------------------------

	@classmethod
	def cached_query(cls, key: str | None = None, timeout: int | None = None) -> CachedQuery:
		"""
		Return a CachedQuery pre-marked for caching.

		Args:
			key: Explicit cache key.
			timeout: TTL in seconds; uses __cache_timeout__ if omitted.

		Returns:
			CachedQuery instance ready for further chaining.
		"""
		return cls.query.cache(key=key, timeout=timeout or cls.__cache_timeout__)

	# ------------------------------------------------------------------
	# Method-level caching decorator
	# ------------------------------------------------------------------

	@staticmethod
	def cached_method(timeout: int | None = None) -> Callable[[F], F]:
		"""
		Decorator that caches the return value of an instance method.

		The cache key incorporates the class name, instance id, method name,
		and call arguments, so different argument combinations are cached
		independently.

		Args:
			timeout: TTL in seconds.  Uses the model's __cache_timeout__ if None.

		Example::

			@CacheMixin.cached_method(timeout=600)
			def compute_stats(self, period: str = "monthly") -> dict:
				...
		"""
		def decorator(func: F) -> F:
			@wraps(func)
			def wrapper(self, *args, **kwargs):
				cache = _get_cache()
				effective_timeout = timeout if timeout is not None else self.__cache_timeout__
				key = self.__class__._get_method_cache_key(
					self.id, func.__name__, args, kwargs
				)
				blob = cache.get(key)
				if blob is None:
					result = func(self, *args, **kwargs)
					cache.set(
						key,
						pickle.dumps(result, protocol=pickle.HIGHEST_PROTOCOL),
						timeout=effective_timeout,
					)
				else:
					try:
						result = pickle.loads(blob)
					except Exception:
						log.warning(
							"Corrupt method cache for %s.%s; recomputing.",
							self.__class__.__name__, func.__name__,
						)
						cache.delete(key)
						result = func(self, *args, **kwargs)
				return result
			return wrapper  # type: ignore[return-value]
		return decorator  # type: ignore[return-value]

	# ------------------------------------------------------------------
	# Instance helpers
	# ------------------------------------------------------------------

	def refresh_cache(self) -> None:
		"""Re-cache this instance, replacing any existing cached version."""
		self.__class__.cache_instance(self)

	def invalidate_cache(self) -> None:
		"""Explicitly remove this instance from the cache."""
		_get_cache().delete(self.__class__._get_instance_cache_key(self.id))

	# ------------------------------------------------------------------
	# Class-level cache management
	# ------------------------------------------------------------------

	@classmethod
	def clear_cache(cls) -> None:
		"""
		Best-effort eviction of all cached data associated with this model.

		Uses ``delete_memoized`` when the backend supports it; otherwise logs
		a warning directing the caller to use a pattern-based delete on their
		cache backend directly.
		"""
		cache = _get_cache()
		if hasattr(cache, "delete_memoized"):
			cache.delete_memoized(cls.get_cached)
			cache.delete_memoized(cls.cached_query)
		else:
			log.warning(
				"Cache backend does not support delete_memoized. "
				"To clear all %s cache entries, use a pattern-based delete "
				"(e.g. SCAN 'fabcache:%s:*') directly on your cache backend.",
				cls.__name__,
				cls.__name__,
			)

	@classmethod
	def warm_cache(cls, instance_ids: list, session=None) -> int:
		"""
		Pre-populate the cache for a list of primary-key values.

		Fetches all uncached ids in a single query, caches them via
		``bulk_cache``, and returns the number of instances actually fetched.

		Args:
			instance_ids: List of primary-key values to warm.
			session: SQLAlchemy Session required for SQLAlchemy 2.x callers.

		Returns:
			Number of instances loaded from the database.
		"""
		cache = _get_cache()
		uncached_ids = [
			iid for iid in instance_ids
			if cache.get(cls._get_instance_cache_key(iid)) is None
		]
		if not uncached_ids:
			return 0

		if session is not None:
			from sqlalchemy import select
			instances = list(
				session.scalars(
					select(cls).where(cls.id.in_(uncached_ids))
				).all()
			)
		elif hasattr(cls, "query"):
			instances = cls.query.filter(cls.id.in_(uncached_ids)).all()
		else:
			log.warning("warm_cache: no session and no .query; cannot warm cache.")
			return 0

		if instances:
			cls.bulk_cache(instances)
		return len(instances)
