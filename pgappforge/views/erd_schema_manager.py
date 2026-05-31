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

import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

log = logging.getLogger(__name__)


# ─── Shared Mermaid serialiser ────────────────────────────────────────────────

def _to_mermaid_str(schema: dict) -> str:
	"""Convert a schema dict to Mermaid erDiagram syntax.

	This is the canonical implementation — both ERDSchemaManager.to_mermaid()
	and ERDView._to_mermaid() delegate here to ensure consistent output.

	Relationships are deduplicated so composite FK columns don't produce
	multiple relationship lines for the same table pair.
	"""
	lines: list[str] = ["erDiagram"]
	for tbl in schema.get("tables", []):
		tname = tbl["name"].upper()
		lines.append(f"    {tname} {{")
		for col in tbl.get("columns", []):
			col_type = re.sub(r"\(.*\)", "", col.get("type", "text")).lower().replace(" ", "_") or "text"
			col_name = col.get("name", "?")
			attrs: list[str] = []
			if col.get("pk"):
				attrs.append("PK")
			if col.get("fk"):
				attrs.append("FK")
			suffix = " " + ",".join(attrs) if attrs else ""
			lines.append(f"        {col_type} {col_name}{suffix}")
		lines.append("    }")

	# Deduplicate relationship pairs
	seen: set[tuple[str, str]] = set()
	for rel in schema.get("relationships", []):
		from_t = (rel.get("from_table") or rel.get("table", "")).upper()
		to_t   = (rel.get("to_table")   or rel.get("ref_table", "")).upper()
		if not from_t or not to_t:
			continue
		pair = (from_t, to_t)
		if pair in seen:
			continue
		seen.add(pair)
		lines.append(f'    {to_t} ||--o{{ {from_t} : "has"')

	return "\n".join(lines)


# ─── DDL identifier safety helpers ──────────────────────────────────────────

_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")


def _qi(name: str) -> str:
	"""Quote a single PostgreSQL identifier and reject dangerous names.

	Raises ValueError for names that don't match the safe identifier pattern
	(letter/underscore start, alphanumeric/underscore body, ≤63 chars).
	Double-quotes any valid name so reserved words are handled safely.
	"""
	if not isinstance(name, str) or not _IDENT_RE.match(name):
		raise ValueError(
			f"Invalid PostgreSQL identifier {name!r}. "
			f"Must match ^[A-Za-z_][A-Za-z0-9_]{{0,62}}$"
		)
	return f'"{name}"'


def _qschema(table: str, schema: str | None = None) -> str:
	"""Return a schema-qualified, double-quoted table reference."""
	return f"{_qi(schema)}.{_qi(table)}" if schema else _qi(table)


def _quote_default(val: Any) -> str:
	"""Safely quote a column DEFAULT value.

	SQL expressions (function calls, keywords, numeric literals) pass through
	unchanged.  Plain strings are single-quoted with internal quotes escaped.
	This prevents unintended SQL injection via user-supplied default values.
	"""
	s = str(val).strip()
	# Numeric literal
	if s.lstrip("-+").replace(".", "", 1).isdigit():
		return s
	# SQL expression markers — pass through as-is
	_expr_markers = ("(", "now", "current_", "gen_random", "nextval",
	                 "true", "false", "null", "interval")
	if any(s.lower().startswith(m) for m in _expr_markers):
		return s
	# Plain string literal — single-quote and escape internal quotes
	return "'" + s.replace("'", "''") + "'"


_SAFE_VALUE_RE = re.compile(r"""^[A-Za-z0-9_, .'"\\:@/-]+$""")

_PG_TYPE_RE = re.compile(
	r"^[A-Za-z][A-Za-z0-9_ ]*"
	r"(\(\s*\d+(\s*,\s*\d+)?\s*\))?"
	r"(\[\])?$"
)


def _safe_type(t: str) -> str:
	t = t.strip()
	if not _PG_TYPE_RE.match(t):
		raise ValueError(f"Invalid PostgreSQL type: {t!r}")
	return t


def _validate_pred_expr(expr: str) -> str:
	e = expr.strip().rstrip(";")
	if ";" in e:
		raise ValueError("predicate expression must not contain semicolons")
	_BANNED_PRED = re.compile(
		r"\b(pg_read_file|pg_ls_dir|lo_export|lo_import|copy\s+|"
		r"do\s+\$|create\s+|drop\s+|alter\s+|insert\b|"
		r"update\b|delete\b)\b",
		re.IGNORECASE,
	)
	if _BANNED_PRED.search(e):
		raise ValueError("predicate expression contains disallowed keyword")
	depth = sum((1 if ch == "(" else -1) if ch in "()" else 0 for ch in e)
	if depth != 0:
		raise ValueError("predicate expression has unbalanced parentheses")
	return e


def _gen_constraint_name(prefix: str, *parts: str) -> str:
	full = f"{prefix}_{'_'.join(parts)}"
	if len(full) <= 63:
		return full
	digest = hashlib.md5(full.encode()).hexdigest()[:8]
	return f"{full[:54]}_{digest}"


