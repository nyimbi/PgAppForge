# Visual Form Builder

## Overview

The Visual Form Builder closes the 20% gap that auto-generated CRUD forms cannot fill. Auto-generated forms work when your model schema directly maps to user intent. They break down when you need:

- Multi-step wizard flows with per-step validation
- Conditional field visibility driven by user answers
- Public, unauthenticated submission with share links
- Scoring and assessment modes (quizzes, evaluations)
- Integration with downstream workflows (Rules Engine, BPM, ReportForge)
- Analytics on submission funnel and field-level friction

The Form Builder is a first-class pgappforge plugin (`pgappforge.plugins.forms`) providing a drag-and-drop canvas, a JSON-backed definition model, a public HTML renderer, and a REST API — all without writing a line of Python.

---

## Architecture

```
FormBuilderView (/form-builder/)       — authenticated designer UI
  └─ /api/forms                         GET list, POST create
  └─ /api/forms/<id>                    PUT update
  └─ /api/forms/<id>/publish            POST → creates FormVersion
  └─ /api/forms/<id>/share              POST → creates FormShareToken

PublicFormView (/forms/)               — unauthenticated end-users
  └─ /public/<token>                    GET rendered HTML form
  └─ /public/<token>/submit             POST submission handler

renderer.render_form(def, token)       — pure function, definition → HTML string
```

**Storage**: all form state lives in JSONB columns (`definition`, `data`, `score_bands`) on PostgreSQL, so schema migrations are rare. The `definition` blob is versioned on publish into immutable `FormVersion` rows.

---

## Form Canvas

### Drag-and-Drop Field Palette

The left panel lists all available field types as draggable chips. Drag any chip onto the centre canvas to append a new field. Fields render as cards showing label and type; click a card to select it and open the right-side configuration panel.

### Field Configuration Panel

When a field card is selected the right panel exposes:

| Setting | Applies to |
|---|---|
| Label | all |
| Placeholder | text, email, number, textarea |
| Required toggle | all |
| Help text | all |
| Options list (one per line) | select, radio, checkbox |

Changes apply immediately to the canvas card label.

### Form Settings

Accessed via Save dialog (title prompt). The `settings` key inside the definition blob accepts:

```json
{
  "title": "Customer Onboarding",
  "description": "Complete all fields to activate your account.",
  "submit_label": "Activate Account",
  "success_message": "Your account is now active!",
  "allow_draft_save": true,
  "show_progress_bar": true,
  "redirect_url": "https://example.com/welcome"
}
```

---

## Field Types

### Text Variants

**single-line** (`type: text`)
Standard `<input type="text">`. Use for names, short answers, codes.
Config: `min_length`, `max_length`, `pattern` (regex), `autocomplete`.

**multi-line** (`type: textarea`)
`<textarea>` with configurable `rows`. Use for addresses, descriptions, notes.
Config: `rows` (default 4), `max_length`, `word_count_limit`.

**rich text** (`type: richtext`)
Embeds a minimal contenteditable editor (Quill or TipTap). Stored as HTML string.
Config: `toolbar` list (`bold`, `italic`, `link`, `bullet`).

**email** (`type: email`)
`<input type="email">` with built-in browser validation. Renderer adds
`pattern="[^@\s]+@[^@\s]+\.[^@\s]+"` for extra coverage.
Config: `domain_whitelist` array.

**phone** (`type: phone`)
`<input type="tel">` with optional `libphonenumber-js` client validation.
Config: `default_country`, `format` (`national` | `international`).

**URL** (`type: url`)
`<input type="url">`. Validates scheme on blur.
Config: `allowed_schemes` (default `["https"]`).

### Number Variants

**integer** (`type: integer`)
`<input type="number" step="1">`. Server-side coerces to int.
Config: `min`, `max`, `step`.

**decimal** (`type: decimal`)
`<input type="number">` with arbitrary step. Stored as `Numeric(precision, scale)`.
Config: `min`, `max`, `step`, `decimal_places`.

**currency** (`type: currency`)
Decimal input with currency symbol prefix/suffix.
Config: `currency_code` (ISO 4217), `symbol_position` (`prefix`|`suffix`).

**percentage** (`type: percentage`)
Decimal input constrained 0–100, displayed with `%` suffix.

**slider** (`type: slider`)
`<input type="range">` rendered with min/max/step tick marks.
Config: `min`, `max`, `step`, `show_value` (live label above thumb).

### Date / Time

**date** (`type: date`)
`<input type="date">`. Stored as ISO 8601 string.
Config: `min_date`, `max_date`, `disallow_past`, `disallow_future`.

