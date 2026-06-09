"""
pgappforge/plugins/erp/industry/real_estate/portfolio/services.py

PortfolioAnalyticsService — stateless business logic for the Portfolio sub-plugin.

All methods accept an explicit SQLAlchemy session (SA 2.x execute() pattern).
No session.commit() inside service methods — callers own the transaction boundary.

Monetary invariant: ALL amounts are integer cents throughout.
Ratio arithmetic: Decimal with ROUND_HALF_UP throughout (no floats for money).

Key methods
-----------
  create_portfolio(name, tenant_id, session, **kwargs) -> PropertyPortfolio
  add_property(portfolio_id, property_id, acquisition_date,
               acquisition_cost_cents, tenant_id, session) -> PortfolioProperty
  get_noi(property_id, from_date, to_date, tenant_id, session) -> dict
  get_cap_rate(property_id, tenant_id, session) -> dict
  get_dscr(property_id, tenant_id, session) -> dict
  compute_irr(property_id, tenant_id, session) -> Decimal | None
  get_portfolio_summary(portfolio_id, tenant_id, session) -> dict
  record_debt(property_id, lender_name, original_principal_cents,
              interest_rate, tenant_id, session, **kwargs) -> PropertyDebt
  record_debt_payment(debt_id, payment_date, total_payment_cents,
                      tenant_id, session) -> DebtPayment
  record_capex(property_id, description, capex_cents, capex_date,
               tenant_id, session, **kwargs) -> CapExRecord
  calculate_distribution(portfolio_id, period, distributable_cents,
                          tenant_id, session) -> DistributionRecord
  pay_distribution(distribution_id, tenant_id, session) -> DistributionRecord
  get_investor_statement(investor_party_id, portfolio_id, tenant_id,
                          session, *, from_period=None) -> dict
"""
from __future__ import annotations

import calendar
import logging
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

import sqlalchemy as sa

from pgappforge.plugins.erp.foundation.events import emit_event
from pgappforge.plugins.workflow.engine import BPMActionRegistry

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# XIRR bisection helper (pure Python, no numpy/scipy)
# ---------------------------------------------------------------------------

def _xirr(
	cash_flows: list[tuple[date, int]],
	max_iter: int = 100,
	tol: float = 1e-6,
) -> Decimal | None:
	"""Newton-Raphson bisection for XIRR.

	cash_flows: list of (date, cents) pairs.
		Negative cents = outflow (investment cost).
		Positive cents = inflow (income or terminal value).
	Dates are measured in fractional years from the first cash flow date
	using the actual/365.25 day-count convention.

	Returns the annual rate as a Decimal rounded to 6 decimal places,
	or None if no solution is found within max_iter iterations or if the
	input is degenerate (fewer than 2 flows).
	"""
	if not cash_flows or len(cash_flows) < 2:
		return None

	sorted_flows = sorted(cash_flows, key=lambda x: x[0])
	t0 = sorted_flows[0][0]
	timed: list[tuple[float, int]] = [
		((dt - t0).days / 365.25, cents)
		for dt, cents in sorted_flows
	]

	def npv(rate: float) -> float:
		if rate <= -1.0:
			return float("inf")
		return sum(cf / ((1.0 + rate) ** t) for t, cf in timed)

	# Locate a sign change in [-0.999, 100.0]
	lo: float = -0.999
	hi: float = 100.0
	npv_lo = npv(lo)

	if npv_lo * npv(hi) > 0:
		for candidate in (10.0, 5.0, 2.0, 1.0, 0.5, 0.1, 0.0, -0.5, -0.9, -0.99):
			if npv_lo * npv(candidate) < 0:
				hi = candidate
				break
		else:
			return None

	# Bisect until interval is smaller than tol
	for _ in range(max_iter):
		mid = (lo + hi) / 2.0
		if abs(hi - lo) < tol:
			break
		if npv_lo * npv(mid) < 0:
			hi = mid
		else:
			lo = mid
			npv_lo = npv(lo)

	result = (lo + hi) / 2.0
	return Decimal(str(result)).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# PortfolioAnalyticsService
# ---------------------------------------------------------------------------

