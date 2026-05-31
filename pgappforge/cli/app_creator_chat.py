"""
Ollama-powered conversational app creation interface for pgappforge.

CLI:  flask forge chat-create [--model qwen2.5:7b] [--ollama-url http://localhost:11434]
Web:  /app-creator/

The model is given tool-calling capability over a set of schema-building
primitives.  Every tool call mutates an in-process SchemaState; the accumulated
state is rendered after each turn so the user can see progress.

Recommended local models (in order of preference for tool calling):
  qwen2.5:7b     — best tool calling, 4.7GB, excellent schema reasoning
  llama3.2:3b    — fast, reliable tools, 2.0GB
  phi4-mini      — excellent instruction following, 2.5GB
  gemma2:2b      — smallest, ~1.5GB, adequate for simple schemas

Ollama tool-use protocol: /api/chat accepts a `tools` list in OpenAI format.
Responses may contain `tool_calls` inside `message`. We loop until no more
tool calls are pending, then return the final reply.
"""
from __future__ import annotations

import json
import logging
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Iterator

import click
import requests

_log_ = logging.getLogger(__name__)

# ─── Schema state ─────────────────────────────────────────────────────────────

_REL_TYPES = {"one-to-many", "many-to-one", "many-to-many", "one-to-one"}

# Standard PK column added to every table automatically
_PK_COL: dict[str, str] = {"name": "id", "type": "serial", "primary_key": "true"}

# Mapping from friendly type names → PostgreSQL types
_TYPE_ALIASES: dict[str, str] = {
	"string": "varchar(255)", "str": "varchar(255)",
	"text": "text", "int": "integer", "integer": "integer",
	"float": "numeric(10,2)", "decimal": "numeric(10,2)", "money": "numeric(12,2)",
	"bool": "boolean", "boolean": "boolean",
	"date": "date", "datetime": "timestamptz", "timestamp": "timestamptz",
	"json": "jsonb", "jsonb": "jsonb",
	"uuid": "uuid", "email": "varchar(320)", "url": "varchar(2048)",
	"phone": "varchar(20)", "array": "text[]",
	"inet": "inet", "cidr": "cidr",
}


def _normalise_type(t: str) -> str:
	return _TYPE_ALIASES.get(t.strip().lower(), t.strip())


@dataclass
class _Table:
	name: str
	columns: list[dict[str, str]] = field(default_factory=lambda: [dict(_PK_COL)])


@dataclass
class _Relationship:
	from_table: str
	to_table: str
	type: str


