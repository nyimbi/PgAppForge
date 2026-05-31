# Python API Reference

---

## `AppBuilder`

**`pgappforge.AppBuilder(app, session, **kwargs)`**

Central orchestrator for a pgappforge application. Manages view registration, security, menus, permissions, addon managers, and the Flask app lifecycle.

### Signature

```python
class AppBuilder:
    def __init__(
        self,
        app: Flask | None = None,
        session: Session | None = None,
        menu: Menu | None = None,
        indexview: type[AbstractViewApi] | None = None,
        base_template: str = "appbuilder/baselayout.html",
        static_folder: str = "static/appbuilder",
        static_url_path: str = "/appbuilder",
        security_manager_class: type[BaseSecurityManager] | None = None,
        update_perms: bool = True,
    ) -> None: ...
```

### Parameters

| Parameter | Type | Description |
|---|---|---|
| `app` | `Flask \| None` | Flask application instance. Pass `None` when using the app-factory pattern; call `init_app(app)` later. |
| `session` | `Session \| None` | SQLAlchemy session. Required for SQLAlchemy-backed security. Pass `None` when using MongoEngine. |
| `menu` | `Menu \| None` | Pre-constructed `Menu` instance. Defaults to a new empty menu. |
| `indexview` | `type \| None` | Custom index view class. Defaults to the built-in `IndexView`. |
| `base_template` | `str` | Jinja2 base template path. |
| `static_folder` | `str` | Flask static folder for framework assets. |
| `static_url_path` | `str` | URL prefix for framework static files. |
| `security_manager_class` | `type \| None` | Custom security manager. Defaults to `SecurityManager` (SQLAlchemy). |
| `update_perms` | `bool` | Auto-sync permissions on startup. Set `False` in production if startup time matters. |

### Returns

`AppBuilder` instance.

### Example

```python
from flask import Flask
from pgappforge import AppBuilder, SQLA

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "postgresql://user:pass@localhost/mydb"
app.config["SECRET_KEY"] = "..."

db = SQLA(app)
appbuilder = AppBuilder(app, db.session)
```

App-factory pattern:

```python
db = SQLA()
appbuilder = AppBuilder()

def create_app():
    app = Flask(__name__)
    app.config.from_object("config")
    db.init_app(app)
    appbuilder.init_app(app, db.session)
    return app
```

---

## `AuditMixin`

**`pgappforge.plugins.audit.AuditMixin`**

Mixin class for SQLAlchemy models. Enables automatic field-level audit logging with cryptographic hash chaining and PII masking.

### Class Attributes

| Attribute | Type | Default | Description |
|---|---|---|---|
| `__audit_exclude_fields__` | `frozenset` | `{"created_on", "changed_on", "created_at", "updated_at", "row_hash"}` | Columns never included in diffs |
| `__audit_pii_fields__` | `frozenset` | `frozenset()` | Columns hashed before storage (`[REDACTED-<sha256[:16]>]`) |

### Methods

#### `anonymize(session, entity_id) -> int`

GDPR right-to-erasure. Replaces PII field values in all audit rows for the given entity with `[REDACTED-<sha256[:16]>]`, preserving diff structure.

```python
@classmethod
def anonymize(cls, session: Session, entity_id: Any) -> int: ...
```

**Parameters:**
- `session` — SQLAlchemy `Session`
- `entity_id` — Primary key of the entity to anonymise

**Returns:** Number of audit rows updated.

### Example

```python
from pgappforge.plugins.audit import AuditMixin
from pgappforge import Model

class Patient(AuditMixin, Model):
    __tablename__ = "patients"
    __audit_pii_fields__ = frozenset({"date_of_birth", "ssn", "phone"})

# GDPR erasure
count = Patient.anonymize(db.session, entity_id=42)
```

---

## `register_field_type`

**`pgappforge.plugins.forms.register_field_type(spec)`**

Register a custom field type in the Form Builder palette. Thread-safe and idempotent (last registration wins for a given `type` key).

