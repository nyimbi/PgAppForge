# Carbon / GHG Tracking — Platform Comparison

## What This Module Does

Scope 1/2/3 GHG emission recording, GHG Protocol-aligned reporting, carbon
offset management, and emission intensity analytics. Ships with Kenya-specific
default emission factors (KETRACO grid, IPCC AR6, BEIS 2024). Designed for
CSRD Article 29a, GHG Protocol Corporate Standard, and future SBTi alignment.

Tables: `co2_emission_factor`, `co2_record`, `co2_report`, `co2_offset`.
BPM-callable via `platform.carbon.*` capability handles.

---

## Competitive Landscape

### SAP Sustainability Cloud (formerly SAP Product Footprint Management)

| Dimension | SAP Sustainability Cloud | This module |
|-----------|--------------------------|-------------|
| Scope coverage | Scope 1/2/3 including product-level LCA | Scope 1/2/3 at activity level; no product LCA |
| Emission factors | GHG Protocol, IPCC, Ecoinvent (licensed) | IPCC AR6, BEIS 2024, Kenya KETRACO — open, vendored |
| CSRD alignment | Full ESRS E1 data model | GHG Protocol aggregation; ESRS mapping is a reporting layer concern |
| Data ingestion | SAP BTP connectors to utility APIs, IoT | Manual record + `source_module`/`source_record_id` for ERP auto-population |
| Offset management | Project registry, Gold Standard API | Type + provider + certificate_ref + cost_cents; registry API is future work |
| Deployment | SAP BTP (SaaS) | Self-hosted PostgreSQL; any PaaS |
| Cost | ~$80–200k/year | Open source |

**Gap vs SAP**: SAP Sustainability Cloud integrates with utility bill APIs and
IoT energy meters for automatic activity data ingestion. This module requires
explicit `record_emission()` calls or event-based auto-recording via
`subscribe_to()` handlers on fleet/shipment events.

---

### Watershed

| Dimension | Watershed | This module |
|-----------|-----------|-------------|
| Target market | Mid-market to enterprise, VC-backed | SME–enterprise, self-hosted |
| Emission factors | Climatiq API, EPA, BEIS, IPCC | Vendored table — updateable via `EmissionFactor` rows or `seed_default_factors()` |
| Scope 3 categories | Full GHG Protocol 15 categories | Single `scope=3` integer; category breakdown is a `source_type` naming convention |
| CSRD / CDP reporting | Native CDP questionnaire export | Report row aggregation; export format is a reporting layer concern |
| Supplier engagement | Supplier data collection portal | Not in scope |
| API | REST + webhook | SQLAlchemy service layer + BPM action registry |
| Price | $50–150k/year SaaS | Open source |

---

### Persefoni

| Dimension | Persefoni | This module |
|-----------|-----------|-------------|
| Focus | Financial sector (PCAF), TCFD | General corporate GHG Protocol |
| PCAF methodology | Asset-class attribution factors | Not implemented — roadmap for fintech plugin integration |
| Audit trail | Immutable versioned snapshots | `co2_record` append-only + domain event log |
| Intensity metrics | Revenue, headcount, m² | `compute_emission_intensity()` — revenue-based; extensible |
| Scenario modelling | Net-zero pathways, SBTi targets | `ReductionTargetSetEvent` stub — target tracking is future model |
| Deployment | SaaS only | Self-hosted |

---

### Normative (now Normative Carbon Accounting)

| Dimension | Normative | This module |
|-----------|-----------|-------------|
| Approach | Spend-based Scope 3 estimation | Activity-based (physical units × emission factor) |
| Accuracy | Estimated (spend proxies) | Higher — uses actual activity data when available |
| Factor updates | Automatic via Normative API | Manual factor row update + `EmissionFactorUpdatedEvent` |
| Price | ~$20–60k/year | Open source |

---

## Emission Factor Governance

This module uses a **vendored factor table** strategy rather than a live API
dependency. Rationale:

1. **Audit stability** — CSRD requires disclosure of methodology and factors
   used. A live API that silently updates factors mid-year breaks audit trails.
   Factor rows have `effective_from`/`effective_to` dates; historical records
   retain their original `emission_factor_id` FK.

2. **Offline operation** — works without internet access (critical for
   on-premise deployments in bandwidth-constrained markets).

3. **Kenya-first defaults** — most global SaaS tools ship with US/EU defaults.
   The 0.390 kgCO2e/kWh Kenya grid factor (KETRACO 2024) reflects the actual
   grid mix (~90% hydro + geothermal) rather than a generic African average.

Factor lookup priority:
1. `source_type` + `country_code` + `effective_from <= period_date` (latest)
2. Same source_type, any country (fallback)
3. `co2e_kg = 0` with a warning log if no factor found

---

## Design Decisions

**Why `Numeric(15,4)` for `co2e_kg` and not `BigInteger` cents?**
Emission values are not monetary — they represent physical quantities (kg)
with sub-gram precision meaningful in aggregate reporting. Using integer
"milli-kg" would be non-standard vs. GHG Protocol conventions. All arithmetic
uses `Decimal` in Python, never `float`.

**Why `period` as `VARCHAR(20)` (e.g. "2025-01") rather than a date range?**
GHG reporting periods are conventions (monthly, quarterly, annual) that don't
map cleanly to calendar date ranges with DST complexity. String periods allow
"2025-Q1", "2025-01", "2025" without schema changes. The `_period_to_date()`
helper converts to a `date` for factor effective-date comparison only.

**Why separate `GHGReport` rows rather than on-the-fly aggregation?**
CSRD Article 29a requires auditable, point-in-time GHG inventory snapshots.
A stored report row captures the state of emissions at report generation time;
subsequent corrections create new records rather than mutating old ones.

**Why `generated_by` on `GHGReport`?**
CSRD requires identification of the person responsible for the GHG inventory.
Storing the user ID at generation time supports the audit trail.

---

## Standards Alignment

| Standard | Status |
|----------|--------|
| GHG Protocol Corporate Standard | Scope 1/2/3 split, methodology field |
| IPCC AR6 factors | Seeded (diesel, petrol, LPG) |
| BEIS 2024 (UK DESNZ) | Seeded (business travel, fleet, waste) |
| KETRACO Kenya grid 2024 | Seeded |
| CSRD ESRS E1 | Aggregation coverage; XBRL tagging is reporting layer |
| CDP Climate | Report data maps to CDP Q7.1–7.4; export format is future work |
| SBTi | Intensity metric via `compute_emission_intensity()`; pathway modelling TBD |
| PCAF | Not in scope (Persefoni / fintech plugin integration roadmap) |
| ISO 14064-1 | Activity-based inventory approach compatible |

---

## Roadmap

- Scope 3 category breakdown (GHG Protocol 15 categories) via `source_category` column
- Climatiq API connector for automatic factor updates with version pinning
- SBTi-aligned reduction pathway modelling (target vs. trajectory)
- PCAF asset-class attribution factors for fintech/banking plugin integration
- CSRD ESRS E1 XBRL tag mapping export
- Utility bill OCR → auto `record_emission()` via documents plugin
- Real-time fleet trip → Scope 1 auto-recording via `ops.fleet.trip.completed` handler
- Carbon budget vs. actual dashboard view
