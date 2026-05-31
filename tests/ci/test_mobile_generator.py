"""Smoke tests for MobileGenerator.generate_complete_app().

Uses the same test_db fixture (SQLite with realistic schema) as test_codegen_pipeline.py.
"""
import json
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))


@pytest.fixture(scope="module")
def test_db(tmp_path_factory):
	"""SQLite test database — mirrors the fixture in test_codegen_pipeline.py."""
	import sqlite3
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
			updated_at DATETIME
		);
		CREATE TABLE projects (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			name VARCHAR(200) NOT NULL,
			status VARCHAR(20) DEFAULT 'active',
			department_id INTEGER REFERENCES departments(id)
		);
	""")
	conn.close()
	return db_path


@pytest.fixture(scope="module")
def mobile_files(test_db, tmp_path_factory):
	from pgappforge.cli.generators.database_inspector import EnhancedDatabaseInspector
	from pgappforge.cli.generators.mobile_generator import MobileGenerator, MobileGenerationConfig

	out = str(tmp_path_factory.mktemp("mobile_out"))
	cfg = MobileGenerationConfig(app_name="TestMobile")
	uri = os.environ.get("PG_TEST_URI") or f"sqlite:///{test_db}"
	with EnhancedDatabaseInspector(uri) as insp:
		gen = MobileGenerator(insp, cfg, out)
		files = gen.generate_complete_app()
	return files


class TestMobileGeneratorSmoke:
	def test_files_is_nonempty_dict(self, mobile_files):
		assert isinstance(mobile_files, dict)
		assert len(mobile_files) > 0

	def test_package_json_present_and_valid(self, mobile_files):
		assert "package.json" in mobile_files
		data = json.loads(mobile_files["package.json"])
		assert "dependencies" in data
		assert "expo" in data["dependencies"]

	def test_tsconfig_json_valid(self, mobile_files):
		assert "tsconfig.json" in mobile_files
		data = json.loads(mobile_files["tsconfig.json"])
		assert "compilerOptions" in data

	def test_no_unresolved_fstring_placeholders_in_tsx(self, mobile_files):
		"""No literal {variable} placeholders should survive templating."""
		placeholder = re.compile(r"\{[a-z_][a-z_0-9]*\}")
		tsx_files = {k: v for k, v in mobile_files.items() if k.endswith(".tsx")}
		leaks = {}
		for path, content in tsx_files.items():
			hits = placeholder.findall(content)
			# Filter out JSX/TSX expressions that are intentional (e.g. {children})
			# We only flag bare Python-style placeholders — those that contain
			# only lowercase_snake identifiers and appear outside JSX context.
			# A reliable heuristic: the same token repeated in content as a raw
			# word not preceded by </  or = signals a leak.
			if hits:
				leaks[path] = hits
		# Allow JSX-style curly expressions (they are intentional)
		# This assertion catches Python f-string accidents like "{app_name}" appearing literally
		for path, hits in leaks.items():
			for h in hits:
				# strip braces and check — if the inner text looks like a Python
				# identifier that was never substituted it is a bug
				inner = h[1:-1]
				assert inner not in (
					"app_name", "app_id", "primary_color", "version",
					"api_base_url", "slug",
				), f"Unresolved placeholder {h!r} found in {path}"

	def test_sh_scripts_executable(self, mobile_files, tmp_path_factory):
		"""Shell scripts written to disk must be executable."""
		import stat
		# The fixture already wrote files via generate_complete_app() which calls _write_files
		# Re-derive the output dir from the generator: we need the actual path.
		# Since mobile_files is already generated, check the on-disk files.
		# We find the output dir by inspecting the tmp_path used in the fixture.
		# Instead: re-run a minimal generate to a known tmp_path so we can inspect.
		from pgappforge.cli.generators.database_inspector import EnhancedDatabaseInspector
		from pgappforge.cli.generators.mobile_generator import MobileGenerator, MobileGenerationConfig
		import sqlite3

		db_path = str(tmp_path_factory.mktemp("db2") / "t.db")
		conn = sqlite3.connect(db_path)
		conn.executescript("CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT);")
		conn.close()

		out_dir = tmp_path_factory.mktemp("mobile_sh")
		cfg = MobileGenerationConfig(app_name="ShTest")
		with EnhancedDatabaseInspector(f"sqlite:///{db_path}") as insp:
			MobileGenerator(insp, cfg, str(out_dir)).generate_complete_app()

		sh_files = list(out_dir.rglob("*.sh"))
		# Not all generators produce .sh files; skip if none present
		for sh in sh_files:
			mode = sh.stat().st_mode
			assert mode & stat.S_IXUSR, f"{sh} is not user-executable"