### Signature

```python
def register_field_type(spec: FieldTypeSpec | dict) -> None: ...
```

### Parameters

| Parameter | Type | Description |
|---|---|---|
| `spec` | `FieldTypeSpec \| dict` | Field type specification. If a `dict` is passed, it is converted via `FieldTypeSpec(**spec)`. |

### Example

```python
from pgappforge.plugins.forms import register_field_type, FieldTypeSpec

register_field_type(FieldTypeSpec(
    type="icd10_picker",
    label="ICD-10 Code",
    group="MEDICAL",
    icon="&#128138;",
    description="Search and select an ICD-10 diagnosis code",
    config_schema={
        "context": {
            "type": "select",
            "label": "Code context",
            "options": ["diagnosis", "procedure", "symptom"],
            "default": "diagnosis",
        },
    },
))
```

---

## `FieldTypeSpec`

**`pgappforge.plugins.forms.FieldTypeSpec`**

Specification for a custom (or built-in) Form Builder field type.

### Signature

```python
class FieldTypeSpec:
    def __init__(
        self,
        *,
        type: str,
        label: str,
        group: str,
        icon: str = "&#10022;",
        config_schema: dict[str, Any] | None = None,
        renderer: str | None = None,
        description: str = "",
    ) -> None: ...
```

### Parameters

| Parameter | Type | Description |
|---|---|---|
| `type` | `str` | Unique snake\_case identifier, e.g. `"icd10_picker"`. Must be alphanumeric + underscores. |
| `label` | `str` | Display name shown in the palette chip. |
| `group` | `str` | Palette group header (e.g. `"MEDICAL"`). Created if it does not exist. |
| `icon` | `str` | HTML entity or short text used as the chip icon. |
| `config_schema` | `dict \| None` | Extra config inputs rendered in the field config panel. Keys become `field.extra_config` entries. Each entry has: `type` (text/number/boolean/select/textarea), `label`, `default`, and optionally `options` (for `select`). |
| `renderer` | `str \| None` | Optional HTML template fragment for public form rendering. Receives: `id`, `label`, `placeholder`, `required`, `value`, `extra_config`. Defaults to a styled text input. |
| `description` | `str` | Tooltip shown on palette chip hover. |

### Raises

`ValueError` if `type` contains characters other than alphanumerics and underscores.

---

## `auto_discover_widgets`

**`pgappforge.plugins.forms.registry.auto_discover_widgets()`**

Scan installed packages for the `pgappforge.widgets` entry point group and register any `FieldTypeSpec` instances they export.

### Signature

```python
def auto_discover_widgets() -> int: ...
```

### Returns

Number of widget types discovered and registered.

### Example

```python
from pgappforge.plugins.forms.registry import auto_discover_widgets

count = auto_discover_widgets()
print(f"Discovered {count} widget types")
```

Called automatically by `FormsPlugin.initialize()` at startup.

---

## `realtime_model`

**`pgappforge.plugins.realtime.realtime_model(broadcast_fields=None)`**

Class decorator that enables real-time broadcasting for a SQLAlchemy model. Registers an `after_commit` session listener that calls `push_update()` for every modified instance of the decorated class.

### Signature

```python
def realtime_model(broadcast_fields: list[str] | None = None): ...
```

### Parameters

| Parameter | Type | Description |
|---|---|---|
| `broadcast_fields` | `list[str] \| None` | If set, only these field names are included in the broadcast payload. `None` broadcasts all changed fields. |

### Example

```python
from pgappforge.plugins.realtime import realtime_model
from pgappforge import Model

@realtime_model(broadcast_fields=["status", "assigned_to"])
class Ticket(Model):
    __tablename__ = "tickets"
    ...
```

---

## `push_update`

**`pgappforge.plugins.realtime.push_update(instance, changed_fields=None)`**

Broadcast a model change via `pg_notify`. Issues `SELECT pg_notify('pgaf_changes', :payload)` on a short-lived autocommit connection. Safe to call outside an active transaction.

