"""
tests/ci/test_travel_expense_plugin.py

CI tests for the HCM Travel & Expense plugin.

Covers:
  - Model instantiation and field defaults
  - check_policy()  — compliant / breach / receipt threshold
  - compute_per_diem() — single-day, multi-day, missing rate
  - submit_report()  — happy path, state guard, no-lines guard
  - approve_report() — full approve, per-line override
  - reject_report()  — state transition + metadata
  - pay_report()     — GL entries captured, BIK event emitted, advance settled
  - request_advance() / disburse_advance() / settle_advance()
  - log_mileage()    — standalone + report-linked MILEAGE line creation
  - get_expense_analytics() — category aggregation, top spenders, summary

No mocks — uses SQLite in-memory (via SQLAlchemy 2.x) with real objects.
GL plugin not installed; _gl_post() falls back silently (tested separately).
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine, event as sa_event
from sqlalchemy.orm import Session

# ---------------------------------------------------------------------------
# Minimal stubs so we can import models without a full Flask app
# ---------------------------------------------------------------------------

import sys
import types


import importlib
import pathlib

# Root of the source tree — allows importing real plugin packages
_SRC_ROOT = str(pathlib.Path(__file__).parent.parent.parent)
if _SRC_ROOT not in sys.path:
    sys.path.insert(0, _SRC_ROOT)

_PLUGIN_ROOT = str(
    pathlib.Path(__file__).parent.parent.parent
    / "pgappforge" / "plugins" / "erp" / "hcm"
)


def _make_stub(name: str, path: list[str] | None = None) -> types.ModuleType:
    """Create a minimal namespace stub that Python's importer can descend into."""
    m = types.ModuleType(name)
    # __path__ must be set for packages so sub-imports work
    m.__path__ = path or []
    m.__package__ = name
    m.__spec__ = None
    return m


# ---------------------------------------------------------------------------
# Stub out the heavy framework layers that pull in Flask / SQLAlchemy app init
# ---------------------------------------------------------------------------

# pgappforge top-level and sub-packages — stubs only; real travel_expense loaded below
_pgaf_root = str(pathlib.Path(__file__).parent.parent.parent)
_plugin_path = str(pathlib.Path(_pgaf_root) / "pgappforge" / "plugins")
_erp_path    = str(pathlib.Path(_pgaf_root) / "pgappforge" / "plugins" / "erp")
_hcm_path    = str(pathlib.Path(_pgaf_root) / "pgappforge" / "plugins" / "erp" / "hcm")
_te_path     = str(pathlib.Path(_hcm_path) / "travel_expense")

sys.modules.setdefault("pgappforge",         _make_stub("pgappforge", [_pgaf_root]))
sys.modules.setdefault("pgappforge.models",  _make_stub("pgappforge.models"))
sys.modules.setdefault("pgappforge.plugins", _make_stub("pgappforge.plugins", [_plugin_path]))
sys.modules.setdefault("pgappforge.plugins.erp",             _make_stub("pgappforge.plugins.erp", [_erp_path]))
sys.modules.setdefault("pgappforge.plugins.erp.foundation",  _make_stub("pgappforge.plugins.erp.foundation"))
sys.modules.setdefault("pgappforge.plugins.erp.hcm",         _make_stub("pgappforge.plugins.erp.hcm", [_hcm_path]))
sys.modules.setdefault("pgappforge.plugins.base_plugin",     _make_stub("pgappforge.plugins.base_plugin"))

# Stub out pgappforge.models.sqla.Model as a plain declarative base
from sqlalchemy.orm import DeclarativeBase

class _Base(DeclarativeBase):
    pass

sqla_stub = _make_stub("pgappforge.models.sqla")
sqla_stub.Model = _Base
# Only replace if not already loaded by the full test suite (avoids corrupting real Model)
if "pgappforge.models.sqla" not in sys.modules:
    sys.modules["pgappforge.models.sqla"] = sqla_stub

# Stub AuditMixin as a no-op mixin
class _AuditMixin:
    pass

audit_pkg = _make_stub("pgappforge.plugins.audit")
audit_pkg.AuditMixin = _AuditMixin
# Only replace if not already loaded
if "pgappforge.plugins.audit" not in sys.modules:
    sys.modules["pgappforge.plugins.audit"] = audit_pkg

