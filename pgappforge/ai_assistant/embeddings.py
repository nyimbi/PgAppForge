"""
pgappforge/ai_assistant/embeddings.py

Code embedding indexer for semantic search.

Uses Ollama /api/embeddings + pgvector to index Python source files
and answer semantic queries ("where is authentication handled?").

Gracefully no-ops when any of the following are unavailable:
  - SQLALCHEMY_DATABASE_URI not configured
  - pgvector extension not installed in PostgreSQL
  - Ollama not running or embed model not pulled
"""
from __future__ import annotations

import ast
import logging
import os
import threading
from pathlib import Path
from typing import Any

import requests as _req

from ._db import get_engine

log = logging.getLogger(__name__)

_EMBED_MODEL: str = os.environ.get("DEV_ASSISTANT_EMBED_MODEL", "nomic-embed-text")
_EMBED_DIM: int = int(os.environ.get("DEV_ASSISTANT_EMBED_DIM", "768"))
_OLLAMA_URL: str = os.environ.get("OLLAMA_URL", "http://localhost:11434")
_MAX_CHUNK_CHARS = 2_000
_SKIP_DIRS = frozenset({
	".venv", ".git", "__pycache__", ".claude", "node_modules",
	"migrations", ".mypy_cache", ".pytest_cache", "dist", "build", "htmlcov", ".tox",
})

_TABLE = "dev_assistant_code_embedding"
_INDEX_LOCK = threading.Lock()  # acquire(blocking=False) acts as the "running" flag


# ---------------------------------------------------------------------------
# Embedding API
# ---------------------------------------------------------------------------

def get_embedding(text: str) -> list[float] | None:
	"""Call Ollama /api/embeddings. Returns None on any failure."""
	try:
		resp = _req.post(
			f"{_OLLAMA_URL}/api/embeddings",
			json={"model": _EMBED_MODEL, "prompt": text},
			timeout=30,
		)
		resp.raise_for_status()
		return resp.json().get("embedding")
	except Exception as exc:
		log.debug("embeddings: get_embedding failed: %s", exc)
		return None


# ---------------------------------------------------------------------------
# Python file chunking (AST-guided, by top-level function/class nodes)
# ---------------------------------------------------------------------------

def chunk_python_file(filepath: Path) -> list[str]:
	"""Split a Python file into function/class-level chunks for embedding.

	Falls back to fixed-size character chunks on parse failure.
	Each chunk is prefixed with filename:lineno for context.
	"""
	try:
		source = filepath.read_text(errors="replace")
	except OSError:
		return []

	try:
		tree = ast.parse(source)
	except SyntaxError:
		chunks = []
		for i in range(0, len(source), _MAX_CHUNK_CHARS):
			c = source[i:i + _MAX_CHUNK_CHARS].strip()
			if c:
				chunks.append(c)
		return chunks

	lines = source.splitlines(keepends=True)
	chunks: list[str] = []

	for node in ast.iter_child_nodes(tree):
		if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
			continue
		# Include decorators if present (node.lineno points at def/class, not the first decorator)
		if getattr(node, "decorator_list", None):
			start = min(d.lineno for d in node.decorator_list) - 1
		else:
			start = node.lineno - 1
		end = getattr(node, "end_lineno", start + 30)
		chunk = "".join(lines[start:end]).strip()
		if chunk:
			chunks.append(f"# {filepath.name}:{start + 1}\n{chunk[:_MAX_CHUNK_CHARS]}")

	if not chunks:
		chunk = source.strip()[:_MAX_CHUNK_CHARS]
		if chunk:
			chunks.append(chunk)

	return chunks


# ---------------------------------------------------------------------------
# Schema setup
# ---------------------------------------------------------------------------

def ensure_schema() -> bool:
	"""Create pgvector extension + embedding table if not present. Returns True on success."""
	from sqlalchemy import text as sa_text
	engine = get_engine()
	if engine is None:
		return False
	try:
		with engine.connect() as conn:
			conn.execute(sa_text("CREATE EXTENSION IF NOT EXISTS vector"))
			conn.execute(sa_text(f"""
				CREATE TABLE IF NOT EXISTS {_TABLE} (
					id          SERIAL PRIMARY KEY,
					file_path   TEXT NOT NULL,
					chunk_index INTEGER NOT NULL,
					content     TEXT NOT NULL,
					embedding   vector({_EMBED_DIM}),
					indexed_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
					file_mtime  FLOAT NOT NULL,
					CONSTRAINT {_TABLE}_uc UNIQUE (file_path, chunk_index)
				)
			"""))
			conn.execute(sa_text(
				f"CREATE INDEX IF NOT EXISTS {_TABLE}_ivfflat "
				f"ON {_TABLE} USING ivfflat (embedding vector_cosine_ops) WITH (lists = 50)"
			))
			conn.commit()
		return True
	except Exception as exc:
		log.warning("embeddings: schema setup failed (pgvector not installed?): %s", exc)
		return False


# ---------------------------------------------------------------------------
# Indexer
# ---------------------------------------------------------------------------

def _emb_literal(emb: list) -> str | None:
	"""Format a float list as a pgvector literal. Returns None on invalid input."""
	try:
		floats = [float(v) for v in emb]
	except (TypeError, ValueError):
		return None
	if not floats or any(v != v or v in (float("inf"), float("-inf")) for v in floats):
		return None
	return "[" + ",".join(repr(v) for v in floats) + "]"


