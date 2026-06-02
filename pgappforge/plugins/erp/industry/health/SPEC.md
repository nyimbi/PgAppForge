# Health Cloud Plugin — SPEC

**Plugin**: `health`
**Domain**: `industry`
**Depends on**: `foundation`
**Version**: 1.0.0

---

## Entities

### Patient (`hlt_patient`)
Links to `erp_party` for demographics. Carries clinical and insurance state.
PHI columns: `allergies`, `active_medications`, `blood_type`.

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | gen_random_uuid() |
| tenant_id | UUID NOT NULL | multi-tenant isolation |
| party_id | UUID FK erp_party | RESTRICT |
| patient_number | VARCHAR(50) UNIQUE | MRN |
| blood_type | VARCHAR(5) | nullable; ABO+Rh e.g. A+, O- |
| allergies | JSONB | PHI: [{allergen, reaction, severity, noted_at}] |
| active_medications | JSONB | PHI: [{ndc_code, drug_name, dose, frequency}] |
| primary_care_provider_id | INTEGER FK ab_user | nullable |
| insurance_member_id | VARCHAR(100) | nullable |
| insurance_plan | VARCHAR(200) | nullable |
| advance_directive | BOOLEAN | |
| organ_donor | BOOLEAN | |
| preferred_language | CHAR(5) | BCP 47 |
| interpreter_needed | BOOLEAN | |

### ClinicalEncounter (`hlt_clinical_encounter`)

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| tenant_id | UUID NOT NULL | |
| patient_id | UUID FK hlt_patient | RESTRICT |
| encounter_type | VARCHAR(15) | INPATIENT \| OUTPATIENT \| EMERGENCY \| TELEHEALTH |
| encounter_date | TIMESTAMPTZ | |
| provider_id | INTEGER FK ab_user | nullable |
| facility_id | UUID | nullable |
| chief_complaint | TEXT | nullable |
| encounter_status | VARCHAR(15) | SCHEDULED \| IN_PROGRESS \| COMPLETED |
| discharge_date | TIMESTAMPTZ | nullable |
| discharge_disposition | VARCHAR(100) | nullable; HOME \| TRANSFER \| EXPIRED \| AMA |

### DiagnosisRecord (`hlt_diagnosis_record`)
**Functionally immutable once `confirmed=TRUE`** — service layer rejects mutations.

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| tenant_id | UUID NOT NULL | |
| encounter_id | UUID FK hlt_clinical_encounter | RESTRICT |
| icd10_code | VARCHAR(10) | ICD-10-CM |
| diagnosis_description | VARCHAR(500) | |
| diagnosis_type | VARCHAR(15) | PRIMARY \| SECONDARY \| COMPLICATION |
| confirmed | BOOLEAN | FALSE until clinician confirms |
| noted_at | TIMESTAMPTZ | |

### ProcedureRecord (`hlt_procedure_record`)

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| tenant_id | UUID NOT NULL | |
| encounter_id | UUID FK hlt_clinical_encounter | RESTRICT |
| cpt_code | VARCHAR(10) | CPT code |
| procedure_name | VARCHAR(500) | |
| performed_at | TIMESTAMPTZ | |
| performed_by | INTEGER FK ab_user | nullable |
| notes | TEXT | nullable |

### Prescription (`hlt_prescription`)

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| tenant_id | UUID NOT NULL | |
| encounter_id | UUID FK hlt_clinical_encounter | RESTRICT |
| patient_id | UUID FK hlt_patient | RESTRICT |
| ndc_code | VARCHAR(15) | National Drug Code |
| drug_name | VARCHAR(300) | PHI |
| dosage | VARCHAR(100) | PHI e.g. 500mg |
| frequency | VARCHAR(100) | PHI e.g. TID |
| duration_days | INTEGER | nullable |
| prescribed_by | INTEGER FK ab_user | nullable |
| prescribed_at | TIMESTAMPTZ | |
| refills_allowed | INTEGER | DEFAULT 0 |
| refills_used | INTEGER | DEFAULT 0 |
| status | VARCHAR(15) | ACTIVE \| DISCONTINUED \| COMPLETED |

### LabResult (`hlt_lab_result`)

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| tenant_id | UUID NOT NULL | |
| patient_id | UUID FK hlt_patient | RESTRICT |
| ordered_by | INTEGER FK ab_user | nullable |
| ordered_at | TIMESTAMPTZ | |
| loinc_code | VARCHAR(10) | LOINC observation code |
| test_name | VARCHAR(300) | |
| specimen_type | VARCHAR(100) | nullable |
| result_value | TEXT | PHI; nullable until resulted |
| result_unit | VARCHAR(50) | nullable |
| reference_range | VARCHAR(100) | nullable |
| abnormal_flag | VARCHAR(5) | N \| H \| L \| HH \| LL \| NULL |
| resulted_at | TIMESTAMPTZ | nullable |
| status | VARCHAR(10) | ORDERED \| COLLECTED \| RESULTED \| REVIEWED |

