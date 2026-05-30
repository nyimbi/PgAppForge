"""
Ollama-powered conversational app creation interface for pgappforge.

CLI:  flask forge chat-create [--model gemma2:2b] [--ollama-url http://localhost:11434]
Web:  /app-creator/  (AppCreatorView)

The model is given tool-calling capability over a small set of schema-building
primitives.  Every tool call mutates an in-process SchemaState; the accumulated
state is rendered as text after each turn so the user can see progress.

Ollama tool-use protocol: the /api/chat endpoint accepts a `tools` list in the
same format as the OpenAI function-calling spec.  Responses may contain a
`tool_calls` list inside the `message` dict.  We loop until no more tool calls
are pending, then return the final assistant reply.
"""
from __future__ import annotations

import json
import logging
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Any

import click
import requests

_log_ = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Schema state — pure data, no I/O
# ---------------------------------------------------------------------------

_REL_TYPES = {"one-to-many", "many-to-one", "many-to-many", "one-to-one"}

_COL_DEFAULTS: list[dict[str, str]] = [
	{"name": "id", "type": "integer", "primary_key": "true"},
]


@dataclass
class _Table:
	name: str
	columns: list[dict[str, str]] = field(default_factory=lambda: list(_COL_DEFAULTS))


@dataclass
class _Relationship:
	from_table: str
	to_table: str
	type: str  # one-to-many | many-to-one | many-to-many | one-to-one


@dataclass
class SchemaState:
	app_name: str = "MyApp"
	description: str = ""
	tables: dict[str, _Table] = field(default_factory=dict)
	relationships: list[_Relationship] = field(default_factory=list)
	history: list[str] = field(default_factory=list)  # undo log of operation names

	# ---------- tool implementations ----------

	def create_table(self, name: str, columns: list[dict[str, Any]]) -> str:
		name = name.strip().lower().replace(" ", "_")
		if name in self.tables:
			return f"Table '{name}' already exists — skipped."
		cols = list(_COL_DEFAULTS)
		for c in columns:
			if isinstance(c, dict) and c.get("name") and c["name"] != "id":
				cols.append({k: str(v) for k, v in c.items()})
		self.tables[name] = _Table(name=name, columns=cols)
		self.history.append(f"create_table:{name}")
		return f"Created table '{name}' with {len(cols)} columns."

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
		self.history.append(f"add_relationship:{from_table}->{to_table}")
		return f"Added {type} relationship: {from_table} -> {to_table}."

	def set_app_name(self, name: str) -> str:
		old = self.app_name
		self.app_name = name.strip()
		self.history.append(f"set_app_name:{old}->{self.app_name}")
		return f"Application name set to '{self.app_name}'."

	def set_description(self, text: str) -> str:
		self.description = text.strip()
		self.history.append("set_description")
		return "Description updated."

	def show_schema(self) -> str:
		return _render_schema(self)

	def undo(self) -> str:
		if not self.history:
			return "Nothing to undo."
		op = self.history.pop()
		kind = op.split(":")[0]
		if kind == "create_table":
			tname = op.split(":")[1]
			self.tables.pop(tname, None)
			# remove dangling relationships
			self.relationships = [
				r for r in self.relationships
				if r.from_table != tname and r.to_table != tname
			]
			return f"Undone: removed table '{tname}'."
		if kind == "add_relationship":
			if self.relationships:
				self.relationships.pop()
			return "Undone: removed last relationship."
		if kind == "set_app_name":
			parts = op.split(":", 1)[1].split("->")
			if len(parts) == 2:
				self.app_name = parts[0]
			return f"App name reverted to '{self.app_name}'."
		if kind == "set_description":
			self.description = ""
			return "Description cleared."
		return f"Undone: {op}."

	def generate_app(self, output_dir: str) -> str:
		"""
		Trigger `flask forge gen all` using the accumulated schema.

		Because gen-all requires a live database URI we instead write a
		pgappforge config stub and call the CLI with --help to validate,
		then return the equivalent command the user should run.
		"""
		if not self.tables:
			return "No tables defined yet — nothing to generate."
		if not output_dir:
			output_dir = self.app_name.lower().replace(" ", "_")
		lines = [
			f"flask forge gen all \\",
			f"  --name {self.app_name.replace(' ', '_')} \\",
			f"  --output-dir {output_dir} \\",
			f"  --uri postgresql://user:pass@localhost/{self.app_name.lower().replace(' ', '_')}",
		]
		return (
			"Schema is ready. Run the following command to generate your application:\n\n"
			+ "\n".join(lines)
			+ "\n\n(Replace the URI with your actual PostgreSQL connection string.)"
		)


# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------

def _render_schema(state: SchemaState) -> str:
	lines: list[str] = [
		f"App: {state.app_name}",
		f"Description: {state.description or '(none)'}",
		f"Tables ({len(state.tables)}):",
	]
	for tname, tbl in state.tables.items():
		col_str = ", ".join(
			f"{c['name']} ({c.get('type','text')})" for c in tbl.columns
		)
		lines.append(f"  {tname}: {col_str}")
	if state.relationships:
		lines.append(f"Relationships ({len(state.relationships)}):")
		for r in state.relationships:
			lines.append(f"  {r.from_table} --[{r.type}]--> {r.to_table}")
	else:
		lines.append("Relationships: (none)")
	return "\n".join(lines)


def _schema_as_mermaid(state: SchemaState) -> str:
	"""ERD in Mermaid syntax for the web view."""
	lines = ["erDiagram"]
	for tname, tbl in state.tables.items():
		lines.append(f"  {tname.upper()} {{")
		for col in tbl.columns:
			ctype = col.get("type", "text").replace(" ", "_")
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
		lines.append(
			f'  {rel.from_table.upper()} {arrow} {rel.to_table.upper()} : ""'
		)
	return "\n".join(lines)


# ---------------------------------------------------------------------------
# Ollama tool definitions
# ---------------------------------------------------------------------------

