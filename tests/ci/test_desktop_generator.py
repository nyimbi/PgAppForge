"""Smoke tests for DesktopGenerator.generate()."""
import os
import py_compile
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))


class TestDesktopGenerator:
	def test_generates_nonempty_dict(self, tmp_path):
		from pgappforge.cli.generators.desktop_generator import DesktopConfig, DesktopGenerator
		cfg = DesktopConfig(app_name="TestDesktop")
		files = DesktopGenerator(cfg, tmp_path).generate()
		assert isinstance(files, dict)
		assert len(files) > 0

	def test_key_files_present(self, tmp_path):
		from pgappforge.cli.generators.desktop_generator import DesktopConfig, DesktopGenerator
		cfg = DesktopConfig(app_name="TestDesktop")
		files = DesktopGenerator(cfg, tmp_path).generate()
		assert "run_desktop.py" in files
		assert "desktop.config.json" in files
		assert "requirements-desktop.txt" in files

	def test_generated_python_compiles(self, tmp_path):
		from pgappforge.cli.generators.desktop_generator import DesktopConfig, DesktopGenerator
		cfg = DesktopConfig(app_name="TestDesktop")
		DesktopGenerator(cfg, tmp_path).generate()

		errors = []
		for py_file in tmp_path.rglob("*.py"):
			try:
				py_compile.compile(str(py_file), doraise=True)
			except py_compile.PyCompileError as exc:
				errors.append(f"{py_file}: {exc}")

		assert errors == [], "Syntax errors in generated Python:\n" + "\n".join(errors)

	def test_app_id_auto_generated(self, tmp_path):
		from pgappforge.cli.generators.desktop_generator import DesktopConfig, DesktopGenerator
		cfg = DesktopConfig(app_name="My Cool App")
		assert cfg.app_id == "com.pgappforge.mycoolapp"

	def test_pyside6_target(self, tmp_path):
		from pgappforge.cli.generators.desktop_generator import DesktopConfig, DesktopGenerator
		cfg = DesktopConfig(app_name="TestDesktop", target="pyside6")
		files = DesktopGenerator(cfg, tmp_path).generate()
		assert "run_desktop_qt.py" in files
		assert "run_desktop.py" not in files

	def test_both_target(self, tmp_path):
		from pgappforge.cli.generators.desktop_generator import DesktopConfig, DesktopGenerator
		cfg = DesktopConfig(app_name="TestDesktop", target="both")
		files = DesktopGenerator(cfg, tmp_path).generate()
		assert "run_desktop.py" in files
		assert "run_desktop_qt.py" in files

	def test_sh_scripts_executable(self, tmp_path):
		import stat
		from pgappforge.cli.generators.desktop_generator import DesktopConfig, DesktopGenerator
		cfg = DesktopConfig(app_name="TestDesktop")
		DesktopGenerator(cfg, tmp_path).generate()

		sh_files = list(tmp_path.rglob("*.sh"))
		for sh in sh_files:
			mode = sh.stat().st_mode
			assert mode & stat.S_IXUSR, f"{sh} is not user-executable"
