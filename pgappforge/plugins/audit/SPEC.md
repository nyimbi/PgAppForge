# Audit Trail & Compliance Engine

## Overview

### Why Audit Trails?

Regulatory frameworks including SOC 2, HIPAA, GDPR, PCI-DSS, and ISO 27001 mandate that applications maintain immutable records of who changed what data, and when. Without a tamper-evident audit trail, organizations face regulatory fines, failed audits, and inability to reconstruct events during incident investigations.

pgappforge's Audit Trail & Compliance Engine provides:

- **Automatic change tracking**: INSERT, UPDATE, and DELETE operations are captured at the SQLAlchemy session level with field-level diffs, requiring zero boilerplate on individual endpoints.
- **Cryptographic hash chain**: Each audit row stores `sha256(json(field_diffs) + prev_hash)`, forming an append-only chain where any tampering of a historical record breaks the chain for all subsequent rows. Verification is O(n) and available via API.
- **Actor-pattern integration**: The engine reads `flask_login.current_user` automatically and supports enrichment via an optional `actor_role` attribute on model instances.
- **PII masking at write time**: Fields listed in `__audit_pii_fields__` are SHA-256 hashed before storage — the diff is preserved (you know the field changed) but the raw value is never written to the audit log.
- **GDPR right-to-erasure**: `AuditMixin.anonymize()` replaces any surviving PII in historical audit rows with `[REDACTED-<hash_prefix>]` without deleting the audit record.
- **Configurable retention**: `AuditRetentionPolicy` models per-entity retention windows with optional archive-before-delete to a secondary PostgreSQL schema or S3-compatible bucket.

### Architecture Decisions

**Session-level events, not mapper events**: Mapper `before_insert`/`after_update` events fire inside the flush, where accessing the session to write secondary rows is illegal (causes autoflush recursion or silent data loss). The engine uses `after_flush` to collect pending diffs into a thread-local staging dict, then `after_commit` to write them in a **fresh independent session** bound to the same engine. This means audit rows survive even if the primary session is rolled back after commit — which is the correct behavior.

**Append-only by design**: The `pgaf_audit_log` table has no `UPDATE` or `DELETE` permissions granted to the application role. If you need GDPR erasure, use `AuditMixin.anonymize()` which overwrites PII within existing rows via a privileged call — the audit record itself (timestamps, operation, hash chain) is preserved.

**BRIN index on `created_at`**: Audit logs grow without bound. A BRIN (Block Range INdex) index on the time column provides efficient range scans at a tiny fraction of the space cost of a B-tree, which is appropriate for an append-only table with naturally ordered inserts.

---

## Quick Start

### 1. Attach `AuditMixin` to your model

```python
from pgappforge.plugins.audit import AuditMixin
from pgappforge import Model
from sqlalchemy import Column, Integer, String, Date

class Patient(AuditMixin, Model):
    __tablename__ = "patients"

    # Fields listed here are SHA-256 hashed before being written to audit log
    __audit_pii_fields__ = frozenset({"date_of_birth", "ssn", "phone", "email"})

    # Fields excluded from diff tracking entirely (e.g. auto-updated timestamps)
    __audit_exclude_fields__ = AuditMixin.__audit_exclude_fields__ | frozenset({"last_login"})

    id = Column(Integer, primary_key=True)
    name = Column(String(255))
    date_of_birth = Column(Date)
    ssn = Column(String(11))
    phone = Column(String(20))
    email = Column(String(255))
    ward = Column(String(64))
```

### 2. Register `AuditPlugin` at app startup

```python
from pgappforge.plugins.audit import AuditPlugin

def create_app():
    app = Flask(__name__)
    appbuilder = AppBuilder(app, db.session)

    plugin = AuditPlugin()
    plugin.initialize(app, appbuilder)
    plugin.register_views(appbuilder)

    return app
```

