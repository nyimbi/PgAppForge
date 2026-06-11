"""
pgappforge/plugins/fintech/bnpl/services.py

BNPLService — Buy-Now-Pay-Later operations.

All methods accept an explicit SQLAlchemy session.  Event emission is
wrapped in try/except so a broken event bus never aborts business logic.

Affordability assessment:
  - Tries lending plugin CRB check first.
  - Falls back to simple heuristic: amount < 5_000_000c → score=750 else 600.

Instalment generation by plan_type:
  PAY_IN_3      — 3 equal monthly instalments (day-of-month preserved)
  PAY_IN_4      — 4 equal biweekly instalments (every 14 days)
  MONTHLY       — uses BNPL_MONTHLY_INSTALLMENTS config key (default 6)
  INVOICE_SPLIT — 2 payments: 50% now, 50% in 30 days
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, date, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

import sqlalchemy as sa
from sqlalchemy import select, func

from pgappforge.plugins.erp.foundation.commons import emit_event
from pgappforge.plugins.fintech.bnpl.models import (
	BNPLApplication,
	BNPLInstallment,
	BNPLMerchant,
	BNPLMerchantSettlement,
	BNPLPlan,
)
from pgappforge.plugins.fintech.bnpl.events import (
	BNPLApprovedEvent,
	BNPLDeclinedEvent,
	InstallmentOverdueEvent,
	InstallmentPaidEvent,
	MerchantSettledEvent,
)

log = logging.getLogger(__name__)

# Minimum credit score to auto-approve
_APPROVAL_THRESHOLD = 650

# Default late payment penalty: 2% of instalment amount per day overdue
_DEFAULT_PENALTY_PCT = Decimal("0.02")


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------

class BNPLError(Exception):
	"""Base exception for BNPL service errors."""


class MerchantNotFoundError(BNPLError):
	"""No merchant found for the given ID."""


class ApplicationNotFoundError(BNPLError):
	"""No application found for the given ID."""


class InstallmentNotFoundError(BNPLError):
	"""No instalment found for the given ID."""


class InvalidApplicationStatusError(BNPLError):
	"""Operation not allowed in the current application status."""


class SettlementAlreadyExistsError(BNPLError):
	"""Settlement for this merchant/period already exists."""


# ---------------------------------------------------------------------------
# BNPLService
# ---------------------------------------------------------------------------

class BNPLService:
	"""Buy-Now-Pay-Later operations.

	Instantiate without arguments; pass session explicitly to every method.
	"""

	def __init__(self, config: dict[str, Any] | None = None) -> None:
		self._config: dict[str, Any] = config or {}
		try:
			from flask import current_app
			self._config = {**current_app.config, **self._config}
		except RuntimeError:
			pass

	# ------------------------------------------------------------------ #
	# Application lifecycle                                                #
	# ------------------------------------------------------------------ #

	def apply(
		self,
		customer_id: str,
		merchant_id: str,
		order_amount_cents: int,
		plan_type: str,
		tenant_id: str,
		session: Any,
	) -> BNPLApplication:
		"""Create a BNPL application and run affordability assessment.

		Persists the application with credit_score, affordability_score set.
		Status remains PENDING — caller must invoke approve() or decline().

		Raises MerchantNotFoundError if merchant does not exist or is inactive.
		"""
		merchant: BNPLMerchant | None = session.execute(
			select(BNPLMerchant).where(
				BNPLMerchant.id == merchant_id,
				BNPLMerchant.tenant_id == tenant_id,
				BNPLMerchant.is_active.is_(True),
			)
		).scalar_one_or_none()

		if merchant is None:
			raise MerchantNotFoundError(
				f"Merchant {merchant_id!r} not found or inactive for tenant {tenant_id!r}"
			)

		credit_score, affordability_score = self._assess_affordability(
			customer_id, order_amount_cents, session
		)

		application = BNPLApplication(
			tenant_id=tenant_id,
			customer_id=customer_id,
			merchant_id=merchant_id,
			order_amount_cents=order_amount_cents,
			plan_type=plan_type,
			status="PENDING",
			credit_score=credit_score,
			affordability_score=affordability_score,
		)
		session.add(application)
		session.flush()

		log.info(
			"BNPLService.apply: application %s created (credit=%d affordability=%d)",
			application.id, credit_score, affordability_score,
		)
		return application

	def _assess_affordability(
		self,
		customer_id: str,
		amount_cents: int,
		session: Any,
	) -> tuple[int, int]:
		"""Return (credit_score, affordability_score).

		Tries the lending plugin CRB check first; falls back to a simple
		amount-based heuristic.
		"""
		try:
			from pgappforge.plugins.fintech.lending.services import CRBService
			crb = CRBService()
			result = crb.check_customer(customer_id=customer_id, session=session)
			return int(result.get("credit_score", 700)), int(result.get("affordability_score", 700))
		except ImportError:
			log.debug("_assess_affordability: lending plugin not installed, using heuristic")
		except Exception as exc:
			log.warning("_assess_affordability: CRB check failed (using heuristic): %s", exc)

		# Simple fallback heuristic: KES 500,000 threshold (5_000_000c)
		if amount_cents < 5_000_000:
			return 750, 750
		return 600, 600

	def approve(
		self,
		application_id: str,
		approved_limit_cents: int,
		tenant_id: str,
		session: Any,
	) -> BNPLPlan:
		"""Approve a PENDING application and generate the instalment plan.

		Creates BNPLPlan + BNPLInstallment rows.
		Advances application.status to APPROVED (then ACTIVE immediately).
		Emits BNPLApprovedEvent.

		Raises ApplicationNotFoundError, InvalidApplicationStatusError.
		"""
		application = self._get_application(application_id, tenant_id, session)
		if application.status != "PENDING":
			raise InvalidApplicationStatusError(
				f"Application {application_id!r} is {application.status!r}, expected PENDING"
			)

		application.status = "APPROVED"
		application.approved_limit_cents = approved_limit_cents
		session.flush()

		plan = self._create_plan(application, approved_limit_cents, session)

		application.status = "ACTIVE"
		session.flush()

		try:
			emit_event(
				BNPLApprovedEvent(
					aggregate_id=application.id,
					aggregate_type="BNPLApplication",
					tenant_id=tenant_id,
					application_id=application.id,
					customer_id=str(application.customer_id),
					merchant_id=str(application.merchant_id),
					plan_id=plan.id,
					approved_limit_cents=approved_limit_cents,
					plan_type=application.plan_type,
					installment_count=plan.installment_count,
				),
				session,
			)
		except Exception as exc:
			log.warning("approve: event emission failed (non-fatal): %s", exc)

		log.info(
			"BNPLService.approve: application %s → plan %s (%d instalments)",
			application.id, plan.id, plan.installment_count,
		)
		return plan

	def _create_plan(
		self,
		application: BNPLApplication,
		approved_limit_cents: int,
		session: Any,
	) -> BNPLPlan:
		"""Build a BNPLPlan and its BNPLInstallment rows based on plan_type."""
		plan_type = application.plan_type
		today = date.today()
		total = approved_limit_cents

		# Determine instalment count and due dates
		if plan_type == "PAY_IN_3":
			count = 3
			due_dates = [
				self._add_months(today, i + 1) for i in range(count)
			]
		elif plan_type == "PAY_IN_4":
			count = 4
			due_dates = [today + timedelta(days=14 * (i + 1)) for i in range(count)]
		elif plan_type == "MONTHLY":
			count = int(self._config.get("BNPL_MONTHLY_INSTALLMENTS", 6))
			due_dates = [
				self._add_months(today, i + 1) for i in range(count)
			]
		elif plan_type == "INVOICE_SPLIT":
			count = 2
			due_dates = [today, today + timedelta(days=30)]
		else:
			# Unknown plan_type — default to 3 monthly
			log.warning("_create_plan: unknown plan_type %r, defaulting to PAY_IN_3", plan_type)
			count = 3
			due_dates = [self._add_months(today, i + 1) for i in range(count)]

		# Integer division — last instalment absorbs rounding remainder
		base_amount = total // count
		remainder = total - base_amount * count

		plan = BNPLPlan(
			tenant_id=application.tenant_id,
			application_id=application.id,
			total_cents=total,
			installment_count=count,
			installment_amount_cents=base_amount,
			interest_rate_pct=Decimal("0"),
			status="ACTIVE",
			first_payment_date=due_dates[0],
		)
		session.add(plan)
		session.flush()

		for i, due_date in enumerate(due_dates):
			amt = base_amount + (remainder if i == count - 1 else 0)
			installment = BNPLInstallment(
				tenant_id=application.tenant_id,
				plan_id=plan.id,
				installment_number=i + 1,
				due_date=due_date,
				amount_cents=amt,
				status="PENDING",
				penalty_cents=0,
			)
			session.add(installment)

		session.flush()
		return plan

	@staticmethod
	def _add_months(d: date, months: int) -> date:
		"""Add *months* months to a date (clamped to month end)."""
		month = d.month - 1 + months
		year = d.year + month // 12
		month = month % 12 + 1
		import calendar
		day = min(d.day, calendar.monthrange(year, month)[1])
		return date(year, month, day)

	def decline(
		self,
		application_id: str,
		reason: str,
		tenant_id: str,
		session: Any,
	) -> BNPLApplication:
		"""Decline a PENDING application.

		Emits BNPLDeclinedEvent.
		Raises ApplicationNotFoundError, InvalidApplicationStatusError.
		"""
		application = self._get_application(application_id, tenant_id, session)
		if application.status != "PENDING":
			raise InvalidApplicationStatusError(
				f"Application {application_id!r} is {application.status!r}, expected PENDING"
			)

		application.status = "DECLINED"
		session.flush()

		try:
			emit_event(
				BNPLDeclinedEvent(
					aggregate_id=application.id,
					aggregate_type="BNPLApplication",
					tenant_id=tenant_id,
					application_id=application.id,
					customer_id=str(application.customer_id),
					merchant_id=str(application.merchant_id),
					reason=reason,
					credit_score=application.credit_score or 0,
					affordability_score=application.affordability_score or 0,
				),
				session,
			)
		except Exception as exc:
			log.warning("decline: event emission failed (non-fatal): %s", exc)

		log.info("BNPLService.decline: application %s DECLINED (%s)", application.id, reason)
		return application

	# ------------------------------------------------------------------ #
	# Instalment operations                                                #
	# ------------------------------------------------------------------ #

	def process_installment(
		self,
		installment_id: str,
		paid_amount_cents: int,
		tenant_id: str,
		session: Any,
	) -> BNPLInstallment:
		"""Mark an instalment PAID and post the entry to GL.

		Emits InstallmentPaidEvent.
		Raises InstallmentNotFoundError.
		"""
		installment: BNPLInstallment | None = session.execute(
			select(BNPLInstallment).where(
				BNPLInstallment.id == installment_id,
				BNPLInstallment.tenant_id == tenant_id,
			)
		).scalar_one_or_none()

		if installment is None:
			raise InstallmentNotFoundError(
				f"Instalment {installment_id!r} not found for tenant {tenant_id!r}"
			)

		today = date.today()
		installment.status = "PAID"
		installment.paid_date = today
		installment.paid_amount_cents = paid_amount_cents
		session.flush()

		# Post to GL — non-fatal
		self._post_installment_to_gl(installment, tenant_id, session)

		# Check if plan is fully completed
		self._check_plan_completion(installment.plan_id, tenant_id, session)

		try:
			# Resolve customer_id through the plan → application relationship
			plan = session.get(BNPLPlan, installment.plan_id)
			application = session.get(BNPLApplication, plan.application_id) if plan else None
			customer_id = str(application.customer_id) if application else ""

			emit_event(
				InstallmentPaidEvent(
					aggregate_id=installment.id,
					aggregate_type="BNPLInstallment",
					tenant_id=tenant_id,
					installment_id=installment.id,
					plan_id=installment.plan_id,
					customer_id=customer_id,
					installment_number=installment.installment_number,
					paid_amount_cents=paid_amount_cents,
					paid_date=today.isoformat(),
				),
				session,
			)
		except Exception as exc:
			log.warning("process_installment: event emission failed (non-fatal): %s", exc)

		log.info(
			"BNPLService.process_installment: instalment %s PAID amount=%dc",
			installment.id, paid_amount_cents,
		)
		return installment

	def _post_installment_to_gl(
		self,
		installment: BNPLInstallment,
		tenant_id: str,
		session: Any,
	) -> None:
		"""Post instalment receipt to GL — non-fatal on any error."""
		try:
			from pgappforge.plugins.erp.finance.gl.services import GLService
			svc = GLService()
			svc.post_simple_journal(
				lines=[
					{"account": "BNPL_RECEIVABLE", "debit_cents": 0, "credit_cents": installment.paid_amount_cents},
					{"account": "BNPL_CASH", "debit_cents": installment.paid_amount_cents, "credit_cents": 0},
				],
				session=session,
				tenant_id=tenant_id,
				description=f"BNPL instalment payment #{installment.installment_number}",
				source_doc_id=installment.id,
				source_doc_type="BNPL_INSTALLMENT",
			)
		except ImportError:
			log.debug("_post_installment_to_gl: GL plugin not installed, skipping")
		except Exception as exc:
			log.warning("_post_installment_to_gl: GL post failed (non-fatal): %s", exc)

	def _check_plan_completion(
		self,
		plan_id: str,
		tenant_id: str,
		session: Any,
	) -> None:
		"""Mark plan COMPLETED if all instalments are PAID or WAIVED."""
		plan: BNPLPlan | None = session.get(BNPLPlan, plan_id)
		if plan is None or plan.status != "ACTIVE":
			return

		pending_count = session.execute(
			select(func.count(BNPLInstallment.id)).where(
				BNPLInstallment.plan_id == plan_id,
				BNPLInstallment.status.in_(["PENDING", "OVERDUE"]),
			)
		).scalar_one()

		if pending_count == 0:
			plan.status = "COMPLETED"
			# Advance application status too
			application = session.get(BNPLApplication, plan.application_id)
			if application and application.status == "ACTIVE":
				application.status = "COMPLETED"
			session.flush()
			log.info("BNPLService._check_plan_completion: plan %s marked COMPLETED", plan_id)

	def run_overdue_check(self, tenant_id: str, session: Any) -> int:
		"""Batch job: mark OVERDUE all PENDING instalments past their due_date.

		Applies a flat penalty of 2% of the instalment amount per day overdue.
		Returns the count of instalments newly marked OVERDUE.
		"""
		today = date.today()
		overdue: list[BNPLInstallment] = session.execute(
			select(BNPLInstallment).where(
				BNPLInstallment.tenant_id == tenant_id,
				BNPLInstallment.status == "PENDING",
				BNPLInstallment.due_date < today,
			)
		).scalars().all()

		count = 0
		for inst in overdue:
			days_late = (today - inst.due_date).days
			penalty = int(
				(Decimal(inst.amount_cents) * _DEFAULT_PENALTY_PCT * days_late).to_integral_value(ROUND_HALF_UP)
			)
			inst.status = "OVERDUE"
			inst.penalty_cents = penalty
			session.flush()

			try:
				plan = session.get(BNPLPlan, inst.plan_id)
				application = session.get(BNPLApplication, plan.application_id) if plan else None
				customer_id = str(application.customer_id) if application else ""

				emit_event(
					InstallmentOverdueEvent(
						aggregate_id=inst.id,
						aggregate_type="BNPLInstallment",
						tenant_id=tenant_id,
						installment_id=inst.id,
						plan_id=inst.plan_id,
						customer_id=customer_id,
						installment_number=inst.installment_number,
						due_date=inst.due_date.isoformat(),
						amount_cents=inst.amount_cents,
						penalty_cents=penalty,
					),
					session,
				)
			except Exception as exc:
				log.warning("run_overdue_check: event emission failed (non-fatal): %s", exc)

			count += 1

		if count:
			log.info("BNPLService.run_overdue_check: marked %d instalments OVERDUE", count)
		return count

	# ------------------------------------------------------------------ #
	# Merchant settlement                                                  #
	# ------------------------------------------------------------------ #

	def settle_merchant(
		self,
		merchant_id: str,
		period: str,
		tenant_id: str,
		session: Any,
	) -> BNPLMerchantSettlement:
		"""Create (or update) the settlement record for a merchant/period.

		Sums all COMPLETED BNPL orders for the given YYYY-MM period,
		deducts platform commission, and persists the settlement row.
		Emits MerchantSettledEvent on status=PAID.

		Raises MerchantNotFoundError, SettlementAlreadyExistsError (if PAID).
		"""
		merchant: BNPLMerchant | None = session.execute(
			select(BNPLMerchant).where(
				BNPLMerchant.id == merchant_id,
				BNPLMerchant.tenant_id == tenant_id,
			)
		).scalar_one_or_none()

		if merchant is None:
			raise MerchantNotFoundError(
				f"Merchant {merchant_id!r} not found for tenant {tenant_id!r}"
			)

		# Block re-settlement of already-paid periods
		existing: BNPLMerchantSettlement | None = session.execute(
			select(BNPLMerchantSettlement).where(
				BNPLMerchantSettlement.tenant_id == tenant_id,
				BNPLMerchantSettlement.merchant_id == merchant_id,
				BNPLMerchantSettlement.period == period,
			)
		).scalar_one_or_none()

		if existing and existing.status == "PAID":
			raise SettlementAlreadyExistsError(
				f"Settlement for merchant {merchant_id!r} period {period!r} already PAID"
			)

		# Compute gross sales from COMPLETED applications in the period
		year_str, month_str = period.split("-")
		year, month = int(year_str), int(month_str)
		from datetime import datetime as _dt
		import calendar
		period_start = _dt(year, month, 1, tzinfo=timezone.utc)
		last_day = calendar.monthrange(year, month)[1]
		period_end = _dt(year, month, last_day, 23, 59, 59, tzinfo=timezone.utc)

		gross_result = session.execute(
			select(func.coalesce(func.sum(BNPLApplication.order_amount_cents), 0)).where(
				BNPLApplication.tenant_id == tenant_id,
				BNPLApplication.merchant_id == merchant_id,
				BNPLApplication.status == "COMPLETED",
				BNPLApplication.updated_at >= period_start,
				BNPLApplication.updated_at <= period_end,
			)
		).scalar_one()

		gross_sales_cents = int(gross_result)
		commission_cents = int(
			(Decimal(gross_sales_cents) * Decimal(str(merchant.commission_pct))).to_integral_value(ROUND_HALF_UP)
		)
		net_payout_cents = gross_sales_cents - commission_cents

		now = datetime.now(timezone.utc)

		if existing is None:
			settlement = BNPLMerchantSettlement(
				tenant_id=tenant_id,
				merchant_id=merchant_id,
				period=period,
				gross_sales_cents=gross_sales_cents,
				commission_cents=commission_cents,
				net_payout_cents=net_payout_cents,
				status="PAID",
				settled_at=now,
			)
			session.add(settlement)
		else:
			existing.gross_sales_cents = gross_sales_cents
			existing.commission_cents = commission_cents
			existing.net_payout_cents = net_payout_cents
			existing.status = "PAID"
			existing.settled_at = now
			settlement = existing

		session.flush()

		try:
			emit_event(
				MerchantSettledEvent(
					aggregate_id=settlement.id,
					aggregate_type="BNPLMerchantSettlement",
					tenant_id=tenant_id,
					settlement_id=settlement.id,
					merchant_id=merchant_id,
					period=period,
					gross_sales_cents=gross_sales_cents,
					commission_cents=commission_cents,
					net_payout_cents=net_payout_cents,
				),
				session,
			)
		except Exception as exc:
			log.warning("settle_merchant: event emission failed (non-fatal): %s", exc)

		log.info(
			"BNPLService.settle_merchant: merchant %s period %s → net=%dc",
			merchant_id, period, net_payout_cents,
		)
		return settlement

	# ------------------------------------------------------------------ #
	# Internal fetch helpers                                               #
	# ------------------------------------------------------------------ #

	def _get_application(
		self,
		application_id: str,
		tenant_id: str,
		session: Any,
	) -> BNPLApplication:
		app: BNPLApplication | None = session.execute(
			select(BNPLApplication).where(
				BNPLApplication.id == application_id,
				BNPLApplication.tenant_id == tenant_id,
			)
		).scalar_one_or_none()
		if app is None:
			raise ApplicationNotFoundError(
				f"Application {application_id!r} not found for tenant {tenant_id!r}"
			)
		return app


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"BNPLService",
	"BNPLError",
	"MerchantNotFoundError",
	"ApplicationNotFoundError",
	"InstallmentNotFoundError",
	"InvalidApplicationStatusError",
	"SettlementAlreadyExistsError",
]
