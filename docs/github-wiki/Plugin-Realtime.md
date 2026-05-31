# Plugin: Realtime

[Home](Home) > Plugin: Realtime

The Realtime plugin provides WebSocket-based multi-user synchronisation, live cursor and presence tracking, and optimistic-concurrency conflict resolution for any pgappforge ModelView. It uses `pg_notify` as the broadcast mechanism, with optional Redis for multi-process deployments.

---

## Requirements

```bash
pip install "pgappforge[realtime]"
```

Requires `flask-socketio`. Redis is required for multi-worker deployments.

---

## Initialisation

```python
PGAPPFORGE_PLUGINS = ["pgappforge.plugins.realtime"]

PGAPPFORGE_PLUGIN_CONFIG = {
    "realtime": {
        "broker_url": "redis://localhost:6379/0",   # required for multi-worker
        "heartbeat_interval": 15,                   # presence ping interval (seconds)
        "cursor_throttle_ms": 50,                   # min ms between cursor broadcasts
        "conflict_strategy": "last_write_wins",     # or "reject_stale"
        "session_ttl_seconds": 3600,
        "socketio_path": "/socket.io",
        "cors_allowed_origins": "*",
        "enable_audit_log": True,
    }
}
```

---

## Model Decorator

Mark any SQLAlchemy model for real-time broadcasting:

```python
from pgappforge.plugins.realtime import realtime_model

@realtime_model(broadcast_fields=["status", "assigned_to"])
class Ticket(Model):
    __tablename__ = "tickets"
    ...
```

After every committed change, `push_update()` is called automatically for instances of the decorated class. Only fields listed in `broadcast_fields` are included in the broadcast payload (all fields if `None`).

---

## Manual Push

```python
from pgappforge.plugins.realtime import push_update

push_update(ticket_instance, changed_fields=["status"])
```

Issues `SELECT pg_notify('pgaf_changes', :payload)` on a short-lived autocommit connection. Safe to call outside an active transaction.

---

## Conflict Strategies

| Strategy | Behaviour |
|---|---|
| `last_write_wins` | Accepts all updates regardless of version |
| `reject_stale` | Raises `ConflictError` when the record was modified since the client loaded it |

---

## Configuration

| Key | Default | Description |
|---|---|---|
| `FAB_REALTIME_HEARTBEAT_INTERVAL` | `15` | Seconds between presence-ping emissions |
| `FAB_REALTIME_LOCK_TIMEOUT` | `5` | Seconds before a record lock is released |
| `FAB_REALTIME_MAX_CONNECTIONS` | `1000` | Maximum concurrent Socket.IO connections |

---

## Further Reading

Full reference: [docs/plugins/realtime.md](../plugins/realtime.md)

---

## See also

- [Plugin: Integration Hub](Plugin-Integration-Hub)
- [Plugin: Form Builder](Plugin-Form-Builder)
- [Architecture](Architecture)
- [Python API Reference](../api/python.md)
- [Configuration Reference](../api/configuration.md)
