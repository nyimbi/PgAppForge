"""
pgappforge/plugins/erp/industry/clubs/services.py

Business logic for the Clubs & Membership plugin.

Five service classes:
  ClubMemberService    — member lifecycle (applications, suspensions, resignations)
  FacilityService      — facility management and booking
  MemberAccountService — charge posting, payments, statements
  GuestService         — guest visit logging and levy charging
  AccessControlService — door/gate access events and occupancy

All methods accept an explicit `session` parameter.
Callers own transaction boundaries — services only flush.
Monetary values are always integer cents.
"""
from __future__ import annotations

import logging
import secrets
from datetime import date, datetime, timezone
from typing import Any

import sqlalchemy as sa
from sqlalchemy import func, select

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _emit(event: Any, session: Any = None) -> None:
	"""Fire-and-forget event emit — non-fatal on failure."""
	try:
		from pgappforge.plugins.erp.industry.clubs.events import emit_event
		emit_event(event, session)
	except Exception:
		log.warning("_emit: event dispatch failed (non-fatal)", exc_info=True)


def _uuid4() -> str:
	import uuid
	return str(uuid.uuid4())


def _now() -> datetime:
	return datetime.now(timezone.utc)


def _today() -> date:
	return date.today()


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class ClubError(Exception):
	"""Base exception for all clubs service errors."""


class MemberNotFoundError(ClubError):
	pass


class FacilityNotFoundError(ClubError):
	pass


class BookingConflictError(ClubError):
	pass


class BookingCapacityError(ClubError):
	pass


class CreditLimitExceededError(ClubError):
	pass


class GuestLimitExceededError(ClubError):
	pass


# ---------------------------------------------------------------------------
# CLASS 1 — ClubMemberService
# ---------------------------------------------------------------------------

