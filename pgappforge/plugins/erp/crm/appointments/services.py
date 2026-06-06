"""
pgappforge/plugins/erp/crm/appointments/services.py

AppointmentsService — stateless business logic for the Appointments/Booking plugin.

Key methods
-----------
  get_available_slots(service_id, staff_id, date, tenant_id, session) -> list[dict]
  book_appointment(service_id, staff_id, start_at, customer_email, customer_name,
                   tenant_id, session, *, customer_id, customer_phone, notes) -> Appointment
  confirm_appointment(appointment_id, session) -> Appointment
  complete_appointment(appointment_id, session) -> Appointment
  cancel_appointment(appointment_id, cancelled_by, reason, session) -> Appointment
  send_reminders(hours_before, session, *, tenant_id) -> list[Appointment]
  get_staff_schedule(staff_id, from_date, to_date, session) -> list[Appointment]
"""
from __future__ import annotations

import logging
import math
import random
import string
from datetime import date, datetime, timedelta, timezone
from typing import Any

import sqlalchemy as sa

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class AppointmentsServiceError(Exception):
	"""Base exception for the Appointments service layer."""


class AppointmentNotFoundError(AppointmentsServiceError):
	"""Raised when the requested appointment cannot be found."""


class AppointmentStateError(AppointmentsServiceError):
	"""Raised when an operation is invalid for the current appointment status."""


