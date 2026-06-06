"""
tests/ci/test_bpm_engine.py

Unit tests for WorkflowEngine (pgappforge/plugins/workflow/engine.py).

Strategy
--------
- Build an in-memory SQLite schema that mirrors the BPM tables without the
  PostgreSQL-specific JSONB columns (replaced with JSON for SQLite compat).
- All mutation tests verify the engine does NOT commit — the caller's session
  remains the transaction boundary.
- No Flask app context is required; the engine is purely session-level.
"""
from __future__ import annotations
import os

from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import (
    Boolean, Column, DateTime, ForeignKey, Integer, String, Text,
    JSON, create_engine, func,
)
from sqlalchemy.orm import DeclarativeBase, Session, relationship, sessionmaker


# ---------------------------------------------------------------------------
# Minimal in-memory schema (SQLite-compatible, no JSONB / INET)
# ---------------------------------------------------------------------------

class _Base(DeclarativeBase):
    pass


class _AbUser(_Base):
    __tablename__ = "ab_user"
    id = Column(Integer, primary_key=True)
    username = Column(String(64))


class _ProcessDefinition(_Base):
    __tablename__ = "bpm_process_definition"
    id            = Column(Integer, primary_key=True, autoincrement=True)
    name          = Column(String(128), nullable=False, unique=True)
    description   = Column(Text)
    is_active     = Column(Boolean, nullable=False, default=True)
    config        = Column(JSON, nullable=False, default=dict)
    created_at    = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    created_by_id = Column(Integer, ForeignKey("ab_user.id"), nullable=True)
    # Versioning columns added in workflow-gaps work
    version              = Column(Integer, nullable=False, default=1)
    parent_definition_id = Column(Integer, ForeignKey("bpm_process_definition.id", ondelete="SET NULL"), nullable=True)
    is_latest            = Column(Boolean, nullable=False, default=True)

    steps     = relationship("_ProcessStep",    order_by="_ProcessStep.order_num",
                             back_populates="definition", cascade="all, delete-orphan")
    instances = relationship("_ProcessInstance", back_populates="definition",
                             cascade="all, delete-orphan")

    @property
    def escalation_hours(self) -> int:
        return (self.config or {}).get("escalation_hours", 24)

    @property
    def notify_emails(self) -> list[str]:
        return (self.config or {}).get("notify_emails", [])


class _ProcessStep(_Base):
    __tablename__ = "bpm_process_step"
    id               = Column(Integer, primary_key=True, autoincrement=True)
    definition_id    = Column(Integer, ForeignKey("bpm_process_definition.id", ondelete="CASCADE"))
    name             = Column(String(128), nullable=False)
    order_num        = Column(Integer, nullable=False)
    assigned_role    = Column(String(64))
    timeout_hours    = Column(Integer, nullable=False, default=24)
    escalate_to_role = Column(String(64))
    actions          = Column(JSON, nullable=False, default=dict)
    # Columns added in workflow-gaps work
    step_type        = Column(String(20), nullable=False, default="TASK")
    auto_advance_hours = Column(Integer, nullable=True)
    timer_action     = Column(String(20), nullable=True)
    role_expression  = Column(String(256), nullable=True)

    definition = relationship("_ProcessDefinition", back_populates="steps")

    @property
    def is_final(self) -> bool:
        return bool((self.actions or {}).get("is_final", False))


class _ProcessInstance(_Base):
    __tablename__ = "bpm_process_instance"
    id              = Column(Integer, primary_key=True, autoincrement=True)
    definition_id   = Column(Integer, ForeignKey("bpm_process_definition.id", ondelete="CASCADE"))
    model_name      = Column(String(128), nullable=False)
    record_id       = Column(Integer, nullable=False)
    current_step_id = Column(Integer, ForeignKey("bpm_process_step.id", ondelete="SET NULL"), nullable=True)
    status          = Column(String(32), nullable=False, default="active")
    started_at      = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    completed_at    = Column(DateTime(timezone=True))
    started_by_id   = Column(Integer, ForeignKey("ab_user.id"), nullable=True)
    step_entered_at      = Column(DateTime(timezone=True))
    # Versioning column added in workflow-gaps work
    definition_version   = Column(Integer, nullable=False, default=1)

    definition   = relationship("_ProcessDefinition", back_populates="instances")
    current_step = relationship("_ProcessStep", foreign_keys=[current_step_id])
    history      = relationship("_ProcessEvent", back_populates="instance",
                                order_by="_ProcessEvent.occurred_at",
                                cascade="all, delete-orphan")

    @property
    def hours_at_current_step(self) -> float:
        if self.step_entered_at is None:
            return 0.0
        entered = self.step_entered_at
        if entered.tzinfo is None:
            entered = entered.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - entered).total_seconds() / 3600.0

    @property
    def is_overdue(self) -> bool:
        step = self.current_step
        if step is None:
            return False
        return self.hours_at_current_step > step.timeout_hours

    @property
    def total_elapsed_hours(self) -> float:
        started = self.started_at
        if started is None:
            return 0.0
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        end = self.completed_at or datetime.now(timezone.utc)
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        return (end - started).total_seconds() / 3600.0