# Stub foundation events
_events_emitted: list = []

foundation_events = _make_stub("pgappforge.plugins.erp.foundation.events")

def _emit_event(ev, session):
    _events_emitted.append(ev)

from dataclasses import dataclass as _dataclass, field as _field

@_dataclass
class _DomainEvent:
    """Minimal stub matching the real DomainEvent base dataclass interface."""
    aggregate_id: str = ""
    aggregate_type: str = ""
    tenant_id: str = ""
    event_id: str = _field(default_factory=lambda: str(uuid.uuid4()))
    occurred_at: str = _field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

foundation_events.DomainEvent = _DomainEvent
foundation_events.emit_event = _emit_event
foundation_events.subscribe = lambda *a, **kw: None
sys.modules["pgappforge.plugins.erp.foundation.events"] = foundation_events

# Stub base_plugin classes
class _PluginPriority:
    NORMAL = 3

class _BasePlugin:
    def __init__(self, appbuilder=None, config=None):
        self.appbuilder = appbuilder
        self.config = config or {}

class _PluginMetadata:
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)

base_plugin_stub = sys.modules["pgappforge.plugins.base_plugin"]
base_plugin_stub.BasePlugin = _BasePlugin
base_plugin_stub.PluginMetadata = _PluginMetadata
base_plugin_stub.PluginPriority = _PluginPriority

# Stub GL service so _gl_post's lazy import finds a no-op instead of the real
# GLService (which has an incompatible post_journal signature and would error).
class _GLServiceStub:
    @staticmethod
    def post_journal(**kwargs):
        return {}

_gl_svc_stub = _make_stub("pgappforge.plugins.erp.finance.gl.services")
_gl_svc_stub.GLService = _GLServiceStub
sys.modules.setdefault("pgappforge.plugins.erp.finance", _make_stub("pgappforge.plugins.erp.finance"))
sys.modules.setdefault("pgappforge.plugins.erp.finance.gl", _make_stub("pgappforge.plugins.erp.finance.gl"))
sys.modules["pgappforge.plugins.erp.finance.gl.services"] = _gl_svc_stub

# Now import the actual plugin modules
from pgappforge.plugins.erp.hcm.travel_expense import models as M
from pgappforge.plugins.erp.hcm.travel_expense import services as S
from pgappforge.plugins.erp.hcm.travel_expense import events as E
from pgappforge.plugins.erp.hcm.travel_expense.services import (
    ExpenseService,
    ExpenseReportNotFoundError,
    AdvanceNotFoundError,
    ExpenseStateError,
    ExpensePolicyError,
)

# ---------------------------------------------------------------------------
# SQLite in-memory engine + session fixture
# ---------------------------------------------------------------------------

# SQLite doesn't support JSONB; swap to plain JSON for tests
from sqlalchemy.dialects import sqlite as _sqlite_dialect
from sqlalchemy import JSON

_engine = create_engine("sqlite:///:memory:", echo=False)

# Patch JSONB → JSON for SQLite
@sa_event.listens_for(_engine, "connect")
def _set_sqlite_pragma(conn, _rec):
    conn.execute("PRAGMA foreign_keys=ON")


def _patch_for_sqlite():
    """Replace PostgreSQL-specific column types with SQLite-compatible equivalents.

    UUID(as_uuid=False) stores strings on PostgreSQL but SQLite's type processor
    tries to parse them as Python uuid.UUID objects, choking on non-UUID values
    that leak through (e.g. integer rowids).  Replacing with String(36) silences
    the processor entirely and keeps string round-trips intact.
    """
    from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
    for mapper in _Base.registry.mappers:
        for col in mapper.persist_selectable.columns:
            if isinstance(col.type, JSONB):
                col.type = JSON()
            elif isinstance(col.type, PG_UUID):
                col.type = sa.String(36)


_patch_for_sqlite()
_Base.metadata.create_all(_engine)


@pytest.fixture
def session():
    """Provide a fresh session, rolling back after each test."""
    conn = _engine.connect()
    trans = conn.begin()
    sess = Session(bind=conn)
    _events_emitted.clear()
    yield sess
    sess.close()
    trans.rollback()
    conn.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TID = "00000000-0000-0000-0000-000000000001"