def index_codebase(root: Path) -> dict[str, Any]:
	"""Walk Python files, embed changed ones, upsert to DB. Returns stats dict."""
	from sqlalchemy import text as sa_text

	if not _INDEX_LOCK.acquire(blocking=False):
		return {"status": "already_running"}
	try:
		engine = get_engine()
		if engine is None:
			return {"status": "no_engine"}

		with engine.connect() as conn:
			rows = conn.execute(sa_text(
				f"SELECT file_path, MAX(file_mtime) FROM {_TABLE} GROUP BY file_path"
			)).fetchall()
		known: dict[str, float] = {r[0]: r[1] for r in rows}

		stats: dict[str, int] = {"files": 0, "chunks": 0, "skipped": 0, "errors": 0}

		for filepath in sorted(root.rglob("*.py")):
			rel = filepath.relative_to(root)
			if any(part in _SKIP_DIRS or part.startswith(".") for part in rel.parts):
				continue
			rel_str = str(rel)
			try:
				mtime = filepath.stat().st_mtime
			except OSError:
				continue
			if known.get(rel_str) == mtime:
				stats["skipped"] += 1
				continue

			chunks = chunk_python_file(filepath)
			# Batch all chunks for one file in a single transaction
			with engine.begin() as conn:
				for chunk_idx, chunk in enumerate(chunks):
					emb = get_embedding(chunk)
					if emb is None:
						stats["errors"] += 1
						continue
					lit = _emb_literal(emb)
					if lit is None:
						stats["errors"] += 1
						continue
					conn.execute(sa_text(f"""
						INSERT INTO {_TABLE}
							(file_path, chunk_index, content, embedding, file_mtime)
						VALUES (:fp, :ci, :content, :emb::vector, :mtime)
						ON CONFLICT (file_path, chunk_index) DO UPDATE SET
							content    = EXCLUDED.content,
							embedding  = EXCLUDED.embedding,
							file_mtime = EXCLUDED.file_mtime,
							indexed_at = NOW()
					"""), {
						"fp": rel_str, "ci": chunk_idx,
						"content": chunk, "emb": lit, "mtime": mtime,
					})
					stats["chunks"] += 1
			stats["files"] += 1

		return stats

	except Exception as exc:
		log.warning("embeddings: indexing error: %s", exc)
		return {"status": "error", "error": str(exc)}
	finally:
		_INDEX_LOCK.release()


def start_background_index(root: Path) -> None:
	"""Start incremental code indexing in a daemon thread. No-ops if DB/pgvector unavailable."""
	if get_engine() is None:
		return

	def _run():
		if not ensure_schema():
			return
		stats = index_codebase(root)
		log.info(
			"embeddings: index complete — %s files, %s chunks (skipped %s, errors %s)",
			stats.get("files"), stats.get("chunks"),
			stats.get("skipped"), stats.get("errors"),
		)

	t = threading.Thread(target=_run, daemon=True, name="da_embedder")
	t.start()


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

def search_embeddings(query: str, top_k: int, root: Path) -> str:
	"""Execute a semantic similarity search. Returns formatted results."""
	from sqlalchemy import text as sa_text

	engine = get_engine()
	if engine is None:
		return "Semantic search unavailable: SQLALCHEMY_DATABASE_URI not configured."

	emb = get_embedding(query)
	if emb is None:
		return (
			f"Semantic search unavailable: could not get embedding from Ollama at {_OLLAMA_URL}. "
			f"Ensure Ollama is running and run: ollama pull {_EMBED_MODEL}"
		)

	emb_literal = _emb_literal(emb)
	if emb_literal is None:
		return "Semantic search unavailable: invalid embedding returned from Ollama."
	try:
		with engine.connect() as conn:
			conn.execute(sa_text("SET LOCAL ivfflat.probes = 10"))
			rows = conn.execute(sa_text(f"""
				SELECT file_path, content, 1 - dist AS similarity
				FROM (
					SELECT file_path, content,
					       embedding <=> :emb::vector AS dist
					FROM {_TABLE}
					ORDER BY embedding <=> :emb::vector
					LIMIT :k
				) sub
			"""), {"emb": emb_literal, "k": top_k}).fetchall()
	except Exception as exc:
		err = str(exc)
		if "does not exist" in err:
			return (
				"Semantic search index is empty or not yet built. "
				"The indexer runs at startup — wait a moment and retry. "
				"Requires: pgvector installed + Ollama running + "
				f"model '{_EMBED_MODEL}' pulled (ollama pull {_EMBED_MODEL})."
			)
		return f"Semantic search query failed: {exc}"

	if not rows:
		return (
			f"No results for: {query!r}\n"
			"Index may be empty. Check pgvector, Ollama, and "
			f"ensure '{_EMBED_MODEL}' is pulled (ollama pull {_EMBED_MODEL})."
		)

	out = [f"Semantic search results for: {query!r}\n"]
	for fp, content, sim in rows:
		out.append(f"### {fp}  (similarity: {sim:.3f})")
		out.append(f"```python\n{content[:600].rstrip()}\n```")
		out.append("")
	return "\n".join(out)


__all__ = [
	"ensure_schema", "start_background_index", "index_codebase", "search_embeddings",
	"get_embedding", "chunk_python_file",
]