---

## Relationships

```
erp_party 1──* Patient
Patient 1──* ClinicalEncounter
Patient 1──* LabResult
Patient 1──* Prescription
ClinicalEncounter 1──* DiagnosisRecord
ClinicalEncounter 1──* ProcedureRecord
ClinicalEncounter 1──* Prescription
```

---

## Business Rules

1. **Single PRIMARY**: Only one `DiagnosisRecord` with `diagnosis_type=PRIMARY` allowed per encounter. Enforced by `add_diagnosis()` and rules engine.
2. **Confirmed immutability**: Once `DiagnosisRecord.confirmed=TRUE`, the service layer rejects any mutation. Rule: `health.diagnosis.immutable_after_confirm`.
3. **Active encounter gate**: Diagnoses, procedures, and prescriptions can only be added to encounters in `IN_PROGRESS` status.
4. **Refill limit**: `refills_used` must never exceed `refills_allowed`. `use_refill()` raises `RefillLimitExceededError` at the limit.
5. **Critical lab alerting**: `abnormal_flag` in `{HH, LL}` triggers `LabCriticalValueEvent` in addition to `LabResultedEvent` for immediate downstream notification.
6. **Lab result idempotency**: A LabResult already in `RESULTED` status cannot be re-resulted via `record_lab_result()`.
7. **Discharge gate**: `discharge_patient()` requires `encounter_status=IN_PROGRESS`.

---

## API Endpoints

### Patients
| Method | Path | Description |
|--------|------|-------------|
| GET | /health/patients/ | List patients |
| GET | /health/patients/{id} | Patient detail (PHI) |
| POST | /health/patients/ | Register patient |

### Encounters
| Method | Path | Description |
|--------|------|-------------|
| GET | /health/encounters/ | List encounters |
| POST | /health/encounters/ | Start encounter |
| GET | /health/encounters/{id} | Detail + diagnoses + procedures |
| POST | /health/encounters/{id}/discharge | Discharge patient |

### Diagnoses
| Method | Path | Description |
|--------|------|-------------|
| GET | /health/diagnoses/ | List (filter by encounter/ICD-10) |
| POST | /health/diagnoses/ | Add diagnosis |
| POST | /health/diagnoses/{id}/confirm | Confirm (make append-only) |

### Prescriptions
| Method | Path | Description |
|--------|------|-------------|
| GET | /health/prescriptions/ | List |
| POST | /health/prescriptions/ | Issue prescription |
| POST | /health/prescriptions/{id}/refill | Use one refill |

### Lab Results
| Method | Path | Description |
|--------|------|-------------|
| GET | /health/labs/ | List |
| POST | /health/labs/ | Order lab test |
| GET | /health/labs/{id} | Detail |
| POST | /health/labs/{id}/result | Record result (→RESULTED) |
| POST | /health/labs/{id}/review | Mark reviewed |

### Reports
| Method | Path | Description |
|--------|------|-------------|
| GET | /health/reports/patient-summary/{id} | Clinical profile |
| GET | /health/reports/abnormal-labs | All abnormal results |
| GET | /health/reports/encounter-volume | Volume by type/status |

---

## Events

### Emitted
| Event | Trigger | PHI? |
|-------|---------|------|
| `health.patient.registered` | `register_patient()` | IDs only |
| `health.patient.updated` | patient update | field names only |
| `health.encounter.started` | `start_encounter()` | IDs only |
| `health.encounter.completed` | `discharge_patient()` | disposition code |
| `health.diagnosis.confirmed` | `confirm_diagnosis()` | ICD-10 code |
| `health.prescription.issued` | `issue_prescription()` | NDC code |
| `health.prescription.discontinued` | discontinue | IDs only |
| `health.lab.resulted` | `record_lab_result()` | LOINC + flag |
| `health.lab.critical_value` | HH/LL flags | LOINC + flag + provider_id |

No PHI is carried in event payloads — only coded identifiers.

### Consumed
| Event | Action |
|-------|--------|
| `party.created` | (optional) pre-register Patient shell |

---

## Cross-plugin Composability

- **Upstream**: `foundation` (Party, DomainEventLog)
- **Downstream consumers of our events**:
  - `finance.ar` — `health.encounter.completed` → generate patient billing
  - `analytics.cdp` — `health.patient.registered` → customer 360 profile
  - Notification plugin — `health.lab.critical_value` → page on-call clinician
  - `grc.privacy` — `health.patient.*` → PHI access audit trail

## Regulatory Notes

- HIPAA (US): PHI columns (`allergies`, `active_medications`, `result_value`,
  `drug_name`, `dosage`) require column-level encryption in production.
  Use pgcrypto or application-layer AES-256 encryption.
- NDPR (Nigeria) / GDPR (EU): Apply equivalent encryption and data residency
  controls for deployments outside the US.
- HL7 FHIR R4: Event payloads use LOINC / SNOMED / ICD-10 codes for
  interoperability. FHIR adapter layer is a separate integration plugin.
