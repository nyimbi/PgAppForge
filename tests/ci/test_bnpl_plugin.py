"""
tests/ci/test_bnpl_plugin.py

CI tests for the BNPL plugin.

Coverage:
  - Model instantiation and repr
  - BNPLService.apply() — creates application with scores
  - BNPLService._assess_affordability() — heuristic fallback
  - BNPLService.approve() — plan + instalments creation for each plan_type
  - BNPLService.decline()
  - BNPLService.process_installment()
  - BNPLService.run_overdue_check()
  - BNPLService.settle_merchant()
  - Event constants and ALL_BNPL_EVENT_TYPES completeness
  - Plugin metadata and registry
"""
from __future__ import annotations

import uuid
from datetime import datetime, date, timedelta, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch, call

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _uuid() -> str:
	return str(uuid.uuid4())


def _mock_session(scalar_result=None):
	session = MagicMock()
	exec_result = MagicMock()
	exec_result.scalar_one_or_none.return_value = scalar_result
	exec_result.scalar_one.return_value = 0
	exec_result.scalars.return_value.all.return_value = []
	session.execute.return_value = exec_result
	session.flush = MagicMock()
	session.add = MagicMock()
	session.get = MagicMock(return_value=None)
	return session


# ---------------------------------------------------------------------------
# Model smoke tests
# ---------------------------------------------------------------------------

class TestBNPLModels:
	def test_merchant_repr(self):
		from pgappforge.plugins.fintech.bnpl.models import BNPLMerchant
		m = BNPLMerchant(
			id=_uuid(), tenant_id="t1",
			name="TechMart Ltd",
			merchant_category="ELECTRONICS",
			settlement_account_number="KE12345678",
			commission_pct=Decimal("0.0200"),
			is_active=True,
		)
		assert "TechMart Ltd" in repr(m)
		assert "True" in repr(m)

	def test_application_repr(self):
		from pgappforge.plugins.fintech.bnpl.models import BNPLApplication
		a = BNPLApplication(
			id=_uuid(), tenant_id="t1",
			customer_id=_uuid(), merchant_id=_uuid(),
			order_amount_cents=150_000_00,
			plan_type="PAY_IN_3",
			status="PENDING",
		)
		assert "PENDING" in repr(a)
		assert "15000000c" in repr(a)

	def test_plan_repr(self):
		from pgappforge.plugins.fintech.bnpl.models import BNPLPlan
		p = BNPLPlan(
			id=_uuid(), tenant_id="t1",
			application_id=_uuid(),
			total_cents=150_000_00,
			installment_count=3,
			installment_amount_cents=50_000_00,
			interest_rate_pct=Decimal("0"),
			status="ACTIVE",
			first_payment_date=date.today(),
		)
		assert "count=3" in repr(p)
		assert "ACTIVE" in repr(p)

	def test_installment_repr(self):
		from pgappforge.plugins.fintech.bnpl.models import BNPLInstallment
		inst = BNPLInstallment(
			id=_uuid(), tenant_id="t1",
			plan_id=_uuid(),
			installment_number=2,
			due_date=date.today() + timedelta(days=30),
			amount_cents=50_000_00,
			status="PENDING",
			penalty_cents=0,
		)
		assert "#2" in repr(inst)
		assert "PENDING" in repr(inst)

	def test_settlement_repr(self):
		from pgappforge.plugins.fintech.bnpl.models import BNPLMerchantSettlement
		s = BNPLMerchantSettlement(
			id=_uuid(), tenant_id="t1",
			merchant_id=_uuid(),
			period="2026-05",
			gross_sales_cents=1_000_000_00,
			commission_cents=20_000_00,
			net_payout_cents=980_000_00,
			status="PENDING",
		)
		assert "2026-05" in repr(s)
		assert "PENDING" in repr(s)

	def test_amounts_are_integer(self):
		from pgappforge.plugins.fintech.bnpl.models import BNPLInstallment
		inst = BNPLInstallment(
			id=_uuid(), tenant_id="t1", plan_id=_uuid(),
			installment_number=1,
			due_date=date.today(),
			amount_cents=50_000_00,
			status="PENDING",
			penalty_cents=0,
		)
		assert isinstance(inst.amount_cents, int)
		assert isinstance(inst.penalty_cents, int)


