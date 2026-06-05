"""
tests/ci/test_sacco_plugin.py

Compile-level and unit tests for the SACCO / MFI / Chama plugin.

Tests:
  - All public model/service/event symbols importable (views skipped if flask_appbuilder absent)
  - Model instantiation with correct column defaults (no DB required)
  - Money arithmetic invariants
  - SACCOService eligibility logic (register_member, apply_sacco_loan)
  - ChamaService merry-go-round rotation logic
  - Dividend ImmutableRecordMixin guard
  - Events dataclass defaults

Note: flask_appbuilder is not installed in this venv (project uses raw Flask +
Flask-SQLAlchemy).  Tests that require FAB are skipped via pytest.importorskip.
"""
from __future__ import annotations

import dataclasses
import importlib
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_session():
	"""Return a minimal mock SQLAlchemy session."""
	session = MagicMock()
	session.get.return_value = None
	session.execute.return_value = MagicMock(
		scalar_one_or_none=MagicMock(return_value=None),
		scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[]))),
	)
	session.flush = MagicMock()
	session.add = MagicMock()
	return session


# ---------------------------------------------------------------------------
# Import / symbol tests
# ---------------------------------------------------------------------------

class TestImports:
	def test_models_importable(self):
		from pgappforge.plugins.fintech.sacco import models
		for name in ["SACCO", "Member", "SACCOLoanProduct", "Dividend", "Chama", "ChamaMember"]:
			assert hasattr(models, name), f"models.{name} missing"

	def test_services_importable(self):
		from pgappforge.plugins.fintech.sacco import services
		assert hasattr(services, "SACCOService")
		assert hasattr(services, "ChamaService")

	def test_events_importable(self):
		from pgappforge.plugins.fintech.sacco import events
		expected = [
			"MemberRegisteredEvent",
			"MemberContributionPostedEvent",
			"MemberExitCalculatedEvent",
			"SACCOLoanApplicationCreatedEvent",
			"SACCOLoanApprovedEvent",
			"DividendDeclaredEvent",
			"DividendPaidEvent",
			"ChamaCreatedEvent",
			"ChamaContributionPostedEvent",
			"MerryGoRoundDisbursedEvent",
			"TableBankingLoanCreatedEvent",
		]
		for name in expected:
			assert hasattr(events, name), f"events.{name} missing"

	def test_views_importable(self):
		pytest.importorskip("flask_appbuilder", reason="flask_appbuilder not installed")
		from pgappforge.plugins.fintech.sacco import views
		for name in [
			"SACCOView", "MemberView", "SACCOLoanProductView",
			"DividendView", "ChamaView", "ChamaMemberView", "SACCODashboardView",
		]:
			assert hasattr(views, name), f"views.{name} missing"

	def test_package_all_non_view_symbols(self):
		"""Verify non-view __all__ symbols without requiring flask_appbuilder."""
		from pgappforge.plugins.fintech.sacco import models, services, events
		model_names = {"SACCO", "Member", "SACCOLoanProduct", "Dividend", "Chama", "ChamaMember"}
		service_names = {"SACCOService", "ChamaService"}
		event_names = set(events.__all__)
		for name in model_names:
			assert hasattr(models, name)
		for name in service_names:
			assert hasattr(services, name)
		for name in event_names:
			assert hasattr(events, name)


# ---------------------------------------------------------------------------
# Model defaults
# ---------------------------------------------------------------------------

