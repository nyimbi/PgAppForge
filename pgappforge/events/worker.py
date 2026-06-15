"""pgappforge/events/worker.py

Durable background event worker — closes the multi-worker gap documented in
docs/research/09_composability_systems.md (row 4: "in-process only; dies under
multi-worker").

Architecture
------------
DomainEventLog is append-only (never updated). This module introduces a separate
``erp_event_dispatch_log`` table that tracks per-event dispatch state without
violating that constraint. The worker joins the two tables to find events pending
dispatch.

SELECT FOR UPDATE SKIP LOCKED gives exactly-once dispatch across N concurrent
worker processes without a distributed lock manager — any row locked by one
worker is transparently skipped by the others.

Deployment note: run exactly ONE EventWorker per deployment (not one per gunicorn
worker). The recommended pattern is a standalone process or a designated primary
worker identified via an env-var flag.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Table definition (SQLAlchemy Core — avoids ORM mapper conflicts)
# ---------------------------------------------------------------------------

_dispatch_table: Any = None  # sqlalchemy.Table, populated on first use


def _get_dispatch_table() -> Any | None:
	"""Return (and lazily create) the erp_event_dispatch_log Table object.

	Returns None when SQLAlchemy or DomainEventLog cannot be imported so the
	module loads cleanly in lightweight environments.
	"""
	global _dispatch_table
	if _dispatch_table is not None:
		return _dispatch_table

	try:
		import sqlalchemy as sa
		from pgappforge.plugins.erp.foundation.models import DomainEventLog

		# Attach to DomainEventLog's metadata so Alembic autogenerates the migration.
		metadata = DomainEventLog.metadata  # type: ignore[attr-defined]

		_dispatch_table = sa.Table(
			"erp_event_dispatch_log",
			metadata,
			sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
			sa.Column(
				"event_id",
				sa.String(36),
				sa.ForeignKey("erp_domain_event_log.event_id", ondelete="CASCADE"),
				nullable=False,
				unique=True,
			),
			# pending → retrying → done | dead
			sa.Column(
				"status",
				sa.String(20),
				nullable=False,
				default="pending",
				server_default=sa.text("'pending'"),
			),
			sa.Column(
				"retry_count",
				sa.Integer,
				nullable=False,
				default=0,
				server_default=sa.text("0"),
			),
			sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
			sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
			sa.Column("error_detail", sa.Text, nullable=True),
			sa.Index("ix_evdispatch_status_next", "status", "next_attempt_at"),
			extend_existing=True,
		)
		return _dispatch_table

	except Exception as exc:
		log.warning("EventWorker: cannot build dispatch table: %s", exc)
		return None


# ---------------------------------------------------------------------------
# EventWorker
# ---------------------------------------------------------------------------

class EventWorker:
	"""Daemon thread that drains DomainEventLog → EventRouter for multi-worker safety.

	Architecture:
	- Polls DomainEventLog table for events with status='pending'
	- Uses SELECT FOR UPDATE SKIP LOCKED to prevent double-processing across workers
	- Dispatches to the in-process EventRouter (which fires @on_event handlers)
	- Retries failed events with exponential backoff up to max_retries
	- After max_retries, sets status='dead' (dead-letter queue)

	Usage:
	    worker = EventWorker(sqlalchemy_engine, get_router())
	    worker.start()  # starts daemon thread
	    # ... app runs ...
	    worker.stop()   # graceful shutdown
	"""

	def __init__(
		self,
		engine: Any = None,
		router: Any = None,
		poll_interval: float = 5.0,
		max_retries: int = 3,
		batch_size: int = 50,
	) -> None:
		self._engine = engine
		self._router = router
		self._poll_interval = poll_interval
		self._max_retries = max_retries
		self._batch_size = batch_size

		self._stop_event = threading.Event()
		self._thread: threading.Thread | None = None
		self._lock = threading.Lock()

		self._stats: dict[str, Any] = {
			"processed": 0,
			"failed": 0,
			"dead": 0,
			"last_poll": None,
		}

	# ------------------------------------------------------------------
	# Public API
	# ------------------------------------------------------------------

	def start(self) -> None:
		"""Start the background polling thread."""
		if self._thread is not None and self._thread.is_alive():
			return
		self._stop_event.clear()
		self._thread = threading.Thread(
			target=self._run,
			name="pgappforge-event-worker",
			daemon=True,
		)
		self._thread.start()
		log.info(
			"EventWorker: started (poll_interval=%.1fs, max_retries=%d)",
			self._poll_interval,
			self._max_retries,
		)

	def stop(self, timeout: float = 30.0) -> None:
		"""Signal the worker to stop and wait for the thread to exit."""
		self._stop_event.set()
		if self._thread is not None:
			self._thread.join(timeout=timeout)
			self._thread = None
		log.info("EventWorker: stopped")

	def is_running(self) -> bool:
		return self._thread is not None and self._thread.is_alive()

	def stats(self) -> dict[str, Any]:
		"""Thread-safe snapshot of dispatch counters.

		Returns:
		    dict with keys: processed, failed, dead, last_poll (datetime | None)
		"""
		with self._lock:
			return dict(self._stats)

	def backoff(self, retry_count: int) -> float:
		"""Exponential backoff: min(poll_interval * 2**retry_count, 300)."""
		return min(self._poll_interval * (2 ** retry_count), 300.0)

	def drain(self, session: Any = None) -> int:
		"""Process pending events once. Returns count dispatched in this call. Safe with session=None."""
		t = _get_dispatch_table()
		if t is None or self._engine is None:
			log.debug("EventWorker.drain: no engine/table — skipping")
			return 0
		try:
			before = self._stats.get("processed", 0)
			self._poll(t)
			return self._stats.get("processed", 0) - before
		except Exception as exc:
			log.warning("EventWorker.drain: error: %s", exc)
			return 0

	def _increment_stat(self, key: str, amount: int = 1) -> None:
		"""Thread-safe stat counter increment."""
		with self._lock:
			self._stats[key] = self._stats.get(key, 0) + amount

	# ------------------------------------------------------------------
	# Internal loop
	# ------------------------------------------------------------------

	def _run(self) -> None:
		t = _get_dispatch_table()
		if t is None:
			log.warning("EventWorker: dispatch table unavailable — worker exiting immediately")
			return

		while not self._stop_event.is_set():
			try:
				self._poll(t)
			except Exception:
				log.exception("EventWorker: unhandled error in poll loop")
			with self._lock:
				self._stats["last_poll"] = datetime.now(timezone.utc)
			# Interruptible sleep: wakes immediately on stop()
			self._stop_event.wait(timeout=self._poll_interval)

	def _poll(self, t: Any) -> None:
		"""Claim a batch of due dispatch rows and process each one."""
		try:
			import sqlalchemy as sa
			from pgappforge.plugins.erp.foundation.models import DomainEventLog
		except ImportError as exc:
			log.warning("EventWorker: import failed in poll: %s", exc)
			return

		now = datetime.now(timezone.utc)
		el = DomainEventLog.__table__  # type: ignore[attr-defined]

		with self._engine.begin() as conn:
			# SELECT FOR UPDATE SKIP LOCKED: this process claims these rows;
			# other workers skip them entirely rather than blocking.
			due_filter = sa.and_(
				t.c.status.in_(["pending", "retrying"]),
				sa.or_(
					t.c.next_attempt_at == None,  # noqa: E711
					t.c.next_attempt_at <= now,
				),
			)
			rows = conn.execute(
				sa.select(
					t.c.id,
					t.c.event_id,
					t.c.retry_count,
					el.c.event_type,
					el.c.payload,
					el.c.tenant_id,
				)
				.select_from(t.join(el, t.c.event_id == el.c.event_id))
				.where(due_filter)
				.limit(self._batch_size)
				.with_for_update(skip_locked=True),
			).fetchall()

			for row in rows:
				self._dispatch_one(conn, t, row, now)

	def _dispatch_one(self, conn: Any, t: Any, row: Any, now: datetime) -> None:
		"""Dispatch one event row and update its dispatch record in-place."""
		import sqlalchemy as sa

		dispatch_id = row.id
		event_id = row.event_id
		retry_count: int = row.retry_count or 0

		try:
			payload = row.payload if isinstance(row.payload, dict) else {}
			tenant_id = str(row.tenant_id) if row.tenant_id else ""

			self._router.dispatch(
				event_type=row.event_type,
				payload=payload,
				tenant_id=tenant_id,
			)

			conn.execute(
				t.update()
				.where(t.c.id == dispatch_id)
				.values(
					status="done",
					processed_at=datetime.now(timezone.utc),
					error_detail=None,
				)
			)
			with self._lock:
				self._stats["processed"] += 1

		except Exception as exc:
			new_retry = retry_count + 1

			if new_retry >= self._max_retries:
				conn.execute(
					t.update()
					.where(t.c.id == dispatch_id)
					.values(
						status="dead",
						retry_count=new_retry,
						error_detail=f"[dead after {new_retry} retries] {exc}",
					)
				)
				log.error(
					"EventWorker: event %s dead after %d retries: %s",
					event_id,
					new_retry,
					exc,
				)
				with self._lock:
					self._stats["dead"] += 1
			else:
				backoff = self.backoff(new_retry)
				next_attempt = datetime.fromtimestamp(
					now.timestamp() + backoff,
					tz=timezone.utc,
				)
				conn.execute(
					t.update()
					.where(t.c.id == dispatch_id)
					.values(
						status="retrying",
						retry_count=new_retry,
						next_attempt_at=next_attempt,
						error_detail=str(exc),
					)
				)
				log.warning(
					"EventWorker: event %s retry %d/%d in %.0fs: %s",
					event_id,
					new_retry,
					self._max_retries,
					backoff,
					exc,
				)
				with self._lock:
					self._stats["failed"] += 1


# ---------------------------------------------------------------------------
# Convenience: enqueue a newly persisted event for dispatch
# ---------------------------------------------------------------------------

def enqueue_dispatch(event_id: str, session: Any) -> None:
	"""Insert an erp_event_dispatch_log row inside the same transaction as emit_event().

	Idempotent — ON CONFLICT DO NOTHING handles duplicate calls safely.
	"""
	t = _get_dispatch_table()
	if t is None:
		return

	try:
		import sqlalchemy as sa
		session.execute(
			sa.insert(t)
			.values(event_id=event_id, status="pending", retry_count=0)
			.on_conflict_do_nothing(index_elements=["event_id"])
		)
	except Exception as exc:
		log.warning("EventWorker.enqueue_dispatch: failed for %s: %s", event_id, exc)


__all__ = ["EventWorker", "enqueue_dispatch"]
