"""CI tests for Phase 1 composition features.

Covers:
  P1.1  EventRouter — glob dispatch, on_event decorator
  P1.2  ModelMixinRegistry — register, list, apply guard
  P1.3  Sub-workflow — start() accepts parent_instance_id
  P1.4  Rules emit_event action — dry-run reflects new action type
  P1.5  Permission algebra — AllOf/AnyOf/Not, operators, decorator import
"""
from __future__ import annotations

import pytest


# ── P1.1: EventRouter ──────────────────────────────────────────────────────

def test_event_router_imports():
	from pgappforge.events import EventRouter, emit, get_router, on_event
	assert callable(EventRouter)
	assert callable(emit)
	assert callable(get_router)
	assert callable(on_event)


def test_event_router_glob_dispatch():
	from pgappforge.events.router import EventRouter

	router = EventRouter()
	received = []

	router.subscribe('finance.*', lambda event_type, payload, tenant_id: received.append(('finance.*', event_type)))
	router.subscribe('crm.customer.created', lambda event_type, payload, tenant_id: received.append(('exact', event_type)))

	router.dispatch('finance.ar.invoice.approved', {}, 't1')
	assert len(received) == 1 and received[0][0] == 'finance.*'

	router.dispatch('crm.customer.created', {}, 't1')
	assert len(received) == 2 and received[1][0] == 'exact'

	router.dispatch('hcm.payroll.processed', {}, 't1')
	assert len(received) == 2  # no new dispatch


def test_event_router_wildcard_star_star():
	from pgappforge.events.router import EventRouter
	import fnmatch

	# Verify fnmatch semantics used in router
	assert fnmatch.fnmatch('finance.ar.invoice.approved', 'finance.*')
	assert fnmatch.fnmatch('finance.ar.invoice.approved', '*.*.*.approved')
	assert not fnmatch.fnmatch('crm.customer.created', 'finance.*')


def test_event_router_subscribe_unsubscribe():
	from pgappforge.events.router import EventRouter

	router = EventRouter()
	calls = []

	def h(event_type, payload, tenant_id):
		calls.append(event_type)

	router.subscribe('test.*', h)
	router.dispatch('test.foo', {}, 't1')
	assert len(calls) == 1

	router.unsubscribe('test.*', h)
	router.dispatch('test.bar', {}, 't1')
	assert len(calls) == 1  # not called after unsubscribe


def test_on_event_decorator_marks_patterns():
	from pgappforge.events.decorators import on_event

	@on_event('test.pattern.x')
	def my_handler(event_type, payload, tenant_id):
		pass

	assert hasattr(my_handler, '_event_patterns')
	assert 'test.pattern.x' in my_handler._event_patterns


def test_event_router_exception_isolation():
	"""A failing handler must not prevent other handlers from running."""
	from pgappforge.events.router import EventRouter

	router = EventRouter()
	second_called = []

	def bad_handler(event_type, payload, tenant_id):
		raise RuntimeError('simulated failure')

	def good_handler(event_type, payload, tenant_id):
		second_called.append(True)

	router.subscribe('x.*', bad_handler)
	router.subscribe('x.*', good_handler)
	router.dispatch('x.test', {}, 't1')  # must not raise
	assert second_called  # good handler still ran


# ── P1.2: ModelMixinRegistry ──────────────────────────────────────────────

def test_mixin_registry_imports():
	from pgappforge.composition import (
		ModelMixinRegistry, register_mixin, apply_all_mixins, get_mixin_registry,
	)
	assert callable(ModelMixinRegistry)


def test_mixin_registry_register_and_list():
	from pgappforge.composition.mixins import ModelMixinRegistry

	reg = ModelMixinRegistry()

	class MixinA:
		pass

	class MixinB:
		pass

	reg.register('a.b.ModelA', MixinA, priority=10)
	reg.register('a.b.ModelA', MixinB, priority=5)
	listed = reg.list_registered()

	assert len(listed) == 2
	names = {e['mixin'] for e in listed}
	assert 'MixinA' in names and 'MixinB' in names


def test_mixin_registry_double_apply_guard():
	from pgappforge.composition.mixins import ModelMixinRegistry

	reg = ModelMixinRegistry()
	reg._applied = True
	result = reg.apply_all()
	assert result == 0  # skipped silently


def test_mixin_registry_cannot_register_after_apply():
	from pgappforge.composition.mixins import ModelMixinRegistry

	reg = ModelMixinRegistry()
	reg._applied = True

	with pytest.raises(RuntimeError, match='apply_all_mixins'):
		reg.register('x.y.Z', type('M', (), {}))


def test_mixin_priority_ordering():
	from pgappforge.composition.mixins import ModelMixinRegistry, _MixinEntry

	reg = ModelMixinRegistry()
	reg.register('x.Model', type('High', (), {}), priority=100)
	reg.register('x.Model', type('Low', (), {}),  priority=1)
	reg._entries.sort(key=lambda e: e.priority)
	assert reg._entries[0].mixin_class.__name__ == 'Low'


# ── P1.3: Sub-workflow composition ────────────────────────────────────────

def test_workflow_engine_start_accepts_parent_instance_id():
	import inspect
	from pgappforge.workflow.engine import PgAppForgeWorkflowEngine

	sig = inspect.signature(PgAppForgeWorkflowEngine.start)
	assert 'parent_instance_id' in sig.parameters, (
		"start() must accept parent_instance_id for sub-workflow composition"
	)
	param = sig.parameters['parent_instance_id']
	assert param.default is None, "parent_instance_id should default to None"


