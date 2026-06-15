"""
pgappforge/ai_assistant/tools.py

Tool implementations for the dev assistant ReAct agent.

All file-access tools enforce path confinement via safe_path():
  resolved.relative_to(PROJECT_ROOT) — not startswith(), which is bypassable via symlinks.

Tool tiers (matched to RBAC roles):
  READ_TOOLS   — Viewer, Developer, Admin
  WRITE_TOOLS  — Developer, Admin only
"""
from __future__ import annotations

import json
import logging
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

import requests as _req

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Project root (override via PGAF_DEV_ASSISTANT_ROOT env var)
# ---------------------------------------------------------------------------

PROJECT_ROOT: Path = Path(
	os.environ.get("PGAF_DEV_ASSISTANT_ROOT", Path(__file__).resolve().parents[2])
).resolve()

# ---------------------------------------------------------------------------
# Path safety
# ---------------------------------------------------------------------------

def safe_path(relative: str) -> Path:
	"""Resolve *relative* inside PROJECT_ROOT, rejecting traversal attempts.

	Uses resolved.relative_to(PROJECT_ROOT) — not startswith() — because a
	symlink inside the project can point outside it and bypass prefix checks.
	"""
	if not relative:
		return PROJECT_ROOT
	relative = relative.lstrip("/")
	resolved = (PROJECT_ROOT / relative).resolve()
	try:
		resolved.relative_to(PROJECT_ROOT)
	except ValueError:
		raise PermissionError(f"Path traversal rejected: {relative!r}")
	return resolved

# ---------------------------------------------------------------------------
# File tools
# ---------------------------------------------------------------------------

MAX_FILE_SIZE = 300_000  # bytes — refuse to read larger files whole


def read_file(path: str) -> str:
	"""Read a source file within the project. Returns full text."""
	p = safe_path(path)
	if not p.exists():
		return f"File not found: {path}"
	if not p.is_file():
		return f"Not a file: {path}"
	size = p.stat().st_size
	if size > MAX_FILE_SIZE:
		return (
			f"File too large ({size:,} bytes). "
			f"Use search_code to find specific content, or read a narrower path."
		)
	return p.read_text(errors="replace")


def write_file(path: str, content: str) -> str:
	"""Write or overwrite a file inside the project."""
	p = safe_path(path)
	p.parent.mkdir(parents=True, exist_ok=True)
	p.write_text(content)
	return f"Written {len(content):,} chars to {path}"


def list_directory(path: str = "") -> str:
	"""List files and directories at *path* (default: project root)."""
	p = safe_path(path)
	if not p.is_dir():
		return f"Not a directory: {path or '(project root)'}"
	entries: list[str] = []
	for child in sorted(p.iterdir()):
		try:
			rel = child.relative_to(PROJECT_ROOT)
		except ValueError:
			continue
		if child.is_dir():
			entries.append(f"  {rel}/")
		else:
			entries.append(f"  {rel}  ({child.stat().st_size:,} bytes)")
	return "\n".join(entries) or "(empty directory)"


def read_log(path: str, last_n_lines: int = 150) -> str:
	"""Read the last N lines of a project-local log file (must be inside PROJECT_ROOT).

	System logs outside the project (e.g. /var/log/) are not accessible by design.
	"""
	p = safe_path(path)
	if not p.exists():
		return f"Log file not found: {path}"
	if not p.is_file():
		return f"Not a file: {path}"
	try:
		last_n_lines = max(1, min(int(last_n_lines), 2000))
	except (TypeError, ValueError):
		last_n_lines = 150
	lines = p.read_text(errors="replace").splitlines()
	return "\n".join(lines[-last_n_lines:]) or "(empty log)"

# ---------------------------------------------------------------------------
# Code search
# ---------------------------------------------------------------------------

def search_code(pattern: str, glob: str = "*.py", max_matches: int = 50) -> str:
	"""Search the codebase with ripgrep. Falls back to grep if rg is absent."""
	if not pattern:
		return "Pattern is required."
	try:
		result = subprocess.run(
			[
				"rg", "--line-number", "--with-filename",
				"--glob", glob,
				f"--max-count={max_matches}",
				pattern,
				str(PROJECT_ROOT),
			],
			capture_output=True, text=True, timeout=15,
		)
		output = result.stdout or result.stderr or "No matches found."
		return output[:8000]
	except FileNotFoundError:
		result = subprocess.run(
			["grep", "-rn", f"--include={glob}", "--max-count=100", pattern, str(PROJECT_ROOT)],
			capture_output=True, text=True, timeout=15,
		)
		return (result.stdout or "No matches found.")[:8000]
	except subprocess.TimeoutExpired:
		return "Search timed out after 15 s."

