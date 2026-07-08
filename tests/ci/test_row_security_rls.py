"""
tests/ci/test_row_security_rls.py

CI tests for the Row-Level Security plugin.

Tests are structured to run without a live database — they verify:
  1. Module imports and class structure
  2. Event dataclass instantiation
  3. Model class attributes and table names
  4. Service method signatures
  5. GL realtime service structure
  6. FPA BudgetLine dimensions column presence
"""
from __future__ import annotations

import asyncio
import importlib
import inspect

import pytest


# ---------------------------------------------------------------------------
# 1. Import tests
# ---------------------------------------------------------------------------

def test_row_security_plugin_imports():
	mod = importlib.import_module("pgappforge.plugins.erp.platform.row_security")
	assert hasattr(mod, "RowSecurityPlugin")
	assert hasattr(mod, "RowSecurityService")
	assert hasattr(mod, "RowSecurityPolicy")
	assert hasattr(mod, "SecurityContext")


def test_row_security_events_import():
	mod = importlib.import_module("pgappforge.plugins.erp.platform.row_security.events")
	assert hasattr(mod, "RowSecurityPolicyCreatedEvent")
	assert hasattr(mod, "RowSecurityPolicyUpdatedEvent")
	assert hasattr(mod, "SecurityContextComputedEvent")


def test_row_security_models_import():
	mod = importlib.import_module("pgappforge.plugins.erp.platform.row_security.models")
	assert hasattr(mod, "RowSecurityPolicy")
	assert hasattr(mod, "SecurityContext")


def test_row_security_services_import():
	mod = importlib.import_module("pgappforge.plugins.erp.platform.row_security.services")
	assert hasattr(mod, "RowSecurityService")


# ---------------------------------------------------------------------------
# 2. Event dataclass field checks
# ---------------------------------------------------------------------------

def test_policy_created_event_fields():
	from pgappforge.plugins.erp.platform.row_security.events import RowSecurityPolicyCreatedEvent
	ev = RowSecurityPolicyCreatedEvent(
		aggregate_id="pol-1",
		aggregate_type="RowSecurityPolicy",
		tenant_id="t-1",
		policy_id="pol-1",
		entity_type="EMPLOYEE",
	)
	assert ev.event_type == "platform.row_security.policy.created"
	assert ev.policy_id == "pol-1"
	assert ev.entity_type == "EMPLOYEE"
	assert ev.tenant_id == "t-1"


def test_policy_updated_event_fields():
	from pgappforge.plugins.erp.platform.row_security.events import RowSecurityPolicyUpdatedEvent
	ev = RowSecurityPolicyUpdatedEvent(
		aggregate_id="pol-2",
		aggregate_type="RowSecurityPolicy",
		tenant_id="t-1",
		policy_id="pol-2",
		scope_field="department_id",
		allowed_count=3,
	)
	assert ev.event_type == "platform.row_security.policy.updated"
	assert ev.scope_field == "department_id"
	assert ev.allowed_count == 3


def test_security_context_computed_event_fields():
	from pgappforge.plugins.erp.platform.row_security.events import SecurityContextComputedEvent
	ev = SecurityContextComputedEvent(
		aggregate_id="usr-1",
		aggregate_type="SecurityContext",
		tenant_id="t-1",
		user_id="usr-1",
		entity_types=["EMPLOYEE", "GL_ACCOUNT"],
	)
	assert ev.event_type == "platform.row_security.context.computed"
	assert ev.user_id == "usr-1"
	assert "EMPLOYEE" in ev.entity_types


# ---------------------------------------------------------------------------
# 3. Model table names and column presence
# ---------------------------------------------------------------------------

def test_row_security_policy_tablename():
	from pgappforge.plugins.erp.platform.row_security.models import RowSecurityPolicy
	assert RowSecurityPolicy.__tablename__ == "rls_policy"


def test_security_context_tablename():
	from pgappforge.plugins.erp.platform.row_security.models import SecurityContext
	assert SecurityContext.__tablename__ == "rls_context"


def test_row_security_policy_columns():
	from pgappforge.plugins.erp.platform.row_security.models import RowSecurityPolicy
	cols = {c.name for c in RowSecurityPolicy.__table__.columns}
	assert "id" in cols
	assert "tenant_id" in cols
	assert "name" in cols
	assert "entity_type" in cols
	assert "scope_field" in cols
	assert "allowed_values" in cols
	assert "role_id" in cols
	assert "is_active" in cols
	assert "description" in cols


