"""
pgappforge/plugins/erp/industry/financial_contracts/services.py

FinancialContractsService — ACTUS-based financial contract calculations.

All methods accept an explicit SQLAlchemy Session; callers own transaction
boundaries.  No Flask context assumed.

All monetary amounts are integer cents.
Interest rates are Decimal (0.05 = 5% p.a.).
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

import sqlalchemy as sa
from sqlalchemy import select

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class FinancialContractsError(Exception):
	"""Base error for Financial Contracts domain violations."""


class ContractNotFoundError(FinancialContractsError):
	"""No FinancialContract with the given id."""


class InvalidContractTypeError(FinancialContractsError):
	"""contract_type is not a supported ACTUS type."""


class CashFlowGenerationError(FinancialContractsError):
	"""Could not generate cash flows for this contract type/terms."""


SUPPORTED_CONTRACT_TYPES = frozenset({"PAM", "ANN", "CLM", "BND", "LAX", "NAM"})

# Day-count convention helpers
_DAY_COUNT_DIVISORS: dict[str, int] = {
	"A360": 360,
	"A365": 365,
	"30E360": 360,
	"ACT/ACT": 365,
}


def _year_fraction(d1: date, d2: date, dcc: str) -> Decimal:
	"""Compute year fraction between two dates under a day-count convention."""
	delta_days = (d2 - d1).days
	divisor = _DAY_COUNT_DIVISORS.get(dcc.upper(), 365)
	return Decimal(delta_days) / Decimal(divisor)


def _discount_factor(rate: Decimal, year_frac: Decimal) -> Decimal:
	"""Simple discount factor: 1 / (1 + r)^t."""
	return Decimal(1) / ((Decimal(1) + rate) ** year_frac)


# ---------------------------------------------------------------------------
# FinancialContractsService
# ---------------------------------------------------------------------------

class FinancialContractsService:
	"""Stateless service for ACTUS financial contract operations.

	Instantiate once per app (or per request).  All methods accept a
	SQLAlchemy Session as their last positional argument; callers own
	transaction boundaries (commit/rollback).
	"""

	# ------------------------------------------------------------------
	# Cash flow generation (ACTUS PAM / ANN / LAX core algorithms)
	# ------------------------------------------------------------------

	def generate_cash_flows(
		self,
		contract_id: str,
		session: Any,
		tenant_id: str = "",
	) -> list:
		"""Generate the full cash flow schedule for a contract.

		Implements:
		  PAM — bullet: IED (notional out), periodic IP, MD (notional + final IP)
		  ANN — level annuity: IED, periodic IP+PR combined, MD
		  LAX — linear amortiser: IED, equal PR + declining IP, MD
		  CLM/BND/NAM — simplified PAM-like schedule (full ACTUS spec
		                requires external risk factor feeds; use contract_terms
		                for extended attributes).

		All amounts in integer cents.  Returns unsaved CashFlowSchedule rows;
		caller must session.add_all() and commit.
		"""
		from pgappforge.plugins.erp.industry.financial_contracts.models import (
			FinancialContract, CashFlowSchedule,
		)
		from pgappforge.plugins.erp.industry.financial_contracts.events import (
			CashFlowsGeneratedEvent, emit_event,
		)

		contract = session.get(FinancialContract, contract_id)
		if contract is None:
			raise ContractNotFoundError(f"FinancialContract {contract_id!r} not found")

		ct = str(contract.contract_type).upper()
		if ct not in SUPPORTED_CONTRACT_TYPES:
			raise InvalidContractTypeError(f"Contract type {ct!r} not supported")

		terms = contract.contract_terms or {}
		dcc = str(contract.day_count_convention)
		notional = int(contract.notional_principal_cents)
		rate = Decimal(str(contract.nominal_interest_rate))
		ied = contract.initial_exchange_date
		md = contract.maturity_date
		ccy = str(contract.currency_code)
		tid = tenant_id or str(contract.tenant_id)

		# Payment frequency in months (from contract_terms or default annual)
		payment_freq_months: int = int(terms.get("payment_frequency_months", 12))

		flows: list[CashFlowSchedule] = []

		# IED: principal exchange (direction depends on contract_role)
		# RPA = receive principal → positive inflow; RPL → negative
		ied_sign = 1 if str(contract.contract_role).upper() == "RPA" else -1
		flows.append(CashFlowSchedule(
			tenant_id=tid,
			contract_id=contract_id,
			schedule_date=ied,
			event_type="IED",
			scheduled_amount_cents=ied_sign * notional,
			currency_code=ccy,
			status="SCHEDULED",
		))

		# Build coupon dates
		coupon_dates: list[date] = []
		cursor = _add_months(ied, payment_freq_months)
		while cursor <= md:
			coupon_dates.append(cursor)
			cursor = _add_months(cursor, payment_freq_months)
		if not coupon_dates or coupon_dates[-1] != md:
			coupon_dates.append(md)

		if ct == "PAM" or ct in ("CLM", "BND", "NAM"):
			# Bullet: periodic interest only, notional back at maturity
			prev = ied
			remaining = notional
			for i, cpn_date in enumerate(coupon_dates):
				yf = _year_fraction(prev, cpn_date, dcc)
				interest_cents = int(
					(Decimal(remaining) * rate * yf).quantize(
						Decimal("1"), rounding=ROUND_HALF_UP
					)
				)
				is_maturity = (cpn_date == md)
				if is_maturity:
					# MD: interest + principal repayment
					flows.append(CashFlowSchedule(
						tenant_id=tid,
						contract_id=contract_id,
						schedule_date=cpn_date,
						event_type="MD",
						scheduled_amount_cents=-(ied_sign * (remaining + interest_cents)),
						currency_code=ccy,
						status="SCHEDULED",
					))
				else:
					flows.append(CashFlowSchedule(
						tenant_id=tid,
						contract_id=contract_id,
						schedule_date=cpn_date,
						event_type="IP",
						scheduled_amount_cents=-(ied_sign * interest_cents),
						currency_code=ccy,
						status="SCHEDULED",
					))
				prev = cpn_date

		elif ct == "ANN":
			# Level annuity: constant total payment (IP + PR)
			n = len(coupon_dates)
			yf0 = _year_fraction(ied, coupon_dates[0], dcc) if coupon_dates else Decimal("1")
			# Annuity payment = PV × r / (1 - (1+r)^-n)  per period
			r_per = rate * yf0
			if r_per == 0:
				annuity_payment = notional // n if n > 0 else notional
			else:
				annuity_payment = int(
					(Decimal(notional) * r_per / (1 - (1 + r_per) ** (-n))).quantize(
						Decimal("1"), rounding=ROUND_HALF_UP
					)
				)
			prev = ied
			remaining = notional
			for i, cpn_date in enumerate(coupon_dates):
				yf = _year_fraction(prev, cpn_date, dcc)
				interest_cents = int(
					(Decimal(remaining) * rate * yf).quantize(
						Decimal("1"), rounding=ROUND_HALF_UP
					)
				)
				principal_cents = annuity_payment - interest_cents
				# Last period: pay off exactly what's remaining
				if i == len(coupon_dates) - 1:
					principal_cents = remaining
				remaining -= principal_cents
				evt = "MD" if cpn_date == md else "PR"
				flows.append(CashFlowSchedule(
					tenant_id=tid,
					contract_id=contract_id,
					schedule_date=cpn_date,
					event_type=evt,
					scheduled_amount_cents=-(ied_sign * (principal_cents + interest_cents)),
					currency_code=ccy,
					status="SCHEDULED",
				))
				prev = cpn_date

		elif ct == "LAX":
			# Linear amortiser: equal principal repayment each period
			n = len(coupon_dates)
			pr_per_period = notional // n if n > 0 else notional
			prev = ied
			remaining = notional
			for i, cpn_date in enumerate(coupon_dates):
				yf = _year_fraction(prev, cpn_date, dcc)
				interest_cents = int(
					(Decimal(remaining) * rate * yf).quantize(
						Decimal("1"), rounding=ROUND_HALF_UP
					)
				)
				# Last period pays remaining balance
				pr = remaining if i == len(coupon_dates) - 1 else pr_per_period
				remaining -= pr
				evt = "MD" if cpn_date == md else "PR"
				flows.append(CashFlowSchedule(
					tenant_id=tid,
					contract_id=contract_id,
					schedule_date=cpn_date,
					event_type=evt,
					scheduled_amount_cents=-(ied_sign * (pr + interest_cents)),
					currency_code=ccy,
					status="SCHEDULED",
				))
				prev = cpn_date

		emit_event(
			"financial_contracts.cash_flows.generated",
			"FinancialContract",
			contract_id,
			{
				"contract_id": contract_id,
				"contract_type": ct,
				"flow_count": len(flows),
				"first_event_date": flows[0].schedule_date.isoformat() if flows else "",
				"maturity_date": md.isoformat(),
			},
			session,
			tenant_id=tid,
		)

		log.info(
			"generate_cash_flows: contract=%r type=%s → %d flows",
			contract_id, ct, len(flows),
		)
		return flows

	# ------------------------------------------------------------------
	# NPV calculation
	# ------------------------------------------------------------------

	def calculate_npv(
		self,
		contract_id: str,
		discount_rate: Decimal | float | str,
		as_of_date: date,
		session: Any,
	) -> int:
		"""Calculate net present value of a contract's cash flows.

		Uses the stored CashFlowSchedule rows (SCHEDULED + SETTLED).
		Discounts each future cash flow back to as_of_date using
		continuously compounded flat rate.

		Returns integer cents.
		"""
		from pgappforge.plugins.erp.industry.financial_contracts.models import (
			FinancialContract, CashFlowSchedule,
		)

		contract = session.get(FinancialContract, contract_id)
		if contract is None:
			raise ContractNotFoundError(f"FinancialContract {contract_id!r} not found")

		rate = Decimal(str(discount_rate))
		dcc = str(contract.day_count_convention)

		flows = session.execute(
			select(CashFlowSchedule)
			.where(
				CashFlowSchedule.contract_id == contract_id,
				CashFlowSchedule.schedule_date >= as_of_date,
				CashFlowSchedule.status.in_(["SCHEDULED"]),
			)
			.order_by(CashFlowSchedule.schedule_date)
		).scalars().all()

		npv = Decimal(0)
		for flow in flows:
			yf = _year_fraction(as_of_date, flow.schedule_date, dcc)
			df = _discount_factor(rate, yf)
			npv += Decimal(flow.scheduled_amount_cents) * df

		return int(npv.quantize(Decimal("1"), rounding=ROUND_HALF_UP))

	# ------------------------------------------------------------------
	# Mark-to-market
	# ------------------------------------------------------------------

	def mark_to_market(
		self,
		contract_id: str,
		market_data: dict,
		session: Any,
		tenant_id: str = "",
	):
		"""Value a contract against current market data and persist snapshot.

		market_data keys:
		  discount_rate (Decimal | float): flat discount rate
		  as_of_date    (date | str):      valuation date
		  risk_factors  (dict):            {factor_code: value}

		Returns a new (unsaved) ContractValuation.
		Caller must session.add() and commit.
		"""
		from pgappforge.plugins.erp.industry.financial_contracts.models import (
			FinancialContract, ContractValuation,
		)
		from pgappforge.plugins.erp.industry.financial_contracts.events import (
			ContractValuedEvent, emit_event,
		)

		contract = session.get(FinancialContract, contract_id)
		if contract is None:
			raise ContractNotFoundError(f"FinancialContract {contract_id!r} not found")

		raw_date = market_data.get("as_of_date", date.today())
		as_of = (
			raw_date
			if isinstance(raw_date, date)
			else date.fromisoformat(str(raw_date))
		)
		discount_rate = Decimal(str(market_data.get("discount_rate", "0.05")))
		risk_factors = market_data.get("risk_factors", {})
		tid = tenant_id or str(contract.tenant_id)

		npv_cents = self.calculate_npv(contract_id, discount_rate, as_of, session)

		# Duration: weighted average time of cash flows
		duration_years = self._calculate_duration(
			contract_id, discount_rate, as_of, session
		)
		convexity = self._calculate_convexity(
			contract_id, discount_rate, as_of, session
		)

		val = ContractValuation(
			tenant_id=tid,
			contract_id=contract_id,
			valuation_date=as_of,
			valuation_method="MARKET",
			npv_cents=npv_cents,
			duration_years=duration_years,
			convexity=convexity,
			risk_factors_used={
				"discount_rate": str(discount_rate),
				**{str(k): str(v) for k, v in risk_factors.items()},
			},
			model_parameters={"flat_rate_model": True, "dcc": str(contract.day_count_convention)},
		)

		emit_event(
			"financial_contracts.contract.valued",
			"FinancialContract",
			contract_id,
			{
				"contract_id": contract_id,
				"valuation_date": as_of.isoformat(),
				"valuation_method": "MARKET",
				"npv_cents": npv_cents,
			},
			session,
			tenant_id=tid,
		)

		log.info(
			"mark_to_market: contract=%r date=%s npv=%d cents",
			contract_id, as_of, npv_cents,
		)
		return val

	# ------------------------------------------------------------------
	# Stress testing
	# ------------------------------------------------------------------

	def stress_test(
		self,
		contract_id: str,
		scenarios: list[dict],
		session: Any,
	) -> list[dict]:
		"""Run NPV stress tests under multiple market scenarios.

		Each scenario dict:
		  name          (str):   scenario label
		  discount_rate (float): rate to use
		  as_of_date    (date):  optional, defaults to today

		Returns list of dicts:
		  {scenario_name, discount_rate, as_of_date, npv_cents, npv_delta_cents}

		Base NPV computed at first scenario's rate (or 0.05 if none given).
		"""
		from pgappforge.plugins.erp.industry.financial_contracts.models import (
			FinancialContract,
		)

		contract = session.get(FinancialContract, contract_id)
		if contract is None:
			raise ContractNotFoundError(f"FinancialContract {contract_id!r} not found")

		today = date.today()
		results: list[dict] = []
		base_npv: int | None = None

		for scenario in scenarios:
			name = str(scenario.get("name", "unnamed"))
			rate = Decimal(str(scenario.get("discount_rate", "0.05")))
			raw_date = scenario.get("as_of_date", today)
			as_of = (
				raw_date
				if isinstance(raw_date, date)
				else date.fromisoformat(str(raw_date))
			)

			npv = self.calculate_npv(contract_id, rate, as_of, session)
			if base_npv is None:
				base_npv = npv
			delta = npv - (base_npv or 0)

			results.append({
				"scenario_name": name,
				"discount_rate": float(rate),
				"as_of_date": as_of.isoformat(),
				"npv_cents": npv,
				"npv_delta_cents": delta,
			})

		log.info(
			"stress_test: contract=%r scenarios=%d base_npv=%d",
			contract_id, len(scenarios), base_npv or 0,
		)
		return results

	# ------------------------------------------------------------------
	# Portfolio maturity profile
	# ------------------------------------------------------------------

	def calculate_maturity_profile(
		self,
		portfolio: list[str],
		session: Any,
	) -> dict:
		"""Aggregate scheduled cash flows by period bucket for a portfolio.

		portfolio: list of FinancialContract.id strings.

		Returns dict:
		  {
		    "buckets": {
		      "0_1Y": {"inflows_cents": int, "outflows_cents": int, "net_cents": int},
		      "1_3Y": {...},
		      "3_5Y": {...},
		      "5_10Y": {...},
		      "10Y_plus": {...},
		    },
		    "total_scheduled_cents": int,
		    "contract_count": int,
		  }
		"""
		from pgappforge.plugins.erp.industry.financial_contracts.models import (
			CashFlowSchedule,
		)

		today = date.today()
		buckets: dict[str, dict[str, int]] = {
			"0_1Y":    {"inflows_cents": 0, "outflows_cents": 0, "net_cents": 0},
			"1_3Y":    {"inflows_cents": 0, "outflows_cents": 0, "net_cents": 0},
			"3_5Y":    {"inflows_cents": 0, "outflows_cents": 0, "net_cents": 0},
			"5_10Y":   {"inflows_cents": 0, "outflows_cents": 0, "net_cents": 0},
			"10Y_plus":{"inflows_cents": 0, "outflows_cents": 0, "net_cents": 0},
		}

		if not portfolio:
			return {"buckets": buckets, "total_scheduled_cents": 0, "contract_count": 0}

		flows = session.execute(
			select(CashFlowSchedule)
			.where(
				CashFlowSchedule.contract_id.in_(portfolio),
				CashFlowSchedule.status == "SCHEDULED",
				CashFlowSchedule.schedule_date >= today,
			)
		).scalars().all()

		total = 0
		for flow in flows:
			days = (flow.schedule_date - today).days
			if days < 365:
				key = "0_1Y"
			elif days < 3 * 365:
				key = "1_3Y"
			elif days < 5 * 365:
				key = "3_5Y"
			elif days < 10 * 365:
				key = "5_10Y"
			else:
				key = "10Y_plus"

			amt = int(flow.scheduled_amount_cents)
			total += abs(amt)
			if amt >= 0:
				buckets[key]["inflows_cents"] += amt
			else:
				buckets[key]["outflows_cents"] += abs(amt)
			buckets[key]["net_cents"] += amt

		return {
			"buckets": buckets,
			"total_scheduled_cents": total,
			"contract_count": len(portfolio),
		}

	# ------------------------------------------------------------------
	# Schedule report
	# ------------------------------------------------------------------

	def generate_schedule_report(
		self,
		contract_id: str,
		session: Any,
	) -> dict:
		"""Generate a complete schedule report for a single contract.

		Returns:
		  contract metadata, sorted cash flow table,
		  totals (scheduled_inflows, scheduled_outflows, net),
		  settlement summary (settled_count, missed_count, pending_count).
		"""
		from pgappforge.plugins.erp.industry.financial_contracts.models import (
			FinancialContract, CashFlowSchedule,
		)

		contract = session.get(FinancialContract, contract_id)
		if contract is None:
			raise ContractNotFoundError(f"FinancialContract {contract_id!r} not found")

		flows = session.execute(
			select(CashFlowSchedule)
			.where(CashFlowSchedule.contract_id == contract_id)
			.order_by(CashFlowSchedule.schedule_date)
		).scalars().all()

		rows: list[dict] = []
		total_inflows = 0
		total_outflows = 0
		settled_count = 0
		missed_count = 0
		pending_count = 0

		for f in flows:
			amt = int(f.scheduled_amount_cents)
			if amt >= 0:
				total_inflows += amt
			else:
				total_outflows += abs(amt)

			if str(f.status) == "SETTLED":
				settled_count += 1
			elif str(f.status) == "MISSED":
				missed_count += 1
			else:
				pending_count += 1

			rows.append({
				"id": str(f.id),
				"schedule_date": f.schedule_date.isoformat(),
				"event_type": f.event_type,
				"scheduled_amount_cents": amt,
				"currency_code": f.currency_code,
				"actual_amount_cents": f.actual_amount_cents,
				"actual_date": f.actual_date.isoformat() if f.actual_date else None,
				"status": f.status,
			})

		return {
			"contract_id": contract_id,
			"actus_contract_id": contract.contract_id,
			"contract_type": contract.contract_type,
			"contract_role": contract.contract_role,
			"currency_code": contract.currency_code,
			"notional_principal_cents": contract.notional_principal_cents,
			"initial_exchange_date": contract.initial_exchange_date.isoformat(),
			"maturity_date": contract.maturity_date.isoformat(),
			"status": contract.status,
			"cash_flows": rows,
			"totals": {
				"flow_count": len(rows),
				"scheduled_inflows_cents": total_inflows,
				"scheduled_outflows_cents": total_outflows,
				"net_cents": total_inflows - total_outflows,
			},
			"settlement_summary": {
				"settled_count": settled_count,
				"missed_count": missed_count,
				"pending_count": pending_count,
			},
		}

	# ------------------------------------------------------------------
	# Internal helpers
	# ------------------------------------------------------------------

	def _calculate_duration(
		self,
		contract_id: str,
		discount_rate: Decimal,
		as_of_date: date,
		session: Any,
	) -> Decimal | None:
		"""Macaulay duration in years."""
		from pgappforge.plugins.erp.industry.financial_contracts.models import (
			FinancialContract, CashFlowSchedule,
		)

		contract = session.get(FinancialContract, contract_id)
		if contract is None:
			return None

		dcc = str(contract.day_count_convention)
		flows = session.execute(
			select(CashFlowSchedule)
			.where(
				CashFlowSchedule.contract_id == contract_id,
				CashFlowSchedule.schedule_date >= as_of_date,
				CashFlowSchedule.status == "SCHEDULED",
			)
		).scalars().all()

		if not flows:
			return None

		pv_total = Decimal(0)
		weighted_time = Decimal(0)
		for f in flows:
			yf = _year_fraction(as_of_date, f.schedule_date, dcc)
			df = _discount_factor(discount_rate, yf)
			pv = Decimal(f.scheduled_amount_cents) * df
			pv_total += pv
			weighted_time += pv * yf

		if pv_total == 0:
			return Decimal(0)

		return (weighted_time / pv_total).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)

	def _calculate_convexity(
		self,
		contract_id: str,
		discount_rate: Decimal,
		as_of_date: date,
		session: Any,
	) -> Decimal | None:
		"""Dollar convexity (second derivative of price w.r.t. yield)."""
		from pgappforge.plugins.erp.industry.financial_contracts.models import (
			FinancialContract, CashFlowSchedule,
		)

		contract = session.get(FinancialContract, contract_id)
		if contract is None:
			return None

		dcc = str(contract.day_count_convention)
		flows = session.execute(
			select(CashFlowSchedule)
			.where(
				CashFlowSchedule.contract_id == contract_id,
				CashFlowSchedule.schedule_date >= as_of_date,
				CashFlowSchedule.status == "SCHEDULED",
			)
		).scalars().all()

		if not flows:
			return None

		pv_total = Decimal(0)
		convexity_sum = Decimal(0)
		for f in flows:
			yf = _year_fraction(as_of_date, f.schedule_date, dcc)
			df = _discount_factor(discount_rate, yf)
			pv = Decimal(f.scheduled_amount_cents) * df
			pv_total += pv
			convexity_sum += pv * yf * (yf + Decimal(1)) / ((Decimal(1) + discount_rate) ** 2)

		if pv_total == 0:
			return Decimal(0)

		return (convexity_sum / pv_total).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _add_months(d: date, months: int) -> date:
	"""Advance date by a number of calendar months (end-of-month safe)."""
	month = d.month - 1 + months
	year = d.year + month // 12
	month = month % 12 + 1
	import calendar
	max_day = calendar.monthrange(year, month)[1]
	return d.replace(year=year, month=month, day=min(d.day, max_day))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"FinancialContractsService",
	"FinancialContractsError",
	"ContractNotFoundError",
	"InvalidContractTypeError",
	"CashFlowGenerationError",
]