@dataclass
class SchemaState:
	app_name: str = "MyApp"
	description: str = ""
	tables: dict[str, _Table] = field(default_factory=dict)
	relationships: list[_Relationship] = field(default_factory=list)
	_undo_log: list[tuple] = field(default_factory=list)  # (op, payload)

	# ── Tool implementations ─────────────────────────────────────────────────

	def create_table(self, name: str, columns: list[dict[str, Any]]) -> str:
		name = name.strip().lower().replace(" ", "_").replace("-", "_")
		if name in self.tables:
			return f"Table '{name}' already exists — use add_column to extend it."
		cols = [dict(_PK_COL)]
		for c in columns:
			if not isinstance(c, dict) or not c.get("name"):
				continue
			cn = c["name"].strip().lower().replace(" ", "_")
			if cn == "id":
				continue
			cols.append({
				"name": cn,
				"type": _normalise_type(c.get("type", "text")),
				**{k: str(v) for k, v in c.items() if k not in ("name", "type")},
			})
		self.tables[name] = _Table(name=name, columns=cols)
		self._undo_log.append(("create_table", name))
		return f"✓ Created table '{name}' with {len(cols)} columns ({', '.join(c['name'] for c in cols)})."

	def add_column(self, table: str, column_name: str, column_type: str,
	               nullable: bool = True, default: str = "") -> str:
		table = table.strip().lower().replace(" ", "_")
		if table not in self.tables:
			return f"Table '{table}' does not exist."
		col_name = column_name.strip().lower().replace(" ", "_")
		# Don't duplicate
		existing = {c["name"] for c in self.tables[table].columns}
		if col_name in existing:
			return f"Column '{col_name}' already exists in '{table}'."
		col: dict[str, str] = {
			"name": col_name,
			"type": _normalise_type(column_type),
		}
		if not nullable:
			col["nullable"] = "false"
		if default:
			col["default"] = default
		self.tables[table].columns.append(col)
		self._undo_log.append(("add_column", (table, col_name)))
		return f"✓ Added column '{col_name}' ({col['type']}) to '{table}'."

	def remove_table(self, name: str) -> str:
		name = name.strip().lower().replace(" ", "_")
		if name not in self.tables:
			return f"Table '{name}' does not exist."
		self.tables.pop(name)
		self.relationships = [
			r for r in self.relationships
			if r.from_table != name and r.to_table != name
		]
		self._undo_log.append(("remove_table", name))
		return f"✓ Removed table '{name}' and its relationships."

	def add_relationship(self, from_table: str, to_table: str, type: str) -> str:
		from_table = from_table.strip().lower().replace(" ", "_")
		to_table = to_table.strip().lower().replace(" ", "_")
		type = type.strip().lower()
		if type not in _REL_TYPES:
			type = "one-to-many"
		missing = [t for t in (from_table, to_table) if t not in self.tables]
		if missing:
			return f"Tables not yet defined: {missing}. Create them first."
		self.relationships.append(_Relationship(from_table, to_table, type))
		self._undo_log.append(("add_relationship", None))
		return f"✓ Added {type} relationship: {from_table} → {to_table}."

	def set_app_name(self, name: str) -> str:
		old = self.app_name
		self.app_name = name.strip()
		self._undo_log.append(("set_app_name", old))
		return f"✓ Application name set to '{self.app_name}'."

	def set_description(self, text: str) -> str:
		self.description = text.strip()
		self._undo_log.append(("set_description", None))
		return "✓ Description updated."

	def show_schema(self) -> str:
		return _render_schema(self)

	def list_templates(self) -> str:
		"""List all bundled pgappforge schema templates the user can apply."""
		try:
			from pgappforge.templates.registry import TemplateRegistry
			items = TemplateRegistry().list()
			lines = ["Available templates (use apply_template to start from one):"]
			for t in items[:30]:  # cap at 30 in context
				lines.append(f"  {t['name']:<25} — {t['description'][:70]}")
			if len(items) > 30:
				lines.append(f"  … and {len(items)-30} more")
			return "\n".join(lines)
		except Exception as exc:
			return f"Could not load templates: {exc}"

	def apply_template(self, template_name: str) -> str:
		"""Import a bundled pgappforge template into the current schema."""
		try:
			from pgappforge.templates.registry import TemplateRegistry
			tmpl = TemplateRegistry().get(template_name)
		except Exception as exc:
			return f"Template '{template_name}' not found: {exc}"
		added = []
		for tname, cols in tmpl.get("tables", {}).items():
			if tname in self.tables:
				continue
			self.create_table(tname, [c for c in cols if c.get("name") != "id"])
			added.append(tname)
		self._undo_log.append(("apply_template", template_name))
		if not added:
			return f"All tables from '{template_name}' already exist."
		return f"✓ Applied template '{template_name}': added tables {added}."

	def undo(self) -> str:
		if not self._undo_log:
			return "Nothing to undo."
		op, payload = self._undo_log.pop()
		if op == "create_table":
			tname = payload
			self.tables.pop(tname, None)
			self.relationships = [
				r for r in self.relationships
				if r.from_table != tname and r.to_table != tname
			]
			return f"✓ Undone: removed table '{tname}'."
		if op == "add_column":
			tname, col_name = payload
			if tname in self.tables:
				self.tables[tname].columns = [
					c for c in self.tables[tname].columns if c["name"] != col_name
				]
			return f"✓ Undone: removed column '{col_name}' from '{tname}'."
		if op == "remove_table":
			return "✓ Note: table removal cannot be undone (data lost)."
		if op == "add_relationship":
			if self.relationships:
				self.relationships.pop()
			return "✓ Undone: removed last relationship."
		if op == "set_app_name":
			self.app_name = payload
			return f"✓ App name reverted to '{self.app_name}'."
		if op == "set_description":
			self.description = ""
			return "✓ Description cleared."
		if op == "apply_template":
			return "✓ Note: template application cannot be selectively undone."
		return f"✓ Undone: {op}."

	def generate_app(self, output_dir: str, database_uri: str = "") -> str:
		"""
		Generate the full pgappforge application from the accumulated schema.

		If database_uri is provided (postgresql://...), creates the schema tables
		directly and runs the generator. Otherwise returns the CLI command to run.
		"""
		if not self.tables:
			return "No tables defined yet — nothing to generate."
		app_slug = self.app_name.lower().replace(" ", "_")
		if not output_dir:
			output_dir = app_slug

		cmd_lines = [
			"flask forge gen all \\",
			f"  --name {app_slug} \\",
			f"  --output-dir ./{output_dir} \\",
			f"  --uri postgresql://user:pass@localhost/{app_slug}",
		]

		# If a database URI is provided, attempt to create the tables and generate
		if database_uri and database_uri.startswith("postgresql"):
			return self._generate_with_uri(database_uri, output_dir, app_slug, cmd_lines)

		return (
			"Schema is ready! Run this command to generate your application:\n\n"
			+ "\n".join(cmd_lines)
			+ "\n\n"
			+ "Or provide the database URI to generate directly:\n"
			+ "  generate_app(output_dir='./myapp', database_uri='postgresql:///mydb')"
		)

	def _generate_with_uri(self, uri: str, output_dir: str, app_slug: str,
	                       cmd_lines: list[str]) -> str:
		"""Create tables in PostgreSQL and run the generator."""
		try:
			from sqlalchemy import create_engine, text
			from pathlib import Path
			from pgappforge.cli.generators.mobile_generator import (
				MobileGenerator, MobileGenerationConfig,
			)
			from pgappforge.cli.generators.database_inspector import EnhancedDatabaseInspector

			engine = create_engine(uri)
			# Create tables from schema state
			with engine.connect() as conn:
				for tname, tbl in self.tables.items():
					col_defs = []
					for c in tbl.columns:
						defn = f"{c['name']} {c['type']}"
						if c.get("primary_key", "").lower() == "true":
							defn += " PRIMARY KEY"
						if c.get("nullable", "true").lower() == "false":
							defn += " NOT NULL"
						if c.get("default"):
							defn += f" DEFAULT {c['default']}"
						col_defs.append(defn)
					ddl = f"CREATE TABLE IF NOT EXISTS {tname} ({', '.join(col_defs)})"
					try:
						conn.execute(text(ddl))
					except Exception as e:
						_log_.warning("Could not create table %s: %s", tname, e)
				conn.commit()

			# Run the code generator
			out = Path(output_dir)
			out.mkdir(parents=True, exist_ok=True)
			cfg = MobileGenerationConfig(
				app_name=self.app_name,
				api_base_url=f"http://localhost:5000/api/v1",
			)
			with EnhancedDatabaseInspector(uri) as inspector:
				gen = MobileGenerator(inspector, cfg, out)
				files = gen.generate_complete_app()

			return (
				f"✓ Generated {len(files)} files in ./{output_dir}/\n\n"
				f"Web app command:\n" + "\n".join(cmd_lines) + "\n\n"
				f"Mobile app (Expo): cd {output_dir} && npm install && npx expo start"
			)
		except Exception as exc:
			_log_.exception("generate_with_uri failed")
			return (
				f"Direct generation failed ({exc}).\n\n"
				"Fallback — run manually:\n" + "\n".join(cmd_lines)
			)


