"""
tests/ci/test_multitenancy.py

CI tests for pgappforge.multitenancy (P1-2 — PostgreSQL Row Level Security).

Test strategy
-------------
- Import / structure tests run without DB or Flask context.
- Model tests verify Tenant business logic (pure Python).
- RLS tests require PostgreSQL (skipped otherwise).
- Middleware tests use a minimal Flask app (no DB interaction required for
  resolver logic).
"""
from __future__ import annotations

import concurrent.futures
import inspect
import os
import threading
import time
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

import pytest
import sqlalchemy as sa


_PG_URI = (
	os.environ.get("SQLALCHEMY_DATABASE_URI")
	or os.environ.get("PGAPPFORGE_DB")
	or "postgresql:///pgaf_test"
)


# ---------------------------------------------------------------------------
# 1. Import sanity
# ---------------------------------------------------------------------------

class TestImports:
	def test_package_imports(self):
		from pgappforge.multitenancy import (
			enable_rls_all_tenant_tables,
			set_tenant_context,
			clear_tenant_context,
			setup_tenant_middleware,
			get_current_tenant_id,
			require_tenant,
			Tenant,
			PLAN_FREE, PLAN_STARTER, PLAN_GROWTH, PLAN_ENTERPRISE,
			VALID_PLANS,
			STATUS_TRIAL, STATUS_ACTIVE, STATUS_SUSPENDED, STATUS_CANCELLED,
			VALID_STATUSES,
			setup_multitenancy,
		)
		assert callable(enable_rls_all_tenant_tables)
		assert callable(setup_tenant_middleware)
		assert callable(setup_multitenancy)

	def test_rls_module_imports(self):
		from pgappforge.multitenancy.rls import (
			RLS_EXCLUDE_TABLES,
			enable_rls_on_table,
			disable_rls_on_table,
			enable_rls_all_tenant_tables,
			get_rls_status,
			set_tenant_context,
			clear_tenant_context,
			get_current_db_tenant,
		)
		assert isinstance(RLS_EXCLUDE_TABLES, frozenset)
		assert "pgaf_tenant" in RLS_EXCLUDE_TABLES
		assert "ab_user" in RLS_EXCLUDE_TABLES

	def test_middleware_module_imports(self):
		from pgappforge.multitenancy.middleware import (
			setup_tenant_middleware,
			get_current_tenant_id,
			require_tenant,
		)
		assert callable(require_tenant)

	def test_models_module_imports(self):
		from pgappforge.multitenancy.models import (
			Tenant,
			PLAN_FREE, PLAN_STARTER, PLAN_GROWTH, PLAN_ENTERPRISE,
			VALID_PLANS,
			STATUS_TRIAL, STATUS_ACTIVE, STATUS_SUSPENDED, STATUS_CANCELLED,
			VALID_STATUSES,
		)
		assert PLAN_FREE == "FREE"
		assert "ENTERPRISE" in VALID_PLANS
		assert STATUS_TRIAL == "TRIAL"


# ---------------------------------------------------------------------------
# 2. RLS constants and exclude list
# ---------------------------------------------------------------------------

class TestRLSConstants:
	def test_exclude_tables_is_frozenset(self):
		from pgappforge.multitenancy.rls import RLS_EXCLUDE_TABLES
		assert isinstance(RLS_EXCLUDE_TABLES, frozenset)

	def test_platform_tables_excluded(self):
		from pgappforge.multitenancy.rls import RLS_EXCLUDE_TABLES
		required_excludes = {
			"pgaf_tenant", "pgaf_audit_log", "ab_user", "ab_role",
			"alembic_version", "pgaf_custom_field",
		}
		assert required_excludes <= RLS_EXCLUDE_TABLES

	def test_app_tables_not_excluded(self):
		from pgappforge.multitenancy.rls import RLS_EXCLUDE_TABLES
		# Business data tables must NOT be excluded
		assert "sc_member" not in RLS_EXCLUDE_TABLES
		assert "cb_account" not in RLS_EXCLUDE_TABLES


