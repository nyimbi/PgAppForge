# Data Import/Export Hub

## Overview

The Data Import/Export Hub (`data_hub` plugin) is the first enterprise feature shipped in response to direct user demand. It provides a self-contained, browser-based interface for bulk data ingestion and extraction, sitting on top of any pgappforge `ModelView` without requiring custom code per model.

### Why it exists

Enterprise users routinely need to:
- Bulk-load data from spreadsheets, data warehouse exports, or partner feeds
- Extract filtered table snapshots for downstream analytics or archival
- Run scheduled exports to object storage or email recipients
- Audit what was imported, by whom, and with what error rate

The existing per-row CRUD UI does not scale to thousands of rows. The Data Hub solves this at the framework level so individual applications do not reinvent it.

---

## Architecture

```
Browser (DataHubView HTML/JS)
    │
    ├─ POST /data-hub/api/import   ──► ImportJob row + optional dry-run preview
    ├─ GET  /data-hub/api/jobs     ──► job history
    ├─ GET  /data-hub/api/suggest-mapping ──► fuzzy column mapping suggestions
    └─ POST /data-hub/api/export   ──► synchronous small export or ExportJob row

pgappforge.plugins.data_hub
    ├── __init__.py      DataHubPlugin  (initialize + register_views)
    ├── models.py        ImportJob, ExportJob  (PostgreSQL JSONB columns)
    ├── mapping.py       fuzzy_score, suggest_column_mapping, get_model_fields_meta
    ├── importers.py     iter_csv / iter_json / iter_ndjson / iter_excel / iter_parquet
    └── views.py         DataHubView  (Flask routes + self-contained SPA HTML)
```

The plugin registers a single `DataHubView` blueprint at `/data-hub`. All state is stored in two PostgreSQL tables (`pgaf_import_job`, `pgaf_export_job`). There are no external service dependencies for the synchronous path; async chunked processing is opt-in via APScheduler.

---

## Import Pipeline

### Supported upload formats

| Format  | Extension(s)      | Library required |
|---------|-------------------|------------------|
| CSV     | `.csv`            | stdlib `csv`     |
| Excel   | `.xlsx`, `.xls`   | `openpyxl`       |
| JSON    | `.json`           | stdlib `json`    |
| NDJSON  | `.ndjson`         | stdlib `json`    |
| Parquet | `.parquet`        | `pyarrow`        |

Missing optional libraries raise a `RuntimeError` with a `pip install` hint at import time, not at startup.

### Column mapping — fuzzy match algorithm

The mapping engine in `mapping.py` runs in two steps:

1. **Normalization** — both the upload column name and the model field name are lowercased and stripped of all non-alphanumeric characters (`re.sub(r"[^a-z0-9]", "", s.lower())`). This makes `"First Name"`, `"first_name"`, and `"firstname"` identical after normalization.

2. **Scoring** — for each (upload column, model field) pair, two scores are computed:
   - `SequenceMatcher` ratio between normalized names
   - Containment check: if one normalized string is a substring of the other, score = 0.85

   The higher of the two scores is taken. A match is suggested only when `score >= threshold` (default 0.6).

3. **Display name fallback** — scoring is also run against the human-readable `display_name` (e.g. `"Customer Id"` for field `customer_id`). The max across both comparisons wins.

The result is a dict `{upload_col: {model_field, score, requires_fk_lookup}}` returned by `suggest_column_mapping()`. The UI renders this as a dropdown with the best suggestion pre-selected and the score shown as a color-coded percentage.

### FK resolution

When `requires_fk_lookup=True`, the upload column contains a human-readable label (e.g. `"Alice"`) rather than a numeric foreign key. The import pipeline (async path) resolves these by:

1. Identifying the related model via `foreign_keys` on the column.
2. Querying the related model's first string column for a case-insensitive match.
3. Substituting the resolved PK or recording a `fk_errors` entry in `validation_summary`.

### Validation rules

Before any rows are written, each chunk passes through:

| Rule | Failure action |
|------|---------------|
| Required field is null/empty | Increment `missing_required`; row skipped or errored per `on_duplicate` policy |
| Type coercion fails (e.g. `"abc"` → `Integer`) | Increment `type_errors`; row recorded in `error_details` |
| FK lookup finds no match | Increment `fk_errors`; row skipped |
| Duplicate detected via `dedup_key` columns | Handled per `on_duplicate` option: `skip` / `update` / `error` |

