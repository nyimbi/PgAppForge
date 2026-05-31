# Real-Time Collaboration Layer

## Overview

The Real-Time Collaboration Layer gives pgappforge multi-user awareness with
zero additional infrastructure beyond PostgreSQL itself.  It uses
`PG LISTEN/NOTIFY` as a change-broadcast bus, Server-Sent Events (SSE) to fan
out to browser clients, and a thin JavaScript snippet that patches live rows
without a full page reload.

### Design goals

- **Zero extra infra** — only PostgreSQL is required.  Redis/SocketIO remain
  optional for deployments that want native WebSocket bidirectionality (see the
  existing `RealtimePlugin` in `__init__.py`).
- **Additive** — the PG LISTEN/NOTIFY path layers on top of the existing
  `RealtimePlugin`; both can coexist.
- **Graceful degradation** — if psycopg2 is absent or the DB is not PostgreSQL
  the listener thread silently disables itself.

### Transport path

```
SQLAlchemy after_commit  ──►  pg_notify('pgaf_changes', JSON)
                                     │
                    PostgreSQL LISTEN/NOTIFY (async)
                                     │
                       Python daemon thread (psycopg2)
                                     │
                    _dispatch_notification()
                    ├── SocketIO emit (if flask-socketio present)
                    └── broadcast_to_clients() → SSE queues → browser EventSource
```

---

## Presence System

### PresenceSession model  (`pgappforge/plugins/realtime/models.py`)

```
pgaf_presence
─────────────────────────────────────────────────────────────────
id            INTEGER  PK
user_id       INTEGER  FK → ab_user.id  ON DELETE CASCADE
session_token VARCHAR(64)  UNIQUE NOT NULL
model_name    VARCHAR(255)
entity_id     VARCHAR(64)
editing_field VARCHAR(255)  nullable — which field the user has focused
last_seen     TIMESTAMPTZ   indexed — used for staleness checks
```

Unique constraint on `(user_id, model_name, entity_id)` so each user has at
most one presence row per record.

### Heartbeat protocol

Clients send a `POST /realtime/api/presence` with their `session_token` every
**15 seconds** (configurable via `FAB_REALTIME_HEARTBEAT_INTERVAL`).  The
server upserts the `PresenceSession` row and returns the token so stateless
clients can re-use it across page loads.

```
Client                                    Server
  │  POST /realtime/api/presence           │
  │  { session_token, model, entity_id,   │
  │    editing_field }                     │
  │ ─────────────────────────────────────► │
  │                                        │  upsert pgaf_presence
  │  { ok: true, session_token: "…" }      │
  │ ◄───────────────────────────────────── │
  │                                        │
  │  (15 s later — repeat)                 │
```

A session is considered **stale** after `heartbeat_interval × 3` seconds
(default 45 s) with no update.  The presence API endpoint filters stale rows
from its response automatically.

### Avatar bar in list views

Add `RealtimeMixin` to any `ModelView`:

```python
from pgappforge.plugins.realtime import RealtimeMixin

class InvoiceModelView(RealtimeMixin, ModelView):
    datamodel = SQLAInterface(Invoice)
```

`RealtimeMixin` injects a Jinja2 macro call into the list template that renders
small circular user-avatar badges at the top of the list.  Each badge shows the
user's initials and is coloured by a hash of their user-id.

```html
<!-- rendered by the avatar-bar macro -->
<span class="rt-avatar" style="background:#4e79a7" title="Alice (editing)">AL</span>
<span class="rt-avatar" style="background:#f28e2b" title="Bob">BO</span>
```

### Tooltip on hover

The avatar badge has a `title` attribute populated from the `editing_field`
column.  When a user has `editing_field` set the tooltip reads:

```
Alice — editing "amount"
```

When `editing_field` is null:

```
Bob — viewing
```

---

## Change Streams

### NOTIFY payload format

Every `push_update()` call issues:

```sql
SELECT pg_notify('pgaf_changes', $payload$)
```

where `$payload$` is a JSON object:

```jsonc
{
  "model":     "Invoice",          // SQLAlchemy class name
  "entity_id": "42",               // str(instance.id)
  "op":        "UPDATE",           // CREATE | UPDATE | DELETE
  "fields":    ["status", "amount"] // changed broadcast fields, may be []
}
```

The channel name `pgaf_changes` is the constant `_CHANNEL` in
`pgappforge/plugins/realtime/__init__.py`.

### SSE endpoint