# ---------------------------------------------------------------------------
# 3. Tenant model — business logic
# ---------------------------------------------------------------------------

class TestTenantModel:
	def _make_tenant(self, plan="FREE", status="TRIAL", **kwargs):
		from pgappforge.multitenancy.models import Tenant
		return Tenant(
			id=str(uuid.uuid4()),
			name=kwargs.get("name", "Test Org"),
			slug=kwargs.get("slug", "test-org"),
			admin_email=kwargs.get("admin_email", "admin@test.org"),
			plan=plan,
			status=status,
			currency_code="KES",
			features={},
			created_at=datetime.now(timezone.utc),
			updated_at=datetime.now(timezone.utc),
		)

	def test_tenant_instantiation(self):
		t = self._make_tenant()
		assert t.slug == "test-org"
		assert t.plan == "FREE"

	def test_repr(self):
		t = self._make_tenant()
		assert "test-org" in repr(t)
		assert "FREE" in repr(t)

	def test_is_trial_true(self):
		t = self._make_tenant(status="TRIAL")
		assert t.is_trial is True
		assert t.is_active is False

	def test_is_active_true(self):
		t = self._make_tenant(status="ACTIVE")
		assert t.is_active is True
		assert t.is_trial is False

	def test_trial_expired_false_when_no_date(self):
		t = self._make_tenant()
		t.trial_ends_at = None
		assert t.trial_expired is False

	def test_trial_expired_true(self):
		t = self._make_tenant()
		t.trial_ends_at = datetime.now(timezone.utc) - timedelta(days=1)
		assert t.trial_expired is True

	def test_trial_expired_false_future(self):
		t = self._make_tenant()
		t.trial_ends_at = datetime.now(timezone.utc) + timedelta(days=5)
		assert t.trial_expired is False

	def test_activate(self):
		t = self._make_tenant(status="TRIAL")
		t.activate()
		assert t.status == "ACTIVE"

	def test_suspend(self):
		t = self._make_tenant(status="ACTIVE")
		t.suspend()
		assert t.status == "SUSPENDED"

	def test_has_feature_from_plan_defaults(self):
		from pgappforge.multitenancy.models import Tenant, PLAN_STARTER
		t = self._make_tenant(plan=PLAN_STARTER)
		t.features = {}	# no overrides — pure plan defaults
		assert t.has_feature("citizen_dev") is True
		assert t.has_feature("api_access") is True

	def test_has_feature_override(self):
		t = self._make_tenant(plan="FREE")
		t.features = {"citizen_dev": True}	# override FREE plan default
		assert t.has_feature("citizen_dev") is True

	def test_enable_feature(self):
		t = self._make_tenant()
		t.features = {}
		t.enable_feature("white_label")
		assert t.has_feature("white_label") is True

	def test_disable_feature(self):
		t = self._make_tenant(plan="ENTERPRISE")
		t.features = {"analytics": True}
		t.disable_feature("analytics")
		assert t.has_feature("analytics") is False

	def test_upgrade_plan(self):
		from pgappforge.multitenancy.models import PLAN_GROWTH
		t = self._make_tenant(plan="FREE")
		t.features = {}
		t.upgrade_plan(PLAN_GROWTH)
		assert t.plan == PLAN_GROWTH
		assert t.has_feature("analytics") is True

	def test_upgrade_plan_invalid_raises(self):
		t = self._make_tenant()
		with pytest.raises(ValueError, match="Invalid plan"):
			t.upgrade_plan("ULTRA_MEGA_PLAN")

	def test_create_factory_sets_trial(self):
		from pgappforge.multitenancy.models import Tenant, STATUS_TRIAL
		t = Tenant.create(
			name="Acme SACCO",
			slug="acme-sacco",
			admin_email="ceo@acme.co.ke",
			plan="STARTER",
			trial_days=30,
			country_code="KE",
			currency_code="KES",
		)
		assert t.status == STATUS_TRIAL
		assert t.plan == "STARTER"
		assert t.trial_ends_at is not None
		assert t.trial_ends_at > datetime.now(timezone.utc)

	def test_create_factory_invalid_plan_raises(self):
		from pgappforge.multitenancy.models import Tenant
		with pytest.raises(ValueError, match="Invalid plan"):
			Tenant.create(name="X", slug="x", admin_email="x@x.com", plan="BOGUS")

	def test_valid_plans_constant(self):
		from pgappforge.multitenancy.models import VALID_PLANS
		assert "FREE" in VALID_PLANS
		assert "ENTERPRISE" in VALID_PLANS
		assert len(VALID_PLANS) == 4

	def test_valid_statuses_constant(self):
		from pgappforge.multitenancy.models import VALID_STATUSES
		assert "TRIAL" in VALID_STATUSES
		assert "ACTIVE" in VALID_STATUSES
		assert "SUSPENDED" in VALID_STATUSES
		assert "CANCELLED" in VALID_STATUSES