# ─── Rendering ────────────────────────────────────────────────────────────────

def _render_schema(state: SchemaState) -> str:
	lines: list[str] = [
		f"App: {state.app_name}",
		f"Description: {state.description or '(none)'}",
		f"Tables ({len(state.tables)}):",
	]
	for tname, tbl in state.tables.items():
		col_str = ", ".join(
			f"{c['name']}:{c.get('type','text')}"
			+ (" PK" if c.get("primary_key","").lower()=="true" else "")
			for c in tbl.columns
		)
		lines.append(f"  {tname}: {col_str}")
	if state.relationships:
		lines.append(f"Relationships ({len(state.relationships)}):")
		for r in state.relationships:
			lines.append(f"  {r.from_table} --[{r.type}]--> {r.to_table}")
	else:
		lines.append("Relationships: none")
	return "\n".join(lines)


def _schema_as_mermaid(state: SchemaState) -> str:
	lines = ["erDiagram"]
	for tname, tbl in state.tables.items():
		lines.append(f"  {tname.upper()} {{")
		for col in tbl.columns:
			ctype = col.get("type", "text").replace("(", "_").replace(")", "").replace(",", "_").replace(" ", "_")
			cname = col["name"]
			pk = " PK" if col.get("primary_key", "").lower() == "true" else ""
			lines.append(f"    {ctype} {cname}{pk}")
		lines.append("  }")
	_rel_map = {
		"one-to-many": "||--o{",
		"many-to-one": "}o--||",
		"many-to-many": "}o--o{",
		"one-to-one": "||--||",
	}
	for rel in state.relationships:
		arrow = _rel_map.get(rel.type, "||--o{")
		lines.append(f'  {rel.from_table.upper()} {arrow} {rel.to_table.upper()} : ""')
	return "\n".join(lines)


# ─── Tool definitions ─────────────────────────────────────────────────────────

_TOOLS: list[dict[str, Any]] = [
	{
		"type": "function",
		"function": {
			"name": "create_table",
			"description": (
				"Add a new table to the schema. An 'id SERIAL PRIMARY KEY' column is added "
				"automatically. Use PostgreSQL types: varchar, text, integer, numeric, boolean, "
				"date, timestamptz, jsonb, uuid, inet, text[]."
			),
			"parameters": {
				"type": "object",
				"properties": {
					"name": {"type": "string", "description": "Table name (snake_case)."},
					"columns": {
						"type": "array",
						"description": "Columns. Each needs 'name' and 'type'. Optional: nullable, default.",
						"items": {"type": "object"},
					},
				},
				"required": ["name", "columns"],
			},
		},
	},
	{
		"type": "function",
		"function": {
			"name": "add_column",
			"description": "Add a column to an existing table.",
			"parameters": {
				"type": "object",
				"properties": {
					"table": {"type": "string"},
					"column_name": {"type": "string"},
					"column_type": {"type": "string", "description": "PostgreSQL type, e.g. varchar(100), integer, boolean."},
					"nullable": {"type": "boolean", "default": True},
					"default": {"type": "string", "description": "SQL default expression (optional)."},
				},
				"required": ["table", "column_name", "column_type"],
			},
		},
	},
	{
		"type": "function",
		"function": {
			"name": "remove_table",
			"description": "Remove a table and all its relationships from the schema.",
			"parameters": {
				"type": "object",
				"properties": {"name": {"type": "string"}},
				"required": ["name"],
			},
		},
	},
	{
		"type": "function",
		"function": {
			"name": "add_relationship",
			"description": "Add a foreign-key relationship between two existing tables.",
			"parameters": {
				"type": "object",
				"properties": {
					"from_table": {"type": "string"},
					"to_table": {"type": "string"},
					"type": {
						"type": "string",
						"enum": list(_REL_TYPES),
					},
				},
				"required": ["from_table", "to_table", "type"],
			},
		},
	},
	{
		"type": "function",
		"function": {
			"name": "set_app_name",
			"description": "Set the application name.",
			"parameters": {
				"type": "object",
				"properties": {"name": {"type": "string"}},
				"required": ["name"],
			},
		},
	},
	{
		"type": "function",
		"function": {
			"name": "set_description",
			"description": "Set a one-paragraph description of the application.",
			"parameters": {
				"type": "object",
				"properties": {"text": {"type": "string"}},
				"required": ["text"],
			},
		},
	},
	{
		"type": "function",
		"function": {
			"name": "show_schema",
			"description": "Display the current schema to the user.",
			"parameters": {"type": "object", "properties": {}},
		},
	},
	{
		"type": "function",
		"function": {
			"name": "list_templates",
			"description": (
				"List all 55 bundled pgappforge schema templates (healthcare, finance, "
				"geospatial, etc.) that can be used as starting points."
			),
			"parameters": {"type": "object", "properties": {}},
		},
	},
	{
		"type": "function",
		"function": {
			"name": "apply_template",
			"description": (
				"Import a bundled schema template into the current schema. "
				"E.g. 'fhir-r4', 'icd10', 'geonames', 'gtfs', 'iso20022'."
			),
			"parameters": {
				"type": "object",
				"properties": {
					"template_name": {
						"type": "string",
						"description": "Template name from list_templates, e.g. 'fhir-r4'.",
					},
				},
				"required": ["template_name"],
			},
		},
	},
	{
		"type": "function",
		"function": {
			"name": "undo",
			"description": "Undo the last schema operation.",
			"parameters": {"type": "object", "properties": {}},
		},
	},
	{
		"type": "function",
		"function": {
			"name": "generate_app",
			"description": (
				"Generate the pgappforge application once the schema is complete. "
				"Call when the user says 'generate', 'build', 'done', or is satisfied. "
				"Optionally provide database_uri to create tables and generate immediately."
			),
			"parameters": {
				"type": "object",
				"properties": {
					"output_dir": {"type": "string", "description": "Output directory."},
					"database_uri": {
						"type": "string",
						"description": "PostgreSQL URI (postgresql://...) to create tables and generate now.",
					},
				},
				"required": [],
			},
		},
	},
]

