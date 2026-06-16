# Dev Assistant — Developer Documentation

Ollama-backed chat interface for developing, debugging, and administering PgAppForge applications. Available to both the developer at build time and the application administrator at runtime.

---

## Architecture

```
Browser (SSE fetch)
  └─ DevAssistantView  (/dev-assistant/)
       ├─ build_system_prompt()   → system prompt with AST repo map
       ├─ build_tool_registry()   → RBAC-filtered tool list
       └─ run_agent_stream()      → Ollama ReAct loop
            ├─ _chat_stream()     → POST /api/chat (NDJSON stream)
            └─ tool dispatch      → 13 tool functions
```

### Module layout

```
pgappforge/
  ai_assistant/
    __init__.py      FAB plugin (DevAssistantPlugin)
    tools.py         13 tool functions + RBAC registry
    context.py       AST repo map + system prompt builder
    agent.py         Ollama ReAct loop (streaming + blocking)
    views.py         Flask views: GET /, POST /chat, GET /models

pgappforge/templates/dev_assistant/
    index.html       Chat UI (vanilla JS + SSE fetch)

tests/ci/
    test_ai_assistant.py   45 tests
```

---

## Installation

### 1. Install Ollama and pull a model

```bash
# Install Ollama: https://ollama.com
ollama pull qwen2.5-coder:7b      # recommended — strong tool-calling
# or
ollama pull llama3.1:8b
ollama pull codestral:22b         # larger, better reasoning
```

### 2. Add to Flask config

```python
# config.py
ADDON_MANAGERS = [
    "pgappforge.ai_assistant.DevAssistantPlugin",
    # ... other addons
]
```

### 3. Environment variables

All configuration is via environment variables (not `app.config`):

| Variable | Default | Description |
|---|---|---|
| `OLLAMA_URL` | `http://localhost:11434` | Ollama base URL |
| `DEV_ASSISTANT_MODEL` | `qwen2.5-coder:7b` | Default model (overridable per-request from UI) |
| `PGAF_DEV_ASSISTANT_ROOT` | Parent of `pgappforge/` package | Project root for path confinement and repo map |
| `DEV_ASSISTANT_WRITE_ROLES` | `Admin,Developer` | Comma-separated FAB role names that unlock write tools (`write_file`, `run_tests`) |

```bash
export OLLAMA_URL=http://ollama-host:11434
export DEV_ASSISTANT_MODEL=qwen2.5-coder:14b
```

### 4. Assign permissions

On first boot, FAB writes three permissions to the security database:

- `can_index on DevAssistantView`  — view the UI
- `can_chat on DevAssistantView`   — submit messages
- `can_models on DevAssistantView` — query available models

Assign these to roles via the FAB security admin (`/users/roles/list`). Write tools (`write_file`, `run_tests`) are additionally gated to roles named **`Admin`** or **`Developer`**; all other roles see read-only tools.

> **Note:** Permissions are created automatically on every startup when `PGAF_UPDATE_PERMS = True` (the default). If you have disabled this, run the FAB security sync manually before assigning roles.

### 5. Production WSGI requirement

`/dev-assistant/chat` is a streaming SSE endpoint. It **requires a non-buffering WSGI worker**. The default gunicorn sync worker buffers the entire response before sending, breaking the token-by-token UI.

```bash
# Option A — gthread (recommended, no extra deps)
gunicorn app:app -w 4 -k gthread --threads 4

# Option B — gevent
pip install gevent
gunicorn app:app -w 4 -k gevent

# Option C — uvicorn (ASGI adapter)
pip install uvicorn asgiref
```

nginx config (already handled by the `X-Accel-Buffering: no` response header):
```nginx
location /dev-assistant/chat {
    proxy_pass http://app;
    proxy_buffering off;
    proxy_cache off;
}
```

---

