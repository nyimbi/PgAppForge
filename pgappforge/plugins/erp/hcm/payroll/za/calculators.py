"""
pgappforge/plugins/erp/hcm/payroll/za/calculators.py

South Africa statutory payroll — FY 2024/25 (March 2024 – February 2025)

All amounts in integer cents (ZAR × 100).
Never uses float or Decimal storage — intermediate arithmetic uses Decimal,
results rounded ROUND_HALF_UP to int before returning.

PAYE bands (annual, ZAR cents) — SARS Budget 2024:
  0            –  23_760_000: 18%
  23_760_001   –  37_062_000: 4_276_800  + 26% on excess over 237,600
  37_062_001   –  51_234_000: 7_721_532  + 31% on excess over 370,620
  51_234_001   –  66_882_000: 12_117_000 + 36% on excess over 512,340
  66_882_001   –  86_478_000: 17_748_000 + 39% on excess over 668,820
  86_478_001   – 181_866_000: 25_375_500 + 41% on excess over 864,780
  > 181_866_000:              64_567_500 + 45% on excess over 1,818,660

Rebates (applied against gross annual tax):
  Primary (all taxpayers):            R17,235/year  = 1_723_500 cents
  Secondary (age >= 65):              R9,444/year   =   944_400 cents
  Tertiary (age >= 75):               R3,145/year   =   314_500 cents
  Tax threshold (primary rebate only): R95,750/year = 9_575_000 cents

UIF (Unemployment Insurance Fund — UIA 2001):
  Employee: 1% of remuneration (capped R17,712/month = 1_771_200 cents/month)
  Employer: 1% of remuneration (same monthly cap)

SDL (Skills Development Levy — SDLA 1999):
  Employer only: 1% of gross monthly remuneration
  (Exempt if total annual payroll < R500,000 — exemption applied upstream)

Sources:
  SARS: https://www.sars.gov.za
  Taxation Laws Amendment Act 2023
  UIF: https://www.labour.gov.za
  SETA/DHET SDL: https://www.dhet.gov.za

EFFECTIVE_FROM: str = "2024-03-01"
"""
from __future__ import annotations

import logging
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

log = logging.getLogger(__name__)

EFFECTIVE_FROM: str = "2024-03-01"

# ---------------------------------------------------------------------------
# Monetary helpers
# ---------------------------------------------------------------------------

