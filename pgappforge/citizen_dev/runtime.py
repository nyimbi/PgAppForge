"""
pgappforge/citizen_dev/runtime.py

Runtime application of citizen-dev customizations.

Applies custom field definitions to live PostgreSQL tables via ``ALTER TABLE
… ADD COLUMN IF NOT EXISTS`` at application startup — after all SQLAlchemy
models are registered but before the first request is served.

Design constraints
------------------
- Idempotent: safe to call multiple times (IF NOT EXISTS guard).
- Non-destructive: never drops or renames columns.
- PostgreSQL-only: uses JSONB, TIMESTAMPTZ, gen_random_uuid().
- Metadata table ``pgaf_custom_field`` stores field definitions for the
  management UI (citizen_dev.views) and future migrations.

Call order in your app factory
-------------------------------
::

    from pgappforge.citizen_dev.runtime import (
        create_custom_field_tables,
        apply_customizations,
    )

    with app.app_context():
        create_custom_field_tables(engine)   # once, idempotent
        apply_customizations(engine)         # reads custom_fields/*.yaml
"""
from __future__ import annotations

import json
import logging
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from pgappforge.citizen_dev.config import (
	CustomFieldDef,
	ModuleCustomization,
	load_customizations,
)

log = logging.getLogger(__name__)

# Module-level registry so the management UI can inspect what was applied
_applied_customizations: list[ModuleCustomization] = []


# ---------------------------------------------------------------------------
# Type mapping helpers
# ---------------------------------------------------------------------------

def _field_type_to_sa_type(field_def: CustomFieldDef) -> Any:
	"""Return the SQLAlchemy column type for a given :class:`CustomFieldDef`."""
	type_map: dict[str, Any] = {
		"string":		sa.String(field_def.max_length or 255),
		"text":			sa.Text(),
		"integer":		sa.Integer(),
		"float":		sa.Float(),
		"boolean":		sa.Boolean(),
		"date":			sa.Date(),
		"datetime":		sa.DateTime(timezone=True),
		"decimal":		sa.Numeric(precision=18, scale=4),
		"email":		sa.String(255),
		"phone":		sa.String(30),
		"url":			sa.String(500),
		"jsonb":		JSONB(),
		"uuid":			sa.String(36),
		"money":		sa.BigInteger(),	# always integer cents
		"select":		sa.String(100),
		"multiselect":	JSONB(),			# stored as JSONB array
	}
	return type_map.get(field_def.type, sa.String(255))


def _sa_type_to_ddl(col_type: Any) -> str:
	"""Convert a SQLAlchemy type object to a PostgreSQL DDL type string."""
	class_name = type(col_type).__name__.upper()
	handlers: dict[str, Any] = {
		"VARCHAR":	lambda t: f"VARCHAR({t.length or 255})",
		"STRING":	lambda t: f"VARCHAR({t.length or 255})",
		"TEXT":		lambda _: "TEXT",
		"INTEGER":	lambda _: "INTEGER",
		"BIGINTEGER": lambda _: "BIGINT",
		"BIGINT":	lambda _: "BIGINT",
		"FLOAT":	lambda _: "DOUBLE PRECISION",
		"BOOLEAN":	lambda _: "BOOLEAN",
		"DATE":		lambda _: "DATE",
		"DATETIME":	lambda _: "TIMESTAMPTZ",
		"NUMERIC":	lambda t: f"NUMERIC({t.precision},{t.scale})",
		"JSONB":	lambda _: "JSONB",
	}
	handler = handlers.get(class_name, lambda _: "TEXT")
	return handler(col_type)


def _format_default(default: Any) -> str:
	"""Render a Python default value as a SQL literal."""
	if isinstance(default, str):
		escaped = default.replace("'", "''")
		return f"'{escaped}'"
	if isinstance(default, bool):
		return "TRUE" if default else "FALSE"
	if default is None:
		return "NULL"
	return str(default)


# ---------------------------------------------------------------------------
# Model → table name resolution
# ---------------------------------------------------------------------------

def _resolve_table_name(module_path: str, model_name: str) -> str | None:
	"""Import ``{module_path}.models`` and return ``Model.__tablename__``.

	Returns None (logged at DEBUG) rather than raising so a missing/broken
	plugin doesn't abort the whole startup.
	"""
	candidates = [
		f"{module_path}.models",
		module_path,
	]
	for mod_path in candidates:
		try:
			import importlib
			mod = importlib.import_module(mod_path)
			model_cls = getattr(mod, model_name, None)
			if model_cls is not None and hasattr(model_cls, "__tablename__"):
				return model_cls.__tablename__
		except Exception as exc:
			log.debug("citizen_dev: cannot import %s: %s", mod_path, exc)
	return None


# ---------------------------------------------------------------------------
# Metadata table DDL
# ---------------------------------------------------------------------------

_CREATE_METADATA_TABLE = """
CREATE TABLE IF NOT EXISTS pgaf_custom_field (
	id			TEXT		PRIMARY KEY DEFAULT gen_random_uuid()::text,
	table_name	VARCHAR(100)	NOT NULL,
	field_name	VARCHAR(100)	NOT NULL,
	field_type	VARCHAR(30)		NOT NULL,
	label		VARCHAR(200),
	required	BOOLEAN			DEFAULT FALSE,
	nullable	BOOLEAN			DEFAULT TRUE,
	max_length	INTEGER,
	choices		JSONB			DEFAULT '[]',
	validators	JSONB			DEFAULT '[]',
	visible_on	JSONB			DEFAULT '["list","detail","form"]',
	created_at	TIMESTAMPTZ		DEFAULT NOW(),
	UNIQUE (table_name, field_name)
)
"""


