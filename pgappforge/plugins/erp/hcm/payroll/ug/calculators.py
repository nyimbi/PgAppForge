"""
pgappforge/plugins/erp/hcm/payroll/ug/calculators.py

Uganda statutory payroll calculators — FY 2024/25 (effective 1 July 2024).

All amounts in integer cents (UGX × 100).
Never uses float or Decimal storage — intermediate arithmetic uses Decimal,
results rounded ROUND_HALF_UP to int before returning.

PAYE bands (annual, UGX cents):
  0              –   282_000_000:  0%  (personal exemption threshold)
  282_000_001    – 1_000_000_000: 10%
  1_000_000_001  – 12_000_000_000: 20%
  12_000_000_001 – 14_000_000_000: 30%
  > 14_000_000_000:               40%

Personal exemption: UGX 2,820,000/year (282_000_000 cents) — first band is 0%.
No insurance relief in Uganda PAYE.

NSSF (National Social Security Fund Act 1985):
  Employee: 5% of gross monthly pay (no cap)
  Employer: 10% of gross monthly pay (no cap)

NHIF (National Health Insurance Fund):
  Not mandatory for private sector.
  Public sector: 4% of gross, employee only.
  Implemented as opt-in: nhif_enrolled=True → 4% employee deduction.

LST (Local Service Tax):
  Annual flat charge deducted in Q1 (first pay period of tax year):
    < UGX 100,000/year:            exempt
    100,000 – 10,000,000:          UGX 5,000/year  (500_000 cents)
    10,000,001 – 30,000,000:       UGX 20,000/year (2_000_000 cents)
    > 30,000,000:                  UGX 100,000/year (10_000_000 cents)
  Pass ytd_lst_cents to avoid double-deduction within the same tax year.

## Sources & Legal References

### PAYE (Income Tax)
- Income Tax Act (Cap 340, Laws of Uganda), as amended.
- Uganda Revenue Authority (URA) PAYE guide and band tables:
  https://www.ura.go.ug/en/individuals/paye
- Finance Act 2024 (Uganda Gazette, June 2024): confirms current bands and
  personal exemption threshold of UGX 2,820,000/year.
- Bands effective: 1 July 2024 (FY 2024/25).
- Personal exemption threshold: UGX 2,820,000/year (235,000/month).
  The first band (0–2,820,000 UGX/year) attracts 0% — implemented as a
  zero-rate band rather than a relief subtraction to simplify computation
  and correctly handle incomes below the threshold.
- No general insurance relief in Uganda individual PAYE (unlike Kenya).
- Disability exemption: Income Tax Act Cap 340 provides exemption for persons
  with disabilities up to specified thresholds. Not implemented here — pass
  net taxable after such exemptions to compute_monthly() if applicable.

### NSSF
- National Social Security Fund Act 1985 (Cap 222, Laws of Uganda), as
  amended by the NSSF (Amendment) Act 2022.
- Employee contribution: 5% of gross monthly earnings (no ceiling).
- Employer contribution: 10% of gross monthly earnings (no ceiling).
- Applies to all employees earning UGX 150,000 or more per month (below this
  threshold, employer is still liable for employer portion under some
  interpretations; confirm with NSSF Uganda).
- NSSF Uganda: https://www.nssfug.org
- Note: The NSSF (Amendment) Act 2022 introduced mid-term access and expanded
  coverage. Contribution rates (5%/10%) remain unchanged as at July 2024.

### NHIF
- National Health Insurance Fund Act 2021 (Uganda). Implementation of the
  mandatory NHIF for the private sector was deferred pending regulations
  as at July 2024.
- Public servants contribute 4% of gross under the existing Government
  NHIF arrangements.
- This module implements NHIF as opt-in (nhif_enrolled flag): when True,
  4% employee deduction is applied. No employer match in the base case.
- Confirm whether mandatory NHIF has been gazette-noticed and activated
  before each FY. Update rate and employer_match flag accordingly.
- Reference: https://www.nhif.go.ug

### LST (Local Service Tax)
- Local Governments Act (Cap 243), Schedule 6; Local Government (LST)
  Regulations as set by each local authority.
- LST is an annual flat tax collected by the employer on behalf of the
  local government in which the employee works.
- Standard national LST bands (UGX annual gross salary):
    Below 100,000:             Exempt
    100,000 – 10,000,000:      UGX 5,000/year
    10,000,001 – 30,000,000:   UGX 20,000/year
    Above 30,000,000:          UGX 100,000/year
- Deducted in full in the first pay period of the year (January for calendar
  year employers; July for FY-aligned employers).
- YTD tracking (ytd_lst_cents) prevents double-deduction if the payroll is
  run multiple times or corrected within Q1.
- Reference: Uganda Revenue Authority LST guide:
  https://www.ura.go.ug/en/businesses/paye/lst

### Annual Update Checklist

Run this checklist each financial year (Uganda FY runs 1 July – 30 June):

1. **Finance Act gazette notice**: Published June/July in the Uganda Gazette.
   Check for amendments to Income Tax Act bands or the personal exemption.
   URL: https://www.finance.go.ug
2. **PAYE bands**: Update `_PAYE_BANDS` with new annual UGX thresholds.
   Confirm with URA PAYE calculator.
3. **NSSF rates**: Employee 5% / Employer 10% rarely change. Verify with NSSF.
   Update `_NSSF_EMPLOYEE_RATE` and `_NSSF_EMPLOYER_RATE` if needed.
4. **NHIF status**: Confirm whether mandatory private-sector NHIF has been
   activated and update `_NHIF_RATE` and employer_match logic accordingly.
5. **LST bands**: LST bands may be revised by Parliament. Update `_LST_BANDS`.
6. **Run tests**: `uv run pytest tests/ci/test_ug_payroll_statutory.py -v`
7. **Update EFFECTIVE_FROM**: Set to the effective date of the current rate set.
8. **Notify downstream**: Communicate rate change date to payroll team before
   mid-period changes take effect.

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


def _clamp(value: int, lo: int, hi: int) -> int:
	return max(lo, min(hi, value))


# ---------------------------------------------------------------------------
# PAYE constants (annual, UGX cents)
# ---------------------------------------------------------------------------

# Each entry: (lower_bound_inclusive, upper_bound_inclusive, rate)
# The 0% band represents the personal exemption threshold.
_PAYE_BANDS: list[tuple[int, int, Decimal]] = [
	(0,               282_000_000,     Decimal("0.00")),   # personal exemption
	(282_000_001,   1_000_000_000,     Decimal("0.10")),
	(1_000_000_001, 12_000_000_000,    Decimal("0.20")),
	(12_000_000_001, 14_000_000_000,   Decimal("0.30")),
	(14_000_000_001, 2**62,            Decimal("0.40")),
]

# No personal relief subtraction — exemption is baked into the 0% band above.
# No insurance relief in Uganda individual PAYE.

# NSSF
_NSSF_EMPLOYEE_RATE: Decimal = Decimal("0.05")
_NSSF_EMPLOYER_RATE: Decimal = Decimal("0.10")

# NHIF (opt-in; public sector rate)
_NHIF_RATE: Decimal = Decimal("0.04")

# LST annual flat bands: (min_annual_gross_cents_exclusive, max_annual_gross_cents_inclusive, annual_lst_cents)
# First entry: below 10_000_000 cents (UGX 100,000) → exempt
_LST_BANDS: list[tuple[int, int, int]] = [
	(0,              10_000_000,    0),             # <= UGX 100,000 — exempt (LST applies above 100,000)
	(10_000_000,   999_999_999,     500_000),        # UGX 100,000–10,000,000 → UGX 5,000
	(1_000_000_000, 2_999_999_999,  2_000_000),      # UGX 10,000,001–30,000,000 → UGX 20,000
	(3_000_000_000, 2**62,          10_000_000),     # > UGX 30,000,000 → UGX 100,000
]


# ---------------------------------------------------------------------------
# UgandaPAYECalculator
# ---------------------------------------------------------------------------

class UgandaPAYECalculator:
	"""Uganda Revenue Authority PAYE engine — FY 2024/25.

	Computes monthly PAYE by annualising the monthly taxable income,
	applying progressive bands (with 0% personal exemption band), then
	dividing the annual tax by pay_frequency_months.

	No insurance relief applies in Uganda PAYE.

	Usage::

	    calc = UgandaPAYECalculator()
	    monthly_paye = calc.compute_monthly(monthly_taxable_cents=50_000_000_00)
	"""

	def compute_annual_tax_before_relief(self, annual_taxable_cents: int) -> int:
		"""Apply progressive PAYE bands to annual taxable income.

		The 0% band for the first UGX 2,820,000/year is included in the
		bands table so incomes at or below the exemption threshold return 0.

		Args:
			annual_taxable_cents: Annual taxable income in UGX cents.

		Returns:
			Gross annual tax in UGX cents (effectively post-exemption due to
			0% band; no separate relief subtraction needed).
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

	def compute_annual_paye(self, annual_taxable_cents: int) -> int:
		"""Annual PAYE after the built-in exemption band. Minimum is 0.

		Args:
			annual_taxable_cents: Annual gross taxable income in UGX cents.

		Returns:
			Annual PAYE payable in UGX cents (>= 0).
		"""
		return max(0, self.compute_annual_tax_before_relief(annual_taxable_cents))

	def compute_monthly(
		self,
		monthly_taxable_cents: int,
		pay_frequency_months: int = 1,
	) -> int:
		"""Monthly PAYE by annualising the monthly taxable income.

		Args:
			monthly_taxable_cents: Monthly taxable income in UGX cents.
			pay_frequency_months: Number of months this period covers (1 = monthly).

		Returns:
			PAYE for this pay period in UGX cents.
		"""
		assert monthly_taxable_cents >= 0, "monthly_taxable_cents must be non-negative"
		assert pay_frequency_months >= 1, "pay_frequency_months must be >= 1"
		periods = 12 // pay_frequency_months
		annual = monthly_taxable_cents * periods
		annual_paye = self.compute_annual_paye(annual)
		return _rc(Decimal(annual_paye) / periods)