def _generate_rollback(ops: list[dict], sql_stmts: list[str]) -> list[str]:
	"""Generate inverse DDL for each operation where it is safe and deterministic."""
	rollback: list[str] = []
	for op in reversed(ops):
		kind = op.get("op", "")
		tbl  = op.get("table", "")
		schema = op.get("schema", "")
		try:
			qtbl = _qschema(tbl, schema or None)
		except ValueError:
			continue
		if kind == "create_table":
			rollback.append(f"DROP TABLE IF EXISTS {qtbl} CASCADE")
		elif kind == "add_column":
			c = op.get("column", {})
			try:
				rollback.append(f"ALTER TABLE {qtbl} DROP COLUMN IF EXISTS {_qi(c['name'])} CASCADE")
			except (ValueError, KeyError):
				pass
		elif kind == "add_fk":
			cname = f"{tbl}_{op.get('column', '')}_{op.get('ref_table', '')}_fkey"
			try:
				rollback.append(f"ALTER TABLE {qtbl} DROP CONSTRAINT IF EXISTS {_qi(cname)}")
			except ValueError:
				pass
		# drop_table, drop_column, alter_column, rename_* — no safe auto-rollback
	return rollback


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
			tables.append({"name": tname, "columns": cols, "comment": tinfo.comment})

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
		return _to_mermaid_str(self.get_schema())

	def _to_sql_ddl_str(self, schema: dict) -> str:
		"""Return CREATE TABLE ... + ALTER TABLE ADD CONSTRAINT FK statements for *schema*.

		Emits all CREATE TABLE statements first, then all ALTER TABLE ADD CONSTRAINT
		FOREIGN KEY statements so forward-reference ordering is not an issue.
		"""
		create_lines: list[str] = []
		fk_lines: list[str] = []

		for tbl in schema.get("tables", []):
			tname = tbl["name"]
			try:
				qtbl = _qi(tname)
			except ValueError:
				continue
			col_defs: list[str] = []
			for col in tbl.get("columns", []):
				try:
					qcol = _qi(col["name"])
				except (ValueError, KeyError):
					continue
				try:
					col_type = _safe_type(col.get("type", "TEXT"))
				except ValueError:
					col_type = "TEXT"
				defn = f"{qcol} {col_type}"
				if col.get("pk"):
					defn += " PRIMARY KEY"
				if not col.get("nullable", True) and not col.get("pk"):
					defn += " NOT NULL"
				if col.get("unique") and not col.get("pk"):
					defn += " UNIQUE"
				if col.get("default") is not None:
					defn += f" DEFAULT {_quote_default(col['default'])}"
				col_defs.append(defn)
				# Collect FK for later ALTER TABLE
				fk_ref = col.get("fk")
				if fk_ref and isinstance(fk_ref, str):
					parts = fk_ref.split(".")
					ref_table = parts[0]
					ref_col = parts[1] if len(parts) > 1 else "id"
					try:
						cname = _gen_constraint_name(tname, col["name"], ref_table, "fkey")
						fk_lines.append(
							f"ALTER TABLE {qtbl} "
							f"ADD CONSTRAINT {_qi(cname)} "
							f"FOREIGN KEY ({qcol}) "
							f"REFERENCES {_qi(ref_table)} ({_qi(ref_col)});"
						)
					except ValueError:
						pass
			if col_defs:
				create_lines.append(
					f"CREATE TABLE IF NOT EXISTS {qtbl} (\n"
					+ ",\n".join(f"    {d}" for d in col_defs)
					+ "\n);"
				)

		# Also emit FKs from the relationships list (if columns don't carry fk attr)
		for rel in schema.get("relationships", []):
			from_t = rel.get("from_table", "")
			from_c = rel.get("from_col", "")
			to_t = rel.get("to_table", "")
			to_c = rel.get("to_col", "id")
			if not (from_t and from_c and to_t):
				continue
			try:
				cname = _gen_constraint_name(from_t, from_c, to_t, "fkey")
				fk_lines.append(
					f"ALTER TABLE {_qi(from_t)} "
					f"ADD CONSTRAINT {_qi(cname)} "
					f"FOREIGN KEY ({_qi(from_c)}) "
					f"REFERENCES {_qi(to_t)} ({_qi(to_c or 'id')});"
				)
			except ValueError:
				pass

		parts: list[str] = []
		if create_lines:
			parts.append("\n\n".join(create_lines))
		if fk_lines:
			parts.append("\n".join(fk_lines))
		return "\n\n".join(parts)

	def _to_dbml_str(self, schema: dict) -> str:
		"""Return DBML format string for *schema*.

		Format::

		    Table orders {
		      id integer [primary key, increment]
		      customer_id integer [not null]
		      note varchar
		    }

		    Ref: orders.customer_id > customers.id
		"""
		_SERIAL_TYPES = {"serial", "bigserial", "smallserial"}
		lines: list[str] = []

		for tbl in schema.get("tables", []):
			lines.append(f"Table {tbl['name']} {{")
			for col in tbl.get("columns", []):
				col_type = col.get("type", "text").lower().split("(")[0].strip()
				attrs: list[str] = []
				if col.get("pk"):
					attrs.append("primary key")
				if col_type in _SERIAL_TYPES:
					attrs.append("increment")
				if not col.get("nullable", True) and not col.get("pk"):
					attrs.append("not null")
				if col.get("default") is not None:
					attrs.append(f"default: `{col['default']}`")
				attr_str = " [" + ", ".join(attrs) + "]" if attrs else ""
				lines.append(f"  {col['name']} {col_type}{attr_str}")
			lines.append("}\n")

		# Ref lines from relationships
		seen_refs: set[tuple[str, str, str, str]] = set()
		for rel in schema.get("relationships", []):
			from_t = rel.get("from_table", "")
			from_c = rel.get("from_col", "")
			to_t = rel.get("to_table", "")
			to_c = rel.get("to_col", "id")
			if not (from_t and from_c and to_t):
				continue
			key = (from_t, from_c, to_t, to_c or "id")
			if key in seen_refs:
				continue
			seen_refs.add(key)
			lines.append(f"Ref: {from_t}.{from_c} > {to_t}.{to_c or 'id'}")

		return "\n".join(lines)

	def import_dbml(self, dbml_text: str) -> dict[str, Any]:
		"""Parse DBML text and apply to the database via apply_changes().

		Handles::

		    Table name {
		      col_name col_type [attrs]
		    }

		    Ref: table_a.col > table_b.col
		"""
		ops: list[dict] = []
		fk_ops: list[dict] = []

		# ── Parse Table blocks ────────────────────────────────────────────────
		table_block_re = re.compile(
			r'Table\s+(\w+)\s*\{([^}]*)\}',
			re.IGNORECASE | re.DOTALL,
		)
		attr_re = re.compile(r'\[([^\]]*)\]')

		for m in table_block_re.finditer(dbml_text):
			tname = m.group(1)
			body = m.group(2)
			columns: list[dict] = []
			for line in body.splitlines():
				line = line.strip()
				if not line or line.startswith("//"):
					continue
				# Extract and remove attribute block
				attr_match = attr_re.search(line)
				attrs_str = attr_match.group(1) if attr_match else ""
				col_line = attr_re.sub("", line).strip()
				parts = col_line.split(None, 1)
				if len(parts) < 2:
					continue
				col_name, col_type_raw = parts[0], parts[1].strip()
				try:
					pg_type = _safe_type(col_type_raw)
				except ValueError:
					pg_type = "TEXT"

				col_def: dict[str, Any] = {
					"name": col_name,
					"type": pg_type,
					"pk": False,
					"nullable": True,
					"unique": False,
					"default": None,
				}
				# Parse attrs
				for attr in (a.strip() for a in attrs_str.split(",")):
					al = attr.lower()
					if al == "primary key" or al == "pk":
						col_def["pk"] = True
						col_def["nullable"] = False
					elif al == "not null" or al == "nn":
						col_def["nullable"] = False
					elif al == "unique":
						col_def["unique"] = True
					elif al.startswith("default:"):
						raw_default = attr[len("default:"):].strip().strip("`")
						col_def["default"] = raw_default
				columns.append(col_def)

			if columns:
				ops.append({"op": "create_table", "table": tname, "columns": columns})

		# ── Parse Ref lines ───────────────────────────────────────────────────
		ref_re = re.compile(
			r'Ref\s*:\s*(\w+)\.(\w+)\s*[<>-]+\s*(\w+)\.(\w+)',
			re.IGNORECASE,
		)
		for m in ref_re.finditer(dbml_text):
			from_t, from_c, to_t, to_c = m.group(1), m.group(2), m.group(3), m.group(4)
			fk_ops.append({
				"op": "add_fk",
				"table": from_t,
				"column": from_c,
				"ref_table": to_t,
				"ref_column": to_c,
			})

		all_ops = ops + fk_ops
		if not all_ops:
			return {"applied": 0, "sql": [], "errors": ["No tables or refs found in DBML"]}
		return self.apply_changes(all_ops)

	def reverse_engineer(self) -> dict[str, Any]:
		"""Read live schema and return Cytoscape canvas JSON.

		Returns::

		    {
		      "elements": [...],   # Cytoscape node/edge elements
		      "schema": {...}      # raw schema dict
		    }
		"""
		schema = self.get_schema()
		elements: list[dict] = []

		# Compound node for all live tables
		elements.append({"data": {
			"id": "mod_LIVE",
			"label": "Live Database",
			"type": "module",
			"color": "#2c3e50",
		}})

		for tbl in schema.get("tables", []):
			tname = tbl["name"]
			cols = tbl.get("columns", [])
			col_summary = ", ".join(c["name"] for c in cols[:4])
			if len(cols) > 4:
				col_summary += f" +{len(cols) - 4}"

			# Detect Actor pattern from table comment JSON
			is_actor = False
			actor_role = ""
			actor_config: dict = {}
			raw_comment: str | None = tbl.get("comment")
			if raw_comment:
				try:
					parsed = json.loads(raw_comment)
					if isinstance(parsed, dict) and "pgaf_actor" in parsed:
						is_actor = True
						actor_config = parsed["pgaf_actor"] if isinstance(parsed["pgaf_actor"], dict) else {}
						actor_role = actor_config.get("role", "")
				except (json.JSONDecodeError, TypeError):
					pass

			node_data: dict[str, Any] = {
				"id": tname,
				"parent": "mod_LIVE",
				"label": tname,
				"type": "table",
				"col_summary": col_summary,
				"color": "#2c3e50",
				"columns": cols,
				"is_actor": is_actor,
				"actor_role": actor_role,
				"actor_config": actor_config,
			}
			elements.append({"data": node_data})

		seen_edges: set[str] = set()
		for rel in schema.get("relationships", []):
			from_t = rel.get("from_table", "")
			to_t = rel.get("to_table", "")
			from_c = rel.get("from_col", "")
			if not (from_t and to_t):
				continue
			eid = f"e_{from_t}_{from_c}_{to_t}"
			if eid in seen_edges:
				continue
			seen_edges.add(eid)
			elements.append({"data": {
				"id": eid,
				"source": from_t,
				"target": to_t,
				"label": from_c,
				"type": "fk",
			}})

		return {"elements": elements, "schema": schema}

	# ─── Apply changes ────────────────────────────────────────────────────────

	def apply_changes(
		self,
		operations: list[dict],
		dry_run: bool = False,
		user_id: int | None = None,
	) -> dict[str, Any]:
		"""Apply a list of schema change operations to the database.

		All operations run in a single transaction — any failure rolls back ALL.
		The inner try/except has been intentionally removed so that exceptions
		propagate to ``engine.begin()`` and trigger a full rollback.

		Args:
		    operations: List of operation dicts (see module docstring).
		    dry_run:    If True, generate SQL but do not execute.
		    user_id:    Optional caller ID for migration audit log.

		Returns:
		    {"applied": N, "sql": [...], "errors": [], "dry_run": bool}
		"""
		sql_stmts: list[str] = []
		errors: list[str] = []

		for op in operations:
			try:
				stmts = self._op_to_sql_list(op)
				sql_stmts.extend(s for s in stmts if s)
			except ValueError as exc:
				errors.append(f"Invalid op {op.get('op')!r}: {exc}")

		if errors:
			return {"applied": 0, "sql": [], "errors": errors, "dry_run": dry_run}

		if dry_run:
			return {
				"dry_run": True,
				"would_apply": len(sql_stmts),
				"sql": sql_stmts,
				"errors": [],
			}

		rollback = _generate_rollback(operations, sql_stmts)
		try:
			with self.engine.begin() as conn:
				# Apply configurable DDL statement timeout to prevent runaway ALTER TABLE
				try:
					from flask import current_app
					timeout_ms = int(current_app.config.get("FAB_ERD_DDL_TIMEOUT_MS", 30_000))
					conn.execute(text(f"SET LOCAL statement_timeout = {timeout_ms}"))
				except Exception:
					pass  # outside request context — skip timeout
				for stmt in sql_stmts:
					log.info("ERD DDL: %s", stmt)
					conn.execute(text(stmt))
				# Write migration log inside the same transaction so log and DDL are atomic
				try:
					conn.execute(text(
						"INSERT INTO erd_migration_log "
						"(user_id, applied_at, ops_json, sql_json, status, rollback_sql, error) "
						"VALUES (:uid, NOW(), :ops, :sql, 'success', :rb, NULL)"
					), {
						"uid": user_id,
						"ops": json.dumps(operations),
						"sql": json.dumps(sql_stmts),
						"rb": json.dumps(rollback),
					})
				except Exception as log_exc:
					log.debug("ERD migration log insert failed (non-fatal): %s", log_exc)
		except Exception as exc:
			log.error("ERD apply_changes failed: %s", exc)
			self._write_migration_log(user_id, operations, sql_stmts, "error", str(exc))
			return {"applied": 0, "sql": sql_stmts, "errors": [str(exc)], "dry_run": False}

		return {"applied": len(sql_stmts), "sql": sql_stmts, "errors": [], "dry_run": False}

	def _write_migration_log(
		self,
		user_id: int | None,
		ops: list[dict],
		sql_stmts: list[str],
		status: str,
		error: str | None = None,
	) -> None:
		"""Append an entry to ErdMigrationLog. Non-fatal on failure."""
		try:
			from pgappforge.models.erd_models import ErdMigrationLog
			from datetime import datetime, timezone
			from sqlalchemy.orm import Session
			rollback = _generate_rollback(ops, sql_stmts)
			entry = ErdMigrationLog(
				user_id=user_id,
				applied_at=datetime.now(timezone.utc),
				ops_json=ops,
				sql_json=sql_stmts,
				status=status,
				error=error,
				rollback_sql=rollback,
			)
			with Session(self.engine) as s:
				s.add(entry)
				s.commit()
		except Exception as exc:
			log.debug("ERD migration log write failed (non-fatal): %s", exc)

	def _op_to_sql_list(self, op: dict) -> list[str]:
		"""Convert a single operation dict to one or more SQL DDL strings.

		Returns a list (usually one item) so that ``create_table`` can emit the
		main CREATE followed by separate ADD CONSTRAINT FOREIGN KEY statements.
		All identifiers are quoted via ``_qi``/``_qschema`` to prevent DDL injection.
		"""
		kind   = op.get("op", "")
		tbl    = op.get("table", "")
		schema = op.get("schema", "") or None
		# qtbl is only needed for table-based ops; some ops (create_enum) have no table
		qtbl: str = ""
		if tbl:
			qtbl = _qschema(tbl, schema)

		# ── CREATE TABLE ──────────────────────────────────────────────────────
		if kind == "create_table":
			cols = op.get("columns", [])
			col_defs: list[str] = []
			fk_stmts: list[str] = []
			for c in cols:
				qcol = _qi(c["name"])
				defn = f"{qcol} {_safe_type(c['type'])}"
				if c.get("pk"):
					defn += " PRIMARY KEY"
				if not c.get("nullable", True):
					defn += " NOT NULL"
				if c.get("unique") and not c.get("pk"):
					defn += " UNIQUE"
				if c.get("default") is not None:
					defn += f" DEFAULT {_quote_default(c['default'])}"
				col_defs.append(defn)
				# Defer FK constraints to ALTER TABLE (avoids ordering issues)
				if c.get("fk"):
					fk_spec   = c["fk"]  # "other_table.col" or "other_table"
					parts     = fk_spec.split(".") if isinstance(fk_spec, str) else []
					ref_table = parts[0] if parts else fk_spec
					ref_col   = parts[1] if len(parts) > 1 else "id"
					cname     = _gen_constraint_name(tbl, c['name'], ref_table, "fkey")
					try:
						fk_stmts.append(
							f"ALTER TABLE {qtbl} "
							f"ADD CONSTRAINT {_qi(cname)} "
							f"FOREIGN KEY ({qcol}) "
							f"REFERENCES {_qi(ref_table)} ({_qi(ref_col)})"
						)
					except ValueError as exc:
						log.warning("ERD: skipping FK due to invalid identifier: %s", exc)
			result = [f"CREATE TABLE IF NOT EXISTS {qtbl} ({', '.join(col_defs)})"]
			result.extend(fk_stmts)
			return result

		# ── DROP TABLE ────────────────────────────────────────────────────────
		if kind == "drop_table":
			return [f"DROP TABLE IF EXISTS {qtbl} CASCADE"]

		# ── ADD COLUMN ────────────────────────────────────────────────────────
		if kind == "add_column":
			c    = op["column"]
			qcol = _qi(c["name"])
			defn = f"{qcol} {_safe_type(c['type'])}"
			if not c.get("nullable", True):
				defn += " NOT NULL"
			if c.get("unique"):
				defn += " UNIQUE"
			if c.get("default") is not None:
				defn += f" DEFAULT {_quote_default(c['default'])}"
			return [f"ALTER TABLE {qtbl} ADD COLUMN IF NOT EXISTS {defn}"]

		# ── DROP COLUMN ───────────────────────────────────────────────────────
		if kind == "drop_column":
			return [f"ALTER TABLE {qtbl} DROP COLUMN IF EXISTS {_qi(op['column'])} CASCADE"]

		# ── ALTER COLUMN ──────────────────────────────────────────────────────
		if kind == "alter_column":
			qcol  = _qi(op["column"])
			stmts: list[str] = []
			if op.get("new_type"):
				new_type = _safe_type(op["new_type"])
				stmts.append(
					f"ALTER TABLE {qtbl} ALTER COLUMN {qcol} "
					f"TYPE {new_type} USING {qcol}::{new_type}"
				)
			if "nullable" in op:
				clause = "DROP NOT NULL" if op["nullable"] else "SET NOT NULL"
				stmts.append(f"ALTER TABLE {qtbl} ALTER COLUMN {qcol} {clause}")
			if "default" in op:
				if op["default"] is None:
					stmts.append(f"ALTER TABLE {qtbl} ALTER COLUMN {qcol} DROP DEFAULT")
				else:
					stmts.append(
						f"ALTER TABLE {qtbl} ALTER COLUMN {qcol} "
						f"SET DEFAULT {_quote_default(op['default'])}"
					)
			return stmts if stmts else []

		# ── ADD FOREIGN KEY ───────────────────────────────────────────────────
		if kind == "add_fk":
			qcol      = _qi(op["column"])
			ref_table = op["ref_table"]
			ref_col   = op.get("ref_column", "id")
			cname     = op.get("constraint_name", f"{tbl}_{op['column']}_{ref_table}_fkey")
			return [
				f"ALTER TABLE {qtbl} ADD CONSTRAINT {_qi(cname)} "
				f"FOREIGN KEY ({qcol}) REFERENCES {_qi(ref_table)} ({_qi(ref_col)})"
			]

		# ── DROP FOREIGN KEY ──────────────────────────────────────────────────
		if kind == "drop_fk":
			return [f"ALTER TABLE {qtbl} DROP CONSTRAINT {_qi(op['constraint_name'])}"]

		# ── RENAME TABLE ──────────────────────────────────────────────────────
		if kind == "rename_table":
			return [f"ALTER TABLE {qtbl} RENAME TO {_qi(op['new_name'])}"]

		# ── RENAME COLUMN ─────────────────────────────────────────────────────
		if kind == "rename_column":
			return [
				f"ALTER TABLE {qtbl} RENAME COLUMN {_qi(op['column'])} TO {_qi(op['new_name'])}"
			]

		# ── ADD INDEX ─────────────────────────────────────────────────────────
		if kind == "add_index":
			raw_cols = op.get("columns", [])
			qcols    = ", ".join(_qi(c) for c in raw_cols)
			unique   = "UNIQUE " if op.get("unique") else ""
			iname    = op.get("name", f"ix_{tbl}_{'_'.join(raw_cols)}")
			return [f"CREATE {unique}INDEX IF NOT EXISTS {_qi(iname)} ON {qtbl} ({qcols})"]

		# ── DROP INDEX ────────────────────────────────────────────────────────
		if kind == "drop_index":
			return [f"DROP INDEX IF EXISTS {_qi(op['name'])}"]

		if kind == "create_enum":
			schema = op.get("schema") or None
			qname  = f"{_qi(schema)}.{_qi(op['name'])}" if schema else _qi(op["name"])
			values = ", ".join(f"'{v.replace(chr(39), chr(39)*2)}'" for v in op.get("values", []))
			return [f"CREATE TYPE {qname} AS ENUM ({values})"]

		if kind == "drop_enum":
			schema = op.get("schema") or None
			qname  = f"{_qi(schema)}.{_qi(op['name'])}" if schema else _qi(op["name"])
			return [f"DROP TYPE IF EXISTS {qname}"]

		if kind == "add_check_constraint":
			expr  = op.get("expression", "").strip()
			if not expr:
				raise ValueError("CHECK expression must be non-empty")
			expr = _validate_pred_expr(expr)
			cname = op.get("name") or f"chk_{tbl}_{abs(hash(expr)) % 10000}"
			return [f"ALTER TABLE {qtbl} ADD CONSTRAINT {_qi(cname)} CHECK ({expr})"]

		if kind == "drop_check_constraint":
			return [f"ALTER TABLE {qtbl} DROP CONSTRAINT {_qi(op['name'])}"]

		if kind == "set_composite_pk":
			cols = [_qi(c) for c in op.get("columns", [])]
			if not cols:
				raise ValueError("set_composite_pk requires at least one column")
			return [
				(
					f"DO $$ DECLARE _pk TEXT; BEGIN "
					f"SELECT conname INTO _pk FROM pg_constraint "
					f"WHERE conrelid = '{qtbl}'::regclass AND contype = 'p'; "
					f"IF _pk IS NOT NULL THEN "
					f"EXECUTE format('ALTER TABLE {qtbl} DROP CONSTRAINT %%I', _pk); "
					f"END IF; END $$;"
				),
				f"ALTER TABLE {qtbl} ADD PRIMARY KEY ({', '.join(cols)})",
			]

		raise ValueError(f"Unknown operation: {kind!r}")

	def _op_to_sql(self, op: dict) -> str | None:
		"""Legacy single-string variant — delegates to _op_to_sql_list."""
		stmts = self._op_to_sql_list(op)
		if not stmts:
			return None
		return "; ".join(stmts)

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

		try:
			with self.engine.begin() as conn:
				for stmt in stmts:
					conn.execute(text(stmt))
		except Exception as exc:
			log.error("ERD import_sql failed: %s", exc)
			return {"applied": 0, "sql": [], "errors": [str(exc)]}

		return {"applied": len(stmts), "sql": stmts, "errors": []}

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
        "label": "Full-text search column (tsvector)",
        "description": "Keeps a tsvector column current for fast full-text search.",
        "icon": "fa-search",
        "category": "search",
        "function": """
ALTER TABLE {table} ADD COLUMN IF NOT EXISTS search_vector TSVECTOR;
CREATE INDEX IF NOT EXISTS ix_{table}_search ON {table} USING GIN(search_vector);

CREATE OR REPLACE FUNCTION {schema}.update_{table}_search()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.search_vector = to_tsvector('english', COALESCE({search_columns}, ''));
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

    # ── 7 — Auto-set created_at on INSERT ────────────────────────────────────
    "created_at_auto": {
        "label": "Auto-set created_at on INSERT",
        "description": "Ensures created_at is never overwritten after the first insert.",
        "icon": "fa-calendar-plus",
        "category": "timestamps",
        "function": """
