"""
pgappforge/citizen_dev/config.py

YAML schema parser for citizen-developer custom field definitions.

Non-developers drop *.yaml files into a ``custom_fields/`` directory at the
project root (or any directory passed to :func:`load_customizations`).  Each
file describes extensions to one SQLAlchemy model — extra columns, extra list
filters, extra list columns, and columns to hide.

Naming convention
-----------------
Field names are automatically prefixed with ``custom_`` if they don't already
carry the prefix.  This prevents collisions with framework-managed columns.

Supported field types
---------------------
string, text, integer, float, boolean, date, datetime, decimal, select,
multiselect, email, phone, url, jsonb, uuid, money (integer cents).
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

log = logging.getLogger(__name__)

SUPPORTED_FIELD_TYPES: frozenset[str] = frozenset([
	"string", "text", "integer", "float", "boolean", "date", "datetime",
	"decimal", "select", "multiselect", "email", "phone", "url",
	"jsonb", "uuid", "money",
])

_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")


@dataclass
class CustomFieldDef:
	"""Definition of a single extra column added to a model at runtime."""

	name: str
	type: str
	label: str = ""
	required: bool = False
	nullable: bool = True
	max_length: int | None = None
	default: Any = None
	choices: list[str] = field(default_factory=list)		# for select / multiselect
	validators: list[dict] = field(default_factory=list)
	visible_on: list[str] = field(default_factory=lambda: ["list", "detail", "form"])

	def __post_init__(self) -> None:
		# Derive label from name when not supplied
		if not self.label:
			self.label = self.name.replace("_", " ").title()

		if self.type not in SUPPORTED_FIELD_TYPES:
			raise ValueError(
				f"Unsupported field type: {self.type!r}. "
				f"Supported: {sorted(SUPPORTED_FIELD_TYPES)}"
			)

		# Enforce snake_case *before* prefixing so the raw name is validated
		raw = self.name.removeprefix("custom_")
		if not _NAME_RE.match(raw):
			raise ValueError(f"Field name must be snake_case: {self.name!r}")

		# Ensure the custom_ prefix
		if not self.name.startswith("custom_"):
			self.name = f"custom_{self.name}"

		# select/multiselect must have choices
		if self.type in ("select", "multiselect") and not self.choices:
			log.warning(
				"Field %r has type %r but no choices defined — it will accept any value.",
				self.name, self.type,
			)

	# Convenience ─────────────────────────────────────────────────────────────

	@property
	def is_required(self) -> bool:
		return self.required

	@property
	def show_on_list(self) -> bool:
		return "list" in self.visible_on

	@property
	def show_on_form(self) -> bool:
		return "form" in self.visible_on

	@property
	def show_on_detail(self) -> bool:
		return "detail" in self.visible_on


@dataclass
class CustomFilterDef:
	"""Definition of an extra search filter surfaced in a model's list view."""

	field: str
	label: str = ""
	type: str = "string"		# string | select | date_range | number_range
	choices_from: str | None = None		# "ModelName.field_name" for dynamic choices

	def __post_init__(self) -> None:
		if not self.label:
			self.label = self.field.replace("_", " ").title()


@dataclass
class ModuleCustomization:
	"""All customizations for one (module_path, model_name) pair."""

	module_path: str			# e.g. "pgappforge.plugins.fintech.sacco"
	model_name: str				# e.g. "Member"
	extra_fields: list[CustomFieldDef] = field(default_factory=list)
	extra_filters: list[CustomFilterDef] = field(default_factory=list)
	extra_list_columns: list[str] = field(default_factory=list)
	hide_list_columns: list[str] = field(default_factory=list)

	@property
	def qualified_name(self) -> str:
		return f"{self.module_path}.{self.model_name}"


# ---------------------------------------------------------------------------
# YAML loading
# ---------------------------------------------------------------------------

def _parse_field(f_data: dict, source: str) -> CustomFieldDef | None:
	"""Parse one field dict from YAML, returning None on error."""
	try:
		known = CustomFieldDef.__dataclass_fields__
		return CustomFieldDef(**{k: v for k, v in f_data.items() if k in known})
	except Exception as exc:
		log.warning("custom_fields/%s: field error: %s (data=%r)", source, exc, f_data)
		return None


def _parse_filter(flt_data: dict) -> CustomFilterDef:
	known = CustomFilterDef.__dataclass_fields__
	return CustomFilterDef(**{k: v for k, v in flt_data.items() if k in known})


def load_customizations(directory: str | Path = "custom_fields") -> list[ModuleCustomization]:
	"""Load all ``*.yaml`` files from *directory* and return parsed customizations.

	Safe to call at startup — missing directory returns an empty list without
	raising.  Malformed files are logged and skipped.

	Parameters
	----------
	directory:
		Path to the directory containing citizen-developer YAML files.
		Defaults to ``custom_fields/`` relative to the working directory.
	"""
	directory = Path(directory)
	if not directory.exists():
		log.debug("citizen_dev: directory %s not found — skipping", directory)
		return []

	result: list[ModuleCustomization] = []

	for yaml_path in sorted(directory.glob("*.yaml")):
		try:
			data = yaml.safe_load(yaml_path.read_text())
			if not data:
				log.debug("citizen_dev: %s is empty — skipping", yaml_path.name)
				continue

			fields: list[CustomFieldDef] = []
			for f_data in data.get("extra_fields", []):
				fd = _parse_field(f_data, yaml_path.name)
				if fd is not None:
					fields.append(fd)

			filters: list[CustomFilterDef] = [
				_parse_filter(flt) for flt in data.get("extra_filters", [])
			]

			cust = ModuleCustomization(
				module_path=data.get("module_path", ""),
				model_name=data.get("model_name", ""),
				extra_fields=fields,
				extra_filters=filters,
				extra_list_columns=data.get("extra_list_columns", []),
				hide_list_columns=data.get("hide_list_columns", []),
			)
			result.append(cust)
			log.info(
				"citizen_dev: loaded %s — %d field(s) for %s",
				yaml_path.name, len(fields), cust.qualified_name,
			)

		except Exception as exc:
			log.warning("citizen_dev: failed to load %s: %s", yaml_path, exc)

	return result


__all__ = [
	"SUPPORTED_FIELD_TYPES",
	"CustomFieldDef",
	"CustomFilterDef",
	"ModuleCustomization",
	"load_customizations",
]
