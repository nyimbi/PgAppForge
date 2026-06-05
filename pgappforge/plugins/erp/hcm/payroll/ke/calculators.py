"""
pgappforge/plugins/erp/hcm/payroll/ke/calculators.py

Kenya statutory payroll calculators — 2024/25 tax year (effective 1 July 2023 /
1 October 2023 / March 2024 as noted per deduction).

All amounts in integer cents (KES × 100).
Never uses float or Decimal storage — intermediate arithmetic uses Decimal,
results rounded ROUND_HALF_UP to int before returning.

PAYE bands (annual, KES cents):
  0           –  28_800_000  @ 10%
  28_800_001  –  38_800_000  @ 25%
  38_800_001  – 600_000_000  @ 30%
  > 600_000_000              @ 35%

Personal relief:        2_400_00 cents/month  (28_800_00/year)
Insurance relief:       15% of qualifying annual premiums, max 5_000_00 cents/month
                        = 60_000_00 cents/year cap

NSSF Act 2013:
  Tier I:  6% of pensionable pay up to 6_000_00 cents/month, employee + employer
  Tier II: 6% of pensionable pay between 6_000_01 and 36_000_00 cents/month, emp + er

SHIF (Social Health Insurance Fund / NHIF replacement, 2023 Act):
  2.75% of gross, clamped [300_00, 1_700_00] cents/month
  Employee-only levy.

Housing Levy (Finance Act 2023):
  Employee: 1.5% of gross
  Employer: 1.5% of gross (matched)

NITA Levy:
  Employer-only: 0.5% of gross/month, capped at 2_500_00 cents/year per employee.
  YTD tracking required to enforce annual cap.

## Sources & Legal References

### PAYE (Income Tax)
- Income Tax Act (Cap 470, Laws of Kenya), Part III — Tax on income of
  individuals.
- Finance Act 2023 (Kenya Gazette Supplement No. 147, 27 June 2023), which
  amended the Income Tax Act to introduce the 35% top band on annual taxable
  income exceeding KES 6,000,000.
- KRA PAYE guide and band tables:
  https://www.kra.go.ke/individual/filing-paying/types-of-taxes/paye
- Bands effective: 1 July 2023 (FY 2023/24 and continuing into 2024/25).
- Personal relief: KES 28,800 per year (KES 2,400/month), unchanged from 2020.
  Confirmed in Finance Act 2023 and KRA PIN-holder notifications.
- Insurance relief: 15% of qualifying life insurance premiums paid, capped at
  KES 60,000 per year (KES 5,000/month). Qualifying products: life insurance,
  education insurance (not pure savings or investment). Section 31(1)(g) ITA
  Cap 470.
- Disability exemption: First KES 150,000/month of income for registered
  persons with disabilities is exempt (Section 14(3) ITA Cap 470).
  Not implemented in this module — pass net taxable after disability exemption
  to compute_monthly() if applicable.

### NSSF
- NSSF Act No. 45 of 2013 (National Social Security Fund Act 2013).
- The Act introduced two-tier contributions replacing the flat KES 200/month
  under the old NSSF Act Cap 258.
  Tier I: 6% of Lower Earnings Limit (LEL = KES 6,000/month) — employee and
          employer each contribute KES 360/month at the LEL.
  Tier II: 6% of earnings between LEL (KES 6,000) and Upper Earnings Limit
           (UEL = KES 36,000/month) — employee and employer matched.
- LEGAL STATUS NOTE: The NSSF Act 2013 was challenged in the Employment and
  Labour Relations Court (Petition No. 82 of 2014, Federation of Kenya
  Employers & 2 others v NSSF). The Court of Appeal (Civil Appeal No. 418 of
  2022, judgment 3 February 2023) upheld the NSSF Act 2013 as constitutional
  and the Tier II contributions enforceable. As of the date of this module
  (June 2026), Tier II remittances are legally required.
  Verify current enforcement and any Finance Act amendments each July.
- Implementation: KenyaNSSFCalculator.compute() applies Tier I on pensionable
  pay up to KES 6,000/month and Tier II on KES 6,001–36,000/month.
  Pensionable pay = basic salary only (not allowances unless employer policy
  designates them pensionable).

### NHIF / SHIF
- NHIF Act (Cap 255, Laws of Kenya) — applicable until 30 September 2023.
- Social Health Insurance Act 2023 (Social Health Insurance Fund / SHIF):
  enacted as part of the Health Laws (Amendment) Act 2023, operationalising
  three funds: Social Health Insurance Fund (SHIF), Emergency, Chronic &
  Critical Illness Fund (ECCIF), and Primary Healthcare Fund (PHF).
- SHIF replaces NHIF from 1 October 2023.
- SHIF rate: 2.75% of gross monthly pay; Floor: KES 300/month;
  Ceiling: KES 1,700/month.
- Employee-only deduction (no employer match under SHIF, unlike NHIF
  which had employer contribution for formal sector).
- Gazette notice: Kenya Gazette Supplement No. 166 (Legal Notice No. 153),
  Social Health Insurance (General) Regulations 2023.
- Reference: https://www.sha.go.ke

### Housing Levy
- Affordable Housing Act 2023 (Affordable Housing Act No. 4 of 2024, assented
  28 March 2024, effective retroactively from 1 March 2024 following the
  Supreme Court's Advisory Opinion Reference No. 1 of 2023).
- Employee: 1.5% of gross monthly salary.
- Employer: 1.5% of gross monthly salary (matched contribution).
- Maximum: No statutory cap; rate applies to total gross including allowances.
- Exemptions: The Affordable Housing Act 2023 exempts pension income recipients
  and retired employees. Set `is_exempt=True` in KenyaHousingLevy.compute().
- KRA remittance: Employer remits combined employee + employer portion monthly
  via iTax (combined 3% of gross per employee).
- Reference: https://www.kra.go.ke/business/companies/companies-pay/paye/
  affordable-housing-levy

### NITA (National Industrial Training Authority)
- National Industrial Training Act (Cap 237, Laws of Kenya).
- NITA Levy: Employer-only. Rate: 0.5% of gross wages paid per month.
- Annual cap per employee: KES 2,500/year (2_500_00 cents).
- YTD tracking is mandatory to enforce the annual cap.
- Applies to formal private-sector employers with >= 5 employees.
- Collected by NITA via direct employer remittance (not via KRA iTax).
- Reference: https://www.nita.go.ke/levy-information/

### Annual Update Checklist

Run this checklist each financial year (Kenya FY runs 1 July – 30 June):

1. **Finance Act gazette notice**: Published June/July each year in the Kenya
   Gazette. Check for amendments to Income Tax Act bands, personal relief, or
   new levies. URL: https://www.parliament.go.ke/acts-of-parliament
2. **PAYE bands**: Update `_PAYE_BANDS` in this file with new thresholds.
   Bands are annual KES cents. Confirm with KRA iTax calculator.
3. **Personal relief**: Update `_PERSONAL_RELIEF_ANNUAL_CENTS`. Currently
   KES 28,800/year (2,400/month). Unchanged since 2020.
4. **NSSF caps**: Verify Tier I LEL (currently KES 6,000/month) and Tier II UEL
   (currently KES 36,000/month). These may be revised by the NSSF Board.
   Update `_NSSF_TIER1_CAP_MONTHLY` and `_NSSF_TIER2_CAP_MONTHLY`.
5. **SHIF rate and caps**: SHIF is new (October 2023); its rate (2.75%) and
   floor/ceiling (KES 300–1,700) may be adjusted by SHA regulations.
   Update `_SHIF_RATE`, `_SHIF_MIN_MONTHLY`, `_SHIF_MAX_MONTHLY`.
6. **Housing Levy**: Rate (1.5% each side) and any exemption category updates.
7. **NITA cap**: Annual cap (KES 2,500) is rarely changed; verify with NITA.
8. **Run tests**: `uv run pytest tests/ci/test_ke_payroll_statutory.py -v`
9. **Update EFFECTIVE_FROM**: Add an `EFFECTIVE_FROM: str = "YYYY-MM-DD"` constant
   to this module documenting the effective date of the current rate set.
10. **Notify downstream**: Payroll runs in progress must be completed before
    rate changes take effect mid-period; communicate change date to payroll team.

EFFECTIVE_FROM: str = "2024-03-01"  # Housing Levy effective March 2024
"""
from __future__ import annotations