class TestModelDefaults:
	def test_sacco_defaults(self):
		from pgappforge.plugins.fintech.sacco.models import SACCO
		assert SACCO.sacco_type.default.arg == "DEPOSIT_TAKING"
		assert SACCO.regulator.default.arg == "SASRA"
		assert SACCO.membership_count.default.arg == 0
		assert SACCO.total_shares_cents.default.arg == 0

	def test_member_defaults(self):
		from pgappforge.plugins.fintech.sacco.models import Member
		assert Member.membership_status.default.arg == "ACTIVE"
		assert Member.shares_held.default.arg == 0
		assert Member.guarantees_active_cents.default.arg == 0

	def test_sacco_loan_product_defaults(self):
		from pgappforge.plugins.fintech.sacco.models import SACCOLoanProduct
		assert float(SACCOLoanProduct.max_multiple_of_savings.default.arg) == 3.0
		assert float(SACCOLoanProduct.processing_fee_pct.default.arg) == 1.0
		assert SACCOLoanProduct.requires_guarantors.default.arg is True
		assert SACCOLoanProduct.min_guarantors.default.arg == 2
		assert float(SACCOLoanProduct.guarantor_coverage_pct.default.arg) == 100.0

	def test_dividend_defaults(self):
		from pgappforge.plugins.fintech.sacco.models import Dividend
		assert Dividend.status.default.arg == "DECLARED"

	def test_chama_defaults(self):
		from pgappforge.plugins.fintech.sacco.models import Chama
		assert Chama.chama_type.default.arg == "MERRY_GO_ROUND"
		assert Chama.meeting_frequency.default.arg == "MONTHLY"
		assert Chama.current_pool_cents.default.arg == 0
		assert Chama.status.default.arg == "ACTIVE"

	def test_chama_member_defaults(self):
		from pgappforge.plugins.fintech.sacco.models import ChamaMember
		assert ChamaMember.total_contributed_cents.default.arg == 0
		assert ChamaMember.total_received_cents.default.arg == 0
		assert ChamaMember.is_current_recipient.default.arg is False
		assert ChamaMember.contribution_streak.default.arg == 0
		assert ChamaMember.status.default.arg == "ACTIVE"

	def test_dividend_immutable_mixin(self):
		from pgappforge.plugins.fintech.sacco.models import Dividend
		from pgappforge.plugins.erp.foundation.commons import ImmutableRecordMixin
		assert issubclass(Dividend, ImmutableRecordMixin)
		assert getattr(Dividend, "_immutable", False) is True

	def test_all_models_have_tenant_id(self):
		from pgappforge.plugins.fintech.sacco import models
		for name in ["SACCO", "Member", "SACCOLoanProduct", "Dividend", "Chama", "ChamaMember"]:
			cls = getattr(models, name)
			assert hasattr(cls, "tenant_id"), f"{name} missing tenant_id column"

	def test_all_models_have_timestamps(self):
		from pgappforge.plugins.fintech.sacco import models
		for name in ["SACCO", "Member", "SACCOLoanProduct", "Dividend", "Chama", "ChamaMember"]:
			cls = getattr(models, name)
			assert hasattr(cls, "created_at"), f"{name} missing created_at"
			assert hasattr(cls, "updated_at"), f"{name} missing updated_at"

	def test_all_monetary_columns_are_integer(self):
		"""Spot-check that key monetary columns use Integer, never Numeric/Float."""
		from pgappforge.plugins.fintech.sacco import models
		from sqlalchemy import Integer
		checks = [
			("SACCO", "total_shares_cents"),
			("SACCO", "total_deposits_cents"),
			("SACCO", "total_loans_outstanding_cents"),
			("SACCO", "reserve_fund_cents"),
			("Member", "total_shares_value_cents"),
			("Member", "monthly_contribution_cents"),
			("Member", "guarantees_active_cents"),
			("Member", "withdrawal_balance_cents"),
			("Dividend", "total_dividend_pool_cents"),
			("Chama", "contribution_amount_cents"),
			("Chama", "current_pool_cents"),
			("ChamaMember", "total_contributed_cents"),
			("ChamaMember", "total_received_cents"),
		]
		for model_name, col_name in checks:
			cls = getattr(models, model_name)
			col = getattr(cls, col_name)
			col_type = col.property.columns[0].type
			assert isinstance(col_type, Integer), (
				f"{model_name}.{col_name} must be Integer (cents), "
				f"got {type(col_type).__name__}"
			)


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------

