"""
pgappforge/plugins/erp/platform/nl_analytics/services.py

NLAnalyticsService — natural language → SQL analytics.

Architecture
------------
1. ``get_schema_context()``   — introspect live DB + semantic layer → prompt context string
2. ``query()``                — NL question → cache check → LLM SQL → validate → execute → cache
3. ``_generate_sql()``        — LLM prompt via existing LLMClient (LiteLLM proxy)
4. ``_is_safe_sql()``         — strict SELECT-only whitelist; blocks all DML/DDL
5. ``_check_cache()``         — SHA-256 hash lookup in pgaf_nl_query_cache (1 h TTL)
6. ``_cache_result()``        — upsert on query_hash

Cache table DDL
---------------
See ``create_cache_table_ddl()`` below — call this once at migration time or
call ``ensure_cache_table()`` at plugin initialisation to auto-create it.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import Any

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# DDL helpers
# ---------------------------------------------------------------------------

def create_cache_table_ddl() -> str:
	"""Return the DDL string for the NL query cache table.

	Call this once (e.g. in an Alembic migration) or let ``ensure_cache_table``
	execute it automatically at plugin init time.

	Design notes:
	  - ``query_hash`` is a 16-char hex prefix of SHA-256(normalised question)
	    used as the dedup key.
	  - ``cached_at`` drives the 1-hour TTL in the cache lookup query.
	  - Full question text stored for observability / re-training data.
	"""
	return """