# Structured system prompt — works well for 7B models
_SYSTEM_PROMPT = """\
You are pgappforge, an expert PostgreSQL application architect.

Your job: help the user design a database schema, then generate a complete web/mobile app.

WORKFLOW:
1. Listen to what the user wants to build.
2. Call set_app_name with a snake_case name.
3. Call set_description with a brief summary.
4. Call create_table for each entity. Use proper PostgreSQL types:
   - Text: varchar(255) for names/titles, text for long content
   - Numbers: integer, numeric(10,2) for money
   - Dates: date, timestamptz
   - Rich data: jsonb for flexible attributes
   - Identity: uuid (when specified), serial (default PK)
   - Domain-specific: inet, cidr, text[] for arrays
5. Call add_relationship to link tables.
6. Ask clarifying questions if the domain is unclear.
7. When the user says "done", "generate", "build it", or similar — call generate_app.

IMPORTANT:
- Always explain what you're doing BEFORE each tool call.
- After tool calls, summarise what was created in plain English.
- If the user mentions a domain (healthcare, finance, logistics), suggest using list_templates.
- Keep explanations short — 1-3 sentences per turn.
- Do not invent tables the user didn't ask for.
"""


# ─── Ollama chat engine ───────────────────────────────────────────────────────

# Models known to support tool calling well with Ollama
RECOMMENDED_MODELS: dict[str, str] = {
	"qwen2.5:7b": "Best tool calling, 4.7GB — recommended",
	"llama3.2:3b": "Fast, reliable tools, 2.0GB",
	"phi4-mini": "Good instruction following, 2.5GB",
	"mistral:7b": "Reliable, 4.1GB",
	"gemma2:2b": "Smallest option, 1.5GB — limited tool reliability",
}


