# personnel — World-Class HCM Comparison
Score: 31/100

Benchmarked against: SAP SuccessFactors, Workday HCM, Oracle HCM Cloud, ADP Workforce Now, BambooHR, Sage HR

---

## Current Capabilities

- Employee master record with org placement (entity, org unit, position, manager chain)
- Employment lifecycle states: ACTIVE, ON_LEAVE, TERMINATED, RETIRED
- Employment types: FULL_TIME, PART_TIME, CONTRACT, CASUAL
- Probation end date field on Employee
- Termination with type (VOLUNTARY, INVOLUNTARY, REDUNDANCY, RETIREMENT), reason, rehire eligibility
- Cross-entity transfer with position vacate/fill integration via OrgService
- Immutable compensation ledger (insert-only EmployeeCompensation rows, effective-dated)
- Pay types: SALARY, HOURLY, COMMISSION; frequencies: ANNUAL, MONTHLY, BIWEEKLY, HOURLY
- Grade code on compensation row (denormalised snapshot)
- Application-level encryption for national_id, tax_id, bank IBAN
- Document vault with metadata (type, filename, object-store URL, issued/expiry dates, verified flag)
- Expiring documents scan within configurable window
- Headcount summary by employment_type × employment_status per entity
- Domain events: EmployeeHiredEvent, EmployeeTerminatedEvent, EmployeeTransferredEvent, CompensationChangedEvent, DocumentVerifiedEvent
- Stateless service with explicit session — caller owns transaction boundary

---

## Gaps

### [CRITICAL] Employment Contract Lifecycle Model Missing
Missing: No contract entity — offer, acceptance, probation confirmation, and contract amendments are unmodelled.
Impl: Add `EmploymentContract` table (`hcm_per_contract`) with status machine: DRAFT → OFFERED → ACCEPTED → ACTIVE → AMENDED → TERMINATED. Link to `Employee.id`, store `contract_type` (PERMANENT, FIXED_TERM, CASUAL, INTERNSHIP), `start_date`, `end_date` (nullable), `notice_period_days` (Kenya Employment Act s.35 mandates 28 days minimum for monthly-paid staff). Add `confirm_probation(employee_id, session)` method that transitions Employee status and records contract confirmation date. Found in: SAP SuccessFactors (Contract Management), Workday (Worker Contract), Oracle HCM Cloud (HR Contract).

### [CRITICAL] Kenya Employment Act Compliance — Notice Periods Not Enforced
Missing: Termination accepts any `termination_date` with no statutory notice period validation.
Impl: On `terminate_employee`, compute `minimum_notice_days` from `employment_type` and `pay_frequency` per Employment Act 2007 s.35 (monthly-paid = 28 days, weekly = 7 days, casual = same day). If `termination_date - today < minimum_notice_days` and `termination_type != "REDUNDANCY"` and no `notice_waived=True` flag, raise `PersonnelServiceError`. For REDUNDANCY, enforce s.40 — 1 month notice or pay in lieu. Store `notice_period_days` and `notice_pay_in_lieu_cents` on the termination record. Found in: ADP Workforce Now (statutory compliance engine), SAP SuccessFactors (country-specific HR localisation).

### [CRITICAL] Exit / Offboarding Checklist Not Modelled
Missing: No structured exit process — clearance checklist, exit interview, final pay computation, and certificate of service are absent.
Impl: Add `EmployeeExit` table (`hcm_per_exit`) linked to Employee with status machine (INITIATED → IN_PROGRESS → CLEARED → CLOSED). Store JSON checklist items (`clearance_items: JSONB` — IT equipment, access cards, loans, library books, SACCO deductions) with per-item `cleared_by` and `cleared_at`. Add `initiate_exit(employee_id, data, session)` that creates the exit record when termination is recorded. Add `clear_exit_item(exit_id, item_key, session)` and `close_exit(exit_id, session)` which validates all items cleared before allowing final payroll run. Found in: Workday (Offboarding), Oracle HCM Cloud (Separation Management), BambooHR (Offboarding checklists).

