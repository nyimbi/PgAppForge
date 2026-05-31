# pgappforge Template Format

Templates are JSON files describing a domain schema. They live in three locations (last wins on name conflicts):

| Location | Purpose |
|----------|---------|
| `pgappforge/templates/bundled/` | Shipped with the package |
| `~/.pgappforge/templates/` | User-installed (persists across projects) |
| `.pgappforge/templates/` | Project-local (checked into the project repo) |

---

## Top-level fields

```json
{
  "name":             "fhir-r4",
  "schema":           "fhir_r4",
  "label":            "HL7 FHIR R4",
  "description":      "Short description (1–2 sentences)",
  "short_description":"One-liner for cards and tooltips",
  "long_description": "Multi-paragraph rich description",
  "when_to_use":      "Guidance on which projects should choose this template",
  "color":            "#3498db",
  "icon":             "fa-heartbeat",
  "version":          "4.0.1",
  "source_url":       "https://hl7.org/fhir/R4/",
  "tags":             ["healthcare", "hl7", "regulation"],
  "table_notes":      { "patient": "Narrative for each table" },
  "tables":           { "patient": [ ...columns... ] },
  "actor":            { ...see below... },
  "extensions":       { ...optional extension metadata... }
}
```

### Required fields

| Field | Type | Notes |
|-------|------|-------|
| `name` | string | Lowercase kebab-case slug. Used as the registry key. |
| `label` | string | Human-readable display name. |
| `tables` | object | Keys are table names; values are arrays of column descriptors. |

### Recommended fields

`schema`, `description`, `short_description`, `version`, `tags`, `color`, `icon`

---

## Column descriptor

Each element of a `tables.*` array:

```json
{
  "name":        "medical_record_number",
  "type":        "VARCHAR(20)",
  "pk":          false,
  "fk":          "organization.id",
  "nullable":    true,
  "unique":      false,
  "index":       true,
  "description": "Hospital-assigned MRN (HIPAA Safe Harbor de-identification field)",
  "pg_extension":"pg_trgm"
}
```

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `name` | string | **required** | Snake-case column name. Avoid SQL reserved words. |
| `type` | string | **required** | PostgreSQL type: `UUID`, `VARCHAR(n)`, `TEXT`, `INTEGER`, `BIGINT`, `NUMERIC(p,s)`, `BOOLEAN`, `DATE`, `TIMESTAMP`, `TIMESTAMPTZ`, `JSONB`, `geometry(Point,4326)`, etc. |
| `pk` | bool | `false` | Primary key. |
| `fk` | string | — | Foreign key reference: `"table_name.column_name"`. |
| `nullable` | bool | `true` | Whether the column is `NOT NULL`. |
| `unique` | bool | `false` | Unique constraint. |
| `index` | bool | `false` | Non-unique B-tree index. |
| `description` | string | — | Narrative shown in ERD tooltips and generated code comments. |
| `pg_extension` | string | — | PostgreSQL extension required for this column's type (e.g. `postgis`, `pg_trgm`, `pgcrypto`). |

---

## `actor` — the primary subject of the domain

Every domain has one principal entity that everything else relates to: `Patient` in healthcare, `Employee` in HR, `Customer` in retail, `Account` in finance, `Subscriber` in SaaS. The `actor` block declares which table plays this role and how to map its fields to a canonical interface.

**Design rules:**
- Auth `User` is **never** the actor. Actors optionally have a FK to `users` for login. Identity ≠ Role.
- `Tenant` in SaaS ≠ `Tenant` in Real Estate. Use `schema_name` to disambiguate.
- Only one actor per template. If a domain has multiple subjects, pick the primary one.

```json
"actor": {
  "role":   "patient",
  "table":  "patient",
  "schema_name": null,

  "display": {
    "singular": "Patient",
    "plural":   "Patients",
    "icon":     "fa-user-md",
    "color":    "primary"
  },

  "field_map": {
    "display_name":  ["given_name", "family_name"],
    "contact_email": "email",
    "contact_phone": "phone",
    "status_field":  "active",
    "status_map": {
      "true":  "active",
      "false": "inactive"
    },
    "external_ids": {
      "mrn": "identifier",
      "nhs": "nhs_number"
    }
  },

  "related_collections": ["encounter", "observation", "condition"],
  "tags": ["hipaa", "person", "billable"]
}
```

### `actor` fields