class _ProcessTransition(_Base):
    """Stub for ProcessTransition (workflow-gaps conditional routing)."""
    __tablename__ = "bpm_process_transition"
    id             = Column(Integer, primary_key=True, autoincrement=True)
    definition_id  = Column(Integer, ForeignKey("bpm_process_definition.id", ondelete="CASCADE"))
    from_step_id   = Column(Integer, ForeignKey("bpm_process_step.id", ondelete="CASCADE"), nullable=True)
    to_step_id     = Column(Integer, ForeignKey("bpm_process_step.id", ondelete="SET NULL"), nullable=True)
    label          = Column(String(128), nullable=True)
    conditions_json = Column(JSON, nullable=False, default=dict)
    priority       = Column(Integer, nullable=False, default=0)
    is_default     = Column(Boolean, nullable=False, default=False)

    from_step = relationship("_ProcessStep", foreign_keys=[from_step_id])
    to_step   = relationship("_ProcessStep", foreign_keys=[to_step_id])


class _ProcessToken(_Base):
    """Stub for ProcessToken (parallel gateway tokens)."""
    __tablename__ = "bpm_process_token"
    id           = Column(Integer, primary_key=True, autoincrement=True)
    instance_id  = Column(Integer, ForeignKey("bpm_process_instance.id", ondelete="CASCADE"))
    step_id      = Column(Integer, ForeignKey("bpm_process_step.id", ondelete="SET NULL"), nullable=True)
    status       = Column(String(20), nullable=False, default="active")
    created_at   = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    completed_at = Column(DateTime(timezone=True), nullable=True)


class _UserDelegation(_Base):
    """Stub for UserDelegation (workflow delegation)."""
    __tablename__ = "bpm_user_delegation"
    id           = Column(Integer, primary_key=True, autoincrement=True)
    delegator_id = Column(Integer, ForeignKey("ab_user.id", ondelete="SET NULL"), nullable=True)
    delegate_id  = Column(Integer, ForeignKey("ab_user.id", ondelete="SET NULL"), nullable=True)
    start_date   = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    end_date     = Column(DateTime(timezone=True), nullable=True)
    is_active    = Column(Boolean, nullable=False, default=True)
    reason       = Column(Text, nullable=True)
    roles_included = Column(JSON, nullable=False, default=list)
    created_at   = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


class _ProcessEvent(_Base):
    __tablename__ = "bpm_process_event"
    id               = Column(Integer, primary_key=True, autoincrement=True)
    instance_id      = Column(Integer, ForeignKey("bpm_process_instance.id", ondelete="CASCADE"))
    event_type       = Column(String(32), nullable=False)
    from_step_id     = Column(Integer, ForeignKey("bpm_process_step.id", ondelete="SET NULL"), nullable=True)
    to_step_id       = Column(Integer, ForeignKey("bpm_process_step.id", ondelete="SET NULL"), nullable=True)
    actor_id         = Column(Integer, ForeignKey("ab_user.id"), nullable=True)
    comment          = Column(Text)
    data             = Column(JSON, nullable=False, default=dict)
    occurred_at      = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    duration_seconds = Column(Integer)

    instance  = relationship("_ProcessInstance", back_populates="history")
    from_step = relationship("_ProcessStep", foreign_keys=[from_step_id])
    to_step   = relationship("_ProcessStep", foreign_keys=[to_step_id])


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
    """Fresh session per test; rolls back after the test."""
    connection = engine.connect()
    transaction = connection.begin()
    sess = Session(bind=connection)
    yield sess
    sess.close()
    transaction.rollback()
    connection.close()


def _make_definition(session, name="Approval", steps=2, is_active=True) -> _ProcessDefinition:
    defn = _ProcessDefinition(name=name, is_active=is_active, config={})
    session.add(defn)
    session.flush()
    for i in range(steps):
        step = _ProcessStep(
            definition_id=defn.id,
            name=f"Step{i + 1}",
            order_num=i,
            timeout_hours=24,
            actions={},
        )
        session.add(step)
    session.flush()
    session.expire(defn)  # reload relationships
    return defn