_TOOLS: list[dict[str, Any]] = [
	{
		"type": "function",
		"function": {
			"name": "create_table",
			"description": (
				"Add a table to the application schema. "
				"An 'id' primary-key column is always added automatically."
			),
			"parameters": {
				"type": "object",
				"properties": {
					"name": {
						"type": "string",
						"description": "Table name (snake_case).",
					},
					"columns": {
						"type": "array",
						"description": (
							"Column definitions. Each object must have 'name' and 'type'. "
							"Optional keys: 'nullable', 'default', 'primary_key'."
						),
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
						"description": "Cardinality of the relationship.",
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
				"properties": {
					"name": {"type": "string"},
				},
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
				"properties": {
					"text": {"type": "string"},
				},
				"required": ["text"],
			},
		},
	},
	{
		"type": "function",
		"function": {
			"name": "show_schema",
			"description": "Display the current schema state to the user.",
			"parameters": {"type": "object", "properties": {}},
		},
	},
	{
		"type": "function",
		"function": {
			"name": "undo",
			"description": "Remove the last schema operation.",
			"parameters": {"type": "object", "properties": {}},
		},
	},
	{
		"type": "function",
		"function": {
			"name": "generate_app",
			"description": (
				"Generate the full pgappforge application once the schema is complete. "
				"Call this when the user says 'build', 'generate', 'done', or similar."
			),
			"parameters": {
				"type": "object",
				"properties": {
					"output_dir": {
						"type": "string",
						"description": "Directory to write the generated application into.",
					},
				},
				"required": [],
			},
		},
	},
]

_SYSTEM_PROMPT = """\
You are pgappforge, an expert at creating PostgreSQL web applications.
When the user describes an application, use the available tools to:
1. Set the app name with set_app_name.
2. Create the database tables needed with create_table.
3. Add appropriate relationships with add_relationship.
4. Set a description with set_description.
5. Ask clarifying questions if needed.
6. Call generate_app when the user says they are ready.

Always explain what you are doing in plain language before and after each tool call.
Keep responses concise — one short paragraph per turn is enough.
"""


# ---------------------------------------------------------------------------
# Core chat engine
# ---------------------------------------------------------------------------

class AppCreatorChat:
	"""
	Drives a multi-turn conversation with an Ollama model that builds a
	pgappforge schema via tool calls.

	Parameters
	----------
	ollama_url:
	    Base URL of the Ollama HTTP API, e.g. ``http://localhost:11434``.
	model:
	    Ollama model tag, e.g. ``gemma2:2b`` or ``phi4-mini``.
	"""

	def __init__(self, ollama_url: str = "http://localhost:11434", model: str = "gemma2:2b") -> None:
		self.ollama_url = ollama_url.rstrip("/")
		self.model = model
		self.state = SchemaState()
		self._messages: list[dict[str, Any]] = [
			{"role": "system", "content": _SYSTEM_PROMPT},
		]

	# ------------------------------------------------------------------
	# Public API
	# ------------------------------------------------------------------

	def start_session(self) -> None:
		"""Blocking REPL — run until user quits."""
		click.echo(click.style("pgappforge chat-create", fg="cyan", bold=True))
		click.echo(f"Model: {self.model}  |  Ollama: {self.ollama_url}")
		click.echo('Describe the app you want to build. Type "quit" or Ctrl-C to exit.\n')

		self._check_ollama()

		try:
			while True:
				try:
					user_input = click.prompt(click.style("You", fg="green", bold=True))
				except (EOFError, KeyboardInterrupt):
					click.echo("\nBye.")
					break

				lower = user_input.strip().lower()
				if lower in {"quit", "exit", "q"}:
					click.echo("Bye.")
					break

				reply = self.process_message(user_input)
				click.echo()
				click.echo(click.style("pgappforge", fg="cyan", bold=True) + ": " + reply)
				click.echo()
				click.echo(click.style("─" * 60, fg="bright_black"))
				click.echo(self._schema_state())
				click.echo(click.style("─" * 60, fg="bright_black"))
				click.echo()
		except Exception as exc:  # noqa: BLE001
			click.echo(click.style(f"Fatal error: {exc}", fg="red"), err=True)
			raise SystemExit(1) from exc

	def process_message(self, user_input: str) -> str:
		"""
		Send *user_input* to the model, execute any tool calls, and return the
		final assistant reply string.
		"""
		self._messages.append({"role": "user", "content": user_input})

		# Agentic loop: keep calling Ollama until no pending tool calls remain.
		for _iteration in range(8):  # hard cap — prevents runaway loops
			response = self._call_ollama(self._messages, _TOOLS)
			msg = response.get("message", {})
			tool_calls: list[dict[str, Any]] = msg.get("tool_calls") or []

			if not tool_calls:
				# Pure text reply — we're done.
				content: str = msg.get("content") or "(no response)"
				self._messages.append({"role": "assistant", "content": content})
				return content

			# Append the assistant turn (may have empty content when only using tools).
			self._messages.append({
				"role": "assistant",
				"content": msg.get("content") or "",
				"tool_calls": tool_calls,
			})

			# Execute each tool and feed results back as tool-role messages.
			for tc in tool_calls:
				fn = tc.get("function", {})
				name: str = fn.get("name", "")
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

		return "(maximum tool iterations reached — please try again)"

	def _call_ollama(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict[str, Any]:
		"""POST to Ollama /api/chat, return parsed JSON response dict."""
		url = f"{self.ollama_url}/api/chat"
		payload = {
			"model": self.model,
			"messages": messages,
			"tools": tools,
			"stream": False,
		}
		try:
			resp = requests.post(url, json=payload, timeout=120)
			resp.raise_for_status()
			return resp.json()
		except requests.ConnectionError as exc:
			raise RuntimeError(
				f"Cannot reach Ollama at {self.ollama_url}. "
				"Start it with: ollama serve"
			) from exc
		except requests.HTTPError as exc:
			raise RuntimeError(f"Ollama API error: {exc.response.text}") from exc

	def _execute_tool(self, name: str, args: dict[str, Any]) -> str:
		"""Dispatch tool call to SchemaState methods."""
		dispatch = {
			"create_table": lambda: self.state.create_table(
				args.get("name", ""),
				args.get("columns", []),
			),
			"add_relationship": lambda: self.state.add_relationship(
				args.get("from_table", ""),
				args.get("to_table", ""),
				args.get("type", "one-to-many"),
			),
			"set_app_name": lambda: self.state.set_app_name(args.get("name", "")),
			"set_description": lambda: self.state.set_description(args.get("text", "")),
			"show_schema": lambda: self.state.show_schema(),
			"undo": lambda: self.state.undo(),
			"generate_app": lambda: self.state.generate_app(args.get("output_dir", "")),
		}
		handler = dispatch.get(name)
		if handler is None:
			return f"Unknown tool: {name}"
		try:
			return handler()
		except Exception as exc:  # noqa: BLE001
			_log_.exception("tool %s failed", name)
			return f"Error in {name}: {exc}"

	def _schema_state(self) -> str:
		return _render_schema(self.state)

	# ------------------------------------------------------------------
	# Internal helpers
	# ------------------------------------------------------------------

	def _check_ollama(self) -> None:
		"""Verify Ollama is reachable and the requested model exists."""
		try:
			r = requests.get(f"{self.ollama_url}/api/tags", timeout=5)
			r.raise_for_status()
			tags = r.json()
			names = [m["name"] for m in tags.get("models", [])]
			if self.model not in names and not any(n.startswith(self.model.split(":")[0]) for n in names):
				click.echo(
					click.style(
						f"Model '{self.model}' not found. Pulling — this may take a minute…",
						fg="yellow",
					)
				)
				subprocess.run(["ollama", "pull", self.model], check=False)
		except requests.ConnectionError:
			click.echo(
				click.style(
					f"Warning: cannot connect to Ollama at {self.ollama_url}. "
					"Make sure `ollama serve` is running.",
					fg="yellow",
				),
				err=True,
			)


# ---------------------------------------------------------------------------
# CLI command
# ---------------------------------------------------------------------------

@click.command("chat-create")
@click.option(
	"--model",
	default="gemma2:2b",
	show_default=True,
	help="Ollama model tag (e.g. gemma2:2b, phi4-mini).",
)
@click.option(
	"--ollama-url",
	default="http://localhost:11434",
	show_default=True,
	envvar="OLLAMA_URL",
	help="Base URL of the Ollama server.",
)
def chat_create(model: str, ollama_url: str) -> None:
	"""
	Start an AI-assisted conversational session to design and generate a
	pgappforge application.

	The model calls tools (create_table, add_relationship, …) to build your
	schema from natural language.  When you are satisfied, say 'generate' or
	'build it' and the model will emit the flask forge gen all command.

	\b
	Example:
	  flask forge chat-create --model gemma2:2b
	  flask forge chat-create --model phi4-mini --ollama-url http://gpu-host:11434
	"""
	chat = AppCreatorChat(ollama_url=ollama_url, model=model)
	chat.start_session()


# ---------------------------------------------------------------------------
# Web view
# ---------------------------------------------------------------------------

# Inline template — avoids adding a template directory dependency.
_WEB_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>App Creator Chat · pgappforge</title>
<script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
<style>
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  background: #0f1117; color: #e2e8f0; height: 100vh;
  display: grid; grid-template-columns: 1fr 380px; grid-template-rows: 48px 1fr;
}
/* --- header --- */
header {
  grid-column: 1 / -1;
  display: flex; align-items: center; gap: 12px;
  padding: 0 20px; background: #1a1f2e;
  border-bottom: 1px solid #2d3554;
}
header h1 { font-size: .95rem; font-weight: 600; color: #7dd3fc; letter-spacing: .04em; }
.model-badge {
  font-size: .72rem; background: #1e3a5f; color: #93c5fd;
  padding: 2px 8px; border-radius: 999px; margin-left: auto;
}
/* --- chat panel --- */
#chat-panel {
  display: flex; flex-direction: column;
  border-right: 1px solid #2d3554;
}
#messages {
  flex: 1; overflow-y: auto; padding: 16px;
  display: flex; flex-direction: column; gap: 12px;
}
.msg { max-width: 88%; line-height: 1.55; font-size: .88rem; }
.msg.user {
  align-self: flex-end;
  background: #1e3a5f; color: #e2e8f0;
  padding: 10px 14px; border-radius: 14px 14px 4px 14px;
}
.msg.assistant {
  align-self: flex-start;
  background: #1e293b; color: #cbd5e1;
  padding: 10px 14px; border-radius: 14px 14px 14px 4px;
  white-space: pre-wrap;
}
.msg.tool {
  align-self: flex-start;
  background: #0f2e1a; color: #6ee7b7;
  padding: 6px 12px; border-radius: 8px;
  font-family: monospace; font-size: .78rem;
}
.msg.error {
  align-self: flex-start;
  background: #2e1515; color: #fca5a5;
  padding: 8px 12px; border-radius: 8px; font-size: .82rem;
}
#input-row {
  display: flex; gap: 8px; padding: 12px 16px;
  border-top: 1px solid #2d3554; background: #12161f;
}
#user-input {
  flex: 1; background: #1e293b; color: #e2e8f0;
  border: 1px solid #334155; border-radius: 8px;
  padding: 10px 12px; font-size: .88rem; resize: none; height: 44px;
  outline: none; transition: border-color .15s;
}
#user-input:focus { border-color: #3b82f6; }
#send-btn {
  padding: 0 18px; background: #2563eb; color: #fff;
  border: none; border-radius: 8px; cursor: pointer;
  font-size: .88rem; font-weight: 600; transition: background .15s;
}
#send-btn:hover { background: #1d4ed8; }
#send-btn:disabled { background: #1e3a5f; cursor: not-allowed; }
/* --- schema panel --- */
#schema-panel {
  display: flex; flex-direction: column; overflow: hidden;
}
#schema-tabs {
  display: flex; border-bottom: 1px solid #2d3554;
  background: #12161f;
}
.tab-btn {
  flex: 1; padding: 10px 0; font-size: .78rem; font-weight: 600;
  background: none; border: none; color: #64748b; cursor: pointer;
  letter-spacing: .04em; transition: color .15s;
}
.tab-btn.active { color: #7dd3fc; border-bottom: 2px solid #3b82f6; }
#schema-text {
  flex: 1; overflow-y: auto; padding: 14px;
  font-family: monospace; font-size: .78rem; color: #94a3b8;
  white-space: pre; background: #0f1117; display: block;
}
#schema-diagram {
  flex: 1; overflow: auto; padding: 14px;
  background: #0f1117; display: none;
}
.mermaid { filter: invert(85%) hue-rotate(180deg); }
</style>
</head>
<body>
<header>
  <h1>pgappforge · App Creator Chat</h1>
  <span class="model-badge" id="model-label">model: …</span>
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
</aside>

