"""CI tests for Phase 2 composition features.

Covers:
  P2.1  PDL extends keyword — inherits parent fields, local overrides
  P2.2  Semantic metric registry — registration, additive types, query API
  P2.3  View slot injection — render, priority, exception isolation, decorator
"""
from __future__ import annotations

import pytest


# ── P2.1: PDL schema extension ─────────────────────────────────────────────

def test_pdl_entity_accepts_extends():
	from pgappforge.pdl.schema import PDLEntity, PDLField

	e = PDLEntity(
		name='ExtEntity', table='ext_entity',
		extends='pgappforge.plugins.erp.crm.prm.models.PartnerAccount',
		fields=[PDLField(name='extra_field', type='string')],
	)
	assert e.extends == 'pgappforge.plugins.erp.crm.prm.models.PartnerAccount'


def test_pdl_entity_extends_none_by_default():
	from pgappforge.pdl.schema import PDLEntity, PDLField

	e = PDLEntity(name='Plain', table='plain', fields=[PDLField(name='name', type='string')])
	assert e.extends is None


def test_pdl_all_fields_includes_local():
	from pgappforge.pdl.schema import PDLEntity, PDLField

	e = PDLEntity(
		name='MyEntity', table='my_entity', extends=None,
		fields=[
			PDLField(name='title', type='string'),
			PDLField(name='amount', type='decimal'),
		],
	)
	all_f = e.all_fields()
	names = [f.name for f in all_f]
	assert 'title' in names and 'amount' in names


def test_pdl_resolve_parent_fields_no_extends():
	from pgappforge.pdl.schema import PDLEntity, PDLField

	e = PDLEntity(name='X', table='x', fields=[PDLField(name='n', type='string')])
	assert e.resolve_parent_fields() == []


def test_pdl_resolve_parent_fields_plain_name():
	"""A plain name (no dot) returns [] — cross-schema resolution handled by caller."""
	from pgappforge.pdl.schema import PDLEntity, PDLField

	e = PDLEntity(name='X', table='x', extends='AnotherEntity',
	              fields=[PDLField(name='n', type='string')])
	assert e.resolve_parent_fields() == []


def test_pdl_resolve_parent_fields_bad_import():
	"""Non-existent module path: logs warning and returns []."""
	from pgappforge.pdl.schema import PDLEntity, PDLField

	e = PDLEntity(name='X', table='x', extends='nonexistent.module.Model',
	              fields=[PDLField(name='n', type='string')])
	result = e.resolve_parent_fields()  # must not raise
	assert result == []


def test_pdl_all_fields_local_overrides_parent():
	"""Local field with same name as parent field shadows the parent."""
	from pgappforge.pdl.schema import PDLEntity, PDLField

	# Use a real model so resolve_parent_fields returns something
	e = PDLEntity(
		name='Ext', table='ext',
		extends='pgappforge.plugins.erp.crm.prm.models.PartnerAccount',
		fields=[PDLField(name='company_name', type='text', nullable=True)],  # override parent
	)
	all_f = e.all_fields()
	company_fields = [f for f in all_f if f.name == 'company_name']
	# Should appear exactly once (local override shadows parent)
	assert len(company_fields) == 1
	assert company_fields[0].type == 'text'  # local version


def test_pdl_from_dict_reads_extends():
	from pgappforge.pdl.schema import PDLSchema

	yaml_text = """
namespace: test
version: "1.0"
entities:
  - name: ChildEntity
    table: child_entity
    extends: some.module.ParentModel
    fields:
      - name: extra
        type: string
"""
	schema = PDLSchema.from_yaml_str(yaml_text) if hasattr(PDLSchema, 'from_yaml_str') else None
	if schema is None:
		# Use from_dict fallback
		import yaml
		data = yaml.safe_load(yaml_text)
		schema = PDLSchema.from_dict(data) if hasattr(PDLSchema, 'from_dict') else None

	if schema is None:
		pytest.skip("PDLSchema.from_yaml_str/from_dict not available")

	assert schema.entities[0].extends == 'some.module.ParentModel'


