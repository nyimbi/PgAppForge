from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from pgappforge.plugins.erp.hcm.wellness.events import (
	EapReferralCreatedEvent,
	WellnessCheckInEvent,
	WellnessProgramEnrolledEvent,
	WellnessReportGeneratedEvent,
)
from pgappforge.plugins.erp.hcm.wellness.models import (
	EapReferral,
	WellnessCheckIn,
	WellnessEnrollment,
	WellnessProgram,
)
from pgappforge.plugins.workflow.engine import BPMActionRegistry

_log = logging.getLogger(__name__)

__all__ = [
	"WellnessServiceError",
	"WellnessNotFoundError",
	"WellnessStateError",
	"WellnessService",
]


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class WellnessServiceError(Exception):
	"""Base error for the Employee Wellness domain."""


class WellnessNotFoundError(WellnessServiceError):
	"""Raised when a requested wellness resource does not exist."""


class WellnessStateError(WellnessServiceError):
	"""Raised when an operation is invalid for the current state."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Thresholds for automatic flag detection
_BURNOUT_SCORE_THRESHOLD = 3
_BURNOUT_ENERGY_THRESHOLD = 2
_HIGH_STRESS_THRESHOLD = 8


def _now_utc() -> datetime:
	return datetime.now(tz=timezone.utc)


def _emit(event: Any) -> None:
	"""Fire-and-forget event emission. Swallows if no bus is wired."""
	try:
		from pgappforge.plugins.erp.foundation.events import emit_event
		emit_event(event)
	except Exception:  # noqa: BLE001
		_log.debug("Event bus unavailable; event %s not published", type(event).__name__)


def _compute_flags(
	wellbeing_score: int,
	energy_level: int | None,
	stress_level: int | None,
) -> list[str]:
	"""Derive automatic flags from numeric scores."""
	flags: list[str] = []
	if wellbeing_score <= _BURNOUT_SCORE_THRESHOLD:
		flags.append("BURNOUT_RISK")
	if energy_level is not None and energy_level <= _BURNOUT_ENERGY_THRESHOLD:
		if "BURNOUT_RISK" not in flags:
			flags.append("BURNOUT_RISK")
	if stress_level is not None and stress_level >= _HIGH_STRESS_THRESHOLD:
		flags.append("HIGH_STRESS")
	return flags


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class WellnessService:
	"""Stateless service layer for HCM Employee Wellness.

	Every method accepts ``session`` as a positional argument.
	"""

	# ------------------------------------------------------------------
	# Enrollment lifecycle
	# ------------------------------------------------------------------

	def enroll_employee(
		self,
		employee_id: str,
		program_id: str,
		tenant_id: str,
		session: Session,
	) -> WellnessEnrollment:
		"""Enroll an employee in a wellness program.

		Raises ``WellnessNotFoundError`` if program not found.
		Raises ``WellnessStateError`` if program is not ACTIVE or employee is already enrolled.
		"""
		assert employee_id, "employee_id is required"
		assert program_id, "program_id is required"
		assert tenant_id, "tenant_id is required"

		program = session.execute(
			select(WellnessProgram).where(
				WellnessProgram.id == program_id,
				WellnessProgram.tenant_id == tenant_id,
			)
		).scalar_one_or_none()

		if program is None:
			raise WellnessNotFoundError(
				f"WellnessProgram {program_id} not found for tenant {tenant_id}."
			)

		if program.status != "ACTIVE":
			raise WellnessStateError(
				f"Cannot enroll in program {program_id}: status is {program.status}, expected ACTIVE."
			)

		existing = session.execute(
			select(WellnessEnrollment).where(
				WellnessEnrollment.employee_id == employee_id,
				WellnessEnrollment.program_id == program_id,
				WellnessEnrollment.status == "ACTIVE",
			)
		).scalar_one_or_none()

		if existing is not None:
			raise WellnessStateError(
				f"Employee {employee_id} already has an ACTIVE enrollment "
				f"(id={existing.id}) in program {program_id}."
			)

		# Check participant cap
		if program.max_participants is not None:
			active_count = session.execute(
				select(WellnessEnrollment).where(
					WellnessEnrollment.program_id == program_id,
					WellnessEnrollment.status == "ACTIVE",
				)
			).scalars().all()
			if len(active_count) >= program.max_participants:
				raise WellnessStateError(
					f"Program {program_id} has reached its maximum participant cap "
					f"of {program.max_participants}."
				)

		enrollment = WellnessEnrollment(
			tenant_id=tenant_id,
			employee_id=employee_id,
			program_id=program_id,
			enrolled_at=_now_utc(),
			status="ACTIVE",
		)
		session.add(enrollment)
		session.flush()

		_emit(
			WellnessProgramEnrolledEvent(
				enrollment_id=enrollment.id,
				employee_id=employee_id,
				program_id=program_id,
			)
		)

		_log.info(
			"WellnessEnrollment created: id=%s employee=%s program=%s",
			enrollment.id, employee_id, program_id,
		)
		return enrollment

	def complete_enrollment(
		self,
		enrollment_id: str,
		session: Session,
	) -> WellnessEnrollment:
		"""Transition an ACTIVE enrollment to COMPLETED.

		Raises ``WellnessNotFoundError`` if enrollment not found.
		Raises ``WellnessStateError`` if enrollment is not ACTIVE.
		"""
		assert enrollment_id, "enrollment_id is required"

		enrollment = session.execute(
			select(WellnessEnrollment).where(WellnessEnrollment.id == enrollment_id)
		).scalar_one_or_none()

		if enrollment is None:
			raise WellnessNotFoundError(f"WellnessEnrollment {enrollment_id} not found.")

		if enrollment.status != "ACTIVE":
			raise WellnessStateError(
				f"Cannot complete enrollment {enrollment_id}: "
				f"expected ACTIVE, got {enrollment.status}."
			)

		enrollment.status = "COMPLETED"
		enrollment.completed_at = _now_utc()
		session.flush()

		_log.info("WellnessEnrollment completed: id=%s", enrollment_id)
		return enrollment

	# ------------------------------------------------------------------
	# Check-ins
	# ------------------------------------------------------------------

	def record_checkin(
		self,
		employee_id: str,
		check_in_date: date,
		wellbeing_score: int,
		tenant_id: str,
		session: Session,
		*,
		energy_level: int | None = None,
		stress_level: int | None = None,
		notes: str | None = None,
		anonymous: bool = False,
	) -> WellnessCheckIn:
		"""Create or update a wellness check-in for an employee on a given date.

		Automatically computes flags from score thresholds and emits
		``WellnessCheckInEvent``.

		``wellbeing_score`` must be in range 1-10.
		``energy_level`` and ``stress_level`` are optional 1-10 integers.
		"""
		assert employee_id, "employee_id is required"
		assert tenant_id, "tenant_id is required"
		assert check_in_date, "check_in_date is required"
		assert 1 <= wellbeing_score <= 10, (
			f"wellbeing_score must be between 1 and 10, got {wellbeing_score}"
		)
		if energy_level is not None:
			assert 1 <= energy_level <= 10, (
				f"energy_level must be between 1 and 10, got {energy_level}"
			)
		if stress_level is not None:
			assert 1 <= stress_level <= 10, (
				f"stress_level must be between 1 and 10, got {stress_level}"
			)

		flags = _compute_flags(wellbeing_score, energy_level, stress_level)

		existing = session.execute(
			select(WellnessCheckIn).where(
				WellnessCheckIn.employee_id == employee_id,
				WellnessCheckIn.check_in_date == check_in_date,
			)
		).scalar_one_or_none()

		if existing is not None:
			existing.wellbeing_score = wellbeing_score
			existing.energy_level = energy_level
			existing.stress_level = stress_level
			existing.flags = flags
			existing.notes = notes
			existing.anonymous = anonymous
			session.flush()
			checkin = existing
			_log.info(
				"WellnessCheckIn updated: id=%s employee=%s date=%s score=%d flags=%s",
				checkin.id, employee_id, check_in_date, wellbeing_score, flags,
			)
		else:
			checkin = WellnessCheckIn(
				tenant_id=tenant_id,
				employee_id=employee_id,
				check_in_date=check_in_date,
				wellbeing_score=wellbeing_score,
				energy_level=energy_level,
				stress_level=stress_level,
				flags=flags,
				notes=notes,
				anonymous=anonymous,
			)
			session.add(checkin)
			session.flush()
			_log.info(
				"WellnessCheckIn created: id=%s employee=%s date=%s score=%d flags=%s",
				checkin.id, employee_id, check_in_date, wellbeing_score, flags,
			)

		_emit(
			WellnessCheckInEvent(
				checkin_id=checkin.id,
				employee_id=employee_id,
				wellbeing_score=wellbeing_score,
				flags=flags,
			)
		)

		return checkin

	# ------------------------------------------------------------------
	# EAP Referrals
	# ------------------------------------------------------------------

	def create_eap_referral(
		self,
		employee_id: str,
		category: str,
		tenant_id: str,
		session: Session,
		*,
		provider: str | None = None,
		notes: str | None = None,
	) -> EapReferral:
		"""Create an EAP referral for an employee.

		``category`` must be one of: MENTAL_HEALTH, SUBSTANCE, FINANCIAL,
		FAMILY, LEGAL, GRIEF, OTHER.
		"""
		assert employee_id, "employee_id is required"
		assert category, "category is required"
		assert tenant_id, "tenant_id is required"

		valid_categories = {
			"MENTAL_HEALTH", "SUBSTANCE", "FINANCIAL",
			"FAMILY", "LEGAL", "GRIEF", "OTHER",
		}
		assert category in valid_categories, (
			f"Invalid EAP category '{category}'. Must be one of: {sorted(valid_categories)}."
		)

		referral = EapReferral(
			tenant_id=tenant_id,
			employee_id=employee_id,
			category=category,
			status="OPEN",
			opened_at=_now_utc(),
			provider=provider,
			notes=notes,
		)
		session.add(referral)
		session.flush()

		_emit(
			EapReferralCreatedEvent(
				referral_id=referral.id,
				employee_id=employee_id,
				category=category,
			)
		)

		_log.info(
			"EapReferral created: id=%s employee=%s category=%s",
			referral.id, employee_id, category,
		)
		return referral

	# ------------------------------------------------------------------
	# Analytics
	# ------------------------------------------------------------------

	def get_wellbeing_trend(
		self,
		employee_id: str,
		from_date: date,
		to_date: date,
		tenant_id: str,
		session: Session,
	) -> dict[str, Any]:
		"""Return wellbeing trend analysis for an employee over a date range.

		Keys: ``avg_wellbeing``, ``avg_energy``, ``avg_stress``, ``trend``,
		``flag_frequency`` (dict of flag→count), ``checkins_count``.

		``trend`` is IMPROVING / STABLE / DECLINING based on comparing
		the first-half vs second-half average wellbeing scores.
		"""
		assert employee_id, "employee_id is required"
		assert tenant_id, "tenant_id is required"

		checkins = session.execute(
			select(WellnessCheckIn).where(
				WellnessCheckIn.employee_id == employee_id,
				WellnessCheckIn.check_in_date >= from_date,
				WellnessCheckIn.check_in_date <= to_date,
			).order_by(WellnessCheckIn.check_in_date.asc())
		).scalars().all()

		if not checkins:
			return {
				"avg_wellbeing": None,
				"avg_energy": None,
				"avg_stress": None,
				"trend": "STABLE",
				"flag_frequency": {},
				"checkins_count": 0,
			}

		scores = [c.wellbeing_score for c in checkins]
		energy_vals = [c.energy_level for c in checkins if c.energy_level is not None]
		stress_vals = [c.stress_level for c in checkins if c.stress_level is not None]

		avg_wellbeing = round(sum(scores) / len(scores), 2)
		avg_energy = round(sum(energy_vals) / len(energy_vals), 2) if energy_vals else None
		avg_stress = round(sum(stress_vals) / len(stress_vals), 2) if stress_vals else None

		# Trend: split into halves
		mid = len(scores) // 2
		if mid > 0:
			first_half_avg = sum(scores[:mid]) / mid
			second_half_avg = sum(scores[mid:]) / len(scores[mid:])
			diff = second_half_avg - first_half_avg
			if diff >= 0.5:
				trend = "IMPROVING"
			elif diff <= -0.5:
				trend = "DECLINING"
			else:
				trend = "STABLE"
		else:
			trend = "STABLE"

		# Flag frequency
		flag_freq: dict[str, int] = {}
		for c in checkins:
			for flag in (c.flags or []):
				flag_freq[flag] = flag_freq.get(flag, 0) + 1

		return {
			"avg_wellbeing": avg_wellbeing,
			"avg_energy": avg_energy,
			"avg_stress": avg_stress,
			"trend": trend,
			"flag_frequency": flag_freq,
			"checkins_count": len(checkins),
		}

	def get_org_wellness_summary(
		self,
		tenant_id: str,
		session: Session,
		*,
		entity_id: str | None = None,
	) -> dict[str, Any]:
		"""Return aggregate wellness stats for the organisation.

		Keys: ``avg_wellbeing``, ``total_checkins``, ``high_risk_count``,
		``active_enrollments``, ``programs_active``, ``eap_open_count``.
		"""
		assert tenant_id, "tenant_id is required"

		checkin_query = select(WellnessCheckIn).where(
			WellnessCheckIn.tenant_id == tenant_id,
		)
		checkins = session.execute(checkin_query).scalars().all()

		total_checkins = len(checkins)
		avg_wellbeing = (
			round(sum(c.wellbeing_score for c in checkins) / total_checkins, 2)
			if total_checkins > 0
			else None
		)
		high_risk_count = sum(
			1 for c in checkins if "BURNOUT_RISK" in (c.flags or [])
		)

		active_enrollments = session.execute(
			select(WellnessEnrollment).where(
				WellnessEnrollment.tenant_id == tenant_id,
				WellnessEnrollment.status == "ACTIVE",
			)
		).scalars().all()

		programs_active = session.execute(
			select(WellnessProgram).where(
				WellnessProgram.tenant_id == tenant_id,
				WellnessProgram.status == "ACTIVE",
			)
		).scalars().all()

		eap_open = session.execute(
			select(EapReferral).where(
				EapReferral.tenant_id == tenant_id,
				EapReferral.status.in_(["OPEN", "IN_PROGRESS"]),
			)
		).scalars().all()

		return {
			"avg_wellbeing": avg_wellbeing,
			"total_checkins": total_checkins,
			"high_risk_count": high_risk_count,
			"active_enrollments": len(active_enrollments),
			"programs_active": len(programs_active),
			"eap_open_count": len(eap_open),
		}

	def generate_wellness_report(
		self,
		tenant_id: str,
		period: str,
		session: Session,
	) -> dict[str, Any]:
		"""Compile org-level wellness stats for a period and emit ``WellnessReportGeneratedEvent``.

		``period`` is a free-form string, e.g. "2025-Q1" or "2025-05".

		Returns the compiled summary dict.
		"""
		assert tenant_id, "tenant_id is required"
		assert period, "period is required"

		summary = self.get_org_wellness_summary(tenant_id, session)
		summary["period"] = period
		summary["generated_at"] = _now_utc().isoformat()

		_emit(
			WellnessReportGeneratedEvent(
				tenant_id=tenant_id,
				period=period,
				summary=summary,
			)
		)

		_log.info(
			"WellnessReport generated: tenant=%s period=%s", tenant_id, period
		)
		return summary


# ---------------------------------------------------------------------------
# BPM Action Registry
# ---------------------------------------------------------------------------


@BPMActionRegistry.register("hcm.wellness.record_checkin", "Record employee wellness check-in")
def _bpm_record_checkin(
	record_ctx: Any,
	session: Session,
	employee_id: str,
	check_in_date: date,
	wellbeing_score: int,
	tenant_id: str,
	**kw: Any,
) -> WellnessCheckIn:
	svc = WellnessService()
	return svc.record_checkin(
		employee_id,
		check_in_date,
		wellbeing_score,
		tenant_id,
		session,
		energy_level=kw.get("energy_level"),
		stress_level=kw.get("stress_level"),
		notes=kw.get("notes"),
		anonymous=kw.get("anonymous", False),
	)
