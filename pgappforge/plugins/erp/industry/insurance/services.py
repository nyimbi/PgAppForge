"""
pgappforge/plugins/erp/industry/insurance/services.py

InsuranceService — stateless business logic for the Insurance plugin.

All methods accept an explicit SQLAlchemy session (SA 2.x execute() pattern).
No session.commit() inside service methods — callers own the transaction boundary.

Monetary invariant: ALL amounts are integer cents throughout.

Key methods
-----------
  underwrite_policy(product_id, holder_id, coverage_details, session) -> dict
      Compute risk score and premium quote without issuing a policy.

  issue_policy(quote_details, session) -> Policy
      Create and activate a policy from an underwriting quote.

  calculate_premium(product_id, risk_factors, session) -> int
      Calculate premium in cents from product base + risk factor adjustments.

  file_claim(policy_id, incident_details, session) -> Claim
      Create a new claim in REPORTED status; emits ClaimFiledEvent.

  assess_claim(claim_id, assessed_amount_cents, session) -> Claim
      Assessor sets assessed amount; transitions to UNDER_REVIEW.

  approve_claim(claim_id, approved_amount_cents, session) -> Claim
      Approve claim for a specific payment amount; emits ClaimApprovedEvent.

  pay_claim(claim_id, session) -> dict
      Trigger AP payment for approved claim; emits ClaimPaidEvent.

  lapse_overdue_policies(session) -> int
      Mark ACTIVE policies with all premiums OVERDUE as LAPSED.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

import sqlalchemy as sa

from pgappforge.plugins.erp.foundation.commons import (
	money_multiply,
	percent_of,
	format_currency,
)

log = logging.getLogger(__name__)

# Overdue threshold: mark premium OVERDUE if due_date + grace days < today
_PREMIUM_GRACE_DAYS = 15


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class InsuranceServiceError(Exception):
	"""Base exception for Insurance service layer errors."""


class ProductNotFoundError(InsuranceServiceError):
	pass


class PolicyNotFoundError(InsuranceServiceError):
	pass


class ClaimNotFoundError(InsuranceServiceError):
	pass


class InsuranceValidationError(InsuranceServiceError):
	"""Business rule validation failure — HTTP 422."""


# ---------------------------------------------------------------------------
# InsuranceService
# ---------------------------------------------------------------------------

class InsuranceService:
	"""Stateless Insurance business logic.

	Instantiate per-request or as a singleton — no instance state.
	"""

	# ------------------------------------------------------------------
	# underwrite_policy
	# ------------------------------------------------------------------

	def underwrite_policy(
		self,
		product_id: str,
		holder_id: str,
		coverage_details: dict,
		session: Any,
	) -> dict:
		"""Compute risk score and premium quote.

		coverage_details keys:
		  coverage_amount_cents: int (required)
		  payment_frequency: str — MONTHLY/QUARTERLY/ANNUAL (default ANNUAL)
		  coverage_start: str ISO date (default today)
		  coverage_end: str ISO date (default today + 1 year)

		Risk score algorithm:
		  base_risk = product.base_premium_cents / product.max_coverage_cents
		  + 0.05 per prior claim (holder.claims_history)
		  + credit_score penalty (if < 650 → +0.15)
		  clamped to [0.0, 1.0]

		Premium = base_premium_cents * (1 + risk_score) adjusted for coverage ratio.

		Returns dict with risk_score, annual_premium_cents, monthly_premium_cents, quote_valid_until.
		"""
		from pgappforge.plugins.erp.industry.insurance.models import InsuranceProduct, PolicyHolder

		product = session.get(InsuranceProduct, product_id)
		if product is None:
			raise ProductNotFoundError(f"InsuranceProduct {product_id!r} not found")
		if not product.is_active:
			raise InsuranceValidationError(f"Product {product.product_code!r} is not active")

		holder = session.get(PolicyHolder, holder_id)
		if holder is None:
			raise InsuranceValidationError(f"PolicyHolder {holder_id!r} not found")

		coverage_amount_cents = int(coverage_details.get("coverage_amount_cents") or 0)
		if coverage_amount_cents <= 0:
			raise InsuranceValidationError("coverage_amount_cents must be > 0")
		if coverage_amount_cents < product.min_coverage_cents:
			raise InsuranceValidationError(
				f"coverage_amount_cents {coverage_amount_cents} below product minimum {product.min_coverage_cents}"
			)
		if coverage_amount_cents > product.max_coverage_cents:
			raise InsuranceValidationError(
				f"coverage_amount_cents {coverage_amount_cents} exceeds product maximum {product.max_coverage_cents}"
			)

		# Risk score
		risk_score = self._compute_risk_score(product, holder)

		# Premium = base_premium * coverage_ratio * (1 + risk_score)
		coverage_ratio = Decimal(str(coverage_amount_cents)) / Decimal(str(product.max_coverage_cents))
		annual_premium_cents = int(
			(
				Decimal(str(product.base_premium_cents))
				* coverage_ratio
				* (Decimal("1") + Decimal(str(risk_score)))
			).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
		)
		monthly_premium_cents = int(
			Decimal(str(annual_premium_cents)) / Decimal("12")
		).quantize(Decimal("1"), rounding=ROUND_HALF_UP) if isinstance(
			int(Decimal(str(annual_premium_cents)) / Decimal("12")), int
		) else int(Decimal(str(annual_premium_cents)) / Decimal("12"))

		coverage_start_str = coverage_details.get("coverage_start") or date.today().isoformat()
		coverage_end_str = coverage_details.get("coverage_end") or (
			date.today() + timedelta(days=365)
		).isoformat()

		return {
			"product_id": product_id,
			"holder_id": holder_id,
			"coverage_amount_cents": coverage_amount_cents,
			"risk_score": float(risk_score),
			"annual_premium_cents": annual_premium_cents,
			"monthly_premium_cents": int(Decimal(str(annual_premium_cents)) / Decimal("12")),
			"quarterly_premium_cents": int(Decimal(str(annual_premium_cents)) / Decimal("4")),
			"payment_frequency": coverage_details.get("payment_frequency") or "ANNUAL",
			"coverage_start": coverage_start_str,
			"coverage_end": coverage_end_str,
			"quote_valid_until": (date.today() + timedelta(days=30)).isoformat(),
		}

	# ------------------------------------------------------------------
	# issue_policy
	# ------------------------------------------------------------------

	def issue_policy(self, quote_details: dict, session: Any) -> Any:
		"""Create and activate a Policy from underwriting quote details.

		quote_details: output from underwrite_policy() plus:
		  tenant_id: str (required)
		  insured_party_id: str (required)
		  agent_id: str (optional)
		  exclusions: list (optional)
		  beneficiaries: list (optional)

		Generates policy_number, creates Policy, schedules Premium installments,
		emits PolicyIssuedEvent. Returns the created Policy.
		"""
		from pgappforge.plugins.erp.industry.insurance.models import Policy, Premium
		from pgappforge.plugins.erp.industry.insurance.events import PolicyIssuedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		required = ("tenant_id", "product_id", "holder_id", "insured_party_id",
		            "coverage_amount_cents", "annual_premium_cents",
		            "coverage_start", "coverage_end")
		missing = [f for f in required if not quote_details.get(f) and quote_details.get(f) != 0]
		if missing:
			raise InsuranceValidationError(f"Missing required fields: {missing}")

		policy_number = self._next_policy_number(quote_details["tenant_id"], session)
		coverage_start = date.fromisoformat(quote_details["coverage_start"])
		coverage_end = date.fromisoformat(quote_details["coverage_end"])
		payment_frequency = quote_details.get("payment_frequency") or "ANNUAL"

		policy = Policy(
			tenant_id=quote_details["tenant_id"],
			policy_number=policy_number,
			product_id=quote_details["product_id"],
			holder_id=quote_details["holder_id"],
			insured_party_id=quote_details["insured_party_id"],
			coverage_start=coverage_start,
			coverage_end=coverage_end,
			coverage_amount_cents=int(quote_details["coverage_amount_cents"]),
			annual_premium_cents=int(quote_details["annual_premium_cents"]),
			payment_frequency=payment_frequency,
			status="ACTIVE",
			exclusions=quote_details.get("exclusions") or [],
			beneficiaries=quote_details.get("beneficiaries") or [],
			agent_id=quote_details.get("agent_id"),
		)
		session.add(policy)
		session.flush()

		# Schedule premium installments
		self._schedule_premiums(policy, session)

		emit_event(
			PolicyIssuedEvent(
				aggregate_id=policy.id,
				aggregate_type="Policy",
				tenant_id=policy.tenant_id,
				policy_id=policy.id,
				policy_number=policy.policy_number,
				product_id=policy.product_id,
				holder_id=policy.holder_id,
				coverage_amount_cents=policy.coverage_amount_cents,
				annual_premium_cents=policy.annual_premium_cents,
				coverage_start=coverage_start.isoformat(),
				coverage_end=coverage_end.isoformat(),
			),
			session,
		)

		log.info(
			"InsuranceService.issue_policy: %r coverage=%d¢ premium=%d¢/yr",
			policy.policy_number, policy.coverage_amount_cents, policy.annual_premium_cents,
		)
		return policy

	# ------------------------------------------------------------------
	# calculate_premium
	# ------------------------------------------------------------------

	def calculate_premium(
		self,
		product_id: str,
		risk_factors: dict,
		session: Any,
	) -> int:
		"""Calculate annual premium in cents from product + risk factors.

		risk_factors keys (all optional, additive adjustments):
		  coverage_amount_cents: int — defaults to product.max_coverage_cents
		  claims_history: int — prior claims count (+5% per claim)
		  credit_score: int — credit score (< 650 adds +15%)
		  age: int — age in years (> 65 adds +10% for life/health)
		  occupation_risk: float — 0.0–1.0 occupational hazard score (+risk*20%)

		Returns annual premium in integer cents.
		"""
		from pgappforge.plugins.erp.industry.insurance.models import InsuranceProduct

		product = session.get(InsuranceProduct, product_id)
		if product is None:
			raise ProductNotFoundError(f"InsuranceProduct {product_id!r} not found")

		coverage_cents = int(risk_factors.get("coverage_amount_cents") or product.max_coverage_cents)
		coverage_ratio = Decimal(str(coverage_cents)) / Decimal(str(max(product.max_coverage_cents, 1)))

		# Build risk multiplier
		risk_add = Decimal("0")
		claims_history = int(risk_factors.get("claims_history") or 0)
		risk_add += Decimal("0.05") * Decimal(str(claims_history))

		credit_score = risk_factors.get("credit_score")
		if credit_score is not None and int(credit_score) < 650:
			risk_add += Decimal("0.15")

		age = risk_factors.get("age")
		if age is not None and int(age) > 65 and product.product_type in ("LIFE", "HEALTH"):
			risk_add += Decimal("0.10")

		occupation_risk = risk_factors.get("occupation_risk")
		if occupation_risk is not None:
			risk_add += Decimal(str(occupation_risk)) * Decimal("0.20")

		risk_add = min(Decimal("1.0"), risk_add)  # cap at +100%

		premium = int(
			(
				Decimal(str(product.base_premium_cents))
				* coverage_ratio
				* (Decimal("1") + risk_add)
			).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
		)
		log.debug(
			"InsuranceService.calculate_premium: product=%r risk_add=%s premium=%d¢",
			product_id, risk_add, premium,
		)
		return premium

	# ------------------------------------------------------------------
	# file_claim
	# ------------------------------------------------------------------

	def file_claim(self, policy_id: str, incident_details: dict, session: Any) -> Any:
		"""File a new claim against a policy.

		incident_details keys (required): tenant_id, claimant_id, incident_date, claimed_amount_cents
		incident_details keys (optional): claim_type, incident_description, incident_location, documents

		Validates:
		  - Policy must be ACTIVE.
		  - claimed_amount_cents > 0.
		  - incident_date <= today.

		Emits ClaimFiledEvent. Returns created Claim.
		"""
		from pgappforge.plugins.erp.industry.insurance.models import Policy, Claim
		from pgappforge.plugins.erp.industry.insurance.events import ClaimFiledEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		policy = session.get(Policy, policy_id)
		if policy is None:
			raise PolicyNotFoundError(f"Policy {policy_id!r} not found")
		if policy.status != "ACTIVE":
			raise InsuranceValidationError(
				f"Cannot file claim on policy {policy.policy_number!r} with status {policy.status!r}"
			)

		claimed_cents = int(incident_details.get("claimed_amount_cents") or 0)
		if claimed_cents <= 0:
			raise InsuranceValidationError("claimed_amount_cents must be > 0")

		incident_date_val = incident_details.get("incident_date")
		if isinstance(incident_date_val, str):
			incident_date_val = date.fromisoformat(incident_date_val)
		if incident_date_val is None:
			incident_date_val = date.today()
		if incident_date_val > date.today():
			raise InsuranceValidationError("incident_date cannot be in the future")

		reported_date = date.today()
		claim_number = self._next_claim_number(policy.tenant_id, session)

		claim = Claim(
			tenant_id=policy.tenant_id,
			claim_number=claim_number,
			policy_id=policy_id,
			claimant_id=incident_details["claimant_id"],
			incident_date=incident_date_val,
			reported_date=reported_date,
			claim_type=incident_details.get("claim_type"),
			incident_description=incident_details.get("incident_description"),
			incident_location=incident_details.get("incident_location") or {},
			claimed_amount_cents=claimed_cents,
			status="REPORTED",
			documents=incident_details.get("documents") or [],
		)
		session.add(claim)
		session.flush()

		emit_event(
			ClaimFiledEvent(
				aggregate_id=claim.id,
				aggregate_type="Claim",
				tenant_id=policy.tenant_id,
				claim_id=claim.id,
				claim_number=claim.claim_number,
				policy_id=policy_id,
				claimant_id=incident_details["claimant_id"],
				claimed_amount_cents=claimed_cents,
				incident_date=incident_date_val.isoformat(),
				reported_date=reported_date.isoformat(),
			),
			session,
		)

		log.info(
			"InsuranceService.file_claim: %r policy=%r claimed=%d¢",
			claim.claim_number, policy_id, claimed_cents,
		)
		return claim

	# ------------------------------------------------------------------
	# assess_claim
	# ------------------------------------------------------------------

	def assess_claim(
		self,
		claim_id: str,
		assessed_amount_cents: int,
		session: Any,
	) -> Any:
		"""Assessor sets assessed amount; transitions claim to UNDER_REVIEW.

		assessed_amount_cents must be >= 0 and <= claimed_amount_cents.
		Returns updated Claim.
		"""
		from pgappforge.plugins.erp.industry.insurance.models import Claim

		claim = session.get(Claim, claim_id)
		if claim is None:
			raise ClaimNotFoundError(f"Claim {claim_id!r} not found")
		if claim.status != "REPORTED":
			raise InsuranceValidationError(
				f"Claim {claim.claim_number!r} is {claim.status!r}, expected REPORTED"
			)
		if assessed_amount_cents < 0:
			raise InsuranceValidationError("assessed_amount_cents cannot be negative")

		claim.assessed_amount_cents = int(assessed_amount_cents)
		claim.status = "UNDER_REVIEW"
		claim.updated_at = datetime.now(timezone.utc)
		session.flush()

		log.info(
			"InsuranceService.assess_claim: %r assessed=%d¢",
			claim.claim_number, assessed_amount_cents,
		)
		return claim

	# ------------------------------------------------------------------
	# approve_claim
	# ------------------------------------------------------------------

	def approve_claim(
		self,
		claim_id: str,
		approved_amount_cents: int,
		session: Any,
		assessor_id: str = "",
		notes: str = "",
	) -> Any:
		"""Approve claim for a specific payment amount.

		approved_amount_cents must be <= assessed_amount_cents (if set) or <= claimed_amount_cents.
		Emits ClaimApprovedEvent. Returns updated Claim.
		"""
		from pgappforge.plugins.erp.industry.insurance.models import Claim
		from pgappforge.plugins.erp.industry.insurance.events import ClaimApprovedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		claim = session.get(Claim, claim_id)
		if claim is None:
			raise ClaimNotFoundError(f"Claim {claim_id!r} not found")
		if claim.status not in ("REPORTED", "UNDER_REVIEW"):
			raise InsuranceValidationError(
				f"Claim {claim.claim_number!r} is {claim.status!r}; cannot approve"
			)
		if approved_amount_cents < 0:
			raise InsuranceValidationError("approved_amount_cents cannot be negative")

		cap = claim.assessed_amount_cents if claim.assessed_amount_cents is not None else claim.claimed_amount_cents
		if approved_amount_cents > cap:
			raise InsuranceValidationError(
				f"approved_amount_cents {approved_amount_cents} exceeds cap {cap}"
			)

		now_utc = datetime.now(timezone.utc)
		claim.approved_amount_cents = int(approved_amount_cents)
		claim.status = "APPROVED"
		if assessor_id:
			claim.assessor_id = assessor_id
		if notes:
			claim.adjudication_notes = notes
		claim.updated_at = now_utc

		emit_event(
			ClaimApprovedEvent(
				aggregate_id=claim_id,
				aggregate_type="Claim",
				tenant_id=claim.tenant_id,
				claim_id=claim_id,
				claim_number=claim.claim_number,
				policy_id=claim.policy_id,
				approved_amount_cents=approved_amount_cents,
				assessor_id=assessor_id,
				approved_at=now_utc.isoformat(),
			),
			session,
		)

		log.info(
			"InsuranceService.approve_claim: %r approved=%d¢",
			claim.claim_number, approved_amount_cents,
		)
		return claim

	# ------------------------------------------------------------------
	# pay_claim
	# ------------------------------------------------------------------

	def pay_claim(self, claim_id: str, session: Any) -> dict:
		"""Trigger payment for an APPROVED claim.

		Updates Claim.paid_amount_cents = approved_amount_cents,
		transitions status to PAID, emits ClaimPaidEvent.

		In production, this would create an AP payment record.
		Returns a payment summary dict.
		"""
		from pgappforge.plugins.erp.industry.insurance.models import Claim
		from pgappforge.plugins.erp.industry.insurance.events import ClaimPaidEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		claim = session.get(Claim, claim_id)
		if claim is None:
			raise ClaimNotFoundError(f"Claim {claim_id!r} not found")
		if claim.status != "APPROVED":
			raise InsuranceValidationError(
				f"Claim {claim.claim_number!r} is {claim.status!r}, expected APPROVED"
			)

		now_utc = datetime.now(timezone.utc)
		claim.paid_amount_cents = claim.approved_amount_cents
		claim.status = "PAID"
		claim.updated_at = now_utc

		emit_event(
			ClaimPaidEvent(
				aggregate_id=claim_id,
				aggregate_type="Claim",
				tenant_id=claim.tenant_id,
				claim_id=claim_id,
				claim_number=claim.claim_number,
				policy_id=claim.policy_id,
				paid_amount_cents=claim.paid_amount_cents,
				paid_at=now_utc.isoformat(),
			),
			session,
		)

		log.info(
			"InsuranceService.pay_claim: %r paid=%d¢",
			claim.claim_number, claim.paid_amount_cents,
		)

		return {
			"claim_id": claim_id,
			"claim_number": claim.claim_number,
			"policy_id": claim.policy_id,
			"paid_amount_cents": claim.paid_amount_cents,
			"paid_at": now_utc.isoformat(),
			"status": claim.status,
			"ap_reference": f"AP-{claim.claim_number}",  # stub — real AP integration replaces this
		}

	# ------------------------------------------------------------------
	# lapse_overdue_policies
	# ------------------------------------------------------------------

	def lapse_overdue_policies(self, session: Any) -> int:
		"""Mark ACTIVE policies whose premiums are all OVERDUE as LAPSED.

		A policy is considered overdue when all DUE/OVERDUE premiums have
		due_date + grace_days < today. Returns count of policies lapsed.
		"""
		from pgappforge.plugins.erp.industry.insurance.models import Policy, Premium
		from pgappforge.plugins.erp.industry.insurance.events import PolicyLapsedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		grace_cutoff = date.today() - timedelta(days=_PREMIUM_GRACE_DAYS)

		# First mark individual premiums as OVERDUE
		session.execute(
			sa.update(Premium)
			.where(Premium.status == "DUE")
			.where(Premium.due_date < grace_cutoff)
			.values(status="OVERDUE", updated_at=datetime.now(timezone.utc))
		)

		# Find policies with no non-overdue unpaid premiums (all outstanding are OVERDUE)
		overdue_policy_ids_q = (
			sa.select(Premium.policy_id)
			.where(Premium.status == "OVERDUE")
			.where(
				~sa.exists(
					sa.select(Premium.id).where(
						Premium.policy_id == Premium.policy_id,
						Premium.status.in_(("DUE", "PAID")),
					)
				)
			)
			.distinct()
		)
		overdue_ids = [r[0] for r in session.execute(overdue_policy_ids_q).all()]

		if not overdue_ids:
			return 0

		# Fetch policies to emit events
		policies = session.execute(
			sa.select(Policy)
			.where(Policy.id.in_(overdue_ids))
			.where(Policy.status == "ACTIVE")
		).scalars().all()

		now_utc = datetime.now(timezone.utc)
		lapsed_count = 0
		for policy in policies:
			policy.status = "LAPSED"
			policy.updated_at = now_utc
			emit_event(
				PolicyLapsedEvent(
					aggregate_id=policy.id,
					aggregate_type="Policy",
					tenant_id=policy.tenant_id,
					policy_id=policy.id,
					policy_number=policy.policy_number,
					holder_id=policy.holder_id,
					lapsed_at=now_utc.isoformat(),
				),
				session,
			)
			lapsed_count += 1

		log.info("InsuranceService.lapse_overdue_policies: lapsed=%d", lapsed_count)
		return lapsed_count

	# ------------------------------------------------------------------
	# Internal helpers
	# ------------------------------------------------------------------

	def _compute_risk_score(self, product: Any, holder: Any) -> Decimal:
		"""Compute risk score 0.0–1.0 from holder underwriting attributes."""
		risk = Decimal("0.1")  # base risk

		# Prior claims
		claims_history = int(holder.claims_history or 0)
		risk += Decimal("0.05") * Decimal(str(claims_history))

		# Credit score
		credit_score = holder.credit_score
		if credit_score is not None:
			if int(credit_score) < 580:
				risk += Decimal("0.20")
			elif int(credit_score) < 650:
				risk += Decimal("0.10")

		# Existing risk_score from holder if set by prior underwriting
		if holder.risk_score is not None:
			# Blend 50/50 with computed
			risk = (risk + Decimal(str(holder.risk_score))) / Decimal("2")

		return min(Decimal("1.0000"), risk).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)

	def _schedule_premiums(self, policy: Any, session: Any) -> None:
		"""Generate Premium installment records for the policy term."""
		from pgappforge.plugins.erp.industry.insurance.models import Premium

		freq = policy.payment_frequency
		annual = policy.annual_premium_cents

		if freq == "ANNUAL":
			amount = annual
			interval_months = 12
		elif freq == "QUARTERLY":
			amount = int(Decimal(str(annual)) / Decimal("4"))
			interval_months = 3
		else:  # MONTHLY
			amount = int(Decimal(str(annual)) / Decimal("12"))
			interval_months = 1

		current = policy.coverage_start
		end = policy.coverage_end
		while current < end:
			session.add(Premium(
				tenant_id=policy.tenant_id,
				policy_id=policy.id,
				due_date=current,
				amount_cents=amount,
				status="DUE",
			))
			# Advance by interval_months
			month = current.month - 1 + interval_months
			year = current.year + month // 12
			month = month % 12 + 1
			try:
				current = current.replace(year=year, month=month)
			except ValueError:
				# day out of range for month — use last day of month
				import calendar
				last_day = calendar.monthrange(year, month)[1]
				current = current.replace(year=year, month=month, day=last_day)

	def _next_policy_number(self, tenant_id: str, session: Any) -> str:
		"""Generate next sequential policy number for tenant."""
		from pgappforge.plugins.erp.industry.insurance.models import Policy
		count = session.execute(
			sa.select(sa.func.count(Policy.id))
			.where(Policy.tenant_id == tenant_id)
		).scalar() or 0
		return f"POL-{count + 1:08d}"

	def _next_claim_number(self, tenant_id: str, session: Any) -> str:
		"""Generate next sequential claim number for tenant."""
		from pgappforge.plugins.erp.industry.insurance.models import Claim
		count = session.execute(
			sa.select(sa.func.count(Claim.id))
			.where(Claim.tenant_id == tenant_id)
		).scalar() or 0
		return f"CLM-{count + 1:08d}"


__all__ = [
	"InsuranceService",
	"InsuranceServiceError",
	"ProductNotFoundError",
	"PolicyNotFoundError",
	"ClaimNotFoundError",
	"InsuranceValidationError",
]
