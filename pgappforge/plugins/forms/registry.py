"""Form Builder field type registry.

Allows any plugin to register custom field types that appear in the palette,
get automatic config-panel UI (from config_schema), and public-form rendering.

Quick start
-----------
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

Built-in field types are defined in _BUILTIN_GROUPS below. Registered types
appear after built-in groups (or merged into an existing group of the same name).
"""
from __future__ import annotations
import threading
from typing import Any

_LOCK = threading.Lock()
_REGISTRY: dict[str, "FieldTypeSpec"] = {}

# config_schema field descriptor keys:
#   type: str       — "text" | "number" | "boolean" | "select" | "textarea"
#   label: str      — shown above the input in the config panel
#   options: list   — required when type == "select"
#   default: Any    — pre-filled value


class FieldTypeSpec:
	"""Specification for a custom (or built-in) form field type.

	Attributes:
		type:           Unique snake_case identifier, e.g. "icd10_picker".
		label:          Display name shown in palette chip, e.g. "ICD-10 Code".
		group:          Palette group header, e.g. "MEDICAL". Created if new.
		icon:           Short HTML (entity or text) used as chip icon, e.g. "&#128138;".
		config_schema:  Dict of extra config inputs rendered in the field config panel.
						Keys become field.extra_config keys in the saved definition.
		renderer:       Optional HTML template for public form rendering.
						Receives: id, label, placeholder, required, value, extra_config.
						Defaults to a styled text input with data-field-type attribute.
		description:    Tooltip shown when hovering the palette chip.
	"""
	__slots__ = ("type", "label", "group", "icon", "config_schema", "renderer", "description")

	def __init__(
		self,
		*,
		type: str,
		label: str,
		group: str,
		icon: str = "&#10022;",
		config_schema: dict[str, Any] | None = None,
		renderer: str | None = None,
		description: str = "",
	) -> None:
		if not type or not type.replace("_", "").isalnum():
			raise ValueError(f"Field type must be alphanumeric + underscores, got: {type!r}")
		self.type = type
		self.label = label
		self.group = group
		self.icon = icon
		self.config_schema = config_schema or {}
		self.renderer = renderer
		self.description = description

	def to_dict(self) -> dict:
		return {
			"type": self.type,
			"label": self.label,
			"group": self.group,
			"icon": self.icon,
			"config_schema": self.config_schema,
			"description": self.description,
		}


def register_field_type(spec: "FieldTypeSpec | dict") -> None:
	"""Register a custom field type. Thread-safe, idempotent (last registration wins)."""
	if isinstance(spec, dict):
		spec = FieldTypeSpec(**spec)
	with _LOCK:
		_REGISTRY[spec.type] = spec


def get_field_type(type_name: str) -> "FieldTypeSpec | None":
	return _REGISTRY.get(type_name)


def get_all_registered() -> list["FieldTypeSpec"]:
	with _LOCK:
		return list(_REGISTRY.values())


def get_renderer(type_name: str) -> str | None:
	"""Return the HTML renderer template for a registered custom type, or None."""
	spec = _REGISTRY.get(type_name)
	return spec.renderer if spec else None


def get_palette_groups() -> list[dict]:
	"""Return full palette: built-in groups with registered types merged/appended."""
	import copy
	groups = copy.deepcopy(_BUILTIN_GROUPS)
	group_index = {g["group"]: g for g in groups}
	with _LOCK:
		registered = list(_REGISTRY.values())
	for spec in registered:
		if spec.group in group_index:
			group_index[spec.group]["fields"].append(spec.to_dict())
		else:
			new_group = {"group": spec.group, "fields": [spec.to_dict()]}
			groups.append(new_group)
			group_index[spec.group] = new_group
	return groups


# ── Built-in field types ──────────────────────────────────────────────────────

