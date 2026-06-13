"""
PgAppForge Domain Language (PDL)
=================================
A YAML-schema DSL that deterministically generates SQLAlchemy models,
Alembic migrations, FAB views, REST API stubs, and pytest fixtures —
no LLM required.

Quick start
-----------
1. Write a PDL YAML file (see ``example.pdl.yaml`` in the project root):

	.. code-block:: yaml

		version: "1.0"
		namespace: myapp.finance
		entities:
		  - name: Invoice
		    table: fin_invoice
		    fields:
		      - name: amount_cents
		        type: money
		        required: true

2. Generate code from the CLI::

		flask forge gen pdl myschema.pdl.yaml --output-dir ./generated

3. Or use the Python API::

		from pgappforge.pdl.schema import PDLSchema
		from pgappforge.pdl.generators import PDLCodeGenerator

		schema = PDLSchema.from_yaml("myschema.pdl.yaml")
		gen = PDLCodeGenerator()
		artifacts = gen.generate_all(schema)   # dict[name, code_str]

Supported field types
---------------------
string, text, integer, biginteger, money (BigInteger cents), float,
decimal, boolean, date, datetime, uuid, jsonb, enum, phone, email, url.

Every entity automatically gets:
  * UUID v7 primary key (``include_uuid_pk=true``)
  * ``tenant_id`` column (``include_tenant_id=true``)
  * ``created_at`` / ``updated_at`` audit timestamps
    (``include_audit_timestamps=true``)

Relationship fields
-------------------
Set ``fk: "ModelName.id"`` on any field to emit a ``ForeignKey`` column.
The model name is converted to snake_case table name automatically.

Generated artefacts
-------------------
================  ===================================================
``model``         SQLAlchemy 2.x model class
``migration``     Alembic ``upgrade()`` / ``downgrade()`` script
``view``          FAB ``ModelView`` + ``BaseERPView`` dashboard
``api``           REST endpoint stub with ``list`` / ``detail`` routes
``tests``         pytest import smoke tests
================  ===================================================
"""

from .schema import PDLSchema, PDLEntity, PDLField, FIELD_TYPES
from .generators import PDLCodeGenerator

__all__ = [
	"PDLSchema",
	"PDLEntity",
	"PDLField",
	"FIELD_TYPES",
	"PDLCodeGenerator",
]
