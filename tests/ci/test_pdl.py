# tests/ci/test_pdl.py
# PDL (PgAppForge Domain Language) — deterministic schema → code generator tests.
# Run with: uv run pytest -vxs tests/ci/test_pdl.py
from __future__ import annotations

import re
import textwrap
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).parent.parent.parent


def _minimal_dict(**overrides) -> dict:
	"""Return a minimal valid PDL dict for SupplierInvoice."""
	base = {
		"version": "1.0",
		"namespace": "myapp.finance",
		"entities": [
			{
				"name": "SupplierInvoice",
				"table": "fin_supplier_invoice",
				"description": "Test invoice",
				"fields": [
					{"name": "amount_cents", "type": "money", "required": True},
					{"name": "status",       "type": "enum",  "choices": ["PENDING", "PAID"]},
				],
			}
		],
	}
	base.update(overrides)
	return base


# ---------------------------------------------------------------------------
# 1. PDLSchema.from_dict() — parsing
# ---------------------------------------------------------------------------

class TestPDLSchemaFromDict:
	def test_parses_version_and_namespace(self):
		from pgappforge.pdl.schema import PDLSchema
		schema = PDLSchema.from_dict(_minimal_dict())
		assert schema.version == "1.0"
		assert schema.namespace == "myapp.finance"

	def test_parses_entity_count(self):
		from pgappforge.pdl.schema import PDLSchema
		schema = PDLSchema.from_dict(_minimal_dict())
		assert len(schema.entities) == 1

	def test_entity_name_and_table(self):
		from pgappforge.pdl.schema import PDLSchema
		entity = PDLSchema.from_dict(_minimal_dict()).entities[0]
		assert entity.name  == "SupplierInvoice"
		assert entity.table == "fin_supplier_invoice"

	def test_field_count(self):
		from pgappforge.pdl.schema import PDLSchema
		entity = PDLSchema.from_dict(_minimal_dict()).entities[0]
		assert len(entity.fields) == 2

	def test_field_names_and_types(self):
		from pgappforge.pdl.schema import PDLSchema
		entity = PDLSchema.from_dict(_minimal_dict()).entities[0]
		names = {f.name: f.type for f in entity.fields}
		assert names == {"amount_cents": "money", "status": "enum"}

	def test_field_required_flag(self):
		from pgappforge.pdl.schema import PDLSchema
		entity = PDLSchema.from_dict(_minimal_dict()).entities[0]
		assert entity.fields[0].required is True
		assert entity.fields[1].required is False

	def test_field_choices_preserved(self):
		from pgappforge.pdl.schema import PDLSchema
		entity = PDLSchema.from_dict(_minimal_dict()).entities[0]
		assert entity.fields[1].choices == ["PENDING", "PAID"]

	def test_auto_label_derived_from_name(self):
		from pgappforge.pdl.schema import PDLSchema
		entity = PDLSchema.from_dict(_minimal_dict()).entities[0]
		assert entity.fields[0].label == "Amount Cents"

	def test_explicit_label_preserved(self):
		from pgappforge.pdl.schema import PDLSchema
		data = _minimal_dict()
		data["entities"][0]["fields"][0]["label"] = "Grand Total"
		entity = PDLSchema.from_dict(data).entities[0]
		assert entity.fields[0].label == "Grand Total"

	def test_module_path_auto_constructed(self):
		from pgappforge.pdl.schema import PDLSchema
		entity = PDLSchema.from_dict(_minimal_dict()).entities[0]
		# myapp.finance + _snake("SupplierInvoice") = myapp.finance.supplier_invoice
		assert entity.module_path == "myapp.finance.supplier_invoice"

	def test_explicit_module_path_preserved(self):
		from pgappforge.pdl.schema import PDLSchema
		data = _minimal_dict()
		data["entities"][0]["module_path"] = "custom.path.here"
		entity = PDLSchema.from_dict(data).entities[0]
		assert entity.module_path == "custom.path.here"

	def test_include_flags_default_to_true(self):
		from pgappforge.pdl.schema import PDLSchema
		entity = PDLSchema.from_dict(_minimal_dict()).entities[0]
		assert entity.include_uuid_pk          is True
		assert entity.include_tenant_id        is True
		assert entity.include_audit_timestamps is True

	def test_generate_list_default(self):
		from pgappforge.pdl.schema import PDLSchema
		entity = PDLSchema.from_dict(_minimal_dict()).entities[0]
		assert set(entity.generate) == {"model", "migration", "view", "api", "tests"}

	def test_fk_field_parsed(self):
		from pgappforge.pdl.schema import PDLSchema
		data = _minimal_dict()
		data["entities"][0]["fields"].append(
			{"name": "vendor_id", "type": "uuid", "fk": "Vendor.id"}
		)
		entity = PDLSchema.from_dict(data).entities[0]
		fk_field = next(f for f in entity.fields if f.name == "vendor_id")
		assert fk_field.fk == "Vendor.id"

	def test_multiple_entities(self):
		from pgappforge.pdl.schema import PDLSchema
		data = _minimal_dict()
		data["entities"].append(
			{"name": "PaymentLine", "table": "fin_payment_line", "fields": []}
		)
		schema = PDLSchema.from_dict(data)
		assert len(schema.entities) == 2
		assert schema.entities[1].name == "PaymentLine"