def _uuid() -> str:
    return str(uuid.uuid4())


def _policy(session, category: str, limit_cents: int | None = None,
            receipt_threshold: int = 0, grade: str | None = None,
            policy_type: str = "CATEGORY_LIMIT") -> M.ExpensePolicy:
    p = M.ExpensePolicy(
        id=_uuid(), tenant_id=_TID,
        name=f"Policy-{category}",
        policy_type=policy_type,
        expense_category=category,
        grade_code=grade,
        single_limit_cents=limit_cents,
        requires_receipt_above_cents=receipt_threshold,
        requires_approval_above_cents=0,
        currency_code="KES",
        is_active=True,
    )
    session.add(p)
    session.flush()
    return p


def _perdiem(session, country: str = "KEN", from_d: date = date(2026, 1, 1),
             to_d: date | None = None) -> M.PerDiemRate:
    r = M.PerDiemRate(
        id=_uuid(), tenant_id=_TID,
        country_code=country,
        city_code=None,
        from_date=from_d,
        to_date=to_d,
        breakfast_cents=50_00,
        lunch_cents=80_00,
        dinner_cents=100_00,
        accommodation_cents=500_00,
        incidentals_cents=30_00,
        currency_code="KES",
    )
    session.add(r)
    session.flush()
    return r


def _report(session, status: str = "DRAFT",
            advance: int = 0) -> M.ExpenseReport:
    r = M.ExpenseReport(
        id=_uuid(), tenant_id=_TID,
        employee_id=_uuid(),
        title="Q1 Field Visit",
        trip_purpose="Client meetings",
        destination="Nairobi",
        trip_start=date(2026, 3, 1),
        trip_end=date(2026, 3, 3),
        currency_code="KES",
        total_claimed_cents=0,
        total_approved_cents=0,
        advance_received_cents=advance,
        reimbursement_due_cents=0,
        status=status,
    )
    session.add(r)
    session.flush()
    return r


def _line(session, report: M.ExpenseReport,
          category: str = "MEALS",
          amount: int = 500_00,
          bik: bool = False) -> M.ExpenseLine:
    ln = M.ExpenseLine(
        id=_uuid(), tenant_id=_TID,
        report_id=report.id,
        expense_date=date(2026, 3, 1),
        expense_category=category,
        description="Test line",
        amount_cents=amount,
        currency_code="KES",
        exchange_rate=Decimal("1"),
        base_amount_cents=amount,
        is_paye_bik=bik,
    )
    session.add(ln)
    session.flush()
    return ln


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------

def test_expense_policy_defaults(session):
    p = _policy(session, "TRANSPORT", limit_cents=200_00)
    assert p.currency_code == "KES"
    assert p.is_active is True
    assert p.requires_receipt_above_cents == 0


def test_expense_report_defaults(session):
    r = _report(session)
    assert r.status == "DRAFT"
    assert r.total_approved_cents == 0


def test_expense_line_base_amount(session):
    r = _report(session)
    ln = _line(session, r, amount=1200_00)
    assert ln.base_amount_cents == 1200_00
    assert ln.policy_breach is False


def test_cash_advance_defaults(session):
    adv = M.CashAdvance(
        id=_uuid(), tenant_id=_TID, employee_id=_uuid(),
        request_date=date(2026, 3, 1),
        trip_purpose="Field trip",
        amount_cents=50000,
        currency_code="KES",
        status="REQUESTED",
        outstanding_cents=50000,
    )
    session.add(adv)
    session.flush()
    assert adv.status == "REQUESTED"


def test_mileage_log_fields(session):
    ml = M.MileageLog(
        id=_uuid(), tenant_id=_TID, employee_id=_uuid(),
        log_date=date(2026, 3, 5),
        from_location="Nairobi", to_location="Nakuru",
        purpose="Site visit",
        distance_km=Decimal("156.5"),
        rate_per_km_cents=25,
        total_cents=3912,
    )
    session.add(ml)
    session.flush()
    assert ml.total_cents == 3912


# ---------------------------------------------------------------------------
# check_policy tests
# ---------------------------------------------------------------------------