`AuditPlugin.initialize()` calls `setup_audit_session_events()` which wires the global `after_flush` / `after_commit` / `after_rollback` listeners onto SQLAlchemy's `Session` class. This is idempotent-safe to call multiple times (SQLAlchemy deduplicates listeners by default).

### 3. Create the audit tables

```bash
flask db upgrade
# or, for direct SQLAlchemy usage:
from pgappforge.plugins.audit.models import AuditLog, AuditRetentionPolicy
AuditLog.__table__.create(engine, checkfirst=True)
AuditRetentionPolicy.__table__.create(engine, checkfirst=True)
```

### 4. Trigger a change and verify

```python
patient = Patient(name="Alice", ward="ICU")
db.session.add(patient)
db.session.commit()
# -> AuditLog row inserted: operation=INSERT, field_diffs={"name": {"before": null, "after": "Alice"}, ...}

patient.ward = "Cardiology"
db.session.commit()
# -> AuditLog row inserted: operation=UPDATE, field_diffs={"ward": {"before": "ICU", "after": "Cardiology"}}
```

### Configuration Keys

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `FAB_AUDIT_PII_FIELDS` | `dict[str, list[str]]` | `{}` | Global PII field override map: `{"Patient": ["ssn", "dob"]}`. Merged with per-model `__audit_pii_fields__`. |
| `FAB_AUDIT_RETENTION_DAYS` | `int` | `730` | Default retention in days when no `AuditRetentionPolicy` row exists for a model. |
| `FAB_AUDIT_ARCHIVE_DESTINATION` | `str \| None` | `None` | Default archive destination URI (PostgreSQL schema URI or S3 URI). |
| `FAB_AUDIT_ENABLED` | `bool` | `True` | Global kill switch. Set to `False` in test environments to suppress audit writes. |
| `FAB_AUDIT_HASH_ALGORITHM` | `str` | `"sha256"` | Hash algorithm for chain computation. Only `sha256` currently supported. |

---

## AuditMixin API

### Class Variables

#### `__audit_exclude_fields__: ClassVar[frozenset]`

Columns that are **never** included in field diffs. Defaults to:

```python
frozenset({"created_on", "changed_on", "created_at", "updated_at", "row_hash"})
```

These are auto-managed timestamp columns that change on every write and produce meaningless noise in diffs. Subclasses should union with the default:

```python
__audit_exclude_fields__ = AuditMixin.__audit_exclude_fields__ | frozenset({"my_internal_counter"})
```

#### `__audit_pii_fields__: ClassVar[frozenset]`

Columns whose values are **SHA-256 hashed** before being stored in `field_diffs`. The hash is truncated to 16 hex characters to indicate the field changed (allowing deduplication) without exposing the raw value. Defaults to `frozenset()`.

Example storage for a PII field:
```json
{
  "ssn": {
    "before": "[REDACTED-a3f4c1e2b5d6f7a8]",
    "after":  "[REDACTED-9b2e4d6f1a3c5e7b]"
  }
}
```

### Class Methods

#### `anonymize(session: Session, entity_id: Any) -> int`

GDPR Article 17 (Right to Erasure) compliance helper. Scans all `AuditLog` rows for this model and entity, replaces any PII field values with `[REDACTED-<sha256_prefix>]`, and flushes. Does **not** delete rows — the audit record (timestamps, operation type, actor, hash chain) is preserved.

**Parameters:**
- `session`: An active SQLAlchemy session with write access to `pgaf_audit_log`.
- `entity_id`: The primary key of the entity being erased. Converted to `str` for comparison.

**Returns:** Number of audit rows modified.

**Example:**
```python
# GDPR erasure request for patient id=42
rows_touched = Patient.anonymize(db.session, entity_id=42)
db.session.commit()
print(f"Anonymized {rows_touched} audit records")
```

**Note:** After anonymization, hash chain verification for this entity will fail because the field_diffs content has changed. This is expected and documented. Store the anonymization timestamp separately if chain continuity proof is required post-erasure.