# ---------------------------------------------------------------------------
# 2. PDLCodeGenerator.generate_model()
# ---------------------------------------------------------------------------

class TestGenerateModel:
	def _entity(self):
		from pgappforge.pdl.schema import PDLSchema
		return PDLSchema.from_dict(_minimal_dict()).entities[0]

	def test_contains_class_definition(self):
		from pgappforge.pdl.generators import PDLCodeGenerator
		code = PDLCodeGenerator().generate_model(self._entity())
		assert "class SupplierInvoice(" in code

	def test_correct_tablename(self):
		from pgappforge.pdl.generators import PDLCodeGenerator
		code = PDLCodeGenerator().generate_model(self._entity())
		assert '__tablename__ = "fin_supplier_invoice"' in code

	def test_uuid_pk_present_by_default(self):
		from pgappforge.pdl.generators import PDLCodeGenerator
		code = PDLCodeGenerator().generate_model(self._entity())
		assert "primary_key=True" in code

	def test_tenant_id_column_present(self):
		from pgappforge.pdl.generators import PDLCodeGenerator
		code = PDLCodeGenerator().generate_model(self._entity())
		assert "tenant_id" in code

	def test_audit_timestamps_present(self):
		from pgappforge.pdl.generators import PDLCodeGenerator
		code = PDLCodeGenerator().generate_model(self._entity())
		assert "created_at" in code
		assert "updated_at" in code

	def test_amount_cents_biginteger(self):
		from pgappforge.pdl.generators import PDLCodeGenerator
		code = PDLCodeGenerator().generate_model(self._entity())
		assert "amount_cents" in code
		assert "BigInteger" in code

	def test_status_string50(self):
		from pgappforge.pdl.generators import PDLCodeGenerator
		code = PDLCodeGenerator().generate_model(self._entity())
		assert "status" in code
		assert "String(50)" in code

	def test_fk_generates_foreignkey(self):
		from pgappforge.pdl.schema import PDLSchema, PDLField
		from pgappforge.pdl.generators import PDLCodeGenerator
		data = _minimal_dict()
		data["entities"][0]["fields"].append(
			{"name": "vendor_id", "type": "uuid", "fk": "Vendor.id"}
		)
		entity = PDLSchema.from_dict(data).entities[0]
		code = PDLCodeGenerator().generate_model(entity)
		assert "ForeignKey" in code
		assert "vendor.id" in code

	def test_jsonb_field_import(self):
		from pgappforge.pdl.schema import PDLSchema
		from pgappforge.pdl.generators import PDLCodeGenerator
		data = _minimal_dict()
		data["entities"][0]["fields"].append(
			{"name": "line_items", "type": "jsonb"}
		)
		entity = PDLSchema.from_dict(data).entities[0]
		code = PDLCodeGenerator().generate_model(entity)
		assert "from sqlalchemy.dialects.postgresql import JSONB" in code
		assert "JSONB" in code

	def test_unique_field_emits_unique_constraint(self):
		from pgappforge.pdl.schema import PDLSchema
		from pgappforge.pdl.generators import PDLCodeGenerator
		data = _minimal_dict()
		data["entities"][0]["fields"].append(
			{"name": "invoice_number", "type": "string", "unique": True}
		)
		entity = PDLSchema.from_dict(data).entities[0]
		code = PDLCodeGenerator().generate_model(entity)
		assert "UniqueConstraint" in code

	def test_indexed_field_emits_index(self):
		from pgappforge.pdl.schema import PDLSchema
		from pgappforge.pdl.generators import PDLCodeGenerator
		data = _minimal_dict()
		data["entities"][0]["fields"].append(
			{"name": "ref_code", "type": "string", "indexed": True}
		)
		entity = PDLSchema.from_dict(data).entities[0]
		code = PDLCodeGenerator().generate_model(entity)
		assert "ix_fin_supplier_invoice_ref_code" in code

	def test_max_length_overrides_string_width(self):
		from pgappforge.pdl.schema import PDLSchema
		from pgappforge.pdl.generators import PDLCodeGenerator
		data = _minimal_dict()
		data["entities"][0]["fields"].append(
			{"name": "ref", "type": "string", "max_length": 30}
		)
		entity = PDLSchema.from_dict(data).entities[0]
		code = PDLCodeGenerator().generate_model(entity)
		assert "String(30)" in code

	def test_repr_method_present(self):
		from pgappforge.pdl.generators import PDLCodeGenerator
		code = PDLCodeGenerator().generate_model(self._entity())
		assert "__repr__" in code

	def test_is_valid_python_syntax(self):
		"""The generated model must parse without SyntaxError."""
		from pgappforge.pdl.generators import PDLCodeGenerator
		import ast
		code = PDLCodeGenerator().generate_model(self._entity())
		ast.parse(code)  # raises SyntaxError on bad code


