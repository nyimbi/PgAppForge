"""
pgappforge/plugins/erp/hcm/payroll/ng/calculators.py

Nigeria statutory payroll — FY 2024/25

All amounts in integer cents (NGN × 100).
Never uses float or Decimal storage — intermediate arithmetic uses Decimal,
results rounded ROUND_HALF_UP to int before returning.

PAYE bands (annual, NGN cents) — Finance Act 2023:
  0            –  30_000_000: 7%
  30_000_001   –  60_000_000: 11%
  60_000_001   – 110_000_000: 15%
  110_000_001  – 160_000_000: 19%
  160_000_001  – 360_000_000: 21%
  > 360_000_000:              24%

Consolidated Relief Allowance (CRA):
  Higher of: NGN 200,000 (20_000_000 cents) OR 1% of gross income
  PLUS: 20% of gross income
  Taxable income = gross - CRA - pension employee - NHF

Pension (Contributory Pension Scheme Act 2014):
  Employee: 8% of (basic + housing + transport); gross used if bundled
  Employer: 10% of (basic + housing + transport)
  No cap for private sector.

NHF (National Housing Fund):
  Employee: 2.5% of basic salary (proxied as gross if bundled)
  Employer: None

NSITF (Nigeria Social Insurance Trust Fund):
  Employer only: 1% of gross (per-employee proxy)

Sources:
  FIRS: https://www.firs.gov.ng
  Finance Act 2023 (Federal Republic of Nigeria Official Gazette)
  National Pension Commission: https://www.pencom.gov.ng
  NHF Act Cap N45 LFN 2004

EFFECTIVE_FROM: str = "2024-01-01"
"""
from __future__ import annotations

import logging
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

log = logging.getLogger(__name__)

EFFECTIVE_FROM: str = "2024-01-01"

# ---------------------------------------------------------------------------
# Monetary helpers
# ---------------------------------------------------------------------------

