"""
pgappforge/plugins/offline/models.py

SQLAlchemy model for the offline sync audit log.

SyncLog records every sync session — pull + push counts, duration, and any
error text — so operators can monitor sync health and diagnose issues.

Migration
---------
Alembic autogenerate will pick this table up automatically when the offline
plugin is active and ``register_models()`` returns ``[SyncLog]``.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Float, Index, Integer, String

try:
	from pgappforge import Model as _Base
except Exception:
	# Fallback: use declarative_base so the file is importable standalone
	from sqlalchemy.orm import declarative_base as _declarative_base
	_Base = _declarative_base()


class SyncLog(_Base):
	"""
	Audit record for a single offline sync session.

	Columns
	-------
	id          : integer primary key, auto-increment.
	model_name  : name of the SQLAlchemy model that was synced (indexed).
	client_id   : opaque device/client identifier supplied by the caller
	              (indexed; matches ``device_id`` in the mutation queue).
	synced_at   : UTC timestamp when the sync completed (set on insert).
	rows_pulled : number of rows returned to the client in this session.
	rows_pushed : number of client changes applied to the server.
	duration_ms : wall-clock time for the sync round-trip in milliseconds
	              (nullable — not always available).
	error       : error message if the session failed, NULL on success.
	"""

	__allow_unmapped__ = True
	__tablename__ = "offline_sync_log"
	__table_args__ = (
		Index("ix_offline_sync_log_model_name", "model_name"),
		Index("ix_offline_sync_log_client_id",  "client_id"),
		{"extend_existing": True},
	)

	id:          int      = Column(Integer, primary_key=True, autoincrement=True)
	model_name:  str      = Column(String(100), nullable=False, index=True)
	client_id:   str      = Column(String(100), nullable=False, index=True)
	synced_at:   datetime = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
	)
	rows_pulled: int      = Column(Integer, nullable=False, default=0)
	rows_pushed: int      = Column(Integer, nullable=False, default=0)
	duration_ms: float | None = Column(Float, nullable=True)
	error:       str | None   = Column(String(500), nullable=True)

	def __repr__(self) -> str:
		return (
			f"<SyncLog id={self.id} model={self.model_name!r} "
			f"client={self.client_id!r} at={self.synced_at} "
			f"pulled={self.rows_pulled} pushed={self.rows_pushed}"
			+ (f" error={self.error!r}" if self.error else "")
			+ ">"
		)