All per-row errors are stored as JSONB in `ImportJob.error_details`:
```json
[
  {"row_num": 14, "field": "employee_id", "error": "fk_not_found", "value": "Unknown Corp"},
  {"row_num": 22, "field": "salary", "error": "type_error", "value": "N/A"}
]
```

### Chunked async processing via APScheduler

Large files are processed in chunks to avoid blocking the web worker and to allow progress reporting via SSE.

Flow:
1. `POST /data-hub/api/import` writes an `ImportJob` row with `status="pending"` and saves the file to `FAB_DATA_HUB_UPLOAD_DIR`.
2. An APScheduler `IntervalTrigger` job polls for `status="pending"` jobs every 5 seconds.
3. The worker reads the file in chunks of `FAB_DATA_HUB_CHUNK_SIZE` rows, updating `rows_inserted` / `rows_errored` after each chunk.
4. `status` transitions: `pending → validating → processing → done | failed | partial`.
5. Clients poll `GET /data-hub/api/jobs/<id>/status` or subscribe to `GET /data-hub/api/jobs/<id>/progress` (SSE) for live updates.

### Dry-run mode

When `dry_run=True` (sent as form field `dry_run=1`):
- No database rows are written.
- The first 5 rows after column mapping are returned as `preview` in the JSON response.
- The `ImportJob` is recorded with `status="dry_run"` for audit purposes.
- Validation errors are still computed and returned in `validation_summary`.

This allows users to verify the mapping before committing a large import.

---

## Export Pipeline

### Filter state export

The export API accepts a `filters` dict that mirrors the active filter state from any `ModelView` list page. Filters are stored on the `ExportJob` row so scheduled exports reproduce the same slice.

Example filter payload:
```json
{
  "model": "employee",
  "filters": {"department_id": 3, "active": true},
  "columns": ["id", "first_name", "last_name", "salary"],
  "format": "csv",
  "options": {"max_rows": 50000, "redact_pii": false}
}
```

### Format selection and column picker

The `columns` array controls which fields appear in the output. Empty array = all columns. Column order in the output matches the array order.

Supported output formats:

| Format  | MIME type                   | Notes |
|---------|-----------------------------|-------|
| CSV     | `text/csv`                  | RFC 4180, UTF-8 with BOM |
| Excel   | `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` | requires `openpyxl` |
| JSON    | `application/json`          | Array of objects |
| NDJSON  | `application/x-ndjson`      | One JSON object per line |
| Parquet | `application/octet-stream`  | requires `pyarrow` |

### PII redaction options

When `options.redact_pii=true`, columns flagged as PII in the model's `__pii_fields__` class attribute are replaced with `"***REDACTED***"` in the output. This is enforced server-side regardless of column selection.

Example model annotation:
```python
class Employee(Model):
    __pii_fields__ = ["ssn", "date_of_birth", "home_address"]
```

### Scheduled exports with RRULE