class PortfolioAnalyticsService:
	"""Stateless portfolio analytics service.

	All methods accept an explicit SQLAlchemy session.  No instance state.
	"""

	# ------------------------------------------------------------------
	# Portfolio management
	# ------------------------------------------------------------------

	def create_portfolio(
		self,
		name: str,
		tenant_id: str,
		session: Any,
		**kwargs: Any,
	):
		"""Create and persist a new PropertyPortfolio.

		kwargs: description, status.
		Returns the new PropertyPortfolio (not yet committed).
		"""
		from pgappforge.plugins.erp.industry.real_estate.portfolio.models import PropertyPortfolio

		portfolio = PropertyPortfolio(
			tenant_id=tenant_id,
			name=name,
			description=kwargs.get("description"),
			status=kwargs.get("status", "ACTIVE"),
		)
		session.add(portfolio)
		session.flush()
		log.info("create_portfolio: %r tenant=%r", portfolio.id, tenant_id)
		return portfolio

	def add_property(
		self,
		portfolio_id: str,
		property_id: str,
		acquisition_date: date,
		acquisition_cost_cents: int,
		tenant_id: str,
		session: Any,
	):
		"""Add a property to a portfolio and emit PropertyAcquiredEvent.

		Returns the new PortfolioProperty (not yet committed).
		"""
		from pgappforge.plugins.erp.industry.real_estate.portfolio.models import PortfolioProperty
		from pgappforge.plugins.erp.industry.real_estate.portfolio.events import PropertyAcquiredEvent

		assert acquisition_cost_cents > 0, "acquisition_cost_cents must be > 0"

		pp = PortfolioProperty(
			tenant_id=tenant_id,
			portfolio_id=portfolio_id,
			property_id=property_id,
			acquisition_date=acquisition_date,
			acquisition_cost_cents=acquisition_cost_cents,
			current_value_cents=None,
		)
		session.add(pp)
		session.flush()

		emit_event(
			PropertyAcquiredEvent(
				aggregate_id=portfolio_id,
				aggregate_type="PropertyPortfolio",
				tenant_id=tenant_id,
				portfolio_id=portfolio_id,
				property_id=property_id,
				acquisition_cost_cents=acquisition_cost_cents,
			),
			session,
		)
		log.info(
			"add_property: portfolio=%r property=%r cost=%d¢",
			portfolio_id, property_id, acquisition_cost_cents,
		)
		return pp

	# ------------------------------------------------------------------
	# NOI
	# ------------------------------------------------------------------

	def get_noi(
		self,
		property_id: str,
		from_date: date,
		to_date: date,
		tenant_id: str,
		session: Any,
	) -> dict:
		"""Net Operating Income = Gross Rental Income - Operating Expenses.

		Pulls rent income and maintenance costs from the PM sub-plugin
		(pm_rent_payment via pm_tenant_lease → pm_unit, and pm_work_order
		via pm_maintenance_request → pm_unit) using SQLAlchemy ORM joins.
		Requires the property_management sub-plugin to be loaded; returns
		zeroes gracefully if the tables are not present.

		Returns:
		  {gross_income_cents, operating_expenses_cents, noi_cents, period_months}
		"""
		income = self._pm_rent_income(property_id, from_date, to_date, tenant_id, session)
		expenses = self._pm_work_order_costs(property_id, from_date, to_date, tenant_id, session)
		noi = income - expenses
		period_months = self._months_between(from_date, to_date)
		return {
			"gross_income_cents": income,
			"operating_expenses_cents": expenses,
			"noi_cents": noi,
			"period_months": period_months,
		}

	def _pm_rent_income(
		self,
		property_id: str,
		from_date: date,
		to_date: date,
		tenant_id: str,
		session: Any,
	) -> int:
		"""SUM of paid rent for units belonging to property_id within the date range."""
		try:
			from pgappforge.plugins.erp.industry.real_estate.property_management.models import (
				RentPayment,
				TenantLease,
				PropertyUnit,
			)
			result = session.execute(
				sa.select(sa.func.coalesce(sa.func.sum(RentPayment.amount_cents), 0))
				.join(TenantLease, RentPayment.lease_id == TenantLease.id)
				.join(PropertyUnit, TenantLease.unit_id == PropertyUnit.id)
				.where(
					PropertyUnit.property_id == property_id,
					RentPayment.tenant_id == tenant_id,
					RentPayment.status == "PAID",
					RentPayment.paid_date >= from_date,
					RentPayment.paid_date <= to_date,
				)
			)
			return int(result.scalar_one() or 0)
		except Exception as exc:
			log.debug("_pm_rent_income: PM plugin not available or query failed: %s", exc)
			return 0

	def _pm_work_order_costs(
		self,
		property_id: str,
		from_date: date,
		to_date: date,
		tenant_id: str,
		session: Any,
	) -> int:
		"""SUM of completed work order costs for units belonging to property_id."""
		try:
			from pgappforge.plugins.erp.industry.real_estate.property_management.models import (
				WorkOrder,
				MaintenanceRequest,
				PropertyUnit,
			)
			result = session.execute(
				sa.select(sa.func.coalesce(sa.func.sum(WorkOrder.actual_cost_cents), 0))
				.join(MaintenanceRequest, WorkOrder.request_id == MaintenanceRequest.id)
				.join(PropertyUnit, MaintenanceRequest.unit_id == PropertyUnit.id)
				.where(
					PropertyUnit.property_id == property_id,
					WorkOrder.tenant_id == tenant_id,
					WorkOrder.status == "COMPLETED",
					WorkOrder.completed_date >= from_date,
					WorkOrder.completed_date <= to_date,
				)
			)
			return int(result.scalar_one() or 0)
		except Exception as exc:
			log.debug("_pm_work_order_costs: PM plugin not available or query failed: %s", exc)
			return 0

	@staticmethod
	def _months_between(from_date: date, to_date: date) -> int:
		"""Calendar-month count between two dates (minimum 1)."""
		months = (to_date.year - from_date.year) * 12 + (to_date.month - from_date.month)
		return max(1, months)

	# ------------------------------------------------------------------
	# Cap Rate
	# ------------------------------------------------------------------

	def get_cap_rate(
		self,
		property_id: str,
		tenant_id: str,
		session: Any,
	) -> dict:
		"""Cap Rate = Annualised NOI / Current Property Value.

		Uses trailing 12-month NOI.  Property value from the most recent
		PropertyValuation record.

		Returns:
		  {noi_cents, property_value_cents, cap_rate_pct}
		  cap_rate_pct is a Decimal (e.g. Decimal('7.2500')), or None if
		  no valuation exists.
		"""
		from pgappforge.plugins.erp.industry.real_estate.models import PropertyValuation

		today = date.today()
		one_year_ago = date(today.year - 1, today.month, today.day)

		noi_data = self.get_noi(property_id, one_year_ago, today, tenant_id, session)
		period_months = noi_data["period_months"]
		annualised_noi = int(
			(Decimal(str(noi_data["noi_cents"])) * Decimal("12") / Decimal(str(period_months)))
			.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
		)

		valuation = session.execute(
			sa.select(PropertyValuation)
			.where(
				PropertyValuation.property_id == property_id,
				PropertyValuation.tenant_id == tenant_id,
			)
			.order_by(sa.desc(PropertyValuation.valuation_date))
			.limit(1)
		).scalar_one_or_none()

		property_value_cents: int | None = (
			valuation.estimated_value_cents if valuation else None
		)

		if not property_value_cents:
			cap_rate_pct: Decimal | None = None
		else:
			cap_rate_pct = (
				Decimal(str(annualised_noi)) / Decimal(str(property_value_cents)) * Decimal("100")
			).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)

		return {
			"noi_cents": annualised_noi,
			"property_value_cents": property_value_cents,
			"cap_rate_pct": cap_rate_pct,
		}

	# ------------------------------------------------------------------
	# DSCR
	# ------------------------------------------------------------------

	def get_dscr(
		self,
		property_id: str,
		tenant_id: str,
		session: Any,
	) -> dict:
		"""DSCR = Annualised NOI / Annual Debt Service.

		Annual debt service = SUM(monthly_payment_cents * 12) for all ACTIVE
		debts on this property where monthly_payment_cents IS NOT NULL.
		A DSCR > 1.25 is considered healthy by most lenders.

		Returns:
		  {noi_cents, annual_debt_service_cents, dscr}
		  dscr is a Decimal, or None if no scheduled debt service found.
		"""
		from pgappforge.plugins.erp.industry.real_estate.portfolio.models import PropertyDebt

		today = date.today()
		one_year_ago = date(today.year - 1, today.month, today.day)
		noi_data = self.get_noi(property_id, one_year_ago, today, tenant_id, session)
		period_months = noi_data["period_months"]
		annualised_noi = int(
			(Decimal(str(noi_data["noi_cents"])) * Decimal("12") / Decimal(str(period_months)))
			.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
		)

		debts = session.execute(
			sa.select(PropertyDebt).where(
				PropertyDebt.property_id == property_id,
				PropertyDebt.tenant_id == tenant_id,
				PropertyDebt.status == "ACTIVE",
				PropertyDebt.monthly_payment_cents.is_not(None),
			)
		).scalars().all()

		annual_debt_service = sum(int(d.monthly_payment_cents) * 12 for d in debts)

		if annual_debt_service == 0:
			dscr: Decimal | None = None
		else:
			dscr = (
				Decimal(str(annualised_noi)) / Decimal(str(annual_debt_service))
			).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)

		return {
			"noi_cents": annualised_noi,
			"annual_debt_service_cents": annual_debt_service,
			"dscr": dscr,
		}

	# ------------------------------------------------------------------
	# IRR
	# ------------------------------------------------------------------

	def compute_irr(
		self,
		property_id: str,
		tenant_id: str,
		session: Any,
	) -> Decimal | None:
		"""Internal Rate of Return on a property investment.

		Cash flow construction:
		  t=0         : -acquisition_cost_cents at acquisition_date
		  t=1..n      : monthly_noi each month (trailing 12M NOI / 12)
		  t=final     : current_value_cents as terminal value (if set)

		Returns None if fewer than 12 months have elapsed since acquisition,
		or if no PortfolioProperty record exists for this property.
		Uses _xirr (pure-Python bisection, no numpy/scipy).
		"""
		from pgappforge.plugins.erp.industry.real_estate.portfolio.models import PortfolioProperty

		pp = session.execute(
			sa.select(PortfolioProperty)
			.where(
				PortfolioProperty.property_id == property_id,
				PortfolioProperty.tenant_id == tenant_id,
			)
			.order_by(sa.asc(PortfolioProperty.acquisition_date))
			.limit(1)
		).scalar_one_or_none()

		if pp is None:
			return None

		today = date.today()
		months_held = self._months_between(pp.acquisition_date, today)
		if months_held < 12:
			return None

		one_year_ago = date(today.year - 1, today.month, today.day)
		noi_data = self.get_noi(property_id, one_year_ago, today, tenant_id, session)
		period_months = noi_data["period_months"]
		annualised_noi = int(
			(Decimal(str(noi_data["noi_cents"])) * Decimal("12") / Decimal(str(period_months)))
			.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
		)
		monthly_noi = annualised_noi // 12

		cash_flows: list[tuple[date, int]] = [
			(pp.acquisition_date, -pp.acquisition_cost_cents),
		]

		# One inflow per month from acquisition forward
		acq = pp.acquisition_date
		for i in range(1, months_held + 1):
			raw_month = acq.month + i - 1
			yr = acq.year + raw_month // 12
			mo = (raw_month % 12) + 1
			day = min(acq.day, calendar.monthrange(yr, mo)[1])
			cash_flows.append((date(yr, mo, day), monthly_noi))

		if pp.current_value_cents and pp.current_value_cents > 0:
			cash_flows.append((today, pp.current_value_cents))

		return _xirr(cash_flows)

	# ------------------------------------------------------------------
	# Portfolio summary
	# ------------------------------------------------------------------

	def get_portfolio_summary(
		self,
		portfolio_id: str,
		tenant_id: str,
		session: Any,
	) -> dict:
		"""Aggregate analytics for every property in a portfolio.

		Returns:
		  {
		    portfolio_id,
		    properties: [{property_id, noi_cents, cap_rate_pct, occupancy_pct,
		                  debt_outstanding_cents, equity_cents}],
		    totals: {total_value_cents, total_debt_cents, total_equity_cents,
		             total_noi_cents, portfolio_ltv_pct}
		  }
		"""
		from pgappforge.plugins.erp.industry.real_estate.portfolio.models import (
			PortfolioProperty,
			PropertyDebt,
		)

		pps = session.execute(
			sa.select(PortfolioProperty).where(
				PortfolioProperty.portfolio_id == portfolio_id,
				PortfolioProperty.tenant_id == tenant_id,
			)
		).scalars().all()

		properties_out: list[dict] = []
		total_value = 0
		total_debt = 0
		total_noi = 0

		today = date.today()
		one_year_ago = date(today.year - 1, today.month, today.day)

		for pp in pps:
			pid = pp.property_id

			noi_data = self.get_noi(pid, one_year_ago, today, tenant_id, session)
			period_months = noi_data["period_months"]
			noi_cents = int(
				(Decimal(str(noi_data["noi_cents"])) * Decimal("12") / Decimal(str(period_months)))
				.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
			)

			cap_data = self.get_cap_rate(pid, tenant_id, session)
			cap_rate_pct = cap_data["cap_rate_pct"]

			debt_rows = session.execute(
				sa.select(PropertyDebt).where(
					PropertyDebt.property_id == pid,
					PropertyDebt.tenant_id == tenant_id,
					PropertyDebt.status == "ACTIVE",
				)
			).scalars().all()
			debt_outstanding = sum(int(d.current_balance_cents) for d in debt_rows)

			current_value = pp.current_value_cents or 0
			equity = current_value - debt_outstanding
			occupancy_pct = self._get_occupancy_pct(pid, tenant_id, session)

			total_value += current_value
			total_debt += debt_outstanding
			total_noi += noi_cents

			properties_out.append({
				"property_id": pid,
				"noi_cents": noi_cents,
				"cap_rate_pct": str(cap_rate_pct) if cap_rate_pct is not None else None,
				"occupancy_pct": str(occupancy_pct) if occupancy_pct is not None else None,
				"debt_outstanding_cents": debt_outstanding,
				"equity_cents": equity,
			})

		total_equity = total_value - total_debt
		portfolio_ltv_pct: Decimal | None = (
			(Decimal(str(total_debt)) / Decimal(str(total_value)) * Decimal("100"))
			.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
			if total_value > 0 else None
		)

		return {
			"portfolio_id": portfolio_id,
			"properties": properties_out,
			"totals": {
				"total_value_cents": total_value,
				"total_debt_cents": total_debt,
				"total_equity_cents": total_equity,
				"total_noi_cents": total_noi,
				"portfolio_ltv_pct": str(portfolio_ltv_pct) if portfolio_ltv_pct is not None else None,
			},
		}

	def _get_occupancy_pct(
		self,
		property_id: str,
		tenant_id: str,
		session: Any,
	) -> Decimal | None:
		"""Occupancy = ACTIVE units / total units for this property (from PM plugin).

		Returns None if the PM plugin is not loaded or no units exist.
		"""
		try:
			from pgappforge.plugins.erp.industry.real_estate.property_management.models import PropertyUnit
			today = date.today()
			total = session.execute(
				sa.select(sa.func.count(PropertyUnit.id)).where(
					PropertyUnit.property_id == property_id,
					PropertyUnit.tenant_id == tenant_id,
				)
			).scalar_one() or 0
			if total == 0:
				return None
			occupied = session.execute(
				sa.select(sa.func.count(PropertyUnit.id)).where(
					PropertyUnit.property_id == property_id,
					PropertyUnit.tenant_id == tenant_id,
					PropertyUnit.status == "OCCUPIED",
				)
			).scalar_one() or 0
			return (
				Decimal(str(occupied)) / Decimal(str(total)) * Decimal("100")
			).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
		except Exception as exc:
			log.debug("_get_occupancy_pct: PM plugin not available: %s", exc)
			return None

	# ------------------------------------------------------------------
	# Debt management
	# ------------------------------------------------------------------

	def record_debt(
		self,
		property_id: str,
		lender_name: str,
		original_principal_cents: int,
		interest_rate: Decimal | str,
		tenant_id: str,
		session: Any,
		**kwargs: Any,
	):
		"""Persist a new PropertyDebt instrument.

		kwargs: loan_type, amortization_years, maturity_date, payment_day_of_month,
		        monthly_payment_cents, lien_position, status.
		Returns the new PropertyDebt (not yet committed).
		"""
		from pgappforge.plugins.erp.industry.real_estate.portfolio.models import PropertyDebt

		assert original_principal_cents > 0, "original_principal_cents must be > 0"

		debt = PropertyDebt(
			tenant_id=tenant_id,
			property_id=property_id,
			lender_name=lender_name,
			loan_type=kwargs.get("loan_type", "MORTGAGE"),
			original_principal_cents=original_principal_cents,
			current_balance_cents=original_principal_cents,
			interest_rate=Decimal(str(interest_rate)),
			amortization_years=kwargs.get("amortization_years"),
			maturity_date=kwargs.get("maturity_date"),
			payment_day_of_month=int(kwargs.get("payment_day_of_month", 1)),
			monthly_payment_cents=kwargs.get("monthly_payment_cents"),
			status=kwargs.get("status", "ACTIVE"),
			lien_position=int(kwargs.get("lien_position", 1)),
		)
		session.add(debt)
		session.flush()
		log.info("record_debt: %r property=%r balance=%d¢", debt.id, property_id, original_principal_cents)
		return debt

	def record_debt_payment(
		self,
		debt_id: str,
		payment_date: date,
		total_payment_cents: int,
		tenant_id: str,
		session: Any,
	):
		"""Record a debt payment and update the outstanding balance.

		Interest split: interest_cents = balance * (rate/100) / 12  (ROUND_HALF_UP).
		principal_cents = total_payment_cents - interest_cents.
		Updates PropertyDebt.current_balance_cents in place.
		Sets status to PAID_OFF when balance reaches zero.

		Returns the new DebtPayment (not yet committed).
		"""
		from pgappforge.plugins.erp.industry.real_estate.portfolio.models import (
			DebtPayment,
			PropertyDebt,
		)

		assert total_payment_cents > 0, "total_payment_cents must be > 0"

		debt = session.get(PropertyDebt, debt_id)
		if debt is None:
			raise ValueError(f"PropertyDebt {debt_id!r} not found")
		if debt.tenant_id != tenant_id:
			raise ValueError("tenant_id mismatch on PropertyDebt")

		balance = Decimal(str(debt.current_balance_cents))
		monthly_rate = Decimal(str(debt.interest_rate)) / Decimal("100") / Decimal("12")
		interest_cents = int(
			(balance * monthly_rate).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
		)
		principal_cents = total_payment_cents - interest_cents

		# Cap principal at remaining balance (final/overpayment guard)
		if principal_cents > int(balance):
			principal_cents = int(balance)
			total_payment_cents = principal_cents + interest_cents

		new_balance = max(0, int(balance) - principal_cents)
		debt.current_balance_cents = new_balance
		if new_balance == 0:
			debt.status = "PAID_OFF"
		debt.updated_at = datetime.now(timezone.utc)

		payment = DebtPayment(
			tenant_id=tenant_id,
			debt_id=debt_id,
			payment_date=payment_date,
			total_payment_cents=total_payment_cents,
			principal_cents=principal_cents,
			interest_cents=interest_cents,
			remaining_balance_cents=new_balance,
			status="PAID",
		)
		session.add(payment)
		session.flush()
		log.info(
			"record_debt_payment: debt=%r principal=%d¢ interest=%d¢ remaining=%d¢",
			debt_id, principal_cents, interest_cents, new_balance,
		)
		return payment

	# ------------------------------------------------------------------
	# CapEx
	# ------------------------------------------------------------------

	def record_capex(
		self,
		property_id: str,
		description: str,
		capex_cents: int,
		capex_date: date,
		tenant_id: str,
		session: Any,
		**kwargs: Any,
	):
		"""Persist a CapExRecord and emit CapExRecordedEvent.

		kwargs: category, budget_cents, vendor_name, is_capitalizable.
		Returns the new CapExRecord (not yet committed).
		"""
		from pgappforge.plugins.erp.industry.real_estate.portfolio.models import CapExRecord
		from pgappforge.plugins.erp.industry.real_estate.portfolio.events import CapExRecordedEvent

		assert capex_cents > 0, "capex_cents must be > 0"

		category = kwargs.get("category", "IMPROVEMENT")
		record = CapExRecord(
			tenant_id=tenant_id,
			property_id=property_id,
			description=description,
			capex_cents=capex_cents,
			capex_date=capex_date,
			category=category,
			budget_cents=kwargs.get("budget_cents"),
			vendor_name=kwargs.get("vendor_name"),
			is_capitalizable=bool(kwargs.get("is_capitalizable", True)),
		)
		session.add(record)
		session.flush()

		emit_event(
			CapExRecordedEvent(
				aggregate_id=property_id,
				aggregate_type="Property",
				tenant_id=tenant_id,
				property_id=property_id,
				capex_cents=capex_cents,
				category=category,
			),
			session,
		)
		log.info(
			"record_capex: %r property=%r amount=%d¢ category=%r",
			record.id, property_id, capex_cents, category,
		)
		return record

	# ------------------------------------------------------------------
	# Distributions
	# ------------------------------------------------------------------

	def calculate_distribution(
		self,
		portfolio_id: str,
		period: str,
		distributable_cents: int,
		tenant_id: str,
		session: Any,
	):
		"""Compute pro-rata investor distribution and create a DRAFT DistributionRecord.

		Algorithm:
		  1. Fetch all ACTIVE InvestorHoldings, sorted desc by ownership_pct.
		  2. Validate SUM(ownership_pct) == 100.0000 ± 0.01.
		  3. Allocate distributable_cents proportionally (ROUND_HALF_UP per investor).
		  4. Assign any rounding remainder to the largest-ownership investor.
		  5. Persist DistributionRecord with status=DRAFT.

		period: "YYYY-MM".
		Returns the new DistributionRecord (not yet committed).
		"""
		from pgappforge.plugins.erp.industry.real_estate.portfolio.models import (
			DistributionRecord,
			InvestorHolding,
		)

		assert distributable_cents > 0, "distributable_cents must be > 0"

		holdings = session.execute(
			sa.select(InvestorHolding)
			.where(
				InvestorHolding.portfolio_id == portfolio_id,
				InvestorHolding.tenant_id == tenant_id,
				InvestorHolding.status == "ACTIVE",
			)
			.order_by(sa.desc(InvestorHolding.ownership_pct))
		).scalars().all()

		if not holdings:
			raise ValueError(f"No ACTIVE investor holdings for portfolio {portfolio_id!r}")

		total_pct = sum(Decimal(str(h.ownership_pct)) for h in holdings)
		if abs(total_pct - Decimal("100")) > Decimal("0.01"):
			raise ValueError(
				f"Ownership percentages sum to {total_pct} — expected 100.00 ± 0.01 "
				f"for portfolio {portfolio_id!r}"
			)

		allocations: list[dict] = []
		allocated_total = 0
		for holding in holdings:
			pct = Decimal(str(holding.ownership_pct))
			amount = int(
				(Decimal(str(distributable_cents)) * pct / Decimal("100"))
				.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
			)
			allocations.append({
				"investor_party_id": str(holding.investor_party_id),
				"ownership_pct": str(pct),
				"amount_cents": amount,
			})
			allocated_total += amount

		# Remainder (from rounding) goes to the largest holder (first in desc-sorted list)
		remainder = distributable_cents - allocated_total
		if remainder != 0:
			allocations[0]["amount_cents"] += remainder

		dist = DistributionRecord(
			tenant_id=tenant_id,
			portfolio_id=portfolio_id,
			period=period,
			total_distributable_cents=distributable_cents,
			allocations=allocations,
			distributed_at=None,
			status="DRAFT",
		)
		session.add(dist)
		session.flush()
		log.info(
			"calculate_distribution: %r portfolio=%r period=%r total=%d¢ investors=%d",
			dist.id, portfolio_id, period, distributable_cents, len(holdings),
		)
		return dist

	def pay_distribution(
		self,
		distribution_id: str,
		tenant_id: str,
		session: Any,
	):
		"""Transition a DRAFT DistributionRecord to PAID and emit DistributionPaidEvent.

		Returns the updated DistributionRecord (not yet committed).
		"""
		from pgappforge.plugins.erp.industry.real_estate.portfolio.models import DistributionRecord
		from pgappforge.plugins.erp.industry.real_estate.portfolio.events import DistributionPaidEvent

		dist = session.get(DistributionRecord, distribution_id)
		if dist is None:
			raise ValueError(f"DistributionRecord {distribution_id!r} not found")
		if dist.tenant_id != tenant_id:
			raise ValueError("tenant_id mismatch on DistributionRecord")
		if dist.status != "DRAFT":
			raise ValueError(f"DistributionRecord {distribution_id!r} is already {dist.status!r}")

		dist.status = "PAID"
		dist.distributed_at = datetime.now(timezone.utc)
		session.flush()

		emit_event(
			DistributionPaidEvent(
				aggregate_id=dist.portfolio_id,
				aggregate_type="PropertyPortfolio",
				tenant_id=tenant_id,
				portfolio_id=dist.portfolio_id,
				period=dist.period,
				total_cents=dist.total_distributable_cents,
			),
			session,
		)
		log.info(
			"pay_distribution: %r portfolio=%r period=%r paid=%d¢",
			distribution_id, dist.portfolio_id, dist.period, dist.total_distributable_cents,
		)
		return dist

	# ------------------------------------------------------------------
	# Investor statement
	# ------------------------------------------------------------------

	def get_investor_statement(
		self,
		investor_party_id: str,
		portfolio_id: str,
		tenant_id: str,
		session: Any,
		*,
		from_period: str | None = None,
	) -> dict:
		"""Return a consolidated investor statement for a portfolio.

		from_period: optional "YYYY-MM" — only PAID distributions >= this period.

		Returns:
		  {
		    investor_party_id,
		    portfolio_id,
		    holdings: [{period, amount_cents}],
		    total_distributions_cents,
		    current_ownership_pct,
		    total_investment_cents,
		  }
		"""
		from pgappforge.plugins.erp.industry.real_estate.portfolio.models import (
			DistributionRecord,
			InvestorHolding,
		)

		holding = session.execute(
			sa.select(InvestorHolding).where(
				InvestorHolding.portfolio_id == portfolio_id,
				InvestorHolding.investor_party_id == investor_party_id,
				InvestorHolding.tenant_id == tenant_id,
				InvestorHolding.status == "ACTIVE",
			).limit(1)
		).scalar_one_or_none()

		current_ownership_pct: Decimal | None = None
		total_investment_cents = 0
		if holding:
			current_ownership_pct = Decimal(str(holding.ownership_pct))
			total_investment_cents = int(holding.investment_cents)

		q = (
			sa.select(DistributionRecord)
			.where(
				DistributionRecord.portfolio_id == portfolio_id,
				DistributionRecord.tenant_id == tenant_id,
				DistributionRecord.status == "PAID",
			)
			.order_by(sa.asc(DistributionRecord.period))
		)
		if from_period:
			q = q.where(DistributionRecord.period >= from_period)

		distributions = session.execute(q).scalars().all()

		holdings_out: list[dict] = []
		total_dist_cents = 0
		for dist in distributions:
			for alloc in (dist.allocations or []):
				if str(alloc.get("investor_party_id")) == str(investor_party_id):
					amount = int(alloc.get("amount_cents", 0))
					holdings_out.append({"period": dist.period, "amount_cents": amount})
					total_dist_cents += amount
					break

		return {
			"investor_party_id": investor_party_id,
			"portfolio_id": portfolio_id,
			"holdings": holdings_out,
			"total_distributions_cents": total_dist_cents,
			"current_ownership_pct": str(current_ownership_pct) if current_ownership_pct is not None else None,
			"total_investment_cents": total_investment_cents,
		}


