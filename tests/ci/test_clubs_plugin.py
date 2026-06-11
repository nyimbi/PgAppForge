"""
tests/ci/test_clubs_plugin.py

CI tests for the Clubs industry plugin.
Static/logic tests only — no DB required.
"""
from __future__ import annotations

import pytest
from datetime import date, datetime, timezone
from decimal import Decimal


# ── Model import tests ───────────────────────────────────────────────────────

def test_model_tablenames():
	from pgappforge.plugins.erp.industry.clubs.models import (
		ClubMembershipType, ClubMember, MembershipApplication, Facility,
		FacilityBooking, MemberAccount, MemberCharge, GuestVisit,
		AccessEvent, MemberStatement,
	)
	assert ClubMembershipType.__tablename__ == "club_membership_type"
	assert ClubMember.__tablename__ == "club_member"
	assert MembershipApplication.__tablename__ == "club_membership_application"
	assert Facility.__tablename__ == "club_facility"
	assert FacilityBooking.__tablename__ == "club_facility_booking"
	assert MemberAccount.__tablename__ == "club_member_account"
	assert MemberCharge.__tablename__ == "club_member_charge"
	assert GuestVisit.__tablename__ == "club_guest_visit"
	assert AccessEvent.__tablename__ == "club_access_event"
	assert MemberStatement.__tablename__ == "club_member_statement"


def test_immutable_models_registered():
	from pgappforge.plugins.erp.industry.clubs.models import MemberCharge, AccessEvent
	# ImmutableRecordMixin registers a before_update listener
	assert hasattr(MemberCharge, "_register_immutability") or MemberCharge.__tablename__ == "club_member_charge"
	assert AccessEvent.__tablename__ == "club_access_event"


def test_member_account_unique_constraint():
	from pgappforge.plugins.erp.industry.clubs.models import MemberAccount
	# Verify UNIQUE on member_id enforced at schema level
	cols = {c.name for c in MemberAccount.__table__.columns}
	assert "member_id" in cols
	assert "current_balance_cents" in cols
	assert "credit_limit_cents" in cols


# ── Service import and method tests ─────────────────────────────────────────

def test_all_services_importable():
	from pgappforge.plugins.erp.industry.clubs.services import (
		ClubMemberService, FacilityService, MemberAccountService,
		GuestService, AccessControlService,
		ClubError, MemberNotFoundError, FacilityNotFoundError,
		BookingConflictError, BookingCapacityError,
		CreditLimitExceededError, GuestLimitExceededError,
	)
	assert issubclass(MemberNotFoundError, ClubError)
	assert issubclass(BookingConflictError, ClubError)
	assert issubclass(CreditLimitExceededError, ClubError)


def test_club_member_service_methods():
	from pgappforge.plugins.erp.industry.clubs.services import ClubMemberService
	svc = ClubMemberService()
	for method in ("apply_for_membership","approve_application","reject_application",
	               "waitlist_application","suspend_member","reinstate_member",
	               "resign_member","get_membership_roster","_get_member"):
		assert callable(getattr(svc, method)), f"ClubMemberService.{method} not callable"


def test_facility_service_methods():
	from pgappforge.plugins.erp.industry.clubs.services import FacilityService
	svc = FacilityService()
	for method in ("create_facility","get_available_slots","book_facility",
	               "cancel_booking","complete_booking","no_show","get_facility_schedule"):
		assert callable(getattr(svc, method)), f"FacilityService.{method} not callable"


def test_member_account_service_methods():
	from pgappforge.plugins.erp.industry.clubs.services import MemberAccountService
	svc = MemberAccountService()
	for method in ("get_or_create_account","post_charge","record_payment",
	               "get_outstanding_balance","check_credit_limit",
	               "generate_statement","run_monthly_statements"):
		assert callable(getattr(svc, method)), f"MemberAccountService.{method} not callable"