| Field | Type | Notes |
|-------|------|-------|
| `role` | string | Lowercase slug identifying the actor type: `"patient"`, `"employee"`, `"real-estate-tenant"`. Must be unique within a schema. |
| `table` | string | The table name (key in `tables`) that holds this actor. |
| `schema_name` | string \| null | Namespace for disambiguation. `"real-estate"` makes the qualified role `real-estate/tenant`. |
| `display.singular` | string | E.g. `"Patient"` — used in UI labels. |
| `display.plural` | string | E.g. `"Patients"` — used in list headings. |
| `display.icon` | string | FontAwesome class: `"fa-user-md"`. |
| `display.color` | string | Bootstrap contextual color: `"primary"`, `"info"`, `"success"`. |
| `field_map.display_name` | string \| string[] | Field name(s) joined with a space to form the display name. |
| `field_map.contact_email` | string \| null | Field holding the primary contact email. |
| `field_map.contact_phone` | string \| null | Field holding the primary contact phone. |
| `field_map.status_field` | string \| null | Field used to derive actor status. |
| `field_map.status_map` | object \| null | Maps raw field values (as strings) to canonical statuses: `"active"`, `"inactive"`. Boolean fields use `"true"` / `"false"` as keys. |
| `field_map.external_ids` | object | Maps id-type slug → field name. E.g. `{"mrn": "identifier"}`. |
| `related_collections` | string[] | Table names representing the actor's primary related data. |
| `tags` | string[] | Free-form labels: `"hipaa"`, `"gdpr"`, `"person"`, `"billable"`, `"regulated"`. |

### Canonical actor statuses

The framework recognises exactly three statuses. Map all domain values to one of these:

| Status | Meaning |
|--------|---------|
| `"active"` | Normal, can transact |
| `"inactive"` | Soft-deleted / suspended / discharged |
| `"unknown"` | No status field defined or value unrecognised |

---

## Tags

Tags drive domain classification (used by the template gallery) and actor feature flags.

### Domain tags (for gallery grouping)

`healthcare`, `hl7`, `finance`, `banking`, `supply-chain`, `retail`, `ecommerce`, `hr`, `payroll`, `education`, `government`, `spatial`, `gis`, `energy`, `iot`, `telecoms`, `social`, `legal`, `analytics`, `dbt`

### Actor tags (feature flags)

| Tag | Meaning |
|-----|---------|
| `person` | Actor is a natural person (affects GDPR/HIPAA UI warnings) |
| `billable` | Actor has financial transactions |
| `hipaa` | PHI — enable field-level encryption and audit logging |
| `gdpr` | Personal data — enable right-to-erasure and consent tracking |
| `regulated` | Subject to external compliance requirements |

---

## Extensions

The `extensions` object holds optional metadata for framework-specific integrations:

```json
"extensions": {
  "requires_pg_extensions": ["postgis", "pg_trgm"],
  "default_schema": "fhir_r4",
  "rls_enabled": true,
  "audit_tables": ["patient", "encounter"]
}
```

---

## Python API

```python
from pgappforge.templates import TemplateRegistry, ActorConfig, ActorMixin, ActorRegistry

# Load a template
reg = TemplateRegistry()
template = reg.get("fhir-r4")

# Get its actor config
cfg = reg.get_actor_config("fhir-r4")   # → ActorConfig(role='patient', ...)
print(cfg.display.plural)               # → "Patients"

# Register all template actors at app startup
reg.register_actors()

# Use ActorMixin on your SQLAlchemy model
from pgappforge.templates import ActorMixin, ActorConfig, ActorDisplay, ActorFieldMap

class Patient(ActorMixin, Base):
    __tablename__ = "patient"
    __actor_config__ = ActorConfig(
        role="patient",
        table="patient",
        display=ActorDisplay(singular="Patient", plural="Patients"),
        field_map=ActorFieldMap(
            display_name=["given_name", "family_name"],
            contact_email="email",
            status_field="active",
            status_map={"true": "active", "false": "inactive"},
        ),
    )
    id = Column(UUID, primary_key=True)
    given_name = Column(String(100))
    family_name = Column(String(100))
    email = Column(String(255))
    active = Column(Boolean, default=True)

# Canonical interface — works regardless of domain field names
patient = session.get(Patient, some_id)
print(patient.actor_display_name)   # "Jane Smith"
print(patient.actor_status)         # "active"
print(patient.actor_contact_email)  # "jane@example.com"

# Cross-actor search (searches all registered actor types)
actor_reg = ActorRegistry.instance()
results = actor_reg.search_all("Smith", session)
for r in results:
    print(r.role, r.display_name, r.status)
```

---

## Naming collision rules

| Scenario | Rule |
|----------|------|
| SaaS `Tenant` vs Real Estate `Tenant` | Different `schema_name` values: `"saas"` vs `"real-estate"`. Never unify. |
| Auth `User` vs domain `Customer` | Auth User is never an actor. Customer has a FK to `users`. |
| `Account` (finance) vs `Account` (auth) | Finance actor uses `schema_name: "finance"`. Auth account is always `User`. |
| `Customer` (e-commerce) vs `Customer` (CRM) | Same concept — CRM template can extend e-commerce. Share the actor role `"customer"`. |