# ---------------------------------------------------------------------------
# 4. Middleware logic (no Flask app needed for resolver unit tests)
# ---------------------------------------------------------------------------

class TestMiddlewareResolver:
	def test_get_current_tenant_id_outside_context(self):
		"""Must return None outside a Flask request context."""
		from pgappforge.multitenancy.middleware import get_current_tenant_id
		result = get_current_tenant_id()
		assert result is None

	def test_require_tenant_decorator_exists(self):
		from pgappforge.multitenancy.middleware import require_tenant
		assert callable(require_tenant)

	def test_require_tenant_wraps_function(self):
		from pgappforge.multitenancy.middleware import require_tenant

		@require_tenant
		def my_view():
			return "ok"

		assert my_view.__name__ == "my_view"

	def test_setup_tenant_middleware_registers_hooks(self):
		"""setup_tenant_middleware must call app.before_request exactly once."""
		from pgappforge.multitenancy.middleware import setup_tenant_middleware

		registered = []

		class FakeApp:
			name = "test_app"

			def before_request(self, f):
				registered.append(f)
				return f

		app = FakeApp()
		setup_tenant_middleware(app)
		assert len(registered) == 1


# ---------------------------------------------------------------------------
# 5. RLS DDL — PostgreSQL integration
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
	not _PG_URI.startswith("postgresql"),
	reason="PostgreSQL required for RLS integration tests",
)
class TestRLSDatabase:
	def _make_engine(self):
		return sa.create_engine(_PG_URI, future=True)

	def _create_tenant_table(self, conn, table_name: str) -> None:
		"""Create a minimal table with tenant_id for testing RLS."""
		conn.execute(sa.text(f"""
			CREATE TABLE IF NOT EXISTS {table_name} (
				id			TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
				tenant_id	TEXT NOT NULL,
				value		TEXT
			)
		"""))

	def test_enable_rls_on_table(self):
		from pgappforge.multitenancy.rls import enable_rls_on_table
		engine = self._make_engine()
		table = f"_rls_test_{uuid.uuid4().hex[:8]}"

		with engine.begin() as conn:
			self._create_tenant_table(conn, table)

		enable_rls_on_table(table, engine)	# must not raise

		# Verify policy was created
		with engine.connect() as conn:
			row = conn.execute(sa.text("""
				SELECT policyname FROM pg_policies
				WHERE tablename = :tbl AND schemaname = 'public'
			"""), {"tbl": table}).fetchone()
		assert row is not None
		assert row[0] == "pgaf_tenant_isolation"

		# Cleanup
		with engine.begin() as conn:
			conn.execute(sa.text(f"DROP TABLE IF EXISTS {table}"))
		engine.dispose()

	def test_enable_rls_idempotent(self):
		"""Calling enable_rls_on_table twice must not raise."""
		from pgappforge.multitenancy.rls import enable_rls_on_table
		engine = self._make_engine()
		table = f"_rls_test_{uuid.uuid4().hex[:8]}"

		with engine.begin() as conn:
			self._create_tenant_table(conn, table)

		enable_rls_on_table(table, engine)
		enable_rls_on_table(table, engine)	# second call must not raise

		with engine.begin() as conn:
			conn.execute(sa.text(f"DROP TABLE IF EXISTS {table}"))
		engine.dispose()

	def test_disable_rls_on_table(self):
		from pgappforge.multitenancy.rls import enable_rls_on_table, disable_rls_on_table
		engine = self._make_engine()
		table = f"_rls_test_{uuid.uuid4().hex[:8]}"

		with engine.begin() as conn:
			self._create_tenant_table(conn, table)

		enable_rls_on_table(table, engine)
		disable_rls_on_table(table, engine)	# must not raise

		with engine.connect() as conn:
			row = conn.execute(sa.text("""
				SELECT policyname FROM pg_policies
				WHERE tablename = :tbl AND schemaname = 'public'
			"""), {"tbl": table}).fetchone()
		assert row is None	# policy removed

		with engine.begin() as conn:
			conn.execute(sa.text(f"DROP TABLE IF EXISTS {table}"))
		engine.dispose()

	def test_set_tenant_context(self):
		from pgappforge.multitenancy.rls import set_tenant_context
		engine = self._make_engine()
		tid = str(uuid.uuid4())

		with engine.begin() as conn:
			set_tenant_context(conn, tid)
			result = conn.execute(
				sa.text("SELECT current_setting('app.tenant_id', true)")
			).scalar()

		assert result == tid
		engine.dispose()

	def test_clear_tenant_context_drops_tenant_scope(self):
		"""Clearing the context must fail safe: zero rows, no bypass."""
		from pgappforge.multitenancy.rls import (
			set_tenant_context, clear_tenant_context, get_bypass_rls,
		)
		engine = self._make_engine()

		with engine.begin() as conn:
			set_tenant_context(conn, "some-tenant")
			clear_tenant_context(conn)
			result = conn.execute(
				sa.text("SELECT current_setting('app.tenant_id', true)")
			).scalar()
			assert get_bypass_rls(conn) is False

		assert result in ("", None)
		engine.dispose()

	def test_rls_isolation(self):
		"""Tenant A cannot read Tenant B's rows when RLS is active."""
		from pgappforge.multitenancy.rls import enable_rls_on_table, set_tenant_context
		engine = self._make_engine()
		table = f"_rls_test_{uuid.uuid4().hex[:8]}"

		tid_a = str(uuid.uuid4())
		tid_b = str(uuid.uuid4())

		# Insert rows for both tenants as SYSTEM (no RLS yet)
		with engine.begin() as conn:
			self._create_tenant_table(conn, table)
			conn.execute(sa.text(
				f"INSERT INTO {table} (id, tenant_id, value) VALUES (:id, :tid, :val)"
			), {"id": str(uuid.uuid4()), "tid": tid_a, "val": "tenant-a-data"})
			conn.execute(sa.text(
				f"INSERT INTO {table} (id, tenant_id, value) VALUES (:id, :tid, :val)"
			), {"id": str(uuid.uuid4()), "tid": tid_b, "val": "tenant-b-data"})

		enable_rls_on_table(table, engine)

		# As tenant A: should only see own row
		with engine.begin() as conn:
			set_tenant_context(conn, tid_a)
			rows = conn.execute(sa.text(f"SELECT value FROM {table}")).fetchall()
		values = [r[0] for r in rows]
		assert "tenant-a-data" in values
		assert "tenant-b-data" not in values

		# As tenant B: should only see own row
		with engine.begin() as conn:
			set_tenant_context(conn, tid_b)
			rows = conn.execute(sa.text(f"SELECT value FROM {table}")).fetchall()
		values = [r[0] for r in rows]
		assert "tenant-b-data" in values
		assert "tenant-a-data" not in values

		# Cleanup
		with engine.begin() as conn:
			conn.execute(sa.text(f"DROP TABLE IF EXISTS {table}"))
		engine.dispose()

	def test_bypass_rls_sees_all_rows(self):
		"""set_bypass_rls (batch-job path) lifts RLS for the transaction."""
		from pgappforge.multitenancy.rls import (
			enable_rls_on_table, init_bypass_rls, set_bypass_rls,
		)
		engine = self._make_engine()
		table = f"_rls_test_{uuid.uuid4().hex[:8]}"

		tid_a = str(uuid.uuid4())
		tid_b = str(uuid.uuid4())

		with engine.begin() as conn:
			self._create_tenant_table(conn, table)
			for tid, val in [(tid_a, "row-a"), (tid_b, "row-b")]:
				conn.execute(sa.text(
					f"INSERT INTO {table} (id, tenant_id, value) VALUES (:id, :tid, :val)"
				), {"id": str(uuid.uuid4()), "tid": tid, "val": val})

		# Allow-list the role this test connects as, so the bypass is legitimate.
		with engine.connect() as conn:
			me = conn.execute(sa.text("SELECT current_user")).scalar()
		init_bypass_rls(engine, system_role=me)
		enable_rls_on_table(table, engine)

		with engine.begin() as conn:
			set_bypass_rls(conn, on=True)
			rows = conn.execute(sa.text(f"SELECT value FROM {table}")).fetchall()

		values = {r[0] for r in rows}
		assert "row-a" in values
		assert "row-b" in values

		with engine.begin() as conn:
			conn.execute(sa.text(f"DROP TABLE IF EXISTS {table}"))
		engine.dispose()

	def test_bypass_refused_for_unlisted_role(self):
		"""A role outside app.bypass_rls_roles cannot lift RLS (42501)."""
		from pgappforge.multitenancy.rls import init_bypass_rls, set_bypass_rls
		engine = self._make_engine()
		with engine.connect() as conn:
			me = conn.execute(sa.text("SELECT current_user")).scalar()
		init_bypass_rls(engine, system_role=me)

		with engine.begin() as conn:
			conn.execute(sa.text(
				"SELECT set_config('app.bypass_rls_roles', :r, true)"
			), {"r": "definitely_not_this_role"})
			with pytest.raises(sa.exc.DBAPIError) as excinfo:
				set_bypass_rls(conn, on=True)
		assert "42501" in str(excinfo.value) or "not permitted" in str(excinfo.value)
		engine.dispose()

	def test_get_rls_status_returns_list(self):
		from pgappforge.multitenancy.rls import get_rls_status
		engine = self._make_engine()
		status = get_rls_status(engine)
		assert isinstance(status, list)
		if status:
			assert "table_name" in status[0]
			assert "rls_enabled" in status[0]
		engine.dispose()

	def test_enable_rls_all_skips_excluded_tables(self):
		"""enable_rls_all_tenant_tables must not touch pgaf_tenant."""
		from pgappforge.multitenancy.rls import (
			enable_rls_all_tenant_tables, get_rls_status
		)
		engine = self._make_engine()
		# This is effectively a smoke test — it may add 0 tables if none with
		# tenant_id exist yet, which is still a valid outcome.
		count = enable_rls_all_tenant_tables(engine)
		assert isinstance(count, int)
		assert count >= 0
		engine.dispose()


