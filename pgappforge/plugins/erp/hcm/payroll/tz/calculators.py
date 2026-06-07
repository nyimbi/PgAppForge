"""
pgappforge/plugins/erp/hcm/payroll/tz/calculators.py

Tanzania statutory payroll calculators — FY 2024/25 (effective 1 July 2024).

All amounts in integer cents (TZS × 100).
Never uses float or Decimal storage — intermediate arithmetic uses Decimal,
results rounded ROUND_HALF_UP to int before returning.

PAYE bands (MONTHLY, TZS cents):
  0            –  27_000_000:  0%
  27_000_001   –  52_000_000:  9%  (on excess over 27_000_000)
  52_000_001   –  76_000_000: 20%  (on excess over 52_000_000)
  76_000_001   – 100_000_000: 25%  (on excess over 76_000_000)
  > 100_000_000:              30%

Note: Tanzania PAYE is computed on monthly income directly (not annualised).
Personal relief = TZS 270,000/month = 27_000_000 cents/month (0% band).

NSSF (National Social Security Fund Act 1997):
  Employee: 10% of gross monthly pay (no cap)
  Employer: 10% of gross monthly pay (no cap)

NHIF (National Health Insurance Fund):
  Employee: 3% of gross monthly pay (no cap)
  Employer: 3% of gross monthly pay (no cap, matched)

SDL (Skills Development Levy — Vocational Education and Training Act 1994):
  Employer-only: 3.5% of gross monthly wages per employee (no cap)

WCF (Workers' Compensation Fund):
  Employer-only: variable by industry risk; white-collar default 0.5%
  wcf_rate is overridable per employee/risk group

## Sources & Legal References

### PAYE (Income Tax)
- Income Tax Act (Cap 332, Laws of Tanzania), as amended.
- Tanzania Revenue Authority (TRA) PAYE guide:
  https://www.tra.go.tz/index.php/paye
- Finance Act 2024 (Tanzania Gazette, June 2024): confirms monthly PAYE
  bands effective 1 July 2024.
- Monthly bands (TZS, not annualised):
    0 – 270,000:           0%
    270,001 – 520,000:     9%
    520,001 – 760,000:    20%
    760,001 – 1,000,000:  25%
    > 1,000,000:          30%
- Tanzania PAYE is applied directly on monthly income (not annualised),
  distinguishing it from Kenya and Uganda practice.
- No separate personal relief deduction — the 0% band acts as the
  personal exemption.

### NSSF
- National Social Security Fund Act 1997 (Cap 50, Laws of Tanzania).
- Employee contribution: 10% of gross monthly earnings (no ceiling).
- Employer contribution: 10% of gross monthly earnings (no ceiling).
- NSSF Tanzania: https://www.nssf.or.tz
- Note: NSSF Act 1997 rate is 10%+10%. Some parastatals contribute via
  PPF (Public Service Pensions Fund) instead; this module implements the
  general private-sector NSSF rate.

### NHIF
- National Health Insurance Fund Act (Cap 395, Laws of Tanzania).
- Employee: 3% of gross monthly contributory salary.
- Employer: 3% of gross monthly contributory salary (matched).
- Applies to all employees in the formal sector (public and private).
- No floor or ceiling on contributions.
- NHIF Tanzania: https://www.nhif.or.tz

### SDL (Skills Development Levy)
- Vocational Education and Training Act 1994 (Cap 82), as amended.
- Employer-only levy: 3.5% of total gross monthly wage bill.
- Applied per-employee basis in this module.
- No cap; rate applies to the full gross pay including all allowances.
- Remitted monthly to VETA (Vocational Education and Training Authority).
- Reference: https://www.veta.go.tz/sdl

### WCF (Workers' Compensation Fund)
- Workers' Compensation Act 2008 (Cap 263, Laws of Tanzania).
- Employer-only levy. Rate varies by industry risk classification:
    Class I (low risk / white-collar):   0.5% of gross wages
    Class II (medium risk):              1.0% of gross wages
    Class III (high risk / heavy industry): 1.5–3.0% of gross wages
- Default rate in this module: 0.5% (white-collar).
  Pass wcf_rate=Decimal("0.010") etc. for higher-risk categories.
- WCF Tanzania: https://www.wcf.go.tz

### Annual Update Checklist

Run this checklist each financial year (Tanzania FY runs 1 July – 30 June):

1. **Finance Act gazette notice**: Published June/July in the Tanzania Gazette.
   Check for amendments to Income Tax Act monthly bands.
   URL: https://www.mof.go.tz
2. **PAYE bands**: Update `_PAYE_BANDS` with new TZS monthly thresholds.
   Confirm with TRA PAYE calculator.
3. **NSSF rates**: Employee 10% / Employer 10% rarely change. Verify with NSSF.
4. **NHIF rates**: Employee 3% / Employer 3% may be adjusted by NHIF regulations.
   Update `_NHIF_RATE` if changed.
5. **SDL rate**: VETA SDL rate (3.5%) is set by the Finance Act; verify annually.
   Update `_SDL_RATE` if changed.
6. **WCF rates**: WCF may revise risk-class rates. Update `_WCF_DEFAULT_RATE`
   and communicate new rates to HR for per-employee overrides.
7. **Run tests**: `uv run pytest tests/ci/test_tz_payroll_statutory.py -v`
8. **Update EFFECTIVE_FROM**: Set to the effective date of the current rate set.
9. **Notify downstream**: Communicate rate change date to payroll team.

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
# PAYE constants (monthly, TZS cents)
# Tanzania PAYE is computed on monthly income directly — not annualised.
# ---------------------------------------------------------------------------

# Each entry: (lower_bound_inclusive, upper_bound_inclusive, rate)
# Lower bound is the floor of the band; excess above lower is taxed at rate.
_PAYE_BANDS: list[tuple[int, int, Decimal]] = [
	(0,          27_000_000,   Decimal("0.00")),   # 0–270,000 TZS: exempt
	(27_000_001, 52_000_000,   Decimal("0.09")),   # 270,001–520,000: 9%
	(52_000_001, 76_000_000,   Decimal("0.20")),   # 520,001–760,000: 20%
	(76_000_001, 100_000_000,  Decimal("0.25")),   # 760,001–1,000,000: 25%
	(100_000_001, 2**62,       Decimal("0.30")),   # > 1,000,000: 30%
]

# NSSF
_NSSF_EMPLOYEE_RATE: Decimal = Decimal("0.10")
_NSSF_EMPLOYER_RATE: Decimal = Decimal("0.10")

# NHIF
_NHIF_RATE: Decimal = Decimal("0.03")

# SDL
_SDL_RATE: Decimal = Decimal("0.035")

# WCF default (white-collar)
_WCF_DEFAULT_RATE: Decimal = Decimal("0.005")


# ---------------------------------------------------------------------------
# TanzaniaPAYECalculator
# ---------------------------------------------------------------------------

class TanzaniaPAYECalculator:
	"""Tanzania Revenue Authority PAYE engine — FY 2024/25.

	Computes monthly PAYE directly from monthly taxable income using
	progressive marginal bands. Tanzania does NOT annualise — bands are
	monthly TZS amounts.

	Usage::

	    calc = TanzaniaPAYECalculator()
	    monthly_paye = calc.compute_monthly(monthly_taxable_cents=60_000_000)
	"""

	def compute_monthly(self, monthly_taxable_cents: int) -> int:
		"""Compute monthly PAYE using marginal monthly bands.

		Args:
			monthly_taxable_cents: Monthly taxable income in TZS cents.

		Returns:
			Monthly PAYE in TZS cents (>= 0).
		"""
		assert monthly_taxable_cents >= 0, "monthly_taxable_cents must be non-negative"
		tax = Decimal(0)
		remaining = monthly_taxable_cents

		for lower, upper, rate in _PAYE_BANDS:
			if remaining <= 0:
				break
			band_width = upper - lower + 1
			taxable_in_band = min(remaining, band_width)
			tax += Decimal(taxable_in_band) * rate
			remaining -= taxable_in_band

		return max(0, _rc(tax))


# ---------------------------------------------------------------------------
# TanzaniaNSSFCalculator
# ---------------------------------------------------------------------------

class TanzaniaNSSFCalculator:
	"""NSSF Act 1997 — Tanzania employee and employer contributions.

	Employee: 10% of gross monthly pay (no cap).
	Employer: 10% of gross monthly pay (no cap).

	Returns dict with keys: employee_cents, employer_cents.
	"""

	def compute(self, gross_cents: int) -> dict[str, int]:
		"""Compute NSSF contributions for a given month.

		Args:
			gross_cents: Gross monthly pay in TZS cents.

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
# TanzaniaNHIFCalculator
# ---------------------------------------------------------------------------