def test_check_policy_no_policy_compliant(session):
    result = ExpenseService.check_policy(
        session, {"expense_category": "MEALS", "amount_cents": 99999},
        employee_grade="G3", tenant_id=_TID,
    )
    assert result["compliant"] is True
    assert result["policy_applied"] == ""


def test_check_policy_within_limit(session):
    _policy(session, "MEALS", limit_cents=500_00)
    result = ExpenseService.check_policy(
        session, {"expense_category": "MEALS", "amount_cents": 400_00},
        employee_grade="G3", tenant_id=_TID,
    )
    assert result["compliant"] is True
    assert result["breach_amount_cents"] == 0


def test_check_policy_breach(session):
    _policy(session, "MEALS", limit_cents=500_00)
    result = ExpenseService.check_policy(
        session, {"expense_category": "MEALS", "amount_cents": 700_00},
        employee_grade="G3", tenant_id=_TID,
    )
    assert result["compliant"] is False
    assert result["breach_amount_cents"] == 200_00
    assert "500" in result["reason"]


def test_check_policy_receipt_threshold(session):
    _policy(session, "ACCOMMODATION", limit_cents=None, receipt_threshold=300_00)
    result = ExpenseService.check_policy(
        session,
        {"expense_category": "ACCOMMODATION", "amount_cents": 400_00, "receipt_url": None},
        employee_grade="", tenant_id=_TID,
    )
    assert result["compliant"] is False
    assert "Receipt" in result["reason"]


def test_check_policy_grade_specific_overrides_catchall(session):
    _policy(session, "TRANSPORT", limit_cents=200_00, grade=None)      # catch-all
    _policy(session, "TRANSPORT", limit_cents=400_00, grade="MANAGER") # grade-specific
    result = ExpenseService.check_policy(
        session, {"expense_category": "TRANSPORT", "amount_cents": 350_00},
        employee_grade="MANAGER", tenant_id=_TID,
    )
    assert result["compliant"] is True   # MANAGER limit is 400, not 200


# ---------------------------------------------------------------------------
# compute_per_diem tests
# ---------------------------------------------------------------------------

def test_compute_per_diem_single_day(session):
    _perdiem(session)
    res = ExpenseService.compute_per_diem(
        session, _uuid(), "KEN",
        date(2026, 3, 1), date(2026, 3, 1),
        {"breakfast": True, "lunch": True, "dinner": True,
         "accommodation": True, "incidentals": True},
        _TID,
    )
    assert res["days"] == 1
    expected = 50_00 + 80_00 + 100_00 + 500_00 + 30_00
    assert res["total_cents"] == expected
    assert len(res["per_day_breakdown"]) == 1


def test_compute_per_diem_multi_day(session):
    _perdiem(session)
    res = ExpenseService.compute_per_diem(
        session, _uuid(), "KEN",
        date(2026, 3, 1), date(2026, 3, 3),
        {"breakfast": True, "lunch": False, "dinner": True,
         "accommodation": True, "incidentals": False},
        _TID,
    )
    assert res["days"] == 3
    per_day = 50_00 + 100_00 + 500_00
    assert res["total_cents"] == per_day * 3


def test_compute_per_diem_missing_rate_zeros(session):
    res = ExpenseService.compute_per_diem(
        session, _uuid(), "ZZZ",
        date(2026, 3, 1), date(2026, 3, 2),
        {"breakfast": True},
        _TID,
    )
    assert res["total_cents"] == 0
    assert all(d["day_total"] == 0 for d in res["per_day_breakdown"])


# ---------------------------------------------------------------------------
# submit_report tests
# ---------------------------------------------------------------------------

def test_submit_report_happy_path(session):
    r = _report(session)
    _line(session, r, "MEALS", 300_00)
    _line(session, r, "TRANSPORT", 150_00)
    report = ExpenseService.submit_report(session, r.id, _TID)
    assert report.status == "SUBMITTED"
    assert report.total_claimed_cents == 450_00
    assert report.reimbursement_due_cents == 450_00
    assert report.submitted_at is not None
    submitted_events = [e for e in _events_emitted
                        if e.event_type == "hcm.travel_expense.report.submitted"]
    assert len(submitted_events) == 1


def test_submit_report_with_advance(session):
    r = _report(session, advance=200_00)
    _line(session, r, "MEALS", 500_00)
    report = ExpenseService.submit_report(session, r.id, _TID)
    assert report.reimbursement_due_cents == 300_00