def _rc(d: Decimal) -> int:
	"""Round Decimal → int cents, ROUND_HALF_UP."""
	return int(d.to_integral_value(rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# PAYE constants (annual, NGN cents)
# ---------------------------------------------------------------------------

_PAYE_BANDS: list[tuple[int, int, Decimal]] = [
	# (lower_bound_annual, upper_bound_annual, rate)
	(0,             30_000_000,  Decimal("0.07")),
	(30_000_001,    60_000_000,  Decimal("0.11")),
	(60_000_001,   110_000_000,  Decimal("0.15")),
	(110_000_001,  160_000_000,  Decimal("0.19")),
	(160_000_001,  360_000_000,  Decimal("0.21")),
	(360_000_001,  2**62,        Decimal("0.24")),
]

# Consolidated Relief Allowance
_CRA_FLAT: int = 20_000_000           # NGN 200,000/year = 20_000_000 cents
_CRA_FLAT_RATE: Decimal = Decimal("0.01")   # 1% of gross (take the higher)
_CRA_GROSS_RATE: Decimal = Decimal("0.20")  # 20% of gross always added

# Pension
_PENSION_EMPLOYEE_RATE: Decimal = Decimal("0.08")
_PENSION_EMPLOYER_RATE: Decimal = Decimal("0.10")

# NHF
_NHF_RATE: Decimal = Decimal("0.025")

# NSITF
_NSITF_RATE: Decimal = Decimal("0.01")


# ---------------------------------------------------------------------------
# NigeriaPAYECalculator
# ---------------------------------------------------------------------------

class NigeriaPAYECalculator:
	"""Federal Inland Revenue Service (FIRS) PAYE engine — Finance Act 2023.

	Taxable income = gross - Consolidated Relief Allowance - pension employee - NHF.
	CRA = max(NGN 200,000, 1% of gross) + 20% of gross.

	Usage::

	    calc = NigeriaPAYECalculator()
	    annual_paye = calc.compute_annual_paye(
	        annual_gross_cents=12_000_000_00,
	        annual_pension_employee_cents=96_000_00,
	        annual_nhf_cents=30_000_00,
	    )
	"""

	def _compute_cra(self, annual_gross_cents: int) -> int:
		"""Consolidated Relief Allowance: max(200,000, 1% gross) + 20% gross.

		Args:
			annual_gross_cents: Annual gross income in NGN cents.

		Returns:
			CRA in NGN cents.
		"""
		flat_component = max(
			_CRA_FLAT,
			_rc(Decimal(annual_gross_cents) * _CRA_FLAT_RATE),
		)
		gross_component = _rc(Decimal(annual_gross_cents) * _CRA_GROSS_RATE)
		return flat_component + gross_component

	def compute_annual_tax_before_cra(self, annual_taxable_cents: int) -> int:
		"""Apply progressive PAYE bands to annual taxable income.

		Args:
			annual_taxable_cents: Annual taxable income in NGN cents (after deductions).

		Returns:
			Gross annual tax in NGN cents.
		"""
		assert annual_taxable_cents >= 0, "annual_taxable_cents must be non-negative"
		tax = Decimal(0)
		remaining = annual_taxable_cents

		for lower, upper, rate in _PAYE_BANDS:
			if remaining <= 0:
				break
			band_width = upper - lower + 1
			taxable_in_band = min(remaining, band_width)
			tax += Decimal(taxable_in_band) * rate
			remaining -= taxable_in_band

		return _rc(tax)

	def compute_annual_paye(
		self,
		annual_gross_cents: int,
		annual_pension_employee_cents: int = 0,
		annual_nhf_cents: int = 0,
	) -> int:
		"""Annual PAYE after CRA and statutory deductions. Minimum is 0.

		Args:
			annual_gross_cents: Annual gross income in NGN cents.
			annual_pension_employee_cents: Annual employee pension contribution.
			annual_nhf_cents: Annual NHF employee contribution.

		Returns:
			Annual PAYE payable in NGN cents (>= 0).
		"""
		cra = self._compute_cra(annual_gross_cents)
		taxable = max(0, annual_gross_cents - cra - annual_pension_employee_cents - annual_nhf_cents)
		return max(0, self.compute_annual_tax_before_cra(taxable))

	def compute_monthly(
		self,
		monthly_gross_cents: int,
		monthly_pension_employee_cents: int = 0,
		monthly_nhf_cents: int = 0,
	) -> int:
		"""Monthly PAYE by annualising the monthly income.

		Args:
			monthly_gross_cents: Monthly gross income in NGN cents.
			monthly_pension_employee_cents: Monthly employee pension.
			monthly_nhf_cents: Monthly NHF employee contribution.

		Returns:
			PAYE for this pay period in NGN cents.
		"""
		annual_paye = self.compute_annual_paye(
			annual_gross_cents=monthly_gross_cents * 12,
			annual_pension_employee_cents=monthly_pension_employee_cents * 12,
			annual_nhf_cents=monthly_nhf_cents * 12,
		)
		return _rc(Decimal(annual_paye) / 12)


# ---------------------------------------------------------------------------
# NigeriaPensionCalculator
# ---------------------------------------------------------------------------

class NigeriaPensionCalculator:
	"""Contributory Pension Scheme (CPS) — Pension Reform Act 2014.

	Employee: 8% of gross (no cap, private sector).
	Employer: 10% of gross (no cap, private sector).

	Note: Strictly, the base should be basic + housing + transport allowances.
	      If salary is bundled/gross, gross is used as the base.

	Returns dict: {employee_cents, employer_cents}
	"""

	def compute(self, gross_cents: int) -> dict[str, int]:
		"""Compute monthly pension contributions.

		Args:
			gross_cents: Gross monthly pay in NGN cents (or basic+housing+transport).

		Returns:
			Dict with employee_cents and employer_cents.
		"""
		assert gross_cents >= 0, "gross_cents must be non-negative"
		employee = _rc(Decimal(gross_cents) * _PENSION_EMPLOYEE_RATE)
		employer = _rc(Decimal(gross_cents) * _PENSION_EMPLOYER_RATE)
		return {"employee_cents": employee, "employer_cents": employer}


# ---------------------------------------------------------------------------
# NigeriaHousingFundCalculator
# ---------------------------------------------------------------------------

class NigeriaHousingFundCalculator:
	"""National Housing Fund (NHF) — NHF Act Cap N45 LFN 2004.

	Employee: 2.5% of basic salary (proxied as gross if salary is bundled).
	Employer: None.

	Returns:
		Employee NHF contribution in NGN cents.
	"""

	def compute(self, basic_cents: int) -> int:
		"""Compute monthly NHF employee contribution.

		Args:
			basic_cents: Basic (or gross) monthly pay in NGN cents.

		Returns:
			NHF contribution in NGN cents.
		"""
		assert basic_cents >= 0, "basic_cents must be non-negative"
		return _rc(Decimal(basic_cents) * _NHF_RATE)


# ---------------------------------------------------------------------------
# NigeriaTaxCalculator — composite, satisfies tax_calculator protocol
# ---------------------------------------------------------------------------

class NigeriaTaxCalculator:
	"""Composite Nigeria statutory calculator for injection into PayrollService.

	Implements the tax_calculator protocol expected by PayrollService.calculate_payrun():
	  .compute(gross_cents, employee_id, session) -> dict

	Returned dict keys:
	  income_tax_cents        — PAYE (after CRA)
	  ni_employee_cents       — pension employee (proxy for NI)
	  pension_employee_cents  — CPS employee contribution (8%)
	  pension_employer_cents  — CPS employer contribution (10%)
	  nhf_cents               — NHF employee contribution (2.5%)
	"""

	def __init__(
		self,
		paye: NigeriaPAYECalculator | None = None,
		pension: NigeriaPensionCalculator | None = None,
		nhf: NigeriaHousingFundCalculator | None = None,
	) -> None:
		self._paye = paye or NigeriaPAYECalculator()
		self._pension = pension or NigeriaPensionCalculator()
		self._nhf = nhf or NigeriaHousingFundCalculator()

	def compute(
		self,
		gross_cents: int,
		employee_id: str,
		session: Any,
	) -> dict[str, int]:
		"""Compute all Nigeria statutory deductions for one employee for one month.

		Args:
			gross_cents: Total gross monthly pay in NGN cents.
			employee_id: Employee UUID (for audit/logging).
			session: SQLAlchemy session (unused here; kept for protocol compat).

		Returns:
			Dict with all statutory deduction amounts.
		"""
		assert gross_cents >= 0, "gross_cents must be non-negative"

		pension_result = self._pension.compute(gross_cents)
		nhf = self._nhf.compute(gross_cents)
		paye = self._paye.compute_monthly(
			monthly_gross_cents=gross_cents,
			monthly_pension_employee_cents=pension_result["employee_cents"],
			monthly_nhf_cents=nhf,
		)

		log.debug(
			"NigeriaTaxCalculator.compute: emp=%s gross=%d paye=%d pension_emp=%d nhf=%d",
			employee_id, gross_cents, paye,
			pension_result["employee_cents"], nhf,
		)

		return {
			"income_tax_cents": paye,
			"ni_employee_cents": pension_result["employee_cents"],
			"pension_employee_cents": pension_result["employee_cents"],
			"pension_employer_cents": pension_result["employer_cents"],
			"nhf_cents": nhf,
		}


__all__ = [
	"NigeriaPAYECalculator",
	"NigeriaPensionCalculator",
	"NigeriaHousingFundCalculator",
	"NigeriaTaxCalculator",
]