**time** (`type: time`)
`<input type="time">`.
Config: `step` (seconds), `min_time`, `max_time`.

**datetime** (`type: datetime`)
`<input type="datetime-local">`.
Config: same as date + time combined.

**date range** (`type: daterange`)
Two date inputs (`start_date`, `end_date`) rendered side-by-side.
Validation ensures end >= start. Stored as `{start: "...", end: "..."}`.

### Selection

**dropdown** (`type: select`)
`<select>`. Supports option groups via `optgroup` label in options list.
Config: `placeholder_option`, `multiple` (multi-select), `searchable` (Select2 progressive enhancement).

**radio** (`type: radio`)
`<input type="radio">` group. Renders vertically by default.
Config: `layout` (`vertical`|`horizontal`|`grid`), `columns` (for grid).

**checkbox** (`type: checkbox`)
`<input type="checkbox">` group. Submitted as array.
Config: `min_selections`, `max_selections`, `layout`.

**toggle** (`type: toggle`)
Single boolean toggle switch (styled `<input type="checkbox">`).
Config: `on_label`, `off_label`, `default_value`.

**rating** (`type: rating`)
Star/emoji rating widget. Stored as integer.
Config: `max_stars` (default 5), `allow_half`, `icon` (`star`|`heart`|`thumb`).

### Relationship

**FK lookup** (`type: fk_lookup`)
Autocomplete input backed by a pgappforge model query endpoint.
Config: `model` (dotted class path), `display_field`, `value_field`, `filter_expr`.
Renders as `<input type="hidden">` + visible text input + dropdown list.

**multi-select M2N** (`type: m2n_select`)
Multi-select backed by a junction table. Stored as array of PKs.
Config: `model`, `display_field`, `value_field`, `max_selections`.

### Upload

**file** (`type: file`)
`<input type="file">`. Uploaded to configurable storage backend.
Config: `allowed_extensions`, `max_size_mb`, `multiple`, `storage_backend` (`local`|`s3`|`gcs`).

**image with crop** (`type: image_crop`)
File input with client-side Cropper.js integration before upload.
Config: `aspect_ratio` (e.g. `1/1`, `16/9`), `min_width`, `min_height`, `output_format`.

**signature pad** (`type: signature`)
Canvas-based signature widget (Signature Pad library). Stored as base64 PNG data URL.
Config: `pen_color`, `background_color`, `min_stroke_count`.

### Structural

**section header** (`type: section`)
Visual divider with title and optional description text. Not a data field.
Config: `title`, `description`, `collapsible`, `collapsed_by_default`.

**page break** (`type: page_break`)
Splits the form into wizard steps. Each page break increments the step counter.
Config: `step_label` (e.g. "Step 2: Contact Info"), `require_valid_before_next`.

**repeating group** (`type: repeating_group`)
A sub-form that users can fill N times (e.g., add multiple dependants).
Config: `fields` (nested field definitions), `min_items`, `max_items`, `add_label`.
Stored as array of objects: `[{field_id: value, ...}, ...]`.

**HTML block** (`type: html`)
Static HTML injected into the form (instructions, images, links). Not a data field.
Config: `content` (sanitised HTML string).

### Computed

**formula** (`type: formula`)
Read-only field whose value is computed client-side from other fields.
Config: `expression` (JS-safe expression string, e.g. `"qty * unit_price"`),
`format` (`number`|`currency`|`percentage`).

**hidden** (`type: hidden`)
`<input type="hidden">`. Pre-populated from URL params or session context.
Config: `source` (`url_param`|`session`|`constant`), `source_key`, `default_value`.

---

## Conditional Logic

### Condition Syntax

Each condition is a JSON object:

```json
{
  "id": "cond_01",
  "field_id": "employment_status",
  "op": "=",
  "value": "employed",
  "action": "show",
  "target_id": "employer_name",
  "group": "AND"
}
```

| Key | Values |
|---|---|
| `op` | `=`, `!=`, `>`, `<`, `>=`, `<=`, `contains`, `starts_with`, `is_empty`, `is_not_empty` |
| `action` | `show`, `hide`, `require`, `unrequire`, `set_value`, `clear` |
| `group` | `AND`, `OR` — how conditions in a multi-condition rule combine |

### Visual Condition Builder

In the Form Builder UI, a "Conditions" tab opens a rule editor:

1. Pick a **trigger field** from the form field list
2. Choose an **operator**
3. Enter the **comparison value**
4. Choose the **action** and **target field**
5. Add more conditions with AND/OR toggle

Rules are serialised into `definition.conditions` and evaluated in the renderer's inline `<script>` block on every input change event.

### AND/OR Groups

Multiple conditions targeting the same field can be grouped:

```json
{
  "target_id": "tax_id_field",
  "action": "show",
  "logic": "AND",
  "conditions": [
    {"field_id": "country", "op": "=", "value": "US"},
    {"field_id": "business_type", "op": "!=", "value": "individual"}
  ]
}
```

---

## Multi-Step Wizard

### Page Break → Wizard Step

Every `page_break` field in the `fields` array creates a step boundary. The renderer groups fields between breaks into logical pages. The client-side wizard hides all pages except the active one and shows a progress bar.

Step metadata is stored in `definition.steps`:

```json
[
  {"step": 1, "label": "Personal Info", "icon": "user"},
  {"step": 2, "label": "Contact Details", "icon": "envelope"},
  {"step": 3, "label": "Review & Submit", "icon": "check"}
]
```

### Per-Step Validation

When `require_valid_before_next: true` on a page break field, the client fires HTML5
`checkValidity()` on all required fields in the current step before advancing. Server-side
re-validates on final submit.

### Draft Auto-Save

When `settings.allow_draft_save: true`, the client POSTs to `/forms/public/<token>/draft`
every 30 seconds with the current field values. The server stores them in
`FormSubmission.draft_token`. On next page load the draft token (stored in `localStorage`)
is sent as a query param to pre-populate the form.

---

## Public Forms

### Share Token Generation

`POST /form-builder/api/forms/<id>/share` returns:

```json
{"url": "/forms/public/abc123...", "token": "abc123..."}
```

Tokens are 32-byte URL-safe random strings. Optional limits:

```json
{"max_submissions": 500, "expires_at": "2026-12-31T23:59:59Z"}
```

When `submissions_used >= max_submissions` or `expires_at` has passed, the public endpoint
returns HTTP 410 Gone.

### Embedding Options

**iFrame embed**

```html
<iframe src="https://app.example.com/forms/public/TOKEN"
        width="100%" height="600" frameborder="0"></iframe>
```

**JavaScript embed** (resizes to content height)

```html
<div id="pgaf-form"></div>
<script src="https://app.example.com/static/appbuilder/js/form-embed.js"
        data-token="TOKEN" data-container="#pgaf-form"></script>
```

### CAPTCHA Integration

Set `settings.captcha: "hcaptcha"` or `"recaptcha_v3"` and provide the site key:

```json
{"captcha": "hcaptcha", "captcha_site_key": "xxxx"}
```

The renderer injects the appropriate widget JS. The submission handler calls the verification
API before persisting the `FormSubmission`.

### Rate Limiting

Configured in `definition.settings.rate_limit`:

```json
{"per_ip": 10, "window_minutes": 60}
```

Enforced in `public_submit` using a Redis counter keyed by `form_id:ip`. Exceeding the limit
returns HTTP 429 with a `Retry-After` header.

---

## Form Analytics

### Completion Funnel

`FormAnalyticsEvent` rows with `event_type` values:

| Event | Meaning |
|---|---|
| `view` | Form page loaded |
| `start` | User interacted with first field |
| `step_complete` | User passed a page break |
| `field_focus` | User focused a field |
| `field_error` | Validation failed on a field |
| `abandon` | Tab closed / navigated away without submit |
| `submit` | Successful submission |

Funnel query (drop-off per step):

```sql
SELECT step_number,
       COUNT(DISTINCT session_id) FILTER (WHERE event_type = 'step_complete') AS completed,
       COUNT(DISTINCT session_id) FILTER (WHERE event_type = 'abandon') AS abandoned
FROM pgaf_form_analytics
WHERE form_id = :form_id
GROUP BY step_number
ORDER BY step_number;
```

### Per-Field Metrics

```sql
SELECT field_id,
       COUNT(*) FILTER (WHERE event_type = 'field_error') AS error_count,
       AVG(duration_ms) FILTER (WHERE event_type = 'field_focus') AS avg_focus_ms
FROM pgaf_form_analytics
WHERE form_id = :form_id
GROUP BY field_id
ORDER BY error_count DESC;
```

Fields with high `error_count` or `avg_focus_ms` indicate confusing labels or validation.

---

## Scoring / Assessment Mode

Enable via `Form.scoring_enabled = True`. Each field option can carry a numeric weight:

```json
{
  "id": "q1",
  "type": "radio",
  "label": "How often do you exercise?",
  "options": [
    {"label": "Daily",   "value": "daily",   "score": 10},
    {"label": "Weekly",  "value": "weekly",  "score": 6},
    {"label": "Monthly", "value": "monthly", "score": 2},
    {"label": "Never",   "value": "never",   "score": 0}
  ]
}
```

On submission the handler sums `option.score` for every answered field and stores the total
in `FormSubmission.score`.