class AppCreatorChat:
	"""
	Drives a multi-turn conversation with an Ollama model that builds a
	pgappforge schema via tool calls.
	"""

	def __init__(
		self,
		ollama_url: str = "http://localhost:11434",
		model: str = "qwen2.5:7b",
		stream: bool = True,
	) -> None:
		self.ollama_url = ollama_url.rstrip("/")
		self.model = model
		self.stream = stream
		self.state = SchemaState()
		self._messages: list[dict[str, Any]] = [
			{"role": "system", "content": _SYSTEM_PROMPT},
		]

	# ── Public API ────────────────────────────────────────────────────────────

	def start_session(self) -> None:
		"""Blocking interactive REPL."""
		click.echo(click.style("pgappforge · App Creator", fg="cyan", bold=True))
		click.echo(f"Model  : {self.model}")
		click.echo(f"Ollama : {self.ollama_url}")
		click.echo(f"Type 'templates' to see 55 built-in schemas, 'quit' to exit.\n")

		self._check_ollama()

		try:
			while True:
				try:
					user_input = click.prompt(click.style("You", fg="green", bold=True))
				except (EOFError, KeyboardInterrupt):
					click.echo("\nBye.")
					break

				lower = user_input.strip().lower()
				if lower in {"quit", "exit", "q", "bye"}:
					click.echo("Bye.")
					break
				if lower == "templates":
					user_input = "List the available templates"

				click.echo()
				if self.stream:
					self._process_message_streaming(user_input)
				else:
					reply = self.process_message(user_input)
					click.echo(click.style("pgappforge", fg="cyan", bold=True) + ": " + reply)

				click.echo()
				click.echo(click.style("─" * 60, fg="bright_black"))
				click.echo(self._schema_state())
				click.echo(click.style("─" * 60, fg="bright_black"))
				click.echo()
		except Exception as exc:
			click.echo(click.style(f"Fatal error: {exc}", fg="red"), err=True)
			raise SystemExit(1) from exc

	def process_message(self, user_input: str) -> str:
		"""Send user_input, execute tool calls, return final reply string."""
		self._messages.append({"role": "user", "content": user_input})

		for _iteration in range(10):
			response = self._call_ollama(self._messages, _TOOLS, stream=False)
			msg = response.get("message", {})
			tool_calls: list[dict[str, Any]] = msg.get("tool_calls") or []

			if not tool_calls:
				content: str = msg.get("content") or "(no response)"
				self._messages.append({"role": "assistant", "content": content})
				return content

			self._messages.append({
				"role": "assistant",
				"content": msg.get("content") or "",
				"tool_calls": tool_calls,
			})

			for tc in tool_calls:
				fn = tc.get("function", {})
				name = fn.get("name", "")
				args_raw = fn.get("arguments", {})
				args: dict[str, Any] = (
					json.loads(args_raw) if isinstance(args_raw, str) else (args_raw or {})
				)
				result = self._execute_tool(name, args)
				_log_.debug("tool %s(%s) -> %s", name, args, result)
				self._messages.append({
					"role": "tool",
					"name": name,
					"content": result,
				})

		return "(tool iteration limit reached — please rephrase your request)"

	def _process_message_streaming(self, user_input: str) -> None:
		"""Process a message with streaming output for the CLI."""
		self._messages.append({"role": "user", "content": user_input})
		prefix = click.style("pgappforge", fg="cyan", bold=True) + ": "

		for _iteration in range(10):
			# First pass: get full response (need to handle tool calls atomically)
			response = self._call_ollama(self._messages, _TOOLS, stream=False)
			msg = response.get("message", {})
			tool_calls: list[dict[str, Any]] = msg.get("tool_calls") or []

			if not tool_calls:
				content = msg.get("content") or ""
				self._messages.append({"role": "assistant", "content": content})
				# Simulate streaming by printing word by word
				click.echo(prefix, nl=False)
				for word in content.split():
					click.echo(word + " ", nl=False)
					sys.stdout.flush()
				click.echo()
				return

			# Print partial content if any
			partial = msg.get("content") or ""
			if partial.strip():
				click.echo(prefix + partial)

			self._messages.append({
				"role": "assistant",
				"content": partial,
				"tool_calls": tool_calls,
			})

			for tc in tool_calls:
				fn = tc.get("function", {})
				name = fn.get("name", "")
				args_raw = fn.get("arguments", {})
				args: dict[str, Any] = (
					json.loads(args_raw) if isinstance(args_raw, str) else (args_raw or {})
				)
				click.echo(click.style(f"  [{name}] ", fg="yellow"), nl=False)
				result = self._execute_tool(name, args)
				click.echo(click.style(result, fg="green"))
				self._messages.append({
					"role": "tool",
					"name": name,
					"content": result,
				})

	# ── Ollama API ────────────────────────────────────────────────────────────

	def _call_ollama(
		self,
		messages: list[dict[str, Any]],
		tools: list[dict[str, Any]],
		stream: bool = False,
	) -> dict[str, Any]:
		url = f"{self.ollama_url}/api/chat"
		payload = {
			"model": self.model,
			"messages": messages,
			"tools": tools,
			"stream": stream,
			"options": {
				"temperature": 0.1,   # low temperature for deterministic tool calls
				"num_ctx": 8192,      # context window
			},
		}
		try:
			resp = requests.post(url, json=payload, timeout=180)
			resp.raise_for_status()
			return resp.json()
		except requests.ConnectionError as exc:
			raise RuntimeError(
				f"Cannot reach Ollama at {self.ollama_url}. Run: ollama serve"
			) from exc
		except requests.HTTPError as exc:
			raise RuntimeError(f"Ollama API error: {exc.response.text}") from exc

	def _execute_tool(self, name: str, args: dict[str, Any]) -> str:
		dispatch = {
			"create_table": lambda: self.state.create_table(
				args.get("name", ""), args.get("columns", []),
			),
			"add_column": lambda: self.state.add_column(
				args.get("table", ""), args.get("column_name", ""),
				args.get("column_type", "text"),
				args.get("nullable", True), args.get("default", ""),
			),
			"remove_table": lambda: self.state.remove_table(args.get("name", "")),
			"add_relationship": lambda: self.state.add_relationship(
				args.get("from_table", ""), args.get("to_table", ""),
				args.get("type", "one-to-many"),
			),
			"set_app_name": lambda: self.state.set_app_name(args.get("name", "")),
			"set_description": lambda: self.state.set_description(args.get("text", "")),
			"show_schema": lambda: self.state.show_schema(),
			"list_templates": lambda: self.state.list_templates(),
			"apply_template": lambda: self.state.apply_template(args.get("template_name", "")),
			"undo": lambda: self.state.undo(),
			"generate_app": lambda: self.state.generate_app(
				args.get("output_dir", ""),
				args.get("database_uri", ""),
			),
		}
		handler = dispatch.get(name)
		if handler is None:
			return f"Unknown tool: {name}"
		try:
			return handler()
		except Exception as exc:
			_log_.exception("tool %s failed", name)
			return f"Error in {name}: {exc}"

	def _schema_state(self) -> str:
		return _render_schema(self.state)

	def _check_ollama(self) -> None:
		"""Verify Ollama is reachable and recommend a model if needed."""
		try:
			r = requests.get(f"{self.ollama_url}/api/tags", timeout=5)
			r.raise_for_status()
			tags = r.json()
			names = [m["name"] for m in tags.get("models", [])]
			model_base = self.model.split(":")[0]
			if not any(n.startswith(model_base) for n in names):
				click.echo(
					click.style(
						f"Model '{self.model}' not found locally. Pulling…",
						fg="yellow",
					)
				)
				result = subprocess.run(["ollama", "pull", self.model], check=False)
				if result.returncode != 0:
					click.echo(click.style(
						f"Pull failed. Available models: {', '.join(names[:5]) or 'none'}\n"
						f"Recommended: {list(RECOMMENDED_MODELS)[0]}",
						fg="yellow",
					))
		except requests.ConnectionError:
			click.echo(
				click.style(
					f"⚠  Cannot reach Ollama at {self.ollama_url}.\n"
					"   Start it with:  ollama serve\n"
					"   Install from:   https://ollama.com",
					fg="yellow",
				),
				err=True,
			)


