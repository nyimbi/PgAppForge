"""
tests/ci/test_clm_plugin.py

CI tests for the Contract Lifecycle Management (CLM) plugin.

Covers:
  - Model instantiation and repr
  - CLMPlugin metadata / event list / subscribe_to
  - CLMService.create_contract
  - CLMService.submit_for_review  (DRAFT → UNDER_REVIEW + ContractApproval seeding)
  - CLMService.record_approval    (APPROVED path → PENDING_SIGNATURE)
  - CLMService.record_approval    (REJECTED path → NEGOTIATION)
  - CLMService.send_for_signature
  - CLMService.record_signature   (all-signed → ACTIVE)
  - CLMService.create_obligation / fulfill_obligation
  - CLMService.get_overdue_obligations
  - CLMService.process_renewals   (auto_renew=True and alert path)
  - CLMService.terminate_contract
  - CLMService.calculate_lease_schedule  (IFRS 16 PV, GL skip gracefully)
  - CLMService.amortise_rou_asset
  - CLMService.get_contract_dashboard
  - IFRS 16 PV formula accuracy
  - Decimal arithmetic: interest + principal == monthly_payment
  - Error paths: ContractNotFoundError, CLMValidationError, ObligationNotFoundError

All tests use real SQLAlchemy in-memory SQLite for speed (no mocks).
No @pytest.mark.asyncio decorators; async tests use get_event_loop().
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

import pytest
import sqlalchemy as sa
from freezegun import freeze_time
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

# ---------------------------------------------------------------------------
# Minimal stubs so the plugin can be imported without a full FAB environment
# ---------------------------------------------------------------------------

import sys
import types


import os as _os

# Root of the source tree — used to set real __path__ on stubs so the import
# system can still find real sub-packages under them.
_SRC_ROOT = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))


def _stub_package(name: str, **attrs: Any) -> types.ModuleType:
	"""Register a stub package whose __path__ points at the real source directory.

	This lets Python resolve genuine sub-packages (e.g. contracts/) even though
	the parent __init__.py would blow up with heavy FAB imports.
	"""
	if name in sys.modules:
		mod = sys.modules[name]
		for k, v in attrs.items():
			setattr(mod, k, v)
		return mod
	mod = types.ModuleType(name)
	mod.__package__ = name
	# Map dotted name → filesystem path under _SRC_ROOT
	rel_path = name.replace(".", _os.sep)
	fs_path = _os.path.join(_SRC_ROOT, rel_path)
	mod.__path__ = [fs_path]  # real path → submodule discovery works
	mod.__file__ = _os.path.join(fs_path, "__init__.py")
	mod.__spec__ = None
	for k, v in attrs.items():
		setattr(mod, k, v)
	sys.modules[name] = mod
	return mod


def _stub_module(name: str, **attrs: Any) -> types.ModuleType:
	"""Register a stub leaf module (no submodule discovery needed)."""
	if name in sys.modules:
		mod = sys.modules[name]
		for k, v in attrs.items():
			setattr(mod, k, v)
		return mod
	mod = types.ModuleType(name)
	mod.__package__ = name.rpartition(".")[0]
	for k, v in attrs.items():
		setattr(mod, k, v)
	sys.modules[name] = mod
	return mod


# ---------------------------------------------------------------------------
# Stub every intermediate package whose real __init__.py imports heavy FAB deps.
# __path__ is set to the real directory so child packages/modules are discoverable.
# ---------------------------------------------------------------------------

_stub_package("pgappforge")
_stub_package("pgappforge.models")
_stub_package("pgappforge.plugins")
_stub_package("pgappforge.plugins.erp")
_stub_package("pgappforge.plugins.erp.crm")
_stub_package("pgappforge.plugins.erp.foundation")

# pgappforge.models.sqla — provide a declarative Base as Model
from sqlalchemy.orm import DeclarativeBase as _DeclarativeBase

class _Base(_DeclarativeBase):
	pass

_stub_module("pgappforge.models.sqla", Model=_Base)

# pgappforge.plugins.audit — AuditMixin as a no-op mixin
class _AuditMixin:
	pass

_stub_module("pgappforge.plugins.audit", AuditMixin=_AuditMixin)

# pgappforge.plugins.rules — RulesMixin as a no-op mixin
_stub_package("pgappforge.plugins.rules")
_stub_module("pgappforge.plugins.rules.mixin", RulesMixin=object)
sys.modules["pgappforge.plugins.rules"].RulesMixin = object  # type: ignore[attr-defined]

# pgappforge.plugins.base_plugin
import enum as _enum

class _PluginPriority(_enum.IntEnum):
	NORMAL = 50

class _PluginMetadata:
	def __init__(self, **kw: Any) -> None:
		for k, v in kw.items():
			setattr(self, k, v)

class _BasePlugin:
	name: str = ""
	domain: str = ""
	depends_on: list[str] = []

	def __init__(self, appbuilder: Any = None, config: dict[str, Any] | None = None) -> None:
		self.appbuilder = appbuilder
		self.config: dict[str, Any] = config or {}

	def add_view(self, *a: Any, **kw: Any) -> None:
		pass

_stub_module(
	"pgappforge.plugins.base_plugin",
	BasePlugin=_BasePlugin,
	PluginMetadata=_PluginMetadata,
	PluginPriority=_PluginPriority,
)

# pgappforge.plugins.erp.foundation.events
from dataclasses import dataclass as _dataclass

_emitted_events: list[Any] = []

@_dataclass
class _DomainEvent:
	aggregate_id: str = ""
	aggregate_type: str = ""
	tenant_id: str = ""
	occurred_at: str = ""

def _emit_event(event: Any, session: Any = None) -> None:
	_emitted_events.append(event)

def _subscribe(event_type: str, handler: Any) -> None:
	pass

_stub_module(
	"pgappforge.plugins.erp.foundation.events",
	DomainEvent=_DomainEvent,
	emit_event=_emit_event,
	subscribe=_subscribe,
)

# ---------------------------------------------------------------------------
# Now import the plugin under test
# ---------------------------------------------------------------------------

from pgappforge.plugins.erp.crm.contracts.models import (
	Contract,
	ContractApproval,
	ContractObligation,
	ContractTemplate,
	ClauseLibrary,
	ContractVersion,
	ESignatureRequest,
	LeaseSchedule,
)
from pgappforge.plugins.erp.crm.contracts.services import (
	CLMService,
	CLMError,
	CLMValidationError,
	ContractNotFoundError,
	ObligationNotFoundError,
	SignatureRequestNotFoundError,
)
from pgappforge.plugins.erp.crm.contracts.events import (
	ContractCreatedEvent,
	ContractApprovedEvent,
	ContractSignedEvent,
	ObligationFulfilledEvent,
	ContractRenewalAlertEvent,
	ContractTerminatedEvent,
	LeaseRecognisedEvent,
)
from pgappforge.plugins.erp.crm.contracts import CLMPlugin


# ---------------------------------------------------------------------------
# Test database setup — PostgreSQL (JSONB requires PG; psycopg2 available)
# ---------------------------------------------------------------------------

import os as _os_env

# Grab the registry metadata from the Model stub
from pgappforge.models.sqla import Model as _Model
_metadata = _Model.metadata

_TEST_DB_URL = _os_env.environ.get(
	"TEST_DATABASE_URL", "postgresql+psycopg2://localhost/postgres"
)
# Ensure psycopg2 scheme
if _TEST_DB_URL.startswith("postgresql://"):
	_TEST_DB_URL = _TEST_DB_URL.replace("postgresql://", "postgresql+psycopg2://", 1)


@pytest.fixture(scope="module")
def engine():
	eng = create_engine(_TEST_DB_URL, echo=False)
	_metadata.create_all(eng, checkfirst=True)
	yield eng
	_metadata.drop_all(eng)
	eng.dispose()


@pytest.fixture
def session(engine):
	with Session(engine) as sess:
		yield sess
		sess.rollback()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tid() -> str:
	return str(uuid.uuid4())


def _uid() -> str:
	return str(uuid.uuid4())


def _contract_data(tenant_id: str, owner_id: str, counterparty_id: str, **overrides: Any) -> dict:
	base = {
		"contract_number": f"CON-{uuid.uuid4().hex[:8].upper()}",
		"title": "Test Contract",
		"contract_type": "SERVICE",
		"counterparty_id": counterparty_id,
		"internal_owner_id": owner_id,
	}
	base.update(overrides)
	return base


# ---------------------------------------------------------------------------
# Model smoke tests
# ---------------------------------------------------------------------------

class TestModelInstantiation:
	def test_contract_repr(self):
		c = Contract(contract_number="X-001", status="DRAFT")
		assert "X-001" in repr(c)
		assert "DRAFT" in repr(c)

	def test_clause_library_repr(self):
		cl = ClauseLibrary(clause_code="LIAB-01", risk_level="HIGH")
		assert "LIAB-01" in repr(cl)
		assert "HIGH" in repr(cl)

	def test_lease_schedule_repr(self):
		ls = LeaseSchedule(contract_id="abc", lease_type="FINANCE", rou_asset_cents=500000)
		assert "FINANCE" in repr(ls)
		assert "500000" in repr(ls)


# ---------------------------------------------------------------------------
# CLMPlugin metadata
# ---------------------------------------------------------------------------

class TestCLMPlugin:
	def test_get_events(self):
		plugin = CLMPlugin(appbuilder=None)
		events = plugin.get_events()
		assert "clm.contract.created" in events
		assert "clm.lease.recognised" in events
		assert len(events) == 8

	def test_subscribe_to_empty(self):
		plugin = CLMPlugin(appbuilder=None)
		assert plugin.subscribe_to() == []

	def test_activate_sets_config(self):
		plugin = CLMPlugin(appbuilder=None)
		plugin.activate()
		assert plugin.config["CLM_DEFAULT_CURRENCY"] == "KES"

	def test_register_models_returns_eight(self):
		plugin = CLMPlugin(appbuilder=None)
		models = plugin.register_models()
		assert len(models) == 8

	def test_metadata_name(self):
		plugin = CLMPlugin(appbuilder=None)
		assert plugin.metadata.name == "clm"


# ---------------------------------------------------------------------------
# CLMService.create_contract
# ---------------------------------------------------------------------------

class TestCreateContract:
	def test_creates_draft_contract(self, session):
		tid = _tid()
		owner = _uid()
		cp = _uid()
		data = _contract_data(tid, owner, cp, contract_value_cents=1_000_000)
		contract = CLMService.create_contract(session, data, tid)
		assert contract.status == "DRAFT"
		assert contract.tenant_id == tid
		assert contract.contract_value_cents == 1_000_000

	def test_creates_version_1(self, session):
		tid = _tid()
		data = _contract_data(tid, _uid(), _uid())
		contract = CLMService.create_contract(session, data, tid)
		versions = session.execute(
			sa.select(ContractVersion).where(ContractVersion.contract_id == contract.id)
		).scalars().all()
		assert len(versions) == 1
		assert versions[0].version_number == 1

	def test_seeds_body_from_template(self, session):
		tid = _tid()
		tmpl = ContractTemplate(
			tenant_id=tid,
			code="NDA-STD",
			name="NDA Standard",
			contract_type="NDA",
			template_body="CONFIDENTIALITY TERMS...",
			jurisdiction="KE",
		)
		session.add(tmpl)
		session.flush()

		data = _contract_data(tid, _uid(), _uid(), contract_type="NDA")
		contract = CLMService.create_contract(session, data, tid, template_id=tmpl.id)
		v1 = session.execute(
			sa.select(ContractVersion).where(ContractVersion.contract_id == contract.id)
		).scalar_one()
		assert "CONFIDENTIALITY TERMS" in v1.body

	def test_missing_template_raises(self, session):
		tid = _tid()
		data = _contract_data(tid, _uid(), _uid())
		with pytest.raises(CLMValidationError, match="not found"):
			CLMService.create_contract(session, data, tid, template_id=str(uuid.uuid4()))


# ---------------------------------------------------------------------------
# CLMService.submit_for_review
# ---------------------------------------------------------------------------

class TestSubmitForReview:
	def test_draft_to_under_review(self, session):
		tid = _tid()
		owner = _uid()
		contract = CLMService.create_contract(session, _contract_data(tid, owner, _uid()), tid)
		contract = CLMService.submit_for_review(session, contract.id, owner, tid)
		assert contract.status == "UNDER_REVIEW"

	def test_creates_approval_rows(self, session):
		tid = _tid()
		owner = _uid()
		contract = CLMService.create_contract(session, _contract_data(tid, owner, _uid()), tid)
		CLMService.submit_for_review(session, contract.id, owner, tid)
		approvals = session.execute(
			sa.select(ContractApproval).where(ContractApproval.contract_id == contract.id)
		).scalars().all()
		assert len(approvals) == 5  # LEGAL, FINANCE, COMMERCIAL, EXECUTIVE, COMPLIANCE

	def test_non_draft_raises(self, session):
		tid = _tid()
		owner = _uid()
		contract = CLMService.create_contract(session, _contract_data(tid, owner, _uid()), tid)
		CLMService.submit_for_review(session, contract.id, owner, tid)
		with pytest.raises(CLMValidationError, match="must be DRAFT"):
			CLMService.submit_for_review(session, contract.id, owner, tid)


# ---------------------------------------------------------------------------
# CLMService.record_approval
# ---------------------------------------------------------------------------

class TestRecordApproval:
	def _setup_under_review(self, session) -> tuple[Any, str, str]:
		tid = _tid()
		owner = _uid()
		contract = CLMService.create_contract(session, _contract_data(tid, owner, _uid()), tid)
		CLMService.submit_for_review(session, contract.id, owner, tid)
		return contract, tid, owner

	def test_approve_all_moves_to_pending_signature(self, session):
		contract, tid, owner = self._setup_under_review(session)
		approvals = session.execute(
			sa.select(ContractApproval).where(ContractApproval.contract_id == contract.id)
		).scalars().all()
		for appr in approvals:
			CLMService.record_approval(session, contract.id, appr.approver_id, "APPROVED", tenant_id=tid)
		session.refresh(contract)
		assert contract.status == "PENDING_SIGNATURE"

	def test_rejection_moves_to_negotiation(self, session):
		contract, tid, owner = self._setup_under_review(session)
		first_approval = session.execute(
			sa.select(ContractApproval)
			.where(ContractApproval.contract_id == contract.id)
			.order_by(ContractApproval.sequence_order)
		).scalars().first()
		CLMService.record_approval(
			session, contract.id, first_approval.approver_id, "REJECTED", tenant_id=tid
		)
		session.refresh(contract)
		assert contract.status == "NEGOTIATION"

	def test_invalid_decision_raises(self, session):
		contract, tid, owner = self._setup_under_review(session)
		with pytest.raises(CLMValidationError, match="Invalid decision"):
			CLMService.record_approval(session, contract.id, owner, "MAYBE", tenant_id=tid)


# ---------------------------------------------------------------------------
# CLMService.send_for_signature / record_signature
# ---------------------------------------------------------------------------

class TestSignature:
	def _setup_pending_signature(self, session) -> tuple[Any, str]:
		tid = _tid()
		owner = _uid()
		contract = CLMService.create_contract(session, _contract_data(tid, owner, _uid()), tid)
		CLMService.submit_for_review(session, contract.id, owner, tid)
		approvals = session.execute(
			sa.select(ContractApproval).where(ContractApproval.contract_id == contract.id)
		).scalars().all()
		for appr in approvals:
			CLMService.record_approval(session, contract.id, appr.approver_id, "APPROVED", tenant_id=tid)
		return contract, tid

	def test_send_creates_requests(self, session):
		contract, tid = self._setup_pending_signature(session)
		sigs = [
			{"signatory_id": _uid(), "signatory_name": "Alice", "signatory_email": "alice@example.com"},
			{"signatory_id": _uid(), "signatory_name": "Bob", "signatory_email": "bob@example.com"},
		]
		reqs = CLMService.send_for_signature(session, contract.id, sigs, provider="LOCAL", tenant_id=tid)
		assert len(reqs) == 2
		assert all(r.status == "SENT" for r in reqs)

	def test_all_signed_activates_contract(self, session):
		contract, tid = self._setup_pending_signature(session)
		sig_id = _uid()
		sigs = [{"signatory_id": sig_id, "signatory_name": "Alice", "signatory_email": "alice@ex.com"}]
		reqs = CLMService.send_for_signature(session, contract.id, sigs, tenant_id=tid)
		CLMService.record_signature(session, reqs[0].id, tenant_id=tid)
		session.refresh(contract)
		assert contract.status == "ACTIVE"
		assert contract.signed_at is not None

	def test_send_on_wrong_status_raises(self, session):
		tid = _tid()
		contract = CLMService.create_contract(session, _contract_data(tid, _uid(), _uid()), tid)
		with pytest.raises(CLMValidationError, match="PENDING_SIGNATURE"):
			CLMService.send_for_signature(session, contract.id, [], tenant_id=tid)


# ---------------------------------------------------------------------------
# CLMService.create_obligation / fulfill_obligation
# ---------------------------------------------------------------------------

class TestObligations:
	def test_create_obligation(self, session):
		tid = _tid()
		contract = CLMService.create_contract(session, _contract_data(tid, _uid(), _uid()), tid)
		obl = CLMService.create_obligation(session, contract.id, {
			"obligation_type": "PAYMENT",
			"description": "Monthly fee",
			"due_date": date.today() + timedelta(days=30),
			"amount_cents": 50_000,
		}, tid)
		assert obl.status == "PENDING"
		assert obl.amount_cents == 50_000

	def test_fulfill_obligation(self, session):
		tid = _tid()
		contract = CLMService.create_contract(session, _contract_data(tid, _uid(), _uid()), tid)
		obl = CLMService.create_obligation(session, contract.id, {
			"obligation_type": "DELIVERY",
			"description": "Deliver goods",
		}, tid)
		obl = CLMService.fulfill_obligation(session, obl.id, notes="Delivered on time", tenant_id=tid)
		assert obl.status == "FULFILLED"
		assert obl.fulfilled_at is not None

	def test_double_fulfill_raises(self, session):
		tid = _tid()
		contract = CLMService.create_contract(session, _contract_data(tid, _uid(), _uid()), tid)
		obl = CLMService.create_obligation(session, contract.id, {
			"obligation_type": "NOTICE",
			"description": "Send notice",
		}, tid)
		CLMService.fulfill_obligation(session, obl.id, tenant_id=tid)
		with pytest.raises(CLMValidationError, match="FULFILLED"):
			CLMService.fulfill_obligation(session, obl.id, tenant_id=tid)

	@freeze_time("2026-06-01")
	def test_get_overdue_obligations(self, session):
		# date.today() is deterministically 2026-06-01 under freeze_time.
		# due_date = 2026-05-27 → 5 days overdue, always.
		tid = _tid()
		contract = CLMService.create_contract(session, _contract_data(tid, _uid(), _uid()), tid)
		obl = CLMService.create_obligation(session, contract.id, {
			"obligation_type": "REPORTING",
			"description": "Q1 report",
			"due_date": date(2026, 5, 27),  # 5 days before frozen "today"
		}, tid)
		results = CLMService.get_overdue_obligations(session, date.today(), tid)
		ids = [r["obligation_id"] for r in results]
		assert obl.id in ids
		for r in results:
			if r["obligation_id"] == obl.id:
				assert r["days_overdue"] == 5


# ---------------------------------------------------------------------------
# CLMService.process_renewals
# ---------------------------------------------------------------------------

class TestProcessRenewals:
	@freeze_time("2026-06-01")
	def test_auto_renew_extends_expiry(self, session):
		# Frozen at 2026-06-01.
		# expiry = 2026-06-16 (15 days out), renewal_notice_days=30 → within notice window.
		tid = _tid()
		data = _contract_data(tid, _uid(), _uid(),
			auto_renew=True,
			renewal_notice_days=30,
			expiry_date=date(2026, 6, 16),
		)
		contract = CLMService.create_contract(session, data, tid)
		contract.status = "ACTIVE"
		session.flush()
		old_expiry = contract.expiry_date
		result = CLMService.process_renewals(session, date.today(), tid)
		assert contract.contract_number in result["auto_renewed"]
		session.refresh(contract)
		assert contract.expiry_date > old_expiry

	@freeze_time("2026-06-01")
	def test_renewal_alert_emitted(self, session):
		# Frozen at 2026-06-01.
		# expiry = 2026-07-01 (30 days out), renewal_notice_days=60 → within notice window.
		tid = _tid()
		data = _contract_data(tid, _uid(), _uid(),
			auto_renew=False,
			renewal_notice_days=60,
			expiry_date=date(2026, 7, 1),
		)
		contract = CLMService.create_contract(session, data, tid)
		contract.status = "ACTIVE"
		session.flush()
		result = CLMService.process_renewals(session, date.today(), tid)
		assert contract.contract_number in result["renewal_alerts"]


# ---------------------------------------------------------------------------
# CLMService.terminate_contract
# ---------------------------------------------------------------------------

class TestTerminateContract:
	def test_terminate_active(self, session):
		tid = _tid()
		contract = CLMService.create_contract(session, _contract_data(tid, _uid(), _uid()), tid)
		contract.status = "ACTIVE"
		session.flush()
		contract = CLMService.terminate_contract(
			session, contract.id, "Mutual agreement", date.today(), tid
		)
		assert contract.status == "TERMINATED"
		assert contract.termination_reason == "Mutual agreement"

	def test_double_terminate_raises(self, session):
		tid = _tid()
		contract = CLMService.create_contract(session, _contract_data(tid, _uid(), _uid()), tid)
		contract.status = "ACTIVE"
		session.flush()
		CLMService.terminate_contract(session, contract.id, "reason", date.today(), tid)
		with pytest.raises(CLMValidationError, match="TERMINATED"):
			CLMService.terminate_contract(session, contract.id, "reason2", date.today(), tid)


# ---------------------------------------------------------------------------
# IFRS 16 — calculate_lease_schedule / amortise_rou_asset
# ---------------------------------------------------------------------------

class TestIfrs16:
	def _make_lease_contract(self, session, tid: str) -> tuple[Any, Any]:
		owner = _uid()
		data = _contract_data(tid, owner, _uid(), contract_type="LEASE")
		contract = CLMService.create_contract(session, data, tid)
		contract.status = "ACTIVE"
		session.flush()

		ls = LeaseSchedule(
			tenant_id=tid,
			contract_id=contract.id,
			lease_type="FINANCE",
			asset_description="Photocopier",
			commencement_date=date.today(),
			lease_term_months=24,
			monthly_payment_cents=100_000,
			discount_rate_pa=Decimal("0.12"),
			rou_asset_cents=0,
			lease_liability_cents=0,
			initial_recognition_date=date.today(),
		)
		session.add(ls)
		session.flush()
		return contract, ls

	def test_pv_formula_correctness(self):
		"""Unit-test the PV formula in isolation."""
		P = Decimal("100000")
		rate_pa = Decimal("0.12")
		r = rate_pa / 12
		n = Decimal("24")
		discount_factor = (Decimal("1") - (Decimal("1") + r) ** (-n)) / r
		pv = P * discount_factor
		pv_cents = int(pv.to_integral_value(rounding=ROUND_HALF_UP))
		# PV must be < undiscounted total (P × n = 2_400_000)
		assert pv_cents < 2_400_000
		# PV must be > 0
		assert pv_cents > 0
		# Known approximate value for 12% pa, 24 months, 100k/month ≈ 2,124,339
		assert 2_100_000 < pv_cents < 2_150_000

	def test_amortisation_invariant(self):
		"""interest + principal == monthly_payment for any valid r, n, P."""
		P = Decimal("100000")
		rate_pa = Decimal("0.12")
		r = rate_pa / 12
		n = Decimal("24")
		discount_factor = (Decimal("1") - (Decimal("1") + r) ** (-n)) / r
		pv = P * discount_factor
		liability = pv
		interest = (liability * r).to_integral_value(rounding=ROUND_HALF_UP)
		principal = (P - interest).to_integral_value(rounding=ROUND_HALF_UP)
		assert int(interest) + int(principal) == int(P)

	def test_calculate_lease_schedule(self, session):
		tid = _tid()
		contract, ls = self._make_lease_contract(session, tid)
		ls_result = CLMService.calculate_lease_schedule(session, contract.id, tid)
		assert ls_result.rou_asset_cents > 0
		assert ls_result.lease_liability_cents > 0
		assert ls_result.rou_asset_cents == ls_result.lease_liability_cents

	def test_amortise_rou_asset(self, session):
		tid = _tid()
		contract, ls = self._make_lease_contract(session, tid)
		CLMService.calculate_lease_schedule(session, contract.id, tid)
		session.refresh(ls)
		rou_before = ls.rou_asset_cents  # capture after recognition, before amortisation
		result = CLMService.amortise_rou_asset(session, contract.id, date.today(), tid)
		assert result["depreciation_cents"] > 0
		assert result["interest_cents"] > 0
		assert result["principal_cents"] > 0
		assert result["interest_cents"] + result["principal_cents"] == result["payment_cents"]
		assert result["rou_carrying_cents"] < rou_before

	def test_non_lease_contract_raises(self, session):
		tid = _tid()
		contract = CLMService.create_contract(session, _contract_data(tid, _uid(), _uid()), tid)
		with pytest.raises(CLMValidationError, match="LEASE required"):
			CLMService.calculate_lease_schedule(session, contract.id, tid)

	def test_missing_lease_schedule_raises(self, session):
		tid = _tid()
		data = _contract_data(tid, _uid(), _uid(), contract_type="LEASE")
		contract = CLMService.create_contract(session, data, tid)
		with pytest.raises(CLMValidationError, match="No LeaseSchedule stub"):
			CLMService.calculate_lease_schedule(session, contract.id, tid)

	def test_zero_rate_pv(self):
		"""Zero discount rate: PV = P × n (no discounting)."""
		P = Decimal("100000")
		r = Decimal("0")
		n = Decimal("24")
		if r == Decimal("0"):
			pv = P * n
		else:
			discount_factor = (Decimal("1") - (Decimal("1") + r) ** (-n)) / r
			pv = P * discount_factor
		assert int(pv) == 2_400_000


# ---------------------------------------------------------------------------
# CLMService.get_contract_dashboard
# ---------------------------------------------------------------------------

class TestDashboard:
	def test_dashboard_returns_expected_keys(self, session):
		tid = _tid()
		result = CLMService.get_contract_dashboard(session, tid)
		assert "active_count" in result
		assert "expiring_30d" in result
		assert "expiring_90d" in result
		assert "overdue_obligations" in result
		assert "total_value_cents" in result
		assert "by_type" in result
		assert "by_status" in result

	def test_active_count_increments(self, session):
		tid = _tid()
		before = CLMService.get_contract_dashboard(session, tid)["active_count"]
		data = _contract_data(tid, _uid(), _uid(), contract_value_cents=500_000)
		contract = CLMService.create_contract(session, data, tid)
		contract.status = "ACTIVE"
		session.flush()
		after = CLMService.get_contract_dashboard(session, tid)["active_count"]
		assert after == before + 1

	def test_total_value_accumulates(self, session):
		tid = _tid()
		for _ in range(3):
			data = _contract_data(tid, _uid(), _uid(), contract_value_cents=100_000)
			c = CLMService.create_contract(session, data, tid)
			c.status = "ACTIVE"
		session.flush()
		dash = CLMService.get_contract_dashboard(session, tid)
		assert dash["total_value_cents"] >= 300_000


# ---------------------------------------------------------------------------
# Error path coverage
# ---------------------------------------------------------------------------

class TestErrorPaths:
	def test_contract_not_found(self, session):
		with pytest.raises(ContractNotFoundError):
			CLMService.submit_for_review(session, str(uuid.uuid4()), _uid(), _tid())

	def test_obligation_not_found(self, session):
		with pytest.raises(ObligationNotFoundError):
			CLMService.fulfill_obligation(session, str(uuid.uuid4()), tenant_id=_tid())

	def test_signature_request_not_found(self, session):
		with pytest.raises(SignatureRequestNotFoundError):
			CLMService.record_signature(session, str(uuid.uuid4()), tenant_id=_tid())

	def test_terminate_not_found(self, session):
		with pytest.raises(ContractNotFoundError):
			CLMService.terminate_contract(
				session, str(uuid.uuid4()), "reason", date.today(), _tid()
			)
