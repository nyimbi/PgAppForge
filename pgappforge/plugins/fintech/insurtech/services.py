"""
pgappforge/plugins/fintech/insurtech/services.py

InsurTechService — insurance product quoting, policy issuance, premium
collection, lapse management, and claims handling.

Design principles:
  - Stateless service; all methods receive an explicit SQLAlchemy session.
  - Transaction boundaries owned by the caller.
  - All monetary amounts in integer cents.
  - Premium formula: base = sum_insured * base_rate_pct / 100,
    then each risk_factor multiplier applied in order.
  - Grace period: 30 days before a policy is lapsed for overdue premiums.
  - GL posting is a lightweight stub; real GL integration injected via
    post_to_gl() helper which callers can monkey-patch or wrap.

Public methods:
  get_quote(...)              -> dict
  issue_policy(...)           -> InsurancePolicy
  _schedule_premiums(...)     -> int
  collect_premium(...)        -> InsurancePremium
  run_lapse_check(...)        -> int
  submit_claim(...)           -> InsuranceClaim
  assess_claim(...)           -> InsuranceClaim
  approve_claim(...)          -> InsuranceClaim
  reject_claim(...)           -> InsuranceClaim
  cancel_policy(...)          -> InsurancePolicy
"""
from __future__ import annotations

import logging
import uuid
from calendar import monthrange
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy import select

from pgappforge.plugins.fintech.insurtech.events import (
	ClaimApprovedEvent,
	ClaimRejectedEvent,
	ClaimSubmittedEvent,
	PolicyIssuedEvent,
	PolicyLapsedEvent,
	PremiumPaidEvent,
)
from pgappforge.plugins.fintech.insurtech.models import (
	InsuranceClaim,
	InsurancePolicy,
	InsurancePremium,
	InsuranceProduct,
	PolicyHolder,
)

log = logging.getLogger(__name__)

# Grace period before lapsing a policy with overdue premiums
_GRACE_DAYS = 30


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class InsurTechError(Exception):
	"""Base domain error for InsurTech operations."""


class ProductNotFoundError(InsurTechError):
	pass


class PolicyNotFoundError(InsurTechError):
	pass


class ClaimNotFoundError(InsurTechError):
	pass


class InsurTechStateError(InsurTechError):
	"""Invalid state transition."""


