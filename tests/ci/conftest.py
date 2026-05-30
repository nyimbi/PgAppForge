"""
tests/ci/conftest.py

PostgreSQL isolation for AppBuilder integration tests.

Strategy:
- On CLASS change: DROP/CREATE SCHEMA (nuclear, handles index duplicates)
- On every test: TRUNCATE all user tables (fast, handles data isolation)

This gives full isolation without the 1-2s overhead of DROP/CREATE on every test.
"""
import os
import pytest

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
