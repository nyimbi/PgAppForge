"""
tests/ci/test_agent_memory.py

CI tests for AgentMemoryStore.

All DB calls are intercepted with a mock session so no real PostgreSQL
(or pgvector extension) is required.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch, call

import pytest

from pgappforge.agent_memory import AgentMemoryStore, create_memory_tables


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_store(session=None) -> AgentMemoryStore:
	return AgentMemoryStore(user_id="u-001", tenant_id="t-001", session=session or MagicMock())


def _mock_row(id="mem-1", content="test fact", memory_type="fact", importance=0.7, relevance=0.9):
	row = MagicMock()
	row.__getitem__ = lambda self, i: [id, content, memory_type, importance, relevance][i]
	# Support r[0], r[1], ... pattern
	row.__iter__ = lambda self: iter([id, content, memory_type, importance, relevance])
	return row


# ---------------------------------------------------------------------------
# Tests: remember()
# ---------------------------------------------------------------------------

class TestRemember:

	def test_remember_returns_id(self):
		session = MagicMock()
		store = _make_store(session)
		with patch.object(store, "_embed", return_value=None):
			mem_id = store.remember("Company has 3 branches", memory_type="fact")
		assert mem_id is not None
		session.execute.assert_called_once()
		session.flush.assert_called_once()

	def test_remember_with_embedding(self):
		session = MagicMock()
		store = _make_store(session)
		fake_embedding = [0.1] * 1536
		with patch.object(store, "_embed", return_value=fake_embedding):
			mem_id = store.remember("User prefers KES", memory_type="preference", importance=0.9)

		assert mem_id is not None
		call_kwargs = session.execute.call_args[0][1]
		assert call_kwargs["memory_type"] == "preference"
		assert call_kwargs["importance"] == 0.9
		assert json.loads(call_kwargs["embedding"]) == fake_embedding

	def test_remember_truncates_long_content(self):
		session = MagicMock()
		store = _make_store(session)
		long_text = "x" * 5000
		with patch.object(store, "_embed", return_value=None):
			store.remember(long_text)
		call_kwargs = session.execute.call_args[0][1]
		assert len(call_kwargs["content"]) == 2000

	def test_remember_returns_none_on_db_error(self):
		session = MagicMock()
		session.execute.side_effect = Exception("DB error")
		store = _make_store(session)
		with patch.object(store, "_embed", return_value=None):
			result = store.remember("some fact")
		assert result is None

	def test_remember_without_session_returns_none(self):
		store = AgentMemoryStore(user_id="u1", tenant_id="t1", session=None)
		with patch("pgappforge.agent_memory.AgentMemoryStore.session", new_callable=lambda: property(lambda self: None)):
			result = store.remember("fact")
		assert result is None


# ---------------------------------------------------------------------------
# Tests: recall()
# ---------------------------------------------------------------------------

class TestRecall:

	def _make_rows(self):
		"""Two mock rows compatible with r[0], r[1], ... access."""
		rows = []
		for i in range(2):
			r = MagicMock()
			# Make positional indexing work via __getitem__
			data = [f"mem-{i}", f"content {i}", "fact", 0.7, 0.85]
			r.__getitem__ = lambda self, idx, d=data: d[idx]
			rows.append(r)
		return rows

	def test_recall_semantic_when_embedding_available(self):
		session = MagicMock()
		store = _make_store(session)
		fake_rows = self._make_rows()
		session.execute.return_value.fetchall.return_value = fake_rows

		with patch.object(store, "_embed", return_value=[0.1] * 1536):
			results = store.recall("salary payment")

		assert isinstance(results, list)
		# Should have called UPDATE for access tracking
		assert session.execute.call_count == 2  # SELECT + UPDATE

	def test_recall_fallback_when_no_embedding(self):
		session = MagicMock()
		store = _make_store(session)
		session.execute.return_value.fetchall.return_value = []

		with patch.object(store, "_embed", return_value=None):
			results = store.recall("anything")

		assert results == []
		# Only SELECT called (no rows → no UPDATE)
		assert session.execute.call_count == 1

	def test_recall_with_type_filter(self):
		session = MagicMock()
		store = _make_store(session)
		session.execute.return_value.fetchall.return_value = []

		with patch.object(store, "_embed", return_value=None):
			store.recall("payroll", memory_types=["preference", "fact"])

		sql_text = str(session.execute.call_args[0][0])
		params = session.execute.call_args[0][1]
		assert "types" in params
		assert params["types"] == ["preference", "fact"]

	def test_recall_returns_empty_without_session(self):
		store = AgentMemoryStore(user_id="u1", tenant_id="t1", session=None)
		with patch("pgappforge.agent_memory.AgentMemoryStore.session", new_callable=lambda: property(lambda self: None)):
			results = store.recall("anything")
		assert results == []

	def test_recall_handles_db_error(self):
		session = MagicMock()
		session.execute.side_effect = Exception("connection lost")
		store = _make_store(session)
		with patch.object(store, "_embed", return_value=None):
			results = store.recall("query")
		assert results == []


# ---------------------------------------------------------------------------
# Tests: build_memory_context()
# ---------------------------------------------------------------------------

class TestBuildMemoryContext:

	def test_returns_formatted_string(self):
		store = _make_store()
		with patch.object(store, "recall", return_value=[
			{"memory_type": "preference", "content": "User prefers KES"},
			{"memory_type": "fact", "content": "Company has 3 branches"},
		]):
			ctx = store.build_memory_context("salary")

		assert "Relevant context from memory:" in ctx
		assert "[preference] User prefers KES" in ctx
		assert "[fact] Company has 3 branches" in ctx

	def test_returns_empty_string_when_no_memories(self):
		store = _make_store()
		with patch.object(store, "recall", return_value=[]):
			ctx = store.build_memory_context("anything")
		assert ctx == ""


# ---------------------------------------------------------------------------
# Tests: forget() / forget_all()
# ---------------------------------------------------------------------------

class TestForget:

	def test_forget_executes_delete(self):
		session = MagicMock()
		store = _make_store(session)
		result = store.forget("mem-123")
		assert result is True
		session.execute.assert_called_once()

	def test_forget_returns_false_on_error(self):
		session = MagicMock()
		session.execute.side_effect = Exception("nope")
		store = _make_store(session)
		result = store.forget("mem-123")
		assert result is False

	def test_forget_all_returns_rowcount(self):
		session = MagicMock()
		session.execute.return_value.rowcount = 5
		store = _make_store(session)
		count = store.forget_all()
		assert count == 5

	def test_forget_all_with_type_filter(self):
		session = MagicMock()
		session.execute.return_value.rowcount = 2
		store = _make_store(session)
		count = store.forget_all(memory_type="preference")
		assert count == 2
		params = session.execute.call_args[0][1]
		assert params.get("type") == "preference"


# ---------------------------------------------------------------------------
# Tests: create_memory_tables()
# ---------------------------------------------------------------------------

class TestCreateMemoryTables:

	def test_creates_table_and_extension(self):
		mock_engine = MagicMock()
		mock_conn = MagicMock()
		mock_engine.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
		mock_engine.begin.return_value.__exit__ = MagicMock(return_value=False)

		create_memory_tables(mock_engine)

		# At least 2 execute calls: CREATE EXTENSION + CREATE TABLE
		assert mock_conn.execute.call_count >= 2
		all_sql = " ".join(str(c[0][0]) for c in mock_conn.execute.call_args_list)
		assert "pgaf_agent_memory" in all_sql
		assert "vector" in all_sql.lower()
