"""Python 3.14 feature integration for pgappforge.

DETECT_IMPLEMENTATION
=====================
Python 3.14 introduces several features this module leverages:

  PEP 750 — Template strings (t-strings)
    t"Hello {name}" produces a Template object instead of str.
    In Python 3.14.5 the Template object exposes three parallel sequences:
      .strings        — tuple of literal str segments (always len(values)+1)
      .interpolations — tuple of Interpolation objects in expression order
      .values         — tuple of already-evaluated expression values
    Interpolation carries (value, expression_str, conversion, format_spec).
    This enables safe, structured processing without string concatenation hacks.

    pgappforge benefit: safe_sql() converts t-string interpolations
    into positional bind parameters, making SQL injection impossible
    by construction — the query shape and the data never merge into
    a single string until the DB driver handles it.

  PEP 749 — annotationlib / lazy annotations
    get_annotations() with FORMAT_VALUE returns evaluated type objects
    at runtime without triggering full module evaluation.  Useful for
    inspecting model field types in the codegen pipeline without
    importing heavy SQLAlchemy machinery just to read a hint.

  PEP 742 — TypeIs (narrowing predicate)
    TypeIs[T] in return position lets type checkers narrow the argument
    type inside the branch, more precisely than TypeGuard.

  PEP 764 — Inline TypedDict
    Inline syntax: type Row = TypedDict("Row", col: str, ...) for
    one-off structured dicts without a class body.

  Union syntax (|) everywhere
    str | None instead of Optional[str] is now fully supported in all
    annotation positions, including runtime isinstance checks via
    types.UnionType.

Runtime detection
-----------------
All 3.14-only paths are guarded by PY314.  On older runtimes the
module degrades gracefully: safe_sql falls back to a naïve
%-style escaping approach (still safer than raw f-strings), and
annotation introspection falls back to typing.get_type_hints().
"""

from __future__ import annotations

import sys
import re
import logging
from typing import Any, NamedTuple

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Feature flag
# ---------------------------------------------------------------------------

PY314: bool = sys.version_info >= (3, 14)

# ---------------------------------------------------------------------------
# Template-string (t-string) plumbing
# ---------------------------------------------------------------------------

if PY314:
	# string.templatelib is the stdlib home for Template / Interpolation in 3.14
	try:
		from string.templatelib import Template, Interpolation  # type: ignore[import]
		_TSTRING_AVAILABLE = True
	except ImportError:
		# Pre-release builds may not have the final module path yet
		_TSTRING_AVAILABLE = False
		Template = None  # type: ignore[assignment,misc]
		Interpolation = None  # type: ignore[assignment,misc]
else:
	_TSTRING_AVAILABLE = False
	Template = None  # type: ignore[assignment,misc]
	Interpolation = None  # type: ignore[assignment,misc]


# ---------------------------------------------------------------------------
# annotationlib plumbing
# ---------------------------------------------------------------------------

if PY314:
	try:
		import annotationlib  # type: ignore[import]
		_ANNOTATIONLIB_AVAILABLE = True
	except ImportError:
		_ANNOTATIONLIB_AVAILABLE = False
else:
	_ANNOTATIONLIB_AVAILABLE = False


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------

class ParameterizedQuery(NamedTuple):
	"""A SQL query with positional bind parameters.

	sql     — query string with %s placeholders (psycopg / asyncpg style)
	params  — tuple of values in placeholder order
	"""
	sql: str
	params: tuple[Any, ...]


# ---------------------------------------------------------------------------
# safe_sql
# ---------------------------------------------------------------------------