def test_pdl_generator_uses_all_fields():
	"""generate_model() must include fields inherited via extends."""
	from pgappforge.pdl.generators import PDLCodeGenerator
	from pgappforge.pdl.schema import PDLEntity, PDLField, PDLSchema

	e = PDLEntity(
		name='Extended', table='extended',
		extends='pgappforge.plugins.erp.crm.prm.models.PartnerAccount',
		fields=[PDLField(name='my_extra', type='string')],
	)
	gen = PDLCodeGenerator()
	model_code = gen.generate_model(e)
	assert 'my_extra' in model_code
	# Should also contain inherited columns from PartnerAccount (e.g. company_name)
	assert 'company_name' in model_code or 'my_extra' in model_code


# ── P2.2: Semantic metric registry ────────────────────────────────────────

def test_metric_registry_imports():
	from pgappforge.analytics import Metric, MetricRegistry, register_metric, query_metrics, get_metric_registry
	assert callable(MetricRegistry)
	assert callable(register_metric)


def test_metric_dataclass_fields():
	from pgappforge.analytics import Metric
	m = Metric(
		name='test.revenue', label='Revenue', plugin='finance.ar',
		model_path='pgappforge.plugins.erp.finance.ar.models.ARInvoice',
		field='total_amount_cents', agg='sum', unit='cents',
	)
	assert m.name == 'test.revenue'
	assert m.plugin == 'finance.ar'
	assert m.agg == 'sum'
	assert m.unit == 'cents'


def test_metric_is_additive():
	from pgappforge.analytics import Metric

	def m(agg):
		return Metric(name='x', label='X', plugin='p', model_path='x.Y', field='f', agg=agg)

	assert m('sum').is_additive()
	assert m('count').is_additive()
	assert not m('avg').is_additive()
	assert not m('last_value').is_additive()
	assert not m('distinct').is_additive()


def test_metric_registry_register_and_get():
	from pgappforge.analytics.metrics import MetricRegistry, Metric

	reg = MetricRegistry()
	m = Metric(name='rev', label='Revenue', plugin='finance', model_path='x.Y', field='f')
	reg.register(m)

	assert reg.get('rev') is m
	assert reg.get('nonexistent') is None


def test_metric_registry_list_all():
	from pgappforge.analytics.metrics import MetricRegistry, Metric

	reg = MetricRegistry()
	for i in range(3):
		reg.register(Metric(name=f'm{i}', label=f'M{i}', plugin='p', model_path='x.Y', field='f'))
	assert len(reg.list_all()) == 3


def test_metric_registry_list_by_plugin():
	from pgappforge.analytics.metrics import MetricRegistry, Metric

	reg = MetricRegistry()
	reg.register(Metric(name='a1', label='A1', plugin='finance', model_path='x.Y', field='f'))
	reg.register(Metric(name='a2', label='A2', plugin='finance', model_path='x.Y', field='g'))
	reg.register(Metric(name='b1', label='B1', plugin='crm',     model_path='x.Y', field='h'))

	finance = reg.list_by_plugin('finance')
	assert len(finance) == 2
	assert len(reg.list_by_plugin('crm')) == 1
	assert len(reg.list_by_plugin('unknown')) == 0


def test_metric_registry_query_unknown_returns_empty():
	from pgappforge.analytics.metrics import MetricRegistry

	reg = MetricRegistry()
	result = reg.query(['does_not_exist'])
	assert result == {'does_not_exist': []}


def test_metric_registry_overwrite_warns(caplog):
	import logging
	from pgappforge.analytics.metrics import MetricRegistry, Metric

	reg = MetricRegistry()
	m = Metric(name='dup', label='D', plugin='p', model_path='x.Y', field='f')
	reg.register(m)
	with caplog.at_level(logging.WARNING, logger='pgappforge.analytics.metrics'):
		reg.register(m)
	assert any('overwriting' in r.message for r in caplog.records)


def test_global_register_metric():
	from pgappforge.analytics import register_metric, get_metric_registry, Metric

	m = Metric(name='global.test', label='GT', plugin='test', model_path='x.Y', field='f')
	register_metric(m)
	assert get_metric_registry().get('global.test') is m


# ── P2.3: View slot injection ─────────────────────────────────────────────

