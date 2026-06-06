from __future__ import annotations

"""CI tests for HCM Benefits + Compensation modules.

Strategy: import all ORM models first (which registers their Table objects in
Model.metadata), then patch every PostgreSQL-specific column type (JSONB,
UUID, DateTime(timezone=True), Numeric) to a SQLite-compatible equivalent
before calling metadata.create_all() on an in-memory SQLite engine.

Service methods query the same ORM-mapped tables, so all SELECT/INSERT
operations work against real rows in SQLite.
"""

import uuid
from datetime import date, timedelta

import pytest
import sqlalchemy as sa
from sqlalchemy import BigInteger, DateTime, Float, Integer, String, Text, create_engine
from sqlalchemy.orm import Session

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _uid() -> str:
    return str(uuid.uuid4())


TENANT = _uid()


# ---------------------------------------------------------------------------
# Import models — registers Table objects in Model.metadata
# ---------------------------------------------------------------------------

# Benefits
from pgappforge.plugins.erp.hcm.benefits.models import (  # noqa: E402
    BenefitClaim,
    BenefitDeduction,
    BenefitEnrollment,
    BenefitPlan,
    OpenEnrollmentWindow,
)

# Compensation
from pgappforge.plugins.erp.hcm.compensation.models import (  # noqa: E402
    AllowanceDefinition,
    CompensationGrade,
    CompensationPackage,
    CompensationReviewCycle,
    DeductionDefinition,
    EmployeeAllowance,
    EmployeeDeduction,
)

# Pull the shared ORM metadata
from pgappforge.models.sqla import Model  # noqa: E402

_ORM_METADATA = Model.metadata

# ---------------------------------------------------------------------------
# Type-patching: swap PG-specific types for SQLite-compatible equivalents
# ---------------------------------------------------------------------------

_TABLES_TO_PATCH = {
    "ben_plan",
    "ben_enrollment",
    "ben_claim",
    "ben_deduction",
    "ben_open_enrollment",
    "comp_grade",
    "comp_package",
    "comp_allowance_def",
    "comp_employee_allowance",
    "comp_deduction_def",
    "comp_employee_deduction",
    "comp_review_cycle",
}


def _patch_column_types(metadata: sa.MetaData) -> None:
    """Replace PG-dialect types and server_defaults with SQLite-safe equivalents."""
    from sqlalchemy.dialects.postgresql import JSONB, UUID
    from sqlalchemy import Numeric

    for tname in _TABLES_TO_PATCH:
        tbl = metadata.tables.get(tname)
        if tbl is None:
            continue
        for col in tbl.columns:
            t = col.type
            if isinstance(t, JSONB):
                col.type = sa.JSON()
            elif isinstance(t, UUID):
                col.type = String(36)
            elif isinstance(t, DateTime) and getattr(t, "timezone", False):
                col.type = DateTime()
            elif isinstance(t, Numeric):
                col.type = Float()

            # Strip any PostgreSQL-specific server_defaults — let Python defaults handle it
            if col.server_default is not None:
                sd = str(col.server_default.arg) if hasattr(col.server_default, "arg") else ""
                if any(pg_token in sd for pg_token in ("::", "gen_random_uuid", "jsonb", "nextval")):
                    col.server_default = None


_patch_column_types(_ORM_METADATA)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def engine():
    """Module-scoped in-memory SQLite engine; tables created once."""
    eng = create_engine("sqlite:///:memory:", echo=False)
    _ORM_METADATA.create_all(eng, checkfirst=True, tables=[
        _ORM_METADATA.tables[t] for t in _TABLES_TO_PATCH
        if t in _ORM_METADATA.tables
    ])
    return eng


@pytest.fixture
def session(engine):
    """Per-test session using a savepoint for isolation."""
    conn = engine.connect()
    trans = conn.begin()
    sess = Session(bind=conn)
    yield sess
    sess.close()
    trans.rollback()
    conn.close()


# ---------------------------------------------------------------------------
# Benefits tests
# ---------------------------------------------------------------------------


def test_benefits_imports():
    """All public symbols import cleanly; plugin name is 'benefits'."""
    from pgappforge.plugins.erp.hcm.benefits import (
        BenefitClaim,
        BenefitDeduction,
        BenefitEnrollment,
        BenefitPlan,
        BenefitsPlugin,
        BenefitsService,
        OpenEnrollmentWindow,
    )

    assert BenefitsPlugin.name == "benefits"
    assert BenefitsPlugin.domain == "hcm"
    assert BenefitPlan.__tablename__ == "ben_plan"
    assert BenefitEnrollment.__tablename__ == "ben_enrollment"
    assert BenefitClaim.__tablename__ == "ben_claim"
    assert BenefitDeduction.__tablename__ == "ben_deduction"
    assert OpenEnrollmentWindow.__tablename__ == "ben_open_enrollment"
    svc = BenefitsService()
    assert svc is not None


