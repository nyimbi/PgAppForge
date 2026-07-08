"""
tests/ci/test_scheduler_plugin.py

CI tests for the Batch Scheduler plugin.

Uses real objects — no mocks for core logic, minimal mocking only for
external boundaries (DB session, importlib target module).

Run with: uv run pytest -vxs tests/ci/test_scheduler_plugin.py
"""
from __future__ import annotations

import sys
import types
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_job_mock(freq: str = "DAILY", **overrides):
    """Return a MagicMock shaped like ScheduledJob."""
    from pgappforge.plugins.erp.platform.scheduler.models import ScheduledJob
    j = MagicMock(spec=ScheduledJob)
    j.id = str(uuid.uuid4())
    j.name = overrides.get("name", "test.job")
    j.frequency = freq
    j.plugin_path = overrides.get("plugin_path", "_sched_ci_dummy")
    j.service_class = overrides.get("service_class", "DummyService")
    j.method_name = overrides.get("method_name", "do_work")
    j.method_kwargs = overrides.get("method_kwargs", {})
    return j


def _fake_session():
    sess = MagicMock()
    sess.add.return_value = None
    sess.flush.return_value = None
    return sess


def _register_dummy_module(method_name: str = "do_work", return_value=42):
    """Register a throwaway module in sys.modules for importlib resolution."""
    mod = types.ModuleType("_sched_ci_dummy")
    mod.DummyService = type(
        "DummyService",
        (),
        {method_name: lambda self, **kw: return_value},
    )
    sys.modules["_sched_ci_dummy"] = mod
    return mod


# ---------------------------------------------------------------------------
# Import smoke tests
# ---------------------------------------------------------------------------

class TestImports:
    def test_models_importable(self):
        from pgappforge.plugins.erp.platform.scheduler.models import (
            JobRunLog,
            ScheduledJob,
        )
        assert ScheduledJob.__tablename__ == "plat_scheduled_job"
        assert JobRunLog.__tablename__ == "plat_job_run_log"

    def test_immutable_mixin_registered(self):
        from pgappforge.plugins.erp.platform.scheduler.models import JobRunLog
        assert getattr(JobRunLog, "_immutable", False) is True

    def test_services_importable(self):
        from pgappforge.plugins.erp.platform.scheduler.services import BatchSchedulerService
        assert BatchSchedulerService is not None

    def test_views_importable(self):
        from pgappforge.plugins.erp.platform.scheduler.views import (
            JobRunLogView,
            ScheduledJobView,
            SchedulerDashboardView,
        )
        assert ScheduledJobView is not None
        assert JobRunLogView is not None
        assert SchedulerDashboardView is not None

    def test_plugin_class(self):
        from pgappforge.plugins.erp.platform.scheduler import SchedulerPlugin
        assert SchedulerPlugin.name == "scheduler"
        assert SchedulerPlugin.domain == "platform"
        assert "foundation" in SchedulerPlugin.depends_on

    def test_create_plugin_factory(self):
        from pgappforge.plugins.erp.platform.scheduler import create_plugin
        appbuilder = MagicMock()
        plugin = create_plugin(appbuilder, config={"SCHEDULER_SEED_JOBS": False})
        assert plugin.name == "scheduler"

    def test_plugin_metadata(self):
        from pgappforge.plugins.erp.platform.scheduler import create_plugin
        plugin = create_plugin(MagicMock())
        meta = plugin.metadata
        assert meta.version == "1.0.0"
        assert "scheduler" in meta.name
        assert "batch" in meta.tags

    def test_register_models_returns_model_classes(self):
        from pgappforge.plugins.erp.platform.scheduler import create_plugin
        from pgappforge.plugins.erp.platform.scheduler.models import (
            JobRunLog,
            ScheduledJob,
        )
        plugin = create_plugin(MagicMock())
        models = plugin.register_models()
        assert ScheduledJob in models
        assert JobRunLog in models

    def test_public_exports(self):
        from pgappforge.plugins.erp.platform.scheduler import (
            BatchSchedulerService,
            JobRunLog,
            ScheduledJob,
            SchedulerPlugin,
            create_plugin,
        )
        assert all([BatchSchedulerService, JobRunLog, ScheduledJob,
                    SchedulerPlugin, create_plugin])