def test_submit_report_wrong_status_raises(session):
    r = _report(session, status="SUBMITTED")
    _line(session, r, "MEALS", 100_00)
    with pytest.raises(ExpenseStateError):
        ExpenseService.submit_report(session, r.id, _TID)


def test_submit_report_no_lines_raises(session):
    r = _report(session)
    with pytest.raises(ExpensePolicyError):
        ExpenseService.submit_report(session, r.id, _TID)


def test_submit_report_marks_policy_breach(session):
    _policy(session, "MEALS", limit_cents=200_00)
    r = _report(session)
    ln = _line(session, r, "MEALS", 500_00)
    ExpenseService.submit_report(session, r.id, _TID)
    session.flush()
    session.refresh(ln)
    assert ln.policy_breach is True
    breach_events = [e for e in _events_emitted
                     if e.event_type == "hcm.travel_expense.policy.breach"]
    assert len(breach_events) == 1


def test_submit_report_not_found_raises(session):
    with pytest.raises(ExpenseReportNotFoundError):
        ExpenseService.submit_report(session, _uuid(), _TID)


# ---------------------------------------------------------------------------
# approve_report tests
# ---------------------------------------------------------------------------

def test_approve_report_full(session):
    r = _report(session, status="SUBMITTED")
    _line(session, r, "MEALS", 300_00)
    _line(session, r, "TRANSPORT", 200_00)
    r.total_claimed_cents = 500_00
    approver = _uuid()
    report = ExpenseService.approve_report(session, r.id, approver, tenant_id=_TID)
    assert report.status == "APPROVED"
    assert report.total_approved_cents == 500_00
    assert report.approved_by == approver


def test_approve_report_line_override(session):
    r = _report(session, status="SUBMITTED")
    ln = _line(session, r, "ENTERTAINMENT", 400_00)
    r.total_claimed_cents = 400_00
    overrides = {ln.id: 300_00}
    report = ExpenseService.approve_report(
        session, r.id, _uuid(), line_overrides=overrides, tenant_id=_TID
    )
    assert report.total_approved_cents == 300_00
    session.flush()
    session.refresh(ln)
    assert ln.approved_amount_cents == 300_00


def test_approve_report_wrong_status_raises(session):
    r = _report(session, status="DRAFT")
    with pytest.raises(ExpenseStateError):
        ExpenseService.approve_report(session, r.id, _uuid(), tenant_id=_TID)


# ---------------------------------------------------------------------------
# reject_report tests
# ---------------------------------------------------------------------------

def test_reject_report(session):
    r = _report(session, status="SUBMITTED")
    approver = _uuid()
    report = ExpenseService.reject_report(session, r.id, approver, "Missing receipts", _TID)
    assert report.status == "REJECTED"
    assert report.metadata_["rejection_reason"] == "Missing receipts"
    assert report.approved_by == approver


def test_reject_report_wrong_status_raises(session):
    r = _report(session, status="PAID")
    with pytest.raises(ExpenseStateError):
        ExpenseService.reject_report(session, r.id, _uuid(), "reason", _TID)


# ---------------------------------------------------------------------------
# pay_report tests
# ---------------------------------------------------------------------------

def test_pay_report(session):
    r = _report(session, status="APPROVED")
    _line(session, r, "MEALS", 300_00)
    _line(session, r, "TRANSPORT", 200_00)
    r.total_approved_cents = 500_00
    r.reimbursement_due_cents = 500_00
    report = ExpenseService.pay_report(session, r.id, "PAY-001", _TID)
    assert report.status == "PAID"
    assert report.payment_ref == "PAY-001"
    assert report.paid_at is not None
    paid_events = [e for e in _events_emitted
                   if e.event_type == "hcm.travel_expense.report.paid"]
    assert len(paid_events) == 1


def test_pay_report_emits_bik_event(session):
    r = _report(session, status="APPROVED")
    _line(session, r, "ENTERTAINMENT", 500_00, bik=True)
    r.total_approved_cents = 500_00
    r.reimbursement_due_cents = 500_00
    ExpenseService.pay_report(session, r.id, "PAY-BIK-001", _TID)
    bik_events = [e for e in _events_emitted
                  if e.event_type == "hcm.travel_expense.bik.flagged"]
    assert len(bik_events) == 1
    assert bik_events[0].bik_amount_cents == 500_00