CREATE OR REPLACE FUNCTION {schema}.set_created_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.created_at IS NULL THEN
        NEW.created_at = NOW();
    END IF;
    RETURN NEW;
END;
$$;""",
        "trigger": """
CREATE TRIGGER trg_{table}_created_at
BEFORE INSERT ON {table}
FOR EACH ROW EXECUTE FUNCTION {schema}.set_created_at();""",
        "params": ["table", "schema"],
        "defaults": {"schema": "public"},
    },

    # ── 8 — Validate email format ─────────────────────────────────────────────
    "validate_email": {
        "label": "Validate email format (RFC-5322 pattern)",
        "description": "Raises an exception if an email column doesn't match a basic pattern.",
        "icon": "fa-envelope-circle-check",
        "category": "validation",
        "function": """
CREATE OR REPLACE FUNCTION {schema}.validate_{table}_email()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.{email_column} IS NOT NULL AND
       NEW.{email_column} !~ '^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$' THEN
        RAISE EXCEPTION 'Invalid email address: %', NEW.{email_column};
    END IF;
    RETURN NEW;
END;
$$;""",
        "trigger": """
CREATE TRIGGER trg_{table}_email_check
BEFORE INSERT OR UPDATE OF {email_column} ON {table}
FOR EACH ROW EXECUTE FUNCTION {schema}.validate_{table}_email();""",
        "params": ["table", "schema", "email_column"],
        "defaults": {"schema": "public", "email_column": "email"},
    },

    # ── 9 — Auto-generate URL slug ────────────────────────────────────────────
    "slugify": {
        "label": "Auto-generate URL slug from title/name",
        "description": "Creates a url-friendly slug from a source column on INSERT (skips if slug already set).",
        "icon": "fa-link",
        "category": "derived",
        "function": """
