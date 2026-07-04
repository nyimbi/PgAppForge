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

import datetime
import difflib
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

try:
	from sqlalchemy import inspect as sa_inspect
	_HAS_SQLALCHEMY = True
except ImportError:
	_HAS_SQLALCHEMY = False

try:
	from .embeddings import (
		search_embeddings as _search_embeddings,
		index_codebase as _index_codebase,
		ensure_schema as _ensure_schema,
	)
	_HAS_EMBEDDINGS = True
except Exception as _emb_exc:
	_search_embeddings = None
	_index_codebase = None
	_ensure_schema = None
	_HAS_EMBEDDINGS = False
	logging.getLogger(__name__).warning(
		"dev_assistant: embeddings module unavailable — semantic_search disabled: %s", _emb_exc
	)

from ._db import get_engine as _get_db_engine

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

# ---------------------------------------------------------------------------
# Audit log (append-only JSONL; records every write operation)
# ---------------------------------------------------------------------------
# Path is derived from PROJECT_ROOT at call time so test overrides propagate.
_AUDIT_SUBPATH = Path("logs") / "dev_assistant_audit.jsonl"


def _audit(action: str, **details: Any) -> None:
	"""Append one audit record. Never raises — audit failure must not break tools."""
	try:
		log_path = PROJECT_ROOT / _AUDIT_SUBPATH
		log_path.parent.mkdir(parents=True, exist_ok=True)
		record = json.dumps({
			"ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
			"action": action, **details,
		})
		with log_path.open("a") as fh:
			fh.write(record + "\n")
	except Exception:
		pass


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
	"""Write or overwrite a file inside the project. Returns a unified diff of what changed."""
	p = safe_path(path)
	old_lines = p.read_text(errors="replace").splitlines(keepends=True) if p.exists() else []
	new_lines = content.splitlines(keepends=True)
	p.parent.mkdir(parents=True, exist_ok=True)
	p.write_text(content)
	diff = list(difflib.unified_diff(old_lines, new_lines, fromfile=f"a/{path}", tofile=f"b/{path}", n=2))
	_audit("write_file", path=path, chars=len(content), lines_changed=len(diff))
	if diff:
		return "".join(diff[:60]) + (f"\n… ({len(diff) - 60} more diff lines)" if len(diff) > 60 else "")
	return f"Written {len(content):,} chars to {path} (no change from previous content)"


def patch_file(path: str, old_str: str, new_str: str) -> str:
	"""Make a targeted replacement inside a file without rewriting the whole thing.

	Fails clearly if old_str appears zero times (typo) or more than once (ambiguous).
	Returns a unified diff of what changed.
	"""
	p = safe_path(path)
	if not p.exists() or not p.is_file():
		return f"File not found: {path}"
	content = p.read_text(errors="replace")
	count = content.count(old_str)
	if count == 0:
		# Give a helpful hint — show the first 200 chars of the file so the agent can recheck
		return (f"old_str not found in {path} (whitespace and indentation must match exactly). "
				f"First 200 chars of file:\n{content[:200]}")
	if count > 1:
		return (f"old_str appears {count} times in {path} — add more surrounding context "
				f"to make it unique.")
	new_content = content.replace(old_str, new_str, 1)
	old_lines = content.splitlines(keepends=True)
	new_lines = new_content.splitlines(keepends=True)
	diff = list(difflib.unified_diff(old_lines, new_lines, fromfile=f"a/{path}", tofile=f"b/{path}", n=3))
	p.write_text(new_content)
	_audit("patch_file", path=path, old_len=len(old_str), new_len=len(new_str))
	return "".join(diff[:80]) or f"Patched {path} (old_str and new_str were identical)"


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

_PYTHON = sys.executable  # resolved once at import; used in all subprocess calls to the active interpreter
_ALLOWED_TEST_DIRS = ("tests/ci/", "tests/sqla/", "tests/security/", "tests/")