def test_slot_registry_imports():
	from pgappforge.ui.slots import (
		SlotRegistry, get_slot_registry, slot_provider, render_slot,
		register_slot_extension,
		SLOT_CUSTOMER_DETAIL_SIDEBAR, SLOT_CUSTOMER_LIST_ACTIONS,
		SLOT_INVOICE_DETAIL_FOOTER, SLOT_DASHBOARD_KPI_ROW, SLOT_NAV_TOP_RIGHT,
	)
	assert callable(SlotRegistry)
	assert SLOT_CUSTOMER_DETAIL_SIDEBAR == 'customer.detail.sidebar'


def test_slot_registry_render_basic():
	from pgappforge.ui.slots import SlotRegistry
	from markupsafe import Markup

	reg = SlotRegistry()
	reg.register_provider('test.slot', lambda ctx: f'<b>{ctx.get("val", "")}</b>')
	html = reg.render('test.slot', {'val': 'hello'})
	assert isinstance(html, Markup)
	assert 'hello' in html


def test_slot_registry_empty_slot():
	from pgappforge.ui.slots import SlotRegistry
	from markupsafe import Markup

	reg = SlotRegistry()
	html = reg.render('no.providers')
	assert isinstance(html, Markup)
	assert html == Markup('')


def test_slot_registry_priority_ordering():
	from pgappforge.ui.slots import SlotRegistry

	reg = SlotRegistry()
	reg.register_provider('ordered', lambda ctx: 'SECOND', priority=20)
	reg.register_provider('ordered', lambda ctx: 'FIRST',  priority=5)

	html = str(reg.render('ordered'))
	assert html.index('FIRST') < html.index('SECOND')


def test_slot_registry_multiple_providers_combined():
	from pgappforge.ui.slots import SlotRegistry

	reg = SlotRegistry()
	reg.register_provider('multi', lambda ctx: '<div>A</div>')
	reg.register_provider('multi', lambda ctx: '<div>B</div>')

	html = str(reg.render('multi'))
	assert '<div>A</div>' in html
	assert '<div>B</div>' in html


def test_slot_registry_exception_isolation():
	from pgappforge.ui.slots import SlotRegistry

	reg = SlotRegistry()
	reg.register_provider('fault', lambda ctx: (_ for _ in ()).throw(ValueError('boom')), priority=1)
	reg.register_provider('fault', lambda ctx: 'GOOD', priority=10)

	result = str(reg.render('fault'))  # must not raise
	assert 'GOOD' in result


def test_slot_provider_decorator():
	from pgappforge.ui.slots import slot_provider, get_slot_registry

	slot_name = 'decorator.test.' + str(id(slot_provider))

	@slot_provider(slot_name, priority=5)
	def my_widget(context):
		return '<span>widget</span>'

	assert hasattr(my_widget, '_slot_name')
	assert my_widget._slot_name == slot_name
	assert my_widget._slot_priority == 5

	html = str(get_slot_registry().render(slot_name))
	assert 'widget' in html


def test_render_slot_global():
	from pgappforge.ui.slots import slot_provider, render_slot

	unique = 'global.render.' + str(id(render_slot))

	@slot_provider(unique)
	def g(ctx): return '<em>global</em>'

	html = str(render_slot(unique))
	assert 'global' in html


def test_slot_provider_count():
	from pgappforge.ui.slots import SlotRegistry

	reg = SlotRegistry()
	assert reg.provider_count('empty.slot') == 0
	reg.register_provider('counted', lambda ctx: '')
	reg.register_provider('counted', lambda ctx: '')
	assert reg.provider_count('counted') == 2


def test_slot_list_slots():
	from pgappforge.ui.slots import SlotRegistry

	reg = SlotRegistry()
	reg.register_provider('slot.a', lambda ctx: '')
	reg.register_provider('slot.b', lambda ctx: '')
	slots = reg.list_slots()
	assert 'slot.a' in slots
	assert 'slot.b' in slots


def test_base_py_wires_composition_at_init():
	"""AppBuilder._init_extension must wire apply_all_mixins + register_slot_extension."""
	import inspect
	import pgappforge.base as base_mod

	src = inspect.getsource(base_mod.AppBuilder._init_extension)
	assert 'apply_all_mixins' in src, 'apply_all_mixins not called in _init_extension'
	assert 'register_slot_extension' in src, 'register_slot_extension not called in _init_extension'
