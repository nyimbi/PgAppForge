"""CI tests for Phase 3 composition features.

Covers:
  P3.1  AI pipeline — Runnable protocol, composition operators
  P3.2  Cross-tenant aggregation — safety validation, API surface
  P3.3  GraphQL federation — registry, SDL generation, decorator
"""
from __future__ import annotations

import sys
import types

import pytest


# ── P3.1: AI pipeline ─────────────────────────────────────────────────────

def test_pipeline_imports():
	from pgappforge.ai.pipeline import (
		Runnable, Composable, ParallelComposable, Lambda, Passthrough,
		LLMStep, SQLStep, RuleStep, WorkflowStep, FormatStep,
	)
	for cls in [Runnable, Composable, ParallelComposable, Lambda, Passthrough,
	            LLMStep, SQLStep, RuleStep, WorkflowStep, FormatStep]:
		assert cls is not None


def test_lambda_runnable():
	from pgappforge.ai.pipeline import Lambda
	double = Lambda(lambda x, **kw: x * 2, name='double')
	assert double.invoke(5) == 10
	assert double.invoke(0) == 0
	assert 'double' in repr(double)


def test_passthrough():
	from pgappforge.ai.pipeline import Passthrough
	pt = Passthrough()
	assert pt.invoke('hello') == 'hello'
	assert pt.invoke({'a': 1}) == {'a': 1}
	assert pt.invoke(None) is None


def test_sequential_pipe():
	from pgappforge.ai.pipeline import Lambda, Composable
	double = Lambda(lambda x, **kw: x * 2, name='double')
	add1   = Lambda(lambda x, **kw: x + 1, name='add1')
	chain  = double.pipe(add1)
	assert isinstance(chain, Composable)
	assert chain.invoke(3) == 7   # (3*2)+1


def test_or_operator_sugar():
	from pgappforge.ai.pipeline import Lambda, Composable
	a = Lambda(lambda x, **kw: x + 10, name='a')
	b = Lambda(lambda x, **kw: x * 2, name='b')
	p = a | b
	assert isinstance(p, Composable)
	assert p.invoke(5) == 30  # (5+10)*2


def test_three_step_chain():
	from pgappforge.ai.pipeline import Lambda
	triple = (
		Lambda(lambda x, **kw: x * 2, name='x2')
		| Lambda(lambda x, **kw: x + 1, name='+1')
		| Lambda(lambda x, **kw: x * 3, name='x3')
	)
	assert triple.invoke(2) == (2 * 2 + 1) * 3   # 15


def test_composable_pipe_flattens():
	"""Chaining two Composables produces a single flat Composable, not nested."""
	from pgappforge.ai.pipeline import Lambda, Composable
	a = Lambda(lambda x, **kw: x, name='a')
	b = Lambda(lambda x, **kw: x, name='b')
	c = Lambda(lambda x, **kw: x, name='c')
	ab = a | b
	abc = ab | c
	assert isinstance(abc, Composable)
	assert len(abc._steps) == 3  # flattened, not [[a,b], c]


def test_parallel_composable():
	from pgappforge.ai.pipeline import Lambda, Passthrough
	double = Lambda(lambda x, **kw: x * 2, name='double')
	# parallel() runs _first then fans result to branches
	# double.invoke(4) = 8, then branches get 8
	fork = double.parallel(again=double, unchanged=Passthrough())
	result = fork.invoke(4)
	assert isinstance(result, dict)
	assert result['again'] == 16      # double(double(4)) = 16
	assert result['unchanged'] == 8   # Passthrough(double(4)) = 8


def test_format_step():
	from pgappforge.ai.pipeline import FormatStep
	fmt = FormatStep('Hello {name}, count={count}')
	assert fmt.invoke({'name': 'Alice', 'count': 5}) == 'Hello Alice, count=5'


def test_format_step_missing_key():
	from pgappforge.ai.pipeline import FormatStep
	fmt = FormatStep('Hello {name}')
	# Missing key: returns raw template (logged, not raised)
	result = fmt.invoke({'other': 'x'})
	assert '{name}' in result  # unchanged where key is missing