def _rc(d: Decimal) -> int:
	"""Round Decimal → int cents, ROUND_HALF_UP."""
	return int(d.to_integral_value(rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# PAYE constants (annual, ZAR cents)
# Each band: (lower_bound, upper_bound, cumulative_tax_at_lower, marginal_rate)
# ---------------------------------------------------------------------------

_PAYE_BANDS: list[tuple[int, int, int, Decimal]] = [
	# (lower_bound, upper_bound, cumulative_tax_at_lower, marginal_rate)
	(0,             23_760_000,   0,          Decimal("0.18")),
	(23_760_001,    37_062_000,   4_276_800,  Decimal("0.26")),
	(37_062_001,    51_234_000,   7_721_532,  Decimal("0.31")),
	(51_234_001,    66_882_000,   12_117_000, Decimal("0.36")),
	(66_882_001,    86_478_000,   17_748_000, Decimal("0.39")),
	(86_478_001,   181_866_000,   25_375_500, Decimal("0.41")),
	(181_866_001,  2**62,         64_567_500, Decimal("0.45")),
]

# Rebates
_PRIMARY_REBATE: int   = 1_723_500   # R17,235/year
_SECONDARY_REBATE: int =   944_400   # R9,444/year (age >= 65)
_TERTIARY_REBATE: int  =   314_500   # R3,145/year (age >= 75)

# UIF
_UIF_RATE: Decimal = Decimal("0.01")
_UIF_CAP_MONTHLY: int = 1_771_200   # R17,712/month per side

# SDL
_SDL_RATE: Decimal = Decimal("0.01")


# ---------------------------------------------------------------------------
# SAPAYECalculator
# ---------------------------------------------------------------------------

class SAPAYECalculator:
	"""SARS PAYE engine — FY 2024/25 (March 2024 – February 2025).

	Uses cumulative band table (SARS sliding-scale approach):
	  tax = cumulative_at_lower + (income - lower) * marginal_rate

	Rebates reduce the gross tax; minimum final tax is 0.

	Usage::

	    calc = SAPAYECalculator()
	    monthly_paye = calc.compute_monthly(
	        monthly_gross_cents=10_000_000,
	        age=45,
	    )
	"""

	def compute_annual_tax_before_rebate(self, annual_taxable_cents: int) -> int:
		"""Apply SARS sliding-scale bands to annual taxable income.

		Args:
			annual_taxable_cents: Annual taxable income in ZAR cents.

		Returns:
			Gross annual tax before rebates in ZAR cents.
		"""
		assert annual_taxable_cents >= 0, "annual_taxable_cents must be non-negative"

		for lower, upper, cumulative, rate in _PAYE_BANDS:
			if annual_taxable_cents <= upper:
				excess = annual_taxable_cents - lower
				tax = Decimal(cumulative) + Decimal(excess) * rate
				return _rc(tax)

		# Unreachable (last band upper is 2**62) but satisfies type checker
		lower, upper, cumulative, rate = _PAYE_BANDS[-1]
		excess = annual_taxable_cents - lower
		return _rc(Decimal(cumulative) + Decimal(excess) * rate)

	def compute_annual_paye(
		self,
		annual_taxable_income_cents: int,
		age: int | None = None,
	) -> int:
		"""Annual PAYE after rebates. Minimum is 0.

		Args:
			annual_taxable_income_cents: Annual gross taxable income in ZAR cents.
			age: Employee age for secondary/tertiary rebate eligibility.

		Returns:
			Annual PAYE payable in ZAR cents (>= 0).
		"""
		gross_tax = self.compute_annual_tax_before_rebate(annual_taxable_income_cents)
		rebate = _PRIMARY_REBATE
		if age is not None and age >= 65:
			rebate += _SECONDARY_REBATE
		if age is not None and age >= 75:
			rebate += _TERTIARY_REBATE
		return max(0, gross_tax - rebate)

	def compute_monthly(
		self,
		monthly_gross_cents: int,
		age: int | None = None,
		pay_frequency_months: int = 1,
	) -> int:
		"""Monthly PAYE by annualising the monthly income.

		Args:
			monthly_gross_cents: Monthly gross remuneration in ZAR cents.
			age: Employee age for rebate tier selection.
			pay_frequency_months: Number of months this period covers (1 = monthly).

		Returns:
			PAYE for this pay period in ZAR cents.
		"""
		periods = 12 // pay_frequency_months
		annual = monthly_gross_cents * periods
		annual_paye = self.compute_annual_paye(annual, age=age)
		return _rc(Decimal(annual_paye) / periods)


# ---------------------------------------------------------------------------
# SAUIFCalculator
# ---------------------------------------------------------------------------

class SAUIFCalculator:
	"""UIF (Unemployment Insurance Fund) — Unemployment Insurance Act 2001.

	Employee: 1% of remuneration (capped R17,712/month = 1_771_200 cents).
	Employer: 1% of remuneration (same cap).

	Returns dict: {employee_cents, employer_cents}
	"""

	def compute(self, gross_cents: int) -> dict[str, int]:
		"""Compute monthly UIF contributions.

		Args:
			gross_cents: Gross monthly remuneration in ZAR cents.

		Returns:
			Dict with employee_cents and employer_cents (both capped).
		"""
		assert gross_cents >= 0, "gross_cents must be non-negative"
		capped = min(gross_cents, _UIF_CAP_MONTHLY)
		each = _rc(Decimal(capped) * _UIF_RATE)
		return {"employee_cents": each, "employer_cents": each}


# ---------------------------------------------------------------------------
# SASDLCalculator
# ---------------------------------------------------------------------------

class SASDLCalculator:
	"""Skills Development Levy (SDL) — Skills Development Levies Act 1999.

	Employer only: 1% of gross monthly remuneration.
	Exemption: employers with total annual payroll < R500,000 are SDL-exempt.
	          Pass is_exempt=True to suppress the levy.

	Returns:
		Employer SDL in ZAR cents.
	"""

	def compute(self, gross_cents: int, is_exempt: bool = False) -> int:
		"""Compute monthly SDL employer levy.

		Args:
			gross_cents: Gross monthly pay in ZAR cents.
			is_exempt: True if employer is below R500,000 annual payroll threshold.

		Returns:
			SDL levy in ZAR cents (0 if exempt).
		"""
		assert gross_cents >= 0, "gross_cents must be non-negative"
		if is_exempt:
			return 0
		return _rc(Decimal(gross_cents) * _SDL_RATE)


# ---------------------------------------------------------------------------
# SATaxCalculator — composite, satisfies tax_calculator protocol
# ---------------------------------------------------------------------------

class SATaxCalculator:
	"""Composite South Africa statutory calculator for injection into PayrollService.

	Implements the tax_calculator protocol expected by PayrollService.calculate_payrun():
	  .compute(gross_cents, employee_id, session, *, age=None) -> dict

	Returned dict keys:
	  income_tax_cents        — PAYE (after rebates)
	  ni_employee_cents       — UIF employee (proxy for NI)
	  pension_employee_cents  — 0 (no statutory pension here; RA/provident fund upstream)
	  pension_employer_cents  — 0
	  uif_employee_cents      — UIF employee contribution (1%, capped)
	  uif_employer_cents      — UIF employer contribution (1%, capped)
	  sdl_cents               — SDL employer levy (1%)
	"""

	def __init__(
		self,
		paye: SAPAYECalculator | None = None,
		uif: SAUIFCalculator | None = None,
		sdl: SASDLCalculator | None = None,
	) -> None:
		self._paye = paye or SAPAYECalculator()
		self._uif = uif or SAUIFCalculator()
		self._sdl = sdl or SASDLCalculator()

	def compute(
		self,
		gross_cents: int,
		employee_id: str,
		session: Any,
		*,
		age: int | None = None,
		sdl_exempt: bool = False,
	) -> dict[str, int]:
		"""Compute all South Africa statutory deductions for one employee for one month.

		Args:
			gross_cents: Total gross monthly remuneration in ZAR cents.
			employee_id: Employee UUID (for audit/logging).
			session: SQLAlchemy session (unused here; kept for protocol compat).
			age: Employee age for PAYE rebate tier (Primary/Secondary/Tertiary).
			sdl_exempt: True if employer is exempt from SDL (payroll < R500,000/year).

		Returns:
			Dict with all statutory deduction amounts.
		"""
		assert gross_cents >= 0, "gross_cents must be non-negative"

		paye = self._paye.compute_monthly(gross_cents, age=age)
		uif_result = self._uif.compute(gross_cents)
		sdl = self._sdl.compute(gross_cents, is_exempt=sdl_exempt)

		log.debug(
			"SATaxCalculator.compute: emp=%s gross=%d paye=%d uif_emp=%d sdl=%d",
			employee_id, gross_cents, paye,
			uif_result["employee_cents"], sdl,
		)

		return {
			"income_tax_cents": paye,
			"ni_employee_cents": uif_result["employee_cents"],
			"pension_employee_cents": 0,
			"pension_employer_cents": 0,
			"uif_employee_cents": uif_result["employee_cents"],
			"uif_employer_cents": uif_result["employer_cents"],
			"sdl_cents": sdl,
		}


__all__ = [
	"SAPAYECalculator",
	"SAUIFCalculator",
	"SASDLCalculator",
	"SATaxCalculator",
]
