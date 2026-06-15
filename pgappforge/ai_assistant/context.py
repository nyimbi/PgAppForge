"""
pgappforge/ai_assistant/context.py

System prompt builder and repository map generator for the dev assistant.

Approach: static system prompt (architecture + constraints) + dynamic repo map
(AST-extracted class/function signatures for top-level Python files).
No full-codebase injection — the agent uses read_file/search_code on demand.
"""
from __future__ import annotations

import ast
import logging
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Repo map
# ---------------------------------------------------------------------------

_SKIP_DIRS = frozenset({
	".venv", ".git", "__pycache__", ".claude", "node_modules",
	"migrations", ".mypy_cache", ".pytest_cache", "dist", "build",
	"htmlcov", ".tox",
})

_MAX_FILES = 80   # cap to avoid blowing the context window
_MAX_METHODS_PER_CLASS = 8


def generate_repo_map(root: Path, max_files: int = _MAX_FILES) -> str:
	"""Build a compact tree-of-signatures map from Python source files.

	Extracts top-level class names (with bases) and module-level functions.
	Method names inside classes are included up to _MAX_METHODS_PER_CLASS.

	Returns a markdown-formatted string suitable for embedding in a system prompt.
	"""
	lines: list[str] = []
	count = 0

	for filepath in sorted(root.rglob("*.py")):
		if count >= max_files:
			lines.append(f"\n... ({count}+ files; use list_directory/search_code for more)")
			break

		rel = filepath.relative_to(root)
		# Skip hidden dirs and noise dirs
		if any(part in _SKIP_DIRS or part.startswith(".") for part in rel.parts):
			continue

		try:
			source = filepath.read_text(errors="replace")
			tree = ast.parse(source)
		except (SyntaxError, OSError):
			continue

		file_lines: list[str] = []
		for node in ast.iter_child_nodes(tree):
			if isinstance(node, ast.ClassDef):
				bases = []
				for b in node.bases:
					if isinstance(b, ast.Name):
						bases.append(b.id)
					elif isinstance(b, ast.Attribute):
						bases.append(f"{b.attr}")
				base_str = f"({', '.join(bases)})" if bases else ""
				file_lines.append(f"  class {node.name}{base_str}")
				# Top methods
				methods = [
					n.name for n in ast.iter_child_nodes(node)
					if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
				][:_MAX_METHODS_PER_CLASS]
				for m in methods:
					file_lines.append(f"    def {m}(...)")
				if len(methods) == _MAX_METHODS_PER_CLASS:
					file_lines.append("    ...")
			elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
				file_lines.append(f"  def {node.name}(...)")

		if file_lines:
			lines.append(f"\n### {rel}")
			lines.extend(file_lines)
			count += 1

	return "\n".join(lines)


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_BASE_SYSTEM_PROMPT = """\
You are a senior developer assistant embedded in PgAppForge — a Flask-AppBuilder (FAB) based
rapid-application-development framework for PostgreSQL-backed web applications.

You can read files, search code, run tests, inspect git history, and write files.
Use your tools proactively: do not guess file contents — read them first.

## Project layout
- pgappforge/           — main package
  - base.py             — AppBuilder orchestrator (views, security, menus)
  - baseviews.py        — BaseView, ModelView, RestCRUDView base classes
  - views.py            — ModelView, MasterDetailView, CompactCRUDMixin
  - api/                — ModelRestApi, OpenAPI/Swagger integration
  - security/           — RBAC: OAuth, LDAP, DB auth (sqla/ and mongoengine/)
  - models/             — SQLAlchemy 2.x patterns, filters, mixins
  - plugins/            — rules engine, workflow engine, ERP modules, chatbot
  - events/             — EventRouter (@on_event), EventWorker (durable dispatch)
  - workflow/           — YAML workflow engine, triggers, parallel branches
  - analytics/          — MetricRegistry, DerivedMetric
  - ai_assistant/       — this module (Ollama-backed dev assistant)
- tests/ci/             — CI test suite
- docs/                 — architecture docs and research

## Code standards (MUST follow)
- Python with TABS (not spaces)
- PostgreSQL only — no MySQL/SQLite workarounds
- Pydantic v2: ConfigDict(extra='forbid', validate_by_name=True)
- SQLAlchemy 2.x: use session.execute(select()) patterns
- Flask-SQLAlchemy 3.1.1+
- UUID7 via uuid6 package: from uuid6 import uuid7; str(uuid7())
- Modern typing: str | None, list[str], dict[str, Any]
- Async throughout where appropriate
- No comments unless the WHY is non-obvious

## Test command
  .venv/bin/python -m pytest tests/ci -q --tb=short

## Your workflow
1. Use read_file / search_code to understand code before modifying it
2. Write tests before implementing new features (TDD)
3. After changes, run run_tests to verify nothing broke
4. Explain what you changed and why after completing a task
"""


def build_system_prompt(
	root: Path,
	app_name: str = "PgAppForge",
	include_repo_map: bool = True,
	extra_context: str = "",
) -> str:
	"""Assemble the full system prompt for the dev assistant.

	Args:
		root:             Project root path.
		app_name:         Application name shown in the prompt header.
		include_repo_map: If True, append an AST-generated repo map (~4K tokens).
		extra_context:    Optional extra instructions (e.g. per-session focus area).

	Returns:
		Full system prompt string.
	"""
	prompt = _BASE_SYSTEM_PROMPT
	if app_name != "PgAppForge":
		prompt = prompt.replace("PgAppForge", app_name)

	if include_repo_map:
		try:
			repo_map = generate_repo_map(root)
			prompt += f"\n\n## Codebase structure (auto-generated)\n{repo_map}"
		except Exception as exc:
			log.warning("dev_assistant: repo map generation failed: %s", exc)

	if extra_context:
		prompt += f"\n\n## Session context\n{extra_context}"

	return prompt


__all__ = ["generate_repo_map", "build_system_prompt"]