# ---------------------------------------------------------------------------
# Event tests
# ---------------------------------------------------------------------------

class TestBNPLEvents:
	def test_all_event_types_list(self):
		from pgappforge.plugins.fintech.bnpl.events import (
			ALL_BNPL_EVENT_TYPES,
			BNPL_APPLICATION_APPROVED,
			BNPL_APPLICATION_DECLINED,
			BNPL_INSTALLMENT_DUE,
			BNPL_INSTALLMENT_PAID,
			BNPL_INSTALLMENT_OVERDUE,
			BNPL_SETTLEMENT_PAID,
		)
		assert BNPL_APPLICATION_APPROVED in ALL_BNPL_EVENT_TYPES
		assert BNPL_APPLICATION_DECLINED in ALL_BNPL_EVENT_TYPES
		assert BNPL_INSTALLMENT_DUE in ALL_BNPL_EVENT_TYPES
		assert BNPL_INSTALLMENT_PAID in ALL_BNPL_EVENT_TYPES
		assert BNPL_INSTALLMENT_OVERDUE in ALL_BNPL_EVENT_TYPES
		assert BNPL_SETTLEMENT_PAID in ALL_BNPL_EVENT_TYPES
		assert len(ALL_BNPL_EVENT_TYPES) == 6

	def test_event_dataclasses(self):
		from pgappforge.plugins.fintech.bnpl.events import (
			BNPLApprovedEvent,
			BNPLDeclinedEvent,
			InstallmentDueEvent,
			InstallmentPaidEvent,
			InstallmentOverdueEvent,
			MerchantSettledEvent,
		)
		app_id = _uuid()

		ev = BNPLApprovedEvent(
			aggregate_id=app_id, aggregate_type="BNPLApplication",
			tenant_id="t1", application_id=app_id, customer_id=_uuid(),
			merchant_id=_uuid(), plan_id=_uuid(),
			approved_limit_cents=150_000_00, plan_type="PAY_IN_3",
			installment_count=3,
		)
		assert ev.event_type == "bnpl.application.approved"

		ev2 = BNPLDeclinedEvent(
			aggregate_id=app_id, aggregate_type="BNPLApplication",
			tenant_id="t1", application_id=app_id, customer_id=_uuid(),
			merchant_id=_uuid(), reason="Low score",
			credit_score=500, affordability_score=500,
		)
		assert ev2.event_type == "bnpl.application.declined"

		inst_id = _uuid()
		ev3 = InstallmentPaidEvent(
			aggregate_id=inst_id, aggregate_type="BNPLInstallment",
			tenant_id="t1", installment_id=inst_id, plan_id=_uuid(),
			customer_id=_uuid(), installment_number=1,
			paid_amount_cents=50_000_00,
			paid_date=date.today().isoformat(),
		)
		assert ev3.event_type == "bnpl.installment.paid"

		ev4 = InstallmentOverdueEvent(
			aggregate_id=inst_id, aggregate_type="BNPLInstallment",
			tenant_id="t1", installment_id=inst_id, plan_id=_uuid(),
			customer_id=_uuid(), installment_number=2,
			due_date=(date.today() - timedelta(days=5)).isoformat(),
			amount_cents=50_000_00, penalty_cents=5_000_00,
		)
		assert ev4.event_type == "bnpl.installment.overdue"

		ev5 = MerchantSettledEvent(
			aggregate_id=_uuid(), aggregate_type="BNPLMerchantSettlement",
			tenant_id="t1", settlement_id=_uuid(), merchant_id=_uuid(),
			period="2026-05", gross_sales_cents=1_000_000_00,
			commission_cents=20_000_00, net_payout_cents=980_000_00,
		)
		assert ev5.event_type == "bnpl.settlement.paid"