---

## Audit Log Schema

### `pgaf_audit_log` table

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `id` | `bigint` (autoincrement PK) | No | Surrogate primary key. Use `bigint` — audit tables grow large. |
| `model_name` | `varchar(255)` | No | Python class name of the audited model (e.g. `"Patient"`). |
| `entity_id` | `varchar(64)` | No | String representation of the entity's primary key. Supports composite PKs serialized as JSON. |
| `operation` | `varchar(10)` | No | One of `INSERT`, `UPDATE`, `DELETE`. |
| `actor_id` | `integer` (FK → `ab_user.id`) | Yes | ID of the authenticated user. `NULL` for system/background operations. |
| `actor_role` | `varchar(128)` | Yes | Role name, populated from `instance.actor_role` if present or from the actor-pattern enrichment hook. |
| `actor_sub_role` | `varchar(128)` | Yes | Sub-role for systems with hierarchical roles (e.g. `"attending_physician"`). |
| `ip_address` | `inet` | Yes | Client IP address from Flask's `request.remote_addr`. `NULL` outside request context. |
| `user_agent` | `varchar(512)` | Yes | HTTP User-Agent header. |
| `field_diffs` | `jsonb` | No | Field-level diff map (see format below). |
| `row_hash` | `varchar(64)` | No | SHA-256 hash of this row's content + previous hash. |
| `prev_hash` | `varchar(64)` | Yes | `row_hash` of the chronologically preceding row for this entity. `NULL` for the first row. |
| `created_at` | `timestamptz` | No | UTC timestamp of the audit event. |

### Indexes

```sql
-- Composite index for the primary query pattern: fetch history for a specific entity
CREATE INDEX ix_pgaf_audit_model_entity ON pgaf_audit_log (model_name, entity_id);

-- BRIN index for time-range queries on the append-only table
CREATE INDEX ix_pgaf_audit_created_brin ON pgaf_audit_log USING brin (created_at);
```

### `field_diffs` JSONB Format

```json
{
  "field_name": {
    "before": <value_before_change_or_null_for_insert>,
    "after":  <value_after_change_or_null_for_delete>
  }
}
```

**INSERT example** — all `after` values populated, all `before` values are `null`:
```json
{
  "name":  {"before": null, "after": "Alice"},
  "ward":  {"before": null, "after": "ICU"},
  "email": {"before": null, "after": "[REDACTED-a3f4c1e2b5d6f7a8]"}
}
```

**UPDATE example** — only changed fields are included:
```json
{
  "ward": {"before": "ICU", "after": "Cardiology"}
}
```

**DELETE example** — all `before` values populated, all `after` values are `null`:
```json
{
  "name": {"before": "Alice", "after": null},
  "ward": {"before": "Cardiology", "after": null}
}
```

### Hash Chain Computation

```
row_hash = sha256( json_canonical(field_diffs) + prev_hash_or_empty_string )
```

Where:
- `json_canonical(field_diffs)` is `json.dumps(field_diffs, sort_keys=True, default=str)` — deterministic serialization.
- `prev_hash_or_empty_string` is the `row_hash` of the previous row for the same `(model_name, entity_id)` pair, or `""` for the first row.
- Concatenation is string concatenation (not JSON wrapping).

**Chain verification** is available at `GET /audit/api/verify/<entity_id>?model=ModelName`.

---

## Compliance Reports

### SOC 2 Access Review Template

SOC 2 Type II requires evidence that access to sensitive data is reviewed periodically. Query:

```sql
-- SOC 2 CC6.2: Privileged access review — all admin actions in the past 90 days
SELECT
    al.created_at,
    u.username        AS actor,
    al.model_name,
    al.entity_id,
    al.operation,
    al.ip_address,
    al.field_diffs
FROM pgaf_audit_log al
LEFT JOIN ab_user u ON u.id = al.actor_id
WHERE al.created_at >= NOW() - INTERVAL '90 days'
  AND al.operation IN ('UPDATE', 'DELETE')
ORDER BY al.created_at DESC;
```

