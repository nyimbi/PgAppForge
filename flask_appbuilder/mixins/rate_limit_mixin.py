"""
rate_limit_mixin.py

Comprehensive rate limiting for Flask-AppBuilder applications with distributed
enforcement, burst handling, gradual throttling, configurable fallbacks, and
detailed analytics.

Key Features:
- Flexible rate limit definitions with multiple strategies
- Distributed rate limiting via Redis (optional; falls back to in-process)
- Burst allowance with token bucket algorithm
- Gradual throttling with probabilistic backoff
- Role-based rate limit overrides
- Detailed analytics and violation tracking via DB model
- Multiple identifier strategies (IP, User, API Key, Combined, Custom)
- Prometheus metrics (optional; skipped when prometheus_client absent)
- Full audit trail of violations

Dependencies:
    - SQLAlchemy >= 2.0
    - Flask-AppBuilder >= 4.0
    - redis >= 4.0 (optional; in-process fallback activates if absent)
    - prometheus_client (optional)

Author: Nyimbi Odero
Date: 2024-08-25
Version: 2.0.0
"""

from __future__ import annotations

import hashlib
import json
import logging
import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

import urllib.request  # stdlib only; no requests dependency

from flask import abort, current_app, g, request
from flask_appbuilder import Model
from sqlalchemy import (
	JSON,
	Boolean,
	DateTime,
	Float,
	Index,
	Integer,
	String,
	Text,
	event,
)
from sqlalchemy.orm import validates
from sqlalchemy.sql import func

# SQLAlchemy 2.x mapped columns (with 1.x fallback)
try:
	from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
	_SQLA2 = True
except ImportError:
	_SQLA2 = False

from sqlalchemy.ext.declarative import declared_attr

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional metrics
# ---------------------------------------------------------------------------
try:
	from prometheus_client import Counter, Gauge, Histogram

	RATE_LIMIT_VIOLATIONS = Counter(
		"rate_limit_violations_total",
		"Number of rate limit violations",
		["model", "operation", "identifier_type"],
	)
	RATE_LIMIT_LATENCY = Histogram(
		"rate_limit_check_latency_seconds",
		"Latency of rate limit checks",
		["model", "operation"],
	)
	RATE_LIMIT_REMAINING = Gauge(
		"rate_limit_remaining",
		"Remaining rate limit quota",
		["model", "operation", "identifier_type"],
	)
	_PROMETHEUS = True
except ImportError:
	_PROMETHEUS = False

	class _Noop:
		"""Drop-in stub for prometheus metric objects."""
		def labels(self, *a, **kw):
			return self
		def inc(self, *a, **kw): pass
		def set(self, *a, **kw): pass
		def time(self):
			import contextlib
			return contextlib.nullcontext()

	RATE_LIMIT_VIOLATIONS = _Noop()
	RATE_LIMIT_LATENCY = _Noop()
	RATE_LIMIT_REMAINING = _Noop()

# ---------------------------------------------------------------------------
# Optional Redis
# ---------------------------------------------------------------------------
try:
	import redis as _redis_module
	_REDIS_AVAILABLE = True
except ImportError:
	_REDIS_AVAILABLE = False
	_redis_module = None

try:
	import aioredis as _aioredis_module
	_AIOREDIS_AVAILABLE = True
except ImportError:
	_AIOREDIS_AVAILABLE = False
	_aioredis_module = None


# ---------------------------------------------------------------------------
# Configuration dataclass
# ---------------------------------------------------------------------------

@dataclass
class RateLimitConfig:
	"""Configuration for a single rate limit policy."""

	limit: int
	per: int  # window size in seconds
	by: str   # "ip" | "user" | "api_key" | "combined" | "custom"
	burst_multiplier: float = 1.0
	throttle_threshold: float = 0.8
	backoff_factor: float = 2.0
	alert_threshold: float = 0.9
	bypass_roles: list[str] = field(default_factory=list)
	custom_identifier: Callable[[], str] | None = None
	fallback_limit: int | None = None


# ---------------------------------------------------------------------------
# Mixin
# ---------------------------------------------------------------------------