class InsurTechValidationError(InsurTechError):
	"""Business rule violation."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _emit(event: Any) -> None:
	try:
		from pgappforge.plugins.erp.foundation.events import emit_event as _ev
		_ev(event, None)
	except Exception:
		pass


def _now() -> datetime:
	return datetime.now(timezone.utc)


def _today() -> date:
	return date.today()


def _policy_number(tenant_id: str) -> str:
	"""Generate a unique policy number: POL-<8hex>."""
	return f"POL-{uuid.uuid4().hex[:8].upper()}"


def _claim_number(tenant_id: str) -> str:
	"""Generate a unique claim number: CLM-<8hex>."""
	return f"CLM-{uuid.uuid4().hex[:8].upper()}"


def _compute_premium(
	sum_insured_cents: int,
	base_rate_pct: float,
	risk_factors: list[dict],
) -> int:
	"""Calculate annual premium in integer cents.

	premium = sum_insured * base_rate_pct / 100
	For each risk_factor: premium *= multiplier
	Result rounded ROUND_HALF_UP to nearest cent.
	"""
	base = Decimal(str(sum_insured_cents)) * Decimal(str(base_rate_pct)) / Decimal("100")
	for rf in risk_factors or []:
		multiplier = Decimal(str(rf.get("multiplier", 1)))
		base = base * multiplier
	return int(base.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _add_months(d: date, months: int) -> date:
	"""Add a number of months to a date, clamping to end of target month."""
	month = d.month - 1 + months
	year = d.year + month // 12
	month = month % 12 + 1
	day = min(d.day, monthrange(year, month)[1])
	return date(year, month, day)


def _post_to_gl(
	policy_id: str,
	amount_cents: int,
	entry_type: str,
	description: str,
	session: Any,
) -> str:
	"""Stub GL posting — returns a journal_id.

	Replace by injecting a real GL adapter.  Returns a synthetic ID so
	the caller can store it without failing.
	"""
	journal_id = f"GL-{uuid.uuid4().hex[:10].upper()}"
	log.debug(
		"GL posted [stub]: type=%r policy=%r amount=%dc journal=%r",
		entry_type,
		policy_id,
		amount_cents,
		journal_id,
	)
	return journal_id


# ---------------------------------------------------------------------------
# BPM process registration
# ---------------------------------------------------------------------------

def _register_bpm() -> None:
	try:
		from pgappforge.plugins.bpm import register

		@register("insurtech.issue_policy", "Issue an insurance policy")
		def _bpm_issue(
			product_id: str,
			customer_id: str,
			sum_insured_cents: int,
			start_date: str,
			tenor_months: int,
			risk_factors: list,
			tenant_id: str,
			session: Any,
		) -> dict:
			svc = InsurTechService()
			policy = svc.issue_policy(
				product_id=product_id,
				customer_id=customer_id,
				sum_insured_cents=sum_insured_cents,
				start_date=date.fromisoformat(start_date),
				tenor_months=tenor_months,
				risk_factors=risk_factors,
				tenant_id=tenant_id,
				session=session,
			)
			return {
				"policy_id": policy.id,
				"policy_number": policy.policy_number,
				"status": policy.status,
			}

		@register("insurtech.submit_claim", "Submit an insurance claim")
		def _bpm_submit(
			policy_id: str,
			claim_type: str,
			incident_date: str,
			description: str,
			amount_claimed_cents: int,
			tenant_id: str,
			session: Any,
		) -> dict:
			svc = InsurTechService()
			claim = svc.submit_claim(
				policy_id=policy_id,
				claim_type=claim_type,
				incident_date=date.fromisoformat(incident_date),
				description=description,
				amount_claimed_cents=amount_claimed_cents,
				tenant_id=tenant_id,
				session=session,
			)
			return {
				"claim_id": claim.id,
				"claim_number": claim.claim_number,
				"status": claim.status,
			}

		@register("insurtech.approve_claim", "Approve an insurance claim")
		def _bpm_approve(
			claim_id: str,
			amount_approved_cents: int,
			decided_by: str,
			tenant_id: str,
			session: Any,
		) -> dict:
			svc = InsurTechService()
			claim = svc.approve_claim(
				claim_id=claim_id,
				amount_approved_cents=amount_approved_cents,
				decided_by=decided_by,
				tenant_id=tenant_id,
				session=session,
			)
			return {
				"claim_id": claim.id,
				"status": claim.status,
				"amount_approved_cents": claim.amount_approved_cents,
			}

	except ImportError:
		log.debug(
			"InsurTechService: BPM plugin not available, skipping process registration"
		)


# ---------------------------------------------------------------------------
# InsurTechService
# ---------------------------------------------------------------------------

class InsurTechService:
	"""Stateless service for insurance product quoting, policy management,
	premium collection, and claims handling.

	All methods receive an explicit SQLAlchemy session and do not call
	session.commit() — the caller owns transaction boundaries.
	"""

	# ------------------------------------------------------------------
	# Quote
	# ------------------------------------------------------------------

	def get_quote(
		self,
		product_id: str,
		sum_insured_cents: int,
		tenor_months: int,
		risk_factors: list[dict],
		tenant_id: str,
		session: Any,
	) -> dict:
		"""Calculate a premium quote for a product.

		Applies the product's premium_formula: base = sum_insured * base_rate_pct / 100,
		then sequentially multiplies by each risk_factor in the supplied list
		(overriding the product defaults with caller-supplied values).

		Args:
			product_id:         InsuranceProduct DB UUID.
			sum_insured_cents:  Proposed coverage amount in integer cents.
			tenor_months:       Policy term in months.
			risk_factors:       List of {name, multiplier} dicts to apply.
			tenant_id:          Tenant scope UUID.
			session:            SQLAlchemy session.

		Returns:
			dict with keys:
			  product_name, product_line, sum_insured_cents,
			  annual_premium_cents, monthly_premium_cents, valid_for_minutes (30).

		Raises:
			ProductNotFoundError: if product not found or inactive.
			InsurTechValidationError: if sum_insured is out of product bounds.
		"""
		product = session.execute(
			select(InsuranceProduct).where(
				InsuranceProduct.id == product_id,
				InsuranceProduct.tenant_id == tenant_id,
				InsuranceProduct.is_active == sa.true(),
			)
		).scalar_one_or_none()
		if not product:
			raise ProductNotFoundError(
				f"InsuranceProduct not found or inactive: {product_id!r}"
			)

		if sum_insured_cents < product.min_sum_insured_cents:
			raise InsurTechValidationError(
				f"sum_insured_cents {sum_insured_cents} below product minimum "
				f"{product.min_sum_insured_cents}"
			)
		if (
			product.max_sum_insured_cents is not None
			and sum_insured_cents > product.max_sum_insured_cents
		):
			raise InsurTechValidationError(
				f"sum_insured_cents {sum_insured_cents} exceeds product maximum "
				f"{product.max_sum_insured_cents}"
			)

		formula = product.premium_formula or {}
		base_rate_pct = float(formula.get("base_rate_pct", 0))
		# Use caller-supplied risk_factors (or fall back to product defaults)
		applied_factors = risk_factors if risk_factors is not None else (
			formula.get("risk_factors") or []
		)

		annual_premium_cents = _compute_premium(
			sum_insured_cents, base_rate_pct, applied_factors
		)
		monthly_premium_cents = int(
			(Decimal(str(annual_premium_cents)) / Decimal("12")).quantize(
				Decimal("1"), rounding=ROUND_HALF_UP
			)
		)

		return {
			"product_name": product.name,
			"product_line": product.product_line,
			"sum_insured_cents": sum_insured_cents,
			"annual_premium_cents": annual_premium_cents,
			"monthly_premium_cents": monthly_premium_cents,
			"valid_for_minutes": 30,
		}

	# ------------------------------------------------------------------
	# Policy issuance
	# ------------------------------------------------------------------

	def issue_policy(
		self,
		product_id: str,
		customer_id: str,
		sum_insured_cents: int,
		start_date: date,
		tenor_months: int,
		risk_factors: list[dict],
		tenant_id: str,
		session: Any,
		full_name: str = "",
		date_of_birth: date | None = None,
	) -> InsurancePolicy:
		"""Issue a new insurance policy.

		Get-or-creates a PolicyHolder for the customer, computes the premium
		via get_quote(), creates the policy in ACTIVE status, and schedules
		monthly premium rows via _schedule_premiums().

		Args:
			product_id:         InsuranceProduct DB UUID.
			customer_id:        Customer UUID (used to get-or-create PolicyHolder).
			sum_insured_cents:  Coverage amount in integer cents.
			start_date:         Policy start date.
			tenor_months:       Policy term in months.
			risk_factors:       List of {name, multiplier} dicts for premium calc.
			tenant_id:          Tenant scope UUID.
			session:            SQLAlchemy session.
			full_name:          Policyholder full name (used if creating new holder).
			date_of_birth:      Policyholder date of birth (optional).

		Returns:
			InsurancePolicy with status=ACTIVE.

		Raises:
			ProductNotFoundError, InsurTechValidationError.
		"""
		assert session is not None, "session required"
		assert tenant_id, "tenant_id required"

		# Get quote first (validates product + sum_insured)
		quote = self.get_quote(
			product_id=product_id,
			sum_insured_cents=sum_insured_cents,
			tenor_months=tenor_months,
			risk_factors=risk_factors,
			tenant_id=tenant_id,
			session=session,
		)

		# Get or create PolicyHolder
		holder = session.execute(
			select(PolicyHolder).where(
				PolicyHolder.customer_id == customer_id,
				PolicyHolder.tenant_id == tenant_id,
			)
		).scalar_one_or_none()
		if not holder:
			holder = PolicyHolder(
				tenant_id=tenant_id,
				customer_id=customer_id,
				full_name=full_name or str(customer_id),
				date_of_birth=date_of_birth,
			)
			session.add(holder)
			session.flush()

		end_date = _add_months(start_date, tenor_months)

		policy = InsurancePolicy(
			tenant_id=tenant_id,
			policy_number=_policy_number(tenant_id),
			holder_id=holder.id,
			product_id=product_id,
			sum_insured_cents=sum_insured_cents,
			annual_premium_cents=quote["annual_premium_cents"],
			start_date=start_date,
			end_date=end_date,
			status="ACTIVE",
		)
		session.add(policy)
		session.flush()

		monthly_cents = quote["monthly_premium_cents"]
		self._schedule_premiums(
			policy_id=policy.id,
			start_date=start_date,
			end_date=end_date,
			monthly_amount_cents=monthly_cents,
			tenant_id=tenant_id,
			session=session,
		)

		_emit(PolicyIssuedEvent(
			aggregate_type="InsurancePolicy",
			aggregate_id=policy.id,
			tenant_id=tenant_id,
			policy_id=policy.id,
			policy_number=policy.policy_number,
			holder_id=holder.id,
			product_id=product_id,
			product_line=quote["product_line"],
			sum_insured_cents=sum_insured_cents,
			annual_premium_cents=quote["annual_premium_cents"],
			start_date=start_date.isoformat(),
			end_date=end_date.isoformat(),
		))
		log.info(
			"Policy issued: number=%r product=%r sum_insured=%dc",
			policy.policy_number,
			product_id,
			sum_insured_cents,
		)
		return policy

	# ------------------------------------------------------------------
	# Premium scheduling
	# ------------------------------------------------------------------

	def _schedule_premiums(
		self,
		policy_id: str,
		start_date: date,
		end_date: date,
		monthly_amount_cents: int,
		tenant_id: str,
		session: Any,
	) -> int:
		"""Create InsurancePremium rows for each month of the policy term.

		Args:
			policy_id:             InsurancePolicy DB UUID.
			start_date:            Policy start date.
			end_date:              Policy end date.
			monthly_amount_cents:  Monthly premium amount in integer cents.
			tenant_id:             Tenant scope UUID.
			session:               SQLAlchemy session.

		Returns:
			Number of premium rows created.
		"""
		rows_created = 0
		current = start_date

		while current < end_date:
			period = current.strftime("%Y-%m")
			# Due on the 1st of the month
			due_date = current.replace(day=1)
			premium = InsurancePremium(
				tenant_id=tenant_id,
				policy_id=policy_id,
				period=period,
				amount_cents=monthly_amount_cents,
				due_date=due_date,
				status="DUE",
			)
			session.add(premium)
			rows_created += 1
			current = _add_months(current, 1)

		session.flush()
		log.debug(
			"Scheduled %d premium rows for policy_id=%r",
			rows_created,
			policy_id,
		)
		return rows_created

	# ------------------------------------------------------------------
	# Premium collection
	# ------------------------------------------------------------------

	def collect_premium(
		self,
		policy_id: str,
		period: str,
		amount_cents: int,
		tenant_id: str,
		session: Any,
	) -> InsurancePremium:
		"""Mark a premium as PAID and post to GL.

		If the payment clears all OVERDUE premiums for the policy and the
		policy is LAPSED, automatically reinstates it to REINSTATED.

		Args:
			policy_id:     InsurancePolicy DB UUID.
			period:        Billing period string "YYYY-MM".
			amount_cents:  Amount paid in integer cents.
			tenant_id:     Tenant scope UUID.
			session:       SQLAlchemy session.

		Returns:
			Updated InsurancePremium (status=PAID).

		Raises:
			InsurTechValidationError: if premium not found or already paid.
		"""
		premium = session.execute(
			select(InsurancePremium).where(
				InsurancePremium.policy_id == policy_id,
				InsurancePremium.period == period,
				InsurancePremium.tenant_id == tenant_id,
			)
		).scalar_one_or_none()
		if not premium:
			raise InsurTechValidationError(
				f"Premium not found: policy={policy_id!r} period={period!r}"
			)
		if premium.status == "PAID":
			raise InsurTechValidationError(
				f"Premium for period {period!r} is already PAID"
			)

		journal_id = _post_to_gl(
			policy_id=policy_id,
			amount_cents=amount_cents,
			entry_type="PREMIUM_RECEIPT",
			description=f"Premium collection {period}",
			session=session,
		)

		premium.status = "PAID"
		premium.paid_date = _today()
		premium.gl_journal_id = journal_id
		session.flush()

		policy = session.get(InsurancePolicy, policy_id)
		if policy:
			_emit(PremiumPaidEvent(
				aggregate_type="InsurancePolicy",
				aggregate_id=policy_id,
				tenant_id=tenant_id,
				premium_id=premium.id,
				policy_id=policy_id,
				policy_number=policy.policy_number,
				period=period,
				amount_cents=amount_cents,
				gl_journal_id=journal_id,
				paid_date=_today().isoformat(),
			))

			# Reinstate if LAPSED and all overdue premiums are now cleared
			if policy.status == "LAPSED":
				overdue_count = session.execute(
					select(sa.func.count(InsurancePremium.id)).where(
						InsurancePremium.policy_id == policy_id,
						InsurancePremium.status == "OVERDUE",
					)
				).scalar_one()
				if overdue_count == 0:
					session.execute(
						sa.update(InsurancePolicy)
						.where(InsurancePolicy.id == policy_id)
						.values(status="REINSTATED", updated_at=_now())
					)
					log.info(
						"Policy reinstated after overdue clearance: policy_id=%r",
						policy_id,
					)

		log.info(
			"Premium collected: policy_id=%r period=%r amount=%dc gl=%r",
			policy_id,
			period,
			amount_cents,
			journal_id,
		)
		return premium

	# ------------------------------------------------------------------
	# Lapse check
	# ------------------------------------------------------------------

	def run_lapse_check(
		self,
		tenant_id: str,
		session: Any,
	) -> int:
		"""Find ACTIVE policies with overdue premiums beyond the grace period and lapse them.

		Grace period: 30 days from the due_date before a DUE premium becomes OVERDUE
		and triggers a lapse.

		Args:
			tenant_id:  Tenant scope UUID.
			session:    SQLAlchemy session.

		Returns:
			Number of policies lapsed.
		"""
		cutoff_date = _today() - timedelta(days=_GRACE_DAYS)

		# Mark DUE premiums past grace period as OVERDUE
		session.execute(
			sa.update(InsurancePremium)
			.where(
				InsurancePremium.tenant_id == tenant_id,
				InsurancePremium.status == "DUE",
				InsurancePremium.due_date <= cutoff_date,
			)
			.values(status="OVERDUE")
		)

		# Find ACTIVE policies that now have OVERDUE premiums
		overdue_policy_ids = session.execute(
			select(InsurancePremium.policy_id)
			.join(InsurancePolicy, InsurancePremium.policy_id == InsurancePolicy.id)
			.where(
				InsurancePremium.tenant_id == tenant_id,
				InsurancePremium.status == "OVERDUE",
				InsurancePolicy.status == "ACTIVE",
			)
			.distinct()
		).scalars().all()

		lapsed_count = 0
		for policy_id in overdue_policy_ids:
			policy = session.get(InsurancePolicy, policy_id)
			if not policy or policy.status != "ACTIVE":
				continue

			overdue_periods = session.execute(
				select(InsurancePremium.period).where(
					InsurancePremium.policy_id == policy_id,
					InsurancePremium.status == "OVERDUE",
				)
			).scalars().all()

			session.execute(
				sa.update(InsurancePolicy)
				.where(InsurancePolicy.id == policy_id)
				.values(status="LAPSED", updated_at=_now())
			)

			_emit(PolicyLapsedEvent(
				aggregate_type="InsurancePolicy",
				aggregate_id=policy_id,
				tenant_id=tenant_id,
				policy_id=policy_id,
				policy_number=policy.policy_number,
				holder_id=str(policy.holder_id),
				overdue_periods=list(overdue_periods),
			))
			lapsed_count += 1

		session.flush()
		log.info(
			"Lapse check complete: tenant=%r lapsed=%d",
			tenant_id,
			lapsed_count,
		)
		return lapsed_count

	# ------------------------------------------------------------------
	# Claims
	# ------------------------------------------------------------------

	def submit_claim(
		self,
		policy_id: str,
		claim_type: str,
		incident_date: date,
		description: str,
		amount_claimed_cents: int,
		tenant_id: str,
		session: Any,
	) -> InsuranceClaim:
		"""File a claim against an active policy.

		Args:
			policy_id:             InsurancePolicy DB UUID.
			claim_type:            DEATH | HOSPITALIZATION | PROPERTY_DAMAGE |
			                       THEFT | ACCIDENT | CROP_LOSS | CRITICAL_ILLNESS
			incident_date:         Date the insured event occurred.
			description:           Narrative description of the incident.
			amount_claimed_cents:  Claimed payout amount in integer cents.
			tenant_id:             Tenant scope UUID.
			session:               SQLAlchemy session.

		Returns:
			InsuranceClaim with status=SUBMITTED.

		Raises:
			PolicyNotFoundError: if policy not found.
			InsurTechStateError: if policy is not ACTIVE.
		"""
		policy = session.execute(
			select(InsurancePolicy).where(
				InsurancePolicy.id == policy_id,
				InsurancePolicy.tenant_id == tenant_id,
			)
		).scalar_one_or_none()
		if not policy:
			raise PolicyNotFoundError(f"Policy not found: {policy_id!r}")
		if policy.status != "ACTIVE":
			raise InsurTechStateError(
				f"Claims can only be filed against ACTIVE policies "
				f"(policy {policy.policy_number!r} is {policy.status!r})"
			)

		claim = InsuranceClaim(
			tenant_id=tenant_id,
			policy_id=policy_id,
			claim_number=_claim_number(tenant_id),
			claim_type=claim_type,
			incident_date=incident_date,
			description=description,
			amount_claimed_cents=amount_claimed_cents,
			status="SUBMITTED",
			submitted_at=_now(),
		)
		session.add(claim)
		session.flush()

		_emit(ClaimSubmittedEvent(
			aggregate_type="InsuranceClaim",
			aggregate_id=claim.id,
			tenant_id=tenant_id,
			claim_id=claim.id,
			claim_number=claim.claim_number,
			policy_id=policy_id,
			policy_number=policy.policy_number,
			claim_type=claim_type,
			amount_claimed_cents=amount_claimed_cents,
			incident_date=incident_date.isoformat(),
		))
		log.info(
			"Claim submitted: number=%r policy=%r type=%r amount=%dc",
			claim.claim_number,
			policy.policy_number,
			claim_type,
			amount_claimed_cents,
		)
		return claim

	def assess_claim(
		self,
		claim_id: str,
		notes: str,
		tenant_id: str,
		session: Any,
	) -> InsuranceClaim:
		"""Move a claim to UNDER_REVIEW status.

		Args:
			claim_id:   InsuranceClaim DB UUID.
			notes:      Assessor notes (appended to description for audit).
			tenant_id:  Tenant scope UUID.
			session:    SQLAlchemy session.

		Returns:
			Updated InsuranceClaim (status=UNDER_REVIEW).

		Raises:
			ClaimNotFoundError, InsurTechStateError.
		"""
		claim = session.execute(
			select(InsuranceClaim).where(
				InsuranceClaim.id == claim_id,
				InsuranceClaim.tenant_id == tenant_id,
			)
		).scalar_one_or_none()
		if not claim:
			raise ClaimNotFoundError(f"Claim not found: {claim_id!r}")
		if claim.status != "SUBMITTED":
			raise InsurTechStateError(
				f"Claim {claim.claim_number!r} must be SUBMITTED to assess "
				f"(current: {claim.status!r})"
			)

		claim.status = "UNDER_REVIEW"
		if notes:
			claim.description = f"{claim.description}\n\n[ASSESSOR NOTES] {notes}"
		session.flush()
		log.info("Claim under review: claim_id=%r", claim_id)
		return claim

	def approve_claim(
		self,
		claim_id: str,
		amount_approved_cents: int,
		decided_by: str,
		tenant_id: str,
		session: Any,
	) -> InsuranceClaim:
		"""Approve a claim and post a GL payout entry.

		Args:
			claim_id:               InsuranceClaim DB UUID.
			amount_approved_cents:  Approved payout in integer cents.
			decided_by:             UUID of the deciding underwriter.
			tenant_id:              Tenant scope UUID.
			session:                SQLAlchemy session.

		Returns:
			Updated InsuranceClaim (status=APPROVED).

		Raises:
			ClaimNotFoundError, InsurTechStateError.
		"""
		claim = session.execute(
			select(InsuranceClaim).where(
				InsuranceClaim.id == claim_id,
				InsuranceClaim.tenant_id == tenant_id,
			)
		).scalar_one_or_none()
		if not claim:
			raise ClaimNotFoundError(f"Claim not found: {claim_id!r}")
		if claim.status not in ("SUBMITTED", "UNDER_REVIEW"):
			raise InsurTechStateError(
				f"Claim {claim.claim_number!r} must be SUBMITTED or UNDER_REVIEW "
				f"to approve (current: {claim.status!r})"
			)

		now = _now()
		_post_to_gl(
			policy_id=str(claim.policy_id),
			amount_cents=amount_approved_cents,
			entry_type="CLAIM_PAYOUT",
			description=f"Claim payout {claim.claim_number}",
			session=session,
		)

		claim.status = "APPROVED"
		claim.amount_approved_cents = amount_approved_cents
		claim.decided_at = now
		claim.decided_by = decided_by
		session.flush()

		policy = session.get(InsurancePolicy, claim.policy_id)
		_emit(ClaimApprovedEvent(
			aggregate_type="InsuranceClaim",
			aggregate_id=claim_id,
			tenant_id=tenant_id,
			claim_id=claim_id,
			claim_number=claim.claim_number,
			policy_id=str(claim.policy_id),
			amount_approved_cents=amount_approved_cents,
			decided_by=str(decided_by),
			decided_at=now.isoformat(),
		))
		log.info(
			"Claim approved: number=%r amount_approved=%dc",
			claim.claim_number,
			amount_approved_cents,
		)
		return claim

	def reject_claim(
		self,
		claim_id: str,
		reason: str,
		decided_by: str,
		tenant_id: str,
		session: Any,
	) -> InsuranceClaim:
		"""Reject a claim.

		Args:
			claim_id:    InsuranceClaim DB UUID.
			reason:      Human-readable rejection reason.
			decided_by:  UUID of the deciding underwriter.
			tenant_id:   Tenant scope UUID.
			session:     SQLAlchemy session.

		Returns:
			Updated InsuranceClaim (status=REJECTED).

		Raises:
			ClaimNotFoundError, InsurTechStateError.
		"""
		claim = session.execute(
			select(InsuranceClaim).where(
				InsuranceClaim.id == claim_id,
				InsuranceClaim.tenant_id == tenant_id,
			)
		).scalar_one_or_none()
		if not claim:
			raise ClaimNotFoundError(f"Claim not found: {claim_id!r}")
		if claim.status not in ("SUBMITTED", "UNDER_REVIEW"):
			raise InsurTechStateError(
				f"Claim {claim.claim_number!r} must be SUBMITTED or UNDER_REVIEW "
				f"to reject (current: {claim.status!r})"
			)

		now = _now()
		claim.status = "REJECTED"
		claim.decided_at = now
		claim.decided_by = decided_by
		if reason:
			claim.description = f"{claim.description}\n\n[REJECTION REASON] {reason}"
		session.flush()

		_emit(ClaimRejectedEvent(
			aggregate_type="InsuranceClaim",
			aggregate_id=claim_id,
			tenant_id=tenant_id,
			claim_id=claim_id,
			claim_number=claim.claim_number,
			policy_id=str(claim.policy_id),
			reason=reason,
			decided_by=str(decided_by),
			decided_at=now.isoformat(),
		))
		log.info(
			"Claim rejected: number=%r reason=%r",
			claim.claim_number,
			reason,
		)
		return claim

	# ------------------------------------------------------------------
	# Policy cancellation
	# ------------------------------------------------------------------

	def cancel_policy(
		self,
		policy_id: str,
		reason: str,
		tenant_id: str,
		session: Any,
	) -> InsurancePolicy:
		"""Cancel a policy and compute a pro-rata refund if applicable.

		Cancellation is allowed from ACTIVE or REINSTATED status.
		A pro-rata refund is computed if the cancellation date is before
		the policy end_date: refund = annual_premium * remaining_months / 12.

		Args:
			policy_id:  InsurancePolicy DB UUID.
			reason:     Human-readable cancellation reason.
			tenant_id:  Tenant scope UUID.
			session:    SQLAlchemy session.

		Returns:
			Updated InsurancePolicy (status=CANCELLED).

		Raises:
			PolicyNotFoundError, InsurTechStateError.
		"""
		policy = session.execute(
			select(InsurancePolicy).where(
				InsurancePolicy.id == policy_id,
				InsurancePolicy.tenant_id == tenant_id,
			)
		).scalar_one_or_none()
		if not policy:
			raise PolicyNotFoundError(f"Policy not found: {policy_id!r}")
		if policy.status not in ("ACTIVE", "REINSTATED"):
			raise InsurTechStateError(
				f"Policy {policy.policy_number!r} must be ACTIVE or REINSTATED "
				f"to cancel (current: {policy.status!r})"
			)

		today = _today()
		refund_cents = 0
		if policy.end_date > today:
			# Remaining full months
			remaining_months = max(0, (
				(policy.end_date.year - today.year) * 12
				+ (policy.end_date.month - today.month)
			))
			if remaining_months > 0:
				refund_cents = int(
					(
						Decimal(str(policy.annual_premium_cents))
						* Decimal(str(remaining_months))
						/ Decimal("12")
					).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
				)
				_post_to_gl(
					policy_id=policy_id,
					amount_cents=refund_cents,
					entry_type="CANCELLATION_REFUND",
					description=(
						f"Pro-rata refund on cancellation {policy.policy_number} "
						f"({remaining_months} remaining months)"
					),
					session=session,
				)

		policy.status = "CANCELLED"
		policy.cancellation_date = today
		policy.cancellation_reason = reason
		policy.updated_at = _now()
		session.flush()

		log.info(
			"Policy cancelled: number=%r reason=%r refund=%dc",
			policy.policy_number,
			reason,
			refund_cents,
		)
		return policy


# ---------------------------------------------------------------------------
# Register BPM processes at module load
# ---------------------------------------------------------------------------

_register_bpm()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"InsurTechService",
	"InsurTechError",
	"ProductNotFoundError",
	"PolicyNotFoundError",
	"ClaimNotFoundError",
	"InsurTechStateError",
	"InsurTechValidationError",
]
