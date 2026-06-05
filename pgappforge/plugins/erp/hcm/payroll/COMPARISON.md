# payroll — World-Class HCM Comparison
Score: 34/100

Benchmarked against: SAP SuccessFactors, Workday HCM, Oracle HCM Cloud, ADP Workforce Now, BambooHR, Sage HR.

---

## Current Capabilities

- Immutable ledger pattern: Payslips and PayslipLines are never mutated post-PAID; reversals insert negated rows.
- Clean state machine: DRAFT → CALCULATED → APPROVED → PAID with enforced transition guards.
- Decimal arithmetic throughout; integer-cent storage; ROUND_HALF_UP — no float contamination.
- ISO 20022 PAIN.001.001.03 XML skeleton for bank EFT dispatch.
- Double-entry GL journal on `post_to_gl()`: DR Salary Expense / CR Net Pay Clearing + PAYE Payable + Pension Payable.
- `tax_calculator` injection point: pluggable jurisdiction engine, though no built-in Kenya engine exists.
- Multi-tenant architecture with `tenant_id` on every table.
- PayrollRun types: REGULAR, OFF_CYCLE, BONUS, TERMINATION.
- Event emission on every state transition (PayrollRunCalculatedEvent, ApprovedEvent, PaidEvent, GLPostedEvent, PayslipReversedEvent).
- Annual `statutory_report()` aggregates PAID runs by entity/year.
- JSONB `periods` on PayrollCalendar for pre-generated pay schedules.
- Composite indexes on hot paths (tenant+status, employee+jurisdiction+effective_from).
- `reverse_payslip()` creates negated-amount correction payslip inline with reason.

---

## Gaps

### [CRITICAL] No Kenya PAYE engine — tax computation is a flat 20% fallback

Missing: Zero implementation of KRA PAYE progressive brackets for KE jurisdiction.
Impl: Add `KenyaPAYECalculator` class in a new `pgappforge/plugins/erp/hcm/payroll/ke/` package. Apply 2024/25 KRA bands against monthly taxable income (annual gross / pay_frequency_months): 0–288,000 KES @ 10%, 288,001–388,000 @ 25%, 388,001–6,000,000 @ 30%, >6,000,000 @ 35%. Subtract personal relief (KES 2,400/month = 28,800/year) and insurance relief (15% of qualifying premiums capped at 5,000/month) before arriving at tax payable. Register as the default `tax_calculator` when `jurisdiction_code == "KE"`.
Found in: ADP Workforce Now (Kenya localisation), Sage HR Kenya, Oracle HCM Kenya Payroll.

### [CRITICAL] NSSF Act 2013 Tier I/II not implemented

Missing: No NSSF contribution logic; `national_insurance_cents` is computed as a flat 12% of gross, which is wrong for Kenya.
Impl: Tier I: 6% of pensionable pay up to KES 6,000/month (employee + employer each). Tier II: 6% of pensionable pay between KES 6,001 and KES 36,000/month (employee + employer each). Pensionable pay = basic salary only (exclude non-pensionable allowances per the Act). Model as separate `PayslipLine` rows with `line_type="NSSF_TIER_I"` / `"NSSF_TIER_II"` so the remittance report can split them. Store employer shares as `is_employer_cost=True` lines.
Found in: Sage HR Kenya, ADP Kenya, Oracle HCM Cloud Kenya.

### [CRITICAL] SHIF/NHIF contribution absent

Missing: No Social Health Insurance Fund deduction; the 2.75% of gross (min KES 300, max KES 1,700/month) introduced under the Social Health Insurance Act 2023 is not modelled.
Impl: Add `KenyaSHIFCalculator` helper: `shif = clamp(round_half_up(gross * 0.0275), 300_00, 1_700_00)` (cents). Emit as `PayslipLine(line_type="NHIF_SHIF")`. Include SHIF as a separate CR line in `post_to_gl()` — `2210: SHIF Payable`. Note: SHIF is employee-only; no employer match.
Found in: ADP Kenya, Workday Kenya localisation, Sage HR.

### [CRITICAL] Housing Levy not implemented

