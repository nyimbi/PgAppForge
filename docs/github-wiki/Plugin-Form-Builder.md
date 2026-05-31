# Plugin: Form Builder

[Home](Home) > Plugin: Form Builder

The Form Builder plugin provides a drag-and-drop interface for building multi-step forms with conditional logic, scoring, public embed URLs, and a fully extensible field type palette.

---

## Initialisation

```python
from pgappforge.plugins.forms import FormsPlugin

plugin = FormsPlugin()
plugin.initialize(app, appbuilder)
plugin.register_views(appbuilder)
```

Registers the Form Builder admin view at `/tools/form-builder/` and the public form renderer at `/public/form/<slug>/`.

On initialisation, `auto_discover_widgets()` is called automatically to load any third-party field types installed in the environment.

---

## Built-in Field Groups

The palette ships with groups including: Text, Number, Date/Time, Choice, File, Signature, Location, and Medical (ICD-10 picker). Each group can be extended with custom types.

---

## Registering a Custom Field Type

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
        "multi_select": {
            "type": "boolean",
            "label": "Allow multiple codes",
            "default": False,
        },
    },
))
```

The registered type appears immediately in the palette under the specified group. Registration is thread-safe and idempotent (last write wins for a given `type` key).

---

## Auto-Discovery

`auto_discover_widgets()` scans installed packages for the `pgappforge.widgets` entry point group and registers any `FieldTypeSpec` instances they export. Returns the count of widgets discovered.

---

## Public Form Embedding

Every published form gets a shareable URL: `/public/form/<slug>/`. Embed in any page:

```html
<iframe src="https://yourapp.com/public/form/patient-intake/" width="100%" height="600"></iframe>
```

---

## Further Reading

Full reference: [docs/plugins/forms.md](../plugins/forms.md)

---

## See also

- [Plugin: Audit Trail](Plugin-Audit-Trail)
- [Plugin: Realtime](Plugin-Realtime)
- [Python API Reference](../api/python.md)
- [Architecture](Architecture)