class TestEvents:
	def test_event_type_strings(self):
		from pgappforge.plugins.fintech.sacco.events import (
			MemberRegisteredEvent,
			DividendDeclaredEvent,
			MerryGoRoundDisbursedEvent,
			TableBankingLoanCreatedEvent,
			ChamaCreatedEvent,
		)
		assert MemberRegisteredEvent().event_type == "sc.member.registered"
		assert DividendDeclaredEvent().event_type == "sc.dividend.declared"
		assert MerryGoRoundDisbursedEvent().event_type == "sc.chama.merry_go_round_disbursed"
		assert TableBankingLoanCreatedEvent().event_type == "sc.chama.table_banking_loan_created"
		assert ChamaCreatedEvent().event_type == "sc.chama.created"

	def test_chama_created_event_default_list(self):
		from pgappforge.plugins.fintech.sacco.events import ChamaCreatedEvent
		ev = ChamaCreatedEvent()
		assert ev.founding_member_ids == []

	def test_loan_application_event_default_list(self):
		from pgappforge.plugins.fintech.sacco.events import SACCOLoanApplicationCreatedEvent
		ev = SACCOLoanApplicationCreatedEvent()
		assert ev.guarantor_ids == []

	def test_events_are_dataclasses(self):
		from pgappforge.plugins.fintech.sacco import events
		for name in events.__all__:
			cls = getattr(events, name)
			assert dataclasses.is_dataclass(cls), f"{name} should be a dataclass"


# ---------------------------------------------------------------------------
# Patch helper — import sacco.services via importlib to avoid the
# "cannot import name 'sacco' from fintech" form which requires the parent
# __init__ to explicitly re-export the sub-package name.
# ---------------------------------------------------------------------------

def _import_sacco_services():
	"""Return the sacco.services module object, importing it if needed."""
	import importlib
	return importlib.import_module("pgappforge.plugins.fintech.sacco.services")


# ---------------------------------------------------------------------------
# SACCOService — register_member
# ---------------------------------------------------------------------------

class TestSACCOServiceRegisterMember:
	def _make_sacco(self):
		s = MagicMock()
		s.id = "sacco-1"
		s.tenant_id = "tenant-1"
		s.membership_count = 5
		s.total_shares_cents = 500000
		return s

	def test_register_member_raises_if_sacco_not_found(self):
		from pgappforge.plugins.fintech.sacco.services import SACCOService
		session = _make_session()
		session.get.return_value = None
		svc = SACCOService()
		with pytest.raises(ValueError, match="not found"):
			svc.register_member(session, "bad-id", "party-1", 10, 100000, "tenant-1")

	def test_register_member_raises_if_already_active(self):
		from pgappforge.plugins.fintech.sacco.services import SACCOService
		from pgappforge.plugins.fintech.sacco.models import Member
		session = _make_session()
		sacco = self._make_sacco()
		session.get.return_value = sacco

		existing_member = MagicMock(spec=Member)
		existing_member.member_number = "M-EXISTING"
		session.execute.return_value = MagicMock(
			scalar_one_or_none=MagicMock(return_value=existing_member)
		)

		svc = SACCOService()
		with pytest.raises(ValueError, match="already an active member"):
			svc.register_member(session, "sacco-1", "party-1", 10, 100000, "tenant-1")

	def test_register_member_happy_path(self):
		svc_mod = _import_sacco_services()
		from pgappforge.plugins.fintech.sacco.services import SACCOService
		session = _make_session()
		sacco = self._make_sacco()
		session.get.return_value = sacco
		session.execute.return_value = MagicMock(
			scalar_one_or_none=MagicMock(return_value=None)
		)

		svc = SACCOService()
		with patch.object(svc_mod, "emit_event"):
			result = svc.register_member(
				session, "sacco-1", "party-1",
				initial_shares=5,
				monthly_contribution_cents=200000,
				tenant_id="tenant-1",
			)

		session.add.assert_called_once()
		assert session.flush.called
		assert sacco.membership_count == 6


# ---------------------------------------------------------------------------
# SACCOService — apply_sacco_loan
# ---------------------------------------------------------------------------