# ---------------------------------------------------------------------------
# 3. PDLCodeGenerator.generate_migration()
# ---------------------------------------------------------------------------

class TestGenerateMigration:
	def _entity(self):
		from pgappforge.pdl.schema import PDLSchema
		return PDLSchema.from_dict(_minimal_dict()).entities[0]

	def test_upgrade_function_present(self):
		from pgappforge.pdl.generators import PDLCodeGenerator
		code = PDLCodeGenerator().generate_migration(self._entity())
		assert "def upgrade()" in code

	def test_downgrade_function_present(self):
		from pgappforge.pdl.generators import PDLCodeGenerator
		code = PDLCodeGenerator().generate_migration(self._entity())
		assert "def downgrade()" in code

	def test_create_table_call(self):
		from pgappforge.pdl.generators import PDLCodeGenerator
		code = PDLCodeGenerator().generate_migration(self._entity())
		assert 'op.create_table(' in code
		assert '"fin_supplier_invoice"' in code

	def test_drop_table_in_downgrade(self):
		from pgappforge.pdl.generators import PDLCodeGenerator
		code = PDLCodeGenerator().generate_migration(self._entity())
		assert 'op.drop_table("fin_supplier_invoice")' in code

	def test_tenant_index_created(self):
		from pgappforge.pdl.generators import PDLCodeGenerator
		code = PDLCodeGenerator().generate_migration(self._entity())
		assert "ix_fin_supplier_invoice_tenant" in code

	def test_alembic_import_present(self):
		from pgappforge.pdl.generators import PDLCodeGenerator
		code = PDLCodeGenerator().generate_migration(self._entity())
		assert "from alembic import op" in code

	def test_field_columns_included(self):
		from pgappforge.pdl.generators import PDLCodeGenerator
		code = PDLCodeGenerator().generate_migration(self._entity())
		assert "amount_cents" in code
		assert "status" in code

	def test_revision_id_in_docstring(self):
		from pgappforge.pdl.generators import PDLCodeGenerator
		code = PDLCodeGenerator().generate_migration(self._entity())
		assert "Revision ID:" in code

	def test_is_valid_python_syntax(self):
		import ast
		from pgappforge.pdl.generators import PDLCodeGenerator
		code = PDLCodeGenerator().generate_migration(self._entity())
		ast.parse(code)


# ---------------------------------------------------------------------------
# 4. PDLCodeGenerator.generate_tests()
# ---------------------------------------------------------------------------

