# Quality Management Plugin — Competitive Comparison

Compares the PgAppForge Quality Management (QC) plugin against SAP QM,
Oracle Quality (OQ), MasterControl, and ETQ Reliance.

---

## Feature Matrix

| Capability | PgAppForge QC | SAP QM | Oracle Quality | MasterControl | ETQ Reliance |
|---|---|---|---|---|---|
| **Inspection Plans** | InspectionPlan with JSONB characteristics (USL/LSL/AQL) | Q-Plan with master inspection characteristics | Collection plans with element groups | Form-based inspection templates | Configurable inspection templates |
| **Inspection Lots** | InspectionLot with source_type (PO/WO/Transfer) | QA01 inspection lot per movement type | Inspection lots tied to transactions | Tied to batch records | Lot/batch management |
| **AQL Sampling** | sampling_pct on plan; ANSI/SKIP_LOT constants | AQL with statistical sampling tables | AQL-based skip lot | Manual sampling rules | ISO 2859 AQL tables |
| **In-line measurement recording** | InspectionResult per characteristic with auto USL/LSL check | Results recording via QE01 | Collection transactions | Form field capture | Result entry per spec |
| **Pass/fail auto-determination** | Auto on complete_inspection via pass_rate >= aql_threshold | Automatic usage decision | Automatic disposition | Configurable pass/fail rules | Rules-driven outcome |
| **NCR lifecycle** | NCR: OPEN→UNDER_REVIEW→DISPOSITION→CLOSED | QM notification: Created→Released→Completed | Defect management workflow | CAPA/NCR linked forms | Nonconformance workflow |
| **CAPA** | CAPA model with CORRECTIVE/PREVENTIVE, effectiveness_verified | CAPA via QM notifications or EHS module | Corrective actions in Oracle EBS | Full CAPA module (core strength) | CAPA with root cause and effectiveness |
| **Calibration** | CalibrationRecord with next_due_date, overdue dashboard metric | PM orders for calibration (indirect) | Calibration via Oracle EAM | Equipment calibration module | Calibration management module |
| **Quality Dashboard** | get_quality_dashboard: pass rate, open NCRs by severity, open CAPAs, overdue cals | Standard QM reports + BI Publisher | OBIEE quality dashboards | Dashboard per module | Analytics dashboards |
| **Event emission** | Domain events (passed/failed/ncr) for downstream consumption | Workflow tasks / ALE messages | Business events | Email/workflow notifications | Notifications |
| **Rules Engine** | 5 built-in rulesets (auto-NCR, CRITICAL due-date enforcement) | Condition-based QM notifications | Workflow rules | Configurable business rules | Rules-driven workflow |
| **Multi-tenant** | tenant_id on every row; full isolation | Client-based separation | Org-based separation | Single-tenant SaaS | Single/multi-tenant options |
| **Deployment** | Self-hosted PostgreSQL, open source | SAP HANA/Oracle, proprietary | Oracle DB, proprietary | Cloud SaaS | Cloud SaaS |

---

## Architecture Differences

### PgAppForge vs SAP QM

SAP QM is deeply integrated with MM (goods receipt triggers lot creation) and PP
(production order completion triggers final inspection) via movement type configuration.
PgAppForge replicates this via domain event subscriptions: `ap.grn.posted` creates an
InspectionLot automatically when `QC_AUTO_CREATE_INCOMING_INSPECTION=True`.

SAP uses a two-key structure (material + plant) for inspection plans; PgAppForge uses
`product_code` (VARCHAR 30) as the natural key, intentionally decoupled from a rigid
item master FK — the caller owns the product catalogue.

SAP's usage decision (UD) is the terminal inspection outcome gate.  PgAppForge maps this
to `InspectionLot.status ∈ {PASSED, FAILED, HOLD, RELEASED}` with `complete_inspection()`
tallying results automatically.

### PgAppForge vs Oracle Quality

Oracle Quality (OQ) uses "collection plans" mapped to transaction types (PO receipts,
WIP completions, etc.).  PgAppForge uses `source_type` on InspectionLot for the same
purpose, keeping the schema simpler at the cost of Oracle's richer parametric
transaction binding.

Oracle's skip-lot program tracks history to determine when lots may be skipped.
PgAppForge exposes `SKIP_LOT` as a sampling_method constant on InspectionPlan; the
skip-lot eligibility logic is left to the calling application or a Rules Engine ruleset.

### PgAppForge vs MasterControl

MasterControl's core strength is document control + CAPA in regulated environments
(FDA 21 CFR Part 11, ISO 13485).  It has a richer CAPA workflow with multi-stage
approvals, electronic signatures, and CAPA effectiveness review periods.

PgAppForge's CAPA is simpler: 4-state machine (OPEN→IN_PROGRESS→VERIFIED→CLOSED),
no built-in e-signature.  For regulated industries, the Rules Engine can enforce
approval gates.  MasterControl has no ERP integration by default; PgAppForge CAPA
integrates natively with InspectionLots, NCRs, and production orders.

### PgAppForge vs ETQ Reliance

ETQ Reliance is a pure quality SaaS with strong calibration and audit management.
Its calibration module tracks NIST traceability chains; PgAppForge's CalibrationRecord
is a flat record with certificate_number and tolerance_value — sufficient for most
manufacturing environments but without traceability tree or accreditation body linkage.

ETQ's nonconformance workflow is configurable per document type; PgAppForge's NCR
has a fixed status machine, customisable via the Rules Engine.

---

## Gaps vs Enterprise QMS

The following capabilities are absent from the current PgAppForge QC plugin and would
be required for enterprise or regulated deployment:

1. **Statistical Process Control (SPC)**: control charts (X-bar/R, CUSUM), Cpk/Ppk
   computation.  Currently only raw measurement storage.
2. **Supplier Quality Management (SQM)**: supplier scorecard, SCAR (Supplier Corrective
   Action Request), debit note generation from NCR.
3. **Skip-lot eligibility engine**: automatic skip-lot promotion/demotion based on
   recent inspection history.
4. **E-signature / audit trail**: 21 CFR Part 11 compliance requires immutable audit
   log with electronic signatures on record closures.
5. **Document linkage**: attach SOPs, drawings, and work instructions to inspection
   plans (currently handled by a separate document management plugin).
6. **Multi-level AQL tables**: full ANSI Z1.4 / ISO 2859-1 table lookup by lot size
   and inspection level; current implementation uses a single sampling_pct threshold.
