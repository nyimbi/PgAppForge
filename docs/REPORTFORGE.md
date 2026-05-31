# ReportForge Plugin

ReportForge is the banded report builder for pgappforge. It provides WYSIWYG report design, multiple export formats, email dispatch, scheduling, access control, versioning, and dashboards.

---

## Enabling the plugin

```python
# config.py
PGAPPFORGE_PLUGINS = ["pgappforge.plugins.reports"]
```

Or instantiate directly:

```python
from pgappforge.plugins.reports import create_plugin
plugin = create_plugin(appbuilder)
plugin.activate()
```

---

## Configuration keys

| Key | Default | Description |
|-----|---------|-------------|
| `REPORTS_MENU_CATEGORY` | `"ReportForge"` | FAB menu category for all report views |
| `REPORTS_PREVIEW_ROW_LIMIT` | `10` | Max rows fetched for HTML/wizard preview |
| `REPORTS_DOWNLOAD_ROW_LIMIT` | `None` | Hard cap on rows in PDF/XLSX/CSV downloads (`None` = unlimited) |
| `REPORTFORGE_ACL_ENABLED` | `True` | Set `False` to bypass all ACL checks (single-user installs only) |
| `REPORTFORGE_DB_READONLY_URI` | `None` | SQLAlchemy URI for a read-only PostgreSQL role used by the SQL editor. **Strongly recommended in production.** Example: `postgresql://reportforge_ro:pass@localhost/mydb` |
| `REPORTFORGE_EMAIL_ALLOWLIST` | `[]` | List of email domain suffixes allowed as dispatch recipients, e.g. `["@example.com"]`. Empty list = no restriction. |
| `REPORTFORGE_SQL_SCHEMAS` | `["public"]` | List of PostgreSQL schemas exposed in the SQL editor schema browser. |
| `REPORTFORGE_QUERY_ROW_LIMIT` | `500` | Maximum rows returned by the SQL editor execute endpoint. |
| `REPORTFORGE_CACHE_MAX_BYTES` | `10_485_760` | Maximum rendered report size (bytes) to store in the render cache (10 MB default). Larger renders are served but not cached. |
| `REPORTFORGE_SMTP_HOST` | `"localhost"` | SMTP server hostname for email dispatch. |
| `REPORTFORGE_SMTP_PORT` | `587` | SMTP port. |
| `REPORTFORGE_SMTP_USER` | `""` | SMTP authentication username. |
| `REPORTFORGE_SMTP_PASSWORD` | `""` | SMTP authentication password. |
| `REPORTFORGE_SMTP_TLS` | `True` | Enable STARTTLS on the SMTP connection. |
| `REPORTFORGE_FROM_EMAIL` | `"reports@localhost"` | Sender address for dispatched reports. |
| `REPORTFORGE_FROM_NAME` | `"ReportForge"` | Sender display name. |

---

## Access control

ReportForge uses a six-layer ACL model evaluated in order:

1. `REPORTFORGE_ACL_ENABLED = False` → always allow (for single-user installs)
2. User has the **Admin** role → always allow
3. User is the **report creator** → always allow
4. Report is **public** (`is_public=True`) and permission is view/run/download → allow
5. A **`ReportGrant`** row exists for `(user_id, "user")` with the requested permission → allow
6. A **`ReportGrant`** row exists for any of the user's role IDs with `(role_id, "role")` → allow
7. → deny

### Permissions

| Permission | Allows |
|------------|--------|
| `view` | Access HTML preview |
| `run` | Run report with parameters |
| `download` | Download PDF/DOCX/XLSX/CSV |
| `edit` | Open designer, publish versions, restore |

Permissions are ranked: `edit` > `download` > `run` > `view`. An `edit` grant implies all lower permissions.

### Managing grants via API

```
GET    /reports/acl/<report_id>           — list all grants (JSON)
POST   /reports/acl/<report_id>           — add grant {principal_type, principal_id, permission}
DELETE /reports/acl/<report_id>/<grant_id> — remove grant
```

---

## Share links (view-once / expiring)

Create a time-limited, optionally quota-limited URL that works without login:

```
POST /reports/share/create/<report_id>

Form fields:
  max_uses       — integer or empty (unlimited)
  expires_hours  — integer (default 24)
  <param_name>   — pre-fill report parameters for the recipient

Response: {ok: true, token: "...", url: "/reports/share/<token>"}
```

The recipient visits `/reports/share/<token>` — no login required.  
The share link endpoint is also used by the async render job to deliver results.

**Security:** quota decrements are atomic (`UPDATE … WHERE uses_remaining > 0 RETURNING id`) to prevent race conditions on view-once tokens.

---

## Embedded widget (iframe)

```
GET /reports/embed/<token>
```

Returns stripped HTML (no nav, suitable for `<iframe>`). Use a share token to generate the URL.

---

## Email dispatch