class TestGenerateTests:
	def _entity(self):
		from pgappforge.pdl.schema import PDLSchema
		return PDLSchema.from_dict(_minimal_dict()).entities[0]

	def test_model_import_test_present(self):
		from pgappforge.pdl.generators import PDLCodeGenerator
		code = PDLCodeGenerator().generate_tests(self._entity())
		assert "test_supplier_invoice_model_imports" in code

	def test_view_import_test_present(self):
		from pgappforge.pdl.generators import PDLCodeGenerator
		code = PDLCodeGenerator().generate_tests(self._entity())
		assert "test_supplier_invoice_view_imports" in code

	def test_api_import_test_present(self):
		from pgappforge.pdl.generators import PDLCodeGenerator
		code = PDLCodeGenerator().generate_tests(self._entity())
		assert "test_supplier_invoice_api_imports" in code

	def test_correct_tablename_assertion(self):
		from pgappforge.pdl.generators import PDLCodeGenerator
		code = PDLCodeGenerator().generate_tests(self._entity())
		assert '"fin_supplier_invoice"' in code

	def test_entity_class_name_referenced(self):
		from pgappforge.pdl.generators import PDLCodeGenerator
		code = PDLCodeGenerator().generate_tests(self._entity())
		assert "SupplierInvoice" in code

	def test_is_valid_python_syntax(self):
		import ast
		from pgappforge.pdl.generators import PDLCodeGenerator
		code = PDLCodeGenerator().generate_tests(self._entity())
		ast.parse(code)


# ---------------------------------------------------------------------------
# 5. PDLField validation
# ---------------------------------------------------------------------------

class TestPDLFieldValidation:
	def test_rejects_invalid_name_camel_case(self):
		from pgappforge.pdl.schema import PDLField
		with pytest.raises(ValueError, match="snake_case"):
			PDLField(name="vendorId", type="string")

	def test_rejects_name_starting_with_digit(self):
		from pgappforge.pdl.schema import PDLField
		with pytest.raises(ValueError, match="snake_case"):
			PDLField(name="3amount", type="string")

	def test_rejects_name_with_spaces(self):
		from pgappforge.pdl.schema import PDLField
		with pytest.raises(ValueError, match="snake_case"):
			PDLField(name="vendor id", type="string")

	def test_rejects_unknown_type(self):
		from pgappforge.pdl.schema import PDLField
		with pytest.raises(ValueError, match="Unknown field type"):
			PDLField(name="foo", type="richtext")

	def test_accepts_valid_snake_case_name(self):
		from pgappforge.pdl.schema import PDLField
		f = PDLField(name="invoice_number", type="string")
		assert f.name == "invoice_number"

	def test_accepts_all_builtin_types(self):
		from pgappforge.pdl.schema import PDLField, FIELD_TYPES
		for type_name in FIELD_TYPES:
			f = PDLField(name="x", type=type_name)
			assert f.type == type_name

	def test_fk_field_bypasses_type_check(self):
		"""FK fields may have type='uuid' but the FK pointer is what matters."""
		from pgappforge.pdl.schema import PDLField
		# Should not raise even if type were otherwise invalid when fk is set
		f = PDLField(name="vendor_id", type="uuid", fk="Vendor.id")
		assert f.fk == "Vendor.id"

	def test_entity_rejects_snake_case_name(self):
		from pgappforge.pdl.schema import PDLEntity
		with pytest.raises(ValueError, match="PascalCase"):
			PDLEntity(name="supplier_invoice", table="fin_si")

	def test_entity_rejects_pascal_table(self):
		from pgappforge.pdl.schema import PDLEntity
		with pytest.raises(ValueError, match="snake_case"):
			PDLEntity(name="Invoice", table="FinInvoice")

	def test_entity_accepts_valid_values(self):
		from pgappforge.pdl.schema import PDLEntity
		e = PDLEntity(name="Invoice", table="fin_invoice")
		assert e.name == "Invoice"

	def test_from_dict_propagates_field_error(self):
		from pgappforge.pdl.schema import PDLSchema
		bad = _minimal_dict()
		bad["entities"][0]["fields"].append({"name": "BadName", "type": "string"})
		with pytest.raises(ValueError):
			PDLSchema.from_dict(bad)

	def test_from_dict_propagates_unknown_type_error(self):
		from pgappforge.pdl.schema import PDLSchema
		bad = _minimal_dict()
		bad["entities"][0]["fields"].append({"name": "foo", "type": "richtext"})
		with pytest.raises(ValueError):
			PDLSchema.from_dict(bad)


