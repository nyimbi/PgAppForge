"""
tests/ci/conftest.py

PostgreSQL isolation for AppBuilder integration tests.

Strategy:
- On CLASS change: DROP/CREATE SCHEMA (nuclear, handles index duplicates)
- On every test: TRUNCATE all user tables (fast, handles data isolation)

This gives full isolation without the 1-2s overhead of DROP/CREATE on every test.

FAB stubs are applied at session scope here so they are consistent across all test
files and prevent MRO/mapper conflicts from multiple test modules doing their own stubs.
"""
import sys
import types
import os
import pytest

# ── Stub flask_appbuilder once at session scope ─────────────────────────────
# This must happen before any plugin module is imported during test collection.
def _stub_fab() -> None:
    """Inject minimal flask_appbuilder stubs so plugin views/models can be imported
    without the full FAB package being installed."""
    _FAB_MODS = [
        "flask_appbuilder", "flask_appbuilder.models", "flask_appbuilder.models.sqla",
        "flask_appbuilder.models.sqla.interface", "flask_appbuilder.security.decorators",
        "flask_appbuilder.baseviews", "flask_appbuilder.views", "flask_appbuilder.forms",
        "flask_appbuilder.fieldwidgets", "flask_appbuilder.actions", "flask_appbuilder.hooks",
        "flask_appbuilder.widgets", "flask_appbuilder.security", "flask_appbuilder.security.manager",
    ]
    for name in _FAB_MODS:
        if name not in sys.modules:
            sys.modules[name] = types.ModuleType(name)

    class _Stub:
        def __init__(self, *a, **kw): pass
        def __call__(self, *a, **kw): return self
        def __class_getitem__(cls, item): return cls
        def __set_name__(self, *a): pass

    _fab = sys.modules["flask_appbuilder"]
    for _attr in ("ModelView", "BaseView", "expose", "has_access", "permission_name",
                  "MasterDetailView", "MultipleView", "RestCRUDView", "RulesMixin"):
        if not hasattr(_fab, _attr):
            setattr(_fab, _attr, _Stub)
    _sqla_iface = sys.modules["flask_appbuilder.models.sqla.interface"]
    if not hasattr(_sqla_iface, "SQLAInterface"):
        _sqla_iface.SQLAInterface = _Stub
    _sec_dec = sys.modules["flask_appbuilder.security.decorators"]
    if not hasattr(_sec_dec, "has_access"):
        _sec_dec.has_access = lambda f: f


_stub_fab()

# Pre-load key pgappforge modules BEFORE any test file is imported.
# This ensures test files that stub these modules (e.g. test_clm_plugin.py)
# find them already in sys.modules and skip stubbing, preserving real implementations.
try:
    import pgappforge.models.sqla  # noqa: F401 — registers Model
    import pgappforge.plugins.audit  # noqa: F401 — registers AuditMixin
    import pgappforge.plugins.rules.mixin  # noqa: F401 — registers RulesMixin, _fire
except Exception:
    pass  # graceful degradation if dependencies not yet available


_PG_URI = (
    os.environ.get("SQLALCHEMY_DATABASE_URI")
    or os.environ.get("PGAPPFORGE_DB")
    or "postgresql:///pgaf_test"
)

_last_class: list[str] = [""]

_TRUNCATE_SQL = """
DO $$ DECLARE r RECORD; BEGIN
  FOR r IN (SELECT tablename FROM pg_tables
            WHERE schemaname = 'public'
              AND tablename NOT IN ('spatial_ref_sys'))
  LOOP
    EXECUTE 'TRUNCATE TABLE public.' || quote_ident(r.tablename)
            || ' RESTART IDENTITY CASCADE';
  END LOOP;
END $$;
"""

_SCHEMA_RESET_SQL = [
    "DROP SCHEMA public CASCADE",
    "CREATE SCHEMA public",
    "GRANT ALL ON SCHEMA public TO PUBLIC",
    "CREATE EXTENSION IF NOT EXISTS pg_trgm",
    "CREATE EXTENSION IF NOT EXISTS ltree",
    "CREATE EXTENSION IF NOT EXISTS postgis",
]


def _exec_pg(uri: str, statements: list[str]) -> None:
    from sqlalchemy import create_engine, text
    engine = create_engine(uri, isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        for sql in statements:
            conn.execute(text(sql))
    engine.dispose()


@pytest.fixture(autouse=True)
def pg_isolation(request):
    """Isolate each test from DB state left by previous tests."""
    if not _PG_URI.startswith("postgresql"):
        yield
        return

    cls_name = request.node.cls.__name__ if request.node.cls else ""

    if cls_name != _last_class[0]:
        # New test class: nuclear reset (handles duplicate indexes from re-imports)
        _last_class[0] = cls_name
        try:
            _exec_pg(_PG_URI, _SCHEMA_RESET_SQL)
        except Exception as exc:
            import warnings
            warnings.warn(f"pg schema reset failed: {exc}")
    else:
        # Same class: just truncate data (fast, handles data isolation)
        try:
            _exec_pg(_PG_URI, [_TRUNCATE_SQL])
        except Exception:
            pass  # No tables yet — first test in class, truncate is no-op

    yield