# ---------------------------------------------------------------------------
# BPM registrations
# ---------------------------------------------------------------------------

@BPMActionRegistry.register("re_portfolio.get_noi", "Compute Net Operating Income")
def _bpm_get_noi(
	record_ctx: dict,
	session: Any,
	property_id: str = "",
	from_date: str = "",
	to_date: str = "",
	**kw: Any,
) -> dict:
	from datetime import date as _date
	tenant_id = record_ctx.get("tenant_id", "")
	try:
		svc = PortfolioAnalyticsService()
		result = svc.get_noi(
			property_id=property_id,
			from_date=_date.fromisoformat(from_date),
			to_date=_date.fromisoformat(to_date),
			tenant_id=tenant_id,
			session=session,
		)
		return {"status": "ok", **result}
	except Exception as exc:
		log.warning("bpm re_portfolio.get_noi failed: %s", exc)
		return {"status": "error", "message": str(exc)}


@BPMActionRegistry.register("re_portfolio.get_cap_rate", "Compute cap rate")
def _bpm_get_cap_rate(
	record_ctx: dict,
	session: Any,
	property_id: str = "",
	**kw: Any,
) -> dict:
	tenant_id = record_ctx.get("tenant_id", "")
	try:
		svc = PortfolioAnalyticsService()
		result = svc.get_cap_rate(
			property_id=property_id,
			tenant_id=tenant_id,
			session=session,
		)
		return {
			"status": "ok",
			"noi_cents": result["noi_cents"],
			"property_value_cents": result["property_value_cents"],
			"cap_rate_pct": str(result["cap_rate_pct"]) if result["cap_rate_pct"] is not None else None,
		}
	except Exception as exc:
		log.warning("bpm re_portfolio.get_cap_rate failed: %s", exc)
		return {"status": "error", "message": str(exc)}


