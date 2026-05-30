"""
replication_mixin.py

A comprehensive data replication system for PgAppForge applications that provides
robust, fault-tolerant data synchronization across distributed database instances.

Key Features:
- Asynchronous multi-master replication with conflict resolution
- Support for standard JSON and PostgreSQL JSONB (with graceful fallback)
- Automatic failover and recovery mechanisms
- Real-time replication monitoring and health checks
- Customizable conflict resolution strategies
- Bulk replication and data migration tools
- Audit logging and replication history
- Performance optimization with batched operations
- Security features including encryption and access control
- Integration with PgAppForge security model

Dependencies:
    - SQLAlchemy>=2.0
    - PgAppForge>=4.0
    - python-jose[cryptography]>=3.3.0  (optional, for encryption)
    - aiohttp>=3.8.0                    (optional, for HTTP-based replication)
    - tenacity>=8.0.0

Author: Nyimbi Odero
Date: 25/08/2024
Version: 3.0
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

try:
	from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
	from sqlalchemy import String, Integer, DateTime, Enum as SAEnum
	_SA2_MAPPED = True
except ImportError:
	_SA2_MAPPED = False

from sqlalchemy import (
	JSON,
	Boolean,
	Column,
	DateTime,
	ForeignKey,
	Integer,
	String,
	event,
	func,
	inspect,
	select,
	text,
)
from sqlalchemy.orm import Session

try:
	from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
	_PG_TYPES = True
except ImportError:
	_PG_TYPES = False

from sqlalchemy.ext.declarative import declared_attr

# Optional: tenacity for retry logic
try:
	from tenacity import retry, stop_after_attempt, wait_exponential
	_TENACITY = True
except ImportError:
	_TENACITY = False

	def retry(*args, **kwargs):
		"""No-op retry decorator when tenacity is unavailable."""
		def decorator(fn):
			return fn
		return decorator

	def stop_after_attempt(n):
		return None

	def wait_exponential(**kwargs):
		return None

# Optional: aiohttp for HTTP-based cross-service replication
try:
	import aiohttp as _aiohttp
	_AIOHTTP = True
except ImportError:
	_AIOHTTP = False

# Optional: python-jose for JWT-based payload encryption
try:
	from jose import jwt as _jwt
	_JOSE = True
except ImportError:
	_JOSE = False

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Replication status literals — used as the Enum values in the column.
# We avoid SQLAlchemy's Enum type directly on the class body to stay
# compatible with both declarative bases.
# ---------------------------------------------------------------------------
REPLICATION_STATUSES = ("PENDING", "IN_PROGRESS", "COMPLETED", "FAILED", "CONFLICT")


class ReplicationConfig:
	"""Configuration settings for replication behaviour.

	All parameters are optional; sane defaults are provided for every
	field so callers only need to override what differs.
	"""

	DEFAULT_RETRY_ATTEMPTS: int = 3
	DEFAULT_BATCH_SIZE: int = 1000
	DEFAULT_TIMEOUT: int = 30
	DEFAULT_SYNC_INTERVAL: int = 300		# 5 minutes
	DEFAULT_HEALTH_CHECK_INTERVAL: int = 60	# 1 minute

	def __init__(self, **kwargs: Any) -> None:
		self.retry_attempts: int = kwargs.get("retry_attempts", self.DEFAULT_RETRY_ATTEMPTS)
		self.batch_size: int = kwargs.get("batch_size", self.DEFAULT_BATCH_SIZE)
		self.timeout: int = kwargs.get("timeout", self.DEFAULT_TIMEOUT)
		self.sync_interval: int = kwargs.get("sync_interval", self.DEFAULT_SYNC_INTERVAL)
		self.health_check_interval: int = kwargs.get(
			"health_check_interval", self.DEFAULT_HEALTH_CHECK_INTERVAL
		)
		self.encrypt_data: bool = kwargs.get("encrypt_data", False)
		self.encryption_secret: str | None = kwargs.get("encryption_secret", None)
		self.compression_enabled: bool = kwargs.get("compression_enabled", False)
		self.verify_checksum: bool = kwargs.get("verify_checksum", True)
		self.failover_enabled: bool = kwargs.get("failover_enabled", False)


class ReplicationMixin:
	"""
	Advanced mixin for database replication with comprehensive features for
	distributed systems and high-availability setups.

	Features:
	- Asynchronous multi-master replication
	- Conflict detection and resolution
	- Data validation and integrity checks
	- Performance optimization with batched operations
	- Monitoring and health checks
	- Optional payload encryption via python-jose

	Usage::

		from pgappforge import Model
		from sqlalchemy import Column, Integer, String
		from pgappforge.mixins.replication_mixin import ReplicationMixin, ReplicationConfig

		class Document(ReplicationMixin, Model):
			__tablename__ = 'nx_documents'

			__replication_config__ = ReplicationConfig(
				retry_attempts=5,
				batch_size=500,
				encrypt_data=True,
			)
			__replication_databases__ = [
				'postgresql://user:pass@db1/myapp',
				'postgresql://user:pass@db2/myapp',
			]

			id = Column(Integer, primary_key=True)
			title = Column(String(200), nullable=False)
	"""

	# ------------------------------------------------------------------
	# Class-level configuration — subclasses override these
	# ------------------------------------------------------------------
	__replication_key__: str = "replication_id"
	__replication_databases__: list[str] = []
	__replication_config__: ReplicationConfig = ReplicationConfig()

	# ------------------------------------------------------------------
	# Columns — declared via declared_attr so they are per-subclass
	# ------------------------------------------------------------------

	@declared_attr
	def replication_id(cls):
		"""Unique identifier for replication tracking (UUID string)."""
		return Column(
			String(36),
			unique=True,
			default=lambda: str(uuid.uuid4()),
			nullable=False,
			index=True,
		)

	@declared_attr
	def last_replicated(cls):
		"""Timestamp of last successful replication (UTC, timezone-aware)."""
		return Column(DateTime(timezone=True), nullable=True, index=True)

	@declared_attr
	def replication_status(cls):
		"""Current replication status."""
		return Column(
			SAEnum(*REPLICATION_STATUSES, name="replication_status_enum", create_type=False),
			nullable=False,
			default="PENDING",
			index=True,
		)

	@declared_attr
	def replication_version(cls):
		"""Monotonically increasing version counter for conflict resolution."""
		return Column(Integer, nullable=False, default=1)

	@declared_attr
	def replication_metadata(cls):
		"""Opaque JSON metadata for replication bookkeeping."""
		# Prefer JSONB on PostgreSQL; fall back to generic JSON elsewhere.
		col_type = JSONB if _PG_TYPES else JSON
		return Column(col_type, nullable=False, default=dict)

	@declared_attr
	def checksum(cls):
		"""SHA-256 hex digest for data integrity verification."""
		return Column(String(64), nullable=True)

	# ------------------------------------------------------------------
	# Instance initialisation
	# ------------------------------------------------------------------

	def __init__(self, *args: Any, **kwargs: Any) -> None:
		super().__init__(*args, **kwargs)
		# Avoid importing g/current_app at module level — may not have app
		# context yet.
		try:
			from flask import current_app, g
			source_db = current_app.config.get("SQLALCHEMY_DATABASE_URI", "unknown")
			user_id = getattr(getattr(g, "user", None), "id", None)
		except RuntimeError:
			# No application context — likely during testing/init
			source_db = "unknown"
			user_id = None

		self.replication_metadata = {
			"created_at": datetime.now(timezone.utc).isoformat(),
			"created_by": user_id,
			"source_db": source_db,
		}

	# ------------------------------------------------------------------
	# Event listener wiring
	# ------------------------------------------------------------------

	@classmethod
	def __declare_last__(cls) -> None:
		"""Wire up SQLAlchemy event listeners after mapper configuration."""
		event.listen(cls, "after_insert", cls._after_insert)
		event.listen(cls, "after_update", cls._after_update)
		event.listen(cls, "after_delete", cls._after_delete)

		# Scheduler integration (APScheduler / Flask-APScheduler)
		try:
			from flask import current_app
			if hasattr(current_app, "scheduler"):
				current_app.scheduler.add_job(
					func=cls._check_replication_health,
					trigger="interval",
					seconds=cls.__replication_config__.health_check_interval,
					id=f"health_check_{cls.__name__}",
					replace_existing=True,
				)
		except RuntimeError:
			pass  # No app context during class definition — scheduler wired later

	@classmethod
	def _after_insert(cls, mapper: Any, connection: Any, target: Any) -> None:
		"""Schedule post-insert replication."""
		cls._schedule_replication(target, "insert")

	@classmethod
	def _after_update(cls, mapper: Any, connection: Any, target: Any) -> None:
		"""Schedule post-update replication."""
		cls._schedule_replication(target, "update")

	@classmethod
	def _after_delete(cls, mapper: Any, connection: Any, target: Any) -> None:
		"""Schedule post-delete replication."""
		cls._schedule_replication(target, "delete")

	@classmethod
	def _schedule_replication(cls, target: Any, operation: str) -> None:
		"""
		Submit replication coroutine to a running event loop if one exists,
		otherwise log a warning.  asyncio.create_task() requires an active
		running loop; we get the running loop explicitly so we don't silently
		swallow errors.
		"""
		try:
			loop = asyncio.get_running_loop()
			loop.create_task(cls._async_replicate(target, operation))
		except RuntimeError:
			# No running loop in synchronous Flask context — fire-and-forget
			# via a fresh loop on a background thread.
			import threading

			def _run() -> None:
				asyncio.run(cls._async_replicate(target, operation))

			threading.Thread(target=_run, daemon=True).start()

	# ------------------------------------------------------------------
	# Core async replication machinery
	# ------------------------------------------------------------------

	@classmethod
	async def _async_replicate(cls, instance: Any, operation: str) -> None:
		"""
		Asynchronously replicate a change to all configured replica databases.

		Args:
			instance:  The model instance that changed.
			operation: One of 'insert', 'update', 'delete'.
		"""
		replication_data = cls._prepare_replication_data(instance)

		# Bump version and refresh metadata before dispatching
		instance.replication_version = (instance.replication_version or 0) + 1
		instance.replication_status = "IN_PROGRESS"

		try:
			from flask import g
			user_id = getattr(getattr(g, "user", None), "id", None)
		except RuntimeError:
			user_id = None

		meta: dict[str, Any] = dict(instance.replication_metadata or {})
		meta.update(
			{
				"last_operation": operation,
				"last_modified_at": datetime.now(timezone.utc).isoformat(),
				"last_modified_by": user_id,
			}
		)
		instance.replication_metadata = meta
		instance.checksum = cls._calculate_checksum(replication_data)

		tasks = [
			cls._replicate_to_database(db_url, instance, operation, replication_data)
			for db_url in cls.__replication_databases__
		]

		try:
			await asyncio.gather(*tasks)
			instance.last_replicated = datetime.now(timezone.utc)
			instance.replication_status = "COMPLETED"
		except Exception as exc:
			instance.replication_status = "FAILED"
			logger.error("Replication error for %s [%s]: %s", cls.__name__, operation, exc)
			if cls.__replication_config__.failover_enabled:
				asyncio.create_task(cls._handle_failover(instance))

	@classmethod
	@retry(
		stop=stop_after_attempt(ReplicationConfig.DEFAULT_RETRY_ATTEMPTS),
		wait=wait_exponential(multiplier=1, min=4, max=10),
	)
	async def _replicate_to_database(
		cls,
		db_url: str,
		instance: Any,
		operation: str,
		data: dict[str, Any],
	) -> None:
		"""
		Replicate *data* to a single target database, with retry on failure.

		Uses SQLAlchemy's async engine directly — does not depend on the
		removed ``sqlalchemy_replicated`` package.

		Args:
			db_url:    Target database connection URL.
			instance:  The source model instance.
			operation: 'insert', 'update', or 'delete'.
			data:      Serialised column data from _prepare_replication_data().
		"""
		from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

		# Convert sync URL to async dialect (postgresql:// -> postgresql+asyncpg://)
		async_url = _to_async_url(db_url)
		engine = create_async_engine(async_url, echo=False, pool_pre_ping=True)

		async with AsyncSession(engine) as session:
			try:
				if operation == "delete":
					stmt = select(cls).where(
						cls.replication_id == instance.replication_id
					)
					result = await session.execute(stmt)
					existing = result.scalar_one_or_none()
					if existing is not None:
						await session.delete(existing)
				else:
					stmt = select(cls).where(
						cls.replication_id == instance.replication_id
					)
					result = await session.execute(stmt)
					existing = result.scalar_one_or_none()

					if existing is not None:
						if operation == "update":
							for key, value in data.items():
								setattr(existing, key, value)
					else:
						session.add(cls(**data))

				await session.commit()

			except Exception as exc:
				await session.rollback()
				logger.error("Database replication error to %s: %s", db_url, exc)
				raise
		await engine.dispose()

	# ------------------------------------------------------------------
	# Data preparation helpers
	# ------------------------------------------------------------------

	@classmethod
	def _prepare_replication_data(cls, instance: Any) -> dict[str, Any]:
		"""
		Serialise *instance* column values into a plain dict suitable for
		transmission and re-insertion.

		JSON/JSONB columns are round-tripped through json.dumps/loads to
		ensure the value is JSON-safe.  UUID columns are stringified.
		Encryption is applied if configured.

		Args:
			instance: Source model instance.

		Returns:
			Mapping of column key -> serialised value.
		"""
		data: dict[str, Any] = {}
		_exclude = {"id", "last_replicated"}

		for column in instance.__table__.columns:
			if column.key in _exclude:
				continue
			value = getattr(instance, column.key)

			# Normalise special types
			if isinstance(column.type, JSON) or (_PG_TYPES and isinstance(column.type, JSONB)):
				if value is not None:
					# Ensure round-trip safety
					value = json.loads(json.dumps(value, default=str))
			elif _PG_TYPES and isinstance(column.type, PG_UUID):
				value = str(value) if value is not None else None
			elif isinstance(value, uuid.UUID):
				value = str(value)

			# Optional field-level encryption
			if cls.__replication_config__.encrypt_data and value is not None:
				value = cls._encrypt_value(value)

			data[column.key] = value

		return data

	@staticmethod
	def _calculate_checksum(data: dict[str, Any]) -> str:
		"""Return SHA-256 hex digest of the canonically serialised *data*."""
		serialised = json.dumps(data, sort_keys=True, default=str).encode("utf-8")
		return hashlib.sha256(serialised).hexdigest()

	@classmethod
	def _encrypt_value(cls, value: Any) -> str | None:
		"""
		Encrypt *value* using HS256 JWT if python-jose is available and an
		encryption secret is configured.  Falls back to returning the value
		unchanged with a warning.
		"""
		if not _JOSE:
			logger.warning(
				"encrypt_data=True but python-jose is not installed; "
				"value transmitted in plain text."
			)
			return value

		secret = cls.__replication_config__.encryption_secret
		if not secret:
			logger.warning(
				"encrypt_data=True but encryption_secret is not set; "
				"value transmitted in plain text."
			)
			return value

		payload = {"v": value if isinstance(value, (str, int, float, bool, type(None))) else str(value)}
		return _jwt.encode(payload, secret, algorithm="HS256")

	@classmethod
	def _decrypt_value(cls, token: str) -> Any:
		"""Decrypt a value encrypted by _encrypt_value()."""
		if not _JOSE:
			return token
		secret = cls.__replication_config__.encryption_secret
		if not secret:
			return token
		payload = _jwt.decode(token, secret, algorithms=["HS256"])
		return payload.get("v")

	# ------------------------------------------------------------------
	# Bulk sync
	# ------------------------------------------------------------------

	@classmethod
	async def sync_from_primary(
		cls,
		primary_db_url: str,
		batch_size: int | None = None,
	) -> None:
		"""
		Full resync from *primary_db_url* in configurable batches.

		Args:
			primary_db_url: Source database URL (sync or async dialect accepted).
			batch_size:     Override the configured batch size.
		"""
		from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

		batch_size = batch_size or cls.__replication_config__.batch_size
		async_url = _to_async_url(primary_db_url)
		engine = create_async_engine(async_url, echo=False)

		async with AsyncSession(engine) as primary_session:
			count_result = await primary_session.execute(
				select(func.count()).select_from(cls)
			)
			total_count: int = count_result.scalar_one()

			for offset in range(0, total_count, batch_size):
				stmt = select(cls).offset(offset).limit(batch_size)
				result = await primary_session.execute(stmt)
				batch = result.scalars().all()
				await cls._sync_batch(batch)

		await engine.dispose()

	@classmethod
	async def _sync_batch(cls, instances: list[Any]) -> None:
		"""Apply a batch of primary instances to all replica databases."""
		tasks = []
		for instance in instances:
			data = cls._prepare_replication_data(instance)
			for db_url in cls.__replication_databases__:
				tasks.append(
					cls._replicate_to_database(db_url, instance, "insert", data)
				)
		await asyncio.gather(*tasks, return_exceptions=True)

	# ------------------------------------------------------------------
	# Conflict resolution
	# ------------------------------------------------------------------

	@classmethod
	async def resolve_conflicts(
		cls,
		conflict_resolution_strategy: Callable[..., Any] | None = None,
		dry_run: bool = False,
	) -> dict[str, Any]:
		"""
		Detect and resolve replication conflicts across all configured databases.

		Args:
			conflict_resolution_strategy:
				Async callable ``(list[instance]) -> instance`` that picks the
				winner when multiple databases hold divergent versions of the
				same replication_id.  Defaults to highest-version-wins with
				last_replicated timestamp as tiebreaker.
			dry_run:
				When True, report conflicts without modifying any database.

		Returns:
			Summary dict with keys: total_conflicts, resolved, failed, details.
		"""
		conflicts = await cls._detect_conflicts()
		results: dict[str, Any] = {
			"total_conflicts": len(conflicts),
			"resolved": 0,
			"failed": 0,
			"details": [],
		}

		for conflict in conflicts:
			try:
				if not dry_run:
					resolved_instance = await cls._resolve_conflict(
						conflict, conflict_resolution_strategy
					)
					await cls._propagate_resolution(resolved_instance)
					results["resolved"] += 1

				results["details"].append(
					{
						"replication_id": str(conflict["replication_id"]),
						"status": "resolved" if not dry_run else "detected",
						"databases_involved": conflict["databases"],
					}
				)
			except Exception as exc:
				results["failed"] += 1
				results["details"].append(
					{
						"replication_id": str(conflict["replication_id"]),
						"status": "failed",
						"error": str(exc),
					}
				)
				logger.error("Conflict resolution failed for %s: %s", conflict.get("replication_id"), exc)

		return results

	@classmethod
	async def _detect_conflicts(cls) -> list[dict[str, Any]]:
		"""
		Scan all replica databases and return records where replication_id
		maps to differing checksums across databases.

		Returns:
			List of conflict descriptors, each with keys: replication_id,
			databases, instances.
		"""
		from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

		# Map replication_id -> {db_url: instance}
		seen: dict[str, dict[str, Any]] = {}

		for db_url in cls.__replication_databases__:
			async_url = _to_async_url(db_url)
			engine = create_async_engine(async_url, echo=False)
			async with AsyncSession(engine) as session:
				result = await session.execute(select(cls))
				for instance in result.scalars():
					rid = str(instance.replication_id)
					seen.setdefault(rid, {})
					seen[rid][db_url] = instance
			await engine.dispose()

		conflicts: list[dict[str, Any]] = []
		for rid, db_map in seen.items():
			if len(db_map) < 2:
				continue
			checksums = {db: inst.checksum for db, inst in db_map.items()}
			if len(set(checksums.values())) > 1:
				conflicts.append(
					{
						"replication_id": rid,
						"databases": list(db_map.keys()),
						"instances": list(db_map.values()),
					}
				)

		return conflicts

	@classmethod
	async def _resolve_conflict(
		cls,
		conflict: dict[str, Any],
		strategy: Callable[..., Any] | None,
	) -> Any:
		"""
		Apply *strategy* to pick the winning instance, or fall back to the
		built-in highest-version / latest-timestamp heuristic.
		"""
		instances: list[Any] = conflict["instances"]

		if strategy is not None:
			return await strategy(instances)

		# Built-in: highest replication_version wins; ties broken by last_replicated
		return max(
			instances,
			key=lambda i: (
				i.replication_version or 0,
				i.last_replicated or datetime.min.replace(tzinfo=timezone.utc),
			),
		)

	@classmethod
	async def _propagate_resolution(cls, winner: Any) -> None:
		"""Write the winning instance to all replica databases."""
		data = cls._prepare_replication_data(winner)
		tasks = [
			cls._replicate_to_database(db_url, winner, "update", data)
			for db_url in cls.__replication_databases__
		]
		await asyncio.gather(*tasks)

	# ------------------------------------------------------------------
	# Failover
	# ------------------------------------------------------------------

	@classmethod
	async def _handle_failover(cls, instance: Any) -> None:
		"""
		Attempt to re-queue a failed replication after a brief back-off.
		Subclasses may override this to integrate with an external queue
		(e.g. Celery, Redis Streams, SQS).
		"""
		logger.warning(
			"Initiating failover for %s id=%s",
			cls.__name__,
			getattr(instance, "replication_id", "?"),
		)
		await asyncio.sleep(5)
		await cls._async_replicate(instance, "update")

	# ------------------------------------------------------------------
	# Health monitoring
	# ------------------------------------------------------------------

	@classmethod
	async def _check_replication_health(cls) -> dict[str, Any]:
		"""
		Probe every configured replica database and report connectivity and
		estimated replication lag.

		Returns:
			Dict with keys: status ('healthy' | 'degraded'), timestamp, databases.
		"""
		from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

		health: dict[str, Any] = {
			"status": "healthy",
			"timestamp": datetime.now(timezone.utc).isoformat(),
			"databases": {},
		}

		for db_url in cls.__replication_databases__:
			try:
				async_url = _to_async_url(db_url)
				engine = create_async_engine(async_url, echo=False, pool_pre_ping=True)
				async with AsyncSession(engine) as session:
					lag = await cls._calculate_replication_lag(session)
					last_ok = await cls._get_last_replication(session)
					health["databases"][db_url] = {
						"status": "online",
						"replication_lag_seconds": lag,
						"last_successful_replication": last_ok,
					}
				await engine.dispose()
			except Exception as exc:
				health["status"] = "degraded"
				health["databases"][db_url] = {
					"status": "offline",
					"error": str(exc),
				}

		return health

	@classmethod
	async def _calculate_replication_lag(cls, session: Any) -> float | None:
		"""
		Estimate replication lag as seconds since the most recently completed
		replication event recorded in *session*.  Returns None if no data.
		"""
		stmt = (
			select(func.max(cls.last_replicated))
			.where(cls.replication_status == "COMPLETED")
		)
		result = await session.execute(stmt)
		last_ts = result.scalar_one_or_none()
		if last_ts is None:
			return None
		if last_ts.tzinfo is None:
			last_ts = last_ts.replace(tzinfo=timezone.utc)
		return (datetime.now(timezone.utc) - last_ts).total_seconds()

	@classmethod
	async def _get_last_replication(cls, session: Any) -> str | None:
		"""
		Return the ISO-8601 timestamp of the most recent successful
		replication visible from *session*, or None.
		"""
		stmt = (
			select(func.max(cls.last_replicated))
			.where(cls.replication_status == "COMPLETED")
		)
		result = await session.execute(stmt)
		ts = result.scalar_one_or_none()
		return ts.isoformat() if ts is not None else None


# ---------------------------------------------------------------------------
# Module-level helper
# ---------------------------------------------------------------------------

def _to_async_url(db_url: str) -> str:
	"""
	Convert a synchronous SQLAlchemy database URL to its async counterpart.

	- ``postgresql://`` -> ``postgresql+asyncpg://``
	- ``sqlite:///``    -> ``sqlite+aiosqlite:///``
	- Already async URLs pass through unchanged.
	"""
	if "+async" in db_url or "asyncpg" in db_url or "aiosqlite" in db_url:
		return db_url
	if db_url.startswith("postgresql://") or db_url.startswith("postgres://"):
		return db_url.replace("postgresql://", "postgresql+asyncpg://", 1).replace(
			"postgres://", "postgresql+asyncpg://", 1
		)
	if db_url.startswith("sqlite:///"):
		return db_url.replace("sqlite:///", "sqlite+aiosqlite:///", 1)
	# mysql, mssql, etc. — return as-is and let the caller handle driver selection
	return db_url
