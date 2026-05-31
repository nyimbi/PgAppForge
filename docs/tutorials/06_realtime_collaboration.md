# Tutorial 06: Real-Time Collaboration

The Realtime plugin broadcasts record-level changes via PostgreSQL `LISTEN/NOTIFY` and optionally via Socket.IO. When multiple users have the same record open, saves in one tab propagate to all others within milliseconds — no polling, no page refresh.

## Prerequisites

- A running pgappforge app
- PostgreSQL (the `pg_notify` transport works with zero additional infrastructure)
- Optional: Redis + `flask-socketio` for full WebSocket cursors and presence

## Step 1 — Enable RealtimePlugin

```python
# config.py
PGAPPFORGE_PLUGINS = ["pgappforge.plugins.realtime"]

PGAPPFORGE_PLUGIN_CONFIG = {
    "realtime": {
        # Omit broker_url to use PG LISTEN/NOTIFY only (no Redis required)
        # "broker_url": "redis://localhost:6379/0",
        "conflict_strategy": "last_write_wins",
        "heartbeat_interval": 15,
        "enable_audit_log": True,
    }
}
```

Restart the app. Two new menu items appear under **Realtime**:

- **Collaboration Sessions** — `/realtime/sessions/`
- **User Presence** — `/realtime/presence/`

## Step 2 — Decorate a Model with @realtime_model

```python
# models.py
from pgappforge.plugins.realtime import realtime_model
from pgappforge.models.sqla import Model
from sqlalchemy import Column, Integer, String, Numeric

@realtime_model(broadcast_fields=["status", "amount", "assigned_to"])
class Order(Model):
    __tablename__ = "orders"

    id          = Column(Integer, primary_key=True)
    order_ref   = Column(String(50), nullable=False)
    status      = Column(String(30), default="PENDING")
    amount      = Column(Numeric(12, 2), nullable=False)
    assigned_to = Column(String(100), nullable=True)
```

`@realtime_model` registers an `after_commit` session listener. After every committed write to an `Order` instance it calls `push_update()`, which issues:

```sql
SELECT pg_notify('pgaf_changes', '{"model": "Order", "entity_id": "42", "op": "UPDATE", "fields": ["status"]}');
```

Only the listed `broadcast_fields` are included in the NOTIFY payload. Clients use this list for field-level highlighting (which field changed) without receiving the full record on every keystroke.

## Step 3 — Add RealtimeMixin to the View

```python
# views.py
from pgappforge.views import ModelView
from pgappforge.plugins.realtime import RealtimeMixin
from .models import Order

class OrderModelView(RealtimeMixin, ModelView):
    datamodel = SQLAInterface(Order)
    list_columns = ["order_ref", "status", "amount", "assigned_to"]
```

`RealtimeMixin` injects the SSE change-stream client into the list and detail templates. When the background listener receives a `pgaf_changes` notification it fans it out to all SSE clients subscribed to that model.

## Step 4 — Open Two Browser Tabs and Edit

1. Open `http://127.0.0.1:5000/ordermodelview/list/` in **Tab A**
2. Open the same URL in **Tab B**
3. In Tab A, click **Edit** on order #42 and change `status` to `SHIPPED`. Save.

In Tab B the row for order #42 updates automatically — the status column flickers briefly to indicate the change, then shows `SHIPPED`. No page refresh.

What happens under the hood:

1. Tab A's save commits the session
2. The `after_commit` listener calls `push_update(order, changed_fields=["status"])`
3. `push_update` issues `SELECT pg_notify('pgaf_changes', ...)`
4. The background `pgaf-realtime-listener` thread receives the notification via `psycopg2`
5. It fans the payload to all SSE clients via `broadcast_to_clients(payload)`
6. Tab B's SSE connection receives the event and updates the row in-place

## Step 5 — View the SSE Connection

The SSE endpoint is at `/realtime/events` (mounted by `RealtimeMixin`). You can inspect it directly:

```bash
curl -N http://127.0.0.1:5000/realtime/events \
  -H "Authorization: Bearer <token>"
```

Events arrive as:

```
data: {"model": "Order", "entity_id": "42", "op": "UPDATE", "fields": ["status"]}

data: {"model": "Order", "entity_id": "17", "op": "INSERT", "fields": []}
```

The stream stays open indefinitely; the client reconnects automatically if the connection drops.

## Step 6 — Programmatic Push

Call `push_update` from anywhere in your application — a Celery task, a webhook handler, a scheduled job:

```python
from pgappforge.plugins.realtime import push_update
from myapp.models import Order
from myapp import db

# Mark an order as fulfilled and broadcast the change immediately
order = db.session.get(Order, order_id)
order.status = "FULFILLED"
db.session.commit()
# The @realtime_model decorator handles push_update automatically after commit.

# Manual push for cases where the model is not decorated
push_update(order, changed_fields=["status", "fulfilled_at"])
```

`push_update` is safe to call from any thread or process. It opens its own short-lived connection to PostgreSQL, issues the NOTIFY, and closes. If the Flask app context is not available (e.g. a worker process) it logs a warning and returns silently.

## Adding Full WebSocket Support

For cursor tracking, live presence avatars, and conflict resolution (`reject_stale`), add Redis and Socket.IO:

```bash
pip install flask-socketio redis
```

```python
# config.py
PGAPPFORGE_PLUGIN_CONFIG = {
    "realtime": {
        "broker_url": "redis://localhost:6379/0",
        "conflict_strategy": "reject_stale",
        "cursor_throttle_ms": 50,
    }
}
```

With Socket.IO active, users see each other's cursor positions as coloured overlays on the form canvas, and the **User Presence** view at `/realtime/presence/` shows who is editing what in real time.

## Next Steps

- Combine with the audit plugin: `enable_audit_log: true` writes a `CollaborationEvent` row for every save made during an active collaboration session
- Add a `reject_stale` conflict strategy to prevent overwriting changes made by another user after you loaded the record
- Use the **Collaboration Sessions** view (`/realtime/sessions/`) to monitor active editing sessions across all models