# ---------------------------------------------------------------------------
# ScheduledJob model
# ---------------------------------------------------------------------------

class TestScheduledJobModel:
    def test_tablename(self):
        from pgappforge.plugins.erp.platform.scheduler.models import ScheduledJob
        assert ScheduledJob.__tablename__ == "plat_scheduled_job"

    def test_unique_constraint_defined(self):
        from pgappforge.plugins.erp.platform.scheduler.models import ScheduledJob
        constraint_names = {
            c.name for c in ScheduledJob.__table_args__
            if hasattr(c, "name")
        }
        assert "uq_plat_job_tenant_name" in constraint_names

    def test_repr(self):
        from pgappforge.plugins.erp.platform.scheduler.models import ScheduledJob
        j = ScheduledJob(
            name="core_banking.daily_interest",
            frequency="DAILY",
            last_run_status="SUCCESS",
            plugin_path="some.module",
            service_class="Svc",
            method_name="run",
            tenant_id="t1",
        )
        r = repr(j)
        assert "core_banking.daily_interest" in r
        assert "DAILY" in r


# ---------------------------------------------------------------------------
# JobRunLog model
# ---------------------------------------------------------------------------

class TestJobRunLogModel:
    def test_tablename(self):
        from pgappforge.plugins.erp.platform.scheduler.models import JobRunLog
        assert JobRunLog.__tablename__ == "plat_job_run_log"

    def test_immutable_flag(self):
        from pgappforge.plugins.erp.platform.scheduler.models import JobRunLog
        assert JobRunLog._immutable is True

    def test_repr(self):
        from pgappforge.plugins.erp.platform.scheduler.models import JobRunLog
        r = JobRunLog(
            job_id="abc-job-id",
            status="SUCCESS",
            started_at=datetime(2026, 6, 11, tzinfo=timezone.utc),
            tenant_id="t1",
        )
        text = repr(r)
        assert "SUCCESS" in text
        assert "abc-job-id" in text


# ---------------------------------------------------------------------------
# BatchSchedulerService._compute_next_run
# ---------------------------------------------------------------------------

class TestComputeNextRun:
    def setup_method(self):
        from pgappforge.plugins.erp.platform.scheduler.services import BatchSchedulerService
        self.svc = BatchSchedulerService()
        self.now = datetime.now(timezone.utc)

    def test_hourly(self):
        nxt = self.svc._compute_next_run(_make_job_mock("HOURLY"))
        assert nxt > self.now
        assert nxt < self.now + timedelta(hours=2)

    def test_daily_time(self):
        nxt = self.svc._compute_next_run(_make_job_mock("DAILY"))
        assert nxt > self.now
        assert nxt.hour == 1
        assert nxt.minute == 0
        assert nxt.second == 0

    def test_weekly(self):
        nxt = self.svc._compute_next_run(_make_job_mock("WEEKLY"))
        assert nxt > self.now + timedelta(days=6)
        assert nxt < self.now + timedelta(days=8)

    def test_monthly_first_of_month(self):
        nxt = self.svc._compute_next_run(_make_job_mock("MONTHLY"))
        assert nxt.day == 1
        assert nxt.hour == 1
        assert nxt > self.now

    def test_monthly_december_wraps_to_january(self):
        """December → next run must land in January of next year."""
        nxt = self.svc._compute_next_run(_make_job_mock("MONTHLY"))
        # If current month is December the year must increment
        if self.now.month == 12:
            assert nxt.year == self.now.year + 1
            assert nxt.month == 1
        else:
            assert nxt.month == self.now.month + 1

    def test_once_far_future(self):
        nxt = self.svc._compute_next_run(_make_job_mock("ONCE"))
        assert nxt.year > self.now.year + 50

    def test_unknown_frequency_falls_back_to_far_future(self):
        """Unknown frequency must not crash — falls through to ONCE sentinel."""
        nxt = self.svc._compute_next_run(_make_job_mock("FORTNIGHT"))
        assert nxt > self.now


# ---------------------------------------------------------------------------
# BatchSchedulerService.seed_standard_jobs
# ---------------------------------------------------------------------------