def test_benefit_plan_enrollment(session: Session):
    """Create BenefitPlan, enroll via service, assert PENDING status."""
    from pgappforge.plugins.erp.hcm.benefits.services import BenefitsService

    plan = BenefitPlan(
        id=_uid(),
        tenant_id=TENANT,
        plan_code="MED01",
        name="Medical",
        plan_type="MEDICAL",
        employee_premium_cents=5000,
        employer_premium_cents=10000,
        coverage_tiers={},
        effective_from=date.today(),
        metadata_={},
    )
    session.add(plan)
    session.flush()

    svc = BenefitsService()
    enrollment = svc.enroll_employee(
        "EMP001",
        plan.id,
        date.today(),
        "SINGLE",
        session,
        tenant_id=TENANT,
    )

    assert enrollment.id is not None
    assert enrollment.status == "PENDING"
    assert enrollment.employee_id == "EMP001"
    assert enrollment.plan_id == plan.id
    assert enrollment.coverage_tier == "SINGLE"


def test_enrollment_lifecycle(session: Session):
    """Enroll → activate → ACTIVE; terminate → TERMINATED."""
    from pgappforge.plugins.erp.hcm.benefits.services import BenefitsService

    plan = BenefitPlan(
        id=_uid(),
        tenant_id=TENANT,
        plan_code="LIFE01",
        name="Life",
        plan_type="LIFE",
        coverage_tiers={},
        effective_from=date.today(),
        metadata_={},
    )
    session.add(plan)
    session.flush()

    svc = BenefitsService()
    enrollment = svc.enroll_employee(
        "EMP002",
        plan.id,
        date.today(),
        "SINGLE",
        session,
        tenant_id=TENANT,
    )
    assert enrollment.status == "PENDING"

    activated = svc.activate_enrollment(enrollment.id, session)
    assert activated.status == "ACTIVE"

    termination_date = date.today() + timedelta(days=30)
    terminated = svc.terminate_enrollment(
        enrollment.id,
        termination_date,
        "voluntary_leave",
        session,
    )
    assert terminated.status == "TERMINATED"
    assert terminated.effective_to == termination_date


def test_claim_workflow(session: Session):
    """Enroll + activate, submit claim → SUBMITTED, adjudicate → APPROVED."""
    from pgappforge.plugins.erp.hcm.benefits.services import BenefitsService

    plan = BenefitPlan(
        id=_uid(),
        tenant_id=TENANT,
        plan_code="DENT01",
        name="Dental",
        plan_type="DENTAL",
        coverage_tiers={},
        effective_from=date.today(),
        metadata_={},
    )
    session.add(plan)
    session.flush()

    svc = BenefitsService()
    enrollment = svc.enroll_employee(
        "EMP003",
        plan.id,
        date.today(),
        "SINGLE",
        session,
        tenant_id=TENANT,
    )
    svc.activate_enrollment(enrollment.id, session)

    claim = svc.submit_claim(
        enrollment.id,
        date.today(),
        15000,
        session,
        service_date=date.today(),
    )
    assert claim.status == "SUBMITTED"
    assert claim.claimed_amount_cents == 15000
    assert claim.employee_id == "EMP003"

    adjudicated = svc.adjudicate_claim(
        claim.id,
        "APPROVED",
        "ADJUDICATOR_01",
        session,
        approved_amount_cents=15000,
    )
    assert adjudicated.status == "APPROVED"
    assert adjudicated.approved_amount_cents == 15000
    assert adjudicated.adjudicator_id == "ADJUDICATOR_01"
    assert adjudicated.adjudicated_at is not None


def test_generate_deductions(session: Session):
    """Plan with tiered premiums, enroll+activate, generate_deductions returns 1 row."""
    from pgappforge.plugins.erp.hcm.benefits.services import BenefitsService

    plan = BenefitPlan(
        id=_uid(),
        tenant_id=TENANT,
        plan_code="VIS01",
        name="Vision",
        plan_type="VISION",
        coverage_tiers={"SINGLE": {"employee_cents": 5000, "employer_cents": 10000}},
        effective_from=date.today(),
        metadata_={},
    )
    session.add(plan)
    session.flush()

    svc = BenefitsService()
    enrollment = svc.enroll_employee(
        "EMP004",
        plan.id,
        date.today(),
        "SINGLE",
        session,
        tenant_id=TENANT,
    )
    svc.activate_enrollment(enrollment.id, session)

    result = svc.generate_deductions("2025-01", TENANT, session)

    assert len(result) == 1
    assert result[0].employee_deduction_cents == 5000
    assert result[0].employer_contribution_cents == 10000
    assert result[0].status == "PENDING"
    assert result[0].period == "2025-01"
    assert result[0].employee_id == "EMP004"


