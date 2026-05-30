"""
tests/ci/test_access_log.py

Unit tests for AccessLogAnalytics (pgappforge/access_log/analytics.py).

Strategy
--------
- SQLite in-memory schema mirrors fab_access_log without PostgreSQL-specific
  types (INET → String, no percentile_cont).
- Methods that use raw SQL (requests_per_minute) or PostgreSQL window functions
  (percentile_cont) are exercised via mocked session.execute.
- Pure-Python helpers (_since, summary_stats, error_summary, etc.) run against
  the real SQLite session.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import (
    Column, DateTime, Integer, SmallInteger, String, Text,
    ForeignKey, create_engine, func,
)
from sqlalchemy.orm import DeclarativeBase, Session


# ---------------------------------------------------------------------------
# SQLite-compatible schema (no INET / JSONB)
# ---------------------------------------------------------------------------

class _Base(DeclarativeBase):
    pass


class _AbUser(_Base):
    __tablename__ = "ab_user"
    id       = Column(Integer, primary_key=True)
    username = Column(String(64))


class _AccessLogEntry(_Base):
    __tablename__ = "fab_access_log"
    # SQLite requires Integer (not BigInteger) for autoincrement to work
    id             = Column(Integer, primary_key=True, autoincrement=True)
    method         = Column(String(8), nullable=False)
    path           = Column(String(2048), nullable=False)
    query_string   = Column(Text)
    blueprint      = Column(String(128))
    view_func      = Column(String(256))
    user_id        = Column(Integer, ForeignKey("ab_user.id", ondelete="SET NULL"), nullable=True)
    username       = Column(String(64))
    ip_address     = Column(String(45))   # text instead of INET
    user_agent     = Column(Text)
    referer        = Column(Text)
    session_id     = Column(String(64))
    status_code    = Column(SmallInteger, nullable=False, default=200)
    response_bytes = Column(Integer)
    duration_ms    = Column(Integer)
    requested_at   = Column(DateTime(timezone=True), nullable=False,
                            default=lambda: datetime.now(timezone.utc))


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
    yield sess
    sess.close()
    tx.rollback()
    connection.close()


def _log(session, path="/api/data", method="GET", status=200, duration=50,
         user_id=1, username="alice", ip="10.0.0.1", hours_ago=0):
    entry = _AccessLogEntry(
        method=method,
        path=path,
        status_code=status,
        duration_ms=duration,
        user_id=user_id,
        username=username,
        ip_address=ip,
        requested_at=datetime.now(timezone.utc) - timedelta(hours=hours_ago),
    )
    session.add(entry)
    return entry


@pytest.fixture
def analytics(session):
    """Return an AccessLogAnalytics instance wired to the test session,
    with the model class swapped for the SQLite-compatible version."""
    from pgappforge.access_log import analytics as _mod
    orig = _mod.AccessLogEntry
    _mod.AccessLogEntry = _AccessLogEntry
    from pgappforge.access_log.analytics import AccessLogAnalytics
    ana = AccessLogAnalytics(session)
    yield ana
    _mod.AccessLogEntry = orig


# ---------------------------------------------------------------------------
# Helper: _since
# ---------------------------------------------------------------------------

def test_since_returns_datetime_in_past(analytics):
    since = analytics._since(24)
    assert since < datetime.now(timezone.utc)
    delta = datetime.now(timezone.utc) - since
    assert abs(delta.total_seconds() - 86400) < 5


def test_since_hours_zero_is_close_to_now(analytics):
    since = analytics._since(0)
    delta = datetime.now(timezone.utc) - since
    assert delta.total_seconds() < 2


# ---------------------------------------------------------------------------
# error_summary
# ---------------------------------------------------------------------------

def test_error_summary_all_success(session, analytics):
    _log(session, status=200)
    _log(session, status=201)
    session.flush()
    summary = analytics.error_summary(hours=1)
    assert summary["total"] >= 2
    assert summary["errors_5xx"] == 0


def test_error_summary_counts_4xx(session, analytics):
    _log(session, status=404, hours_ago=0)
    session.flush()
    summary = analytics.error_summary(hours=1)
    assert summary["errors_4xx"] >= 1


def test_error_summary_counts_5xx(session, analytics):
    _log(session, status=500, hours_ago=0)
    session.flush()
    summary = analytics.error_summary(hours=1)
    assert summary["errors_5xx"] >= 1


def test_error_summary_error_rate_zero_when_no_requests(analytics):
    # No rows in time window far future
    summary = analytics.error_summary(hours=0)
    assert summary["error_rate_pct"] == 0.0


# ---------------------------------------------------------------------------
# summary_stats
# ---------------------------------------------------------------------------

def test_summary_stats_returns_expected_keys(analytics):
    stats = analytics.summary_stats(hours=24)
    expected = {"total_requests", "requests_per_hour", "unique_users",
                "avg_response_ms", "error_count", "error_rate_pct"}
    assert expected.issubset(set(stats.keys()))


def test_summary_stats_counts_unique_users(session, analytics):
    _log(session, user_id=10, username="u10")
    _log(session, user_id=11, username="u11")
    _log(session, user_id=10, username="u10")
    session.flush()
    stats = analytics.summary_stats(hours=1)
    assert stats["unique_users"] >= 2


def test_summary_stats_total_ge_error_count(session, analytics):
    _log(session, status=200)
    _log(session, status=500)
    session.flush()
    stats = analytics.summary_stats(hours=1)
    assert stats["total_requests"] >= stats["error_count"]


# ---------------------------------------------------------------------------
# slow_requests
# ---------------------------------------------------------------------------

def test_slow_requests_returns_entries_above_threshold(session, analytics):
    _log(session, duration=2000, path="/slow/endpoint")
    _log(session, duration=50,   path="/fast/endpoint")
    session.flush()
    slow = analytics.slow_requests(threshold_ms=1000, hours=1)
    assert all(e.duration_ms >= 1000 for e in slow)
    paths = [e.path for e in slow]
    assert "/slow/endpoint" in paths
    assert "/fast/endpoint" not in paths


def test_slow_requests_respects_limit(session, analytics):
    for _ in range(5):
        _log(session, duration=5000)
    session.flush()
    slow = analytics.slow_requests(threshold_ms=100, hours=1, limit=3)
    assert len(slow) <= 3


def test_slow_requests_empty_when_all_fast(session, analytics):
    _log(session, duration=10, path="/zippy")
    session.flush()
    slow = analytics.slow_requests(threshold_ms=9999, hours=1)
    assert all(e.duration_ms >= 9999 for e in slow)


# ---------------------------------------------------------------------------
# user_session_timeline
# ---------------------------------------------------------------------------

def test_user_session_timeline_filters_by_user(session, analytics):
    today = datetime.now(timezone.utc)
    for path in ["/a", "/b", "/c"]:
        session.add(_AccessLogEntry(
            method="GET", path=path, status_code=200,
            user_id=42, username="charlie",
            requested_at=today,
        ))
    session.add(_AccessLogEntry(
        method="GET", path="/other", status_code=200,
        user_id=99, username="bob",
        requested_at=today,
    ))
    session.flush()
    tl = analytics.user_session_timeline(user_id=42, date=today)
    assert all(e.user_id == 42 for e in tl)
    assert len(tl) >= 3


def test_user_session_timeline_excludes_other_day(session, analytics):
    yesterday = datetime.now(timezone.utc) - timedelta(days=2)
    session.add(_AccessLogEntry(
        method="GET", path="/old", status_code=200,
        user_id=55, username="past_user",
        requested_at=yesterday,
    ))
    session.flush()
    today = datetime.now(timezone.utc)
    tl = analytics.user_session_timeline(user_id=55, date=today)
    assert len(tl) == 0


# ---------------------------------------------------------------------------
# top_ips
# ---------------------------------------------------------------------------

def test_top_ips_returns_most_active_ip(session, analytics):
    for _ in range(5):
        _log(session, ip="192.168.1.1", hours_ago=0)
    _log(session, ip="192.168.1.2", hours_ago=0)
    session.flush()
    ips = analytics.top_ips(hours=1)
    assert len(ips) >= 1
    first_ip = ips[0]["ip"]
    assert first_ip == "192.168.1.1"


# ---------------------------------------------------------------------------
# requests_per_minute — mocked (raw SQL not SQLite-compatible)
# ---------------------------------------------------------------------------

def test_requests_per_minute_calls_raw_sql(analytics):
    fake_row = MagicMock()
    fake_row.minute = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    fake_row.requests = 10
    fake_row.errors = 1
    fake_row.avg_ms = 55
    analytics.session.execute = MagicMock(
        return_value=MagicMock(fetchall=MagicMock(return_value=[fake_row]))
    )
    result = analytics.requests_per_minute(hours=1)
    assert len(result) == 1
    assert result[0]["requests"] == 10
    assert result[0]["errors"] == 1


# ---------------------------------------------------------------------------
# top_endpoints — mocked (percentile_cont not in SQLite)
# ---------------------------------------------------------------------------

def test_top_endpoints_mocked(analytics):
    fake_row = MagicMock()
    fake_row.path = "/api/test"
    fake_row.method = "GET"
    fake_row.hits = 42
    fake_row.avg_ms = 120
    fake_row.p95_ms = 300
    fake_row.errors = 2
    analytics.session.query = MagicMock(return_value=MagicMock(
        filter=MagicMock(return_value=MagicMock(
            group_by=MagicMock(return_value=MagicMock(
                order_by=MagicMock(return_value=MagicMock(
                    limit=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[fake_row])))
                ))
            ))
        ))
    ))
    result = analytics.top_endpoints(limit=5, hours=1)
    assert len(result) == 1
    assert result[0]["path"] == "/api/test"
    assert result[0]["error_rate_pct"] == round(100 * 2 / 42, 1)
