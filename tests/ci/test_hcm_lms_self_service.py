"""
tests/ci/test_hcm_lms_self_service.py

CI tests for HCM LMS and Self-Service (ESS) modules.

Strategy
--------
- Import smoke tests verify plugin metadata and public API.
- Service tests use a real SQLAlchemy Session over an in-memory SQLite engine
  with SQLite-compatible table definitions (JSON not JSONB, String(36) not
  UUID, DateTime not DateTime(timezone=True), Float not Numeric).
- ``emit_event`` (LMS) and ``SelfServiceService._bus`` (ESS) are patched to
  no-ops so tests never need a Flask context or event log table.
- No @pytest.mark.asyncio, no MagicMock for the session.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import sqlalchemy as sa
from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Session, relationship


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _uid() -> str:
    return str(uuid.uuid4())


TENANT = _uid()


# ---------------------------------------------------------------------------
# Standalone SQLite-compatible ORM base and table definitions
#
# We deliberately do NOT import the plugin model classes — they reference
# JSONB / UUID(as_uuid=False) / DateTime(timezone=True) / Numeric which
# cannot be used with create_all() on SQLite.  Instead we define a minimal
# mirror schema using SQLite-safe column types.  The service code uses
# SQLAlchemy select/insert via the same mapper classes it normally would,
# but since we're patching emit_event and _bus the only things exercised
# are the real service logic and the real session.
# ---------------------------------------------------------------------------

class _Base(DeclarativeBase):
    pass


class _LmsCourse(_Base):
    __tablename__ = "lms_course"

    id = Column(String(36), primary_key=True, default=_uid)
    tenant_id = Column(String(36), nullable=False)
    code = Column(String(50), nullable=True)
    title = Column(String(300), nullable=False)
    description = Column(Text, nullable=True)
    course_type = Column(String(30), nullable=False, default="INTERNAL")
    status = Column(String(20), nullable=False, default="DRAFT")
    duration_minutes = Column(Integer, nullable=False, default=0)
    passing_score = Column(Integer, nullable=False, default=70)
    max_attempts = Column(Integer, nullable=False, default=3)
    is_mandatory = Column(Boolean, nullable=False, default=False)
    mandatory_roles = Column(JSON, nullable=False, default=list)
    due_days = Column(Integer, nullable=True)
    content_url = Column(Text, nullable=True)
    scorm_manifest = Column(JSON, nullable=False, default=dict)
    thumbnail_url = Column(Text, nullable=True)
    tags = Column(JSON, nullable=False, default=list)
    entity_id = Column(String(50), nullable=True)
    created_by = Column(String(50), nullable=True)
    published_at = Column(DateTime, nullable=True)

    lessons = relationship(
        "_LmsLesson", back_populates="course",
        cascade="all, delete-orphan", lazy="select",
    )
    enrollments = relationship(
        "_LmsEnrollment", back_populates="course",
        cascade="all, delete-orphan", lazy="select",
    )
    certificates = relationship(
        "_LmsCertificate", back_populates="course",
        cascade="all, delete-orphan", lazy="select",
    )


class _LmsLesson(_Base):
    __tablename__ = "lms_lesson"

    id = Column(String(36), primary_key=True, default=_uid)
    tenant_id = Column(String(36), nullable=False)
    course_id = Column(
        String(36), ForeignKey("lms_course.id", ondelete="CASCADE"), nullable=False
    )
    title = Column(String(300), nullable=False)
    lesson_type = Column(String(30), nullable=False, default="VIDEO")
    order_num = Column(Integer, nullable=False, default=0)
    content_url = Column(Text, nullable=True)
    duration_minutes = Column(Integer, nullable=False, default=0)
    is_required = Column(Boolean, nullable=False, default=True)
    pass_score = Column(Integer, nullable=False, default=70)

    course = relationship("_LmsCourse", back_populates="lessons", lazy="select")
    progress_rows = relationship(
        "_LmsProgress", back_populates="lesson",
        cascade="all, delete-orphan", lazy="select",
    )


class _LmsEnrollment(_Base):
    __tablename__ = "lms_enrollment"

    id = Column(String(36), primary_key=True, default=_uid)
    tenant_id = Column(String(36), nullable=False)
    employee_id = Column(String(50), nullable=False)
    course_id = Column(
        String(36), ForeignKey("lms_course.id", ondelete="CASCADE"), nullable=False
    )
    status = Column(String(20), nullable=False, default="ENROLLED")
    enrolled_at = Column(DateTime, nullable=False,
                         default=lambda: datetime.now(tz=timezone.utc))
    due_date = Column(Date, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    final_score = Column(Integer, nullable=True)
    passed = Column(Boolean, nullable=True)
    attempt_number = Column(Integer, nullable=False, default=1)
    assigned_by = Column(String(50), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "employee_id", "course_id", "attempt_number",
            name="uq_lms_enrollment_employee_course_attempt",
        ),
    )

    course = relationship("_LmsCourse", back_populates="enrollments", lazy="select")
    progress_rows = relationship(
        "_LmsProgress", back_populates="enrollment",
        cascade="all, delete-orphan", lazy="select",
    )
    certificate = relationship(
        "_LmsCertificate", back_populates="enrollment",
        uselist=False, lazy="select",
    )


class _LmsProgress(_Base):
    __tablename__ = "lms_progress"

    id = Column(String(36), primary_key=True, default=_uid)
    tenant_id = Column(String(36), nullable=False)
    enrollment_id = Column(
        String(36), ForeignKey("lms_enrollment.id", ondelete="CASCADE"), nullable=False
    )
    lesson_id = Column(
        String(36), ForeignKey("lms_lesson.id", ondelete="CASCADE"), nullable=False
    )
    status = Column(String(20), nullable=False, default="NOT_STARTED")
    score = Column(Integer, nullable=True)
    attempts = Column(Integer, nullable=False, default=0)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    time_spent_seconds = Column(Integer, nullable=False, default=0)
    scorm_data = Column(JSON, nullable=False, default=dict)

    __table_args__ = (
        UniqueConstraint(
            "enrollment_id", "lesson_id",
            name="uq_lms_progress_enrollment_lesson",
        ),
    )

    enrollment = relationship("_LmsEnrollment", back_populates="progress_rows", lazy="select")
    lesson = relationship("_LmsLesson", back_populates="progress_rows", lazy="select")


class _LmsCertificate(_Base):
    __tablename__ = "lms_certificate"

    id = Column(String(36), primary_key=True, default=_uid)
    tenant_id = Column(String(36), nullable=False)
    employee_id = Column(String(50), nullable=False)
    course_id = Column(
        String(36), ForeignKey("lms_course.id", ondelete="CASCADE"), nullable=False
    )
    enrollment_id = Column(
        String(36), ForeignKey("lms_enrollment.id", ondelete="CASCADE"), nullable=False
    )
    issued_at = Column(DateTime, nullable=False)
    expires_at = Column(Date, nullable=True)
    certificate_ref = Column(String(100), nullable=False)
    credential_url = Column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "certificate_ref",
            name="uq_lms_certificate_tenant_ref",
        ),
    )

    course = relationship("_LmsCourse", back_populates="certificates", lazy="select")
    enrollment = relationship("_LmsEnrollment", back_populates="certificate", lazy="select")


# --- ESS models ---

class _LeaveRequest(_Base):
    __tablename__ = "ess_leave_request"

    id = Column(String(36), primary_key=True, default=_uid)
    tenant_id = Column(String(36), nullable=False, index=True)
    employee_id = Column(String(50), nullable=False)
    leave_type = Column(String(30), nullable=False)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    days_requested = Column(Float, nullable=False)
    status = Column(String(20), nullable=False, default="PENDING")
    reason = Column(Text, nullable=True)
    approved_by = Column(String(50), nullable=True)
    approved_at = Column(DateTime, nullable=True)
    rejected_by = Column(String(50), nullable=True)
    rejection_reason = Column(Text, nullable=True)
    handover_notes = Column(Text, nullable=True)
    entity_id = Column(String(50), nullable=True)

    VALID_LEAVE_TYPES = frozenset({
        "ANNUAL", "SICK", "MATERNITY", "PATERNITY",
        "COMPASSIONATE", "STUDY", "UNPAID",
    })
    VALID_STATUSES = frozenset({"PENDING", "APPROVED", "REJECTED", "CANCELLED"})


class _LeaveBalance(_Base):
    __tablename__ = "ess_leave_balance"

    id = Column(String(36), primary_key=True, default=_uid)
    tenant_id = Column(String(36), nullable=False, index=True)
    employee_id = Column(String(50), nullable=False)
    leave_type = Column(String(30), nullable=False)
    year = Column(Integer, nullable=False)
    entitled_days = Column(Float, nullable=False, default=0)
    used_days = Column(Float, nullable=False, default=0)
    carried_over_days = Column(Float, nullable=False, default=0)
    balance_days = Column(Float, nullable=False, default=0)

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "employee_id", "leave_type", "year",
            name="uq_ess_leave_balance_tenant_emp_type_year",
        ),
    )

    def recompute_balance(self) -> None:
        self.balance_days = (
            float(self.entitled_days)
            + float(self.carried_over_days)
            - float(self.used_days)
        )


class _ProfileUpdateRequest(_Base):
    __tablename__ = "ess_profile_update"

    id = Column(String(36), primary_key=True, default=_uid)
    tenant_id = Column(String(36), nullable=False, index=True)
    employee_id = Column(String(50), nullable=False)
    requested_changes = Column(JSON, nullable=False)
    status = Column(String(20), nullable=False, default="PENDING")
    submitted_at = Column(DateTime, nullable=False,
                          default=lambda: datetime.now(tz=timezone.utc))
    reviewed_by = Column(String(50), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    notes = Column(Text, nullable=True)

    VALID_STATUSES = frozenset({"PENDING", "APPROVED", "REJECTED"})


class _EssDocument(_Base):
    __tablename__ = "ess_document"

    id = Column(String(36), primary_key=True, default=_uid)
    tenant_id = Column(String(36), nullable=False, index=True)
    employee_id = Column(String(50), nullable=False)
    document_type = Column(String(50), nullable=False)
    title = Column(String(300), nullable=False)
    file_path = Column(Text, nullable=True)
    file_size_bytes = Column(Integer, nullable=True)
    mime_type = Column(String(100), nullable=True)
    period = Column(String(20), nullable=True)
    is_visible = Column(Boolean, nullable=False, default=True)
    metadata_ = Column("metadata", JSON, nullable=False, default=dict)


class _Announcement(_Base):
    __tablename__ = "ess_announcement"

    id = Column(String(36), primary_key=True, default=_uid)
    tenant_id = Column(String(36), nullable=False, index=True)
    title = Column(String(300), nullable=False)
    body = Column(Text, nullable=False)
    author_id = Column(String(50), nullable=True)
    published_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    audience_roles = Column(JSON, nullable=False, default=list)
    is_pinned = Column(Boolean, nullable=False, default=False)
    priority = Column(String(20), nullable=False, default="NORMAL")
    entity_id = Column(String(50), nullable=True)

    VALID_PRIORITIES = frozenset({"LOW", "NORMAL", "HIGH", "URGENT"})


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def engine():
    eng = sa.create_engine("sqlite:///:memory:", future=True)
    _Base.metadata.create_all(eng)
    yield eng
    _Base.metadata.drop_all(eng)


@pytest.fixture
def session(engine):
    conn = engine.connect()
    trans = conn.begin()
    sess = Session(bind=conn)
    yield sess
    sess.close()
    trans.rollback()
    conn.close()


# ---------------------------------------------------------------------------
# Patch helpers
# ---------------------------------------------------------------------------

def _noop_emit(*_args: Any, **_kwargs: Any) -> None:
    """Drop-in for emit_event that requires no session or Flask context."""


class _FakeBus:
    def emit(self, *_args: Any, **_kwargs: Any) -> None:
        pass


# ---------------------------------------------------------------------------
# Patch: redirect service model lookups to the test-local ORM classes.
#
# The LMS service imports its models at the top of the module and binds them
# to local names (LmsCourse, LmsLesson, …). When the service runs a
# ``select(LmsCourse)`` it hits the plugin's ORM class, which is mapped
# against the PG-specific table definition — but that table was never
# created in our SQLite engine.  We therefore patch each model name inside
# the service module to point at our SQLite-compatible mirror class.
# ---------------------------------------------------------------------------

_LMS_PATCHES: dict[str, Any] = {
    "LmsCourse": _LmsCourse,
    "LmsLesson": _LmsLesson,
    "LmsEnrollment": _LmsEnrollment,
    "LmsProgress": _LmsProgress,
    "LmsCertificate": _LmsCertificate,
    "emit_event": _noop_emit,
}

_ESS_PATCHES: dict[str, Any] = {
    "LeaveRequest": _LeaveRequest,
    "LeaveBalance": _LeaveBalance,
    "ProfileUpdateRequest": _ProfileUpdateRequest,
    "EssDocument": _EssDocument,
    "Announcement": _Announcement,
}


def _lms_service():
    """Return a real LmsService instance with models patched to SQLite mirrors."""
    from pgappforge.plugins.erp.hcm.lms.services import LmsService
    return LmsService()


def _ess_service():
    """Return a real SelfServiceService with models patched and _bus stubbed."""
    from pgappforge.plugins.erp.hcm.self_service.services import SelfServiceService
    svc = SelfServiceService.__new__(SelfServiceService)
    svc._bus = _FakeBus()
    return svc


# ===========================================================================
# LMS TESTS
# ===========================================================================

def test_lms_imports():
    """Plugin imports cleanly and plugin.name == 'lms'."""
    from pgappforge.plugins.erp.hcm.lms import LmsPlugin
    from pgappforge.plugins.erp.hcm.lms.services import LmsService
    from pgappforge.plugins.erp.hcm.lms.models import (
        LmsCourse, LmsLesson, LmsEnrollment, LmsProgress, LmsCertificate,
    )
    assert LmsPlugin.name == "lms"
    assert LmsPlugin.domain == "hcm"
    # Service and all five model symbols are importable
    for cls in (LmsService, LmsCourse, LmsLesson, LmsEnrollment, LmsProgress, LmsCertificate):
        assert cls is not None


def test_publish_course(session):
    """DRAFT → PUBLISHED transition updates status and published_at."""
    course = _LmsCourse(
        id=_uid(),
        code="PY101",
        title="Python Basics",
        status="DRAFT",
        tenant_id=TENANT,
        passing_score=70,
        max_attempts=3,
        mandatory_roles=[],
        scorm_manifest={},
        tags=[],
    )
    session.add(course)
    session.flush()

    with patch.multiple("pgappforge.plugins.erp.hcm.lms.services", **_LMS_PATCHES):
        svc = _lms_service()
        result = svc.publish_course(course.id, session)

    assert result.status == "PUBLISHED"
    assert result.published_at is not None


def test_enroll_and_complete_lesson(session):
    """Enroll an employee then complete the sole lesson; enrollment reaches COMPLETED."""
    course_id = _uid()
    lesson_id = _uid()

    course = _LmsCourse(
        id=course_id,
        title="Intro to Testing",
        status="PUBLISHED",
        tenant_id=TENANT,
        passing_score=60,
        max_attempts=3,
        mandatory_roles=[],
        scorm_manifest={},
        tags=[],
        published_at=datetime.now(tz=timezone.utc),
    )
    lesson = _LmsLesson(
        id=lesson_id,
        course_id=course_id,
        title="Lesson 1",
        tenant_id=TENANT,
        is_required=True,
        pass_score=60,
    )
    session.add_all([course, lesson])
    session.flush()

    with patch.multiple("pgappforge.plugins.erp.hcm.lms.services", **_LMS_PATCHES):
        svc = _lms_service()
        enrollment = svc.enroll_employee("EMP001", course_id, TENANT, session)

    assert enrollment.status == "ENROLLED"

    # Confirm a progress row was created
    prog = session.execute(
        sa.select(_LmsProgress).where(_LmsProgress.enrollment_id == enrollment.id)
    ).scalars().all()
    assert len(prog) == 1
    assert prog[0].status == "NOT_STARTED"

    with patch.multiple("pgappforge.plugins.erp.hcm.lms.services", **_LMS_PATCHES):
        svc = _lms_service()
        progress = svc.complete_lesson(enrollment.id, lesson_id, session, score=80)

    assert progress.status == "COMPLETED"
    assert progress.score == 80

    # Enrollment should auto-complete since the only required lesson is done
    session.refresh(enrollment)
    assert enrollment.status == "COMPLETED"
    assert enrollment.passed is True


def test_mandatory_compliance_check(session):
    """Overdue mandatory enrollment appears in compliance violations."""
    course_id = _uid()
    past_due = date.today() - timedelta(days=5)

    course = _LmsCourse(
        id=course_id,
        title="Mandatory Safety Training",
        status="PUBLISHED",
        tenant_id=TENANT,
        is_mandatory=True,
        passing_score=70,
        max_attempts=3,
        mandatory_roles=[],
        scorm_manifest={},
        tags=[],
        published_at=datetime.now(tz=timezone.utc),
    )
    enrollment = _LmsEnrollment(
        id=_uid(),
        employee_id="EMP002",
        course_id=course_id,
        tenant_id=TENANT,
        status="ENROLLED",
        due_date=past_due,
        attempt_number=1,
        enrolled_at=datetime.now(tz=timezone.utc),
    )
    session.add_all([course, enrollment])
    session.flush()

    with patch.multiple("pgappforge.plugins.erp.hcm.lms.services", **_LMS_PATCHES):
        svc = _lms_service()
        violations = svc.check_mandatory_compliance(TENANT, session)

    assert len(violations) >= 1
    violation_enrollment_ids = {v["enrollment_id"] for v in violations}
    assert enrollment.id in violation_enrollment_ids
    assert violations[0]["type"] == "OVERDUE"


def test_course_analytics(session):
    """Analytics dict contains enrollment_count after 1 completed enrollment."""
    course_id = _uid()
    lesson_id = _uid()

    course = _LmsCourse(
        id=course_id,
        title="Analytics Course",
        status="PUBLISHED",
        tenant_id=TENANT,
        passing_score=50,
        max_attempts=3,
        mandatory_roles=[],
        scorm_manifest={},
        tags=[],
        published_at=datetime.now(tz=timezone.utc),
    )
    lesson = _LmsLesson(
        id=lesson_id,
        course_id=course_id,
        title="Module 1",
        tenant_id=TENANT,
        is_required=True,
        pass_score=50,
    )
    session.add_all([course, lesson])
    session.flush()

    with patch.multiple("pgappforge.plugins.erp.hcm.lms.services", **_LMS_PATCHES):
        svc = _lms_service()
        enrollment = svc.enroll_employee("EMP003", course_id, TENANT, session)
        svc.complete_lesson(enrollment.id, lesson_id, session, score=75)
        analytics = svc.get_course_analytics(course_id, session)

    assert "enrollment_count" in analytics
    assert analytics["enrollment_count"] == 1
    assert analytics["course_id"] == course_id


# ===========================================================================
# SELF-SERVICE TESTS
# ===========================================================================

def test_self_service_imports():
    """Plugin imports cleanly and plugin.name == 'self_service'."""
    from pgappforge.plugins.erp.hcm.self_service import (
        SelfServicePlugin,
        SelfServiceService,
        LeaveRequest,
        LeaveBalance,
        Announcement,
    )
    assert SelfServicePlugin.name == "self_service"
    assert SelfServicePlugin.domain == "hcm"
    for cls in (SelfServiceService, LeaveRequest, LeaveBalance, Announcement):
        assert cls is not None


def test_leave_request_workflow(session):
    """Submit → PENDING; approve → APPROVED; balance is deducted."""
    # Pre-seed an annual leave balance so submit doesn't fail on insufficient days
    balance = _LeaveBalance(
        id=_uid(),
        tenant_id=TENANT,
        employee_id="EMP001",
        leave_type="ANNUAL",
        year=date.today().year,
        entitled_days=21.0,
        used_days=0.0,
        carried_over_days=0.0,
        balance_days=21.0,
    )
    session.add(balance)
    session.flush()

    start = date.today()
    end = start + timedelta(days=2)

    with patch.multiple("pgappforge.plugins.erp.hcm.self_service.services", **_ESS_PATCHES):
        svc = _ess_service()
        req = svc.submit_leave_request(
            "EMP001", "ANNUAL", start, end, TENANT, session,
            reason="Holiday",
        )

    assert req.status == "PENDING"
    assert req.id is not None

    with patch.multiple("pgappforge.plugins.erp.hcm.self_service.services", **_ESS_PATCHES):
        svc = _ess_service()
        approved = svc.approve_leave(req.id, "MGR001", session)

    assert approved.status == "APPROVED"
    assert approved.approved_by == "MGR001"

    # Balance should have been deducted
    session.refresh(balance)
    assert balance.used_days > 0


def test_leave_balance_default(session):
    """get_leave_balance creates a default row when none exists."""
    tenant = _uid()  # isolated tenant so no prior balance rows

    with patch.multiple("pgappforge.plugins.erp.hcm.self_service.services", **_ESS_PATCHES):
        svc = _ess_service()
        balance = svc.get_leave_balance("EMP999", "ANNUAL", 2025, tenant, session)

    assert balance.id is not None
    assert balance.entitled_days >= 0
    assert balance.leave_type == "ANNUAL"
    assert balance.year == 2025


def test_publish_announcement(session):
    """publish_announcement creates a record; get_employee_dashboard returns it."""
    tenant = _uid()

    with patch.multiple("pgappforge.plugins.erp.hcm.self_service.services", **_ESS_PATCHES):
        svc = _ess_service()
        ann = svc.publish_announcement(
            "Test Title", "Body text here", "ADMIN01", tenant, session,
        )

    assert ann.id is not None
    assert ann.published_at is not None

    with patch.multiple("pgappforge.plugins.erp.hcm.self_service.services", **_ESS_PATCHES):
        svc = _ess_service()
        dashboard = svc.get_employee_dashboard("EMP001", tenant, session)

    assert isinstance(dashboard["announcements"], list)
    ann_ids = [a.id for a in dashboard["announcements"]]
    assert ann.id in ann_ids