class ClubMemberService:
	"""Member lifecycle: applications, suspensions, roster."""

	@staticmethod
	def _next_member_number(tenant_id: str, session: Any) -> str:
		from pgappforge.plugins.erp.industry.clubs.models import ClubMember
		count = (
			session.execute(
				select(func.count(ClubMember.id)).where(ClubMember.tenant_id == tenant_id)
			).scalar_one()
			or 0
		)
		return f"M-{count + 1:05d}"

	def _get_member(self, member_id: str, tenant_id: str, session: Any) -> Any:
		from pgappforge.plugins.erp.industry.clubs.models import ClubMember
		member = session.execute(
			select(ClubMember).where(
				ClubMember.id == member_id,
				ClubMember.tenant_id == tenant_id,
			)
		).scalar_one_or_none()
		if not member:
			raise MemberNotFoundError(f"ClubMember {member_id!r} not found")
		return member

	def apply_for_membership(
		self,
		applicant_name: str,
		email: str,
		phone: str,
		member_type_id: str,
		tenant_id: str,
		session: Any,
		*,
		proposer_member_id: str | None = None,
		seconder_member_id: str | None = None,
	) -> Any:
		"""Submit a new membership application (status=PENDING)."""
		from pgappforge.plugins.erp.industry.clubs.models import MembershipApplication
		from pgappforge.plugins.erp.industry.clubs.events import MemberApplicationSubmittedEvent

		app = MembershipApplication(
			tenant_id=tenant_id,
			applicant_name=applicant_name,
			applicant_email=email,
			applicant_phone=phone,
			member_type_id=member_type_id,
			proposer_member_id=proposer_member_id,
			seconder_member_id=seconder_member_id,
			status="PENDING",
			applied_at=_now(),
		)
		session.add(app)
		session.flush()

		_emit(
			MemberApplicationSubmittedEvent(
				aggregate_id=app.id,
				aggregate_type="MembershipApplication",
				tenant_id=tenant_id,
				application_id=app.id,
				applicant_name=applicant_name,
				member_type_id=member_type_id,
			),
			session,
		)
		log.info("apply_for_membership: %s → %s", applicant_name, app.id)
		return app

	def approve_application(
		self,
		application_id: str,
		decided_by: str,
		tenant_id: str,
		session: Any,
	) -> Any:
		"""Approve an application; create ClubMember + MemberAccount; charge joining fee."""
		from pgappforge.plugins.erp.industry.clubs.models import (
			ClubMember,
			ClubMembershipType,
			MemberAccount,
			MembershipApplication,
		)
		from pgappforge.plugins.erp.industry.clubs.events import MemberApprovedEvent

		app = session.get(MembershipApplication, application_id)
		if app is None or app.tenant_id != tenant_id:
			raise ClubError(f"MembershipApplication {application_id!r} not found")
		if app.status not in ("PENDING", "WAITLISTED"):
			raise ClubError(
				f"Application {application_id!r} has status {app.status!r}; "
				"expected PENDING or WAITLISTED"
			)

		membership_number = self._next_member_number(tenant_id, session)

		member = ClubMember(
			tenant_id=tenant_id,
			membership_number=membership_number,
			full_name=app.applicant_name,
			email=app.applicant_email or "",
			phone=app.applicant_phone or "",
			member_type_id=app.member_type_id,
			proposer_member_id=app.proposer_member_id,
			seconder_member_id=app.seconder_member_id,
			status="ACTIVE",
			joined_date=_today(),
		)
		session.add(member)
		session.flush()

		# Get or create account
		account = MemberAccountService().get_or_create_account(member.id, tenant_id, session)

		# Update application
		app.status = "APPROVED"
		app.decided_at = _now()
		app.decided_by = decided_by
		app.resulting_member_id = member.id
		session.flush()

		# Joining fee
		mtype = session.get(ClubMembershipType, app.member_type_id)
		if mtype is not None and (mtype.joining_fee_cents or 0) > 0:
			MemberAccountService().post_charge(
				member.id,
				"ANNUAL_FEE",
				f"Joining fee — {mtype.name}",
				mtype.joining_fee_cents,
				tenant_id,
				session,
				reference_id=str(app.id),
				reference_type="MembershipApplication",
			)

		_emit(
			MemberApprovedEvent(
				aggregate_id=member.id,
				aggregate_type="ClubMember",
				tenant_id=tenant_id,
				member_id=member.id,
				membership_number=membership_number,
				member_type_id=str(app.member_type_id),
			),
			session,
		)
		log.info("approve_application: %s → member %s (%s)", application_id, member.id, membership_number)
		return member

	def reject_application(
		self,
		application_id: str,
		decided_by: str,
		reason: str,
		tenant_id: str,
		session: Any,
	) -> Any:
		"""Reject a PENDING application."""
		from pgappforge.plugins.erp.industry.clubs.models import MembershipApplication

		app = session.get(MembershipApplication, application_id)
		if app is None or app.tenant_id != tenant_id:
			raise ClubError(f"MembershipApplication {application_id!r} not found")

		app.status = "REJECTED"
		app.decided_at = _now()
		app.decided_by = decided_by
		app.notes = reason
		session.flush()
		log.info("reject_application: %s", application_id)
		return app

	def waitlist_application(
		self,
		application_id: str,
		tenant_id: str,
		session: Any,
	) -> Any:
		"""Move a PENDING application to the waitlist."""
		from pgappforge.plugins.erp.industry.clubs.models import MembershipApplication

		app = session.get(MembershipApplication, application_id)
		if app is None or app.tenant_id != tenant_id:
			raise ClubError(f"MembershipApplication {application_id!r} not found")

		app.status = "WAITLISTED"
		session.flush()
		log.info("waitlist_application: %s", application_id)
		return app

	def suspend_member(
		self,
		member_id: str,
		reason: str,
		tenant_id: str,
		session: Any,
	) -> Any:
		"""Set status=SUSPENDED and record suspension_reason."""
		from pgappforge.plugins.erp.industry.clubs.events import MemberSuspendedEvent

		member = self._get_member(member_id, tenant_id, session)
		member.status = "SUSPENDED"
		member.suspension_reason = reason
		member.updated_at = _now()
		session.flush()

		_emit(
			MemberSuspendedEvent(
				aggregate_id=member.id,
				aggregate_type="ClubMember",
				tenant_id=tenant_id,
				member_id=member.id,
				reason=reason,
			),
			session,
		)
		log.info("suspend_member: %s — %s", member_id, reason)
		return member

	def reinstate_member(
		self,
		member_id: str,
		tenant_id: str,
		session: Any,
	) -> Any:
		"""Clear suspension; set status=ACTIVE."""
		member = self._get_member(member_id, tenant_id, session)
		member.status = "ACTIVE"
		member.suspension_reason = None
		member.updated_at = _now()
		session.flush()
		log.info("reinstate_member: %s", member_id)
		return member

	def resign_member(
		self,
		member_id: str,
		effective_date: date,
		tenant_id: str,
		session: Any,
	) -> Any:
		"""Record a formal resignation."""
		from pgappforge.plugins.erp.industry.clubs.events import MemberResignedEvent

		member = self._get_member(member_id, tenant_id, session)
		member.status = "RESIGNED"
		member.resigned_date = effective_date
		member.updated_at = _now()
		session.flush()

		_emit(
			MemberResignedEvent(
				aggregate_id=member.id,
				aggregate_type="ClubMember",
				tenant_id=tenant_id,
				member_id=member.id,
			),
			session,
		)
		log.info("resign_member: %s effective %s", member_id, effective_date)
		return member

	def get_membership_roster(
		self,
		tenant_id: str,
		session: Any,
		*,
		status: str | None = None,
		member_type_id: str | None = None,
	) -> list[dict]:
		"""Return filtered membership roster as a list of dicts."""
		from pgappforge.plugins.erp.industry.clubs.models import ClubMember

		q = select(ClubMember).where(ClubMember.tenant_id == tenant_id)
		if status:
			q = q.where(ClubMember.status == status)
		if member_type_id:
			q = q.where(ClubMember.member_type_id == member_type_id)
		q = q.order_by(ClubMember.membership_number)

		members = session.execute(q).scalars().all()
		return [
			{
				"id": m.id,
				"membership_number": m.membership_number,
				"full_name": m.full_name,
				"email": m.email,
				"phone": m.phone,
				"status": m.status,
				"member_type_id": m.member_type_id,
				"joined_date": m.joined_date,
				"resigned_date": m.resigned_date,
			}
			for m in members
		]


# ---------------------------------------------------------------------------
# CLASS 2 — FacilityService
# ---------------------------------------------------------------------------

