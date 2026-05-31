"""Real-Time Collaboration views — SSE stream, presence heartbeat, field locking.

Endpoints
---------
GET  /realtime/events                             — SSE change stream
POST /realtime/api/presence                       — presence heartbeat / upsert
GET  /realtime/api/presence/<model>/<entity_id>   — who is viewing a record
POST /realtime/api/lock/<model>/<entity_id>/<fld> — acquire field lock
DELETE /realtime/api/lock/<model>/<entity_id>/<fld> — release field lock

All endpoints require @has_access (HTTP 403 when unauthenticated).
"""
from __future__ import annotations

import json
import queue
import secrets
import threading
import time
import logging
from datetime import datetime, timezone, timedelta

from flask import abort, current_app, request, jsonify, Response
from flask_login import current_user

from pgappforge import BaseView, expose
from pgappforge.security.decorators import has_access

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SSE client registry
# ---------------------------------------------------------------------------
# Maps an arbitrary int key (id(queue)) → Queue instance.
# Entries are reaped when the client disconnects (GeneratorExit) or when
# broadcast_to_clients() detects a full/stale queue.

_SSE_CLIENTS: dict[int, queue.Queue] = {}
_SSE_LOCK = threading.Lock()


# ---------------------------------------------------------------------------
# View
# ---------------------------------------------------------------------------