# ---------------------------------------------------------------------------
# Service tests
# ---------------------------------------------------------------------------

def _make_merchant(tenant_id: str = "t1", commission_pct: str = "0.0200") -> "BNPLMerchant":
	from pgappforge.plugins.fintech.bnpl.models import BNPLMerchant
	return BNPLMerchant(
		id=_uuid(), tenant_id=tenant_id,
		name="TechMart", merchant_category="ELECTRONICS",
		settlement_account_number="KE-ACC-001",
		commission_pct=Decimal(commission_pct),
		is_active=True,
		created_at=datetime.now(timezone.utc),
		updated_at=datetime.now(timezone.utc),
	)


def _make_application(
	tenant_id: str = "t1",
	status: str = "PENDING",
	plan_type: str = "PAY_IN_3",
	order_amount_cents: int = 150_000_00,
) -> "BNPLApplication":
	from pgappforge.plugins.fintech.bnpl.models import BNPLApplication
	return BNPLApplication(
		id=_uuid(), tenant_id=tenant_id,
		customer_id=_uuid(), merchant_id=_uuid(),
		order_amount_cents=order_amount_cents,
		plan_type=plan_type,
		status=status,
		credit_score=750,
		affordability_score=750,
		created_at=datetime.now(timezone.utc),
		updated_at=datetime.now(timezone.utc),
	)


class TestBNPLServiceApply:
	def test_apply_creates_application(self):
		from pgappforge.plugins.fintech.bnpl.services import BNPLService

		merchant = _make_merchant()
		session = _mock_session(scalar_result=merchant)

		added_objects = []
		session.add.side_effect = lambda obj: added_objects.append(obj)

		svc = BNPLService()
		app = svc.apply(
			customer_id=_uuid(),
			merchant_id=merchant.id,
			order_amount_cents=100_000_00,
			plan_type="PAY_IN_3",
			tenant_id="t1",
			session=session,
		)

		assert app.status == "PENDING"
		assert app.credit_score is not None
		assert app.affordability_score is not None
		assert any(obj is app for obj in added_objects)

	def test_apply_merchant_not_found(self):
		from pgappforge.plugins.fintech.bnpl.services import (
			BNPLService,
			MerchantNotFoundError,
		)
		session = _mock_session(scalar_result=None)
		svc = BNPLService()
		with pytest.raises(MerchantNotFoundError):
			svc.apply(_uuid(), _uuid(), 100_000_00, "PAY_IN_3", "t1", session)

	def test_assess_affordability_heuristic_low_amount(self):
		from pgappforge.plugins.fintech.bnpl.services import BNPLService
		svc = BNPLService()
		session = MagicMock()
		# < 5_000_000c → 750
		score, aff = svc._assess_affordability(_uuid(), 1_000_000, session)
		assert score == 750
		assert aff == 750

	def test_assess_affordability_heuristic_high_amount(self):
		from pgappforge.plugins.fintech.bnpl.services import BNPLService
		svc = BNPLService()
		session = MagicMock()
		# >= 5_000_000c → 600
		score, aff = svc._assess_affordability(_uuid(), 5_000_000, session)
		assert score == 600
		assert aff == 600


