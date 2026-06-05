# org — World-Class HCM Comparison
Score: 28/100

## Current Capabilities

- `LegalEntity` model with basic metadata (name, registration number, country, active flag)
- `OrgUnit` with adjacency-list parent-child hierarchy and `unit_type` enum (department/division/section/team/branch)
- `JobCatalog` with job family, level, and FLSA exempt flag
- `CompensationGrade` with effective-dated min/mid/max salary bands (single currency)
- `Position` model with headcount ceiling, fill tracking, and `position_type` (permanent/contract/casual)
- `create_legal_entity`, `deactivate_legal_entity`
- `create_org_unit`, `restructure_org_unit` (reparenting with cycle detection)
- `create_position`, `fill_position`, `vacate_position`
- `publish_compensation_grade`, `active_grade` (as-of date lookup)
- `org_tree` (recursive hierarchy serialiser for a single legal entity)
- Stateless service pattern with explicit session injection — clean architecture

---

## Gaps

### [CRITICAL] Effective-dated org unit changes

**Missing:** All structural changes (reparent, rename, type change) are destructive in-place mutations with no history.

**Impl:** Add an `OrgUnitHistory` table with `(org_unit_id, effective_date, change_type, old_value_json, new_value_json, changed_by)`. `restructure_org_unit` writes a history row before mutating. Add `org_unit_as_of(unit_id, as_of_date, session)` service method that replays history to reconstruct the hierarchy at any past date. PostgreSQL `tsrange` or a simple `(valid_from, valid_to)` pair on the main table also works and enables index-assisted point-in-time queries.

**Found in:** SAP SuccessFactors (MDF object versioning), Workday (effective-dated supervisory orgs), Oracle HCM Cloud (date-effective records on all org objects)

---

### [CRITICAL] Matrix / dotted-line reporting

**Missing:** Every `OrgUnit` and `Position` has exactly one parent — no support for matrix organisations where an employee reports to both a functional manager and a project/geographic manager.

**Impl:** Add a `ReportingLine` association table: `(from_position_id, to_position_id, line_type: Literal['solid','dotted'], effective_date, end_date)`. Enforce that exactly one solid line exists per position at any time (partial unique index `WHERE line_type = 'solid' AND end_date IS NULL`). Add `reporting_lines(position_id, session)` to the service returning both directions.

**Found in:** Workday (primary + additional supervisory orgs), SAP SuccessFactors (matrix relationships), Oracle HCM Cloud (line manager + project manager)

---

### [CRITICAL] Position vacancy tracking with workflow

**Missing:** `fill_position` and `vacate_position` are instant mutations. There is no requisition state, approval gate, or vacancy age tracking.

**Impl:** Add a `PositionRequisition` model with states `(open → approved → filled | cancelled)` and `opened_at`, `target_fill_date`, `filled_at` timestamps. Introduce `open_vacancy(position_id, requester_id, target_date, session)` and `approve_requisition(req_id, approver_id, session)`. Vacancy age (days open) becomes a derived column. Integrate with a simple `ApprovalChain` lookup keyed on org unit cost centre for Kenya's typical HR committee approval flows.

**Found in:** Workday (job requisition lifecycle), SAP SuccessFactors (recruiting requisition), ADP Workforce Now (open position tracking)

---

### [CRITICAL] FTE / headcount budget vs actual

**Missing:** `Position` has `max_headcount` but there is no budget-vs-actual headcount table, no cost-centre linkage, and no period-based FTE budget that finance can set independently of individual positions.

**Impl:** Add `HeadcountBudget(org_unit_id, fiscal_year, period, budgeted_fte, budgeted_amount_kes, currency)`. Compute `actual_fte` as `COUNT(filled positions) + SUM(part_time_fraction)` via a materialised view or a `get_headcount_actual(org_unit_id, period, session)` service method using a CTE over `Position`. Expose a `headcount_variance(org_unit_id, period, session)` method returning `(budgeted, actual, variance_fte, variance_amount)`.

**Found in:** Workday (headcount budget/actuals), SAP SuccessFactors (workforce planning), Oracle HCM Cloud (workforce budget)

---

### [HIGH] Span of control analytics

**Missing:** No service method computes span of control (number of direct reports per manager position), and no aggregate report exists for min/max/average span across the org.

**Impl:** Add `span_of_control(session, entity_id=None)` returning a list of `{position_id, manager_name, direct_reports: int, org_unit}`. Use a single CTE joining `Position` to itself via the `reporting_line` (solid) relationship. Flag outliers: spans < 2 (under-delegation) or > 12 (overload) as configurable thresholds. For Kenya's public-sector clients the threshold often differs by cadre — parameterise it.

**Found in:** Workday (org effectiveness analytics), SAP SuccessFactors (org chart analytics), Oracle HCM Cloud (manager effectiveness)

---

### [HIGH] Org chart visualisation payload

