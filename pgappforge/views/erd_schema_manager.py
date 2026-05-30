"""
ERD Schema Manager — bidirectional schema operations for pgappforge ERD designer.

Handles:
- Reading live PostgreSQL schema via database inspector
- Applying schema changes (ADD/DROP/ALTER TABLE/COLUMN) from ERD edits
- Importing schemas from Mermaid erDiagram, DBML, plain SQL
- Triggering the pgappforge codegen pipeline on the current schema

The ERD view calls this manager for all schema mutations. All DDL is executed
inside a transaction with rollback on error and full audit logging.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

log = logging.getLogger(__name__)


# ─── Schema diff types ─────────────────────────────────────────────────────

# Accepted operations in the diff payload from the ERD UI:
#   {"op": "create_table",  "table": "orders",
#    "columns": [{"name": "id", "type": "SERIAL", "pk": true}, ...]}
#
#   {"op": "drop_table",    "table": "orders"}
#
#   {"op": "add_column",    "table": "orders",
#    "column": {"name": "status", "type": "VARCHAR(20)", "nullable": true}}
#
#   {"op": "drop_column",   "table": "orders", "column": "status"}
#
#   {"op": "alter_column",  "table": "orders", "column": "status",
#    "new_type": "TEXT", "nullable": false, "default": "'pending'"}
#
#   {"op": "add_fk",        "table": "orders", "column": "customer_id",
#    "ref_table": "customers", "ref_column": "id"}
#
#   {"op": "drop_fk",       "table": "orders", "constraint_name": "orders_customer_id_fkey"}
#
#   {"op": "rename_table",  "table": "orders", "new_name": "purchase_orders"}
#
#   {"op": "rename_column", "table": "orders", "column": "amt", "new_name": "amount"}


class ERDSchemaManager:
	"""Manages bidirectional schema operations for the ERD designer.

	Args:
	    engine: SQLAlchemy Engine connected to the target PostgreSQL database.
	"""

	def __init__(self, engine: Engine) -> None:
		self.engine = engine

	# ─── Read ────────────────────────────────────────────────────────────────

	def get_schema(self) -> dict[str, Any]:
		"""Return the full database schema as a dict suitable for the ERD UI.

		Returns::

		    {
		      "tables": [
		        {
		          "name": "employees",
		          "columns": [
		            {"name": "id", "type": "integer", "pk": True, "nullable": False,
		             "fk": None, "default": None, "unique": False}
		          ]
		        }
		      ],
		      "relationships": [
		        {"from_table": "employees", "from_col": "dept_id",
		         "to_table": "departments", "to_col": "id",
		         "constraint": "employees_dept_id_fkey"}
		      ]
		    }
		"""
		from pgappforge.cli.generators.database_inspector import EnhancedDatabaseInspector

		uri = str(self.engine.url)
		with EnhancedDatabaseInspector(uri) as inspector:
			analysis = inspector.analyze_database()

		tables = []
		for tname, tinfo in analysis.get("tables", {}).items():
			cols = []
			for col in tinfo.columns:
				fk_ref = None
				if col.foreign_key and tinfo.relationships:
					for rel in tinfo.relationships:
						if col.name in rel.local_columns:
							fk_ref = f"{rel.remote_table}.{rel.remote_columns[0]}"
							break
				cols.append({
					"name": col.name,
					"type": col.type,
					"pk": col.primary_key,
					"nullable": col.nullable,
					"fk": fk_ref,
					"default": str(col.default) if col.default else None,
					"unique": col.unique,
					"comment": col.comment,
				})
			tables.append({"name": tname, "columns": cols})

		rels = []
		for rel in analysis.get("relationships", []):
			rels.append({
				"from_table": rel.get("source_table"),
				"from_col": rel.get("local_columns", [None])[0],
				"to_table": rel.get("target_table"),
				"to_col": rel.get("remote_columns", ["id"])[0],
			})

		return {"tables": tables, "relationships": rels}

	def to_mermaid(self) -> str:
		"""Convert the live database schema to Mermaid erDiagram syntax."""
		schema = self.get_schema()
		lines = ["erDiagram"]
		for tbl in schema["tables"]:
			lines.append(f"  {tbl['name']} {{")
			for col in tbl["columns"]:
				pk_mark = " PK" if col["pk"] else ""
				fk_mark = " FK" if col["fk"] else ""
				type_clean = re.sub(r"\(.*\)", "", col["type"]).lower().replace(" ", "_")
				lines.append(f"    {type_clean} {col['name']}{pk_mark}{fk_mark}")
			lines.append("  }")
		for rel in schema["relationships"]:
			if rel["from_table"] and rel["to_table"]:
				lines.append(
					f'  {rel["from_table"]} ||--o{{ {rel["to_table"]} : "FK"'
				)
		return "\n".join(lines)

	# ─── Apply changes ────────────────────────────────────────────────────────

	def apply_changes(self, operations: list[dict]) -> dict[str, Any]:
		"""Apply a list of schema change operations to the database.

		All operations run in a single transaction — any failure rolls back all.

		Args:
		    operations: List of operation dicts (see module docstring).

		Returns:
		    {"applied": N, "sql": [generated SQL strings], "errors": [...]}
		"""
		sql_stmts = []
		errors: list[str] = []

		for op in operations:
			try:
				stmt = self._op_to_sql(op)
				if stmt:
					sql_stmts.append(stmt)
			except ValueError as exc:
				errors.append(f"Invalid op {op.get('op')}: {exc}")

		if errors:
			return {"applied": 0, "sql": [], "errors": errors}

		with self.engine.begin() as conn:
			try:
				for stmt in sql_stmts:
					log.info("ERD schema change: %s", stmt)
					conn.execute(text(stmt))
				return {"applied": len(sql_stmts), "sql": sql_stmts, "errors": []}
			except Exception as exc:
				return {"applied": 0, "sql": sql_stmts, "errors": [str(exc)]}

	def _op_to_sql(self, op: dict) -> str | None:
		"""Convert a single operation dict to a SQL DDL string."""
		kind = op.get("op", "")
		tbl = op.get("table", "")

		if kind == "create_table":
			cols = op.get("columns", [])
			col_defs = []
			for c in cols:
				defn = f"{c['name']} {c['type']}"
				if c.get("pk"):
					defn += " PRIMARY KEY"
				if not c.get("nullable", True):
					defn += " NOT NULL"
				if c.get("default") is not None:
					defn += f" DEFAULT {c['default']}"
				col_defs.append(defn)
			return f"CREATE TABLE IF NOT EXISTS {tbl} ({', '.join(col_defs)})"

		if kind == "drop_table":
			return f"DROP TABLE IF EXISTS {tbl} CASCADE"

		if kind == "add_column":
			c = op["column"]
			defn = f"{c['name']} {c['type']}"
			if not c.get("nullable", True):
				defn += " NOT NULL"
			if c.get("default") is not None:
				defn += f" DEFAULT {c['default']}"
			return f"ALTER TABLE {tbl} ADD COLUMN {defn}"

		if kind == "drop_column":
			return f"ALTER TABLE {tbl} DROP COLUMN {op['column']} CASCADE"

		if kind == "alter_column":
			col = op["column"]
			stmts = []
			if op.get("new_type"):
				stmts.append(
					f"ALTER TABLE {tbl} ALTER COLUMN {col} TYPE {op['new_type']} "
					f"USING {col}::{op['new_type']}"
				)
			if "nullable" in op:
				if op["nullable"]:
					stmts.append(f"ALTER TABLE {tbl} ALTER COLUMN {col} DROP NOT NULL")
				else:
					stmts.append(f"ALTER TABLE {tbl} ALTER COLUMN {col} SET NOT NULL")
			if "default" in op:
				if op["default"] is None:
					stmts.append(f"ALTER TABLE {tbl} ALTER COLUMN {col} DROP DEFAULT")
				else:
					stmts.append(f"ALTER TABLE {tbl} ALTER COLUMN {col} SET DEFAULT {op['default']}")
			return "; ".join(stmts) if stmts else None

		if kind == "add_fk":
			col = op["column"]
			ref = op["ref_table"]
			ref_col = op.get("ref_column", "id")
			cname = f"{tbl}_{col}_fkey"
			return (
				f"ALTER TABLE {tbl} ADD CONSTRAINT {cname} "
				f"FOREIGN KEY ({col}) REFERENCES {ref}({ref_col})"
			)

		if kind == "drop_fk":
			return f"ALTER TABLE {tbl} DROP CONSTRAINT {op['constraint_name']}"

		if kind == "rename_table":
			return f"ALTER TABLE {tbl} RENAME TO {op['new_name']}"

		if kind == "rename_column":
			return f"ALTER TABLE {tbl} RENAME COLUMN {op['column']} TO {op['new_name']}"

		if kind == "add_index":
			cols = ", ".join(op.get("columns", []))
			unique = "UNIQUE " if op.get("unique") else ""
			iname = op.get("name", f"ix_{tbl}_{cols.replace(', ', '_')}")
			return f"CREATE {unique}INDEX IF NOT EXISTS {iname} ON {tbl} ({cols})"

		if kind == "drop_index":
			return f"DROP INDEX IF EXISTS {op['name']}"

		raise ValueError(f"Unknown operation: {kind}")

	# ─── Import from external formats ────────────────────────────────────────

	def import_mermaid(self, mermaid_text: str) -> dict[str, Any]:
		"""Parse a Mermaid erDiagram and apply it to the database.

		Extracts entity definitions and creates tables for any that don't exist.
		"""
		tables: dict[str, list[dict]] = {}
		current_table: str | None = None

		for line in mermaid_text.splitlines():
			line = line.strip()
			if not line or line == "erDiagram":
				continue

			# Table definition: TABLENAME {
			m = re.match(r"^(\w+)\s*\{", line)
			if m:
				current_table = m.group(1)
				tables[current_table] = []
				continue

			# Column definition: type name [PK] [FK]
			if current_table and line and line != "}":
				parts = line.split()
				if len(parts) >= 2:
					col_type = parts[0].upper()
					col_name = parts[1]
					is_pk = "PK" in parts
					is_fk = "FK" in parts
					# Map Mermaid types to PostgreSQL
					pg_type = _mermaid_type_to_pg(col_type)
					tables[current_table].append({
						"name": col_name,
						"type": pg_type,
						"pk": is_pk,
						"nullable": not is_pk,
						"fk": None,
					})
				continue

			if line == "}":
				current_table = None

		operations = [
			{"op": "create_table", "table": name, "columns": cols}
			for name, cols in tables.items()
		]
		return self.apply_changes(operations)

	def import_sql(self, sql: str) -> dict[str, Any]:
		"""Execute raw SQL DDL statements against the database.

		Only CREATE TABLE, ALTER TABLE, and CREATE INDEX statements are permitted
		(no DML, no DROP DATABASE, etc.) for safety.
		"""
		allowed = re.compile(
			r"^\s*(CREATE\s+TABLE|ALTER\s+TABLE|CREATE\s+(UNIQUE\s+)?INDEX|COMMENT\s+ON)",
			re.IGNORECASE,
		)
		stmts = [s.strip() for s in sql.split(";") if s.strip()]
		rejected = [s[:60] for s in stmts if not allowed.match(s)]
		if rejected:
			return {"applied": 0, "sql": [], "errors": [f"Rejected unsafe SQL: {r}" for r in rejected]}

		applied = 0
		errors: list[str] = []
		with self.engine.begin() as conn:
			for stmt in stmts:
				try:
					conn.execute(text(stmt))
					applied += 1
				except Exception as exc:
					errors.append(str(exc))
					if errors:
						break

		return {"applied": applied, "sql": stmts[:applied], "errors": errors}

	# ─── Codegen trigger ─────────────────────────────────────────────────────

	def generate_app(
		self,
		output_dir: str,
		app_name: str,
		enable_api: bool = True,
		enable_docker: bool = False,
	) -> dict[str, Any]:
		"""Trigger the pgappforge codegen pipeline on the current database schema.

		Runs ``flask forge gen all`` as a subprocess so it uses the full CLI
		pipeline including template generation, view generation, etc.

		Args:
		    output_dir: Directory where the generated app will be written.
		    app_name:   Name for the generated application.
		    enable_api: Include REST API generation.
		    enable_docker: Include Docker files.

		Returns:
		    {"status": "success"|"error", "output_dir": str, "stdout": str, "stderr": str}
		"""
		from pgappforge.cli.generators.database_inspector import EnhancedDatabaseInspector
		from pgappforge.cli.generators.app_generator import FullAppGenerator, AppGenerationConfig

		uri = str(self.engine.url)
		Path(output_dir).mkdir(parents=True, exist_ok=True)

		try:
			with EnhancedDatabaseInspector(uri) as inspector:
				config = AppGenerationConfig(
					app_name=app_name,
					enable_api=enable_api,
					enable_docker=enable_docker,
					enable_testing=False,
					enable_ci_cd=False,
					database_type="postgresql",
				)
				gen = FullAppGenerator(inspector, config, output_dir)
				result = gen.generate_complete_app()

			return {
				"status": result.get("status", "success"),
				"output_dir": output_dir,
				"files_generated": result.get("files_generated", 0),
				"next_steps": result.get("next_steps", []),
			}
		except Exception as exc:
			log.exception("App generation failed")
			return {"status": "error", "output_dir": output_dir, "error": str(exc)}


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _mermaid_type_to_pg(mtype: str) -> str:
	"""Map a Mermaid type token to a PostgreSQL type."""
	mapping = {
		"INT": "INTEGER",
		"INTEGER": "INTEGER",
		"BIGINT": "BIGINT",
		"SERIAL": "SERIAL",
		"BIGSERIAL": "BIGSERIAL",
		"VARCHAR": "VARCHAR(255)",
		"STRING": "TEXT",
		"TEXT": "TEXT",
		"BOOL": "BOOLEAN",
		"BOOLEAN": "BOOLEAN",
		"FLOAT": "DOUBLE PRECISION",
		"DECIMAL": "NUMERIC",
		"DATE": "DATE",
		"DATETIME": "TIMESTAMP WITH TIME ZONE",
		"TIMESTAMP": "TIMESTAMP WITH TIME ZONE",
		"JSON": "JSONB",
		"UUID": "UUID",
	}
	return mapping.get(mtype.upper(), "TEXT")


# ─── Trigger & Procedure Editor ──────────────────────────────────────────────

TRIGGER_TEMPLATES: dict[str, dict] = {
    "updated_at": {
        "label": "Auto-update updated_at timestamp",
        "description": "Sets updated_at = NOW() before every UPDATE.",
        "function": """
