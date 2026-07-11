"""Regression tests for finance arithmetic defects."""
from __future__ import annotations

import sys
import types
import json
from datetime import date
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
USING_PACKAGE_STUBS = "pgappforge" not in sys.modules
if USING_PACKAGE_STUBS:
	for package_name, package_path in {
		"pgappforge": ROOT / "pgappforge",
		"pgappforge.plugins": ROOT / "pgappforge" / "plugins",
		"pgappforge.plugins.erp": ROOT / "pgappforge" / "plugins" / "erp",
		"pgappforge.plugins.erp.finance": ROOT / "pgappforge" / "plugins" / "erp" / "finance",
	}.items():
		package = types.ModuleType(package_name)
		package.__path__ = [str(package_path)]
		sys.modules[package_name] = package

	sqla_stub = types.ModuleType("pgappforge.models.sqla")

	class Model:
		def __init__(self, **kwargs):
			for key, value in kwargs.items():
				setattr(self, key, value)

	class SQLAInterface:
		def __init__(self, *args, **kwargs):
			pass

	sqla_stub.Model = Model
	sqla_stub.__path__ = []
	sys.modules["pgappforge.models.sqla"] = sqla_stub
	sqla_interface_stub = types.ModuleType("pgappforge.models.sqla.interface")
	sqla_interface_stub.SQLAInterface = SQLAInterface
	sys.modules["pgappforge.models.sqla.interface"] = sqla_interface_stub

	class _Mixin(Model):
		pass

	audit_stub = types.ModuleType("pgappforge.plugins.audit")
	audit_stub.AuditMixin = _Mixin
	sys.modules["pgappforge.plugins.audit"] = audit_stub

	rules_mixin_stub = types.ModuleType("pgappforge.plugins.rules.mixin")
	rules_mixin_stub.RulesMixin = _Mixin
	sys.modules["pgappforge.plugins.rules.mixin"] = rules_mixin_stub

	@dataclass
	class DomainEvent:
		aggregate_id: str = ""
		aggregate_type: str = ""
		tenant_id: str = ""

	foundation_events_stub = types.ModuleType("pgappforge.plugins.erp.foundation.events")
	foundation_events_stub.DomainEvent = DomainEvent
	foundation_events_stub.emit_event = lambda event, session: session.add(event)
	sys.modules["pgappforge.plugins.erp.foundation.events"] = foundation_events_stub

from pgappforge.plugins.erp.finance.lease_accounting.models import Lease, LeasePaymentSchedule
from pgappforge.plugins.erp.finance.lease_accounting import services as lease_services
from pgappforge.plugins.erp.finance.lease_accounting.services import LeaseService
from pgappforge.plugins.erp.finance.hedge_accounting.models import HedgeRelationship
from pgappforge.plugins.erp.finance.hedge_accounting.services import HedgeAccountingService
from pgappforge.plugins.erp.finance.joint_venture.models import JointVenture
from pgappforge.plugins.erp.finance.joint_venture.services import JointVentureService
from pgappforge.plugins.erp.finance.material_ledger.models import CostingPeriod, MaterialLedger
from pgappforge.plugins.erp.finance.material_ledger import services as material_services
from pgappforge.plugins.erp.finance.material_ledger.services import MaterialLedgerService


class FakeStatement:
	def where(self, *args, **kwargs):
		return self

	def values(self, *args, **kwargs):
		return self

	def order_by(self, *args, **kwargs):
		return self


class FakeFunc:
	def __getattr__(self, name):
		return lambda *args, **kwargs: (name, args, kwargs)


class FakeSA:
	func = FakeFunc()

	@staticmethod
	def select(*args, **kwargs):
		return FakeStatement()

	@staticmethod
	def update(*args, **kwargs):
		return FakeStatement()


class FakeExecuteResult:
	def __init__(self, *, scalars=None, scalar_one_or_none=None, scalar_one=None):
		self._scalars = scalars if scalars is not None else []
		self._scalar_one_or_none = scalar_one_or_none
		self._scalar_one = scalar_one

	def scalars(self):
		return SimpleNamespace(all=lambda: self._scalars)

	def scalar_one_or_none(self):
		return self._scalar_one_or_none

	def scalar_one(self):
		return self._scalar_one


