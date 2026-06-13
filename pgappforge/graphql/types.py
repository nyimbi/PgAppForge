"""
pgappforge/graphql/types.py

Common Strawberry scalars and base types for the auto-generated GraphQL schema.

Provides:
  - JSON scalar (maps to Any Python value)
  - DateTime scalar (ISO-8601 strings)
  - Cursor scalar (opaque pagination cursor)
  - PageInfo — standard Relay-style pagination metadata
  - ErrorType — structured error envelope
"""
from __future__ import annotations

import datetime
from typing import Any, NewType, Optional

# ── Optional import ─────────────────────────────────────────────────────────
try:
	import strawberry
	from strawberry.scalars import JSON  # re-export
	_STRAWBERRY_OK = True
except ImportError:
	_STRAWBERRY_OK = False


# ---------------------------------------------------------------------------
# Scalars
# ---------------------------------------------------------------------------

if _STRAWBERRY_OK:
	# JSON scalar — arbitrary dict/list/primitive
	JSONScalar = strawberry.scalar(
		NewType("JSON", Any),
		description="Arbitrary JSON value.",
		serialize=lambda v: v,
		parse_value=lambda v: v,
	)

	# DateTime scalar — Python datetime ↔ ISO-8601 string
	DateTimeScalar = strawberry.scalar(
		NewType("DateTime", Any),
		description="ISO-8601 datetime string.",
		serialize=lambda v: v.isoformat() if isinstance(v, datetime.datetime) else str(v) if v else None,
		parse_value=lambda v: datetime.datetime.fromisoformat(v) if v else None,
	)

	# Opaque pagination cursor
	Cursor = strawberry.scalar(
		NewType("Cursor", str),
		description="Opaque pagination cursor (base64-encoded offset).",
		serialize=lambda v: v,
		parse_value=lambda v: v,
	)

	@strawberry.type
	class PageInfo:
		"""Relay-style pagination metadata."""
		has_next_page: bool = False
		has_previous_page: bool = False
		start_cursor: Optional[str] = None
		end_cursor: Optional[str] = None
		total_count: int = 0

	@strawberry.type
	class ErrorType:
		"""Structured error envelope returned by mutations."""
		field: Optional[str]
		message: str
		code: Optional[str] = None

	__all__ = [
		"JSONScalar",
		"DateTimeScalar",
		"Cursor",
		"PageInfo",
		"ErrorType",
	]
else:
	# Stub so imports don't fail when strawberry is not installed
	JSONScalar = None
	DateTimeScalar = None
	Cursor = None
	PageInfo = None  # type: ignore[assignment]
	ErrorType = None  # type: ignore[assignment]

	__all__ = [
		"JSONScalar",
		"DateTimeScalar",
		"Cursor",
		"PageInfo",
		"ErrorType",
	]