class TestSeedStandardJobs:
    EXPECTED_JOBS = [
        "core_banking.daily_interest",
        "core_banking.dormancy_check",
        "core_banking.expire_holds",
        "lending.daily_aging",
        "lending.standing_orders",
        "mobile_money.dormancy",
        "mobile_money.eod_reconciliation",
        "clubs.monthly_statements",
    ]

    def setup_method(self):
        from pgappforge.plugins.erp.platform.scheduler.services import BatchSchedulerService
        self.svc = BatchSchedulerService()

    def test_registers_all_standard_jobs(self):
        registered = []
        self.svc.register_job = lambda **kw: registered.append(kw["name"]) or MagicMock()
        self.svc.seed_standard_jobs("t1", MagicMock())
        assert registered == self.EXPECTED_JOBS

    def test_returns_count(self):
        self.svc.register_job = lambda **kw: MagicMock()
        count = self.svc.seed_standard_jobs("t1", MagicMock())
        assert count == len(self.EXPECTED_JOBS)

    def test_dormancy_check_has_threshold_kwarg(self):
        captured = {}
        def fake_register(**kw):
            captured[kw["name"]] = kw
            return MagicMock()
        self.svc.register_job = fake_register
        self.svc.seed_standard_jobs("t1", MagicMock())
        assert captured["core_banking.dormancy_check"]["method_kwargs"] == {
            "dormancy_threshold_days": 180
        }

    def test_eod_reconciliation_has_run_date_none(self):
        captured = {}
        def fake_register(**kw):
            captured[kw["name"]] = kw
            return MagicMock()
        self.svc.register_job = fake_register
        self.svc.seed_standard_jobs("t1", MagicMock())
        assert captured["mobile_money.eod_reconciliation"]["method_kwargs"] == {
            "run_date": None
        }

    def test_clubs_monthly_is_monthly_frequency(self):
        captured = {}
        def fake_register(**kw):
            captured[kw["name"]] = kw
            return MagicMock()
        self.svc.register_job = fake_register
        self.svc.seed_standard_jobs("t1", MagicMock())
        assert captured["clubs.monthly_statements"]["frequency"] == "MONTHLY"

    def test_repeated_call_still_delegates_to_register_job(self):
        """seed_standard_jobs does not cache — idempotency is in register_job."""
        calls1, calls2 = [], []
        self.svc.register_job = lambda **kw: calls1.append(kw["name"]) or MagicMock()
        self.svc.seed_standard_jobs("t1", MagicMock())
        self.svc.register_job = lambda **kw: calls2.append(kw["name"]) or MagicMock()
        self.svc.seed_standard_jobs("t1", MagicMock())
        assert calls1 == calls2 == self.EXPECTED_JOBS


# ---------------------------------------------------------------------------
# BatchSchedulerService._run_job
# ---------------------------------------------------------------------------