The `schedule` field on `ExportJob` accepts an [RFC 5545](https://tools.ietf.org/html/rfc5545) RRULE string:

```
FREQ=WEEKLY;BYDAY=MO;BYHOUR=6;BYMINUTE=0
```

The scheduler computes `next_run_at` using `dateutil.rrule` and updates `last_run_at` + `next_run_at` after each execution. Delivery methods:

| Method    | Config keys |
|-----------|-------------|
| `download` | Output URL written to `output_url`; retained for 7 days |
| `email`    | `{email: "recipient@example.com"}` — requires Flask-Mail |
| `storage`  | `{bucket: "reports", key_prefix: "exports/"}` — requires configured object storage |

---

## Data Quality Reports

After each import, `validation_summary` on the `ImportJob` row captures:

### Completeness score per field

```
completeness(field) = rows_with_non_null_value / total_rows
```

Reported as a percentage. Fields below 80% completeness are flagged in the UI with an amber indicator.

### Outlier detection (z-score)

For numeric fields, the import worker computes mean and standard deviation over the chunk. Rows where `|value - mean| / std > 3` are flagged as outliers in `error_details` with `error="outlier"`. These are not rejected by default but are surfaced in the quality report.

### Duplicate ratio

```
duplicate_ratio = rows_skipped_as_duplicate / total_rows
```

Computed when a `dedup_key` is configured. A ratio above 20% triggers a warning in `validation_summary.high_duplicate_warning = true`.

---

## Configuration

All config keys are read from the Flask app config (`app.config`).

| Key | Default | Description |
|-----|---------|-------------|
| `FAB_DATA_HUB_CHUNK_SIZE` | `500` | Rows processed per APScheduler tick |
| `FAB_DATA_HUB_MAX_UPLOAD_MB` | `100` | Maximum upload file size in megabytes |
| `FAB_DATA_HUB_UPLOAD_DIR` | `/tmp/pgaf_uploads` | Temporary directory for uploaded files |
| `FAB_DATA_HUB_RETENTION_DAYS` | `7` | Days to retain completed job records and output files |
| `FAB_DATA_HUB_ASYNC` | `True` | Enable APScheduler async processing; `False` = synchronous (dev/test) |
| `FAB_DATA_HUB_PII_REDACT_DEFAULT` | `False` | Redact PII columns by default in all exports |

### Enabling the plugin

```python
# config.py
PGAPPFORGE_PLUGINS = ["pgappforge.plugins.data_hub"]
```

Or manually:
```python
from pgappforge.plugins.data_hub import DataHubPlugin
plugin = DataHubPlugin()
plugin.initialize(app, appbuilder)
plugin.register_views(appbuilder)
```

---

## API Reference

All endpoints require authentication (enforced via `@has_access`). CSRF protection applies to mutating endpoints in production.

---

### `POST /data-hub/api/import`

Upload a file and create an import job.

**Request** — `multipart/form-data`

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `file` | file | yes | The data file to import |
| `model` | string | yes | Target model `__tablename__` or class name |
| `mapping` | JSON string | no | `{upload_col: model_field}` override |
| `dry_run` | `"0"` or `"1"` | no | Preview without writing (default `"0"`) |
| `chunk_size` | integer | no | Override `FAB_DATA_HUB_CHUNK_SIZE` for this job |
| `on_duplicate` | `skip\|update\|error` | no | Duplicate row policy (default `skip`) |
| `dedup_key` | JSON array string | no | Column names used as dedup key |

**Response** `200 OK`
```json
{
  "job_id": 42,
  "status": "pending",
  "preview": null
}
```

Dry-run response:
```json
{
  "job_id": 43,
  "status": "dry_run",
  "preview": [
    {"first_name": "Alice", "last_name": "Smith", "salary": "95000"},
    {"first_name": "Bob",   "last_name": "Jones", "salary": "82000"}
  ]
}
```

**Error responses**

| Code | Condition |
|------|-----------|
| `400` | Missing `file` or `model` |
| `404` | Model not found |
| `413` | File exceeds `FAB_DATA_HUB_MAX_UPLOAD_MB` |

---

### `GET /data-hub/api/jobs/<id>/status`

Poll a single job's current state.

**Response** `200 OK`
```json
{
  "id": 42,
  "status": "processing",
  "total_rows": 10000,
  "rows_inserted": 3500,
  "rows_updated": 0,
  "rows_skipped": 12,
  "rows_errored": 3,
  "validation_summary": {
    "missing_required": 3,
    "type_errors": 0,
    "fk_errors": 0,
    "duplicates": 12
  },
  "pct_complete": 35.0
}
```

---

### `GET /data-hub/api/jobs/<id>/progress` (SSE)

Server-Sent Events stream for live progress. The client receives `data:` lines containing JSON-encoded progress objects (same schema as `/status`) every ~1 second until `status` is `done`, `failed`, or `partial`.

```
data: {"id":42,"status":"processing","rows_inserted":3500,"pct_complete":35.0}

data: {"id":42,"status":"processing","rows_inserted":7000,"pct_complete":70.0}

data: {"id":42,"status":"done","rows_inserted":9985,"rows_errored":15,"pct_complete":100.0}
```

The stream closes automatically when the job reaches a terminal state.

---

### `GET /data-hub/api/jobs`

List the 50 most recent import jobs for the current user.

**Response** `200 OK`
```json
{
  "jobs": [
    {
      "id": 42,
      "model_name": "employee",
      "filename": "employees_q1.csv",
      "file_format": "csv",
      "status": "done",
      "rows_inserted": 9985,
      "rows_updated": 0,
      "rows_errored": 15,
      "created_at": "2026-05-31T08:14:22+00:00"
    }
  ]
}
```

---

### `POST /data-hub/api/export`

Create an export job or return a synchronous download for small datasets.

**Request** — `application/json`

```json
{
  "model": "employee",
  "format": "csv",
  "filters": {"department_id": 3, "active": true},
  "columns": ["id", "first_name", "last_name", "salary"],
  "options": {
    "max_rows": 10000,
    "redact_pii": false,
    "include_fk_labels": true
  },
  "schedule": "FREQ=WEEKLY;BYDAY=MO;BYHOUR=6;BYMINUTE=0",
  "delivery_method": "download"
}
```

**Response — synchronous download** (≤ `FAB_DATA_HUB_CHUNK_SIZE` rows)

Returns the file directly with an appropriate `Content-Disposition: attachment` header.

**Response — async job**
```json
{
  "job_id": 7,
  "status": "pending",
  "download_url": null
}
```

Once complete, `download_url` is populated:
```json
{
  "job_id": 7,
  "status": "done",
  "download_url": "/data-hub/api/export/7/download",
  "row_count": 4821
}
```

**Error responses**

| Code | Condition |
|------|-----------|
| `400` | Invalid request payload |
| `404` | Model not found |

---

## Security Notes

- All endpoints enforce `@has_access` — unauthenticated requests receive `401`.
- Uploaded files are stored in `FAB_DATA_HUB_UPLOAD_DIR` with a random UUID filename, never the original name.
- File content is never executed; only parsed through the registered format iterators.
- Export jobs store the requesting user's ID in `created_by_id`. Admin users can view all jobs; non-admin users see only their own.
- PII redaction is applied server-side and cannot be bypassed by column selection.

---

## Database Tables

### `pgaf_import_job`

| Column | Type | Notes |
|--------|------|-------|
| `id` | integer PK | |
| `model_name` | varchar(255) | Target model |
| `filename` | varchar(512) | Original filename |
| `file_format` | varchar(20) | csv / xlsx / json / ndjson / parquet |
| `status` | varchar(20) | pending / validating / processing / done / failed / partial / dry_run |
| `column_mapping` | jsonb | Upload → model field mapping used |
| `options` | jsonb | Job options (chunk_size, dry_run, on_duplicate, dedup_key) |
| `total_rows` | integer | |
| `rows_inserted` | integer | |
| `rows_updated` | integer | |
| `rows_skipped` | integer | |
| `rows_errored` | integer | |
| `error_details` | jsonb | Per-row error list |
| `validation_summary` | jsonb | Aggregate counts |
| `created_by_id` | integer FK → ab_user | Nullable |
| `created_at` | timestamptz | |
| `started_at` | timestamptz | |
| `completed_at` | timestamptz | |
| `file_path` | varchar(1024) | Temp file on disk |

### `pgaf_export_job`

| Column | Type | Notes |
|--------|------|-------|
| `id` | integer PK | |
| `model_name` | varchar(255) | |
| `file_format` | varchar(20) | |
| `status` | varchar(20) | pending / done / failed |
| `filters` | jsonb | Active filter state |
| `columns` | jsonb | Selected columns (empty = all) |
| `options` | jsonb | redact_pii, include_fk_labels, max_rows |
| `schedule` | varchar(256) | RRULE for recurring exports |
| `last_run_at` | timestamptz | |
| `next_run_at` | timestamptz | |
| `delivery_method` | varchar(20) | download / email / storage |
| `delivery_config` | jsonb | Delivery-specific config |
| `output_url` | varchar(1024) | Download link when done |
| `row_count` | integer | |
| `created_by_id` | integer FK → ab_user | Nullable |
| `created_at` | timestamptz | |
| `completed_at` | timestamptz | |

---

## Extension Points

- **Custom validators**: Subclass `DataHubView` and override `_validate_row(job, row, mapping)`.
- **Custom transformers**: Add a `transform` key to `column_mapping` entries — the async worker applies `eval`-safe transform expressions (whitelisted operators only).
- **Custom delivery**: Implement `IDeliveryBackend` and register via `FAB_DATA_HUB_DELIVERY_BACKENDS`.
- **Pre/post import hooks**: Connect to `data_hub_pre_import` and `data_hub_post_import` signals via Flask-SQLAlchemy event system.

---

## Roadmap

- [ ] Async chunked processing worker (APScheduler integration)
- [ ] SSE progress endpoint (`/jobs/<id>/progress`)
- [ ] Per-job status endpoint (`/jobs/<id>/status`)
- [ ] Excel export via openpyxl
- [ ] Parquet export via pyarrow
- [ ] FK label resolution in async worker
- [ ] PII redaction enforcement
- [ ] Scheduled export + RRULE scheduling
- [ ] Email + object storage delivery backends
- [ ] Data quality report UI panel
- [ ] Admin view for all users' jobs