def test_benefits_bpm_registered():
    """BPM capabilities hcm.benefits.enroll and hcm.benefits.terminate are registered."""
    import pgappforge.plugins.erp.hcm.benefits.services  # noqa: F401
    from pgappforge.plugins.workflow.engine import BPMActionRegistry

    caps = {c["name"] for c in BPMActionRegistry.list_capabilities()}
    assert "hcm.benefits.enroll" in caps
    assert "hcm.benefits.terminate" in caps


# ---------------------------------------------------------------------------
# Compensation tests
# ---------------------------------------------------------------------------


def test_compensation_imports():
    """All public compensation symbols import cleanly; plugin name is 'compensation'."""
    from pgappforge.plugins.erp.hcm.compensation import (
        AllowanceDefinition,
        CompensationBudgetError,
        CompensationGrade,
        CompensationNotFoundError,
        CompensationPackage,
        CompensationPlugin,
        CompensationReviewCycle,
        CompensationService,
        CompensationServiceError,
        CompensationStateError,
        DeductionDefinition,
        EmployeeAllowance,
        EmployeeDeduction,
    )

    assert CompensationPlugin.name == "compensation"
    assert CompensationPlugin.domain == "hcm"
    assert CompensationGrade.__tablename__ == "comp_grade"
    assert CompensationPackage.__tablename__ == "comp_package"
    assert AllowanceDefinition.__tablename__ == "comp_allowance_def"
    assert EmployeeAllowance.__tablename__ == "comp_employee_allowance"
    assert DeductionDefinition.__tablename__ == "comp_deduction_def"
    assert EmployeeDeduction.__tablename__ == "comp_employee_deduction"
    assert CompensationReviewCycle.__tablename__ == "comp_review_cycle"

    svc = CompensationService()
    assert svc is not None
    assert issubclass(CompensationNotFoundError, CompensationServiceError)
    assert issubclass(CompensationStateError, CompensationServiceError)
    assert issubclass(CompensationBudgetError, CompensationServiceError)


def test_assign_package(session: Session):
    """assign_package inserts a CompensationPackage with correct fields."""
    from pgappforge.plugins.erp.hcm.compensation.services import CompensationService

    svc = CompensationService()
    pkg = svc.assign_package(
        "EMP001",
        None,
        5_000_000,
        date.today(),
        session,
        tenant_id=TENANT,
        currency_code="KES",
    )

    assert pkg.id is not None
    assert pkg.base_salary_cents == 5_000_000
    assert pkg.employee_id == "EMP001"
    assert pkg.tenant_id == TENANT
    assert pkg.currency_code == "KES"
    assert pkg.pay_frequency == "MONTHLY"
    assert pkg.package_type == "STANDARD"
    assert pkg.effective_to is None


def test_compute_total_package(session: Session):
    """assign_package + get_active_package + compute_total_package returns correct dict."""
    from pgappforge.plugins.erp.hcm.compensation.services import CompensationService

    svc = CompensationService()
    today = date.today()
    svc.assign_package(
        "EMP005",
        None,
        5_000_000,
        today,
        session,
        tenant_id=TENANT,
        currency_code="KES",
    )

    pkg = svc.get_active_package("EMP005", today, TENANT, session)
    assert pkg is not None
    assert pkg.base_salary_cents == 5_000_000

    result = svc.compute_total_package("EMP005", today, TENANT, session)

    assert result["base_salary_cents"] == 5_000_000
    assert "total_allowances_cents" in result
    assert "total_deductions_cents" in result
    assert "gross_salary_cents" in result
    assert "total_cost_to_company_cents" in result
    assert result["employee_id"] == "EMP005"
    assert result["currency_code"] == "KES"
    # No allowances/deductions assigned — gross == base
    assert result["gross_salary_cents"] == 5_000_000


def test_review_cycle_budget_error(session: Session):
    """approve_review_cycle raises CompensationBudgetError when committed > budget."""
    from pgappforge.plugins.erp.hcm.compensation.services import (
        CompensationBudgetError,
        CompensationService,
    )

    today = date.today()
    cycle = CompensationReviewCycle(
        id=_uid(),
        tenant_id=TENANT,
        cycle_type="ANNUAL_MERIT",
        review_year=today.year,
        status="IN_PROGRESS",
        budget_pool_cents=1_000_000,
        committed_cents=1_200_000,  # intentionally over budget
        period_start=today.replace(month=1, day=1),
        period_end=today.replace(month=12, day=31),
        metadata_={},
    )
    session.add(cycle)
    session.flush()

    svc = CompensationService()
    with pytest.raises(CompensationBudgetError):
        svc.approve_review_cycle(cycle.id, "APPROVER_01", session)