def test_security_context_columns():
	from pgappforge.plugins.erp.platform.row_security.models import SecurityContext
	cols = {c.name for c in SecurityContext.__table__.columns}
	assert "id" in cols
	assert "tenant_id" in cols
	assert "user_id" in cols
	assert "computed_scope" in cols
	assert "computed_at" in cols
	assert "expires_at" in cols


def test_allowed_values_is_jsonb():
	from pgappforge.plugins.erp.platform.row_security.models import RowSecurityPolicy
	from sqlalchemy.dialects.postgresql import JSONB
	col = RowSecurityPolicy.__table__.columns["allowed_values"]
	assert isinstance(col.type, JSONB)


def test_computed_scope_is_jsonb():
	from pgappforge.plugins.erp.platform.row_security.models import SecurityContext
	from sqlalchemy.dialects.postgresql import JSONB
	col = SecurityContext.__table__.columns["computed_scope"]
	assert isinstance(col.type, JSONB)


# ---------------------------------------------------------------------------
# 4. Service method signatures
# ---------------------------------------------------------------------------

def test_row_security_service_has_define_policy():
	from pgappforge.plugins.erp.platform.row_security.services import RowSecurityService
	svc = RowSecurityService()
	assert callable(svc.define_policy)
	sig = inspect.signature(svc.define_policy)
	params = set(sig.parameters)
	assert "role_id" in params
	assert "entity_type" in params
	assert "scope_field" in params
	assert "allowed_values" in params
	assert "name" in params
	assert "tenant_id" in params
	assert "session" in params


def test_row_security_service_has_get_user_scope():
	from pgappforge.plugins.erp.platform.row_security.services import RowSecurityService
	svc = RowSecurityService()
	assert callable(svc.get_user_scope)
	sig = inspect.signature(svc.get_user_scope)
	params = set(sig.parameters)
	assert "user_id" in params
	assert "entity_type" in params
	assert "tenant_id" in params
	assert "session" in params


def test_row_security_service_has_apply_scope_filters():
	from pgappforge.plugins.erp.platform.row_security.services import RowSecurityService
	svc = RowSecurityService()
	assert callable(svc.apply_scope_filters)
	sig = inspect.signature(svc.apply_scope_filters)
	params = set(sig.parameters)
	assert "stmt" in params
	assert "entity_type" in params
	assert "user_id" in params
	assert "tenant_id" in params
	assert "session" in params


def test_define_policy_rejects_unsafe_scope_field():
	from pgappforge.plugins.erp.platform.row_security.services import (
		InvalidRowSecurityPolicyError,
		RowSecurityService,
	)
	svc = RowSecurityService()
	with pytest.raises(InvalidRowSecurityPolicyError, match="scope"):
		svc.define_policy(
			role_id="Manager",
			entity_type="EMPLOYEE",
			scope_field="department_id; drop table users",
			allowed_values=["HR"],
			name="HR managers",
			tenant_id="tenant-1",
			session=object(),
		)


def test_define_policy_rejects_non_list_allowed_values():
	from pgappforge.plugins.erp.platform.row_security.services import (
		InvalidRowSecurityPolicyError,
		RowSecurityService,
	)
	svc = RowSecurityService()
	with pytest.raises(InvalidRowSecurityPolicyError, match="allowed_values"):
		svc.define_policy(
			role_id="Manager",
			entity_type="EMPLOYEE",
			scope_field="department_id",
			allowed_values="HR",
			name="HR managers",
			tenant_id="tenant-1",
			session=object(),
		)


def test_apply_scope_filters_rejects_unsafe_cached_scope_field():
	from pgappforge.plugins.erp.platform.row_security.services import (
		InvalidRowSecurityPolicyError,
		RowSecurityService,
	)
	svc = RowSecurityService()
	svc.get_user_scope = lambda *_args, **_kwargs: {
		"department_id; drop table users": ["HR"],
	}
	with pytest.raises(InvalidRowSecurityPolicyError, match="scope"):
		svc.apply_scope_filters(
			object(),
			"EMPLOYEE",
			"user-1",
			"tenant-1",
			object(),
		)


def test_apply_scope_filters_normalizes_scalar_values():
	import sqlalchemy as sa
	from pgappforge.plugins.erp.platform.row_security.services import RowSecurityService
	svc = RowSecurityService()
	svc.get_user_scope = lambda *_args, **_kwargs: {"department_id": [123, " HR "]}
	stmt = sa.select(sa.literal(1))

	filtered = svc.apply_scope_filters(
		stmt,
		"EMPLOYEE",
		"user-1",
		"tenant-1",
		object(),
	)

	sql = str(filtered)
	assert "department_id" in sql