class TestSACCOServiceApplySACCOLoan:
	def _make_member(self, shares_value=300000, monthly=50000, status="ACTIVE"):
		m = MagicMock()
		m.id = "member-1"
		m.party_id = "party-1"
		m.member_number = "M-001"
		m.membership_status = status
		m.total_shares_value_cents = shares_value
		m.monthly_contribution_cents = monthly
		m.guarantees_active_cents = 0
		m.guarantees_given = []
		m.tenant_id = "tenant-1"
		m.sacco_id = "sacco-1"
		return m

	def _make_product(self, multiple=3, max_cap=None, max_tenor=60,
	                  requires_guarantors=True, min_guarantors=2,
	                  coverage_pct=Decimal("100")):
		p = MagicMock()
		p.id = "prod-1"
		p.product_name = "Development Loan"
		p.loan_type = "DEVELOPMENT"
		p.is_active = True
		p.max_multiple_of_savings = Decimal(str(multiple))
		p.max_amount_cents = max_cap
		p.max_tenor_months = max_tenor
		p.interest_rate_pa = Decimal("0.12")
		p.processing_fee_pct = Decimal("1")
		p.requires_guarantors = requires_guarantors
		p.min_guarantors = min_guarantors
		p.guarantor_coverage_pct = coverage_pct
		return p

	def _make_guarantor(self, shares_value=200000, guarantees_active=0):
		g = MagicMock()
		g.total_shares_value_cents = shares_value
		g.guarantees_active_cents = guarantees_active
		g.guarantees_given = []
		return g

	def test_raises_if_member_not_found(self):
		from pgappforge.plugins.fintech.sacco.services import SACCOService
		session = _make_session()
		session.get.return_value = None
		svc = SACCOService()
		with pytest.raises(ValueError, match="not found"):
			svc.apply_sacco_loan(session, "m-bad", "prod-1", 100000, 12, [], "t1")

	def test_raises_if_member_not_active(self):
		from pgappforge.plugins.fintech.sacco.services import SACCOService
		session = _make_session()
		member = self._make_member(status="SUSPENDED")
		session.get.side_effect = lambda model, id_: member if id_ == "member-1" else None
		svc = SACCOService()
		with pytest.raises(ValueError, match="not active"):
			svc.apply_sacco_loan(session, "member-1", "prod-1", 100000, 12, [], "t1")

	def test_raises_if_amount_exceeds_savings_multiple(self):
		from pgappforge.plugins.fintech.sacco.services import SACCOService
		session = _make_session()
		member = self._make_member(shares_value=100000, monthly=0)
		product = self._make_product(multiple=3, requires_guarantors=False)

		def _get(model, id_):
			if id_ == "member-1":
				return member
			if id_ == "prod-1":
				return product
			return None
		session.get.side_effect = _get
		svc = SACCOService()
		with pytest.raises(ValueError, match="exceeds eligible limit"):
			svc.apply_sacco_loan(session, "member-1", "prod-1", 400000, 12, [], "t1")

	def test_raises_if_insufficient_guarantors(self):
		from pgappforge.plugins.fintech.sacco.services import SACCOService
		session = _make_session()
		member = self._make_member(shares_value=1000000)
		product = self._make_product(requires_guarantors=True, min_guarantors=2)

		def _get(model, id_):
			if id_ == "member-1":
				return member
			if id_ == "prod-1":
				return product
			return None
		session.get.side_effect = _get
		svc = SACCOService()
		with pytest.raises(ValueError, match="requires 2 guarantors"):
			svc.apply_sacco_loan(session, "member-1", "prod-1", 100000, 12, ["g-1"], "t1")

	def test_raises_if_guarantor_coverage_insufficient(self):
		from pgappforge.plugins.fintech.sacco.services import SACCOService
		session = _make_session()
		member = self._make_member(shares_value=1000000)
		product = self._make_product(
			requires_guarantors=True, min_guarantors=2,
			coverage_pct=Decimal("100"),
		)
		g1 = self._make_guarantor(shares_value=10000, guarantees_active=0)
		g2 = self._make_guarantor(shares_value=10000, guarantees_active=0)

		def _get(model, id_):
			if id_ == "member-1":
				return member
			if id_ == "prod-1":
				return product
			return None
		session.get.side_effect = _get
		session.execute.return_value = MagicMock(
			scalars=MagicMock(
				return_value=MagicMock(all=MagicMock(return_value=[g1, g2]))
			)
		)
		svc = SACCOService()
		with pytest.raises(ValueError, match="coverage.*insufficient"):
			svc.apply_sacco_loan(session, "member-1", "prod-1", 500000, 12, ["g1", "g2"], "t1")

	def test_happy_path_no_guarantors(self):
		svc_mod = _import_sacco_services()
		from pgappforge.plugins.fintech.sacco.services import SACCOService
		session = _make_session()
		member = self._make_member(shares_value=1000000, monthly=0)
		product = self._make_product(multiple=3, requires_guarantors=False, max_tenor=60)

		def _get(model, id_):
			if id_ == "member-1":
				return member
			if id_ == "prod-1":
				return product
			return None
		session.get.side_effect = _get

		svc = SACCOService()
		with patch.object(svc_mod, "emit_event"):
			result = svc.apply_sacco_loan(
				session, "member-1", "prod-1", 500000, 24, [], "t1"
			)

		assert result["eligibility_check"] == "PASSED"
		assert result["amount_cents"] == 500000
		assert result["eligible_amount_cents"] == 3000000


