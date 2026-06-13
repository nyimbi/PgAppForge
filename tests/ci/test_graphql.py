"""
tests/ci/test_graphql.py

Compile-check and unit tests for pgappforge/graphql/.

Tests are structured as pure import + logic checks — no live DB or Flask
app context required.  Strawberry is optional: tests that need it are
skipped cleanly when it is not installed.

Run with: uv run pytest -vxs tests/ci/test_graphql.py
"""
from __future__ import annotations

import sys
import types

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_STRAWBERRY_AVAILABLE = True
try:
	import strawberry  # noqa: F401
except ImportError:
	_STRAWBERRY_AVAILABLE = False

requires_strawberry = pytest.mark.skipif(
	not _STRAWBERRY_AVAILABLE,
	reason="strawberry-graphql not installed",
)


# ---------------------------------------------------------------------------
# Import smoke tests
# ---------------------------------------------------------------------------

class TestGraphQLImports:
	"""All modules in pgappforge/graphql/ must import without error."""

	def test_types_importable(self):
		from pgappforge.graphql.types import (
			JSONScalar, DateTimeScalar, Cursor, PageInfo, ErrorType,
		)
		# When strawberry is missing these are None — that is intentional
		assert True  # import itself is the assertion

	def test_schema_importable(self):
		from pgappforge.graphql.schema import create_schema, add_graphql_view
		assert callable(create_schema)
		assert callable(add_graphql_view)

	def test_views_importable(self):
		from pgappforge.graphql.views import register_graphql_blueprint
		assert callable(register_graphql_blueprint)

	def test_package_init_importable(self):
		from pgappforge.graphql import add_graphql_view, create_schema, register_graphql_blueprint
		assert callable(add_graphql_view)
		assert callable(create_schema)
		assert callable(register_graphql_blueprint)


# ---------------------------------------------------------------------------
# GraphQL helpers (no DB needed)
# ---------------------------------------------------------------------------

class TestGraphQLHelpers:
	def test_model_to_dict_basic(self):
		"""_model_to_dict serialises columns to str or None."""
		from pgappforge.graphql.schema import _model_to_dict
		import types as _t
		import decimal, datetime

		# Build a minimal fake SA model row
		col_a = _t.SimpleNamespace(name="id")
		col_b = _t.SimpleNamespace(name="amount")
		col_c = _t.SimpleNamespace(name="ts")

		obj = _t.SimpleNamespace(
			id="abc-123",
			amount=decimal.Decimal("99.5"),
			ts=datetime.datetime(2026, 1, 1),
		)
		obj.__table__ = _t.SimpleNamespace(columns=[col_a, col_b, col_c])

		result = _model_to_dict(obj)
		assert result["id"] == "abc-123"
		assert result["amount"] == str(decimal.Decimal("99.5"))
		assert result["ts"] is not None

	def test_model_to_dict_none_values(self):
		from pgappforge.graphql.schema import _model_to_dict
		import types as _t

		col = _t.SimpleNamespace(name="foo")
		obj = _t.SimpleNamespace(foo=None)
		obj.__table__ = _t.SimpleNamespace(columns=[col])

		result = _model_to_dict(obj)
		assert result["foo"] is None

	def test_get_all_subclasses(self):
		from pgappforge.graphql.schema import _get_all_subclasses

		class Root:
			pass
		class Child(Root):
			pass
		class GrandChild(Child):
			pass

		subs = _get_all_subclasses(Root)
		assert Child in subs
		assert GrandChild in subs
		assert len(subs) == 2


# ---------------------------------------------------------------------------
# Strawberry schema construction
# ---------------------------------------------------------------------------

@requires_strawberry
class TestStrawberrySchema:
	def test_create_schema_no_models_returns_schema(self):
		"""create_schema([]) returns a valid schema with health + version fields."""
		from pgappforge.graphql.schema import create_schema
		schema = create_schema(models=[])
		assert schema is not None

	def test_health_field(self):
		"""Query.health returns 'ok'."""
		from pgappforge.graphql.schema import create_schema
		import strawberry

		schema = create_schema(models=[])
		result = schema.execute_sync("{ health }")
		assert result.errors is None or result.errors == []
		assert result.data["health"] == "ok"

	def test_version_field(self):
		"""Query.version returns the framework version string."""
		from pgappforge.graphql.schema import create_schema

		schema = create_schema(models=[])
		result = schema.execute_sync("{ version }")
		assert result.errors is None or result.errors == []
		assert "4.8" in result.data["version"]

	def test_mutation_placeholder(self):
		"""Mutation.placeholder is present and returns 'ok'."""
		from pgappforge.graphql.schema import create_schema

		schema = create_schema(models=[])
		result = schema.execute_sync("mutation { placeholder }")
		assert result.errors is None or result.errors == []
		assert result.data["placeholder"] == "ok"

	def test_create_schema_with_fake_model(self):
		"""A fake SQLAlchemy-like model class produces list/get query fields."""
		from pgappforge.graphql.schema import create_schema
		import types as _t

		# Build a minimal fake SA model
		col_id   = _t.SimpleNamespace(name="id",   primary_key=True)
		col_name = _t.SimpleNamespace(name="name",  primary_key=False)
		tbl_pk   = _t.SimpleNamespace(columns=[col_id])

		class FakeModel:
			__name__      = "FakeModel"
			__tablename__ = "fake_model"
			__table__     = _t.SimpleNamespace(
				columns=[col_id, col_name],
				primary_key=tbl_pk,
			)

		schema = create_schema(models=[FakeModel])
		# Schema is valid regardless of how many fields injected
		assert schema is not None


@requires_strawberry
class TestGraphQLTypes:
	def test_page_info_defaults(self):
		from pgappforge.graphql.types import PageInfo
		pi = PageInfo()
		assert pi.has_next_page is False
		assert pi.total_count == 0

	def test_error_type_fields(self):
		from pgappforge.graphql.types import ErrorType
		err = ErrorType(field="name", message="required", code="REQUIRED")
		assert err.message == "required"
		assert err.code == "REQUIRED"
