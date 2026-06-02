# HCM Personnel Administration Plugin — SPEC

## Domain
`hcm` | Plugin name: `hcm.personnel` | Depends on: `foundation`, `hcm.org`

## Entities

### Employee (`hcm_per_employee`)
Core employment record. Demographic data lives on `foundation.Party` (soft FK via `party_id`). Sensitive fields are application-level encrypted before storage — database stores ciphertext only.

| Field | Type | Notes |
|---|---|---|
| id | UUID PK | |
| tenant_id | UUID NOT NULL | |
| employee_number | VARCHAR(30) | Unique per tenant |
| party_id | UUID (soft FK) | FK to erp_party.id — no DB constraint |
| position_id | UUID FK → hcm_org_position | |
| entity_id | UUID FK → hcm_org_legal_entity | |
| org_unit_id | UUID FK → hcm_org_unit | |
| manager_id | UUID FK → hcm_per_employee (self) | Nullable — CEO has no manager |
| employment_type | VARCHAR(20) | FULL_TIME \| PART_TIME \| CONTRACT \| CASUAL |
| employment_status | VARCHAR(20) | ACTIVE \| ON_LEAVE \| TERMINATED \| RETIRED |
| start_date | DATE NOT NULL | Official commencement date |
| probation_end_date | DATE | NULL = not on probation |
| termination_date | DATE | NULL while active |
| termination_type | VARCHAR(20) | VOLUNTARY \| INVOLUNTARY \| REDUNDANCY \| RETIREMENT |
| termination_reason | VARCHAR(255) | |
| rehire_eligible | BOOLEAN | DEFAULT true |
| cost_center_code | VARCHAR(20) | Overrides org unit for payroll |
| national_id_encrypted | TEXT | App-encrypted before storage |
| tax_id_encrypted | TEXT | App-encrypted before storage |
| bank_account_iban_encrypted | TEXT | App-encrypted before storage |
| bank_bic | VARCHAR(11) | Plaintext — not sensitive |
| created_at / updated_at | TIMESTAMPTZ | |

**Security note**: `national_id_encrypted`, `tax_id_encrypted`, `bank_account_iban_encrypted` are NEVER returned by the API. Decryption happens only via the service layer with appropriate audit logging.

Multiple active `Employee` rows for the same `party_id` represent concurrent employments across legal entities (secondments, multi-country).

### EmployeeCompensation (`hcm_per_employee_compensation`)
**IMMUTABLE LEDGER** — every pay change inserts a new row. Never UPDATE.

Active rate = row with highest `effective_date <= today`.

| Field | Type | Notes |
|---|---|---|
| id | UUID PK | |
| tenant_id | UUID NOT NULL | |
| employee_id | UUID FK → hcm_per_employee | |
| effective_date | DATE NOT NULL | When this rate becomes active |
| pay_type | VARCHAR(20) | SALARY \| HOURLY \| COMMISSION |
| amount_cents | INTEGER NOT NULL | Gross pay in cents — NEVER float |
| currency_code | CHAR(3) | ISO 4217 |
| frequency | VARCHAR(20) | ANNUAL \| MONTHLY \| BIWEEKLY \| HOURLY |
| grade_code | VARCHAR(20) | Pay grade at time of change |
| reason | VARCHAR(50) | NEW_HIRE \| MERIT \| PROMOTION \| MARKET \| OTHER |
| approved_by | UUID | FK to ab_user |
| created_at / updated_at | TIMESTAMPTZ | |

### EmployeeDocument (`hcm_per_employee_document`)
Document metadata. File content in object storage; `storage_url` is the key.

| Field | Type | Notes |
|---|---|---|
| id | UUID PK | |
| tenant_id | UUID NOT NULL | |
| employee_id | UUID FK → hcm_per_employee | |
| document_type | VARCHAR(50) | CONTRACT \| PASSPORT \| VISA \| CERTIFICATE \| NDA \| OTHER |
| filename | VARCHAR(500) | Original filename |
| storage_url | TEXT | Object store key; resolve to signed URL on read |
| issued_date | DATE | |
| expiry_date | DATE | Alert when expiry_date < today + 30 days |
| is_verified | BOOLEAN | DEFAULT false; HR-verified |
| created_at / updated_at | TIMESTAMPTZ | |

## Business Rules

1. `start_date` required on hire (Rules Engine)
2. `amount_cents` must be positive integer (Rules Engine) — NEVER float
3. `termination_type` required when `termination_date` is set
4. Cannot rehire employee where `rehire_eligible=False`
5. Compensation history is immutable — INSERT only, never UPDATE
6. Encrypted fields never exposed via API responses
7. `EmployeeCompensation` records belong to a single employee; cross-entity pay requires separate records per entity
8. `employment_status` transitions: ACTIVE → ON_LEAVE ↔ ACTIVE → TERMINATED | RETIRED

## API Endpoints

| Method | Path | Description |
|---|---|---|
| GET | /hcm/personnel/employees/ | List employees (filterable) |
| GET | /hcm/personnel/employees/{id} | Detail (no encrypted fields) |
| POST | /hcm/personnel/employees/ | Hire employee |
| PUT | /hcm/personnel/employees/{id} | Update non-sensitive fields |
| POST | /hcm/personnel/employees/{id}/terminate | Terminate |
| POST | /hcm/personnel/employees/{id}/transfer | Transfer/reassign |
| GET | /hcm/personnel/compensation/{employee_id} | Compensation history |
| GET | /hcm/personnel/compensation/{employee_id}/current | Active rate |
| POST | /hcm/personnel/compensation/ | Record new comp (INSERT only) |
| GET | /hcm/personnel/documents/{employee_id} | List documents |
| POST | /hcm/personnel/documents/ | Attach document metadata |
| POST | /hcm/personnel/documents/{doc_id}/verify | Mark verified |
| GET | /hcm/personnel/reports/roster | Active employee roster |
| GET | /hcm/personnel/reports/compensation | Compensation summary by grade |
| GET | /hcm/personnel/reports/expiring-docs | Documents expiring in N days |

## Events Emitted
- `hcm.personnel.employee.hired` — new employee record created
- `hcm.personnel.employee.assigned` — position/org unit changed
- `hcm.personnel.employee.transferred` — cross-entity move
- `hcm.personnel.employee.terminated` — employment ended
- `hcm.personnel.employee.rehired` — previous employee rehired
- `hcm.personnel.compensation.changed` — new EmployeeCompensation inserted
- `hcm.personnel.document.verified` — document marked is_verified=True
- `hcm.personnel.document.expiring` — document expiry < 30 days away

## Events Consumed
- `hcm.org.position.created` — pre-validate position reference
- `hcm.time.timesheet.approved` — downstream payroll computes hourly pay

## Rules Engine Rulesets (pre-configured)
1. `hcm.personnel.employee.require_start_date` — start_date required on hire
2. `hcm.personnel.compensation.positive_amount` — amount_cents > 0
3. `hcm.personnel.employee.termination_type_required` — type required with date
4. `hcm.personnel.employee.no_rehire_if_ineligible` — block ineligible rehire

## Reports
1. **Employee Roster** — active employees with employment type and start date
2. **Compensation Summary** — employee count and average/min/max pay per grade code
3. **Document Expiry Alert** — documents expiring within N days (default 30)

## Cross-Plugin Composability
- Emits `hcm.personnel.employee.assigned` → consumed by `hcm.org` to fill positions
- Emits `hcm.personnel.employee.terminated` → consumed by `hcm.org` to vacate positions and `hcm.time` to cancel pending leave
- Consumes `hcm.time.timesheet.approved` → feeds payroll calculation for hourly employees