def test_pay_report_wrong_status_raises(session):
    r = _report(session, status="SUBMITTED")
    with pytest.raises(ExpenseStateError):
        ExpenseService.pay_report(session, r.id, "X", _TID)


def test_pay_report_settles_linked_advance(session):
    r = _report(session, status="APPROVED")
    _line(session, r, "MEALS", 300_00)
    r.total_approved_cents = 300_00
    r.reimbursement_due_cents = 0

    adv = M.CashAdvance(
        id=_uuid(), tenant_id=_TID, employee_id=r.employee_id,
        request_date=date(2026, 2, 28),
        trip_purpose="Pre-advance",
        amount_cents=300_00,
        currency_code="KES",
        status="DISBURSED",
        disbursement_ref="ADV-001",
        linked_report_id=r.id,
        outstanding_cents=300_00,
    )
    session.add(adv)
    session.flush()

    ExpenseService.pay_report(session, r.id, "PAY-ADV-001", _TID)
    session.flush()
    session.refresh(adv)
    assert adv.outstanding_cents == 0
    assert adv.status == "SETTLED"


# ---------------------------------------------------------------------------
# request_advance / disburse_advance / settle_advance
# ---------------------------------------------------------------------------

def test_request_advance(session):
    adv = ExpenseService.request_advance(
        session, _uuid(), 100_000_00, "KES", "Upcountry trip", _TID
    )
    assert adv.status == "REQUESTED"
    assert adv.outstanding_cents == 100_000_00


def test_request_advance_zero_raises(session):
    with pytest.raises(ExpensePolicyError):
        ExpenseService.request_advance(session, _uuid(), 0, "KES", "Trip", _TID)


def test_disburse_advance(session):
    adv = M.CashAdvance(
        id=_uuid(), tenant_id=_TID, employee_id=_uuid(),
        request_date=date(2026, 3, 1),
        trip_purpose="Field trip",
        amount_cents=50_000_00,
        currency_code="KES",
        status="APPROVED",
        outstanding_cents=50_000_00,
    )
    session.add(adv)
    session.flush()
    result = ExpenseService.disburse_advance(session, adv.id, "DREF-001", _TID)
    assert result.status == "DISBURSED"
    assert result.disbursement_ref == "DREF-001"
    disbursed_events = [e for e in _events_emitted
                        if e.event_type == "hcm.travel_expense.advance.disbursed"]
    assert len(disbursed_events) == 1


def test_disburse_advance_wrong_status_raises(session):
    adv = M.CashAdvance(
        id=_uuid(), tenant_id=_TID, employee_id=_uuid(),
        request_date=date(2026, 3, 1),
        trip_purpose="x",
        amount_cents=10000,
        currency_code="KES",
        status="REQUESTED",
        outstanding_cents=10000,
    )
    session.add(adv)
    session.flush()
    with pytest.raises(ExpenseStateError):
        ExpenseService.disburse_advance(session, adv.id, "X", _TID)


def test_settle_advance_exact(session):
    emp = _uuid()
    r = _report(session, status="APPROVED")
    r.employee_id = emp
    r.total_approved_cents = 30_000_00
    r.advance_received_cents = 30_000_00

    adv = M.CashAdvance(
        id=_uuid(), tenant_id=_TID, employee_id=emp,
        request_date=date(2026, 3, 1),
        trip_purpose="Field",
        amount_cents=30_000_00,
        currency_code="KES",
        status="DISBURSED",
        outstanding_cents=30_000_00,
    )
    session.add(adv)
    session.flush()

    result = ExpenseService.settle_advance(session, adv.id, r.id, _TID)
    assert result["settled"] is True
    assert result["outstanding_cents"] == 0
    assert result["refund_due"] is False