import logging
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Monetary helpers
# ---------------------------------------------------------------------------

def _rc(d: Decimal) -> int:
	"""Round Decimal → int cents, ROUND_HALF_UP."""
	return int(d.to_integral_value(rounding=ROUND_HALF_UP))


def _clamp(value: int, lo: int, hi: int) -> int:
	return max(lo, min(hi, value))


# ---------------------------------------------------------------------------
# PAYE constants (annual, cents)
# ---------------------------------------------------------------------------

_PAYE_BANDS: list[tuple[int, int, Decimal]] = [
	# (lower_bound_annual, upper_bound_annual, rate)
	(0,          28_800_000,   Decimal("0.10")),
	(28_800_001, 38_800_000,   Decimal("0.25")),
	(38_800_001, 600_000_000,  Decimal("0.30")),
	(600_000_001, 2**62,       Decimal("0.35")),
]

_PERSONAL_RELIEF_ANNUAL_CENTS: int = 28_800_00    # 28,800 KES/year = 2,400/month
_INSURANCE_RELIEF_MAX_ANNUAL_CENTS: int = 60_000_00  # 5,000/month cap
_INSURANCE_RELIEF_RATE: Decimal = Decimal("0.15")

# NSSF
_NSSF_TIER1_CAP_MONTHLY: int = 6_000_00     # 6,000 KES/month
_NSSF_TIER2_CAP_MONTHLY: int = 36_000_00    # 36,000 KES/month
_NSSF_RATE: Decimal = Decimal("0.06")

