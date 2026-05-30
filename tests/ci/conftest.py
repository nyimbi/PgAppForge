"""
tests/ci/conftest.py

PostgreSQL schema reset for AppBuilder integration tests.

Each test that calls AppBuilder() triggers create_db(), which creates tables
and indexes. On a shared PostgreSQL DB, multiple test classes will collide on
the same index names (e.g. ix_app_config_category).

This conftest resets the public schema before each test class changes
(tracked by class name). For non-PostgreSQL tests the reset is skipped.
"""
import os
import pytest

_PG_URI = (
    os.environ.get("SQLALCHEMY_DATABASE_URI")
    or os.environ.get("PGAPPFORGE_DB")
    or "postgresql:///pgaf_test"
)

_last_class: list[str] = [""]  # mutable container to track last seen class name


def _reset_pg_schema(uri: str) -> None:
    from sqlalchemy import create_engine, text
    engine = create_engine(uri, isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
        conn.execute(text("GRANT ALL ON SCHEMA public TO PUBLIC"))
        for ext in ("pg_trgm", "ltree", "postgis"):
            conn.execute(text(f"CREATE EXTENSION IF NOT EXISTS {ext}"))
    engine.dispose()


@pytest.fixture(autouse=True)
def pg_schema_reset(request):
    """Reset PostgreSQL schema when the test class changes, to avoid DuplicateTable errors."""
    if not _PG_URI.startswith("postgresql"):
        yield
        return

    cls_name = request.node.cls.__name__ if request.node.cls else ""
    if cls_name != _last_class[0]:
        _last_class[0] = cls_name
        try:
            _reset_pg_schema(_PG_URI)
        except Exception as exc:
            import warnings
            warnings.warn(f"pg_schema_reset failed: {exc}")
    yield