```
GET /realtime/events?sub=Invoice_42&sub=Invoice_list
```

Returns a `text/event-stream` response.  The `sub` query params are informational
(used by future filter logic); the server currently fans out **all** model-change
events to every connected SSE client.

Each event frame:

```
data: {"model":"Invoice","entity_id":"42","op":"UPDATE","fields":["status"]}\n\n
```

Keepalive ping (every 25 s of no traffic):

```
data: {"type":"ping"}\n\n
```

On connect:

```
data: {"type":"connected"}\n\n
```

### UI update on change

The client-side snippet (injected by `RealtimeMixin`) listens on the SSE stream
and applies updates:

**List view** — for rows matching `entity_id`, a subtle flash animation
highlights the changed cells, then an AJAX call to the detail endpoint refreshes
the row data in place.  No full reload required.

**Detail view** — a small badge appears below the record title:

```
↻ Updated 2 s ago by Alice
```

The badge is updated on each received event for the current record and auto-hides
after 30 s.

---

## Field Locking (Advisory)

Advisory locks prevent two users from concurrently editing the same field.
They are **advisory** — the framework does not block DB writes, but the UI
signals the conflict and offers a merge dialog.

### FieldLock model  (`pgappforge/plugins/realtime/models.py`)

```
pgaf_field_lock
─────────────────────────────────────────────────────────────────
id            INTEGER  PK
model_name    VARCHAR(255)  NOT NULL
entity_id     VARCHAR(64)   NOT NULL
field_name    VARCHAR(255)  NOT NULL
user_id       INTEGER  FK → ab_user.id  ON DELETE CASCADE
locked_at     TIMESTAMPTZ
expires_at    TIMESTAMPTZ   indexed — for sweep queries
```

Unique constraint on `(model_name, entity_id, field_name)` — at most one lock
per field per record.

### Lock acquisition

```
POST /realtime/api/lock/<model_name>/<entity_id>/<field_name>
```

Response when lock granted:

```json
{ "ok": true, "acquired": true }
```

Response when already locked by another user:

```json
{ "ok": true, "acquired": false, "locked_by": 7 }
```

The lock TTL is `FAB_REALTIME_LOCK_TIMEOUT` seconds (default 30).  A lock
automatically grants to its requester if it has already expired, even if the
stored `user_id` differs.

### Lock release

```
DELETE /realtime/api/lock/<model_name>/<entity_id>/<field_name>
```

Only the owning user can release a lock.  Response:

```json
{ "ok": true }
```

### Conflict resolution UI

When a client receives a `model_change` event for a record it currently has
open:

1. If the changed `fields` overlap with fields the current user is editing, a
   non-blocking conflict banner appears:

   ```
   ⚠ "status" was updated by Alice while you were editing.
      [Discard my change]  [Keep mine and overwrite]
   ```

2. The user resolves by choosing one option; the client either discards its
   pending value (re-fetches from server) or proceeds with a save that
   will overwrite the server value (`last_write_wins` behaviour).

3. If the plugin is configured with `conflict_strategy: "reject_stale"` the
   server will return `HTTP 409 Conflict` on save and the client shows a hard
   error rather than an inline banner.

---

## Activity Feed Widget

The activity feed shows the last 20 collaboration events for an entity.

### Jinja2 macro usage

In any template:

```jinja
{% from 'realtime/macros.html' import activity_feed %}
{{ activity_feed(model_name='Invoice', entity_id=record.id) }}
```

The macro renders a `<ul class="rt-activity-feed">` list, each item containing:

```html
<li class="rt-event rt-event--record.save.update">
  <span class="rt-event__actor">Alice</span>
  <span class="rt-event__verb">saved</span>
  <span class="rt-event__field">status → "paid"</span>
  <time class="rt-event__time" datetime="2026-05-31T09:14:00Z">2 min ago</time>
</li>
```

The feed is populated via AJAX to `GET /realtime/api/events/<model>/<entity_id>`
and refreshes whenever an SSE `model_change` event is received for the entity.

### Last 20 events per entity

The API endpoint queries `CollaborationEvent` ordered by `created_at DESC`
with `LIMIT 20`, filtered by the session's `model_name` and `record_pk`.  This
keeps the payload small and the render fast regardless of total event volume.

---

## Framework API

### `@realtime_model` decorator

