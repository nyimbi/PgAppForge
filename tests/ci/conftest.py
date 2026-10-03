"""
tests/ci/conftest.py

PostgreSQL isolation for AppBuilder integration tests.

Strategy:
- On CLASS change: DROP/CREATE SCHEMA (nuclear, handles index duplicates)
- On every test: TRUNCATE all user tables (fast, handles data isolation)

This gives full isolation without the 1-2s overhead of DROP/CREATE on every test.

DB failures are loud: a schema reset or truncate that silently passes leaves the next
test reading another test's rows, which is far worse than a red suite.
"""
import logging
import os
import pytest

log = logging.getLogger(__name__)

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


_ADVISORY_LOCK_ID = 0x706761665F636900  # hex of "pgaf_ci\0" — unique per DB


def _exec_pg(uri: str, statements: list[str], retries: int = 3) -> None:
    import time
    from sqlalchemy import create_engine, text
    engine = create_engine(uri, isolation_level="AUTOCOMMIT")
    for attempt in range(retries):
        try:
            with engine.connect() as conn:
                for sql in statements:
                    conn.execute(text(sql))
            break
        except Exception as exc:
            is_deadlock = "deadlock" in str(exc).lower() or "40P01" in str(exc)
            if is_deadlock and attempt < retries - 1:
                time.sleep(0.5 * (attempt + 1))
                continue
            raise
    engine.dispose()


def _exec_pg_locked(uri: str, statements: list[str]) -> None:
    """Execute statements while holding a session-level advisory lock on ONE
    pinned connection. Serializes concurrent schema resets across pytest workers.

    Key constraint: pg_advisory_lock is session-scoped — the lock must be
    acquired, used, and released on the same connection. NullPool prevents
    SQLAlchemy from recycling the connection mid-flight.
    """
    import time
    from sqlalchemy import create_engine, text
    from sqlalchemy.pool import NullPool

    engine = create_engine(uri, isolation_level="AUTOCOMMIT", poolclass=NullPool)
    conn = engine.connect()
    acquired = False
    try:
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            acquired = bool(
                conn.execute(
                    text("SELECT pg_try_advisory_lock(:k)"),
                    {"k": _ADVISORY_LOCK_ID},
                ).scalar()
            )
            if acquired:
                break
            time.sleep(0.25)

        if not acquired:
            raise TimeoutError(
                f"could not acquire pg advisory lock {_ADVISORY_LOCK_ID} within 10s"
            )

        for sql in statements:
            try:
                conn.execute(text(sql))
            except Exception as exc:
                msg = str(exc).lower()
                if "already exists" in msg or "duplicate" in msg:
                    continue
                raise
    finally:
        if acquired:
            try:
                conn.execute(
                    text("SELECT pg_advisory_unlock(:k)"),
                    {"k": _ADVISORY_LOCK_ID},
                )
            except Exception:
                pass  # connection already dead — lock dies with the session anyway
        conn.close()
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
            _exec_pg_locked(_PG_URI, _SCHEMA_RESET_SQL)
        except Exception:
            log.exception(
                "pg schema reset failed for %s against %s",
                cls_name or "<module-level test>",
                _PG_URI,
            )
            raise
    else:
        # Same class: just truncate data (fast, handles data isolation)
        try:
            _exec_pg(_PG_URI, [_TRUNCATE_SQL])
        except Exception:
            log.exception(
                "pg truncate failed for %s against %s",
                cls_name or "<module-level test>",
                _PG_URI,
            )
            raise

    yield