def run_tests(test_path: str = "") -> str:
	"""Run pytest on *test_path* (default: tests/ci). Returns last 8 K of output."""
	if test_path:
		p = safe_path(test_path)
		rel = str(p.relative_to(PROJECT_ROOT))
		if not any(rel.startswith(d) for d in _ALLOWED_TEST_DIRS):
			return f"Test path not in allowed directories: {test_path}"
		cmd = [_PYTHON, "-m", "pytest", "-q", "--tb=short", str(p)]
	else:
		cmd = [_PYTHON, "-m", "pytest", "-q", "--tb=short", "tests/ci"]
	try:
		result = subprocess.run(
			cmd, capture_output=True, text=True,
			timeout=180, cwd=str(PROJECT_ROOT),
		)
		output = (result.stdout + result.stderr)[-8000:]
		_audit("run_tests", path=test_path or "tests/ci", returncode=result.returncode)
		return output
	except subprocess.TimeoutExpired:
		return "Tests timed out after 180 s."

# ---------------------------------------------------------------------------
# Whitelisted shell command runner
# ---------------------------------------------------------------------------

_ALLOWED_CMD_PREFIXES = (
	"git diff", "git log", "git status", "git show", "git branch",
	"rg ", "grep ",
	# Canonical paths for the active interpreter
	f"{_PYTHON} -m pytest",
	f"{_PYTHON} -m pyright",
	f"{_PYTHON} -m pip list",
	f"{_PYTHON} -m pip show",
	# Legacy relative path kept for backwards compat in local dev
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
	cmd_stripped = command.strip()
	cmd_lower = cmd_stripped.lower()  # lowercase only for blocked-pattern matching

	for blocked in _BLOCKED_PATTERNS:
		if blocked in cmd_lower:
			return f"Command blocked (matches blocked pattern {blocked!r}): {command!r}"

	# Allowlist check uses the original case — sys.executable paths are case-sensitive on Linux
	# and the capital /Users/ prefix on macOS must match literally.
	if not any(cmd_stripped.startswith(prefix) for prefix in _ALLOWED_CMD_PREFIXES):
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


def get_db_schema(table_name: str = "") -> str:
	"""Introspect the live PostgreSQL database schema using SQLAlchemy reflection.

	With no argument: list all public tables.
	With table_name: show columns, types, PKs, FKs, and indexes for that table.
	"""
	if not _HAS_SQLALCHEMY:
		return "SQLAlchemy not installed (unexpected in this environment)."
	engine = _get_db_engine()
	if engine is None:
		return "No SQLALCHEMY_DATABASE_URI in environment."
	try:
		insp = sa_inspect(engine)
		if table_name:
			cols = insp.get_columns(table_name, schema="public")
			pk_cols = set(insp.get_pk_constraint(table_name, schema="public").get("constrained_columns", []))
			fks = insp.get_foreign_keys(table_name, schema="public")
			idxs = insp.get_indexes(table_name, schema="public")
			lines = [f"Table: {table_name}", "─" * 60, "Columns:"]
			for col in cols:
				pk = " [PK]" if col["name"] in pk_cols else ""
				null = "" if col.get("nullable", True) else " NOT NULL"
				default = f"  DEFAULT {col['default']}" if col.get("default") else ""
				lines.append(f"  {col['name']:<32} {str(col['type']):<20}{pk}{null}{default}")
			if fks:
				lines.append("\nForeign keys:")
				for fk in fks:
					lines.append(f"  {fk['constrained_columns']} → "
								 f"{fk['referred_table']}.{fk['referred_columns']}")
			if idxs:
				lines.append("\nIndexes:")
				for idx in idxs:
					uniq = " UNIQUE" if idx.get("unique") else ""
					lines.append(f"  {idx['name']}{uniq}: {idx['column_names']}")
			return "\n".join(lines)
		else:
			tables = sorted(insp.get_table_names(schema="public"))
			return f"Public tables ({len(tables)}):\n" + "\n".join(f"  {t}" for t in tables)
	except Exception as exc:
		return f"Schema introspection failed: {exc}"


def alembic_status() -> str:
	"""Show current Alembic migration revision and pending heads.

	Runs `alembic current` and `alembic heads` — safe read-only commands.
	"""
	try:
		r_current = subprocess.run(
			[_PYTHON, "-m", "alembic", "current"],
			capture_output=True, text=True, timeout=15, cwd=str(PROJECT_ROOT),
		)
		r_heads = subprocess.run(
			[_PYTHON, "-m", "alembic", "heads"],
			capture_output=True, text=True, timeout=15, cwd=str(PROJECT_ROOT),
		)
		current = (r_current.stdout + r_current.stderr).strip() or "(no output)"
		heads = (r_heads.stdout + r_heads.stderr).strip() or "(no output)"
		return f"Current revision:\n{current}\n\nAvailable heads:\n{heads}"
	except subprocess.TimeoutExpired:
		return "alembic timed out after 15 s."
	except FileNotFoundError:
		return f"{_PYTHON} -m alembic not found. Install alembic in the project venv."


def get_project_deps() -> str:
	"""Show project dependencies: requirements files and installed packages.

	Reads requirements/base.txt, requirements.txt, or pyproject.toml if present,
	then falls back to `pip list` for the active interpreter.
	"""
	candidates = [
		"requirements/base.txt", "requirements.txt",
		"requirements/dev.txt", "pyproject.toml", "setup.cfg",
	]
	parts: list[str] = []
	for name in candidates:
		p = PROJECT_ROOT / name
		if p.exists():
			parts.append(f"=== {name} ===\n{p.read_text()[:3000]}")
	if parts:
		return "\n\n".join(parts)[:8000]
	# Fall back to live pip list
	result = subprocess.run(
		[_PYTHON, "-m", "pip", "list", "--format=columns"],
		capture_output=True, text=True, timeout=20,
	)
	return result.stdout[:4000] or result.stderr[:500] or "(no dependency information found)"


def read_audit_log(last_n: int = 30) -> str:
	"""Read the dev assistant write-operation audit log.

	Records every write_file, patch_file, run_tests, git_commit, git_create_branch,
	rollback_changes, and reindex_codebase call with a UTC timestamp.
	Use this to review what the AI changed and when.
	"""
	log_path = PROJECT_ROOT / _AUDIT_SUBPATH
	if not log_path.exists():
		return "(no audit log yet — no write operations have been performed in this project)"
	try:
		last_n = max(1, min(int(last_n), 200))
	except (TypeError, ValueError):
		last_n = 30
	lines = log_path.read_text().splitlines()
	return "\n".join(lines[-last_n:]) or "(audit log is empty)"


def git_commit(message: str) -> str:
	"""Stage all tracked modified files and create a git commit.

	Only stages files already tracked by git (git add -u) — never adds untracked
	files, which prevents accidentally committing .env or secrets.
	"""
	if not message or not message.strip():
		return "Commit message is required."
	r_add = subprocess.run(
		["git", "add", "-u"],
		capture_output=True, text=True, cwd=str(PROJECT_ROOT), timeout=10,
	)
	if r_add.returncode != 0:
		return f"git add -u failed: {r_add.stderr}"
	r_commit = subprocess.run(
		["git", "commit", "-m", message.strip()],
		capture_output=True, text=True, cwd=str(PROJECT_ROOT), timeout=15,
	)
	output = (r_commit.stdout + r_commit.stderr).strip()
	_audit("git_commit", message=message.strip()[:200], returncode=r_commit.returncode)
	return output[:2000] or "(no output)"


def git_create_branch(branch_name: str) -> str:
	"""Create and checkout a new git branch from the current HEAD.

	Branch name is sanitised — only alphanumerics, hyphens, underscores, and slashes.
	"""
	if not branch_name or not branch_name.strip():
		return "Branch name is required."
	safe_name = re.sub(r"[^a-zA-Z0-9._\-/]", "-", branch_name.strip())
	result = subprocess.run(
		["git", "checkout", "-b", safe_name],
		capture_output=True, text=True, cwd=str(PROJECT_ROOT), timeout=10,
	)
	output = (result.stdout + result.stderr).strip()
	_audit("git_create_branch", branch=safe_name, returncode=result.returncode)
	return output[:1000] or "(no output)"


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

def semantic_search(query: str, top_k: int = 10) -> str:
	"""Find code by meaning using vector embeddings — e.g. 'where is auth handled?'"""
	if not query or not query.strip():
		return "Error: query is required."
	if not _HAS_EMBEDDINGS:
		return "Semantic search not available — embeddings module failed to load."
	top_k = min(max(1, int(top_k)), 20)
	return _search_embeddings(query.strip(), top_k, PROJECT_ROOT)


def search_web(query: str, num_results: int = 5) -> str:
	"""Search the web via SearXNG (requires SEARXNG_URL env var)."""
	if not query or not query.strip():
		return "Error: query is required."
	searxng_url = os.environ.get("SEARXNG_URL", "").rstrip("/")
	if not searxng_url:
		return (
			"Web search unavailable: set the SEARXNG_URL environment variable "
			"(e.g. SEARXNG_URL=http://localhost:8888) to enable this tool."
		)
	num_results = min(max(1, int(num_results)), 10)
	try:
		resp = _req.get(
			f"{searxng_url}/search",
			params={"q": query.strip(), "format": "json", "categories": "general"},
			timeout=10,
		)
		resp.raise_for_status()
		data = resp.json()
	except Exception as exc:
		return f"Web search failed: {exc}"
	results = data.get("results", [])[:num_results]
	if not results:
		return f"No results found for: {query!r}"
	lines = [f"Web search: {query!r}\n"]
	for i, r in enumerate(results, 1):
		title = r.get("title", "")
		url = r.get("url", "")
		snippet = r.get("content", "")[:300]
		lines.append(f"{i}. **{title}**\n   {url}\n   {snippet}\n")
	return "\n".join(lines)


def get_ci_status(limit: int = 5) -> str:
	"""Get recent CI/CD pipeline status via the GitHub CLI (gh)."""
	limit = min(max(1, int(limit)), 20)
	try:
		r = subprocess.run(
			["gh", "run", "list", "--limit", str(limit), "--json",
			 "status,conclusion,name,headBranch,createdAt,databaseId"],
			capture_output=True, text=True, cwd=str(PROJECT_ROOT), timeout=15,
		)
	except FileNotFoundError:
		return "gh CLI not found. Install from https://cli.github.com/ to use this tool."
	if r.returncode != 0:
		stderr = r.stderr.strip()
		if "authenticat" in stderr.lower() or "not logged" in stderr.lower():
			return f"gh CLI not authenticated. Run: gh auth login\n{stderr}"
		return f"gh run list failed: {stderr}"
	try:
		runs = json.loads(r.stdout)
	except json.JSONDecodeError:
		return f"Could not parse gh output: {r.stdout[:500]}"
	if not runs:
		return "No recent CI runs found."
	icons = {"success": "[ok]", "failure": "[FAIL]", "cancelled": "[cancel]",
	         "in_progress": "[running]", "queued": "[queued]", "skipped": "[skip]"}
	lines = [f"Recent CI runs ({len(runs)}):\n"]
	for run in runs:
		conclusion = run.get("conclusion") or run.get("status", "")
		icon = icons.get(conclusion, "?")
		name = run.get("name", "")[:50]
		branch = run.get("headBranch", "")
		created = (run.get("createdAt") or "")[:16]
		run_id = run.get("databaseId", "")
		lines.append(f"  {icon} [{conclusion}] {name} ({branch}) — {created}  id:{run_id}")
	# Fetch failure logs for most recent failed run
	failed = [r for r in runs if r.get("conclusion") == "failure"]
	if failed:
		run_id = failed[0].get("databaseId", "")
		try:
			log_r = subprocess.run(
				["gh", "run", "view", str(run_id), "--log-failed"],
				capture_output=True, text=True, cwd=str(PROJECT_ROOT), timeout=20,
			)
			if log_r.returncode == 0 and log_r.stdout.strip():
				lines.append(f"\nFailed run details (id:{run_id}):")
				lines.append(log_r.stdout[:2000])
		except Exception:
			pass
	return "\n".join(lines)


def find_usages(symbol: str, context_lines: int = 2) -> str:
	"""Find all usages of a symbol (function, class, variable) across the codebase."""
	if not symbol or not symbol.strip():
		return "Error: symbol name is required."
	sym = re.sub(r"[^\w.]", "", symbol.strip())
	if not sym:
		return f"Error: invalid symbol name: {symbol!r}"
	context_lines = min(max(0, int(context_lines)), 10)
	rg_cmd = ["rg", "--type", "py", "-n", f"--context={context_lines}",
	          "--word-regexp", "--fixed-strings", sym, str(PROJECT_ROOT)]
	grep_cmd = ["grep", "-rn", "--include=*.py", "-w", "-F",
	            f"--context={context_lines}", sym, str(PROJECT_ROOT)]
	try:
		result = subprocess.run(rg_cmd, capture_output=True, text=True, timeout=15)
	except FileNotFoundError:
		result = subprocess.run(grep_cmd, capture_output=True, text=True, timeout=15)
	output = result.stdout.strip()
	if not output:
		return f"No usages found for: {sym!r}"
	lines = output.split("\n")
	total_lines = len(lines)
	if total_lines > 150:
		lines = lines[:150]
		lines.append(f"... (truncated — {total_lines} total lines)")
	return f"Usages of '{sym}':\n\n" + "\n".join(lines)


def get_test_coverage(path: str = "") -> str:
	"""Run pytest with coverage and return the missing-lines report."""
	test_path = "tests/ci"
	if path:
		try:
			resolved = safe_path(path.strip())
			test_path = str(resolved.relative_to(PROJECT_ROOT))
		except PermissionError as exc:
			return str(exc)
	try:
		result = subprocess.run(
			[_PYTHON, "-m", "pytest", test_path,
			 "--cov=pgappforge", "--cov-report=term-missing",
			 "--tb=no", "-q", "--no-header"],
			capture_output=True, text=True, cwd=str(PROJECT_ROOT), timeout=120,
		)
	except Exception as exc:
		return f"Coverage run failed: {exc}"
	output = (result.stdout + result.stderr).strip()
	return output[:8000] or "(no output from coverage run)"


def rollback_changes(confirm: str = "") -> str:
	"""Stash all uncommitted tracked-file changes (recoverable via git stash pop).

	Requires confirm='YES' when changes exist to prevent accidental data loss.
	"""
	status_r = subprocess.run(
		["git", "status", "--short"],
		capture_output=True, text=True, cwd=str(PROJECT_ROOT),
	)
	status = status_r.stdout.strip()
	if not status:
		return "Working tree is clean — nothing to roll back."
	if confirm != "YES":
		return (
			f"rollback_changes requires confirm='YES' to proceed.\n"
			f"Uncommitted changes:\n{status}\n\n"
			f"Changes will be stashed (recoverable via `git stash pop`)."
		)
	result = subprocess.run(
		["git", "stash", "push", "--message",
		 f"dev_assistant rollback {datetime.datetime.now(datetime.timezone.utc).isoformat()}"],
		capture_output=True, text=True, cwd=str(PROJECT_ROOT), timeout=10,
	)
	if result.returncode != 0:
		return f"Rollback failed: {result.stderr.strip()}"
	_audit("rollback_changes", reverted=status[:500], method="stash")
	return f"Changes stashed (recoverable via `git stash pop`). Was:\n{status}"


def reindex_codebase() -> str:
	"""Re-index Python source files into the semantic search embedding store.

	Runs synchronously. Use after significant file changes when semantic_search
	results are stale. Requires pgvector + Ollama nomic-embed-text model.
	"""
	if not _HAS_EMBEDDINGS:
		return "Semantic search not available — embeddings module failed to load."
	try:
		if not _ensure_schema():
			return "Reindex failed: could not verify embedding schema (check pgvector + DB config)."
		stats = _index_codebase(PROJECT_ROOT)
		if stats.get("status") == "already_running":
			return "Indexing already in progress (background indexer running). Try again in a moment."
		if stats.get("status") == "no_engine":
			return "Reindex failed: SQLALCHEMY_DATABASE_URI not configured."
		if stats.get("status") == "error":
			return f"Reindex error: {stats.get('error', 'unknown')}"
		_audit("reindex_codebase", files=stats.get("files", 0),
		       chunks=stats.get("chunks", 0), errors=stats.get("errors", 0))
		return (
			f"Reindex complete: {stats.get('files', 0)} files, "
			f"{stats.get('chunks', 0)} chunks, "
			f"{stats.get('skipped', 0)} skipped (unchanged), "
			f"{stats.get('errors', 0)} errors."
		)
	except Exception as exc:
		return f"Reindex failed: {exc}"


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
	{
		"type": "function",
		"function": {
			"name": "patch_file",
			"description": (
				"Make a targeted replacement inside a file WITHOUT rewriting the whole thing. "
				"Prefer this over write_file whenever you only need to change specific lines. "
				"Fails clearly if old_str appears zero times or more than once."
			),
			"parameters": {
				"type": "object",
				"properties": {
					"path": {"type": "string", "description": "Relative path from project root"},
					"old_str": {"type": "string", "description": "Exact text to find (whitespace-sensitive)"},
					"new_str": {"type": "string", "description": "Replacement text"},
				},
				"required": ["path", "old_str", "new_str"],
			},
		},
	},
	{
		"type": "function",
		"function": {
			"name": "get_db_schema",
			"description": (
				"Introspect the live PostgreSQL database schema. "
				"With no argument: list all public tables. "
				"With table_name: show columns, types, nullability, PKs, FKs, and indexes."
			),
			"parameters": {
				"type": "object",
				"properties": {
					"table_name": {"type": "string", "description": "Table name to inspect (empty = list all tables)"},
				},
				"required": [],
			},
		},
	},
	{
		"type": "function",
		"function": {
			"name": "alembic_status",
			"description": "Show the current Alembic migration revision and available heads.",
			"parameters": {"type": "object", "properties": {}, "required": []},
		},
	},
	{
		"type": "function",
		"function": {
			"name": "get_project_deps",
			"description": "Show project dependencies from requirements files or pip list.",
			"parameters": {"type": "object", "properties": {}, "required": []},
		},
	},
	{
		"type": "function",
		"function": {
			"name": "read_audit_log",
			"description": (
				"Read the dev assistant write-operation audit log. "
				"Records every write_file, patch_file, run_tests, git_commit, git_create_branch, "
				"rollback_changes, and reindex_codebase call with a UTC timestamp. "
				"Use to review what the AI changed and when."
			),
			"parameters": {
				"type": "object",
				"properties": {
					"last_n": {"type": "integer", "description": "Number of records to show (default 30, max 200)"},
				},
				"required": [],
			},
		},
	},
	{
		"type": "function",
		"function": {
			"name": "git_commit",
			"description": (
				"Stage all tracked modified files (git add -u) and create a git commit. "
				"Does NOT add untracked files — safe against accidentally committing .env or secrets."
			),
			"parameters": {
				"type": "object",
				"properties": {
					"message": {"type": "string", "description": "Commit message"},
				},
				"required": ["message"],
			},
		},
	},
	{
		"type": "function",
		"function": {
			"name": "git_create_branch",
			"description": "Create and checkout a new git branch from the current HEAD.",
			"parameters": {
				"type": "object",
				"properties": {
					"branch_name": {"type": "string", "description": "Branch name (sanitised to safe characters)"},
				},
				"required": ["branch_name"],
			},
		},
	},
	{
		"type": "function",
		"function": {
			"name": "semantic_search",
			"description": (
				"Search the codebase by MEANING using vector embeddings — finds code even when "
				"you don't know the exact function name. E.g. 'where is JWT auth handled?' or "
				"'find the payment processing logic'. Requires pgvector + Ollama nomic-embed-text."
			),
			"parameters": {
				"type": "object",
				"properties": {
					"query": {"type": "string", "description": "Natural language description of what to find"},
					"top_k": {"type": "integer", "description": "Number of results to return (default 10, max 20)"},
				},
				"required": ["query"],
			},
		},
	},
	{
		"type": "function",
		"function": {
			"name": "search_web",
			"description": "Search the web via SearXNG for documentation, error messages, or library info. Requires SEARXNG_URL env var.",
			"parameters": {
				"type": "object",
				"properties": {
					"query": {"type": "string", "description": "Search query"},
					"num_results": {"type": "integer", "description": "Number of results (default 5, max 10)"},
				},
				"required": ["query"],
			},
		},
	},
	{
		"type": "function",
		"function": {
			"name": "get_ci_status",
			"description": "Get recent GitHub Actions CI/CD pipeline status via the gh CLI. Shows pass/fail and failure logs.",
			"parameters": {
				"type": "object",
				"properties": {
					"limit": {"type": "integer", "description": "Number of recent runs to show (default 5, max 20)"},
				},
				"required": [],
			},
		},
	},
	{
		"type": "function",
		"function": {
			"name": "find_usages",
			"description": "Find all usages of a symbol (function name, class name, variable) across the Python codebase.",
			"parameters": {
				"type": "object",
				"properties": {
					"symbol": {"type": "string", "description": "Symbol name to search for"},
					"context_lines": {"type": "integer", "description": "Lines of context around each match (default 2, max 10)"},
				},
				"required": ["symbol"],
			},
		},
	},
	{
		"type": "function",
		"function": {
			"name": "get_test_coverage",
			"description": "Run pytest with coverage and show which lines are not covered.",
			"parameters": {
				"type": "object",
				"properties": {
					"path": {"type": "string", "description": "Test path or file (empty = all CI tests)"},
				},
				"required": [],
			},
		},
	},
	{
		"type": "function",
		"function": {
			"name": "rollback_changes",
			"description": (
				"Stash all uncommitted tracked-file changes (recoverable via `git stash pop`). "
				"Pass confirm='YES' to proceed — required when changes exist to prevent accidents."
			),
			"parameters": {
				"type": "object",
				"properties": {
					"confirm": {
						"type": "string",
						"description": "Must be 'YES' to actually stash changes. Omit to preview what would be stashed.",
					},
				},
				"required": [],
			},
		},
	},
	{
		"type": "function",
		"function": {
			"name": "reindex_codebase",
			"description": (
				"Re-index Python source files into the semantic search embedding store. "
				"Run after significant file changes when semantic_search results are stale. "
				"Requires pgvector + Ollama nomic-embed-text pulled."
			),
			"parameters": {"type": "object", "properties": {}, "required": []},
		},
	},
]