**Missing:** `org_tree` returns a flat list of dicts. There is no depth-limited, paginated, or D3/vis-js-compatible tree payload.

**Impl:** Extend `org_tree` to accept `max_depth: int | None`, `include_positions: bool`, and `include_headcount: bool` parameters. Return a nested `{id, name, children: [...], position_count, filled_count, vacant_count}` structure. For large Kenyan parastatals with 10k+ units, add a `subtree(root_unit_id, depth, session)` method that uses a PostgreSQL recursive CTE (`WITH RECURSIVE`) bounded by depth to avoid full-tree loads.

**Found in:** All six benchmarks — standard org chart drill-down

---

### [HIGH] Job grading pay band enforcement at hire/transfer

**Missing:** `CompensationGrade` stores bands but `fill_position` never validates that the offered salary sits within the band for the position's grade.

**Impl:** Add `validate_compensation(position_id, offered_salary_kes, session) -> tuple[bool, str]` that fetches the position's `CompensationGrade` via `active_grade` and asserts `min_salary <= offered <= max_salary`. Raise `CompensationBandViolationError` with the breach amount. For Kenya's public service, salary scales are gazetted — store the gazette reference on `CompensationGrade.gazette_reference` and surface it in the error message.

**Found in:** SAP SuccessFactors (compensation eligibility), Workday (compensation grade enforcement), Oracle HCM Cloud (salary basis validation)

---

### [HIGH] Org restructuring workflow (merger / split / rename with audit)

**Missing:** `restructure_org_unit` is a one-liner reparent with no workflow state, approver chain, effective date, or rollback capability.

**Impl:** Add `OrgRestructureRequest` model with `restructure_type: Literal['merge','split','rename','reparent','abolish']`, `requested_by`, `approved_by`, `effective_date`, `status`, and a `change_payload_json` capturing before/after snapshot. Service methods: `request_restructure(...)`, `approve_restructure(req_id, approver, session)`, `execute_restructure(req_id, session)` (only runs when `effective_date <= today`). A nightly job or a pre-request hook checks for pending effective-dated changes.

**Found in:** SAP SuccessFactors (org change workflow), Workday (reorganisation event), Oracle HCM Cloud (position change transaction)

---

### [HIGH] Multi-currency compensation grade support

**Missing:** `CompensationGrade` has `min_salary`, `mid_salary`, `max_salary` with no currency column — implicitly KES but unusable for multinationals operating across EAC.

**Impl:** Add `currency: str = 'KES'` to `CompensationGrade`. Add `CompensationGradeExchange(grade_id, target_currency, exchange_rate, rate_date)` for spot-rate snapshots. Expose `grade_in_currency(grade_code, currency, session)` that converts using the latest stored rate. For EAC operations, pre-seed rates for KES/UGX/TZS/RWF/ETB from the CBK/BNR API.

**Found in:** SAP SuccessFactors (global grade structures), Workday (multi-currency compensation), Oracle HCM Cloud (global grade ranges)

---

### [HIGH] Role-based vs person-based org modelling

**Missing:** The model is purely position-based. There is no concept of an abstract "role" that can be assigned to multiple positions or inherited from a parent org unit.

**Impl:** Add a `OrgRole` model (RACI matrix entries: `role_name, responsibilities_json, org_unit_id, inherited: bool`). Positions reference zero or more roles via `PositionRole` association. `get_roles_for_position(position_id, session)` walks the hierarchy upward collecting inherited roles. This is essential for Kenya's devolved government where the same role (e.g. "Budget Officer") exists in every county but with inherited responsibilities from national Treasury.

**Found in:** SAP SuccessFactors (org roles), Workday (role-based security and org), Oracle HCM Cloud (abstract roles)

---

### [MEDIUM] Workforce planning — FTE targets and vacancy projections

**Missing:** No forward-looking FTE projection, no attrition modelling, no "what-if" scenario support.

**Impl:** Add `WorkforcePlan(org_unit_id, scenario_name, fiscal_year, target_fte, planned_hires, planned_exits, planned_transfers)` model. `project_headcount(org_unit_id, fiscal_year, session)` returns monthly snapshots of projected headcount based on plan assumptions vs actuals. For Kenya context, model known retirement dates (mandatory retirement at 60/65 per public service rules) as planned exits automatically sourced from employee DOB.

**Found in:** Workday (workforce planning module), SAP SuccessFactors (workforce analytics), Oracle HCM Cloud (workforce modeling)

---

### [MEDIUM] Org unit cost centre linkage

**Missing:** `OrgUnit` has no cost centre or GL account reference — impossible to do cost allocation or charge headcount costs to the right budget line.

**Impl:** Add `cost_centre_code: str | None` and `gl_account_code: str | None` to `OrgUnit`. Add a `CostCentreAllocation(org_unit_id, cost_centre_code, allocation_pct, effective_date)` table for split-funding scenarios (common in donor-funded NGOs and Kenya government projects). `get_cost_centres(org_unit_id, session)` returns the weighted allocation list.