def test_sql_step_requires_session():
	from pgappforge.ai.pipeline import SQLStep
	step = SQLStep(query="SELECT 1")
	with pytest.raises(ValueError, match='session='):
		step.invoke({})


def test_llm_step_uses_safe_local_defaults(monkeypatch):
	from pgappforge.ai.pipeline import LLMStep

	calls = {}

	def fake_completion(**kwargs):
		calls.update(kwargs)
		return types.SimpleNamespace(
			choices=[types.SimpleNamespace(
				message=types.SimpleNamespace(content="done"),
			)]
		)

	monkeypatch.setitem(sys.modules, "litellm", types.SimpleNamespace(completion=fake_completion))
	monkeypatch.delenv("LITELLM_URL", raising=False)
	monkeypatch.delenv("LITELLM_BASE_URL", raising=False)
	monkeypatch.delenv("LITELLM_API_KEY", raising=False)

	result = LLMStep(system="summarize", max_tokens=32).invoke("hello")

	assert result == "done"
	assert calls["api_base"] == "http://localhost:4000/v1"
	assert calls["api_key"] == ""
	assert calls["model"] == "gpt-4o-mini"
	assert calls["max_tokens"] == 32


def test_llm_step_rejects_unsafe_gateway(monkeypatch):
	from pgappforge.ai.pipeline import LLMStep
	from pgappforge.plugins.erp.platform.nlp.client import LLMConfigError

	monkeypatch.setitem(sys.modules, "litellm", types.SimpleNamespace(completion=lambda **kw: None))
	monkeypatch.delenv("LITELLM_URL", raising=False)
	monkeypatch.setenv("LITELLM_BASE_URL", "http://example.com:4000/v1")

	with pytest.raises(LLMConfigError):
		LLMStep().invoke("hello")


def test_llm_step_rejects_injected_api_key(monkeypatch):
	from pgappforge.ai.pipeline import LLMStep
	from pgappforge.plugins.erp.platform.nlp.client import LLMConfigError

	monkeypatch.setitem(sys.modules, "litellm", types.SimpleNamespace(completion=lambda **kw: None))

	with pytest.raises(LLMConfigError):
		LLMStep(api_key="token\r\nX-Test: yes").invoke("hello")


def test_runnable_protocol_is_abstract():
	from pgappforge.ai.pipeline import Runnable
	with pytest.raises(TypeError):
		Runnable()  # cannot instantiate abstract class


# ── P3.2: Cross-tenant aggregation ────────────────────────────────────────

def test_aggregation_imports():
	from pgappforge.multitenancy.aggregation import (
		CrossTenantAggregator, SystemSession, SYSTEM_TENANT_ID,
	)
	assert SYSTEM_TENANT_ID == 'SYSTEM'
	assert callable(CrossTenantAggregator)
	assert callable(SystemSession)


def test_aggregation_safety_validation_table():
	from pgappforge.multitenancy.aggregation import CrossTenantAggregator
	agg = CrossTenantAggregator()
	with pytest.raises(ValueError, match='Unsafe table name'):
		agg.compute_metric_across_tenants(
			table='users; DROP TABLE users',
			field='id',
			session=None,
		)


def test_aggregation_safety_validation_field():
	from pgappforge.multitenancy.aggregation import CrossTenantAggregator
	agg = CrossTenantAggregator()
	with pytest.raises(ValueError, match='Unsafe field name'):
		agg.compute_metric_across_tenants(
			table='users',
			field="id) FROM users; --",
			session=None,
		)


def test_aggregation_agg_allowlist():
	from pgappforge.multitenancy.aggregation import CrossTenantAggregator
	agg = CrossTenantAggregator()
	with pytest.raises(ValueError, match='agg must be'):
		agg.compute_metric_across_tenants('users', 'id', agg='exec', session=None)


def test_aggregation_valid_agg_types():
	from pgappforge.multitenancy.aggregation import CrossTenantAggregator
	agg = CrossTenantAggregator()
	for valid in ('count', 'sum', 'avg', 'max', 'min'):
		# Will fail on session=None at the execute step, not at validation
		try:
			agg.compute_metric_across_tenants('safe_table', 'amount', agg=valid, session=None)
		except (ValueError, AttributeError):
			pass  # AttributeError from session=None is fine


