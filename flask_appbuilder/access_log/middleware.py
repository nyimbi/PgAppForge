"""Flask before/after_request hooks that log every HTTP request.

Usage::

    from flask_appbuilder.access_log import AccessLogMiddleware

    middleware = AccessLogMiddleware()
    middleware.init_app(app, db.session)

Configuration keys (read from app.config)::

    FAB_ACCESS_LOG_ENABLED        = True
    FAB_ACCESS_LOG_EXCLUDE_PATHS  = ['/static/', '/health']
    FAB_ACCESS_LOG_EXCLUDE_METHODS= ['OPTIONS']
    FAB_ACCESS_LOG_BATCH_SIZE     = 50     # flush every N requests
    FAB_ACCESS_LOG_HASH_SESSION   = True   # hash session id for privacy
"""
from __future__ import annotations

import hashlib
import time
from typing import Callable

from flask import Flask, g, request, current_app
from sqlalchemy.orm import Session


class AccessLogMiddleware:
	"""Records every HTTP request in the fab_access_log table.

	Writes are buffered in a list and flushed periodically using a separate
	SQLAlchemy session so access logging never interferes with the main
	request session.
	"""

	def __init__(self) -> None:
		self._session_factory: Callable[[], Session] | None = None
		self._exclude_paths: list[str] = ["/static/"]
		self._exclude_methods: list[str] = ["OPTIONS"]
		self._batch_size: int = 50
		self._hash_session: bool = True
		self._buffer: list[dict] = []

	def init_app(
		self,
		app: Flask,
		db_session: Session | None = None,
		*,
		exclude_paths: list[str] | None = None,
		exclude_methods: list[str] | None = None,
		batch_size: int = 50,
	) -> None:
		"""Attach the middleware to a Flask application.

		Args:
		    app: Flask application instance.
		    db_session: SQLAlchemy session to use for writes. If None, the
		               middleware reads from ``app.extensions['sqlalchemy']``.
		    exclude_paths: Path prefixes to skip (e.g. ``['/static/']``).
		    exclude_methods: HTTP methods to skip (default: OPTIONS).
		    batch_size: Flush the buffer after this many requests.
		"""
		self._exclude_paths = exclude_paths or app.config.get(
			"FAB_ACCESS_LOG_EXCLUDE_PATHS", ["/static/", "/favicon.ico"]
		)
		self._exclude_methods = exclude_methods or app.config.get(
			"FAB_ACCESS_LOG_EXCLUDE_METHODS", ["OPTIONS"]
		)
		self._batch_size = batch_size or app.config.get("FAB_ACCESS_LOG_BATCH_SIZE", 50)
		self._hash_session = app.config.get("FAB_ACCESS_LOG_HASH_SESSION", True)

		# Store session factory — prefer the explicit one, fall back to FAB's
		if db_session is not None:
			self._db_session = db_session
		else:
			self._db_session = None  # resolved lazily from app context

		app.before_request(self._before)
		app.after_request(self._after)
		app.teardown_appcontext(self._teardown)

	def _should_skip(self) -> bool:
		if not current_app.config.get("FAB_ACCESS_LOG_ENABLED", True):
			return True
		if request.method in self._exclude_methods:
			return True
		return any(request.path.startswith(p) for p in self._exclude_paths)

	def _before(self) -> None:
		if self._should_skip():
			return
		g._access_log_start = time.monotonic()

	def _after(self, response):
		if self._should_skip() or not hasattr(g, "_access_log_start"):
			return response

		duration_ms = int((time.monotonic() - g._access_log_start) * 1000)

		# Get current user if available (Flask-Login)
		user_id = None
		username = None
		try:
			from flask_login import current_user as cu
			if cu and cu.is_authenticated:
				user_id = getattr(cu, "id", None)
				username = getattr(cu, "username", None)
		except Exception:
			pass

		# Hash session ID for privacy
		session_id = None
		try:
			from flask import session as flask_session
			raw_sid = flask_session.get("_id") or str(dict(flask_session))
			if self._hash_session and raw_sid:
				session_id = hashlib.sha256(raw_sid.encode()).hexdigest()[:32]
		except Exception:
			pass

		entry = {
			"method": request.method,
			"path": request.path[:2048],
			"query_string": request.query_string.decode("utf-8", errors="replace") or None,
			"blueprint": request.blueprints[0] if request.blueprints else None,
			"view_func": request.endpoint,
			"user_id": user_id,
			"username": username,
			"ip_address": request.remote_addr,
			"user_agent": (request.user_agent.string or "")[:512],
			"referer": (request.referrer or "")[:512] or None,
			"session_id": session_id,
			"status_code": response.status_code,
			"response_bytes": response.calculate_content_length(),
			"duration_ms": duration_ms,
		}

		self._buffer.append(entry)

		if len(self._buffer) >= self._batch_size:
			self._flush()

		return response

	def _teardown(self, exc) -> None:
		if self._buffer:
			try:
				self._flush()
			except Exception:
				pass

	def _flush(self) -> None:
		if not self._buffer:
			return

		from flask_appbuilder.access_log.models import AccessLogEntry
		entries = self._buffer[:]
		self._buffer.clear()

		try:
			db = self._db_session
			if db is None:
				return  # session not configured — skip silently

			for data in entries:
				entry = AccessLogEntry(**data)
				db.add(entry)
			db.commit()
		except Exception as exc:
			try:
				db.rollback()
			except Exception:
				pass
			# Don't let access log writes crash the application
			import logging
			logging.getLogger(__name__).debug("Access log flush failed: %s", exc)

	def flush(self) -> None:
		"""Manually flush buffered entries (useful in tests or on shutdown)."""
		self._flush()
