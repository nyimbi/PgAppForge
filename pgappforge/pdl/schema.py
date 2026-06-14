from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import importlib
import re
import logging

import yaml

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Field-type registry
# (fab_type, sa_expression)
# ---------------------------------------------------------------------------
FIELD_TYPES: dict[str, tuple[str, str]] = {
	"string":     ("String(255)",           "sa.String(255)"),
	"text":       ("Text",                  "sa.Text()"),
	"integer":    ("Integer",               "sa.Integer()"),
	"biginteger": ("BigInteger",            "sa.BigInteger()"),
	"money":      ("BigInteger",            "sa.BigInteger()"),   # always cents
	"float":      ("Float",                 "sa.Float()"),
	"decimal":    ("Numeric(18,4)",         "sa.Numeric(18,4)"),
	"boolean":    ("Boolean",               "sa.Boolean()"),
	"date":       ("Date",                  "sa.Date()"),
	"datetime":   ("DateTime(timezone=True)", "sa.DateTime(timezone=True)"),
	"uuid":       ("String(36)",            "sa.String(36)"),
	"jsonb":      ("JSONB",                 "JSONB()"),
	"enum":       ("String(50)",            "sa.String(50)"),    # VARCHAR; use choices for validation
	"phone":      ("String(30)",            "sa.String(30)"),
	"email":      ("String(255)",           "sa.String(255)"),
	"url":        ("String(500)",           "sa.String(500)"),
}

_VALID_FIELD_NAME = re.compile(r'^[a-z][a-z0-9_]*$')
_VALID_ENTITY_NAME = re.compile(r'^[A-Z][A-Za-z0-9]*$')
_VALID_TABLE_NAME  = re.compile(r'^[a-z][a-z0-9_]*$')


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class PDLField:
	name:      str
	type:      str
	required:  bool       = False
	nullable:  bool       = True
	unique:    bool       = False
	indexed:   bool       = False
	default:   str | None = None
	max_length: int | None = None
	choices:   list[str]  = field(default_factory=list)
	fk:        str | None = None    # "OtherModel.id" → ForeignKey
	label:     str        = ""
	help_text: str        = ""

	def __post_init__(self) -> None:
		if not self.label:
			self.label = self.name.replace("_", " ").title()
		if not _VALID_FIELD_NAME.match(self.name):
			raise ValueError(
				f"Field name must be snake_case (got '{self.name}'). "
				"Use only lowercase letters, digits and underscores, starting with a letter."
			)
		if self.fk is None and self.type not in FIELD_TYPES:
			raise ValueError(
				f"Unknown field type '{self.type}' for field '{self.name}'. "
				f"Valid types: {sorted(FIELD_TYPES)}"
			)