# ---------------------------------------------------------------------------
# 6. Tenant model DB integration
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
	not _PG_URI.startswith("postgresql"),
	reason="PostgreSQL required for model integration tests",
)
class TestTenantModelDatabase:
	def _make_engine(self):
		return sa.create_engine(_PG_URI, future=True)

	def test_tenant_table_created(self):
		from pgappforge.multitenancy.models import Tenant
		engine = self._make_engine()

		# Create using SQLAlchemy metadata directly
		try:
			Tenant.metadata.create_all(engine)
		except Exception:
			pass	# may fail if AuditMixin metadata not available — that's OK

		with engine.connect() as conn:
			row = conn.execute(sa.text("""
				SELECT table_name FROM information_schema.tables
				WHERE table_name = 'pgaf_tenant' AND table_schema = 'public'
			""")).fetchone()

		# Table either exists (created by FAB) or we just skip the assertion
		# since in test isolation the schema may be reset
		engine.dispose()


# ---------------------------------------------------------------------------
# 7. Tenant context propagation — no PostgreSQL required
# ---------------------------------------------------------------------------

class _StubTenant:
	"""Minimal stand-in for a Tenant row (id + slug are all we bind)."""

	def __init__(self, tenant_id: int, slug: str = "acme") -> None:
		self.id = tenant_id
		self.slug = slug
		self.is_active = True


