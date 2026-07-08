"""Shared SQL guardrails for platform reporting and analytics surfaces."""
from __future__ import annotations

import re
from typing import Iterable


_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?$")
_READ_ONLY_RE = re.compile(r"^\s*(SELECT|WITH)\b", re.IGNORECASE)
_LINE_COMMENT_RE = re.compile(r"--[^\n\r]*")
_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
_FORBIDDEN_SQL_RE = re.compile(
	r"\b("
	r"ALTER|ANALYZE|ATTACH|CALL|COPY|CREATE|DELETE|DETACH|DO|DROP|EXEC|EXECUTE|"
	r"GRANT|INSERT|LISTEN|LOCK|MERGE|NOTIFY|REFRESH|REINDEX|RESET|REVOKE|SET|"
	r"TRUNCATE|UPDATE|VACUUM"
	r")\b",
	re.IGNORECASE,
)
_FORBIDDEN_FUNCTION_RE = re.compile(
	r"\b(pg_sleep|dblink|lo_export|lo_import|copy_to_program|copy_from_program)\s*\(",
	re.IGNORECASE,
)
_AGGREGATES = frozenset({"SUM", "AVG", "COUNT", "MIN", "MAX"})


class QueryGuardError(ValueError):
	"""Raised when a report or analytics query violates SQL guardrails."""


def strip_sql_comments(sql_query: str) -> str:
	"""Return *sql_query* without SQL comments for conservative validation."""
	without_blocks = _BLOCK_COMMENT_RE.sub(" ", sql_query or "")
	return _LINE_COMMENT_RE.sub(" ", without_blocks)


def validate_read_only_sql(sql_query: str) -> str:
	"""Validate and return a normalized read-only SQL statement.

	The guard is deliberately conservative: reporting and analytics SQL must be
	one read-only ``SELECT`` or ``WITH`` statement with no semicolon chaining and
	no mutation/admin keywords. It is not a full SQL parser, but it closes the
	obvious hazards while keeping the dependency surface small.
	"""
	sql = strip_sql_comments(sql_query).strip()
	if not sql:
		raise QueryGuardError("SQL query is required")
	if ";" in sql.rstrip(";"):
		raise QueryGuardError("Only one SQL statement is allowed")
	sql = sql.rstrip(";").strip()
	if not _READ_ONLY_RE.match(sql):
		raise QueryGuardError("Only SELECT or WITH queries are allowed")
	if _FORBIDDEN_SQL_RE.search(sql):
		raise QueryGuardError("Report and analytics queries must be read-only")
	if _FORBIDDEN_FUNCTION_RE.search(sql):
		raise QueryGuardError("Unsafe SQL function is not allowed")
	return sql


def validate_sql_identifier(identifier: str, *, label: str = "field") -> str:
	"""Validate a SQL identifier used in generated SQL fragments."""
	value = (identifier or "").strip()
	if not _IDENT_RE.match(value):
		raise QueryGuardError(f"Unsafe {label} identifier: {identifier!r}")
	return value


def validate_aggregate(aggregate: str) -> str:
	"""Validate and normalize an analytics aggregate function."""
	value = (aggregate or "").strip().upper()
	if value not in _AGGREGATES:
		raise QueryGuardError(
			f"Unsupported aggregate {aggregate!r}; allowed: {sorted(_AGGREGATES)}"
		)
	return value


def validate_identifier_collection(
	identifiers: Iterable[str],
	*,
	label: str = "field",
) -> list[str]:
	"""Validate a collection of SQL identifiers and preserve order."""
	return [validate_sql_identifier(identifier, label=label) for identifier in identifiers]