@dataclass
class PDLEntity:
	name:   str                    # PascalCase model name, e.g. "SupplierInvoice"
	table:  str                    # snake_case table name,  e.g. "fin_supplier_invoice"
	fields: list[PDLField]         = field(default_factory=list)
	module_path:              str  = ""
	description:              str  = ""
	include_tenant_id:        bool = True
	include_audit_timestamps: bool = True
	include_uuid_pk:          bool = True
	generate: list[str]            = field(default_factory=lambda: ["model", "migration", "view", "api", "tests"])
	workflows: list[str]           = field(default_factory=list)
	extends:   str | None          = None   # dotted import path or plain entity name

	def __post_init__(self) -> None:
		if not _VALID_ENTITY_NAME.match(self.name):
			raise ValueError(
				f"Entity name must be PascalCase (got '{self.name}'). "
				"Example: 'SupplierInvoice'."
			)
		if not _VALID_TABLE_NAME.match(self.table):
			raise ValueError(
				f"Table name must be snake_case (got '{self.table}'). "
				"Example: 'fin_supplier_invoice'."
			)

	def resolve_parent_fields(self) -> list[PDLField]:
		"""Return PDLField objects for columns inherited from the parent class.

		- If ``extends`` is None, returns ``[]``.
		- If ``extends`` is a dotted path (contains "."), imports the module,
		  loads the class, and introspects ``__table__.columns`` using the same
		  logic as :func:`pgappforge.pdl.inspector._inspect_model`.
		- If ``extends`` is a plain name (no dot), returns ``[]``; the caller
		  is responsible for resolving the name within the same PDLSchema.
		"""
		if not self.extends:
			return []
		if "." not in self.extends:
			# plain name — intra-schema resolution is the caller's job
			return []

		module_path, class_name = self.extends.rsplit(".", 1)
		try:
			mod = importlib.import_module(module_path)
		except ImportError as exc:
			log.warning("PDLEntity.resolve_parent_fields: cannot import %r: %s", module_path, exc)
			return []

		model_cls = getattr(mod, class_name, None)
		if model_cls is None:
			log.warning("PDLEntity.resolve_parent_fields: %r not found in %r", class_name, module_path)
			return []

		table = getattr(model_cls, "__table__", None)
		if table is None:
			log.warning("PDLEntity.resolve_parent_fields: %r has no __table__", class_name)
			return []

		_SA_TYPE_MAP: dict[str, str] = {
			"String": "string", "Text": "text", "Integer": "integer",
			"BigInteger": "integer", "Numeric": "decimal", "Float": "float",
			"Boolean": "boolean", "Date": "date", "DateTime": "datetime",
			"JSONB": "jsonb", "JSON": "jsonb",
		}

		_SKIP = {"id", "tenant_id", "created_at", "updated_at"}

		parent_fields: list[PDLField] = []
		for col in table.columns:
			if col.name in _SKIP:
				continue
			sa_type_name = type(col.type).__name__
			pdl_type = _SA_TYPE_MAP.get(sa_type_name, "string")

			fk_target: str | None = None
			if col.foreign_keys:
				fk = next(iter(col.foreign_keys))
				fk_target = fk.target_fullname

			max_len: int | None = getattr(col.type, "length", None)

			try:
				pf = PDLField(
					name=col.name,
					type=pdl_type,
					nullable=bool(col.nullable),
					unique=bool(col.unique),
					indexed=bool(col.index),
					fk=fk_target,
					max_length=max_len,
				)
				parent_fields.append(pf)
			except ValueError as exc:
				log.warning("PDLEntity.resolve_parent_fields: skipping column %r: %s", col.name, exc)

		return parent_fields

	def all_fields(self) -> list[PDLField]:
		"""Return parent fields merged with local fields.

		Local fields shadow parent fields with the same name, allowing selective
		overrides without repeating unchanged columns.
		"""
		parent = self.resolve_parent_fields()
		local_names = {f.name for f in self.fields}
		merged = [pf for pf in parent if pf.name not in local_names]
		merged.extend(self.fields)
		return merged


@dataclass
class PDLSchema:
	version:   str             = "1.0"
	namespace: str             = ""
	entities:  list[PDLEntity] = field(default_factory=list)

	# ------------------------------------------------------------------
	# Factory methods
	# ------------------------------------------------------------------

	@classmethod
	def from_yaml(cls, path: str | Path) -> "PDLSchema":
		"""Parse a PDL YAML file into a :class:`PDLSchema`."""
		raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
		if not isinstance(raw, dict):
			raise ValueError(f"PDL YAML must be a mapping at the top level: {path}")
		return cls.from_dict(raw)

	@classmethod
	def from_dict(cls, data: dict) -> "PDLSchema":
		"""Construct a :class:`PDLSchema` from a plain Python dict."""
		schema = cls(
			version=str(data.get("version", "1.0")),
			namespace=data.get("namespace", ""),
		)

		for ent_data in data.get("entities", []):
			fields: list[PDLField] = []
			for f_data in ent_data.get("fields", []):
				# Keep only keys that PDLField accepts
				known = {k: v for k, v in f_data.items() if k in PDLField.__dataclass_fields__}
				try:
					fields.append(PDLField(**known))
				except Exception as exc:
					raise ValueError(
						f"Entity '{ent_data.get('name', '?')}' field error: {exc}"
					) from exc

			module_path = ent_data.get(
				"module_path",
				(schema.namespace + "." + _snake(ent_data["name"])) if schema.namespace else "",
			)

			entity = PDLEntity(
				name=ent_data["name"],
				table=ent_data["table"],
				fields=fields,
				module_path=module_path,
				description=ent_data.get("description", ""),
				include_tenant_id=ent_data.get("include_tenant_id", True),
				include_audit_timestamps=ent_data.get("include_audit_timestamps", True),
				include_uuid_pk=ent_data.get("include_uuid_pk", True),
				generate=ent_data.get("generate", ["model", "migration", "view", "api", "tests"]),
				workflows=ent_data.get("workflows", []),
				extends=ent_data.get("extends", None),
			)
			schema.entities.append(entity)

		return schema


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _snake(name: str) -> str:
	"""Convert PascalCase to snake_case.  'SupplierInvoice' → 'supplier_invoice'."""
	return re.sub(r'([A-Z])', lambda m: '_' + m.group(1).lower(), name).lstrip('_')


__all__ = ["PDLSchema", "PDLEntity", "PDLField", "FIELD_TYPES", "_snake"]