**Found in:** SAP SuccessFactors (cost centre assignment), Workday (cost centre hierarchy), ADP Workforce Now (department cost codes)

---

### [MEDIUM] Position classification / job family hierarchy

**Missing:** `JobCatalog` has `job_family` as a plain string. There is no structured job family hierarchy, no NOC/ISCO-08 code linkage, and no career path modelling.

**Impl:** Add `JobFamily(code, name, parent_family_id)` as a self-referential tree (same adjacency-list pattern as `OrgUnit`). Add `isco_code: str | None` to `JobCatalog` for KNBS/ILO labour market reporting compliance. Add `career_path(job_catalog_id, session)` that returns the lateral and vertical progression options within the family tree.

**Found in:** SAP SuccessFactors (job classification), Workday (job profile hierarchy), Oracle HCM Cloud (job family structure)

---

### [MEDIUM] Org unit status lifecycle (proposed → active → frozen → abolished)

**Missing:** `OrgUnit.active` is a boolean — no intermediate states, no "proposed" state for units under approval, no "frozen" state for units being restructured.

**Impl:** Replace `active: bool` with `status: Literal['proposed','active','frozen','abolished']`. Add `status_changed_at: datetime` and `status_changed_by: str`. Guard all position creation and employee assignment operations against units in non-active states. "Frozen" is useful during Kenya government re-organisations (e.g. post-election ministry mergers) where a unit exists on paper but hiring is suspended.

**Found in:** SAP SuccessFactors (org unit status), Workday (org inactive/active lifecycle), Oracle HCM Cloud (org status)

---

### [MEDIUM] Delegation of authority matrix

**Missing:** No model captures which org unit or position has authority to approve what financial/HR action up to what limit.

**Impl:** Add `DelegationOfAuthority(org_unit_id, position_id, action_type, amount_limit_kes, currency, delegated_to_position_id, effective_date, expiry_date)`. `can_approve(position_id, action_type, amount, session) -> bool` checks the active delegation chain. Critical for Kenya's PFMA compliance where procurement and hiring approvals must stay within gazzetted limits by cadre.

**Found in:** SAP SuccessFactors (authority management), Workday (delegation of authority), Oracle HCM Cloud (approval hierarchy)

---

### [MEDIUM] Locality / work location model

**Missing:** `OrgUnit` has no physical location, county, or remote-work policy attached. For Kenya's devolved structure, county-level org units are legally distinct from national ones.

**Impl:** Add `Location(code, name, county: str, sub_county: str | None, latitude: float | None, longitude: float | None, remote_eligible: bool)`. Link `OrgUnit.location_id -> Location.id`. Add `county` as an indexed column to enable per-county headcount reports required by Kenya's devolution reporting framework (CIDP reports).

**Found in:** Workday (location hierarchy), SAP SuccessFactors (work location), BambooHR (location/department)

---

### [MEDIUM] Temporary assignment / acting role support

**Missing:** When a position is vacant or the incumbent is on leave, there is no model for an acting/temporary assignment to another employee.

**Impl:** Add `ActingAssignment(position_id, acting_employee_id, delegating_employee_id, start_date, end_date, reason, approved_by)`. `current_acting(position_id, session)` returns the active assignment if any. `fill_position` should check for active acting assignments and either terminate them or log a warning. Kenya public service requires a formal acting letter — store `acting_letter_ref` on the record.

**Found in:** SAP SuccessFactors (acting positions), Workday (interim position coverage), Oracle HCM Cloud (acting assignments)

---

### [LOW] Org unit abbreviation / short code uniqueness

**Missing:** `OrgUnit` has no unique short code — org units can only be distinguished by their UUID, which is useless in payroll extract files and government HR returns.

**Impl:** Add `short_code: str` with a unique constraint scoped to `legal_entity_id`. Validate format (e.g. `^[A-Z0-9]{2,8}$`) via an `AfterValidator`. Kenya's IPPD system requires a numeric ministry/department code — add `ippd_code: str | None` for public sector clients.

**Found in:** SAP SuccessFactors (org unit ID), ADP Workforce Now (department code), BambooHR (department identifier)

---

### [LOW] Headcount reporting snapshots for statutory returns

**Missing:** No periodic snapshot mechanism — headcount reports for KNBS, NSSF, NHIF, and county assembly budget submissions require point-in-time headcount, not live data.

**Impl:** Add a `HeadcountSnapshot(snapshot_date, org_unit_id, filled_positions, vacant_positions, fte_total, created_at)` table populated by a scheduled `take_headcount_snapshot(entity_id, as_of, session)` service method. PostgreSQL `pg_cron` or a Celery beat task triggers it on the last working day of each month. Snapshots feed statutory export formats without touching live transactional tables.

**Found in:** SAP SuccessFactors (headcount analytics), Workday (headcount reports), ADP Workforce Now (HR reports)