# ---------------------------------------------------------------------------
# UgandaNSSFCalculator
# ---------------------------------------------------------------------------

class UgandaNSSFCalculator:
	"""NSSF Act 1985 (as amended 2022) — Uganda employee and employer contributions.

	Employee: 5% of gross monthly pay (no cap).
	Employer: 10% of gross monthly pay (no cap).

	Returns dict with keys: employee_cents, employer_cents.
	"""

	def compute(self, gross_cents: int) -> dict[str, int]:
		"""Compute NSSF contributions for a given month.

		Args:
			gross_cents: Gross monthly pay in UGX cents.

		Returns:
			Dict with employee_cents and employer_cents.
		"""
		assert gross_cents >= 0, "gross_cents must be non-negative"
		employee = _rc(Decimal(gross_cents) * _NSSF_EMPLOYEE_RATE)
		employer = _rc(Decimal(gross_cents) * _NSSF_EMPLOYER_RATE)
		return {
			"employee_cents": employee,
			"employer_cents": employer,
		}


# ---------------------------------------------------------------------------
# UgandaNHIFCalculator
# ---------------------------------------------------------------------------

class UgandaNHIFCalculator:
	"""National Health Insurance Fund — Uganda.

	Mandatory only for public sector employees as at FY 2024/25.
	Private sector: opt-in via nhif_enrolled=True.
	Rate: 4% of gross monthly pay, employee-only (no employer match in base case).

	Returns dict with key: employee_cents.
	"""

	def compute(
		self,
		gross_cents: int,
		nhif_enrolled: bool = False,
	) -> dict[str, int]:
		"""Compute NHIF deduction for a given month.

		Args:
			gross_cents: Gross monthly pay in UGX cents.
			nhif_enrolled: True if employee is enrolled in NHIF (public sector
			    or voluntarily enrolled private sector employee).

		Returns:
			Dict with employee_cents (0 if not enrolled).
		"""
		assert gross_cents >= 0, "gross_cents must be non-negative"
		if not nhif_enrolled:
			return {"employee_cents": 0}
		employee = _rc(Decimal(gross_cents) * _NHIF_RATE)
		return {"employee_cents": employee}