# ---------------------------------------------------------------------------
# ChamaService — create_chama
# ---------------------------------------------------------------------------

class TestChamaServiceCreate:
	def test_raises_if_no_members(self):
		from pgappforge.plugins.fintech.sacco.services import ChamaService
		session = _make_session()
		svc = ChamaService()
		with pytest.raises(ValueError, match="at least one founding member"):
			svc.create_chama(
				session, "Test Chama", "MERRY_GO_ROUND",
				date(2024, 1, 1), "MONTHLY", 100000, "t1",
				founding_member_ids=[],
			)

	def test_raises_if_zero_contribution(self):
		from pgappforge.plugins.fintech.sacco.services import ChamaService
		session = _make_session()
		svc = ChamaService()
		with pytest.raises(ValueError, match="must be positive"):
			svc.create_chama(
				session, "Test Chama", "MERRY_GO_ROUND",
				date(2024, 1, 1), "MONTHLY", 0, "t1",
				founding_member_ids=["p-1"],
			)

	def test_creates_chama_and_members(self):
		svc_mod = _import_sacco_services()
		from pgappforge.plugins.fintech.sacco.services import ChamaService
		from pgappforge.plugins.fintech.sacco.models import Chama, ChamaMember

		session = _make_session()
		added_objects = []
		session.add.side_effect = lambda obj: added_objects.append(obj)

		svc = ChamaService()
		with patch.object(svc_mod, "emit_event"):
			result = svc.create_chama(
				session, "Pesa Poa Chama", "MERRY_GO_ROUND",
				date(2024, 3, 1), "MONTHLY", 500000, "t1",
				founding_member_ids=["p-1", "p-2", "p-3"],
				chairperson_id="p-1",
			)

		# 1 Chama + 3 ChamaMember = 4 adds
		assert len(added_objects) == 4
		chama_objs = [o for o in added_objects if isinstance(o, Chama)]
		member_objs = [o for o in added_objects if isinstance(o, ChamaMember)]
		assert len(chama_objs) == 1
		assert len(member_objs) == 3
		# First founding member is initial merry-go-round recipient
		assert member_objs[0].is_current_recipient is True
		for m in member_objs[1:]:
			assert m.is_current_recipient is False


# ---------------------------------------------------------------------------
# ChamaService — record_contribution
# ---------------------------------------------------------------------------