class TanzaniaNHIFCalculator:
	"""National Health Insurance Fund — Tanzania.

	Employee: 3% of gross monthly pay (no cap).
	Employer: 3% of gross monthly pay (matched, no cap).

	Returns dict with keys: employee_cents, employer_cents.
	"""

	def compute(self, gross_cents: int) -> dict[str, int]:
		"""Compute NHIF contributions for a given month.

		Args:
			gross_cents: Gross monthly pay in TZS cents.

		Returns:
			Dict with employee_cents and employer_cents.
		"""
		assert gross_cents >= 0, "gross_cents must be non-negative"
		each = _rc(Decimal(gross_cents) * _NHIF_RATE)
		return {
			"employee_cents": each,
			"employer_cents": each,
		}


# ---------------------------------------------------------------------------
# TanzaniaSDLCalculator
# ---------------------------------------------------------------------------

class TanzaniaSDLCalculator:
	"""Skills Development Levy — Vocational Education and Training Act 1994.

	Employer-only: 3.5% of gross monthly wages per employee.
	No employee deduction. No cap.

	Returns int: employer_sdl_cents.
	"""

	def compute(self, gross_cents: int) -> int:
		"""Compute SDL levy for the current pay period.

		Args:
			gross_cents: Gross monthly pay in TZS cents.

		Returns:
			SDL levy in TZS cents (employer-only).
		"""
		assert gross_cents >= 0, "gross_cents must be non-negative"
		return _rc(Decimal(gross_cents) * _SDL_RATE)


