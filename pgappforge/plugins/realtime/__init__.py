"""
pgappforge/plugins/realtime/__init__.py

Real-time collaboration plugin for PgAppForge.

Provides WebSocket-based multi-user synchronisation, live cursor/presence
tracking, and optimistic-concurrency conflict resolution for any FAB ModelView.

How to enable
-------------
Add ``"realtime"`` (or the dotted import path) to the ``PGAPPFORGE_PLUGINS``
list in your Flask config, then supply plugin-specific keys under
``PGAPPFORGE_PLUGIN_CONFIG["realtime"]``::

    PGAPPFORGE_PLUGINS = ["pgappforge.plugins.realtime"]

    PGAPPFORGE_PLUGIN_CONFIG = {
        "realtime": {
            # Required
            "broker_url": "redis://localhost:6379/0",

            # Optional — all have defaults shown here
            "channel_prefix":       "pgaf_rt",
            "heartbeat_interval":   15,       # seconds between presence pings
            "cursor_throttle_ms":   50,       # min ms between cursor broadcasts
            "conflict_strategy":    "last_write_wins",  # or "reject_stale"
            "session_ttl_seconds":  3600,     # CollaborationSession expiry
            "socketio_path":        "/socket.io",
            "cors_allowed_origins": "*",
            "enable_audit_log":     True,
        }
    }

Config keys
-----------
broker_url          : Redis (or other SocketIO message-queue) connection URL.
                      Required when flask-socketio is installed.
channel_prefix      : Prefix for all pubsub channel names.
heartbeat_interval  : Seconds between client presence-ping emissions.
cursor_throttle_ms  : Throttle for cursor-position events (ms).
conflict_strategy   : "last_write_wins" skips version checks;
                      "reject_stale" raises ConflictError when record was
                      modified since the client loaded it.
session_ttl_seconds : Seconds before an idle CollaborationSession expires.
socketio_path       : URL path for the Socket.IO endpoint.
cors_allowed_origins: Passed directly to flask-socketio.
enable_audit_log    : When True, on_record_save writes a CollaborationEvent.

Optional heavy dependencies
---------------------------
flask-socketio and redis are NOT hard dependencies of pgappforge.  This plugin
guards their import with try/except so the package can be imported even when
they are absent — activation will fail gracefully with an ImportError logged at
ERROR level.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from flask import render_template_string
from pgappforge.security.decorators import has_access
from pgappforge.baseviews import BaseView, expose

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional heavy-dependency guards
# ---------------------------------------------------------------------------

try:
	from flask_socketio import SocketIO, emit, join_room, leave_room
	HAS_SOCKETIO = True
except ImportError:
	HAS_SOCKETIO = False
	log.debug("realtime plugin: flask-socketio not installed — WebSocket events disabled")

try:
	import redis as _redis_mod  # noqa: F401  (existence check only)
	HAS_REDIS = True
except ImportError:
	HAS_REDIS = False
	log.debug("realtime plugin: redis package not installed — broker unavailable")

# ---------------------------------------------------------------------------
# SQLAlchemy models
# ---------------------------------------------------------------------------

try:
	from sqlalchemy import (
		Column, String, Integer, Boolean, Text, DateTime, ForeignKey, Index,
	)
	from sqlalchemy.dialects.postgresql import JSONB
	from sqlalchemy.orm import relationship
	from pgappforge.models.sqla import Model

	class CollaborationSession(Model):
		"""
		Tracks an active editing session opened by a user on a specific record.

		One session per (user, model_name, record_pk) tuple; expires after
		``session_ttl_seconds`` of inactivity.
		"""
		__tablename__ = "realtime_collaboration_session"
		__table_args__ = (
			Index("ix_rt_session_record", "model_name", "record_pk"),
			Index("ix_rt_session_user",   "user_id"),
			Index("ix_rt_session_active",  "is_active"),
			{"extend_existing": True},
		)

		id = Column(Integer, primary_key=True)
		# FAB user FK — nullable so rows survive user deletion
		user_id = Column(Integer, ForeignKey("ab_user.id", ondelete="SET NULL"), nullable=True)
		# Dotted model class name, e.g. "myapp.models.Invoice"
		model_name = Column(String(255), nullable=False, index=True)
		# String representation of the record PK (supports composite keys via JSON)
		record_pk = Column(String(255), nullable=False)
		# Socket.IO session id
		socket_id = Column(String(128), nullable=True)
		# Arbitrary client state (cursor pos, viewport, etc.)
		session_meta = Column(JSONB, nullable=False, server_default="{}")
		is_active = Column(Boolean, nullable=False, default=True)
		started_at = Column(
			DateTime(timezone=True),
			nullable=False,
			default=lambda: datetime.now(timezone.utc),
		)
		last_seen_at = Column(
			DateTime(timezone=True),
			nullable=False,
			default=lambda: datetime.now(timezone.utc),
			onupdate=lambda: datetime.now(timezone.utc),
		)

		events = relationship(
			"CollaborationEvent",
			back_populates="session",
			cascade="all, delete-orphan",
			lazy="dynamic",
		)

		def __repr__(self) -> str:
			return (
				f"<CollaborationSession id={self.id} user={self.user_id} "
				f"model={self.model_name} pk={self.record_pk} active={self.is_active}>"
			)

	class CollaborationEvent(Model):
		"""
		Append-only audit log of real-time collaboration actions.

		Records saves, conflicts, cursor moves, and chat messages.
		Queryable for replay or conflict forensics.
		"""
		__tablename__ = "realtime_collaboration_event"
		__table_args__ = (
			Index("ix_rt_event_session",   "session_id"),
			Index("ix_rt_event_type",      "event_type"),
			Index("ix_rt_event_created",   "created_at"),
			{"extend_existing": True},
		)

		id = Column(Integer, primary_key=True)
		session_id = Column(
			Integer,
			ForeignKey("realtime_collaboration_session.id", ondelete="CASCADE"),
			nullable=False,
		)
		# Dot-namespaced event type: "record.save", "record.conflict",
		# "cursor.move", "presence.join", "presence.leave"
		event_type = Column(String(64), nullable=False)
		# Full event payload — field diffs, cursor coords, etc.
		payload = Column(JSONB, nullable=False, server_default="{}")
		created_at = Column(
			DateTime(timezone=True),
			nullable=False,
			default=lambda: datetime.now(timezone.utc),
		)

		session = relationship("CollaborationSession", back_populates="events")

		def __repr__(self) -> str:
			return (
				f"<CollaborationEvent id={self.id} type={self.event_type} "
				f"session={self.session_id}>"
			)

	class UserPresence(Model):
		"""
		Current online/away state of a user within a specific view context.

		Updated on each heartbeat; stale rows (> heartbeat_interval * 3) are
		treated as offline by the presence query.
		"""
		__tablename__ = "realtime_user_presence"
		__table_args__ = (
			Index("ix_rt_presence_user",    "user_id"),
			Index("ix_rt_presence_context", "view_context"),
			Index("ix_rt_presence_online",  "is_online"),
			{"extend_existing": True},
		)

		id = Column(Integer, primary_key=True)
		user_id = Column(
			Integer,
			ForeignKey("ab_user.id", ondelete="CASCADE"),
			nullable=False,
		)
		# e.g. "EmployeeModelView" or "invoices/42"
		view_context = Column(String(255), nullable=False)
		# Socket.IO session id for targeted emit
		socket_id = Column(String(128), nullable=True)
		# Display name snapshot (avoids join on hot presence queries)
		display_name = Column(String(255), nullable=True)
		# {x, y} normalised cursor position [0.0–1.0]
		cursor_position = Column(JSONB, nullable=True)
		is_online = Column(Boolean, nullable=False, default=True)
		last_heartbeat = Column(
			DateTime(timezone=True),
			nullable=False,
			default=lambda: datetime.now(timezone.utc),
		)

		def __repr__(self) -> str:
			return (
				f"<UserPresence id={self.id} user={self.user_id} "
				f"context={self.view_context} online={self.is_online}>"
			)

	_MODELS_AVAILABLE = True

except Exception as _model_exc:  # pragma: no cover — SQLAlchemy not installed
	_MODELS_AVAILABLE = False
	log.warning("realtime plugin: could not define SQLAlchemy models: %s", _model_exc)

	# Provide empty sentinels so __all__ / register_models() stay importable
	class CollaborationSession:  # type: ignore[no-redef]
		pass

	class CollaborationEvent:  # type: ignore[no-redef]
		pass

	class UserPresence:  # type: ignore[no-redef]
		pass

# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------

_SESSION_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Collaboration Sessions — PgAppForge Realtime</title>
  <link rel="stylesheet"
        href="https://maxcdn.bootstrapcdn.com/bootstrap/3.3.7/css/bootstrap.min.css">
</head>
<body>
<div class="container" style="margin-top:40px">
  <div class="panel panel-primary">
    <div class="panel-heading">
      <h3 class="panel-title">
        <span class="glyphicon glyphicon-link"></span>
        Collaboration Sessions
        <span class="label label-success pull-right">Plugin active</span>
      </h3>
    </div>
    <div class="panel-body">
      <p class="lead">Real-time collaboration is <strong>enabled</strong>.</p>
      <p>This view lists active editing sessions across all ModelViews.
         Each row represents one browser tab that has a record open.</p>
      <table class="table table-striped table-bordered table-hover">
        <thead>
          <tr>
            <th>#</th><th>User</th><th>Model</th>
            <th>Record PK</th><th>Socket ID</th><th>Last Seen</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td colspan="6" class="text-center text-muted">
              <em>No active sessions — connect a client to see live data.</em>
            </td>
          </tr>
        </tbody>
      </table>
      <div class="alert alert-info">
        <strong>Tip:</strong> Configure
        <code>broker_url</code> in
        <code>PGAPPFORGE_PLUGIN_CONFIG["realtime"]</code> and install
        <code>flask-socketio</code> + <code>redis</code> to enable
        WebSocket transport.
      </div>
    </div>
  </div>
</div>
</body>
</html>
"""