CREATE TABLE IF NOT EXISTS pgaf_nl_query_cache (
	id            TEXT        NOT NULL PRIMARY KEY,
	query_hash    TEXT        NOT NULL,
	question      TEXT        NOT NULL,
	cached_sql    TEXT        NOT NULL,
	cached_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
	tenant_id     TEXT        NOT NULL DEFAULT 'default',
	hit_count     INTEGER     NOT NULL DEFAULT 0,
	CONSTRAINT uq_nl_query_hash_tenant UNIQUE (query_hash, tenant_id)
);
CREATE INDEX IF NOT EXISTS ix_pgaf_nl_cache_hash ON pgaf_nl_query_cache (query_hash, tenant_id);
CREATE INDEX IF NOT EXISTS ix_pgaf_nl_cache_at   ON pgaf_nl_query_cache (cached_at);
""".strip()


def ensure_cache_table(session) -> None:
	"""Create pgaf_nl_query_cache if it does not already exist.

	Safe to call repeatedly — uses CREATE TABLE IF NOT EXISTS.
	Silently swallows errors (e.g. no DDL permissions) so the plugin
	degrades gracefully to a no-cache mode.
	"""
	try:
		import sqlalchemy as sa
		ddl = create_cache_table_ddl()
		for stmt in ddl.split(";"):
			stmt = stmt.strip()
			if stmt:
				session.execute(sa.text(stmt + ";"))
		session.commit()
		log.info("NLAnalytics: pgaf_nl_query_cache ready")
	except Exception as exc:
		log.debug("NLAnalytics: cache table ensure skipped — %s", exc)
		try:
			session.rollback()
		except Exception:
			pass


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class NLAnalyticsService:
	"""Natural language to SQL analytics service.

	Uses LLM + schema context to convert plain English questions into
	PostgreSQL SELECT queries.  Results are cached via a simple hash
	cache (pgaf_nl_query_cache) to avoid repeated LLM calls for identical
	questions.

	Instantiate once per request (or as a singleton) — ``_schema_context``
	is an instance-level cache so it survives across calls within the same
	process lifetime.

	Config keys (read from Flask app config):
		NL_ANALYTICS_ENABLED (bool, default True)
		LLM_MODEL            (str,  default "gpt-4o")  — passed to LiteLLM
		NL_ANALYTICS_MAX_ROWS (int, default 500)

	Example::

		svc = NLAnalyticsService()
		result = svc.query("How many active SACCO members do we have?", session)
		# → {"sql": "SELECT COUNT(*) ...", "results": [...], "row_count": 1, ...}
	"""

	_schema_context: str | None = None

	# ------------------------------------------------------------------
	# Schema context
	# ------------------------------------------------------------------

	def get_schema_context(self, session) -> str:
		"""Build schema context string from live SQLAlchemy introspection
		plus any registered SemanticRegistry entries.

		Result is cached on the instance for the process lifetime.
		"""
		if self._schema_context:
			return self._schema_context

		lines: list[str] = ["# PgAppForge Database Schema\n"]

		# ── Live table introspection ─────────────────────────────────
		try:
			from sqlalchemy import inspect as sa_inspect
			from flask import current_app
			engine = current_app.extensions.get("sqlalchemy").engine
			inspector = sa_inspect(engine)

			SKIP_TABLES = {"alembic_version", "pgaf_audit_log", "pgaf_nl_query_cache"}
			SKIP_PREFIXES = ("ab_",)

			for table_name in sorted(inspector.get_table_names()):
				if table_name in SKIP_TABLES:
					continue
				if any(table_name.startswith(p) for p in SKIP_PREFIXES):
					continue
				try:
					cols = inspector.get_columns(table_name)
					col_defs = ", ".join(
						f"{c['name']} ({str(c['type'])})"
						for c in cols[:20]
					)
					lines.append(f"Table {table_name}: {col_defs}")
				except Exception:
					pass
		except Exception as exc:
			log.debug("NLAnalytics: schema introspection skipped — %s", exc)

		# ── Semantic layer context ───────────────────────────────────
		try:
			from pgappforge.semantic import SemanticRegistry
			reg = SemanticRegistry.get()
			ctx = reg.build_llm_context()
			if ctx:
				lines.append("\n" + ctx)
		except Exception as exc:
			log.debug("NLAnalytics: semantic layer unavailable — %s", exc)

		# ── Fallback inline semantic terms ───────────────────────────
		lines.append("\n# Common Business Terms")
		for term, defn in self._builtin_semantic().items():
			lines.append(f"'{term}' means: {defn}")

		self._schema_context = "\n".join(lines)
		return self._schema_context

	@staticmethod
	def _builtin_semantic() -> dict[str, str]:
		return {
			"active members":  "members with status = 'ACTIVE'",
			"total loan book": "SUM of outstanding_balance_cents / 100 in KES",
			"overdue loans":   "loans where days_past_due > 30",
			"monthly revenue": "SUM of amount_cents / 100 WHERE period = current month",
			"active policies": "insurance policies where status = 'ACTIVE'",
			"par30":           "Portfolio at Risk 30: % of loan book with days_past_due >= 30",
		}

	# ------------------------------------------------------------------
	# Main entry point
	# ------------------------------------------------------------------

	def query(
		self,
		question: str,
		session,
		*,
		tenant_id: str = "default",
	) -> dict[str, Any]:
		"""Convert a natural language question to SQL and execute it.

		Args:
			question:   Plain-English analytics question.
			session:    SQLAlchemy session bound to the target database.
			tenant_id:  Tenant identifier used for cache scoping.

		Returns a dict with keys::

			sql        str | None  — the generated (or cached) SQL
			results    list[dict]  — up to NL_ANALYTICS_MAX_ROWS rows
			columns    list[str]   — column names in result order
			row_count  int         — len(results)
			error      str | None  — error message if something went wrong
			cached     bool        — True when result came from cache
		"""
		# ── Cache check ──────────────────────────────────────────────
		cached = self._check_cache(question, session, tenant_id=tenant_id)
		if cached:
			return {**cached, "cached": True}

		# ── LLM SQL generation ───────────────────────────────────────
		try:
			sql = self._generate_sql(question, session)
		except Exception as exc:
			log.warning("NLAnalytics: SQL generation failed — %s", exc)
			return {
				"sql": None,
				"error": f"SQL generation failed: {exc}",
				"results": [],
				"columns": [],
				"row_count": 0,
				"cached": False,
			}

		# ── Safety validation ────────────────────────────────────────
		if not self._is_safe_sql(sql):
			return {
				"sql": sql,
				"error": "Only SELECT queries are permitted.",
				"results": [],
				"columns": [],
				"row_count": 0,
				"cached": False,
			}

		# ── Execute ───────────────────────────────────────────────────
		try:
			max_rows = self._config_int("NL_ANALYTICS_MAX_ROWS", 500)
			import sqlalchemy as sa
			result_proxy = session.execute(sa.text(sql))
			columns = list(result_proxy.keys())
			raw_rows = result_proxy.fetchmany(max_rows)
			rows = [dict(zip(columns, row)) for row in raw_rows]

			# Serialise non-JSON-safe types
			rows = _jsonify_rows(rows)

			self._cache_result(question, sql, session, tenant_id=tenant_id)

			return {
				"sql": sql,
				"results": rows,
				"columns": columns,
				"row_count": len(rows),
				"error": None,
				"cached": False,
			}
		except Exception as exc:
			log.warning("NLAnalytics: query execution failed — %s", exc)
			return {
				"sql": sql,
				"error": f"Query execution failed: {exc}",
				"results": [],
				"columns": [],
				"row_count": 0,
				"cached": False,
			}

	# ------------------------------------------------------------------
	# SQL generation
	# ------------------------------------------------------------------

	def _generate_sql(self, question: str, session) -> str:
		"""Send question + schema context to LLM; return cleaned SQL string."""
		from pgappforge.plugins.erp.platform.nlp.client import LLMClient
		client = LLMClient()
		schema_ctx = self.get_schema_context(session)

		prompt = (
			"You are a PostgreSQL expert for an ERP/fintech system. "
			"Generate a valid PostgreSQL SELECT query for the following question.\n\n"
			f"Schema (truncated to 3000 chars):\n{schema_ctx[:3000]}\n\n"
			f"Question: {question}\n\n"
			"Rules:\n"
			"- Return ONLY the SQL query — no explanation, no markdown fences\n"
			f"- Add LIMIT 500 unless the question requests a specific number\n"
			"- Format monetary amounts as value/100 ::NUMERIC(18,2) aliased 'amount_kes'\n"
			"- Use short table aliases for readability\n"
			"- Only SELECT statements; never INSERT/UPDATE/DELETE/DROP\n\n"
			"SQL:"
		)

		response = client.chat(
			[{"role": "user", "content": prompt}],
			max_tokens=600,
			temperature=0.0,
		)

		# Strip markdown code fences if the LLM included them
		sql = response.strip()
		sql = re.sub(r"^```sql?\s*", "", sql, flags=re.IGNORECASE)
		sql = re.sub(r"\s*```$", "", sql)
		return sql.strip()

	# ------------------------------------------------------------------
	# Safety
	# ------------------------------------------------------------------

	@staticmethod
	def _is_safe_sql(sql: str) -> bool:
		"""Return True only for plain SELECT statements.

		Blocks all DML (INSERT/UPDATE/DELETE), DDL (DROP/CREATE/ALTER/TRUNCATE),
		and inline comments (--) which could mask injected keywords.
		"""
		sql_upper = sql.upper().strip()
		if not sql_upper.startswith("SELECT"):
			return False
		_BANNED = frozenset({
			"INSERT", "UPDATE", "DELETE", "DROP", "CREATE",
			"ALTER", "TRUNCATE", "EXEC", "EXECUTE", "GRANT",
			"REVOKE", "COPY", "\\i", "--",
		})
		return not any(kw in sql_upper for kw in _BANNED)

	# ------------------------------------------------------------------
	# Cache
	# ------------------------------------------------------------------

	@staticmethod
	def _query_hash(question: str) -> str:
		return hashlib.sha256(question.lower().strip().encode()).hexdigest()[:16]

	def _check_cache(
		self,
		question: str,
		session,
		*,
		tenant_id: str = "default",
	) -> dict | None:
		"""Return cached result dict or None.

		Cache hit: same (query_hash, tenant_id) pair within the last hour,
		with hit_count incremented.
		"""
		try:
			import sqlalchemy as sa
			q_hash = self._query_hash(question)
			row = session.execute(
				sa.text(
					"SELECT cached_sql FROM pgaf_nl_query_cache "
					"WHERE query_hash = :h AND tenant_id = :t "
					"  AND cached_at > NOW() - INTERVAL '1 hour'"
				),
				{"h": q_hash, "t": tenant_id},
			).fetchone()
			if row:
				# Bump hit count (best-effort, non-fatal)
				try:
					session.execute(
						sa.text(
							"UPDATE pgaf_nl_query_cache "
							"SET hit_count = hit_count + 1 "
							"WHERE query_hash = :h AND tenant_id = :t"
						),
						{"h": q_hash, "t": tenant_id},
					)
				except Exception:
					pass
				return {
					"sql": row[0],
					"results": [],
					"columns": [],
					"row_count": 0,
					"error": None,
					"note": "Result from cache; re-execute SQL to get fresh rows.",
				}
		except Exception as exc:
			log.debug("NLAnalytics: cache lookup skipped — %s", exc)
		return None

	def _cache_result(
		self,
		question: str,
		sql: str,
		session,
		*,
		tenant_id: str = "default",
	) -> None:
		"""Upsert a successful NL→SQL result into the cache table."""
		try:
			import sqlalchemy as sa
			from uuid6 import uuid7
			q_hash = self._query_hash(question)
			session.execute(
				sa.text(
					"INSERT INTO pgaf_nl_query_cache "
					"  (id, query_hash, question, cached_sql, cached_at, tenant_id) "
					"VALUES (:id, :h, :q, :sql, NOW(), :t) "
					"ON CONFLICT (query_hash, tenant_id) "
					"  DO UPDATE SET cached_sql = EXCLUDED.cached_sql, "
					"               cached_at  = NOW()"
				),
				{
					"id":  str(uuid7()),
					"h":   q_hash,
					"q":   question[:500],
					"sql": sql,
					"t":   tenant_id,
				},
			)
		except Exception as exc:
			log.debug("NLAnalytics: cache write skipped — %s", exc)

	# ------------------------------------------------------------------
	# Internals
	# ------------------------------------------------------------------

	@staticmethod
	def _config_int(key: str, default: int) -> int:
		try:
			from flask import current_app
			return int(current_app.config.get(key, default))
		except Exception:
			return default


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _jsonify_rows(rows: list[dict]) -> list[dict]:
	"""Convert non-JSON-serialisable values (Decimal, date, etc.) to strings."""
	import datetime, decimal
	clean = []
	for row in rows:
		new_row = {}
		for k, v in row.items():
			if isinstance(v, (datetime.datetime, datetime.date)):
				new_row[k] = v.isoformat()
			elif isinstance(v, decimal.Decimal):
				new_row[k] = float(v)
			elif v is None or isinstance(v, (str, int, float, bool)):
				new_row[k] = v
			else:
				new_row[k] = str(v)
		clean.append(new_row)
	return clean


__all__ = [
	"NLAnalyticsService",
	"create_cache_table_ddl",
	"ensure_cache_table",
]