## URL Routes

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/dev-assistant/` | `can_index` | Chat UI |
| `POST` | `/dev-assistant/chat` | `can_chat` | SSE stream endpoint |
| `GET` | `/dev-assistant/models` | `can_models` | JSON list of Ollama models |

---

## POST /dev-assistant/chat

### Request

```json
{
  "message": "What does the ARInvoice model look like?",
  "model":   "qwen2.5-coder:7b",
  "history": [
    {"role": "user",      "content": "Show me the AP module"},
    {"role": "assistant", "content": "Here is pgappforge/plugins/erp/finance/ap/..."}
  ]
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `message` | string | yes | Current user turn |
| `model` | string | no | Overrides `DEV_ASSISTANT_MODEL`; sanitized server-side |
| `history` | array | no | Prior turns; `system`/`tool` roles stripped; capped at 40 turns; content capped at 8000 chars/turn |

### Response (SSE stream)

Each `data:` line is a JSON object with an `event` field:

```
data: {"event":"token","data":"The AR"}
data: {"event":"token","data":"Invoice model..."}
data: {"event":"tool_call","tool":"read_file","args":{"path":"pgappforge/.../models.py"}}
data: {"event":"tool_result","tool":"read_file","result":"class ARInvoice..."}
data: {"event":"token","data":"Here is the full model:"}
data: {"event":"done"}
```

| Event | Fields | Description |
|---|---|---|
| `token` | `data` | Incremental text from the model |
| `tool_call` | `tool`, `args` | Agent is about to execute a tool |
| `tool_result` | `tool`, `result` (truncated to 500 chars) | Tool execution result |
| `done` | — | Stream complete |
| `error` | `message` | Recoverable error (Ollama unreachable, tool failure, etc.) |

---

## Tools

### Read tools (all authenticated roles)

| Tool | Description |
|---|---|
| `read_file` | Read a source file (≤ 300 KB). Path confined to project root. |
| `list_directory` | List files in a project directory |
| `search_code` | Ripgrep (falls back to grep). Returns `file:line: match`. |
| `get_git_diff` | Working-tree diff, optionally scoped to a path |
| `get_git_log` | Last N commits (max 50), optionally filtered by path |
| `get_git_status` | `git status --short` |
| `run_command` | Whitelisted read-only commands (see below) |
| `read_log` | Last N lines of a project-local log file (max 2000) |
| `get_env_vars` | Project-relevant env vars with credentials masked |
| `get_route_list` | All `@expose()`-decorated routes via static analysis |
| `check_ollama_models` | List available Ollama models |

### Write tools (Admin and Developer roles only)

| Tool | Description |
|---|---|
| `write_file` | Create or overwrite a file inside the project |
| `run_tests` | Run pytest on `tests/ci/` or a specific test path |

### run_command allowlist

Allowed command prefixes:

```
git diff, git log, git status, git show, git branch
rg <pattern>
grep <pattern>
<python> -m pytest
<python> -m pyright
<python> -m pip list
<python> -m pip show
find <path>
```

Where `<python>` is both `sys.executable` and `.venv/bin/python` (for local dev compat).

Blocked patterns (checked before allowlist):

```
rm, rmdir, sudo, curl, wget
pip install/uninstall, uv add/remove
> / >>  (redirects)
chmod, chown
/etc/ /root/ /proc/ /sys/
ssh, scp
; rm  && rm  || rm
nohup, &  (background)
-exec, -execdir  (find subprocess spawning)
| bash  | sh  | python  (pipe to interpreter)
```

### Path safety

All file tools resolve paths with `Path.resolve()` and call `.relative_to(PROJECT_ROOT)`. Symlink traversal is rejected — a symlink inside the project pointing outside it cannot be followed.

```python
safe_path("../../etc/passwd")   # raises PermissionError
safe_path("/etc/passwd")        # raises PermissionError (lstripped then rejected)
safe_path("pgappforge/base.py") # ok
```

### Credential masking in get_env_vars

Values are masked (`***`) when:
- The key name (lowercased) contains any of: `secret`, `password`, `passwd`, `token`, `key`, `private`, `credential`, `uri`, `url`, `dsn`, `connstr`
- The value matches a connection-string pattern: `scheme://user:pass@host`

This means `SQLALCHEMY_DATABASE_URI` and `DATABASE_URL` are always masked.

---

## ReAct Agent Loop

```
user_message
    │
    ▼
[system prompt + history + user message]
    │
    ▼
POST Ollama /api/chat (stream=True)
    │
    ├─ done_reason == "stop"  →  yield final tokens  →  SSE done
    │
    └─ done_reason == "tool_calls"
            │
            ├─ anti-loop check: (name + sorted_args) fingerprint
            │   repeat fingerprint  →  SSE error + done
            │
            ├─ MAX_TOOL_ROUNDS exceeded (12)  →  SSE error + done
            │
            └─ execute each tool
                    │  append {"role":"tool","name":name,"content":result}
                    └─ loop back to POST Ollama
```

**Anti-loop guard:** The fingerprint is `"|".join(sorted(name + ":" + json.dumps(args, sort_keys=True) for each call))`. This allows the same tool with different args (e.g., reading two different files) while catching infinite loops on identical calls.

**Timeout:** Connect timeout 10 s, per-chunk read timeout 30 s. For large models generating long tokens, increase `OLLAMA_REQUEST_TIMEOUT` (not yet exposed — patch `agent.py:102` directly if needed).

---

## Context and System Prompt

`build_system_prompt(root)` constructs the system prompt by:

1. Embedding `_BASE_SYSTEM_PROMPT` — project layout, code standards (tabs, PG-only, Pydantic v2, SQLAlchemy 2.x, UUID7, modern typing), test command, agent workflow instructions.
2. Appending an AST-based repo map (up to 80 files): class names + bases + top 8 methods + module-level functions. No code execution — pure AST parse.
3. Appending any `extra_context` string passed by the caller.

The `app_name` parameter replaces all occurrences of "PgAppForge" in the prompt, enabling white-labelled deployments.

### Skipped directories in repo map

`.venv`, `.git`, `__pycache__`, `node_modules`, `migrations`, `static`, `translations`, `dist`, `build`, `.tox`

---

## CSRF Considerations

The `/dev-assistant/chat` endpoint uses `request.get_json(force=True)`. Whether it is covered by Flask-WTF CSRF depends on your project's CSRF configuration:

- **CSRF globally disabled** (common in API-first FAB setups): no action needed.
- **CSRF globally enabled**: add `@csrf.exempt` to `DevAssistantView.chat`, or configure the CSRF extension to exclude the endpoint. Without this, every POST will return HTTP 400.

The browser fetch in `index.html` sends no CSRF token header. Add one if required:

```javascript
headers: {
    "Content-Type": "application/json",
    "X-CSRFToken": document.querySelector('meta[name="csrf-token"]').content,
}
```

---

## Plugin Registration Internals

`DevAssistantPlugin(BaseManager)` is loaded via `ADDON_MANAGERS`. The FAB lifecycle:

1. `AppBuilder._process_legacy_addons()` imports the class and instantiates it with `(appbuilder)`.
2. Calls `pre_process()` → `register_views()` → `post_process()` inside an app context.
3. `register_views()` calls `appbuilder.add_view_no_menu(DevAssistantView)`.
4. `add_view_no_menu` registers the Flask blueprint, discovers `@expose`-decorated methods, and writes permissions to the security DB (when `PGAF_UPDATE_PERMS=True`).

No menu entry is created. The UI is accessible directly at `/dev-assistant/`.

---

## Running Tests

```bash
# Full ai_assistant suite (45 tests, ~3 min)
.venv/bin/python -m pytest tests/ci/test_ai_assistant.py -v

# Quick smoke test (import + tool registry)
.venv/bin/python -c "
from pgappforge.ai_assistant.tools import build_tool_registry, TOOL_SCHEMAS
schemas, reg = build_tool_registry({'Admin'})
print(f'{len(schemas)} tools for Admin, {len(reg)} in registry')
from pgappforge.ai_assistant.context import build_system_prompt
from pathlib import Path
prompt = build_system_prompt(Path('.'))
print(f'System prompt: {len(prompt)} chars')
"
```

---

## Deployment Checklist

- [ ] Ollama running and model pulled (`ollama pull qwen2.5-coder:7b`)
- [ ] `ADDON_MANAGERS` includes `"pgappforge.ai_assistant.DevAssistantPlugin"`
- [ ] `OLLAMA_URL` set if Ollama is not on localhost
- [ ] WSGI worker supports streaming (gthread/gevent/uvicorn — not gunicorn sync)
- [ ] nginx `proxy_buffering off` on `/dev-assistant/chat` (or `X-Accel-Buffering: no` header handled)
- [ ] App booted once so FAB writes `can_index/can_chat/can_models` permissions
- [ ] Roles granted the three permissions in FAB security admin
- [ ] Roles named `Admin` / `Developer` exist for write-tool access (or edit `tools.py:_WRITE_ROLES`)
- [ ] CSRF exemption configured if Flask-WTF CSRF is globally enabled

---

## Known Limitations

| Area | Limitation | Workaround |
|---|---|---|
| Context window | No token counting — large `read_file` calls can exhaust model context | Use `search_code` to find specific content instead of reading whole files |
| History | Client-owned history: a crafted client can inject `assistant` role turns | Acceptable trust boundary for admin/developer tool |
| Model validation | Model name sanitized but not validated against installed models | Ollama returns an error event if model is not found |
| Streaming timeout | 30s per-chunk read timeout — may truncate very slow model responses | Set a longer timeout by patching `agent.py` or increasing Ollama's keep-alive |
| Write tools | `write_file` has no diff preview or undo — writes are immediate | Review with `get_git_diff` after writes; use `get_git_status` to track changes |
| Concurrent sessions | No server-side session storage — each request is stateless | History is client-owned; multiple tabs work independently |
