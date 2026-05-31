"""
Tests for ERD Designer security and correctness fixes.

Covers:
- _qi() identifier validation
- _quote_default() safe quoting
- _op_to_sql_list() with FKs, UNIQUE, reserved word tables
- apply_changes() atomicity (inner try/except removed)
- import_sql allowlist
- _to_mermaid_str() valid output
- Path traversal prevention in generate_app
- _generate_rollback() inverse DDL
"""

from __future__ import annotations

import pytest


# ─── Identifier quoting ───────────────────────────────────────────────────────

def test_qi_valid_identifiers():
    from pgappforge.views.erd_schema_manager import _qi
    assert _qi("orders") == '"orders"'
    assert _qi("my_table_123") == '"my_table_123"'
    assert _qi("user") == '"user"'   # reserved word — quoting makes it safe
    assert _qi("_internal") == '"_internal"'


def test_qi_rejects_dangerous_names():
    from pgappforge.views.erd_schema_manager import _qi
    for bad in [
        "x; DROP TABLE users; --",
        "a b",
        "a-b",
        "a.b",
        "",
        "123start",
        "a" * 64,   # 64 chars > 63 limit
    ]:
        with pytest.raises(ValueError, match="Invalid PostgreSQL identifier"):
            _qi(bad)


def test_qschema_with_and_without_schema():
    from pgappforge.views.erd_schema_manager import _qschema
    assert _qschema("orders") == '"orders"'
    assert _qschema("orders", "myschema") == '"myschema"."orders"'


# ─── Default quoting ─────────────────────────────────────────────────────────

def test_quote_default_string_literals():
    from pgappforge.views.erd_schema_manager import _quote_default
    assert _quote_default("pending") == "'pending'"
    assert _quote_default("it's") == "'it''s'"  # internal quote escaped
    assert _quote_default("draft") == "'draft'"


def test_quote_default_numeric_pass_through():
    from pgappforge.views.erd_schema_manager import _quote_default
    assert _quote_default(42)    == "42"
    assert _quote_default(3.14)  == "3.14"
    assert _quote_default(-1)    == "-1"
    assert _quote_default("100") == "100"


def test_quote_default_sql_expressions_pass_through():
    from pgappforge.views.erd_schema_manager import _quote_default
    assert _quote_default("NOW()") == "NOW()"
    assert _quote_default("CURRENT_TIMESTAMP") == "CURRENT_TIMESTAMP"
    assert _quote_default("gen_random_uuid()") == "gen_random_uuid()"
    assert _quote_default("nextval('my_seq')") == "nextval('my_seq')"
    assert _quote_default("true") == "true"
    assert _quote_default("null") == "null"


# ─── DDL generation ──────────────────────────────────────────────────────────

def test_op_to_sql_list_create_table_basic():
    from pgappforge.views.erd_schema_manager import ERDSchemaManager
    import unittest.mock as mock
    mgr = ERDSchemaManager(engine=mock.MagicMock())
    stmts = mgr._op_to_sql_list({
        "op": "create_table",
        "table": "orders",
        "columns": [
            {"name": "id", "type": "SERIAL", "pk": True, "nullable": False},
            {"name": "status", "type": "VARCHAR(20)", "nullable": True, "default": "pending"},
        ],
    })
    assert len(stmts) == 1
    sql = stmts[0]
    assert '"orders"' in sql
    assert '"id"' in sql
    assert '"status"' in sql
    assert "PRIMARY KEY" in sql
    assert "'pending'" in sql  # default is quoted as string literal


def test_op_to_sql_list_emits_unique():
    from pgappforge.views.erd_schema_manager import ERDSchemaManager
    import unittest.mock as mock
    mgr = ERDSchemaManager(engine=mock.MagicMock())
    stmts = mgr._op_to_sql_list({
        "op": "create_table",
        "table": "customers",
        "columns": [
            {"name": "id",    "type": "SERIAL", "pk": True},
            {"name": "email", "type": "TEXT",   "unique": True, "nullable": False},
        ],
    })
    sql = stmts[0]
    assert "UNIQUE" in sql
    assert '"email"' in sql