# ---------------------------------------------------------------------------
# TanzaniaWCFCalculator
# ---------------------------------------------------------------------------

class TanzaniaWCFCalculator:
	"""Workers' Compensation Fund — Workers' Compensation Act 2008.

	Employer-only levy. Rate varies by industry risk classification.
	Default: 0.5% (white-collar / low-risk).
	Override wcf_rate per employee or risk group as needed.

	Returns int: employer_wcf_cents.
	"""

	def compute(
		self,
		gross_cents: int,
		wcf_rate: Decimal = _WCF_DEFAULT_RATE,
	) -> int:
		"""Compute WCF levy for the current pay period.

		Args:
			gross_cents: Gross monthly pay in TZS cents.
			wcf_rate: WCF rate as a Decimal fraction (e.g. Decimal("0.005")).
			    Default 0.5% (white-collar). Use Decimal("0.010") for medium-risk,
			    Decimal("0.015")–Decimal("0.030") for high-risk categories.

		Returns:
			WCF levy in TZS cents (employer-only).
		"""
		assert gross_cents >= 0, "gross_cents must be non-negative"
		assert wcf_rate >= Decimal(0), "wcf_rate must be non-negative"
		return _rc(Decimal(gross_cents) * wcf_rate)


# ---------------------------------------------------------------------------
# TanzaniaTaxCalculator — composite, satisfies tax_calculator protocol
# ---------------------------------------------------------------------------