# ─── CLI command ──────────────────────────────────────────────────────────────

@click.command("chat-create")
@click.option(
	"--model", "-m",
	default="qwen2.5:7b",
	show_default=True,
	envvar="PGAF_OLLAMA_MODEL",
	help=(
		"Ollama model tag. Best for tool calling: qwen2.5:7b (recommended), "
		"llama3.2:3b, phi4-mini, mistral:7b."
	),
)
@click.option(
	"--ollama-url",
	default="http://localhost:11434",
	show_default=True,
	envvar="PGAF_OLLAMA_URL",
	help="Base URL of the Ollama server.",
)
@click.option(
	"--no-stream",
	is_flag=True,
	help="Disable streaming output (wait for full response).",
)
@click.option(
	"--list-models",
	is_flag=True,
	help="List recommended models and exit.",
)
def chat_create(model: str, ollama_url: str, no_stream: bool, list_models: bool) -> None:
	"""
	AI-assisted conversational app designer powered by a local Ollama model.

	Describe the application you want to build in plain English. The model will
	ask questions, create tables and relationships, and generate the full
	pgappforge application when you are satisfied.

	\b
	Recommended models (install with: ollama pull <model>):
	  qwen2.5:7b    — best tool calling, 4.7GB  ← default
	  llama3.2:3b   — fast, 2.0GB
	  phi4-mini     — good reasoning, 2.5GB

	\b
	Examples:
	  flask forge chat-create
	  flask forge chat-create --model llama3.2:3b
	  PGAF_OLLAMA_MODEL=qwen2.5:7b flask forge chat-create
	"""
	if list_models:
		click.echo("Recommended Ollama models for pgappforge chat-create:\n")
		for m, desc in RECOMMENDED_MODELS.items():
			click.echo(f"  {m:<20}  {desc}")
		click.echo("\nInstall:  ollama pull qwen2.5:7b")
		return

	chat = AppCreatorChat(
		ollama_url=ollama_url,
		model=model,
		stream=not no_stream,
	)
	chat.start_session()


# ─── Web view ─────────────────────────────────────────────────────────────────

_WEB_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>App Creator · pgappforge</title>
<script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
<style>
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  background: #0f1117; color: #e2e8f0; height: 100vh;
  display: grid; grid-template-columns: 1fr 380px; grid-template-rows: 52px 1fr;
}
header {
  grid-column: 1 / -1;
  display: flex; align-items: center; gap: 12px; padding: 0 20px;
  background: #1a1f2e; border-bottom: 1px solid #2d3554;
}
header h1 { font-size: .95rem; font-weight: 600; color: #7dd3fc; letter-spacing: .04em; }
.header-right { display: flex; align-items: center; gap: 10px; margin-left: auto; }
.model-select {
  background: #1e293b; color: #93c5fd; border: 1px solid #334155;
  border-radius: 6px; padding: 4px 8px; font-size: .75rem; cursor: pointer;
}
.badge { font-size: .72rem; background: #1e3a5f; color: #93c5fd; padding: 3px 8px; border-radius: 999px; }
#chat-panel { display: flex; flex-direction: column; border-right: 1px solid #2d3554; }
#messages { flex: 1; overflow-y: auto; padding: 16px; display: flex; flex-direction: column; gap: 12px; }
.msg { max-width: 88%; line-height: 1.55; font-size: .88rem; }
.msg.user {
  align-self: flex-end; background: #1e3a5f; color: #e2e8f0;
  padding: 10px 14px; border-radius: 14px 14px 4px 14px;
}
.msg.assistant {
  align-self: flex-start; background: #1e293b; color: #cbd5e1;
  padding: 10px 14px; border-radius: 14px 14px 14px 4px; white-space: pre-wrap;
}
.msg.tool {
  align-self: flex-start; background: #0f2e1a; color: #6ee7b7;
  padding: 6px 12px; border-radius: 8px; font-family: monospace; font-size: .78rem;
}
.msg.error {
  align-self: flex-start; background: #2e1515; color: #fca5a5;
  padding: 8px 12px; border-radius: 8px; font-size: .82rem;
}
.msg.thinking { align-self: flex-start; color: #4b5563; font-style: italic; font-size: .82rem; }
#input-row {
  display: flex; gap: 8px; padding: 12px 16px;
  border-top: 1px solid #2d3554; background: #12161f;
}
#user-input {
  flex: 1; background: #1e293b; color: #e2e8f0; border: 1px solid #334155;
  border-radius: 8px; padding: 10px 12px; font-size: .88rem;
  resize: none; height: 44px; outline: none; transition: border-color .15s;
}
#user-input:focus { border-color: #3b82f6; }
#send-btn {
  padding: 0 18px; background: #2563eb; color: #fff; border: none;
  border-radius: 8px; cursor: pointer; font-size: .88rem; font-weight: 600;
  transition: background .15s;
}
#send-btn:hover:not(:disabled) { background: #1d4ed8; }
#send-btn:disabled { background: #1e3a5f; cursor: not-allowed; }
#schema-panel { display: flex; flex-direction: column; overflow: hidden; }
#schema-tabs { display: flex; border-bottom: 1px solid #2d3554; background: #12161f; }
.tab-btn {
  flex: 1; padding: 10px 0; font-size: .78rem; font-weight: 600;
  background: none; border: none; color: #64748b; cursor: pointer;
  letter-spacing: .04em; transition: color .15s;
}
.tab-btn.active { color: #7dd3fc; border-bottom: 2px solid #3b82f6; }
#schema-text {
  flex: 1; overflow-y: auto; padding: 14px; font-family: monospace;
  font-size: .78rem; color: #94a3b8; white-space: pre; background: #0f1117;
}
#schema-diagram { flex: 1; overflow: auto; padding: 14px; background: #0f1117; display: none; }
.mermaid { filter: invert(85%) hue-rotate(180deg); }
#action-bar {
  display: flex; gap: 8px; padding: 10px 14px;
  border-top: 1px solid #2d3554; background: #12161f;
}
.action-btn {
  flex: 1; padding: 8px 0; font-size: .76rem; font-weight: 600; border: none;
  border-radius: 6px; cursor: pointer; transition: opacity .15s;
}
.action-btn:hover { opacity: .85; }
#gen-btn { background: #16a34a; color: #fff; }
#reset-btn { background: #2d3554; color: #94a3b8; flex: 0; padding: 8px 14px; }
#copy-btn { background: #1e3a5f; color: #93c5fd; flex: 0; padding: 8px 14px; }
</style>
</head>
<body>
<header>
  <h1>pgappforge · App Creator Chat</h1>
  <div class="header-right">
    <select class="model-select" id="model-select">
      <option value="qwen2.5:7b">qwen2.5:7b ★</option>
      <option value="llama3.2:3b">llama3.2:3b</option>
      <option value="phi4-mini">phi4-mini</option>
      <option value="mistral:7b">mistral:7b</option>
      <option value="gemma2:2b">gemma2:2b</option>
    </select>
    <span class="badge" id="status-badge">connecting…</span>
  </div>