```python
from pgappforge.plugins.realtime import realtime_model

@realtime_model(broadcast_fields=["status", "amount", "assignee_id"])
class Invoice(Model):
    __tablename__ = "invoice"
    id     = Column(Integer, primary_key=True)
    status = Column(String(32))
    amount = Column(Numeric(12, 2))
    assignee_id = Column(Integer, ForeignKey("ab_user.id"))
```

Effects:

- Sets `Invoice._realtime_enabled = True` and
  `Invoice._realtime_broadcast_fields = frozenset({"status", "amount", "assignee_id"})`.
- Registers an `after_commit` SQLAlchemy session event that calls `push_update()`
  for every modified instance of `Invoice`, passing only the declared
  `broadcast_fields` that are present on the instance.

If `broadcast_fields` is omitted, `push_update()` is called with an empty
`fields` list (clients receive the event but no field-level hints).

### `RealtimeMixin` for ModelViews

```python
from pgappforge.plugins.realtime import RealtimeMixin
from flask_appbuilder import ModelView
from flask_appbuilder.models.sqla.interface import SQLAInterface

class InvoiceModelView(RealtimeMixin, ModelView):
    datamodel    = SQLAInterface(Invoice)
    list_columns = ["id", "status", "amount"]
    # optional — defaults to the model class name
    realtime_model_name = "Invoice"
```

`RealtimeMixin` provides:

| Attribute | Default | Purpose |
|-----------|---------|---------|
| `realtime_enabled` | `True` | Toggle per-view |
| `realtime_model_name` | `""` | Override if model name ≠ view name |

When `realtime_enabled` is `True` the mixin:

1. Injects SSE subscription JavaScript into list and detail templates.
2. Renders the avatar-bar macro in the list header.
3. Sends presence heartbeats from the browser.

### `push_update()` programmatic API

```python
from pgappforge.plugins.realtime import push_update

def approve_invoice(invoice_id: int):
    inv = db.session.get(Invoice, invoice_id)
    inv.status = "approved"
    db.session.commit()
    # explicit push if the model is not decorated with @realtime_model:
    push_update(inv, changed_fields=["status"])
```

`push_update` signature:

```python
def push_update(
    instance: Any,
    changed_fields: list[str] | None = None,
) -> None
```

- Connects to the PostgreSQL engine from `current_app.extensions["sqlalchemy"]`.
- Issues `SELECT pg_notify('pgaf_changes', :payload)` in an autocommit
  transaction.
- Silently logs a warning and returns if called outside an app context or when
  the DB is not PostgreSQL.

---

## Configuration

All keys are read from `current_app.config` with `FAB_REALTIME_` prefix.

| Key | Default | Type | Description |
|-----|---------|------|-------------|
| `FAB_REALTIME_HEARTBEAT_INTERVAL` | `15` | int (seconds) | Client presence ping cadence |
| `FAB_REALTIME_LOCK_TIMEOUT` | `30` | int (seconds) | Advisory lock TTL |
| `FAB_REALTIME_MAX_CONNECTIONS` | `1000` | int | Max concurrent SSE clients; excess connections receive `HTTP 503` |

### Example Flask config

```python
FAB_REALTIME_HEARTBEAT_INTERVAL = 15   # seconds
FAB_REALTIME_LOCK_TIMEOUT       = 30   # seconds
FAB_REALTIME_MAX_CONNECTIONS    = 500
```

### Environment variable override

Each key can alternatively be set via environment variable using the same name:

```bash
export FAB_REALTIME_HEARTBEAT_INTERVAL=10
export FAB_REALTIME_LOCK_TIMEOUT=60
```

### Interaction with SocketIO plugin config

When the full `RealtimePlugin` (`broker_url` + flask-socketio) is active,
`FAB_REALTIME_HEARTBEAT_INTERVAL` also governs the SocketIO heartbeat handler
so both transports stay in sync.

---

## Integration with Audit Trail

### AuditMixin → NOTIFY

When a model uses both `AuditMixin` and `@realtime_model`, the `AuditMixin`
`after_commit` hook fires first (SQLAlchemy event ordering: registration order),
writing the audit row.  Then the `@realtime_model` hook fires and calls
`push_update()`, which triggers `pg_notify`.

This means audit rows are always committed **before** the NOTIFY fires, so
clients that react to the SSE event and immediately query the audit log will see
a consistent state.

### RealtimeMixin listens, AuditMixin fires

```
User saves record
      │
      ▼
AuditMixin.after_commit  ──► INSERT INTO pgaf_audit_log
      │
      ▼
@realtime_model.after_commit ──► pg_notify('pgaf_changes', {...})
      │
      ▼
_listen_loop (daemon thread)
      │
      ├── SocketIO.emit  (if configured)
      └── broadcast_to_clients() → SSE → browser
```