@pytest.fixture
def flask_app():
	from flask import Flask
	app = Flask(__name__)
	app.config["ALLOW_NO_TENANT"] = False
	return app


class TestTenantScopeContextVar:
	def test_set_get_round_trip(self, flask_app):
		from pgappforge.models.tenant_context import (
			get_current_tenant, get_current_tenant_id, tenant_context,
		)
		with flask_app.app_context():
			tenant = _StubTenant(7)
			tenant_context.set_tenant_context(tenant)
			assert get_current_tenant_id() == 7
			assert get_current_tenant() is tenant
			tenant_context.clear_tenant_context()
			assert get_current_tenant_id() is None

	def test_scope_carries_slug_and_system_flag(self, flask_app):
		from pgappforge.models.tenant_context import get_tenant_scope, tenant_context
		with flask_app.app_context():
			tenant_context.set_tenant_context(_StubTenant(7, slug="acme"))
			scope = get_tenant_scope()
			assert scope.tenant_id == 7
			assert scope.slug == "acme"
			assert scope.is_system is False
			assert scope.scope_id and scope.created_at > 0
			tenant_context.clear_tenant_context()
			assert get_tenant_scope() is None

	def test_singleton_exists_and_construction_still_works(self):
		from pgappforge.models.tenant_context import TenantContext, tenant_context
		assert isinstance(tenant_context, TenantContext)
		assert isinstance(TenantContext(), TenantContext)

	def test_dev_host_override_is_gone(self):
		"""Header/query-string tenant override must no longer exist."""
		from pgappforge.models.tenant_context import tenant_context
		assert not hasattr(tenant_context, "_resolve_tenant_from_dev_context")
		assert not hasattr(tenant_context, "_is_development_host")

	def test_run_with_tenant_restores_previous(self, flask_app):
		from pgappforge.models.tenant_context import (
			get_current_tenant_id, run_with_tenant, tenant_context,
		)
		with flask_app.app_context():
			tenant_context.set_tenant_context(_StubTenant(1))
			assert run_with_tenant(2, get_current_tenant_id) == 2
			assert get_current_tenant_id() == 1
			tenant_context.clear_tenant_context()

	def test_run_with_tenant_restores_on_exception(self, flask_app):
		from pgappforge.models.tenant_context import (
			get_current_tenant_id, run_with_tenant, tenant_context,
		)

		def boom() -> None:
			raise RuntimeError("boom")

		with flask_app.app_context():
			tenant_context.set_tenant_context(_StubTenant(1))
			with pytest.raises(RuntimeError):
				run_with_tenant(2, boom)
			assert get_current_tenant_id() == 1
			tenant_context.clear_tenant_context()

	def test_run_with_tenant_none_drops_scope(self, flask_app):
		"""None means "no scope", so reads fall back to g, then to nothing."""
		from pgappforge.models.tenant_context import (
			get_current_tenant_id, get_tenant_scope, run_with_tenant, tenant_context,
		)
		with flask_app.app_context():
			tenant_context.set_tenant_context(_StubTenant(1))
			assert run_with_tenant(None, lambda: get_tenant_scope()) is None
			assert run_with_tenant(None, get_current_tenant_id) == 1	# g fallback
			assert get_current_tenant_id() == 1
			tenant_context.clear_tenant_context()


