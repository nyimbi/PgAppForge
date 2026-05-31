# Data Import/Export Hub

The Data Hub plugin provides a self-contained, browser-based interface for bulk data ingestion and extraction that sits on top of any pgappforge `ModelView` without per-model custom code. It handles CSV, Excel, JSON, NDJSON, and Parquet upload with fuzzy column mapping, FK resolution, validation, and chunked async processing — plus a symmetric export pipeline with scheduled delivery and PII redaction.

All state is persisted to two PostgreSQL tables (`pgaf_import_job`, `pgaf_export_job`) using JSONB columns. There are no required external service dependencies for the synchronous path; async chunked processing is opt-in via APScheduler.

## Quick Start

```python
from pgappforge.plugins.data_hub import DataHubPlugin

def create_app():
    app = Flask(__name__)
    appbuilder = AppBuilder(app, db.session)

    plugin = DataHubPlugin()
    plugin.initialize(app, appbuilder)
    plugin.register_views(appbuilder)   # mounts /data-hub/ under "Tools" menu

    return app
```

Or via config:

```python
# config.py
PGAPPFORGE_PLUGINS = ["pgappforge.plugins.data_hub"]
```

Then run migrations to create the job tables:

```bash
flask db upgrade
```

## Configuration Options

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `FAB_DATA_HUB_CHUNK_SIZE` | `int` | `500` | Rows processed per APScheduler tick |
| `FAB_DATA_HUB_MAX_UPLOAD_MB` | `int` | `100` | Maximum upload file size in megabytes |
| `FAB_DATA_HUB_UPLOAD_DIR` | `str` | `/tmp/pgaf_uploads` | Temporary directory for uploaded files |
| `FAB_DATA_HUB_RETENTION_DAYS` | `int` | `7` | Days to retain completed job records and output files |
| `FAB_DATA_HUB_ASYNC` | `bool` | `True` | Enable APScheduler async processing; `False` = synchronous (dev/test) |
| `FAB_DATA_HUB_PII_REDACT_DEFAULT` | `bool` | `False` | Redact PII columns by default in all exports |

Optional library dependencies — missing libraries raise a `RuntimeError` with a `pip install` hint at call time, not at startup:

| Format | Extra required |
|--------|---------------|
| Excel (`.xlsx`, `.xls`) | `openpyxl` |
| Parquet (`.parquet`) | `pyarrow` |

## Key API / Endpoints

All endpoints enforce `@has_access`. CSRF protection applies to mutating endpoints.

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/data-hub/` | Import/export UI |
| `POST` | `/data-hub/api/import` | Upload file and create import job (`multipart/form-data`) |
| `GET` | `/data-hub/api/jobs` | List the 50 most recent import jobs for the current user |
| `GET` | `/data-hub/api/jobs/<id>/status` | Poll a single job's current state and validation summary |
| `GET` | `/data-hub/api/jobs/<id>/progress` | SSE stream of live progress until job reaches terminal state |
| `GET` | `/data-hub/api/suggest-mapping` | Fuzzy column mapping suggestions for an uploaded file header |
| `POST` | `/data-hub/api/export` | Create an export job or return a synchronous download for small datasets |

### Import request fields (`multipart/form-data`)

| Field | Required | Description |
|-------|----------|-------------|
| `file` | yes | Data file (CSV / XLSX / JSON / NDJSON / Parquet) |
| `model` | yes | Target model `__tablename__` or class name |
| `mapping` | no | JSON string `{upload_col: model_field}` — overrides fuzzy auto-mapping |
| `dry_run` | no | `"1"` to preview without writing (returns first 5 rows) |
| `on_duplicate` | no | `skip` / `update` / `error` (default `skip`) |
| `dedup_key` | no | JSON array of column names used as duplicate key |

### Export request body (`application/json`)

```json
{
  "model": "employee",
  "format": "csv",
  "filters": {"department_id": 3, "active": true},
  "columns": ["id", "first_name", "last_name", "salary"],
  "options": {"max_rows": 50000, "redact_pii": false},
  "schedule": "FREQ=WEEKLY;BYDAY=MO;BYHOUR=6;BYMINUTE=0",
  "delivery_method": "download"
}
```

`schedule` accepts an RFC 5545 RRULE string. `delivery_method` is one of `download`, `email` (requires Flask-Mail), or `storage` (requires configured object storage).

## Example Usage

```python
# --- Dry-run preview before committing a large import ---
# POST /data-hub/api/import
# form fields: file=employees.csv, model=employee, dry_run=1
# Response:
# {
#   "job_id": 43,
#   "status": "dry_run",
#   "preview": [
#     {"first_name": "Alice", "last_name": "Smith", "salary": "95000"},
#     ...
#   ]
# }

# --- Live progress via SSE ---
# GET /data-hub/api/jobs/43/progress
# data: {"id":43,"status":"processing","rows_inserted":3500,"pct_complete":35.0}
# data: {"id":43,"status":"done","rows_inserted":9985,"rows_errored":15,"pct_complete":100.0}

# --- Annotate a model for PII redaction in exports ---
class Employee(Model):
    __tablename__ = "employees"
    __pii_fields__ = ["ssn", "date_of_birth", "home_address"]
    ...

# --- Custom validator hook ---
from pgappforge.plugins.data_hub.views import DataHubView

class MyDataHubView(DataHubView):
    def _validate_row(self, job, row, mapping):
        if row.get("salary", 0) < 0:
            return {"error": "negative_salary", "value": row["salary"]}
        return None
```

Import job status values: `pending` → `validating` → `processing` → `done | failed | partial`. Dry-run jobs record as `dry_run` and never write rows.

Validation errors are accumulated per-row in `ImportJob.error_details` as JSONB. The quality report on each job includes per-field completeness scores (flagged below 80%), numeric outliers (z-score > 3), and duplicate ratio (warned above 20%).

## See Also

- [Audit plugin](audit.md) — audit trail for imported records; import jobs are themselves auditable via the ORM
- [Integrations plugin](integrations.md) — scheduled pulls from external systems, complementing the manual upload flow here
- pgappforge SPEC: `pgappforge/plugins/data_hub/SPEC.md`