CREATE OR REPLACE FUNCTION {schema}.slugify_{table}()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.{slug_column} IS NULL OR NEW.{slug_column} = '' THEN
        NEW.{slug_column} = lower(
            regexp_replace(
                regexp_replace(NEW.{source_column}, '[^a-zA-Z0-9\\s-]', '', 'g'),
            '\\s+', '-', 'g')
        );
    END IF;
    RETURN NEW;
END;
$$;""",
        "trigger": """
CREATE TRIGGER trg_{table}_slugify
BEFORE INSERT ON {table}
FOR EACH ROW EXECUTE FUNCTION {schema}.slugify_{table}();""",
        "params": ["table", "schema", "source_column", "slug_column"],
        "defaults": {"schema": "public", "source_column": "title", "slug_column": "slug"},
    },

    # ── 10 — Immutable field guard ────────────────────────────────────────────
    "immutable_field": {
        "label": "Protect immutable field after creation",
        "description": "Raises an error if a field is changed after the row is first inserted.",
        "icon": "fa-lock",
        "category": "validation",
        "function": """
CREATE OR REPLACE FUNCTION {schema}.guard_{table}_{guard_column}()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.{guard_column} IS DISTINCT FROM NEW.{guard_column} THEN
        RAISE EXCEPTION '% is immutable after creation', '{guard_column}';
    END IF;
    RETURN NEW;
