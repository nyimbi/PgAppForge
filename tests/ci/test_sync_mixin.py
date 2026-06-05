"""
tests/ci/test_sync_mixin.py

Structural + unit tests for SyncMixin and helpers
(pgappforge/plugins/offline/sync_mixin.py).

Strategy
--------
- No real DB, no Flask app context needed.
- _row_to_dict and _is_new are pure functions; tested directly.
- SyncMixin class-attribute defaults verified by introspection.
- SQLAlchemy inspect is monkey-patched where needed.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Import smoke test
# ---------------------------------------------------------------------------

class TestImports:

	def test_sync_mixin_imports_clean(self):
		from pgappforge.plugins.offline.sync_mixin import SyncMixin, _row_to_dict, _is_new
		assert SyncMixin is not None
		assert callable(_row_to_dict)
		assert callable(_is_new)

	def test_sync_limit_is_module_level(self):
		import pgappforge.plugins.offline.sync_mixin as _mod
		assert hasattr(_mod, "_SYNC_LIMIT")
		assert _mod._SYNC_LIMIT == 500
		# Must NOT be a class attribute on SyncMixin
		assert "_SYNC_LIMIT" not in _mod.SyncMixin.__dict__


# ---------------------------------------------------------------------------
# SyncMixin class-attribute defaults
# ---------------------------------------------------------------------------

class TestSyncMixinClassAttributes:

	def setup_method(self):
		from pgappforge.plugins.offline.sync_mixin import SyncMixin
		self.SyncMixin = SyncMixin

	def test_sync_owner_field_default(self):
		assert self.SyncMixin.sync_owner_field == "owner_id"

	def test_sync_tenant_field_default(self):
		assert self.SyncMixin.sync_tenant_field is None

	def test_sync_writable_fields_default(self):
		assert self.SyncMixin.sync_writable_fields is None

	def test_all_three_attributes_exist(self):
		for attr in ("sync_owner_field", "sync_tenant_field", "sync_writable_fields"):
			assert hasattr(self.SyncMixin, attr), f"Missing attribute: {attr}"


# ---------------------------------------------------------------------------
# _row_to_dict
# ---------------------------------------------------------------------------

class TestRowToDict:
	"""
	_row_to_dict() uses a lazy import:
	    from sqlalchemy import inspect as sa_inspect
	Patch target is therefore sqlalchemy.inspect (the source), not a module attribute.
	"""

	def setup_method(self):
		from pgappforge.plugins.offline.sync_mixin import _row_to_dict
		self._row_to_dict = _row_to_dict

	def _mapper_for(self, row, keys):
		"""Return a mapper mock whose .columns list covers the given keys."""
		mapper = MagicMock()
		mapper.columns = [_make_col(k) for k in keys]
		return mapper

	def test_handles_datetime_value(self):
		row = MagicMock()
		row.created_on = datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
		mapper = self._mapper_for(row, ["created_on"])

		with patch("sqlalchemy.inspect", return_value=mapper):
			result = self._row_to_dict(row)

		assert isinstance(result["created_on"], str)
		assert "2025" in result["created_on"]

	def test_handles_none_values(self):
		row = MagicMock()
		row.note = None
		mapper = self._mapper_for(row, ["note"])

		with patch("sqlalchemy.inspect", return_value=mapper):
			result = self._row_to_dict(row)

		assert result["note"] is None

	def test_handles_scalar_types(self):
		row = MagicMock()
		row.count = 42
		row.ratio = 3.14
		row.active = True
		row.name = "hello"
		mapper = self._mapper_for(row, ["count", "ratio", "active", "name"])

		with patch("sqlalchemy.inspect", return_value=mapper):
			result = self._row_to_dict(row)

		assert result["count"] == 42
		assert result["ratio"] == 3.14
		assert result["active"] is True
		assert result["name"] == "hello"

	def test_fallback_uses_vars_on_inspect_failure(self):
		"""When sa_inspect raises, _row_to_dict falls back to vars(row)."""
		# Must use instance attributes — class attributes don't appear in vars(instance)
		class _PlainRow:
			def __init__(self):
				self.status = "ok"
				self._sa_internal = "ignored"

		row = _PlainRow()

		with patch("sqlalchemy.inspect", side_effect=Exception("no mapper")):
			result = self._row_to_dict(row)

		assert result.get("status") == "ok"
		assert "_sa_internal" not in result

	def test_non_serializable_value_is_stringified(self):
		row = MagicMock()
		row.blob = object()  # not str/int/float/bool/None/datetime
		mapper = self._mapper_for(row, ["blob"])

		with patch("sqlalchemy.inspect", return_value=mapper):
			result = self._row_to_dict(row)

		assert isinstance(result["blob"], str)


# ---------------------------------------------------------------------------
# _is_new
# ---------------------------------------------------------------------------

class TestIsNew:

	def setup_method(self):
		from pgappforge.plugins.offline.sync_mixin import _is_new
		self._is_new = _is_new

	def test_returns_true_for_row_created_after_since(self):
		since = datetime(2025, 1, 1, tzinfo=timezone.utc)
		row = MagicMock(spec=[])
		row.created_on = datetime(2025, 6, 1, tzinfo=timezone.utc)
		assert self._is_new(row, since) is True

	def test_returns_false_for_row_created_before_since(self):
		since = datetime(2025, 6, 1, tzinfo=timezone.utc)
		row = MagicMock(spec=[])
		row.created_on = datetime(2020, 1, 1, tzinfo=timezone.utc)
		assert self._is_new(row, since) is False

	def test_returns_false_when_created_on_equals_since(self):
		ts = datetime(2025, 3, 15, tzinfo=timezone.utc)
		row = MagicMock(spec=[])
		row.created_on = ts
		# since == created_on → not strictly greater → False
		assert self._is_new(row, ts) is False

	def test_returns_false_without_created_column(self):
		since = datetime(2025, 1, 1, tzinfo=timezone.utc)
		row = MagicMock(spec=[])  # spec=[] means hasattr returns False for everything
		# Neither created_on nor created_at present → _is_new uses getattr with None default
		# getattr(row, 'created_on', None) raises AttributeError on spec=[] mock —
		# but _is_new uses `getattr(row, ...) or getattr(row, ...)` which will get None
		# Let's use a plain object with no date attrs
		class _NoDateRow:
			pass
		assert self._is_new(_NoDateRow(), since) is False

	def test_uses_created_at_fallback_when_created_on_missing(self):
		since = datetime(2024, 1, 1, tzinfo=timezone.utc)

		class _Row:
			created_at = datetime(2025, 5, 1, tzinfo=timezone.utc)

		assert self._is_new(_Row(), since) is True

	def test_naive_datetime_treated_as_utc(self):
		"""A naive created_on is coerced to UTC before comparison."""
		since = datetime(2024, 1, 1, tzinfo=timezone.utc)

		class _Row:
			created_on = datetime(2025, 3, 1)  # naive

		assert self._is_new(_Row(), since) is True

	def test_recent_row_is_new(self):
		since = datetime.now(timezone.utc) - timedelta(hours=1)

		class _Row:
			created_on = datetime.now(timezone.utc)

		assert self._is_new(_Row(), since) is True

	def test_old_row_is_not_new(self):
		since = datetime.now(timezone.utc)

		class _Row:
			created_on = datetime(2020, 1, 1, tzinfo=timezone.utc)

		assert self._is_new(_Row(), since) is False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_col(key: str):
	col = MagicMock()
	col.key = key
	return col
