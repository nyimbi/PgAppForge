# Tutorial 04: Building and Publishing Forms

The Form Builder is a drag-and-drop designer for creating standalone data-collection forms. Forms are published with a share token and can be embedded in any web page via `<iframe>`. Submissions are stored in the database and optionally written directly to a model table.

## Prerequisites

- A running pgappforge app (see [Tutorial 02](02_first_app_from_db.md))
- The `FormsPlugin` enabled (below)

## Step 1 — Enable FormsPlugin

In your Flask application factory:

```python
# app.py
from pgappforge import AppBuilder
from pgappforge.plugins.forms import FormsPlugin

def create_app():
    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = os.environ["DATABASE_URL"]

    db = SQLAlchemy(app)
    appbuilder = AppBuilder(app, db.session)

    plugin = FormsPlugin()
    plugin.initialize(app, appbuilder)
    plugin.register_views(appbuilder)

    return app
```

Restart the app. A "Form Builder" item appears in the **Tools** menu.

## Step 2 — Navigate to the Form Builder

Go to `http://127.0.0.1:5000/formbuilder/`. You see three panels:

- **Left** — widget palette, organised by type (Basic, Selection, Advanced)
- **Centre** — canvas where you drag fields to build the form
- **Right** — configuration panel for the selected field

Click **+ New Form** to start a blank form. Give it a name, e.g. "Support Request".

## Step 3 — Add Fields

Drag fields from the palette onto the canvas in order:

| Field | Widget type | Configuration |
|-------|------------|---------------|
| Full Name | Text | Label: "Your Name", Required: yes |
| Email | Email | Label: "Email Address", Required: yes |
| Department | Dropdown | Label: "Department", Options: Engineering / Sales / HR / Other |
| Message | Textarea | Label: "Message", Rows: 5, Required: yes |

For each field, click it on the canvas to open its configuration in the right panel. Set:

- **Label** — user-facing label text
- **Required** — toggles client-side and server-side validation
- **Placeholder** — hint text shown in the empty field
- **Help text** — secondary instruction shown below the field

For the Department dropdown, enter each option on a separate line in the Options textarea.

The palette includes 26 widget types: text, email, url, phone, number, date, time, datetime, textarea, richtext, checkbox, checkboxgroup, radio, select (dropdown), multiselect, file, image, signature, rating, range, color, hidden, divider, heading, captcha, and repeater.

## Step 4 — Set Validation Rules

Click the Email field. In the right panel:

- **Required**: on
- **Format validation**: "email" (built-in pattern — rejects malformed addresses on submit)

Click the Message field:

- **Required**: on
- **Min length**: 20 (rejects single-word submissions)

Validation runs both in the browser (instant feedback) and on the server (cannot be bypassed).

## Step 5 — Publish the Form

Click **Publish** in the toolbar. A dialog appears with two options:

- **Expiry date** — optional; form stops accepting submissions after this date
- **Max submissions** — optional; closes the form after N responses

Leave both blank for an open-ended form. Click **Publish**.

The dialog shows:

```
Share token: a7f3c9d2e1b84056
Public URL:  http://127.0.0.1:5000/forms/public/a7f3c9d2e1b84056
```

The public form URL works without authentication. Anyone with the link can submit the form.

## Step 6 — Embed the Form in Another Page

Copy the share token and use it in an `<iframe>`:

```html
<iframe
  src="http://your-domain.com/forms/public/a7f3c9d2e1b84056"
  width="100%"
  height="600"
  style="border: none;"
  title="Support Request Form">
</iframe>
```

The public renderer applies your form's field order, labels, validation rules, and required flags. On submit it:

1. Validates all fields server-side
2. Stores the submission in the `forms_submission` table with a timestamp and the responder's IP
3. Returns a configurable thank-you message

## Viewing Submissions

In the Form Builder, select your form and click **Submissions**. You see a paginated table of all responses with timestamps. Export to CSV with the **Download** button.

To write submissions directly to a model table, set **Target model** in the form's settings to a SQLAlchemy model class name (e.g. `SupportTicket`). The Form Builder maps field names to column names automatically; unmapped fields are ignored.

## Next Steps

- Add conditional logic: show/hide fields based on the value of another field (use the **Conditions** tab on each field)
- Multi-step forms: click **Add Step** in the toolbar to split long forms into wizard pages
- Scoring: assign point values to radio/select options (useful for assessments)