class TanzaniaTaxCalculator:
	"""Composite Tanzania statutory calculator for injection into PayrollService.

	Implements the tax_calculator protocol expected by PayrollService.calculate_payrun():
	  .compute(gross_cents, employee_id, session, **kwargs) -> dict

	The returned dict matches PayrollService's tax_result keys plus Tanzania-specific
	statutory breakdown:
	  income_tax_cents        — PAYE
	  ni_employee_cents       — NSSF employee (10%)
	  pension_employee_cents  — 0 (NSSF IS the statutory pension)
	  pension_employer_cents  — NSSF employer (10%)
	  nssf_employee_cents     — NSSF employee (alias for ni_employee_cents)
	  nssf_employer_cents     — NSSF employer (alias for pension_employer_cents)
	  nhif_employee_cents     — NHIF employee deduction (3%)
	  nhif_employer_cents     — NHIF employer contribution (3%)
	  sdl_cents               — SDL employer levy (3.5%)
	  wcf_cents               — WCF employer levy (variable rate)
	  pensionable_pay_cents   — gross used for NSSF computation
	"""

	def __init__(
		self,
		paye: TanzaniaPAYECalculator | None = None,
		nssf: TanzaniaNSSFCalculator | None = None,
		nhif: TanzaniaNHIFCalculator | None = None,
		sdl: TanzaniaSDLCalculator | None = None,
		wcf: TanzaniaWCFCalculator | None = None,
	) -> None:
		self._paye = paye or TanzaniaPAYECalculator()
		self._nssf = nssf or TanzaniaNSSFCalculator()
		self._nhif = nhif or TanzaniaNHIFCalculator()
		self._sdl = sdl or TanzaniaSDLCalculator()
		self._wcf = wcf or TanzaniaWCFCalculator()

	def compute(
		self,
		gross_cents: int,
		employee_id: str,
		session: Any,
		*,
		pensionable_pay_cents: int | None = None,
		wcf_rate: Decimal = _WCF_DEFAULT_RATE,
	) -> dict[str, int]:
		"""Compute all Tanzania statutory deductions for one employee for one month.

		Args:
			gross_cents: Total gross monthly pay in TZS cents.
			employee_id: Employee UUID (for audit/logging).
			session: SQLAlchemy session (unused here; kept for protocol compat).
			pensionable_pay_cents: Gross for NSSF purposes; defaults to gross_cents.
			wcf_rate: WCF rate as Decimal (default 0.005 for white-collar).

		Returns:
			Dict with all statutory deduction amounts.
		"""
		assert gross_cents >= 0, "gross_cents must be non-negative"
		if pensionable_pay_cents is None:
			pensionable_pay_cents = gross_cents

		# PAYE — monthly direct computation (not annualised)
		paye = self._paye.compute_monthly(monthly_taxable_cents=gross_cents)

		# NSSF
		nssf_result = self._nssf.compute(pensionable_pay_cents)

		# NHIF
		nhif_result = self._nhif.compute(gross_cents)

		# SDL
		sdl = self._sdl.compute(gross_cents)

		# WCF
		wcf = self._wcf.compute(gross_cents, wcf_rate=wcf_rate)

		log.debug(
			"TanzaniaTaxCalculator.compute: emp=%s gross=%d paye=%d "
			"nssf_emp=%d nssf_er=%d nhif_emp=%d nhif_er=%d sdl=%d wcf=%d",
			employee_id, gross_cents, paye,
			nssf_result["employee_cents"], nssf_result["employer_cents"],
			nhif_result["employee_cents"], nhif_result["employer_cents"],
			sdl, wcf,
		)

		return {
			# Core protocol keys
			"income_tax_cents": paye,
			"ni_employee_cents": nssf_result["employee_cents"],
			"pension_employee_cents": 0,   # NSSF is the statutory pension
			"pension_employer_cents": nssf_result["employer_cents"],
			# Tanzania-specific breakdown
			"nssf_employee_cents": nssf_result["employee_cents"],
			"nssf_employer_cents": nssf_result["employer_cents"],
			"nhif_employee_cents": nhif_result["employee_cents"],
			"nhif_employer_cents": nhif_result["employer_cents"],
			"sdl_cents": sdl,
			"wcf_cents": wcf,
			"pensionable_pay_cents": pensionable_pay_cents,
		}


__all__ = [
	"TanzaniaPAYECalculator",
	"TanzaniaNSSFCalculator",
	"TanzaniaNHIFCalculator",
	"TanzaniaSDLCalculator",
	"TanzaniaWCFCalculator",
	"TanzaniaTaxCalculator",
]
