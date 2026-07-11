"""
tests/ci/test_citizen_dev.py

CI tests for pgappforge.citizen_dev (P0-2 — YAML-first citizen dev layer).

Test strategy
-------------
- Pure-logic / parsing tests run without any database or Flask context.
- Runtime (ALTER TABLE) tests use the shared PostgreSQL fixture from conftest.py.
- No mocks — real objects only.
- All classes/functions under test are imported directly so failures surface
  precisely.
"""
from __future__ import annotations

import os
import textwrap
import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import DeclarativeBase, Session


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PG_URI = (
	os.environ.get("SQLALCHEMY_DATABASE_URI")
	or os.environ.get("PGAPPFORGE_DB")
	or "postgresql:///pgaf_test"
)


def _pg_engine():
	return sa.create_engine(_PG_URI, future=True)


# ---------------------------------------------------------------------------
# 1. Import sanity
# ---------------------------------------------------------------------------

class TestImports:
	def test_config_module_imports(self):
		from pgappforge.citizen_dev.config import (
			SUPPORTED_FIELD_TYPES,
			CustomFieldDef,
			CustomFilterDef,
			ModuleCustomization,
			load_customizations,
		)
		assert "string" in SUPPORTED_FIELD_TYPES
		assert "jsonb" in SUPPORTED_FIELD_TYPES
		assert "money" in SUPPORTED_FIELD_TYPES

	def test_runtime_module_imports(self):
		from pgappforge.citizen_dev.runtime import (
			apply_customizations,
			create_custom_field_tables,
			get_applied_customizations,
		)
		assert callable(apply_customizations)
		assert callable(create_custom_field_tables)
		assert callable(get_applied_customizations)

	def test_package_init_exports(self):
		import pgappforge.citizen_dev as cd
		assert hasattr(cd, "setup_citizen_dev")
		assert hasattr(cd, "CustomFieldDef")
		assert hasattr(cd, "load_customizations")
		assert hasattr(cd, "apply_customizations")


# ---------------------------------------------------------------------------
# 2. CustomFieldDef validation
# ---------------------------------------------------------------------------

class TestCustomFieldDef:
	def test_auto_prefix(self):
		from pgappforge.citizen_dev.config import CustomFieldDef
		fd = CustomFieldDef(name="salary", type="money")
		assert fd.name == "custom_salary"

	def test_already_prefixed_not_doubled(self):
		from pgappforge.citizen_dev.config import CustomFieldDef
		fd = CustomFieldDef(name="custom_salary", type="money")
		assert fd.name == "custom_salary"

	def test_auto_label_from_name(self):
		from pgappforge.citizen_dev.config import CustomFieldDef
		fd = CustomFieldDef(name="employer_code", type="string")
		assert fd.label == "Employer Code"

	def test_explicit_label_preserved(self):
		from pgappforge.citizen_dev.config import CustomFieldDef
		fd = CustomFieldDef(name="employer_code", type="string", label="EMP Code")
		assert fd.label == "EMP Code"

	def test_invalid_type_raises(self):
		from pgappforge.citizen_dev.config import CustomFieldDef
		with pytest.raises(ValueError, match="Unsupported field type"):
			CustomFieldDef(name="bad", type="blob")

	def test_invalid_name_raises(self):
		from pgappforge.citizen_dev.config import CustomFieldDef
		with pytest.raises(ValueError, match="snake_case"):
			CustomFieldDef(name="BadName", type="string")

	def test_name_starting_with_digit_raises(self):
		from pgappforge.citizen_dev.config import CustomFieldDef
		with pytest.raises(ValueError, match="snake_case"):
			CustomFieldDef(name="1field", type="string")

	def test_all_supported_types_instantiate(self):
		from pgappforge.citizen_dev.config import CustomFieldDef, SUPPORTED_FIELD_TYPES
		for ftype in SUPPORTED_FIELD_TYPES:
			fd = CustomFieldDef(name=f"field_{ftype.replace('/', '_')}", type=ftype)
			assert fd.type == ftype

	def test_visible_on_properties(self):
		from pgappforge.citizen_dev.config import CustomFieldDef
		fd = CustomFieldDef(name="col", type="string", visible_on=["list", "form"])
		assert fd.show_on_list is True
		assert fd.show_on_form is True
		assert fd.show_on_detail is False

	def test_default_visible_on(self):
		from pgappforge.citizen_dev.config import CustomFieldDef
		fd = CustomFieldDef(name="col", type="string")
		assert fd.show_on_list is True
		assert fd.show_on_detail is True
		assert fd.show_on_form is True