class FakeSession:
	def __init__(self, get_map: dict | None = None, execute_results: list[FakeExecuteResult] | None = None):
		self.added = []
		self.executed = []
		self.get_map = get_map or {}
		self.execute_results = execute_results or []

	def add(self, obj):
		if obj.__class__.__name__ == "CostSettlement":
			obj.id = "settlement-1"
			obj.run_at = SimpleNamespace(isoformat=lambda: "2026-01-31T00:00:00")
		self.added.append(obj)

	def get(self, model, key):
		value = self.get_map.get((model, key))
		if value is not None:
			return value
		model_name = getattr(model, "__name__", model)
		for (stored_model, stored_key), stored_value in self.get_map.items():
			if stored_key == key and getattr(stored_model, "__name__", stored_model) == model_name:
				return stored_value
		return None

	def execute(self, statement):
		self.executed.append(statement)
		if self.execute_results:
			return self.execute_results.pop(0)
		return FakeExecuteResult()

	def flush(self):
		return None


def test_create_lease_generates_amortization_schedule_rows():
	session = FakeSession()
	service = LeaseService()

	lease = service.create_lease(
		tenant_id="tenant-1",
		name="Office lease",
		start_date=date(2026, 1, 1),
		end_date=date(2026, 3, 31),
		discount_rate=Decimal("0.01"),
		payment_schedule=[
			{"period": "2026-01", "payment_cents": 3400},
			{"period": "2026-02", "payment_cents": 3400},
			{"period": "2026-03", "payment_cents": 3401},
		],
		session=session,
	)

	rows = [obj for obj in session.added if isinstance(obj, LeasePaymentSchedule)]
	assert lease.lease_liability_cents == 10000
	assert len(rows) == 3
	assert sum(row.principal_cents for row in rows) == 10000
	assert rows[-1].liability_balance_cents == 0


def test_material_ledger_actual_cost_uses_opening_plus_receipts_denominator(monkeypatch):
	monkeypatch.setattr(material_services, "sa", FakeSA)
	period = CostingPeriod(
		id="period-1",
		tenant_id="tenant-1",
		plant_id="plant-1",
		fiscal_year=2026,
		period_number=1,
		status="OPEN",
	)
	ledger = MaterialLedger(
		id="ledger-1",
		material_id="mat-1",
		plant_id="plant-1",
		period_id="period-1",
		opening_value_cents=1000,
		opening_qty=Decimal("10"),
		receipts_value_cents=2000,
		receipts_qty=Decimal("10"),
		issues_qty=Decimal("5"),
		purchase_price_variance_cents=0,
		exchange_rate_difference_cents=0,
		production_variance_cents=0,
		multilevel_variance_cents=0,
		closing_qty=Decimal("15"),
		standard_price_cents=100,
		costing_status="OPEN",
	)
	session = FakeSession(
		get_map={(CostingPeriod, "period-1"): period},
		execute_results=[FakeExecuteResult(scalars=[ledger])],
	)

	MaterialLedgerService().run_settlement("period-1", "plant-1", session)

	assert ledger.actual_price_cents == 150


def test_hedge_effectiveness_ratio_preserves_offsetting_sign():
	hedge = HedgeRelationship(
		id="hedge-1",
		hedged_item_type="CASH_FLOW",
		effectiveness_lower=Decimal("80"),
		effectiveness_upper=Decimal("125"),
	)
	session = FakeSession(get_map={(HedgeRelationship, "hedge-1"): hedge})

	entry = HedgeAccountingService().test_effectiveness(
		hedge_id="hedge-1",
		period="2026-01",
		instrument_change_cents=100,
		hedged_item_change_cents=100,
		session=session,
	)

	assert not (Decimal("80") <= entry.effectiveness_ratio <= Decimal("125"))


def test_hedge_effective_portion_to_oci_and_ineffective_to_pl():
	hedge = HedgeRelationship(
		id="hedge-1",
		hedged_item_type="CASH_FLOW",
		effectiveness_lower=Decimal("80"),
		effectiveness_upper=Decimal("125"),
	)
	session = FakeSession(get_map={(HedgeRelationship, "hedge-1"): hedge})

	entry = HedgeAccountingService().test_effectiveness(
		hedge_id="hedge-1",
		period="2026-01",
		instrument_change_cents=120,
		hedged_item_change_cents=-100,
		session=session,
	)

	assert entry.oci_cents == 100
	assert entry.pl_cents == 20


def _thirds_jv():
	return JointVenture(
		id="jv-1",
		partners=[
			{"entity_id": "a", "ownership_pct": Decimal("33.333333")},
			{"entity_id": "b", "ownership_pct": Decimal("33.333333")},
			{"entity_id": "c", "ownership_pct": Decimal("33.333334")},
		],
	)