### [CRITICAL] Disciplinary Process Not Modelled
Missing: No disciplinary case entity — verbal warnings, written warnings, show-cause notices, hearings, and outcomes are untracked.
Impl: Add `DisciplinaryCase` (`hcm_per_disciplinary_case`) with status: OPEN → SHOW_CAUSE_ISSUED → HEARING_SCHEDULED → HEARING_COMPLETE → CLOSED. Store `offence_description`, `case_type` (VERBAL_WARNING, WRITTEN_WARNING, FINAL_WARNING, DISMISSAL), `hearing_date`, `outcome`, `outcome_date`, `presiding_officer_id`. Add `DisciplinaryCaseDocument` child table for letters. Service methods: `open_disciplinary_case`, `issue_show_cause`, `record_hearing_outcome`. Enforce that DISMISSAL outcome must precede `terminate_employee(termination_type=INVOLUNTARY)` — otherwise HR can bypass due process. Found in: SAP SuccessFactors (Disciplinary Actions), Oracle HCM Cloud (Work Relationship), Sage HR (Disciplinary module).

### [CRITICAL] Grievance Management Workflow Missing
Missing: No grievance case entity — employees have no formal channel to raise complaints with tracked resolution.
Impl: Add `GrievanceCase` (`hcm_per_grievance`) with status: FILED → ACKNOWLEDGED → UNDER_REVIEW → RESOLVED → ESCALATED → CLOSED. Store `grievance_type` (HARASSMENT, DISCRIMINATION, UNSAFE_CONDITIONS, COMPENSATION, OTHER), `filed_by_employee_id`, `respondent_employee_id` (nullable), `assigned_to_id`, `resolution_notes`. Kenya Employment Act s.47 requires internal grievance procedures. Target resolution SLA stored as `due_date`; overdue cases surfaced via `overdue_grievances(tenant_id, session)` query. Found in: Workday (Grievance Management), SAP SuccessFactors (Employee Relations).

### [HIGH] Onboarding Checklist Not Modelled
Missing: No structured onboarding workflow — document collection, induction schedule, equipment allocation, and buddy assignment are absent.
Impl: Add `OnboardingPlan` (`hcm_per_onboarding`) created automatically by `hire_employee` (hook pattern, optional). Store `template_id` (FK to configurable onboarding templates), `assigned_buddy_id`, `induction_date`, `checklist_items: JSONB` (each item: `key`, `label`, `due_days_from_start`, `owner_role`, `completed_at`, `completed_by`). `complete_onboarding_item(plan_id, item_key, session)` closes individual tasks. Fire `OnboardingCompletedEvent` when all items done. Found in: BambooHR (Onboarding), Workday (Onboarding worklets), ADP Workforce Now.

### [HIGH] Position-Based Headcount Control Not Enforced at Hire
Missing: `hire_employee` calls `OrgService().fill_position` but silently swallows exceptions — headcount limits are not enforced as a hard gate.
Impl: Before inserting Employee, call `OrgService().position_headcount_check(position_id, session)` and raise `PersonnelServiceError("Position headcount limit reached")` if approved headcount is full. Remove the bare `except Exception: log.warning(...)` swallow on position fill — a failed fill should roll back the hire or at minimum return a structured warning the caller can inspect. Add `headcount_budget` (approved vs actual) to the return of `headcount_summary`. Found in: SAP SuccessFactors (Position Management), Workday (Staffing Model), Oracle HCM Cloud (Headcount Budget).

### [HIGH] Job Grades / Salary Bands Not Modelled
Missing: `grade_code` is a free-text denormalised snapshot — no `JobGrade` entity enforcing min/max salary band per grade.
Impl: Add `JobGrade` table (`hcm_org_job_grade`: `grade_code PK`, `label`, `min_amount_cents`, `max_amount_cents`, `currency_code`, `effective_date`). In `record_compensation`, when `grade_code` is provided, validate `min_amount_cents <= amount_cents <= max_amount_cents`; raise `CompensationError("Amount outside grade band")` if violated. Add `grade_band_check_bypass` flag for approved exceptions (stored with approver and reason). Found in: SAP SuccessFactors (Compensation Grades), Workday (Compensation Grades), Oracle HCM Cloud (Salary Ranges).