</header>

<section id="chat-panel">
  <div id="messages"></div>
  <div id="input-row">
    <textarea id="user-input" placeholder="Describe the app you want to build…" rows="1"></textarea>
    <button id="send-btn">Send</button>
  </div>
</section>

<aside id="schema-panel">
  <div id="schema-tabs">
    <button class="tab-btn active" data-tab="text">Schema</button>
    <button class="tab-btn" data-tab="diagram">ERD</button>
  </div>
  <pre id="schema-text">No tables yet.</pre>
  <div id="schema-diagram"><div class="mermaid" id="mermaid-src"></div></div>
  <div id="action-bar">
    <button class="action-btn" id="gen-btn">⚡ Generate App</button>
    <button class="action-btn" id="copy-btn">Copy CMD</button>
    <button class="action-btn" id="reset-btn">Reset</button>
  </div>
</aside>

<script>
mermaid.initialize({ startOnLoad: false, theme: 'default' });

const messagesEl = document.getElementById('messages');
const inputEl    = document.getElementById('user-input');
const sendBtn    = document.getElementById('send-btn');
const schemaTextEl = document.getElementById('schema-text');
const mermaidSrc = document.getElementById('mermaid-src');
const statusBadge = document.getElementById('status-badge');
const modelSelect = document.getElementById('model-select');
let currentTab = 'text';
let lastSchemaText = '';

document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    currentTab = btn.dataset.tab;
    document.getElementById('schema-text').style.display = currentTab === 'text' ? 'block' : 'none';
    document.getElementById('schema-diagram').style.display = currentTab === 'diagram' ? 'block' : 'none';
    if (currentTab === 'diagram') renderMermaid();
  });
});

function renderMermaid() {
  const src = mermaidSrc.textContent.trim();
  if (!src || src === 'erDiagram') return;
  mermaid.render('erd-svg', src).then(({svg}) => {
    mermaidSrc.innerHTML = svg;
  }).catch(() => {});
}

function appendMessage(role, text) {
  const div = document.createElement('div');
  div.className = 'msg ' + role;
  div.textContent = text;
  messagesEl.appendChild(div);
  messagesEl.scrollTop = messagesEl.scrollHeight;
  return div;
}

function updateSchema(text, mermaid) {
  lastSchemaText = text;
  schemaTextEl.textContent = text;
  mermaidSrc.textContent = mermaid;
  mermaidSrc.removeAttribute('data-processed');
  if (currentTab === 'diagram') renderMermaid();
}

async function sendMessage() {
  const text = inputEl.value.trim();
  if (!text) return;
  inputEl.value = '';
  sendBtn.disabled = true;
  appendMessage('user', text);
  const thinking = appendMessage('thinking', '…');

  try {
    const res = await fetch('/app-creator/chat', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ message: text, model: modelSelect.value }),
    });
    const data = await res.json();
    thinking.remove();
    if (!res.ok) { appendMessage('error', data.error || 'Server error'); return; }
    if (data.tool_log) data.tool_log.forEach(e => appendMessage('tool', e));
    appendMessage('assistant', data.reply);
    updateSchema(data.schema_text, data.schema_mermaid);
    statusBadge.textContent = data.model || '';
  } catch (err) {
    thinking.remove();
    appendMessage('error', 'Request failed: ' + err.message);
  } finally {
    sendBtn.disabled = false;
    inputEl.focus();
  }
}