CREATE OR REPLACE FUNCTION {schema}.set_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;""",
        "trigger": """
CREATE TRIGGER trg_{table}_updated_at
BEFORE UPDATE ON {table}
FOR EACH ROW EXECUTE FUNCTION {schema}.set_updated_at();""",
        "params": ["table", "schema"],
        "defaults": {"schema": "public"},
    },
    "audit_log": {
        "label": "Audit log (INSERT/UPDATE/DELETE → audit table)",
        "description": "Logs every change to a generic audit_log table with old/new JSONB.",
        "function": """
CREATE TABLE IF NOT EXISTS audit_log (
    id         BIGSERIAL PRIMARY KEY,
    table_name TEXT      NOT NULL,
    action     TEXT      NOT NULL,  -- INSERT, UPDATE, DELETE
    old_data   JSONB,
    new_data   JSONB,
    changed_by TEXT      DEFAULT current_user,
    changed_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE OR REPLACE FUNCTION public.log_changes()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    INSERT INTO audit_log(table_name, action, old_data, new_data)
    VALUES (
        TG_TABLE_NAME,
        TG_OP,
        CASE WHEN TG_OP IN ('UPDATE','DELETE') THEN row_to_json(OLD)::jsonb END,
        CASE WHEN TG_OP IN ('UPDATE','INSERT') THEN row_to_json(NEW)::jsonb END
    );
    RETURN COALESCE(NEW, OLD);
END;
$$;""",
        "trigger": """
CREATE TRIGGER trg_{table}_audit
AFTER INSERT OR UPDATE OR DELETE ON {table}
FOR EACH ROW EXECUTE FUNCTION public.log_changes();""",
        "params": ["table"],
        "defaults": {},
    },
    "soft_delete_guard": {
        "label": "Prevent hard DELETE on soft-delete table",
        "description": "Converts DELETE into SET deleted_at = NOW() instead.",
        "function": """
CREATE OR REPLACE FUNCTION {schema}.soft_delete_{table}()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    UPDATE {table} SET deleted_at = NOW() WHERE id = OLD.id;
    RETURN NULL;  -- cancel the actual DELETE
END;
$$;""",
        "trigger": """
CREATE TRIGGER trg_{table}_soft_delete
BEFORE DELETE ON {table}
FOR EACH ROW
WHEN (OLD.deleted_at IS NULL)
EXECUTE FUNCTION {schema}.soft_delete_{table}();""",
        "params": ["table", "schema"],
        "defaults": {"schema": "public"},
    },
    "row_level_security_tenant": {
        "label": "Enable Row Level Security for multi-tenant table",
        "description": "Adds RLS policy so users only see rows matching their tenant_id.",
        "function": """
-- Enable RLS on the table
ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;

-- Drop existing policy if re-applying
DROP POLICY IF EXISTS {table}_tenant_isolation ON {table};

-- Policy: users see only their tenant's rows
-- Requires: SET app.current_tenant_id = '<tenant_id>' at session start
CREATE POLICY {table}_tenant_isolation ON {table}
USING (tenant_id::text = current_setting('app.current_tenant_id', true));""",
        "trigger": None,  # RLS doesn't use a trigger
        "params": ["table"],
        "defaults": {},
    },
    "notify_on_change": {
        "label": "Send pg_notify on INSERT/UPDATE",
        "description": "Sends a PostgreSQL NOTIFY for real-time listeners (WebSocket sync).",
        "function": """
CREATE OR REPLACE FUNCTION {schema}.notify_{table}_change()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE
    payload JSONB;
BEGIN
    payload = jsonb_build_object(
        'table',  TG_TABLE_NAME,
        'action', TG_OP,
        'id',     COALESCE(NEW.id, OLD.id)
    );
    PERFORM pg_notify('{channel}', payload::text);
    RETURN COALESCE(NEW, OLD);
END;
$$;""",
        "trigger": """
CREATE TRIGGER trg_{table}_notify
AFTER INSERT OR UPDATE OR DELETE ON {table}
FOR EACH ROW EXECUTE FUNCTION {schema}.notify_{table}_change();""",
        "params": ["table", "schema", "channel"],
        "defaults": {"schema": "public", "channel": "pgappforge_changes"},
    },
    "tsvector_search": {
        "label": "Maintain tsvector full-text search column",
        "description": "Keeps a tsvector column current for fast full-text search.",
        "function": """
-- Add the search column if it doesn't exist
ALTER TABLE {table} ADD COLUMN IF NOT EXISTS search_vector TSVECTOR;
CREATE INDEX IF NOT EXISTS ix_{table}_search ON {table} USING GIN(search_vector);

CREATE OR REPLACE FUNCTION {schema}.update_{table}_search()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.search_vector = to_tsvector('english',
        COALESCE({search_columns}, ''));
    RETURN NEW;
END;
$$;""",
        "trigger": """
CREATE TRIGGER trg_{table}_search_update
BEFORE INSERT OR UPDATE ON {table}
FOR EACH ROW EXECUTE FUNCTION {schema}.update_{table}_search();""",
        "params": ["table", "schema", "search_columns"],
        "defaults": {"schema": "public", "search_columns": "''"},
    },
}


class TriggerProcedureManager:
	"""Manages PostgreSQL triggers and stored procedures/functions.

	Usage::

	    mgr = TriggerProcedureManager(engine)

	    # Apply a template
	    mgr.apply_template('updated_at', table='employees')

	    # List existing triggers
	    triggers = mgr.list_triggers()

	    # List functions/procedures
	    funcs = mgr.list_functions()

	    # Create custom function
	    mgr.create_function('my_func', body='...')

	    # Drop
	    mgr.drop_trigger('employees', 'trg_employees_updated_at')
	"""

	def __init__(self, engine) -> None:
		self.engine = engine

	def list_templates(self) -> list[dict]:
		"""Return all available trigger/function templates."""
		return [
			{
				"key": k,
				"label": v["label"],
				"description": v["description"],
				"params": v["params"],
				"defaults": v["defaults"],
				"has_trigger": v.get("trigger") is not None,
			}
			for k, v in TRIGGER_TEMPLATES.items()
		]

	def render_template(self, template_key: str, **params) -> dict[str, str]:
		"""Render a template with the given parameter values.

		Returns: {"function": "CREATE FUNCTION ...", "trigger": "CREATE TRIGGER ..."}
		"""
		tmpl = TRIGGER_TEMPLATES.get(template_key)
		if not tmpl:
			raise ValueError(f"Unknown template: {template_key!r}. "
			                 f"Available: {list(TRIGGER_TEMPLATES)}")

		# Apply defaults then override with provided params
		ctx = {**tmpl["defaults"], **params}

		func_sql = tmpl["function"].format(**ctx).strip()
		trig_sql = tmpl["trigger"].format(**ctx).strip() if tmpl["trigger"] else None

		return {"function": func_sql, "trigger": trig_sql}

	def apply_template(self, template_key: str, **params) -> dict:
		"""Render and execute a template.

		Returns: {"applied": bool, "sql": [stmts], "errors": [...]}
		"""
		rendered = self.render_template(template_key, **params)
		stmts = [rendered["function"]]
		if rendered["trigger"]:
			stmts.append(rendered["trigger"])

		return self._execute_ddl(stmts)

	def create_function(
		self,
		name: str,
		args: str = "",
		returns: str = "VOID",
		language: str = "plpgsql",
		body: str = "BEGIN\nEND;",
		schema: str = "public",
		replace: bool = True,
	) -> dict:
		"""Create or replace a PostgreSQL function."""
		or_replace = "OR REPLACE " if replace else ""
		sql = (
			f"CREATE {or_replace}FUNCTION {schema}.{name}({args})\n"
			f"RETURNS {returns} LANGUAGE {language} AS $$\n"
			f"{body}\n$$;"
		)
		return self._execute_ddl([sql])

	def create_procedure(
		self,
		name: str,
		args: str = "",
		language: str = "plpgsql",
		body: str = "BEGIN\nEND;",
		schema: str = "public",
		replace: bool = True,
	) -> dict:
		"""Create or replace a PostgreSQL procedure (PostgreSQL 11+)."""
		or_replace = "OR REPLACE " if replace else ""
		sql = (
			f"CREATE {or_replace}PROCEDURE {schema}.{name}({args})\n"
			f"LANGUAGE {language} AS $$\n"
			f"{body}\n$$;"
		)
		return self._execute_ddl([sql])

	def drop_function(self, name: str, args: str = "", schema: str = "public") -> dict:
		sql = f"DROP FUNCTION IF EXISTS {schema}.{name}({args}) CASCADE"
		return self._execute_ddl([sql])

	def drop_trigger(self, table: str, trigger_name: str) -> dict:
		sql = f"DROP TRIGGER IF EXISTS {trigger_name} ON {table} CASCADE"
		return self._execute_ddl([sql])

	def list_triggers(self, table: str | None = None) -> list[dict]:
		"""List all triggers, optionally filtered by table."""
		where = f"AND event_object_table = '{table}'" if table else ""
		q = f"""
		    SELECT trigger_name, event_object_table, event_manipulation,
		           action_timing, action_statement
		    FROM information_schema.triggers
		    WHERE trigger_schema NOT IN ('pg_catalog', 'information_schema')
		    {where}
		    ORDER BY event_object_table, trigger_name
		"""
		with self.engine.connect() as conn:
			rows = conn.execute(text(q)).fetchall()
		return [dict(r._mapping) for r in rows]

	def list_functions(self, schema: str = "public") -> list[dict]:
		"""List all user-defined functions and procedures."""
		q = """
		    SELECT p.proname AS name,
		           n.nspname AS schema,
		           pg_get_function_arguments(p.oid) AS args,
		           pg_get_function_result(p.oid) AS returns,
		           l.lanname AS language,
		           p.prokind AS kind  -- 'f'=function, 'p'=procedure
		    FROM pg_proc p
		    JOIN pg_namespace n ON n.oid = p.pronamespace
		    JOIN pg_language l ON l.oid = p.prolang
		    WHERE n.nspname = :schema
		      AND l.lanname NOT IN ('internal', 'c')
		    ORDER BY p.proname
		"""
		with self.engine.connect() as conn:
			rows = conn.execute(text(q), {"schema": schema}).fetchall()
		return [dict(r._mapping) for r in rows]

	def get_function_source(self, name: str, schema: str = "public") -> str | None:
		"""Return the source code of a function/procedure."""
		q = """
		    SELECT pg_get_functiondef(p.oid) AS source
		    FROM pg_proc p
		    JOIN pg_namespace n ON n.oid = p.pronamespace
		    WHERE p.proname = :name AND n.nspname = :schema
		    LIMIT 1
		"""
		with self.engine.connect() as conn:
			row = conn.execute(text(q), {"name": name, "schema": schema}).fetchone()
		return row[0] if row else None

	def _execute_ddl(self, stmts: list[str]) -> dict:
		"""Execute DDL statements in a single transaction. Rolls back all on any error."""
		errors: list[str] = []
		applied = 0
		try:
			with self.engine.begin() as conn:
				for stmt in stmts:
					conn.execute(text(stmt))
					applied += 1
		except Exception as exc:
			errors.append(str(exc))
			applied = 0  # full rollback — none applied
		return {"applied": applied, "sql": stmts[:applied], "errors": errors}