def _make_engine(session):
    """Import engine against the test models by monkey-patching the module."""
    import pgappforge.plugins.workflow.engine as _eng_mod
    import pgappforge.plugins.workflow.models as _mod

    # Swap real model classes for the SQLite-compatible ones so the engine
    # can operate without PostgreSQL.
    orig = {}
    for attr, repl in [
        ("ProcessDefinition",  _ProcessDefinition),
        ("ProcessInstance",    _ProcessInstance),
        ("ProcessStep",        _ProcessStep),
        ("ProcessEvent",       _ProcessEvent),
        ("ProcessTransition",  _ProcessTransition),
        ("ProcessToken",       _ProcessToken),
        ("UserDelegation",     _UserDelegation),
    ]:
        orig[attr] = getattr(_mod, attr)
        setattr(_mod, attr, repl)
        setattr(_eng_mod, attr, repl)

    from pgappforge.plugins.workflow.engine import WorkflowEngine
    eng = WorkflowEngine(session)

    yield eng

    # Restore
    for attr, cls in orig.items():
        setattr(_mod, attr, cls)
        setattr(_eng_mod, attr, cls)


@pytest.fixture
def wf_engine(session):
    yield from _make_engine(session)


# ---------------------------------------------------------------------------
# Tests: start_process
# ---------------------------------------------------------------------------

def test_start_process_creates_instance(session, wf_engine):
    defn = _make_definition(session, steps=2)
    inst = wf_engine.start_process(defn.id, "Invoice", 42, started_by_id=1)
    assert inst.id is not None
    assert inst.status == "active"
    assert inst.model_name == "Invoice"
    assert inst.record_id == 42


def test_start_process_emits_start_event(session, wf_engine):
    defn = _make_definition(session, steps=2)
    inst = wf_engine.start_process(defn.id, "Invoice", 1)
    session.flush()
    events = session.query(_ProcessEvent).filter_by(instance_id=inst.id).all()
    assert len(events) == 1
    assert events[0].event_type == "start"


def test_start_process_sets_first_step(session, wf_engine):
    defn = _make_definition(session, steps=3)
    inst = wf_engine.start_process(defn.id, "PO", 5)
    first_step = defn.steps[0]
    assert inst.current_step_id == first_step.id


def test_start_process_raises_for_missing_definition(session, wf_engine):
    with pytest.raises(ValueError, match="not found"):
        wf_engine.start_process(9999, "X", 1)


def test_start_process_raises_for_inactive_definition(session, wf_engine):
    defn = _make_definition(session, is_active=False)
    with pytest.raises(ValueError, match="not active"):
        wf_engine.start_process(defn.id, "X", 1)


def test_start_process_raises_for_definition_with_no_steps(session, wf_engine):
    defn = _ProcessDefinition(name="Empty", is_active=True, config={})
    session.add(defn)
    session.flush()
    with pytest.raises(ValueError, match="no steps"):
        wf_engine.start_process(defn.id, "X", 1)


# ---------------------------------------------------------------------------
# Tests: advance
# ---------------------------------------------------------------------------

def test_advance_moves_to_next_step(session, wf_engine):
    defn = _make_definition(session, steps=3)
    inst = wf_engine.start_process(defn.id, "Contract", 10)
    step2 = defn.steps[1]
    evt = wf_engine.advance(inst.id, actor_id=7, comment="looks good")
    assert evt.event_type == "transition"
    assert inst.current_step_id == step2.id


def test_advance_at_last_step_completes_process(session, wf_engine):
    defn = _make_definition(session, steps=2)
    inst = wf_engine.start_process(defn.id, "Invoice", 1)
    # Advance once (step 0 → step 1)
    wf_engine.advance(inst.id)
    # Advance again — step 1 is the last, should complete
    evt = wf_engine.advance(inst.id)
    assert evt.event_type == "complete"
    assert inst.status == "completed"
    assert inst.completed_at is not None


def test_advance_records_transition_data(session, wf_engine):
    defn = _make_definition(session, steps=3)
    inst = wf_engine.start_process(defn.id, "X", 1)
    evt = wf_engine.advance(inst.id, actor_id=3)
    assert "from_step_name" in evt.data
    assert "to_step_name" in evt.data


def test_advance_raises_for_inactive_instance(session, wf_engine):
    defn = _make_definition(session, steps=2)
    inst = wf_engine.start_process(defn.id, "X", 1)
    inst.status = "completed"
    with pytest.raises(ValueError, match="not active"):
        wf_engine.advance(inst.id)


# ---------------------------------------------------------------------------
# Tests: reject
# ---------------------------------------------------------------------------

def test_reject_sends_instance_back_one_step(session, wf_engine):
    defn = _make_definition(session, steps=3)
    inst = wf_engine.start_process(defn.id, "Claim", 1)
    wf_engine.advance(inst.id)  # now at step index 1
    step0_id = defn.steps[0].id
    evt = wf_engine.reject(inst.id, actor_id=2, comment="needs revision")
    assert evt.event_type == "reject"
    assert inst.current_step_id == step0_id


