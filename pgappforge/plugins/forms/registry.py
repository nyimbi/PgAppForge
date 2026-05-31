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

# ── Auto-discovery from pgappforge widget library ─────────────────────────────

import re as _re

# Widget class names that are layout/display-only — not form inputs
_SKIP_WIDGET_NAMES: frozenset = frozenset({
	"RenderTemplateWidget", "FormWidget", "ListWidget", "SearchWidget",
	"ShowWidget", "GroupFormListWidget", "ListMasterWidget", "ListAddWidget",
	"ListThumbnail", "ListLinkWidget", "ListCarousel", "ListItem", "ListBlock",
	"ShowBlockWidget", "ShowVerticalWidget", "FormVerticalWidget",
	"FormHorizontalWidget", "FormInlineWidget", "ApprovalWidget", "MenuWidget",
	"ChartWidget", "AdvancedChartsWidget", "FormBuilderWidget", "ValidationWidget",
})

# Categories from get_available_widgets() whose contents are display/layout — auto-skip
_SKIP_CATEGORIES: frozenset = frozenset({
	"core",       # layout templates: ListWidget, FormWidget, etc.
	"layout",     # Timeline, Tree, VirtualList, Graph — visualizers, not inputs
	"workflow",   # Kanban, Gantt, Wizard, Diagram — workflow viewers, not inputs
	"analytics",  # KPI, Pivot — charts/dashboards, not inputs
})

# Module path fragment → palette group name
_MODULE_TO_GROUP: list[tuple[str, str]] = [
	(".input.",       "INPUT"),
	(".geo.",         "GEO & LOCATION"),
	(".media.",       "MEDIA"),
	(".editing.",     "EDITING"),
	(".data.",        "DATA"),
	(".social.",      "SOCIAL"),
	(".workflow.",    "WORKFLOW"),
	(".layout.",      "LAYOUT"),
	(".analytics.",   "ANALYTICS"),
	(".forms.",       "FORMS"),
	(".visualization.", "GEO & LOCATION"),
	("fieldwidgets",  "FIELD INPUTS"),
	("modern_ui",     "ENHANCED"),
	("specialized",   "DATA"),
]

# Icon hints by keyword in class name
_ICON_HINTS: list[tuple[str, str]] = [
	("Password",  "&#128274;"),
	("Color",     "&#127752;"),
	("Tag",       "&#127991;"),
	("Date",      "&#128197;"),
	("Time",      "&#9200;"),
	("Signature", "&#10000;"),
	("Map",       "&#128506;"),
	("Geo",       "&#127759;"),
	("GPS",       "&#127759;"),
	("Address",   "&#127968;"),
	("Phone",     "&#128222;"),
	("Image",     "&#128247;"),
	("Camera",    "&#128247;"),
	("Video",     "&#127909;"),
	("Audio",     "&#127925;"),
	("File",      "&#128206;"),
	("QR",        "&#9638;"),
	("Barcode",   "&#9638;"),
	("JSON",      "&#123;"),
	("Array",     "&#91;"),
	("Code",      "&#60;/&#62;"),
	("Markdown",  "M"),
	("Rich",      "&#10000;"),
	("Mermaid",   "&#9671;"),
	("DBML",      "&#9671;"),
	("GPS",       "&#128204;"),
	("Chat",      "&#128172;"),
	("Comment",   "&#128172;"),
	("ICD",       "&#9874;"),
	("SNOMED",    "&#9874;"),
	("Select2",   "&#9660;"),
	("Toggle",    "&#9889;"),
	("Range",     "&#8596;"),
	("Slider",    "&#8596;"),
	("Star",      "&#11088;"),
	("Rating",    "&#11088;"),
	("Spread",    "&#128200;"),
	("Chart",     "&#128200;"),
	("Kanban",    "&#9783;"),
	("Gantt",     "&#128198;"),
	("Wizard",    "&#128736;"),
]


def _camel_to_snake(name: str) -> str:
	"""ICD10SearchWidget → icd10_search"""
	name = _re.sub(r"Widget$", "", name)
	s1 = _re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name)
	s2 = _re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", s1)
	return s2.lower()


def _camel_to_label(name: str) -> str:
	"""ICD10SearchWidget → ICD10 Search"""
	name = _re.sub(r"Widget$", "", name)
	s1 = _re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", name)
	s2 = _re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", s1)
	return s2.strip()


def _widget_icon(name: str) -> str:
	for kw, icon in _ICON_HINTS:
		if kw.lower() in name.lower():
			return icon
	return "&#9633;"  # generic square


def _first_docline(cls: type) -> str:
	doc = getattr(cls, "__doc__", None) or ""
	skip_prefixes = ("---", "===", ">>>", ":param", ":type", ":return", ":rtype", "#", "@")
	for line in doc.splitlines():
		line = line.strip()
		if line and not any(line.startswith(p) for p in skip_prefixes):
			return line[:140]
	return ""


def _group_from_class(cls: type, category: str) -> str:
	mod = getattr(cls, "__module__", "") or ""
	for fragment, group in _MODULE_TO_GROUP:
		if fragment in mod:
			return group
	return category.upper().replace("_", " ")


def _builtin_types() -> frozenset:
	"""Set of type identifiers already in _BUILTIN_GROUPS."""
	return frozenset(
		f["type"]
		for g in _BUILTIN_GROUPS
		for f in g["fields"]
	)


def auto_discover_widgets() -> int:
	"""Auto-register all form-compatible pgappforge widgets as field types.

	Calls get_available_widgets(), filters out layout/display-only classes,
	and registers each remaining widget as a FieldTypeSpec with a fallback
	renderer (data-field-type + data-widget-config for JS enhancement).

	Returns the number of new types registered.
	Idempotent — safe to call multiple times.
	"""
	try:
		from pgappforge.widgets import get_available_widgets
	except ImportError:
		return 0

	existing_builtin = _builtin_types()
	count = 0
	all_widgets = get_available_widgets()

	for category, widget_map in all_widgets.items():
		if category in _SKIP_CATEGORIES:
			continue
		for cls_name, cls in widget_map.items():
			if cls_name in _SKIP_WIDGET_NAMES:
				continue
			type_name = _camel_to_snake(cls_name)
			if not type_name or type_name in existing_builtin:
				continue
			if get_field_type(type_name) is not None:
				continue  # already registered
			label = _camel_to_label(cls_name)
			group = _group_from_class(cls, category)
			description = _first_docline(cls)
			icon = _widget_icon(cls_name)
			try:
				register_field_type(FieldTypeSpec(
					type=type_name,
					label=label,
					group=group,
					icon=icon,
					description=description,
				))
				count += 1
			except Exception:
				pass  # invalid type name or other issue — skip silently
	return count