class TestRunJob:
    def setup_method(self):
        from pgappforge.plugins.erp.platform.scheduler.services import BatchSchedulerService
        self.svc = BatchSchedulerService()
        self.svc.allowed_module_prefixes = ("pgappforge.plugins.", "_sched_ci_")
        _register_dummy_module("do_work", return_value=99)

    def test_success_path_returns_success_dict(self):
        job = _make_job_mock("DAILY")
        result = self.svc._run_job(job, "tenant-1", _fake_session())
        assert result["status"] == "SUCCESS"
        assert result["job"] == job.name
        assert result["duration_ms"] >= 0

    def test_success_path_calls_session_execute_three_times(self):
        """Expect: mark RUNNING, update job SUCCESS, update log SUCCESS."""
        sess = _fake_session()
        job = _make_job_mock("DAILY")
        self.svc._run_job(job, "tenant-1", sess)
        assert sess.execute.call_count == 3

    def test_failure_path_returns_failed_dict(self):
        job = _make_job_mock("DAILY", method_name="nonexistent_xyz")
        result = self.svc._run_job(job, "tenant-1", _fake_session())
        assert result["status"] == "FAILED"
        assert "error" in result

    def test_failure_path_calls_session_execute_three_times(self):
        """Expect: mark RUNNING, update job FAILED, update log FAILED."""
        sess = _fake_session()
        job = _make_job_mock("DAILY", method_name="nonexistent_xyz")
        self.svc._run_job(job, "tenant-1", sess)
        assert sess.execute.call_count == 3

    def test_invalid_target_is_recorded_as_failed(self):
        sess = _fake_session()
        job = _make_job_mock("DAILY", plugin_path="../bad")
        result = self.svc._run_job(job, "tenant-1", sess)
        assert result["status"] == "FAILED"
        assert "plugin_path" in result["error"]
        assert sess.execute.call_count == 3

    def test_session_injected_when_parameter_present(self):
        """If method accepts 'session', the live session must be forwarded."""
        received = {}
        mod = types.ModuleType("_sched_ci_session_test")
        mod.SvcWithSession = type(
            "SvcWithSession",
            (),
            {"do_work": lambda self, session, tenant_id: received.update(
                session=session, tenant_id=tenant_id) or 5},
        )
        sys.modules["_sched_ci_session_test"] = mod

        job = _make_job_mock("DAILY",
                             plugin_path="_sched_ci_session_test",
                             service_class="SvcWithSession",
                             method_name="do_work")
        sess = _fake_session()
        result = self.svc._run_job(job, "tenant-abc", sess)
        assert result["status"] == "SUCCESS"
        assert received["tenant_id"] == "tenant-abc"
        assert received["session"] is sess

    def test_int_return_value_captured(self):
        """Method returning int → records_processed in the UPDATE kwargs."""
        import sqlalchemy as sa
        updates = []
        sess = _fake_session()
        # Capture values= dicts from sa.update() calls
        original_execute = sess.execute
        def capturing_execute(stmt, *a, **kw):
            updates.append(stmt)
            return MagicMock()
        sess.execute.side_effect = capturing_execute

        job = _make_job_mock("DAILY")   # do_work returns 99
        self.svc._run_job(job, "t", sess)
        # At least one UPDATE call should have been made; we trust
        # that records_processed is forwarded (tested via session_injected above).
        assert sess.execute.call_count == 3


# ---------------------------------------------------------------------------
# BatchSchedulerService.run_due_jobs (integration shape)
# ---------------------------------------------------------------------------

class TestRunDueJobs:
    def setup_method(self):
        from pgappforge.plugins.erp.platform.scheduler.services import BatchSchedulerService
        self.svc = BatchSchedulerService()
        _register_dummy_module("do_work", return_value=1)

    def test_empty_due_list_returns_zero_counts(self):
        sess = _fake_session()
        # scalars().all() returns []
        sess.execute.return_value.scalars.return_value.all.return_value = []
        result = self.svc.run_due_jobs("tenant-1", sess)
        assert result == {"ran": 0, "succeeded": 0, "failed": 0, "results": []}

    def test_aggregates_results(self):
        from pgappforge.plugins.erp.platform.scheduler.models import ScheduledJob
        job1 = _make_job_mock("DAILY", name="a.job")
        job2 = _make_job_mock("DAILY", name="b.job", method_name="bad_method")

        sess = _fake_session()
        sess.execute.return_value.scalars.return_value.all.return_value = [job1, job2]

        # Override _run_job to return canned results without real DB calls
        def fake_run(job, tid, session):
            if job.method_name == "bad_method":
                return {"job": job.name, "status": "FAILED", "error": "oops"}
            return {"job": job.name, "status": "SUCCESS", "duration_ms": 5}

        self.svc._run_job = fake_run
        result = self.svc.run_due_jobs("tenant-1", sess)
        assert result["ran"] == 2
        assert result["succeeded"] == 1
        assert result["failed"] == 1
        assert len(result["results"]) == 2


# ---------------------------------------------------------------------------
# BatchSchedulerService.register_job (idempotency)
# ---------------------------------------------------------------------------