### [HIGH] Probation Confirmation Service Method Missing
Missing: `probation_end_date` is stored but there is no `confirm_probation` / `extend_probation` / `fail_probation` service method.
Impl: Add `confirm_probation(employee_id, confirmed: bool, extension_days: int | None, session)`. If `confirmed=True`, emit `ProbationConfirmedEvent` and (if contract model exists) transition contract to ACTIVE. If `confirmed=False`, trigger disciplinary/termination path. If `extension_days`, compute new `probation_end_date` and validate against Kenya statutory maximum (90 days extendable to 6 months per Employment Act s.42). Add `employees_on_probation(tenant_id, session)` query returning employees where `probation_end_date >= today` and `employment_status = ACTIVE`. Found in: Workday, SAP SuccessFactors, Sage HR.

### [HIGH] Leave Integration Hook Missing from Employment Lifecycle
Missing: `employment_status = ON_LEAVE` is a valid enum value but no service method sets it, and leave balance entitlement seeding on hire is absent.
Impl: Add `go_on_leave(employee_id, leave_type, start_date, expected_return_date, session)` and `return_from_leave(employee_id, actual_return_date, session)` methods that transition `employment_status`. On `hire_employee`, emit `EmployeeEntitlementsInitEvent` so the leave plugin can seed statutory balances: 21 days annual leave, 90 days maternity, 14 days paternity (Kenya Employment Act ss.28–30). The personnel service should not own leave balances, but must fire the event. Found in: all six benchmark systems.

### [HIGH] Background Check Integration Hook Absent
Missing: No pre-hire or post-offer background check state on Employee or as a linked entity.
Impl: Add `background_check_status` column on Employee: NOT_REQUIRED | PENDING | PASSED | FAILED | WAIVED. Add `update_background_check(employee_id, status, provider_ref, session)` service method. Block `hire_employee` from setting `employment_status = ACTIVE` if tenant config `REQUIRE_BACKGROUND_CHECK = True` and status is not PASSED or WAIVED. Store `background_check_provider` and `background_check_ref` for audit. Found in: Workday (Background Check Integration), ADP Workforce Now, Oracle HCM Cloud.

### [MEDIUM] Compensation Approval Workflow Not Enforced
Missing: `approved_by` on EmployeeCompensation is nullable and purely informational — no approval gate exists.
Impl: Add `approval_status` column: PENDING | APPROVED | REJECTED. `record_compensation` inserts with status PENDING when amount exceeds a configurable threshold (`COMP_APPROVAL_THRESHOLD_CENTS`). Add `approve_compensation(comp_id, approver_id, session)` and `reject_compensation(comp_id, approver_id, reason, session)`. Only APPROVED records are considered by `current_compensation`. Emit `CompensationApprovedEvent`. Found in: SAP SuccessFactors (Compensation Planning), Workday (Business Process Framework), Oracle HCM Cloud.

### [MEDIUM] Redundancy / WIBA / Statutory Severance Not Computed
Missing: REDUNDANCY termination type exists but severance entitlement (Kenya Employment Act s.40: 15 days per year of service) is not calculated.
Impl: Add `compute_redundancy_pay(employee_id, termination_date, session) -> dict` that calculates years of service from `start_date`, computes `severance_days = years * 15`, `severance_amount_cents = (monthly_salary / 30) * severance_days`. Store result on `EmployeeExit.severance_amount_cents`. Also add WIBA (Work Injury Benefits Act) flag on Employee for industrial injury claims that may alter exit pay. Found in: ADP Workforce Now (statutory severance), SAP SuccessFactors (KE localisation), Sage HR Kenya edition.

### [MEDIUM] Employee Number Auto-Generation Missing
Missing: `employee_number` is required but caller-supplied — no service-side auto-generation with configurable format per entity.
Impl: Add `generate_employee_number(entity_id, session) -> str` producing a format like `KE-{entity_code}-{seq:05d}` using a PostgreSQL sequence per entity (`hcm_per_emp_seq_{entity_id_short}`). `hire_employee` should call this when `employee_number` is absent in data, not raise a validation error. Store format template in entity config. Found in: Workday (auto-sequenced Worker ID), Oracle HCM Cloud (Person Number), ADP Workforce Now.

### [MEDIUM] Rehire / Returning Employee Detection Missing
Missing: `rehire_eligible = True` is stored but no service method detects a returning employee on re-hire or links to prior employment records.
Impl: Add `find_prior_employment(party_id, tenant_id, session) -> list[Employee]` that returns terminated records for the same `party_id`. `hire_employee` should accept `prior_employee_id` to link new engagement to history (seniority continuity for leave accrual). Emit `EmployeeRehiredEvent` with prior service years for downstream leave/payroll to apply. Found in: Workday (Rehire), SAP SuccessFactors (Global Assignment), Oracle HCM Cloud.

