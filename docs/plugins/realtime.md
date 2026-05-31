# Real-Time Collaboration Layer

The Realtime plugin adds multi-user awareness to any pgappforge `ModelView` using PostgreSQL `LISTEN/NOTIFY` as the change-broadcast bus and Server-Sent Events (SSE) to fan changes out to browser clients. Live row patches, presence avatars, and field-level advisory locks are available with zero infrastructure beyond the database you already have.

Flask-SocketIO and Redis are optional heavy dependencies: if they are absent the plugin falls back to the SSE path and degrades gracefully. Both transports can coexist — the PG LISTEN/NOTIFY path fans out to both SSE queues and any active SocketIO rooms.

## Quick Start

```python
from pgappforge.plugins.realtime import (
    RealtimePlugin, realtime_model, RealtimeMixin, push_update
)

# config.py — minimal (SSE only, no WebSocket broker required)
PGAPPFORGE_PLUGINS = ["pgappforge.plugins.realtime"]
PGAPPFORGE_PLUGIN_CONFIG = {
    "realtime": {
        "conflict_strategy": "last_write_wins",
        "enable_audit_log": True,
    }
}

# Optional: full WebSocket mode
PGAPPFORGE_PLUGIN_CONFIG = {
    "realtime": {
        "broker_url": "redis://localhost:6379/0",
        "heartbeat_interval": 15,
        "cursor_throttle_ms": 50,
        "conflict_strategy": "last_write_wins",
        "session_ttl_seconds": 3600,
    }
}

# Decorate a model to broadcast changes automatically
@realtime_model(broadcast_fields=["status", "amount"])
class Order(Model):
    __tablename__ = "orders"
    id     = Column(Integer, primary_key=True)
    status = Column(String(32))
    amount = Column(Numeric(12, 2))

# Add presence and SSE UI injection to any ModelView
class OrderModelView(RealtimeMixin, ModelView):
    datamodel = SQLAInterface(Order)
    list_columns = ["id", "status", "amount"]

# Register plugin in app factory
def create_app():
    app = Flask(__name__)
    appbuilder = AppBuilder(app, db.session)
    plugin = RealtimePlugin(appbuilder, config={"broker_url": "redis://..."})
    plugin.activate()
    return app

# Programmatic push (for models not decorated with @realtime_model)
def approve_order(order_id: int):
    order = db.session.get(Order, order_id)
    order.status = "approved"
    db.session.commit()
    push_update(order, changed_fields=["status"])
```

Run migrations after enabling:

```bash
flask db migrate -m "add realtime presence and field_lock tables"
flask db upgrade
```

## Configuration Options

All keys live under `PGAPPFORGE_PLUGIN_CONFIG["realtime"]` (not top-level `FAB_*` keys).

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `broker_url` | `str \| None` | `None` | Redis connection URL. Required for WebSocket transport via flask-socketio. |
| `channel_prefix` | `str` | `"pgaf_rt"` | Prefix for all pubsub channel names |
| `heartbeat_interval` | `int` | `15` | Seconds between client presence-ping emissions |
| `cursor_throttle_ms` | `int` | `50` | Minimum ms between cursor-position broadcasts |
| `conflict_strategy` | `str` | `"last_write_wins"` | `"last_write_wins"` or `"reject_stale"` (HTTP 409 on stale save) |
| `session_ttl_seconds` | `int` | `3600` | Seconds before an idle `CollaborationSession` expires |
| `socketio_path` | `str` | `"/socket.io"` | URL path for the Socket.IO endpoint |
| `cors_allowed_origins` | `str` | `"*"` | Passed directly to flask-socketio CORS config |
| `enable_audit_log` | `bool` | `True` | When `True`, `on_record_save` appends a `CollaborationEvent` row |

Additionally, `FAB_REALTIME_HEARTBEAT_INTERVAL`, `FAB_REALTIME_LOCK_TIMEOUT`, and `FAB_REALTIME_MAX_CONNECTIONS` can be set as environment variables or top-level Flask config keys as overrides.

## Key API / Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/realtime/events` | required | SSE stream; `?sub=Model_id` params for future filter hints. Keepalive ping every 25 s. |
| `GET` | `/realtime/sessions/` | required | Admin view — active `CollaborationSession` records |
| `GET` | `/realtime/presence/` | required | Admin view — live `UserPresence` rows |
| `POST` | `/realtime/api/presence` | required | Heartbeat upsert; body: `{session_token, model, entity_id, editing_field}` |
| `POST` | `/realtime/api/lock/<model>/<entity_id>/<field>` | required | Acquire advisory field lock; returns `{"ok": true, "acquired": bool, "locked_by": id_or_null}` |
| `DELETE` | `/realtime/api/lock/<model>/<entity_id>/<field>` | required | Release lock (only the owning user may release) |

SSE event frame format:

```
data: {"model":"Order","entity_id":"42","op":"UPDATE","fields":["status"]}\n\n
```

The NOTIFY payload contains only model name, entity id, operation, and field names — never field values.

## Example Usage

```python
# Activity feed macro in any Jinja2 template
{% from 'realtime/macros.html' import activity_feed %}
{{ activity_feed(model_name='Order', entity_id=record.id) }}

# Avatar bar is injected automatically by RealtimeMixin into list views.
# Each badge shows user initials coloured by hash of user_id:
# <span class="rt-avatar" style="background:#4e79a7" title="Alice (editing)">AL</span>

# Conflict resolution — when conflict_strategy="reject_stale":
# Server returns HTTP 409 on save if record was modified since client loaded it.
# With "last_write_wins" (default), the client receives an inline banner instead:
# "status" was updated by Alice while you were editing.
# [Discard my change]  [Keep mine and overwrite]

# Testing without a running app
from pgappforge.plugins.realtime import realtime_model

@realtime_model(broadcast_fields=["x", "y"])
class Dummy:
    pass

assert Dummy._realtime_enabled is True
assert Dummy._realtime_broadcast_fields == frozenset({"x", "y"})
```

A presence session is considered stale after `heartbeat_interval * 3` seconds (default 45 s) with no update and is automatically excluded from presence queries. SSE client queues are capped at 100 messages; overflow silently evicts the slow client.

## See Also

- [Audit plugin](audit.md) — `AuditLog` for compliance; `CollaborationEvent` (written by Realtime) is for collaboration forensics only
- [Integrations plugin](integrations.md) — outbound webhooks can be triggered by the same model-change events
- pgappforge SPEC: `pgappforge/plugins/realtime/SPEC.md`