# ---------------------------------------------------------------------------
# 3. CustomFilterDef
# ---------------------------------------------------------------------------

class TestCustomFilterDef:
	def test_basic_instantiation(self):
		from pgappforge.citizen_dev.config import CustomFilterDef
		f = CustomFilterDef(field="custom_employer_code")
		assert f.field == "custom_employer_code"
		assert f.type == "string"

	def test_auto_label(self):
		from pgappforge.citizen_dev.config import CustomFilterDef
		f = CustomFilterDef(field="custom_employer_code")
		assert f.label == "Custom Employer Code"

	def test_explicit_label(self):
		from pgappforge.citizen_dev.config import CustomFilterDef
		f = CustomFilterDef(field="custom_employer_code", label="My Filter")
		assert f.label == "My Filter"


# ---------------------------------------------------------------------------
# 4. ModuleCustomization
# ---------------------------------------------------------------------------

class TestModuleCustomization:
	def test_qualified_name(self):
		from pgappforge.citizen_dev.config import ModuleCustomization
		mc = ModuleCustomization(
			module_path="pgappforge.plugins.fintech.sacco",
			model_name="Member",
		)
		assert mc.qualified_name == "pgappforge.plugins.fintech.sacco.Member"

	def test_empty_customization(self):
		from pgappforge.citizen_dev.config import ModuleCustomization
		mc = ModuleCustomization(module_path="a.b.c", model_name="Foo")
		assert mc.extra_fields == []
		assert mc.extra_filters == []


# ---------------------------------------------------------------------------
# 5. load_customizations — YAML parsing
# ---------------------------------------------------------------------------

class TestLoadCustomizations:
	def test_missing_directory_returns_empty(self, tmp_path):
		from pgappforge.citizen_dev.config import load_customizations
		result = load_customizations(tmp_path / "nonexistent")
		assert result == []

	def test_empty_directory_returns_empty(self, tmp_path):
		from pgappforge.citizen_dev.config import load_customizations
		result = load_customizations(tmp_path)
		assert result == []

	def test_valid_yaml_parsed(self, tmp_path):
		from pgappforge.citizen_dev.config import load_customizations
		yaml_content = textwrap.dedent("""
			module_path: myapp.models
			model_name: Customer
			extra_fields:
			  - name: loyalty_tier
			    type: select
			    choices: [BRONZE, SILVER, GOLD]
			  - name: referral_code
			    type: string
			    max_length: 20
		""")
		(tmp_path / "customers.yaml").write_text(yaml_content)
		result = load_customizations(tmp_path)
		assert len(result) == 1
		mc = result[0]
		assert mc.model_name == "Customer"
		assert len(mc.extra_fields) == 2
		assert mc.extra_fields[0].name == "custom_loyalty_tier"
		assert mc.extra_fields[0].choices == ["BRONZE", "SILVER", "GOLD"]
		assert mc.extra_fields[1].name == "custom_referral_code"
		assert mc.extra_fields[1].max_length == 20

	def test_invalid_field_type_skipped_not_fatal(self, tmp_path):
		from pgappforge.citizen_dev.config import load_customizations
		yaml_content = textwrap.dedent("""
			module_path: myapp.models
			model_name: Widget
			extra_fields:
			  - name: good_field
			    type: string
			  - name: bad_field
			    type: blob
		""")
		(tmp_path / "widgets.yaml").write_text(yaml_content)
		result = load_customizations(tmp_path)
		assert len(result) == 1
		# bad_field should be skipped, good_field kept
		assert len(result[0].extra_fields) == 1
		assert result[0].extra_fields[0].name == "custom_good_field"

	def test_malformed_yaml_skipped(self, tmp_path):
		from pgappforge.citizen_dev.config import load_customizations
		(tmp_path / "broken.yaml").write_text(": this is not valid yaml: [unclosed")
		result = load_customizations(tmp_path)
		assert result == []

	def test_multiple_files_all_loaded(self, tmp_path):
		from pgappforge.citizen_dev.config import load_customizations
		for i in range(3):
			(tmp_path / f"model{i}.yaml").write_text(textwrap.dedent(f"""
				module_path: myapp
				model_name: Model{i}
				extra_fields:
				  - name: col{i}
				    type: integer
			"""))
		result = load_customizations(tmp_path)
		assert len(result) == 3
		names = {mc.model_name for mc in result}
		assert names == {"Model0", "Model1", "Model2"}

	def test_example_yaml_file_parses(self):
		"""The committed example file must parse without errors."""
		from pgappforge.citizen_dev.config import load_customizations
		example_dir = Path(__file__).parents[2] / "custom_fields"
		if not example_dir.exists():
			pytest.skip("custom_fields/ directory not found")
		result = load_customizations(example_dir)
		# At minimum the example_sacco_member.yaml should load
		assert len(result) >= 1
		names = [mc.model_name for mc in result]
		assert "Member" in names

	def test_extra_list_columns_and_filters_parsed(self, tmp_path):
		from pgappforge.citizen_dev.config import load_customizations
		yaml_content = textwrap.dedent("""
			module_path: myapp.models
			model_name: Invoice
			extra_fields:
			  - name: po_number
			    type: string
			extra_list_columns:
			  - custom_po_number
			extra_filters:
			  - field: custom_po_number
			    label: PO Number
			    type: string
		""")
		(tmp_path / "invoice.yaml").write_text(yaml_content)
		result = load_customizations(tmp_path)
		mc = result[0]
		assert mc.extra_list_columns == ["custom_po_number"]
		assert len(mc.extra_filters) == 1
		assert mc.extra_filters[0].field == "custom_po_number"