class FacilityService:
	"""Facility management and booking."""

	@staticmethod
	def _booking_ref() -> str:
		return "BK-" + secrets.token_hex(4).upper()

	def create_facility(
		self,
		name: str,
		code: str,
		facility_type: str,
		capacity: int,
		tenant_id: str,
		session: Any,
		**kwargs: Any,
	) -> Any:
		"""Create a new bookable facility."""
		from pgappforge.plugins.erp.industry.clubs.models import Facility

		facility = Facility(
			tenant_id=tenant_id,
			name=name,
			code=code,
			facility_type=facility_type,
			capacity=capacity,
			**{
				k: v for k, v in kwargs.items()
				if k in (
					"location", "is_members_only", "guest_allowed",
					"max_guests_per_booking", "hourly_rate_cents",
					"booking_advance_hours", "max_consecutive_hours",
					"open_time", "close_time", "is_active",
				)
			},
		)
		session.add(facility)
		session.flush()
		log.info("create_facility: %s (%s) tenant=%s", name, code, tenant_id)
		return facility

	def get_available_slots(
		self,
		facility_id: str,
		booking_date: date,
		tenant_id: str,
		session: Any,
	) -> list[dict]:
		"""Return 30-minute slot grid for a facility on a given date."""
		from pgappforge.plugins.erp.industry.clubs.models import Facility, FacilityBooking

		facility = session.execute(
			select(Facility).where(
				Facility.id == facility_id,
				Facility.tenant_id == tenant_id,
			)
		).scalar_one_or_none()
		if not facility:
			raise FacilityNotFoundError(f"Facility {facility_id!r} not found")

		# Existing CONFIRMED bookings for that date
		existing = session.execute(
			select(FacilityBooking).where(
				FacilityBooking.facility_id == facility_id,
				FacilityBooking.booking_date == booking_date,
				FacilityBooking.status == "CONFIRMED",
				FacilityBooking.tenant_id == tenant_id,
			)
		).scalars().all()

		# Generate 30-min slots
		def _hhmm_to_minutes(hhmm: str) -> int:
			h, m = hhmm.split(":")
			return int(h) * 60 + int(m)

		def _minutes_to_hhmm(minutes: int) -> str:
			return f"{minutes // 60:02d}:{minutes % 60:02d}"

		open_min = _hhmm_to_minutes(facility.open_time or "06:00")
		close_min = _hhmm_to_minutes(facility.close_time or "22:00")

		slots = []
		cursor = open_min
		while cursor + 30 <= close_min:
			slot_start = cursor
			slot_end = cursor + 30
			available = True
			for bk in existing:
				bk_start = _hhmm_to_minutes(bk.start_time)
				bk_end = _hhmm_to_minutes(bk.end_time)
				if bk_start < slot_end and bk_end > slot_start:
					available = False
					break
			slots.append({
				"start_time": _minutes_to_hhmm(slot_start),
				"end_time": _minutes_to_hhmm(slot_end),
				"available": available,
			})
			cursor += 30

		return slots

	def book_facility(
		self,
		facility_id: str,
		member_id: str,
		booking_date: date,
		start_time: str,
		end_time: str,
		guest_count: int,
		tenant_id: str,
		session: Any,
		*,
		notes: str | None = None,
	) -> Any:
		"""Confirm a facility booking; post charge if hourly_rate_cents > 0."""
		from pgappforge.plugins.erp.industry.clubs.models import (
			ClubMember,
			Facility,
			FacilityBooking,
		)
		from pgappforge.plugins.erp.industry.clubs.events import FacilityBookedEvent

		# 1. Get facility
		facility = session.execute(
			select(Facility).where(
				Facility.id == facility_id,
				Facility.tenant_id == tenant_id,
			)
		).scalar_one_or_none()
		if not facility:
			raise FacilityNotFoundError(f"Facility {facility_id!r} not found")
		if not facility.is_active:
			raise ClubError(f"Facility {facility.code!r} is not active")

		# 2. Validate member ACTIVE
		member = session.execute(
			select(ClubMember).where(
				ClubMember.id == member_id,
				ClubMember.tenant_id == tenant_id,
			)
		).scalar_one_or_none()
		if not member:
			raise MemberNotFoundError(f"ClubMember {member_id!r} not found")
		if member.status != "ACTIVE":
			raise ClubError(f"Member {member_id!r} has status {member.status!r}; must be ACTIVE to book")

		# 3. Conflict check
		conflicts = session.execute(
			select(FacilityBooking).where(
				FacilityBooking.facility_id == facility_id,
				FacilityBooking.booking_date == booking_date,
				FacilityBooking.status == "CONFIRMED",
				FacilityBooking.tenant_id == tenant_id,
				FacilityBooking.start_time < end_time,
				FacilityBooking.end_time > start_time,
			)
		).scalars().all()
		if conflicts:
			raise BookingConflictError(
				f"Facility {facility.code!r} is already booked on {booking_date} "
				f"{start_time}–{end_time}"
			)

		# 4. Guest capacity
		if guest_count > facility.max_guests_per_booking:
			raise BookingCapacityError(
				f"Guest count {guest_count} exceeds facility limit "
				f"{facility.max_guests_per_booking}"
			)

		# 5. Duration
		def _hhmm_to_minutes(hhmm: str) -> int:
			h, m = hhmm.split(":")
			return int(h) * 60 + int(m)

		duration_minutes = _hhmm_to_minutes(end_time) - _hhmm_to_minutes(start_time)
		if duration_minutes <= 0:
			raise ClubError(f"end_time {end_time!r} must be after start_time {start_time!r}")

		# 6. Fee
		fee = (facility.hourly_rate_cents or 0) * duration_minutes // 60

		# 7. Create booking
		booking_ref = self._booking_ref()
		booking = FacilityBooking(
			tenant_id=tenant_id,
			facility_id=facility_id,
			member_id=member_id,
			booking_ref=booking_ref,
			booking_date=booking_date,
			start_time=start_time,
			end_time=end_time,
			duration_minutes=duration_minutes,
			guest_count=guest_count,
			total_fee_cents=fee,
			status="CONFIRMED",
			notes=notes,
		)
		session.add(booking)
		session.flush()

		# 8. Charge if applicable
		if fee > 0:
			MemberAccountService().post_charge(
				member_id,
				"FACILITY_BOOKING",
				f"Booking {booking_ref}",
				fee,
				tenant_id,
				session,
				reference_id=str(booking.id),
				reference_type="FacilityBooking",
			)

		# 9. Emit
		_emit(
			FacilityBookedEvent(
				aggregate_id=booking.id,
				aggregate_type="FacilityBooking",
				tenant_id=tenant_id,
				booking_id=booking.id,
				facility_id=facility_id,
				member_id=member_id,
				booking_date=str(booking_date),
			),
			session,
		)
		log.info(
			"book_facility: ref=%s facility=%s member=%s date=%s %s–%s fee=%d¢",
			booking_ref, facility_id, member_id, booking_date, start_time, end_time, fee,
		)
		return booking

	def cancel_booking(
		self,
		booking_id: str,
		tenant_id: str,
		session: Any,
		*,
		reason: str | None = None,
	) -> Any:
		"""Cancel a confirmed booking."""
		from pgappforge.plugins.erp.industry.clubs.models import FacilityBooking
		from pgappforge.plugins.erp.industry.clubs.events import BookingCancelledEvent

		booking = session.execute(
			select(FacilityBooking).where(
				FacilityBooking.id == booking_id,
				FacilityBooking.tenant_id == tenant_id,
			)
		).scalar_one_or_none()
		if not booking:
			raise ClubError(f"FacilityBooking {booking_id!r} not found")

		booking.status = "CANCELLED"
		booking.cancellation_reason = reason
		booking.updated_at = _now()
		session.flush()

		_emit(
			BookingCancelledEvent(
				aggregate_id=booking.id,
				aggregate_type="FacilityBooking",
				tenant_id=tenant_id,
				booking_id=booking.id,
				facility_id=str(booking.facility_id),
				member_id=str(booking.member_id),
			),
			session,
		)
		log.info("cancel_booking: %s", booking_id)
		return booking

	def complete_booking(
		self,
		booking_id: str,
		tenant_id: str,
		session: Any,
	) -> Any:
		"""Mark a booking as COMPLETED."""
		from pgappforge.plugins.erp.industry.clubs.models import FacilityBooking

		booking = session.execute(
			select(FacilityBooking).where(
				FacilityBooking.id == booking_id,
				FacilityBooking.tenant_id == tenant_id,
			)
		).scalar_one_or_none()
		if not booking:
			raise ClubError(f"FacilityBooking {booking_id!r} not found")

		booking.status = "COMPLETED"
		booking.updated_at = _now()
		session.flush()
		log.info("complete_booking: %s", booking_id)
		return booking

	def no_show(
		self,
		booking_id: str,
		tenant_id: str,
		session: Any,
	) -> Any:
		"""Mark a booking as NO_SHOW."""
		from pgappforge.plugins.erp.industry.clubs.models import FacilityBooking

		booking = session.execute(
			select(FacilityBooking).where(
				FacilityBooking.id == booking_id,
				FacilityBooking.tenant_id == tenant_id,
			)
		).scalar_one_or_none()
		if not booking:
			raise ClubError(f"FacilityBooking {booking_id!r} not found")

		booking.status = "NO_SHOW"
		booking.updated_at = _now()
		session.flush()
		log.info("no_show: %s", booking_id)
		return booking

	def get_facility_schedule(
		self,
		facility_id: str,
		booking_date: date,
		tenant_id: str,
		session: Any,
	) -> list[dict]:
		"""Return all bookings for a facility on a given date."""
		from pgappforge.plugins.erp.industry.clubs.models import FacilityBooking

		bookings = session.execute(
			select(FacilityBooking)
			.where(
				FacilityBooking.facility_id == facility_id,
				FacilityBooking.booking_date == booking_date,
				FacilityBooking.tenant_id == tenant_id,
			)
			.order_by(FacilityBooking.start_time)
		).scalars().all()

		return [
			{
				"booking_id": b.id,
				"booking_ref": b.booking_ref,
				"member_id": b.member_id,
				"start_time": b.start_time,
				"end_time": b.end_time,
				"duration_minutes": b.duration_minutes,
				"guest_count": b.guest_count,
				"status": b.status,
				"total_fee_cents": b.total_fee_cents,
			}
			for b in bookings
		]