# ---------------------------------------------------------------------------
# UgandaLSTCalculator
# ---------------------------------------------------------------------------

class UgandaLSTCalculator:
	"""Local Service Tax (LST) — Uganda Local Governments Act.

	Annual flat tax deducted in full in the first pay period of the tax year.
	YTD tracking via ytd_lst_cents prevents double-deduction.

	LST bands (annual gross UGX cents):
	  < 10_000_000:           exempt (0)
	  10_000_000–999_999_999: UGX 5,000 → 500_000 cents
	  1_000_000_000–2_999_999_999: UGX 20,000 → 2_000_000 cents
	  >= 3_000_000_000:       UGX 100,000 → 10_000_000 cents
	"""

	def _annual_lst_amount(self, annual_gross_cents: int) -> int:
		"""Determine the flat LST amount for the employee's income band.

		Args:
			annual_gross_cents: Annual gross pay in UGX cents.

		Returns:
			Annual LST in UGX cents.
		"""
		for lower, upper, lst_cents in _LST_BANDS:
			if lower <= annual_gross_cents <= upper:
				return lst_cents
		# Should not reach here; defensive fallback
		return _LST_BANDS[-1][2]

	def compute(
		self,
		monthly_gross_cents: int,
		ytd_lst_cents: int = 0,
	) -> int:
		"""Compute LST deduction for the current pay period.

		LST is deducted in full in the first pay period of the year.
		If ytd_lst_cents > 0, the annual LST has already been collected —
		return 0 to prevent double-deduction.

		Args:
			monthly_gross_cents: Gross monthly pay in UGX cents (used to
			    derive annual gross for band determination).
			ytd_lst_cents: LST already collected this tax year for this employee.

		Returns:
			LST to deduct this period in UGX cents (0 if already collected).
		"""
		assert monthly_gross_cents >= 0, "monthly_gross_cents must be non-negative"
		assert ytd_lst_cents >= 0, "ytd_lst_cents must be non-negative"

		if ytd_lst_cents > 0:
			# LST already collected this year — no further deduction
			return 0

		annual_gross = monthly_gross_cents * 12
		return self._annual_lst_amount(annual_gross)