# ---------------------------------------------------------------------------
# 6. Runtime helpers (pure logic, no DB)
# ---------------------------------------------------------------------------

class TestRuntimeHelpers:
	def test_field_type_to_sa_type_string(self):
		from pgappforge.citizen_dev.config import CustomFieldDef
		from pgappforge.citizen_dev.runtime import _field_type_to_sa_type
		fd = CustomFieldDef(name="x", type="string", max_length=50)
		col = _field_type_to_sa_type(fd)
		assert "String" in type(col).__name__ or "VARCHAR" in str(col)

	def test_field_type_to_sa_type_jsonb(self):
		from pgappforge.citizen_dev.config import CustomFieldDef
		from pgappforge.citizen_dev.runtime import _field_type_to_sa_type
		from sqlalchemy.dialects.postgresql import JSONB
		fd = CustomFieldDef(name="x", type="jsonb")
		col = _field_type_to_sa_type(fd)
		assert isinstance(col, JSONB)

	def test_field_type_to_sa_type_money(self):
		from pgappforge.citizen_dev.config import CustomFieldDef
		from pgappforge.citizen_dev.runtime import _field_type_to_sa_type
		fd = CustomFieldDef(name="x", type="money")
		col = _field_type_to_sa_type(fd)
		assert "BigInteger" in type(col).__name__ or "BIGINT" in str(col).upper()

	def test_sa_type_to_ddl_varchar(self):
		from pgappforge.citizen_dev.runtime import _sa_type_to_ddl
		assert _sa_type_to_ddl(sa.String(100)) in ("VARCHAR(100)",)

	def test_sa_type_to_ddl_datetime(self):
		from pgappforge.citizen_dev.runtime import _sa_type_to_ddl
		assert _sa_type_to_ddl(sa.DateTime(timezone=True)) == "TIMESTAMPTZ"

	def test_sa_type_to_ddl_numeric(self):
		from pgappforge.citizen_dev.runtime import _sa_type_to_ddl
		assert _sa_type_to_ddl(sa.Numeric(18, 4)) == "NUMERIC(18,4)"

	def test_format_default_string(self):
		from pgappforge.citizen_dev.runtime import _format_default
		assert _format_default("foo") == "'foo'"

	def test_format_default_bool(self):
		from pgappforge.citizen_dev.runtime import _format_default
		assert _format_default(True) == "TRUE"
		assert _format_default(False) == "FALSE"

	def test_format_default_int(self):
		from pgappforge.citizen_dev.runtime import _format_default
		assert _format_default(42) == "42"

	def test_format_default_string_escapes_quotes(self):
		from pgappforge.citizen_dev.runtime import _format_default
		assert _format_default("O'Brien") == "'O''Brien'"

	def test_resolve_table_name_unknown_module(self):
		from pgappforge.citizen_dev.runtime import _resolve_table_name
		result = _resolve_table_name("nonexistent.module", "FakeModel")
		assert result is None

	def test_get_applied_customizations_returns_list(self):
		from pgappforge.citizen_dev.runtime import get_applied_customizations
		result = get_applied_customizations()
		assert isinstance(result, list)