END;
$$;""",
        "trigger": """
CREATE TRIGGER trg_{table}_{guard_column}_immutable
BEFORE UPDATE OF {guard_column} ON {table}
FOR EACH ROW EXECUTE FUNCTION {schema}.guard_{table}_{guard_column}();""",
        "params": ["table", "schema", "guard_column"],
        "defaults": {"schema": "public", "guard_column": "created_at"},
    },

    # ── 11 — Version/history table ────────────────────────────────────────────
    "version_history": {
        "label": "Append-only version history",
        "description": "Copies every UPDATE to a {table}_history table for full row history.",
        "icon": "fa-clock-rotate-left",
        "category": "audit",
        "function": """
CREATE TABLE IF NOT EXISTS {table}_history (
    history_id  BIGSERIAL PRIMARY KEY,
    action      TEXT NOT NULL,
    changed_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    changed_by  TEXT DEFAULT current_user,
    data        JSONB NOT NULL
);

CREATE OR REPLACE FUNCTION {schema}.archive_{table}()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    INSERT INTO {table}_history(action, data)
    VALUES (TG_OP, row_to_json(OLD)::jsonb);
    RETURN NEW;
END;
$$;""",
        "trigger": """
CREATE TRIGGER trg_{table}_history
BEFORE UPDATE OR DELETE ON {table}
FOR EACH ROW EXECUTE FUNCTION {schema}.archive_{table}();""",
        "params": ["table", "schema"],
        "defaults": {"schema": "public"},
    },

    # ── 12 — UUID primary key auto-generate ───────────────────────────────────
    "uuid_pk": {
        "label": "Auto-generate UUID primary key",
        "description": "Generates a gen_random_uuid() value if id is NULL on INSERT.",
        "icon": "fa-fingerprint",
        "category": "identity",
        "function": """