# ---------------------------------------------------------------------------
# CLASS 3 — MemberAccountService
# ---------------------------------------------------------------------------

class MemberAccountService:
	"""Member charge account: charges, payments, statements."""

	def get_or_create_account(
		self,
		member_id: str,
		tenant_id: str,
		session: Any,
	) -> Any:
		"""Return existing MemberAccount or create one."""
		from pgappforge.plugins.erp.industry.clubs.models import MemberAccount

		account = session.execute(
			select(MemberAccount).where(
				MemberAccount.member_id == member_id,
				MemberAccount.tenant_id == tenant_id,
			)
		).scalar_one_or_none()
		if account is None:
			account = MemberAccount(
				tenant_id=tenant_id,
				member_id=member_id,
				current_balance_cents=0,
				credit_limit_cents=0,
			)
			session.add(account)
			session.flush()
		return account

	def post_charge(
		self,
		member_id: str,
		charge_type: str,
		description: str,
		amount_cents: int,
		tenant_id: str,
		session: Any,
		*,
		reference_id: str | None = None,
		reference_type: str | None = None,
	) -> Any:
		"""Post a charge (positive=debit, negative=credit) and update running balance."""
		from pgappforge.plugins.erp.industry.clubs.models import MemberAccount, MemberCharge
		from pgappforge.plugins.erp.industry.clubs.events import MemberChargedEvent

		account = self.get_or_create_account(member_id, tenant_id, session)

		charge = MemberCharge(
			tenant_id=tenant_id,
			member_id=member_id,
			account_id=account.id,
			charge_type=charge_type,
			description=description,
			amount_cents=amount_cents,
			reference_id=reference_id,
			reference_type=reference_type,
			charged_at=_now(),
		)
		session.add(charge)

		# Atomic balance update via UPDATE statement (avoids stale read races)
		session.execute(
			sa.update(MemberAccount)
			.where(MemberAccount.id == account.id)
			.values(
				current_balance_cents=MemberAccount.current_balance_cents + amount_cents,
				updated_at=_now(),
			)
		)
		session.flush()

		_emit(
			MemberChargedEvent(
				aggregate_id=member_id,
				aggregate_type="ClubMember",
				tenant_id=tenant_id,
				member_id=member_id,
				amount_cents=amount_cents,
				charge_type=charge_type,
			),
			session,
		)
		log.info(
			"post_charge: member=%s type=%s amount=%d¢",
			member_id, charge_type, amount_cents,
		)
		return charge

	def record_payment(
		self,
		member_id: str,
		amount_cents: int,
		payment_ref: str,
		tenant_id: str,
		session: Any,
	) -> dict:
		"""Record a payment (posts negative charge) and return new balance."""
		self.post_charge(
			member_id,
			"MISCELLANEOUS",
			f"Payment ref {payment_ref}",
			-amount_cents,
			tenant_id,
			session,
		)
		new_balance = self.get_outstanding_balance(member_id, tenant_id, session)
		log.info("record_payment: member=%s ref=%s amount=%d¢", member_id, payment_ref, amount_cents)
		return {
			"member_id": member_id,
			"payment_ref": payment_ref,
			"new_balance_cents": new_balance,
		}

	def get_outstanding_balance(
		self,
		member_id: str,
		tenant_id: str,
		session: Any,
	) -> int:
		"""Return current_balance_cents; 0 if no account exists."""
		from pgappforge.plugins.erp.industry.clubs.models import MemberAccount

		account = session.execute(
			select(MemberAccount).where(
				MemberAccount.member_id == member_id,
				MemberAccount.tenant_id == tenant_id,
			)
		).scalar_one_or_none()
		return (account.current_balance_cents or 0) if account else 0

	def check_credit_limit(
		self,
		member_id: str,
		additional_cents: int,
		tenant_id: str,
		session: Any,
	) -> bool:
		"""Return True if the transaction would not exceed the credit limit.

		credit_limit_cents == 0 means no limit — always returns True.
		"""
		account = self.get_or_create_account(member_id, tenant_id, session)
		if not account.credit_limit_cents:
			return True
		return (account.current_balance_cents + additional_cents) <= account.credit_limit_cents

	def generate_statement(
		self,
		member_id: str,
		statement_date: date,
		tenant_id: str,
		session: Any,
	) -> Any:
		"""Generate a monthly member statement snapshot."""
		from pgappforge.plugins.erp.industry.clubs.models import (
			ClubMember,
			MemberAccount,
			MemberCharge,
			MemberStatement,
		)
		from pgappforge.plugins.erp.industry.clubs.events import StatementGeneratedEvent

		account = self.get_or_create_account(member_id, tenant_id, session)

		# Determine period start
		if account.last_statement_date:
			period_start = account.last_statement_date
		else:
			member = session.get(ClubMember, member_id)
			period_start = (member.joined_date if member and member.joined_date else date(1970, 1, 1))

		# Opening balance = closing balance of last statement, or 0
		last_stmt = session.execute(
			select(MemberStatement)
			.where(
				MemberStatement.member_id == member_id,
				MemberStatement.tenant_id == tenant_id,
				MemberStatement.statement_date < statement_date,
			)
			.order_by(MemberStatement.statement_date.desc())
			.limit(1)
		).scalar_one_or_none()
		opening_balance = (last_stmt.closing_balance_cents or 0) if last_stmt else 0

		# Aggregate charges/payments in period
		charge_rows = session.execute(
			select(MemberCharge.amount_cents)
			.where(
				MemberCharge.member_id == member_id,
				MemberCharge.tenant_id == tenant_id,
				MemberCharge.charged_at >= datetime.combine(period_start, datetime.min.time()).replace(tzinfo=timezone.utc),
				MemberCharge.charged_at <= datetime.combine(statement_date, datetime.max.time()).replace(tzinfo=timezone.utc),
			)
		).scalars().all()

		charges_cents = sum(c for c in charge_rows if c > 0)
		payments_cents = abs(sum(c for c in charge_rows if c < 0))
		closing_balance = opening_balance + charges_cents - payments_cents

		stmt = MemberStatement(
			tenant_id=tenant_id,
			member_id=member_id,
			statement_date=statement_date,
			opening_balance_cents=opening_balance,
			charges_cents=charges_cents,
			payments_cents=payments_cents,
			closing_balance_cents=closing_balance,
			status="DRAFT",
		)
		session.add(stmt)

		account.last_statement_date = statement_date
		session.flush()

		_emit(
			StatementGeneratedEvent(
				aggregate_id=member_id,
				aggregate_type="ClubMember",
				tenant_id=tenant_id,
				member_id=member_id,
				statement_date=str(statement_date),
				closing_balance_cents=closing_balance,
			),
			session,
		)
		log.info(
			"generate_statement: member=%s date=%s closing=%d¢",
			member_id, statement_date, closing_balance,
		)
		return stmt

	def run_monthly_statements(
		self,
		tenant_id: str,
		session: Any,
	) -> int:
		"""Generate statements for all ACTIVE members whose statement day matches today."""
		from pgappforge.plugins.erp.industry.clubs.models import ClubMember, MemberAccount

		today = _today()
		accounts = session.execute(
			select(MemberAccount)
			.join(ClubMember, ClubMember.id == MemberAccount.member_id)
			.where(
				MemberAccount.tenant_id == tenant_id,
				ClubMember.status == "ACTIVE",
				MemberAccount.statement_day_of_month == today.day,
			)
		).scalars().all()

		count = 0
		for account in accounts:
			try:
				self.generate_statement(account.member_id, today, tenant_id, session)
				count += 1
			except Exception:
				log.warning(
					"run_monthly_statements: failed for member=%s",
					account.member_id,
					exc_info=True,
				)
		log.info("run_monthly_statements: generated %d statements for tenant=%s", count, tenant_id)
		return count


