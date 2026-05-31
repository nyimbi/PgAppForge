# Tutorial 05: Audit Trail and GDPR Compliance

pgappforge's audit plugin records every INSERT, UPDATE, and DELETE on decorated models as tamper-evident, hash-chained log entries. The audit log supports GDPR right-to-erasure via `anonymize()`, which redacts PII values while preserving the structural diff for compliance purposes.

## Prerequisites

- A running pgappforge app with at least one SQLAlchemy model
- `pgappforge.plugins.audit` available (bundled — no extra install)

## Step 1 — Add AuditMixin to a Model

```python
# models.py
from pgappforge.plugins.audit import AuditMixin
from pgappforge.models.sqla import Model
from sqlalchemy import Column, String, Date, Integer

class Patient(AuditMixin, Model):
    __tablename__ = "patients"

    # Declare which columns contain PII — these are hashed in audit storage.
    # The hash is deterministic (SHA-256) so you can verify a value without
    # storing the plaintext.
    __audit_pii_fields__ = frozenset({"date_of_birth", "ssn", "phone"})

    id            = Column(Integer, primary_key=True)
    first_name    = Column(String(100), nullable=False)
    last_name     = Column(String(100), nullable=False)
    date_of_birth = Column(Date, nullable=True)
    ssn           = Column(String(11), nullable=True)   # PII
    phone         = Column(String(20), nullable=True)   # PII
    status        = Column(String(20), default="ACTIVE")
```

`AuditMixin.__init_subclass__` registers SQLAlchemy session listeners automatically when the class is defined. No further setup is needed.

Run `flask db upgrade` (or `flask fab create-db`) to create the `audit_log` table.

## Step 2 — Trigger Some Changes

Use the standard pgappforge UI or the REST API:

```bash
# Create a patient via the API
curl -X POST http://127.0.0.1:5000/api/v1/patient/ \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"first_name": "Jane", "last_name": "Smith", "status": "ACTIVE"}'

# Update the status
curl -X PUT http://127.0.0.1:5000/api/v1/patient/1 \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"status": "DISCHARGED"}'
```

Every committed session event (INSERT on create, UPDATE on edit, DELETE on remove) produces one audit row. The row contains:

- `model_name` — Python class name (`"Patient"`)
- `entity_id` — string representation of the primary key
- `operation` — `INSERT`, `UPDATE`, or `DELETE`
- `field_diffs` — JSONB diff: `{"status": {"before": "ACTIVE", "after": "DISCHARGED"}}`
- `actor_id` — the authenticated user who made the change
- `created_at` — UTC timestamp
- `row_hash` — SHA-256 of `field_diffs + previous_row_hash` (hash chain)

## Step 3 — View the Audit Timeline

Navigate to `/audit/` in the UI. You see a timeline of all audit events across all models.

Filter the list:

- **Model**: select `Patient` to show only patient changes
- **Entity ID**: enter `1` to show changes to patient record 1
- **Operation**: filter to `UPDATE` only
- **Date range**: restrict to a specific period

Each row expands to show the full field diff with before/after values side by side.

## Step 4 — Filter by Model and Entity

The audit timeline URL supports query parameters:

```
/audit/?model=Patient&entity_id=1
```

This is useful for embedding an audit panel in a detail view. In your `ModelView`:

```python
class PatientModelView(ModelView):
    # ...
    @expose("/audit/<int:pk>")
    @has_access
    def audit_trail(self, pk):
        return redirect(f"/audit/?model=Patient&entity_id={pk}")
```

## Step 5 — Verify the Hash Chain

The audit plugin chains row hashes so any deletion or modification of an audit row breaks the chain and is detectable.

Verify via the REST API:

```bash
# Verify all audit rows for entity 42 (Patient model)
GET /audit/api/verify/42?model=Patient
```

Response on a valid chain:

```json
{
  "entity_id": "42",
  "model": "Patient",
  "row_count": 7,
  "chain_valid": true,
  "first_hash": "3a7bc...",
  "last_hash": "f91de..."
}
```

Response when tampering is detected:

```json
{
  "chain_valid": false,
  "broken_at_row": 4,
  "expected_hash": "3a7bc...",
  "found_hash": "00000..."
}
```

## Step 6 — GDPR Right-to-Erasure

To anonymize all PII in the audit log for a specific patient while keeping the structural diff for compliance:

```python
from pgappforge.models.sqla import db
from myapp.models import Patient

# Replaces PII field values with [REDACTED-<sha256_prefix>] in all audit rows
rows_anonymized = Patient.anonymize(db.session, patient_id=42)
print(f"Anonymized {rows_anonymized} audit rows for patient 42")
```

After anonymization the audit row for a `phone` change looks like:

```json
{
  "phone": {
    "before": "[REDACTED-a3f9c2b1d4e8...]",
    "after":  "[REDACTED-7e2a1f3b9c04...]"
  }
}
```

The hash in `[REDACTED-...]` is a deterministic SHA-256 prefix of the original value. You can verify that a known value matches a redacted entry without the audit log storing the plaintext — useful in compliance audits where you need to confirm erasure of a specific value.

## What's Next

- Add `__audit_exclude_fields__` to skip noisy high-frequency columns (e.g. `last_heartbeat`, `request_count`)
- Integrate with the approval workflow: every approval decision is automatically audit-logged when you use `ApprovalMixin`
- Export audit data to a SIEM or data warehouse using the audit REST API: `GET /audit/api/export?model=Patient&format=jsonl`