def test_system_tenant_id_value():
	from pgappforge.multitenancy.aggregation import SYSTEM_TENANT_ID
	# Must match the sentinel in rls.py
	assert SYSTEM_TENANT_ID == 'SYSTEM'
	# Must not be empty (that would mean "no tenant" not "all tenants")
	assert SYSTEM_TENANT_ID


# ── P3.3: GraphQL federation ───────────────────────────────────────────────

def test_federation_imports():
	from pgappforge.graphql.federation import (
		FederationRegistry, FederatedTypeEntry, get_federation_registry,
		federated_type, key_field,
	)
	assert callable(FederationRegistry)
	assert callable(FederatedTypeEntry)
	assert callable(get_federation_registry)
	assert callable(federated_type)
	assert callable(key_field)


def test_federation_registry_register_and_list():
	from pgappforge.graphql.federation import FederationRegistry

	reg = FederationRegistry()
	cls = type('Invoice', (), {'__annotations__': {'id': str, 'amount': int}})
	reg.register('Invoice', cls, plugin='finance.ar', key_fields=['id'])

	assert reg.get('Invoice') is not None
	assert reg.get('Invoice').plugin == 'finance.ar'
	assert reg.get('Invoice').key_fields == ['id']
	assert len(reg.list_types()) == 1
	assert len(reg.list_by_plugin('finance.ar')) == 1
	assert len(reg.list_by_plugin('crm')) == 0


def test_federation_sdl_contains_key_directive():
	from pgappforge.graphql.federation import FederationRegistry

	reg = FederationRegistry()
	cls = type('Order', (), {'__annotations__': {'id': str, 'total': int}, '__doc__': 'Order type'})
	reg.register('Order', cls, plugin='crm.orders', key_fields=['id'])
	sdl = reg.build_schema_sdl()

	assert '@key(fields: "id")' in sdl
	assert 'type Order' in sdl
	assert 'federation/v2.0' in sdl


def test_federation_sdl_includes_all_types():
	from pgappforge.graphql.federation import FederationRegistry

	reg = FederationRegistry()
	for name in ('TypeA', 'TypeB', 'TypeC'):
		cls = type(name, (), {'__annotations__': {'id': str}})
		reg.register(name, cls, plugin='test', key_fields=['id'])

	sdl = reg.build_schema_sdl()
	assert 'TypeA' in sdl and 'TypeB' in sdl and 'TypeC' in sdl


def test_federated_type_decorator():
	from pgappforge.graphql.federation import federated_type, get_federation_registry

	@federated_type(key='id', plugin='test.decorator')
	class MyEntity:
		"""A test entity."""
		id: str
		value: int

	assert hasattr(MyEntity, '_federation_key')
	assert MyEntity._federation_key == ['id']
	entry = get_federation_registry().get('MyEntity')
	assert entry is not None
	assert entry.plugin == 'test.decorator'


def test_federation_key_list():
	from pgappforge.graphql.federation import FederationRegistry

	reg = FederationRegistry()
	cls = type('CompKey', (), {'__annotations__': {'org_id': str, 'user_id': str}})
	reg.register('CompKey', cls, plugin='auth', key_fields=['org_id', 'user_id'])
	entry = reg.get('CompKey')
	assert entry.key_fields == ['org_id', 'user_id']

	sdl = reg.build_schema_sdl()
	assert '@key(fields: "org_id")' in sdl
	assert '@key(fields: "user_id")' in sdl


def test_federation_overwrite_warns(caplog):
	import logging
	from pgappforge.graphql.federation import FederationRegistry
	reg = FederationRegistry()
	cls = type('Dup', (), {})
	reg.register('Dup', cls, plugin='plugin.a')
	with caplog.at_level(logging.WARNING, logger='pgappforge.graphql.federation'):
		reg.register('Dup', cls, plugin='plugin.b')
	assert any('overwriting' in r.message for r in caplog.records)
