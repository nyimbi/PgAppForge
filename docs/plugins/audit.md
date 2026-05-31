# Audit Trail & Compliance Engine

The Audit Trail plugin captures every INSERT, UPDATE, and DELETE on opted-in models as an immutable, cryptographically hash-chained log stored in PostgreSQL. It satisfies the change-tracking requirements of SOC 2, HIPAA, GDPR, and PCI-DSS without any per-endpoint boilerplate: events are captured at the SQLAlchemy session level (`after_flush` / `after_commit`), not in view code.

PII fields are SHA-256 hashed before storage so the diff is preserved (you know the field changed) but raw values never reach the audit table. The GDPR right-to-erasure path (`AuditMixin.anonymize()`) overwrites surviving values in-place without deleting the audit record itself.

## Quick Start

```python
from pgappforge.plugins.audit import AuditPlugin, AuditMixin
from pgappforge import Model
from sqlalchemy import Column, Integer, String, Date

# 1. Attach AuditMixin to any model
class Patient(AuditMixin, Model):
    __tablename__ = "patients"
    __audit_pii_fields__ = frozenset({"date_of_birth", "ssn", "phone", "email"})
    # Extend the default exclusion set if needed
    __audit_exclude_fields__ = AuditMixin.__audit_exclude_fields__ | frozenset({"last_login"})

    id            = Column(Integer, primary_key=True)
    name          = Column(String(255))
    date_of_birth = Column(Date)
    ssn           = Column(String(11))
    ward          = Column(String(64))

# 2. Register the plugin in your app factory
def create_app():
    app = Flask(__name__)
    appbuilder = AppBuilder(app, db.session)

    plugin = AuditPlugin()
    plugin.initialize(app, appbuilder)   # wires session-level listeners
    plugin.register_views(appbuilder)    # mounts /audit/ UI under "Compliance" menu

    return app

# 3. Create tables
flask db upgrade
# or: AuditLog.__table__.create(engine, checkfirst=True)
```

From this point every `db.session.commit()` on a `Patient` instance automatically produces an `AuditLog` row. No changes to view or API code are needed.

## Configuration Options

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `FAB_AUDIT_PII_FIELDS` | `dict[str, list[str]]` | `{}` | Global PII override map — `{"Patient": ["ssn", "dob"]}`. Merged with per-model `__audit_pii_fields__`. |
| `FAB_AUDIT_RETENTION_DAYS` | `int` | `730` | Default retention when no `AuditRetentionPolicy` row exists for a model. |
| `FAB_AUDIT_ARCHIVE_DESTINATION` | `str \| None` | `None` | Default archive URI — PostgreSQL schema URI or S3-compatible URI. |
| `FAB_AUDIT_ENABLED` | `bool` | `True` | Global kill switch. Set `False` in test environments to suppress audit writes. |
| `FAB_AUDIT_HASH_ALGORITHM` | `str` | `"sha256"` | Hash algorithm for chain computation. Only `sha256` currently supported. |

## Key API

### `AuditMixin.anonymize(session, entity_id) -> int`

GDPR Article 17 compliance. Scans all `AuditLog` rows for this model and entity, replaces PII field values with `[REDACTED-<sha256_prefix>]`, and flushes. The audit record (timestamps, operation, actor, hash chain) is preserved; only `field_diffs` content is overwritten.

```python
rows_touched = Patient.anonymize(db.session, entity_id=42)
db.session.commit()
```

Note: anonymization breaks hash-chain verification for that entity by design. Log the erasure event separately if chain-continuity proof is required post-erasure.

### `setup_audit_session_events()`

Called once by `AuditPlugin.initialize()`. Wires the global `after_flush`, `after_commit`, and `after_rollback` listeners onto SQLAlchemy's `Session` class. Safe to call multiple times (SQLAlchemy deduplicates listeners).

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/audit/` | Timeline UI — filterable by model, entity, actor, date range, operation |
| `GET` | `/audit/api/changes` | Paginated audit log; query params: `model`, `entity_id`, `actor_id`, `since`, `op`, `page`, `per_page` (max 200) |
| `GET` | `/audit/api/verify/<entity_id>` | Hash-chain integrity check; returns `{"valid": bool, "rows_checked": int}` |

All routes require `@has_access`. Grant `can_index` on `AuditLogView` to compliance roles:

```python
appbuilder.sm.add_permission_role(
    appbuilder.sm.find_role("Compliance"),
    appbuilder.sm.find_permission_view_menu("can_index", "AuditLogView")
)
```

## Example Usage

```python
# Normal ORM usage — audit is transparent
patient = Patient(name="Alice", ward="ICU")
db.session.add(patient)
db.session.commit()
# -> AuditLog: operation=INSERT, field_diffs={"name": {"before": null, "after": "Alice"}, ...}

patient.ward = "Cardiology"
db.session.commit()
# -> AuditLog: operation=UPDATE, field_diffs={"ward": {"before": "ICU", "after": "Cardiology"}}

# Query via API
# GET /audit/api/changes?model=Patient&entity_id=1&since=2026-01-01

# Embed in a custom view
from pgappforge.plugins.audit.models import AuditLog
from sqlalchemy import select, desc

rows = db.session.execute(
    select(AuditLog)
    .where(AuditLog.model_name == "Patient")
    .where(AuditLog.entity_id == str(patient.id))
    .order_by(desc(AuditLog.created_at))
    .limit(10)
).scalars().all()

# Schedule the retention job (Celery / APScheduler)
from pgappforge.plugins.audit.retention import run_retention_job
scheduler.add_job(run_retention_job, "cron", hour=2, minute=0)
```

### Known Limitations

- Bulk ORM operations (`session.execute(update(...))`, `bulk_update_mappings()`) bypass session events and are not captured.
- The `pgaf_audit_log` table uses PostgreSQL `JSONB` and `INET` column types — this plugin is PostgreSQL-only.
- After `anonymize()`, hash-chain verification for that entity will report `valid: false`. This is expected behavior.

## See Also

- [Data Hub plugin](data_hub.md) — bulk import/export with PII redaction options
- [Realtime plugin](realtime.md) — `CollaborationEvent` for collaboration forensics (complements, does not replace, `AuditLog`)
- pgappforge SPEC: `pgappforge/plugins/audit/SPEC.md`
- HIPAA §164.312(b), GDPR Article 30, SOC 2 CC6.2 compliance query templates are in `SPEC.md`