def create_custom_field_tables(engine: Any) -> None:
	"""Create the ``pgaf_custom_field`` metadata table if it doesn't exist.

	Call once in the app factory before :func:`apply_customizations`.
	Idempotent (``CREATE TABLE IF NOT EXISTS``).
	"""
	with engine.begin() as conn:
		conn.execute(sa.text(_CREATE_METADATA_TABLE))
	log.debug("citizen_dev: pgaf_custom_field table ensured")


# ---------------------------------------------------------------------------
# Metadata persistence
# ---------------------------------------------------------------------------

def _store_field_metadata(conn: Any, table_name: str, field_def: CustomFieldDef) -> None:
	"""Upsert field metadata into ``pgaf_custom_field``.

	Failure is silently swallowed — the metadata row is informational only;
	the actual column has already been added.
	"""
	try:
		conn.execute(sa.text("""
			INSERT INTO pgaf_custom_field
				(id, table_name, field_name, field_type, label, required, nullable,
				 max_length, choices, validators, visible_on, created_at)
			VALUES
				(gen_random_uuid()::text, :tbl, :fname, :ftype, :label,
				 :required, :nullable, :max_len,
				 :choices::jsonb, :validators::jsonb, :visible_on::jsonb,
				 NOW())
			ON CONFLICT (table_name, field_name) DO UPDATE
				SET label		= EXCLUDED.label,
					field_type	= EXCLUDED.field_type,
					required	= EXCLUDED.required,
					nullable	= EXCLUDED.nullable
		"""), {
			"tbl":		table_name,
			"fname":	field_def.name,
			"ftype":	field_def.type,
			"label":	field_def.label,
			"required":	field_def.required,
			"nullable":	field_def.nullable,
			"max_len":	field_def.max_length,
			"choices":	json.dumps(field_def.choices),
			"validators": json.dumps(field_def.validators),
			"visible_on": json.dumps(field_def.visible_on),
		})
	except Exception as exc:
		log.debug("citizen_dev: metadata upsert skipped: %s", exc)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def apply_customizations(
	engine: Any,
	customizations: list[ModuleCustomization] | None = None,
	custom_fields_dir: str = "custom_fields",
) -> int:
	"""Apply custom field definitions to the live database.

	For each :class:`~pgappforge.citizen_dev.config.CustomFieldDef`:

	1. Resolve the model's ``__tablename__`` via dynamic import.
	2. Check ``information_schema.columns`` — skip if column already exists.
	3. Execute ``ALTER TABLE … ADD COLUMN IF NOT EXISTS …``.
	4. Upsert field metadata into ``pgaf_custom_field``.

	Parameters
	----------
	engine:
		SQLAlchemy engine connected to the target PostgreSQL database.
	customizations:
		Pre-parsed list.  When *None* (default), calls
		:func:`~pgappforge.citizen_dev.config.load_customizations` with
		*custom_fields_dir*.
	custom_fields_dir:
		Directory to scan when *customizations* is None.

	Returns
	-------
	int
		Number of columns actually added (existing ones are skipped).
	"""
	if customizations is None:
		customizations = load_customizations(custom_fields_dir)

	added = 0

	with engine.begin() as conn:
		for cust in customizations:
			table_name = _resolve_table_name(cust.module_path, cust.model_name)
			if not table_name:
				log.warning(
					"citizen_dev: cannot resolve table for %s — skipping",
					cust.qualified_name,
				)
				continue

			for field_def in cust.extra_fields:
				try:
					# Check whether column already exists
					row = conn.execute(sa.text("""
						SELECT column_name
						FROM information_schema.columns
						WHERE table_schema = 'public'
						  AND table_name   = :tbl
						  AND column_name  = :col
					"""), {"tbl": table_name, "col": field_def.name}).fetchone()

					if row:
						log.debug(
							"citizen_dev: %s.%s already exists — skipping",
							table_name, field_def.name,
						)
						continue

					# Build DDL
					col_type = _field_type_to_sa_type(field_def)
					type_ddl = _sa_type_to_ddl(col_type)
					null_fragment = "" if field_def.nullable else " NOT NULL"
					default_fragment = (
						f" DEFAULT {_format_default(field_def.default)}"
						if field_def.default is not None
						else ""
					)
					ddl = (
						f"ALTER TABLE {table_name} "
						f"ADD COLUMN IF NOT EXISTS {field_def.name} "
						f"{type_ddl}{null_fragment}{default_fragment}"
					)
					conn.execute(sa.text(ddl))
					_store_field_metadata(conn, table_name, field_def)

					added += 1
					log.info(
						"citizen_dev: added column %s.%s (%s)",
						table_name, field_def.name, type_ddl,
					)

				except Exception as exc:
					log.warning(
						"citizen_dev: failed to add %s.%s: %s",
						cust.model_name, field_def.name, exc,
					)

	_applied_customizations.extend(customizations)
	return added


def get_applied_customizations() -> list[ModuleCustomization]:
	"""Return a snapshot of all customizations applied in this process."""
	return list(_applied_customizations)


__all__ = [
	"apply_customizations",
	"create_custom_field_tables",
	"get_applied_customizations",
]