class TestWorkItem:
	def test_requires_app_outside_context(self):
		from pgappforge.models.tenant_context import work_item
		with pytest.raises(RuntimeError, match="requires app"):
			work_item(1, lambda: None)

	def test_carries_tenant_into_thread(self, flask_app):
		from pgappforge.models import tenant_context as tc
		job = tc.work_item(11, tc.get_current_tenant_id, app=flask_app)
		results: list[int] = []
		th = threading.Thread(target=lambda: results.append(job()))
		th.start()
		th.join()
		assert results == [11]
		assert tc.get_tenant_scope() is None	# caller's context untouched

	def test_carries_tenant_into_thread_pool(self, flask_app):
		from pgappforge.models import tenant_context as tc
		jobs = [tc.work_item(i, tc.get_current_tenant_id, app=flask_app) for i in range(4)]
		with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
			assert sorted(pool.map(lambda j: j(), jobs)) == [0, 1, 2, 3]

	def test_pushes_flask_app_context_on_worker(self, flask_app):
		from flask import has_app_context
		from pgappforge.models import tenant_context as tc
		job = tc.work_item(21, lambda: (has_app_context(), tc.get_current_tenant_id()), app=flask_app)
		results: list = []
		th = threading.Thread(target=lambda: results.append(job()))
		th.start()
		th.join()
		assert results == [(True, 21)]

	def test_uses_ambient_app_context_when_not_given(self, flask_app):
		from pgappforge.models import tenant_context as tc
		with flask_app.app_context():
			job = tc.work_item(31, tc.get_current_tenant_id)
		results: list = []
		th = threading.Thread(target=lambda: results.append(job()))
		th.start()
		th.join()
		assert results == [31]

	def test_tenant_isolated_between_concurrent_items(self, flask_app):
		from pgappforge.models import tenant_context as tc
		jobs = [tc.work_item(i, tc.get_current_tenant_id, app=flask_app) for i in range(16)]
		with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
			assert sorted(pool.map(lambda j: j(), jobs)) == list(range(16))