### [MEDIUM] Cost Center Not Validated Against Chart of Accounts
Missing: `cost_center_code` is free text with no FK or validation against a GL/finance plugin.
Impl: Add soft-validation: call `FinanceService().validate_cost_center(cost_center_code, tenant_id, session)` if available (optional dependency, logged warning if absent). Store `cost_center_id` (UUID FK to `fin_gl_cost_center.id`) alongside the code so payroll journal entries have a proper FK target. Found in: SAP SuccessFactors (Cost Assignment), Workday (Cost Center Worktag), Oracle HCM Cloud.

### [MEDIUM] Document Version History Not Supported
Missing: `EmployeeDocument` has no versioning — re-uploading a contract replaces the only record.
Impl: Add `version: int` (default 1) and `superseded_by_id: UUID` nullable self-FK on `EmployeeDocument`. `attach_document` should detect an existing unversioned document of the same `document_type` for the employee, set `superseded_by_id` on the old record, and increment `version` on the new one. `is_verified` resets to False on new version. Active document = row with `superseded_by_id IS NULL`. Found in: Workday (Document Versioning), Oracle HCM Cloud, BambooHR.

### [MEDIUM] Employment Status Transition Guard Missing
Missing: `employment_status` can be set to any string via direct attribute mutation in `transfer_employee` and similar paths — no state machine enforces valid transitions.
Impl: Add `_valid_status_transitions: dict[str, set[str]]` class constant and a `_assert_status_transition(current, target)` helper that raises `PersonnelServiceError` for illegal moves (e.g., TERMINATED → ACTIVE without explicit rehire). Apply guard in `terminate_employee`, `transfer_employee`, and any future status-mutating method. Found in: Workday (Business Process Framework), SAP SuccessFactors (Employment Workflow).

### [LOW] Currency Defaulting to USD — Kenya Context
Missing: Default `currency_code = "USD"` is wrong for a Kenya-targeted system; should default to KES.
Impl: Change `EmployeeCompensation.currency_code` server default to `"KES"` and update `hire_employee` initial compensation default. Add a tenant-level `default_currency_code` config looked up at runtime. Found in: ADP Workforce Now (locale-aware defaults), Sage HR Kenya.

### [LOW] Headcount Summary Lacks Approved vs Actual Budget View
Missing: `headcount_summary` returns raw counts but not approved headcount budget, vacancy count, or budget utilisation %.
Impl: Join against `hcm_org_position` (approved headcount per org unit) to compute `approved`, `filled`, `vacant`, `over_budget` per cost centre. Expose as `headcount_budget_summary(entity_id, session)`. Found in: Workday (Headcount Planning), SAP SuccessFactors (Workforce Analytics), Oracle HCM Cloud.

---

## Summary Table

| Capability Area | Score | Benchmark Gap |
|---|---|---|
| Employee master data | 7/10 | Missing contract, background check, rehire link |
| Compensation management | 5/10 | No grade band enforcement, no approval gate, KES default wrong |
| Employment lifecycle | 4/10 | No contract entity, no probation service, no status guard |
| Termination / exit | 3/10 | No notice enforcement, no severance calc, no clearance checklist |
| Disciplinary / grievance | 0/10 | Entirely absent |
| Onboarding | 0/10 | Entirely absent |
| Document management | 5/10 | No versioning, no doc-type-specific expiry rules |
| Compliance (Kenya EA 2007) | 2/10 | Notice periods, severance, leave seeding all missing |
| Analytics / reporting | 3/10 | Headcount only; no budget vs actual, no attrition |
| Integration hooks | 4/10 | Leave event missing, no background check, cost center unvalidated |

**Overall: 31/100**

The foundation (immutable compensation ledger, encrypted PII, event emission, stateless service pattern, multi-tenancy) is architecturally sound and ahead of many open-source HRM systems. The critical deficit is the complete absence of the compliance and workflow layers that justify an HCM system in a regulatory context: disciplinary, grievance, exit clearance, statutory notice/severance, and onboarding. These are table-stakes for any system deployed in Kenya or any other EA-regulated jurisdiction.