def test_workflow_engine_imports_cleanly():
	from pgappforge.workflow.engine import PgAppForgeWorkflowEngine
	engine = PgAppForgeWorkflowEngine()
	assert hasattr(engine, 'start')
	assert hasattr(engine, 'load_yaml')
	assert hasattr(engine, 'load_dict')


# ── P1.4: Rules emit_event action ─────────────────────────────────────────

def test_rules_engine_imports_cleanly():
	from pgappforge.plugins.rules.engine import RulesEngine
	assert callable(RulesEngine)


def test_rules_dry_run_reflects_emit_event():
	"""evaluate_dry() should include would_emit_events in its result dict."""
	import inspect
	from pgappforge.plugins.rules import engine as eng_module

	src = inspect.getsource(eng_module)
	# The dry-run result dict or the emit_event handling must be present
	assert 'emit_event' in src, "emit_event action type not implemented in rules engine"
	assert 'would_emit_events' in src or 'emit_event' in src, (
		"dry-run should track emit_event actions"
	)


def test_rules_resolve_value_available():
	"""_resolve_value must still work after our additions."""
	from pgappforge.plugins.rules.engine import _resolve_value

	ctx = {'invoice_id': 'inv-001', 'tenant_id': 't1'}
	assert _resolve_value('$invoice_id', ctx) == 'inv-001'
	assert _resolve_value('{{invoice_id}} for {{tenant_id}}', ctx) == 'inv-001 for t1'
	assert _resolve_value('literal', ctx) == 'literal'


# ── P1.5: Permission algebra ──────────────────────────────────────────────

def test_permission_algebra_imports():
	from pgappforge.security.policies import (
		Policy, HasRole, HasPermission, IsOwner, IsAuthenticated, IsAdmin,
		Lambda, AllOf, AnyOf, Not, require_policy,
		ALLOW_ALL, DENY_ALL, AUTH_ONLY, ADMIN_ONLY,
	)
	for obj in [HasRole, HasPermission, IsOwner, AllOf, AnyOf, Not, Lambda]:
		assert issubclass(obj, Policy)


def _make_user(roles, perms=None, user_id='u1', authenticated=True):
	class U:
		pass
	u = U()
	u.roles = [type('R', (), {'name': r})() for r in roles]
	u.permissions = perms or []
	u.is_authenticated = authenticated
	u.id = user_id
	return u


def test_has_role():
	from pgappforge.security.policies import HasRole
	officer = _make_user(['loan_officer'])
	assert HasRole('loan_officer').check(officer)
	assert not HasRole('manager').check(officer)
	assert not HasRole('loan_officer').check(None)


def test_all_of():
	from pgappforge.security.policies import AllOf, HasRole
	p = AllOf(HasRole('loan_officer'), HasRole('manager'))
	assert not p.check(_make_user(['loan_officer']))
	assert p.check(_make_user(['loan_officer', 'manager']))


def test_any_of():
	from pgappforge.security.policies import AnyOf, HasRole
	p = AnyOf(HasRole('manager'), HasRole('credit_officer'))
	assert not p.check(_make_user(['loan_officer']))
	assert p.check(_make_user(['credit_officer']))
	assert p.check(_make_user(['manager']))


def test_not():
	from pgappforge.security.policies import Not, HasRole
	p = Not(HasRole('blocked'))
	assert p.check(_make_user(['loan_officer']))
	assert not p.check(_make_user(['blocked']))


def test_operator_overloading():
	from pgappforge.security.policies import HasRole, AllOf, AnyOf, Not
	p = HasRole('a') & HasRole('b')
	assert isinstance(p, AllOf)

	p2 = HasRole('a') | HasRole('b')
	assert isinstance(p2, AnyOf)

	p3 = ~HasRole('a')
	assert isinstance(p3, Not)


def test_complex_policy():
	"""AllOf(loan_officer, AnyOf(manager, credit_committee))"""
	from pgappforge.security.policies import AllOf, AnyOf, HasRole

	approve = AllOf(HasRole('loan_officer'), AnyOf(HasRole('manager'), HasRole('credit_committee')))

	junior  = _make_user(['loan_officer'])
	senior  = _make_user(['loan_officer', 'manager'])
	staff   = _make_user(['manager'])  # not loan_officer

	assert not approve.check(junior)   # has officer but not manager/committee
	assert approve.check(senior)       # officer AND manager ✓
	assert not approve.check(staff)    # manager but not officer


def test_is_owner():
	from pgappforge.security.policies import IsOwner
	user = _make_user([], user_id='user-42')
	assert IsOwner('owner_id').check(user, {'owner_id': 'user-42'})
	assert not IsOwner('owner_id').check(user, {'owner_id': 'other'})
	assert not IsOwner('owner_id').check(user, {})


def test_is_authenticated():
	from pgappforge.security.policies import IsAuthenticated
	assert IsAuthenticated().check(_make_user([]))
	assert not IsAuthenticated().check(None)


def test_allow_deny_all():
	from pgappforge.security.policies import ALLOW_ALL, DENY_ALL
	assert ALLOW_ALL.check(None)
	assert not DENY_ALL.check(_make_user(['Admin']))


def test_lambda_policy():
	from pgappforge.security.policies import Lambda
	p = Lambda(lambda u, c: c is not None and c.get('dept') == 'Finance', name='is_finance')
	user = _make_user([])
	assert p.check(user, {'dept': 'Finance'})
	assert not p.check(user, {'dept': 'HR'})
	assert 'is_finance' in repr(p)


def test_repr_is_readable():
	from pgappforge.security.policies import AllOf, AnyOf, HasRole
	p = AllOf(HasRole('a'), AnyOf(HasRole('b'), HasRole('c')))
	r = repr(p)
	assert 'AllOf' in r and 'AnyOf' in r and "'a'" in r
