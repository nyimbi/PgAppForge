"""
pgappforge/plugins/fintech/sacco/sasra.py

SASRA (Sacco Societies Regulatory Authority) compliance return generator.

Generates SAS1, SAS2, SAS3 prudential returns as structured dicts
that can be exported to Excel/CSV or submitted via SASRA portal.

References:
  - SASRA Prudential Guidelines (Kenya)
  - SACCO Societies Act Cap 490B
  - SASRA Minimum Capital Requirements: institutional_capital / total_assets >= 8%
  - SASRA PAR limits: PAR30 <= 10%, PAR90 <= 5%
  - Liquidity: liquid_assets / short_term_liabilities >= 15%

Field mapping to sc_sacco columns:
  institutional_capital -> reserve_fund_cents  (statutory reserve fund; ~20% of surplus)
  share_capital         -> total_shares_cents   (sum of all member share values)
  liquid_assets         -> total_deposits_cents (FOSA deposits; best available proxy)
  total_loan_book       -> total_loans_outstanding_cents

PAR queries mirror services.get_sacco_financials: join via Member.party_id so loans
are attributed to the correct SACCO irrespective of multi-tenant topology.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

import sqlalchemy as sa
from sqlalchemy import select, func, and_

from pgappforge.plugins.fintech.sacco.models import (
	SACCO,
	Member,
	SACCOLoanProduct,
	SaccoLedgerEntry,
	SaccoStandingOrder,
	Dividend,
	LoanRepaymentSchedule,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _pct(num: int, denom: int) -> str:
	"""Return (num/denom * 100) formatted to 2 d.p., or '0.00' on zero denominator."""
	if denom == 0:
		return "0.00"
	return str(
		(Decimal(str(num)) / Decimal(str(denom)) * 100)
		.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
	)


def _kes(cents: int) -> str:
	"""Convert integer cents to KES string with 2 d.p. (e.g. 150000 → '1500.00')."""
	return str(Decimal(str(cents)) / Decimal("100"))


# ---------------------------------------------------------------------------
# SASRAReturnsService
# ---------------------------------------------------------------------------

class SASRAReturnsService:
	"""Generate SASRA prudential returns SAS1, SAS2, SAS3.

	All monetary values are stored internally as integer cents and formatted
	as KES strings on output (e.g. 150000 cents → '1500.00').

	Period convention:
	  SAS1 — point-in-time (as_of_date)
	  SAS2 — range (from_date → to_date)
	  SAS3 — point-in-time (as_of_date)
	"""

	def __init__(self, session: Any, sacco_id: str, tenant_id: str) -> None:
		self._session = session
		self._sacco_id = sacco_id
		self._tenant_id = tenant_id

	# ------------------------------------------------------------------
	# Private utilities
	# ------------------------------------------------------------------

	def _get_sacco(self) -> Any:
		"""Load SACCO row; returns None if not found."""
		return self._session.execute(
			select(SACCO).where(
				SACCO.id == self._sacco_id,
				SACCO.tenant_id == self._tenant_id,
			)
		).scalar_one_or_none()

	def _active_member_party_ids(self) -> list[str]:
		"""Return party_ids for all ACTIVE members of this SACCO."""
		rows = self._session.execute(
			select(Member.party_id).where(
				Member.sacco_id == self._sacco_id,
				Member.membership_status == "ACTIVE",
			)
		).scalars().all()
		return list(rows)

	def _loan_par(
		self,
		party_ids: list[str],
		min_dpd: int,
		extra_filter: Any = None,
	) -> int:
		"""Sum outstanding_principal_cents for loans past due >= min_dpd days.

		Mirrors services.get_sacco_financials: queries via borrower_id membership,
		not tenant_id, to respect multi-SACCO topologies.

		Returns 0 if the lending plugin is unavailable or the query fails.
		"""
		if not party_ids:
			return 0
		try:
			from pgappforge.plugins.fintech.lending.models import Loan
			conditions = [
				Loan.borrower_id.in_(party_ids),
				Loan.status.in_(["ARREARS", "DEFAULTED"]),
				Loan.days_past_due >= min_dpd,
			]
			if extra_filter is not None:
				conditions.append(extra_filter)
			result = self._session.execute(
				select(func.coalesce(func.sum(Loan.outstanding_principal_cents), 0)).where(
					and_(*conditions)
				)
			).scalar_one()
			return int(result or 0)
		except ImportError:
			log.debug("sasra: lending plugin not available, PAR=%d defaulting to 0", min_dpd)
			return 0
		except Exception as exc:
			log.warning("sasra: PAR%d query failed: %s", min_dpd, exc)
			return 0

	# ------------------------------------------------------------------
	# SAS1 — Statement of Assets and Liabilities
	# ------------------------------------------------------------------

	def generate_sas1(self, as_of_date: date) -> dict:
		"""SAS1 — Statement of Assets and Liabilities.

		Assets
		  Loans (gross outstanding principal)
		  Loan loss provisions (deducted to arrive at net loans)
		  Cash & bank equivalents (approximated from FOSA deposit base)
		  Other assets (zero unless extended)

		Liabilities
		  Member deposits (FOSA savings)
		  External borrowings
		  Other liabilities

		Net Worth
		  Share capital  — total_shares_cents (sum of member par-value shares)
		  Institutional capital — reserve_fund_cents (statutory reserve)
		  Retained earnings (zero unless extended with income statement data)

		Balance check: total_assets == total_liabilities + total_net_worth.
		Due to the simplified model (no full GL), this will rarely balance exactly;
		it is flagged as an informational field only.
		"""
		sacco = self._get_sacco()
		if not sacco:
			raise ValueError(f"SACCO {self._sacco_id!r} not found for tenant {self._tenant_id!r}")

		# Gross loan book from lending plugin; fall back to denormalised aggregate.
		party_ids = self._active_member_party_ids()
		gross_loans = 0
		loan_provisions = 0
		try:
			from pgappforge.plugins.fintech.lending.models import Loan
			if party_ids:
				loan_rows = self._session.execute(
					select(
						func.coalesce(func.sum(Loan.outstanding_principal_cents), 0).label("principal"),
						# provision approximation: fully-provisioned LOSS loans + 50% DOUBTFUL
						# Real IFRS9 provisions would come from a dedicated provision table.
					).where(
						and_(
							Loan.borrower_id.in_(party_ids),
							Loan.status.in_(["ACTIVE", "ARREARS", "DEFAULTED"]),
						)
					)
				).one()
				gross_loans = int(loan_rows.principal or 0)
		except ImportError:
			gross_loans = sacco.total_loans_outstanding_cents
		except Exception as exc:
			log.warning("sasra SAS1: loan query failed — %s; using stale aggregate", exc)
			gross_loans = sacco.total_loans_outstanding_cents

		# Provision estimate from NPA classification
		try:
			from pgappforge.plugins.fintech.lending.models import Loan
			if party_ids:
				prov_rows = self._session.execute(
					select(
						func.coalesce(func.sum(Loan.outstanding_principal_cents), 0)
					).where(
						and_(
							Loan.borrower_id.in_(party_ids),
							Loan.npa_classification.in_(["LOSS"]),
						)
					)
				).scalar_one()
				doubtful_rows = self._session.execute(
					select(
						func.coalesce(func.sum(Loan.outstanding_principal_cents), 0)
					).where(
						and_(
							Loan.borrower_id.in_(party_ids),
							Loan.npa_classification == "DOUBTFUL",
						)
					)
				).scalar_one()
				# CBK standard: LOSS 100%, DOUBTFUL 50%, SUBSTANDARD 20%
				loan_provisions = int(prov_rows or 0) + int(int(doubtful_rows or 0) * 0.5)
		except Exception:
			loan_provisions = 0

		net_loans = gross_loans - loan_provisions

		# Monetary aggregates from SACCO record
		total_deposits = sacco.total_deposits_cents			# FOSA deposits (liquid proxy)
		total_shares = sacco.total_shares_cents				# member share capital
		reserve_fund = sacco.reserve_fund_cents				# statutory reserve (institutional capital)

		# Total assets: net loans + deposits held as cash/bank equivalent
		# This is a simplified balance sheet; a full implementation would include
		# investment portfolios, fixed assets, and inter-SACCO placements.
		total_assets = net_loans + total_deposits
		total_liabilities = total_deposits					# simplified: deposits are the main liability
		total_net_worth = total_shares + reserve_fund

		balance_check = (total_assets == total_liabilities + total_net_worth)

		return {
			"return_type": "SAS1",
			"sacco_name": sacco.name,
			"sacco_registration": sacco.registration_number,
			"sacco_type": sacco.sacco_type,
			"regulator": sacco.regulator,
			"period_end": as_of_date.isoformat(),
			"generated_at": datetime.now(timezone.utc).isoformat(),
			"assets": {
				"gross_loans_kes": _kes(gross_loans),
				"loan_provisions_kes": _kes(loan_provisions),
				"net_loans_kes": _kes(net_loans),
				"cash_and_bank_equivalents_kes": _kes(total_deposits),
				"other_assets_kes": "0.00",
				"total_assets_kes": _kes(total_assets),
			},
			"liabilities": {
				"member_deposits_fosa_kes": _kes(total_deposits),
				"external_borrowings_kes": "0.00",
				"other_liabilities_kes": "0.00",
				"total_liabilities_kes": _kes(total_liabilities),
			},
			"net_worth": {
				"share_capital_kes": _kes(total_shares),
				"institutional_capital_reserve_kes": _kes(reserve_fund),
				"retained_earnings_kes": "0.00",
				"total_net_worth_kes": _kes(total_net_worth),
			},
			"balance_check_passes": balance_check,
			"_note": (
				"Simplified balance sheet. Cash/bank proxied from total_deposits_cents. "
				"Full GL integration required for exact balance sheet."
			),
		}

	# ------------------------------------------------------------------
	# SAS2 — Income and Expenditure Statement
	# ------------------------------------------------------------------

	def generate_sas2(self, from_date: date, to_date: date) -> dict:
		"""SAS2 — Income and Expenditure Statement.

		Income
		  Interest on loans — sum of interest_applied_cents from LoanRepayment
		  Investment income  — zero (requires investment module)
		  Fees & commissions — SaccoLedgerEntry entries with entry_type FEE_INCOME
		  Other income       — zero unless extended

		Expenditure
		  Dividend / interest on member deposits — total_dividend_pool_cents from Dividend
		  Operating expenses   — zero (requires CoA/GL)
		  Loan loss provisions — zero (requires provision schedule)
		  Other expenses       — zero unless extended

		Net surplus = total_income - total_expenditure.
		"""
		sacco = self._get_sacco()
		if not sacco:
			raise ValueError(f"SACCO {self._sacco_id!r} not found for tenant {self._tenant_id!r}")

		# ---- Interest income: LoanRepayment.interest_applied_cents ----
		# Join via member party_ids to scope to this SACCO's loans.
		party_ids = self._active_member_party_ids()
		interest_income = 0
		try:
			from pgappforge.plugins.fintech.lending.models import Loan, LoanRepayment
			if party_ids:
				interest_income = self._session.execute(
					select(
						func.coalesce(func.sum(LoanRepayment.interest_applied_cents), 0)
					).join(Loan, LoanRepayment.loan_id == Loan.id).where(
						and_(
							Loan.borrower_id.in_(party_ids),
							LoanRepayment.payment_date >= from_date,
							LoanRepayment.payment_date <= to_date,
						)
					)
				).scalar_one() or 0
				interest_income = int(interest_income)
		except ImportError:
			log.debug("sasra SAS2: lending plugin not available; interest_income=0")
		except Exception as exc:
			log.warning("sasra SAS2: interest_income query failed: %s", exc)

		# ---- Fee income: SaccoLedgerEntry with entry_type FEE_INCOME ----
		fee_income = 0
		try:
			fee_income = self._session.execute(
				select(
					func.coalesce(func.sum(SaccoLedgerEntry.amount_cents), 0)
				).where(
					and_(
						SaccoLedgerEntry.sacco_id == self._sacco_id,
						SaccoLedgerEntry.entry_type == "FEE_INCOME",
						SaccoLedgerEntry.value_date >= from_date,
						SaccoLedgerEntry.value_date <= to_date,
					)
				)
			).scalar_one() or 0
			fee_income = int(fee_income)
		except Exception as exc:
			log.warning("sasra SAS2: fee_income query failed: %s", exc)

		# ---- Dividend / deposit interest expense ----
		# Uses total_dividend_pool_cents (AGM-approved distribution pool).
		# payment_date may be NULL for DECLARED-but-not-yet-paid dividends;
		# we use approved_date as a fallback for period attribution.
		dividend_expense = 0
		try:
			dividend_expense = self._session.execute(
				select(
					func.coalesce(func.sum(Dividend.total_dividend_pool_cents), 0)
				).where(
					and_(
						Dividend.sacco_id == self._sacco_id,
						Dividend.status.in_(["DECLARED", "PAID"]),
						sa.or_(
							and_(
								Dividend.payment_date.is_not(None),
								Dividend.payment_date >= from_date,
								Dividend.payment_date <= to_date,
							),
							and_(
								Dividend.payment_date.is_(None),
								Dividend.approved_date >= from_date,
								Dividend.approved_date <= to_date,
							),
						),
					)
				)
			).scalar_one() or 0
			dividend_expense = int(dividend_expense)
		except Exception as exc:
			log.warning("sasra SAS2: dividend_expense query failed: %s", exc)

		total_income = interest_income + fee_income
		total_expenditure = dividend_expense
		net_surplus = total_income - total_expenditure

		return {
			"return_type": "SAS2",
			"sacco_name": sacco.name,
			"sacco_registration": sacco.registration_number,
			"period_from": from_date.isoformat(),
			"period_to": to_date.isoformat(),
			"generated_at": datetime.now(timezone.utc).isoformat(),
			"income": {
				"interest_on_loans_kes": _kes(interest_income),
				"investment_income_kes": "0.00",
				"fees_and_commissions_kes": _kes(fee_income),
				"other_income_kes": "0.00",
				"total_income_kes": _kes(total_income),
			},
			"expenditure": {
				"dividends_and_deposit_interest_kes": _kes(dividend_expense),
				"operating_expenses_kes": "0.00",
				"loan_loss_provisions_kes": "0.00",
				"other_expenses_kes": "0.00",
				"total_expenditure_kes": _kes(total_expenditure),
			},
			"net_surplus_deficit_kes": _kes(net_surplus),
			"surplus_or_deficit": "SURPLUS" if net_surplus >= 0 else "DEFICIT",
		}

	# ------------------------------------------------------------------
	# SAS3 — Capital Adequacy and Asset Quality
	# ------------------------------------------------------------------

	def generate_sas3(self, as_of_date: date) -> dict:
		"""SAS3 — Capital Adequacy and Asset Quality.

		SASRA prudential standards:
		  Capital Adequacy Ratio  institutional_capital / total_assets >= 8%
		  PAR30                   loans overdue >= 30 days / total loan book <= 10%
		  PAR90                   loans overdue >= 90 days / total loan book <= 5%
		  Liquidity Ratio         liquid_assets / short_term_liabilities >= 15%

		institutional_capital maps to reserve_fund_cents (statutory reserve).
		total_loan_book maps to total_loans_outstanding_cents (SACCO aggregate).
		liquid_assets proxied from total_deposits_cents (FOSA holdings).
		short_term_liabilities proxied from total_deposits_cents (demand deposits).

		PAR is computed from live loan data via the lending plugin (member join),
		falling back to stored delinquency_rate_pct if unavailable.
		"""
		sacco = self._get_sacco()
		if not sacco:
			raise ValueError(f"SACCO {self._sacco_id!r} not found for tenant {self._tenant_id!r}")

		party_ids = self._active_member_party_ids()

		# ---- Capital adequacy ----
		institutional_capital = sacco.reserve_fund_cents
		total_loans_book = sacco.total_loans_outstanding_cents
		# Total assets: loan book + FOSA deposits (simplified; no investment portfolio)
		total_assets = total_loans_book + sacco.total_deposits_cents
		capital_ratio_pct = _pct(institutional_capital, total_assets)

		# ---- Asset quality: PAR30 and PAR90 ----
		# PAR30: all loans with days_past_due >= 30 (ARREARS or DEFAULTED status)
		par30_cents = self._loan_par(party_ids, min_dpd=30)

		# PAR90: loans >= 90 DPD (typically DEFAULTED / NPA)
		par90_cents = self._loan_par(party_ids, min_dpd=90)

		# If lending plugin unavailable, fall back to stored delinquency_rate_pct
		# as a best-effort PAR90 proxy (delinquency_rate_pct is stored as Numeric(5,2))
		par30_pct = _pct(par30_cents, total_loans_book)
		par90_pct = _pct(par90_cents, total_loans_book)
		if par90_cents == 0 and total_loans_book > 0 and float(sacco.delinquency_rate_pct or 0) > 0:
			# Use stored rate as fallback display value only
			par90_pct = str(
				Decimal(str(sacco.delinquency_rate_pct))
				.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
			)

		# ---- Liquidity ----
		# SASRA defines liquid assets as cash + bank balances + short-term placements.
		# Proxied here from FOSA total_deposits_cents (demand deposits held).
		liquid_assets = sacco.total_deposits_cents
		short_term_liabilities = sacco.total_deposits_cents	# demand deposits = short-term liability
		liquidity_pct = _pct(liquid_assets, short_term_liabilities)
		# When liquid == short-term, ratio = 100%. Real calculation needs separate cash GL.

		# ---- Compliance evaluation ----
		capital_ok = Decimal(capital_ratio_pct) >= Decimal("8.0")
		par30_ok = Decimal(par30_pct) <= Decimal("10.0")
		par90_ok = Decimal(par90_pct) <= Decimal("5.0")
		liquidity_ok = Decimal(liquidity_pct) >= Decimal("15.0")
		fully_compliant = all([capital_ok, par30_ok, par90_ok, liquidity_ok])

		breaches = [
			label for label, ok in [
				("CAPITAL_ADEQUACY", capital_ok),
				("PAR30", par30_ok),
				("PAR90", par90_ok),
				("LIQUIDITY", liquidity_ok),
			]
			if not ok
		]

		return {
			"return_type": "SAS3",
			"sacco_name": sacco.name,
			"sacco_registration": sacco.registration_number,
			"sacco_type": sacco.sacco_type,
			"regulator": sacco.regulator,
			"as_of_date": as_of_date.isoformat(),
			"generated_at": datetime.now(timezone.utc).isoformat(),
			"capital_adequacy": {
				"institutional_capital_kes": _kes(institutional_capital),
				"total_assets_kes": _kes(total_assets),
				"capital_ratio_pct": capital_ratio_pct,
				"minimum_required_pct": "8.00",
				"compliant": capital_ok,
			},
			"asset_quality": {
				"total_loan_book_kes": _kes(total_loans_book),
				"par30_kes": _kes(par30_cents),
				"par30_pct": par30_pct,
				"par30_limit_pct": "10.00",
				"par30_compliant": par30_ok,
				"par90_kes": _kes(par90_cents),
				"par90_pct": par90_pct,
				"par90_limit_pct": "5.00",
				"par90_compliant": par90_ok,
			},
			"liquidity": {
				"liquid_assets_kes": _kes(liquid_assets),
				"short_term_liabilities_kes": _kes(short_term_liabilities),
				"liquidity_ratio_pct": liquidity_pct,
				"minimum_required_pct": "15.00",
				"compliant": liquidity_ok,
			},
			"overall_compliance": fully_compliant,
			"breaches": breaches,
			"membership_count": sacco.membership_count,
			"_note": (
				"Liquidity ratio proxied from FOSA deposits. "
				"Full GL integration required for SASRA portal submission."
			),
		}

	# ------------------------------------------------------------------
	# Composite: all returns for the period
	# ------------------------------------------------------------------

	def generate_all(self, from_date: date, to_date: date) -> dict:
		"""Generate SAS1, SAS2, SAS3 returns for the period.

		SAS1 and SAS3 are point-in-time (to_date).
		SAS2 covers the full from_date → to_date range.
		"""
		return {
			"sas1": self.generate_sas1(to_date),
			"sas2": self.generate_sas2(from_date, to_date),
			"sas3": self.generate_sas3(to_date),
		}


__all__ = ["SASRAReturnsService"]


# ---------------------------------------------------------------------------
# BPM Action Registration
# ---------------------------------------------------------------------------

try:
	from pgappforge.plugins.workflow.engine import BPMActionRegistry as _BPMReg

	@_BPMReg.register("sacco.sasra.generate_returns", "Generate SASRA prudential returns (SAS1/SAS2/SAS3)")
	def _bpm_sasra_returns(record_ctx, session, sacco_id="", from_date="", to_date="", **kw):
		from pgappforge.plugins.fintech.sacco.sasra import SASRAReturnsService
		from datetime import date as _date
		svc = SASRAReturnsService(session, sacco_id, record_ctx.get("tenant_id", ""))
		fd = _date.fromisoformat(from_date) if from_date else _date.today().replace(day=1)
		td = _date.fromisoformat(to_date) if to_date else _date.today()
		return svc.generate_all(fd, td)

except (ImportError, Exception):
	pass