class TestBNPLServiceApprove:
	"""Test approve() for each plan_type."""

	def _run_approve(self, plan_type: str, order_amount_cents: int = 150_000_00):
		from pgappforge.plugins.fintech.bnpl.services import BNPLService
		from pgappforge.plugins.fintech.bnpl.models import BNPLPlan, BNPLInstallment

		application = _make_application(plan_type=plan_type, order_amount_cents=order_amount_cents)
		session = _mock_session(scalar_result=application)

		added = []
		session.add.side_effect = lambda obj: added.append(obj)

		# session.get for plan completion check — return None (plan not yet persisted in mock)
		session.get.return_value = None

		svc = BNPLService()
		with patch("pgappforge.plugins.fintech.bnpl.services.emit_event"):
			plan = svc.approve(
				application_id=application.id,
				approved_limit_cents=order_amount_cents,
				tenant_id="t1",
				session=session,
			)

		plan_objs = [o for o in added if isinstance(o, BNPLPlan)]
		inst_objs = [o for o in added if isinstance(o, BNPLInstallment)]
		return plan, plan_objs, inst_objs

	def test_approve_pay_in_3(self):
		plan, plan_objs, inst_objs = self._run_approve("PAY_IN_3")
		assert len(plan_objs) == 1
		assert len(inst_objs) == 3
		assert plan.installment_count == 3
		# Amounts sum to total
		total_from_insts = sum(i.amount_cents for i in inst_objs)
		assert total_from_insts == 150_000_00

	def test_approve_pay_in_4(self):
		_, _, inst_objs = self._run_approve("PAY_IN_4")
		assert len(inst_objs) == 4
		# Biweekly: each due_date 14 days apart
		dates = sorted(i.due_date for i in inst_objs)
		for i in range(len(dates) - 1):
			delta = (dates[i + 1] - dates[i]).days
			assert delta == 14

	def test_approve_invoice_split(self):
		_, _, inst_objs = self._run_approve("INVOICE_SPLIT")
		assert len(inst_objs) == 2
		# 30-day gap
		dates = sorted(i.due_date for i in inst_objs)
		assert (dates[1] - dates[0]).days == 30

	def test_approve_monthly_default_6(self):
		_, _, inst_objs = self._run_approve("MONTHLY")
		assert len(inst_objs) == 6

	def test_approve_wrong_status_raises(self):
		from pgappforge.plugins.fintech.bnpl.services import (
			BNPLService,
			InvalidApplicationStatusError,
		)
		application = _make_application(status="DECLINED")
		session = _mock_session(scalar_result=application)
		svc = BNPLService()
		with pytest.raises(InvalidApplicationStatusError):
			svc.approve(application.id, 100_000_00, "t1", session)

	def test_installment_amounts_sum_to_total(self):
		"""Integer division rounding — last instalment absorbs remainder."""
		from pgappforge.plugins.fintech.bnpl.models import BNPLInstallment

		# Use an amount not evenly divisible by 3
		_, _, inst_objs = self._run_approve("PAY_IN_3", order_amount_cents=100_000_01)
		total = sum(i.amount_cents for i in inst_objs)
		assert total == 100_000_01


class TestBNPLServiceDecline:
	def test_decline_sets_status(self):
		from pgappforge.plugins.fintech.bnpl.services import BNPLService

		application = _make_application(status="PENDING")
		session = _mock_session(scalar_result=application)
		svc = BNPLService()
		with patch("pgappforge.plugins.fintech.bnpl.services.emit_event"):
			result = svc.decline(application.id, "Credit score below threshold", "t1", session)
		assert result.status == "DECLINED"

	def test_decline_wrong_status_raises(self):
		from pgappforge.plugins.fintech.bnpl.services import (
			BNPLService,
			InvalidApplicationStatusError,
		)
		application = _make_application(status="ACTIVE")
		session = _mock_session(scalar_result=application)
		svc = BNPLService()
		with pytest.raises(InvalidApplicationStatusError):
			svc.decline(application.id, "reason", "t1", session)


class TestBNPLServiceProcessInstallment:
	def test_process_installment_marks_paid(self):
		from pgappforge.plugins.fintech.bnpl.services import BNPLService
		from pgappforge.plugins.fintech.bnpl.models import BNPLInstallment

		today = date.today()
		inst = BNPLInstallment(
			id=_uuid(), tenant_id="t1", plan_id=_uuid(),
			installment_number=1,
			due_date=today,
			amount_cents=50_000_00,
			status="PENDING",
			penalty_cents=0,
		)
		session = _mock_session(scalar_result=inst)
		# session.get returns None (no plan found — plan completion check skipped)
		session.get.return_value = None

		svc = BNPLService()
		with patch("pgappforge.plugins.fintech.bnpl.services.emit_event"):
			result = svc.process_installment(inst.id, 50_000_00, "t1", session)

		assert result.status == "PAID"
		assert result.paid_amount_cents == 50_000_00
		assert result.paid_date == today

	def test_process_installment_not_found(self):
		from pgappforge.plugins.fintech.bnpl.services import (
			BNPLService,
			InstallmentNotFoundError,
		)
		session = _mock_session(scalar_result=None)
		svc = BNPLService()
		with pytest.raises(InstallmentNotFoundError):
			svc.process_installment(_uuid(), 50_000_00, "t1", session)