class SlotUnavailableError(AppointmentsServiceError):
	"""Raised when the requested slot is no longer available."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _generate_booking_ref(prefix: str = "APT") -> str:
	"""Generate a short booking reference, e.g. APT-X4K9M."""
	suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=5))
	return f"{prefix}-{suffix}"


def _slots_overlap(
	slot_start: datetime,
	slot_end: datetime,
	booked_start: datetime,
	booked_end: datetime,
) -> bool:
	"""Return True if [slot_start, slot_end) overlaps [booked_start, booked_end)."""
	return slot_start < booked_end and slot_end > booked_start


# ---------------------------------------------------------------------------
# AppointmentsService
# ---------------------------------------------------------------------------

class AppointmentsService:
	"""Stateless business logic for Appointments/Booking."""

	# ------------------------------------------------------------------
	# 1. get_available_slots
	# ------------------------------------------------------------------

	@staticmethod
	def get_available_slots(
		service_id: str,
		staff_id: str,
		target_date: date,
		tenant_id: str,
		session: Any,
	) -> list[dict[str, Any]]:
		"""Return available booking slots for a staff member on a given date.

		Algorithm:
		  1. Load the AppointmentService to get duration_minutes, buffer_minutes,
		     min_advance_hours, max_advance_days.
		  2. Gate on advance booking rules.
		  3. Load StaffAvailability for the target day_of_week.
		  4. Load existing Appointments (not CANCELLED) for the staff on that date.
		  5. Load StaffBlockedSlots that overlap the date.
		  6. Carve the availability window into (duration_minutes)-sized slots,
		     skipping any that overlap booked appointments + buffer or blocked slots.
		  7. Return list of {start: ISO, end: ISO} dicts.
		"""
		from pgappforge.plugins.erp.crm.appointments.models import (
			AppointmentService,
			StaffAvailability,
			StaffBlockedSlot,
			Appointment,
		)

		# Load service
		service = session.execute(
			sa.select(AppointmentService).where(
				AppointmentService.id == service_id,
				AppointmentService.tenant_id == tenant_id,
				AppointmentService.is_active.is_(True),
			)
		).scalar_one_or_none()
		if service is None:
			raise AppointmentsServiceError(
				f"AppointmentService {service_id} not found or inactive for tenant {tenant_id}"
			)

		duration = service.duration_minutes
		buffer = service.buffer_minutes
		slot_step = timedelta(minutes=duration)
		effective_step = timedelta(minutes=duration + buffer)

		# Advance booking gates
		now_utc = datetime.now(timezone.utc)
		today_utc = now_utc.date()
		earliest_start = now_utc + timedelta(hours=service.min_advance_hours)
		latest_date = today_utc + timedelta(days=service.max_advance_days)

		if target_date < today_utc:
			return []  # Past date
		if target_date > latest_date:
			return []  # Too far in advance

		# Check staff eligibility (empty eligible_staff_ids = all eligible)
		eligible = service.eligible_staff_ids
		if eligible and staff_id not in eligible:
			return []

		# Load staff availability for this day_of_week (0=Mon)
		day_of_week = target_date.weekday()  # Python: 0=Monday
		availability_rows = list(
			session.execute(
				sa.select(StaffAvailability).where(
					StaffAvailability.staff_id == staff_id,
					StaffAvailability.day_of_week == day_of_week,
					StaffAvailability.is_active.is_(True),
				)
			).scalars().all()
		)
		# Filter by effective dates
		active_windows: list[tuple[datetime, datetime]] = []
		for avail in availability_rows:
			if avail.effective_from and target_date < avail.effective_from:
				continue
			if avail.effective_to and target_date > avail.effective_to:
				continue
			# Build tz-aware datetimes on target_date
			win_start = datetime.combine(target_date, avail.start_time, tzinfo=timezone.utc)
			win_end = datetime.combine(target_date, avail.end_time, tzinfo=timezone.utc)
			if win_end > win_start:
				active_windows.append((win_start, win_end))

		if not active_windows:
			return []

		# Day boundaries for queries
		day_start = datetime.combine(target_date, datetime.min.time(), tzinfo=timezone.utc)
		day_end = day_start + timedelta(days=1)

		# Load existing booked slots for this staff on target_date
		booked = list(
			session.execute(
				sa.select(Appointment).where(
					Appointment.staff_id == staff_id,
					Appointment.start_at >= day_start,
					Appointment.start_at < day_end,
					Appointment.status.notin_(["CANCELLED"]),
				)
			).scalars().all()
		)
		# Include buffer in the busy windows
		busy_intervals: list[tuple[datetime, datetime]] = [
			(a.start_at, a.end_at + timedelta(minutes=buffer))
			for a in booked
		]

		# Load blocked slots overlapping this day
		blocked = list(
			session.execute(
				sa.select(StaffBlockedSlot).where(
					StaffBlockedSlot.staff_id == staff_id,
					StaffBlockedSlot.blocked_from < day_end,
					StaffBlockedSlot.blocked_to > day_start,
				)
			).scalars().all()
		)
		blocked_intervals: list[tuple[datetime, datetime]] = [
			(b.blocked_from, b.blocked_to) for b in blocked
		]

		all_busy = busy_intervals + blocked_intervals

		# Carve slots from each availability window
		available_slots: list[dict[str, Any]] = []
		for win_start, win_end in active_windows:
			cursor = win_start
			while cursor + slot_step <= win_end:
				slot_end = cursor + slot_step
				# Apply min_advance_hours gate
				if cursor < earliest_start:
					cursor += timedelta(minutes=30)  # advance by minimum granularity
					continue
				# Check against all busy intervals
				overlaps = any(
					_slots_overlap(cursor, slot_end, busy_s, busy_e)
					for busy_s, busy_e in all_busy
				)
				if not overlaps:
					available_slots.append({
						"start": cursor.isoformat(),
						"end": slot_end.isoformat(),
					})
				cursor += timedelta(minutes=30)  # 30-min granularity for slot grid

		log.info(
			"AppointmentsService.get_available_slots: %d slots for staff=%s date=%s",
			len(available_slots), staff_id, target_date,
		)
		return available_slots

	# ------------------------------------------------------------------
	# 2. book_appointment
	# ------------------------------------------------------------------

	@staticmethod
	def book_appointment(
		service_id: str,
		staff_id: str,
		start_at: datetime,
		customer_email: str,
		customer_name: str,
		tenant_id: str,
		session: Any,
		*,
		customer_id: str | None = None,
		customer_phone: str | None = None,
		notes: str | None = None,
	) -> Any:
		"""Book an appointment after re-validating slot availability.

		end_at = start_at + duration_minutes + buffer_minutes.
		Raises SlotUnavailableError if the slot is taken since get_available_slots.
		"""
		from pgappforge.plugins.erp.crm.appointments.models import (
			AppointmentService,
			StaffBlockedSlot,
			Appointment,
		)
		from pgappforge.plugins.erp.crm.appointments.events import AppointmentBookedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		assert start_at.tzinfo is not None, "start_at must be timezone-aware"

		service = session.execute(
			sa.select(AppointmentService).where(
				AppointmentService.id == service_id,
				AppointmentService.tenant_id == tenant_id,
				AppointmentService.is_active.is_(True),
			)
		).scalar_one_or_none()
		if service is None:
			raise AppointmentsServiceError(
				f"AppointmentService {service_id} not found or inactive"
			)

		duration = service.duration_minutes
		buffer = service.buffer_minutes
		end_at = start_at + timedelta(minutes=duration + buffer)

		# Re-validate: check no overlapping ACTIVE appointment for this staff
		conflict = session.execute(
			sa.select(Appointment).where(
				Appointment.staff_id == staff_id,
				Appointment.status.notin_(["CANCELLED"]),
				Appointment.start_at < end_at,
				Appointment.end_at > start_at,
			)
		).scalar_one_or_none()
		if conflict is not None:
			raise SlotUnavailableError(
				f"Slot {start_at.isoformat()} is no longer available for staff {staff_id}"
			)

		# Check blocked slots
		blocked = session.execute(
			sa.select(StaffBlockedSlot).where(
				StaffBlockedSlot.staff_id == staff_id,
				StaffBlockedSlot.blocked_from < end_at,
				StaffBlockedSlot.blocked_to > start_at,
			)
		).scalar_one_or_none()
		if blocked is not None:
			raise SlotUnavailableError(
				f"Staff {staff_id} is blocked during {start_at.isoformat()}"
			)

		# Advance booking gates
		now_utc = datetime.now(timezone.utc)
		earliest_start = now_utc + timedelta(hours=service.min_advance_hours)
		latest_date = now_utc.date() + timedelta(days=service.max_advance_days)
		if start_at < earliest_start:
			raise SlotUnavailableError(
				f"Appointment requires at least {service.min_advance_hours}h advance notice"
			)
		if start_at.date() > latest_date:
			raise SlotUnavailableError(
				f"Cannot book more than {service.max_advance_days} days in advance"
			)

		booking_ref = _generate_booking_ref()
		# Ensure uniqueness within tenant (re-roll on collision, max 5 attempts)
		for _ in range(5):
			existing_ref = session.execute(
				sa.select(Appointment).where(
					Appointment.tenant_id == tenant_id,
					Appointment.booking_ref == booking_ref,
				)
			).scalar_one_or_none()
			if existing_ref is None:
				break
			booking_ref = _generate_booking_ref()

		appointment = Appointment(
			tenant_id=tenant_id,
			service_id=service_id,
			staff_id=staff_id,
			customer_id=customer_id,
			customer_email=customer_email,
			customer_name=customer_name,
			customer_phone=customer_phone,
			start_at=start_at,
			end_at=end_at,
			status="PENDING",
			amount_cents=service.price_cents,
			currency_code=service.currency_code,
			notes=notes,
			reminder_sent=False,
			booking_ref=booking_ref,
			metadata_={},
		)
		session.add(appointment)
		session.flush()

		emit_event(AppointmentBookedEvent(
			aggregate_id=appointment.id,
			aggregate_type="Appointment",
			tenant_id=tenant_id,
			appointment_id=appointment.id,
			service_id=service_id,
			customer_id=customer_id or "",
			staff_id=staff_id,
			start_at=start_at.isoformat(),
		), session)

		log.info(
			"AppointmentsService.book_appointment: %s booked ref=%s staff=%s start=%s",
			appointment.id, booking_ref, staff_id, start_at.isoformat(),
		)
		return appointment

	# ------------------------------------------------------------------
	# 3. confirm_appointment
	# ------------------------------------------------------------------

	@staticmethod
	def confirm_appointment(appointment_id: str, session: Any) -> Any:
		"""Transition PENDING → CONFIRMED. Emits AppointmentConfirmedEvent."""
		from pgappforge.plugins.erp.crm.appointments.models import Appointment
		from pgappforge.plugins.erp.crm.appointments.events import AppointmentConfirmedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		appointment = session.execute(
			sa.select(Appointment).where(Appointment.id == appointment_id)
		).scalar_one_or_none()
		if appointment is None:
			raise AppointmentNotFoundError(f"Appointment {appointment_id} not found")
		if appointment.status != "PENDING":
			raise AppointmentStateError(
				f"Cannot confirm appointment in status {appointment.status!r}; must be PENDING"
			)

		appointment.status = "CONFIRMED"
		session.flush()

		emit_event(AppointmentConfirmedEvent(
			aggregate_id=appointment.id,
			aggregate_type="Appointment",
			tenant_id=appointment.tenant_id,
			appointment_id=appointment.id,
			customer_id=appointment.customer_id or "",
		), session)

		log.info("AppointmentsService.confirm_appointment: %s CONFIRMED", appointment_id)
		return appointment

	# ------------------------------------------------------------------
	# 4. complete_appointment
	# ------------------------------------------------------------------

	@staticmethod
	def complete_appointment(appointment_id: str, session: Any) -> Any:
		"""Transition CONFIRMED → COMPLETED. Computes duration_minutes from timestamps."""
		from pgappforge.plugins.erp.crm.appointments.models import Appointment
		from pgappforge.plugins.erp.crm.appointments.events import AppointmentCompletedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		appointment = session.execute(
			sa.select(Appointment).where(Appointment.id == appointment_id)
		).scalar_one_or_none()
		if appointment is None:
			raise AppointmentNotFoundError(f"Appointment {appointment_id} not found")
		if appointment.status != "CONFIRMED":
			raise AppointmentStateError(
				f"Cannot complete appointment in status {appointment.status!r}; must be CONFIRMED"
			)

		appointment.status = "COMPLETED"
		session.flush()

		# Compute actual duration from start/end timestamps
		delta = appointment.end_at - appointment.start_at
		duration_minutes = int(delta.total_seconds() / 60)

		emit_event(AppointmentCompletedEvent(
			aggregate_id=appointment.id,
			aggregate_type="Appointment",
			tenant_id=appointment.tenant_id,
			appointment_id=appointment.id,
			duration_minutes=duration_minutes,
		), session)

		log.info(
			"AppointmentsService.complete_appointment: %s COMPLETED duration=%dmin",
			appointment_id, duration_minutes,
		)
		return appointment

	# ------------------------------------------------------------------
	# 5. cancel_appointment
	# ------------------------------------------------------------------

	@staticmethod
	def cancel_appointment(
		appointment_id: str,
		cancelled_by: str,
		reason: str,
		session: Any,
	) -> Any:
		"""Cancel an appointment from any non-terminal status. Emits AppointmentCancelledEvent."""
		from pgappforge.plugins.erp.crm.appointments.models import Appointment
		from pgappforge.plugins.erp.crm.appointments.events import AppointmentCancelledEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		appointment = session.execute(
			sa.select(Appointment).where(Appointment.id == appointment_id)
		).scalar_one_or_none()
		if appointment is None:
			raise AppointmentNotFoundError(f"Appointment {appointment_id} not found")
		if appointment.status in ("COMPLETED", "CANCELLED"):
			raise AppointmentStateError(
				f"Cannot cancel appointment already in status {appointment.status!r}"
			)

		appointment.status = "CANCELLED"
		appointment.cancellation_reason = reason
		appointment.cancelled_by = cancelled_by
		session.flush()

		emit_event(AppointmentCancelledEvent(
			aggregate_id=appointment.id,
			aggregate_type="Appointment",
			tenant_id=appointment.tenant_id,
			appointment_id=appointment.id,
			cancelled_by=cancelled_by,
			reason=reason,
		), session)

		log.info(
			"AppointmentsService.cancel_appointment: %s CANCELLED by %s",
			appointment_id, cancelled_by,
		)
		return appointment

	# ------------------------------------------------------------------
	# 6. send_reminders
	# ------------------------------------------------------------------

	@staticmethod
	def send_reminders(
		hours_before: int,
		session: Any,
		*,
		tenant_id: str | None = None,
	) -> list[Any]:
		"""Find upcoming appointments within hours_before and dispatch reminders.

		Marks reminder_sent=True and emits ReminderSentEvent for each.
		Returns the list of appointments reminded.
		"""
		from pgappforge.plugins.erp.crm.appointments.models import Appointment
		from pgappforge.plugins.erp.crm.appointments.events import ReminderSentEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		now_utc = datetime.now(timezone.utc)
		window_end = now_utc + timedelta(hours=hours_before)

		stmt = sa.select(Appointment).where(
			Appointment.status.in_(["PENDING", "CONFIRMED"]),
			Appointment.reminder_sent.is_(False),
			Appointment.start_at > now_utc,
			Appointment.start_at <= window_end,
		)
		if tenant_id:
			stmt = stmt.where(Appointment.tenant_id == tenant_id)

		upcoming: list[Any] = list(session.execute(stmt).scalars().all())

		for apt in upcoming:
			apt.reminder_sent = True
			session.flush()

			send_at = now_utc.isoformat()
			emit_event(ReminderSentEvent(
				aggregate_id=apt.id,
				aggregate_type="Appointment",
				tenant_id=apt.tenant_id,
				appointment_id=apt.id,
				customer_id=apt.customer_id or "",
				send_at=send_at,
			), session)

			# Non-fatal notification dispatch
			try:
				AppointmentsService._dispatch_reminder(apt)
			except Exception as exc:
				log.warning(
					"AppointmentsService.send_reminders: dispatch for %s failed (non-fatal): %s",
					apt.id, exc,
				)

		log.info(
			"AppointmentsService.send_reminders: %d reminders sent (window=%dh)",
			len(upcoming), hours_before,
		)
		return upcoming

	@staticmethod
	def _dispatch_reminder(appointment: Any) -> None:
		"""Placeholder for actual reminder notification dispatch."""
		log.debug(
			"AppointmentsService._dispatch_reminder: would notify %s for appointment %s at %s",
			appointment.customer_email or appointment.customer_id,
			appointment.id,
			appointment.start_at.isoformat() if appointment.start_at else "?",
		)

	# ------------------------------------------------------------------
	# 7. get_staff_schedule
	# ------------------------------------------------------------------

	@staticmethod
	def get_staff_schedule(
		staff_id: str,
		from_date: date,
		to_date: date,
		session: Any,
	) -> list[Any]:
		"""Return all non-cancelled appointments for a staff member in [from_date, to_date]."""
		from pgappforge.plugins.erp.crm.appointments.models import Appointment

		range_start = datetime.combine(from_date, datetime.min.time(), tzinfo=timezone.utc)
		range_end = datetime.combine(to_date, datetime.max.time(), tzinfo=timezone.utc)

		appointments = list(
			session.execute(
				sa.select(Appointment)
				.where(
					Appointment.staff_id == staff_id,
					Appointment.start_at >= range_start,
					Appointment.start_at <= range_end,
					Appointment.status.notin_(["CANCELLED"]),
				)
				.order_by(Appointment.start_at)
			).scalars().all()
		)

		log.info(
			"AppointmentsService.get_staff_schedule: %d appointments for staff=%s %s→%s",
			len(appointments), staff_id, from_date, to_date,
		)
		return appointments


# ---------------------------------------------------------------------------
# BPM Action registrations
# ---------------------------------------------------------------------------

def _register_bpm_actions() -> None:
	try:
		from pgappforge.plugins.workflow.engine import BPMActionRegistry
	except ImportError:
		return

	@BPMActionRegistry.register(
		"crm.appointments.book",
		"Book appointment from workflow",
	)
	def _bpm_book_appointment(
		record_ctx: dict,
		session: Any,
		service_id: str = "",
		staff_id: str = "",
		start_at: str = "",
		customer_email: str = "",
		customer_name: str = "",
		customer_id: str | None = None,
		customer_phone: str | None = None,
		notes: str | None = None,
		**kw: Any,
	) -> dict:
		tenant_id = record_ctx.get("tenant_id", "")
		try:
			from datetime import datetime, timezone as tz
			start_dt = datetime.fromisoformat(start_at)
			if start_dt.tzinfo is None:
				start_dt = start_dt.replace(tzinfo=tz.utc)
			appointment = AppointmentsService.book_appointment(
				service_id=service_id,
				staff_id=staff_id,
				start_at=start_dt,
				customer_email=customer_email,
				customer_name=customer_name,
				tenant_id=tenant_id,
				session=session,
				customer_id=customer_id,
				customer_phone=customer_phone,
				notes=notes,
			)
			return {
				"status": "ok",
				"appointment_id": appointment.id,
				"booking_ref": appointment.booking_ref,
				"appointment_status": appointment.status,
			}
		except Exception as exc:
			log.warning("bpm crm.appointments.book failed: %s", exc)
			return {"status": "error", "message": str(exc)}


_register_bpm_actions()


__all__ = [
	"AppointmentsService",
	"AppointmentsServiceError",
	"AppointmentNotFoundError",
	"AppointmentStateError",
	"SlotUnavailableError",
]
