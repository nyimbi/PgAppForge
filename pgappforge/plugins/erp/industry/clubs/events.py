"""
pgappforge/plugins/erp/industry/clubs/events.py

Domain events for the Clubs & Membership plugin.

All events subclass DomainEvent from pgappforge.plugins.erp.foundation.events.
Emit via emit_event(event_instance, session) — the INSERT into DomainEventLog
is atomic with the business transaction that triggered it.

Usage
-----
    from pgappforge.plugins.erp.industry.clubs.events import (
        MemberApprovedEvent, emit_event,
    )

    emit_event(MemberApprovedEvent(
        aggregate_id=member.id,
        aggregate_type="ClubMember",
        tenant_id=member.tenant_id,
        member_id=member.id,
        membership_number=member.membership_number,
        member_type_id=member.member_type_id,
    ), session)
"""
from __future__ import annotations

from dataclasses import dataclass

from pgappforge.plugins.erp.foundation.events import DomainEvent, emit_event, subscribe, unsubscribe


# ---------------------------------------------------------------------------
# Membership lifecycle events
# ---------------------------------------------------------------------------

@dataclass
class MemberApplicationSubmittedEvent(DomainEvent):
	"""Fired when a new membership application is submitted."""
	event_type: str = "club.application.submitted"
	application_id: str = ""
	applicant_name: str = ""
	member_type_id: str = ""


@dataclass
class MemberApprovedEvent(DomainEvent):
	"""Fired when an application is approved and a member record is created."""
	event_type: str = "club.member.approved"
	member_id: str = ""
	membership_number: str = ""
	member_type_id: str = ""


@dataclass
class MemberSuspendedEvent(DomainEvent):
	"""Fired when a member's status is set to SUSPENDED."""
	event_type: str = "club.member.suspended"
	member_id: str = ""
	reason: str = ""


@dataclass
class MemberResignedEvent(DomainEvent):
	"""Fired when a member formally resigns."""
	event_type: str = "club.member.resigned"
	member_id: str = ""


# ---------------------------------------------------------------------------
# Facility booking events
# ---------------------------------------------------------------------------

@dataclass
class FacilityBookedEvent(DomainEvent):
	"""Fired when a facility booking is confirmed."""
	event_type: str = "club.facility.booked"
	booking_id: str = ""
	facility_id: str = ""
	member_id: str = ""
	booking_date: str = ""  # ISO date string YYYY-MM-DD


@dataclass
class BookingCancelledEvent(DomainEvent):
	"""Fired when a confirmed booking is cancelled."""
	event_type: str = "club.booking.cancelled"
	booking_id: str = ""
	facility_id: str = ""
	member_id: str = ""


# ---------------------------------------------------------------------------
# Billing events
# ---------------------------------------------------------------------------

@dataclass
class MemberChargedEvent(DomainEvent):
	"""Fired when a charge is posted to a member's account."""
	event_type: str = "club.member.charged"
	member_id: str = ""
	amount_cents: int = 0
	charge_type: str = ""  # FACILITY_BOOKING/FOOD_BEVERAGE/etc.


# ---------------------------------------------------------------------------
# Guest events
# ---------------------------------------------------------------------------

@dataclass
class GuestVisitLoggedEvent(DomainEvent):
	"""Fired when a guest visit is recorded against a member."""
	event_type: str = "club.guest.visited"
	member_id: str = ""
	guest_name: str = ""
	visit_date: str = ""  # ISO date string YYYY-MM-DD


# ---------------------------------------------------------------------------
# Access control events
# ---------------------------------------------------------------------------

@dataclass
class AccessGrantedEvent(DomainEvent):
	"""Fired when a member is granted access through a controlled door/gate."""
	event_type: str = "club.access.granted"
	member_id: str = ""
	door_id: str = ""


@dataclass
class AccessDeniedEvent(DomainEvent):
	"""Fired when a member is denied access — includes denial reason."""
	event_type: str = "club.access.denied"
	member_id: str = ""
	door_id: str = ""
	reason: str = ""  # SUSPENDED/LAPSED/UNKNOWN_MEMBER etc.


# ---------------------------------------------------------------------------
# Statement events
# ---------------------------------------------------------------------------

@dataclass
class StatementGeneratedEvent(DomainEvent):
	"""Fired when a monthly member statement is generated."""
	event_type: str = "club.statement.generated"
	member_id: str = ""
	statement_date: str = ""  # ISO date string YYYY-MM-DD
	closing_balance_cents: int = 0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	# Re-exports for convenience — callers only need to import from this module
	"DomainEvent",
	"emit_event",
	"subscribe",
	"unsubscribe",
	# Clubs events
	"MemberApplicationSubmittedEvent",
	"MemberApprovedEvent",
	"MemberSuspendedEvent",
	"MemberResignedEvent",
	"FacilityBookedEvent",
	"BookingCancelledEvent",
	"MemberChargedEvent",
	"GuestVisitLoggedEvent",
	"AccessGrantedEvent",
	"AccessDeniedEvent",
	"StatementGeneratedEvent",
]
