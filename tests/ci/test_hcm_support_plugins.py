"""
tests/ci/test_hcm_support_plugins.py

CI tests for HCM Analytics, Lunch, Referral, and Wellness plugins.

Coverage:
  - Import smoke tests + plugin name/metadata assertions
  - HrAnalyticsService: compute_flight_risk, generate_snapshot
  - LunchService: publish_menu, place_order
  - ReferralService: submit_referral, get_referrer_stats
  - WellnessService: record_checkin (with flag detection), get_wellbeing_trend

Rules:
  - SQLite in-memory engine (no PostgreSQL required)
  - JSONB → JSON, UUID(as_uuid=False) → String(36), DateTime(timezone=True) → DateTime
  - Numeric → Float, BigInteger → Integer for SQLite compat
  - No @pytest.mark.asyncio — plain functions
  - No MagicMock — real SQLAlchemy Session throughout
  - scope="module" engine fixture; per-test transactional sessions
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
import sqlalchemy as sa
from sqlalchemy import (
	Boolean,
	Column,
	Date,
	DateTime,
	Float,
	ForeignKey,
	Index,
	Integer,
	JSON,
	String,
	Text,
	Time,
	UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Session


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _uid() -> str:
	return str(uuid.uuid4())


TENANT = _uid()


# ---------------------------------------------------------------------------
# Minimal SQLite-compatible declarative base (independent of pgappforge Base)
# ---------------------------------------------------------------------------

class _Base(DeclarativeBase):
	pass


# ---------------------------------------------------------------------------
# Stub for HCM personnel Employee model (hcm_per_employee)
# compute_flight_risk imports the real Employee class successfully (no ImportError),
# then queries hcm_per_employee at runtime.  We register a minimal stub table so
# the SELECT succeeds and returns 0 rows — triggering the "no employee data" scoring
# path (only the no-promotion-in-3yr factor fires → score=20 → LOW).
# ---------------------------------------------------------------------------

class _Employee(_Base):
	__tablename__ = "hcm_per_employee"
	__table_args__ = {"extend_existing": True}
	id = Column(String(36), primary_key=True, default=_uid)
	tenant_id = Column(String(36), nullable=False)
	employee_number = Column(String(50), nullable=True)
	party_id = Column(String(36), nullable=True)
	position_id = Column(String(36), nullable=True)
	entity_id = Column(String(36), nullable=True)
	org_unit_id = Column(String(36), nullable=True)
	manager_id = Column(String(36), nullable=True)
	department_id = Column(String(36), nullable=True)
	employment_type = Column(String(30), nullable=True)
	employment_status = Column(String(30), nullable=True)
	gender = Column(String(10), nullable=True)
	date_of_birth = Column(Date, nullable=True)
	start_date = Column(Date, nullable=True)
	probation_end_date = Column(Date, nullable=True)
	termination_date = Column(Date, nullable=True)
	termination_type = Column(String(30), nullable=True)
	termination_reason = Column(Text, nullable=True)
	rehire_eligible = Column(Boolean, nullable=True)
	cost_center_code = Column(String(50), nullable=True)
	background_check_status = Column(String(30), nullable=True)
	background_check_provider = Column(String(100), nullable=True)
	background_check_ref = Column(String(100), nullable=True)
	national_id_encrypted = Column(Text, nullable=True)
	tax_id_encrypted = Column(Text, nullable=True)
	bank_account_iban_encrypted = Column(Text, nullable=True)
	bank_bic = Column(String(20), nullable=True)
	created_at = Column(DateTime, nullable=True)
	updated_at = Column(DateTime, nullable=True)


# ---------------------------------------------------------------------------
# Analytics tables
# ---------------------------------------------------------------------------

class _HrAnalyticsSnapshot(_Base):
	__tablename__ = "hr_anl_snapshot"
	__table_args__ = (
		Index("ix_hr_anl_snap_tenant_type_period", "tenant_id", "snapshot_type", "period"),
		{"extend_existing": True},
	)
	id = Column(String(36), primary_key=True, default=_uid)
	tenant_id = Column(String(36), nullable=False)
	snapshot_type = Column(String(50), nullable=False)
	period = Column(String(20), nullable=False)
	entity_id = Column(String(50), nullable=True)
	data = Column(JSON, nullable=False, default=dict)
	computed_at = Column(DateTime, nullable=True)
	period_start = Column(Date, nullable=True)
	period_end = Column(Date, nullable=True)
	created_at = Column(DateTime, nullable=True)
	updated_at = Column(DateTime, nullable=True)


class _HrFlightRiskScore(_Base):
	__tablename__ = "hr_anl_flight_risk"
	__table_args__ = (
		Index("ix_hr_anl_fr_employee_current", "employee_id", "is_current"),
		{"extend_existing": True},
	)
	id = Column(String(36), primary_key=True, default=_uid)
	tenant_id = Column(String(36), nullable=False)
	employee_id = Column(String(50), nullable=False)
	score = Column(Integer, nullable=False)
	risk_level = Column(String(20), nullable=False)
	factors = Column(JSON, nullable=False, default=list)
	computed_at = Column(DateTime, nullable=True)
	is_current = Column(Boolean, nullable=False, default=True)
	notes = Column(Text, nullable=True)
	created_at = Column(DateTime, nullable=True)
	updated_at = Column(DateTime, nullable=True)


class _HrAnalyticsReport(_Base):
	__tablename__ = "hr_anl_report"
	__table_args__ = {"extend_existing": True}
	id = Column(String(36), primary_key=True, default=_uid)
	tenant_id = Column(String(36), nullable=False)
	report_type = Column(String(50), nullable=False)
	title = Column(String(300), nullable=False)
	period = Column(String(20), nullable=False)
	entity_id = Column(String(50), nullable=True)
	generated_by = Column(String(50), nullable=True)
	generated_at = Column(DateTime, nullable=True)
	parameters = Column(JSON, nullable=False, default=dict)
	result_data = Column(JSON, nullable=False, default=dict)
	created_at = Column(DateTime, nullable=True)
	updated_at = Column(DateTime, nullable=True)


# ---------------------------------------------------------------------------
# Lunch tables
# ---------------------------------------------------------------------------

class _LunchSupplier(_Base):
	__tablename__ = "lun_supplier"
	__table_args__ = {"extend_existing": True}
	id = Column(String(36), primary_key=True, default=_uid)
	tenant_id = Column(String(36), nullable=False)
	name = Column(String(200), nullable=False)
	contact_email = Column(String(200), nullable=True)
	contact_phone = Column(String(50), nullable=True)
	is_active = Column(Boolean, nullable=False, default=True)
	delivery_days = Column(JSON, nullable=False, default=list)
	notes = Column(Text, nullable=True)
	created_at = Column(DateTime, nullable=True)
	updated_at = Column(DateTime, nullable=True)


class _LunchMenu(_Base):
	__tablename__ = "lun_menu"
	__table_args__ = {"extend_existing": True}
	id = Column(String(36), primary_key=True, default=_uid)
	tenant_id = Column(String(36), nullable=False)
	supplier_id = Column(String(36), ForeignKey("lun_supplier.id"), nullable=False)
	menu_date = Column(Date, nullable=False)
	status = Column(String(20), nullable=False, default="DRAFT")
	cutoff_time = Column(Time, nullable=True)
	items = Column(JSON, nullable=False, default=list)
	created_at = Column(DateTime, nullable=True)
	updated_at = Column(DateTime, nullable=True)


class _LunchOrder(_Base):
	__tablename__ = "lun_order"
	__table_args__ = (
		UniqueConstraint("employee_id", "menu_id", name="uq_lun_order_employee_menu"),
		{"extend_existing": True},
	)
	id = Column(String(36), primary_key=True, default=_uid)
	tenant_id = Column(String(36), nullable=False)
	employee_id = Column(String(50), nullable=False)
	menu_id = Column(String(36), ForeignKey("lun_menu.id"), nullable=False)
	order_date = Column(Date, nullable=False)
	items = Column(JSON, nullable=False, default=list)
	subtotal_cents = Column(Integer, nullable=False, default=0)
	subsidy_cents = Column(Integer, nullable=False, default=0)
	employee_pays_cents = Column(Integer, nullable=False, default=0)
	status = Column(String(20), nullable=False, default="DRAFT")
	placed_at = Column(DateTime, nullable=True)
	special_instructions = Column(Text, nullable=True)
	created_at = Column(DateTime, nullable=True)
	updated_at = Column(DateTime, nullable=True)


class _LunchSubsidyPolicy(_Base):
	__tablename__ = "lun_subsidy_policy"
	__table_args__ = {"extend_existing": True}
	id = Column(String(36), primary_key=True, default=_uid)
	tenant_id = Column(String(36), nullable=False)
	entity_id = Column(String(50), nullable=True)
	subsidy_type = Column(String(20), nullable=False)
	fixed_amount_cents = Column(Integer, nullable=False, default=0)
	percentage = Column(Float, nullable=False, default=0)
	max_daily_cents = Column(Integer, nullable=True)
	is_active = Column(Boolean, nullable=False, default=True)
	effective_from = Column(Date, nullable=False)
	effective_to = Column(Date, nullable=True)
	created_at = Column(DateTime, nullable=True)
	updated_at = Column(DateTime, nullable=True)


# ---------------------------------------------------------------------------
# Referral tables
# ---------------------------------------------------------------------------

class _ReferralProgram(_Base):
	__tablename__ = "ref_program"
	__table_args__ = {"extend_existing": True}
	id = Column(String(36), primary_key=True, default=_uid)
	tenant_id = Column(String(36), nullable=False)
	name = Column(String(200), nullable=False)
	status = Column(String(20), nullable=False, default="ACTIVE")
	reward_amount_cents = Column(Integer, nullable=False, default=0)
	reward_type = Column(String(20), nullable=False, default="CASH")
	reward_conditions = Column(JSON, nullable=False, default=dict)
	eligible_positions = Column(JSON, nullable=False, default=list)
	starts_at = Column(Date, nullable=False)
	ends_at = Column(Date, nullable=True)
	created_at = Column(DateTime, nullable=True)
	updated_at = Column(DateTime, nullable=True)


class _ReferralSubmission(_Base):
	__tablename__ = "ref_submission"
	__table_args__ = {"extend_existing": True}
	id = Column(String(36), primary_key=True, default=_uid)
	tenant_id = Column(String(36), nullable=False)
	referrer_id = Column(String(50), nullable=False)
	program_id = Column(String(36), ForeignKey("ref_program.id"), nullable=False)
	candidate_name = Column(String(200), nullable=False)
	candidate_email = Column(String(200), nullable=False)
	candidate_phone = Column(String(50), nullable=True)
	position = Column(String(200), nullable=True)
	status = Column(String(20), nullable=False, default="SUBMITTED")
	resume_url = Column(Text, nullable=True)
	notes = Column(Text, nullable=True)
	submitted_at = Column(DateTime, nullable=False)
	hired_at = Column(DateTime, nullable=True)
	reward_eligible = Column(Boolean, nullable=False, default=False)
	created_at = Column(DateTime, nullable=True)
	updated_at = Column(DateTime, nullable=True)


class _ReferralReward(_Base):
	__tablename__ = "ref_reward"
	__table_args__ = (
		UniqueConstraint("submission_id", name="uq_ref_reward_submission"),
		{"extend_existing": True},
	)
	id = Column(String(36), primary_key=True, default=_uid)
	tenant_id = Column(String(36), nullable=False)
	submission_id = Column(String(36), ForeignKey("ref_submission.id"), nullable=False, unique=True)
	referrer_id = Column(String(50), nullable=False)
	reward_amount_cents = Column(Integer, nullable=False)
	reward_type = Column(String(20), nullable=False)
	status = Column(String(20), nullable=False, default="PENDING")
	approved_by = Column(String(50), nullable=True)
	approved_at = Column(DateTime, nullable=True)
	paid_at = Column(DateTime, nullable=True)
	payment_ref = Column(String(100), nullable=True)
	created_at = Column(DateTime, nullable=True)
	updated_at = Column(DateTime, nullable=True)


# ---------------------------------------------------------------------------
# Wellness tables
# ---------------------------------------------------------------------------

class _WellnessProgram(_Base):
	__tablename__ = "wel_program"
	__table_args__ = {"extend_existing": True}
	id = Column(String(36), primary_key=True, default=_uid)
	tenant_id = Column(String(36), nullable=False)
	name = Column(String(200), nullable=False)
	description = Column(Text, nullable=True)
	program_type = Column(String(20), nullable=False, default="GENERAL")
	status = Column(String(20), nullable=False, default="ACTIVE")
	provider = Column(String(200), nullable=True)
	start_date = Column(Date, nullable=True)
	end_date = Column(Date, nullable=True)
	is_voluntary = Column(Boolean, nullable=False, default=True)
	target_roles = Column(JSON, nullable=False, default=list)
	max_participants = Column(Integer, nullable=True)
	created_at = Column(DateTime, nullable=True)
	updated_at = Column(DateTime, nullable=True)


class _WellnessEnrollment(_Base):
	__tablename__ = "wel_enrollment"
	__table_args__ = (
		UniqueConstraint("employee_id", "program_id", name="uq_wel_enrollment_employee_program"),
		{"extend_existing": True},
	)
	id = Column(String(36), primary_key=True, default=_uid)
	tenant_id = Column(String(36), nullable=False)
	employee_id = Column(String(50), nullable=False)
	program_id = Column(String(36), ForeignKey("wel_program.id"), nullable=False)
	enrolled_at = Column(DateTime, nullable=False)
	status = Column(String(20), nullable=False, default="ACTIVE")
	completed_at = Column(DateTime, nullable=True)
	created_at = Column(DateTime, nullable=True)
	updated_at = Column(DateTime, nullable=True)


class _WellnessCheckIn(_Base):
	__tablename__ = "wel_checkin"
	__table_args__ = (
		UniqueConstraint("employee_id", "check_in_date", name="uq_wel_checkin_employee_date"),
		{"extend_existing": True},
	)
	id = Column(String(36), primary_key=True, default=_uid)
	tenant_id = Column(String(36), nullable=False)
	employee_id = Column(String(50), nullable=False)
	check_in_date = Column(Date, nullable=False)
	wellbeing_score = Column(Integer, nullable=False)
	energy_level = Column(Integer, nullable=True)
	stress_level = Column(Integer, nullable=True)
	flags = Column(JSON, nullable=False, default=list)
	anonymous = Column(Boolean, nullable=False, default=False)
	notes = Column(Text, nullable=True)
	created_at = Column(DateTime, nullable=True)
	updated_at = Column(DateTime, nullable=True)


class _EapReferral(_Base):
	__tablename__ = "wel_eap_referral"
	__table_args__ = {"extend_existing": True}
	id = Column(String(36), primary_key=True, default=_uid)
	tenant_id = Column(String(36), nullable=False)
	employee_id = Column(String(50), nullable=False)
	category = Column(String(50), nullable=False)
	status = Column(String(20), nullable=False, default="OPEN")
	opened_at = Column(DateTime, nullable=False)
	closed_at = Column(DateTime, nullable=True)
	provider = Column(String(200), nullable=True)
	sessions_count = Column(Integer, nullable=False, default=0)
	notes = Column(Text, nullable=True)
	created_at = Column(DateTime, nullable=True)
	updated_at = Column(DateTime, nullable=True)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def engine():
	"""SQLite in-memory engine with all four plugin schemas."""
	eng = sa.create_engine(
		"sqlite:///:memory:",
		connect_args={"check_same_thread": False},
		echo=False,
	)
	_Base.metadata.create_all(eng)
	return eng


@pytest.fixture
def session(engine):
	"""Transactional session rolled back after each test."""
	connection = engine.connect()
	trans = connection.begin()
	sess = Session(bind=connection)
	yield sess
	sess.close()
	trans.rollback()
	connection.close()


# ===========================================================================
# ANALYTICS
# ===========================================================================

def test_analytics_imports():
	from pgappforge.plugins.erp.hcm.analytics import (
		HrAnalyticsPlugin,
		HrAnalyticsService,
		HrAnalyticsSnapshot,
		HrFlightRiskScore,
	)
	assert HrAnalyticsPlugin.name == "analytics"
	assert HrAnalyticsSnapshot.__tablename__ == "hr_anl_snapshot"
	assert HrFlightRiskScore.__tablename__ == "hr_anl_flight_risk"
	# Service is a plain class — instantiates without args
	svc = HrAnalyticsService()
	assert callable(svc.compute_flight_risk)
	assert callable(svc.generate_snapshot)


def test_flight_risk_score(session):
	"""compute_flight_risk persists a score row and returns valid risk metadata.

	Strategy: patch sys.modules so the service's internal
	  `from pgappforge.plugins.erp.hcm.personnel.models import Employee`
	resolves to our SQLite-compatible _Employee stub, and patch the analytics
	models module so HrFlightRiskScore writes to our test table.
	"""
	import sys
	import types
	import pgappforge.plugins.erp.hcm.analytics.models as anl_models

	# --- Patch personnel models to use SQLite stub ---
	_personnel_key = "pgappforge.plugins.erp.hcm.personnel.models"
	_orig_personnel = sys.modules.get(_personnel_key)
	_stub_personnel = types.ModuleType(_personnel_key)
	_stub_personnel.Employee = _Employee  # type: ignore[attr-defined]
	sys.modules[_personnel_key] = _stub_personnel

	# --- Patch analytics models so HrFlightRiskScore writes to our table ---
	_orig_flight = anl_models.HrFlightRiskScore
	anl_models.HrFlightRiskScore = _HrFlightRiskScore  # type: ignore[attr-defined]

	try:
		from pgappforge.plugins.erp.hcm.analytics.services import HrAnalyticsService
		score = HrAnalyticsService.compute_flight_risk("EMP001", TENANT, session)

		assert score.employee_id == "EMP001"
		assert score.tenant_id == TENANT
		assert score.risk_level in ("LOW", "MEDIUM", "HIGH", "CRITICAL")
		assert 0 <= score.score <= 100
		assert score.is_current is True
		assert isinstance(score.factors, list)
	finally:
		anl_models.HrFlightRiskScore = _orig_flight  # type: ignore[attr-defined]
		if _orig_personnel is None:
			sys.modules.pop(_personnel_key, None)
		else:
			sys.modules[_personnel_key] = _orig_personnel


def test_generate_snapshot(session):
	"""generate_snapshot persists an HrAnalyticsSnapshot with correct type.

	Uses HEADCOUNT type — which calls compute_headcount → queries Employee.
	Patch sys.modules for personnel + analytics model swaps for SQLite.
	"""
	import sys
	import types
	import pgappforge.plugins.erp.hcm.analytics.models as anl_models

	_personnel_key = "pgappforge.plugins.erp.hcm.personnel.models"
	_orig_personnel = sys.modules.get(_personnel_key)
	_stub_personnel = types.ModuleType(_personnel_key)
	_stub_personnel.Employee = _Employee  # type: ignore[attr-defined]
	sys.modules[_personnel_key] = _stub_personnel

	_orig_snapshot = anl_models.HrAnalyticsSnapshot
	_orig_flight = anl_models.HrFlightRiskScore
	anl_models.HrAnalyticsSnapshot = _HrAnalyticsSnapshot  # type: ignore[attr-defined]
	anl_models.HrFlightRiskScore = _HrFlightRiskScore  # type: ignore[attr-defined]

	try:
		from pgappforge.plugins.erp.hcm.analytics.services import HrAnalyticsService
		snapshot = HrAnalyticsService.generate_snapshot(
			TENANT, "HEADCOUNT", "2025-06", session
		)
		assert snapshot.snapshot_type == "HEADCOUNT"
		assert snapshot.period == "2025-06"
		assert snapshot.tenant_id == TENANT
		assert snapshot.id, "snapshot must have an id after flush"
		# data is a dict (the service assigns a dict; our test column stores it as-is)
		assert isinstance(snapshot.data, dict)
	finally:
		anl_models.HrAnalyticsSnapshot = _orig_snapshot  # type: ignore[attr-defined]
		anl_models.HrFlightRiskScore = _orig_flight  # type: ignore[attr-defined]
		if _orig_personnel is None:
			sys.modules.pop(_personnel_key, None)
		else:
			sys.modules[_personnel_key] = _orig_personnel


# ===========================================================================
# LUNCH
# ===========================================================================

def test_lunch_imports():
	from pgappforge.plugins.erp.hcm.lunch import (
		LunchPlugin,
		LunchService,
		LunchSupplier,
		LunchMenu,
		LunchOrder,
	)
	assert LunchPlugin.name == "lunch"
	assert LunchSupplier.__tablename__ == "lun_supplier"
	assert LunchMenu.__tablename__ == "lun_menu"
	assert LunchOrder.__tablename__ == "lun_order"
	svc = LunchService()
	assert callable(svc.publish_menu)
	assert callable(svc.place_order)


def test_lunch_order_flow(session):
	"""Full happy path: create supplier → menu → publish → place order.

	The LunchService imports LunchMenu/LunchOrder/LunchSubsidyPolicy at module
	load time, so patching the models module is too late.  Instead we patch the
	names directly on the already-imported services module.
	"""
	import pgappforge.plugins.erp.hcm.lunch.services as lun_svc_mod

	# Capture originals from the service module's own namespace
	_orig_svc = {
		"LunchMenu": lun_svc_mod.LunchMenu,
		"LunchOrder": lun_svc_mod.LunchOrder,
		"LunchSubsidyPolicy": lun_svc_mod.LunchSubsidyPolicy,
	}
	lun_svc_mod.LunchMenu = _LunchMenu  # type: ignore[attr-defined]
	lun_svc_mod.LunchOrder = _LunchOrder  # type: ignore[attr-defined]
	lun_svc_mod.LunchSubsidyPolicy = _LunchSubsidyPolicy  # type: ignore[attr-defined]

	try:
		from pgappforge.plugins.erp.hcm.lunch.services import LunchService

		svc = LunchService()

		# Supplier (inserted directly — not routed through service)
		supplier = _LunchSupplier(
			id=_uid(), tenant_id=TENANT, name="Test Caterers", is_active=True,
			delivery_days=[],
		)
		session.add(supplier)
		session.flush()

		# Menu with one available item
		menu_date = date.today()
		menu_items = [
			{"id": "i1", "name": "Rice", "price_cents": 500, "available": True}
		]
		menu = _LunchMenu(
			id=_uid(), tenant_id=TENANT, supplier_id=supplier.id,
			menu_date=menu_date, status="DRAFT", items=menu_items,
		)
		session.add(menu)
		session.flush()

		# Publish
		published = svc.publish_menu(menu.id, session)
		assert published.status == "PUBLISHED"

		# Place order — service resolves items from menu definition
		order = svc.place_order(
			"EMP001",
			menu.id,
			[{"item_id": "i1", "qty": 1, "unit_price_cents": 500}],
			session,
			tenant_id=TENANT,
		)

		assert order.status == "PLACED"
		assert order.subtotal_cents == 500
		assert order.employee_id == "EMP001"
		assert order.menu_id == menu.id
	finally:
		for k, v in _orig_svc.items():
			setattr(lun_svc_mod, k, v)


# ===========================================================================
# REFERRAL
# ===========================================================================

def test_referral_imports():
	from pgappforge.plugins.erp.hcm.referral import (
		ReferralPlugin,
		ReferralService,
		ReferralSubmission,
	)
	assert ReferralPlugin.name == "referral"
	assert ReferralSubmission.__tablename__ == "ref_submission"
	svc = ReferralService()
	assert callable(svc.submit_referral)
	assert callable(svc.get_referrer_stats)


def _patch_ref_svc():
	"""Return (svc_mod, orig_dict) with referral service model names swapped."""
	import pgappforge.plugins.erp.hcm.referral.services as svc_mod
	orig = {
		"ReferralProgram": svc_mod.ReferralProgram,
		"ReferralSubmission": svc_mod.ReferralSubmission,
		"ReferralReward": svc_mod.ReferralReward,
	}
	svc_mod.ReferralProgram = _ReferralProgram  # type: ignore[attr-defined]
	svc_mod.ReferralSubmission = _ReferralSubmission  # type: ignore[attr-defined]
	svc_mod.ReferralReward = _ReferralReward  # type: ignore[attr-defined]
	return svc_mod, orig


def _unpatch_ref_svc(svc_mod, orig):
	for k, v in orig.items():
		setattr(svc_mod, k, v)


def test_referral_submission(session):
	"""submit_referral creates a SUBMITTED submission for an ACTIVE program."""
	svc_mod, orig = _patch_ref_svc()
	try:
		from pgappforge.plugins.erp.hcm.referral.services import ReferralService

		svc = ReferralService()

		program = _ReferralProgram(
			id=_uid(),
			tenant_id=TENANT,
			name="Q2 2025 Referral Drive",
			status="ACTIVE",
			reward_amount_cents=50000,
			reward_type="CASH",
			reward_conditions={},
			eligible_positions=[],
			starts_at=date.today(),
		)
		session.add(program)
		session.flush()

		sub = svc.submit_referral(
			"EMP001",
			program.id,
			"John Doe",
			"john@example.com",
			TENANT,
			session,
		)

		assert sub.status == "SUBMITTED"
		assert sub.referrer_id == "EMP001"
		assert sub.candidate_name == "John Doe"
		assert sub.candidate_email == "john@example.com"
		assert sub.program_id == program.id
		assert sub.id, "submission must have an id after flush"
	finally:
		_unpatch_ref_svc(svc_mod, orig)


def test_referral_stats(session):
	"""get_referrer_stats returns a dict with a 'submissions' key."""
	from datetime import datetime, timezone

	svc_mod, orig = _patch_ref_svc()
	try:
		from pgappforge.plugins.erp.hcm.referral.services import ReferralService

		svc = ReferralService()

		program = _ReferralProgram(
			id=_uid(), tenant_id=TENANT, name="Stats Test Program",
			status="ACTIVE", reward_amount_cents=10000, reward_type="CASH",
			reward_conditions={}, eligible_positions=[],
			starts_at=date.today(),
		)
		session.add(program)
		session.flush()

		sub = _ReferralSubmission(
			id=_uid(), tenant_id=TENANT, referrer_id="EMP001",
			program_id=program.id, candidate_name="Jane Smith",
			candidate_email="jane@example.com", status="SUBMITTED",
			submitted_at=datetime.now(timezone.utc), reward_eligible=False,
		)
		session.add(sub)
		session.flush()

		stats = svc.get_referrer_stats("EMP001", TENANT, session)

		assert "submissions" in stats
		assert stats["submissions"] >= 1
		assert "hired" in stats
		assert "conversion_rate" in stats
		assert "rewards_paid_cents" in stats
	finally:
		_unpatch_ref_svc(svc_mod, orig)


# ===========================================================================
# WELLNESS
# ===========================================================================

def test_wellness_imports():
	from pgappforge.plugins.erp.hcm.wellness import (
		WellnessPlugin,
		WellnessService,
		WellnessCheckIn,
	)
	assert WellnessPlugin.name == "wellness"
	assert WellnessCheckIn.__tablename__ == "wel_checkin"
	svc = WellnessService()
	assert callable(svc.record_checkin)
	assert callable(svc.get_wellbeing_trend)


def _patch_wel_svc():
	"""Return (svc_mod, orig_dict) with wellness service model names swapped."""
	import pgappforge.plugins.erp.hcm.wellness.services as svc_mod
	orig = {
		"WellnessCheckIn": svc_mod.WellnessCheckIn,
		"WellnessEnrollment": svc_mod.WellnessEnrollment,
		"WellnessProgram": svc_mod.WellnessProgram,
		"EapReferral": svc_mod.EapReferral,
	}
	svc_mod.WellnessCheckIn = _WellnessCheckIn  # type: ignore[attr-defined]
	svc_mod.WellnessEnrollment = _WellnessEnrollment  # type: ignore[attr-defined]
	svc_mod.WellnessProgram = _WellnessProgram  # type: ignore[attr-defined]
	svc_mod.EapReferral = _EapReferral  # type: ignore[attr-defined]
	return svc_mod, orig


def _unpatch_wel_svc(svc_mod, orig):
	for k, v in orig.items():
		setattr(svc_mod, k, v)


def test_checkin_and_flags(session):
	"""record_checkin with score <= 3 sets BURNOUT_RISK flag."""
	svc_mod, orig = _patch_wel_svc()
	try:
		from pgappforge.plugins.erp.hcm.wellness.services import WellnessService

		svc = WellnessService()
		today = date.today()

		checkin = svc.record_checkin("EMP001", today, 2, TENANT, session)

		assert checkin.wellbeing_score == 2
		assert checkin.employee_id == "EMP001"
		assert isinstance(checkin.flags, list)
		assert "BURNOUT_RISK" in checkin.flags, (
			f"score=2 should trigger BURNOUT_RISK; got flags={checkin.flags}"
		)
	finally:
		_unpatch_wel_svc(svc_mod, orig)


def test_wellness_trend(session):
	"""get_wellbeing_trend returns a dict with 'trend' key after 3 check-ins."""
	svc_mod, orig = _patch_wel_svc()
	try:
		from pgappforge.plugins.erp.hcm.wellness.services import WellnessService

		svc = WellnessService()
		today = date.today()
		emp = "EMP_TREND"

		# Insert 3 check-ins directly (no upsert conflict since different days)
		for i, score in enumerate([5, 6, 7]):
			day = today - timedelta(days=6 - i)
			checkin = _WellnessCheckIn(
				id=_uid(), tenant_id=TENANT, employee_id=emp,
				check_in_date=day, wellbeing_score=score, flags=[],
				anonymous=False,
			)
			session.add(checkin)
		session.flush()

		result = svc.get_wellbeing_trend(
			emp,
			today - timedelta(days=7),
			today,
			TENANT,
			session,
		)

		assert "trend" in result
		assert result["trend"] in ("IMPROVING", "STABLE", "DECLINING")
		assert result["checkins_count"] == 3
		assert result["avg_wellbeing"] is not None
	finally:
		_unpatch_wel_svc(svc_mod, orig)
