"""
tests/ci/test_agency_plugin.py

CI tests for the Agency Banking plugin.

Coverage:
  - Module imports and field constraints (no DB)
  - ImmutableRecordMixin on AgencyTransaction
  - Event dataclass defaults
  - AgencyService pure-logic helpers: _compute_commission, _agent_commission_pct,
    _run_kyc_check, check_float_level
  - AgencyService.onboard_outlet (session stub)
  - AgencyService.accredit_agent: ACCREDITED on KYC pass, PENDING on fail
  - AgencyService.process_transaction: COMPLETED, InsufficientFloatError,
    AgentNotAccreditedError
  - AgencyService.top_up_float: balance update
  - AgencyService.settle_commissions: aggregation arithmetic
  - AgencyPlugin: metadata, register_models, get_events, depends_on
  - Views: importorskip guard

No mocks for business logic — real objects + session stubs.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch, call

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_session() -> MagicMock:
	sess = MagicMock()
	sess.add = MagicMock()
	sess.flush = MagicMock()
	sess.execute = MagicMock()
	return sess


def _uid() -> str:
	return str(uuid.uuid4())


def _outlet(**kw) -> SimpleNamespace:
	defaults = dict(
		id=_uid(),
		tenant_id="t1",
		name="Test Shop",
		outlet_type="RETAIL_SHOP",
		services=["CASH_IN", "CASH_OUT"],
		location={"region": "Nairobi", "lat": -1.29, "lng": 36.82, "address": "Tom Mboya St"},
		float_balance_cents=1_000_000,
		float_minimum_cents=500_000,
		status="ACTIVE",
	)
	defaults.update(kw)
	return SimpleNamespace(**defaults)


def _agent(**kw) -> SimpleNamespace:
	defaults = dict(
		id=_uid(),
		tenant_id="t1",
		outlet_id=_uid(),
		agent_name="Jane Mwangi",
		msisdn="+254700000001",
		national_id="12345678",
		accreditation_status="ACCREDITED",
		accredited_at=datetime.now(timezone.utc),
		kyc_tier=2,
	)
	defaults.update(kw)
	return SimpleNamespace(**defaults)


def _float(**kw) -> SimpleNamespace:
	defaults = dict(
		id=_uid(),
		tenant_id="t1",
		outlet_id=_uid(),
		current_balance_cents=2_000_000,
		last_topped_up_at=None,
		updated_at=datetime.now(timezone.utc),
	)
	defaults.update(kw)
	return SimpleNamespace(**defaults)


# ---------------------------------------------------------------------------
# Import tests
# ---------------------------------------------------------------------------

def test_models_import():
	from pgappforge.plugins.fintech.agency.models import (
		AgencyOutlet,
		AgencyAgent,
		AgencyTransaction,
		AgencyFloat,
		AgencyCommission,
	)
	assert AgencyOutlet.__tablename__ == "ft_agency_outlet"
	assert AgencyAgent.__tablename__ == "ft_agency_agent"
	assert AgencyTransaction.__tablename__ == "ft_agency_transaction"
	assert AgencyFloat.__tablename__ == "ft_agency_float"
	assert AgencyCommission.__tablename__ == "ft_agency_commission"


def test_events_import():
	from pgappforge.plugins.fintech.agency.events import (
		AgentAccreditedEvent,
		FloatToppedUpEvent,
		AgencyTransactionEvent,
		CommissionSettledEvent,
		OutletSuspendedEvent,
		ALL_AGENCY_EVENT_TYPES,
	)
	assert len(ALL_AGENCY_EVENT_TYPES) == 5
	assert "agency.agent.accredited" in ALL_AGENCY_EVENT_TYPES
	assert "agency.float.topped_up" in ALL_AGENCY_EVENT_TYPES
	assert "agency.transaction" in ALL_AGENCY_EVENT_TYPES
	assert "agency.commission.settled" in ALL_AGENCY_EVENT_TYPES
	assert "agency.outlet.suspended" in ALL_AGENCY_EVENT_TYPES

	ev = AgentAccreditedEvent()
	assert ev.event_type == "agency.agent.accredited"
	assert ev.kyc_tier == 1

	fev = FloatToppedUpEvent()
	assert fev.event_type == "agency.float.topped_up"
	assert fev.amount_cents == 0

	tev = AgencyTransactionEvent()
	assert tev.event_type == "agency.transaction"
	assert tev.fee_cents == 0


def test_services_import():
	from pgappforge.plugins.fintech.agency.services import (
		AgencyService,
		AgencyError,
		OutletNotFoundError,
		AgentNotFoundError,
		AgentNotAccreditedError,
		InsufficientFloatError,
		FloatNotFoundError,
	)
	assert issubclass(OutletNotFoundError, AgencyError)
	assert issubclass(AgentNotAccreditedError, AgencyError)
	assert issubclass(InsufficientFloatError, AgencyError)


def test_views_import():
	pytest.importorskip("flask_appbuilder", reason="flask_appbuilder not available in this env")
	from pgappforge.plugins.fintech.agency.views import (
		AgencyOutletView,
		AgencyAgentView,
		AgencyTransactionView,
		AgencyDashboardView,
	)
	assert hasattr(AgencyOutletView, "datamodel")
	assert hasattr(AgencyAgentView, "datamodel")
	assert hasattr(AgencyTransactionView, "datamodel")
	assert AgencyTransactionView.can_add is False
	assert AgencyTransactionView.can_edit is False


# ---------------------------------------------------------------------------
# Model field tests
# ---------------------------------------------------------------------------

def test_agency_outlet_columns():
	from pgappforge.plugins.fintech.agency.models import AgencyOutlet
	import sqlalchemy as sa
	cols = {c.name: c for c in AgencyOutlet.__table__.columns}
	# money columns must be Integer, not Numeric/Float
	assert isinstance(cols["float_balance_cents"].type, sa.Integer)
	assert isinstance(cols["float_minimum_cents"].type, sa.Integer)
	# defaults
	assert cols["status"].default.arg == "ACTIVE"
	assert cols["float_balance_cents"].default.arg == 0
	assert cols["float_minimum_cents"].default.arg == 500_000


def test_agency_transaction_columns():
	from pgappforge.plugins.fintech.agency.models import AgencyTransaction
	import sqlalchemy as sa
	cols = {c.name: c for c in AgencyTransaction.__table__.columns}
	assert isinstance(cols["amount_cents"].type, sa.Integer)
	assert isinstance(cols["fee_cents"].type, sa.Integer)
	assert isinstance(cols["agent_commission_cents"].type, sa.Integer)
	# reference must be unique
	uqs = [c.name for c in AgencyTransaction.__table__.constraints
		   if hasattr(c, "columns") and "reference" in [col.name for col in getattr(c, "columns", [])]]
	assert len(uqs) >= 1


def test_agency_float_columns():
	from pgappforge.plugins.fintech.agency.models import AgencyFloat
	import sqlalchemy as sa
	cols = {c.name: c for c in AgencyFloat.__table__.columns}
	assert isinstance(cols["current_balance_cents"].type, sa.Integer)
	# outlet_id must be unique (one-to-one with outlet)
	uqs_names = [c.name for c in AgencyFloat.__table__.constraints
				 if hasattr(c, "columns") and "outlet_id" in [col.name for col in getattr(c, "columns", [])]]
	assert len(uqs_names) >= 1


def test_agency_commission_columns():
	from pgappforge.plugins.fintech.agency.models import AgencyCommission
	import sqlalchemy as sa
	cols = {c.name: c for c in AgencyCommission.__table__.columns}
	for col in ("gross_commission_cents", "tax_cents", "net_commission_cents"):
		assert isinstance(cols[col].type, sa.Integer), f"{col} must be Integer"
	assert cols["status"].default.arg == "PENDING"


# ---------------------------------------------------------------------------
# ImmutableRecordMixin
# ---------------------------------------------------------------------------

def test_agency_transaction_immutable():
	"""AgencyTransaction must block UPDATE via ImmutableRecordMixin."""
	from pgappforge.plugins.fintech.agency.models import AgencyTransaction
	from pgappforge.plugins.erp.foundation.commons import ImmutableRecordMixin
	assert issubclass(AgencyTransaction, ImmutableRecordMixin)
	assert AgencyTransaction._immutable is True


# ---------------------------------------------------------------------------
# Event dataclass completeness
# ---------------------------------------------------------------------------

def test_event_dataclass_fields():
	from pgappforge.plugins.fintech.agency.events import (
		AgentAccreditedEvent,
		FloatToppedUpEvent,
		AgencyTransactionEvent,
		CommissionSettledEvent,
		OutletSuspendedEvent,
	)
	# Each event must have aggregate_type/aggregate_id from DomainEvent
	for cls in (AgentAccreditedEvent, FloatToppedUpEvent, AgencyTransactionEvent,
				CommissionSettledEvent, OutletSuspendedEvent):
		ev = cls()
		assert hasattr(ev, "aggregate_type")
		assert hasattr(ev, "tenant_id")
		assert hasattr(ev, "event_type")
		assert ev.event_type.startswith("agency.")


# ---------------------------------------------------------------------------
# Service: pure-logic helpers
# ---------------------------------------------------------------------------

def test_compute_commission_defaults():
	from pgappforge.plugins.fintech.agency.services import AgencyService
	svc = AgencyService()
	# CASH_OUT = 0.50% of amount
	assert svc._compute_commission("CASH_OUT", 100_000) == 500
	# ACCOUNT_OPENING = 1.00%
	assert svc._compute_commission("ACCOUNT_OPENING", 100_000) == 1_000
	# unknown service → 0.20% default
	assert svc._compute_commission("UNKNOWN_SERVICE", 100_000) == 200


def test_agent_commission_pct():
	from pgappforge.plugins.fintech.agency.services import AgencyService
	svc = AgencyService()
	assert svc._agent_commission_pct("CASH_IN") == Decimal("0.20")
	assert svc._agent_commission_pct("CASH_OUT") == Decimal("0.50")
	assert svc._agent_commission_pct("REMITTANCE") == Decimal("0.40")


def test_commission_pct_config_override():
	from pgappforge.plugins.fintech.agency.services import AgencyService
	custom = {"CASH_OUT": Decimal("1.00")}
	svc = AgencyService(config={"AGENCY_COMMISSION_RATES": custom})
	assert svc._agent_commission_pct("CASH_OUT") == Decimal("1.00")


def test_run_kyc_check_pass():
	from pgappforge.plugins.fintech.agency.services import AgencyService
	svc = AgencyService()
	passed, tier = svc._run_kyc_check("12345678", "+254700000001")
	assert passed is True
	assert tier == 2


def test_run_kyc_check_fail_short_id():
	from pgappforge.plugins.fintech.agency.services import AgencyService
	svc = AgencyService()
	passed, tier = svc._run_kyc_check("123", "+254700000001")
	assert passed is False


# ---------------------------------------------------------------------------
# Service: onboard_outlet (session stub)
# ---------------------------------------------------------------------------

def test_onboard_outlet_creates_outlet_and_float():
	from pgappforge.plugins.fintech.agency.services import AgencyService
	from pgappforge.plugins.fintech.agency.models import AgencyOutlet, AgencyFloat

	sess = _make_session()
	added = []
	sess.add.side_effect = lambda obj: added.append(obj)

	svc = AgencyService()
	outlet = svc.onboard_outlet(
		name="Kenyatta Ave Outlet",
		outlet_type="RETAIL_SHOP",
		services=["CASH_IN", "CASH_OUT"],
		location={"region": "CBD", "lat": -1.28, "lng": 36.81, "address": "Kenyatta Ave"},
		tenant_id="t1",
		session=sess,
	)

	assert isinstance(outlet, AgencyOutlet)
	assert outlet.name == "Kenyatta Ave Outlet"
	assert outlet.outlet_type == "RETAIL_SHOP"
	assert outlet.status == "ACTIVE"
	assert outlet.float_minimum_cents == 500_000

	# Both outlet and float should have been added
	types = [type(obj).__name__ for obj in added]
	assert "AgencyOutlet" in types
	assert "AgencyFloat" in types


def test_onboard_outlet_custom_float_minimum():
	from pgappforge.plugins.fintech.agency.services import AgencyService
	from pgappforge.plugins.fintech.agency.models import AgencyFloat

	sess = _make_session()
	added = []
	sess.add.side_effect = lambda obj: added.append(obj)

	svc = AgencyService()
	outlet = svc.onboard_outlet(
		name="Mobile Van",
		outlet_type="MOBILE_VAN",
		services=["CASH_IN"],
		location={},
		tenant_id="t1",
		session=sess,
		float_minimum_cents=200_000,
	)
	assert outlet.float_minimum_cents == 200_000
	floats = [o for o in added if isinstance(o, AgencyFloat)]
	assert len(floats) == 1


# ---------------------------------------------------------------------------
# Service: accredit_agent
# ---------------------------------------------------------------------------

def test_accredit_agent_accredited_on_kyc_pass():
	from pgappforge.plugins.fintech.agency.services import AgencyService
	from pgappforge.plugins.fintech.agency.models import AgencyAgent

	sess = _make_session()
	outlet = _outlet()

	added = []
	sess.add.side_effect = lambda obj: added.append(obj)

	svc = AgencyService()
	# Patch _get_outlet to return our stub
	with patch.object(svc, "_get_outlet", return_value=outlet):
		agent = svc.accredit_agent(
			outlet_id=outlet.id,
			agent_name="John Kamau",
			msisdn="+254711000001",
			national_id="98765432",		# 8 chars → KYC pass
			tenant_id="t1",
			session=sess,
		)

	assert isinstance(agent, AgencyAgent)
	assert agent.accreditation_status == "ACCREDITED"
	assert agent.kyc_tier == 2
	assert agent.accredited_at is not None


def test_accredit_agent_stays_pending_on_kyc_fail():
	from pgappforge.plugins.fintech.agency.services import AgencyService

	sess = _make_session()
	outlet = _outlet()
	sess.add.side_effect = lambda obj: None

	svc = AgencyService()
	with patch.object(svc, "_get_outlet", return_value=outlet):
		agent = svc.accredit_agent(
			outlet_id=outlet.id,
			agent_name="Bad ID",
			msisdn="+254711000002",
			national_id="123",			# too short → KYC fail
			tenant_id="t1",
			session=sess,
		)

	assert agent.accreditation_status == "PENDING"
	assert agent.accredited_at is None


def test_accredit_agent_suspended_outlet_raises():
	from pgappforge.plugins.fintech.agency.services import AgencyService

	svc = AgencyService()
	sess = _make_session()
	outlet = _outlet(status="SUSPENDED")

	with patch.object(svc, "_get_outlet", return_value=outlet):
		with pytest.raises(AssertionError):
			svc.accredit_agent(
				outlet_id=outlet.id,
				agent_name="X",
				msisdn="+254",
				national_id="12345678",
				tenant_id="t1",
				session=sess,
			)


# ---------------------------------------------------------------------------
# Service: process_transaction
# ---------------------------------------------------------------------------

def test_process_transaction_cash_out_success():
	from pgappforge.plugins.fintech.agency.services import AgencyService
	from pgappforge.plugins.fintech.agency.models import AgencyTransaction

	sess = _make_session()
	agent = _agent(outlet_id="outlet-1")
	float_rec = _float(outlet_id="outlet-1", current_balance_cents=5_000_000)
	outlet = _outlet(id="outlet-1", float_balance_cents=5_000_000)
	added = []
	sess.add.side_effect = lambda obj: added.append(obj)

	svc = AgencyService()
	with patch.object(svc, "_get_agent", return_value=agent), \
		 patch.object(svc, "_get_float", return_value=float_rec), \
		 patch.object(svc, "_get_outlet", return_value=outlet):

		txn = svc.process_transaction(
			agent_id=agent.id,
			service_type="CASH_OUT",
			customer_msisdn="+254720000001",
			amount_cents=1_000_000,
			tenant_id="t1",
			session=sess,
			reference="REF-001",
		)

	assert isinstance(txn, AgencyTransaction)
	assert txn.status == "COMPLETED"
	assert txn.reference == "REF-001"
	assert txn.amount_cents == 1_000_000
	# Float should have been debited
	assert float_rec.current_balance_cents == 4_000_000


def test_process_transaction_cash_in_credits_float():
	from pgappforge.plugins.fintech.agency.services import AgencyService

	sess = _make_session()
	agent = _agent(outlet_id="outlet-2")
	float_rec = _float(outlet_id="outlet-2", current_balance_cents=1_000_000)
	outlet = _outlet(id="outlet-2", float_balance_cents=1_000_000)
	sess.add.side_effect = lambda obj: None

	svc = AgencyService()
	with patch.object(svc, "_get_agent", return_value=agent), \
		 patch.object(svc, "_get_float", return_value=float_rec), \
		 patch.object(svc, "_get_outlet", return_value=outlet):

		txn = svc.process_transaction(
			agent_id=agent.id,
			service_type="CASH_IN",
			customer_msisdn="+254720000002",
			amount_cents=500_000,
			tenant_id="t1",
			session=sess,
		)

	assert txn.status == "COMPLETED"
	assert float_rec.current_balance_cents == 1_500_000


def test_process_transaction_insufficient_float_raises():
	from pgappforge.plugins.fintech.agency.services import AgencyService, InsufficientFloatError

	sess = _make_session()
	agent = _agent()
	float_rec = _float(current_balance_cents=100_000)  # only KES 1,000
	sess.add.side_effect = lambda obj: None

	svc = AgencyService()
	with patch.object(svc, "_get_agent", return_value=agent), \
		 patch.object(svc, "_get_float", return_value=float_rec):

		with pytest.raises(InsufficientFloatError):
			svc.process_transaction(
				agent_id=agent.id,
				service_type="CASH_OUT",
				customer_msisdn="+254720000003",
				amount_cents=500_000,		# more than float
				tenant_id="t1",
				session=sess,
			)


def test_process_transaction_unaccredited_agent_raises():
	from pgappforge.plugins.fintech.agency.services import AgencyService, AgentNotAccreditedError

	sess = _make_session()
	agent = _agent(accreditation_status="PENDING")
	sess.add.side_effect = lambda obj: None

	svc = AgencyService()
	with patch.object(svc, "_get_agent", return_value=agent):
		with pytest.raises(AgentNotAccreditedError):
			svc.process_transaction(
				agent_id=agent.id,
				service_type="CASH_IN",
				customer_msisdn="+254720000004",
				amount_cents=100_000,
				tenant_id="t1",
				session=sess,
			)


def test_process_transaction_zero_amount_raises():
	from pgappforge.plugins.fintech.agency.services import AgencyService

	svc = AgencyService()
	sess = _make_session()
	with pytest.raises(AssertionError):
		svc.process_transaction(
			agent_id="a", service_type="CASH_IN",
			customer_msisdn="+254", amount_cents=0,
			tenant_id="t1", session=sess,
		)


# ---------------------------------------------------------------------------
# Service: top_up_float
# ---------------------------------------------------------------------------

def test_top_up_float_adds_balance():
	from pgappforge.plugins.fintech.agency.services import AgencyService

	sess = _make_session()
	outlet = _outlet(id="out-1", float_balance_cents=1_000_000)
	float_rec = _float(outlet_id="out-1", current_balance_cents=1_000_000)

	svc = AgencyService()
	with patch.object(svc, "_get_outlet", return_value=outlet), \
		 patch.object(svc, "_get_float", return_value=float_rec):

		result = svc.top_up_float("out-1", 2_000_000, "t1", sess)

	assert result.current_balance_cents == 3_000_000
	assert result.last_topped_up_at is not None
	assert outlet.float_balance_cents == 3_000_000


def test_top_up_float_zero_raises():
	from pgappforge.plugins.fintech.agency.services import AgencyService

	svc = AgencyService()
	with pytest.raises(AssertionError):
		svc.top_up_float("out-1", 0, "t1", _make_session())


# ---------------------------------------------------------------------------
# Service: check_float_level
# ---------------------------------------------------------------------------

def test_check_float_level_not_low():
	from pgappforge.plugins.fintech.agency.services import AgencyService

	outlet = _outlet(float_minimum_cents=500_000)
	float_rec = _float(current_balance_cents=1_000_000)
	svc = AgencyService()
	with patch.object(svc, "_get_outlet", return_value=outlet), \
		 patch.object(svc, "_get_float", return_value=float_rec):

		result = svc.check_float_level("out-1", "t1", _make_session())

	assert result["current_cents"] == 1_000_000
	assert result["minimum_cents"] == 500_000
	assert result["is_low"] is False


def test_check_float_level_is_low():
	from pgappforge.plugins.fintech.agency.services import AgencyService

	outlet = _outlet(float_minimum_cents=500_000)
	float_rec = _float(current_balance_cents=200_000)
	svc = AgencyService()
	with patch.object(svc, "_get_outlet", return_value=outlet), \
		 patch.object(svc, "_get_float", return_value=float_rec):

		result = svc.check_float_level("out-1", "t1", _make_session())

	assert result["is_low"] is True


# ---------------------------------------------------------------------------
# Service: settle_commissions arithmetic
# ---------------------------------------------------------------------------

def test_settle_commissions_wht_arithmetic():
	"""15% WHT on gross commission is computed correctly."""
	from pgappforge.plugins.erp.foundation.commons import percent_of
	gross = 10_000		# KES 100.00
	wht_rate = Decimal("15")
	tax = percent_of(gross, wht_rate)
	net = max(0, gross - tax)
	assert tax == 1_500
	assert net == 8_500


def test_settle_commissions_invalid_period_raises():
	from pgappforge.plugins.fintech.agency.services import AgencyService

	svc = AgencyService()
	with pytest.raises(AssertionError):
		svc.settle_commissions("2025/01", "t1", _make_session())


# ---------------------------------------------------------------------------
# AgencyPlugin
# ---------------------------------------------------------------------------

def test_agency_plugin_metadata():
	from pgappforge.plugins.fintech.agency import AgencyPlugin
	p = AgencyPlugin()
	assert p.name == "agency_banking"
	assert p.domain == "fintech"
	assert "foundation" in p.depends_on
	assert "core_banking" in p.depends_on


def test_agency_plugin_register_models():
	from pgappforge.plugins.fintech.agency import AgencyPlugin
	from pgappforge.plugins.fintech.agency.models import (
		AgencyOutlet, AgencyAgent, AgencyTransaction, AgencyFloat, AgencyCommission,
	)
	p = AgencyPlugin()
	models = p.register_models()
	names = {m.__name__ for m in models}
	assert names == {"AgencyOutlet", "AgencyAgent", "AgencyTransaction", "AgencyFloat", "AgencyCommission"}


def test_agency_plugin_get_events():
	from pgappforge.plugins.fintech.agency import AgencyPlugin
	p = AgencyPlugin()
	evts = p.get_events()
	assert len(evts) == 5
	assert "agency.agent.accredited" in evts
	assert "agency.commission.settled" in evts


def test_agency_plugin_metadata_object():
	from pgappforge.plugins.fintech.agency import AgencyPlugin
	p = AgencyPlugin()
	meta = p.metadata
	assert meta.name == "agency_banking"
	assert "float" in meta.description.lower()
	assert len(meta.permissions) >= 6


def test_agency_plugin_initialize_defaults():
	from pgappforge.plugins.fintech.agency import AgencyPlugin
	p = AgencyPlugin()
	p.initialize()
	assert "AGENCY_MENU_CATEGORY" in p.config
	assert p.config["AGENCY_WHT_RATE"] == "15"
	assert p.config["AGENCY_DEFAULT_CURRENCY"] == "KES"
