"""
tests/ci/test_search_manager.py

Unit tests for GlobalSearchManager (pgappforge/search/manager.py).

Strategy
--------
- Exercises the ILIKE fallback path (SQLite in-memory) — the PostgreSQL FTS
  path is exercised via mocked session.bind / execute for branch coverage.
- No Flask app is required for most tests; init_app() is exercised separately.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch, PropertyMock
from types import SimpleNamespace

import pytest
from sqlalchemy import Column, Integer, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


# ---------------------------------------------------------------------------
# Minimal models for search tests
# ---------------------------------------------------------------------------

class _Base(DeclarativeBase):
    pass


class _Employee(_Base):
    __tablename__ = "employee"
    id         = Column(Integer, primary_key=True)
    first_name = Column(String(64))
    last_name  = Column(String(64))
    email      = Column(String(128))


class _Department(_Base):
    __tablename__ = "department"
    id   = Column(Integer, primary_key=True)
    name = Column(String(128))
    code = Column(String(16))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def engine():
    e = create_engine("sqlite:///:memory:", echo=False)
    _Base.metadata.create_all(e)
    return e


@pytest.fixture
def session(engine):
    connection = engine.connect()
    tx = connection.begin()
    sess = Session(bind=connection)
    # Seed data
    sess.add_all([
        _Employee(first_name="Alice", last_name="Smith", email="alice@example.com"),
        _Employee(first_name="Bob",   last_name="Jones", email="bob@example.com"),
        _Employee(first_name="Charlie", last_name="Brown", email="cbrown@example.com"),
        _Department(name="Engineering", code="ENG"),
        _Department(name="Finance",     code="FIN"),
    ])
    sess.flush()
    yield sess
    sess.close()
    tx.rollback()
    connection.close()


@pytest.fixture
def manager(session):
    from pgappforge.search.manager import GlobalSearchManager
    m = GlobalSearchManager()
    m._session = session
    m.register(_Employee,   fields=["first_name", "last_name", "email"],
                label="Employees",   url_template="/employee/show/{pk}")
    m.register(_Department, fields=["name", "code"],
                label="Departments", url_template="/department/show/{pk}")
    return m


# ---------------------------------------------------------------------------
# Registration tests
# ---------------------------------------------------------------------------

def test_register_adds_model_to_registered_list():
    from pgappforge.search.manager import GlobalSearchManager
    m = GlobalSearchManager()
    m.register(_Employee, fields=["first_name"])
    # model_name uses __name__ of the class, which is "_Employee" in this module
    assert _Employee.__name__ in m.registered_models


def test_register_multiple_models():
    from pgappforge.search.manager import GlobalSearchManager
    m = GlobalSearchManager()
    m.register(_Employee,   fields=["first_name"])
    m.register(_Department, fields=["name"])
    assert len(m.registered_models) == 2


def test_register_uses_class_name_as_default_label():
    from pgappforge.search.manager import GlobalSearchManager
    m = GlobalSearchManager()
    m.register(_Department, fields=["name"])
    reg = m._registrations[0]
    # label defaults to model_class.__name__, which is "_Department" here
    assert reg.label == _Department.__name__


def test_register_uses_custom_label():
    from pgappforge.search.manager import GlobalSearchManager
    m = GlobalSearchManager()
    m.register(_Department, fields=["name"], label="Dept Units")
    assert m._registrations[0].label == "Dept Units"


def test_register_generates_default_url_template():
    from pgappforge.search.manager import GlobalSearchManager
    m = GlobalSearchManager()
    m.register(_Employee, fields=["first_name"])
    reg = m._registrations[0]
    assert "{pk}" in reg.url_template


# ---------------------------------------------------------------------------
# Search — ILIKE path (SQLite)
# ---------------------------------------------------------------------------

def test_search_returns_results_for_matching_query(manager):
    results = manager.search("alice")
    assert len(results) >= 1
    # model_name = class.__name__; local test class is "_Employee"
    assert any(r.model_name == _Employee.__name__ for r in results)


def test_search_is_case_insensitive(manager):
    results = manager.search("ALICE")
    assert len(results) >= 1


def test_search_returns_empty_for_no_match(manager):
    results = manager.search("xyzxyznotfound999")
    assert results == []


def test_search_returns_empty_for_blank_query(manager):
    results = manager.search("")
    assert results == []


def test_search_returns_empty_when_no_models_registered(session):
    from pgappforge.search.manager import GlobalSearchManager
    m = GlobalSearchManager()
    m._session = session
    results = m.search("alice")
    assert results == []


def test_search_returns_empty_when_no_session():
    from pgappforge.search.manager import GlobalSearchManager
    m = GlobalSearchManager()
    m.register(_Employee, fields=["first_name"])
    results = m.search("alice")
    assert results == []


def test_search_result_has_correct_url(manager):
    results = manager.search("alice")
    emp = next(r for r in results if r.model_name == _Employee.__name__)
    assert emp.url.startswith("/employee/show/")


def test_search_result_display_capped_at_80_chars(manager, session):
    long_name = "A" * 100
    session.add(_Employee(first_name=long_name, last_name="Test", email="long@example.com"))
    session.flush()
    results = manager.search("A" * 5)
    for r in results:
        assert len(r.display) <= 80


def test_search_respects_limit(manager):
    # Add extra employees all matching "brown"
    for i in range(5):
        manager._session.add(_Employee(first_name="brown", last_name=f"extra{i}",
                                       email=f"b{i}@x.com"))
    manager._session.flush()
    results = manager.search("brown", limit=2)
    assert len(results) <= 2


def test_search_across_multiple_models(manager):
    results = manager.search("en")  # hits "Engineering" + maybe emails
    model_names = {r.model_name for r in results}
    assert _Department.__name__ in model_names


def test_clean_query_strips_special_chars():
    from pgappforge.search.manager import GlobalSearchManager
    m = GlobalSearchManager()
    # _clean_query replaces non-word chars with spaces then strips; may produce
    # multiple spaces for multi-char punctuation sequences — normalise to compare.
    import re
    def _norm(s):
        return re.sub(r"\s+", " ", s).strip()
    assert _norm(m._clean_query("hello; DROP TABLE")) == "hello DROP TABLE"
    assert _norm(m._clean_query("foo@bar.baz")) == "foo bar baz"


# ---------------------------------------------------------------------------
# init_app wiring
# ---------------------------------------------------------------------------

def test_init_app_attaches_to_flask_extensions():
    from pgappforge.search.manager import GlobalSearchManager
    app = MagicMock()
    app.extensions = {}
    sess = MagicMock()
    m = GlobalSearchManager()
    m.init_app(app, sess)
    assert app.extensions.get("fab_search_manager") is m
    assert m._session is sess


# ---------------------------------------------------------------------------
# PostgreSQL FTS path — mocked
# ---------------------------------------------------------------------------

def test_search_uses_pg_path_when_dialect_is_postgresql(session):
    from pgappforge.search.manager import GlobalSearchManager
    m = GlobalSearchManager()

    # Mock a "postgresql" dialect
    fake_bind = MagicMock()
    fake_bind.dialect.name = "postgresql"
    fake_session = MagicMock()
    fake_session.bind = fake_bind

    m._session = fake_session
    m.register(_Employee, fields=["first_name", "email"])

    # Make execute return an empty result so _search_pg doesn't crash
    fake_session.execute.return_value.fetchall.return_value = []

    results = m.search("alice")
    assert fake_session.execute.called
    assert results == []