# ---------------------------------------------------------------------------
# UgandaTaxCalculator — composite, satisfies tax_calculator protocol
# ---------------------------------------------------------------------------

class UgandaTaxCalculator:
	"""Composite Uganda statutory calculator for injection into PayrollService.

	Implements the tax_calculator protocol expected by PayrollService.calculate_payrun():
	  .compute(gross_cents, employee_id, session, **kwargs) -> dict

	The returned dict matches PayrollService's tax_result keys plus Uganda-specific
	statutory breakdown:
	  income_tax_cents        — PAYE
	  ni_employee_cents       — NSSF employee (5%)
	  pension_employee_cents  — 0 (NSSF IS the statutory pension)
	  pension_employer_cents  — NSSF employer (10%)
	  nssf_employee_cents     — NSSF employee (alias for ni_employee_cents)
	  nssf_employer_cents     — NSSF employer (alias for pension_employer_cents)
	  nhif_cents              — NHIF employee deduction (0 if not enrolled)
	  lst_cents               — LST deducted this period
	  pensionable_pay_cents   — gross used for NSSF computation
	"""

	def __init__(
		self,
		paye: UgandaPAYECalculator | None = None,
		nssf: UgandaNSSFCalculator | None = None,
		nhif: UgandaNHIFCalculator | None = None,
		lst: UgandaLSTCalculator | None = None,
	) -> None:
		self._paye = paye or UgandaPAYECalculator()
		self._nssf = nssf or UgandaNSSFCalculator()
		self._nhif = nhif or UgandaNHIFCalculator()
		self._lst = lst or UgandaLSTCalculator()

	def compute(
		self,
		gross_cents: int,
		employee_id: str,
		session: Any,
		*,
		pensionable_pay_cents: int | None = None,
		ytd_lst_cents: int = 0,
		nhif_enrolled: bool = False,
	) -> dict[str, int]:
		"""Compute all Uganda statutory deductions for one employee for one month.

		Args:
			gross_cents: Total gross monthly pay in UGX cents.
			employee_id: Employee UUID (for audit/logging).
			session: SQLAlchemy session (unused here; kept for protocol compat).
			pensionable_pay_cents: Gross for NSSF purposes; defaults to gross_cents.
			ytd_lst_cents: Year-to-date LST collected for this employee.
			nhif_enrolled: True if employee is enrolled in NHIF.

		Returns:
			Dict with all statutory deduction amounts.
		"""
		assert gross_cents >= 0, "gross_cents must be non-negative"
		if pensionable_pay_cents is None:
			pensionable_pay_cents = gross_cents

		# PAYE — on total gross
		paye = self._paye.compute_monthly(monthly_taxable_cents=gross_cents)

		# NSSF
		nssf_result = self._nssf.compute(pensionable_pay_cents)

		# NHIF
		nhif_result = self._nhif.compute(gross_cents, nhif_enrolled=nhif_enrolled)

		# LST
		lst = self._lst.compute(gross_cents, ytd_lst_cents=ytd_lst_cents)

		log.debug(
			"UgandaTaxCalculator.compute: emp=%s gross=%d paye=%d "
			"nssf_emp=%d nssf_er=%d nhif=%d lst=%d",
			employee_id, gross_cents, paye,
			nssf_result["employee_cents"], nssf_result["employer_cents"],
			nhif_result["employee_cents"], lst,
		)

		return {
			# Core protocol keys
			"income_tax_cents": paye,
			"ni_employee_cents": nssf_result["employee_cents"],
			"pension_employee_cents": 0,   # NSSF is the statutory pension
			"pension_employer_cents": nssf_result["employer_cents"],
			# Uganda-specific breakdown
			"nssf_employee_cents": nssf_result["employee_cents"],
			"nssf_employer_cents": nssf_result["employer_cents"],
			"nhif_cents": nhif_result["employee_cents"],
			"lst_cents": lst,
			"pensionable_pay_cents": pensionable_pay_cents,
		}


__all__ = [
	"UgandaPAYECalculator",
	"UgandaNSSFCalculator",
	"UgandaNHIFCalculator",
	"UgandaLSTCalculator",
	"UgandaTaxCalculator",
]