# ---------------------------------------------------------------------------
# Git tools
# ---------------------------------------------------------------------------

def get_git_diff(path: str = "") -> str:
	"""Get the current working-tree diff, optionally scoped to *path*."""
	args: list[str] = ["git", "diff"]
	if path:
		args.append(str(safe_path(path)))
	result = subprocess.run(
		args, capture_output=True, text=True, cwd=str(PROJECT_ROOT), timeout=10
	)
	return (result.stdout or "(no diff)")[:10000]


def get_git_log(n: int = 10, path: str = "") -> str:
	"""Get the last *n* commit log lines, optionally filtered by *path*."""
	try:
		count = max(1, min(int(n), 50))
	except (TypeError, ValueError):
		count = 10
	args = ["git", "log", "--oneline", f"-{count}"]
	if path:
		args += ["--", str(safe_path(path))]
	result = subprocess.run(
		args, capture_output=True, text=True, cwd=str(PROJECT_ROOT), timeout=10
	)
	return result.stdout or "(no log)"


def get_git_status() -> str:
	"""Get current git working-tree status."""
	result = subprocess.run(
		["git", "status", "--short"],
		capture_output=True, text=True, cwd=str(PROJECT_ROOT), timeout=10,
	)
	return result.stdout or "(clean working tree)"

# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------

_ALLOWED_TEST_DIRS = ("tests/ci/", "tests/sqla/", "tests/security/", "tests/")


def run_tests(test_path: str = "") -> str:
	"""Run pytest on *test_path* (default: tests/ci). Returns last 8 K of output."""
	if test_path:
		p = safe_path(test_path)
		rel = str(p.relative_to(PROJECT_ROOT))
		if not any(rel.startswith(d) for d in _ALLOWED_TEST_DIRS):
			return f"Test path not in allowed directories: {test_path}"
		cmd = [sys.executable, "-m", "pytest", "-q", "--tb=short", str(p)]
	else:
		cmd = [sys.executable, "-m", "pytest", "-q", "--tb=short", "tests/ci"]
	try:
		result = subprocess.run(
			cmd, capture_output=True, text=True,
			timeout=180, cwd=str(PROJECT_ROOT),
		)
		return (result.stdout + result.stderr)[-8000:]
	except subprocess.TimeoutExpired:
		return "Tests timed out after 180 s."

# ---------------------------------------------------------------------------
# Whitelisted shell command runner
# ---------------------------------------------------------------------------

_ALLOWED_CMD_PREFIXES = (
	"git diff", "git log", "git status", "git show", "git branch",
	"rg ", "grep ",
	".venv/bin/python -m pytest",
	".venv/bin/python -m pyright",
	".venv/bin/python -m pip list",
	".venv/bin/python -m pip show",
	"find ",
)

_BLOCKED_PATTERNS = (
	"rm ", "rmdir", "sudo", "curl", "wget",
	"pip install", "pip uninstall", "uv add", "uv remove",
	"> /", ">>",
	"chmod", "chown",
	"/etc/", "/root/", "/proc/", "/sys/",
	"ssh ", "scp ",
	"; rm", "&&rm", "||rm",
	"nohup", " &",
	# find -exec spawns arbitrary processes outside the project — block explicitly
	"-exec ", "-execdir ",
	# guard against piping to interpreters
	"| bash", "| sh", "| python",
)


def run_command(command: str, timeout: int = 30) -> str:
	"""Execute a whitelisted read-only shell command in the project root."""
	timeout = min(int(timeout), 60)
	cmd_lower = command.strip().lower()

	for blocked in _BLOCKED_PATTERNS:
		if blocked in cmd_lower:
			return f"Command blocked (matches blocked pattern {blocked!r}): {command!r}"

	if not any(cmd_lower.startswith(prefix) for prefix in _ALLOWED_CMD_PREFIXES):
		return (
			f"Command not in allowlist: {command!r}. "
			f"Allowed prefixes: {_ALLOWED_CMD_PREFIXES}"
		)

	try:
		args = shlex.split(command)
	except ValueError as exc:
		return f"Could not parse command: {exc}"

	try:
		result = subprocess.run(
			args,
			capture_output=True, text=True,
			timeout=timeout,
			cwd=str(PROJECT_ROOT),
		)
		return (result.stdout + result.stderr)[:10000]
	except subprocess.TimeoutExpired:
		return f"Command timed out after {timeout} s."
	except Exception as exc:
		return f"Command failed: {exc}"

# ---------------------------------------------------------------------------
# App introspection
# ---------------------------------------------------------------------------