# ---------------------------------------------------------------------------
# 6. Example PDL file parses without error
# ---------------------------------------------------------------------------

class TestExamplePDLFile:
	def test_example_file_exists(self):
		example = _PROJECT_ROOT / "example.pdl.yaml"
		assert example.exists(), f"example.pdl.yaml not found at {example}"

	def test_example_file_parses(self):
		from pgappforge.pdl.schema import PDLSchema
		example = _PROJECT_ROOT / "example.pdl.yaml"
		schema = PDLSchema.from_yaml(example)
		assert len(schema.entities) >= 1

	def test_example_entity_name_correct(self):
		from pgappforge.pdl.schema import PDLSchema
		example = _PROJECT_ROOT / "example.pdl.yaml"
		schema = PDLSchema.from_yaml(example)
		assert schema.entities[0].name == "SupplierInvoice"

	def test_example_table_correct(self):
		from pgappforge.pdl.schema import PDLSchema
		example = _PROJECT_ROOT / "example.pdl.yaml"
		schema = PDLSchema.from_yaml(example)
		assert schema.entities[0].table == "fin_supplier_invoice"

	def test_example_has_expected_fields(self):
		from pgappforge.pdl.schema import PDLSchema
		example = _PROJECT_ROOT / "example.pdl.yaml"
		schema = PDLSchema.from_yaml(example)
		field_names = {f.name for f in schema.entities[0].fields}
		assert "vendor_id"          in field_names
		assert "invoice_number"     in field_names
		assert "total_amount_cents" in field_names
		assert "status"             in field_names
		assert "line_items"         in field_names

	def test_example_generate_produces_all_artifacts(self):
		from pgappforge.pdl.schema import PDLSchema
		from pgappforge.pdl.generators import PDLCodeGenerator
		example = _PROJECT_ROOT / "example.pdl.yaml"
		schema = PDLSchema.from_yaml(example)
		gen = PDLCodeGenerator()
		results = gen.generate_all(schema)
		# Expect five artifact types for the one entity
		keys = set(results.keys())
		assert any("models.py"    in k for k in keys)
		assert any("migration.py" in k for k in keys)
		assert any("views.py"     in k for k in keys)
		assert any("api.py"       in k for k in keys)
		assert any("test_model.py" in k for k in keys)

	def test_example_model_is_valid_python(self):
		import ast
		from pgappforge.pdl.schema import PDLSchema
		from pgappforge.pdl.generators import PDLCodeGenerator
		example = _PROJECT_ROOT / "example.pdl.yaml"
		schema = PDLSchema.from_yaml(example)
		entity = schema.entities[0]
		code = PDLCodeGenerator().generate_model(entity)
		ast.parse(code)

	def test_example_migration_is_valid_python(self):
		import ast
		from pgappforge.pdl.schema import PDLSchema
		from pgappforge.pdl.generators import PDLCodeGenerator
		example = _PROJECT_ROOT / "example.pdl.yaml"
		schema = PDLSchema.from_yaml(example)
		entity = schema.entities[0]
		code = PDLCodeGenerator().generate_migration(entity)
		ast.parse(code)

	def test_example_view_is_valid_python(self):
		import ast
		from pgappforge.pdl.schema import PDLSchema
		from pgappforge.pdl.generators import PDLCodeGenerator
		example = _PROJECT_ROOT / "example.pdl.yaml"
		schema = PDLSchema.from_yaml(example)
		entity = schema.entities[0]
		code = PDLCodeGenerator().generate_view(entity)
		ast.parse(code)

	def test_example_api_is_valid_python(self):
		import ast
		from pgappforge.pdl.schema import PDLSchema
		from pgappforge.pdl.generators import PDLCodeGenerator
		example = _PROJECT_ROOT / "example.pdl.yaml"
		schema = PDLSchema.from_yaml(example)
		entity = schema.entities[0]
		code = PDLCodeGenerator().generate_api(entity)
		ast.parse(code)

	def test_example_tests_is_valid_python(self):
		import ast
		from pgappforge.pdl.schema import PDLSchema
		from pgappforge.pdl.generators import PDLCodeGenerator
		example = _PROJECT_ROOT / "example.pdl.yaml"
		schema = PDLSchema.from_yaml(example)
		entity = schema.entities[0]
		code = PDLCodeGenerator().generate_tests(entity)
		ast.parse(code)
