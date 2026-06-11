"""
pgappforge/plugins/erp/industry/clubs/models.py

SQLAlchemy models for the Clubs & Membership plugin.

Design rules:
  - All PKs: UUID v4, server_default=gen_random_uuid()
  - All timestamps: TIMESTAMPTZ DEFAULT NOW()
  - All models: tenant_id UUID NOT NULL
  - Monetary amounts: INTEGER cents ONLY (never Decimal/float in storage)
  - JSONB for entitlements, emergency_contact, dietary_preferences, communication_preferences
  - ImmutableRecordMixin on ledger/audit records: MemberCharge, AccessEvent

Table name convention: club_<entity>
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any

import sqlalchemy as sa
from sqlalchemy import (
	Boolean,
	Column,
	Date,
	DateTime,
	ForeignKey,
	Index,
	Integer,
	String,
	Text,
	UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from pgappforge.models.sqla import Model
from pgappforge.plugins.audit import AuditMixin
from pgappforge.plugins.erp.foundation.commons import ImmutableRecordMixin


def _uuid4() -> str:
	return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

MEMBER_STATUS = ("PENDING", "ACTIVE", "SUSPENDED", "LAPSED", "RESIGNED")
APPLICATION_STATUS = ("PENDING", "APPROVED", "REJECTED", "WAITLISTED")
FACILITY_TYPE = ("COURT", "POOL", "GYM", "DINING", "FUNCTION_HALL", "LOCKER_ROOM", "SPA")
BOOKING_STATUS = ("CONFIRMED", "CANCELLED", "NO_SHOW", "COMPLETED")
CHARGE_TYPE = (
	"FACILITY_BOOKING", "FOOD_BEVERAGE", "PRO_SHOP", "GUEST_LEVY",
	"SUBSCRIPTION", "ANNUAL_FEE", "MISCELLANEOUS",
)
ACCESS_DIRECTION = ("IN", "OUT")
ACCESS_RESULT = ("GRANTED", "DENIED")
STATEMENT_STATUS = ("DRAFT", "SENT", "PAID", "OVERDUE")


# ---------------------------------------------------------------------------
# ClubMembershipType
# ---------------------------------------------------------------------------

class ClubMembershipType(AuditMixin, Model):
	"""Defines a membership tier (e.g. Full, Social, Junior, Corporate).

	entitlements JSONB: {guest_visits_per_day: 2, booking_advance_hours: 168,
	                      facilities: ["COURT","POOL"]}
	"""

	__allow_unmapped__ = True
	__tablename__ = "club_membership_type"
	__table_args__ = (
		UniqueConstraint("tenant_id", "code", name="uq_club_membership_type_tenant_code"),
		Index("ix_club_membership_type_tenant", "tenant_id"),
		Index("ix_club_membership_type_active", "is_active"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	name = Column(String(100), nullable=False, comment="Display name e.g. 'Full Member'")
	code = Column(String(20), nullable=False, comment="Short code e.g. 'FULL', 'SOCIAL'")

	# Fees — integer cents
	annual_fee_cents = Column(Integer, nullable=False, default=0, server_default="0", comment="Annual subscription fee in cents")
	joining_fee_cents = Column(Integer, nullable=False, default=0, server_default="0", comment="One-time joining fee in cents")
	monthly_fee_cents = Column(Integer, nullable=False, default=0, server_default="0", comment="Monthly subscription fee in cents (if billed monthly)")

	entitlements = Column(
		JSONB,
		nullable=False,
		default=dict,
		server_default="{}",
		comment="{guest_visits_per_day: 2, booking_advance_hours: 168, facilities: []}",
	)
	is_active = Column(Boolean, nullable=False, default=True, server_default="true")

	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	updated_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		onupdate=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	members: list[ClubMember] = relationship(
		"ClubMember",
		back_populates="member_type",
		lazy="select",
	)
	applications: list[MembershipApplication] = relationship(
		"MembershipApplication",
		back_populates="member_type",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<ClubMembershipType code={self.code!r} name={self.name!r} "
			f"annual={self.annual_fee_cents}¢>"
		)


# ---------------------------------------------------------------------------
# ClubMember
# ---------------------------------------------------------------------------

class ClubMember(AuditMixin, Model):
	"""A registered member of the club.

	proposer_member_id / seconder_member_id are soft self-FKs (no FK constraint
	to allow flexible seeding; referential integrity enforced at service layer).
	customer_id is a soft FK to foundation.Party / CRM Customer.
	emergency_contact JSONB: {name, phone, relationship}
	dietary_preferences JSONB: ["VEGETARIAN","HALAL"]
	communication_preferences JSONB: {email: true, sms: true, whatsapp: false}
	"""

	__allow_unmapped__ = True
	__tablename__ = "club_member"
	__table_args__ = (
		UniqueConstraint("tenant_id", "membership_number", name="uq_club_member_tenant_number"),
		Index("ix_club_member_tenant", "tenant_id"),
		Index("ix_club_member_type", "member_type_id"),
		Index("ix_club_member_status", "status"),
		Index("ix_club_member_customer", "customer_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	membership_number = Column(String(20), nullable=False, comment="Human-readable ID e.g. M-00142")
	member_type_id = Column(
		UUID(as_uuid=False),
		ForeignKey("club_membership_type.id", ondelete="RESTRICT"),
		nullable=False,
		index=True,
	)

	# Soft FK to foundation.Party / CRM Customer
	customer_id = Column(UUID(as_uuid=False), nullable=True, index=True, comment="Soft FK to foundation.Party / CRM Customer")

	full_name = Column(String(200), nullable=False)
	email = Column(String(200), nullable=True)
	phone = Column(String(30), nullable=True)

	joined_date = Column(Date, nullable=True)
	resigned_date = Column(Date, nullable=True)

	status = Column(
		String(15),
		nullable=False,
		default="PENDING",
		server_default="PENDING",
		comment="PENDING/ACTIVE/SUSPENDED/LAPSED/RESIGNED",
	)
	suspension_reason = Column(String(200), nullable=True)

	# Soft self-FKs (no FK constraint; service layer enforces referential integrity)
	proposer_member_id = Column(UUID(as_uuid=False), nullable=True, comment="Soft FK to club_member.id — proposer")
	seconder_member_id = Column(UUID(as_uuid=False), nullable=True, comment="Soft FK to club_member.id — seconder")

	emergency_contact = Column(
		JSONB,
		nullable=False,
		default=dict,
		server_default="{}",
		comment="{name, phone, relationship}",
	)
	dietary_preferences = Column(
		JSONB,
		nullable=False,
		default=list,
		server_default="[]",
		comment='["VEGETARIAN","HALAL",...]',
	)
	communication_preferences = Column(
		JSONB,
		nullable=False,
		default=dict,
		server_default="{}",
		comment="{email: true, sms: true, whatsapp: false}",
	)
	photo_url = Column(String(500), nullable=True)

	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	updated_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		onupdate=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	member_type: ClubMembershipType = relationship("ClubMembershipType", back_populates="members", lazy="select")
	account: MemberAccount = relationship(
		"MemberAccount",
		back_populates="member",
		uselist=False,
		lazy="select",
	)
	bookings: list[FacilityBooking] = relationship(
		"FacilityBooking",
		back_populates="member",
		lazy="select",
	)
	charges: list[MemberCharge] = relationship(
		"MemberCharge",
		back_populates="member",
		lazy="select",
	)
	guest_visits: list[GuestVisit] = relationship(
		"GuestVisit",
		back_populates="member",
		lazy="select",
	)
	access_events: list[AccessEvent] = relationship(
		"AccessEvent",
		back_populates="member",
		lazy="select",
	)
	statements: list[MemberStatement] = relationship(
		"MemberStatement",
		back_populates="member",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<ClubMember number={self.membership_number!r} "
			f"name={self.full_name!r} status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# MembershipApplication
# ---------------------------------------------------------------------------

class MembershipApplication(AuditMixin, Model):
	"""Membership application — tracks the approval workflow.

	resulting_member_id is set when the application is APPROVED and a
	ClubMember record has been created.
	"""

	__allow_unmapped__ = True
	__tablename__ = "club_membership_application"
	__table_args__ = (
		Index("ix_club_application_tenant", "tenant_id"),
		Index("ix_club_application_status", "status"),
		Index("ix_club_application_member_type", "member_type_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	applicant_name = Column(String(200), nullable=False)
	applicant_email = Column(String(200), nullable=True)
	applicant_phone = Column(String(30), nullable=True)

	member_type_id = Column(
		UUID(as_uuid=False),
		ForeignKey("club_membership_type.id", ondelete="RESTRICT"),
		nullable=False,
		index=True,
	)

	# Soft self-FKs
	proposer_member_id = Column(UUID(as_uuid=False), nullable=True, comment="Soft FK to club_member.id")
	seconder_member_id = Column(UUID(as_uuid=False), nullable=True, comment="Soft FK to club_member.id")

	status = Column(
		String(15),
		nullable=False,
		default="PENDING",
		server_default="PENDING",
		comment="PENDING/APPROVED/REJECTED/WAITLISTED",
	)

	applied_at = Column(DateTime(timezone=True), nullable=False)
	decided_at = Column(DateTime(timezone=True), nullable=True)
	decided_by = Column(UUID(as_uuid=False), nullable=True, comment="User/admin who decided")

	resulting_member_id = Column(
		UUID(as_uuid=False),
		ForeignKey("club_member.id", ondelete="SET NULL"),
		nullable=True,
		index=True,
		comment="Set when APPROVED — references the created ClubMember",
	)

	notes = Column(Text, nullable=True)

	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	updated_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		onupdate=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	member_type: ClubMembershipType = relationship("ClubMembershipType", back_populates="applications", lazy="select")

	def __repr__(self) -> str:
		return (
			f"<MembershipApplication applicant={self.applicant_name!r} "
			f"status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# Facility
# ---------------------------------------------------------------------------

class Facility(AuditMixin, Model):
	"""A bookable club facility (court, pool, gym, dining room, etc.).

	hourly_rate_cents = 0 means included in membership — no charge on booking.
	open_time / close_time stored as HH:MM strings for simplicity; service layer
	validates and converts for scheduling logic.
	"""

	__allow_unmapped__ = True
	__tablename__ = "club_facility"
	__table_args__ = (
		UniqueConstraint("tenant_id", "code", name="uq_club_facility_tenant_code"),
		Index("ix_club_facility_tenant", "tenant_id"),
		Index("ix_club_facility_type", "facility_type"),
		Index("ix_club_facility_active", "is_active"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	name = Column(String(100), nullable=False)
	code = Column(String(20), nullable=False, comment="Unique short code e.g. POOL_MAIN, COURT_1")
	facility_type = Column(
		String(20),
		nullable=False,
		comment="COURT/POOL/GYM/DINING/FUNCTION_HALL/LOCKER_ROOM/SPA",
	)

	capacity = Column(Integer, nullable=False, default=1, server_default="1", comment="Max concurrent bookings / persons")
	location = Column(String(200), nullable=True)

	is_members_only = Column(Boolean, nullable=False, default=True, server_default="true")
	guest_allowed = Column(Boolean, nullable=False, default=True, server_default="true")
	max_guests_per_booking = Column(Integer, nullable=False, default=3, server_default="3")

	# Pricing — integer cents; 0 = included in membership
	hourly_rate_cents = Column(Integer, nullable=False, default=0, server_default="0", comment="0 = included in membership")

	booking_advance_hours = Column(Integer, nullable=False, default=168, server_default="168", comment="How far ahead members can book (168 = 1 week)")
	max_consecutive_hours = Column(Integer, nullable=False, default=2, server_default="2")

	open_time = Column(String(5), nullable=False, default="06:00", server_default="'06:00'", comment="HH:MM opening time")
	close_time = Column(String(5), nullable=False, default="22:00", server_default="'22:00'", comment="HH:MM closing time")

	is_active = Column(Boolean, nullable=False, default=True, server_default="true")

	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	updated_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		onupdate=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	bookings: list[FacilityBooking] = relationship(
		"FacilityBooking",
		back_populates="facility",
		lazy="select",
	)
	guest_visits: list[GuestVisit] = relationship(
		"GuestVisit",
		back_populates="facility",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<Facility code={self.code!r} type={self.facility_type!r} "
			f"capacity={self.capacity} active={self.is_active}>"
		)


# ---------------------------------------------------------------------------
# FacilityBooking
# ---------------------------------------------------------------------------

class FacilityBooking(AuditMixin, Model):
	"""A member's reservation of a club facility for a given date/time slot.

	booking_ref is globally unique (generated at service layer, e.g. BK-00042).
	Index on (tenant_id, facility_id, booking_date) accelerates availability queries.
	"""

	__allow_unmapped__ = True
	__tablename__ = "club_facility_booking"
	__table_args__ = (
		Index("ix_club_booking_availability", "tenant_id", "facility_id", "booking_date"),
		Index("ix_club_booking_member", "member_id"),
		Index("ix_club_booking_status", "status"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	facility_id = Column(
		UUID(as_uuid=False),
		ForeignKey("club_facility.id", ondelete="RESTRICT"),
		nullable=False,
		index=True,
	)
	member_id = Column(
		UUID(as_uuid=False),
		ForeignKey("club_member.id", ondelete="RESTRICT"),
		nullable=False,
		index=True,
	)

	booking_ref = Column(String(20), nullable=False, unique=True, comment="Human-readable booking reference e.g. BK-00042")
	booking_date = Column(Date, nullable=False)
	start_time = Column(String(5), nullable=False, comment="HH:MM slot start")
	end_time = Column(String(5), nullable=False, comment="HH:MM slot end")
	duration_minutes = Column(Integer, nullable=False)

	guest_count = Column(Integer, nullable=False, default=0, server_default="0")
	total_fee_cents = Column(Integer, nullable=False, default=0, server_default="0", comment="Total booking fee in cents; 0 if included in membership")

	status = Column(
		String(12),
		nullable=False,
		default="CONFIRMED",
		server_default="CONFIRMED",
		comment="CONFIRMED/CANCELLED/NO_SHOW/COMPLETED",
	)
	cancellation_reason = Column(String(200), nullable=True)
	notes = Column(Text, nullable=True)

	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	updated_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		onupdate=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	facility: Facility = relationship("Facility", back_populates="bookings", lazy="select")
	member: ClubMember = relationship("ClubMember", back_populates="bookings", lazy="select")

	def __repr__(self) -> str:
		return (
			f"<FacilityBooking ref={self.booking_ref!r} date={self.booking_date} "
			f"status={self.status!r} fee={self.total_fee_cents}¢>"
		)


# ---------------------------------------------------------------------------
# MemberAccount
# ---------------------------------------------------------------------------

class MemberAccount(AuditMixin, Model):
	"""Club charge account for a member — tracks running balance and billing settings.

	current_balance_cents > 0 means the member owes the club.
	credit_limit_cents = 0 means no credit facility extended.
	"""

	__allow_unmapped__ = True
	__tablename__ = "club_member_account"
	__table_args__ = (
		Index("ix_club_member_account_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	member_id = Column(
		UUID(as_uuid=False),
		ForeignKey("club_member.id", ondelete="RESTRICT"),
		nullable=False,
		unique=True,
		index=True,
	)

	credit_limit_cents = Column(Integer, nullable=False, default=0, server_default="0", comment="0 = no credit facility")
	current_balance_cents = Column(Integer, nullable=False, default=0, server_default="0", comment="Positive = member owes club")
	statement_day_of_month = Column(Integer, nullable=False, default=1, server_default="1", comment="Day of month for monthly statement generation")
	auto_debit = Column(Boolean, nullable=False, default=False, server_default="false")
	payment_method_ref = Column(String(100), nullable=True, comment="Opaque reference to payments module record")
	last_statement_date = Column(Date, nullable=True)

	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	updated_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		onupdate=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	member: ClubMember = relationship("ClubMember", back_populates="account", lazy="select")
	charges: list[MemberCharge] = relationship(
		"MemberCharge",
		back_populates="account",
		lazy="select",
	)
	statements: list[MemberStatement] = relationship(
		"MemberStatement",
		back_populates="member",
		lazy="select",
		primaryjoin="MemberAccount.member_id == MemberStatement.member_id",
		foreign_keys="MemberStatement.member_id",
		viewonly=True,
	)

	def __repr__(self) -> str:
		return (
			f"<MemberAccount member={self.member_id!r} "
			f"balance={self.current_balance_cents}¢>"
		)


# ---------------------------------------------------------------------------
# MemberCharge
# ---------------------------------------------------------------------------

class MemberCharge(ImmutableRecordMixin, Model):
	"""Immutable ledger entry for a charge posted to a member's account.

	reference_id / reference_type point to the originating business record
	(e.g. a FacilityBooking.id with reference_type="FacilityBooking").
	Once inserted this record MUST NOT be updated — raise a reversal entry.
	"""

	__allow_unmapped__ = True
	__tablename__ = "club_member_charge"
	__table_args__ = (
		Index("ix_club_charge_member", "member_id"),
		Index("ix_club_charge_account", "account_id"),
		Index("ix_club_charge_type", "charge_type"),
		Index("ix_club_charge_charged_at", "charged_at"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	member_id = Column(
		UUID(as_uuid=False),
		ForeignKey("club_member.id", ondelete="RESTRICT"),
		nullable=False,
		index=True,
	)
	account_id = Column(
		UUID(as_uuid=False),
		ForeignKey("club_member_account.id", ondelete="RESTRICT"),
		nullable=False,
		index=True,
	)

	charge_type = Column(
		String(25),
		nullable=False,
		comment="FACILITY_BOOKING/FOOD_BEVERAGE/PRO_SHOP/GUEST_LEVY/SUBSCRIPTION/ANNUAL_FEE/MISCELLANEOUS",
	)
	description = Column(String(300), nullable=False)
	amount_cents = Column(Integer, nullable=False, comment="Charge amount in cents; positive = debit")

	# Source record reference (polymorphic soft FK)
	reference_id = Column(String(100), nullable=True, comment="ID of source record (booking, etc.)")
	reference_type = Column(String(50), nullable=True, comment="Type of source record e.g. FacilityBooking")

	charged_at = Column(DateTime(timezone=True), nullable=False)

	# No created_at / updated_at — ImmutableRecordMixin insert-only records use charged_at

	member: ClubMember = relationship("ClubMember", back_populates="charges", lazy="select")
	account: MemberAccount = relationship("MemberAccount", back_populates="charges", lazy="select")

	def __repr__(self) -> str:
		return (
			f"<MemberCharge member={self.member_id!r} "
			f"type={self.charge_type!r} amount={self.amount_cents}¢>"
		)


# Register immutability guard — must be called after class body is complete
MemberCharge._register_immutability()


# ---------------------------------------------------------------------------
# GuestVisit
# ---------------------------------------------------------------------------

class GuestVisit(AuditMixin, Model):
	"""Log of a non-member guest brought in by a member.

	charge_id is a soft FK to MemberCharge.id (no FK constraint to allow
	deferred charging patterns).
	"""

	__allow_unmapped__ = True
	__tablename__ = "club_guest_visit"
	__table_args__ = (
		Index("ix_club_guest_member", "member_id"),
		Index("ix_club_guest_visit_date", "visit_date"),
		Index("ix_club_guest_facility", "facility_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	member_id = Column(
		UUID(as_uuid=False),
		ForeignKey("club_member.id", ondelete="RESTRICT"),
		nullable=False,
		index=True,
	)

	guest_name = Column(String(200), nullable=False)
	guest_phone = Column(String(30), nullable=True)
	visit_date = Column(Date, nullable=False)

	facility_id = Column(
		UUID(as_uuid=False),
		ForeignKey("club_facility.id", ondelete="SET NULL"),
		nullable=True,
		index=True,
	)
	purpose = Column(String(200), nullable=True)

	levy_cents = Column(Integer, nullable=False, default=0, server_default="0", comment="Guest levy charged in cents")
	charged_to_account = Column(Boolean, nullable=False, default=True, server_default="true")

	# Soft FK to club_member_charge.id (deferred; no FK constraint)
	charge_id = Column(UUID(as_uuid=False), nullable=True, comment="Soft FK to club_member_charge.id")

	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	updated_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		onupdate=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	member: ClubMember = relationship("ClubMember", back_populates="guest_visits", lazy="select")
	facility: Facility = relationship("Facility", back_populates="guest_visits", lazy="select")

	def __repr__(self) -> str:
		return (
			f"<GuestVisit member={self.member_id!r} guest={self.guest_name!r} "
			f"date={self.visit_date} levy={self.levy_cents}¢>"
		)


# ---------------------------------------------------------------------------
# AccessEvent
# ---------------------------------------------------------------------------

class AccessEvent(ImmutableRecordMixin, Model):
	"""Immutable access control event emitted by door/gate controllers.

	Insert-only — never update. Append reversal/correction events if needed.
	device_id identifies the physical controller (asset tag).
	door_id is the logical identifier used in access rules (e.g. MAIN_GATE).
	"""

	__allow_unmapped__ = True
	__tablename__ = "club_access_event"
	__table_args__ = (
		Index("ix_club_access_member", "member_id"),
		Index("ix_club_access_occurred_at", "occurred_at"),
		Index("ix_club_access_door", "door_id"),
		Index("ix_club_access_result", "access_result"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	member_id = Column(
		UUID(as_uuid=False),
		ForeignKey("club_member.id", ondelete="RESTRICT"),
		nullable=False,
		index=True,
	)

	door_id = Column(String(50), nullable=False, comment="Logical door code e.g. MAIN_GATE, POOL_ENTRY")
	door_name = Column(String(100), nullable=False)
	direction = Column(String(3), nullable=False, comment="IN/OUT")
	access_result = Column(String(7), nullable=False, comment="GRANTED/DENIED")
	denial_reason = Column(String(100), nullable=True, comment="SUSPENDED/LAPSED/UNKNOWN_MEMBER etc.")
	device_id = Column(String(50), nullable=True, comment="Physical controller asset tag")
	occurred_at = Column(DateTime(timezone=True), nullable=False)

	member: ClubMember = relationship("ClubMember", back_populates="access_events", lazy="select")

	def __repr__(self) -> str:
		return (
			f"<AccessEvent member={self.member_id!r} door={self.door_id!r} "
			f"direction={self.direction!r} result={self.access_result!r}>"
		)


# Register immutability guard — must be called after class body is complete
AccessEvent._register_immutability()


# ---------------------------------------------------------------------------
# MemberStatement
# ---------------------------------------------------------------------------

class MemberStatement(AuditMixin, Model):
	"""Monthly billing statement snapshot for a member's account.

	closing_balance_cents = opening_balance_cents + charges_cents - payments_cents
	UniqueConstraint ensures exactly one statement per member per period.
	"""

	__allow_unmapped__ = True
	__tablename__ = "club_member_statement"
	__table_args__ = (
		UniqueConstraint(
			"tenant_id", "member_id", "statement_date",
			name="uq_club_statement_tenant_member_date",
		),
		Index("ix_club_statement_member", "member_id"),
		Index("ix_club_statement_date", "statement_date"),
		Index("ix_club_statement_status", "status"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	member_id = Column(
		UUID(as_uuid=False),
		ForeignKey("club_member.id", ondelete="RESTRICT"),
		nullable=False,
		index=True,
	)

	statement_date = Column(Date, nullable=False)
	opening_balance_cents = Column(Integer, nullable=False, comment="Balance at start of period in cents")
	charges_cents = Column(Integer, nullable=False, comment="Total charges in period in cents")
	payments_cents = Column(Integer, nullable=False, comment="Total payments received in period in cents")
	closing_balance_cents = Column(Integer, nullable=False, comment="Balance at end of period in cents")

	status = Column(
		String(10),
		nullable=False,
		default="DRAFT",
		server_default="DRAFT",
		comment="DRAFT/SENT/PAID/OVERDUE",
	)

	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	updated_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		onupdate=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	member: ClubMember = relationship("ClubMember", back_populates="statements", lazy="select")

	def __repr__(self) -> str:
		return (
			f"<MemberStatement member={self.member_id!r} date={self.statement_date} "
			f"closing={self.closing_balance_cents}¢ status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"ClubMembershipType",
	"ClubMember",
	"MembershipApplication",
	"Facility",
	"FacilityBooking",
	"MemberAccount",
	"MemberCharge",
	"GuestVisit",
	"AccessEvent",
	"MemberStatement",
]
