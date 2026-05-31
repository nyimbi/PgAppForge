# Configuration Reference

All configuration is set in a Flask `config.py` (or equivalent). Keys are uppercase strings read from `app.config`.

---

## Core

| Key | Type | Default | Description |
|---|---|---|---|
| `SECRET_KEY` | `str` | — | **Required.** Flask session signing key. Minimum 20 characters; use `secrets.token_hex(32)` to generate. |
| `SQLALCHEMY_DATABASE_URI` | `str` | — | **Required.** PostgreSQL connection URI. Only `postgresql://` (and `postgresql+psycopg2://`, `postgresql+asyncpg://`) are accepted. |
| `APP_NAME` | `str` | `"F.A.B."` | Application display name shown in the navbar and title bar. |
| `APP_THEME` | `str` | `"cerulean"` | Bootstrap theme name. Options include `cerulean`, `cosmo`, `flatly`, `lumen`, `slate`, etc. |
| `FAB_UPDATE_PERMS` | `bool` | `True` | Auto-sync role/permission records on startup. Set `False` to skip in high-frequency restarts. |
| `FAB_SECURITY_MANAGER_CLASS` | `str` | `None` | Dotted import path to a custom security manager class. |
| `ADDON_MANAGERS` | `list[str]` | `[]` | List of dotted import paths for addon manager classes to load at startup. |

---

## Authentication

| Key | Type | Default | Description |
|---|---|---|---|
| `AUTH_TYPE` | `int` | `1` (`AUTH_DB`) | Authentication backend. Constants: `AUTH_DB=1`, `AUTH_LDAP=2`, `AUTH_OID=3`, `AUTH_OAUTH=4`, `AUTH_REMOTE_USER=5`. Import from `pgappforge.const`. |
| `AUTH_ROLE_ADMIN` | `str` | `"Admin"` | Name of the administrator role. |
| `AUTH_ROLE_PUBLIC` | `str` | `"Public"` | Name of the role granted to unauthenticated users. |
| `AUTH_USER_REGISTRATION` | `bool` | `False` | Allow users to self-register. |
| `AUTH_USER_REGISTRATION_ROLE` | `str` | `None` | Role assigned to self-registered users. |
| `AUTH_USER_REGISTRATION_ROLE_JMESPATH` | `str` | `None` | JMESPath expression evaluated against OAuth/OIDC token claims to determine the registration role. |
| `AUTH_ROLES_MAPPING` | `dict` | `{}` | Map OAuth/LDAP group names to pgappforge role names: `{"ldap_group": "Admin"}`. |
| `AUTH_ROLES_SYNC_AT_LOGIN` | `bool` | `False` | Re-sync role mappings on every login (not only on first registration). |
| `WTF_CSRF_ENABLED` | `bool` | `True` | Enable CSRF protection on all forms and JSON POST endpoints. |
| `WTF_CSRF_TIME_LIMIT` | `int` | `3600` | CSRF token expiry in seconds. |

---

## Plugins

### Audit Trail

| Key | Type | Default | Description |
|---|---|---|---|
| `FAB_AUDIT_PII_FIELDS` | `set[str]` | `set()` | Global fallback PII field names. Per-model `__audit_pii_fields__` takes precedence. |
| `FAB_AUDIT_RETENTION_DAYS` | `int \| None` | `None` | Purge audit rows older than this many days. `None` disables purging. |

### Business Rules / Webhooks

| Key | Type | Default | Description |
|---|---|---|---|
| `FAB_RULES_WEBHOOK_ALLOWLIST` | `list[str]` | `[]` | Allowed URL prefixes for outbound webhook targets. Empty list blocks all outbound webhooks. |

### Realtime

| Key | Type | Default | Description |
|---|---|---|---|
| `FAB_REALTIME_HEARTBEAT_INTERVAL` | `int` | `15` | Seconds between client presence-ping emissions. |
| `FAB_REALTIME_LOCK_TIMEOUT` | `int` | `5` | Seconds before an idle record lock is released automatically. |
| `FAB_REALTIME_MAX_CONNECTIONS` | `int` | `1000` | Maximum concurrent Socket.IO connections per worker process. |

### Data Hub

| Key | Type | Default | Description |
|---|---|---|---|
| `FAB_DATA_HUB_CHUNK_SIZE` | `int` | `500` | Rows per database transaction during CSV/Excel import. |
| `FAB_DATA_HUB_MAX_UPLOAD_MB` | `int` | `50` | Maximum upload file size in megabytes. |

### Integration Hub

| Key | Type | Default | Description |
|---|---|---|---|
| `FAB_INTEGRATION_ENCRYPTION_KEY` | `str` | — | **Required when using Integration Hub.** Fernet encryption key for stored OAuth tokens. Generate with `cryptography.fernet.Fernet.generate_key()`. |
| `FAB_INTEGRATION_WEBHOOK_RETRY_MAX` | `int` | `5` | Maximum outbound webhook delivery attempts before marking the delivery as failed. |

### ERD Designer

| Key | Type | Default | Description |
|---|---|---|---|
| `FAB_ERD_DDL_ENABLED` | `bool` | `False` | Enable schema-mutation endpoints (`CREATE TABLE`, `ALTER TABLE`, etc.). Keep `False` on production databases you do not want the designer to touch. |
| `FAB_ERD_DDL_TIMEOUT_MS` | `int` | `30000` | PostgreSQL `SET LOCAL statement_timeout` applied to each DDL batch (milliseconds). Prevents runaway `ALTER TABLE` on large tables. |
| `FAB_CODEGEN_OUTPUT_ROOT` | `str` | `"/tmp/pgaf_generated"` | Root directory for the app-generation endpoint. Paths outside this root are rejected with HTTP 400 (path traversal prevention). |

---

## Minimal Production Config

```python
import os

SECRET_KEY = os.environ["SECRET_KEY"]
SQLALCHEMY_DATABASE_URI = os.environ["DATABASE_URL"]
APP_NAME = "My App"
FAB_UPDATE_PERMS = True
WTF_CSRF_ENABLED = True
FAB_ERD_DDL_ENABLED = False   # only enable deliberately
```