class RateLimitMixin:
	"""
	Advanced rate limiting mixin with distributed enforcement and analytics.

	Usage::

		class MyModel(RateLimitMixin, Model):
			__tablename__ = "my_model"
			__rate_limits__ = {
				"search": RateLimitConfig(limit=1000, per=3600, by="user",
				                          burst_multiplier=1.5,
				                          bypass_roles=["admin"]),
			}
	"""

	__rate_limits__: dict[str, RateLimitConfig] = {}
	__cache_config__: dict[str, Any] = {"enabled": True, "ttl": 300, "max_size": 10000}

	# In-process fallback state; keyed by (operation, identifier)
	_local_cache: dict[str, tuple[int, float]] = {}

	@classmethod
	def __declare_last__(cls) -> None:
		"""Validate and normalise rate limit configuration on model declaration."""
		if not cls.__rate_limits__:
			cls.__rate_limits__ = {
				"default": RateLimitConfig(
					limit=1000, per=3600, by="ip", burst_multiplier=1.5
				)
			}
			logger.warning("No rate limits defined for %s, using defaults", cls.__name__)

		for op, config in list(cls.__rate_limits__.items()):
			if isinstance(config, dict):
				cls.__rate_limits__[op] = RateLimitConfig(**config)

	# ------------------------------------------------------------------
	# Redis client helpers
	# ------------------------------------------------------------------

	@staticmethod
	def _get_redis_url() -> str:
		return current_app.config.get("REDIS_URL", "redis://localhost:6379/0")

	@staticmethod
	def get_redis_client(async_mode: bool = False):
		"""Return a cached Redis (or aioredis) client from the app context."""
		if async_mode:
			if not _AIOREDIS_AVAILABLE:
				raise RuntimeError("aioredis is not installed; cannot use async Redis.")
			if not hasattr(current_app, "aioredis_client"):
				current_app.aioredis_client = _aioredis_module.from_url(
					RateLimitMixin._get_redis_url()
				)
			return current_app.aioredis_client

		if not _REDIS_AVAILABLE:
			return None  # caller must handle None → local fallback

		if not hasattr(current_app, "redis_client"):
			current_app.redis_client = _redis_module.from_url(
				RateLimitMixin._get_redis_url()
			)
		return current_app.redis_client

	# ------------------------------------------------------------------
	# Identifier resolution
	# ------------------------------------------------------------------

	@classmethod
	def get_identifier(cls, operation: str) -> str:
		"""Resolve a rate-limit identifier for the current request."""
		config = cls.__rate_limits__[operation]

		if config.custom_identifier is not None:
			return config.custom_identifier()

		by = config.by
		if by == "ip":
			return request.remote_addr or "unknown"
		if by == "user":
			user = getattr(g, "user", None)
			return str(user.id) if user else "anonymous"
		if by == "api_key":
			return request.headers.get("X-API-Key", "anonymous")
		if by == "combined":
			parts: list[str] = [request.remote_addr or ""]
			user = getattr(g, "user", None)
			if user:
				parts.append(str(user.id))
			api_key = request.headers.get("X-API-Key")
			if api_key:
				parts.append(api_key)
			return hashlib.sha256(":".join(parts).encode()).hexdigest()

		raise ValueError(f"Invalid identifier type: {by!r}")

	# ------------------------------------------------------------------
	# Public check interface
	# ------------------------------------------------------------------

	@classmethod
	async def check_rate_limit_async(
		cls, operation: str, identifier: str | None = None
	) -> bool:
		"""Asynchronous rate limit check (requires aioredis)."""
		redis_client = cls.get_redis_client(async_mode=True)
		config = cls._resolve_config(operation)
		identifier = identifier or cls.get_identifier(operation)
		return await cls._check_redis_async(operation, identifier, config, redis_client)

	@classmethod
	def check_rate_limit(
		cls, operation: str, identifier: str | None = None
	) -> bool:
		"""
		Synchronous rate limit check.

		Returns True when the request is allowed, False (or aborts 429) when
		the limit is exceeded.
		"""
		with RATE_LIMIT_LATENCY.labels(cls.__name__, operation).time():
			config = cls._resolve_config(operation)

			# Role bypass
			user = getattr(g, "user", None)
			if config.bypass_roles and user:
				if any(getattr(user, "has_role", lambda r: False)(role)
				       for role in config.bypass_roles):
					return True

			identifier = identifier or cls.get_identifier(operation)
			redis_client = cls.get_redis_client()

			if redis_client is None:
				# No Redis installed → go straight to local fallback
				return cls._check_local_fallback(operation, identifier)

			try:
				return cls._check_redis_sync(operation, identifier, config, redis_client)
			except Exception as exc:  # redis.RedisError or connection errors
				logger.error("Redis error during rate limit check: %s", exc)
				if config.fallback_limit is not None:
					return cls._check_local_fallback(operation, identifier)
				raise

	# ------------------------------------------------------------------
	# Internal: config resolution
	# ------------------------------------------------------------------

	@classmethod
	def _resolve_config(cls, operation: str) -> RateLimitConfig:
		if operation not in cls.__rate_limits__:
			logger.warning("Unknown operation %r for %s, using default", operation, cls.__name__)
			operation = "default"
		return cls.__rate_limits__[operation]

	# ------------------------------------------------------------------
	# Internal: Redis sync implementation
	# ------------------------------------------------------------------

	@classmethod
	def _check_redis_sync(
		cls,
		operation: str,
		identifier: str,
		config: RateLimitConfig,
		redis_client,
	) -> bool:
		key = f"rate_limit:{cls.__name__}:{operation}:{identifier}"

		pipe = redis_client.pipeline()
		pipe.incr(key)
		pipe.expire(key, config.per)
		result = pipe.execute()

		request_count: int = result[0]
		effective_limit = int(config.limit * config.burst_multiplier)

		RATE_LIMIT_REMAINING.labels(cls.__name__, operation, config.by).set(
			max(0, effective_limit - request_count)
		)

		if request_count > effective_limit:
			cls._handle_violation(operation, identifier, config, throttled=False)
			return False

		if request_count > (config.limit * config.throttle_threshold):
			if cls._should_throttle(request_count, config):
				cls._handle_violation(operation, identifier, config, throttled=True)
				return False

		return True

	# ------------------------------------------------------------------
	# Internal: Redis async implementation
	# ------------------------------------------------------------------

	@classmethod
	async def _check_redis_async(
		cls,
		operation: str,
		identifier: str,
		config: RateLimitConfig,
		redis_client,
	) -> bool:
		key = f"rate_limit:{cls.__name__}:{operation}:{identifier}"

		pipe = redis_client.pipeline()
		pipe.incr(key)
		pipe.expire(key, config.per)
		result = await pipe.execute()

		request_count: int = result[0]
		effective_limit = int(config.limit * config.burst_multiplier)

		RATE_LIMIT_REMAINING.labels(cls.__name__, operation, config.by).set(
			max(0, effective_limit - request_count)
		)

		if request_count > effective_limit:
			cls._handle_violation(operation, identifier, config, throttled=False)
			return False

		if request_count > (config.limit * config.throttle_threshold):
			if cls._should_throttle(request_count, config):
				cls._handle_violation(operation, identifier, config, throttled=True)
				return False

		return True

	# ------------------------------------------------------------------
	# Internal: throttle decision
	# ------------------------------------------------------------------

	@classmethod
	def _should_throttle(cls, count: int, config: RateLimitConfig) -> bool:
		"""Probabilistic throttle once usage crosses throttle_threshold."""
		usage_ratio = count / max(1, int(config.limit * config.burst_multiplier))
		if usage_ratio <= config.throttle_threshold:
			return False
		throttle_prob = (usage_ratio - config.throttle_threshold) / max(
			1e-9, 1.0 - config.throttle_threshold
		)
		return random.random() < throttle_prob

	# ------------------------------------------------------------------
	# Internal: in-process fallback
	# ------------------------------------------------------------------

	@classmethod
	def _check_local_fallback(cls, operation: str, identifier: str) -> bool:
		"""In-process sliding-window counter when Redis is unavailable."""
		config = cls._resolve_config(operation)
		limit = config.fallback_limit if config.fallback_limit is not None else config.limit
		cache_key = f"{operation}:{identifier}"
		now = time.monotonic()

		count, window_start = cls._local_cache.get(cache_key, (0, now))

		if now - window_start >= config.per:
			# New window
			cls._local_cache[cache_key] = (1, now)
			return True

		if count >= limit:
			return False

		cls._local_cache[cache_key] = (count + 1, window_start)
		return True

	# ------------------------------------------------------------------
	# Internal: violation handling
	# ------------------------------------------------------------------

	@classmethod
	def _handle_violation(
		cls,
		operation: str,
		identifier: str,
		config: RateLimitConfig,
		throttled: bool = False,
	) -> None:
		label = "throttled" if throttled else "exceeded"
		logger.warning(
			"Rate limit %s for %s/%s by %s", label, cls.__name__, operation, identifier
		)

		RATE_LIMIT_VIOLATIONS.labels(cls.__name__, operation, config.by).inc()

		violation_meta: dict[str, Any] = {
			"user_agent": request.user_agent.string if request else None,
			"path": request.path if request else None,
			"method": request.method if request else None,
			"burst_multiplier": config.burst_multiplier,
			"throttle_threshold": config.throttle_threshold,
		}

		violation = RateLimitViolation(
			model_name=cls.__name__,
			operation=operation,
			identifier=identifier,
			limit=config.limit,
			period=config.per,
			throttled=throttled,
			violation_metadata=violation_meta,
		)

		try:
			db = current_app.extensions.get("sqlalchemy")
			if db:
				db.session.add(violation)
				db.session.commit()
		except Exception as exc:
			logger.error("Failed to persist rate limit violation: %s", exc)
			try:
				db.session.rollback()
			except Exception:
				pass

		if cls._should_alert(operation, config):
			cls._send_rate_limit_alert(operation, identifier, config)

		retry_after = int(config.per * config.backoff_factor)
		abort(429, description={
			"error": "Rate limit exceeded",
			"retry_after": retry_after,
			"limit": config.limit,
			"period": config.per,
			"throttled": throttled,
		})

	# ------------------------------------------------------------------
	# Internal: alert helpers
	# ------------------------------------------------------------------

	@classmethod
	def _should_alert(cls, operation: str, config: RateLimitConfig) -> bool:
		redis_client = cls.get_redis_client()
		if redis_client is None:
			return False
		key = f"alert:{cls.__name__}:{operation}"
		try:
			violations = redis_client.incr(key)
			redis_client.expire(key, 300)
			threshold = int(config.limit * config.alert_threshold)
			return violations >= threshold
		except Exception:
			return False

	@classmethod
	def _send_rate_limit_alert(
		cls, operation: str, identifier: str, config: RateLimitConfig
	) -> None:
		if not current_app.config.get("RATE_LIMIT_ALERTS_ENABLED"):
			return

		alert_data = {
			"model": cls.__name__,
			"operation": operation,
			"identifier": identifier,
			"limit": config.limit,
			"period": config.per,
			"timestamp": datetime.now(timezone.utc).isoformat(),
		}

		slack_url = current_app.config.get("SLACK_WEBHOOK_URL")
		if slack_url:
			try:
				payload = json.dumps({"text": f"Rate limit alert: {json.dumps(alert_data)}"}).encode()
				req = urllib.request.Request(
					slack_url,
					data=payload,
					headers={"Content-Type": "application/json"},
					method="POST",
				)
				urllib.request.urlopen(req, timeout=5)
			except Exception as exc:
				logger.error("Failed to send Slack rate limit alert: %s", exc)

	# ------------------------------------------------------------------
	# Public: status query
	# ------------------------------------------------------------------

	@classmethod
	def get_rate_limit_status(
		cls, operation: str, identifier: str | None = None
	) -> dict[str, Any]:
		"""Return current quota usage for an operation/identifier pair."""
		if operation not in cls.__rate_limits__:
			raise ValueError(f"Rate limit not defined for operation: {operation!r}")

		config = cls.__rate_limits__[operation]
		identifier = identifier or cls.get_identifier(operation)
		redis_client = cls.get_redis_client()

		if redis_client is None:
			cache_key = f"{operation}:{identifier}"
			count, _ = cls._local_cache.get(cache_key, (0, time.monotonic()))
			effective_limit = int(config.limit * config.burst_multiplier)
			return {
				"current_count": count,
				"limit": config.limit,
				"burst_limit": effective_limit,
				"remaining": max(0, effective_limit - count),
				"reset_in": config.per,
				"throttling": count > (config.limit * config.throttle_threshold),
				"usage_percent": (count / max(1, effective_limit)) * 100,
				"window_size": config.per,
				"identifier_type": config.by,
				"backend": "local",
			}

		key = f"rate_limit:{cls.__name__}:{operation}:{identifier}"
		try:
			pipe = redis_client.pipeline()
			pipe.get(key)
			pipe.ttl(key)
			result = pipe.execute()

			count = int(result[0]) if result[0] else 0
			ttl = result[1] if result[1] and result[1] > 0 else config.per
			effective_limit = int(config.limit * config.burst_multiplier)

			return {
				"current_count": count,
				"limit": config.limit,
				"burst_limit": effective_limit,
				"remaining": max(0, effective_limit - count),
				"reset_in": ttl,
				"throttling": count > (config.limit * config.throttle_threshold),
				"usage_percent": (count / max(1, effective_limit)) * 100,
				"window_size": config.per,
				"identifier_type": config.by,
				"backend": "redis",
			}
		except Exception as exc:
			logger.error("Redis error getting rate limit status: %s", exc)
			return {
				"error": "Rate limit status unavailable",
				"fallback_active": config.fallback_limit is not None,
			}

	# ------------------------------------------------------------------
	# Public: dynamic config update
	# ------------------------------------------------------------------

	@classmethod
	def update_rate_limit(cls, operation: str, **kwargs: Any) -> None:
		"""Merge kwargs into an existing RateLimitConfig at runtime."""
		if operation not in cls.__rate_limits__:
			raise ValueError(f"No rate limit config for operation: {operation!r}")
		config = cls.__rate_limits__[operation]
		for k, v in kwargs.items():
			if hasattr(config, k):
				setattr(config, k, v)
			else:
				raise AttributeError(f"RateLimitConfig has no attribute {k!r}")

	@classmethod
	def reset_rate_limit(cls, operation: str, identifier: str) -> bool:
		"""Reset the counter for a specific operation/identifier (Redis only)."""
		redis_client = cls.get_redis_client()
		if redis_client is None:
			cls._local_cache.pop(f"{operation}:{identifier}", None)
			return True
		key = f"rate_limit:{cls.__name__}:{operation}:{identifier}"
		try:
			redis_client.delete(key)
			return True
		except Exception as exc:
			logger.error("Failed to reset rate limit key %s: %s", key, exc)
			return False


