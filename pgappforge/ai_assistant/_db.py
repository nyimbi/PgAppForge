"""
pgappforge/ai_assistant/_db.py

Shared SQLAlchemy engine singleton for dev assistant sub-modules.
Avoids creating multiple connection pools against the same DSN.
"""
from __future__ import annotations

import logging
import os
import threading
from typing import Any

from sqlalchemy import create_engine

log = logging.getLogger(__name__)

_engine: Any = None
_engine_lock = threading.Lock()


def get_engine() -> Any:
	"""Return the shared engine, creating it lazily. Returns None if DSN not set."""
	global _engine
	if _engine is not None:
		return _engine
	with _engine_lock:
		if _engine is not None:  # re-check under lock — avoid double-create
			return _engine
		dsn = os.environ.get("SQLALCHEMY_DATABASE_URI", "")
		if not dsn:
			return None
		try:
			_engine = create_engine(
				dsn,
				connect_args={"connect_timeout": 5},
				pool_pre_ping=True,
				pool_size=2,
				max_overflow=3,
			)
			return _engine
		except Exception as exc:
			log.debug("dev_assistant._db: could not create engine: %s", exc)
			return None


def reset_engine() -> None:
	"""Dispose and reset the shared engine (called in tests to inject a test DSN)."""
	global _engine
	with _engine_lock:
		if _engine is not None:
			try:
				_engine.dispose()
			except Exception:
				pass
		_engine = None


__all__ = ["get_engine", "reset_engine"]
