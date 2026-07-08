"""Shared SQL guardrails for platform reporting and analytics surfaces."""
from __future__ import annotations

from collections.abc import Iterable
import re
from typing import Any


_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?$")
_READ_ONLY_RE = re.compile(r"^\s*(SELECT|WITH)\b", re.IGNORECASE)
_DOLLAR_QUOTE_START_RE = re.compile(r"\$[A-Za-z_][A-Za-z0-9_]*\$|\$\$")
_FORBIDDEN_SQL_RE = re.compile(
	r"\b("
	r"ALTER|ANALYZE|ATTACH|CALL|COPY|CREATE|DELETE|DETACH|DO|DROP|EXEC|EXECUTE|"
	r"GRANT|INSERT|LISTEN|LOCK|MERGE|NOTIFY|REFRESH|REINDEX|RESET|REVOKE|SET|"
	r"TRUNCATE|UPDATE|VACUUM"
	r")\b",
	re.IGNORECASE,
)
_SELECT_INTO_RE = re.compile(r"\bSELECT\b(?:(?!\bFROM\b).)*\bINTO\b", re.IGNORECASE | re.DOTALL)
_FORBIDDEN_FUNCTION_RE = re.compile(
	r"\b("
	r"copy_from_program|copy_to_program|dblink|lo_export|lo_import|"
	r"pg_advisory_lock|pg_advisory_xact_lock|pg_cancel_backend|pg_file_rename|"
	r"pg_file_unlink|pg_file_write|pg_ls_dir|pg_notify|pg_read_binary_file|"
	r"pg_read_file|pg_reload_conf|pg_rotate_logfile|pg_sleep|pg_stat_file|"
	r"pg_terminate_backend|set_config"
	r")\s*\(",
	re.IGNORECASE,
)
_AGGREGATES = frozenset({"SUM", "AVG", "COUNT", "MIN", "MAX"})


class QueryGuardError(ValueError):
	"""Raised when a report or analytics query violates SQL guardrails."""


def _match_dollar_quote(sql: str, index: int) -> tuple[str, int] | None:
	match = _DOLLAR_QUOTE_START_RE.match(sql, index)
	if match is None:
		return None
	tag = match.group(0)
	end = sql.find(tag, match.end())
	if end == -1:
		return None
	return tag, end + len(tag)


def _copy_quoted(sql: str, index: int, quote: str) -> tuple[str, int]:
	chars = [quote]
	i = index + 1
	while i < len(sql):
		chars.append(sql[i])
		if sql[i] == quote:
			if i + 1 < len(sql) and sql[i + 1] == quote:
				chars.append(sql[i + 1])
				i += 2
				continue
			return "".join(chars), i + 1
		if sql[i] == "\\" and i + 1 < len(sql):
			chars.append(sql[i + 1])
			i += 2
			continue
		i += 1
	return "".join(chars), i


def _mask_quoted(sql: str, index: int, quote: str) -> tuple[str, int]:
	value, end = _copy_quoted(sql, index, quote)
	return " " * len(value), end


def strip_sql_comments(sql_query: str) -> str:
	"""Return *sql_query* without SQL comments outside quoted literals."""
	if not isinstance(sql_query, str):
		raise QueryGuardError("SQL query must be a string")
	sql = sql_query or ""
	chars: list[str] = []
	i = 0
	while i < len(sql):
		if sql.startswith("--", i):
			i += 2
			while i < len(sql) and sql[i] not in "\n\r":
				i += 1
			if i < len(sql):
				chars.append(sql[i])
				i += 1
			else:
				chars.append(" ")
			continue
		if sql.startswith("/*", i):
			end = sql.find("*/", i + 2)
			if end == -1:
				chars.append(" ")
				break
			chars.append(" ")
			i = end + 2
			continue
		if sql[i] in {"'", '"'}:
			value, i = _copy_quoted(sql, i, sql[i])
			chars.append(value)
			continue
		dollar_quote = _match_dollar_quote(sql, i)
		if dollar_quote is not None:
			_, end = dollar_quote
			chars.append(sql[i:end])
			i = end
			continue
		chars.append(sql[i])
		i += 1
	return "".join(chars)


def _mask_sql_literals(sql: str) -> str:
	chars: list[str] = []
	i = 0
	while i < len(sql):
		if sql[i] in {"'", '"'}:
			value, i = _mask_quoted(sql, i, sql[i])
			chars.append(value)
			continue
		dollar_quote = _match_dollar_quote(sql, i)
		if dollar_quote is not None:
			_, end = dollar_quote
			chars.append(" " * (end - i))
			i = end
			continue
		chars.append(sql[i])
		i += 1
	return "".join(chars)


def _has_statement_separator(sql: str) -> bool:
	i = 0
	while i < len(sql):
		if sql[i] == ";":
			return True
		if sql[i] in {"'", '"'}:
			_, i = _copy_quoted(sql, i, sql[i])
			continue
		dollar_quote = _match_dollar_quote(sql, i)
		if dollar_quote is not None:
			_, i = dollar_quote
			continue
		i += 1
	return False


def _strip_single_trailing_terminator(sql: str) -> str:
	text = sql.rstrip()
	if not text.endswith(";"):
		return text
	without_terminator = text[:-1].rstrip()
	if _has_statement_separator(without_terminator):
		raise QueryGuardError("Only one SQL statement is allowed")
	return without_terminator


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
	sql = _strip_single_trailing_terminator(sql)
	if _has_statement_separator(sql):
		raise QueryGuardError("Only one SQL statement is allowed")
	if not _READ_ONLY_RE.match(sql):
		raise QueryGuardError("Only SELECT or WITH queries are allowed")
	sql_without_literals = _mask_sql_literals(sql)
	if _FORBIDDEN_SQL_RE.search(sql_without_literals):
		raise QueryGuardError("Report and analytics queries must be read-only")
	if _SELECT_INTO_RE.search(sql_without_literals):
		raise QueryGuardError("Report and analytics queries must be read-only")
	if _FORBIDDEN_FUNCTION_RE.search(sql_without_literals):
		raise QueryGuardError("Unsafe SQL function is not allowed")
	return sql


def validate_sql_identifier(identifier: Any, *, label: str = "field") -> str:
	"""Validate a SQL identifier used in generated SQL fragments."""
	if not isinstance(identifier, str):
		raise QueryGuardError(f"Unsafe {label} identifier: {identifier!r}")
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
	if isinstance(identifiers, (str, bytes)) or not isinstance(identifiers, Iterable):
		raise QueryGuardError(f"{label} identifiers must be a collection")
	return [validate_sql_identifier(identifier, label=label) for identifier in identifiers]
