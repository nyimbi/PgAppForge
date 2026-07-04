"""
pgappforge/ai_assistant/session_service.py

Persistent conversation session storage in PostgreSQL.

Sessions are scoped to user_id. Each session stores the full message history
as JSONB. Gracefully no-ops when the database is unavailable.
"""
from __future__ import annotations

import json
import logging

from sqlalchemy import text as sa_text
from uuid6 import uuid7

from ._db import get_engine

log = logging.getLogger(__name__)

_TABLE = "dev_assistant_session"
_MAX_PER_USER = 50


def ensure_schema() -> bool:
	"""Create the session table if it does not exist. Returns True on success."""
	engine = get_engine()
	if engine is None:
		return False
	try:
		with engine.connect() as conn:
			conn.execute(sa_text(f"""
				CREATE TABLE IF NOT EXISTS {_TABLE} (
					id         TEXT PRIMARY KEY,
					user_id    TEXT NOT NULL,
					title      TEXT NOT NULL DEFAULT '',
					messages   JSONB NOT NULL DEFAULT '[]',
					created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
					updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
				)
			"""))
			conn.execute(sa_text(
				f"CREATE INDEX IF NOT EXISTS {_TABLE}_user_idx "
				f"ON {_TABLE} (user_id, updated_at DESC)"
			))
			conn.commit()
		return True
	except Exception as exc:
		log.warning("session_service: schema setup failed: %s", exc)
		return False


def create_session(user_id: str, title: str = "", messages: list | None = None) -> str | None:
	"""Create a new session, pruning oldest if user is at cap. Returns new session ID or None."""
	engine = get_engine()
	if engine is None:
		return None
	try:
		session_id = str(uuid7())
		with engine.begin() as conn:
			# Prune sessions beyond the per-user cap before inserting
			conn.execute(sa_text(f"""
				DELETE FROM {_TABLE} WHERE id IN (
					SELECT id FROM {_TABLE}
					WHERE user_id = :uid
					ORDER BY updated_at DESC
					OFFSET :cap
				)
			"""), {"uid": user_id, "cap": _MAX_PER_USER - 1})
			conn.execute(sa_text(
				f"INSERT INTO {_TABLE} (id, user_id, title, messages) "
				"VALUES (:id, :uid, :title, :msgs)"
			), {
				"id": session_id, "uid": user_id,
				"title": (title or "")[:200],
				"msgs": json.dumps(messages or []),
			})
		return session_id
	except Exception as exc:
		log.warning("session_service: create failed: %s", exc)
		return None


def load_session(session_id: str, user_id: str) -> dict | None:
	"""Load session by ID. Returns None if not found or not owned by user."""
	engine = get_engine()
	if engine is None:
		return None
	try:
		with engine.connect() as conn:
			row = conn.execute(sa_text(
				f"SELECT id, title, messages, created_at, updated_at "
				f"FROM {_TABLE} WHERE id = :id AND user_id = :uid"
			), {"id": session_id, "uid": user_id}).fetchone()
		if row is None:
			return None
		msgs = row[2]
		if isinstance(msgs, str):
			msgs = json.loads(msgs or "[]")
		return {
			"id": row[0],
			"title": row[1] or "",
			"messages": msgs,
			"created_at": str(row[3]),
			"updated_at": str(row[4]),
		}
	except Exception as exc:
		log.warning("session_service: load failed: %s", exc)
		return None


def save_session(session_id: str, user_id: str, messages: list, title: str = "") -> bool:
	"""Upsert session messages (and title if non-empty). Returns True on success."""
	engine = get_engine()
	if engine is None:
		return False
	try:
		with engine.connect() as conn:
			result = conn.execute(sa_text(
				f"UPDATE {_TABLE} "
				"SET messages = :msgs, "
				"    title = COALESCE(NULLIF(:title, ''), title), "
				"    updated_at = NOW() "
				"WHERE id = :id AND user_id = :uid"
			), {
				"id": session_id, "uid": user_id,
				"msgs": json.dumps(messages),
				"title": (title or "")[:200],
			})
			conn.commit()
			return result.rowcount > 0
	except Exception as exc:
		log.warning("session_service: save failed: %s", exc)
		return False


def list_sessions(user_id: str, limit: int = 20) -> list[dict]:
	"""List sessions for a user, most recently updated first."""
	engine = get_engine()
	if engine is None:
		return []
	try:
		with engine.connect() as conn:
			rows = conn.execute(sa_text(
				f"SELECT id, title, updated_at, jsonb_array_length(messages) "
				f"FROM {_TABLE} WHERE user_id = :uid "
				"ORDER BY updated_at DESC LIMIT :lim"
			), {"uid": user_id, "lim": min(limit, _MAX_PER_USER)}).fetchall()
		return [
			{
				"id": r[0],
				"title": r[1] or "Untitled",
				"updated_at": str(r[2]),
				"msg_count": r[3] or 0,
			}
			for r in rows
		]
	except Exception as exc:
		log.warning("session_service: list failed: %s", exc)
		return []


def delete_session(session_id: str, user_id: str) -> bool:
	"""Delete session. Returns True if a row was deleted."""
	engine = get_engine()
	if engine is None:
		return False
	try:
		with engine.connect() as conn:
			result = conn.execute(sa_text(
				f"DELETE FROM {_TABLE} WHERE id = :id AND user_id = :uid"
			), {"id": session_id, "uid": user_id})
			conn.commit()
			return result.rowcount > 0
	except Exception as exc:
		log.warning("session_service: delete failed: %s", exc)
		return False


__all__ = [
	"ensure_schema",
	"create_session", "load_session", "save_session",
	"list_sessions", "delete_session",
]