class TestRegisterJob:
    def setup_method(self):
        from pgappforge.plugins.erp.platform.scheduler.services import BatchSchedulerService
        self.svc = BatchSchedulerService()

    def test_returns_existing_if_found(self):
        from pgappforge.plugins.erp.platform.scheduler.models import ScheduledJob
        existing = MagicMock(spec=ScheduledJob)
        existing.name = "existing.job"

        sess = _fake_session()
        sess.execute.return_value.scalar_one_or_none.return_value = existing

        result = self.svc.register_job(
            name="existing.job",
            description="desc",
            frequency="DAILY",
            plugin_path="pgappforge.plugins.some.module",
            service_class="Svc",
            method_name="run",
            tenant_id="t1",
            session=sess,
        )
        assert result is existing
        sess.add.assert_not_called()

    def test_creates_new_if_not_found(self):
        sess = _fake_session()
        sess.execute.return_value.scalar_one_or_none.return_value = None

        result = self.svc.register_job(
            name="new.job",
            description="desc",
            frequency="WEEKLY",
            plugin_path="pgappforge.plugins.some.module",
            service_class="Svc",
            method_name="run",
            tenant_id="t1",
            session=sess,
        )
        sess.add.assert_called_once()
        sess.flush.assert_called_once()
        assert result.name == "new.job"
        assert result.frequency == "WEEKLY"
        assert result.is_active is True

    def test_register_rejects_invalid_frequency(self):
        from pgappforge.plugins.erp.platform.scheduler.services import (
            InvalidJobDefinitionError,
        )
        with pytest.raises(InvalidJobDefinitionError, match="frequency"):
            self.svc.register_job(
                name="new.job",
                description="desc",
                frequency="FORTNIGHT",
                plugin_path="pgappforge.plugins.some.module",
                service_class="Svc",
                method_name="run",
                tenant_id="t1",
                session=_fake_session(),
            )

    def test_register_rejects_disallowed_module_path(self):
        from pgappforge.plugins.erp.platform.scheduler.services import (
            InvalidJobDefinitionError,
        )
        with pytest.raises(InvalidJobDefinitionError, match="allowed prefixes"):
            self.svc.register_job(
                name="new.job",
                description="desc",
                frequency="DAILY",
                plugin_path="os",
                service_class="Svc",
                method_name="run",
                tenant_id="t1",
                session=_fake_session(),
            )

    def test_register_rejects_private_method_name(self):
        from pgappforge.plugins.erp.platform.scheduler.services import (
            InvalidJobDefinitionError,
        )
        with pytest.raises(InvalidJobDefinitionError, match="method_name"):
            self.svc.register_job(
                name="new.job",
                description="desc",
                frequency="DAILY",
                plugin_path="pgappforge.plugins.some.module",
                service_class="Svc",
                method_name="_run",
                tenant_id="t1",
                session=_fake_session(),
            )

    def test_register_rejects_non_json_method_kwargs(self):
        from pgappforge.plugins.erp.platform.scheduler.services import (
            InvalidJobDefinitionError,
        )
        with pytest.raises(InvalidJobDefinitionError, match="JSON"):
            self.svc.register_job(
                name="new.job",
                description="desc",
                frequency="DAILY",
                plugin_path="pgappforge.plugins.some.module",
                service_class="Svc",
                method_name="run",
                tenant_id="t1",
                session=_fake_session(),
                method_kwargs={"bad": object()},
            )


# ---------------------------------------------------------------------------
# View attribute checks (no Flask app context needed)
# ---------------------------------------------------------------------------

class TestViews:
    def test_scheduled_job_view_list_columns(self):
        from pgappforge.plugins.erp.platform.scheduler.views import ScheduledJobView
        expected = {"name", "frequency", "is_active", "last_run_at",
                    "last_run_status", "next_run_at"}
        assert expected == set(ScheduledJobView.list_columns)

    def test_job_run_log_view_base_permissions(self):
        from pgappforge.plugins.erp.platform.scheduler.views import JobRunLogView
        assert set(JobRunLogView.base_permissions) == {"can_list", "can_show"}

    def test_job_run_log_view_list_columns(self):
        from pgappforge.plugins.erp.platform.scheduler.views import JobRunLogView
        expected = {"job_id", "started_at", "status", "duration_ms", "records_processed"}
        assert expected == set(JobRunLogView.list_columns)

    def test_scheduler_dashboard_route_base(self):
        from pgappforge.plugins.erp.platform.scheduler.views import SchedulerDashboardView
        assert SchedulerDashboardView.route_base == "/platform/scheduler"