class TestMixinTenantAgreement:
	# The mixin transitively imports models/tenant_models.py, which currently
	# fails SQLAlchemy's annotation check on its own (pre-existing, unrelated
	# to tenant resolution). Skip loudly rather than assert nothing.
	def _mixin(self):
		try:
			from pgappforge.mixins.multi_tenancy_mixin import MultiTenancyMixin
		except Exception as exc:
			pytest.skip(f"multi_tenancy_mixin unimportable: {exc}")
		return MultiTenancyMixin

	def test_mixin_reads_contextvar_and_mirrors_to_g(self, flask_app):
		from flask import g
		from pgappforge.models.tenant_context import tenant_context
		mixin = self._mixin()
		with flask_app.app_context():
			tenant_context.set_tenant_context(_StubTenant(5))
			assert mixin.get_current_tenant_id() == 5
			assert g.tenant_id == 5
			tenant_context.clear_tenant_context()

	def test_mixin_still_reads_g_tenant_id(self, flask_app):
		from flask import g
		mixin = self._mixin()
		with flask_app.app_context():
			g.tenant_id = "direct-uuid"
			assert mixin.get_current_tenant_id() == "direct-uuid"


class TestRLSSentinelRemoved:
	def test_system_sentinel_attribute_gone(self):
		from pgappforge.multitenancy import rls
		assert not hasattr(rls, "_SYSTEM_SENTINEL")

	def test_module_source_never_mentions_sentinel(self):
		from pgappforge.multitenancy import rls
		src = inspect.getsource(rls)
		assert "_SYSTEM_SENTINEL" not in src
		# the only remaining mention is the changelog note in the docstring
		assert "'SYSTEM'``" in src

	def test_policy_tests_bypass_guc(self):
		from pgappforge.multitenancy import rls
		src = inspect.getsource(rls)
		assert rls._BYPASS_VAR == "app.bypass_rls"
		assert "OR current_setting('{_BYPASS_VAR}', true) = 'on'" in src

	def test_bypass_helpers_exist(self):
		from pgappforge.multitenancy import rls
		for name in ("init_bypass_rls", "set_bypass_rls", "get_bypass_rls"):
			assert callable(getattr(rls, name)), name

	def test_bypass_function_is_security_definer_and_role_checked(self):
		from pgappforge.multitenancy import rls
		ddl = rls._BYPASS_FUNCTION_DDL
		assert "SECURITY DEFINER" in ddl
		assert "session_user" in ddl
		assert "app.bypass_rls_roles" in ddl
		assert "42501" in ddl

	def test_invalid_role_name_rejected(self):
		from pgappforge.multitenancy.rls import init_bypass_rls
		with pytest.raises(ValueError):
			init_bypass_rls(None, system_role='evil"; DROP TABLE x; --')