Missing: The Affordable Housing Levy (1.5% employee + 1.5% employer of gross salary) introduced by the Finance Act 2023 is absent.
Impl: Employee deduction: `round_half_up(gross * 0.015)`. Employer contribution: same amount, `is_employer_cost=True`. Add GL lines: `2220: Housing Levy Payable (Employee)` and `5020: Housing Levy Expense (Employer)`. Exempt categories (pension income, retirees) should be flagged via an employee attribute checked at calculation time.
Found in: Sage HR Kenya, ADP Kenya, Oracle HCM Cloud.

### [CRITICAL] NITA Levy absent

Missing: National Industrial Training Authority levy (0.5% of gross, capped at KES 2,500/year = KES 208.33/month) is not modelled.
Impl: Track year-to-date NITA levy per employee in a `YTDAccumulator` table (or JSONB on the payslip) so the monthly cap of 208.33 is not breached mid-year when an employee gets a bonus. Emit as `PayslipLine(line_type="NITA")` with `is_employer_cost=True` (employer-only levy).
Found in: Sage HR Kenya, local payroll vendors (Britam, KCB payroll).

### [HIGH] No P9 form generation (KRA annual employee tax return)

Missing: No function to generate the KRA P9 certificate of earnings per employee per year.
Impl: Add `generate_p9(employee_id, year, session) -> dict` to `PayrollService`. Aggregate from `PayslipLine` rows grouped by `employee_id` and year (join via `PayrollRun.period_start`). Required fields: employer PIN, employee PIN/ID, months employed, basic salary, benefits-in-kind, gross pay, tax charged, personal relief, PAYE paid each month. Return a structured dict consumable by a Jinja2/WeasyPrint PDF template. The 12-row monthly breakdown must match KRA iTax P9 column layout exactly.
Found in: Sage HR Kenya, ADP Kenya, Oracle HCM Kenya, all KRA-compliant payroll systems.

### [HIGH] No monthly PAYE return in KRA iTax CSV format

Missing: `statutory_report()` returns an internal summary dict; it does not produce the KRA iTax-compatible PAYE return file.
Impl: Add `generate_paye_return(entity_id, period_start, period_end, session) -> str`. Output CSV matching the KRA iTax PAYE Monthly Return layout: employer PIN, return period, employee name, ID/passport, KRA PIN, gross pay, non-cash benefits, pension contribution, owner-occupied interest, personal relief, insurance relief, taxable pay, tax on taxable pay, monthly personal relief, tax payable, tax withheld. One row per employee. File encoding: UTF-8 BOM (KRA iTax requirement).
Found in: ADP Kenya, Sage HR Kenya, all KRA-registered payroll bureaus.

### [HIGH] No Benefit-in-Kind (BIK) computation

Missing: Company car, medical cover, housing allowance, and other non-cash benefits are not modelled as taxable earnings.
Impl: Add `BenefitInKind` model with fields: `employee_id`, `benefit_type` (CAR | HOUSING | MEDICAL | OTHER), `monthly_value_cents`, `is_taxable`, `effective_from`. In `calculate_payrun()`, load active BIK records for each employee and add taxable BIK to `taxable_gross` before PAYE calculation (but exclude from `pensionable_pay` for NSSF). Non-taxable BIK still appears on the payslip as an informational line. Workday/SAP model this as a separate BIK register feeding into gross-for-tax.
Found in: SAP SuccessFactors, Workday HCM, Oracle HCM Cloud, ADP.

### [HIGH] Bank EFT file: IBAN-only; no local Kenya bank formats (KCB/Equity/Stanbic CSV)

Missing: The ISO 20022 PAIN.001 generator assumes IBAN everywhere; Kenyan banks use local account numbers + branch sort codes and have proprietary CSV bulk-payment formats.
Impl: Add `generate_kenya_bank_file(payrun_id, bank_code, session) -> str` with a `bank_code` dispatch table: `"KCB"`, `"EQUITY"`, `"STANBIC"`, `"COOPERATIVE"`. Each bank has a fixed CSV column layout (account number, bank branch code, amount, narration, employee name). Store employee `bank_name`, `bank_branch_code`, `bank_account_number` as separate columns (not IBAN) in the payslip snapshot. Keep PAIN.001 for SWIFT/international transfers.
Found in: ADP Kenya, Sage HR Kenya, local payroll vendors.