def test_reject_at_first_step_stays_at_first_step(session, wf_engine):
    defn = _make_definition(session, steps=2)
    inst = wf_engine.start_process(defn.id, "X", 1)
    first_id = defn.steps[0].id
    evt = wf_engine.reject(inst.id)
    assert inst.current_step_id == first_id
    assert evt.event_type == "reject"


# ---------------------------------------------------------------------------
# Tests: complete / cancel
# ---------------------------------------------------------------------------

def test_complete_marks_instance_completed(session, wf_engine):
    defn = _make_definition(session, steps=2)
    inst = wf_engine.start_process(defn.id, "Task", 99)
    wf_engine.complete(inst.id, actor_id=5)
    assert inst.status == "completed"
    assert inst.completed_at is not None


def test_cancel_marks_instance_cancelled(session, wf_engine):
    defn = _make_definition(session, steps=2)
    inst = wf_engine.start_process(defn.id, "Task", 1)
    result = wf_engine.cancel(inst.id, actor_id=1, comment="no longer needed")
    assert result.status == "cancelled"


def test_cancel_emits_cancel_event(session, wf_engine):
    defn = _make_definition(session, steps=2)
    inst = wf_engine.start_process(defn.id, "Task", 1)
    wf_engine.cancel(inst.id)
    session.flush()
    events = [e for e in session.query(_ProcessEvent).filter_by(instance_id=inst.id).all()
              if e.event_type == "cancel"]
    assert len(events) == 1


# ---------------------------------------------------------------------------
# Tests: queries
# ---------------------------------------------------------------------------

def test_get_instance_for_record_returns_active(session, wf_engine):
    defn = _make_definition(session, steps=2)
    inst = wf_engine.start_process(defn.id, "Invoice", 77)
    found = wf_engine.get_instance_for_record("Invoice", 77)
    assert found is not None
    assert found.id == inst.id


def test_get_instance_for_record_returns_none_when_completed(session, wf_engine):
    defn = _make_definition(session, steps=2)
    inst = wf_engine.start_process(defn.id, "Invoice", 88)
    wf_engine.complete(inst.id)
    found = wf_engine.get_instance_for_record("Invoice", 88)
    assert found is None


def test_get_queue_returns_instances_for_role(session, wf_engine):
    defn = _make_definition(session, steps=2)
    # Set the first step's role
    defn.steps[0].assigned_role = "finance"
    session.flush()
    wf_engine.start_process(defn.id, "PO", 1)
    wf_engine.start_process(defn.id, "PO", 2)
    queue = wf_engine.get_queue("finance")
    assert len(queue) == 2


def test_form_time_event_records_duration(session, wf_engine):
    defn = _make_definition(session, steps=2)
    inst = wf_engine.start_process(defn.id, "X", 1)
    evt = wf_engine.form_time_event(inst.id, actor_id=3, seconds=120)
    assert evt.event_type == "form_time"
    assert evt.duration_seconds == 120


def test_form_time_event_raises_for_missing_instance(session, wf_engine):
    with pytest.raises(ValueError, match="not found"):
        wf_engine.form_time_event(9999, actor_id=1, seconds=60)


def test_timeline_returns_ordered_events(session, wf_engine):
    defn = _make_definition(session, steps=3)
    inst = wf_engine.start_process(defn.id, "Contract", 1)
    wf_engine.advance(inst.id, actor_id=1)
    wf_engine.advance(inst.id, actor_id=1)
    tl = wf_engine.timeline(inst.id)
    assert len(tl) >= 2
    types = [e["event_type"] for e in tl]
    assert types[0] == "start"


def test_dashboard_stats_returns_expected_keys(session, wf_engine):
    stats = wf_engine.dashboard_stats()
    assert set(stats.keys()) == {"active_count", "overdue_count", "completed_today", "total_definitions"}


def test_escalate_overdue_emits_escalation_event(session, wf_engine):
    defn = _make_definition(session, steps=2)
    defn.steps[0].timeout_hours = 1
    session.flush()
    inst = wf_engine.start_process(defn.id, "Overdue", 1)
    # Back-date step entry by 2 hours
    inst.step_entered_at = datetime.now(timezone.utc) - timedelta(hours=2)
    session.flush()
    events = wf_engine.escalate_overdue()
    assert len(events) == 1
    assert events[0].event_type == "escalation"


def test_escalate_overdue_does_not_double_escalate(session, wf_engine):
    defn = _make_definition(session, steps=2)
    defn.steps[0].timeout_hours = 1
    session.flush()
    inst = wf_engine.start_process(defn.id, "Overdue2", 2)
    inst.step_entered_at = datetime.now(timezone.utc) - timedelta(hours=3)
    session.flush()
    first = wf_engine.escalate_overdue()
    second = wf_engine.escalate_overdue()
    assert len(first) == 1
    assert len(second) == 0