# ---------------------------------------------------------------------------
# 7. Database integration (PostgreSQL required)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
	not _PG_URI.startswith("postgresql"),
	reason="PostgreSQL required for runtime integration tests",
)
class TestRuntimeDatabase:
	"""Integration tests that actually ALTER TABLE in the test DB."""

	def _make_engine(self):
		return sa.create_engine(_PG_URI, future=True)

	def _create_test_table(self, conn, table_name: str) -> None:
		conn.execute(sa.text(f"""
			CREATE TABLE IF NOT EXISTS {table_name} (
				id			TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
				name		VARCHAR(200),
				created_at	TIMESTAMPTZ DEFAULT NOW()
			)
		"""))

	def test_create_custom_field_tables(self):
		from pgappforge.citizen_dev.runtime import create_custom_field_tables
		engine = self._make_engine()
		create_custom_field_tables(engine)	# must not raise
		# Verify table exists
		with engine.connect() as conn:
			row = conn.execute(sa.text("""
				SELECT table_name FROM information_schema.tables
				WHERE table_name = 'pgaf_custom_field' AND table_schema = 'public'
			""")).fetchone()
		assert row is not None
		engine.dispose()

	def test_apply_customizations_returns_added_count(self, tmp_path):
		from pgappforge.citizen_dev.config import CustomFieldDef, ModuleCustomization
		from pgappforge.citizen_dev.runtime import (
			apply_customizations,
			create_custom_field_tables,
		)

		engine = self._make_engine()
		table = f"_ci_test_{uuid.uuid4().hex[:8]}"

		with engine.begin() as conn:
			self._create_test_table(conn, table)

		create_custom_field_tables(engine)

		# Build customization manually (no module to import)
		fd = CustomFieldDef(name="score", type="integer")
		mc = ModuleCustomization(
			module_path="__nonexistent__",
			model_name="__NonExistent__",
			extra_fields=[fd],
		)
		# Patch the table name resolution by pre-resolving ourselves
		from pgappforge.citizen_dev import runtime as rt
		original = rt._resolve_table_name

		def _patched(mod, mdl):
			if mod == "__nonexistent__":
				return table
			return original(mod, mdl)

		rt._resolve_table_name = _patched
		try:
			added = apply_customizations(engine, customizations=[mc])
		finally:
			rt._resolve_table_name = original

		assert added == 1

		assert mc in rt.get_applied_customizations()

		# Clean up
		with engine.begin() as conn:
			conn.execute(sa.text(f"DROP TABLE IF EXISTS {table}"))
		engine.dispose()

	def test_apply_customizations_idempotent(self, tmp_path):
		"""Calling apply twice must not raise and reports each current application."""
		from pgappforge.citizen_dev.config import CustomFieldDef, ModuleCustomization
		from pgappforge.citizen_dev.runtime import apply_customizations, create_custom_field_tables
		from pgappforge.citizen_dev import runtime as rt

		engine = self._make_engine()
		table = f"_ci_test_{uuid.uuid4().hex[:8]}"

		with engine.begin() as conn:
			self._create_test_table(conn, table)
		create_custom_field_tables(engine)

		fd = CustomFieldDef(name="flag", type="boolean", default=False)
		mc = ModuleCustomization(module_path="__x__", model_name="__X__", extra_fields=[fd])

		original = rt._resolve_table_name

		def _patch(m, n):
			return table if m == "__x__" else original(m, n)

		rt._resolve_table_name = _patch
		try:
			first = apply_customizations(engine, customizations=[mc])
			second = apply_customizations(engine, customizations=[mc])
		finally:
			rt._resolve_table_name = original

		assert first == 1
		assert second == 1

		with engine.begin() as conn:
			conn.execute(sa.text(f"DROP TABLE IF EXISTS {table}"))
		engine.dispose()