Send a rendered report as an email attachment:

```
POST /reports/dispatch/<report_id>

Form fields:
  to_email   — comma-separated recipients (validated against REPORTFORGE_EMAIL_ALLOWLIST)
  subject    — email subject line
  body_text  — plain text body
  format     — pdf | docx | xlsx | csv (default: pdf)
```

Supported formats and their MIME types:

| Format | MIME type |
|--------|-----------|
| `pdf` | `application/pdf` |
| `docx` | `application/vnd.openxmlformats-officedocument.wordprocessingml.document` |
| `xlsx` | `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` |
| `csv` | `text/csv` |

**Security:** CR/LF characters are stripped from all header fields to prevent email header injection.

---

## Scheduling

### One-shot scheduled dispatch

Set `scheduled_at` on a `ReportDispatch` row and call the scheduler:

```python
from pgappforge.plugins.reports.scheduler import run_all
count = run_all()  # call from Celery beat or cron
```

### Recurring dispatches (RRULE)

Set `recurrence_rule` on a `ReportDispatch` using an RRULE string:

```
FREQ=WEEKLY;BYDAY=MO         — every Monday
FREQ=MONTHLY;BYMONTHDAY=1    — 1st of every month
FREQ=DAILY                   — daily
```

After each successful send, the scheduler computes the next occurrence and re-queues the dispatch automatically. When the rule is exhausted, the dispatch stays in `SENT` state.

### User subscriptions

Users can subscribe to receive a personalised copy of a report:

```
POST /reports/subscribe/<report_id>

Form fields:
  frequency    — RRULE fragment (e.g. FREQ=WEEKLY;BYDAY=MO)
  format       — pdf | xlsx | csv (default: pdf)
  <param_name> — pre-fill report parameters for this subscriber
```

Unsubscribe:
```
POST /reports/unsubscribe/<subscription_id>
```

---

## Background rendering

For large reports that would exceed request timeouts:

```
POST /reports/render-async/<report_id>   — enqueue job, returns {job_id}
GET  /reports/jobs/<job_id>/status       — poll status

Response: {status: "pending|running|done|failed", download_url: "..."}
```

The `download_url` is a 1-use, 15-minute share link valid immediately when `status=done`.

---

## Report versioning

Access from the designer sidebar or directly:

```
GET  /reportforge/reports/<id>/versions                  — version history
POST /reportforge/reports/<id>/versions/publish          — snapshot current state
POST /reportforge/reports/<id>/versions/<v>/restore      — restore to version v
```

**What is versioned:** bands, fields, parameters, branding, data source, page config.  
**What is NOT versioned:** `category_id`, `is_public`, `owner_id`, ACL grants, share tokens, subscriptions, access logs.

Restoring is atomic — the report is never left in a half-restored state (savepoint rollback on failure).

---

## SQL editor

Accessible at `/reportforge/sql-editor/`. For advanced users to build and save queries.

**Security:** Only `SELECT`, `WITH`, and `EXPLAIN` statements are permitted. All other statements are blocked by both a first-token check and a keyword regex. The connection uses `SET LOCAL default_transaction_read_only = on` in addition to the optional read-only role.

Configure a read-only PostgreSQL role for production:

```sql
CREATE ROLE reportforge_readonly WITH LOGIN PASSWORD 'secret';
GRANT CONNECT ON DATABASE mydb TO reportforge_readonly;
GRANT USAGE ON SCHEMA public TO reportforge_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO reportforge_readonly;
```

```python
REPORTFORGE_DB_READONLY_URI = "postgresql://reportforge_readonly:secret@localhost/mydb"
```

---

## Optional dependencies

| Package | Purpose | Install |
|---------|---------|---------|
| `reportlab` | PDF export | `pip install reportlab` |
| `openpyxl` | XLSX export | `pip install openpyxl` |
| `python-docx` | DOCX export | `pip install python-docx` |
| `python-dateutil` | RRULE recurrence | `pip install python-dateutil` |
| `matplotlib` | Chart rendering in PDF | `pip install matplotlib` |

All dependencies are soft — the plugin loads and functions without them; affected features return a clear error message.

---

## Running the scheduler

### Celery beat

```python
from celery import Celery
from celery.schedules import crontab

app = Celery(...)

app.conf.beat_schedule = {
    "reportforge-tick": {
        "task": "myapp.tasks.reportforge_tick",
        "schedule": crontab(minute="*/5"),
    }
}

@app.task
def reportforge_tick():
    from flask import current_app
    with current_app.app_context():
        from pgappforge.plugins.reports.scheduler import run_all
        return run_all()
```

### Flask CLI

Add to your CLI commands:

```python
@app.cli.command("reportforge-run-scheduled")
def cli_run_scheduled():
    from pgappforge.plugins.reports.scheduler import run_all
    count = run_all()
    click.echo(f"Processed {count} items")
```