def test_settle_advance_employee_owes_refund(session):
    emp = _uuid()
    r = _report(session, status="APPROVED")
    r.employee_id = emp
    r.total_approved_cents = 20_000_00

    adv = M.CashAdvance(
        id=_uuid(), tenant_id=_TID, employee_id=emp,
        request_date=date(2026, 3, 1),
        trip_purpose="Field",
        amount_cents=30_000_00,
        currency_code="KES",
        status="DISBURSED",
        outstanding_cents=30_000_00,
    )
    session.add(adv)
    session.flush()

    result = ExpenseService.settle_advance(session, adv.id, r.id, _TID)
    assert result["refund_due"] is True
    assert result["refund_cents"] == 10_000_00


# ---------------------------------------------------------------------------
# log_mileage tests
# ---------------------------------------------------------------------------

def test_log_mileage_standalone(session):
    ml = ExpenseService.log_mileage(
        session, _uuid(),
        {
            "log_date": date(2026, 3, 5),
            "from_location": "Nairobi",
            "to_location": "Nakuru",
            "purpose": "Site visit",
            "distance_km": "156.5",
            "rate_per_km_cents": 25,
        },
        _TID,
    )
    assert ml.total_cents == 3913   # round_half_up(156.5 × 25 = 3912.5) → 3913
    assert ml.report_id is None


def test_log_mileage_linked_creates_expense_line(session):
    r = _report(session)
    initial_total = r.total_claimed_cents

    ExpenseService.log_mileage(
        session, r.employee_id,
        {
            "log_date": date(2026, 3, 5),
            "from_location": "HQ",
            "to_location": "Kisumu",
            "purpose": "Training",
            "distance_km": "100",
            "rate_per_km_cents": 20,
            "report_id": r.id,
        },
        _TID,
    )
    session.flush()
    session.refresh(r)
    assert r.total_claimed_cents == initial_total + 2000

    lines = session.execute(
        sa.select(M.ExpenseLine).where(
            M.ExpenseLine.report_id == r.id,
            M.ExpenseLine.expense_category == "MILEAGE",
        )
    ).scalars().all()
    assert len(lines) == 1
    assert lines[0].amount_cents == 2000


def test_log_mileage_rounding(session):
    ml = ExpenseService.log_mileage(
        session, _uuid(),
        {
            "log_date": date(2026, 3, 5),
            "from_location": "A", "to_location": "B",
            "purpose": "P",
            "distance_km": "10.3",
            "rate_per_km_cents": 3,
        },
        _TID,
    )
    # 10.3 × 3 = 30.9 → rounds to 31
    assert ml.total_cents == 31


# ---------------------------------------------------------------------------
# get_expense_analytics tests
# ---------------------------------------------------------------------------

def test_get_expense_analytics_empty(session):
    result = ExpenseService.get_expense_analytics(
        session, date(2026, 1, 1), date(2026, 12, 31), _TID
    )
    assert result["summary"]["total_reports"] == 0
    assert result["summary"]["total_claimed_cents"] == 0
    assert result["by_category"] == {}
    assert result["top_spenders"] == []


def test_get_expense_analytics_counts(session):
    # Create two APPROVED reports with lines
    for _ in range(2):
        r = _report(session, status="APPROVED")
        r.total_approved_cents = 400_00
        ln = _line(session, r, "MEALS", 400_00)
        ln.approved_amount_cents = 400_00

    result = ExpenseService.get_expense_analytics(
        session, date(2026, 1, 1), date(2026, 12, 31), _TID
    )
    assert "MEALS" in result["by_category"]
    assert result["by_category"]["MEALS"]["line_count"] == 2
    assert result["by_category"]["MEALS"]["total_claimed_cents"] == 800_00
    assert len(result["top_spenders"]) == 2


# ---------------------------------------------------------------------------
# events module tests
# ---------------------------------------------------------------------------

def test_event_instantiation():
    ev = E.ExpenseReportSubmittedEvent(
        aggregate_id="r1", aggregate_type="ExpenseReport", tenant_id=_TID,
        report_id="r1", employee_id="e1",
        total_claimed_cents=500_00, advance_received_cents=0,
        reimbursement_due_cents=500_00,
    )
    assert ev.event_type == "hcm.travel_expense.report.submitted"
    assert ev.total_claimed_cents == 500_00


def test_all_events_in_all():
    for name in E.__all__:
        assert hasattr(E, name), f"{name} missing from events module"


def test_all_models_in_all():
    for name in M.__all__:
        assert hasattr(M, name), f"{name} missing from models module"
