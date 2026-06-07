"""
pgappforge/plugins/erp/hcm/payroll/et/calculators.py

Ethiopia statutory payroll — FY 2024/25

All amounts in integer cents (ETB × 100).
Never uses float or Decimal storage — intermediate arithmetic uses Decimal,
results rounded ROUND_HALF_UP to int before returning.

PAYE bands (MONTHLY, ETB cents):
  0        –  60_000: 0%   (ETB 600/month exempt)
  60_001   – 165_000: 10%
  165_001  – 320_000: 15%
  320_001  – 525_000: 20%
  525_001  – 780_000: 25%
  > 780_000:          35%

Note: Ethiopia PAYE is applied on MONTHLY income directly — no annualisation step.

Pension (PSSA — Private Sector employees):
  Employee: 7% of gross (no cap)
  Employer: 11% of gross (no cap)

Sources:
  Ethiopian Revenue and Customs Authority (ERCA): https://www.erca.gov.et
  Income Tax Proclamation No. 979/2016
  Pension and Social Protection Proclamation No. 715/2011

EFFECTIVE_FROM: str = "2024-07-01"
"""
from __future__ import annotations

import logging
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

log = logging.getLogger(__name__)

EFFECTIVE_FROM: str = "2024-07-01"

# ---------------------------------------------------------------------------
# Monetary helpers
# ---------------------------------------------------------------------------

def _rc(d: Decimal) -> int:
	"""Round Decimal → int cents, ROUND_HALF_UP."""
	return int(d.to_integral_value(rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# PAYE constants (MONTHLY, ETB cents)
# Note: Ethiopia PAYE bands are monthly — no annualisation required.
# ---------------------------------------------------------------------------

_PAYE_BANDS: list[tuple[int, int, Decimal]] = [
	# (lower_bound_monthly, upper_bound_monthly, rate)
	(0,       60_000,  Decimal("0.00")),
	(60_001,  165_000, Decimal("0.10")),
	(165_001, 320_000, Decimal("0.15")),
	(320_001, 525_000, Decimal("0.20")),
	(525_001, 780_000, Decimal("0.25")),
	(780_001, 2**62,   Decimal("0.35")),
]

# Pension (PSSA)
_PENSION_EMPLOYEE_RATE: Decimal = Decimal("0.07")
_PENSION_EMPLOYER_RATE: Decimal = Decimal("0.11")


# ---------------------------------------------------------------------------
# EthiopiaPAYECalculator
# ---------------------------------------------------------------------------

class EthiopiaPAYECalculator:
	"""Ethiopia Revenue and Customs Authority (ERCA) PAYE engine — 2024/25.

	Ethiopia PAYE is computed directly on monthly income — bands are monthly,
	not annualised. No annualisation step required.

	Usage::

	    calc = EthiopiaPAYECalculator()
	    monthly_paye = calc.compute_monthly(monthly_taxable_income_cents=200_000)
	"""

	def compute_monthly(self, monthly_taxable_income_cents: int) -> int:
		"""Apply progressive monthly PAYE bands to monthly taxable income.

		Args:
			monthly_taxable_income_cents: Monthly taxable income in ETB cents.

		Returns:
			Monthly PAYE payable in ETB cents (>= 0).
		"""
		assert monthly_taxable_income_cents >= 0, "monthly_taxable_income_cents must be non-negative"
		tax = Decimal(0)
		remaining = monthly_taxable_income_cents

		for lower, upper, rate in _PAYE_BANDS:
			if remaining <= 0:
				break
			band_width = upper - lower + 1
			taxable_in_band = min(remaining, band_width)
			tax += Decimal(taxable_in_band) * rate
			remaining -= taxable_in_band

		return max(0, _rc(tax))


# ---------------------------------------------------------------------------
# EthiopiaPensionCalculator
# ---------------------------------------------------------------------------

class EthiopiaPensionCalculator:
	"""PSSA (Private Sector) pension contributions.

	Employee: 7% of gross (no cap).
	Employer: 11% of gross (no cap).

	Returns dict: {employee_cents, employer_cents}
	"""

	def compute(self, gross_cents: int) -> dict[str, int]:
		"""Compute monthly pension contributions.

		Args:
			gross_cents: Gross monthly pay in ETB cents.

		Returns:
			Dict with employee_cents and employer_cents.
		"""
		assert gross_cents >= 0, "gross_cents must be non-negative"
		employee = _rc(Decimal(gross_cents) * _PENSION_EMPLOYEE_RATE)
		employer = _rc(Decimal(gross_cents) * _PENSION_EMPLOYER_RATE)
		return {"employee_cents": employee, "employer_cents": employer}


# ---------------------------------------------------------------------------
# EthiopiaTaxCalculator — composite, satisfies tax_calculator protocol
# ---------------------------------------------------------------------------

class EthiopiaTaxCalculator:
	"""Composite Ethiopia statutory calculator for injection into PayrollService.

	Implements the tax_calculator protocol expected by PayrollService.calculate_payrun():
	  .compute(gross_cents, employee_id, session) -> dict

	Returned dict keys:
	  income_tax_cents        — PAYE (monthly bands, no annualisation)
	  ni_employee_cents       — pension employee (proxy for NI)
	  pension_employee_cents  — PSSA employee contribution
	  pension_employer_cents  — PSSA employer contribution
	"""

	def __init__(
		self,
		paye: EthiopiaPAYECalculator | None = None,
		pension: EthiopiaPensionCalculator | None = None,
	) -> None:
		self._paye = paye or EthiopiaPAYECalculator()
		self._pension = pension or EthiopiaPensionCalculator()

	def compute(
		self,
		gross_cents: int,
		employee_id: str,
		session: Any,
	) -> dict[str, int]:
		"""Compute all Ethiopia statutory deductions for one employee for one month.

		Args:
			gross_cents: Total gross monthly pay in ETB cents.
			employee_id: Employee UUID (for audit/logging).
			session: SQLAlchemy session (unused here; kept for protocol compat).

		Returns:
			Dict with all statutory deduction amounts.
		"""
		assert gross_cents >= 0, "gross_cents must be non-negative"

		paye = self._paye.compute_monthly(gross_cents)
		pension_result = self._pension.compute(gross_cents)

		log.debug(
			"EthiopiaTaxCalculator.compute: emp=%s gross=%d paye=%d pension_emp=%d pension_er=%d",
			employee_id, gross_cents, paye,
			pension_result["employee_cents"], pension_result["employer_cents"],
		)

		return {
			"income_tax_cents": paye,
			"ni_employee_cents": pension_result["employee_cents"],
			"pension_employee_cents": pension_result["employee_cents"],
			"pension_employer_cents": pension_result["employer_cents"],
		}


__all__ = [
	"EthiopiaPAYECalculator",
	"EthiopiaPensionCalculator",
	"EthiopiaTaxCalculator",
]