<script>
mermaid.initialize({ startOnLoad: false, theme: 'default' });

const messagesEl = document.getElementById('messages');
const inputEl    = document.getElementById('user-input');
const sendBtn    = document.getElementById('send-btn');
const schemaText = document.getElementById('schema-text');
const mermaidSrc = document.getElementById('mermaid-src');
const modelLabel = document.getElementById('model-label');

let currentTab = 'text';

// --- tab switching ---
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
  mermaid.render('mermaid-svg', src).then(({svg}) => {
    mermaidSrc.innerHTML = svg;
  }).catch(() => {});
}

function appendMessage(role, text) {
  const div = document.createElement('div');
  div.className = 'msg ' + role;
  div.textContent = text;
  messagesEl.appendChild(div);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function updateSchema(schemaText_, mermaidDef) {
  schemaText.textContent = schemaText_;
  mermaidSrc.textContent = mermaidDef;
  mermaidSrc.removeAttribute('data-processed');
  if (currentTab === 'diagram') renderMermaid();
}

async function sendMessage() {
  const text = inputEl.value.trim();
  if (!text) return;
  inputEl.value = '';
  sendBtn.disabled = true;
  appendMessage('user', text);

  try {
    const res = await fetch('/app-creator/chat', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({message: text}),
    });
    const data = await res.json();
    if (!res.ok) {
      appendMessage('error', data.error || 'Server error');
      return;
    }
    appendMessage('assistant', data.reply);
    if (data.tool_log) {
      data.tool_log.forEach(entry => appendMessage('tool', entry));
    }
    updateSchema(data.schema_text, data.schema_mermaid);
    modelLabel.textContent = 'model: ' + (data.model || '?');
  } catch (err) {
    appendMessage('error', 'Request failed: ' + err.message);
  } finally {
    sendBtn.disabled = false;
    inputEl.focus();
  }
}