### [HIGH] No payslip PDF generation or email dispatch

Missing: No PDF rendering of individual payslips; no mechanism to email payslips to employees.
Impl: Add `generate_payslip_pdf(payslip_id, session) -> bytes` using WeasyPrint + a Jinja2 HTML template. Template must show: company logo, employee name/ID, period, earnings table, deductions table (PAYE/NSSF Tier I/II/SHIF/Housing Levy/NITA itemised), gross, net, YTD columns, employer statutory contributions. Add `dispatch_payslips(payrun_id, session, mailer)` that iterates PAID payslips, generates PDFs, and sends via the `mailer` interface (pluggable SMTP/SendGrid). Password-protect PDFs with last 4 digits of employee ID (standard Kenya practice).
Found in: ADP Workforce Now, BambooHR, Sage HR, Workday (employee self-service PDF).

### [HIGH] GL journal missing Kenya-specific statutory liability accounts

Missing: `post_to_gl()` collapses PAYE + NI into account `2100` and all pension into `2200`; Kenya requires separate GL lines for PAYE, NSSF Tier I, NSSF Tier II, SHIF, Housing Levy (employee), Housing Levy (employer), and NITA.
Impl: Expand `post_to_gl()` credit lines: `2100 PAYE Payable`, `2210 NSSF Tier I Payable`, `2211 NSSF Tier II Payable`, `2215 SHIF Payable`, `2220 Housing Levy Payable (Employee)`, `5020 Housing Levy Expense (Employer)` DR, `5025 NITA Levy Expense` DR, `2230 NITA Payable`. Drive amounts from typed `PayslipLine` aggregates (join on `line_type`) rather than the single `total_employee_tax_cents` aggregate which cannot distinguish between levy types.
Found in: SAP FI-Payroll integration, Workday Financials, Oracle Fusion Financials.

### [MEDIUM] No year-to-date accumulator table

Missing: No YTD tracking per employee per tax year; NITA cap enforcement, PAYE cumulative tax table method, and P9 generation all require monthly YTD data.
Impl: Add `PayrollYTD` model: `(tenant_id, employee_id, tax_year, month, gross_cents, taxable_gross_cents, paye_cents, nssf_tier1_cents, nssf_tier2_cents, shif_cents, housing_levy_cents, nita_cents, net_cents)`. Populated by `calculate_payrun()` as a side-effect. Index on `(tenant_id, employee_id, tax_year)`. Query in `generate_p9()` and in the NITA cap check. SAP and Workday maintain equivalent wage-type cumulation tables.
Found in: SAP SuccessFactors (Payroll Wage Types), Workday (Pay Accumulator), Oracle Payroll Balances, ADP.

### [MEDIUM] No 13th month / bonus processing with correct tax treatment

Missing: BONUS payroll type exists as an enum but no special tax treatment is applied — Kenya Revenue Authority requires annual bonus to be annualised for PAYE computation (spread across 12 months equivalent).
Impl: In `KenyaPAYECalculator`, detect `payroll_type == "BONUS"`. Annualise the bonus: `annualised = regular_monthly_gross * 12 + bonus_amount`. Compute tax on annualised figure, subtract tax already paid YTD, and the delta is the bonus PAYE. This matches KRA's "month of payment" method for lump-sum payments. Expose as a separate `compute_bonus_paye(employee_id, bonus_cents, ytd_paye_cents, year, session)` method.
Found in: ADP Workforce Now, Workday (Supplemental Rate), Oracle HCM Cloud Kenya.

### [MEDIUM] No gross-to-net reconciliation report

Missing: No report that reconciles per-employee and aggregate gross-to-net showing each deduction type as a column, with variances vs. prior period.
Impl: Add `gross_to_net_report(payrun_id, session) -> list[dict]`. For each payslip in the run, return: employee_id, gross, basic_pay, allowances, overtime, bonus, paye, nssf_tier1, nssf_tier2, shif, housing_levy_nita, other_deductions, net_pay. Add a `prior_payrun_id` optional parameter; if supplied, compute month-over-month variance columns. Output should be exportable as Excel (openpyxl) via the reporting plugin. ADP calls this the "Register Report"; Workday calls it the "Payroll Results Summary".
Found in: ADP Workforce Now (Payroll Register), Workday, SAP SuccessFactors, Oracle.