class TestBNPLServiceOverdueCheck:
	def test_run_overdue_check_marks_overdue(self):
		from pgappforge.plugins.fintech.bnpl.services import BNPLService
		from pgappforge.plugins.fintech.bnpl.models import BNPLInstallment

		yesterday = date.today() - timedelta(days=3)
		inst1 = BNPLInstallment(
			id=_uuid(), tenant_id="t1", plan_id=_uuid(),
			installment_number=1, due_date=yesterday,
			amount_cents=50_000_00, status="PENDING", penalty_cents=0,
		)
		inst2 = BNPLInstallment(
			id=_uuid(), tenant_id="t1", plan_id=_uuid(),
			installment_number=2, due_date=yesterday - timedelta(days=2),
			amount_cents=50_000_00, status="PENDING", penalty_cents=0,
		)

		session = MagicMock()
		exec_result = MagicMock()
		exec_result.scalars.return_value.all.return_value = [inst1, inst2]
		session.execute.return_value = exec_result
		session.flush = MagicMock()
		session.get.return_value = None

		svc = BNPLService()
		with patch("pgappforge.plugins.fintech.bnpl.services.emit_event"):
			count = svc.run_overdue_check("t1", session)

		assert count == 2
		assert inst1.status == "OVERDUE"
		assert inst2.status == "OVERDUE"
		# Penalty applied (3 days late, 2% per day = 6% of 50_000_00)
		assert inst1.penalty_cents == int(50_000_00 * Decimal("0.02") * 3)

	def test_run_overdue_check_no_overdues(self):
		from pgappforge.plugins.fintech.bnpl.services import BNPLService

		session = MagicMock()
		exec_result = MagicMock()
		exec_result.scalars.return_value.all.return_value = []
		session.execute.return_value = exec_result

		svc = BNPLService()
		count = svc.run_overdue_check("t1", session)
		assert count == 0


class TestBNPLServiceSettlement:
	def test_settle_merchant_creates_settlement(self):
		from pgappforge.plugins.fintech.bnpl.services import BNPLService
		from pgappforge.plugins.fintech.bnpl.models import BNPLMerchantSettlement

		merchant = _make_merchant(commission_pct="0.0200")

		call_count = 0
		def execute_side_effect(stmt):
			nonlocal call_count
			call_count += 1
			result = MagicMock()
			if call_count == 1:
				# merchant lookup
				result.scalar_one_or_none.return_value = merchant
			elif call_count == 2:
				# existing settlement lookup
				result.scalar_one_or_none.return_value = None
			elif call_count == 3:
				# gross sales sum
				result.scalar_one.return_value = 1_000_000_00
			else:
				result.scalar_one_or_none.return_value = None
				result.scalar_one.return_value = 0
			return result

		session = MagicMock()
		session.execute.side_effect = execute_side_effect
		session.flush = MagicMock()
		session.add = MagicMock()

		added = []
		session.add.side_effect = lambda obj: added.append(obj)

		svc = BNPLService()
		with patch("pgappforge.plugins.fintech.bnpl.services.emit_event"):
			settlement = svc.settle_merchant(merchant.id, "2026-05", "t1", session)

		assert settlement.status == "PAID"
		assert settlement.gross_sales_cents == 1_000_000_00
		assert settlement.commission_cents == 20_000_00		# 2% of 1_000_000_00
		assert settlement.net_payout_cents == 980_000_00

	def test_settle_merchant_already_paid_raises(self):
		from pgappforge.plugins.fintech.bnpl.services import (
			BNPLService,
			SettlementAlreadyExistsError,
		)
		from pgappforge.plugins.fintech.bnpl.models import BNPLMerchantSettlement

		merchant = _make_merchant()
		existing_settlement = BNPLMerchantSettlement(
			id=_uuid(), tenant_id="t1",
			merchant_id=merchant.id, period="2026-05",
			gross_sales_cents=1_000_000_00,
			commission_cents=20_000_00,
			net_payout_cents=980_000_00,
			status="PAID",
		)

		call_count = 0
		def execute_side_effect(stmt):
			nonlocal call_count
			call_count += 1
			result = MagicMock()
			if call_count == 1:
				result.scalar_one_or_none.return_value = merchant
			else:
				result.scalar_one_or_none.return_value = existing_settlement
			return result

		session = MagicMock()
		session.execute.side_effect = execute_side_effect

		svc = BNPLService()
		with pytest.raises(SettlementAlreadyExistsError):
			svc.settle_merchant(merchant.id, "2026-05", "t1", session)