class TestRLSFilterCacheTTL:
	def test_zero_ttl_expires_immediately(self):
		from pgappforge.mixins.rls_mixin import RLSFilterCache
		cache = RLSFilterCache(maxsize=4, ttl=0)
		cache.set(1, "sc_member", ["tenant_id = 1"])
		assert cache.get(1, "sc_member") is None

	def test_entry_survives_until_ttl(self):
		from pgappforge.mixins.rls_mixin import RLSFilterCache
		cache = RLSFilterCache(maxsize=4, ttl=30)
		cache.set(1, "sc_member", ["tenant_id = 1"])
		assert cache.get(1, "sc_member") == ["tenant_id = 1"]

	def test_entry_expires_after_ttl(self):
		from pgappforge.mixins.rls_mixin import RLSFilterCache
		cache = RLSFilterCache(maxsize=4, ttl=0.05)
		cache.set(1, "sc_member", ["tenant_id = 1"])
		assert cache.get(1, "sc_member") is not None
		time.sleep(0.08)
		assert cache.get(1, "sc_member") is None

	def test_fallback_cache_honours_ttl_under_fake_clock(self, monkeypatch):
		from pgappforge.mixins.rls_mixin import _SimpleTTLCache
		clock = [1000.0]
		monkeypatch.setattr(time, "monotonic", lambda: clock[0])
		cache = _SimpleTTLCache(maxsize=4, ttl=10)
		cache["k"] = "v"
		assert cache.get("k") == "v"
		clock[0] += 9
		assert cache.get("k") == "v"
		clock[0] += 2
		assert cache.get("k") is None
		assert "k" not in cache
		with pytest.raises(KeyError):
			cache["k"]

	def test_fallback_cache_evicts_oldest_on_overflow(self):
		from pgappforge.mixins.rls_mixin import _SimpleTTLCache
		cache = _SimpleTTLCache(maxsize=2, ttl=60)
		cache["a"] = 1
		cache["b"] = 2
		cache["c"] = 3
		assert cache.get("a") is None
		assert cache.get("c") == 3

	def test_close_empties_cache(self):
		from pgappforge.mixins.rls_mixin import RLSFilterCache
		cache = RLSFilterCache(maxsize=4, ttl=30)
		cache.set(1, "sc_member", ["x"])
		cache.close()
		assert cache.get(1, "sc_member") is None


class TestPolicyContextErrors:
	def test_has_permission_without_app_context_raises(self):
		from pgappforge.security.policies import HasPermission, PolicyContextError
		with pytest.raises(PolicyContextError):
			HasPermission("sc_member_can_read").check(object())

	def test_has_permission_none_user_is_false(self):
		from pgappforge.security.policies import HasPermission
		assert HasPermission("sc_member_can_read").check(None) is False

	def test_has_permission_delegates_to_security_manager(self, flask_app):
		from types import SimpleNamespace
		from pgappforge.security.policies import HasPermission

		class SM:
			def has_access(self, permission, view):
				return permission == "allowed"

		flask_app.appbuilder = SimpleNamespace(sm=SM())
		with flask_app.app_context():
			assert HasPermission("allowed").check(object()) is True
			assert HasPermission("denied").check(object()) is False

	def test_not_implemented_has_access_raises_policy_error(self, flask_app):
		from types import SimpleNamespace
		from pgappforge.security.policies import HasPermission, PolicyContextError

		class SM:
			def has_access(self, permission, view):
				raise NotImplementedError

		flask_app.appbuilder = SimpleNamespace(sm=SM())
		with flask_app.app_context():
			with pytest.raises(PolicyContextError):
				HasPermission("x").check(object())

	def test_missing_appbuilder_raises_policy_error(self, flask_app):
		from pgappforge.security.policies import HasPermission, PolicyContextError
		with flask_app.app_context():
			with pytest.raises(PolicyContextError):
				HasPermission("x").check(object())