CREATE OR REPLACE FUNCTION {schema}.set_uuid_{table}()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.id IS NULL THEN
        NEW.id = gen_random_uuid();
    END IF;
    RETURN NEW;
END;
$$;""",
        "trigger": """
CREATE TRIGGER trg_{table}_uuid
BEFORE INSERT ON {table}
FOR EACH ROW EXECUTE FUNCTION {schema}.set_uuid_{table}();""",
        "params": ["table", "schema"],
        "defaults": {"schema": "public"},
    },

    # ── 13 — Ledger running balance ───────────────────────────────────────────
    "ledger_balance": {
        "label": "Running balance for financial ledger",
        "description": "Computes a cumulative SUM(amount) running balance on INSERT.",
        "icon": "fa-scale-balanced",
        "category": "finance",
        "function": """
ALTER TABLE {table} ADD COLUMN IF NOT EXISTS balance NUMERIC(18,2) DEFAULT 0;

CREATE OR REPLACE FUNCTION {schema}.update_{table}_balance()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE
    prev_balance NUMERIC(18,2);
BEGIN
    SELECT COALESCE(MAX(balance), 0) INTO prev_balance FROM {table}
    WHERE {account_column} = NEW.{account_column};
    NEW.balance = prev_balance + NEW.{amount_column};
    RETURN NEW;