# ---------------------------------------------------------------------------
# CLASS 4 — GuestService
# ---------------------------------------------------------------------------

class GuestService:
	"""Guest visit logging with daily-limit enforcement and levy charging."""

	def log_guest_visit(
		self,
		member_id: str,
		guest_name: str,
		visit_date: date,
		tenant_id: str,
		session: Any,
		*,
		facility_id: str | None = None,
		guest_phone: str | None = None,
		purpose: str | None = None,
		charge_levy: bool = True,
	) -> Any:
		"""Record a guest visit and optionally post a levy charge."""
		from pgappforge.plugins.erp.industry.clubs.models import (
			ClubMember,
			ClubMembershipType,
			GuestVisit,
		)
		from pgappforge.plugins.erp.industry.clubs.events import GuestVisitLoggedEvent

		# Validate member ACTIVE
		member = session.execute(
			select(ClubMember).where(
				ClubMember.id == member_id,
				ClubMember.tenant_id == tenant_id,
			)
		).scalar_one_or_none()
		if not member:
			raise MemberNotFoundError(f"ClubMember {member_id!r} not found")
		if member.status != "ACTIVE":
			raise ClubError(
				f"Member {member_id!r} has status {member.status!r}; cannot bring guests"
			)

		# Daily limit from membership type entitlements
		mtype = session.get(ClubMembershipType, member.member_type_id)
		entitlements = (mtype.entitlements or {}) if mtype else {}
		daily_limit = int(entitlements.get("guest_visits_per_day", 2))

		today_count = session.execute(
			select(func.count(GuestVisit.id)).where(
				GuestVisit.member_id == member_id,
				GuestVisit.tenant_id == tenant_id,
				GuestVisit.visit_date == visit_date,
			)
		).scalar_one() or 0

		if today_count >= daily_limit:
			raise GuestLimitExceededError(
				f"Member {member_id!r} has reached the daily guest limit of {daily_limit}"
			)

		levy_cents = int(entitlements.get("guest_levy_cents", 0))

		visit = GuestVisit(
			tenant_id=tenant_id,
			member_id=member_id,
			guest_name=guest_name,
			guest_phone=guest_phone,
			visit_date=visit_date,
			facility_id=facility_id,
			purpose=purpose,
			levy_cents=levy_cents,
			charged_to_account=charge_levy and levy_cents > 0,
		)
		session.add(visit)
		session.flush()

		# Post levy charge if applicable
		if levy_cents > 0 and charge_levy:
			charge = MemberAccountService().post_charge(
				member_id,
				"GUEST_LEVY",
				f"Guest levy — {guest_name}",
				levy_cents,
				tenant_id,
				session,
				reference_id=str(visit.id),
				reference_type="GuestVisit",
			)
			visit.charge_id = charge.id
			session.flush()

		_emit(
			GuestVisitLoggedEvent(
				aggregate_id=visit.id,
				aggregate_type="GuestVisit",
				tenant_id=tenant_id,
				member_id=member_id,
				guest_name=guest_name,
				visit_date=str(visit_date),
			),
			session,
		)
		log.info(
			"log_guest_visit: member=%s guest=%s date=%s levy=%d¢",
			member_id, guest_name, visit_date, levy_cents,
		)
		return visit

	def get_member_guest_history(
		self,
		member_id: str,
		from_date: date,
		tenant_id: str,
		session: Any,
	) -> list[dict]:
		"""Return guest visits for a member since from_date."""
		from pgappforge.plugins.erp.industry.clubs.models import GuestVisit

		visits = session.execute(
			select(GuestVisit)
			.where(
				GuestVisit.member_id == member_id,
				GuestVisit.tenant_id == tenant_id,
				GuestVisit.visit_date >= from_date,
			)
			.order_by(GuestVisit.visit_date.desc())
		).scalars().all()

		return [
			{
				"id": v.id,
				"guest_name": v.guest_name,
				"guest_phone": v.guest_phone,
				"visit_date": v.visit_date,
				"facility_id": v.facility_id,
				"purpose": v.purpose,
				"levy_cents": v.levy_cents,
				"charged_to_account": v.charged_to_account,
			}
			for v in visits
		]


