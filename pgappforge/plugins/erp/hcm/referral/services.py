from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from pgappforge.plugins.erp.hcm.referral.events import (
	ReferralExpiredEvent,
	ReferralHiredEvent,
	ReferralRewardPaidEvent,
	ReferralSubmittedEvent,
)
from pgappforge.plugins.erp.hcm.referral.models import (
	ReferralProgram,
	ReferralReward,
	ReferralSubmission,
)
from pgappforge.plugins.workflow.engine import BPMActionRegistry

_log = logging.getLogger(__name__)

__all__ = [
	"ReferralServiceError",
	"ReferralNotFoundError",
	"ReferralStateError",
	"ReferralService",
]


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class ReferralServiceError(Exception):
	"""Base error for the Employee Referrals domain."""


class ReferralNotFoundError(ReferralServiceError):
	"""Raised when a requested referral resource does not exist."""


class ReferralStateError(ReferralServiceError):
	"""Raised when an operation is invalid for the current state."""


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_TERMINAL_STATUSES = frozenset({"HIRED", "REJECTED", "WITHDRAWN", "EXPIRED"})
_VALID_TRANSITIONS: dict[str, set[str]] = {
	"SUBMITTED":    {"SCREENING", "REJECTED", "WITHDRAWN", "EXPIRED"},
	"SCREENING":    {"INTERVIEWING", "REJECTED", "WITHDRAWN", "EXPIRED"},
	"INTERVIEWING": {"OFFERED", "REJECTED", "WITHDRAWN", "EXPIRED"},
	"OFFERED":      {"HIRED", "REJECTED", "WITHDRAWN", "EXPIRED"},
	"HIRED":        set(),
	"REJECTED":     set(),
	"WITHDRAWN":    set(),
	"EXPIRED":      set(),
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now_utc() -> datetime:
	return datetime.now(tz=timezone.utc)


def _emit(event: Any) -> None:
	"""Fire-and-forget event emission. Swallows if no bus is wired."""
	try:
		from pgappforge.plugins.erp.foundation.events import emit_event
		emit_event(event)
	except Exception:  # noqa: BLE001
		_log.debug("Event bus unavailable; event %s not published", type(event).__name__)


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class ReferralService:
	"""Stateless service layer for HCM Employee Referrals.

	Every method accepts ``session`` as a positional argument so callers
	can pass the SQLAlchemy session explicitly.
	"""

	# ------------------------------------------------------------------
	# Submission lifecycle
	# ------------------------------------------------------------------

	def submit_referral(
		self,
		referrer_id: str,
		program_id: str,
		candidate_name: str,
		candidate_email: str,
		tenant_id: str,
		session: Session,
		*,
		position: str | None = None,
		resume_url: str | None = None,
		notes: str | None = None,
	) -> ReferralSubmission:
		"""Create a new referral submission.

		Raises ``ReferralNotFoundError`` if the program does not exist.
		Raises ``ReferralStateError`` if the program is not ACTIVE.
		"""
		assert referrer_id, "referrer_id is required"
		assert program_id, "program_id is required"
		assert candidate_name, "candidate_name is required"
		assert candidate_email, "candidate_email is required"
		assert tenant_id, "tenant_id is required"

		program = session.execute(
			select(ReferralProgram).where(
				ReferralProgram.id == program_id,
				ReferralProgram.tenant_id == tenant_id,
			)
		).scalar_one_or_none()

		if program is None:
			raise ReferralNotFoundError(
				f"ReferralProgram {program_id} not found for tenant {tenant_id}."
			)

		if program.status != "ACTIVE":
			raise ReferralStateError(
				f"Program {program_id} is {program.status}, not ACTIVE. "
				"Referrals cannot be submitted to inactive programs."
			)

		# Check position eligibility if program restricts positions
		eligible_positions: list[str] = program.eligible_positions or []
		if eligible_positions and position and position not in eligible_positions:
			raise ReferralStateError(
				f"Position '{position}' is not eligible for program {program_id}. "
				f"Eligible: {eligible_positions}."
			)

		submission = ReferralSubmission(
			tenant_id=tenant_id,
			referrer_id=referrer_id,
			program_id=program_id,
			candidate_name=candidate_name,
			candidate_email=candidate_email,
			position=position,
			resume_url=resume_url,
			notes=notes,
			status="SUBMITTED",
			submitted_at=_now_utc(),
			reward_eligible=False,
		)
		session.add(submission)
		session.flush()

		_emit(
			ReferralSubmittedEvent(
				referral_id=submission.id,
				referrer_id=referrer_id,
				candidate_name=candidate_name,
				position_id=position or "",
			)
		)

		_log.info(
			"ReferralSubmission created: id=%s referrer=%s candidate=%s program=%s",
			submission.id, referrer_id, candidate_name, program_id,
		)
		return submission

	def update_status(
		self,
		submission_id: str,
		new_status: str,
		session: Session,
		*,
		hired_at: datetime | None = None,
	) -> ReferralSubmission:
		"""Update submission status via the defined state machine.

		On HIRED: evaluates reward conditions and creates a ``ReferralReward``
		if the referrer is eligible, then emits ``ReferralHiredEvent``.

		On EXPIRED: emits ``ReferralExpiredEvent``.

		Raises ``ReferralNotFoundError`` if submission not found.
		Raises ``ReferralStateError`` if the transition is invalid.
		"""
		assert submission_id, "submission_id is required"
		assert new_status, "new_status is required"

		submission = session.execute(
			select(ReferralSubmission).where(ReferralSubmission.id == submission_id)
		).scalar_one_or_none()

		if submission is None:
			raise ReferralNotFoundError(f"ReferralSubmission {submission_id} not found.")

		allowed = _VALID_TRANSITIONS.get(submission.status, set())
		if new_status not in allowed:
			raise ReferralStateError(
				f"Cannot transition submission {submission_id} from "
				f"{submission.status!r} to {new_status!r}. "
				f"Allowed transitions: {sorted(allowed) or 'none (terminal state)'}."
			)

		submission.status = new_status

		if new_status == "HIRED":
			submission.hired_at = hired_at or _now_utc()
			reward_amount = self._evaluate_reward_eligibility(submission, session)
			if reward_amount is not None:
				submission.reward_eligible = True
				reward = self._create_reward(submission, reward_amount, session)
				_emit(
					ReferralHiredEvent(
						referral_id=submission_id,
						referrer_id=submission.referrer_id,
						candidate_id="",  # candidate employee id resolved externally
						reward_amount_cents=reward.reward_amount_cents,
					)
				)
			else:
				_emit(
					ReferralHiredEvent(
						referral_id=submission_id,
						referrer_id=submission.referrer_id,
						candidate_id="",
						reward_amount_cents=0,
					)
				)

		elif new_status == "EXPIRED":
			_emit(
				ReferralExpiredEvent(
					referral_id=submission_id,
					referrer_id=submission.referrer_id,
				)
			)

		session.flush()
		_log.info(
			"ReferralSubmission status updated: id=%s status=%s",
			submission_id, new_status,
		)
		return submission

	# ------------------------------------------------------------------
	# Reward management
	# ------------------------------------------------------------------

	def approve_reward(
		self,
		reward_id: str,
		approver_id: str,
		session: Session,
	) -> ReferralReward:
		"""Approve a PENDING reward.

		Raises ``ReferralNotFoundError`` if reward not found.
		Raises ``ReferralStateError`` if reward is not PENDING.
		"""
		assert reward_id, "reward_id is required"
		assert approver_id, "approver_id is required"

		reward = session.execute(
			select(ReferralReward).where(ReferralReward.id == reward_id)
		).scalar_one_or_none()

		if reward is None:
			raise ReferralNotFoundError(f"ReferralReward {reward_id} not found.")

		if reward.status != "PENDING":
			raise ReferralStateError(
				f"Cannot approve reward {reward_id}: "
				f"expected PENDING, got {reward.status}."
			)

		reward.status = "APPROVED"
		reward.approved_by = approver_id
		reward.approved_at = _now_utc()
		session.flush()

		_log.info(
			"ReferralReward approved: id=%s approver=%s", reward_id, approver_id
		)
		return reward

	def mark_reward_paid(
		self,
		reward_id: str,
		payment_ref: str,
		paid_at: datetime,
		session: Session,
	) -> ReferralReward:
		"""Mark an APPROVED reward as PAID and emit ``ReferralRewardPaidEvent``.

		Raises ``ReferralNotFoundError`` if reward not found.
		Raises ``ReferralStateError`` if reward is not APPROVED.
		"""
		assert reward_id, "reward_id is required"
		assert payment_ref, "payment_ref is required"
		assert paid_at, "paid_at is required"

		reward = session.execute(
			select(ReferralReward).where(ReferralReward.id == reward_id)
		).scalar_one_or_none()

		if reward is None:
			raise ReferralNotFoundError(f"ReferralReward {reward_id} not found.")

		if reward.status != "APPROVED":
			raise ReferralStateError(
				f"Cannot mark reward {reward_id} as paid: "
				f"expected APPROVED, got {reward.status}."
			)

		reward.status = "PAID"
		reward.payment_ref = payment_ref
		reward.paid_at = paid_at
		session.flush()

		_emit(
			ReferralRewardPaidEvent(
				referral_id=reward.submission_id,
				referrer_id=reward.referrer_id,
				amount_cents=reward.reward_amount_cents,
				payment_date=paid_at.date().isoformat(),
			)
		)

		_log.info(
			"ReferralReward paid: id=%s ref=%s amount_cents=%d",
			reward_id, payment_ref, reward.reward_amount_cents,
		)
		return reward

	# ------------------------------------------------------------------
	# Analytics
	# ------------------------------------------------------------------

	def get_referrer_stats(
		self,
		referrer_id: str,
		tenant_id: str,
		session: Session,
	) -> dict[str, Any]:
		"""Return referral statistics for a single referrer.

		Keys: ``submissions``, ``hired``, ``conversion_rate``,
		``rewards_paid_cents``, ``pending_rewards_cents``.
		"""
		assert referrer_id, "referrer_id is required"
		assert tenant_id, "tenant_id is required"

		submissions = session.execute(
			select(ReferralSubmission).where(
				ReferralSubmission.tenant_id == tenant_id,
				ReferralSubmission.referrer_id == referrer_id,
			)
		).scalars().all()

		total = len(submissions)
		hired = sum(1 for s in submissions if s.status == "HIRED")
		conversion_rate = round(hired / total * 100, 2) if total > 0 else 0.0

		submission_ids = [s.id for s in submissions]
		rewards: list[ReferralReward] = []
		if submission_ids:
			rewards = session.execute(
				select(ReferralReward).where(
					ReferralReward.submission_id.in_(submission_ids)
				)
			).scalars().all()

		rewards_paid_cents = sum(
			r.reward_amount_cents for r in rewards if r.status == "PAID"
		)
		pending_rewards_cents = sum(
			r.reward_amount_cents for r in rewards if r.status in {"PENDING", "APPROVED"}
		)

		return {
			"submissions": total,
			"hired": hired,
			"conversion_rate": conversion_rate,
			"rewards_paid_cents": rewards_paid_cents,
			"pending_rewards_cents": pending_rewards_cents,
		}

	def get_program_analytics(
		self,
		program_id: str,
		session: Session,
	) -> dict[str, Any]:
		"""Return aggregated analytics for a referral program.

		Keys: ``total_submissions``, ``by_status``, ``conversion_rate``,
		``total_rewards_committed_cents``.
		"""
		assert program_id, "program_id is required"

		submissions = session.execute(
			select(ReferralSubmission).where(
				ReferralSubmission.program_id == program_id,
			)
		).scalars().all()

		total = len(submissions)
		hired = sum(1 for s in submissions if s.status == "HIRED")
		conversion_rate = round(hired / total * 100, 2) if total > 0 else 0.0

		by_status: dict[str, int] = {}
		for s in submissions:
			by_status[s.status] = by_status.get(s.status, 0) + 1

		submission_ids = [s.id for s in submissions]
		total_rewards_committed_cents = 0
		if submission_ids:
			rewards = session.execute(
				select(ReferralReward).where(
					ReferralReward.submission_id.in_(submission_ids),
					ReferralReward.status.in_(["PENDING", "APPROVED", "PAID"]),
				)
			).scalars().all()
			total_rewards_committed_cents = sum(r.reward_amount_cents for r in rewards)

		return {
			"total_submissions": total,
			"by_status": by_status,
			"conversion_rate": conversion_rate,
			"total_rewards_committed_cents": total_rewards_committed_cents,
		}

	# ------------------------------------------------------------------
	# Internal helpers
	# ------------------------------------------------------------------

	def _evaluate_reward_eligibility(
		self,
		submission: ReferralSubmission,
		session: Session,
	) -> int | None:
		"""Return reward_amount_cents if eligible, else None.

		Checks program reward_conditions:
		- ``after_days``: submission must be at least N days old.
		- ``must_pass_probation``: placeholder; requires external confirmation.
		"""
		program = session.execute(
			select(ReferralProgram).where(ReferralProgram.id == submission.program_id)
		).scalar_one_or_none()

		if program is None:
			return None

		conditions: dict[str, Any] = program.reward_conditions or {}

		# Check after_days condition
		after_days = conditions.get("after_days")
		if after_days is not None and submission.submitted_at:
			elapsed = (_now_utc() - submission.submitted_at).days
			if elapsed < int(after_days):
				_log.info(
					"Reward not yet eligible: submission=%s elapsed_days=%d required=%d",
					submission.id, elapsed, after_days,
				)
				return None

		return int(program.reward_amount_cents)

	def _create_reward(
		self,
		submission: ReferralSubmission,
		reward_amount_cents: int,
		session: Session,
	) -> ReferralReward:
		"""Create a PENDING ReferralReward for a hired submission."""
		program = session.execute(
			select(ReferralProgram).where(ReferralProgram.id == submission.program_id)
		).scalar_one_or_none()

		reward_type = program.reward_type if program else "CASH"

		reward = ReferralReward(
			tenant_id=submission.tenant_id,
			submission_id=submission.id,
			referrer_id=submission.referrer_id,
			reward_amount_cents=reward_amount_cents,
			reward_type=reward_type,
			status="PENDING",
		)
		session.add(reward)
		session.flush()

		_log.info(
			"ReferralReward created: id=%s submission=%s amount_cents=%d",
			reward.id, submission.id, reward_amount_cents,
		)
		return reward


# ---------------------------------------------------------------------------
# BPM Action Registry
# ---------------------------------------------------------------------------


@BPMActionRegistry.register("hcm.referral.update_status", "Update referral submission status")
def _bpm_update_status(
	record_ctx: Any,
	session: Session,
	submission_id: str,
	new_status: str,
	**kw: Any,
) -> ReferralSubmission:
	svc = ReferralService()
	return svc.update_status(
		submission_id,
		new_status,
		session,
		hired_at=kw.get("hired_at"),
	)