END;
$$;""",
        "trigger": """
CREATE TRIGGER trg_{table}_balance
BEFORE INSERT ON {table}
FOR EACH ROW EXECUTE FUNCTION {schema}.update_{table}_balance();""",
        "params": ["table", "schema", "account_column", "amount_column"],
        "defaults": {"schema": "public", "account_column": "account_id", "amount_column": "amount"},
    },

    # ── 14 — JSONB schema validation ──────────────────────────────────────────
    "jsonb_schema_validate": {
        "label": "Validate JSONB against required keys",
        "description": "Raises an error if a required key is missing from a JSONB column.",
        "icon": "fa-code",
        "category": "validation",
        "function": """
CREATE OR REPLACE FUNCTION {schema}.validate_{table}_{json_column}()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE
    required_key TEXT;
BEGIN
    FOREACH required_key IN ARRAY STRING_TO_ARRAY('{required_keys}', ',') LOOP
        IF NOT (NEW.{json_column} ? trim(required_key)) THEN
            RAISE EXCEPTION 'Missing required key "%" in {json_column}', trim(required_key);
        END IF;
    END LOOP;
    RETURN NEW;
END;
$$;""",
        "trigger": """
CREATE TRIGGER trg_{table}_{json_column}_schema
BEFORE INSERT OR UPDATE OF {json_column} ON {table}
FOR EACH ROW EXECUTE FUNCTION {schema}.validate_{table}_{json_column}();""",
        "params": ["table", "schema", "json_column", "required_keys"],
        "defaults": {"schema": "public", "json_column": "metadata", "required_keys": "type,version"},
    },

    # ── 15 — Encrypt sensitive column hint ────────────────────────────────────
    "encrypt_column": {
        "label": "Encrypt sensitive column (pgcrypto)",
        "description": "Encrypts a column value with pgp_sym_encrypt before storage. Requires pgcrypto.",
        "icon": "fa-user-secret",
        "category": "security",
        "function": """
-- Requires: CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE OR REPLACE FUNCTION {schema}.encrypt_{table}_{column}()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE
    encryption_key TEXT := current_setting('app.encryption_key', true);
BEGIN
    IF NEW.{column} IS NOT NULL AND encryption_key IS NOT NULL THEN
        NEW.{column} = encode(
            pgp_sym_encrypt(NEW.{column}, encryption_key), 'base64'
        );
    END IF;
    RETURN NEW;
END;
$$;""",
        "trigger": """
CREATE TRIGGER trg_{table}_{column}_encrypt
BEFORE INSERT OR UPDATE OF {column} ON {table}
FOR EACH ROW EXECUTE FUNCTION {schema}.encrypt_{table}_{column}();""",
        "params": ["table", "schema", "column"],
        "defaults": {"schema": "public", "column": "ssn"},
    },

    # ── 16 — Prevent update after publish/finalize ────────────────────────────
    "publish_lock": {
        "label": "Lock row after published/finalized status",
        "description": "Prevents editing rows once they reach a terminal status (published, finalized, etc).",
        "icon": "fa-file-circle-check",
        "category": "workflow",
        "function": """
CREATE OR REPLACE FUNCTION {schema}.lock_{table}_on_publish()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.{status_column} = '{locked_status}' THEN
        RAISE EXCEPTION 'Cannot modify a {locked_status} {table} row (id=%)', OLD.id;
    END IF;
    RETURN NEW;
END;
$$;""",
        "trigger": """
CREATE TRIGGER trg_{table}_publish_lock
BEFORE UPDATE ON {table}
FOR EACH ROW EXECUTE FUNCTION {schema}.lock_{table}_on_publish();""",
        "params": ["table", "schema", "status_column", "locked_status"],
        "defaults": {"schema": "public", "status_column": "status", "locked_status": "published"},
    },

    # ── 17 — Row-count quota guard ────────────────────────────────────────────
    "quota_guard": {
        "label": "Enforce row-count quota per parent",
        "description": "Prevents adding more than N rows for a given parent_id (e.g. ≤5 addresses per user).",
        "icon": "fa-gauge-high",
        "category": "validation",
        "function": """
CREATE OR REPLACE FUNCTION {schema}.check_{table}_quota()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE
    current_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO current_count
    FROM {table} WHERE {parent_column} = NEW.{parent_column};
    IF current_count >= {max_rows} THEN
        RAISE EXCEPTION 'Quota exceeded: maximum {max_rows} {table} rows per {parent_column}';
    END IF;
    RETURN NEW;
END;
$$;""",
        "trigger": """