class TestChamaServiceRecordContribution:
	def _make_chama(self, pool=0, status="ACTIVE", chama_type="MERRY_GO_ROUND"):
		c = MagicMock()
		c.id = "chama-1"
		c.chama_name = "Test Chama"
		c.chama_type = chama_type
		c.status = status
		c.current_pool_cents = pool
		c.group_account_id = None
		c.tenant_id = "t1"
		return c

	def _make_chama_member(self, contributed=0, streak=3):
		m = MagicMock()
		m.total_contributed_cents = contributed
		m.contribution_streak = streak
		return m

	def test_raises_if_chama_not_active(self):
		from pgappforge.plugins.fintech.sacco.services import ChamaService
		session = _make_session()
		chama = self._make_chama(status="DORMANT")
		session.get.return_value = chama
		svc = ChamaService()
		with pytest.raises(ValueError, match="not active"):
			svc.record_contribution(session, "chama-1", "member-1", 50000)

	def test_raises_if_not_a_member(self):
		from pgappforge.plugins.fintech.sacco.services import ChamaService
		session = _make_session()
		chama = self._make_chama()
		session.get.return_value = chama
		session.execute.return_value = MagicMock(
			scalar_one_or_none=MagicMock(return_value=None)
		)
		svc = ChamaService()
		with pytest.raises(ValueError, match="not an active member"):
			svc.record_contribution(session, "chama-1", "non-member", 50000)

	def test_contribution_updates_pool_and_streak(self):
		svc_mod = _import_sacco_services()
		from pgappforge.plugins.fintech.sacco.services import ChamaService
		session = _make_session()
		chama = self._make_chama(pool=100000)
		cm = self._make_chama_member(contributed=200000, streak=5)
		session.get.return_value = chama
		session.execute.return_value = MagicMock(
			scalar_one_or_none=MagicMock(return_value=cm)
		)
		svc = ChamaService()
		with patch.object(svc_mod, "emit_event"):
			result = svc.record_contribution(session, "chama-1", "m-1", 50000)

		assert chama.current_pool_cents == 150000
		assert cm.total_contributed_cents == 250000
		assert cm.contribution_streak == 6
		assert result["new_pool_cents"] == 150000


# ---------------------------------------------------------------------------
# ChamaService — merry-go-round
# ---------------------------------------------------------------------------

class TestChamaServiceMerryGoRound:
	def _make_chama(self, pool=500000):
		c = MagicMock()
		c.id = "chama-1"
		c.chama_name = "MGR Chama"
		c.chama_type = "MERRY_GO_ROUND"
		c.current_pool_cents = pool
		c.group_account_id = None
		c.tenant_id = "t1"
		return c

	def _make_cm(self, member_id, is_recipient=False, received=0):
		m = MagicMock()
		m.member_id = member_id
		m.is_current_recipient = is_recipient
		m.total_received_cents = received
		m.join_date = date(2024, 1, 1)
		m.id = f"cm-{member_id}"
		return m

	def test_raises_if_wrong_type(self):
		from pgappforge.plugins.fintech.sacco.services import ChamaService
		chama = self._make_chama()
		chama.chama_type = "TABLE_BANKING"
		session = _make_session()
		session.get.return_value = chama
		svc = ChamaService()
		with pytest.raises(ValueError, match="not MERRY_GO_ROUND"):
			svc.process_merry_go_round(session, "chama-1", "m-1")

	def test_raises_if_pool_empty(self):
		from pgappforge.plugins.fintech.sacco.services import ChamaService
		chama = self._make_chama(pool=0)
		session = _make_session()
		session.get.return_value = chama
		svc = ChamaService()
		with pytest.raises(ValueError, match="no funds to disburse"):
			svc.process_merry_go_round(session, "chama-1", "m-1")

	def test_raises_if_not_current_recipient(self):
		from pgappforge.plugins.fintech.sacco.services import ChamaService
		chama = self._make_chama(pool=500000)
		session = _make_session()
		session.get.return_value = chama
		session.execute.return_value = MagicMock(
			scalar_one_or_none=MagicMock(return_value=None),
			scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[]))),
		)
		svc = ChamaService()
		with pytest.raises(ValueError, match="not the current merry-go-round recipient"):
			svc.process_merry_go_round(session, "chama-1", "m-not-recipient")

	def test_disburse_rotates_recipient(self):
		svc_mod = _import_sacco_services()
		from pgappforge.plugins.fintech.sacco.services import ChamaService
		chama = self._make_chama(pool=500000)
		session = _make_session()
		session.get.return_value = chama

		cm1 = self._make_cm("m-1", is_recipient=True, received=0)
		cm2 = self._make_cm("m-2", is_recipient=False, received=0)
		cm3 = self._make_cm("m-3", is_recipient=False, received=0)

		call_count = [0]
		def _execute(query):
			call_count[0] += 1
			if call_count[0] == 1:
				return MagicMock(scalar_one_or_none=MagicMock(return_value=cm1))
			else:
				return MagicMock(
					scalars=MagicMock(
						return_value=MagicMock(all=MagicMock(return_value=[cm1, cm2, cm3]))
					)
				)
		session.execute.side_effect = _execute

		svc = ChamaService()
		with patch.object(svc_mod, "emit_event"):
			result = svc.process_merry_go_round(session, "chama-1", "m-1")

		assert chama.current_pool_cents == 0
		assert cm1.total_received_cents == 500000
		assert cm1.is_current_recipient is False
		assert cm2.is_current_recipient is True
		assert result["amount_disbursed_cents"] == 500000
		assert result["next_recipient_member_id"] == "m-2"