**API equivalent:**
```
GET /audit/api/changes?since=2025-03-01&op=DELETE&per_page=200
```

### HIPAA Change Log Template

HIPAA §164.312(b) requires audit controls that record activity in information systems containing ePHI:

```sql
-- HIPAA audit log for Patient model, last 365 days
SELECT
    al.id,
    al.created_at                    AS "Event Time",
    COALESCE(u.username, 'SYSTEM')   AS "User",
    al.operation                     AS "Action",
    al.entity_id                     AS "Record ID",
    al.ip_address                    AS "Source IP",
    al.field_diffs                   AS "Changed Fields"
FROM pgaf_audit_log al
LEFT JOIN ab_user u ON u.id = al.actor_id
WHERE al.model_name = 'Patient'
  AND al.created_at >= NOW() - INTERVAL '365 days'
ORDER BY al.created_at;
```

### GDPR Article 30 Record of Processing Template

Article 30 requires records of processing activities. Audit log provides the raw material:

```sql
-- GDPR Art. 30: All processing on a data subject (for SAR response)
SELECT
    al.created_at   AS "Processing Time",
    al.operation    AS "Processing Activity",
    al.model_name   AS "Data Category",
    al.actor_id     AS "Processor",
    al.field_diffs  AS "Data Elements Affected"
FROM pgaf_audit_log al
WHERE al.entity_id = :subject_entity_id
  AND al.model_name IN ('Patient', 'PatientContact', 'MedicalRecord')
ORDER BY al.created_at;
```

---

## Data Retention

### `AuditRetentionPolicy` Model

One row per model class, configuring how long audit records are retained:

| Field | Type | Description |
|-------|------|-------------|
| `model_name` | `varchar(255)` UNIQUE | Python model class name. |
| `retain_days` | `integer` | Retain audit rows for this many days. Default 730 (2 years). |
| `archive_before_delete` | `boolean` | If `True`, rows are archived before deletion. |
| `archive_destination` | `varchar(512)` | Archive URI. See formats below. |
| `pii_fields` | `jsonb` | List of PII field names for this model (supplements `__audit_pii_fields__`). |

### Archive Destination Formats

**PostgreSQL secondary schema:**
```
postgresql://user:pass@host:5432/audit_archive?options=-csearch_path=archive
```

**S3-compatible:**
```
s3://my-bucket/audit-archive/{model}/{year}/{month}/
```
S3 archival requires the optional `pgappforge-audit-s3` extra (`pip install pgappforge[audit-s3]`).

### Configuring Retention

```python
from pgappforge.plugins.audit.models import AuditRetentionPolicy

# Patient records: 7-year HIPAA retention, archive to cold storage before delete
policy = AuditRetentionPolicy(
    model_name="Patient",
    retain_days=2555,  # 7 years
    archive_before_delete=True,
    archive_destination="s3://my-hipaa-archive/audit/",
    pii_fields=["ssn", "date_of_birth", "phone"],
)
db.session.add(policy)
db.session.commit()
```

### Scheduled Retention Job

The retention job should be run via your scheduler (Celery, APScheduler, cron):

```python
from pgappforge.plugins.audit.retention import run_retention_job

# Celery task
@celery.task
def audit_retention():
    run_retention_job()

# APScheduler
scheduler.add_job(run_retention_job, "cron", hour=2, minute=0)
```

The retention job:
1. Queries `AuditRetentionPolicy` for all configured models.
2. For models with `archive_before_delete=True`, exports rows older than `retain_days` to the archive destination.
3. Deletes archived rows from `pgaf_audit_log`.
4. For models without a policy, uses `FAB_AUDIT_RETENTION_DAYS` as the default.

---

## Query API

### `GET /audit/api/changes`

Returns a paginated list of audit log entries.

