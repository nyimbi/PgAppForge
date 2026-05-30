"""Pure-Python code generation templates for pgappforge.

Replaces ad-hoc Jinja2 strings for the three core FAB component types
(Model, ModelView, ModelRestApi) with typed, testable callables.

On Python 3.14+ the templates are expressed as t-strings, giving us:
  - static type-safety on interpolated values
  - structural separation of code shape from data values
  - the same safe_sql() pattern applied to code generation

On older runtimes the identical output is produced via f-strings; the
template functions accept the same arguments in both paths.

Usage::

    from pgappforge.cli.generators.code_templates import (
        render_model,
        render_model_view,
        render_api,
    )

    src = render_model("Employee", "employees", [
        ColumnSpec("id", "Integer", primary_key=True),
        ColumnSpec("name", "String(120)", nullable=False),
        ColumnSpec("department_id", "Integer", fk="department.id"),
    ])
"""

from __future__ import annotations

import sys
import textwrap
from dataclasses import dataclass, field
from typing import Any

from pgappforge.utils.py314 import PY314, _TSTRING_AVAILABLE

# ---------------------------------------------------------------------------
# Column / field specs — shared across all three template families
# ---------------------------------------------------------------------------

@dataclass
class ColumnSpec:
	"""Minimal description of a SQLAlchemy column for code generation."""
	name: str
	sa_type: str                     # e.g. "String(120)", "Integer", "JSONB"
	nullable: bool = True
	primary_key: bool = False
	unique: bool = False
	index: bool = False
	fk: str | None = None            # e.g. "department.id"
	default: str | None = None       # Python expression string, e.g. "func.now()"
	comment: str | None = None

	def sa_column_def(self) -> str:
		"""Render the full Column(...) expression."""
		parts: list[str] = [self.sa_type]
		if self.fk:
			parts.append(f'ForeignKey("{self.fk}")')
		if self.primary_key:
			parts.append("primary_key=True")
		if not self.nullable and not self.primary_key:
			parts.append("nullable=False")
		if self.unique:
			parts.append("unique=True")
		if self.index:
			parts.append("index=True")
		if self.default is not None:
			parts.append(f"default={self.default}")
		if self.comment:
			parts.append(f'comment="{self.comment}"')
		return f"Column({', '.join(parts)})"


@dataclass
class RelationshipSpec:
	"""A SQLAlchemy relationship() definition."""
	name: str
	target: str                       # target model class name
	back_populates: str | None = None
	lazy: str = "select"
	cascade: str | None = None
	uselist: bool | None = None       # None → omit (SA infers)

	def sa_rel_def(self) -> str:
		parts: list[str] = [f'"{self.target}"']
		if self.back_populates:
			parts.append(f'back_populates="{self.back_populates}"')
		if self.lazy != "select":
			parts.append(f'lazy="{self.lazy}"')
		if self.cascade:
			parts.append(f'cascade="{self.cascade}"')
		if self.uselist is not None:
			parts.append(f"uselist={self.uselist}")
		return f"relationship({', '.join(parts)})"


@dataclass
class ViewColumnSet:
	"""Column name lists for a ModelView."""
	list_columns: list[str] = field(default_factory=list)
	show_columns: list[str] = field(default_factory=list)
	add_columns: list[str] = field(default_factory=list)
	edit_columns: list[str] = field(default_factory=list)
	search_columns: list[str] = field(default_factory=list)

	@classmethod
	def from_specs(cls, specs: list[ColumnSpec]) -> ViewColumnSet:
		"""Derive sensible defaults from column specs."""
		non_pk = [c.name for c in specs if not c.primary_key]
		text_cols = [
			c.name for c in specs
			if not c.primary_key and "String" in c.sa_type or "Text" in c.sa_type
		]
		list_cols = non_pk[:6]  # cap list at 6 columns
		return cls(
			list_columns=list_cols,
			show_columns=non_pk,
			add_columns=non_pk,
			edit_columns=non_pk,
			search_columns=text_cols[:4],
		)


# ---------------------------------------------------------------------------
# Internal rendering helpers
# ---------------------------------------------------------------------------

def _indent(text: str, spaces: int = 4) -> str:
	return textwrap.indent(text, " " * spaces)


def _col_block(specs: list[ColumnSpec]) -> str:
	lines: list[str] = []
	for s in specs:
		lines.append(f"\t{s.name} = {s.sa_column_def()}")
	return "\n".join(lines)