def test_op_to_sql_list_emits_fk_constraint():
    from pgappforge.views.erd_schema_manager import ERDSchemaManager
    import unittest.mock as mock
    mgr = ERDSchemaManager(engine=mock.MagicMock())
    stmts = mgr._op_to_sql_list({
        "op": "create_table",
        "table": "order_items",
        "columns": [
            {"name": "id",       "type": "SERIAL", "pk": True},
            {"name": "order_id", "type": "INTEGER", "fk": "orders.id"},
        ],
    })
    # Should have 2 statements: CREATE TABLE + ALTER TABLE ... ADD CONSTRAINT
    assert len(stmts) == 2
    assert "CREATE TABLE" in stmts[0]
    assert "ADD CONSTRAINT" in stmts[1]
    assert "FOREIGN KEY" in stmts[1]
    assert '"orders"' in stmts[1]


def test_op_to_sql_list_reserved_word_table():
    from pgappforge.views.erd_schema_manager import ERDSchemaManager
    import unittest.mock as mock
    mgr = ERDSchemaManager(engine=mock.MagicMock())
    stmts = mgr._op_to_sql_list({
        "op": "create_table",
        "table": "user",  # reserved word
        "columns": [{"name": "id", "type": "SERIAL", "pk": True}],
    })
    sql = stmts[0]
    assert '"user"' in sql   # table name must be quoted


def test_op_to_sql_list_add_fk_quotes_identifiers():
    from pgappforge.views.erd_schema_manager import ERDSchemaManager
    import unittest.mock as mock
    mgr = ERDSchemaManager(engine=mock.MagicMock())
    stmts = mgr._op_to_sql_list({
        "op": "add_fk",
        "table": "orders",
        "column": "customer_id",
        "ref_table": "customers",
        "ref_column": "id",
    })
    sql = stmts[0]
    assert '"orders"' in sql
    assert '"customer_id"' in sql
    assert '"customers"' in sql
    assert '"id"' in sql


def test_op_to_sql_list_rejects_injection_in_table_name():
    from pgappforge.views.erd_schema_manager import ERDSchemaManager
    import unittest.mock as mock
    mgr = ERDSchemaManager(engine=mock.MagicMock())
    with pytest.raises(ValueError):
        mgr._op_to_sql_list({
            "op": "drop_table",
            "table": "users; DROP SCHEMA public CASCADE --",
        })


def test_op_to_sql_list_rename_table():
    from pgappforge.views.erd_schema_manager import ERDSchemaManager
    import unittest.mock as mock
    mgr = ERDSchemaManager(engine=mock.MagicMock())
    stmts = mgr._op_to_sql_list({
        "op": "rename_table", "table": "orders", "new_name": "purchase_orders"
    })
    assert '"orders"' in stmts[0]
    assert '"purchase_orders"' in stmts[0]
    assert "RENAME TO" in stmts[0]


# ─── apply_changes atomicity ──────────────────────────────────────────────────

def test_apply_changes_dry_run():
    from pgappforge.views.erd_schema_manager import ERDSchemaManager
    import unittest.mock as mock
    engine = mock.MagicMock()
    mgr = ERDSchemaManager(engine=engine)
    result = mgr.apply_changes(
        [{"op": "create_table", "table": "test", "columns": [{"name": "id", "type": "SERIAL", "pk": True}]}],
        dry_run=True,
    )
    assert result["dry_run"] is True
    assert result["would_apply"] >= 1
    assert len(result["sql"]) >= 1
    # Engine should NOT have been called
    engine.begin.assert_not_called()


def test_apply_changes_invalid_identifier_returns_error():
    from pgappforge.views.erd_schema_manager import ERDSchemaManager
    import unittest.mock as mock
    mgr = ERDSchemaManager(engine=mock.MagicMock())
    result = mgr.apply_changes([
        {"op": "create_table", "table": "bad name!", "columns": []}
    ])
    assert result["applied"] == 0
    assert len(result["errors"]) > 0


# ─── import_sql allowlist ─────────────────────────────────────────────────────

def test_import_sql_rejects_dml():
    from pgappforge.views.erd_schema_manager import ERDSchemaManager
    import unittest.mock as mock
    mgr = ERDSchemaManager(engine=mock.MagicMock())
    for bad_sql in [
        "DELETE FROM users",
        "INSERT INTO users VALUES (1)",
        "UPDATE users SET name='x'",
        "DROP TABLE users",
    ]:
        result = mgr.import_sql(bad_sql)
        assert result["applied"] == 0, f"Should reject: {bad_sql}"
        assert result["errors"]


