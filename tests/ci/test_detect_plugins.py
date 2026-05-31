"""Tests for MobileGenerator._detect_plugins.

The key fix under test: _detect_plugins uses t.columns (TableInfo attribute)
not t.get("columns", []), so it must not raise AttributeError on real objects.
"""
import sys
import os
import pytest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))


def _make_table(col_names: list[str]) -> mock.MagicMock:
	"""Build a TableInfo-like mock with .columns containing objects with .name."""
	t = mock.MagicMock()
	t.is_association_table = False
	cols = []
	for name in col_names:
		col = mock.MagicMock()
		col.name = name
		cols.append(col)
	t.columns = cols
	return t


def _make_generator(tables: dict[str, list[str]]) -> "MobileGenerator":
	from pgappforge.cli.generators.mobile_generator import MobileGenerator, MobileGenerationConfig
	cfg = MobileGenerationConfig(app_name="TestApp")
	# MobileGenerator requires an inspector — pass a minimal mock
	insp = mock.MagicMock()
	gen = object.__new__(MobileGenerator)
	gen.inspector = insp
	gen.config = cfg
	return gen


# ── BPM ───────────────────────────────────────────────────────────────────────

def test_bpm_true_on_bpm_prefix():
	gen = _make_generator({})
	tables = {"bpm_process": _make_table(["id"])}
	plugins = gen._detect_plugins(tables)
	assert plugins["bpm"] is True


def test_bpm_false_on_unrelated_table():
	gen = _make_generator({})
	tables = {"employees": _make_table(["id"])}
	plugins = gen._detect_plugins(tables)
	assert plugins["bpm"] is False


# ── Approval ──────────────────────────────────────────────────────────────────

def test_approval_true():
	gen = _make_generator({})
	tables = {"approval_request": _make_table(["id"])}
	plugins = gen._detect_plugins(tables)
	assert plugins["approval"] is True


# ── ICD-10 ────────────────────────────────────────────────────────────────────

def test_icd10_true():
	gen = _make_generator({})
	tables = {"icd10_code": _make_table(["id", "code"])}
	plugins = gen._detect_plugins(tables)
	assert plugins["icd10"] is True


def test_icd10_false_when_absent():
	gen = _make_generator({})
	tables = {"employees": _make_table(["id"])}
	plugins = gen._detect_plugins(tables)
	assert plugins["icd10"] is False


# ── SNOMED ────────────────────────────────────────────────────────────────────

def test_snomed_true():
	gen = _make_generator({})
	tables = {"snomed_concept": _make_table(["id"])}
	plugins = gen._detect_plugins(tables)
	assert plugins["snomed"] is True


# ── Wallet ────────────────────────────────────────────────────────────────────

def test_wallet_true():
	gen = _make_generator({})
	tables = {"wallet_account": _make_table(["id"])}
	plugins = gen._detect_plugins(tables)
	assert plugins["wallet"] is True


# ── Offline ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("col_names,expected", [
	(["id", "updated_at"], True),
	(["id", "deleted_at"], True),
	(["id", "synced_at"], True),
	(["id", "name"],      False),
])
def test_offline_detection(col_names, expected):
	gen = _make_generator({})
	tables = {"orders": _make_table(col_names)}
	plugins = gen._detect_plugins(tables)
	assert plugins["offline"] is expected


# ── Voice ─────────────────────────────────────────────────────────────────────

def test_voice_false_when_not_in_features():
	from pgappforge.cli.generators.mobile_generator import MobileGenerator, MobileGenerationConfig
	cfg = MobileGenerationConfig(app_name="TestApp", features=["auth", "list"])
	gen = object.__new__(MobileGenerator)
	gen.inspector = mock.MagicMock()
	gen.config = cfg
	tables = {"orders": _make_table(["id"])}
	plugins = gen._detect_plugins(tables)
	assert plugins["voice"] is False


def test_voice_true_when_in_features():
	from pgappforge.cli.generators.mobile_generator import MobileGenerator, MobileGenerationConfig
	cfg = MobileGenerationConfig(app_name="TestApp", features=["auth", "voice"])
	gen = object.__new__(MobileGenerator)
	gen.inspector = mock.MagicMock()
	gen.config = cfg
	tables = {"orders": _make_table(["id"])}
	plugins = gen._detect_plugins(tables)
	assert plugins["voice"] is True


# ── Regression: no AttributeError on TableInfo-like objects ───────────────────

def test_no_attribute_error_on_tableinfo_objects():
	"""_detect_plugins must not call t.get() — TableInfo objects have .columns, not dict API."""
	gen = _make_generator({})
	t = _make_table(["id", "updated_at"])
	# Make .get raise to prove the code path is never hit
	t.get = mock.MagicMock(side_effect=AttributeError("TableInfo has no .get()"))
	tables = {"orders": t}
	# Must not raise
	plugins = gen._detect_plugins(tables)
	assert plugins["offline"] is True
	t.get.assert_not_called()