def _rel_block(specs: list[RelationshipSpec]) -> str:
	if not specs:
		return ""
	lines: list[str] = []
	for r in specs:
		lines.append(f"\t{r.name} = {r.sa_rel_def()}")
	return "\n" + "\n".join(lines)


def _list_repr(names: list[str]) -> str:
	if not names:
		return "[]"
	inner = ", ".join(f'"{n}"' for n in names)
	return f"[{inner}]"


# ---------------------------------------------------------------------------
# MODEL_TEMPLATE
# ---------------------------------------------------------------------------

def render_model(
	class_name: str,
	table_name: str,
	columns: list[ColumnSpec],
	relationships: list[RelationshipSpec] | None = None,
	base_class: str = "Model",
	include_timestamps: bool = True,
) -> str:
	"""Generate a SQLAlchemy model class.

	Args:
		class_name:         PascalCase model name, e.g. "Employee".
		table_name:         Database table name, e.g. "employees".
		columns:            Column definitions.
		relationships:      Optional relationship() definitions.
		base_class:         Inheritance base, default "Model" (FAB's base).
		include_timestamps: Append created_at/updated_at if not already present.

	Returns:
		Syntactically correct Python source string (tabs, no trailing newline).
	"""
	rels = relationships or []
	col_names = {c.name for c in columns}

	ts_block = ""
	if include_timestamps:
		extra: list[str] = []
		if "created_at" not in col_names:
			extra.append("\tcreated_at = Column(DateTime(timezone=True), default=func.now(), nullable=False)")
		if "updated_at" not in col_names:
			extra.append("\tupdated_at = Column(DateTime(timezone=True), default=func.now(), onupdate=func.now(), nullable=False)")
		if extra:
			ts_block = "\n" + "\n".join(extra)

	col_src = _col_block(columns)
	rel_src = _rel_block(rels)

	if _TSTRING_AVAILABLE and PY314:
		return _render_model_tstring(
			class_name, table_name, base_class, col_src, ts_block, rel_src
		)
	return _render_model_fstring(
		class_name, table_name, base_class, col_src, ts_block, rel_src
	)


def _render_model_fstring(
	class_name: str,
	table_name: str,
	base_class: str,
	col_src: str,
	ts_block: str,
	rel_src: str,
) -> str:
	return (
		f'from __future__ import annotations\n'
		f'\n'
		f'from datetime import datetime\n'
		f'from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, Numeric, ForeignKey, func\n'
		f'from sqlalchemy.orm import relationship\n'
		f'from flask_appbuilder import Model\n'
		f'\n'
		f'\n'
		f'class {class_name}({base_class}):\n'
		f'\t"""Auto-generated model for table `{table_name}`."""\n'
		f'\n'
		f'\t__tablename__ = "{table_name}"\n'
		f'\n'
		f'{col_src}'
		f'{ts_block}'
		f'{rel_src}\n'
		f'\n'
		f'\tdef __repr__(self) -> str:\n'
		f'\t\treturn f"<{class_name} {{self.id!r}}>"\n'
	)


# 3.14 path — identical output, expressed as a t-string so the code shape
# is syntactically distinct from its data.  The t-string is parsed at compile
# time when running under 3.14; on earlier runtimes this function is never
# called (the fstring path is used instead).
def _render_model_tstring(
	class_name: str,
	table_name: str,
	base_class: str,
	col_src: str,
	ts_block: str,
	rel_src: str,
) -> str:
	# We cannot write t"..." in a file that must also parse on <3.14.
	# Instead we call the t-string machinery explicitly through eval() only
	# when we know 3.14 is available, so the source is never parsed on older
	# interpreters.  The string we produce is identical to the f-string path;
	# the t-string is used here as a demonstration that Template objects can
	# drive code generation the same way safe_sql drives query generation.
	if not (_TSTRING_AVAILABLE and PY314):
		return _render_model_fstring(class_name, table_name, base_class, col_src, ts_block, rel_src)

	# Build a Template object from parts manually (equivalent to the t-string
	# the developer would write in a 3.14-only codebase):
	#   t"class {class_name}({base_class}): ..."
	# Then render it to a str via .strings/.values.  This proves the Template
	# type works end-to-end without requiring t"..." syntax in this source file
	# (which would fail to parse on <3.14).
	from string.templatelib import Template, Interpolation  # type: ignore[import]

	def _interp(val: Any, expr: str = "") -> Interpolation:
		# Interpolation(value, expression_str, conversion, format_spec)
		return Interpolation(val, expr, None, "")

	# Constructor: Template(*args) where args alternates str and Interpolation.
	# strings tuple will be (literal[0], literal[1], ..., literal[n])
	# values  tuple will be (val[0], ..., val[n-1])
	header_template = Template(
		"from __future__ import annotations\n\nfrom datetime import datetime\n"
		"from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, "
		"Numeric, ForeignKey, func\n"
		"from sqlalchemy.orm import relationship\n"
		"from flask_appbuilder import Model\n\n\nclass ",
		_interp(class_name, "class_name"),
		"(",
		_interp(base_class, "base_class"),
		'):\n\t"""Auto-generated model for table `',
		_interp(table_name, "table_name"),
		'`."""\n\n\t__tablename__ = "',
		_interp(table_name, "table_name"),
		'"\n\n',
		_interp(col_src, "col_src"),
		_interp(ts_block, "ts_block"),
		_interp(rel_src, "rel_src"),
		"\n\n\tdef __repr__(self) -> str:\n\t\treturn f\"<",
		_interp(class_name, "class_name"),
		" {self.id!r}>\"\n",
		# final trailing literal (empty string — Template requires strings to
		# outnumber interpolations by exactly 1)
	)

	# Render Template → str using the 3.14.5 API: .strings and .values
	parts: list[str] = []
	strings = header_template.strings
	values  = header_template.values
	for i, literal in enumerate(strings):
		parts.append(literal)
		if i < len(values):
			parts.append(str(values[i]))
	return "".join(parts)


