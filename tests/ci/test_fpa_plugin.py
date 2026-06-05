"""
tests/ci/test_fpa_plugin.py

CI tests for the FP&A plugin — models, services, events, plugin metadata.

Strategy (matching project convention for plugins without a live DB in CI):
  - Model smoke tests: plain instantiation + repr, no DB required.
  - Service tests: real FPAService methods against a mock Session that returns
    pre-built model objects.  Only the SQLAlchemy query path is mocked; all
    business logic (variance calc, status thresholds, scenario adjustment,
    KPI classification) runs for real.
  - Event dataclass tests: field defaults only.
  - Plugin metadata tests: no Flask context required.

Run:
    uv run pytest -vxs tests/ci/test_fpa_plugin.py
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch, call
from typing import Any

import pytest

TENANT = "00000000-0000-0000-0000-000000000001"


def _uid() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Model smoke tests  (pure instantiation — no DB)
# ---------------------------------------------------------------------------

def test_budget_cycle_repr():
    from pgappforge.plugins.erp.finance.fpa.models import BudgetCycle
    cycle = BudgetCycle(
        id=_uid(), tenant_id=TENANT,
        name="FY2026 Annual", fiscal_year=2026,
        cycle_type="ANNUAL", status="INPUT_OPEN",
    )
    assert "FY2026" in repr(cycle)
    assert cycle.status == "INPUT_OPEN"


def test_budget_version_repr():
    from pgappforge.plugins.erp.finance.fpa.models import BudgetVersion
    v = BudgetVersion(
        id=_uid(), tenant_id=TENANT, cycle_id=_uid(),
        version_name="Budget v1", version_type="ORIGINAL",
        is_active=True,
    )
    assert "Budget v1" in repr(v)
    assert v.locked_at is None


def test_budget_line_repr():
    from pgappforge.plugins.erp.finance.fpa.models import BudgetLine
    line = BudgetLine(
        id=_uid(), tenant_id=TENANT, version_id=_uid(),
        gl_account_code="4000",
        period_month=date(2026, 1, 1),
        amount_cents=500_000,
        driver_type="MANUAL", status="DRAFT",
    )
    assert "4000" in repr(line)
    assert line.amount_cents == 500_000


def test_budget_driver_repr():
    from pgappforge.plugins.erp.finance.fpa.models import BudgetDriver
    d = BudgetDriver(
        id=_uid(), tenant_id=TENANT,
        driver_code="HEADCOUNT_SALARY",
        name="Headcount Salary Driver",
        driver_type="HEADCOUNT", unit="persons",
        base_value=Decimal("120000.0000"), is_global=True,
    )
    assert "HEADCOUNT_SALARY" in repr(d)


def test_scenario_model_repr():
    from pgappforge.plugins.erp.finance.fpa.models import ScenarioModel
    s = ScenarioModel(
        id=_uid(), tenant_id=TENANT,
        name="Optimistic 2026", base_version_id=_uid(),
        scenario_type="OPTIMISTIC",
        adjustment_rules={"4": {"pct": 10}},
        status="DRAFT",
    )
    assert "Optimistic" in repr(s)


def test_forecast_snapshot_repr():
    from pgappforge.plugins.erp.finance.fpa.models import ForecastSnapshot
    snap = ForecastSnapshot(
        id=_uid(), tenant_id=TENANT, cycle_id=_uid(),
        snapshot_date=date(2026, 3, 31),
        period_month=date(2026, 1, 1),
        gl_account_code="4000",
        actual_cents=480_000, budget_cents=500_000,
        forecast_cents=480_000, variance_cents=-20_000,
        variance_pct=Decimal("-4.0000"),
    )
    assert "4000" in repr(snap)


def test_kpi_target_repr():
    from pgappforge.plugins.erp.finance.fpa.models import KPITarget
    kpi = KPITarget(
        id=_uid(), tenant_id=TENANT, kpi_code="GROSS_MARGIN",
        kpi_name="Gross Margin %", cycle_id=_uid(),
        period_month=date(2026, 1, 1),
        target_value=Decimal("45.0000"),
        unit="percent", direction="HIGHER_IS_BETTER", status="ON_TRACK",
    )
    assert "GROSS_MARGIN" in repr(kpi)


# ---------------------------------------------------------------------------
# Helper: build a mock session that returns canned objects
# ---------------------------------------------------------------------------

def _mock_session() -> MagicMock:
    sess = MagicMock()
    sess.add = MagicMock()
    sess.flush = MagicMock()
    return sess


def _scalar_result(value: Any) -> MagicMock:
    """Return a chainable mock that ends in scalar_one_or_none() → value."""
    r = MagicMock()
    r.scalar_one_or_none.return_value = value
    r.scalars.return_value.all.return_value = value if isinstance(value, list) else []
    r.scalar_one.return_value = value
    return r


def _scalars_result(values: list) -> MagicMock:
    r = MagicMock()
    r.scalars.return_value.all.return_value = values
    r.scalar_one_or_none.return_value = values[0] if values else None
    return r


# ---------------------------------------------------------------------------
# Service: open_budget_cycle
# ---------------------------------------------------------------------------

def test_open_budget_cycle_sets_input_open():
    from pgappforge.plugins.erp.finance.fpa.services import FPAService

    svc = FPAService()
    sess = _mock_session()

    with patch(
        "pgappforge.plugins.erp.finance.fpa.services.emit_event"
    ) as mock_emit:
        cycle = svc.open_budget_cycle(
            sess,
            {"name": "FY2026 Annual", "fiscal_year": 2026, "cycle_type": "QUARTERLY"},
            TENANT,
        )

    assert cycle.status == "INPUT_OPEN"
    assert cycle.fiscal_year == 2026
    assert cycle.cycle_type == "QUARTERLY"
    assert cycle.tenant_id == TENANT
    sess.add.assert_called_once_with(cycle)
    sess.flush.assert_called()
    mock_emit.assert_called_once()
    event_arg = mock_emit.call_args[0][0]
    assert event_arg.event_type == "fpa.budget_cycle.opened"
    assert event_arg.fiscal_year == 2026


# ---------------------------------------------------------------------------
# Service: create_version (no copy)
# ---------------------------------------------------------------------------

def test_create_version_no_copy():
    from pgappforge.plugins.erp.finance.fpa.services import FPAService
    from pgappforge.plugins.erp.finance.fpa.models import BudgetCycle

    svc = FPAService()
    cycle_id = _uid()

    cycle = BudgetCycle(
        id=cycle_id, tenant_id=TENANT,
        name="FY2026", fiscal_year=2026,
        cycle_type="ANNUAL", status="INPUT_OPEN",
    )
    sess = _mock_session()
    sess.execute.return_value = _scalar_result(cycle)

    version = svc.create_version(
        sess, cycle_id, "Budget v1", "ORIGINAL", tenant_id=TENANT
    )

    assert version.version_name == "Budget v1"
    assert version.version_type == "ORIGINAL"
    assert version.cycle_id == cycle_id
    assert version.is_active is True


# ---------------------------------------------------------------------------
# Service: create_version (copy from existing)
# ---------------------------------------------------------------------------

def test_create_version_copy_clones_lines():
    from pgappforge.plugins.erp.finance.fpa.services import FPAService
    from pgappforge.plugins.erp.finance.fpa.models import BudgetCycle, BudgetVersion, BudgetLine

    svc = FPAService()
    cycle_id = _uid()
    src_version_id = _uid()

    cycle = BudgetCycle(
        id=cycle_id, tenant_id=TENANT, name="FY2026",
        fiscal_year=2026, cycle_type="ANNUAL", status="INPUT_OPEN",
    )
    src_version = BudgetVersion(
        id=src_version_id, tenant_id=TENANT, cycle_id=cycle_id,
        version_name="v1", version_type="ORIGINAL", is_active=True,
    )
    src_lines = [
        BudgetLine(
            id=_uid(), tenant_id=TENANT, version_id=src_version_id,
            gl_account_code="4000", period_month=date(2026, 1, 1),
            amount_cents=100_000, driver_type="MANUAL", status="APPROVED",
        ),
        BudgetLine(
            id=_uid(), tenant_id=TENANT, version_id=src_version_id,
            gl_account_code="4000", period_month=date(2026, 2, 1),
            amount_cents=200_000, driver_type="MANUAL", status="APPROVED",
        ),
    ]

    call_count = [0]

    def _execute(stmt):
        n = call_count[0]
        call_count[0] += 1
        if n == 0:
            return _scalar_result(cycle)          # _require_cycle (select BudgetCycle)
        if n == 1:
            return _scalar_result(src_version)    # _require_version for copy source
        # n==2: scalars().all() for source lines
        r = MagicMock()
        r.scalars.return_value.all.return_value = src_lines
        return r

    sess = _mock_session()
    sess.execute.side_effect = _execute

    added_items = []
    sess.add.side_effect = lambda obj: added_items.append(obj)

    version = svc.create_version(
        sess, cycle_id, "v2", "REVISED_1",
        copy_from_version_id=src_version_id, tenant_id=TENANT,
    )

    # New version should have been added
    assert any(getattr(obj, "version_name", None) == "v2" for obj in added_items)

    # Two BudgetLine clones should have been added (version_id matches the new version)
    cloned_lines = [
        obj for obj in added_items
        if isinstance(obj, BudgetLine)
    ]
    assert len(cloned_lines) == 2
    amounts = {l.amount_cents for l in cloned_lines}
    assert amounts == {100_000, 200_000}
    assert all(l.status == "DRAFT" for l in cloned_lines)


# ---------------------------------------------------------------------------
# Service: apply_driver
# ---------------------------------------------------------------------------

def test_apply_driver_inserts_12_lines_for_annual_cycle():
    from pgappforge.plugins.erp.finance.fpa.services import FPAService
    from pgappforge.plugins.erp.finance.fpa.models import (
        BudgetCycle, BudgetVersion, BudgetDriver,
    )

    svc = FPAService()
    cycle_id = _uid()
    version_id = _uid()
    driver_id = _uid()

    cycle = BudgetCycle(
        id=cycle_id, tenant_id=TENANT, name="FY2026",
        fiscal_year=2026, cycle_type="ANNUAL", status="INPUT_OPEN",
    )
    version = BudgetVersion(
        id=version_id, tenant_id=TENANT, cycle_id=cycle_id,
        version_name="v1", version_type="ORIGINAL",
        is_active=True, locked_at=None,
    )
    driver = BudgetDriver(
        id=driver_id, tenant_id=TENANT,
        driver_code="FLAT_RENT", name="Flat Rent",
        driver_type="RATE", unit="USD",
        base_value=Decimal("50000.0000"), is_global=True,
    )

    call_count = [0]

    def _execute(stmt):
        n = call_count[0]
        call_count[0] += 1
        if n == 0:
            return _scalar_result(version)     # _require_version
        if n == 1:
            return _scalar_result(cycle)       # _require_cycle
        if n == 2:
            return _scalar_result(driver)      # driver lookup
        # Month-by-month line lookup → None (insert new)
        return _scalar_result(None)

    sess = _mock_session()
    sess.execute.side_effect = _execute

    added = []
    sess.add.side_effect = lambda obj: added.append(obj)

    lines = svc.apply_driver(sess, version_id, "6100", "FLAT_RENT", TENANT)

    assert len(lines) == 12
    assert all(l.amount_cents == 50_000 for l in lines)
    assert all(l.gl_account_code == "6100" for l in lines)
    # All 12 lines were added via session.add
    from pgappforge.plugins.erp.finance.fpa.models import BudgetLine
    new_lines = [o for o in added if isinstance(o, BudgetLine)]
    assert len(new_lines) == 12


# ---------------------------------------------------------------------------
# Service: generate_scenario
# ---------------------------------------------------------------------------

def test_generate_scenario_applies_adjustment_rules():
    from pgappforge.plugins.erp.finance.fpa.services import FPAService
    from pgappforge.plugins.erp.finance.fpa.models import (
        BudgetVersion, BudgetLine, ScenarioModel,
    )

    svc = FPAService()
    base_ver_id = _uid()
    scenario_id = _uid()

    base_version = BudgetVersion(
        id=base_ver_id, tenant_id=TENANT, cycle_id=_uid(),
        version_name="v1", version_type="ORIGINAL",
        is_active=True, locked_at=None,
    )
    scenario = ScenarioModel(
        id=scenario_id, tenant_id=TENANT,
        name="Optimistic", base_version_id=base_ver_id,
        scenario_type="OPTIMISTIC",
        adjustment_rules={"4": {"pct": 10}, "6": {"pct": -5}},
        status="DRAFT",
        generated_version_id=None,
    )
    src_lines = [
        BudgetLine(
            id=_uid(), tenant_id=TENANT, version_id=base_ver_id,
            gl_account_code="4000", period_month=date(2026, 1, 1),
            amount_cents=1_000_000, driver_type="MANUAL", status="DRAFT",
        ),
        BudgetLine(
            id=_uid(), tenant_id=TENANT, version_id=base_ver_id,
            gl_account_code="6000", period_month=date(2026, 1, 1),
            amount_cents=500_000, driver_type="MANUAL", status="DRAFT",
        ),
    ]

    call_count = [0]

    def _execute(stmt):
        n = call_count[0]
        call_count[0] += 1
        if n == 0:
            return _scalar_result(scenario)        # scenario lookup
        if n == 1:
            return _scalar_result(base_version)    # _require_version
        r = MagicMock()
        r.scalars.return_value.all.return_value = src_lines
        return r

    sess = _mock_session()
    sess.execute.side_effect = _execute

    added = []

    def _add(obj):
        added.append(obj)
        # Simulate SA flush assigning PK to BudgetVersion if it has none
        if isinstance(obj, BudgetVersion) and not obj.id:
            obj.id = _uid()

    sess.add.side_effect = _add

    with patch(
        "pgappforge.plugins.erp.finance.fpa.services.emit_event"
    ):
        result = svc.generate_scenario(sess, scenario_id, TENANT)

    assert result.status == "GENERATED"
    assert result.generated_version_id is not None

    from pgappforge.plugins.erp.finance.fpa.models import BudgetLine
    cloned = [o for o in added if isinstance(o, BudgetLine)]
    assert len(cloned) == 2

    rev = next(l for l in cloned if l.gl_account_code == "4000")
    exp = next(l for l in cloned if l.gl_account_code == "6000")
    assert rev.amount_cents == 1_100_000   # +10%
    assert exp.amount_cents == 475_000     # -5%


# ---------------------------------------------------------------------------
# Service: approve_budget
# ---------------------------------------------------------------------------

def test_approve_budget_locks_version_and_cycle():
    from pgappforge.plugins.erp.finance.fpa.services import FPAService
    from pgappforge.plugins.erp.finance.fpa.models import (
        BudgetCycle, BudgetVersion, BudgetLine,
    )

    svc = FPAService()
    cycle_id = _uid()
    version_id = _uid()

    cycle = BudgetCycle(
        id=cycle_id, tenant_id=TENANT, name="FY2026",
        fiscal_year=2026, cycle_type="ANNUAL", status="UNDER_REVIEW",
    )
    version = BudgetVersion(
        id=version_id, tenant_id=TENANT, cycle_id=cycle_id,
        version_name="v1", version_type="ORIGINAL",
        is_active=True, locked_at=None,
    )
    lines = [
        BudgetLine(
            id=_uid(), tenant_id=TENANT, version_id=version_id,
            gl_account_code="4000", period_month=date(2026, 1, 1),
            amount_cents=200_000, driver_type="MANUAL", status="SUBMITTED",
        ),
        BudgetLine(
            id=_uid(), tenant_id=TENANT, version_id=version_id,
            gl_account_code="4000", period_month=date(2026, 2, 1),
            amount_cents=300_000, driver_type="MANUAL", status="SUBMITTED",
        ),
    ]

    call_count = [0]

    def _execute(stmt):
        n = call_count[0]
        call_count[0] += 1
        if n == 0:
            return _scalar_result(version)    # _require_version
        if n == 1:
            return _scalar_result(cycle)      # _require_cycle
        r = MagicMock()
        r.scalars.return_value.all.return_value = lines
        return r

    sess = _mock_session()
    sess.execute.side_effect = _execute

    with patch(
        "pgappforge.plugins.erp.finance.fpa.services.emit_event"
    ) as mock_emit:
        approved = svc.approve_budget(sess, version_id, "user-001", TENANT)

    assert approved.locked_at is not None
    assert cycle.status == "APPROVED"
    assert cycle.approved_by == "user-001"
    assert all(l.status == "APPROVED" for l in lines)

    mock_emit.assert_called_once()
    event = mock_emit.call_args[0][0]
    assert event.event_type == "fpa.budget.approved"
    assert event.total_budget_cents == 500_000


def test_approve_budget_raises_if_already_locked():
    from pgappforge.plugins.erp.finance.fpa.services import FPAService, VersionLockedError
    from pgappforge.plugins.erp.finance.fpa.models import BudgetVersion

    svc = FPAService()
    version_id = _uid()
    version = BudgetVersion(
        id=version_id, tenant_id=TENANT, cycle_id=_uid(),
        version_name="v1", version_type="ORIGINAL",
        is_active=True,
        locked_at=datetime.now(timezone.utc),  # already locked
    )

    sess = _mock_session()
    sess.execute.return_value = _scalar_result(version)

    with pytest.raises(VersionLockedError):
        svc.approve_budget(sess, version_id, "user-001", TENANT)


# ---------------------------------------------------------------------------
# Service: get_variance_analysis
# ---------------------------------------------------------------------------

def test_get_variance_analysis_sorted_by_abs_variance():
    from pgappforge.plugins.erp.finance.fpa.services import FPAService
    from pgappforge.plugins.erp.finance.fpa.models import ForecastSnapshot

    svc = FPAService()
    cycle_id = _uid()
    period = date(2026, 1, 1)

    snaps = [
        ForecastSnapshot(
            id=_uid(), tenant_id=TENANT, cycle_id=cycle_id,
            snapshot_date=date(2026, 3, 31), period_month=period,
            gl_account_code="4000",
            actual_cents=80_000, budget_cents=100_000,
            forecast_cents=80_000, variance_cents=-20_000,
            variance_pct=Decimal("-20.0000"),
        ),
        ForecastSnapshot(
            id=_uid(), tenant_id=TENANT, cycle_id=cycle_id,
            snapshot_date=date(2026, 3, 31), period_month=period,
            gl_account_code="5000",
            actual_cents=10_000, budget_cents=100_000,
            forecast_cents=10_000, variance_cents=-90_000,
            variance_pct=Decimal("-90.0000"),
        ),
    ]

    call_count = [0]

    def _execute(stmt):
        n = call_count[0]
        call_count[0] += 1
        if n == 0:
            # func.max snapshot_date
            r = MagicMock()
            r.scalar_one_or_none.return_value = date(2026, 3, 31)
            return r
        if n == 1:
            # snapshot rows
            r = MagicMock()
            r.scalars.return_value.all.return_value = snaps
            return r
        # GL account names (ImportError path — never reached in unit test)
        r = MagicMock()
        r.scalars.return_value.all.return_value = []
        return r

    sess = _mock_session()
    sess.execute.side_effect = _execute

    with patch(
        "pgappforge.plugins.erp.finance.fpa.services.emit_event"
    ):
        results = svc.get_variance_analysis(sess, cycle_id, period, TENANT)

    assert len(results) == 2
    # 5000 has larger abs variance (-90k) so comes first
    assert results[0]["gl_account_code"] == "5000"
    assert results[1]["gl_account_code"] == "4000"
    assert results[0]["variance_cents"] == -90_000
    assert results[1]["variance_pct"] == -20.0


def test_get_variance_analysis_empty_when_no_snapshots():
    from pgappforge.plugins.erp.finance.fpa.services import FPAService

    svc = FPAService()
    sess = _mock_session()
    # func.max returns None
    r = MagicMock()
    r.scalar_one_or_none.return_value = None
    sess.execute.return_value = r

    results = svc.get_variance_analysis(sess, _uid(), date(2026, 1, 1), TENANT)
    assert results == []


# ---------------------------------------------------------------------------
# Service: update_kpi — threshold logic
# ---------------------------------------------------------------------------

def _kpi_fixture(direction="HIGHER_IS_BETTER", target=Decimal("45.0000")):
    from pgappforge.plugins.erp.finance.fpa.models import KPITarget
    return KPITarget(
        id=_uid(), tenant_id=TENANT, kpi_code="GM",
        kpi_name="Gross Margin", cycle_id=_uid(),
        period_month=date(2026, 1, 1),
        target_value=target, unit="percent",
        direction=direction, status="ON_TRACK",
    )


def _update_kpi(actual, direction="HIGHER_IS_BETTER", target=Decimal("45.0000")):
    from pgappforge.plugins.erp.finance.fpa.services import FPAService

    svc = FPAService()
    kpi = _kpi_fixture(direction=direction, target=target)
    sess = _mock_session()
    sess.execute.return_value = _scalar_result(kpi)

    with patch("pgappforge.plugins.erp.finance.fpa.services.emit_event"):
        return svc.update_kpi(
            sess, "GM", date(2026, 1, 1), Decimal(str(actual)),
            kpi.cycle_id, TENANT
        )


def test_kpi_on_track_exactly_at_5pct_boundary():
    """5% shortfall is exactly ON_TRACK (boundary is <= 5.0)."""
    # actual=42.75, target=45.0 → (45-42.75)/45 * 100 = 5.0% → ON_TRACK
    updated = _update_kpi(Decimal("42.75"))
    assert updated.status == "ON_TRACK", "5.0% shortfall should be ON_TRACK (boundary inclusive)"


def test_kpi_at_risk_just_above_5pct_boundary():
    """Just above 5% shortfall falls into AT_RISK."""
    # actual=42.74, target=45.0 → shortfall = 2.26/45 * 100 ≈ 5.022% → AT_RISK
    updated = _update_kpi(Decimal("42.74"))
    assert updated.status == "AT_RISK", "5.02% shortfall should be AT_RISK (just above 5% boundary)"


def test_kpi_at_risk_just_below_15pct_boundary():
    """14.9% shortfall stays AT_RISK (not yet OFF_TRACK)."""
    # actual = 45 * (1 - 0.149) = 45 * 0.851 = 38.295
    updated = _update_kpi(Decimal("38.295"))
    assert updated.status == "AT_RISK", "14.9% shortfall should be AT_RISK (just below 15% boundary)"


def test_kpi_off_track_exactly_at_15pct_boundary():
    """Exactly 15% shortfall is AT_RISK (boundary is <= 15.0); just above is OFF_TRACK."""
    # 15.0% exactly: actual = 45 * 0.85 = 38.25
    updated = _update_kpi(Decimal("38.25"))
    assert updated.status == "AT_RISK", "15.0% shortfall should be AT_RISK (boundary inclusive)"


def test_kpi_off_track_above_15pct():
    """More than 15% shortfall → OFF_TRACK."""
    # actual=38.0, target=45.0 → shortfall = 7/45 * 100 ≈ 15.56% → OFF_TRACK
    updated = _update_kpi(Decimal("38.0"))
    assert updated.status == "OFF_TRACK", "15.56% shortfall should be OFF_TRACK (> 15%)"


def test_update_kpi_on_track_within_5_pct():
    # 44.5 vs 45.0 → shortfall ~1.1% → ON_TRACK
    updated = _update_kpi(Decimal("44.5"))
    assert updated.status == "ON_TRACK"
    assert updated.actual_value == Decimal("44.5")


def test_update_kpi_at_risk_5_to_15_pct():
    # 41.0 vs 45.0 → shortfall ~8.9% → AT_RISK
    updated = _update_kpi(Decimal("41.0"))
    assert updated.status == "AT_RISK"


def test_update_kpi_off_track_over_15_pct():
    # 35.0 vs 45.0 → shortfall ~22.2% → OFF_TRACK
    updated = _update_kpi(Decimal("35.0"))
    assert updated.status == "OFF_TRACK"


def test_update_kpi_lower_is_better_off_track_when_over():
    # OpEx target 20%, actual 25% → over by 25% → OFF_TRACK
    updated = _update_kpi(
        Decimal("25.0"),
        direction="LOWER_IS_BETTER",
        target=Decimal("20.0000"),
    )
    assert updated.status == "OFF_TRACK"


def test_update_kpi_lower_is_better_on_track_below():
    # OpEx target 20%, actual 19.5% → under by 2.5% → ON_TRACK
    updated = _update_kpi(
        Decimal("19.5"),
        direction="LOWER_IS_BETTER",
        target=Decimal("20.0000"),
    )
    assert updated.status == "ON_TRACK"


def test_update_kpi_emits_status_changed_event():
    from pgappforge.plugins.erp.finance.fpa.services import FPAService

    svc = FPAService()
    kpi = _kpi_fixture()
    kpi.status = "ON_TRACK"  # initial status
    sess = _mock_session()
    sess.execute.return_value = _scalar_result(kpi)

    with patch(
        "pgappforge.plugins.erp.finance.fpa.services.emit_event"
    ) as mock_emit:
        # 35.0 vs 45.0 → OFF_TRACK (status changes)
        svc.update_kpi(
            sess, "GM", date(2026, 1, 1), Decimal("35.0"),
            kpi.cycle_id, TENANT
        )

    mock_emit.assert_called_once()
    event = mock_emit.call_args[0][0]
    assert event.event_type == "fpa.kpi.status_changed"
    assert event.old_status == "ON_TRACK"
    assert event.new_status == "OFF_TRACK"


def test_update_kpi_no_event_when_status_unchanged():
    from pgappforge.plugins.erp.finance.fpa.services import FPAService

    svc = FPAService()
    kpi = _kpi_fixture()
    kpi.status = "ON_TRACK"  # already ON_TRACK
    sess = _mock_session()
    sess.execute.return_value = _scalar_result(kpi)

    with patch(
        "pgappforge.plugins.erp.finance.fpa.services.emit_event"
    ) as mock_emit:
        # 44.8 → still ON_TRACK
        svc.update_kpi(
            sess, "GM", date(2026, 1, 1), Decimal("44.8"),
            kpi.cycle_id, TENANT
        )

    mock_emit.assert_not_called()


# ---------------------------------------------------------------------------
# Service: compute_rolling_forecast — structure
# ---------------------------------------------------------------------------

def test_compute_rolling_forecast_structure():
    from pgappforge.plugins.erp.finance.fpa.services import FPAService
    from pgappforge.plugins.erp.finance.fpa.models import BudgetCycle, BudgetVersion, BudgetLine

    svc = FPAService()
    cycle_id = _uid()
    version_id = _uid()

    cycle = BudgetCycle(
        id=cycle_id, tenant_id=TENANT, name="FY2026",
        fiscal_year=2026, cycle_type="ANNUAL", status="APPROVED",
    )
    version = BudgetVersion(
        id=version_id, tenant_id=TENANT, cycle_id=cycle_id,
        version_name="v1", version_type="ORIGINAL",
        is_active=True, locked_at=datetime.now(timezone.utc),
    )

    # 6 budget lines: Jun–Nov 2026
    budget_lines = [
        BudgetLine(
            id=_uid(), tenant_id=TENANT, version_id=version_id,
            gl_account_code="4000",
            period_month=date(2026, 6 + i, 1),
            amount_cents=100_000,
            driver_type="MANUAL", status="APPROVED",
        )
        for i in range(6)
    ]

    call_count = [0]

    def _execute(stmt):
        n = call_count[0]
        call_count[0] += 1
        if n == 0:
            return _scalar_result(cycle)     # _require_cycle
        if n == 1:
            # active version query
            r = MagicMock()
            r.scalars.return_value.all.return_value = [version]
            r.scalar_one_or_none.return_value = version
            return r
        if n == 2:
            # budget lines for months in range
            r = MagicMock()
            r.scalars.return_value.all.return_value = budget_lines
            return r
        # actual snapshots for past months → None
        r = MagicMock()
        r.scalar_one_or_none.return_value = None
        return r

    sess = _mock_session()
    sess.execute.side_effect = _execute

    result = svc.compute_rolling_forecast(
        sess, cycle_id, date(2026, 6, 15), horizon_months=6, tenant_id=TENANT
    )

    assert "months" in result
    assert "total_forecast_cents" in result
    assert len(result["months"]) == 6

    jun = next(m for m in result["months"] if m["period_month"] == "2026-06-01")
    jul = next(m for m in result["months"] if m["period_month"] == "2026-07-01")
    # Jun <= as_of_date → is_actual=True
    assert jun["is_actual"] is True
    # Jul > as_of_date → is_actual=False
    assert jul["is_actual"] is False


# ---------------------------------------------------------------------------
# Plugin metadata
# ---------------------------------------------------------------------------

def test_fpa_plugin_register_models():
    from pgappforge.plugins.erp.finance.fpa import FPAPlugin

    plugin = FPAPlugin.__new__(FPAPlugin)
    plugin.config = {}
    models = plugin.register_models()
    names = {m.__name__ for m in models}
    expected = {
        "BudgetCycle", "BudgetVersion", "BudgetLine",
        "BudgetDriver", "ScenarioModel", "ForecastSnapshot", "KPITarget",
    }
    assert expected == names


def test_fpa_plugin_get_events():
    from pgappforge.plugins.erp.finance.fpa import FPAPlugin

    plugin = FPAPlugin.__new__(FPAPlugin)
    plugin.config = {}
    events = plugin.get_events()
    assert "fpa.budget_cycle.opened" in events
    assert "fpa.budget.approved" in events
    assert "fpa.forecast_snapshot.taken" in events
    assert "fpa.scenario.generated" in events
    assert "fpa.kpi.status_changed" in events
    assert "fpa.variance.alert" in events


def test_fpa_plugin_subscribe_to_gl_period_closed():
    from pgappforge.plugins.erp.finance.fpa import FPAPlugin

    plugin = FPAPlugin.__new__(FPAPlugin)
    plugin.config = {}
    assert "gl.period.closed" in plugin.subscribe_to()


def test_fpa_plugin_metadata_fields():
    from pgappforge.plugins.erp.finance.fpa import FPAPlugin

    plugin = FPAPlugin.__new__(FPAPlugin)
    plugin.config = {}
    meta = plugin.metadata
    assert meta.name == "fpa"
    assert meta.version == "1.0.0"
    assert "fpa" in meta.tags
    assert "can_fpa_cycle_approve" in meta.permissions


def test_fpa_plugin_depends_on():
    from pgappforge.plugins.erp.finance.fpa import FPAPlugin

    assert "foundation" in FPAPlugin.depends_on
    assert "gl" in FPAPlugin.depends_on


# ---------------------------------------------------------------------------
# Events: dataclass field defaults
# ---------------------------------------------------------------------------

def test_events_have_correct_event_types():
    from pgappforge.plugins.erp.finance.fpa.events import (
        BudgetApprovedEvent,
        BudgetCycleOpenedEvent,
        ForecastSnapshotTakenEvent,
        KPIStatusChangedEvent,
        ScenarioGeneratedEvent,
        VarianceAlertEvent,
    )
    assert BudgetCycleOpenedEvent().event_type == "fpa.budget_cycle.opened"
    assert BudgetApprovedEvent().event_type == "fpa.budget.approved"
    assert ForecastSnapshotTakenEvent().event_type == "fpa.forecast_snapshot.taken"
    assert ScenarioGeneratedEvent().event_type == "fpa.scenario.generated"
    assert KPIStatusChangedEvent().event_type == "fpa.kpi.status_changed"
    assert VarianceAlertEvent().event_type == "fpa.variance.alert"


def test_variance_alert_default_threshold():
    from pgappforge.plugins.erp.finance.fpa.events import VarianceAlertEvent
    e = VarianceAlertEvent()
    assert e.alert_threshold_pct == 15.0


def test_forecast_snapshot_event_fields():
    from pgappforge.plugins.erp.finance.fpa.events import ForecastSnapshotTakenEvent
    e = ForecastSnapshotTakenEvent(
        aggregate_id="c1", aggregate_type="BudgetCycle", tenant_id=TENANT,
        cycle_id="c1", snapshot_date="2026-03-31",
        accounts_processed=12,
        total_actual_cents=1_000_000,
        total_budget_cents=1_100_000,
        total_variance_cents=-100_000,
        variance_pct=-9.09,
    )
    assert e.accounts_processed == 12
    assert e.total_variance_cents == -100_000


# ---------------------------------------------------------------------------
# Internal helpers: _eval_driver_formula
# ---------------------------------------------------------------------------

def test_eval_driver_formula_basic():
    from pgappforge.plugins.erp.finance.fpa.services import _eval_driver_formula
    result = _eval_driver_formula(
        "base_value * params['headcount'] * params['rate']",
        Decimal("1"),
        {"headcount": 10, "rate": 5000},
    )
    assert result == Decimal("50000")


def test_eval_driver_formula_disallows_builtins():
    from pgappforge.plugins.erp.finance.fpa.services import (
        _eval_driver_formula, FPAServiceError,
    )
    with pytest.raises((FPAServiceError, NameError, Exception)):
        _eval_driver_formula("__import__('os').getcwd()", Decimal("1"), {})


# ---------------------------------------------------------------------------
# Internal helpers: _month_range
# ---------------------------------------------------------------------------

def test_month_range_annual_returns_12_months():
    from pgappforge.plugins.erp.finance.fpa.services import _month_range
    from pgappforge.plugins.erp.finance.fpa.models import BudgetCycle

    cycle = BudgetCycle(
        id=_uid(), tenant_id=TENANT, name="FY2026",
        fiscal_year=2026, cycle_type="ANNUAL", status="INPUT_OPEN",
    )
    months = _month_range(cycle)
    assert len(months) == 12
    assert months[0] == date(2026, 1, 1)
    assert months[-1] == date(2026, 12, 1)


def test_month_range_quarterly_returns_3_months():
    from pgappforge.plugins.erp.finance.fpa.services import _month_range
    from pgappforge.plugins.erp.finance.fpa.models import BudgetCycle

    cycle = BudgetCycle(
        id=_uid(), tenant_id=TENANT, name="Q1 2026",
        fiscal_year=2026, cycle_type="QUARTERLY", status="INPUT_OPEN",
    )
    months = _month_range(cycle)
    assert len(months) == 3
    assert months[0] == date(2026, 1, 1)
    assert months[2] == date(2026, 3, 1)


def test_month_range_rolling_returns_12_from_today():
    from pgappforge.plugins.erp.finance.fpa.services import _month_range
    from pgappforge.plugins.erp.finance.fpa.models import BudgetCycle

    cycle = BudgetCycle(
        id=_uid(), tenant_id=TENANT, name="Rolling",
        fiscal_year=2026, cycle_type="ROLLING_12M", status="INPUT_OPEN",
    )
    months = _month_range(cycle)
    assert len(months) == 12
    today = date.today()
    assert months[0] == date(today.year, today.month, 1)
