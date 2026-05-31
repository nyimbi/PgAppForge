# Visual Form Builder

The Forms plugin provides a drag-and-drop form designer, a JSON-backed definition model, a public HTML renderer, and a REST API for building and deploying data-capture forms without writing Python. It covers the gap that auto-generated CRUD forms cannot fill: multi-step wizard flows, conditional field visibility, public unauthenticated submissions, scoring/assessment modes, and submission funnel analytics.

Form definitions are stored as JSONB in PostgreSQL and versioned on publish into immutable `FormVersion` rows. All rendering is server-side; the public submission endpoint (`/forms/public/<token>`) requires no authentication.

## Quick Start

```python
from pgappforge.plugins.forms import FormsPlugin, register_field_type, FieldTypeSpec

def create_app():
    app = Flask(__name__)
    appbuilder = AppBuilder(app, db.session)

    plugin = FormsPlugin()
    plugin.initialize(app, appbuilder)   # auto-discovers widget library (65 types)
    plugin.register_views(appbuilder)    # mounts /form-builder/ and /forms/public/

    return app
```

Register a custom field type at startup:

```python
register_field_type(FieldTypeSpec(
    type="my_widget",
    label="My Widget",
    group="CUSTOM",
    icon="&#9733;",
    description="A custom input widget",
    config_schema={
        "max_value": {"type": "number", "label": "Max value", "default": 100}
    },
))
```

The palette ships with 91 field types total: 26 curated built-ins plus 65 auto-discovered from the widget library.

## Configuration Options

The Forms plugin has no `FAB_FORMS_*` keys of its own for core operation. Supporting features pull from the following app-config keys:

| Key | Used by | Description |
|-----|---------|-------------|
| `FAB_DATA_HUB_UPLOAD_DIR` | File / image-crop fields | Storage directory for uploaded files |
| `SECRET_KEY` | Share token generation | Flask secret key (standard requirement) |
| Redis (`CACHE_TYPE = "RedisCache"`) | Rate limiting on public submissions | Required for distributed rate limit counters; falls back to in-process |

Per-form rate limiting is configured inside the form definition itself:

```json
{
  "settings": {
    "rate_limit": {"per_ip": 10, "window_minutes": 60},
    "captcha": "hcaptcha",
    "captcha_site_key": "xxxx",
    "allow_draft_save": true,
    "show_progress_bar": true,
    "redirect_url": "https://example.com/thank-you"
  }
}
```

## Key API / Endpoints

Authenticated designer endpoints (all require `@has_access`):

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/form-builder/` | Drag-and-drop designer UI |
| `GET` | `/form-builder/api/forms` | List all forms with current definition |
| `POST` | `/form-builder/api/forms` | Create a new form; returns `{"id": int, "slug": str}` |
| `PUT` | `/form-builder/api/forms/<id>` | Update title or definition (partial) |
| `POST` | `/form-builder/api/forms/<id>/publish` | Snapshot current definition into an immutable `FormVersion`; returns `{"version": int}` |
| `POST` | `/form-builder/api/forms/<id>/share` | Generate a public share token; optional `max_submissions` and `expires_at` |
| `GET` | `/form-builder/api/field-types` | List all registered field types (used to populate the palette) |

Public unauthenticated endpoints:

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/forms/public/<token>` | Render the published form as HTML |
| `POST` | `/forms/public/<token>/submit` | Accept form submission; returns 410 when token expired or limit reached, 429 on rate-limit breach |
| `POST` | `/forms/public/<token>/draft` | Auto-save draft (when `allow_draft_save: true`); persists to `FormSubmission.draft_token` |

## Example Usage

```python
# 1. Create a multi-step scored assessment via the API
import requests

definition = {
    "fields": [
        {"id": "q1", "type": "radio", "label": "How often do you exercise?",
         "options": [
             {"label": "Daily",  "value": "daily",  "score": 10},
             {"label": "Weekly", "value": "weekly", "score": 6},
             {"label": "Never",  "value": "never",  "score": 0},
         ]},
        {"id": "step2", "type": "page_break",
         "step_label": "Step 2: Details", "require_valid_before_next": True},
        {"id": "email", "type": "email", "label": "Your email", "required": True},
    ],
    "steps": [
        {"step": 1, "label": "Health Check", "icon": "heart"},
        {"step": 2, "label": "Contact",       "icon": "envelope"},
    ],
    "conditions": [
        {
            "field_id": "q1", "op": "=", "value": "never",
            "action": "show", "target_id": "email"
        }
    ],
    "settings": {
        "title": "Health Assessment",
        "submit_label": "Submit",
        "score_bands": [
            {"min": 8, "max": 10, "label": "Excellent", "color": "#4caf50"},
            {"min": 0, "max": 7,  "label": "At Risk",   "color": "#ef5350"},
        ]
    }
}

# 2. Publish and share
# POST /form-builder/api/forms/1/publish  -> {"version": 1}
# POST /form-builder/api/forms/1/share    -> {"url": "/forms/public/abc123", "token": "abc123"}

# 3. Embed in any page
# <iframe src="/forms/public/abc123" width="100%" height="600" frameborder="0"></iframe>

# 4. Trigger a downstream workflow on submission (Rules Engine integration)
# In form definition settings.post_submit_actions:
# [{"type": "rules", "config": {"rule_set_id": 42, "input_mapping": {"score": "submission.score"}}}]
```

Field types covering the major categories: `text`, `textarea`, `richtext`, `email`, `phone`, `url`, `integer`, `decimal`, `currency`, `percentage`, `slider`, `date`, `time`, `datetime`, `daterange`, `select`, `radio`, `checkbox`, `toggle`, `rating`, `fk_lookup`, `m2n_select`, `file`, `image_crop`, `signature`, `section`, `page_break`, `repeating_group`, `html`, `formula`, `hidden`.

Conditional logic operators: `=`, `!=`, `>`, `<`, `>=`, `<=`, `contains`, `starts_with`, `is_empty`, `is_not_empty`. Actions: `show`, `hide`, `require`, `unrequire`, `set_value`, `clear`.

## See Also

- [Integrations plugin](integrations.md) — `post_submit_actions` can trigger outbound webhooks or BPM workflows
- [Audit plugin](audit.md) — `FormSubmission` rows are auditable via `AuditMixin` if attached
- pgappforge SPEC: `pgappforge/plugins/forms/SPEC.md`