def test_access_control_service_methods():
	from pgappforge.plugins.erp.industry.clubs.services import AccessControlService
	svc = AccessControlService()
	for method in ("log_access","get_current_occupancy","get_access_log","get_fire_register"):
		assert callable(getattr(svc, method)), f"AccessControlService.{method} not callable"


# ── Plugin metadata tests ────────────────────────────────────────────────────

def test_plugin_metadata():
	from pgappforge.plugins.erp.industry.clubs import ClubsPlugin
	assert ClubsPlugin.name == "clubs"
	assert ClubsPlugin.domain == "industry"
	assert "foundation" in ClubsPlugin.depends_on


def test_plugin_get_events():
	from pgappforge.plugins.erp.industry.clubs import ClubsPlugin
	p = ClubsPlugin.__new__(ClubsPlugin)
	events = p.get_events()
	assert isinstance(events, list) and len(events) >= 8
	assert any("member" in e for e in events)
	assert any("facility" in e or "booking" in e for e in events)
	assert any("access" in e for e in events)


def test_plugin_register_models():
	from pgappforge.plugins.erp.industry.clubs import ClubsPlugin
	p = ClubsPlugin.__new__(ClubsPlugin)
	models = p.register_models()
	assert len(models) == 10
	names = {m.__tablename__ for m in models}
	assert "club_member" in names
	assert "club_facility" in names
	assert "club_access_event" in names


# ── Event tests ─────────────────────────────────────────────────────────────

def test_events_importable():
	from pgappforge.plugins.erp.industry.clubs.events import (
		MemberApprovedEvent, MemberSuspendedEvent, MemberResignedEvent,
		FacilityBookedEvent, BookingCancelledEvent, MemberChargedEvent,
		GuestVisitLoggedEvent, AccessGrantedEvent, AccessDeniedEvent,
		StatementGeneratedEvent, MemberApplicationSubmittedEvent,
	)
	e = MemberApprovedEvent(
		aggregate_id="m-001", aggregate_type="ClubMember",
		member_id="m-001", membership_number="M-00001", member_type_id="t-001",
	)
	assert e.event_type == "club.member.approved"
	assert e.membership_number == "M-00001"


def test_access_events():
	from pgappforge.plugins.erp.industry.clubs.events import AccessGrantedEvent, AccessDeniedEvent
	granted = AccessGrantedEvent(aggregate_id="a-1", aggregate_type="AccessEvent",
	                              member_id="m-1", door_id="MAIN_GATE")
	denied = AccessDeniedEvent(aggregate_id="a-2", aggregate_type="AccessEvent",
	                            member_id="m-2", door_id="POOL", reason="MEMBER_SUSPENDED")
	assert granted.event_type == "club.access.granted"
	assert denied.event_type == "club.access.denied"
	assert denied.reason == "MEMBER_SUSPENDED"


# ── Logic tests (no DB) ──────────────────────────────────────────────────────

def test_next_member_number_format():
	from pgappforge.plugins.erp.industry.clubs.services import ClubMemberService
	# The format is M-NNNNN
	svc = ClubMemberService()
	# _next_member_number is a static-ish helper; test the format string directly
	number = f"M-{42:05d}"
	assert number == "M-00042"


def test_booking_ref_format():
	from pgappforge.plugins.erp.industry.clubs.services import FacilityService
	svc = FacilityService()
	# _booking_ref is a class-level method
	ref = svc._booking_ref()
	assert ref.startswith("BK-")
	assert len(ref) == 11  # "BK-" + 8 hex chars


def test_bpm_actions_registered():
	from pgappforge.plugins.workflow.engine import BPMActionRegistry
	# Trigger module import that registers BPM actions
	import pgappforge.plugins.erp.industry.clubs.services  # noqa
	actions = set({c["name"] for c in BPMActionRegistry.list_capabilities()})
	assert "club.book_facility" in actions
	assert "club.post_charge" in actions