The browser receives the SSE event and can optionally re-fetch the activity feed,
which will include the new audit-log entry.

### CollaborationEvent vs AuditLog

| | `CollaborationEvent` | `AuditLog` |
|---|---|---|
| Written by | `RealtimePlugin.on_record_save()` | `AuditMixin` |
| Scope | Collaboration session context | All saves, all users |
| Payload | Session-scoped field diffs | Full before/after snapshot |
| Retention | Purged with session cascade | Long-term retention |
| Purpose | Collaboration forensics, replay | Compliance, audit |

Both systems are independent and non-conflicting; enabling one does not require
the other.

---

## Database Migrations

The two new tables (`pgaf_presence`, `pgaf_field_lock`) are picked up
automatically by Alembic autogenerate if `RealtimePlugin.register_models()` is
called during migration:

```bash
flask db migrate -m "add realtime presence and field_lock tables"
flask db upgrade
```

For manual SQL:

```sql
CREATE TABLE pgaf_presence (
    id            SERIAL PRIMARY KEY,
    user_id       INTEGER REFERENCES ab_user(id) ON DELETE CASCADE NOT NULL,
    session_token VARCHAR(64) NOT NULL UNIQUE,
    model_name    VARCHAR(255),
    entity_id     VARCHAR(64),
    editing_field VARCHAR(255),
    last_seen     TIMESTAMPTZ DEFAULT now() NOT NULL
);
CREATE UNIQUE INDEX ON pgaf_presence (user_id, model_name, entity_id);
CREATE INDEX ON pgaf_presence (last_seen);

CREATE TABLE pgaf_field_lock (
    id          SERIAL PRIMARY KEY,
    model_name  VARCHAR(255) NOT NULL,
    entity_id   VARCHAR(64)  NOT NULL,
    field_name  VARCHAR(255) NOT NULL,
    user_id     INTEGER REFERENCES ab_user(id) ON DELETE CASCADE NOT NULL,
    locked_at   TIMESTAMPTZ DEFAULT now(),
    expires_at  TIMESTAMPTZ NOT NULL
);
CREATE UNIQUE INDEX ON pgaf_field_lock (model_name, entity_id, field_name);
CREATE INDEX ON pgaf_field_lock (expires_at);
```

---

## Security Considerations

- All SSE and presence/lock API endpoints require `@has_access` — unauthenticated
  requests receive `HTTP 403`.
- `session_token` is a `secrets.token_urlsafe(32)` value (256-bit entropy);
  it is stored server-side and must match on every heartbeat.
- Field lock release is gated by `user_id` match — users cannot release locks
  they do not own.
- The NOTIFY payload contains only the model name, entity id, operation, and
  field names — no field *values* are transmitted via the bus.
- SSE client queues are capped at 100 messages (`Queue(maxsize=100)`); overflow
  evicts the slow client silently.
- Stale SSE connections (no `get()` activity for > 120 s) are reaped on the
  next `broadcast_to_clients()` call.

---

## Testing

```python
# tests/ci/test_realtime_plugin.py
import json
import pytest
from pgappforge.plugins.realtime import push_update, realtime_model
from pgappforge.plugins.realtime.views import broadcast_to_clients, _SSE_CLIENTS

def test_push_update_no_app_context(caplog):
    """push_update outside app context logs a warning, does not raise."""
    class FakeModel:
        id = 1
    push_update(FakeModel(), changed_fields=["status"])
    assert any("push_update failed" in r.message for r in caplog.records)

def test_realtime_model_decorator_sets_attrs():
    @realtime_model(broadcast_fields=["x", "y"])
    class Dummy:
        pass
    assert Dummy._realtime_enabled is True
    assert Dummy._realtime_broadcast_fields == frozenset({"x", "y"})

def test_broadcast_to_clients_drops_full_queue():
    import queue
    q = queue.Queue(maxsize=1)
    q.put("existing")
    import time
    q._last_active = time.monotonic()
    _SSE_CLIENTS[999] = q
    broadcast_to_clients({"model": "X", "entity_id": "1", "op": "UPDATE", "fields": []})
    assert 999 not in _SSE_CLIENTS  # full queue → evicted
```

Run with:

```bash
.venv/bin/python -m pytest tests/ci/test_realtime_plugin.py -vxs
```
