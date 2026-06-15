# Ollama-Powered Agentic Development Assistant in Flask-AppBuilder

**Research Date:** 2026-06-15
**Scope:** Embedding an Ollama-backed coding agent inside a FAB web application for developer + admin users
**Depth:** Deep Research

---

## Research Summary

Ollama exposes a clean REST API (`/api/chat`, `/api/generate`, `/api/tags`, `/api/ps`) that fully supports tool/function calling via OpenAI-compatible JSON Schema definitions. The best local coding models as of mid-2026 are **qwen2.5-coder** (all sizes) and **qwen3-coder** for agentic loops, with **mistral-small** (not Nemo) for tool-heavy agents on constrained hardware. A FAB-embedded assistant maps cleanly to a custom `BaseView` blueprint that serves a chat UI, streams tokens via SSE (`text/event-stream`), and drives a ReAct agent loop in a background thread. The most critical non-obvious constraint is sandboxing: path traversal via symlinks bypasses prefix checks, and subprocesses inherit the parent's OS-level access regardless of application-layer restrictions.

---

## Table of Contents

1. [Ollama API Capabilities](#1-ollama-api-capabilities)
2. [Coding-Capable Models](#2-coding-capable-models)
3. [Agentic Patterns](#3-agentic-patterns)
4. [Codebase Context Injection](#4-codebase-context-injection)
5. [Security Considerations](#5-security-considerations)
6. [Existing Implementations to Reference](#6-existing-implementations-to-reference)
7. [Recommended Architecture for FAB](#7-recommended-architecture-for-fab)
8. [Concrete Tool List](#8-concrete-tool-list)
9. [Recommended Models and Pull Commands](#9-recommended-models-and-pull-commands)
10. [Research Gaps and Open Questions](#10-research-gaps-and-open-questions)
11. [Sources](#11-sources)

---

## 1. Ollama API Capabilities

### Base URL and Transport

Ollama runs a local HTTP server on `http://localhost:11434` by default. Configurable via `OLLAMA_HOST`. All requests are `POST` with a JSON body unless noted. Responses are either a single JSON object (`stream: false`) or newline-delimited JSON / NDJSON (`stream: true`, the default).

### Full Endpoint Reference

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/generate` | POST | Single-turn completion |
| `/api/chat` | POST | Multi-turn chat with tool calling |
| `/api/tags` | GET | List locally downloaded models |
| `/api/ps` | GET | List currently running (in-memory) models |
| `/api/show` | POST | Model metadata (capabilities, template, parameters) |
| `/api/pull` | POST | Download a model from registry |
| `/api/delete` | DELETE | Remove a model |
| `/api/embed` | POST | Generate embeddings |
| `/api/create` | POST | Create a model from Modelfile |
| `/api/version` | GET | Ollama server version |

### `/api/chat` — Primary Endpoint for Agents

```
POST http://localhost:11434/api/chat
```

**Request parameters:**

| Parameter | Type | Notes |
|---|---|---|
| `model` | string (required) | `model:tag` format |
| `messages` | array | `system`, `user`, `assistant`, `tool` roles |
| `tools` | array | JSON Schema tool definitions |
| `stream` | bool | Default `true` |
| `format` | string or JSON schema | `"json"` or structured output schema |
| `options` | object | temperature, seed, num_ctx, etc. |
| `keep_alive` | string | How long to hold model in VRAM (default `5m`) |
| `think` | bool | Enable thinking/reasoning output (thinking models) |

**Message roles:**

```json
{"role": "system",    "content": "You are a coding assistant..."}
{"role": "user",      "content": "Refactor this function"}
{"role": "assistant", "content": "", "tool_calls": [...]}
{"role": "tool",      "content": "result string", "tool_name": "read_file"}
```

**Load model without a query** (warm-up): send empty `messages` array.
**Unload model** (free VRAM): send empty `messages` + `"keep_alive": 0`.

### `/api/generate` — Single-Turn Completion

Useful for one-shot code generation tasks without a conversation history. Supports the `suffix` parameter for fill-in-the-middle (FIM) completion — important for inline code completion use cases.

```json
{
  "model": "qwen2.5-coder:7b",
  "prompt": "def binary_search(arr, target):",
  "suffix": "\n    return -1",
  "stream": true
}
```

### NDJSON Streaming Format

When `stream: true` (default), each token is one JSON line:

```
{"model":"qwen2.5-coder:7b","created_at":"2026-06-15T10:00:00Z","message":{"role":"assistant","content":"Here"},"done":false}
{"model":"qwen2.5-coder:7b","created_at":"2026-06-15T10:00:01Z","message":{"role":"assistant","content":" is"},"done":false}
{"model":"qwen2.5-coder:7b","created_at":"...","message":{"role":"assistant","content":""},"done":true,"done_reason":"stop","eval_count":42,"eval_duration":1200000000}
```

Key fields on the final (`done: true`) object:
- `eval_count` — tokens generated
- `eval_duration` — nanoseconds; tokens/sec = `eval_count / eval_duration * 1e9`
- `prompt_eval_count` — tokens consumed from the prompt
- `done_reason` — `"stop"` | `"length"` | `"tool_calls"`

**Python streaming pattern:**

```python
import requests, json

def stream_chat(model: str, messages: list, tools: list = None) -> None:
    payload = {"model": model, "messages": messages, "stream": True}
    if tools:
        payload["tools"] = tools
    resp = requests.post("http://localhost:11434/api/chat", json=payload, stream=True)
    for line in resp.iter_lines():
        if line:
            chunk = json.loads(line)
            content = chunk.get("message", {}).get("content", "")
            if content:
                print(content, end="", flush=True)
            if chunk.get("done"):
                break
```

### `/api/tags` — Available Models

```bash
GET http://localhost:11434/api/tags
```

Response schema:
```json
{
  "models": [{
    "name": "qwen2.5-coder:7b",
    "model": "qwen2.5-coder:7b",
    "modified_at": "2026-06-10T12:00:00Z",
    "size": 4685934592,
    "details": {
      "format": "gguf",
      "family": "qwen2",
      "parameter_size": "7.6B",
      "quantization_level": "Q4_K_M"
    }
  }]
}
```

Use this to populate a model-selector dropdown in the FAB UI.

### `/api/ps` — Running Models

```bash
GET http://localhost:11434/api/ps
```

Returns models currently loaded in VRAM. Extra fields: `expires_at` (when Ollama will unload it), `size_vram` (bytes consumed on GPU). Useful for a status indicator in the assistant UI.

### Tool Calling API Format

Ollama implements the OpenAI-compatible tool calling format. Flow:

1. Client sends `messages` + `tools` (JSON Schema definitions)
2. Model responds with either text OR `tool_calls` in the message
3. Client executes the tool
4. Client appends `{"role": "tool", "content": "<result>", "tool_name": "<name>"}` to messages
5. Client re-calls `/api/chat` with full updated history
6. Model generates final answer

**Tool definition schema:**
```json
{
  "type": "function",
  "function": {
    "name": "read_file",
    "description": "Read the contents of a file at a given path within the project workspace",
    "parameters": {
      "type": "object",
      "properties": {
        "path": {
          "type": "string",
          "description": "Relative path from project root, e.g. pgappforge/base.py"
        }
      },
      "required": ["path"]
    }
  }
}
```

**Tool call response from model:**
```json
{
  "role": "assistant",
  "content": "",
  "tool_calls": [
    {
      "function": {
        "name": "read_file",
        "arguments": {"path": "pgappforge/base.py"}
      }
    }
  ]
}
```

**Important caveats:**
- Tool calling works best with models post-trained on tool-use data: Llama 3.1+, Qwen 2.5+, Qwen 3, Mistral Small (not Nemo), Phi-4-mini.
- Current Ollama tool parameter schemas are a **limited subset of JSON Schema** — complex nested schemas may not parse correctly.
- Small models (~8B) degrade significantly with complex multi-tool prompts.
- Streaming with tool calls: accumulate the full `tool_calls` field before executing, then include results in the follow-up request.

### System Prompt Injection

Inject codebase context via the `system` role message. This is processed once and cached, making it cheap relative to repeating it in every user message:

```python
messages = [
    {"role": "system", "content": CODEBASE_SYSTEM_PROMPT},
    {"role": "user",   "content": "How does the permission system work?"}
]
```

The `/api/generate` endpoint also accepts a `system` parameter directly.

---

## 2. Coding-Capable Models

### Benchmark Rankings (mid-2026)

| Model | HumanEval | Context | VRAM (Q4_K_M) | Tool Calling | Notes |
|---|---|---|---|---|---|
| qwen2.5-coder:32b | 92.7% | 128K | ~24 GB | Yes | Near GPT-4o on Aider benchmark |
| qwen3-coder:30b | ~90%+ | 128K | ~22 GB | Yes | RL-trained for multi-step agentic workflows |
| qwen2.5-coder:14b | ~89% | 128K | ~16 GB | Yes | Sweet spot for 16 GB VRAM |
| qwen2.5-coder:7b | 88.4% | 128K | ~8 GB | Yes | 40+ tokens/sec on RTX 4090 |
| deepseek-coder-v2:16b | 81.1% | 128K | ~16 GB | Partial | MoE: 2.4B active params, fast inference |
| mistral-small:24b | ~82% | 32K | ~18 GB | Yes (native) | Strong function calling, JSON output |
| codellama:34b | ~49% | 100K | ~40 GB | No | Superseded; avoid for new work |
| codellama:7b | ~37% | 16K | ~5-6 GB | No | Only for extremely VRAM-constrained |
| mistral-nemo:12b | N/A | 128K | ~9 GB | **No** | No native tool calling in Ollama |

**Key finding:** `qwen2.5-coder:7b` at 88.4% HumanEval outperforms `codellama:70b` at 67.8% while fitting on an 8 GB GPU. CodeLlama is a generation behind on all metrics. Mistral-Nemo lacks native tool calling capability in Ollama — it responds with plain text instead of `tool_calls`.

### Models with Native Tool Calling in Ollama

Confirmed working:
- `qwen2.5-coder` (all sizes)
- `qwen3` / `qwen3-coder`
- `llama3.1` / `llama3.2` / `llama3.3`
- `mistral-small` (24B)
- `phi4-mini`
- `gemma4` (26B, native function calling)
- `deepseek-r1` (reasoning + tool use)

NOT working natively for tool calls:
- `mistral-nemo` — check `ollama show <model>` for "tools" in capabilities
- `codellama` (any variant)

To check if a pulled model supports tools:
```bash
ollama show qwen2.5-coder:7b | grep -i tools
```

### Quantization Tradeoffs: Q4_K_M vs Q8_0

| Quantization | Bits | Perplexity delta vs F16 | 7B size | 7B VRAM | Best for |
|---|---|---|---|---|---|
| Q4_K_M | 4-bit (K-means grouped) | +~0.5% | ~4.4 GB | 8 GB+ | Default; imperceptible quality loss for chat |
| Q5_K_M | 5-bit | +~0.2% | ~5.5 GB | 10 GB+ | Better for reasoning/coding if VRAM allows |
| Q8_0 | 8-bit (linear) | +~0.001% | ~7.0 GB | 12 GB+ | Near-lossless; preferred for coding/math |
| F16 | 16-bit | baseline | ~14 GB | 24 GB+ | Only if memory is unconstrained |

**For coding agents specifically:** Q8_0 is the preferred quantization when VRAM allows. The jump from Q4 to Q8 is "particularly noticeable for coding tasks and complex reasoning." Q4_K_M's K-means grouping (targeting sensitive weight clusters) gives meaningfully better results than plain Q4 and is the right fallback on 8 GB GPUs.

**Rule of thumb:**
- 8 GB VRAM → `qwen2.5-coder:7b` (Q4_K_M, ~4.4 GB + context headroom)
- 16 GB VRAM → `qwen2.5-coder:14b` (Q4_K_M) or 7b (Q8_0)
- 24 GB VRAM → `qwen2.5-coder:32b` (Q4_K_M)

### VRAM Requirements by Model Size

| Parameter Count | Q4_K_M VRAM | Q8_0 VRAM | F16 VRAM |
|---|---|---|---|
| 7B | ~5-8 GB | ~7-9 GB | ~14 GB |
| 14B | ~10-12 GB | ~16 GB | ~28 GB |
| 32B | ~20-24 GB | ~38 GB | ~64 GB |
| 34B (CodeLlama) | ~22-26 GB | ~40 GB | ~68 GB |

KV cache adds 1-2 GB per 16K context tokens. Factor this in when calculating headroom.

---

## 3. Agentic Patterns

### ReAct (Reason + Act) Loop

ReAct is the standard loop architecture for code agents. The model alternates between:
1. **Thought** — analyzes current state, plans next action
2. **Action** — emits a tool call (read_file, run_tests, etc.)
3. **Observation** — receives tool result, updates context

The loop terminates when:
- The model emits a final text answer (no tool calls)
- A maximum iteration count is reached
- The model explicitly signals task completion

**Minimal Python implementation:**

```python
import json
import requests

MAX_ITERATIONS = 10

def react_agent(model: str, system_prompt: str, user_query: str, tools: list, tool_registry: dict) -> str:
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user",   "content": user_query},
    ]

    for iteration in range(MAX_ITERATIONS):
        resp = requests.post(
            "http://localhost:11434/api/chat",
            json={"model": model, "messages": messages, "tools": tools, "stream": False},
        ).json()

        assistant_msg = resp["message"]
        messages.append(assistant_msg)

        tool_calls = assistant_msg.get("tool_calls", [])
        if not tool_calls:
            # No tool calls — model is done reasoning
            return assistant_msg.get("content", "")

        # Execute each tool and append results
        for call in tool_calls:
            fn_name = call["function"]["name"]
            fn_args = call["function"]["arguments"]
            if isinstance(fn_args, str):
                fn_args = json.loads(fn_args)

            if fn_name not in tool_registry:
                result = f"Error: unknown tool '{fn_name}'"
            else:
                try:
                    result = tool_registry[fn_name](**fn_args)
                except Exception as e:
                    result = f"Tool error: {e}"

            messages.append({
                "role": "tool",
                "content": str(result),
                "tool_name": fn_name,
            })

    return "Max iterations reached without a final answer."
```

**Anti-loop guard:** If the same tool with the same arguments is called twice consecutively, inject a message: `"You already tried that. Try a different approach or summarize what you know."` — models that lack this instruction will loop indefinitely on the same failed search.

### Tool Definition Schema for the Agent

Full schema example for a coding-agent tool set:

```python
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the contents of a source file in the project. Returns the full text.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative path from project root, e.g. pgappforge/base.py"}
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write or overwrite a file in the project workspace. Use with caution.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative path from project root"},
                    "content": {"type": "string", "description": "Full file content to write"}
                },
                "required": ["path", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_code",
            "description": "Search for a pattern in the codebase using ripgrep. Returns matching lines with file and line number.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Regex pattern to search for"},
                    "glob": {"type": "string", "description": "Optional glob filter, e.g. '*.py'"}
                },
                "required": ["pattern"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "run_tests",
            "description": "Run the test suite or a specific test file and return stdout/stderr.",
            "parameters": {
                "type": "object",
                "properties": {
                    "test_path": {"type": "string", "description": "Optional: specific test file or test name. Omit to run all CI tests."}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Execute a whitelisted shell command in the project root. Only specific commands are allowed.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "The shell command to run"},
                    "timeout": {"type": "integer", "description": "Timeout in seconds (max 60)"}
                },
                "required": ["command"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_directory",
            "description": "List files and directories at a given path within the project.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative path to list. Defaults to project root."}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_git_diff",
            "description": "Get the current git diff or diff for a specific file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Optional: specific file path to diff"}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_git_log",
            "description": "Get the git commit log (last N commits).",
            "parameters": {
                "type": "object",
                "properties": {
                    "n": {"type": "integer", "description": "Number of commits to return (default 10)"},
                    "path": {"type": "string", "description": "Optional: filter to commits touching this file"}
                },
                "required": []
            }
        }
    }
]
```

### Streaming Responses: SSE vs WebSocket

**Recommendation: SSE (Server-Sent Events)**

For a developer assistant in a Flask/FAB app, SSE is strongly preferred over WebSocket:

| Criterion | SSE | WebSocket |
|---|---|---|
| Direction | Server → Client (unidirectional) | Bidirectional |
| Flask support | Native via `Response(generator, mimetype='text/event-stream')` | Requires Flask-SocketIO + eventlet/gevent |
| Auto-reconnect | Built into browser `EventSource` | Manual |
| Proxy/reverse proxy | Works through nginx/Traefik without special config | Requires upgrade headers |
| Auth | Standard HTTP headers | Requires custom handshake |
| Complexity | Low | High |

The assistant only needs server→client streaming (tokens flowing from Ollama to the browser). The client sends a single HTTP POST to start a new agent turn — that's not streaming, just a regular request. SSE handles this split cleanly.

**Flask SSE implementation:**

```python
from flask import Response, stream_with_context, request
from pgappforge.baseviews import BaseView
from pgappforge import AppBuilder
import json, requests as http

class DevAssistantView(BaseView):
    route_base = "/dev-assistant"

    @expose("/stream", methods=["POST"])
    @has_access
    def stream(self):
        data = request.get_json()
        model = data.get("model", "qwen2.5-coder:7b")
        messages = data.get("messages", [])

        @stream_with_context
        def generate():
            resp = http.post(
                "http://localhost:11434/api/chat",
                json={"model": model, "messages": messages, "stream": True},
                stream=True,
            )
            for line in resp.iter_lines():
                if line:
                    chunk = json.loads(line)
                    content = chunk.get("message", {}).get("content", "")
                    if content:
                        payload = json.dumps({"content": content})
                        yield f"data: {payload}\n\n"
                    if chunk.get("done"):
                        yield f"data: {json.dumps({'done': True})}\n\n"
                        break

        return Response(generate(), mimetype="text/event-stream",
                        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
```

The `X-Accel-Buffering: no` header is critical — without it, nginx will buffer the entire response before sending, defeating streaming.

**Browser-side EventSource:**

```javascript
const form = document.getElementById('chat-form');
form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const body = JSON.stringify({ model: selectedModel, messages: conversationHistory });
    const resp = await fetch('/dev-assistant/chat', { method: 'POST', body, headers: {'Content-Type': 'application/json'} });
    const reader = resp.body.getReader();
    // or use EventSource for reconnect support
});
```

For agentic (multi-turn with tool calls) streaming, the pattern is slightly different: the backend runs the full ReAct loop and streams each intermediate "thought + action + observation" chunk as a named SSE event:

```python
yield f"event: thought\ndata: {json.dumps({'text': thought_text})}\n\n"
yield f"event: tool_call\ndata: {json.dumps({'name': fn_name, 'args': fn_args})}\n\n"
yield f"event: tool_result\ndata: {json.dumps({'result': result[:500]})}\n\n"
yield f"event: final\ndata: {json.dumps({'text': final_answer})}\n\n"
```

---

## 4. Codebase Context Injection

### RAG vs Full Context Injection

**Decision framework:**

| Scenario | Strategy |
|---|---|
| Codebase < 100K tokens (~400K chars) | Full context injection |
| Codebase 100K-500K tokens | Selective injection (key files) + search tool |
| Codebase > 500K tokens | Agentic RAG or hybrid |
| Real-time precision required | Full context injection |
| Large, rarely-changing codebase | RAG with embeddings |

For a FAB application (this repo is a medium-sized Python project), the practical approach is:

1. **Static system prompt layer** — inject the overall architecture description (10-20K tokens max)
2. **Dynamic context layer** — use `read_file` and `search_code` tools so the agent fetches exactly what it needs on demand
3. **No full-codebase injection** — even with 128K context windows, dumping all files degrades reasoning quality (Chroma Research documented measurable degradation as input length grew in 18 frontier models)

### Building the FAB System Prompt

The system prompt should describe the app structure concisely. A good template:

```python
FAB_SYSTEM_PROMPT = """
You are a senior developer assistant embedded in PgAppForge (a Flask-AppBuilder fork).
You have access to tools to read files, search code, run tests, and execute whitelisted commands.

## Project Structure
- pgappforge/ — main package
  - base.py — AppBuilder orchestrator (views, security, menus)
  - baseviews.py, views.py — ModelView, BaseView, RestCRUDView
  - api/ — ModelRestApi, OpenAPI integration
  - security/ — RBAC, OAuth, LDAP (sqla/ and mongoengine/)
  - models/ — SQLAlchemy 2.x patterns, filters, mixins
  - plugins/ — rules engine, workflow engine
- tests/ci/ — CI test suite (run with: uv run pytest -vxs tests/ci)
- docs/ — architecture docs, research

## Key Constraints
- Python with tabs (not spaces)
- PostgreSQL only — no other DB workarounds
- Pydantic v2 with ConfigDict(extra='forbid')
- Async throughout where appropriate
- UUID7 via uuid6 package

## Database
- SQLAlchemy 2.x: use session.execute(select()) patterns
- Flask-SQLAlchemy 3.1.1+

## Your Workflow
1. Use read_file and search_code to understand code before making changes
2. Write tests before implementing features (TDD)
3. Use run_tests to verify changes
4. Explain what you changed and why

Use tools proactively. Do not guess file contents — read them first.
"""
```

### Token Budget Strategies

```
Context window: 128K tokens
System prompt: ~2-4K tokens
Tool schemas: ~1-2K tokens  
Conversation history: ~10-20K tokens (trim old turns)
File reads (on demand): ~5-50K tokens per read
KV cache overhead: ~1-2K per 16K context
Remaining for generation: 50K+
```

**History trimming strategy:** Keep only the last N full conversation turns. When context approaches 80% of the model's `num_ctx`, summarize older turns into a compressed block and drop the raw messages.

**Practical num_ctx setting for Ollama:**

```python
options = {
    "num_ctx": 32768,   # 32K — good default for most coding tasks
    "temperature": 0.1,  # Low for deterministic code generation
    "top_p": 0.9,
}
```

Setting `num_ctx` beyond the model's training context degrades quality. 32K is the practical sweet spot for most coding assistant sessions.

---

## 5. Security Considerations

### Path Traversal Prevention

The most critical security issue. Simple prefix checks are **insufficient** due to symlink traversal:

```python
# VULNERABLE: bypassable via symlinks
if not path.startswith("/workspace"):
    raise PermissionError("Access denied")

# CORRECT: resolve symlinks before checking
import os
from pathlib import Path

PROJECT_ROOT = Path("/Users/nyimbiodero/src/pjs/fab-ext").resolve()

def safe_path(relative: str) -> Path:
    """Resolve path, reject traversal attempts."""
    # Normalize the input
    if relative.startswith("/"):
        raise ValueError("Absolute paths not allowed")
    resolved = (PROJECT_ROOT / relative).resolve()
    # Check it's still inside the project root after symlink resolution
    try:
        resolved.relative_to(PROJECT_ROOT)
    except ValueError:
        raise PermissionError(f"Path traversal detected: {relative!r}")
    return resolved
```

**Never use** `path.startswith(str(root))` — always use `resolved.relative_to(root)` which calls `os.path.realpath` internally.

### Subprocess Sandboxing

Subprocesses inherit OS-level access regardless of parent application-layer restrictions. This means any `subprocess.run()` call that doesn't explicitly restrict permissions can be a full escape vector.

**Minimum subprocess hardening:**

```python
import subprocess
import os

ALLOWED_COMMANDS = frozenset([
    "uv run pytest",
    "uv run pyright",
    "git diff",
    "git log",
    "git status",
    "rg",           # ripgrep for search_code tool
    "find",
    "cat",
    "head",
    "tail",
])

BLOCKED_PATTERNS = [
    "rm ", "rm\t", "rmdir",
    "sudo",
    "curl", "wget",
    "pip install", "pip uninstall",
    "> /", ">>",         # redirect to root paths
    "chmod", "chown",
    "/etc/", "/root/", "/proc/", "/sys/",
    "ssh", "scp",
    "|",                 # pipe chaining — evaluate case by case
    ";",                 # command chaining
    "&&", "||",          # conditional chaining
]

def is_command_allowed(cmd: str) -> bool:
    cmd_lower = cmd.strip().lower()
    # Check blocked patterns first
    for pattern in BLOCKED_PATTERNS:
        if pattern in cmd_lower:
            return False
    # Check allowlist prefix
    for allowed in ALLOWED_COMMANDS:
        if cmd_lower.startswith(allowed):
            return True
    return False

def run_command(command: str, timeout: int = 30) -> str:
    timeout = min(timeout, 60)  # Hard cap
    if not is_command_allowed(command):
        return f"Command not permitted: {command!r}"

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(PROJECT_ROOT),  # Always run from project root
            env={**os.environ, "HOME": "/tmp/agent-home"},  # Restrict HOME
        )
        output = result.stdout + result.stderr
        return output[:10000]  # Truncate large outputs
    except subprocess.TimeoutExpired:
        return f"Command timed out after {timeout}s"
    except Exception as e:
        return f"Command failed: {e}"
```

**Do not use `cd` in commands** — directory changes don't persist across calls and create path confusion. Always set `cwd` explicitly in `subprocess.run`.

### Docker-Based Sandboxing (Recommended for Production)

For maximum security, run agent command execution in an ephemeral Docker container:

```python
import subprocess, tempfile, os

def run_in_docker(command: str, timeout: int = 30) -> str:
    """Execute command in ephemeral Docker container with project mounted read-only."""
    docker_cmd = [
        "docker", "run", "--rm",
        "--network=none",           # No network access
        "--memory=512m",            # Memory limit
        "--cpus=0.5",               # CPU limit
        "--read-only",              # Read-only root filesystem
        f"--volume={PROJECT_ROOT}:/workspace:ro",  # Project as read-only
        "--workdir=/workspace",
        "python:3.12-slim",
        "sh", "-c", command
    ]
    result = subprocess.run(docker_cmd, capture_output=True, text=True, timeout=timeout + 5)
    return (result.stdout + result.stderr)[:10000]
```

The `--read-only` flag prevents any writes to the container filesystem. If the agent needs to write files (test artifacts, generated code), use a separate writable tmpfs mount:

```
--tmpfs /tmp:exec,size=100m
```

### Dangerous Operations Checklist

Operations to explicitly block or require confirmation before executing:

| Operation | Risk | Mitigation |
|---|---|---|
| `rm -rf` / `rmdir` | Data loss | Block entirely |
| `git push` | Unauthorized code push | Block; require explicit user confirmation |
| `git reset --hard` | Lose uncommitted work | Require confirmation |
| Network requests (curl/wget) | Data exfiltration, SSRF | Block in default mode |
| `pip install` / `uv add` | Dependency injection | Restrict to allowlist |
| Writing to `~/.gitconfig`, `~/.bashrc` | Persistence mechanism | Resolve and block paths outside project root |
| File writes outside PROJECT_ROOT | Arbitrary file write | Enforce via `safe_path()` |
| Subprocesses that spawn subprocesses | Sandbox escape | Block `nohup`, `&` backgrounding |

### FAB-Specific Access Control

Bind tool permissions to FAB RBAC roles:

```python
READ_ONLY_TOOLS = {"read_file", "search_code", "list_directory", "get_git_diff", "get_git_log"}
WRITE_TOOLS = {"write_file", "run_command", "run_tests"}

def get_allowed_tools(current_user) -> list:
    if current_user.has_role("Admin") or current_user.has_role("Developer"):
        return TOOLS  # All tools
    elif current_user.has_role("Viewer"):
        return [t for t in TOOLS if t["function"]["name"] in READ_ONLY_TOOLS]
    return []
```

---

## 6. Existing Implementations to Reference

### Open-WebUI

**Repo:** https://github.com/open-webui/open-webui

The canonical Ollama UI. Key architectural lessons:

- **Reverse proxy pattern:** All Ollama API calls are proxied through the backend (`/ollama` route → `OLLAMA_BASE_URL/...`). The frontend never calls Ollama directly. This prevents CORS issues and enforces authentication.
- **Stack:** SvelteKit frontend + FastAPI/Python backend + ChromaDB for RAG + SQLite/PostgreSQL for persistence.
- **RBAC:** Role-based access restricts model pulling/creation to admins.
- **Pipelines:** Plugin system for extending model behavior without forking core code.
- **RAG:** Chunks documents, embeds via `nomic-embed-text` (default), stores in ChromaDB, retrieves at query time.
- **Model unloading:** Calls `POST /api/generate` with `keep_alive=0` to free VRAM.

For a FAB integration, adopt the reverse-proxy pattern: the FAB view calls Ollama, never the browser directly.

### Continue.dev

**Repo:** https://github.com/continuedev/continue | **Docs:** https://docs.continue.dev

Open-source VS Code/JetBrains coding assistant. Key architectural lessons:

- **Context providers:** `@codebase`, `@file`, `@docs`, `@git`, `@terminal` — each provider injects a different slice of context. Codebase provider uses embeddings + keyword search for semantic retrieval.
- **Embeddings-based indexing:** Indexes the full workspace at startup, enabling semantic search without sending entire codebase in each prompt.
- **Repository map:** `@Folder` generates an Aider-style repo map (file tree + function signatures) that fits efficiently in context.
- **Agent mode:** Multi-file autonomous refactoring. Uses a plan-then-execute loop.
- **MCP (Model Context Protocol):** Connects to external services (GitHub, Sentry, Linear) as tool providers.
- **`.continue/rules/`:** Team-shared AI behavior configuration committed to the repo.

Adopt the repository map approach for the FAB assistant — generate a compact structural summary (file tree + class/function names) as part of the system prompt. This gives the model spatial awareness without consuming the full file budget.

### Aider

**Repo:** https://github.com/paul-gauthier/aider

Command-line AI pair programmer. Key architectural lessons:

- **Repo map:** Generates a compressed representation of the codebase using tree-sitter to extract function/class signatures. Fits the structure of large codebases into ~4K tokens.
- **Diff-based edits:** Model outputs `SEARCH/REPLACE` blocks rather than full file rewrites, reducing error surface and token cost.
- **Git integration:** Automatically commits successful changes with descriptive messages.
- **Architecture scores:** Qwen2.5-coder 32B "within a few points of GPT-4o" on Aider's benchmark.

Adopt the diff/patch approach for the `write_file` tool — instead of full rewrites, have the model produce unified diff format and apply it with Python's `difflib` or `patch` command. This is safer and easier to review.

---

## 7. Recommended Architecture for FAB

### Overview

```
Browser (Developer/Admin)
    │
    │  HTTP POST (new message) → /dev-assistant/chat
    │  SSE stream ←           /dev-assistant/stream/<session_id>
    │
    ▼
FAB Dev Assistant View (BaseView blueprint)
    ├── Auth: @has_access — only Developer/Admin roles
    ├── Session store: Redis or DB-backed conversation history
    ├── Tool registry: bound to PROJECT_ROOT, role-restricted
    │
    ▼
ReAct Agent Loop (background thread or async task)
    ├── Builds messages[] with system prompt + conversation history
    ├── Calls POST http://localhost:11434/api/chat
    ├── Parses tool_calls from response
    ├── Executes safe tools (read_file, search_code, run_tests, etc.)
    ├── Streams each phase (thought/tool/result/final) as SSE events
    └── Appends tool results to messages, loops until done
    │
    ▼
Ollama Server (localhost:11434)
    └── qwen2.5-coder:7b or :14b or :32b (based on available VRAM)
```

### FAB View Registration

```python
# pgappforge/ai_assistant/views.py

from pgappforge.baseviews import BaseView
from pgappforge.security.decorators import has_access
from flask import expose, Response, request, render_template, stream_with_context, g
from .agent import run_agent_streaming
from .tools import build_tool_registry

class DevAssistantView(BaseView):
    route_base = "/dev-assistant"
    default_view = "index"

    @expose("/")
    @has_access
    def index(self):
        return self.render_template(
            "dev_assistant/index.html",
            available_models=self._get_available_models(),
        )

    @expose("/chat", methods=["POST"])
    @has_access
    def chat(self):
        data = request.get_json()
        model = data.get("model", "qwen2.5-coder:7b")
        user_message = data["message"]
        session_id = data.get("session_id")
        # Save to session store, return session_id
        ...

    @expose("/stream/<session_id>")
    @has_access
    def stream(self, session_id):
        messages = self._load_session(session_id)
        model = self._get_session_model(session_id)
        tool_registry = build_tool_registry(g.user)

        @stream_with_context
        def generate():
            for event_type, payload in run_agent_streaming(model, messages, tool_registry):
                yield f"event: {event_type}\ndata: {json.dumps(payload)}\n\n"

        return Response(generate(), mimetype="text/event-stream",
                        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    def _get_available_models(self):
        try:
            resp = requests.get("http://localhost:11434/api/tags", timeout=2)
            return resp.json().get("models", [])
        except Exception:
            return []
```

**Registration in app factory:**

```python
# in your create_app() or appbuilder init

from pgappforge.ai_assistant.views import DevAssistantView

appbuilder.add_view(
    DevAssistantView,
    "Dev Assistant",
    icon="fa-robot",
    category="Tools",
    category_icon="fa-wrench",
)
```

### Directory Structure

```
pgappforge/
└── ai_assistant/
    ├── __init__.py
    ├── views.py          # FAB BaseView with SSE streaming
    ├── agent.py          # ReAct loop, Ollama API calls
    ├── tools.py          # Tool implementations (safe_path, run_command, etc.)
    ├── context.py        # System prompt builder, repo map generator
    ├── session.py        # Conversation history storage (DB or Redis)
    └── templates/
        └── dev_assistant/
            └── index.html    # Chat UI (HTMX or vanilla JS)
tests/ci/
└── test_ai_assistant/
    ├── test_tools.py     # Unit tests for each tool function
    ├── test_agent.py     # Integration tests for ReAct loop
    └── test_views.py     # Flask test client for SSE endpoint
```

### Conversation History Storage

Use the existing FAB SQLAlchemy session for persistence:

```python
# pgappforge/ai_assistant/models.py

from sqlalchemy import Column, String, JSON, DateTime, ForeignKey, Integer
from sqlalchemy.orm import relationship
from pgappforge import db

class AssistantSession(db.Model):
    __tablename__ = "assistant_session"
    id = Column(String(36), primary_key=True, default=uuid7str)
    user_id = Column(Integer, ForeignKey("ab_user.id"), nullable=False)
    model = Column(String(100), nullable=False)
    created_at = Column(DateTime, server_default=db.func.now())
    updated_at = Column(DateTime, onupdate=db.func.now())
    messages = relationship("AssistantMessage", back_populates="session", order_by="AssistantMessage.position")

class AssistantMessage(db.Model):
    __tablename__ = "assistant_message"
    id = Column(String(36), primary_key=True, default=uuid7str)
    session_id = Column(String(36), ForeignKey("assistant_session.id"), nullable=False)
    position = Column(Integer, nullable=False)
    role = Column(String(20), nullable=False)  # system/user/assistant/tool
    content = Column(String, nullable=False)
    tool_calls = Column(JSON, nullable=True)
    tool_name = Column(String(100), nullable=True)
    session = relationship("AssistantSession", back_populates="messages")
```

### Repository Map Generator

Generates a compact structural summary for the system prompt:

```python
import ast
from pathlib import Path

def generate_repo_map(root: Path, max_files: int = 50) -> str:
    """Generate a compact tree-of-signatures map for the system prompt."""
    lines = ["## Project Structure\n"]
    py_files = sorted(root.rglob("*.py"))[:max_files]

    for filepath in py_files:
        rel = filepath.relative_to(root)
        if any(part.startswith(".") for part in rel.parts):
            continue
        if "migrations" in rel.parts or "__pycache__" in rel.parts:
            continue

        lines.append(f"\n### {rel}")
        try:
            tree = ast.parse(filepath.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    bases = [b.id if isinstance(b, ast.Name) else "..." for b in node.bases]
                    lines.append(f"  class {node.name}({', '.join(bases)})")
                elif isinstance(node, ast.FunctionDef) and node.col_offset == 0:
                    lines.append(f"  def {node.name}(...)")
        except SyntaxError:
            lines.append("  [parse error]")

    return "\n".join(lines)
```

---

## 8. Concrete Tool List

Final recommended tool set for the FAB dev assistant agent:

| Tool | Purpose | Risk Level | Available to |
|---|---|---|---|
| `read_file` | Read any file within PROJECT_ROOT | Low | All roles |
| `write_file` | Write/overwrite a file (with diff preview) | Medium | Developer, Admin |
| `list_directory` | List files and dirs at a path | Low | All roles |
| `search_code` | ripgrep search across codebase | Low | All roles |
| `get_git_diff` | Current working tree diff | Low | All roles |
| `get_git_log` | Commit history (read-only) | Low | All roles |
| `get_git_blame` | Who last changed each line of a file | Low | All roles |
| `run_tests` | Execute pytest suite or specific test | Medium | Developer, Admin |
| `run_command` | Whitelisted shell commands only | High | Admin only |
| `query_database` | Read-only SQL query against the app DB | Medium | Developer, Admin |
| `get_model_info` | Get SQLAlchemy model columns/relationships | Low | All roles |
| `get_route_list` | List all registered Flask routes | Low | All roles |
| `check_ollama_models` | List available Ollama models | Low | All roles |

### Tool Implementations

```python
# pgappforge/ai_assistant/tools.py

import ast
import json
import os
import subprocess
from pathlib import Path

PROJECT_ROOT = Path("/Users/nyimbiodero/src/pjs/fab-ext").resolve()

# --- SAFE PATH ---

def safe_path(relative: str) -> Path:
    if not relative:
        return PROJECT_ROOT
    relative = relative.lstrip("/")
    resolved = (PROJECT_ROOT / relative).resolve()
    try:
        resolved.relative_to(PROJECT_ROOT)
    except ValueError:
        raise PermissionError(f"Path traversal rejected: {relative!r}")
    return resolved

# --- FILE TOOLS ---

def read_file(path: str) -> str:
    p = safe_path(path)
    if not p.exists():
        return f"File not found: {path}"
    if p.stat().st_size > 500_000:
        return f"File too large ({p.stat().st_size} bytes). Use search_code to find specific content."
    return p.read_text(errors="replace")

def write_file(path: str, content: str) -> str:
    p = safe_path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return f"Written {len(content)} chars to {path}"

def list_directory(path: str = "") -> str:
    p = safe_path(path)
    if not p.is_dir():
        return f"Not a directory: {path}"
    entries = []
    for child in sorted(p.iterdir()):
        rel = child.relative_to(PROJECT_ROOT)
        kind = "dir" if child.is_dir() else f"file ({child.stat().st_size} bytes)"
        entries.append(f"  {rel}  [{kind}]")
    return "\n".join(entries) or "(empty)"

# --- SEARCH ---

def search_code(pattern: str, glob: str = "*.py") -> str:
    try:
        result = subprocess.run(
            ["rg", "--line-number", "--glob", glob, "--max-count=50", pattern, str(PROJECT_ROOT)],
            capture_output=True, text=True, timeout=15,
        )
        output = result.stdout or result.stderr
        return output[:8000] or "No matches found."
    except FileNotFoundError:
        # Fallback to grep if rg not available
        result = subprocess.run(
            ["grep", "-rn", "--include=*.py", pattern, str(PROJECT_ROOT)],
            capture_output=True, text=True, timeout=15,
        )
        return (result.stdout or "No matches.")[:8000]
    except subprocess.TimeoutExpired:
        return "Search timed out."

# --- GIT TOOLS ---

def get_git_diff(path: str = "") -> str:
    args = ["git", "diff"]
    if path:
        args.append(str(safe_path(path)))
    result = subprocess.run(args, capture_output=True, text=True, cwd=str(PROJECT_ROOT), timeout=10)
    return (result.stdout or "(no diff)")[:10000]

def get_git_log(n: int = 10, path: str = "") -> str:
    args = ["git", "log", f"--oneline", f"-{min(n, 50)}"]
    if path:
        args += ["--", str(safe_path(path))]
    result = subprocess.run(args, capture_output=True, text=True, cwd=str(PROJECT_ROOT), timeout=10)
    return result.stdout or "(no log)"

# --- TEST RUNNER ---

ALLOWED_TEST_PREFIXES = ("tests/ci/", "tests/sqla/", "tests/security/")

def run_tests(test_path: str = "") -> str:
    if test_path:
        p = safe_path(test_path)
        if not any(str(p.relative_to(PROJECT_ROOT)).startswith(prefix) for prefix in ALLOWED_TEST_PREFIXES):
            return f"Test path not in allowed directories: {test_path}"
        cmd = ["uv", "run", "pytest", "-vxs", str(p)]
    else:
        cmd = ["uv", "run", "pytest", "-vxs", "tests/ci"]

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=120, cwd=str(PROJECT_ROOT),
        )
        return (result.stdout + result.stderr)[-8000:]  # Last 8K chars (end of output)
    except subprocess.TimeoutExpired:
        return "Tests timed out after 120 seconds."

# --- REGISTRY BUILDER ---

def build_tool_registry(user) -> dict:
    """Build tool registry based on user role."""
    from flask_login import current_user

    registry = {
        "read_file": read_file,
        "list_directory": list_directory,
        "search_code": search_code,
        "get_git_diff": get_git_diff,
        "get_git_log": get_git_log,
    }

    has_write = any(r.name in ("Admin", "Developer") for r in user.roles)
    if has_write:
        registry["write_file"] = write_file
        registry["run_tests"] = run_tests

    return registry
```

---

## 9. Recommended Models and Pull Commands

### Primary Recommendation by VRAM Tier

**8 GB VRAM (minimum viable):**
```bash
ollama pull qwen2.5-coder:7b
# 4.7 GB download, Q4_K_M, 88.4% HumanEval, 128K context
```

**16 GB VRAM (recommended for production):**
```bash
ollama pull qwen2.5-coder:14b
# ~9 GB download, Q4_K_M, ~89% HumanEval, 128K context

# Alternative: stronger tool calling
ollama pull qwen3-coder:14b
# RL-trained for multi-step coding agent workflows
```

**24 GB VRAM (best quality):**
```bash
ollama pull qwen2.5-coder:32b
# ~20 GB download, Q4_K_M, 92.7% HumanEval, 128K context
# Within a few points of GPT-4o on Aider benchmark
```

**Tool-calling specialist (any VRAM tier):**
```bash
# General tool calling + code — best at its size for agents
ollama pull mistral-small:24b   # 16 GB VRAM, native function calling, strong JSON output

# Agentic coding, RL-trained
ollama pull qwen3-coder:30b     # 24 GB VRAM
```

**Embeddings model (for optional RAG):**
```bash
ollama pull nomic-embed-text    # 274 MB, fast, good code embedding quality
# or
ollama pull mxbai-embed-large   # 670 MB, higher quality
```

**DO NOT USE for tool-calling agents:**
```bash
# These lack native tool calling in Ollama:
# ollama pull mistral-nemo       ← plain text response, no tool_calls
# ollama pull codellama          ← superseded, no tool calling
```

### Model Verification Command

After pulling, verify tool calling support:
```bash
ollama show qwen2.5-coder:7b
# Look for "tools" in the capabilities section
```

### Suggested Default Stack for This Project

```bash
# Install all three for developer + assistant use
ollama pull qwen2.5-coder:7b     # Fast iteration, 8B, 40+ tok/s
ollama pull qwen2.5-coder:14b    # Production default, 14B
ollama pull nomic-embed-text     # Embeddings for optional RAG

# Verify they're available
curl http://localhost:11434/api/tags | python3 -m json.tool
```

---

## 10. Research Gaps and Open Questions

1. **Ollama streaming + tool calls:** The official docs note to "accumulate chunked tool_calls fields" but provide limited examples of streaming agentic loops with tool results. Need to test `stream: true` with `tool_calls` in practice — the done_reason will be `"tool_calls"` not `"stop"`, requiring special handling in the streaming parser.

2. **FAB session management:** The project's existing `ai_data/` and `collaborative/` modules likely have session or conversation primitives. Need to audit `pgappforge/ai_data/utils/context_manager.py` before building a new session model.

3. **KV cache persistence across requests:** Ollama's `keep_alive` keeps the model in VRAM but not the KV cache state. Long conversations re-process the full history on each call. Ollama does not currently expose a stateful session API (unlike some inference servers). This means token cost grows linearly with conversation length.

4. **Structured output format for diffs:** The `format` parameter (JSON schema) in `/api/chat` could force the model to always output diffs in a structured format rather than relying on prompt-following. Not yet tested with `qwen2.5-coder`.

5. **Qwen3-Coder availability in Ollama:** `qwen3-coder` was referenced in search results but its exact availability and tags in the Ollama registry need verification: `ollama pull qwen3-coder` — check https://ollama.com/library/qwen3-coder.

6. **HTMX vs full JS for the chat UI:** FAB's existing templates use Bootstrap + jQuery. Whether to add HTMX for SSE consumption or use vanilla `EventSource` API needs a decision. HTMX's `hx-ext="sse"` extension handles `text/event-stream` natively and integrates with FAB templates without adding a full JS framework.

7. **Multi-user concurrency:** If multiple developers use the assistant simultaneously, Ollama queues requests and serves them sequentially. Under heavy load, this will cause visible latency. The `/api/ps` endpoint can expose current load; a UI indicator preventing "pile-up" submissions would improve UX.

---

## 11. Sources

### Ollama Official Documentation
- [Ollama Streaming API](https://docs.ollama.com/api/streaming)
- [Ollama Tool Calling](https://docs.ollama.com/capabilities/tool-calling)
- [Ollama API Reference (GitHub)](https://github.com/ollama/ollama/blob/main/docs/api.md)
- [Ollama /api/tags - List Models](https://docs.ollama.com/api/tags)
- [Ollama Tool Support Blog Post](https://ollama.com/blog/tool-support)

### Ollama API Tutorials and References
- [Ollama REST API - Postman Documentation](https://www.postman.com/postman-student-programs/ollama-api/documentation/suc47x8/ollama-rest-api)
- [Generation and Chat API - DeepWiki](https://deepwiki.com/ollama/ollama/3.2-generation-and-chat-api)
- [Tool Calling and Function Execution - DeepWiki](https://deepwiki.com/ollama/ollama/7.2-tool-calling-and-function-execution)
- [Ollama API Calls: From curl to OpenAI SDK](https://eastondev.com/blog/en/posts/ai/ollama-api-calls/)
- [How to use Ollama APIs - Geshan Manandhar](https://geshan.com.np/blog/2025/02/ollama-api/)
- [Ollama chat endpoint parameters - Medium](https://medium.com/@laurentkubaski/ollama-chat-endpoint-parameters-21a7ac1252e5)
- [Ollama Tool Support (Function Calling) - Medium](https://medium.com/@laurentkubaski/ollama-tool-support-aka-function-calling-23a1c0189bee)
- [Build AI Agents with Ollama Tool Calling - Markaicode](https://markaicode.com/build-ai-agents-ollama-tool-calling-guide/)
- [Ollama Function Calling Practical Guide - LocalAIMaster](https://localaimaster.com/blog/ollama-function-calling-tools)
- [JSON-based Agents with Ollama & LangChain - Neo4j Blog](https://medium.com/neo4j/json-based-agents-with-ollama-langchain-9cf9ab3c84ef)
- [LLM Basics: Ollama Function Calling - Caktus Group](https://www.caktusgroup.com/blog/2025/12/03/learning-llm-basics-ollama-function-calling/)
- [Best Ollama Models for Function Calling 2025 - Collabnix](https://collabnix.com/best-ollama-models-for-function-calling-tools-complete-guide-2025/)

### Model Benchmarks and Comparisons
- [Best Local Coding LLM 2026: Qwen2.5-Coder vs DeepSeek-Coder-V2 vs Codestral - DEV Community](https://dev.to/jovan_chan_9500711396d4e6/best-local-coding-llm-in-2026-qwen25-coder-vs-deepseek-coder-v2-vs-codestral-45g8)
- [Best Ollama Models: 12 Models Ranked (June 2026) - Morph](https://www.morphllm.com/best-ollama-models)
- [Best Ollama Model for Tool Calling Agent 2026 - Webscraft](https://webscraft.org/blog/yaku-model-ollama-obrati-dlya-agenta-z-tool-calling-porivnyannya-i-benchmarki?lang=en)
- [CodeLlama vs DeepSeek Coder vs Qwen Coder - InsiderLLM](https://insiderllm.com/guides/codellama-vs-deepseek-coder-vs-qwen-coder/)
- [DeepSeek Coder V2 VRAM Requirements - GigaGPU](https://gigagpu.com/deepseek-coder-v2-vram-requirements/)
- [DeepSeek Coder V2 16B: 90% HumanEval, 16GB VRAM - LocalAIMaster](https://localaimaster.com/models/deepseek-coder-v2-16b)
- [Ollama Models Cheat Sheet 2026 - ComputingForGeeks](https://computingforgeeks.com/ollama-models-cheat-sheet/)
- [Best Ollama Models in 2026 - ML Journey](https://mljourney.com/best-ollama-models-in-2026-a-practical-guide-by-use-case/)
- [Local AI Models for Coding: Is It Realistic in 2026? - Failing Fast](https://failingfast.io/local-coding-ai-models/)
- [The Definitive Guide to Running Qwen3-Coder & DeepSeek Locally - TheAITechPulse](https://www.theaitechpulse.com/running-qwen3-coder-deepseek-locally-vram-guide)

### Quantization
- [LLM Quantization Explained: Q4, Q8, FP16 - LLMHardware.io](https://llmhardware.io/guides/llm-quantization-guide)
- [Demystifying LLM Quantization Suffixes - Medium](https://medium.com/@paul.ilvez/demystifying-llm-quantization-suffixes-what-q4-k-m-q8-0-and-q6-k-really-mean-0ec2770f17d3)
- [Q4 vs Q5 vs Q6 vs Q8 Quantization: Real Quality Loss Numbers - RunAIHome](https://runaihome.com/blog/quantization-q4-q5-q6-q8-quality-loss-2026/)
- [GGUF Quantization Explained - BMDPat](https://bmdpat.com/blog/gguf-quantization-q4-q5-q8-explained-2026)
- [Quantization Explained - Microcenter](https://www.microcenter.com/site/mc-news/article/quantization-explained-for-local-ai.aspx)

### ReAct Pattern and Agentic Architecture
- [How to Implement ReAct Pattern for AI Agents - Fast.io](https://fast.io/resources/implementing-react-pattern-ai-agents/)
- [Implementing ReAct Agentic Pattern From Scratch - Daily Dose of DS](https://www.dailydoseofds.com/ai-agents-crash-course-part-10-with-implementation/)
- [Building ReAct agents with LangGraph - Dylan Castillo](https://dylancastillo.co/posts/react-agent-langgraph.html)
- [Building Production ReAct Agents From Scratch - Decoding AI](https://www.decodingai.com/p/building-production-react-agents)
- [LangChain AI Agents: Complete Implementation Guide 2025 - Digital Applied](https://www.digitalapplied.com/blog/langchain-ai-agents-guide-2025)

### SSE and Flask Streaming
- [How to Use SSE to Stream LLM Responses - Medium](https://rowanblackwoon.medium.com/how-to-use-server-sent-events-sse-to-stream-llm-responses-5a3694618c4b)
- [Implementing SSE with Python Flask and React - Ajackus](https://www.ajackus.com/blog/implement-sse-using-python-flask-and-react/)
- [Streaming ChatGPT with SSE in Flask - Pamela Fox Blog](http://blog.pamelafox.org/2023/05/streaming-chatgpt-with-server-sent.html)
- [Streaming data from Flask to HTMX using SSE - Mathspp](https://mathspp.com/blog/streaming-data-from-flask-to-htmx-using-server-side-events)
- [Server-Sent Events in Python with Flask - Medium](https://louwersj.medium.com/server-sent-events-in-python-with-flask-1f9219a1da21)
- [How and why to implement streaming in LLM applications - KushoAI](https://blog.kusho.ai/how-and-why-to-implement-streaming-in-your-llm-application/)

### Context Injection and RAG Strategy
- [Coding Agents are Effective Long-Context Processors - arXiv](https://arxiv.org/html/2603.20432v1)
- [Context Engineering: Why LLMs need more than prompts - GetUnblocked](https://getunblocked.com/blog/context-engineering/)
- [Long Context vs RAG: When 1M Token Windows Replace RAG - SitePoint](https://www.sitepoint.com/long-context-vs-rag-1m-token-windows/)
- [AI Context Windows: Engineering Around Token Limits - Kinde](https://www.kinde.com/learn/ai-for-software-engineering/best-practice/ai-context-windows-engineering-around-token-limits-in-large-codebases/)
- [RAG Is Dead. Long Live Context Engineering - Callstack](https://www.callstack.com/blog/rag-is-dead-long-live-context-engineering-for-llm-systems/)

### Security
- [Architecting Resilient LLM Agents: Secure Plan-then-Execute - arXiv](https://arxiv.org/pdf/2509.08646)
- [Coding Agent Sandbox: Secure Environments for AI-Generated Code - Bunnyshell](https://www.bunnyshell.com/guides/coding-agent-sandbox/)
- [Setting Up a Secure Python Sandbox for LLM Agents - dida.do](https://dida.do/blog/setting-up-a-secure-python-sandbox-for-llm-agents)
- [Practical Security Guidance for Sandboxing Agentic Workflows - NVIDIA](https://developer.nvidia.com/blog/practical-security-guidance-for-sandboxing-agentic-workflows-and-managing-execution-risk/)
- [Agent Sandboxing and Secure Code Execution - TianPan.co](https://tianpan.co/blog/2026-03-09-agent-sandboxing-secure-code-execution)

### Existing Implementations
- [Open-WebUI GitHub Repository](https://github.com/open-webui/open-webui)
- [Open-WebUI Documentation](https://docs.openwebui.com/)
- [Open WebUI Architecture Discussion - GitHub](https://github.com/open-webui/open-webui/discussions/10044)
- [Open WebUI & Ollama Architecture for 500 Concurrent Users - Markaicode](https://markaicode.com/architecture/scalable-open-webui-architecture-production/)
- [Continue.dev: Complete Local AI Coding Assistant Setup - SitePoint](https://www.sitepoint.com/continuedev-for-developers-the-complete-local-ai-coding-assistant-setup/)
- [Continue.dev Context Providers Documentation](https://docs.continue.dev/customize/deep-dives/custom-providers)
- [Continue.dev: Open-Source AI Code Agent Guide - Better Stack](https://betterstack.com/community/guides/ai/continue-dev-ai/)
- [Continue.dev In-depth Analysis - Atoms.dev](https://atoms.dev/insights/continuedev-an-in-depth-analysis-of-an-open-source-ai-powered-coding-assistant-for-enhanced-developer-workflows/6de278ae9d7e4858beaa8e53780b2773)

### Flask-AppBuilder Integration Reference
- [FAB Base Views Documentation](https://flask-appbuilder.readthedocs.io/en/latest/views.html)
- [FAB Base Module Source](https://flask-appbuilder.readthedocs.io/en/latest/_modules/flask_appbuilder/base.html)
- [FAB API Reference](https://flask-appbuilder.readthedocs.io/en/latest/api.html)