_SENSITIVE_KEY_FRAGMENTS = frozenset({
	"secret", "password", "passwd", "token", "key", "private", "credential",
	"uri", "url", "dsn", "connstr",
})

# Matches any connection string embedding credentials: proto://user:pass@host
_CONNSTR_RE = re.compile(r"[a-z+]+://[^:@\s]+:[^@\s]+@", re.IGNORECASE)


def get_env_vars() -> str:
	"""Return project-relevant environment variables with sensitive values masked.

	Shows vars prefixed with PGAF_, FLASK_, SQLALCHEMY_, DATABASE_, REDIS_,
	CELERY_, DEBUG, TESTING, APP_ — enough to confirm what config the live
	process loaded without leaking credentials.
	"""
	_SHOW_PREFIXES = (
		"PGAF_", "FLASK_", "SQLALCHEMY_", "DATABASE_", "REDIS_",
		"CELERY_", "DEBUG", "TESTING", "APP_", "OLLAMA_", "DEV_ASSISTANT_",
	)
	lines: list[str] = []
	for k, v in sorted(os.environ.items()):
		if not any(k.startswith(p) or k == p.rstrip("_") for p in _SHOW_PREFIXES):
			continue
		k_lower = k.lower()
		if any(frag in k_lower for frag in _SENSITIVE_KEY_FRAGMENTS):
			display = "***"
		elif _CONNSTR_RE.search(v):
			display = "***  (connection string masked)"
		else:
			display = v[:120] + ("…" if len(v) > 120 else "")
		lines.append(f"  {k}={display}")
	return "\n".join(lines) or "(no matching environment variables found)"


def get_route_list() -> str:
	"""Find all @expose-decorated routes via static analysis."""
	return search_code(r"@expose\(", glob="*.py", max_matches=100)


def check_ollama_models() -> str:
	"""List models available in the local Ollama instance."""
	ollama_url = os.environ.get("OLLAMA_URL", "http://localhost:11434")
	try:
		resp = _req.get(f"{ollama_url}/api/tags", timeout=3)
		resp.raise_for_status()
		models = resp.json().get("models", [])
		if not models:
			return "No models found. Run: ollama pull qwen2.5-coder:7b"
		lines = [f"  {m['name']}  ({m.get('size', 0)//1_000_000} MB)" for m in models]
		return "Available Ollama models:\n" + "\n".join(lines)
	except Exception as exc:
		return f"Ollama not reachable at {ollama_url}: {exc}"

# ---------------------------------------------------------------------------
# Tool schema (JSON Schema for Ollama tool calling)
# ---------------------------------------------------------------------------

