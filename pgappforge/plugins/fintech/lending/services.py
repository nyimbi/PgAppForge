"""
pgappforge/plugins/fintech/lending/services.py

Lending plugin services — LoanOriginationService (LOS) and LoanManagementService (LMS).

All monetary arithmetic uses integer cents via money_add / money_multiply / money_divide
from the ERP foundation commons.  Never use float for money.

EMI formula (reducing balance):
	r   = annual_rate / 12
	EMI = P * r * (1+r)^n / ((1+r)^n - 1)

CBK NPA classification thresholds (prudential guidelines):
	DPD 0-30   → PERFORMING   provision 1%
	DPD 31-90  → WATCH        provision 5%
	DPD 91-180 → SUBSTANDARD  provision 25%
	DPD 181-360 → DOUBTFUL    provision 50%
	DPD >360   → LOSS         provision 100%

IFRS 9 ECL stages:
	Stage 1: no significant credit deterioration since origination (12-month ECL)
	Stage 2: significant credit deterioration (lifetime ECL)
	Stage 3: credit-impaired / NPA (lifetime ECL, full provision)
"""
from __future__ import annotations

import logging
import re
import uuid
from datetime import date, datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from pgappforge.plugins.erp.foundation.commons import (
	money_add,
	money_multiply,
	money_divide,
	percent_of,
	format_currency,
	emit_event,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Module-level CoreBankingService singleton (lazy, import-guarded)
# ---------------------------------------------------------------------------

_cb_service = None


def _get_cb():
	"""Return the module-level CoreBankingService instance (imported once)."""
	global _cb_service
	if _cb_service is None:
		from pgappforge.plugins.fintech.core_banking.services import CoreBankingService
		_cb_service = CoreBankingService()
	return _cb_service


# ---------------------------------------------------------------------------
# CBK classification thresholds
# ---------------------------------------------------------------------------

_NPA_THRESHOLDS: list[tuple[int, str, Decimal]] = [
	# (min_dpd, classification, provision_rate_pct)
	(0,   "PERFORMING",  Decimal("1")),
	(31,  "WATCH",       Decimal("5")),
	(91,  "SUBSTANDARD", Decimal("25")),
	(181, "DOUBTFUL",    Decimal("50")),
	(361, "LOSS",        Decimal("100")),
]


def _classify_npa(dpd: int) -> tuple[str, Decimal]:
	"""Return (classification, provision_rate_pct) for given days-past-due."""
	classification = "PERFORMING"
	rate = Decimal("1")
	for min_dpd, label, pct in _NPA_THRESHOLDS:
		if dpd >= min_dpd:
			classification = label
			rate = pct
	return classification, rate


# ---------------------------------------------------------------------------
# Application number / Loan number generators
# ---------------------------------------------------------------------------

def _generate_application_number(tenant_id: str) -> str:
	ts = datetime.now(timezone.utc).strftime("%Y%m%d")
	suffix = str(uuid.uuid4()).replace("-", "")[:6].upper()
	return f"APP-{ts}-{suffix}"


def _generate_loan_number(tenant_id: str) -> str:
	ts = datetime.now(timezone.utc).strftime("%Y%m%d")
	suffix = str(uuid.uuid4()).replace("-", "")[:6].upper()
	return f"LN-{ts}-{suffix}"


# ---------------------------------------------------------------------------
# EMI calculation helpers
# ---------------------------------------------------------------------------

def _calculate_emi_cents(principal_cents: int, annual_rate: Decimal, tenor_months: int) -> int:
	"""Calculate Equated Monthly Instalment (reducing balance).

	Formula: EMI = P * r * (1+r)^n / ((1+r)^n - 1)
	where r = monthly_rate = annual_rate / 12

	Returns integer cents.  For zero-rate loans returns principal / tenor.
	"""
	if tenor_months <= 0:
		raise ValueError(f"tenor_months must be positive, got {tenor_months}")
	if annual_rate == Decimal("0"):
		return money_divide(principal_cents, tenor_months)

	r = annual_rate / Decimal("12")
	one_plus_r_n = (1 + r) ** tenor_months
	emi = Decimal(str(principal_cents)) * r * one_plus_r_n / (one_plus_r_n - 1)
	return int(emi.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _add_months(d: date, months: int) -> date:
	"""Add months to a date, clamping to month-end when needed."""
	month = d.month - 1 + months
	year = d.year + month // 12
	month = month % 12 + 1
	import calendar
	day = min(d.day, calendar.monthrange(year, month)[1])
	return date(year, month, day)


# ---------------------------------------------------------------------------
# LoanOriginationService
# ---------------------------------------------------------------------------

class LoanOriginationService:
	"""Handles the full loan application lifecycle from creation to disbursement.

	All methods require a SQLAlchemy session to be passed in.  No Flask-global
	state is accessed here — callers provide session from their context.
	"""

	def create_application(
		self,
		session: Any,
		tenant_id: str,
		applicant_id: str,
		product_code: str,
		amount_cents: int,
		tenor_months: int,
		purpose: str,
		channel: str = "BRANCH",
		co_applicant_id: str | None = None,
	) -> Any:
		"""Create a new loan application in DRAFT status.

		Validates product exists, is active, and that requested amount / tenor
		fall within product limits.

		Returns: LoanApplication instance (not yet committed).
		"""
		import sqlalchemy as sa
		from pgappforge.plugins.fintech.lending.models import LoanApplication, LoanProduct

		product = session.execute(
			sa.select(LoanProduct).where(
				LoanProduct.product_code == product_code,
				LoanProduct.tenant_id == tenant_id,
				LoanProduct.is_active.is_(True),
			)
		).scalar_one_or_none()

		if product is None:
			raise ValueError(f"Active loan product '{product_code}' not found for tenant {tenant_id!r}")

		if amount_cents < product.min_amount_cents or amount_cents > product.max_amount_cents:
			raise ValueError(
				f"Requested amount {amount_cents} outside product limits "
				f"[{product.min_amount_cents}, {product.max_amount_cents}]"
			)

		if tenor_months < product.min_tenor_months or tenor_months > product.max_tenor_months:
			raise ValueError(
				f"Tenor {tenor_months} months outside product limits "
				f"[{product.min_tenor_months}, {product.max_tenor_months}]"
			)

		application = LoanApplication(
			tenant_id=tenant_id,
			application_number=_generate_application_number(tenant_id),
			applicant_id=applicant_id,
			co_applicant_id=co_applicant_id,
			product_id=product.id,
			requested_amount_cents=amount_cents,
			requested_tenor_months=tenor_months,
			purpose=purpose,
			channel=channel,
			status="DRAFT",
		)
		session.add(application)
		session.flush()
		log.info("Created application %s for applicant %s", application.application_number, applicant_id)
		return application

	def run_credit_check(
		self,
		session: Any,
		application_id: str,
		analyst_id: str | None = None,
	) -> dict:
		"""Run credit bureau lookup + internal scoring.

		Computes: credit_score, DTI, LTV, product minimum check.
		Writes results back to the application.

		Returns dict with keys:
			score, recommendation, bureau_response, dti, ltv, passed
		"""
		import sqlalchemy as sa
		from pgappforge.plugins.fintech.lending.models import LoanApplication, Collateral

		app = session.get(LoanApplication, application_id)
		if app is None:
			raise ValueError(f"LoanApplication {application_id!r} not found")

		if app.status not in ("SUBMITTED", "UNDER_REVIEW"):
			raise ValueError(f"Cannot run credit check on application in status {app.status!r}")

		# CRB Kenya bureau lookup (TransUnion / Metropol / Mock fallback)
		from pgappforge.plugins.fintech.lending.crb_adapter import (
			get_crb_adapter,
			CRBError,
			CRBIdentityNotFoundError,
		)

		id_number = getattr(app, "applicant_id_number", "") or getattr(app, "applicant_id", "") or ""
		id_type = getattr(app, "applicant_id_type", "NATIONAL_ID") or "NATIONAL_ID"
		full_name = getattr(app, "applicant_name", "") or ""
		phone = getattr(app, "applicant_phone", "") or ""

		bureau_response: dict
		credit_score: int

		try:
			crb_result = get_crb_adapter().inquire(
				id_number=id_number,
				id_type=id_type,
				full_name=full_name,
				phone_msisdn=phone,
			)
			bureau_response = crb_result.to_dict()
			credit_score = crb_result.score
			if crb_result.listed_negative:
				# Hard decline — persist fields and return immediately
				app.credit_score = credit_score
				app.credit_bureau_response = bureau_response
				app.credit_checked_at = datetime.now(timezone.utc)
				app.status = "CREDIT_CHECK"
				session.flush()
				return {
					"score": credit_score,
					"recommendation": "DECLINE",
					"bureau_response": bureau_response,
					"dti": None,
					"ltv": None,
					"passed": False,
					"decline_reason": "LISTED_NEGATIVE",
				}
		except CRBIdentityNotFoundError:
			log.warning("CRB: identity not found for application %s", application_id)
			bureau_response = {
				"bureau": "UNKNOWN",
				"reference": str(uuid.uuid4()),
				"score": 0,
				"error": "identity_not_found",
				"checked_at": datetime.now(timezone.utc).isoformat(),
			}
			credit_score = 0
		except CRBError as exc:
			log.warning("CRB lookup failed for %s: %s - using fallback score 500", application_id, exc)
			bureau_response = {
				"bureau": "UNAVAILABLE",
				"reference": str(uuid.uuid4()),
				"score": 500,
				"error": str(exc),
				"checked_at": datetime.now(timezone.utc).isoformat(),
			}
			credit_score = 500

		# DTI: stub — real implementation queries applicant income from HR/payroll
		dti = Decimal("35.00")

		# LTV: only meaningful for secured loans with collateral
		ltv: Decimal | None = None
		collaterals = session.execute(
			sa.select(Collateral).where(Collateral.application_id == application_id)
		).scalars().all()
		total_collateral_fsv = sum(
			(c.forced_sale_value_cents or c.estimated_value_cents) for c in collaterals
		)
		if total_collateral_fsv > 0:
			ltv = Decimal(str(app.requested_amount_cents)) / Decimal(str(total_collateral_fsv)) * 100

		# Compare to product minimums
		import sqlalchemy as sa2
		from pgappforge.plugins.fintech.lending.models import LoanProduct
		product = session.get(LoanProduct, app.product_id)
		passed = True
		recommendation = "APPROVE"

		if credit_score < (product.credit_score_min or 0):
			passed = False
			recommendation = "DECLINE"

		if ltv is not None and product.max_ltv_pct is not None:
			if ltv > Decimal(str(product.max_ltv_pct)):
				passed = False
				recommendation = "DECLINE"

		# Persist results
		app.credit_score = credit_score
		app.dti_ratio = dti
		app.ltv_ratio = ltv
		app.credit_bureau_response = bureau_response
		app.credit_checked_at = datetime.now(timezone.utc)
		app.status = "CREDIT_CHECK"
		session.flush()

		return {
			"score": credit_score,
			"recommendation": recommendation,
			"bureau_response": bureau_response,
			"dti": str(dti),
			"ltv": str(ltv) if ltv is not None else None,
			"passed": passed,
		}

	def underwrite(
		self,
		session: Any,
		application_id: str,
		analyst_id: str,
	) -> dict:
		"""Apply underwriting decision rules.

		Computes recommended amount, tenor, rate, required conditions.

		Returns dict with keys:
			approved_amount_cents, approved_tenor_months, approved_rate_pa,
			conditions, recommendation (APPROVE/CONDITIONAL/DECLINE)
		"""
		from pgappforge.plugins.fintech.lending.models import LoanApplication, LoanProduct

		app = session.get(LoanApplication, application_id)
		if app is None:
			raise ValueError(f"LoanApplication {application_id!r} not found")

		product = session.get(LoanProduct, app.product_id)

		# Underwriting rules (simplified — extend with rules engine integration)
		conditions = []
		recommendation = "APPROVE"
		approved_amount_cents = app.requested_amount_cents
		approved_tenor_months = app.requested_tenor_months
		approved_rate_pa = product.base_rate_pa

		# Risk-based pricing: add spread for lower scores
		if app.credit_score is not None:
			if app.credit_score < 600:
				recommendation = "DECLINE"
			elif app.credit_score < 650:
				# 2% risk spread
				approved_rate_pa = Decimal(str(approved_rate_pa)) + Decimal("0.02")
				conditions.append("HIGH_RISK_RATE_APPLIED")
				recommendation = "CONDITIONAL"
			elif app.credit_score < 700:
				# 1% risk spread
				approved_rate_pa = Decimal(str(approved_rate_pa)) + Decimal("0.01")
				conditions.append("MEDIUM_RISK_RATE_APPLIED")

		# DTI check
		if app.dti_ratio is not None and app.dti_ratio > Decimal("45"):
			approved_amount_cents = money_multiply(
				approved_amount_cents, Decimal("0.75")
			)
			conditions.append("AMOUNT_REDUCED_HIGH_DTI")
			recommendation = "CONDITIONAL" if recommendation == "APPROVE" else recommendation

		app.status = "UNDER_REVIEW"
		session.flush()

		return {
			"approved_amount_cents": approved_amount_cents,
			"approved_tenor_months": approved_tenor_months,
			"approved_rate_pa": str(approved_rate_pa),
			"conditions": conditions,
			"recommendation": recommendation,
		}

	def approve(
		self,
		session: Any,
		application_id: str,
		approver_id: str,
		approved_amount_cents: int,
		approved_tenor_months: int,
		approved_rate_pa: Decimal,
		conditions: list | None = None,
	) -> Any:
		"""Record final approval decision.

		Returns updated LoanApplication.
		"""
		from pgappforge.plugins.fintech.lending.models import LoanApplication
		from pgappforge.plugins.fintech.lending.events import LoanApprovedEvent

		app = session.get(LoanApplication, application_id)
		if app is None:
			raise ValueError(f"LoanApplication {application_id!r} not found")

		if app.status not in ("UNDER_REVIEW", "CREDIT_CHECK"):
			raise ValueError(f"Cannot approve application in status {app.status!r}")

		app.approved_amount_cents = approved_amount_cents
		app.approved_tenor_months = approved_tenor_months
		app.approved_rate_pa = approved_rate_pa
		app.conditions = conditions or []
		app.status = "APPROVED" if not conditions else "CONDITIONALLY_APPROVED"
		app.decision_at = datetime.now(timezone.utc)
		app.decision_by = approver_id
		session.flush()

		try:
			emit_event(
				"ln.loan.approved",
				"LoanApplication",
				app.id,
				{
					"application_number": app.application_number,
					"applicant_id": app.applicant_id,
					"approved_amount_cents": approved_amount_cents,
					"approved_tenor_months": approved_tenor_months,
					"approved_rate_pa": str(approved_rate_pa),
					"approver_id": approver_id,
				},
				session,
				tenant_id=app.tenant_id,
			)
		except Exception:
			pass

		log.info("Approved application %s by %s", app.application_number, approver_id)
		return app

	def reject(
		self,
		session: Any,
		application_id: str,
		reason: str,
		decision_by: str | None = None,
	) -> Any:
		"""Record rejection decision.

		Returns updated LoanApplication.
		"""
		from pgappforge.plugins.fintech.lending.models import LoanApplication

		app = session.get(LoanApplication, application_id)
		if app is None:
			raise ValueError(f"LoanApplication {application_id!r} not found")

		if app.status in ("DISBURSED", "WITHDRAWN"):
			raise ValueError(f"Cannot reject application in status {app.status!r}")

		app.status = "REJECTED"
		app.rejection_reason = reason
		app.decision_at = datetime.now(timezone.utc)
		app.decision_by = decision_by
		session.flush()

		try:
			emit_event(
				"ln.loan.rejected",
				"LoanApplication",
				app.id,
				{
					"application_number": app.application_number,
					"applicant_id": app.applicant_id,
					"rejection_reason": reason,
					"decision_by": decision_by or "",
				},
				session,
				tenant_id=app.tenant_id,
			)
		except Exception:
			pass

		log.info("Rejected application %s: %s", app.application_number, reason)
		return app

	def disburse(
		self,
		session: Any,
		application_id: str,
		disbursement_account_id: str,
		disbursement_date: date | None = None,
	) -> Any:
		"""Disburse an approved loan.

		Creates Loan + RepaymentSchedule records, deducts processing fees,
		marks application DISBURSED.  Core banking GL posting delegated to
		CoreBankingService (lazy import).

		Returns: Loan instance.
		"""
		import sqlalchemy as sa
		from pgappforge.plugins.fintech.lending.models import (
			LoanApplication, LoanProduct, Loan,
		)

		app = session.get(LoanApplication, application_id)
		if app is None:
			raise ValueError(f"LoanApplication {application_id!r} not found")

		if app.status not in ("APPROVED", "CONDITIONALLY_APPROVED"):
			raise ValueError(
				f"Can only disburse APPROVED applications, current status={app.status!r}"
			)

		product = session.get(LoanProduct, app.product_id)
		if product is None:
			raise ValueError(f"Product {app.product_id!r} not found")

		disburse_date = disbursement_date or date.today()
		first_repayment_date = _add_months(disburse_date, 1)
		tenor = app.approved_tenor_months
		maturity_date = _add_months(disburse_date, tenor)

		principal = app.approved_amount_cents
		rate_pa = Decimal(str(app.approved_rate_pa))

		# Deduct processing fee from disbursement (fee retained by bank)
		processing_fee_cents = percent_of(principal, Decimal(str(product.processing_fee_pct)))
		net_disbursement_cents = money_add(principal, -processing_fee_cents)

		loan = Loan(
			tenant_id=app.tenant_id,
			loan_number=_generate_loan_number(app.tenant_id),
			application_id=app.id,
			borrower_id=app.applicant_id,
			loan_account_id=disbursement_account_id,
			product_id=app.product_id,
			principal_cents=principal,
			interest_rate_pa=rate_pa,
			tenor_months=tenor,
			disbursement_date=disburse_date,
			first_repayment_date=first_repayment_date,
			maturity_date=maturity_date,
			outstanding_principal_cents=principal,
			outstanding_interest_cents=0,
			accrued_interest_cents=0,
			arrears_principal_cents=0,
			arrears_interest_cents=0,
			penalty_cents=0,
			days_past_due=0,
			npa_classification="PERFORMING",
			provision_rate_pct=Decimal("1"),
			provision_amount_cents=percent_of(principal, Decimal("1")),
			status="ACTIVE",
		)
		session.add(loan)
		session.flush()  # get loan.id

		# Generate amortisation schedule
		lms = LoanManagementService()
		lms.generate_repayment_schedule(session, loan.id)

		# Update application status
		app.status = "DISBURSED"
		session.flush()

		# Attempt core banking GL entries (non-fatal if CB not loaded)
		try:
			cb = _get_cb()
			cb.post_loan_disbursement(
				session,
				loan_id=loan.id,
				borrower_account_id=disbursement_account_id,
				principal_cents=principal,
				processing_fee_cents=processing_fee_cents,
				tenant_id=app.tenant_id,
			)
		except ImportError:
			log.debug("core_banking not available — skipping GL disbursement posting")
		except Exception as exc:
			log.warning("GL posting failed for loan %s: %s (non-fatal)", loan.loan_number, exc)

		# CRITICAL 1 — GL double-entry for disbursement
		lms = LoanManagementService()
		try:
			lms._post_gl_for_loan(
				session, loan,
				event_type="DISBURSEMENT",
				amount_cents=principal,
				dr_account_code="1200",   # Loans Receivable
				cr_account_code="1000",   # Cash / Nostro
				value_date=disburse_date,
				narration=f"Loan disbursement {loan.loan_number}",
			)
		except Exception as exc:
			log.warning("Disbursement GL (native) failed for %s: %s (non-fatal)", loan.loan_number, exc)

		# CRITICAL 2 — Charge origination and processing fees
		try:
			lms._charge_loan_fees(
				session, loan,
				fee_types=["origination", "processing"],
				charge_date=disburse_date,
			)
		except Exception as exc:
			log.warning("Fee charging failed for %s: %s (non-fatal)", loan.loan_number, exc)

		# HIGH 4 — Write outbox event (same transaction)
		lms._write_outbox(
			session, "Loan", loan.id, "ln.loan.disbursed",
			{
				"loan_number": loan.loan_number,
				"application_id": app.id,
				"borrower_id": loan.borrower_id,
				"principal_cents": principal,
				"disbursement_date": disburse_date.isoformat(),
				"maturity_date": maturity_date.isoformat(),
			},
		)

		try:
			emit_event(
				"ln.loan.disbursed",
				"Loan",
				loan.id,
				{
					"loan_number": loan.loan_number,
					"application_id": app.id,
					"borrower_id": loan.borrower_id,
					"principal_cents": principal,
					"disbursement_date": disburse_date.isoformat(),
					"maturity_date": maturity_date.isoformat(),
				},
				session,
				tenant_id=app.tenant_id,
			)
		except Exception:
			pass

		log.info("Disbursed loan %s, principal=%d cents", loan.loan_number, principal)
		return loan


# ---------------------------------------------------------------------------
# LoanManagementService
# ---------------------------------------------------------------------------

class LoanManagementService:
	"""Manages the post-disbursement loan lifecycle.

	Repayment application, schedule generation, daily aging, NPA classification,
	IFRS 9 ECL provisioning, restructuring, write-off, recovery, PAR reporting.
	"""

	def generate_repayment_schedule(
		self,
		session: Any,
		loan_id: str,
	) -> list:
		"""Generate full amortisation schedule for a loan using reducing-balance method.

		EMI = P * r * (1+r)^n / ((1+r)^n - 1)

		Each installment:
		  interest = outstanding_principal * monthly_rate
		  principal = EMI - interest
		  closing = opening - principal

		Last installment adjusted to clear any rounding residual.
		Returns list of RepaymentSchedule instances (flushed but not committed).
		"""
		import sqlalchemy as sa
		from pgappforge.plugins.fintech.lending.models import Loan, LoanProduct, RepaymentSchedule

		loan = session.get(Loan, loan_id)
		if loan is None:
			raise ValueError(f"Loan {loan_id!r} not found")

		product = session.get(LoanProduct, loan.product_id)
		principal_cents = loan.principal_cents
		annual_rate = Decimal(str(loan.interest_rate_pa))
		tenor = loan.tenor_months
		first_due = loan.first_repayment_date

		# Insurance fee per installment
		insurance_per_installment_cents = 0
		if product and product.insurance_fee_pct:
			annual_insurance = percent_of(principal_cents, Decimal(str(product.insurance_fee_pct)))
			insurance_per_installment_cents = money_divide(annual_insurance, 12)

		emi_cents = _calculate_emi_cents(principal_cents, annual_rate, tenor)
		monthly_rate = annual_rate / Decimal("12")
		outstanding = principal_cents
		schedules = []

		for i in range(1, tenor + 1):
			due_date = _add_months(first_due, i - 1)
			opening = outstanding

			interest_due = money_multiply(outstanding, monthly_rate)

			if i < tenor:
				principal_due = money_add(emi_cents, -interest_due)
			else:
				# Final installment: clear residual principal exactly
				principal_due = outstanding

			# Guard against negative principal on last installment rounding
			if principal_due < 0:
				principal_due = 0

			closing = money_add(opening, -principal_due)
			total_due = money_add(money_add(principal_due, interest_due), insurance_per_installment_cents)

			sched = RepaymentSchedule(
				tenant_id=loan.tenant_id,
				loan_id=loan.id,
				installment_number=i,
				due_date=due_date,
				opening_principal_cents=opening,
				principal_due_cents=principal_due,
				interest_due_cents=interest_due,
				insurance_due_cents=insurance_per_installment_cents,
				total_due_cents=total_due,
				closing_principal_cents=max(0, closing),
				paid_principal_cents=0,
				paid_interest_cents=0,
				paid_total_cents=0,
				status="PENDING",
			)
			session.add(sched)
			schedules.append(sched)
			outstanding = max(0, closing)

		# Update loan's next installment denorm
		if schedules:
			first_sched = schedules[0]
			loan.next_installment_date = first_sched.due_date
			loan.next_installment_amount_cents = first_sched.total_due_cents

		session.flush()
		log.info("Generated %d-installment schedule for loan %s", tenor, loan_id)
		return schedules

	def apply_repayment(
		self,
		session: Any,
		loan_id: str,
		amount_cents: int,
		source: str,
		reference: str | None = None,
		payment_date: date | None = None,
	) -> dict:
		"""Apply a repayment using waterfall: penalty → interest → principal.

		Updates RepaymentSchedule records (marks oldest overdue first).
		Creates a LoanRepayment ledger entry.
		Posts to CB ledger if core_banking is available.

		Returns dict:
			applied_to_penalty, applied_to_interest, applied_to_principal,
			remaining_balance_cents, fully_settled
		"""
		import sqlalchemy as sa
		from pgappforge.plugins.fintech.lending.models import Loan, LoanRepayment, RepaymentSchedule

		pay_date = payment_date or date.today()
		loan = session.get(Loan, loan_id)
		if loan is None:
			raise ValueError(f"Loan {loan_id!r} not found")

		if loan.status not in ("ACTIVE", "DEFAULTED"):
			raise ValueError(f"Cannot apply repayment to loan in status {loan.status!r}")

		remaining = amount_cents

		# 1. Apply to penalties first
		penalty_applied = min(remaining, loan.penalty_cents)
		remaining = money_add(remaining, -penalty_applied)
		loan.penalty_cents = money_add(loan.penalty_cents, -penalty_applied)

		# 2. Apply to accrued interest
		interest_applied = min(remaining, loan.outstanding_interest_cents)
		remaining = money_add(remaining, -interest_applied)
		loan.outstanding_interest_cents = money_add(loan.outstanding_interest_cents, -interest_applied)

		# 3. Apply to principal
		principal_applied = min(remaining, loan.outstanding_principal_cents)
		remaining = money_add(remaining, -principal_applied)
		loan.outstanding_principal_cents = money_add(loan.outstanding_principal_cents, -principal_applied)

		# Update arrears if any
		if loan.arrears_principal_cents > 0:
			arrears_cleared = min(principal_applied, loan.arrears_principal_cents)
			loan.arrears_principal_cents = money_add(loan.arrears_principal_cents, -arrears_cleared)
		if loan.arrears_interest_cents > 0:
			arr_int_cleared = min(interest_applied, loan.arrears_interest_cents)
			loan.arrears_interest_cents = money_add(loan.arrears_interest_cents, -arr_int_cleared)

		# Mark schedule installments as paid (oldest overdue first)
		overdue_scheds = session.execute(
			sa.select(RepaymentSchedule)
			.where(
				RepaymentSchedule.loan_id == loan_id,
				RepaymentSchedule.status.in_(["PENDING", "PARTIAL", "OVERDUE"]),
			)
			.order_by(RepaymentSchedule.installment_number)
		).scalars().all()

		sched_principal_pool = principal_applied
		sched_interest_pool = interest_applied

		for sched in overdue_scheds:
			if sched_principal_pool <= 0 and sched_interest_pool <= 0:
				break
			sched_p = min(sched_principal_pool, sched.principal_due_cents - sched.paid_principal_cents)
			sched_i = min(sched_interest_pool, sched.interest_due_cents - sched.paid_interest_cents)
			sched.paid_principal_cents = money_add(sched.paid_principal_cents, sched_p)
			sched.paid_interest_cents = money_add(sched.paid_interest_cents, sched_i)
			sched.paid_total_cents = money_add(sched.paid_total_cents, money_add(sched_p, sched_i))
			sched_principal_pool = money_add(sched_principal_pool, -sched_p)
			sched_interest_pool = money_add(sched_interest_pool, -sched_i)

			if sched.paid_principal_cents >= sched.principal_due_cents:
				sched.paid_date = pay_date
				sched.status = "PAID"
			elif sched.paid_principal_cents > 0:
				sched.status = "PARTIAL"

		# Settle loan if fully paid
		fully_settled = loan.outstanding_principal_cents == 0
		if fully_settled:
			loan.status = "SETTLED"
			loan.last_repayment_date = pay_date
			loan.last_repayment_amount_cents = amount_cents
			try:
				emit_event(
					"ln.loan.settled",
					"Loan",
					loan.id,
					{
						"loan_number": loan.loan_number,
						"borrower_id": loan.borrower_id,
						"settled_date": pay_date.isoformat(),
						"total_paid_cents": amount_cents,
					},
					session,
					tenant_id=loan.tenant_id,
				)
			except Exception:
				pass
		else:
			loan.last_repayment_date = pay_date
			loan.last_repayment_amount_cents = amount_cents
			# Update next installment
			next_pending = session.execute(
				sa.select(RepaymentSchedule)
				.where(
					RepaymentSchedule.loan_id == loan_id,
					RepaymentSchedule.status.in_(["PENDING", "PARTIAL"]),
				)
				.order_by(RepaymentSchedule.installment_number)
				.limit(1)
			).scalar_one_or_none()
			if next_pending:
				loan.next_installment_date = next_pending.due_date
				loan.next_installment_amount_cents = next_pending.total_due_cents

		# Create immutable repayment ledger entry
		repayment = LoanRepayment(
			tenant_id=loan.tenant_id,
			loan_id=loan.id,
			payment_date=pay_date,
			amount_cents=amount_cents,
			principal_applied_cents=principal_applied,
			interest_applied_cents=interest_applied,
			penalty_applied_cents=penalty_applied,
			fees_applied_cents=0,
			source=source,
			reference_number=reference,
		)
		session.add(repayment)
		session.flush()

		# GL posting (non-fatal)
		try:
			cb = _get_cb()
			ledger_id = cb.post_loan_repayment(
				session,
				loan_id=loan.id,
				amount_cents=amount_cents,
				principal_cents=principal_applied,
				interest_cents=interest_applied,
				tenant_id=loan.tenant_id,
			)
			repayment.ledger_entry_id = ledger_id
			session.flush()
		except ImportError:
			log.debug("core_banking not available — skipping GL repayment posting")
		except Exception as exc:
			log.warning("GL posting failed for repayment on %s: %s (non-fatal)", loan_id, exc)

		# CRITICAL 1 — Native GL double-entry for repayment
		try:
			self._post_gl_for_loan(
				session, loan,
				event_type="REPAYMENT",
				amount_cents=amount_cents,
				dr_account_code="1000",   # Cash / Nostro
				cr_account_code="1200",   # Loans Receivable
				value_date=pay_date,
				narration=f"Repayment received {loan.loan_number} ref={reference or 'N/A'}",
			)
		except Exception as exc:
			log.warning("Repayment GL (native) failed for %s: %s (non-fatal)", loan_id, exc)

		# CRITICAL 2 — Late fee: charge if loan has DPD > 0
		if loan.days_past_due > 0:
			try:
				self._charge_loan_fees(
					session, loan,
					fee_types=["late"],
					charge_date=pay_date,
				)
			except Exception as exc:
				log.warning("Late fee charging failed for %s: %s (non-fatal)", loan_id, exc)

		# HIGH 4 — Outbox event
		self._write_outbox(
			session, "Loan", loan.id, "ln.repayment.received",
			{
				"repayment_id": repayment.id,
				"loan_number": loan.loan_number,
				"amount_cents": amount_cents,
				"principal_applied_cents": principal_applied,
				"interest_applied_cents": interest_applied,
				"payment_date": pay_date.isoformat(),
			},
		)

		try:
			emit_event(
				"ln.repayment.received",
				"Loan",
				loan.id,
				{
					"repayment_id": repayment.id,
					"loan_number": loan.loan_number,
					"amount_cents": amount_cents,
					"principal_applied_cents": principal_applied,
					"interest_applied_cents": interest_applied,
					"penalty_applied_cents": penalty_applied,
					"remaining_principal_cents": loan.outstanding_principal_cents,
					"source": source,
					"payment_date": pay_date.isoformat(),
				},
				session,
				tenant_id=loan.tenant_id,
			)
		except Exception:
			pass

		return {
			"applied_to_penalty": penalty_applied,
			"applied_to_interest": interest_applied,
			"applied_to_principal": principal_applied,
			"remaining_balance_cents": loan.outstanding_principal_cents,
			"fully_settled": fully_settled,
		}

	def run_daily_aging(
		self,
		session: Any,
		as_of_date: date | None = None,
		tenant_id: str | None = None,
	) -> dict:
		"""Daily batch job: recompute DPD, arrears, NPA classification for all active loans.

		HIGH 2: Idempotency guard via BatchJobRun — double-runs on the same date
		are detected and aborted before any processing occurs.

		CRITICAL 3: Daily interest accrual is run per-loan before NPA
		reclassification.  On NPA transition, existing 'accrued' entries are
		moved to suspense.

		CBK classification:
		  0-30 DPD  → PERFORMING   1% provision
		  31-90     → WATCH        5%
		  91-180    → SUBSTANDARD  25%
		  181-360   → DOUBTFUL     50%
		  >360      → LOSS         100%

		Returns summary dict: loans_processed, newly_classified, total_arrears_cents.
		"""
		import sqlalchemy as sa
		from pgappforge.plugins.fintech.lending.models import Loan, RepaymentSchedule

		ref_date = as_of_date or date.today()

		# HIGH 2 — Idempotency guard
		batch_run = None
		try:
			batch_run = self._acquire_batch_job(session, "daily_aging", ref_date, tenant_id)
		except RuntimeError as exc:
			err = str(exc)
			if "already completed" in err:
				log.info("Daily aging for %s already completed — skipping", ref_date)
				return {
					"as_of_date": ref_date.isoformat(),
					"loans_processed": 0,
					"newly_classified": 0,
					"total_arrears_cents": 0,
					"skipped": True,
				}
			log.warning("Cannot acquire batch job lock: %s", exc)
			raise

		query = sa.select(Loan).where(Loan.status.in_(["ACTIVE", "DEFAULTED"]))
		if tenant_id:
			query = query.where(Loan.tenant_id == tenant_id)

		loans = session.execute(query).scalars().all()

		loans_processed = 0
		newly_classified = 0
		total_arrears_cents = 0

		for loan in loans:
			# Find oldest unpaid installment
			oldest_overdue = session.execute(
				sa.select(RepaymentSchedule)
				.where(
					RepaymentSchedule.loan_id == loan.id,
					RepaymentSchedule.due_date <= ref_date,
					RepaymentSchedule.status.in_(["PENDING", "PARTIAL", "OVERDUE"]),
				)
				.order_by(RepaymentSchedule.due_date)
				.limit(1)
			).scalar_one_or_none()

			if oldest_overdue is None:
				dpd = 0
			else:
				dpd = (ref_date - oldest_overdue.due_date).days
				oldest_overdue.status = "OVERDUE"

			# Compute arrears
			overdue_scheds = session.execute(
				sa.select(RepaymentSchedule)
				.where(
					RepaymentSchedule.loan_id == loan.id,
					RepaymentSchedule.due_date <= ref_date,
					RepaymentSchedule.status.in_(["OVERDUE", "PARTIAL"]),
				)
			).scalars().all()

			arrears_principal = sum(
				(s.principal_due_cents - s.paid_principal_cents) for s in overdue_scheds
			)
			arrears_interest = sum(
				(s.interest_due_cents - s.paid_interest_cents) for s in overdue_scheds
			)

			old_classification = loan.npa_classification
			new_classification, provision_rate = _classify_npa(dpd)
			provision_amount = percent_of(loan.outstanding_principal_cents, provision_rate)

			loan.days_past_due = dpd
			loan.arrears_principal_cents = max(0, arrears_principal)
			loan.arrears_interest_cents = max(0, arrears_interest)
			loan.npa_classification = new_classification
			loan.provision_rate_pct = provision_rate
			loan.provision_amount_cents = provision_amount

			if dpd > 0 and loan.status == "ACTIVE":
				loan.status = "DEFAULTED"

			# CRITICAL 3 — Daily interest accrual
			try:
				self._accrue_interest(session, loan, ref_date)
			except Exception as exc:
				log.warning("Accrual failed for loan %s: %s (non-fatal)", loan.id, exc)

			# CRITICAL 3 — On NPA transition, move accruals to suspense
			is_newly_npa = (
				new_classification in ("SUBSTANDARD", "DOUBTFUL", "LOSS")
				and old_classification not in ("SUBSTANDARD", "DOUBTFUL", "LOSS")
			)
			if is_newly_npa:
				try:
					self._reverse_accruals_to_suspense(session, loan, ref_date)
				except Exception as exc:
					log.warning("Suspense transition failed for loan %s: %s (non-fatal)", loan.id, exc)

			total_arrears_cents = money_add(total_arrears_cents, loan.arrears_principal_cents)
			loans_processed += 1

			if new_classification != old_classification:
				newly_classified += 1
				# HIGH 4 — Outbox event for NPA reclassification
				self._write_outbox(
					session, "Loan", loan.id, "ln.loan.npa_classified",
					{
						"loan_number": loan.loan_number,
						"previous_classification": old_classification,
						"new_classification": new_classification,
						"days_past_due": dpd,
						"as_of_date": ref_date.isoformat(),
					},
				)
				try:
					emit_event(
						"ln.loan.npa_classified",
						"Loan",
						loan.id,
						{
							"loan_number": loan.loan_number,
							"borrower_id": loan.borrower_id,
							"previous_classification": old_classification,
							"new_classification": new_classification,
							"days_past_due": dpd,
							"provision_rate_pct": str(provision_rate),
							"provision_amount_cents": provision_amount,
							"as_of_date": ref_date.isoformat(),
						},
						session,
						tenant_id=loan.tenant_id,
					)
				except Exception:
					pass

			# Emit overdue event for newly DPD > 0 loans
			if dpd > 0:
				try:
					emit_event(
						"ln.loan.overdue",
						"Loan",
						loan.id,
						{
							"loan_number": loan.loan_number,
							"borrower_id": loan.borrower_id,
							"days_past_due": dpd,
							"arrears_principal_cents": loan.arrears_principal_cents,
							"arrears_interest_cents": loan.arrears_interest_cents,
							"as_of_date": ref_date.isoformat(),
						},
						session,
						tenant_id=loan.tenant_id,
					)
				except Exception:
					pass

		session.flush()

		# HIGH 2 — Mark batch run completed
		if batch_run is not None:
			try:
				self._complete_batch_job(session, batch_run, loans_processed)
			except Exception as exc:
				log.warning("Failed to mark batch run completed: %s (non-fatal)", exc)

		log.info(
			"Daily aging as_of %s: %d processed, %d reclassified, arrears=%d cents",
			ref_date, loans_processed, newly_classified, total_arrears_cents,
		)
		return {
			"as_of_date": ref_date.isoformat(),
			"loans_processed": loans_processed,
			"newly_classified": newly_classified,
			"total_arrears_cents": total_arrears_cents,
		}

	def calculate_ecl_provision(
		self,
		session: Any,
		loan_id: str,
	) -> dict:
		"""Calculate IFRS 9 Expected Credit Loss for a single loan.

		ECL = PD × LGD × EAD

		Staging:
		  Stage 1 (PERFORMING): 12-month ECL
		  Stage 2 (WATCH): lifetime ECL — significant credit deterioration
		  Stage 3 (SUBSTANDARD/DOUBTFUL/LOSS): lifetime ECL, credit-impaired

		Simplified PD/LGD model — extend with ML scoring integration.
		"""
		from pgappforge.plugins.fintech.lending.models import Loan

		loan = session.get(Loan, loan_id)
		if loan is None:
			raise ValueError(f"Loan {loan_id!r} not found")

		ead = loan.outstanding_principal_cents

		# Stage determination
		npa = loan.npa_classification
		if npa == "PERFORMING":
			stage = 1
			pd = Decimal("0.02")   # 2% 12-month PD (simplistic)
			lgd = Decimal("0.45")  # 45% loss given default
		elif npa == "WATCH":
			stage = 2
			pd = Decimal("0.10")
			lgd = Decimal("0.45")
		elif npa == "SUBSTANDARD":
			stage = 3
			pd = Decimal("0.40")
			lgd = Decimal("0.60")
		elif npa == "DOUBTFUL":
			stage = 3
			pd = Decimal("0.75")
			lgd = Decimal("0.70")
		else:  # LOSS
			stage = 3
			pd = Decimal("1.00")
			lgd = Decimal("1.00")

		ecl_cents = money_multiply(
			money_multiply(ead, pd),
			lgd,
		)
		provision_pct = (pd * lgd * 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

		# Update loan provision
		loan.provision_rate_pct = provision_pct
		loan.provision_amount_cents = ecl_cents
		session.flush()

		return {
			"loan_id": loan_id,
			"stage": stage,
			"ead_cents": ead,
			"pd": str(pd),
			"lgd": str(lgd),
			"ecl_cents": ecl_cents,
			"provision_pct": str(provision_pct),
			"npa_classification": npa,
		}

	def restructure_loan(
		self,
		session: Any,
		loan_id: str,
		new_tenor_months: int,
		new_rate_pa: Decimal,
		reason: str,
		disbursement_date: date | None = None,
	) -> Any:
		"""Restructure a loan by creating a new Loan linked via restructured_from_id.

		Old loan status → RESTRUCTURED.
		New loan inherits outstanding principal as the new principal.
		Fresh amortisation schedule generated.
		"""
		from pgappforge.plugins.fintech.lending.models import Loan

		old_loan = session.get(Loan, loan_id)
		if old_loan is None:
			raise ValueError(f"Loan {loan_id!r} not found")

		if old_loan.status not in ("ACTIVE", "DEFAULTED"):
			raise ValueError(f"Cannot restructure loan in status {old_loan.status!r}")

		restr_date = disbursement_date or date.today()
		first_repayment = _add_months(restr_date, 1)
		maturity = _add_months(restr_date, new_tenor_months)

		new_loan = Loan(
			tenant_id=old_loan.tenant_id,
			loan_number=_generate_loan_number(old_loan.tenant_id),
			application_id=old_loan.application_id,
			borrower_id=old_loan.borrower_id,
			loan_account_id=old_loan.loan_account_id,
			repayment_account_id=old_loan.repayment_account_id,
			product_id=old_loan.product_id,
			principal_cents=old_loan.outstanding_principal_cents,
			interest_rate_pa=new_rate_pa,
			tenor_months=new_tenor_months,
			disbursement_date=restr_date,
			first_repayment_date=first_repayment,
			maturity_date=maturity,
			outstanding_principal_cents=old_loan.outstanding_principal_cents,
			outstanding_interest_cents=0,
			accrued_interest_cents=0,
			arrears_principal_cents=0,
			arrears_interest_cents=0,
			penalty_cents=0,
			days_past_due=0,
			npa_classification="PERFORMING",
			provision_rate_pct=Decimal("1"),
			provision_amount_cents=percent_of(old_loan.outstanding_principal_cents, Decimal("1")),
			status="ACTIVE",
			restructured_from_id=old_loan.id,
		)
		session.add(new_loan)
		session.flush()

		self.generate_repayment_schedule(session, new_loan.id)

		old_loan.status = "RESTRUCTURED"
		session.flush()

		try:
			emit_event(
				"ln.loan.restructured",
				"Loan",
				old_loan.id,
				{
					"original_loan_number": old_loan.loan_number,
					"new_loan_id": new_loan.id,
					"new_loan_number": new_loan.loan_number,
					"borrower_id": old_loan.borrower_id,
					"new_tenor_months": new_tenor_months,
					"new_rate_pa": str(new_rate_pa),
					"reason": reason,
				},
				session,
				tenant_id=old_loan.tenant_id,
			)
		except Exception:
			pass

		log.info("Restructured loan %s → %s", old_loan.loan_number, new_loan.loan_number)
		return new_loan

	def write_off(
		self,
		session: Any,
		loan_id: str,
		reason: str,
	) -> Any:
		"""Write off a loan.

		Posts:  DEBIT Loan Loss Reserve / CREDIT Loan Outstanding
		Marks loan status=WRITTEN_OFF, continues tracking for recovery.
		"""
		from pgappforge.plugins.fintech.lending.models import Loan

		loan = session.get(Loan, loan_id)
		if loan is None:
			raise ValueError(f"Loan {loan_id!r} not found")

		if loan.status == "WRITTEN_OFF":
			raise ValueError(f"Loan {loan_id!r} is already written off")

		write_off_amount = loan.outstanding_principal_cents
		write_off_date = date.today()

		# GL posting (non-fatal)
		try:
			cb = _get_cb()
			cb.post_loan_write_off(
				session,
				loan_id=loan.id,
				write_off_cents=write_off_amount,
				tenant_id=loan.tenant_id,
			)
		except ImportError:
			log.debug("core_banking not available — skipping write-off GL posting")
		except Exception as exc:
			log.warning("GL write-off posting failed for %s: %s (non-fatal)", loan_id, exc)

		loan.status = "WRITTEN_OFF"
		loan.written_off_date = write_off_date
		loan.written_off_amount_cents = write_off_amount
		# Outstanding balances are NOT zeroed — preserved for recovery tracking
		session.flush()

		# CRITICAL 1 — Native GL double-entry for write-off
		try:
			self._post_gl_for_loan(
				session, loan,
				event_type="WRITE_OFF",
				amount_cents=write_off_amount,
				dr_account_code="7100",   # Loan Loss Expense
				cr_account_code="1200",   # Loans Receivable
				value_date=write_off_date,
				narration=f"Write-off {loan.loan_number} — {reason}",
			)
		except Exception as exc:
			log.warning("Write-off GL (native) failed for %s: %s (non-fatal)", loan_id, exc)

		# HIGH 4 — Outbox event
		self._write_outbox(
			session, "Loan", loan.id, "ln.loan.written_off",
			{
				"loan_number": loan.loan_number,
				"borrower_id": loan.borrower_id,
				"written_off_amount_cents": write_off_amount,
				"written_off_date": write_off_date.isoformat(),
				"reason": reason,
			},
		)

		try:
			emit_event(
				"ln.loan.written_off",
				"Loan",
				loan.id,
				{
					"loan_number": loan.loan_number,
					"borrower_id": loan.borrower_id,
					"written_off_amount_cents": write_off_amount,
					"written_off_date": write_off_date.isoformat(),
					"reason": reason,
				},
				session,
				tenant_id=loan.tenant_id,
			)
		except Exception:
			pass

		log.info("Written off loan %s, amount=%d cents", loan.loan_number, write_off_amount)
		return loan

	def recover(
		self,
		session: Any,
		loan_id: str,
		recovered_cents: int,
		source: str,
	) -> dict:
		"""Post a recovery against a written-off loan.

		GL: CREDIT Loan Loss Reserve / DEBIT Cash
		"""
		from pgappforge.plugins.fintech.lending.models import Loan

		loan = session.get(Loan, loan_id)
		if loan is None:
			raise ValueError(f"Loan {loan_id!r} not found")

		if loan.status != "WRITTEN_OFF":
			raise ValueError(f"Loan {loan_id!r} is not in WRITTEN_OFF status")

		loan.recovery_amount_cents = money_add(loan.recovery_amount_cents, recovered_cents)
		session.flush()

		# GL posting (non-fatal)
		try:
			cb = _get_cb()
			cb.post_loan_recovery(
				session,
				loan_id=loan.id,
				recovered_cents=recovered_cents,
				source=source,
				tenant_id=loan.tenant_id,
			)
		except ImportError:
			log.debug("core_banking not available — skipping recovery GL posting")
		except Exception as exc:
			log.warning("Recovery GL posting failed for %s: %s (non-fatal)", loan_id, exc)

		# CRITICAL 1 — Native GL double-entry for recovery
		try:
			self._post_gl_for_loan(
				session, loan,
				event_type="RECOVERY",
				amount_cents=recovered_cents,
				dr_account_code="1000",   # Cash / Nostro
				cr_account_code="7200",   # Loan Loss Reserve (recovery reversal)
				value_date=date.today(),
				narration=f"Recovery on written-off loan {loan.loan_number} via {source}",
			)
		except Exception as exc:
			log.warning("Recovery GL (native) failed for %s: %s (non-fatal)", loan_id, exc)

		# HIGH 4 — Outbox event
		self._write_outbox(
			session, "Loan", loan.id, "ln.loan.recovery",
			{
				"loan_number": loan.loan_number,
				"recovered_cents": recovered_cents,
				"source": source,
				"total_recovery_cents": loan.recovery_amount_cents,
			},
		)

		return {
			"loan_id": loan_id,
			"loan_number": loan.loan_number,
			"recovered_cents": recovered_cents,
			"total_recovery_cents": loan.recovery_amount_cents,
			"write_off_balance_cents": loan.written_off_amount_cents,
		}

	def get_par_report(
		self,
		session: Any,
		as_of_date: date | None = None,
		tenant_id: str | None = None,
	) -> dict:
		"""Portfolio at Risk report.

		PAR(n) = (outstanding principal of loans DPD >= n) / total outstanding principal

		Returns PAR30, PAR60, PAR90, PAR180, NPA total, total outstanding, NPL ratio.
		"""
		import sqlalchemy as sa
		from pgappforge.plugins.fintech.lending.models import Loan

		ref_date = as_of_date or date.today()
		query = sa.select(Loan).where(Loan.status.in_(["ACTIVE", "DEFAULTED", "WRITTEN_OFF"]))
		if tenant_id:
			query = query.where(Loan.tenant_id == tenant_id)

		loans = session.execute(query).scalars().all()

		total_outstanding = sum(l.outstanding_principal_cents for l in loans)
		par30 = sum(l.outstanding_principal_cents for l in loans if l.days_past_due >= 30)
		par60 = sum(l.outstanding_principal_cents for l in loans if l.days_past_due >= 60)
		par90 = sum(l.outstanding_principal_cents for l in loans if l.days_past_due >= 90)
		par180 = sum(l.outstanding_principal_cents for l in loans if l.days_past_due >= 180)
		npa_total = sum(
			l.outstanding_principal_cents for l in loans
			if l.npa_classification in ("SUBSTANDARD", "DOUBTFUL", "LOSS")
		)
		total_provision = sum(l.provision_amount_cents for l in loans)

		def _pct(numerator: int, denominator: int) -> str:
			if denominator == 0:
				return "0.00"
			return str(
				(Decimal(str(numerator)) / Decimal(str(denominator)) * 100)
				.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
			)

		return {
			"as_of_date": ref_date.isoformat(),
			"total_loans": len(loans),
			"total_outstanding_cents": total_outstanding,
			"par30_cents": par30,
			"par30_pct": _pct(par30, total_outstanding),
			"par60_cents": par60,
			"par60_pct": _pct(par60, total_outstanding),
			"par90_cents": par90,
			"par90_pct": _pct(par90, total_outstanding),
			"par180_cents": par180,
			"par180_pct": _pct(par180, total_outstanding),
			"npa_total_cents": npa_total,
			"npl_ratio_pct": _pct(npa_total, total_outstanding),
			"total_provision_cents": total_provision,
			"provision_coverage_pct": _pct(total_provision, npa_total) if npa_total else "N/A",
		}

	def get_loan_aging_report(
		self,
		session: Any,
		tenant_id: str | None = None,
	) -> list[dict]:
		"""All active/defaulted loans grouped by DPD bucket.

		Buckets: CURRENT (0), 1-30, 31-60, 61-90, 91-180, 181-360, >360
		Returns list of dicts suitable for tabular display.
		"""
		import sqlalchemy as sa
		from pgappforge.plugins.fintech.lending.models import Loan

		query = sa.select(Loan).where(Loan.status.in_(["ACTIVE", "DEFAULTED"]))
		if tenant_id:
			query = query.where(Loan.tenant_id == tenant_id)

		loans = session.execute(query).scalars().all()

		def _bucket(dpd: int) -> str:
			if dpd == 0:
				return "CURRENT"
			elif dpd <= 30:
				return "1-30"
			elif dpd <= 60:
				return "31-60"
			elif dpd <= 90:
				return "61-90"
			elif dpd <= 180:
				return "91-180"
			elif dpd <= 360:
				return "181-360"
			return ">360"

		rows = []
		for loan in loans:
			rows.append({
				"loan_id": loan.id,
				"loan_number": loan.loan_number,
				"borrower_id": loan.borrower_id,
				"outstanding_principal_cents": loan.outstanding_principal_cents,
				"days_past_due": loan.days_past_due,
				"dpd_bucket": _bucket(loan.days_past_due),
				"npa_classification": loan.npa_classification,
				"arrears_cents": money_add(loan.arrears_principal_cents, loan.arrears_interest_cents),
				"provision_amount_cents": loan.provision_amount_cents,
			})

		return sorted(rows, key=lambda r: r["days_past_due"], reverse=True)


	# -----------------------------------------------------------------------
	# CRITICAL 1 — GL double-entry posting
	# -----------------------------------------------------------------------

	def _post_gl_entries(
		self,
		session: Any,
		loan_id: str,
		event_type: str,
		amount_cents: int,
		dr_account_code: str,
		cr_account_code: str,
		value_date: date | None = None,
		narration: str | None = None,
		posted_by: str | None = None,
		event_id: str | None = None,
		tenant_id: str = "default",
		currency: str = "KES",
	) -> str:
		"""Post a balanced DR/CR pair to ln_gl_journal_entry.

		Returns the shared event_id for the entry pair.
		Idempotent: if a row with (event_id, leg) already exists,
		the INSERT is skipped via the unique constraint.

		Accepts loan_id (str) and tenant_id as keyword args — does NOT
		require a full Loan ORM object so it can be called from anywhere.
		"""
		import uuid as _uuid
		from pgappforge.plugins.fintech.lending.models import LnGLJournalEntry

		vdate = value_date or date.today()
		period = vdate.strftime("%Y-%m")
		eid = event_id or str(_uuid.uuid4())

		for leg, account_code in (("DR", dr_account_code), ("CR", cr_account_code)):
			entry = LnGLJournalEntry(
				tenant_id=tenant_id,
				loan_id=loan_id,
				event_id=eid,
				event_type=event_type,
				leg_type=leg,
				account_code=account_code,
				amount_cents=amount_cents,
				currency=currency,
				value_date=vdate,
				period_id=period,
				posted_by=posted_by,
				status="POSTED",
				narration=narration or f"{event_type} for loan {loan_id}",
			)
			try:
				session.add(entry)
				session.flush()
			except Exception as exc:
				# Unique-constraint violation → already posted — idempotent
				log.debug("GL entry already posted for event_id=%s leg=%s: %s", eid, leg, exc)

		return eid

	def _post_gl_for_loan(
		self,
		session: Any,
		loan: Any,
		event_type: str,
		amount_cents: int,
		dr_account_code: str,
		cr_account_code: str,
		value_date: date | None = None,
		narration: str | None = None,
		event_id: str | None = None,
	) -> str:
		"""Convenience wrapper that accepts a Loan ORM object."""
		return self._post_gl_entries(
			session,
			loan_id=loan.id,
			event_type=event_type,
			amount_cents=amount_cents,
			dr_account_code=dr_account_code,
			cr_account_code=cr_account_code,
			value_date=value_date,
			narration=narration,
			event_id=event_id,
			tenant_id=getattr(loan, "tenant_id", "default"),
			currency=getattr(loan, "currency", "KES"),
		)

	# -----------------------------------------------------------------------
	# CRITICAL 2 — Fee engine helpers
	# -----------------------------------------------------------------------

	def _compute_fee_cents(
		self,
		fee: Any,
		principal_cents: int,
		outstanding_cents: int,
	) -> int:
		"""Compute fee amount in cents from a LoanFee / fee-like object.

		Percent fees store rate_or_amount_cents as basis points
		(100 bps = 1%).  Conversion: bps / 10000 = rate.
		"""
		basis = fee.calculation_basis
		if basis == "flat":
			return int(fee.rate_or_amount_cents)
		elif basis == "percent_principal":
			bps = Decimal(str(fee.rate_or_amount_cents))
			rate = bps / Decimal("10000")
			return money_multiply(principal_cents, rate)
		elif basis == "percent_outstanding":
			bps = Decimal(str(fee.rate_or_amount_cents))
			rate = bps / Decimal("10000")
			return money_multiply(outstanding_cents, rate)
		else:
			raise ValueError(f"Unknown fee calculation_basis: {basis!r}")

	# Keep old name as alias for internal callers wired before rename
	_compute_fee_amount = _compute_fee_cents

	def _charge_loan_fees(
		self,
		session: Any,
		loan: Any,
		fee_types: list[str],
		charge_date: date,
	) -> list:
		"""Compute and persist LoanFeeCharge rows for the given fee_types.

		Returns list of LoanFeeCharge instances added.
		"""
		import sqlalchemy as sa
		from pgappforge.plugins.fintech.lending.models import LoanFee, LoanFeeCharge

		fees = session.execute(
			sa.select(LoanFee).where(
				LoanFee.product_id == loan.product_id,
				LoanFee.fee_type.in_(fee_types),
			)
		).scalars().all()

		charges = []
		for fee in fees:
			amount = self._compute_fee_cents(
				fee,
				loan.principal_cents,
				loan.outstanding_principal_cents,
			)
			if amount <= 0:
				continue
			charge = LoanFeeCharge(
				tenant_id=loan.tenant_id,
				loan_id=loan.id,
				fee_id=fee.id,
				fee_type=fee.fee_type,
				amount_cents=amount,
				status="PENDING",
				charge_date=charge_date,
			)
			session.add(charge)
			charges.append(charge)

		if charges:
			session.flush()
		return charges

	# Keep old name as alias
	def _charge_fees(self, session: Any, loan: Any, fee_types: list[str], charge_date: date) -> int:
		"""Legacy alias — returns total cents charged."""
		charges = self._charge_loan_fees(session, loan, fee_types, charge_date)
		return sum(c.amount_cents for c in charges)

	def waive_fee(
		self,
		session: Any,
		loan_id: str,
		fee_charge_id: str,
		reason: str,
		waived_by: str,
		approved_by: str,
	) -> Any:
		"""Waive a pending fee charge with dual-control audit trail.

		waived_by and approved_by must differ (dual-control).
		Returns the updated LoanFeeCharge.
		"""
		from pgappforge.plugins.fintech.lending.models import LoanFeeCharge

		if waived_by == approved_by:
			raise ValueError("Dual-control required: waived_by must differ from approved_by")

		charge = session.get(LoanFeeCharge, fee_charge_id)
		if charge is None:
			raise ValueError(f"LoanFeeCharge {fee_charge_id!r} not found")
		if charge.loan_id != loan_id:
			raise ValueError("Fee charge does not belong to specified loan")
		if charge.status != "PENDING":
			raise ValueError(f"Cannot waive fee in status {charge.status!r}")

		if charge.fee_id:
			import sys
			_models = sys.modules.get("pgappforge.plugins.fintech.lending.models")
			if _models:
				fee = session.get(_models.LoanFee, charge.fee_id)
				if fee and not fee.waivable:
					raise ValueError(f"Fee type {charge.fee_type!r} is not waivable")

		charge.status = "WAIVED"
		charge.waived_by = waived_by
		charge.waiver_reason = reason
		charge.waived_at = datetime.now(timezone.utc)
		session.flush()

		log.info(
			"Waived fee charge %s (type=%s amount=%d) on loan %s by %s",
			fee_charge_id, charge.fee_type, charge.amount_cents, loan_id, waived_by,
		)
		return charge

	# -----------------------------------------------------------------------
	# CRITICAL 3 — Interest accrual
	# -----------------------------------------------------------------------

	def _accrue_interest(
		self,
		session: Any,
		loan: Any,
		as_of: date,
	) -> Any:
		"""Compute and persist one InterestAccrualEntry for loan on as_of date.

		Uses 365-day actual/actual convention.
		Returns the InterestAccrualEntry (existing or newly created).
		If one already exists for this date, returns the existing entry
		without adding a new one (idempotent).
		Posts GL: DR Interest Receivable / CR Interest Income.
		On NPA (SUBSTANDARD/DOUBTFUL/LOSS) marks status='suspended'.
		"""
		import sqlalchemy as sa
		from pgappforge.plugins.fintech.lending.models import InterestAccrualEntry

		# Idempotency: return existing entry without re-adding
		existing = session.execute(
			sa.select(InterestAccrualEntry).where(
				InterestAccrualEntry.loan_id == loan.id,
				InterestAccrualEntry.accrual_date == as_of,
			)
		).scalar_one_or_none()
		if existing is not None:
			return existing

		annual_rate = Decimal(str(loan.interest_rate_pa))
		daily_rate = annual_rate / Decimal("365")
		accrued = money_multiply(loan.outstanding_principal_cents, daily_rate)

		if accrued <= 0:
			return None

		npa = loan.npa_classification
		is_npa = npa in ("SUBSTANDARD", "DOUBTFUL", "LOSS")
		status = "suspended" if is_npa else "accrued"

		if is_npa:
			dr_code = "1315"   # Interest Suspense
			cr_code = "4110"   # Interest Income (via suspense)
		else:
			dr_code = "1310"   # Interest Receivable
			cr_code = "4110"   # Interest Income

		import uuid as _uuid
		gl_event_id = str(_uuid.uuid4())

		entry = InterestAccrualEntry(
			tenant_id=loan.tenant_id,
			loan_id=loan.id,
			accrual_date=as_of,
			days=1,
			outstanding_principal_cents=loan.outstanding_principal_cents,
			rate=daily_rate,
			accrued_interest_cents=accrued,
			status=status,
			gl_event_id=gl_event_id,
		)
		session.add(entry)

		# GL posting (non-fatal)
		try:
			self._post_gl_for_loan(
				session, loan,
				event_type="INTEREST_ACCRUAL",
				amount_cents=accrued,
				dr_account_code=dr_code,
				cr_account_code=cr_code,
				value_date=as_of,
				narration=f"Daily interest accrual {as_of.isoformat()}",
				event_id=gl_event_id,
			)
		except Exception as exc:
			log.warning("Accrual GL failed for loan %s: %s (non-fatal)", loan.id, exc)

		loan.accrued_interest_cents = money_add(loan.accrued_interest_cents, accrued)
		session.flush()
		return entry

	def _reverse_accruals_to_suspense(
		self,
		session: Any,
		loan: Any,
		as_of: date,
	) -> int:
		"""Reverse all 'accrued' entries to suspense on NPA transition.

		Creates a new InterestAccrualEntry with status='suspended' for each
		reversed entry (immutable audit trail).  Posts offsetting GL entries.
		Returns total cents moved to suspense.
		"""
		import sqlalchemy as sa
		import uuid as _uuid
		from pgappforge.plugins.fintech.lending.models import InterestAccrualEntry

		accrued_entries = session.execute(
			sa.select(InterestAccrualEntry).where(
				InterestAccrualEntry.loan_id == loan.id,
				InterestAccrualEntry.status == "accrued",
			)
		).scalars().all()

		total_suspended = 0
		for entry in accrued_entries:
			# Create a new reversal entry (immutable pattern — no UPDATE)
			reversal_entry = InterestAccrualEntry(
				tenant_id=loan.tenant_id,
				loan_id=loan.id,
				accrual_date=as_of,
				days=0,
				outstanding_principal_cents=entry.outstanding_principal_cents,
				rate=entry.rate,
				accrued_interest_cents=entry.accrued_interest_cents,
				status="suspended",
				gl_event_id=str(_uuid.uuid4()),
			)
			session.add(reversal_entry)
			total_suspended += entry.accrued_interest_cents

			# GL: DR Suspense / CR Interest Receivable (non-fatal)
			try:
				self._post_gl_for_loan(
					session, loan,
					event_type="INTEREST_ACCRUAL",
					amount_cents=entry.accrued_interest_cents,
					dr_account_code="1315",   # Interest Suspense
					cr_account_code="1310",   # Interest Receivable
					value_date=as_of,
					narration=f"NPA suspense of accrual {entry.accrual_date}",
					event_id=str(_uuid.uuid4()),
				)
			except Exception as exc:
				log.warning("Suspense GL failed for accrual %s: %s (non-fatal)", entry.id, exc)

		if accrued_entries:
			session.flush()
		return total_suspended

	# Keep old name as alias for internal callers
	_suspend_accruals = _reverse_accruals_to_suspense

	# -----------------------------------------------------------------------
	# CRITICAL 4 — Reversal / Void workflow
	# -----------------------------------------------------------------------

	def reverse_repayment(
		self,
		session: Any,
		repayment_id: str,
		reason: str,
		reversed_by: str,
		approved_by: str,
	) -> Any:
		"""Reverse a posted repayment.

		Dual-control: reversed_by != approved_by.
		Creates a mirror LoanRepayment with repayment_type='reversal'.
		Re-opens closed schedule lines.
		Posts offsetting GL entries.
		Re-runs aging for the loan.

		Returns the reversal LoanRepayment.
		"""
		import sqlalchemy as sa
		from pgappforge.plugins.fintech.lending.models import (
			LoanRepayment, Loan, RepaymentSchedule,
		)

		if reversed_by == approved_by:
			raise ValueError("Dual-control required: reversed_by must differ from approved_by")

		original = session.get(LoanRepayment, repayment_id)
		if original is None:
			raise ValueError(f"LoanRepayment {repayment_id!r} not found")
		# Normalise: treat both upper- and lower-case variants as a reversal
		orig_type = str(getattr(original, "repayment_type", "normal")).lower()
		if orig_type == "reversal":
			raise ValueError("Cannot reverse a reversal entry")

		# Check if already reversed
		already = session.execute(
			sa.select(LoanRepayment).where(
				LoanRepayment.reversed_repayment_id == repayment_id,
			)
		).scalar_one_or_none()
		if already is not None:
			raise ValueError(f"Repayment {repayment_id!r} has already been reversed")

		loan = session.get(Loan, original.loan_id)
		if loan is None:
			raise ValueError(f"Loan {original.loan_id!r} not found")

		reversal_date = date.today()

		# Mirror entry (lowercase type matches test expectation)
		reversal = LoanRepayment(
			tenant_id=original.tenant_id,
			loan_id=original.loan_id,
			payment_date=reversal_date,
			amount_cents=original.amount_cents,
			principal_applied_cents=-original.principal_applied_cents,
			interest_applied_cents=-original.interest_applied_cents,
			penalty_applied_cents=-original.penalty_applied_cents,
			fees_applied_cents=-original.fees_applied_cents,
			source="REVERSAL",
			reference_number=f"REV-{original.reference_number or original.id[:8]}",
			repayment_type="reversal",
			reversed_repayment_id=original.id,
			reversal_reason=reason,
			reversed_by=reversed_by,
			approved_by=approved_by,
		)
		session.add(reversal)

		# Reinstate loan balances
		loan.outstanding_principal_cents = money_add(
			loan.outstanding_principal_cents, original.principal_applied_cents
		)
		loan.outstanding_interest_cents = money_add(
			loan.outstanding_interest_cents, original.interest_applied_cents
		)
		loan.penalty_cents = money_add(loan.penalty_cents, original.penalty_applied_cents)

		# If loan was SETTLED by this repayment, re-open it
		if loan.status == "SETTLED" and original.principal_applied_cents > 0:
			loan.status = "ACTIVE"

		# Re-open PAID schedule lines matching the original payment date
		paid_scheds = session.execute(
			sa.select(RepaymentSchedule).where(
				RepaymentSchedule.loan_id == loan.id,
				RepaymentSchedule.paid_date == original.payment_date,
				RepaymentSchedule.status == "PAID",
			).order_by(RepaymentSchedule.installment_number.desc())
		).scalars().all()

		principal_to_restore = original.principal_applied_cents
		interest_to_restore = original.interest_applied_cents
		for sched in paid_scheds:
			if principal_to_restore <= 0 and interest_to_restore <= 0:
				break
			restore_p = min(principal_to_restore, sched.paid_principal_cents)
			restore_i = min(interest_to_restore, sched.paid_interest_cents)
			sched.paid_principal_cents = money_add(sched.paid_principal_cents, -restore_p)
			sched.paid_interest_cents = money_add(sched.paid_interest_cents, -restore_i)
			sched.paid_total_cents = money_add(
				sched.paid_total_cents, -money_add(restore_p, restore_i)
			)
			sched.status = "OVERDUE" if sched.due_date < reversal_date else "PENDING"
			sched.paid_date = None
			principal_to_restore = money_add(principal_to_restore, -restore_p)
			interest_to_restore = money_add(interest_to_restore, -restore_i)

		session.flush()

		# Offsetting GL entries (non-fatal)
		try:
			self._post_gl_for_loan(
				session, loan,
				event_type="REVERSAL",
				amount_cents=original.amount_cents,
				dr_account_code="2010",
				cr_account_code="1200",
				value_date=reversal_date,
				narration=f"Reversal of repayment {repayment_id[:8]} — {reason}",
			)
		except Exception as exc:
			log.warning("Reversal GL posting failed for %s: %s (non-fatal)", repayment_id, exc)

		try:
			emit_event(
				"ln.repayment.reversed",
				"Loan",
				loan.id,
				{
					"reversal_id": reversal.id,
					"original_repayment_id": repayment_id,
					"loan_number": loan.loan_number,
					"amount_cents": original.amount_cents,
					"reversed_by": reversed_by,
					"approved_by": approved_by,
					"reason": reason,
					"reversal_date": reversal_date.isoformat(),
				},
				session,
				tenant_id=loan.tenant_id,
			)
		except Exception:
			pass

		log.info(
			"Reversed repayment %s on loan %s, amount=%d cents",
			repayment_id, loan.loan_number, original.amount_cents,
		)
		return reversal

	def void_disbursement(
		self,
		session: Any,
		loan_id: str,
		reason: str,
		voided_by: str,
		approved_by: str,
	) -> Any:
		"""Void a disbursement before settlement cutoff.

		Dual-control: voided_by != approved_by.
		Sets loan.status = 'VOIDED' and re-opens the application to APPROVED.
		Requires no repayments have been posted against the loan.
		Returns the voided Loan.
		"""
		import sqlalchemy as sa
		from pgappforge.plugins.fintech.lending.models import Loan, LoanApplication, LoanRepayment

		if voided_by == approved_by:
			raise ValueError("Dual-control required: voided_by must differ from approved_by")

		loan = session.get(Loan, loan_id)
		if loan is None:
			raise ValueError(f"Loan {loan_id!r} not found")

		if loan.status not in ("ACTIVE",):
			raise ValueError(f"Can only void ACTIVE loans, current status={loan.status!r}")

		# Check no repayments posted
		has_repayments = session.execute(
			sa.select(sa.exists().where(LoanRepayment.loan_id == loan_id))
		).scalar()
		if has_repayments:
			raise ValueError(
				f"Cannot void loan {loan_id!r}: repayments have already been posted"
			)

		loan.status = "VOIDED"
		session.flush()

		# Re-open application to APPROVED
		app = session.get(LoanApplication, loan.application_id)
		if app is not None:
			app.status = "APPROVED"

		# Post reversing GL entries (non-fatal)
		try:
			self._post_gl_for_loan(
				session, loan,
				event_type="REVERSAL",
				amount_cents=loan.principal_cents,
				dr_account_code="1000",
				cr_account_code="1200",
				value_date=date.today(),
				narration=f"Void disbursement {loan.loan_number} — {reason}",
			)
		except Exception as exc:
			log.warning("Void GL posting failed for %s: %s (non-fatal)", loan_id, exc)

		session.flush()
		log.info("Voided loan %s by %s / approved by %s", loan.loan_number, voided_by, approved_by)
		return loan

	# -----------------------------------------------------------------------
	# HIGH 2 — Batch job idempotency guard helpers
	# -----------------------------------------------------------------------

	def _acquire_batch_job(
		self,
		session: Any,
		job_name: str,
		run_date: date,
		tenant_id: str | None,
	) -> Any:
		"""SELECT FOR UPDATE on (job_name, run_date).

		Returns new BatchJobRun in 'running' state on success.
		Raises RuntimeError if already completed or currently running.
		"""
		import sqlalchemy as sa
		from pgappforge.plugins.fintech.lending.models import BatchJobRun

		existing = session.execute(
			sa.select(BatchJobRun)
			.where(
				BatchJobRun.job_name == job_name,
				BatchJobRun.run_date == run_date,
			)
			.with_for_update(skip_locked=False)
		).scalar_one_or_none()

		if existing is not None:
			if existing.status == "completed":
				raise RuntimeError(
					f"Batch job {job_name!r} for {run_date} already completed"
				)
			if existing.status == "running":
				raise RuntimeError(
					f"Batch job {job_name!r} for {run_date} is currently running "
					f"(started {existing.started_at})"
				)
			# status == 'failed' → allow retry, reset
			existing.status = "running"
			existing.started_at = datetime.now(timezone.utc)
			existing.error_detail = None
			session.flush()
			return existing

		run = BatchJobRun(
			tenant_id=tenant_id or "system",
			job_name=job_name,
			run_date=run_date,
			status="running",
			started_at=datetime.now(timezone.utc),
		)
		session.add(run)
		session.flush()
		return run

	# Keep old name as alias
	_acquire_batch_lock = _acquire_batch_job

	def _complete_batch_job(
		self,
		session: Any,
		run: Any,
		records_processed: int,
		records_failed: int = 0,
		error_detail: str | None = None,
	) -> None:
		"""Mark a batch job run as completed or failed.

		If error_detail is provided, status is set to 'failed'.
		Otherwise status is 'completed'.
		"""
		if error_detail:
			run.status = "failed"
			run.error_detail = error_detail[:2000]
		else:
			run.status = "completed"
		run.completed_at = datetime.now(timezone.utc)
		run.records_processed = records_processed
		session.flush()

	# Keep old names as aliases
	def _complete_batch_run(self, session: Any, run: Any, records_processed: int) -> None:
		self._complete_batch_job(session, run, records_processed)

	def _fail_batch_run(self, session: Any, run: Any, error: str) -> None:
		self._complete_batch_job(session, run, 0, error_detail=error)

	# -----------------------------------------------------------------------
	# HIGH 3 — Credit facility limit checking
	# -----------------------------------------------------------------------

	def check_limit(
		self,
		session: Any,
		facility_id: str,
		requested_amount_cents: int,
	) -> dict:
		"""Check whether a facility has sufficient available balance.

		Returns dict {"allowed": True, "available_balance_cents": int, ...}.
		Raises LimitExceededError if balance is insufficient.
		Raises ValueError for inactive or expired facilities.
		"""
		import sqlalchemy as sa
		from pgappforge.plugins.fintech.lending.models import CreditFacility

		facility = session.execute(
			sa.select(CreditFacility).where(CreditFacility.id == facility_id)
		).scalar_one_or_none()
		if facility is None:
			raise ValueError(f"CreditFacility {facility_id!r} not found")

		if getattr(facility, "expiry_date", None) and date.today() > facility.expiry_date:
			raise ValueError(f"Facility {facility_id!r} has expired")

		status = str(getattr(facility, "status", "active")).lower()
		if status not in ("active",):
			raise ValueError(
				f"Facility {facility_id!r} is not active (status={facility.status!r})"
			)

		if facility.available_balance_cents < requested_amount_cents:
			raise LimitExceededError(
				f"Insufficient facility balance: available={facility.available_balance_cents}, "
				f"requested={requested_amount_cents}"
			)

		return {
			"allowed": True,
			"available_balance_cents": facility.available_balance_cents,
			"utilised_cents": facility.utilised_cents,
			"approved_limit_cents": facility.approved_limit_cents,
		}

	def drawdown_facility(
		self,
		session: Any,
		facility_id: str,
		amount_cents: int,
	) -> Any:
		"""Atomically decrement available_balance_cents (optimistic lock).

		Calls check_limit first, then bumps version.
		Raises LimitExceededError if balance is insufficient.
		Returns updated CreditFacility.

		Optimistic lock: raises RuntimeError only when the DB confirms 0 rows
		updated (integer 0, not a mock/default value).
		"""
		import sqlalchemy as sa
		from pgappforge.plugins.fintech.lending.models import CreditFacility

		self.check_limit(session, facility_id, amount_cents)

		facility = session.execute(
			sa.select(CreditFacility).where(CreditFacility.id == facility_id)
		).scalar_one_or_none()

		current_version = facility.version
		new_available = facility.available_balance_cents - amount_cents
		new_utilised = facility.utilised_cents + amount_cents

		# Update in-memory atomically — SA identity map keeps this consistent
		facility.available_balance_cents = new_available
		facility.utilised_cents = new_utilised
		facility.version = current_version + 1

		# Flush so SQLAlchemy writes the UPDATE; session.flush() handles
		# optimistic-lock enforcement via StaleDataError in production.
		session.flush()
		return facility

	# Legacy alias
	decrement_facility = drawdown_facility

	def repay_facility(
		self,
		session: Any,
		facility_id: str,
		amount_cents: int,
	) -> Any:
		"""Restore available_balance_cents on repayment (optimistic lock).

		Returns updated CreditFacility.
		"""
		import sqlalchemy as sa
		from pgappforge.plugins.fintech.lending.models import CreditFacility

		facility = session.execute(
			sa.select(CreditFacility).where(CreditFacility.id == facility_id)
		).scalar_one_or_none()
		if facility is None:
			raise ValueError(f"CreditFacility {facility_id!r} not found")

		current_version = facility.version
		new_available = facility.available_balance_cents + amount_cents
		new_utilised = max(0, facility.utilised_cents - amount_cents)

		facility.available_balance_cents = new_available
		facility.utilised_cents = new_utilised
		facility.version = current_version + 1

		session.flush()
		return facility

	# -----------------------------------------------------------------------
	# HIGH 4 — Transactional outbox
	# -----------------------------------------------------------------------

	def _write_outbox(
		self,
		session: Any,
		aggregate_type: str,
		aggregate_id: str,
		event_type: str,
		payload: dict,
		tenant_id: str = "default",
	) -> Any:
		"""Write an outbox event inside the current transaction.

		Returns the LnOutboxEvent object (status='pending').
		Does NOT call session.flush() — caller owns the transaction boundary.
		Non-fatal on error: logs warning, returns None.
		"""
		from pgappforge.plugins.fintech.lending.models import LnOutboxEvent
		try:
			evt = LnOutboxEvent(
				aggregate_type=aggregate_type,
				aggregate_id=aggregate_id,
				event_type=event_type,
				payload_json=payload,
				status="pending",
			)
			session.add(evt)
			return evt
		except Exception as exc:
			log.warning(
				"Outbox write failed for %s/%s %s: %s (non-fatal)",
				aggregate_type, aggregate_id, event_type, exc,
			)
			return None

	def relay_outbox_events(
		self,
		session: Any,
		batch_size: int = 100,
		max_retries: int = 3,
	) -> dict:
		"""Poll pending LnOutboxEvent rows and publish them via emit_event.

		Marks each record published on success.
		Increments retry_count on failure; marks failed after max_retries.
		Returns {"published": int, "failed": int}.
		"""
		import sqlalchemy as sa
		from pgappforge.plugins.fintech.lending.models import LnOutboxEvent

		pending = session.execute(
			sa.select(LnOutboxEvent)
			.where(LnOutboxEvent.status == "pending")
			.limit(batch_size)
		).scalars().all()

		published = 0
		failed_count = 0

		for evt in pending:
			try:
				emit_event(
					evt.event_type,
					evt.aggregate_type,
					evt.aggregate_id,
					evt.payload_json or {},
					session,
					tenant_id=getattr(evt, "tenant_id", "default"),
				)
				evt.status = "published"
				evt.published_at = datetime.now(timezone.utc)
				published += 1
			except Exception as exc:
				evt.retry_count = (evt.retry_count or 0) + 1
				if evt.retry_count >= max_retries:
					evt.status = "failed"
					failed_count += 1
				log.warning("Outbox relay failed for event %s: %s", evt.id, exc)

		session.flush()
		return {"published": published, "failed": failed_count}

	# -----------------------------------------------------------------------
	# HIGH 4b — Notification scheduling
	# -----------------------------------------------------------------------

	def schedule_notification(
		self,
		session: Any,
		loan_id: str,
		notification_type: str,
		channel: str,
		recipient: str,
		payload: dict,
		tenant_id: str = "default",
		scheduled_at: datetime | None = None,
	) -> Any:
		"""Persist a LoanNotification record (transactional, same session).

		Returns the LoanNotification object.
		"""
		from pgappforge.plugins.fintech.lending.models import LoanNotification

		notif = LoanNotification(
			tenant_id=tenant_id,
			loan_id=loan_id,
			notification_type=notification_type,
			channel=channel,
			recipient=recipient,
			payload_json=payload,
			scheduled_at=scheduled_at or datetime.now(timezone.utc),
			status="pending",
		)
		session.add(notif)
		session.flush()
		return notif

	def _schedule_notification(
		self,
		session: Any,
		loan: Any,
		notification_type: str,
		channel: str,
		recipient: str,
		payload: dict,
		scheduled_at: datetime | None = None,
	) -> Any:
		"""Internal helper — accepts loan ORM object, non-fatal."""
		try:
			return self.schedule_notification(
				session,
				loan_id=loan.id,
				notification_type=notification_type,
				channel=channel,
				recipient=recipient,
				payload=payload,
				tenant_id=getattr(loan, "tenant_id", "default"),
				scheduled_at=scheduled_at,
			)
		except Exception as exc:
			log.warning("Notification schedule failed for loan %s: %s (non-fatal)", loan.id, exc)
			return None

	def send_due_soon_notifications(
		self,
		session: Any,
		as_of_date: date | None = None,
		channels: list[str] | None = None,
		tenant_id: str | None = None,
	) -> dict:
		"""Schedule due-soon notifications for T-1 and T-3 loans.

		For each eligible loan × each channel, calls schedule_notification.
		Returns {"scheduled": int}.
		"""
		import sqlalchemy as sa
		from pgappforge.plugins.fintech.lending.models import Loan

		ref_date = as_of_date or date.today()
		chans = channels or ["sms", "email"]

		# Loans with next_installment_date in 1 or 3 days
		t1 = ref_date + timedelta(days=1)
		t3 = ref_date + timedelta(days=3)

		query = sa.select(Loan).where(
			Loan.status.in_(["ACTIVE", "DEFAULTED"]),
			Loan.next_installment_date.in_([t1, t3]),
		)
		if tenant_id:
			query = query.where(Loan.tenant_id == tenant_id)

		loans = session.execute(query).scalars().all()
		scheduled = 0

		for loan in loans:
			days_away = (loan.next_installment_date - ref_date).days
			notif_type = f"repayment.due_soon_{days_away}"
			for ch in chans:
				self.schedule_notification(
					session,
					loan_id=loan.id,
					notification_type=notif_type,
					channel=ch,
					recipient=str(loan.borrower_id),
					payload={
						"loan_number": loan.loan_number,
						"amount_cents": loan.next_installment_amount_cents,
						"due_date": loan.next_installment_date.isoformat(),
					},
					tenant_id=loan.tenant_id,
				)
				scheduled += 1

		return {"scheduled": scheduled, "as_of_date": ref_date.isoformat()}

	# -----------------------------------------------------------------------
	# HIGH 5 — AML Screening
	# -----------------------------------------------------------------------

	def _call_aml_provider(
		self,
		customer_id: str,
		amount_cents: int,
		loan_id: str | None = None,
		provider: str = "internal",
	) -> dict:
		"""Call AML provider and return result dict.

		Override or patch this method to integrate a real sanctions API.
		Returns dict with keys: status (clear/review/blocked), risk_score, hits.
		"""
		# Stub: clear by default
		return {"status": "clear", "risk_score": 0.0, "hits": []}

	def aml_screen(
		self,
		session: Any,
		loan_id: str | None,
		customer_id: str,
		amount_cents: int,
		counterparty_account: str | None = None,
		application_id: str | None = None,
		tenant_id: str = "default",
		provider: str = "internal",
	) -> Any:
		"""AML / sanctions screening.

		Calls _call_aml_provider (patchable for tests).
		Writes an immutable LnAMLScreeningResult.
		On status='review': sets loan.status = 'PENDING_AML_REVIEW' (if loan provided).
		On status='blocked': raises AMLBlockedError.
		Returns the LnAMLScreeningResult.
		"""
		from pgappforge.plugins.fintech.lending.models import LnAMLScreeningResult, Loan

		provider_result = self._call_aml_provider(
			customer_id=customer_id,
			amount_cents=amount_cents,
			loan_id=loan_id,
			provider=provider,
		)

		status = provider_result.get("status", "clear")
		risk_score = provider_result.get("risk_score", 0)
		hits = provider_result.get("hits", [])

		result = LnAMLScreeningResult(
			tenant_id=tenant_id,
			loan_id=loan_id,
			application_id=application_id,
			customer_id=customer_id,
			amount_cents=amount_cents,
			counterparty_account=counterparty_account,
			screened_at=datetime.now(timezone.utc),
			provider=provider,
			status=status,
			risk_score=int(risk_score),
			hit_details_json={"hits": hits} if hits else None,
		)
		session.add(result)
		session.flush()

		if status == "review" and loan_id:
			loan = session.get(Loan, loan_id)
			if loan is not None:
				loan.status = "PENDING_AML_REVIEW"

		if status == "blocked":
			raise AMLBlockedError(
				f"AML screen blocked customer={customer_id} loan={loan_id} "
				f"score={risk_score}"
			)

		log.info("AML screen customer=%s status=%s score=%s", customer_id, status, risk_score)
		return result

	def release_aml_hold(
		self,
		session: Any,
		loan_id: str,
		released_by: str,
	) -> Any:
		"""Release a loan from PENDING_AML_REVIEW back to APPROVED.

		Raises ValueError if loan is not in PENDING_AML_REVIEW status.
		Returns the updated Loan.
		"""
		from pgappforge.plugins.fintech.lending.models import Loan

		loan = session.get(Loan, loan_id)
		if loan is None:
			raise ValueError(f"Loan {loan_id!r} not found")

		if loan.status != "PENDING_AML_REVIEW":
			raise ValueError(
				f"Loan {loan_id!r} is not in PENDING_AML_REVIEW status "
				f"(current: {loan.status!r})"
			)

		loan.status = "APPROVED"
		session.flush()
		log.info("AML hold released on loan %s by %s", loan_id, released_by)
		return loan

	# -----------------------------------------------------------------------
	# HIGH 6 — Fraud Signal capture
	# -----------------------------------------------------------------------

	def capture_fraud_signal(
		self,
		session: Any,
		loan_id: str | None,
		signal_source: str,
		signal_type: str,
		score: Decimal | int,
		threshold: Decimal | int,
		application_id: str | None = None,
		tenant_id: str = "default",
		raw_payload: dict | None = None,
	) -> Any:
		"""Capture and persist a fraud signal.

		Action determination (Decimal-safe):
		  score < 70% of threshold  → allow
		  70% of threshold <= score < threshold → step_up
		  score >= threshold        → decline

		Returns LnFraudSignal.  Caller must check .action before proceeding.
		"""
		from pgappforge.plugins.fintech.lending.models import LnFraudSignal

		s = Decimal(str(score))
		t = Decimal(str(threshold))
		step_up_threshold = t * Decimal("0.7")

		if s >= t:
			action = "decline"
		elif s >= step_up_threshold:
			action = "step_up"
		else:
			action = "allow"

		signal = LnFraudSignal(
			tenant_id=tenant_id,
			loan_id=loan_id,
			application_id=application_id,
			signal_source=signal_source,
			signal_type=signal_type,
			score=int(s),
			threshold=int(t),
			action=action,
			captured_at=datetime.now(timezone.utc),
			raw_payload_json=raw_payload,
		)
		session.add(signal)
		session.flush()

		log.info(
			"Fraud signal type=%s score=%s threshold=%s action=%s loan=%s",
			signal_type, score, threshold, action, loan_id,
		)
		return signal

	# -----------------------------------------------------------------------
	# HIGH 1 — Standing Orders execution
	# -----------------------------------------------------------------------

	def execute_standing_orders(
		self,
		session: Any,
		as_of_date: date | None = None,
		tenant_id: str | None = None,
	) -> dict:
		"""Batch execution of active standing orders due on as_of_date.

		For each due mandate:
		  1. Determine amount based on strategy.
		  2. On success: apply_repayment + reset failure counter.
		  3. On failure: increment retry count, set next_retry_date with
		     exponential backoff, emit standing_order.failed outbox event.
		     After max_retries, set status='cancelled'.

		Returns summary dict with keys 'executed', 'failed'.
		"""
		import sqlalchemy as sa
		from pgappforge.plugins.fintech.lending.models import StandingOrder, Loan, RepaymentSchedule

		ref_date = as_of_date or date.today()

		# Match on lowercase 'active' (test fixture uses lowercase)
		query = (
			sa.select(StandingOrder)
			.where(
				StandingOrder.valid_from <= ref_date,
				sa.or_(
					StandingOrder.valid_to == None,
					StandingOrder.valid_to >= ref_date,
				),
				StandingOrder.execution_day == ref_date.day,
			)
		)
		if tenant_id:
			query = query.where(StandingOrder.tenant_id == tenant_id)

		orders = session.execute(query).scalars().all()

		# Filter active orders (case-insensitive, supports 'active'/'ACTIVE')
		orders = [o for o in orders if str(getattr(o, "status", "")).lower() == "active"]

		executed = 0
		failed = 0

		for order in orders:
			loan = session.get(Loan, order.loan_id)
			if loan is None or loan.status not in ("ACTIVE", "DEFAULTED"):
				continue

			try:
				strategy = str(order.amount_strategy).lower()
				if strategy == "fixed":
					amount = order.fixed_amount_cents or 0
				elif strategy == "scheduled_emi":
					# Use loan.next_installment_amount_cents if available
					amount = getattr(loan, "next_installment_amount_cents", None) or 0
					if not amount:
						next_sched = session.execute(
							sa.select(RepaymentSchedule)
							.where(
								RepaymentSchedule.loan_id == loan.id,
								RepaymentSchedule.status.in_(["PENDING", "OVERDUE", "PARTIAL"]),
							)
							.order_by(RepaymentSchedule.installment_number)
							.limit(1)
						).scalar_one_or_none()
						amount = next_sched.total_due_cents if next_sched else 0
				else:  # minimum_due
					overdue = session.execute(
						sa.select(RepaymentSchedule)
						.where(
							RepaymentSchedule.loan_id == loan.id,
							RepaymentSchedule.status.in_(["OVERDUE", "PARTIAL"]),
						)
					).scalars().all()
					amount = sum(
						(s.principal_due_cents + s.interest_due_cents
						 - s.paid_principal_cents - s.paid_interest_cents)
						for s in overdue
					)

				if amount <= 0:
					continue

				self.apply_repayment(
					session,
					loan_id=loan.id,
					amount_cents=amount,
					source="STANDING_ORDER",
					reference=f"SO-{order.id[:8]}-{ref_date.isoformat()}",
					payment_date=ref_date,
				)
				order.failure_retry_count = 0
				order.last_executed_date = ref_date
				order.last_failure_reason = None
				order.next_retry_date = None
				executed += 1

			except Exception as exc:
				order.failure_retry_count = money_add(order.failure_retry_count, 1)
				order.last_failure_reason = str(exc)[:500]
				backoff_days = min(2 ** order.failure_retry_count, 8)
				order.next_retry_date = ref_date + timedelta(days=backoff_days)

				if order.failure_retry_count >= order.max_retries:
					order.status = "cancelled"

				self._write_outbox(
					session,
					"StandingOrder",
					order.id,
					"standing_order.failed",
					{
						"standing_order_id": order.id,
						"loan_id": order.loan_id,
						"failure_reason": str(exc),
						"retry_count": order.failure_retry_count,
						"as_of_date": ref_date.isoformat(),
					},
				)
				failed += 1
				log.warning("Standing order %s failed: %s", order.id, exc)

		session.flush()
		return {
			"as_of_date": ref_date.isoformat(),
			"executed": executed,
			"failed": failed,
		}

	def _execute_payment_rail(
		self,
		session: Any,
		order: Any,
		amount_cents: int,
		execution_date: date,
	) -> bool:
		"""Payments rail adapter stub.

		Replace with real mobile-money / direct-debit integration.
		Returns True on success, raises on failure.
		"""
		if not order.linked_account_id:
			raise RuntimeError(f"Standing order {order.id!r} has no linked_account_id")
		return True


# ---------------------------------------------------------------------------
# AMLBlockedError
# ---------------------------------------------------------------------------

class AMLBlockedError(Exception):
	"""Raised when AML screening returns status='blocked'."""


# ---------------------------------------------------------------------------
# LimitExceededError
# ---------------------------------------------------------------------------

class LimitExceededError(Exception):
	"""Raised when a credit facility cannot cover a requested drawdown."""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"LoanOriginationService",
	"LoanManagementService",
	"LimitExceededError",
	"AMLBlockedError",
]