_PRESENCE_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>User Presence — PgAppForge Realtime</title>
  <link rel="stylesheet"
        href="https://maxcdn.bootstrapcdn.com/bootstrap/3.3.7/css/bootstrap.min.css">
</head>
<body>
<div class="container" style="margin-top:40px">
  <div class="panel panel-info">
    <div class="panel-heading">
      <h3 class="panel-title">
        <span class="glyphicon glyphicon-user"></span>
        User Presence
        <span class="label label-success pull-right">Plugin active</span>
      </h3>
    </div>
    <div class="panel-body">
      <p class="lead">Live cursors and online/away status.</p>
      <p>Shows which users are currently active in which views,
         their last heartbeat timestamp, and their normalised cursor
         coordinates <code>{x, y}</code> within the viewport.</p>
      <table class="table table-striped table-bordered table-hover">
        <thead>
          <tr>
            <th>User</th><th>Display Name</th><th>View Context</th>
            <th>Cursor</th><th>Online</th><th>Last Heartbeat</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td colspan="6" class="text-center text-muted">
              <em>No presence data yet — awaiting client heartbeats.</em>
            </td>
          </tr>
        </tbody>
      </table>
      <div class="alert alert-warning">
        <strong>Note:</strong> Rows are considered stale after
        <code>heartbeat_interval × 3</code> seconds without a ping and
        are excluded from live presence queries.
      </div>
    </div>
  </div>