**Query Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `model` | `string` | Filter by model name (e.g. `Patient`). |
| `entity_id` | `string` | Filter by entity primary key. |
| `actor_id` | `integer` | Filter by actor user ID. |
| `since` | `ISO 8601 date/datetime` | Return entries at or after this timestamp. |
| `op` | `INSERT \| UPDATE \| DELETE` | Filter by operation type. |
| `page` | `integer` | Page number, 1-indexed. Default `1`. |
| `per_page` | `integer` | Results per page. Default `50`, max `200`. |

**Response Format:**

```json
{
  "entries": [
    {
      "id": 1042,
      "model_name": "Patient",
      "entity_id": "99",
      "operation": "UPDATE",
      "actor_id": 3,
      "actor_role": "nurse",
      "field_diffs": {
        "ward": {"before": "ICU", "after": "Cardiology"}
      },
      "row_hash": "a3f4c1e2b5d6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a2",
      "prev_hash": "1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2",
      "created_at": "2025-06-01T14:23:11.482910+00:00"
    }
  ],
  "page": 1,
  "per_page": 50
}
```

### `GET /audit/api/verify/<entity_id>?model=ModelName`

Verifies hash chain integrity for a specific entity.

**Response:**

```json
{
  "valid": true,
  "rows_checked": 14
}
```

If `valid` is `false`, the chain was broken at some point — either by tampering or by a `anonymize()` call (which is expected and should be cross-referenced with your erasure log).

---

## Visual Audit Viewer

The audit timeline UI is available at `/audit/` and provides:

- **Filter bar**: Filter by model name, entity ID, actor ID, date range, and operation type.
- **Timeline entries**: Each entry shows operation type (color-coded INSERT/UPDATE/DELETE), model and entity ID, timestamp, actor, and a field-by-field before/after diff.
- **Dark theme**: Designed for operations/compliance teams reviewing logs in low-light environments.

### Access Control

The `/audit/` route and `/audit/api/` endpoints are protected by `@has_access`, which enforces FAB's role-based permission system. Grant the `can_index` permission on `AuditLogView` to roles that should have read access:

```python
appbuilder.sm.add_permission_role(
    appbuilder.sm.find_role("Compliance"),
    appbuilder.sm.find_permission_view_menu("can_index", "AuditLogView")
)
```

### Embedding in Custom Views

```python
from pgappforge.plugins.audit.models import AuditLog
from sqlalchemy import select, desc

# Fetch last 10 changes for a specific patient in a custom view
rows = db.session.execute(
    select(AuditLog)
    .where(AuditLog.model_name == "Patient")
    .where(AuditLog.entity_id == str(patient_id))
    .order_by(desc(AuditLog.created_at))
    .limit(10)
).scalars().all()
```

---

## Known Limitations

1. **Bulk operations bypass the ORM**: `session.execute(update(...))`, `session.bulk_update_mappings()`, and raw SQL do not fire SQLAlchemy ORM events. These operations will not be captured by the audit engine. Use ORM-level operations for audited models, or instrument bulk paths manually.

2. **Composite primary keys**: `entity_id` is stored as `str(instance.id)`. Models with composite PKs should override `__audit_entity_id__` (future feature) or serialize the PK manually.

3. **Hash chain after anonymize**: Running `anonymize()` changes `field_diffs` content, breaking hash chain verification for that entity post-erasure. This is by design — log the erasure event separately.

4. **Session identity**: Pending audit rows are keyed by `id(session)`. In long-lived worker processes that reuse session objects, this is stable. In edge cases where Python reuses a memory address for a new session before the old one's `after_commit` fires, rows could be lost. The `after_rollback` listener mitigates this for the rollback case.

5. **PostgreSQL-only**: `field_diffs` uses `JSONB` and `ip_address` uses `INET` — both PostgreSQL-native types. This is intentional; pgappforge targets PostgreSQL exclusively.
