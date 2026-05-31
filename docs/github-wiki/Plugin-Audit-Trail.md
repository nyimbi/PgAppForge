# Plugin: Audit Trail

[Home](Home) > Plugin: Audit Trail

The Audit Trail plugin provides automatic field-level change tracking for any SQLAlchemy model, with cryptographic hash chaining, PII masking, and GDPR right-to-erasure support.

---

## Initialisation

```python
from pgappforge.plugins.audit import AuditPlugin

plugin = AuditPlugin()
plugin.initialize(app, appbuilder)
plugin.register_views(appbuilder)
```

This wires global SQLAlchemy session listeners and registers the Audit Log view at `/compliance/audit-log/`.

---

## Attaching to a Model

```python
from pgappforge.plugins.audit import AuditMixin
from pgappforge import Model

class Patient(AuditMixin, Model):
    __tablename__ = "patients"
    __audit_pii_fields__ = frozenset({"date_of_birth", "ssn", "phone"})
```

From this point, every `INSERT`, `UPDATE`, and `DELETE` on `Patient` is captured in `audit_log` with:

- `model_name` — class name
- `entity_id` — primary key
- `operation` — INSERT / UPDATE / DELETE
- `field_diffs` — `{field: {before, after}}` JSON
- `actor_id` — authenticated user id (Flask-Login)
- `actor_role` — value of `instance.actor_role` if present
- `ip_address`, `user_agent` — request context
- `row_hash` — SHA-256 of diffs + previous hash (tamper-evident chain)

PII fields named in `__audit_pii_fields__` are hashed before storage: `[REDACTED-<sha256[:16]>]`.

---

## GDPR Anonymisation

```python
count = Patient.anonymize(session, entity_id=42)
# Replaces PII values in all audit rows for entity 42
# Returns: number of rows anonymised
```

---

## Configuration

| Key | Default | Description |
|---|---|---|
| `FAB_AUDIT_PII_FIELDS` | `{}` | Global fallback PII field set (per-model `__audit_pii_fields__` takes precedence) |
| `FAB_AUDIT_RETENTION_DAYS` | `None` | If set, a scheduled task purges rows older than this many days |

---

## Further Reading

Full reference: [docs/plugins/audit.md](../plugins/audit.md)

---

## See also

- [Plugin: Data Hub](Plugin-Data-Hub)
- [Plugin: Form Builder](Plugin-Form-Builder)
- [Architecture](Architecture)
- [Python API Reference](../api/python.md)
- [Configuration Reference](../api/configuration.md)
