# FAQ

[Home](Home) > FAQ

---

### 1. Why PostgreSQL only?

pgappforge targets PostgreSQL exclusively to leverage features unavailable in generic SQL: `pg_notify` for real-time broadcasts, `jsonb` for flexible metadata, row-level security for multi-tenancy, `information_schema` + `pg_catalog` for deep introspection, and native UUID generation. Supporting multiple databases would require constant lowest-common-denominator compromises that undermine the framework's value proposition. If you need SQLite or MySQL, flask-appbuilder (the upstream project) supports them.

---

### 2. Can I use it with an existing database?

Yes. The generators introspect whatever schema is already in the database. Run `flask forge gen all --uri postgresql://...` against your existing database and you get a working application immediately. No schema migration required to get started — you can layer pgappforge on top of any existing PostgreSQL database.

---

### 3. How does it differ from flask-appbuilder?

pgappforge is a PostgreSQL-native fork of flask-appbuilder (FAB) with: a code generator that produces FAB-compatible code from introspection, visual designers (ERD, Security), five production-grade plugins, 62 schema templates, and the actor pattern. The base CRUD views, security system, and REST API generation are inherited from FAB and extended. If your app already uses FAB, migration is additive — pgappforge is a drop-in superset.

---

### 4. How do I add authentication?

Set `AUTH_TYPE` in your config. Options:

```python
from pgappforge.const import AUTH_DB, AUTH_LDAP, AUTH_OAUTH, AUTH_OID, AUTH_REMOTE_USER

AUTH_TYPE = AUTH_DB        # database username/password (default)
AUTH_TYPE = AUTH_LDAP      # LDAP / Active Directory
AUTH_TYPE = AUTH_OAUTH     # OAuth 2.0 (Google, GitHub, Azure, etc.)
AUTH_TYPE = AUTH_OID       # OpenID Connect
AUTH_TYPE = AUTH_REMOTE_USER  # trust a header set by a reverse proxy
```

For OAuth, also set `OAUTH_PROVIDERS` with provider credentials. For LDAP, set `AUTH_LDAP_SERVER`. See the [Configuration Reference](../api/configuration.md) for full details.

---

### 5. Can I customise generated code?

Yes. Generated files are plain Python — edit them directly. Re-running the generator will warn before overwriting existing files and will ask for confirmation. A common pattern is to generate once into a `generated/` directory, copy the files you want to keep into your main package, and customise from there.

---

### 6. How do templates differ from code generation?

Templates define **what schema to create** (tables, columns, relationships). Code generation produces **application code** (models, views, APIs) from an existing schema. The typical workflow is: apply a template (`flask forge templates apply`) → run the generator (`flask forge gen all`) → customise the output.

---

### 7. What's the Form Builder registration API?

```python
from pgappforge.plugins.forms import register_field_type, FieldTypeSpec

register_field_type(FieldTypeSpec(
    type="my_widget",   # unique snake_case key
    label="My Widget",
    group="CUSTOM",
    icon="&#9733;",
    config_schema={...},  # extra config inputs shown in the field panel
))
```

See [Plugin: Form Builder](Plugin-Form-Builder) and the [Python API Reference](../api/python.md) for full `FieldTypeSpec` parameter documentation.

---

### 8. How do I add a custom widget to the Form Builder palette?

Two steps:

1. Call `register_field_type(FieldTypeSpec(...))` at app startup (or in a `pgappforge.widgets` entry point for auto-discovery).
2. Optionally provide a `renderer` string (HTML template fragment) to control public-form rendering. Without a renderer, the widget falls back to a styled text input.

The widget appears in the palette immediately under the specified `group`. No restart needed if you call `register_field_type` before the first request.

---

### 9. Is multi-tenancy supported?

Yes via `RLSMixin` (row-level security). Attach it to any model to enforce per-tenant data isolation using PostgreSQL RLS policies. Tenant context is set per-request from the authenticated user's tenant assignment. See `pgappforge/mixins/rls_mixin.py` and the multi-tenant setup guide at `docs/MULTI_TENANT_SETUP_GUIDE.md`.

---

### 10. How do I run it in production?

- Use gunicorn (or uvicorn for async): `gunicorn -w 4 "app:create_app()"`.
- Set `SECRET_KEY` from an environment variable — never hardcode it.
- Set `SQLALCHEMY_DATABASE_URI` from an environment variable.
- Use a connection pool (the default SQLAlchemy pool is fine; tune `pool_size` and `max_overflow` for your workload).
- Put pgappforge behind nginx or a CDN for static assets.
- If using the Realtime plugin with multiple workers, configure a Redis `broker_url`.
- Review `docs/SECURITY_DEPLOYMENT_GUIDE.md` before exposing to the internet.

---

### 11. What's the actor pattern?

The actor pattern names the primary domain entity in a template — the thing every other table relates to (patient, employee, customer, contact). Declaring an actor unlocks human-readable view labels, sub-role filtered views, and automatic `ActorMixin` annotation in generated models. See [Actor Pattern](Actor-Pattern).

---

### 12. How do I report a security issue?

Do not open a public GitHub issue for security vulnerabilities. Email **nyimbi+pgaf@gmail.com** with subject `[SECURITY] pgappforge`. Include: affected version, steps to reproduce, and your assessment of impact. You will receive an acknowledgement within 48 hours. See `docs/SECRET_KEY_SECURITY_GUIDE.md` and `docs/SECURITY_DEPLOYMENT_GUIDE.md` for hardening guidance.

---

## See also

- [Installation](Installation)
- [Quick Start](Quick-Start)
- [Architecture](Architecture)
- [Configuration Reference](../api/configuration.md)
- [Python API Reference](../api/python.md)
