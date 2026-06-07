"""
pgappforge/plugins/erp/hcm/payroll/gh/calculators.py

Ghana statutory payroll — FY 2024/25

All amounts in integer pesewas (GHS × 100).
Never uses float or Decimal storage — intermediate arithmetic uses Decimal,
results rounded ROUND_HALF_UP to int before returning.

PAYE bands (annual, GHS pesewas) — Budget Statement 2024:
  0            –    40_200: 0%    (GHS 402/year exempt = GHS 33.50/month)
  40_201       –   588_000: 5%
  588_001      –   756_000: 10%
  756_001      – 5_016_000: 17.5%
  5_016_001    –24_000_000: 25%
  > 24_000_000:             35%

SSNIT (Social Security and National Insurance Trust):
  Employee: 5.5% of gross (remitted to SSNIT)
  Employer: 13% of gross (11% to SSNIT Tier 1, 2% to 2nd tier occupational pension)

NHIL (National Health Insurance Levy):
  Employer only: 2.5% of gross (per-employee proxy for wage-bill levy)

Sources:
  Ghana Revenue Authority: https://gra.gov.gh
  SSNIT: https://www.ssnit.org.gh
  Budget Statement 2024 (Republic of Ghana)
  National Health Insurance Act 2003 (Act 650) as amended

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
	"""Round Decimal → int pesewas, ROUND_HALF_UP."""
	return int(d.to_integral_value(rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# PAYE constants (annual, GHS pesewas)
# ---------------------------------------------------------------------------

_PAYE_BANDS: list[tuple[int, int, Decimal]] = [
	# (lower_bound_annual, upper_bound_annual, rate)
	(0,          40_200,    Decimal("0.000")),
	(40_201,    588_000,    Decimal("0.050")),
	(588_001,   756_000,    Decimal("0.100")),
	(756_001,  5_016_000,   Decimal("0.175")),
	(5_016_001, 24_000_000, Decimal("0.250")),
	(24_000_001, 2**62,     Decimal("0.350")),
]

# SSNIT
_SSNIT_EMPLOYEE: Decimal = Decimal("0.055")
_SSNIT_EMPLOYER: Decimal = Decimal("0.13")

# NHIL
_NHIL_RATE: Decimal = Decimal("0.025")


# ---------------------------------------------------------------------------
# GhanaPAYECalculator
# ---------------------------------------------------------------------------

class GhanaPAYECalculator:
	"""Ghana Revenue Authority PAYE engine — 2024/25.

	Computes monthly PAYE from monthly taxable income by annualising,
	applying progressive bands, then dividing by 12.

	Usage::

	    calc = GhanaPAYECalculator()
	    monthly_paye = calc.compute_monthly(monthly_taxable_income_cents=500_000)
	"""

	def compute_annual_tax(self, annual_taxable_cents: int) -> int:
		"""Apply progressive PAYE bands to annual taxable income.

		Args:
			annual_taxable_cents: Annual taxable income in GHS pesewas.

		Returns:
			Annual tax in GHS pesewas.
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
			annual_taxable_income_cents: Annual gross taxable income in GHS pesewas.

		Returns:
			Annual PAYE payable in GHS pesewas (>= 0).
		"""
		return max(0, self.compute_annual_tax(annual_taxable_income_cents))

	def compute_monthly(
		self,
		monthly_taxable_income_cents: int,
		pay_frequency_months: int = 1,
	) -> int:
		"""Monthly PAYE by annualising the monthly income.

		Args:
			monthly_taxable_income_cents: Monthly taxable income in GHS pesewas.
			pay_frequency_months: Number of months this period covers (1 = monthly).

		Returns:
			PAYE for this pay period in GHS pesewas.
		"""
		annual = monthly_taxable_income_cents * (12 // pay_frequency_months)
		annual_paye = self.compute_annual_paye(annual)
		return _rc(Decimal(annual_paye) / (12 // pay_frequency_months))


# ---------------------------------------------------------------------------
# GhanaSSNITCalculator
# ---------------------------------------------------------------------------

class GhanaSSNITCalculator:
	"""SSNIT contributions — Social Security and National Insurance Trust.

	Employee: 5.5% of gross.
	Employer: 13% of gross (11% Tier 1 to SSNIT, 2% Tier 2 to occupational pension).

	Returns dict: {employee_cents, employer_cents}
	"""

	def compute(self, gross_cents: int) -> dict[str, int]:
		"""Compute monthly SSNIT contributions.

		Args:
			gross_cents: Gross monthly pay in GHS pesewas.

		Returns:
			Dict with employee_cents and employer_cents.
		"""
		assert gross_cents >= 0, "gross_cents must be non-negative"
		employee = _rc(Decimal(gross_cents) * _SSNIT_EMPLOYEE)
		employer = _rc(Decimal(gross_cents) * _SSNIT_EMPLOYER)
		return {"employee_cents": employee, "employer_cents": employer}


# ---------------------------------------------------------------------------
# GhanaNHILCalculator
# ---------------------------------------------------------------------------

class GhanaNHILCalculator:
	"""National Health Insurance Levy (NHIL).

	Employer only: 2.5% of gross monthly pay (per-employee proxy for wage-bill levy).

	Returns:
		Employer NHIL contribution in GHS pesewas.
	"""

	def compute(self, gross_cents: int) -> int:
		"""Compute monthly NHIL employer levy.

		Args:
			gross_cents: Gross monthly pay in GHS pesewas.

		Returns:
			NHIL levy in GHS pesewas.
		"""
		assert gross_cents >= 0, "gross_cents must be non-negative"
		return _rc(Decimal(gross_cents) * _NHIL_RATE)


# ---------------------------------------------------------------------------
# GhanaTaxCalculator — composite, satisfies tax_calculator protocol
# ---------------------------------------------------------------------------

class GhanaTaxCalculator:
	"""Composite Ghana statutory calculator for injection into PayrollService.

	Implements the tax_calculator protocol expected by PayrollService.calculate_payrun():
	  .compute(gross_cents, employee_id, session) -> dict

	Returned dict keys:
	  income_tax_cents        — PAYE
	  ni_employee_cents       — SSNIT employee (proxy for NI)
	  pension_employee_cents  — 0 (SSNIT covers pension; alias via ni_employee)
	  pension_employer_cents  — SSNIT employer
	  ssnit_employee_cents    — SSNIT employee contribution (5.5%)
	  ssnit_employer_cents    — SSNIT employer contribution (13%)
	  nhil_cents              — NHIL employer levy (2.5%)
	"""

	def __init__(
		self,
		paye: GhanaPAYECalculator | None = None,
		ssnit: GhanaSSNITCalculator | None = None,
		nhil: GhanaNHILCalculator | None = None,
	) -> None:
		self._paye = paye or GhanaPAYECalculator()
		self._ssnit = ssnit or GhanaSSNITCalculator()
		self._nhil = nhil or GhanaNHILCalculator()

	def compute(
		self,
		gross_cents: int,
		employee_id: str,
		session: Any,
	) -> dict[str, int]:
		"""Compute all Ghana statutory deductions for one employee for one month.

		Args:
			gross_cents: Total gross monthly pay in GHS pesewas.
			employee_id: Employee UUID (for audit/logging).
			session: SQLAlchemy session (unused here; kept for protocol compat).

		Returns:
			Dict with all statutory deduction amounts.
		"""
		assert gross_cents >= 0, "gross_cents must be non-negative"

		paye = self._paye.compute_monthly(gross_cents)
		ssnit_result = self._ssnit.compute(gross_cents)
		nhil = self._nhil.compute(gross_cents)

		log.debug(
			"GhanaTaxCalculator.compute: emp=%s gross=%d paye=%d ssnit_emp=%d nhil=%d",
			employee_id, gross_cents, paye,
			ssnit_result["employee_cents"], nhil,
		)

		return {
			"income_tax_cents": paye,
			"ni_employee_cents": ssnit_result["employee_cents"],
			"pension_employee_cents": 0,
			"pension_employer_cents": ssnit_result["employer_cents"],
			"ssnit_employee_cents": ssnit_result["employee_cents"],
			"ssnit_employer_cents": ssnit_result["employer_cents"],
			"nhil_cents": nhil,
		}


__all__ = [
	"GhanaPAYECalculator",
	"GhanaSSNITCalculator",
	"GhanaNHILCalculator",
	"GhanaTaxCalculator",
]