# ---------------------------------------------------------------------------
# SACCOService — declare_dividend
# ---------------------------------------------------------------------------

class TestSACCOServiceDividend:
	def _make_sacco(self):
		s = MagicMock()
		s.id = "sacco-1"
		s.name = "Test SACCO"
		s.tenant_id = "t1"
		s.reserve_fund_cents = 500000
		s.total_deposits_cents = 1000000
		s.total_loans_outstanding_cents = 800000
		return s

	def test_raises_if_sacco_not_found(self):
		from pgappforge.plugins.fintech.sacco.services import SACCOService
		session = _make_session()
		session.get.return_value = None
		svc = SACCOService()
		with pytest.raises(ValueError, match="not found"):
			svc.declare_dividend(session, "bad-id", 2024, "10", "2", 1000000)

	def test_raises_if_duplicate_declaration(self):
		from pgappforge.plugins.fintech.sacco.services import SACCOService
		from pgappforge.plugins.fintech.sacco.models import Dividend
		session = _make_session()
		sacco = self._make_sacco()
		session.get.return_value = sacco

		existing = MagicMock(spec=Dividend)
		existing.id = "div-existing"
		existing.status = "DECLARED"
		session.execute.return_value = MagicMock(
			scalar_one_or_none=MagicMock(return_value=existing)
		)
		svc = SACCOService()
		with pytest.raises(ValueError, match="already declared"):
			svc.declare_dividend(session, "sacco-1", 2024, "10", "2", 1000000)

	def test_declare_dividend_happy_path(self):
		svc_mod = _import_sacco_services()
		from pgappforge.plugins.fintech.sacco.services import SACCOService
		session = _make_session()
		sacco = self._make_sacco()
		session.get.return_value = sacco
		session.execute.return_value = MagicMock(
			scalar_one_or_none=MagicMock(return_value=None)
		)
		svc = SACCOService()
		with patch.object(svc_mod, "emit_event"):
			result = svc.declare_dividend(
				session, "sacco-1", 2024, "12.5", "3.0", 2000000, tenant_id="t1"
			)

		session.add.assert_called_once()
		session.flush.assert_called()
		div = session.add.call_args[0][0]
		assert div.financial_year == 2024
		assert div.status == "DECLARED"
		assert div.total_dividend_pool_cents == 2000000


# ---------------------------------------------------------------------------
# SACCOService — get_sacco_financials
# ---------------------------------------------------------------------------

class TestSACCOServiceFinancials:
	def test_get_sacco_financials_no_loans(self):
		from pgappforge.plugins.fintech.sacco.services import SACCOService
		session = _make_session()
		sacco = MagicMock()
		sacco.id = "sacco-1"
		sacco.name = "KES SACCO"
		sacco.total_deposits_cents = 500000
		sacco.total_loans_outstanding_cents = 0
		sacco.reserve_fund_cents = 100000

		m1 = MagicMock()
		m1.total_shares_value_cents = 200000
		m1.party_id = "p-1"
		m2 = MagicMock()
		m2.total_shares_value_cents = 300000
		m2.party_id = "p-2"

		session.get.return_value = sacco
		session.execute.return_value = MagicMock(
			scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[m1, m2])))
		)

		svc = SACCOService()
		result = svc.get_sacco_financials(session, "sacco-1")

		assert result["total_shares_cents"] == 500000
		assert result["total_savings_cents"] == 1000000  # 500k shares + 500k deposits
		assert result["membership_count"] == 2
		assert result["reserve_fund_cents"] == 100000