class RealtimeView(BaseView):
	"""Mounts all real-time collaboration HTTP endpoints."""

	route_base = "/realtime"

	# ------------------------------------------------------------------
	# SSE stream
	# ------------------------------------------------------------------

	@expose("/events")
	@has_access
	def sse_events(self):
		"""Server-Sent Events stream for real-time model changes.

		Query params
		------------
		sub : repeatable  e.g. ``?sub=Invoice_42&sub=Invoice_list``
		      Currently informational; future versions will filter by room.

		The stream emits:
		  - ``{"type":"connected"}`` immediately on open
		  - ``{"model":…,"entity_id":…,"op":…,"fields":[…]}`` on each change
		  - ``{"type":"ping"}`` every ~25 s as a keepalive
		"""
		max_conn = int(current_app.config.get("FAB_REALTIME_MAX_CONNECTIONS", 1000))
		with _SSE_LOCK:
			if len(_SSE_CLIENTS) >= max_conn:
				abort(503, description="SSE connection limit reached")

		q: queue.Queue = queue.Queue(maxsize=100)
		q._last_active = time.monotonic()  # type: ignore[attr-defined]
		sid = id(q)

		with _SSE_LOCK:
			_SSE_CLIENTS[sid] = q

		def generate():
			try:
				yield 'data: {"type":"connected"}\n\n'
				while True:
					try:
						msg = q.get(timeout=25)
						q._last_active = time.monotonic()  # type: ignore[attr-defined]
						yield f"data: {msg}\n\n"
					except queue.Empty:
						yield 'data: {"type":"ping"}\n\n'
			except GeneratorExit:
				pass
			finally:
				with _SSE_LOCK:
					_SSE_CLIENTS.pop(sid, None)

		return Response(
			generate(),
			mimetype="text/event-stream",
			headers={
				"Cache-Control": "no-cache",
				"X-Accel-Buffering": "no",
			},
		)

	# ------------------------------------------------------------------
	# Presence heartbeat
	# ------------------------------------------------------------------

	@expose("/api/presence", methods=["POST"])
	@has_access
	def api_presence_heartbeat(self):
		"""Upsert a PresenceSession row (client heartbeat).

		Request JSON
		------------
		session_token : str  (optional on first call; returned and re-used after)
		model         : str  model class name
		entity_id     : str  record PK as string
		editing_field : str  (optional) currently focused field name
		"""
		from pgappforge.plugins.realtime.models import PresenceSession
		from sqlalchemy import select

		data = request.get_json(silent=True) or {}
		db = self.appbuilder.get_session

		uid = getattr(current_user, "id", None)
		if not uid:
			return jsonify({"ok": False, "error": "not authenticated"}), 403

		token = data.get("session_token") or secrets.token_urlsafe(32)
		model_name = data.get("model", "")
		entity_id = str(data.get("entity_id", ""))
		editing_field = data.get("editing_field")

		existing = db.execute(
			select(PresenceSession).where(PresenceSession.session_token == token)
		).scalar()

		if existing:
			existing.model_name = model_name
			existing.entity_id = entity_id
			existing.editing_field = editing_field
			existing.last_seen = datetime.now(timezone.utc)
		else:
			existing = PresenceSession(
				user_id=uid,
				session_token=token,
				model_name=model_name,
				entity_id=entity_id,
				editing_field=editing_field,
				last_seen=datetime.now(timezone.utc),
			)
			db.add(existing)

		db.commit()
		return jsonify({"ok": True, "session_token": token})

	# ------------------------------------------------------------------
	# Presence query
	# ------------------------------------------------------------------

	@expose("/api/presence/<model_name>/<entity_id>")
	@has_access
	def api_get_presence(self, model_name: str, entity_id: str):
		"""Return active PresenceSession rows for a record.

		Filters out sessions whose ``last_seen`` is older than
		``FAB_REALTIME_HEARTBEAT_INTERVAL × 3`` seconds (default 45 s).
		"""
		from pgappforge.plugins.realtime.models import PresenceSession
		from sqlalchemy import select

		db = self.appbuilder.get_session
		interval = int(current_app.config.get("FAB_REALTIME_HEARTBEAT_INTERVAL", 15))
		cutoff = datetime.now(timezone.utc) - timedelta(seconds=interval * 3)

		sessions = db.execute(
			select(PresenceSession)
			.where(PresenceSession.model_name == model_name)
			.where(PresenceSession.entity_id == entity_id)
			.where(PresenceSession.last_seen > cutoff)
		).scalars().all()

		return jsonify({
			"sessions": [
				{
					"user_id": s.user_id,
					"editing_field": s.editing_field,
					"last_seen": s.last_seen.isoformat(),
				}
				for s in sessions
			]
		})

	# ------------------------------------------------------------------
	# Field lock — acquire
	# ------------------------------------------------------------------

	@expose("/api/lock/<model_name>/<entity_id>/<field_name>", methods=["POST"])
	@has_access
	def api_lock_field(self, model_name: str, entity_id: str, field_name: str):
		"""Acquire an advisory lock on a field.

		Returns ``{"ok":true,"acquired":true}`` when the lock is granted.
		Returns ``{"ok":true,"acquired":false,"locked_by":<user_id>}`` when
		another user holds a non-expired lock.

		An expired lock is silently taken over by the requester.
		"""
		from pgappforge.plugins.realtime.models import FieldLock
		from sqlalchemy import select

		db = self.appbuilder.get_session
		uid = getattr(current_user, "id", None)
		if not uid:
			abort(403)

		lock_timeout = int(current_app.config.get("FAB_REALTIME_LOCK_TIMEOUT", 30))
		now = datetime.now(timezone.utc)
		expires = now + timedelta(seconds=lock_timeout)

		existing = db.execute(
			select(FieldLock)
			.where(FieldLock.model_name == model_name)
			.where(FieldLock.entity_id == entity_id)
			.where(FieldLock.field_name == field_name)
		).scalar()

		if existing:
			# Owner refreshes their own lock, or expired lock is taken over.
			if existing.user_id == uid or existing.expires_at < now:
				existing.user_id = uid
				existing.locked_at = now
				existing.expires_at = expires
				db.commit()
				return jsonify({"ok": True, "acquired": True})
			# Active lock held by someone else.
			return jsonify({
				"ok": True,
				"acquired": False,
				"locked_by": existing.user_id,
			})

		db.add(FieldLock(
			model_name=model_name,
			entity_id=entity_id,
			field_name=field_name,
			user_id=uid,
			locked_at=now,
			expires_at=expires,
		))
		db.commit()
		return jsonify({"ok": True, "acquired": True})

	# ------------------------------------------------------------------
	# Field lock — release
	# ------------------------------------------------------------------

	@expose("/api/lock/<model_name>/<entity_id>/<field_name>", methods=["DELETE"])
	@has_access
	def api_release_lock(self, model_name: str, entity_id: str, field_name: str):
		"""Release an advisory field lock owned by the current user.

		No-op (still returns 200) if the lock does not exist or belongs to
		another user — avoids leaking lock ownership information.
		"""
		from pgappforge.plugins.realtime.models import FieldLock
		from sqlalchemy import select

		db = self.appbuilder.get_session
		uid = getattr(current_user, "id", None)

		lock = db.execute(
			select(FieldLock)
			.where(FieldLock.model_name == model_name)
			.where(FieldLock.entity_id == entity_id)
			.where(FieldLock.field_name == field_name)
			.where(FieldLock.user_id == uid)
		).scalar()

		if lock:
			db.delete(lock)
			db.commit()

		return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# SSE fan-out helper (called from _dispatch_notification in __init__.py)
# ---------------------------------------------------------------------------

def broadcast_to_clients(payload: dict) -> None:
	"""Fan out a change payload dict to all live SSE client queues.

	Evicts clients whose queue is full (slow consumer) or whose last
	``get()`` was more than 120 s ago (stale / disconnected client that
	has not yet triggered GeneratorExit).

	Thread-safe: acquires ``_SSE_LOCK`` for the full sweep.
	"""
	msg = json.dumps(payload)
	with _SSE_LOCK:
		dead: list[int] = []
		for sid, q in _SSE_CLIENTS.items():
			last_active = getattr(q, "_last_active", 0)
			if time.monotonic() - last_active > 120:
				dead.append(sid)
				continue
			try:
				q.put_nowait(msg)
			except queue.Full:
				dead.append(sid)
		for sid in dead:
			_SSE_CLIENTS.pop(sid, None)