### Score Bands

```json
[
  {"min": 80, "max": 100, "label": "Excellent",          "color": "#4caf50"},
  {"min": 60, "max": 79,  "label": "Good",               "color": "#8bc34a"},
  {"min": 40, "max": 59,  "label": "Needs Improvement",  "color": "#ff9800"},
  {"min": 0,  "max": 39,  "label": "At Risk",            "color": "#ef5350"}
]
```

`FormSubmission.outcome` is set to the matching band label.

### PDF Report Generation

When `settings.score_report_pdf: true`, the submission handler calls
`pgappforge.plugins.reports.engine.render_pdf` with a pre-configured score report template,
attaches it to the submission record, and optionally emails it to `submitter_email`.

---

## Integration Points

### Rules Engine

```json
{
  "type": "rules",
  "config": {"rule_set_id": 42, "input_mapping": {"score": "submission.score"}}
}
```

On submit, `RulesEngine.evaluate(rule_set_id, context)` is called. Returned actions
(e.g., `assign_user`, `send_notification`) are dispatched.

### BPM Workflow

```json
{
  "type": "bpm",
  "config": {"process_definition_key": "loan_application", "variables": {"form_id": "submission.id"}}
}
```

Triggers a BPMN process instance via `pgappforge.plugins.workflow.engine.start_process`.

### ReportForge

```json
{
  "type": "report",
  "config": {"report_id": 7, "parameter_mapping": {"applicant_id": "submission.submitter_id"}}
}
```

Renders a ReportForge report with submission data injected as parameters.

---

## API Reference

### List Forms

```
GET /form-builder/api/forms
Authorization: session (has_access required)
```

Response:
```json
{
  "forms": [
    {
      "id": 1,
      "title": "Customer Onboarding",
      "slug": "customer-onboarding-a1b2c3d4",
      "status": "published",
      "definition": {...},
      "created_at": "2026-05-31T10:00:00+00:00"
    }
  ]
}
```

### Create Form

```
POST /form-builder/api/forms
Authorization: session (has_access required)
Content-Type: application/json
```

Body:
```json
{
  "title": "My New Form",
  "definition": {
    "fields": [],
    "steps": [],
    "settings": {"title": "My New Form", "submit_label": "Submit"},
    "conditions": []
  }
}
```

Response `201`:
```json
{"id": 5, "slug": "my-new-form-deadbeef"}
```

### Update Form

```
PUT /form-builder/api/forms/<id>
Authorization: session (has_access required)
Content-Type: application/json
```

Body: partial — any subset of `title`, `definition`.

Response `200`:
```json
{"id": 5}
```

### Publish Form

```
POST /form-builder/api/forms/<id>/publish
Authorization: session (has_access required)
```

Creates an immutable `FormVersion` snapshot. Sets `Form.status = "published"`.

Response `200`:
```json
{"version": 3}
```

### Create Share Token

```
POST /form-builder/api/forms/<id>/share
Authorization: session (has_access required)
Content-Type: application/json
```

Optional body:
```json
{"max_submissions": 100, "expires_at": "2026-12-31T23:59:59Z"}
```

Response `200`:
```json
{"url": "/forms/public/abc123...", "token": "abc123..."}
```

### Submit Public Form

```
POST /forms/public/<token>/submit
Content-Type: application/x-www-form-urlencoded
(no authentication required)
```

Body: form-encoded field values. `csrf_token` is stripped before persistence.

Response `200`: success HTML page.

Response `404`: token not found.

Response `410`: token expired or submission limit reached.

Response `429`: rate limit exceeded.

---

## Database Schema

| Table | Purpose |
|---|---|
| `pgaf_form` | Form definitions with current version pointer |
| `pgaf_form_version` | Immutable published snapshots |
| `pgaf_form_share_token` | Public access tokens with optional limits |
| `pgaf_form_submission` | Submitted data with optional score/outcome |
| `pgaf_form_analytics` | Funnel and field-level analytics events |

All JSONB columns use PostgreSQL-native JSONB (not JSON text), enabling GIN index queries
like `data @> '{"country": "US"}'`.

---

## Security Considerations

- The `FormBuilderView` and all `/api/forms` endpoints require `has_access` (authenticated session).
- `PublicFormView` is intentionally unauthenticated but rate-limited per IP.
- CSRF tokens are validated on public form submission via Flask-WTF when available.
- File uploads are sanitised (extension whitelist, magic-byte check) before storage.
- HTML block content is sanitised with `bleach` before render.
- Score band boundaries are validated on save to prevent overlaps and gaps.
- Share tokens are 32-byte URL-safe random strings (256-bit entropy).
