# GRC Privacy Plugin — SPEC

## Domain
`grc` — governance, risk & compliance

## Purpose
GDPR / privacy compliance tooling: consent lifecycle management, data subject
request (DSR) workflow automation, and Article 30 Record of Processing
Activities (RoPA).

## Entities

### ConsentRecord *(append-only — NEVER UPDATE)*
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| tenant_id | UUID NOT NULL | |
| party_id | UUID FK erp_party | the data subject |
| purpose | VARCHAR(500) | e.g. 'marketing_emails' |
| legal_basis | VARCHAR(30) | GDPR Art. 6 vocabulary |
| granted_at | TIMESTAMPTZ DEFAULT NOW() | |
| withdrawn_at | TIMESTAMPTZ | NULL = still active |
| expires_at | TIMESTAMPTZ | NULL = no expiry |
| source | VARCHAR(100) | WEB_FORM \| API \| PAPER \| IMPORT |
| version | VARCHAR(50) | policy document version |
| ip_address | VARCHAR(45) | IPv4/IPv6 |

Legal basis values: CONSENT | CONTRACT | LEGAL_OBLIGATION | VITAL_INTERESTS | PUBLIC_TASK | LEGITIMATE_INTERESTS

**Withdrawal pattern**: insert a new row with `withdrawn_at = NOW()` — never modify existing rows.

### DataSubjectRequest
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| tenant_id | UUID NOT NULL | |
| dsr_number | VARCHAR(50) UNIQUE | DSR-YYYYMM-NNNNN |
| party_id | UUID FK erp_party | |
| request_type | VARCHAR(15) | ACCESS \| ERASURE \| RECTIFICATION \| PORTABILITY \| RESTRICTION \| OBJECTION |
| status | VARCHAR(15) | RECEIVED \| VERIFIED \| IN_PROGRESS \| COMPLETED \| REJECTED |
| received_at | TIMESTAMPTZ | |
| due_at | TIMESTAMPTZ | regulatory deadline (30 days default) |
| completed_at | TIMESTAMPTZ | |
| response_url | TEXT | packaged export URL |
| notes | TEXT | |
| created_at / updated_at | TIMESTAMPTZ | |

Status flow: RECEIVED → VERIFIED → IN_PROGRESS → COMPLETED | REJECTED

### DataProcessingRecord
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| tenant_id | UUID NOT NULL | |
| processing_purpose | VARCHAR(500) | |
| data_categories | TEXT[] | array of category strings |
| data_subjects_description | TEXT | |
| recipients | JSONB | list of recipient objects |
| retention_period_days | INT | -1 = indefinite |
| legal_basis | VARCHAR(30) | GDPR Art. 6 |
| controller_name | VARCHAR(300) | |
| processor_name | VARCHAR(300) | NULL if no processor |
| is_cross_border | BOOL | EEA transfer flag |
| safeguards | JSONB | SCCs, BCRs, etc. |
| created_at / updated_at | TIMESTAMPTZ | |

## Business Rules
1. ConsentRecord is append-only; withdrawals are new rows, not updates.
2. legal_basis must be one of the 6 GDPR Art. 6 bases.
3. DSR due_at must be set at creation (default: received_at + 30 days).
4. DSR status transitions are strictly ordered; invalid transitions raise errors.
5. Active consent = latest record has withdrawn_at IS NULL and (expires_at IS NULL or > NOW()).
6. DSR numbers are unique and auto-generated: DSR-YYYYMM-NNNNN.

## Events Emitted
- `privacy.consent.granted`
- `privacy.consent.withdrawn`
- `privacy.dsr.received`
- `privacy.dsr.completed`
- `privacy.dsr.overdue`

## Events Consumed
- `party.created` — initialise default consent records
- `party.merged` — merge consent records on deduplication

## API Endpoints

| Method | Path | Description |
|---|---|---|
| POST | /privacy/consent/ | Grant consent |
| GET | /privacy/consent/check | Check active consent |
| POST | /privacy/consent/withdraw | Withdraw consent |
| GET | /privacy/dsr/ | List DSRs |
| POST | /privacy/dsr/ | Create DSR |
| POST | /privacy/dsr/{id}/transition | Change DSR status |
| GET | /privacy/processing-records/ | List processing records |
| POST | /privacy/processing-records/ | Create processing record |
| GET | /privacy/reports/consent-summary | Consent by purpose/basis |
| GET | /privacy/reports/dsr-status | DSR counts by status/type |
| GET | /privacy/reports/overdue-dsrs | DSRs past due date |

## Rules Engine Rulesets (4)
1. `consent.legal_basis_valid` — GDPR Art. 6 vocabulary
2. `consent.immutable` — block UPDATE on ConsentRecord
3. `dsr.request_type_valid` — valid DSR types
4. `dsr.due_date_required` — due_at mandatory at creation

## Cross-plugin Composability
- **Upstream**: foundation (Party)
- **Downstream**: grc.controls (consent-related controls)
