from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from pgappforge.plugins.erp.hcm.benefits.events import (
	BenefitClaimAdjudicatedEvent,
	BenefitClaimSubmittedEvent,
	BenefitDeductionsGeneratedEvent,
	BenefitEnrolledEvent,
	BenefitTerminatedEvent,
)
from pgappforge.plugins.erp.hcm.benefits.models import (
	BenefitClaim,
	BenefitDeduction,
	BenefitEnrollment,
	BenefitPlan,
)
from pgappforge.plugins.workflow.engine import BPMActionRegistry

_log = logging.getLogger(__name__)

__all__ = [
	"BenefitsServiceError",
	"EnrollmentNotFoundError",
	"EnrollmentStateError",
	"ClaimNotFoundError",
	"BenefitsService",
]


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class BenefitsServiceError(Exception):
	"""Base error for the Benefits domain."""


class EnrollmentNotFoundError(BenefitsServiceError):
	"""Raised when a requested enrollment does not exist."""


class EnrollmentStateError(BenefitsServiceError):
	"""Raised when an enrollment operation is invalid for the current status."""


class ClaimNotFoundError(BenefitsServiceError):
	"""Raised when a requested claim does not exist."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now_utc() -> datetime:
	return datetime.now(tz=timezone.utc)


def _emit(event: Any, session: Any = None) -> None:
	"""Fire-and-forget event emission.  Swallows if no bus is wired."""
	try:
		from pgappforge.plugins.erp.foundation.events import emit_event
		emit_event(event, session)
	except Exception:  # noqa: BLE001
		_log.debug("Event bus unavailable; event %s not published", type(event).__name__)


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class BenefitsService:
	"""Stateless service layer for HCM Benefits Administration.

	Every method accepts ``session`` as a positional argument so callers
	can pass the SQLAlchemy session explicitly — useful both in Flask-AppBuilder
	views (where ``db.session`` is the norm) and in BPM action callbacks.
	"""

	# ------------------------------------------------------------------
	# Enrollment lifecycle
	# ------------------------------------------------------------------

	def enroll_employee(
		self,
		employee_id: str,
		plan_id: str,
		effective_from: Any,  # date or ISO string
		coverage_tier: str,
		session: Session,
		*,
		tenant_id: str,
		enrolled_by: str | None = None,
	) -> BenefitEnrollment:
		"""Create a PENDING enrollment.

		Raises ``EnrollmentStateError`` if an ACTIVE enrollment for the same
		(tenant, employee, plan) already exists.
		"""
		assert employee_id, "employee_id is required"
		assert plan_id, "plan_id is required"
		assert effective_from, "effective_from is required"
		assert tenant_id, "tenant_id is required"

		existing = session.execute(
			select(BenefitEnrollment).where(
				BenefitEnrollment.tenant_id == tenant_id,
				BenefitEnrollment.employee_id == employee_id,
				BenefitEnrollment.plan_id == plan_id,
				BenefitEnrollment.status == "ACTIVE",
			)
		).scalar_one_or_none()

		if existing is not None:
			raise EnrollmentStateError(
				f"Employee {employee_id} already has an ACTIVE enrollment "
				f"(id={existing.id}) for plan {plan_id}."
			)

		enrollment = BenefitEnrollment(
			tenant_id=tenant_id,
			employee_id=employee_id,
			plan_id=plan_id,
			coverage_tier=coverage_tier,
			status="PENDING",
			effective_from=effective_from,
			enrolled_by=enrolled_by,
			enrolled_at=_now_utc(),
		)
		session.add(enrollment)
		session.flush()

		_emit(
			BenefitEnrolledEvent(
				enrollment_id=enrollment.id,
				employee_id=employee_id,
				plan_id=plan_id,
				tenant_id=tenant_id,
				effective_date=str(effective_from),
			)
		)

		_log.info(
			"Enrollment created: id=%s employee=%s plan=%s tenant=%s",
			enrollment.id, employee_id, plan_id, tenant_id,
		)
		return enrollment

	def activate_enrollment(
		self,
		enrollment_id: str,
		session: Session,
		*,
		tenant_id: str = "",
	) -> BenefitEnrollment:
		"""Transition a PENDING enrollment to ACTIVE."""
		assert enrollment_id, "enrollment_id is required"

		filters = [BenefitEnrollment.id == enrollment_id]
		if tenant_id:
			filters.append(BenefitEnrollment.tenant_id == tenant_id)

		enrollment = session.execute(
			select(BenefitEnrollment).where(*filters)
		).scalar_one_or_none()

		if enrollment is None:
			raise EnrollmentNotFoundError(f"Enrollment {enrollment_id} not found.")

		if enrollment.status != "PENDING":
			raise EnrollmentStateError(
				f"Cannot activate enrollment {enrollment_id}: "
				f"expected status PENDING, got {enrollment.status}."
			)

		enrollment.status = "ACTIVE"
		session.flush()
		_log.info("Enrollment activated: id=%s", enrollment_id)
		return enrollment

	def terminate_enrollment(
		self,
		enrollment_id: str,
		termination_date: Any,
		reason: str,
		session: Session,
		*,
		tenant_id: str = "",
	) -> BenefitEnrollment:
		"""Terminate an ACTIVE enrollment."""
		assert enrollment_id, "enrollment_id is required"
		assert termination_date, "termination_date is required"

		filters = [BenefitEnrollment.id == enrollment_id]
		if tenant_id:
			filters.append(BenefitEnrollment.tenant_id == tenant_id)

		enrollment = session.execute(
			select(BenefitEnrollment).where(*filters)
		).scalar_one_or_none()

		if enrollment is None:
			raise EnrollmentNotFoundError(f"Enrollment {enrollment_id} not found.")

		if enrollment.status != "ACTIVE":
			raise EnrollmentStateError(
				f"Cannot terminate enrollment {enrollment_id}: "
				f"expected status ACTIVE, got {enrollment.status}."
			)

		enrollment.status = "TERMINATED"
		enrollment.effective_to = termination_date
		session.flush()

		_emit(
			BenefitTerminatedEvent(
				enrollment_id=enrollment_id,
				employee_id=enrollment.employee_id,
				reason=reason,
				termination_date=str(termination_date),
			)
		)

		_log.info(
			"Enrollment terminated: id=%s employee=%s reason=%s",
			enrollment_id, enrollment.employee_id, reason,
		)
		return enrollment

	def waive_enrollment(
		self,
		enrollment_id: str,
		reason: str,
		session: Session,
	) -> BenefitEnrollment:
		"""Waive a PENDING enrollment (employee opts out)."""
		assert enrollment_id, "enrollment_id is required"

		enrollment = session.execute(
			select(BenefitEnrollment).where(BenefitEnrollment.id == enrollment_id)
		).scalar_one_or_none()

		if enrollment is None:
			raise EnrollmentNotFoundError(f"Enrollment {enrollment_id} not found.")

		if enrollment.status != "PENDING":
			raise EnrollmentStateError(
				f"Cannot waive enrollment {enrollment_id}: "
				f"expected status PENDING, got {enrollment.status}."
			)

		enrollment.status = "WAIVED"
		enrollment.waiver_reason = reason
		session.flush()
		_log.info("Enrollment waived: id=%s reason=%s", enrollment_id, reason)
		return enrollment

	# ------------------------------------------------------------------
	# Claims
	# ------------------------------------------------------------------

	def submit_claim(
		self,
		enrollment_id: str,
		claim_date: Any,
		claimed_amount_cents: int,
		session: Session,
		*,
		service_date: Any | None = None,
		attachments: list[Any] | None = None,
	) -> BenefitClaim:
		"""Submit a new claim against an ACTIVE enrollment."""
		assert enrollment_id, "enrollment_id is required"
		assert claimed_amount_cents > 0, "claimed_amount_cents must be positive"

		enrollment = session.execute(
			select(BenefitEnrollment).where(BenefitEnrollment.id == enrollment_id)
		).scalar_one_or_none()

		if enrollment is None:
			raise EnrollmentNotFoundError(f"Enrollment {enrollment_id} not found.")

		if enrollment.status != "ACTIVE":
			raise EnrollmentStateError(
				f"Cannot submit claim: enrollment {enrollment_id} is {enrollment.status}, not ACTIVE."
			)

		claim = BenefitClaim(
			tenant_id=enrollment.tenant_id,
			enrollment_id=enrollment_id,
			employee_id=enrollment.employee_id,
			claim_date=claim_date,
			service_date=service_date,
			claimed_amount_cents=claimed_amount_cents,
			status="SUBMITTED",
			attachments=attachments or [],
		)
		session.add(claim)
		session.flush()

		_emit(
			BenefitClaimSubmittedEvent(
				claim_id=claim.id,
				enrollment_id=enrollment_id,
				employee_id=enrollment.employee_id,
				claimed_amount_cents=claimed_amount_cents,
			)
		)

		_log.info(
			"Claim submitted: id=%s enrollment=%s amount_cents=%d",
			claim.id, enrollment_id, claimed_amount_cents,
		)
		return claim

	def adjudicate_claim(
		self,
		claim_id: str,
		decision: str,
		adjudicator_id: str,
		session: Session,
		*,
		approved_amount_cents: int | None = None,
		denial_reason: str | None = None,
	) -> BenefitClaim:
		"""Adjudicate a claim: APPROVED / DENIED / PARTIALLY_APPROVED."""
		assert claim_id, "claim_id is required"
		assert decision in {"APPROVED", "DENIED", "PARTIALLY_APPROVED"}, (
			f"Invalid decision '{decision}'. Must be APPROVED, DENIED, or PARTIALLY_APPROVED."
		)
		assert adjudicator_id, "adjudicator_id is required"

		claim = session.execute(
			select(BenefitClaim).where(BenefitClaim.id == claim_id)
		).scalar_one_or_none()

		if claim is None:
			raise ClaimNotFoundError(f"Claim {claim_id} not found.")

		if claim.status not in {"SUBMITTED", "UNDER_REVIEW"}:
			raise BenefitsServiceError(
				f"Cannot adjudicate claim {claim_id}: "
				f"current status is {claim.status}, expected SUBMITTED or UNDER_REVIEW."
			)

		claim.status = decision
		if approved_amount_cents is not None:
			claim.approved_amount_cents = approved_amount_cents
		claim.adjudicator_id = adjudicator_id
		claim.adjudicated_at = _now_utc()
		if denial_reason:
			claim.denial_reason = denial_reason
		session.flush()

		_emit(
			BenefitClaimAdjudicatedEvent(
				claim_id=claim_id,
				decision=decision,
				approved_amount_cents=approved_amount_cents,
				adjudicator_id=adjudicator_id,
			)
		)

		_log.info(
			"Claim adjudicated: id=%s decision=%s adjudicator=%s",
			claim_id, decision, adjudicator_id,
		)
		return claim

	# ------------------------------------------------------------------
	# Payroll deductions
	# ------------------------------------------------------------------

	def generate_deductions(
		self,
		period: str,
		tenant_id: str,
		session: Session,
	) -> list[BenefitDeduction]:
		"""Generate payroll deductions for all ACTIVE enrollments in a period.

		Skips any enrollment where a deduction for the period already exists
		(guarded by the UNIQUE constraint).  Returns the list of newly created
		``BenefitDeduction`` rows.
		"""
		assert period, "period is required (e.g. '2025-01')"
		assert tenant_id, "tenant_id is required"

		active_enrollments = session.execute(
			select(BenefitEnrollment).where(
				BenefitEnrollment.tenant_id == tenant_id,
				BenefitEnrollment.status == "ACTIVE",
			)
		).scalars().all()

		created: list[BenefitDeduction] = []
		total_cents = 0

		for enrollment in active_enrollments:
			plan: BenefitPlan | None = session.execute(
				select(BenefitPlan).where(BenefitPlan.id == enrollment.plan_id)
			).scalar_one_or_none()

			if plan is None:
				_log.warning("Plan %s not found for enrollment %s — skipping", enrollment.plan_id, enrollment.id)
				continue

			# Resolve amounts from tiered or flat-rate premiums
			tier = enrollment.coverage_tier or "SINGLE"
			tiers: dict = plan.coverage_tiers or {}

			if tier in tiers and isinstance(tiers[tier], dict):
				employee_cents: int = int(tiers[tier].get("employee_cents", 0))
				employer_cents: int = int(tiers[tier].get("employer_cents", 0))
			else:
				employee_cents = int(plan.employee_premium_cents or 0)
				employer_cents = int(plan.employer_premium_cents or 0)

			deduction = BenefitDeduction(
				tenant_id=tenant_id,
				enrollment_id=enrollment.id,
				employee_id=enrollment.employee_id,
				period=period,
				employee_deduction_cents=employee_cents,
				employer_contribution_cents=employer_cents,
				status="PENDING",
			)
			try:
				session.add(deduction)
				with session.begin_nested():
					session.flush()
				created.append(deduction)
				total_cents += employee_cents + employer_cents
			except IntegrityError:
				_log.debug(
					"Deduction for enrollment=%s period=%s already exists — skipped",
					enrollment.id, period,
				)

		_emit(
			BenefitDeductionsGeneratedEvent(
				payrun_id="",
				period=period,
				count=len(created),
				total_cents=total_cents,
			)
		)

		_log.info(
			"Deductions generated: period=%s tenant=%s count=%d total_cents=%d",
			period, tenant_id, len(created), total_cents,
		)
		return created

	def mark_deductions_processed(
		self,
		period: str,
		payrun_id: str,
		tenant_id: str,
		session: Session,
	) -> int:
		"""Mark all PENDING deductions for a period/tenant as PROCESSED.

		Returns the number of rows updated.
		"""
		assert period, "period is required"
		assert payrun_id, "payrun_id is required"
		assert tenant_id, "tenant_id is required"

		pending = session.execute(
			select(BenefitDeduction).where(
				BenefitDeduction.tenant_id == tenant_id,
				BenefitDeduction.period == period,
				BenefitDeduction.status == "PENDING",
			)
		).scalars().all()

		now = _now_utc()
		for deduction in pending:
			deduction.status = "PROCESSED"
			deduction.payrun_id = payrun_id
			deduction.processed_at = now

		session.flush()
		count = len(pending)
		_log.info(
			"Deductions marked processed: period=%s payrun=%s tenant=%s count=%d",
			period, payrun_id, tenant_id, count,
		)
		return count

	# ------------------------------------------------------------------
	# Reporting / summary
	# ------------------------------------------------------------------

	def get_employee_summary(
		self,
		employee_id: str,
		tenant_id: str,
		session: Session,
	) -> dict[str, Any]:
		"""Return a summary dict for an employee's benefits position.

		Keys:
		- ``enrollments``: list of dicts for each ACTIVE enrollment
		- ``claims_ytd``: {count, total_cents}
		- ``deductions_ytd``: {total_employee_cents, total_employer_cents}
		"""
		assert employee_id, "employee_id is required"
		assert tenant_id, "tenant_id is required"

		from datetime import date
		current_year = str(date.today().year)

		# Active enrollments
		enrollments = session.execute(
			select(BenefitEnrollment).where(
				BenefitEnrollment.tenant_id == tenant_id,
				BenefitEnrollment.employee_id == employee_id,
				BenefitEnrollment.status == "ACTIVE",
			)
		).scalars().all()

		enrollment_list = [
			{
				"enrollment_id": e.id,
				"plan_id": e.plan_id,
				"coverage_tier": e.coverage_tier,
				"effective_from": str(e.effective_from),
			}
			for e in enrollments
		]

		# Claims YTD — all claims whose claim_date falls in the current year
		claims_ytd = session.execute(
			select(BenefitClaim).where(
				BenefitClaim.tenant_id == tenant_id,
				BenefitClaim.employee_id == employee_id,
				sa_func_year_filter(BenefitClaim.claim_date, current_year),
			)
		).scalars().all()

		claims_total = sum(c.claimed_amount_cents for c in claims_ytd)

		# Deductions YTD — periods starting with current year (e.g. "2025-")
		deductions_ytd = session.execute(
			select(BenefitDeduction).where(
				BenefitDeduction.tenant_id == tenant_id,
				BenefitDeduction.employee_id == employee_id,
				BenefitDeduction.period.like(f"{current_year}-%"),
			)
		).scalars().all()

		total_emp_ded = sum(d.employee_deduction_cents for d in deductions_ytd)
		total_er_contrib = sum(d.employer_contribution_cents for d in deductions_ytd)

		return {
			"enrollments": enrollment_list,
			"claims_ytd": {
				"count": len(claims_ytd),
				"total_cents": claims_total,
			},
			"deductions_ytd": {
				"total_employee_cents": total_emp_ded,
				"total_employer_cents": total_er_contrib,
			},
		}


# ---------------------------------------------------------------------------
# SQLAlchemy helper for year filtering without raw SQL string interpolation
# ---------------------------------------------------------------------------

import sqlalchemy as _sa  # noqa: E402


def sa_func_year_filter(column: Any, year_str: str) -> Any:
	"""Return a SQLAlchemy WHERE clause matching rows in *year_str* (e.g. '2025')."""
	return _sa.extract("year", column) == int(year_str)


# ---------------------------------------------------------------------------
# BPM Action Registry
# ---------------------------------------------------------------------------


@BPMActionRegistry.register("hcm.benefits.enroll", "Enroll employee in benefit plan")
def _bpm_enroll(
	record_ctx: Any,
	session: Session,
	employee_id: str,
	plan_id: str,
	effective_from: Any,
	tenant_id: str,
	**kw: Any,
) -> BenefitEnrollment:
	svc = BenefitsService()
	return svc.enroll_employee(
		employee_id,
		plan_id,
		effective_from,
		kw.get("coverage_tier", "SINGLE"),
		session,
		tenant_id=tenant_id,
		enrolled_by=kw.get("enrolled_by"),
	)


@BPMActionRegistry.register("hcm.benefits.terminate", "Terminate employee benefit enrollment")
def _bpm_terminate(
	record_ctx: Any,
	session: Session,
	enrollment_id: str,
	termination_date: Any,
	reason: str = "terminated",
	**kw: Any,
) -> BenefitEnrollment:
	svc = BenefitsService()
	return svc.terminate_enrollment(enrollment_id, termination_date, reason, session)