# Read-only tool names — available to all roles
READ_TOOL_NAMES: frozenset[str] = frozenset({
	"read_file", "list_directory", "search_code",
	"get_git_diff", "get_git_log", "get_git_status",
	"run_command", "check_ollama_models", "read_log", "get_env_vars",
	"get_route_list", "get_db_schema", "alembic_status",
	"get_project_deps", "read_audit_log",
	"semantic_search", "search_web", "get_ci_status", "find_usages", "get_test_coverage",
})

# Write tool names — Developer + Admin only
WRITE_TOOL_NAMES: frozenset[str] = frozenset({
	"write_file", "patch_file", "run_tests",
	"git_commit", "git_create_branch", "rollback_changes", "reindex_codebase",
})

# ---------------------------------------------------------------------------
# Registry builder
# ---------------------------------------------------------------------------

_TOOL_FN_MAP: dict[str, Any] = {
	"read_file": read_file,
	"write_file": write_file,
	"patch_file": patch_file,
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
	"get_db_schema": get_db_schema,
	"alembic_status": alembic_status,
	"get_project_deps": get_project_deps,
	"read_audit_log": read_audit_log,
	"git_commit": git_commit,
	"git_create_branch": git_create_branch,
	"semantic_search": semantic_search,
	"search_web": search_web,
	"get_ci_status": get_ci_status,
	"find_usages": find_usages,
	"get_test_coverage": get_test_coverage,
	"rollback_changes": rollback_changes,
	"reindex_codebase": reindex_codebase,
}