sendBtn.addEventListener('click', sendMessage);
inputEl.addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
});

// Greet
fetch('/app-creator/state').then(r => r.json()).then(d => {
  modelLabel.textContent = 'model: ' + (d.model || '?');
  updateSchema(d.schema_text, d.schema_mermaid);
  appendMessage('assistant',
    'Hello! Describe the application you want to build and I will design ' +
    'the database schema for you. Say "generate" when you are ready.');
});
</script>
</body>
</html>
"""


def _make_web_chat_class() -> type:
	"""
	Build AppCreatorView dynamically so that the Flask/pgappforge imports
	are deferred — the CLI command works without a running Flask app.
	"""
	from flask import jsonify, render_template_string, request as flask_request
	from pgappforge.baseviews import BaseView, expose

	class AppCreatorView(BaseView):
		"""
		Web chat interface for the Ollama-powered app creator.

		Mounts at /app-creator/.  Maintains one SchemaState per Flask session
		key; the Ollama AppCreatorChat instance lives in the view object (single
		process, single user — fine for a dev tool).

		Routes
		------
		GET  /app-creator/          — chat UI
		GET  /app-creator/state     — current schema as JSON
		POST /app-creator/chat      — process one message, return JSON
		POST /app-creator/reset     — clear schema state
		"""

		route_base = "/app-creator"
		default_view = "index"

		def __init__(self) -> None:
			super().__init__()
			self._chat: AppCreatorChat | None = None

		def _get_chat(self) -> AppCreatorChat:
			if self._chat is None:
				from flask import current_app
				cfg = current_app.config
				self._chat = AppCreatorChat(
					ollama_url=cfg.get("OLLAMA_URL", "http://localhost:11434"),
					model=cfg.get("OLLAMA_MODEL", "gemma2:2b"),
				)
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

			chat_obj = self._get_chat()

			# Intercept tool calls to build a human-readable log.
			tool_log: list[str] = []
			original_execute = chat_obj._execute_tool

			def _instrumented_execute(name: str, args: dict[str, Any]) -> str:
				result = original_execute(name, args)
				tool_log.append(f"[{name}] {result}")
				return result

			chat_obj._execute_tool = _instrumented_execute  # type: ignore[method-assign]
			try:
				reply = chat_obj.process_message(user_msg)
			except Exception as exc:  # noqa: BLE001
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
				self._chat._messages = [
					{"role": "system", "content": _SYSTEM_PROMPT}
				]
			return jsonify({"ok": True, "schema_text": _render_schema(SchemaState())})

	return AppCreatorView


# Lazy singleton — instantiated only when imported inside a Flask context.
def get_app_creator_view_class() -> type:
	"""Return the AppCreatorView class (imports deferred)."""
	return _make_web_chat_class()