# ---------------------------------------------------------------------------
# 5. Plugin metadata
# ---------------------------------------------------------------------------

def test_plugin_metadata():
	from pgappforge.plugins.erp.platform.row_security import RowSecurityPlugin
	assert RowSecurityPlugin.domain == "platform"
	assert "foundation" in RowSecurityPlugin.depends_on
	assert RowSecurityPlugin.metadata.name == "row_security"
	assert RowSecurityPlugin.metadata.version == "1.0.0"
	assert "security" in RowSecurityPlugin.metadata.tags


def test_plugin_register_models():
	from pgappforge.plugins.erp.platform.row_security import RowSecurityPlugin
	from pgappforge.plugins.erp.platform.row_security.models import RowSecurityPolicy, SecurityContext
	# Call unbound — BasePlugin.__init__ requires appbuilder; test at class level
	plugin = RowSecurityPlugin.__new__(RowSecurityPlugin)
	models = plugin.register_models()
	assert RowSecurityPolicy in models
	assert SecurityContext in models


def test_plugin_get_events():
	from pgappforge.plugins.erp.platform.row_security import RowSecurityPlugin
	from pgappforge.plugins.erp.platform.row_security.events import (
		RowSecurityPolicyCreatedEvent,
		RowSecurityPolicyUpdatedEvent,
		SecurityContextComputedEvent,
	)
	plugin = RowSecurityPlugin.__new__(RowSecurityPlugin)
	events = plugin.get_events()
	assert RowSecurityPolicyCreatedEvent in events
	assert RowSecurityPolicyUpdatedEvent in events
	assert SecurityContextComputedEvent in events


# ---------------------------------------------------------------------------
# 6. GL realtime service
# ---------------------------------------------------------------------------

def test_realtime_gl_service_imports():
	mod = importlib.import_module("pgappforge.plugins.erp.finance.gl.realtime")
	assert hasattr(mod, "RealtimeGLService")


def test_realtime_gl_service_methods():
	from pgappforge.plugins.erp.finance.gl.realtime import RealtimeGLService
	svc = RealtimeGLService()
	assert callable(svc.get_live_pnl)
	assert callable(svc.get_live_balance_sheet)


def test_realtime_pnl_signature():
	from pgappforge.plugins.erp.finance.gl.realtime import RealtimeGLService
	sig = inspect.signature(RealtimeGLService.get_live_pnl)
	params = set(sig.parameters)
	assert "tenant_id" in params
	assert "period" in params
	assert "session" in params
	assert "dimension_filters" in params
	assert "account_types" in params


def test_realtime_balance_sheet_signature():
	from pgappforge.plugins.erp.finance.gl.realtime import RealtimeGLService
	sig = inspect.signature(RealtimeGLService.get_live_balance_sheet)
	params = set(sig.parameters)
	assert "tenant_id" in params
	assert "period" in params
	assert "session" in params
	assert "dimension_filters" in params


# ---------------------------------------------------------------------------
# 7. FPA BudgetLine dimensions column
# ---------------------------------------------------------------------------

def test_fpa_budget_line_has_dimensions():
	from pgappforge.plugins.erp.finance.fpa.models import BudgetLine
	from sqlalchemy.dialects.postgresql import JSONB
	cols = {c.name for c in BudgetLine.__table__.columns}
	assert "dimensions" in cols, "BudgetLine must have dimensions JSONB column"
	col = BudgetLine.__table__.columns["dimensions"]
	assert isinstance(col.type, JSONB)


# ---------------------------------------------------------------------------
# 8. GL post_simple_journal IC mirror block present (code inspection)
# ---------------------------------------------------------------------------

def test_post_simple_journal_has_ic_mirror_code():
	import inspect as _inspect
	from pgappforge.plugins.erp.finance.gl.services import GLService
	src = _inspect.getsource(GLService.post_simple_journal)
	assert "intercompany_entity_id" in src, \
		"post_simple_journal must detect intercompany_entity_id on line dicts"
	assert "IntercompanyService" in src, \
		"post_simple_journal must import and call IntercompanyService"
	assert "IC mirror posted" in src or "ic_entity" in src, \
		"post_simple_journal must log IC mirror result"