# ---------------------------------------------------------------------------
# Plugin metadata and registry tests
# ---------------------------------------------------------------------------

class TestBNPLPlugin:
	def test_plugin_metadata(self):
		from pgappforge.plugins.fintech.bnpl import BNPLPlugin
		plugin = BNPLPlugin.__new__(BNPLPlugin)
		plugin.config = {}
		md = plugin.metadata
		assert md.name == "bnpl"
		assert "fintech" in md.tags
		assert md.version == "1.0.0"

	def test_plugin_depends_on(self):
		from pgappforge.plugins.fintech.bnpl import BNPLPlugin
		assert "core_banking" in BNPLPlugin.depends_on
		assert "lending" in BNPLPlugin.depends_on

	def test_plugin_get_events(self):
		from pgappforge.plugins.fintech.bnpl import BNPLPlugin
		from pgappforge.plugins.fintech.bnpl.events import ALL_BNPL_EVENT_TYPES
		plugin = BNPLPlugin.__new__(BNPLPlugin)
		plugin.config = {}
		assert plugin.get_events() == ALL_BNPL_EVENT_TYPES

	def test_register_models_returns_all_five(self):
		from pgappforge.plugins.fintech.bnpl import BNPLPlugin
		plugin = BNPLPlugin.__new__(BNPLPlugin)
		plugin.config = {}
		models = plugin.register_models()
		names = {m.__name__ for m in models}
		assert names == {
			"BNPLMerchant",
			"BNPLApplication",
			"BNPLPlan",
			"BNPLInstallment",
			"BNPLMerchantSettlement",
		}

	def test_in_fintech_registry(self):
		from pgappforge.plugins.fintech import PLUGIN_REGISTRY, _INSTALL_ORDER
		assert "bnpl" in PLUGIN_REGISTRY
		assert "bnpl" in _INSTALL_ORDER
		# Must come after lending
		assert _INSTALL_ORDER.index("bnpl") > _INSTALL_ORDER.index("lending")

	def test_initialize_sets_defaults(self):
		from pgappforge.plugins.fintech.bnpl import BNPLPlugin
		plugin = BNPLPlugin.__new__(BNPLPlugin)
		plugin.config = {}
		plugin.initialize()
		assert plugin.config["BNPL_MONTHLY_INSTALLMENTS"] == 6
		assert plugin.config["BNPL_MENU_CATEGORY"] == "BNPL"

	def test_add_months_helper(self):
		from pgappforge.plugins.fintech.bnpl.services import BNPLService
		from datetime import date
		# Jan 31 + 1 month → Feb 28/29 (clamped)
		result = BNPLService._add_months(date(2026, 1, 31), 1)
		assert result.month == 2
		assert result.day in (28, 29)

		# March 15 + 3 months → June 15
		result2 = BNPLService._add_months(date(2026, 3, 15), 3)
		assert result2 == date(2026, 6, 15)