document.getElementById('gen-btn').addEventListener('click', async () => {
  sendBtn.disabled = true;
  appendMessage('user', '(generate app)');
  const thinking = appendMessage('thinking', 'Generating…');
  try {
    const res = await fetch('/app-creator/chat', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ message: 'generate the app now', model: modelSelect.value }),
    });
    const data = await res.json();
    thinking.remove();
    appendMessage('assistant', data.reply);
    updateSchema(data.schema_text, data.schema_mermaid);
  } finally { sendBtn.disabled = false; }
});

document.getElementById('copy-btn').addEventListener('click', () => {
  navigator.clipboard.writeText(lastSchemaText).then(() => {
    document.getElementById('copy-btn').textContent = 'Copied!';
    setTimeout(() => document.getElementById('copy-btn').textContent = 'Copy CMD', 1500);
  });
});

document.getElementById('reset-btn').addEventListener('click', async () => {
  if (!confirm('Reset schema? This cannot be undone.')) return;
  await fetch('/app-creator/reset', { method: 'POST' });
  messagesEl.innerHTML = '';
  updateSchema('No tables yet.', 'erDiagram');
  appendMessage('assistant', 'Schema reset. What would you like to build?');
});

sendBtn.addEventListener('click', sendMessage);
inputEl.addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
});

// Init
fetch('/app-creator/state').then(r => r.json()).then(d => {
  modelSelect.value = d.model || 'qwen2.5:7b';
  statusBadge.textContent = d.model || '';
  updateSchema(d.schema_text || 'No tables yet.', d.schema_mermaid || 'erDiagram');
  appendMessage('assistant',
    'Hello! Describe the app you want to build.\\n\\n' +
    'Tip: say "list templates" to see 55 ready-made schemas (healthcare, finance, geospatial, and more).');
}).catch(() => {
  statusBadge.textContent = 'offline';
  appendMessage('error', 'Cannot connect to pgappforge. Is the server running?');
});
</script>
</body>
</html>
"""


def _make_web_chat_class() -> type:
	"""Build AppCreatorView dynamically (defers Flask imports)."""
	from flask import jsonify, render_template_string, request as flask_request
	from pgappforge.baseviews import BaseView, expose

	class AppCreatorView(BaseView):
		"""
		Web chat interface for the Ollama-powered app creator.

		Routes:
		  GET  /app-creator/        chat UI
		  GET  /app-creator/state   current schema as JSON
		  POST /app-creator/chat    process one message
		  POST /app-creator/reset   clear schema
		"""

		route_base = "/app-creator"
		default_view = "index"

		def __init__(self) -> None:
			super().__init__()
			self._chat: AppCreatorChat | None = None

		def _get_chat(self, model: str | None = None) -> AppCreatorChat:
			from flask import current_app
			cfg = current_app.config
			url = cfg.get("PGAF_OLLAMA_URL", cfg.get("OLLAMA_URL", "http://localhost:11434"))
			default_model = cfg.get("PGAF_OLLAMA_MODEL", cfg.get("OLLAMA_MODEL", "qwen2.5:7b"))
			use_model = model or default_model
			if self._chat is None or self._chat.model != use_model:
				self._chat = AppCreatorChat(ollama_url=url, model=use_model, stream=False)
			return self._chat

		@expose("/")
		def index(self):
			return render_template_string(_WEB_TEMPLATE)

		@expose("/state")
		def state(self):
			chat = self._get_chat()
			return jsonify({
				"model": chat.model,
				"schema_text": _render_schema(chat.state),
				"schema_mermaid": _schema_as_mermaid(chat.state),
			})

		@expose("/chat", methods=["POST"])
		def chat(self):
			data = flask_request.get_json(force=True, silent=True) or {}
			user_msg: str = (data.get("message") or "").strip()
			if not user_msg:
				return jsonify({"error": "empty message"}), 400

			model = data.get("model") or None
			chat_obj = self._get_chat(model)

			tool_log: list[str] = []
			original_execute = chat_obj._execute_tool

			def _instrumented(name: str, args: dict[str, Any]) -> str:
				result = original_execute(name, args)
				tool_log.append(f"[{name}] {result}")
				return result

			chat_obj._execute_tool = _instrumented  # type: ignore[method-assign]
			try:
				reply = chat_obj.process_message(user_msg)
			except Exception as exc:
				_log_.exception("chat error")
				return jsonify({"error": str(exc)}), 500
			finally:
				chat_obj._execute_tool = original_execute  # type: ignore[method-assign]

			return jsonify({
				"reply": reply,
				"tool_log": tool_log,
				"schema_text": _render_schema(chat_obj.state),
				"schema_mermaid": _schema_as_mermaid(chat_obj.state),
				"model": chat_obj.model,
			})

		@expose("/reset", methods=["POST"])
		def reset(self):
			if self._chat is not None:
				self._chat.state = SchemaState()
				self._chat._messages = [{"role": "system", "content": _SYSTEM_PROMPT}]
			return jsonify({
				"ok": True,
				"schema_text": _render_schema(SchemaState()),
				"schema_mermaid": _schema_as_mermaid(SchemaState()),
			})

	return AppCreatorView


def get_app_creator_view_class() -> type:
	"""Return the AppCreatorView class (Flask imports deferred)."""
	return _make_web_chat_class()