_BUILTIN_GROUPS: list[dict] = [
	{"group": "TEXT", "fields": [
		{"type": "text",      "icon": "T",           "label": "Text",       "config_schema": {}, "description": "Single-line text input"},
		{"type": "email",     "icon": "@",            "label": "Email",      "config_schema": {}, "description": "Email address with format validation"},
		{"type": "phone",     "icon": "#",            "label": "Phone",      "config_schema": {}, "description": "Phone number input"},
		{"type": "url",       "icon": "&#128279;",    "label": "URL",        "config_schema": {}, "description": "URL with http/https validation"},
		{"type": "textarea",  "icon": "&#9776;",      "label": "Long Text",  "description": "Multi-line text area",
		 "config_schema": {"rows": {"type": "number", "label": "Default rows", "default": 4}}},
		{"type": "rich_text", "icon": "&#10000;",     "label": "Rich Text",  "description": "Rich text editor (TipTap)",
		 "config_schema": {"toolbar": {"type": "select", "label": "Toolbar preset",
		                               "options": ["minimal", "standard", "full"], "default": "standard"}}},
	]},
	{"group": "NUMBER", "fields": [
		{"type": "number",   "icon": "123",         "label": "Number",    "config_schema": {}, "description": "Integer or decimal number"},
		{"type": "currency", "icon": "$",           "label": "Currency",  "description": "Currency amount with symbol",
		 "config_schema": {"currency": {"type": "select", "label": "Currency",
		                                "options": ["USD", "EUR", "GBP", "KES", "ZAR", "NGN", "JPY", "CAD", "AUD"],
		                                "default": "USD"}}},
		{"type": "slider",   "icon": "&#8596;",     "label": "Slider",    "description": "Range slider with min/max/step",
		 "config_schema": {
			"slider_min":  {"type": "number", "label": "Min value",  "default": 0},
			"slider_max":  {"type": "number", "label": "Max value",  "default": 100},
			"slider_step": {"type": "number", "label": "Step size",  "default": 1},
		 }},
	]},
	{"group": "DATE & TIME", "fields": [
		{"type": "date",       "icon": "&#128197;", "label": "Date",         "config_schema": {}, "description": "Date picker"},
		{"type": "datetime",   "icon": "&#128336;", "label": "Date & Time",  "config_schema": {}, "description": "Date and time picker"},
		{"type": "time",       "icon": "&#9200;",   "label": "Time",         "config_schema": {}, "description": "Time picker"},
		{"type": "date_range", "icon": "&#128198;", "label": "Date Range",   "config_schema": {}, "description": "Start and end date picker"},
	]},
	{"group": "CHOICE", "fields": [
		{"type": "select",   "icon": "&#9660;",   "label": "Dropdown",      "config_schema": {}, "description": "Single-select dropdown"},
		{"type": "radio",    "icon": "&#9673;",   "label": "Radio Buttons", "config_schema": {}, "description": "Single-select radio group"},
		{"type": "checkbox", "icon": "&#9745;",   "label": "Checkboxes",    "config_schema": {}, "description": "Multi-select checkbox group"},
		{"type": "toggle",   "icon": "&#9889;",   "label": "Toggle",        "config_schema": {}, "description": "Boolean on/off toggle"},
		{"type": "rating",   "icon": "&#11088;",  "label": "Rating Stars",  "description": "Star rating widget",
		 "config_schema": {"max_stars": {"type": "number", "label": "Max stars (2–10)", "default": 5}}},
	]},
	{"group": "RELATIONSHIP", "fields": [
		{"type": "fk_lookup", "icon": "&#128269;", "label": "Record Lookup",  "config_schema": {}, "description": "FK lookup with live search against a model"},
		{"type": "m2n",       "icon": "&#128279;", "label": "Multi-Lookup",   "config_schema": {}, "description": "Multi-select FK lookup (M2N)"},
	]},
	{"group": "FILE", "fields": [
		{"type": "file",      "icon": "&#128206;", "label": "File Upload",  "config_schema": {}, "description": "Any file type"},
		{"type": "image",     "icon": "&#128247;", "label": "Image",        "description": "Image upload with optional crop",
		 "config_schema": {"allow_crop": {"type": "boolean", "label": "Allow crop tool", "default": False}}},
		{"type": "signature", "icon": "&#10000;",  "label": "Signature Pad","config_schema": {}, "description": "Canvas signature pad (saves as PNG)"},
	]},
	{"group": "COMPUTED", "fields": [
		{"type": "formula", "icon": "=",        "label": "Formula",  "description": "Computed value from other fields ({field_id} syntax)",
		 "config_schema": {"expression": {"type": "textarea", "label": "Expression — use {field_id} to reference fields, e.g. {price}*{qty}", "default": ""}}},
		{"type": "hidden",  "icon": "&#128065;","label": "Hidden",   "config_schema": {}, "description": "Pre-filled hidden field"},
	]},
	{"group": "STRUCTURE", "fields": [
		{"type": "section",    "icon": "&#128204;", "label": "Section Header",  "config_schema": {}, "description": "Visual section divider with title"},
		{"type": "page_break", "icon": "&#128214;", "label": "Page Break",      "config_schema": {}, "description": "Creates a new wizard step"},
		{"type": "html_block", "icon": "&#10064;",  "label": "HTML Block",      "description": "Raw HTML content block",
		 "config_schema": {"html": {"type": "textarea", "label": "HTML content", "default": "<p>Your content here</p>"}}},
		{"type": "repeating",  "icon": "&#8635;",   "label": "Repeating Group", "config_schema": {}, "description": "Dynamic rows of sub-fields"},
	]},
]