# ---------------------------------------------------------------------------
# Violation model
# ---------------------------------------------------------------------------

class RateLimitViolation(Model):
	"""Persistent record of rate limit violations for audit and analytics."""

	__tablename__ = "nx_rate_limit_violations"
	__table_args__ = (
		Index("ix_rlv_model_operation", "model_name", "operation"),
		Index("ix_rlv_identifier", "identifier"),
		Index("ix_rlv_timestamp", "timestamp"),
	)

	id = mapped_column(Integer, primary_key=True) if _SQLA2 else None
	model_name = mapped_column(String(100), nullable=False) if _SQLA2 else None
	operation = mapped_column(String(100), nullable=False) if _SQLA2 else None
	identifier = mapped_column(String(255), nullable=False) if _SQLA2 else None
	limit = mapped_column(Integer, nullable=False) if _SQLA2 else None
	period = mapped_column(Integer, nullable=False) if _SQLA2 else None
	timestamp = mapped_column(DateTime(timezone=True), nullable=False) if _SQLA2 else None
	throttled = mapped_column(Boolean, default=False, nullable=False) if _SQLA2 else None
	# Named violation_metadata to avoid clash with SQLAlchemy's __table_args__ metadata attr
	violation_metadata = mapped_column(JSON, nullable=True) if _SQLA2 else None

	# SQLAlchemy 1.x column definitions (used when mapped_column is unavailable)
	if not _SQLA2:
		from sqlalchemy import Column as _Col
		id = _Col(Integer, primary_key=True)
		model_name = _Col(String(100), nullable=False)
		operation = _Col(String(100), nullable=False)
		identifier = _Col(String(255), nullable=False)
		limit = _Col(Integer, nullable=False)
		period = _Col(Integer, nullable=False)
		timestamp = _Col(DateTime, nullable=False)
		throttled = _Col(Boolean, default=False, nullable=False)
		violation_metadata = _Col(JSON, nullable=True)

	def __init__(self, **kwargs: Any) -> None:
		if "timestamp" not in kwargs:
			kwargs["timestamp"] = datetime.now(timezone.utc)
		super().__init__(**kwargs)

	def __repr__(self) -> str:
		return (
			f"<RateLimitViolation {self.model_name}:{self.operation} "
			f"by {self.identifier} at {self.timestamp}>"
		)

	@classmethod
	def get_violation_stats(
		cls,
		model_name: str | None = None,
		operation: str | None = None,
		timeframe: timedelta | None = None,
	) -> dict[str, Any]:
		"""Aggregate statistics over stored violations."""
		from sqlalchemy import select
		from flask import current_app

		db = current_app.extensions.get("sqlalchemy")
		if db is None:
			return {"error": "Database not available"}

		stmt = select(cls)
		if model_name:
			stmt = stmt.where(cls.model_name == model_name)
		if operation:
			stmt = stmt.where(cls.operation == operation)
		if timeframe:
			cutoff = datetime.now(timezone.utc) - timeframe
			stmt = stmt.where(cls.timestamp >= cutoff)

		rows = db.session.execute(stmt).scalars().all()

		total = len(rows)
		unique_ids = len({r.identifier for r in rows})

		# Group by hour (stdlib, no pandas)
		by_hour: dict[str, int] = {}
		for r in rows:
			ts = r.timestamp
			if ts:
				bucket = ts.strftime("%Y-%m-%dT%H:00:00")
				by_hour[bucket] = by_hour.get(bucket, 0) + 1

		# Group by (model_name, operation)
		by_type: dict[str, int] = {}
		for r in rows:
			key = f"{r.model_name}:{r.operation}"
			by_type[key] = by_type.get(key, 0) + 1

		return {
			"total_violations": total,
			"unique_identifiers": unique_ids,
			"by_hour": by_hour,
			"by_type": by_type,
		}