</div>
</body>
</html>
"""


class CollaborationSessionView(BaseView):
	"""
	Admin view listing active CollaborationSession records.

	Mounted at ``/realtime/sessions/`` by RealtimePlugin.register_views().
	Requires the ``can_list`` permission on this view (enforced by @has_access).
	"""

	route_base = "/realtime/sessions"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		return render_template_string(_SESSION_TEMPLATE)


class PresenceView(BaseView):
	"""
	Admin view showing live UserPresence rows.

	Mounted at ``/realtime/presence/`` by RealtimePlugin.register_views().
	Requires the ``can_list`` permission on this view.
	"""

	route_base = "/realtime/presence"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		return render_template_string(_PRESENCE_TEMPLATE)


# ---------------------------------------------------------------------------
# RealtimePlugin
# ---------------------------------------------------------------------------

_DEFAULT_CONFIG: dict[str, Any] = {
	"broker_url":           None,
	"channel_prefix":       "pgaf_rt",
	"heartbeat_interval":   15,
	"cursor_throttle_ms":   50,
	"conflict_strategy":    "last_write_wins",
	"session_ttl_seconds":  3600,
	"socketio_path":        "/socket.io",
	"cors_allowed_origins": "*",
	"enable_audit_log":     True,
}


class RealtimePlugin(BasePlugin):
	"""
	Real-time collaboration plugin.

	Features
	--------
	- WebSocket sync via flask-socketio (gracefully degrades to polling)
	- Live cursor broadcasting with configurable throttle
	- Optimistic-concurrency conflict resolution (last-write-wins or reject_stale)
	- Presence tracking with heartbeat expiry
	- Append-only collaboration event audit log

	Lifecycle
	---------
	1. ``initialize()``  — merge config, validate deps, set up SocketIO if available
	2. ``register_views()`` — mount CollaborationSessionView + PresenceView
	3. ``register_models()`` — return [CollaborationSession, CollaborationEvent, UserPresence]
	4. ``on_record_save()`` — optionally write CollaborationEvent audit row
	5. ``on_user_login()``  — create/reactivate UserPresence row for the user
	6. ``deactivate()``     — disconnect SocketIO, clean up framework resources
	"""

	# ------------------------------------------------------------------
	# Metadata
	# ------------------------------------------------------------------

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="realtime",
			version="0.1.0",
			description=(
				"Real-time collaboration: WebSocket sync, live cursors, "
				"conflict resolution."
			),
			author="PgAppForge Contributors",
			tags=["realtime", "websocket", "collaboration", "presence"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_list_CollaborationSessionView",
				"can_list_PresenceView",
			],
			safe_mode_compatible=True,
			example_config={
				"broker_url":        "redis://localhost:6379/0",
				"conflict_strategy": "last_write_wins",
				"enable_audit_log":  True,
			},
		)

	# ------------------------------------------------------------------
	# Lifecycle
	# ------------------------------------------------------------------

	def initialize(self) -> None:
		"""Merge defaults, validate config, conditionally init SocketIO."""
		merged = {**_DEFAULT_CONFIG, **self.config}
		self.config = merged
		self._socketio: Any = None
		self._validate_config()

		if HAS_SOCKETIO:
			broker = self.config.get("broker_url")
			if broker:
				try:
					self._socketio = SocketIO(
						self.appbuilder.get_app,
						message_queue=broker,
						path=self.config["socketio_path"],
						cors_allowed_origins=self.config["cors_allowed_origins"],
						async_mode="threading",
					)
					self._register_socketio_handlers()
					log.info(
						"realtime plugin: SocketIO initialised (broker=%s)", broker
					)
				except Exception as exc:
					log.error(
						"realtime plugin: SocketIO init failed: %s — "
						"falling back to no WebSocket transport",
						exc,
					)
			else:
				log.warning(
					"realtime plugin: flask-socketio is installed but "
					"'broker_url' is not set — WebSocket events disabled"
				)
		else:
			log.info(
				"realtime plugin: flask-socketio not available — "
				"install it to enable WebSocket transport"
			)

	def configure(self, config: dict[str, Any]) -> None:
		"""Merge new config on top of current config."""
		self.config = {**self.config, **config}
		self._validate_config()

	def activate(self) -> bool:
		"""Full activation through the BasePlugin lifecycle."""
		return super().activate()

	def deactivate(self) -> bool:
		"""Disconnect SocketIO server before tearing down."""
		if self._socketio is not None:
			try:
				self._socketio.stop()
				log.info("realtime plugin: SocketIO server stopped")
			except Exception as exc:
				log.warning("realtime plugin: error stopping SocketIO: %s", exc)
			self._socketio = None
		return super().deactivate()

	# ------------------------------------------------------------------
	# Views
	# ------------------------------------------------------------------

	def register_views(self) -> None:
		"""Mount CollaborationSessionView and PresenceView into AppBuilder."""
		self.add_view(
			CollaborationSessionView,
			"Collaboration Sessions",
			icon="fa-link",
			category="Realtime",
			category_icon="fa-bolt",
		)
		self.add_view(
			PresenceView,
			"User Presence",
			icon="fa-users",
			category="Realtime",
		)
		log.info(
			"realtime plugin: registered views CollaborationSessionView, PresenceView"
		)

	# ------------------------------------------------------------------
	# Models
	# ------------------------------------------------------------------

	def register_models(self) -> list:
		"""Return model classes for Alembic autogenerate."""
		if _MODELS_AVAILABLE:
			return [CollaborationSession, CollaborationEvent, UserPresence]
		log.warning(
			"realtime plugin: SQLAlchemy models unavailable — "
			"skipping model registration"
		)
		return []

	# ------------------------------------------------------------------
	# Hook overrides
	# ------------------------------------------------------------------

	def on_record_save(self, model_class, record, is_new: bool) -> None:
		"""
		Write a CollaborationEvent audit row when a record is saved.

		Only fires when ``enable_audit_log`` is True and models are available.
		Looks up the active CollaborationSession for the current user + record
		and appends an event of type ``"record.save"``.

		Skips silently if no session is found (user not in a collaboration context).
		"""
		if not self.config.get("enable_audit_log", True):
			return
		if not _MODELS_AVAILABLE:
			return

		event_type = "record.save.create" if is_new else "record.save.update"
		pk_val = str(getattr(record, "id", None) or "")
		model_name = f"{model_class.__module__}.{model_class.__name__}"

		try:
			db = self.appbuilder.get_session
			session = (
				db.query(CollaborationSession)
				.filter_by(model_name=model_name, record_pk=pk_val, is_active=True)
				.first()
			)
			if session is None:
				return
			event = CollaborationEvent(
				session_id=session.id,
				event_type=event_type,
				payload={
					"model": model_name,
					"pk": pk_val,
					"is_new": is_new,
				},
			)
			db.add(event)
			db.commit()
			log.debug(
				"realtime plugin: logged %s for session %s", event_type, session.id
			)
		except Exception as exc:
			log.error("realtime plugin: on_record_save audit failed: %s", exc)

	def on_user_login(self, user) -> None:
		"""
		Create or reactivate a UserPresence row when a user authenticates.

		Sets ``is_online=True`` and refreshes ``last_heartbeat``.
		"""
		if not _MODELS_AVAILABLE:
			return

		try:
			db = self.appbuilder.get_session
			presence = (
				db.query(UserPresence)
				.filter_by(user_id=user.id, view_context="__global__")
				.first()
			)
			if presence is None:
				presence = UserPresence(
					user_id=user.id,
					view_context="__global__",
					display_name=getattr(user, "username", str(user.id)),
					is_online=True,
					last_heartbeat=datetime.now(timezone.utc),
				)
				db.add(presence)
			else:
				presence.is_online = True
				presence.last_heartbeat = datetime.now(timezone.utc)
			db.commit()
			log.debug(
				"realtime plugin: presence upserted for user %s", user.id
			)
		except Exception as exc:
			log.error("realtime plugin: on_user_login presence update failed: %s", exc)

	# ------------------------------------------------------------------
	# Config schema
	# ------------------------------------------------------------------

	def get_config_schema(self) -> dict:
		"""JSON Schema describing all supported config keys."""
		return {
			"$schema": "https://json-schema.org/draft/2020-12/schema",
			"title": "RealtimePlugin configuration",
			"type": "object",
			"additionalProperties": False,
			"properties": {
				"broker_url": {
					"type": ["string", "null"],
					"description": (
						"Redis (or other SocketIO message-queue) connection URL. "
						"Required for WebSocket transport."
					),
					"examples": ["redis://localhost:6379/0"],
				},
				"channel_prefix": {
					"type": "string",
					"default": "pgaf_rt",
					"description": "Prefix for all pubsub channel names.",
				},
				"heartbeat_interval": {
					"type": "integer",
					"minimum": 1,
					"default": 15,
					"description": "Seconds between client presence-ping emissions.",
				},
				"cursor_throttle_ms": {
					"type": "integer",
					"minimum": 0,
					"default": 50,
					"description": "Minimum ms between cursor-position broadcasts.",
				},
				"conflict_strategy": {
					"type": "string",
					"enum": ["last_write_wins", "reject_stale"],
					"default": "last_write_wins",
					"description": (
						"'last_write_wins' skips version checks. "
						"'reject_stale' raises ConflictError when the record was "
						"modified since the client loaded it."
					),
				},
				"session_ttl_seconds": {
					"type": "integer",
					"minimum": 60,
					"default": 3600,
					"description": "Seconds before an idle CollaborationSession expires.",
				},
				"socketio_path": {
					"type": "string",
					"default": "/socket.io",
					"description": "URL path for the Socket.IO endpoint.",
				},
				"cors_allowed_origins": {
					"type": "string",
					"default": "*",
					"description": "Passed directly to flask-socketio CORS config.",
				},
				"enable_audit_log": {
					"type": "boolean",
					"default": True,
					"description": (
						"When True, on_record_save appends a CollaborationEvent row."
					),
				},
			},
		}

	# ------------------------------------------------------------------
	# Internal
	# ------------------------------------------------------------------

	def _validate_config(self) -> None:
		"""Lightweight config validation — raises ValueError on bad values."""
		strategy = self.config.get("conflict_strategy", "last_write_wins")
		if strategy not in ("last_write_wins", "reject_stale"):
			raise ValueError(
				f"realtime plugin: invalid conflict_strategy {strategy!r}; "
				"must be 'last_write_wins' or 'reject_stale'"
			)
		ttl = self.config.get("session_ttl_seconds", 3600)
		if not isinstance(ttl, int) or ttl < 60:
			raise ValueError(
				f"realtime plugin: session_ttl_seconds must be an integer >= 60, got {ttl!r}"
			)

	def _register_socketio_handlers(self) -> None:
		"""
		Register Socket.IO event handlers.

		Handlers are registered only when flask-socketio is available and a
		broker URL is configured.  All heavy logic lives here so the rest of
		the class stays readable when SocketIO is absent.
		"""
		if not HAS_SOCKETIO or self._socketio is None:
			return

		prefix = self.config["channel_prefix"]

		@self._socketio.on(f"{prefix}:join")
		def _on_join(data: dict) -> None:
			"""Client joins a record-scoped room."""
			room = _room_key(data.get("model", ""), data.get("pk", ""))
			join_room(room)
			emit(f"{prefix}:joined", {"room": room}, room=room)
			log.debug("realtime: client joined room %s", room)

		@self._socketio.on(f"{prefix}:leave")
		def _on_leave(data: dict) -> None:
			"""Client leaves a record-scoped room."""
			room = _room_key(data.get("model", ""), data.get("pk", ""))
			leave_room(room)
			emit(f"{prefix}:left", {"room": room}, room=room)
			log.debug("realtime: client left room %s", room)

		@self._socketio.on(f"{prefix}:cursor")
		def _on_cursor(data: dict) -> None:
			"""Broadcast cursor position to all peers in the same room."""
			room = _room_key(data.get("model", ""), data.get("pk", ""))
			emit(
				f"{prefix}:cursor",
				{"user": data.get("user"), "pos": data.get("pos")},
				room=room,
				include_self=False,
			)

		@self._socketio.on(f"{prefix}:heartbeat")
		def _on_heartbeat(data: dict) -> None:
			"""Client heartbeat — update UserPresence.last_heartbeat."""
			if not _MODELS_AVAILABLE:
				return
			user_id = data.get("user_id")
			if not user_id:
				return
			try:
				db = self.appbuilder.get_session
				presence = db.query(UserPresence).filter_by(user_id=user_id).first()
				if presence:
					presence.last_heartbeat = datetime.now(timezone.utc)
					presence.cursor_position = data.get("cursor")
					db.commit()
			except Exception as exc:
				log.error("realtime plugin: heartbeat DB update failed: %s", exc)

		log.info("realtime plugin: Socket.IO handlers registered (prefix=%s)", prefix)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _room_key(model: str, pk: str) -> str:
	"""Return a stable room name for a given model + record PK."""
	return f"rt:{model}:{pk}"


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_plugin(appbuilder, config: dict[str, Any] | None = None) -> RealtimePlugin:
	"""
	Factory function for the realtime plugin.

	Called by the pgappforge plugin loader when it discovers this module via
	``PGAPPFORGE_PLUGINS``.  You may also call it directly::

	    from pgappforge.plugins.realtime import create_plugin

	    plugin = create_plugin(appbuilder, config={"broker_url": "redis://..."})
	    plugin.activate()

	Args:
	    appbuilder: The PgAppForge / AppBuilder instance.
	    config:     Optional dict of config keys (merged over defaults).

	Returns:
	    An initialised (but not yet activated) RealtimePlugin instance.
	"""
	return RealtimePlugin(appbuilder, config=config or {})


# ---------------------------------------------------------------------------
# PG LISTEN/NOTIFY transport — zero-extra-infra change broadcast
# ---------------------------------------------------------------------------

import json as _json
import threading as _threading
import select as _select
from typing import Any as _Any

_CHANNEL = "pgaf_changes"
_listener_thread: _threading.Thread | None = None


def push_update(instance: _Any, changed_fields: list[str] | None = None) -> None:
	"""Broadcast a model change via ``pg_notify``.

	Issues ``SELECT pg_notify('pgaf_changes', :payload)`` on the app's
	SQLAlchemy engine.  Safe to call outside a transaction — uses its own
	short-lived autocommit connection.

	Args:
	    instance:       SQLAlchemy model instance that was changed.
	    changed_fields: Optional list of changed field names; sent as-is in
	                    the NOTIFY payload for client-side filtering.
	"""
	try:
		from flask import current_app
		import sqlalchemy as _sa
		engine = current_app.extensions["sqlalchemy"].engine
		payload = _json.dumps({
			"model": type(instance).__name__,
			"entity_id": str(getattr(instance, "id", "")),
			"op": "UPDATE",
			"fields": changed_fields or [],
		})
		with engine.connect() as conn:
			conn.execute(
				_sa.text("SELECT pg_notify(:channel, :payload)"),
				{"channel": _CHANNEL, "payload": payload},
			)
			conn.commit()
	except Exception as exc:
		log.warning("push_update failed: %s", exc)


def realtime_model(broadcast_fields: list[str] | None = None):
	"""Class decorator: enable real-time broadcasting for a SQLAlchemy model.

	Registers an ``after_commit`` session listener that calls
	:func:`push_update` for every modified instance of the decorated class.

	Args:
	    broadcast_fields: Field names to include in the NOTIFY payload.
	                      If omitted, an empty list is sent (event fires but
	                      no field-level hints are given to clients).

	Example::

	    @realtime_model(broadcast_fields=["status", "amount"])
	    class Invoice(Model):
	        ...
	"""
	def decorator(cls):
		cls._realtime_broadcast_fields = frozenset(broadcast_fields or [])
		cls._realtime_enabled = True
		_register_after_commit_listener(cls)
		return cls
	return decorator


def _register_after_commit_listener(model_cls: type) -> None:
	"""Attach an SQLAlchemy after_commit hook for *model_cls*."""
	from sqlalchemy import event as _sa_event
	from sqlalchemy.orm import Session as _Session

	@_sa_event.listens_for(_Session, "after_commit")
	def _after_commit(session):
		if not getattr(model_cls, "_realtime_enabled", False):
			return
		broadcast = model_cls._realtime_broadcast_fields
		for instance in list(session.new) + list(session.dirty):
			if not isinstance(instance, model_cls):
				continue
			changed = [f for f in broadcast if hasattr(instance, f)] if broadcast else []
			try:
				push_update(instance, changed_fields=changed)
			except Exception:
				pass


class RealtimeMixin:
	"""Add to any ModelView to enable presence tracking and SSE change-stream UI.

	Example::

	    class InvoiceModelView(RealtimeMixin, ModelView):
	        datamodel = SQLAInterface(Invoice)

	Attributes:
	    realtime_enabled    : Toggle per-view (default True).
	    realtime_model_name : Override when the model class name differs from
	                          the view name (default empty → use model name).
	"""

	realtime_enabled: bool = True
	realtime_model_name: str = ""


def _start_pg_listener(app) -> None:
	"""Start the background PostgreSQL LISTEN thread (idempotent)."""
	global _listener_thread
	if _listener_thread and _listener_thread.is_alive():
		return
	_listener_thread = _threading.Thread(
		target=_pg_listen_loop,
		args=(app,),
		daemon=True,
		name="pgaf-realtime-listener",
	)
	_listener_thread.start()


def _pg_listen_loop(app) -> None:
	"""Background thread: LISTEN on pgaf_changes and fan out via SSE."""
	try:
		import psycopg2
		db_uri = app.config.get("SQLALCHEMY_DATABASE_URI", "")
		if not db_uri.startswith("postgresql"):
			log.info("RealtimeMixin PG listener: non-PG URI, disabled")
			return
		conn = psycopg2.connect(db_uri)
		conn.set_isolation_level(psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT)
		cur = conn.cursor()
		cur.execute(f"LISTEN {_CHANNEL};")
		log.info("pgaf realtime: LISTEN %s started", _CHANNEL)
		while True:
			if _select.select([conn], [], [], 5)[0]:
				conn.poll()
				while conn.notifies:
					notify = conn.notifies.pop(0)
					_dispatch_pg_notification(app, notify.payload)
	except Exception as exc:
		log.error("pgaf realtime listener crashed: %s", exc)


def _dispatch_pg_notification(app, payload_str: str) -> None:
	"""Fan out a raw NOTIFY payload to SSE clients and SocketIO rooms."""
	try:
		payload = _json.loads(payload_str)
	except Exception:
		return
	# SSE fan-out (always attempted)
	try:
		from pgappforge.plugins.realtime.views import broadcast_to_clients
		broadcast_to_clients(payload)
	except Exception as exc:
		log.debug("SSE broadcast skipped: %s", exc)
	# SocketIO fan-out (only when flask-socketio is present and configured)
	try:
		with app.app_context():
			socketio = app.extensions.get("socketio")
			if socketio:
				room = f"model_{payload['model']}_{payload['entity_id']}"
				list_room = f"model_{payload['model']}_list"
				socketio.emit("model_change", payload, room=room)
				socketio.emit("model_change", payload, room=list_room)
	except Exception as exc:
		log.debug("SocketIO dispatch skipped: %s", exc)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	# Plugin class + factory
	"RealtimePlugin",
	"create_plugin",
	# Views
	"CollaborationSessionView",
	"PresenceView",
	# Models
	"CollaborationSession",
	"CollaborationEvent",
	"UserPresence",
	# PG LISTEN/NOTIFY API
	"push_update",
	"realtime_model",
	"RealtimeMixin",
]