@BPMActionRegistry.register("re_portfolio.calculate_distribution", "Calculate investor distribution")
def _bpm_calculate_distribution(
	record_ctx: dict,
	session: Any,
	portfolio_id: str = "",
	period: str = "",
	distributable_cents: int = 0,
	**kw: Any,
) -> dict:
	tenant_id = record_ctx.get("tenant_id", "")
	try:
		svc = PortfolioAnalyticsService()
		dist = svc.calculate_distribution(
			portfolio_id=portfolio_id,
			period=period,
			distributable_cents=int(distributable_cents),
			tenant_id=tenant_id,
			session=session,
		)
		return {"status": "ok", "distribution_id": dist.id, "status_value": dist.status}
	except Exception as exc:
		log.warning("bpm re_portfolio.calculate_distribution failed: %s", exc)
		return {"status": "error", "message": str(exc)}


@BPMActionRegistry.register("re_portfolio.record_capex", "Record capital expenditure")
def _bpm_record_capex(
	record_ctx: dict,
	session: Any,
	property_id: str = "",
	description: str = "",
	capex_cents: int = 0,
	capex_date: str = "",
	**kw: Any,
) -> dict:
	from datetime import date as _date
	tenant_id = record_ctx.get("tenant_id", "")
	try:
		svc = PortfolioAnalyticsService()
		record = svc.record_capex(
			property_id=property_id,
			description=description,
			capex_cents=int(capex_cents),
			capex_date=_date.fromisoformat(capex_date),
			tenant_id=tenant_id,
			session=session,
			**{k: v for k, v in kw.items() if k in ("category", "budget_cents", "vendor_name", "is_capitalizable")},
		)
		return {"status": "ok", "capex_id": record.id}
	except Exception as exc:
		log.warning("bpm re_portfolio.record_capex failed: %s", exc)
		return {"status": "error", "message": str(exc)}


__all__ = [
	"PortfolioAnalyticsService",
	"_xirr",
]