def test_import_sql_allows_ddl():
    from pgappforge.views.erd_schema_manager import ERDSchemaManager
    import unittest.mock as mock
    # Mock engine so we don't need a real DB
    engine = mock.MagicMock()
    conn  = engine.begin.return_value.__enter__.return_value
    mgr   = ERDSchemaManager(engine=engine)
    result = mgr.import_sql("CREATE TABLE x (id SERIAL PRIMARY KEY)")
    # Engine should have been called (allowlist passed)
    assert engine.begin.called


# ─── Mermaid output ───────────────────────────────────────────────────────────

def test_to_mermaid_str_valid_syntax():
    from pgappforge.views.erd_schema_manager import _to_mermaid_str
    schema = {
        "tables": [
            {"name": "orders", "columns": [
                {"name": "id", "type": "SERIAL", "pk": True, "fk": None},
                {"name": "customer_id", "type": "INTEGER", "pk": False, "fk": "customers"},
            ]},
            {"name": "customers", "columns": [
                {"name": "id", "type": "SERIAL", "pk": True, "fk": None},
            ]},
        ],
        "relationships": [
            {"from_table": "orders", "to_table": "customers"},
        ],
    }
    mermaid = _to_mermaid_str(schema)
    assert mermaid.startswith("erDiagram")
    assert "ORDERS" in mermaid
    assert "CUSTOMERS" in mermaid
    assert "||--o{" in mermaid   # correct cardinality arrow
    # No unterminated strings
    lines = mermaid.split("\n")
    for line in lines:
        if ': "' in line:
            assert line.count('"') % 2 == 0, f"Unterminated string in: {line}"


def test_to_mermaid_str_deduplicates_relationships():
    from pgappforge.views.erd_schema_manager import _to_mermaid_str
    schema = {
        "tables": [{"name": "a", "columns": []}, {"name": "b", "columns": []}],
        "relationships": [
            {"from_table": "a", "to_table": "b"},
            {"from_table": "a", "to_table": "b"},  # duplicate
        ],
    }
    mermaid = _to_mermaid_str(schema)
    # Should appear only once
    assert mermaid.count("||--o{") == 1


# ─── Path traversal ───────────────────────────────────────────────────────────

def test_safe_output_dir_rejects_traversal():
    from flask import Flask
    from pgappforge.views.erd_designer import _safe_output_dir

    app = Flask(__name__)
    app.config["FAB_CODEGEN_OUTPUT_ROOT"] = "/tmp/pgaf_test_root"
    with app.app_context():
        # Traversal attempt
        with pytest.raises(Exception):
            _safe_output_dir("../../etc/passwd", "app")


def test_safe_output_dir_allows_valid_path():
    import pathlib
    from flask import Flask
    from pgappforge.views.erd_designer import _safe_output_dir

    app = Flask(__name__)
    app.config["FAB_CODEGEN_OUTPUT_ROOT"] = "/tmp/pgaf_test_root"
    with app.app_context():
        root   = pathlib.Path("/tmp/pgaf_test_root").resolve()
        result = _safe_output_dir(None, "MyApp")
        # Result must be under the resolved root (handles macOS /private/tmp symlink)
        assert str(result).startswith(str(root))


# ─── Rollback generation ──────────────────────────────────────────────────────

def test_generate_rollback_create_table():
    from pgappforge.views.erd_schema_manager import _generate_rollback
    ops = [{"op": "create_table", "table": "widgets", "columns": []}]
    rollback = _generate_rollback(ops, [])
    assert len(rollback) == 1
    assert "DROP TABLE" in rollback[0]
    assert '"widgets"' in rollback[0]


def test_generate_rollback_add_column():
    from pgappforge.views.erd_schema_manager import _generate_rollback
    ops = [{"op": "add_column", "table": "orders", "column": {"name": "note", "type": "TEXT"}}]
    rollback = _generate_rollback(ops, [])
    assert any("DROP COLUMN" in s for s in rollback)


# ─── erd_models syntax ────────────────────────────────────────────────────────

def test_erd_models_importable():
    from pgappforge.models.erd_models import ErdDesign, ErdMigrationLog
    assert ErdDesign.__tablename__ == "erd_design"
    assert ErdMigrationLog.__tablename__ == "erd_migration_log"