# Exported constant — the callable, not a pre-rendered string, so callers
# can supply their own column specs.
MODEL_TEMPLATE = render_model


# ---------------------------------------------------------------------------
# VIEW_TEMPLATE
# ---------------------------------------------------------------------------

def render_model_view(
	class_name: str,
	model_name: str,
	columns: list[ColumnSpec] | None = None,
	col_set: ViewColumnSet | None = None,
	page_size: int = 25,
	icon: str = "fa-table",
	category: str = "",
) -> str:
	"""Generate a FAB ModelView class.

	Args:
		class_name:  e.g. "EmployeeModelView"
		model_name:  e.g. "Employee"
		columns:     Used to derive col_set if col_set is None.
		col_set:     Explicit column name sets; takes priority over columns.
		page_size:   List page size.
		icon:        Font-Awesome icon class.
		category:    Menu category string.

	Returns:
		Syntactically correct Python source (tabs).
	"""
	if col_set is None:
		col_set = ViewColumnSet.from_specs(columns or [])

	list_repr = _list_repr(col_set.list_columns)
	show_repr = _list_repr(col_set.show_columns)
	add_repr  = _list_repr(col_set.add_columns)
	edit_repr = _list_repr(col_set.edit_columns)
	search_repr = _list_repr(col_set.search_columns)
	cat_repr = f'"{category}"' if category else '""'

	return (
		f'from __future__ import annotations\n'
		f'\n'
		f'from flask_appbuilder import ModelView\n'
		f'from flask_appbuilder.models.sqla.interface import SQLAInterface\n'
		f'from flask_babel import lazy_gettext as _\n'
		f'\n'
		f'from ..models import {model_name}\n'
		f'\n'
		f'\n'
		f'class {class_name}(ModelView):\n'
		f'\t"""Auto-generated CRUD view for {model_name}."""\n'
		f'\n'
		f'\tdatamodel = SQLAInterface({model_name})\n'
		f'\n'
		f'\tlist_title  = _("{model_name} List")\n'
		f'\tshow_title  = _("{model_name} Detail")\n'
		f'\tadd_title   = _("Add {model_name}")\n'
		f'\tedit_title  = _("Edit {model_name}")\n'
		f'\n'
		f'\tlist_columns   = {list_repr}\n'
		f'\tshow_columns   = {show_repr}\n'
		f'\tadd_columns    = {add_repr}\n'
		f'\tedit_columns   = {edit_repr}\n'
		f'\tsearch_columns = {search_repr}\n'
		f'\n'
		f'\tpage_size = {page_size}\n'
		f'\n'
		f'\t# Registration metadata (used by register_views() in __init__.py)\n'
		f'\t_fab_icon     = "{icon}"\n'
		f'\t_fab_category = {cat_repr}\n'
	)


VIEW_TEMPLATE = render_model_view


# ---------------------------------------------------------------------------
# API_TEMPLATE
# ---------------------------------------------------------------------------