### [MEDIUM] Payslip currency hardcoded to "USD" in events and GL

Missing: `calculate_payrun()` defaults currency to `"USD"`; event emission in `calculate_payrun` and `mark_paid` hardcodes `currency="USD"`. Kenya operations are KES.
Impl: Derive currency from the PayrollCalendar or a legal entity `default_currency_code` field. Pass `currency_code` through all events. The `post_to_gl()` journal should tag amounts with the run's actual currency. Multi-currency payrolls (expats paid in USD) need an FX rate column on `Payslip` to convert employer cost to entity functional currency for GL posting.
Found in: SAP SuccessFactors (multiple currency support), Workday, Oracle HCM Cloud.

### [MEDIUM] No employee self-service portal integration or payslip access audit trail

Missing: No model or API endpoint for employees to retrieve their own payslips; no access log for payslip downloads (required under Kenya Data Protection Act 2019).
Impl: Add `PayslipAccessLog` model: `(id, tenant_id, payslip_id, accessed_by, access_type [VIEW|DOWNLOAD|EMAIL], ip_address, accessed_at)`. Expose a `GET /api/v1/payslips/{id}/download` endpoint that checks the requesting user is the owning employee (or has HR role), generates PDF, logs the access, and returns the PDF. BambooHR and Workday ESS both implement this pattern.
Found in: BambooHR (Self-Service), Workday ESS, ADP Workforce Now ESS, SAP SuccessFactors.

### [MEDIUM] No multi-approver workflow or payroll audit trail

Missing: Single `approved_by` field; no history of who reviewed, queried, or unlocked a payrun. Regulatory audit (KRA, NITA inspector) requires full change log.
Impl: Add `PayrollRunAuditEvent` table: `(id, tenant_id, payrun_id, event_type [DRAFT|LOCK|UNLOCK|APPROVE|REJECT|PAID|REVERSED|GL_POSTED], actor_id, actor_role, comment, created_at)`. Write one row at every state transition in `PayrollService`. Optionally model a two-person rule: primary approver + secondary sign-off, both required before status advances to APPROVED. Workday enforces configurable approval chains via Business Process Framework.
Found in: Workday (Business Process), SAP SuccessFactors (Approval Workflows), Oracle HCM Cloud, ADP.

### [LOW] `reverse_payslip()` restricted to PAID-only; no mid-period correction path

Missing: Only PAID payslips can be reversed; a CALCULATED or APPROVED payslip with an error requires manual DB intervention.
Impl: Allow reversal of APPROVED payslips (before bank dispatch) by adding `"APPROVED"` to the allowed statuses check. For CALCULATED payslips, `calculate_payrun()` already deletes and recalculates lines — document this as the correction path and add a `recalculate_payslip(payslip_id, corrected_earnings, session)` convenience method that re-runs the per-employee calculation block for a single payslip without re-running the entire payrun.
Found in: ADP, Sage HR (payslip unlock), Oracle Payroll (retroactive pay).

### [LOW] PAIN.001 XML is a structural skeleton, not a certifiable output

Missing: The ISO 20022 XML generator uses string concatenation and hardcodes `<DbtrAcct>` as `COMPANY-PAYROLL`; it is not certifiable for actual bank submission.
Impl: Integrate `python-iso20022` or `lxml` with the official pain.001.001.03 XSD. Source company bank details from a `CompanyBankAccount` model. Validate the generated XML against the XSD before returning. Add `<Dbtr><Nm>`, `<DbtrAgt><FinInstnId><BIC>`, and proper `<PmtTpInf>` elements required by CBK's KEPSS (Kenya Electronic Payment and Settlement System) gateway. File this under a `SWIFT` feature flag so domestic EFT and SWIFT paths are independent.
Found in: ADP (NACHA/SWIFT certified outputs), Oracle Financials (SWIFT MT103), SAP TRM.