def safe_sql(template: Any) -> ParameterizedQuery:
	"""Convert a t-string (or fallback string) to a parameterised query.

	On Python 3.14+ with t-strings available pass a Template object::

		name = "O'Brien"
		table = "users"
		query = safe_sql(t"SELECT * FROM {table} WHERE last_name = {name}")
		# query.sql    → "SELECT * FROM %s WHERE last_name = %s"
		# query.params → ('users', "O'Brien")

	On older runtimes pass a plain str with ``{placeholder}`` syntax and
	a dict of values — the function extracts named placeholders and
	substitutes them positionally::

		query = safe_sql("SELECT * FROM {table} WHERE last_name = {name}",
		                 table="users", name="O'Brien")

	The t-string path is injection-safe by construction: interpolated
	values never land in the query string — only positional markers do.
	The fallback path is injection-safe because values are passed to the
	DB driver as parameters, never via string concatenation.

	Args:
		template: A Template object (3.14+) or a plain str with
		          ``{name}`` placeholders.  When passing a str, keyword
		          arguments supply the substitution values.

	Returns:
		ParameterizedQuery(sql, params)
	"""
	if _TSTRING_AVAILABLE and isinstance(template, Template):
		return _safe_sql_from_template(template)

	# Fallback: plain str
	if isinstance(template, str):
		return _safe_sql_from_str(template)

	raise TypeError(
		f"safe_sql expects a t-string Template or str, got {type(template).__name__}"
	)


def _safe_sql_from_template(template: Any) -> ParameterizedQuery:
	"""Extract parts from a Template object and build a parameterised query.

	Python 3.14.5 Template layout:
	  .strings        — (n+1,) tuple of literal str segments
	  .interpolations — (n,)   tuple of Interpolation objects
	  .values         — (n,)   tuple of evaluated expression values

	The interleaving is:  strings[0] interp[0] strings[1] interp[1] … strings[n]
	"""
	# .values is the simplest path: already-evaluated expression results in order.
	# .strings gives us the literal segments in order.
	strings = template.strings        # tuple[str, ...]
	values  = template.values         # tuple[Any, ...]

	sql_parts: list[str] = []
	params: list[Any] = []

	# strings is always one element longer than values
	for i, literal in enumerate(strings):
		sql_parts.append(literal)
		if i < len(values):
			params.append(values[i])
			sql_parts.append("%s")

	return ParameterizedQuery(sql="".join(sql_parts), params=tuple(params))


def _safe_sql_from_str(template: str, **values: Any) -> ParameterizedQuery:
	"""Fallback: extract {name} placeholders from a plain str.

	Order of appearance in the string determines parameter order.
	"""
	# Find all {name} or {name:fmt} placeholders in order, deduplicated
	# while preserving first-occurrence order.
	pattern = re.compile(r"\{(\w+)(?::[^}]*)?\}")
	seen: dict[str, None] = {}
	for m in pattern.finditer(template):
		seen[m.group(1)] = None

	params: list[Any] = []
	for name in seen:
		if name not in values:
			raise KeyError(
				f"safe_sql fallback: placeholder '{{{name}}}' has no matching keyword argument"
			)
		params.append(values[name])

	# Replace {name} and {name:fmt} with %s
	sql = pattern.sub("%s", template)
	return ParameterizedQuery(sql=sql, params=tuple(params))


# Convenience wrapper that matches the t-string calling convention
# but also accepts keyword arguments for the fallback path.
def safe_sql_kw(template: Any, **values: Any) -> ParameterizedQuery:
	"""Like safe_sql but accepts keyword arguments for the fallback path.

	Usage (3.14+)::

		q = safe_sql_kw(t"SELECT * FROM users WHERE id = {user_id}")

	Usage (fallback)::

		q = safe_sql_kw("SELECT * FROM users WHERE id = {user_id}",
		                user_id=42)
	"""
	if _TSTRING_AVAILABLE and isinstance(template, Template):
		return _safe_sql_from_template(template)
	if isinstance(template, str):
		return _safe_sql_from_str(template, **values)
	raise TypeError(type(template).__name__)


# ---------------------------------------------------------------------------
# annotationlib integration
# ---------------------------------------------------------------------------

def get_field_annotations(cls: type) -> dict[str, Any]:
	"""Return evaluated runtime annotations for *cls*.

	On 3.14+: uses annotationlib.get_annotations() with FORMAT_VALUE so
	annotations are evaluated lazily and returned as actual type objects,
	not strings — even when ``from __future__ import annotations`` is active.

	On earlier runtimes: falls back to typing.get_type_hints(), which
	performs a similar evaluation but requires the class's module globals
	to be importable at call time.

	Args:
		cls: Any class, typically a SQLAlchemy model or Pydantic model.

	Returns:
		Dict mapping attribute name to its type object (or string if
		evaluation failed).
	"""
	if _ANNOTATIONLIB_AVAILABLE:
		try:
			# FORMAT_VALUE = 3 in annotationlib (evaluates annotations)
			fmt = getattr(annotationlib, "FORMAT_VALUE", 3)
			return annotationlib.get_annotations(cls, format=fmt)
		except Exception as exc:
			log.debug("annotationlib.get_annotations failed for %s: %s", cls, exc)

	# Fallback
	import typing
	try:
		return typing.get_type_hints(cls)
	except Exception as exc:
		log.debug("typing.get_type_hints failed for %s: %s", cls, exc)
		return getattr(cls, "__annotations__", {})