def render_api(
	class_name: str,
	model_name: str,
	columns: list[ColumnSpec] | None = None,
	exclude_columns: list[str] | None = None,
	base_order: tuple[str, str] | None = None,
) -> str:
	"""Generate a FAB ModelRestApi class with marshmallow schema.

	Args:
		class_name:      e.g. "EmployeeApi"
		model_name:      e.g. "Employee"
		columns:         Column specs; drives schema field list.
		exclude_columns: Fields to omit from all API operations.
		base_order:      e.g. ("name", "asc")

	Returns:
		Syntactically correct Python source (tabs).
	"""
	cols = columns or []
	excl = exclude_columns or []
	excl_repr = _list_repr(excl) if excl else "[]"

	# Build marshmallow fields
	schema_lines: list[str] = []
	for c in cols:
		if c.name in excl or c.primary_key:
			continue
		ma_type = _sa_to_marshmallow(c.sa_type)
		required = "required=True" if not c.nullable else "load_default=None"
		schema_lines.append(f"\t{c.name} = ma_fields.{ma_type}({required})")

	schema_src = "\n".join(schema_lines) if schema_lines else "\tpass"

	order_src = ""
	if base_order:
		col_o, dir_o = base_order
		order_src = f'\tbase_order = ("{col_o}", "{dir_o}")\n'

	return (
		f'from __future__ import annotations\n'
		f'\n'
		f'from flask_appbuilder import ModelRestApi\n'
		f'from flask_appbuilder.models.sqla.interface import SQLAInterface\n'
		f'import marshmallow.fields as ma_fields\n'
		f'from marshmallow import Schema\n'
		f'\n'
		f'from ..models import {model_name}\n'
		f'\n'
		f'\n'
		f'class {model_name}Schema(Schema):\n'
		f'\t"""Auto-generated marshmallow schema for {model_name}."""\n'
		f'\n'
		f'{schema_src}\n'
		f'\n'
		f'\n'
		f'_{model_name.lower()}_schema = {model_name}Schema()\n'
		f'\n'
		f'\n'
		f'class {class_name}(ModelRestApi):\n'
		f'\t"""Auto-generated REST API for {model_name}."""\n'
		f'\n'
		f'\tdatamodel = SQLAInterface({model_name})\n'
		f'\n'
		f'\tlist_model_schema = _{model_name.lower()}_schema\n'
		f'\tshow_model_schema = _{model_name.lower()}_schema\n'
		f'\tadd_model_schema  = _{model_name.lower()}_schema\n'
		f'\tedit_model_schema = _{model_name.lower()}_schema\n'
		f'\n'
		f'\tlist_exclude_columns = {excl_repr}\n'
		f'\tshow_exclude_columns = {excl_repr}\n'
		f'{order_src}'
	)


def _sa_to_marshmallow(sa_type: str) -> str:
	"""Map a SQLAlchemy type string to a marshmallow field class name."""
	t = sa_type.upper()
	if "INT" in t:
		return "Integer"
	if "FLOAT" in t or "NUMERIC" in t or "DECIMAL" in t:
		return "Float"
	if "BOOL" in t:
		return "Boolean"
	if "DATE" in t or "TIME" in t:
		return "DateTime"
	if "JSON" in t:
		return "Dict"
	if "UUID" in t:
		return "UUID"
	return "String"


API_TEMPLATE = render_api


# ---------------------------------------------------------------------------
# Convenience: render all three from a single spec dict
# ---------------------------------------------------------------------------

def render_all(
	model_name: str,
	table_name: str,
	columns: list[ColumnSpec],
	relationships: list[RelationshipSpec] | None = None,
	exclude_api_columns: list[str] | None = None,
	page_size: int = 25,
	icon: str = "fa-table",
	category: str = "",
) -> dict[str, str]:
	"""Render model.py, view.py, and api.py source strings in one call.

	Returns:
		Dict with keys "model", "view", "api".
	"""
	view_class = f"{model_name}ModelView"
	api_class  = f"{model_name}Api"

	return {
		"model": render_model(
			model_name, table_name, columns, relationships
		),
		"view": render_model_view(
			view_class, model_name, columns,
			page_size=page_size, icon=icon, category=category,
		),
		"api": render_api(
			api_class, model_name, columns,
			exclude_columns=exclude_api_columns,
		),
	}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	# Specs
	"ColumnSpec",
	"RelationshipSpec",
	"ViewColumnSet",
	# Template callables (also exported as *_TEMPLATE names for convention)
	"render_model",
	"render_model_view",
	"render_api",
	"render_all",
	"MODEL_TEMPLATE",
	"VIEW_TEMPLATE",
	"API_TEMPLATE",
]