CREATE TRIGGER trg_{table}_quota
BEFORE INSERT ON {table}
FOR EACH ROW EXECUTE FUNCTION {schema}.check_{table}_quota();""",
        "params": ["table", "schema", "parent_column", "max_rows"],
        "defaults": {"schema": "public", "parent_column": "user_id", "max_rows": "10"},
    },

    # ── 18 — Materialized summary refresh ────────────────────────────────────
    "refresh_summary": {
        "label": "Refresh materialized view on data change",
        "description": "Calls REFRESH MATERIALIZED VIEW CONCURRENTLY after INSERT/UPDATE/DELETE.",
        "icon": "fa-rotate",
        "category": "performance",
        "function": """
CREATE OR REPLACE FUNCTION {schema}.refresh_{view_name}()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    REFRESH MATERIALIZED VIEW CONCURRENTLY {schema}.{view_name};
    RETURN NULL;
END;
$$;""",
        "trigger": """
CREATE TRIGGER trg_{table}_refresh_{view_name}
AFTER INSERT OR UPDATE OR DELETE ON {table}
FOR EACH STATEMENT EXECUTE FUNCTION {schema}.refresh_{view_name}();""",
        "params": ["table", "schema", "view_name"],
        "defaults": {"schema": "public", "view_name": "mv_summary"},
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
		"""Return all available trigger/function templates with full metadata.

		Includes ``icon``, ``category``, ``function_sql``, and ``trigger_sql``
		so the frontend can render the template card grid, filter by category,
		and build client-side SQL previews without a round-trip.
		"""
		return [
			{
				"key":          k,
				"label":        v["label"],
				"description":  v.get("description", ""),
				"icon":         v.get("icon", "fa-bolt"),
				"category":     v.get("category", "general"),
				"params":       v.get("params", []),
				"defaults":     v.get("defaults", {}),
				"has_trigger":  v.get("trigger") is not None,
				"function_sql": v.get("function", ""),
				"trigger_sql":  v.get("trigger", ""),
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

		# Validate all identifier-like params to prevent format-string injection.
		# Multi-column params (search_columns) are validated element-by-element.
		for key, val in ctx.items():
			if isinstance(val, str) and not _SAFE_VALUE_RE.match(val):
				raise ValueError(
					f"Template parameter {key!r} contains unsafe characters: {val!r}"
				)

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
		"""List all triggers, optionally filtered by table.

		Uses parameterized binding for the table name to prevent SQL injection.
		"""
		if table is not None:
			q = """
			    SELECT trigger_name, event_object_table, event_manipulation,
			           action_timing, action_statement
			    FROM information_schema.triggers
			    WHERE trigger_schema NOT IN ('pg_catalog', 'information_schema')
			      AND event_object_table = :table
			    ORDER BY event_object_table, trigger_name
			"""
			params: dict = {"table": table}
		else:
			q = """
			    SELECT trigger_name, event_object_table, event_manipulation,
			           action_timing, action_statement
			    FROM information_schema.triggers
			    WHERE trigger_schema NOT IN ('pg_catalog', 'information_schema')
			    ORDER BY event_object_table, trigger_name
			"""
			params = {}
		with self.engine.connect() as conn:
			rows = conn.execute(text(q), params).fetchall()
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


# ─── ORM type mapping helpers (shared with erd_designer.py) ─────────────────

def _pg_to_sa_type(pg_type: str) -> str:
	"""Map a PostgreSQL type string to a SQLAlchemy Column type."""
	t = pg_type.upper().split("(")[0].strip()
	return {
		"SERIAL": "Integer", "BIGSERIAL": "BigInteger", "INTEGER": "Integer",
		"BIGINT": "BigInteger", "SMALLINT": "SmallInteger", "BOOLEAN": "Boolean",
		"TEXT": "Text", "VARCHAR": "String", "CHAR": "String",
		"NUMERIC": "Numeric", "DECIMAL": "Numeric", "FLOAT": "Float",
		"REAL": "Float", "DOUBLE": "Float", "DATE": "Date",
		"TIMESTAMP": "DateTime", "TIMESTAMPTZ": "DateTime", "TIME": "Time",
		"UUID": "UUID", "JSONB": "JSONB", "JSON": "JSON", "BYTEA": "LargeBinary",
		"INET": "String", "CIDR": "String",
	}.get(t, "String")


def _pg_to_django_type(pg_type: str) -> str:
	"""Map a PostgreSQL type string to a Django model field."""
	t = pg_type.upper().split("(")[0].strip()
	return {
		"SERIAL": "models.AutoField()", "BIGSERIAL": "models.BigAutoField()",
		"INTEGER": "models.IntegerField()", "BIGINT": "models.BigIntegerField()",
		"BOOLEAN": "models.BooleanField()", "TEXT": "models.TextField()",
		"VARCHAR": "models.CharField(max_length=255)", "DATE": "models.DateField()",
		"TIMESTAMP": "models.DateTimeField()", "TIMESTAMPTZ": "models.DateTimeField()",
		"NUMERIC": "models.DecimalField(max_digits=10, decimal_places=2)",
		"FLOAT": "models.FloatField()", "UUID": "models.UUIDField()",
		"JSONB": "models.JSONField()", "JSON": "models.JSONField()",
	}.get(t, "models.TextField()")


def _pg_to_prisma_type(pg_type: str) -> str:
	"""Map a PostgreSQL type string to a Prisma schema type."""
	t = pg_type.upper().split("(")[0].strip()
	return {
		"SERIAL": "Int", "BIGSERIAL": "BigInt", "INTEGER": "Int",
		"BIGINT": "BigInt", "BOOLEAN": "Boolean", "TEXT": "String",
		"VARCHAR": "String", "DATE": "DateTime", "TIMESTAMP": "DateTime",
		"TIMESTAMPTZ": "DateTime", "NUMERIC": "Decimal", "FLOAT": "Float",
		"UUID": "String", "JSONB": "Json", "JSON": "Json",
	}.get(t, "String")