### Signature

```python
def push_update(
    instance: Any,
    changed_fields: list[str] | None = None,
) -> None: ...
```

### Parameters

| Parameter | Type | Description |
|---|---|---|
| `instance` | SQLAlchemy model instance | The changed object. |
| `changed_fields` | `list[str] \| None` | Field names included in the payload. `None` broadcasts all fields on the instance. |

### Example

```python
from pgappforge.plugins.realtime import push_update

ticket.status = "closed"
db.session.commit()
push_update(ticket, changed_fields=["status"])
```

---

## `TemplateRegistry.list`

**`pgappforge.templates.TemplateRegistry.list() -> list[dict]`**

Return metadata for all available templates, sorted by name. Scans bundled, user-installed, and project-local directories on first call (cached thereafter).

### Returns

List of dicts, each containing:

| Key | Type | Description |
|---|---|---|
| `name` | `str` | Template identifier |
| `schema` | `str` | Default PostgreSQL schema name |
| `label` | `str` | Human-readable display name |
| `description` | `str` | Short description |
| `version` | `str` | Template version string |
| `table_count` | `int` | Number of tables defined |
| `tags` | `list[str]` | Classification tags |
| `source` | `str` | `"bundled"` or `"user"` |

### Example

```python
from pgappforge.templates import TemplateRegistry

registry = TemplateRegistry()
for t in registry.list():
    print(t["name"], t["table_count"], "tables", t["tags"])
```

---

## `TemplateRegistry.get`

**`pgappforge.templates.TemplateRegistry.get(name) -> dict`**

Return the full template definition for the given name.

### Signature

```python
def get(self, name: str) -> dict[str, Any]: ...
```

### Parameters

| Parameter | Type | Description |
|---|---|---|
| `name` | `str` | Template name, e.g. `"fhir-r4"` |

### Returns

Full template dict including `tables`, `tags`, `actor`/`actors`, `extensions`, etc.

### Raises

`TemplateNotFoundError` if the template does not exist. The error message lists all available names.

### Example

```python
fhir = registry.get("fhir-r4")
print(list(fhir["tables"].keys()))
# ['patient', 'encounter', 'observation', ...]
```

---

## `TemplateRegistry.install_from_file`

**`pgappforge.templates.TemplateRegistry.install_from_file(path) -> str`**

Install a template from a local JSON file into the user templates directory (`~/.pgappforge/templates/`).

### Signature

```python
def install_from_file(self, path: str | Path) -> str: ...
```

### Parameters

| Parameter | Type | Description |
|---|---|---|
| `path` | `str \| Path` | Path to the template JSON file |

### Returns

The template `name` string.

### Raises

- `FileNotFoundError` if the file does not exist.
- `json.JSONDecodeError` if the file is not valid JSON.

### Example

```python
name = registry.install_from_file("/tmp/my-template.json")
print(f"Installed: {name}")
```

---

## Plugin Initialisation Pattern

All five plugins (`AuditPlugin`, `DataHubPlugin`, `FormsPlugin`, `RealtimePlugin`, `IntegrationHubPlugin`) follow the same two-step initialisation pattern:

```python
from pgappforge.plugins.audit import AuditPlugin
from pgappforge.plugins.forms import FormsPlugin
from pgappforge.plugins.realtime import RealtimePlugin
from pgappforge.plugins.integrations import IntegrationHubPlugin

def create_app():
    app = Flask(__name__)
    db = SQLA(app)
    appbuilder = AppBuilder(app, db.session)

    for plugin_cls in [AuditPlugin, FormsPlugin, RealtimePlugin, IntegrationHubPlugin]:
        plugin = plugin_cls()
        plugin.initialize(app, appbuilder)   # wires listeners / config
        plugin.register_views(appbuilder)    # adds views to the menu

    return app
```

`initialize(app, appbuilder)` is always called first. `register_views(appbuilder)` can be called later (e.g. after all models are imported) if view registration order matters.