# ---------------------------------------------------------------------------
# CLASS 5 — AccessControlService
# ---------------------------------------------------------------------------

class AccessControlService:
	"""Door/gate access events; occupancy counting; fire register."""

	def log_access(
		self,
		member_identifier: str,
		door_id: str,
		door_name: str,
		direction: str,
		tenant_id: str,
		session: Any,
		*,
		device_id: str | None = None,
	) -> Any:
		"""Log an access attempt; returns GRANTED or DENIED AccessEvent."""
		from pgappforge.plugins.erp.industry.clubs.models import AccessEvent, ClubMember
		from pgappforge.plugins.erp.industry.clubs.events import AccessGrantedEvent, AccessDeniedEvent

		# Try to locate member by id or membership_number
		member = session.execute(
			select(ClubMember).where(
				ClubMember.tenant_id == tenant_id,
				sa.or_(
					ClubMember.id == member_identifier,
					ClubMember.membership_number == member_identifier,
				),
			)
		).scalar_one_or_none()

		if member is None:
			event = AccessEvent(
				tenant_id=tenant_id,
				member_id=member_identifier if len(member_identifier) == 36 else _uuid4(),
				door_id=door_id,
				door_name=door_name,
				direction=direction,
				access_result="DENIED",
				denial_reason="UNKNOWN_MEMBER",
				device_id=device_id,
				occurred_at=_now(),
			)
			session.add(event)
			session.flush()
			_emit(
				AccessDeniedEvent(
					aggregate_id=event.id,
					aggregate_type="AccessEvent",
					tenant_id=tenant_id,
					member_id=event.member_id,
					door_id=door_id,
					reason="UNKNOWN_MEMBER",
				),
				session,
			)
			log.warning("log_access: DENIED (UNKNOWN_MEMBER) identifier=%s door=%s", member_identifier, door_id)
			return event

		if member.status != "ACTIVE":
			denial_reason = f"MEMBER_{member.status}"
			event = AccessEvent(
				tenant_id=tenant_id,
				member_id=member.id,
				door_id=door_id,
				door_name=door_name,
				direction=direction,
				access_result="DENIED",
				denial_reason=denial_reason,
				device_id=device_id,
				occurred_at=_now(),
			)
			session.add(event)
			session.flush()
			_emit(
				AccessDeniedEvent(
					aggregate_id=event.id,
					aggregate_type="AccessEvent",
					tenant_id=tenant_id,
					member_id=member.id,
					door_id=door_id,
					reason=denial_reason,
				),
				session,
			)
			log.warning(
				"log_access: DENIED (%s) member=%s door=%s",
				denial_reason, member.id, door_id,
			)
			return event

		# GRANTED
		event = AccessEvent(
			tenant_id=tenant_id,
			member_id=member.id,
			door_id=door_id,
			door_name=door_name,
			direction=direction,
			access_result="GRANTED",
			device_id=device_id,
			occurred_at=_now(),
		)
		session.add(event)
		session.flush()
		_emit(
			AccessGrantedEvent(
				aggregate_id=event.id,
				aggregate_type="AccessEvent",
				tenant_id=tenant_id,
				member_id=member.id,
				door_id=door_id,
			),
			session,
		)
		log.info("log_access: GRANTED member=%s door=%s dir=%s", member.id, door_id, direction)
		return event

	def get_current_occupancy(
		self,
		door_id: str,
		tenant_id: str,
		session: Any,
	) -> int:
		"""Count net IN minus OUT events for today at a given door."""
		from pgappforge.plugins.erp.industry.clubs.models import AccessEvent

		today_start = datetime.combine(_today(), datetime.min.time()).replace(tzinfo=timezone.utc)

		ins = session.execute(
			select(func.count(AccessEvent.id)).where(
				AccessEvent.tenant_id == tenant_id,
				AccessEvent.door_id == door_id,
				AccessEvent.direction == "IN",
				AccessEvent.access_result == "GRANTED",
				AccessEvent.occurred_at >= today_start,
			)
		).scalar_one() or 0

		outs = session.execute(
			select(func.count(AccessEvent.id)).where(
				AccessEvent.tenant_id == tenant_id,
				AccessEvent.door_id == door_id,
				AccessEvent.direction == "OUT",
				AccessEvent.access_result == "GRANTED",
				AccessEvent.occurred_at >= today_start,
			)
		).scalar_one() or 0

		return max(0, ins - outs)

	def get_access_log(
		self,
		member_id: str,
		tenant_id: str,
		session: Any,
		*,
		from_date: date | None = None,
	) -> list[dict]:
		"""Return up to 500 access events for a member, newest first."""
		from pgappforge.plugins.erp.industry.clubs.models import AccessEvent

		q = select(AccessEvent).where(
			AccessEvent.member_id == member_id,
			AccessEvent.tenant_id == tenant_id,
		)
		if from_date:
			from_dt = datetime.combine(from_date, datetime.min.time()).replace(tzinfo=timezone.utc)
			q = q.where(AccessEvent.occurred_at >= from_dt)
		q = q.order_by(AccessEvent.occurred_at.desc()).limit(500)

		events = session.execute(q).scalars().all()
		return [
			{
				"id": e.id,
				"door_id": e.door_id,
				"door_name": e.door_name,
				"direction": e.direction,
				"access_result": e.access_result,
				"denial_reason": e.denial_reason,
				"device_id": e.device_id,
				"occurred_at": e.occurred_at,
			}
			for e in events
		]

	def get_fire_register(
		self,
		tenant_id: str,
		session: Any,
	) -> list[dict]:
		"""Return all members currently on premises (IN count > OUT count today)."""
		from pgappforge.plugins.erp.industry.clubs.models import AccessEvent, ClubMember

		today_start = datetime.combine(_today(), datetime.min.time()).replace(tzinfo=timezone.utc)

		# Ins per member today
		ins_sub = (
			select(
				AccessEvent.member_id,
				func.count(AccessEvent.id).label("in_count"),
				func.max(AccessEvent.occurred_at).label("last_entry_time"),
				func.max(AccessEvent.door_name).label("last_door_name"),
			)
			.where(
				AccessEvent.tenant_id == tenant_id,
				AccessEvent.direction == "IN",
				AccessEvent.access_result == "GRANTED",
				AccessEvent.occurred_at >= today_start,
			)
			.group_by(AccessEvent.member_id)
			.subquery("ins")
		)

		# Outs per member today
		outs_sub = (
			select(
				AccessEvent.member_id,
				func.count(AccessEvent.id).label("out_count"),
			)
			.where(
				AccessEvent.tenant_id == tenant_id,
				AccessEvent.direction == "OUT",
				AccessEvent.access_result == "GRANTED",
				AccessEvent.occurred_at >= today_start,
			)
			.group_by(AccessEvent.member_id)
			.subquery("outs")
		)

		rows = session.execute(
			select(
				ClubMember.id.label("member_id"),
				ClubMember.membership_number,
				ClubMember.full_name,
				ins_sub.c.last_door_name,
				ins_sub.c.last_entry_time,
				ins_sub.c.in_count,
				sa.func.coalesce(outs_sub.c.out_count, 0).label("out_count"),
			)
			.join(ins_sub, ins_sub.c.member_id == ClubMember.id)
			.outerjoin(outs_sub, outs_sub.c.member_id == ClubMember.id)
			.where(ClubMember.tenant_id == tenant_id)
			.where(ins_sub.c.in_count > sa.func.coalesce(outs_sub.c.out_count, 0))
			.order_by(ins_sub.c.last_entry_time)
		).all()

		return [
			{
				"member_id": row.member_id,
				"membership_number": row.membership_number,
				"full_name": row.full_name,
				"last_door_name": row.last_door_name,
				"last_entry_time": row.last_entry_time,
			}
			for row in rows
		]