TOOL_SCHEMAS: list[dict] = [
	{
		"type": "function",
		"function": {
			"name": "read_file",
			"description": "Read the contents of a source file in the project. Returns full text.",
			"parameters": {
				"type": "object",
				"properties": {
					"path": {"type": "string", "description": "Relative path from project root, e.g. pgappforge/base.py"},
				},
				"required": ["path"],
			},
		},
	},
	{
		"type": "function",
		"function": {
			"name": "write_file",
			"description": "Write or overwrite a file in the project workspace.",
			"parameters": {
				"type": "object",
				"properties": {
					"path": {"type": "string", "description": "Relative path from project root"},
					"content": {"type": "string", "description": "Full file content to write"},
				},
				"required": ["path", "content"],
			},
		},
	},
	{
		"type": "function",
		"function": {
			"name": "list_directory",
			"description": "List files and directories at a path within the project.",
			"parameters": {
				"type": "object",
				"properties": {
					"path": {"type": "string", "description": "Relative path (empty = project root)"},
				},
				"required": [],
			},
		},
	},
	{
		"type": "function",
		"function": {
			"name": "search_code",
			"description": "Search the codebase with ripgrep. Returns matching lines with file:line.",
			"parameters": {
				"type": "object",
				"properties": {
					"pattern": {"type": "string", "description": "Regex or literal pattern"},
					"glob": {"type": "string", "description": "File glob filter, e.g. '*.py' (default)"},
				},
				"required": ["pattern"],
			},
		},
	},
	{
		"type": "function",
		"function": {
			"name": "get_git_diff",
			"description": "Get the current working-tree git diff.",
			"parameters": {
				"type": "object",
				"properties": {
					"path": {"type": "string", "description": "Optional: scope to this file/dir"},
				},
				"required": [],
			},
		},
	},
	{
		"type": "function",
		"function": {
			"name": "get_git_log",
			"description": "Get recent commit log.",
			"parameters": {
				"type": "object",
				"properties": {
					"n": {"type": "integer", "description": "Number of commits (default 10, max 50)"},
					"path": {"type": "string", "description": "Optional: filter to commits touching this file"},
				},
				"required": [],
			},
		},
	},
	{
		"type": "function",
		"function": {
			"name": "get_git_status",
			"description": "Get the current git working-tree status (modified/untracked files).",
			"parameters": {"type": "object", "properties": {}, "required": []},
		},
	},
	{
		"type": "function",
		"function": {
			"name": "run_tests",
			"description": "Run the pytest test suite or a specific test file.",
			"parameters": {
				"type": "object",
				"properties": {
					"test_path": {"type": "string", "description": "Specific test file or dir. Empty = run all CI tests."},
				},
				"required": [],
			},
		},
	},
	{
		"type": "function",
		"function": {
			"name": "run_command",
			"description": "Execute a whitelisted shell command (git read-only, rg, grep, find, pytest, pyright, pip list/show).",
			"parameters": {
				"type": "object",
				"properties": {
					"command": {"type": "string", "description": "The shell command to run"},
					"timeout": {"type": "integer", "description": "Timeout in seconds (max 60)"},
				},
				"required": ["command"],
			},
		},
	},
	{
		"type": "function",
		"function": {
			"name": "check_ollama_models",
			"description": "List locally available Ollama models.",
			"parameters": {"type": "object", "properties": {}, "required": []},
		},
	},
	{
		"type": "function",
		"function": {
			"name": "get_env_vars",
			"description": "Show project-relevant environment variables (PGAF_, FLASK_, SQLALCHEMY_, etc.). Sensitive values are masked with ***.",
			"parameters": {"type": "object", "properties": {}, "required": []},
		},
	},
	{
		"type": "function",
		"function": {
			"name": "read_log",
			"description": "Read the last N lines of a log file inside the project (app logs, test output logs, etc.).",
			"parameters": {
				"type": "object",
				"properties": {
					"path": {"type": "string", "description": "Relative path to the log file"},
					"last_n_lines": {"type": "integer", "description": "How many lines from the end to return (default 150, max 2000)"},
				},
				"required": ["path"],
			},
		},
	},
	{
		"type": "function",
		"function": {
			"name": "get_route_list",
			"description": "Find all @expose-decorated view routes via static analysis of the codebase.",
			"parameters": {"type": "object", "properties": {}, "required": []},
		},
	},
]

# Read-only tool names — available to all roles
READ_TOOL_NAMES: frozenset[str] = frozenset({
	"read_file", "list_directory", "search_code",
	"get_git_diff", "get_git_log", "get_git_status",
	"run_command", "check_ollama_models", "read_log", "get_env_vars",
	"get_route_list",
})

# Write tool names — Developer + Admin only
WRITE_TOOL_NAMES: frozenset[str] = frozenset({
	"write_file", "run_tests",
})

# ---------------------------------------------------------------------------
# Registry builder
# ---------------------------------------------------------------------------

_TOOL_FN_MAP: dict[str, Any] = {
	"read_file": read_file,
	"write_file": write_file,
	"list_directory": list_directory,
	"search_code": search_code,
	"get_git_diff": get_git_diff,
	"get_git_log": get_git_log,
	"get_git_status": get_git_status,
	"run_tests": run_tests,
	"run_command": run_command,
	"check_ollama_models": check_ollama_models,
	"read_log": read_log,
	"get_env_vars": get_env_vars,
	"get_route_list": get_route_list,
}


def build_tool_registry(user_roles: set[str]) -> tuple[list[dict], dict[str, Any]]:
	"""Return (tool_schemas, tool_fn_registry) filtered by user roles.

	Args:
		user_roles: set of role name strings (e.g. {'Admin', 'Developer'})

	Returns:
		schemas: list of tool JSON Schema dicts to pass to Ollama
		registry: name → callable for tool execution
	"""
	has_write = bool(user_roles & {"Admin", "Developer"})
	allowed_names = READ_TOOL_NAMES | (WRITE_TOOL_NAMES if has_write else frozenset())
	schemas = [s for s in TOOL_SCHEMAS if s["function"]["name"] in allowed_names]
	registry = {name: fn for name, fn in _TOOL_FN_MAP.items() if name in allowed_names}
	return schemas, registry


__all__ = [
	"safe_path", "PROJECT_ROOT",
	"read_file", "write_file", "list_directory", "search_code",
	"get_git_diff", "get_git_log", "get_git_status",
	"run_tests", "run_command", "check_ollama_models", "read_log", "get_env_vars",
	"get_route_list",
	"TOOL_SCHEMAS", "READ_TOOL_NAMES", "WRITE_TOOL_NAMES",
	"build_tool_registry",
]