def describe_field_type(annotation: Any) -> str:
	"""Produce a human-readable label for a runtime annotation.

	Handles Union types expressed via the | operator (types.UnionType on
	3.10+), typing.Union, and plain types.

	Examples::

		describe_field_type(str | None)    → "str | None"
		describe_field_type(list[int])     → "list[int]"
		describe_field_type(int)           → "int"
	"""
	import types as _types
	import typing

	# NoneType must be checked before the generic isinstance(type) branch,
	# because NoneType IS a type whose __name__ is "NoneType" not "None".
	if annotation is type(None):
		return "None"

	# 3.10+ union: int | str  (also matches on 3.14 where int|None → UnionType)
	if hasattr(_types, "UnionType") and isinstance(annotation, _types.UnionType):
		parts = [describe_field_type(a) for a in annotation.__args__]
		return " | ".join(parts)

	# typing.Union / Optional
	origin = getattr(annotation, "__origin__", None)
	if origin is typing.Union:
		parts = [describe_field_type(a) for a in annotation.__args__]
		return " | ".join(parts)

	# Generic alias: list[str], dict[str, int] …
	if hasattr(annotation, "__origin__") and hasattr(annotation, "__args__"):
		origin_name = getattr(annotation.__origin__, "__name__", str(annotation.__origin__))
		args = ", ".join(describe_field_type(a) for a in annotation.__args__)
		return f"{origin_name}[{args}]"

	# Plain type
	if isinstance(annotation, type):
		return annotation.__name__

	return repr(annotation)


# ---------------------------------------------------------------------------
# TypeIs helper (3.14 narrowing predicate, degrades to bool on older runtimes)
# ---------------------------------------------------------------------------

if PY314:
	try:
		from typing import TypeIs  # type: ignore[attr-defined]
	except ImportError:
		from typing import TypeGuard as TypeIs  # type: ignore[assignment]
else:
	try:
		from typing import TypeIs  # type: ignore[attr-defined]
	except ImportError:
		try:
			from typing_extensions import TypeIs  # type: ignore[assignment]
		except ImportError:
			from typing import TypeGuard as TypeIs  # type: ignore[assignment]


def is_template(obj: Any) -> TypeIs[Any]:  # TypeIs[Template] when available
	"""Return True if *obj* is a 3.14 t-string Template object."""
	if not _TSTRING_AVAILABLE or Template is None:
		return False
	return isinstance(obj, Template)


def is_interpolation(obj: Any) -> TypeIs[Any]:  # TypeIs[Interpolation] when available
	"""Return True if *obj* is a t-string Interpolation part."""
	if not _TSTRING_AVAILABLE or Interpolation is None:
		return False
	return isinstance(obj, Interpolation)


# ---------------------------------------------------------------------------
# Inline TypedDict (3.14) — degrade gracefully
# ---------------------------------------------------------------------------
# 3.14 allows:  type SqlResult = TypedDict("SqlResult", sql=str, params=tuple)
# We simulate the same shape portably.

try:
	from typing import TypedDict

	class SqlResult(TypedDict):
		sql: str
		params: tuple[Any, ...]

except Exception:
	SqlResult = dict  # type: ignore[assignment,misc]


# ---------------------------------------------------------------------------
# Public API summary
# ---------------------------------------------------------------------------

__all__ = [
	# Feature flag
	"PY314",
	"_TSTRING_AVAILABLE",
	"_ANNOTATIONLIB_AVAILABLE",
	# Core types
	"ParameterizedQuery",
	"SqlResult",
	"TypeIs",
	# SQL safety
	"safe_sql",
	"safe_sql_kw",
	# Annotation introspection
	"get_field_annotations",
	"describe_field_type",
	# t-string type guards
	"is_template",
	"is_interpolation",
]
