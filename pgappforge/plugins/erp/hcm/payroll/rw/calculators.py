"""
pgappforge/plugins/erp/hcm/payroll/rw/calculators.py

Rwanda statutory payroll — FY 2024/25

All amounts in integer cents (RWF × 100).
Never uses float or Decimal storage — intermediate arithmetic uses Decimal,
results rounded ROUND_HALF_UP to int before returning.

PAYE bands (annual, RWF cents):
  0             –  360_000_000: 0%   (personal exemption: RWF 3,600,000/year)
  360_000_001   – 1_200_000_000: 20%
  > 1_200_000_000:               30%

RSB (Rwanda Social Security Board):
  Employee: 5% of gross (no cap)
  Employer: 5% of gross (no cap)

RAMA (Rwandan Medical Insurance):
  Employee: 7.5% of gross (capped RWF 300,000/year = 30_000_000 cents)
  Employer: 7.5% of gross (capped RWF 300,000/year = 30_000_000 cents)

Sources:
  Rwanda Revenue Authority: https://www.rra.gov.rw
  RSB: https://www.rsb.gov.rw
  RAMA: https://www.rama.rw
  Finance Law 2024 (Official Gazette of Rwanda)

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
# PAYE constants (annual, RWF cents)
# ---------------------------------------------------------------------------

_PAYE_BANDS: list[tuple[int, int, Decimal]] = [
	# (lower_bound_annual, upper_bound_annual, rate)
	(0,             360_000_000,   Decimal("0.00")),
	(360_000_001,   1_200_000_000, Decimal("0.20")),
	(1_200_000_001, 2**62,         Decimal("0.30")),
]

# Personal exemption — first RWF 3,600,000/year (360_000_000 cents) taxed at 0%
_PERSONAL_EXEMPTION: int = 360_000_000  # RWF 3,600,000/year

# RSB
_RSB_RATE: Decimal = Decimal("0.05")

# RAMA
_RAMA_RATE: Decimal = Decimal("0.075")
_RAMA_ANNUAL_CAP: int = 30_000_000  # RWF 300,000/year per side


# ---------------------------------------------------------------------------
# RwandaPAYECalculator
# ---------------------------------------------------------------------------

class RwandaPAYECalculator:
	"""Rwanda Revenue Authority PAYE engine — 2024/25.

	Computes monthly PAYE from monthly taxable income by annualising,
	applying progressive bands, then dividing by 12.

	Usage::

	    calc = RwandaPAYECalculator()
	    monthly_paye = calc.compute_monthly(monthly_taxable_income_cents=5_000_000_00)
	"""

	def compute_annual_tax(self, annual_taxable_cents: int) -> int:
		"""Apply progressive PAYE bands to annual taxable income.

		Args:
			annual_taxable_cents: Annual taxable income in RWF cents.

		Returns:
			Annual tax in RWF cents.
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

	def compute_annual_paye(self, annual_taxable_income_cents: int) -> int:
		"""Annual PAYE. Minimum is 0.

		Args:
			annual_taxable_income_cents: Annual gross taxable income in RWF cents.

		Returns:
			Annual PAYE payable in RWF cents (>= 0).
		"""
		return max(0, self.compute_annual_tax(annual_taxable_income_cents))

	def compute_monthly(
		self,
		monthly_taxable_income_cents: int,
		pay_frequency_months: int = 1,
	) -> int:
		"""Monthly PAYE by annualising the monthly income.

		Args:
			monthly_taxable_income_cents: Monthly taxable income in RWF cents.
			pay_frequency_months: Number of months this period covers (1 = monthly).

		Returns:
			PAYE for this pay period in RWF cents.
		"""
		annual = monthly_taxable_income_cents * (12 // pay_frequency_months)
		annual_paye = self.compute_annual_paye(annual)
		return _rc(Decimal(annual_paye) / (12 // pay_frequency_months))


# ---------------------------------------------------------------------------
# RwandaRSBCalculator
# ---------------------------------------------------------------------------

class RwandaRSBCalculator:
	"""Rwanda Social Security Board contributions.

	Employee: 5% of gross (no cap).
	Employer: 5% of gross (no cap).

	Returns dict: {employee_cents, employer_cents}
	"""

	def compute(self, gross_cents: int) -> dict[str, int]:
		"""Compute monthly RSB contributions.

		Args:
			gross_cents: Gross monthly pay in RWF cents.

		Returns:
			Dict with employee_cents and employer_cents.
		"""
		assert gross_cents >= 0, "gross_cents must be non-negative"
		each = _rc(Decimal(gross_cents) * _RSB_RATE)
		return {"employee_cents": each, "employer_cents": each}


# ---------------------------------------------------------------------------
# RwandaRAMACalculator
# ---------------------------------------------------------------------------

class RwandaRAMACalculator:
	"""Rwandan Medical Insurance (RAMA) contributions.

	Employee: 7.5% of gross (capped RWF 300,000/year = 30_000_000 cents/year).
	Employer: 7.5% of gross (same annual cap per side).

	Cap is applied annually; monthly cap = 30_000_000 / 12 = 2_500_000 cents/month.

	Returns dict: {employee_cents, employer_cents}
	"""

	_MONTHLY_CAP: int = _RAMA_ANNUAL_CAP // 12  # 2_500_000 cents/month per side

	def compute(self, gross_cents: int) -> dict[str, int]:
		"""Compute monthly RAMA contributions.

		Args:
			gross_cents: Gross monthly pay in RWF cents.

		Returns:
			Dict with employee_cents and employer_cents.
		"""
		assert gross_cents >= 0, "gross_cents must be non-negative"
		raw = _rc(Decimal(gross_cents) * _RAMA_RATE)
		each = min(raw, self._MONTHLY_CAP)
		return {"employee_cents": each, "employer_cents": each}


# ---------------------------------------------------------------------------
# RwandaTaxCalculator — composite, satisfies tax_calculator protocol
# ---------------------------------------------------------------------------

class RwandaTaxCalculator:
	"""Composite Rwanda statutory calculator for injection into PayrollService.

	Implements the tax_calculator protocol expected by PayrollService.calculate_payrun():
	  .compute(gross_cents, employee_id, session) -> dict

	Returned dict keys:
	  income_tax_cents        — PAYE
	  ni_employee_cents       — RSB employee (proxy for NI)
	  pension_employee_cents  — 0 (RSB covers pension; alias via ni_employee)
	  pension_employer_cents  — RSB employer
	  rsb_employee_cents      — RSB employee contribution
	  rsb_employer_cents      — RSB employer contribution
	  rama_employee_cents     — RAMA employee contribution
	  rama_employer_cents     — RAMA employer contribution
	"""

	def __init__(
		self,
		paye: RwandaPAYECalculator | None = None,
		rsb: RwandaRSBCalculator | None = None,
		rama: RwandaRAMACalculator | None = None,
	) -> None:
		self._paye = paye or RwandaPAYECalculator()
		self._rsb = rsb or RwandaRSBCalculator()
		self._rama = rama or RwandaRAMACalculator()

	def compute(
		self,
		gross_cents: int,
		employee_id: str,
		session: Any,
	) -> dict[str, int]:
		"""Compute all Rwanda statutory deductions for one employee for one month.

		Args:
			gross_cents: Total gross monthly pay in RWF cents.
			employee_id: Employee UUID (for audit/logging).
			session: SQLAlchemy session (unused here; kept for protocol compat).

		Returns:
			Dict with all statutory deduction amounts.
		"""
		assert gross_cents >= 0, "gross_cents must be non-negative"

		paye = self._paye.compute_monthly(gross_cents)
		rsb_result = self._rsb.compute(gross_cents)
		rama_result = self._rama.compute(gross_cents)

		log.debug(
			"RwandaTaxCalculator.compute: emp=%s gross=%d paye=%d rsb_emp=%d rama_emp=%d",
			employee_id, gross_cents, paye,
			rsb_result["employee_cents"], rama_result["employee_cents"],
		)

		return {
			"income_tax_cents": paye,
			"ni_employee_cents": rsb_result["employee_cents"],
			"pension_employee_cents": 0,
			"pension_employer_cents": rsb_result["employer_cents"],
			"rsb_employee_cents": rsb_result["employee_cents"],
			"rsb_employer_cents": rsb_result["employer_cents"],
			"rama_employee_cents": rama_result["employee_cents"],
			"rama_employer_cents": rama_result["employer_cents"],
		}


__all__ = [
	"RwandaPAYECalculator",
	"RwandaRSBCalculator",
	"RwandaRAMACalculator",
	"RwandaTaxCalculator",
]