# ---------------------------------------------------------------------------
# ChamaService — table banking
# ---------------------------------------------------------------------------

class TestChamaServiceTableBanking:
	def _make_chama(self, pool=1000000):
		c = MagicMock()
		c.id = "chama-tb"
		c.chama_name = "Table Bankers"
		c.chama_type = "TABLE_BANKING"
		c.status = "ACTIVE"
		c.current_pool_cents = pool
		c.rules = {"loan_interest_rate_pw": "10"}
		c.tenant_id = "t1"
		c.group_account_id = None
		return c

	def _make_chama_member(self):
		m = MagicMock()
		m.member_id = "borrow-1"
		m.status = "ACTIVE"
		return m

	def test_raises_if_wrong_chama_type(self):
		from pgappforge.plugins.fintech.sacco.services import ChamaService
		chama = self._make_chama()
		chama.chama_type = "MERRY_GO_ROUND"
		session = _make_session()
		session.get.return_value = chama
		svc = ChamaService()
		with pytest.raises(ValueError, match="not TABLE_BANKING"):
			svc.record_table_banking_loan(session, "chama-tb", "b-1", 100000, 4, "t1")

	def test_raises_if_exceeds_pool(self):
		from pgappforge.plugins.fintech.sacco.services import ChamaService
		chama = self._make_chama(pool=50000)
		session = _make_session()
		session.get.return_value = chama
		cm = self._make_chama_member()
		session.execute.return_value = MagicMock(
			scalar_one_or_none=MagicMock(return_value=cm)
		)
		svc = ChamaService()
		with pytest.raises(ValueError, match="exceeds available pool"):
			svc.record_table_banking_loan(session, "chama-tb", "b-1", 100000, 4, "t1")

	def test_loan_deducts_from_pool_and_calculates_interest(self):
		svc_mod = _import_sacco_services()
		from pgappforge.plugins.fintech.sacco.services import ChamaService
		chama = self._make_chama(pool=1000000)
		session = _make_session()
		session.get.return_value = chama
		cm = self._make_chama_member()
		session.execute.return_value = MagicMock(
			scalar_one_or_none=MagicMock(return_value=cm)
		)
		svc = ChamaService()
		with patch.object(svc_mod, "emit_event"):
			result = svc.record_table_banking_loan(
				session, "chama-tb", "b-1", 200000, 4, "t1",
				loan_date=date(2024, 6, 1),
			)

		assert chama.current_pool_cents == 800000
		assert result["interest_cents"] == 20000        # 10% of 200000
		assert result["total_repayable_cents"] == 220000
		assert result["remaining_pool_cents"] == 800000


# ---------------------------------------------------------------------------
# ChamaService — get_chama_statement
# ---------------------------------------------------------------------------

class TestChamaStatement:
	def test_get_chama_statement_structure(self):
		from pgappforge.plugins.fintech.sacco.services import ChamaService

		session = _make_session()
		chama = MagicMock()
		chama.id = "c-1"
		chama.chama_name = "Pesa Chama"
		chama.chama_type = "MERRY_GO_ROUND"
		chama.current_pool_cents = 300000

		cm1 = MagicMock()
		cm1.member_id = "m-1"
		cm1.status = "ACTIVE"
		cm1.total_contributed_cents = 100000
		cm1.total_received_cents = 0
		cm1.is_current_recipient = True
		cm1.contribution_streak = 6
		cm1.join_date = date(2024, 1, 1)

		session.get.return_value = chama
		session.execute.return_value = MagicMock(
			scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[cm1])))
		)

		svc = ChamaService()
		result = svc.get_chama_statement(session, "c-1", period_months=3)

		assert result["chama_name"] == "Pesa Chama"
		assert result["member_count"] == 1
		assert result["current_pool_cents"] == 300000
		assert result["total_contributions_cents"] == 100000
		assert len(result["member_summaries"]) == 1
		assert result["member_summaries"][0]["is_current_recipient"] is True