def test_joint_venture_cash_call_allocates_all_cents_with_largest_remainder():
	session = FakeSession(get_map={(JointVenture, "jv-1"): _thirds_jv()})

	call = JointVentureService().issue_cash_call(
		jv_id="jv-1",
		period="2026-01",
		total_cents=100,
		due_date=date(2026, 1, 31),
		session=session,
	)

	assert sum(row["amount_cents"] for row in call.distribution) == 100


def test_joint_venture_expense_distribution_allocates_all_cents_with_largest_remainder():
	session = FakeSession(get_map={(JointVenture, "jv-1"): _thirds_jv()})

	billing = JointVentureService().distribute_expense(
		jv_id="jv-1",
		expense_journal_id="journal-1",
		period="2026-01",
		total_cents=100,
		session=session,
	)

	assert sum(row["amount_cents"] for row in billing.distribution) == 100


def test_modify_lease_remeasures_with_existing_discount_rate_when_new_rate_is_none(monkeypatch):
	monkeypatch.setattr(lease_services, "sa", FakeSA)
	lease = Lease(
		id="lease-1",
		discount_rate=Decimal("0.01"),
		lease_liability_cents=2941,
	)
	session = FakeSession(get_map={(Lease, "lease-1"): lease})

	modification = LeaseService().modify_lease(
		lease_id="lease-1",
		effective_date=date(2026, 2, 1),
		new_payments=[
			{"period": "2026-02", "payment_cents": 1200},
			{"period": "2026-03", "payment_cents": 1200},
			{"period": "2026-04", "payment_cents": 1200},
		],
		new_discount_rate=None,
		reason="payment increase",
		session=session,
	)

	assert modification.remeasured_liability_cents is not None
	assert modification.remeasured_liability_cents != lease.lease_liability_cents


def test_material_ledger_revaluation_rounds_fractional_closing_quantity(monkeypatch):
	monkeypatch.setattr(material_services, "sa", FakeSA)
	period = CostingPeriod(
		id="period-1",
		tenant_id="tenant-1",
		plant_id="plant-1",
		fiscal_year=2026,
		period_number=1,
		status="OPEN",
	)
	ledger = MaterialLedger(
		id="ledger-1",
		material_id="mat-1",
		plant_id="plant-1",
		period_id="period-1",
		opening_value_cents=150,
		opening_qty=Decimal("1.5"),
		receipts_value_cents=0,
		receipts_qty=Decimal("0"),
		issues_qty=Decimal("0"),
		purchase_price_variance_cents=0,
		exchange_rate_difference_cents=0,
		production_variance_cents=0,
		multilevel_variance_cents=0,
		closing_qty=Decimal("1.5"),
		standard_price_cents=80,
		costing_status="OPEN",
	)
	session = FakeSession(
		get_map={(CostingPeriod, "period-1"): period},
		execute_results=[FakeExecuteResult(scalars=[ledger])],
	)

	MaterialLedgerService().run_settlement("period-1", "plant-1", session)

	assert ledger.actual_price_cents == 100
	assert ledger.revaluation_cents == 30


def test_material_ledger_period_close_totals_all_variance_buckets(monkeypatch):
	monkeypatch.setattr(material_services, "sa", FakeSA)
	period = CostingPeriod(
		id="period-1",
		tenant_id="tenant-1",
		plant_id="plant-1",
		fiscal_year=2026,
		period_number=1,
		status="OPEN",
	)
	ledger = MaterialLedger(
		id="ledger-1",
		period_id="period-1",
		purchase_price_variance_cents=0,
		exchange_rate_difference_cents=100,
		production_variance_cents=50,
		multilevel_variance_cents=0,
		revaluation_cents=0,
	)
	session = FakeSession(
		get_map={(CostingPeriod, "period-1"): period},
		execute_results=[
			FakeExecuteResult(),
			FakeExecuteResult(scalars=[ledger]),
		],
	)

	MaterialLedgerService().close_period("period-1", session)

	close_events = [obj for obj in session.added if getattr(obj, "event_type", "") == "material_ledger.period_closed"]
	payload = getattr(close_events[-1], "payload", None)
	if isinstance(payload, str):
		payload = json.loads(payload)
	elif payload is None:
		payload = vars(close_events[-1])
	assert payload["total_variance_cents"] == 150