# Role names that unlock write tools. Mirrors views._WRITE_ROLES; both read the same env var.
WRITE_ROLES: frozenset[str] = frozenset(
	r.strip()
	for r in os.environ.get("DEV_ASSISTANT_WRITE_ROLES", "Admin,Developer").split(",")
	if r.strip()
)


def build_tool_registry(user_roles: set[str]) -> tuple[list[dict], dict[str, Any]]:
	"""Return (tool_schemas, tool_fn_registry) filtered by user roles.

	Args:
		user_roles: set of role name strings (e.g. {'Admin', 'Developer'})

	Returns:
		schemas: list of tool JSON Schema dicts to pass to Ollama
		registry: name → callable for tool execution
	"""
	has_write = bool(user_roles & WRITE_ROLES)
	allowed_names = READ_TOOL_NAMES | (WRITE_TOOL_NAMES if has_write else frozenset())
	schemas = [s for s in TOOL_SCHEMAS if s["function"]["name"] in allowed_names]
	registry = {name: fn for name, fn in _TOOL_FN_MAP.items() if name in allowed_names}
	return schemas, registry


__all__ = [
	"safe_path", "PROJECT_ROOT",
	"read_file", "write_file", "patch_file", "list_directory", "search_code",
	"get_git_diff", "get_git_log", "get_git_status",
	"run_tests", "run_command", "check_ollama_models", "read_log", "get_env_vars",
	"get_route_list", "get_db_schema", "alembic_status", "get_project_deps",
	"read_audit_log", "git_commit", "git_create_branch",
	"semantic_search", "search_web", "get_ci_status", "find_usages",
	"get_test_coverage", "rollback_changes", "reindex_codebase",
	"TOOL_SCHEMAS", "READ_TOOL_NAMES", "WRITE_TOOL_NAMES", "WRITE_ROLES",
	"build_tool_registry",
	"_AUDIT_SUBPATH",
]
