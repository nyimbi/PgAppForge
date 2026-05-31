# Plugin: Data Hub

[Home](Home) > Plugin: Data Hub

The Data Hub plugin provides chunked CSV and Excel import/export, transformation pipelines, and progress tracking for any pgappforge model.

---

## Initialisation

```python
from pgappforge.plugins.data_hub import DataHubPlugin

plugin = DataHubPlugin()
plugin.initialize(app, appbuilder)
plugin.register_views(appbuilder)
```

Registers the Data Hub view at `/tools/data-hub/`.

---

## Capabilities

### Import

- Upload CSV or Excel (`.xlsx`) files via the browser UI or REST endpoint.
- Files are processed in configurable chunks (`FAB_DATA_HUB_CHUNK_SIZE`) to avoid memory exhaustion on large uploads.
- Column mapping UI lets users align file headers to model fields before import begins.
- Validation errors are reported per-row with a downloadable error report.

### Export

- Export any model's current data as CSV or Excel.
- Supports column selection, ordering, and basic filter expressions.
- Large exports are streamed in chunks; the browser receives a `Content-Disposition: attachment` response.

### Transformation Pipelines

Register a transformation function that runs on each chunk before insert:

```python
from pgappforge.plugins.data_hub import register_transform

@register_transform("patients")
def clean_patient_row(row: dict) -> dict:
    row["phone"] = row["phone"].replace(" ", "")
    return row
```

---

## Configuration

| Key | Default | Description |
|---|---|---|
| `FAB_DATA_HUB_CHUNK_SIZE` | `500` | Rows processed per database transaction during import |
| `FAB_DATA_HUB_MAX_UPLOAD_MB` | `50` | Maximum upload file size in megabytes |

---

## Further Reading

Full reference: [docs/plugins/data_hub.md](../plugins/data_hub.md)

---

## See also

- [Plugin: Audit Trail](Plugin-Audit-Trail)
- [Plugin: Form Builder](Plugin-Form-Builder)
- [Architecture](Architecture)
- [Configuration Reference](../api/configuration.md)
