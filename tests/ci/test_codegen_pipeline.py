"""Integration tests for the database introspection and codegen pipeline.

NOTE: This project targets PostgreSQL only. The tests here use SQLite as a CI
substitute when a real PostgreSQL instance is unavailable. To test against
PostgreSQL, set the PG_TEST_URI environment variable:
  export PG_TEST_URI=postgresql://user:pass@localhost/test_db
"""
import os
import sys
import shutil
import sqlite3
import py_compile
import tempfile
import pytest

PG_TEST_URI = os.environ.get("PG_TEST_URI")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))


@pytest.fixture(scope="module")
def test_db(tmp_path_factory):
    """Create a realistic SQLite test database."""
    db_path = str(tmp_path_factory.mktemp("db") / "test.db")
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE departments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name VARCHAR(100) NOT NULL UNIQUE,
            code VARCHAR(10) NOT NULL,
            budget DECIMAL(15,2),
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE employees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            first_name VARCHAR(50) NOT NULL,
            last_name VARCHAR(50) NOT NULL,
            email VARCHAR(120) NOT NULL UNIQUE,
            salary DECIMAL(10,2),
            department_id INTEGER REFERENCES departments(id),
            manager_id INTEGER REFERENCES employees(id),
            is_active BOOLEAN DEFAULT 1,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name VARCHAR(200) NOT NULL,
            status VARCHAR(20) DEFAULT 'active',
            department_id INTEGER REFERENCES departments(id)
        );
        CREATE TABLE employee_projects (
            employee_id INTEGER REFERENCES employees(id),
            project_id INTEGER REFERENCES projects(id),
            PRIMARY KEY (employee_id, project_id)
        );
    """)
    conn.close()
    return db_path


@pytest.fixture(scope="module")
def inspector(test_db):
    from pgappforge.cli.generators.database_inspector import EnhancedDatabaseInspector
    uri = os.environ.get("PG_TEST_URI") or f"sqlite:///{test_db}"
    with EnhancedDatabaseInspector(uri) as insp:
        yield insp


class TestDatabaseInspector:
    def test_connects_and_analyzes(self, inspector):
        analysis = inspector.analyze_database()
        assert "tables" in analysis
        assert "departments" in analysis["tables"]
        assert "employees" in analysis["tables"]

    def test_detects_association_table(self, inspector):
        analysis = inspector.analyze_database()
        assert "employee_projects" in analysis.get("association_tables", [])

    def test_detects_relationships(self, inspector):
        analysis = inspector.analyze_database()
        assert len(analysis.get("relationships", [])) > 0

    def test_analyzes_self_referencing(self, inspector):
        table = inspector.analyze_table("employees")
        fk_names = [c.name for c in table.columns if c.foreign_key]
        assert "manager_id" in fk_names

    def test_table_comment_sqlite_graceful(self, inspector):
        # SQLite doesn't support comments — should not raise
        table = inspector.analyze_table("departments")
        assert table is not None


class TestModelGenerator:
    def test_generates_models(self, inspector):
        from pgappforge.cli.generators.model_generator import (
            EnhancedModelGenerator, ModelGenerationConfig
        )
        gen = EnhancedModelGenerator(inspector, ModelGenerationConfig(generate_pydantic=False))
        result = gen.generate_all_models()
        assert "models.py" in result
        assert "class Departments" in result["models.py"]
        assert "class Employees" in result["models.py"]

    def test_generated_models_syntax_valid(self, inspector):
        from pgappforge.cli.generators.model_generator import (
            EnhancedModelGenerator, ModelGenerationConfig
        )
        gen = EnhancedModelGenerator(inspector, ModelGenerationConfig(generate_pydantic=False))
        result = gen.generate_all_models()
        with tempfile.NamedTemporaryFile(suffix=".py", delete=False, mode="w") as f:
            f.write(result["models.py"])
            f.flush()
            py_compile.compile(f.name, doraise=True)

    def test_association_table_stats(self, inspector):
        analysis = inspector.analyze_database()
        # employee_projects is detected as an association table
        assert "employee_projects" in analysis.get("association_tables", [])

    def test_pydantic_schemas_valid_syntax(self, inspector):
        from pgappforge.cli.generators.model_generator import (
            EnhancedModelGenerator, ModelGenerationConfig
        )
        gen = EnhancedModelGenerator(inspector, ModelGenerationConfig(generate_pydantic=True))
        result = gen.generate_all_models()
        assert "schemas.py" in result
        with tempfile.NamedTemporaryFile(suffix=".py", delete=False, mode="w") as f:
            f.write(result["schemas.py"])
            f.flush()
            py_compile.compile(f.name, doraise=True)


class TestFullAppGenerator:
    def test_generates_complete_app(self, test_db, tmp_path):
        from pgappforge.cli.generators.database_inspector import EnhancedDatabaseInspector
        from pgappforge.cli.generators.app_generator import FullAppGenerator, AppGenerationConfig

        uri = os.environ.get("PG_TEST_URI") or f"sqlite:///{test_db}"
        with EnhancedDatabaseInspector(uri) as insp:
            config = AppGenerationConfig(
                app_name="TestApp",
                enable_docker=False,
                enable_testing=False,
                enable_ci_cd=False,
            )
            result = FullAppGenerator(insp, config, str(tmp_path)).generate_complete_app()

        assert result["status"] == "success"
        assert result["files_generated"] > 0

    def test_all_generated_python_valid_syntax(self, test_db, tmp_path):
        from pgappforge.cli.generators.database_inspector import EnhancedDatabaseInspector
        from pgappforge.cli.generators.app_generator import FullAppGenerator, AppGenerationConfig

        out = tmp_path / "app"
        uri = os.environ.get("PG_TEST_URI") or f"sqlite:///{test_db}"
        with EnhancedDatabaseInspector(uri) as insp:
            config = AppGenerationConfig(app_name="SyntaxTest", enable_docker=False)
            FullAppGenerator(insp, config, str(out)).generate_complete_app()

        errors = []
        for root, _, files in os.walk(out):
            for f in files:
                if f.endswith(".py"):
                    path = os.path.join(root, f)
                    try:
                        py_compile.compile(path, doraise=True)
                    except py_compile.PyCompileError as e:
                        errors.append(str(e))

        assert errors == [], f"Syntax errors in generated code:\n" + "\n".join(errors)

    def test_key_files_generated(self, test_db, tmp_path):
        from pgappforge.cli.generators.database_inspector import EnhancedDatabaseInspector
        from pgappforge.cli.generators.app_generator import FullAppGenerator, AppGenerationConfig

        uri = os.environ.get("PG_TEST_URI") or f"sqlite:///{test_db}"
        with EnhancedDatabaseInspector(uri) as insp:
            config = AppGenerationConfig(app_name="FileTest", enable_docker=False)
            FullAppGenerator(insp, config, str(tmp_path)).generate_complete_app()

        expected = [
            "app/__init__.py",
            "app/models/models.py",
            "app/api/api.py",
            "config/config.py",
            "app/templates/base.html",
        ]
        for rel_path in expected:
            full = tmp_path / rel_path
            assert full.exists(), f"Expected generated file missing: {rel_path}"