# SHIF
_SHIF_RATE: Decimal = Decimal("0.0275")
_SHIF_MIN_MONTHLY: int = 300_00             # KES 300/month
_SHIF_MAX_MONTHLY: int = 1_700_00           # KES 1,700/month

# Housing Levy
_HOUSING_LEVY_RATE: Decimal = Decimal("0.015")

# NITA
_NITA_RATE: Decimal = Decimal("0.005")
_NITA_CAP_ANNUAL: int = 2_500_00            # KES 2,500/year


# ---------------------------------------------------------------------------
# KenyaPAYECalculator
# ---------------------------------------------------------------------------

class KenyaPAYECalculator:
	"""Kenya Revenue Authority PAYE engine — 2024/25 tax year.

	Computes monthly PAYE from monthly taxable income by annualising,
	applying progressive bands, subtracting reliefs, then dividing by
	pay_frequency_months.

	Usage::

	    calc = KenyaPAYECalculator()
	    monthly_paye = calc.compute_monthly(
	        monthly_taxable_income_cents=100_000_00,
	        monthly_insurance_premiums_cents=5_000_00,
	    )
	"""

	def compute_annual_tax_before_relief(self, annual_taxable_cents: int) -> int:
		"""Apply progressive PAYE bands to annual taxable income.

		Args:
			annual_taxable_cents: Annual taxable income in KES cents.

		Returns:
			Gross annual tax before reliefs, in KES cents.
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

	def compute_annual_relief(
		self,
		annual_insurance_premiums_cents: int = 0,
	) -> int:
		"""Total annual relief: personal + insurance.

		Args:
			annual_insurance_premiums_cents: Qualifying life/health insurance premiums paid
			    annually. Insurance relief = 15%, capped at 60,000 KES/year.

		Returns:
			Total relief in KES cents.
		"""
		personal = _PERSONAL_RELIEF_ANNUAL_CENTS
		insurance = _rc(
			Decimal(annual_insurance_premiums_cents) * _INSURANCE_RELIEF_RATE
		)
		insurance = min(insurance, _INSURANCE_RELIEF_MAX_ANNUAL_CENTS)
		return personal + insurance

	def compute_annual_paye(
		self,
		annual_taxable_income_cents: int,
		annual_insurance_premiums_cents: int = 0,
	) -> int:
		"""Annual PAYE after all reliefs. Minimum is 0 (no negative PAYE).

		Args:
			annual_taxable_income_cents: Annual gross taxable income in KES cents.
			annual_insurance_premiums_cents: Qualifying annual insurance premiums in KES cents.

		Returns:
			Annual PAYE payable in KES cents (>= 0).
		"""
		gross_tax = self.compute_annual_tax_before_relief(annual_taxable_income_cents)
		relief = self.compute_annual_relief(annual_insurance_premiums_cents)
		return max(0, gross_tax - relief)

	def compute_monthly(
		self,
		monthly_taxable_income_cents: int,
		monthly_insurance_premiums_cents: int = 0,
		pay_frequency_months: int = 1,
	) -> int:
		"""Monthly PAYE by annualising the monthly income.

		Args:
			monthly_taxable_income_cents: Monthly taxable income in KES cents.
			monthly_insurance_premiums_cents: Monthly insurance premiums in KES cents.
			pay_frequency_months: Number of months this period covers (1 = monthly).

		Returns:
			PAYE for this pay period in KES cents.
		"""
		annual = monthly_taxable_income_cents * (12 // pay_frequency_months)
		annual_premiums = monthly_insurance_premiums_cents * (12 // pay_frequency_months)
		annual_paye = self.compute_annual_paye(annual, annual_premiums)
		return _rc(Decimal(annual_paye) / (12 // pay_frequency_months))

	def compute_bonus_paye(
		self,
		regular_monthly_gross_cents: int,
		bonus_cents: int,
		ytd_paye_cents: int,
		months_elapsed: int = 0,
	) -> int:
		"""PAYE on lump-sum bonus using KRA annualisation method.

		Annualises (regular_monthly * 12 + bonus), computes annual PAYE,
		subtracts YTD PAYE already withheld. Delta is tax on the bonus.

		Args:
			regular_monthly_gross_cents: Regular monthly gross (excluding bonus).
			bonus_cents: Bonus amount this period.
			ytd_paye_cents: PAYE already withheld this tax year.
			months_elapsed: Months already paid in this tax year (for prorating).

		Returns:
			PAYE attributable to the bonus in KES cents (>= 0).
		"""
		annualised = regular_monthly_gross_cents * 12 + bonus_cents
		annual_paye = self.compute_annual_paye(annualised)
		bonus_paye = max(0, annual_paye - ytd_paye_cents)
		log.debug(
			"KenyaPAYECalculator.compute_bonus_paye: annualised=%d annual_paye=%d ytd=%d delta=%d",
			annualised, annual_paye, ytd_paye_cents, bonus_paye,
		)
		return bonus_paye


# ---------------------------------------------------------------------------
# KenyaNSSFCalculator
# ---------------------------------------------------------------------------

class KenyaNSSFCalculator:
	"""NSSF Act 2013 — Tier I and Tier II contributions.

	Pensionable pay = basic salary only (exclude non-pensionable allowances).
	Both employee and employer contribute equal amounts.

	Returns a dict with keys:
	  employee_tier1_cents, employer_tier1_cents,
	  employee_tier2_cents, employer_tier2_cents,
	  employee_total_cents, employer_total_cents
	"""

	def compute(self, pensionable_pay_cents: int) -> dict[str, int]:
		"""Compute NSSF Tier I and Tier II for a given month.

		Args:
			pensionable_pay_cents: Basic (pensionable) salary in KES cents for the month.

		Returns:
			Dict with employee and employer shares for Tier I and Tier II.
		"""
		assert pensionable_pay_cents >= 0, "pensionable_pay_cents must be non-negative"

		# Tier I: 6% on first 6,000 KES
		tier1_base = min(pensionable_pay_cents, _NSSF_TIER1_CAP_MONTHLY)
		tier1_each = _rc(Decimal(tier1_base) * _NSSF_RATE)

		# Tier II: 6% on amount between 6,000 and 36,000 KES
		tier2_excess = max(0, pensionable_pay_cents - _NSSF_TIER1_CAP_MONTHLY)
		tier2_base = min(tier2_excess, _NSSF_TIER2_CAP_MONTHLY - _NSSF_TIER1_CAP_MONTHLY)
		tier2_each = _rc(Decimal(tier2_base) * _NSSF_RATE)

		return {
			"employee_tier1_cents": tier1_each,
			"employer_tier1_cents": tier1_each,
			"employee_tier2_cents": tier2_each,
			"employer_tier2_cents": tier2_each,
			"employee_total_cents": tier1_each + tier2_each,
			"employer_total_cents": tier1_each + tier2_each,
		}


# ---------------------------------------------------------------------------
# KenyaSHIFCalculator
# ---------------------------------------------------------------------------

class KenyaSHIFCalculator:
	"""Social Health Insurance Fund (SHIF) — Social Health Insurance Act 2023.

	Replaces NHIF from October 2023.
	Rate: 2.75% of gross monthly pay.
	Floor: KES 300/month (300_00 cents).
	Ceiling: KES 1,700/month (1_700_00 cents).
	Employee-only levy (no employer match).
	"""

	def compute(self, gross_cents: int) -> int:
		"""Compute monthly SHIF deduction.

		Args:
			gross_cents: Gross monthly pay in KES cents.

		Returns:
			SHIF contribution in KES cents.
		"""
		assert gross_cents >= 0, "gross_cents must be non-negative"
		raw = _rc(Decimal(gross_cents) * _SHIF_RATE)
		return _clamp(raw, _SHIF_MIN_MONTHLY, _SHIF_MAX_MONTHLY)


# ---------------------------------------------------------------------------
# KenyaHousingLevy
# ---------------------------------------------------------------------------

class KenyaHousingLevy:
	"""Affordable Housing Levy — Finance Act 2023.

	Employee: 1.5% of gross monthly salary.
	Employer: 1.5% of gross monthly salary (matched contribution).

	Exemptions (checked via employee attribute flag):
	  - Pension income recipients
	  - Retired employees

	Returns dict: {employee_cents, employer_cents}
	"""

	def compute(
		self,
		gross_cents: int,
		is_exempt: bool = False,
	) -> dict[str, int]:
		"""Compute Housing Levy for employee and employer.

		Args:
			gross_cents: Gross monthly pay in KES cents.
			is_exempt: True for pension/retiree exempt categories.

		Returns:
			Dict with employee_cents and employer_cents.
		"""
		assert gross_cents >= 0, "gross_cents must be non-negative"
		if is_exempt:
			return {"employee_cents": 0, "employer_cents": 0}

		each = _rc(Decimal(gross_cents) * _HOUSING_LEVY_RATE)
		return {"employee_cents": each, "employer_cents": each}


# ---------------------------------------------------------------------------
# KenyaNITALevy
# ---------------------------------------------------------------------------

class KenyaNITALevy:
	"""National Industrial Training Authority levy.

	Employer-only: 0.5% of gross monthly pay.
	Annual cap: KES 2,500/year (2_500_00 cents).
	YTD tracking is required — pass ytd_nita_cents to enforce the cap.
	"""

	def compute(
		self,
		gross_cents: int,
		ytd_nita_cents: int = 0,
	) -> int:
		"""Compute NITA levy for the current pay period.

		Args:
			gross_cents: Gross monthly pay in KES cents.
			ytd_nita_cents: NITA already collected this tax year for this employee.

		Returns:
			NITA levy for this period (may be zero if annual cap already reached).
		"""
		assert gross_cents >= 0, "gross_cents must be non-negative"
		assert ytd_nita_cents >= 0, "ytd_nita_cents must be non-negative"

		remaining_cap = max(0, _NITA_CAP_ANNUAL - ytd_nita_cents)
		if remaining_cap <= 0:
			return 0

		raw = _rc(Decimal(gross_cents) * _NITA_RATE)
		return min(raw, remaining_cap)


# ---------------------------------------------------------------------------
# KenyaTaxCalculator — composite, satisfies tax_calculator protocol
# ---------------------------------------------------------------------------

class KenyaTaxCalculator:
	"""Composite Kenya statutory calculator for injection into PayrollService.

	Implements the tax_calculator protocol expected by PayrollService.calculate_payrun():
	  .compute(gross_cents, employee_id, session) -> dict

	The returned dict matches PayrollService's tax_result keys plus Kenya-specific
	statutory breakdown used by calculate_payrun() KE branch:
	  income_tax_cents          — PAYE
	  ni_employee_cents         — NSSF employee total (Tier I + II)
	  pension_employee_cents    — 0 (NSSF IS the pension; set by ni_employee)
	  pension_employer_cents    — NSSF employer total
	  nssf_tier1_employee       — Tier I employee
	  nssf_tier1_employer       — Tier I employer
	  nssf_tier2_employee       — Tier II employee
	  nssf_tier2_employer       — Tier II employer
	  shif_cents                — SHIF employee deduction
	  housing_levy_employee     — Housing Levy employee
	  housing_levy_employer     — Housing Levy employer
	  nita_cents                — NITA employer levy (this period)
	  pensionable_pay_cents     — basic salary used for NSSF computation

	The caller (PayrollService.calculate_payrun) is responsible for pulling
	employee attributes (basic salary, insurance premiums, YTD NITA, exempt flags)
	from the employee_data dict before calling this method.
	"""

	def __init__(
		self,
		paye: KenyaPAYECalculator | None = None,
		nssf: KenyaNSSFCalculator | None = None,
		shif: KenyaSHIFCalculator | None = None,
		housing: KenyaHousingLevy | None = None,
		nita: KenyaNITALevy | None = None,
	) -> None:
		self._paye = paye or KenyaPAYECalculator()
		self._nssf = nssf or KenyaNSSFCalculator()
		self._shif = shif or KenyaSHIFCalculator()
		self._housing = housing or KenyaHousingLevy()
		self._nita = nita or KenyaNITALevy()

	def compute(
		self,
		gross_cents: int,
		employee_id: str,
		session: Any,
		*,
		pensionable_pay_cents: int | None = None,
		monthly_insurance_premiums_cents: int = 0,
		ytd_nita_cents: int = 0,
		housing_exempt: bool = False,
	) -> dict[str, int]:
		"""Compute all Kenya statutory deductions for one employee for one month.

		Args:
			gross_cents: Total gross monthly pay in KES cents.
			employee_id: Employee UUID (for audit/logging).
			session: SQLAlchemy session (unused here; kept for protocol compat).
			pensionable_pay_cents: Basic salary only for NSSF; defaults to gross_cents.
			monthly_insurance_premiums_cents: Qualifying insurance premiums this month.
			ytd_nita_cents: Year-to-date NITA collected for this employee.
			housing_exempt: True if employee is exempt from Housing Levy.

		Returns:
			Dict with all statutory deduction amounts.
		"""
		assert gross_cents >= 0, "gross_cents must be non-negative"
		if pensionable_pay_cents is None:
			pensionable_pay_cents = gross_cents

		# PAYE — on total gross (BIK added upstream if applicable)
		paye = self._paye.compute_monthly(
			monthly_taxable_income_cents=gross_cents,
			monthly_insurance_premiums_cents=monthly_insurance_premiums_cents,
		)

		# NSSF
		nssf_result = self._nssf.compute(pensionable_pay_cents)

		# SHIF
		shif = self._shif.compute(gross_cents)

		# Housing Levy
		housing_result = self._housing.compute(gross_cents, is_exempt=housing_exempt)

		# NITA
		nita = self._nita.compute(gross_cents, ytd_nita_cents=ytd_nita_cents)

		log.debug(
			"KenyaTaxCalculator.compute: emp=%s gross=%d paye=%d nssf_emp=%d shif=%d housing_emp=%d nita=%d",
			employee_id, gross_cents, paye,
			nssf_result["employee_total_cents"], shif,
			housing_result["employee_cents"], nita,
		)

		return {
			# Core protocol keys
			"income_tax_cents": paye,
			"ni_employee_cents": nssf_result["employee_total_cents"],
			"pension_employee_cents": 0,   # NSSF is the statutory pension
			"pension_employer_cents": nssf_result["employer_total_cents"],
			# Kenya-specific breakdown
			"nssf_tier1_employee": nssf_result["employee_tier1_cents"],
			"nssf_tier1_employer": nssf_result["employer_tier1_cents"],
			"nssf_tier2_employee": nssf_result["employee_tier2_cents"],
			"nssf_tier2_employer": nssf_result["employer_tier2_cents"],
			"shif_cents": shif,
			"housing_levy_employee": housing_result["employee_cents"],
			"housing_levy_employer": housing_result["employer_cents"],
			"nita_cents": nita,
			"pensionable_pay_cents": pensionable_pay_cents,
		}


__all__ = [
	"KenyaPAYECalculator",
	"KenyaNSSFCalculator",
	"KenyaSHIFCalculator",
	"KenyaHousingLevy",
	"KenyaNITALevy",
	"KenyaTaxCalculator",
]