# ---------------------------------------------------------------------------
# BPM Action registrations
# ---------------------------------------------------------------------------

try:
	from pgappforge.plugins.workflow.engine import BPMActionRegistry as _BPMReg

	@_BPMReg.register("club.book_facility", "Book a club facility for a member")
	def _bpm_book_facility(
		record_ctx,
		session,
		facility_id="",
		member_id="",
		booking_date="",
		start_time="",
		end_time="",
		**kw,
	):
		try:
			from pgappforge.plugins.erp.industry.clubs.services import FacilityService
			from datetime import date as _date
			bd = _date.fromisoformat(booking_date) if booking_date else _date.today()
			b = FacilityService().book_facility(
				facility_id, member_id, bd, start_time, end_time, 0,
				record_ctx.get("tenant_id", ""), session,
			)
			return {"status": "ok", "booking_ref": b.booking_ref}
		except Exception as exc:
			return {"status": "error", "message": str(exc)}

	@_BPMReg.register("club.post_charge", "Post a charge to a club member's account")
	def _bpm_post_charge(
		record_ctx,
		session,
		member_id="",
		charge_type="MISCELLANEOUS",
		description="",
		amount_cents=0,
		**kw,
	):
		try:
			from pgappforge.plugins.erp.industry.clubs.services import MemberAccountService
			c = MemberAccountService().post_charge(
				member_id, charge_type, description, amount_cents,
				record_ctx.get("tenant_id", ""), session,
			)
			return {"status": "ok", "charge_id": str(c.id), "amount_cents": amount_cents}
		except Exception as exc:
			return {"status": "error", "message": str(exc)}

except (ImportError, Exception):
	pass


__all__ = [
	"ClubMemberService",
	"FacilityService",
	"MemberAccountService",
	"GuestService",
	"AccessControlService",
	"ClubError",
	"MemberNotFoundError",
	"FacilityNotFoundError",
	"BookingConflictError",
	"BookingCapacityError",
	"CreditLimitExceededError",
	"GuestLimitExceededError",
]
