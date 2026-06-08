# Anomaly Detection — Platform Comparison

## What This Module Does

Statistical and rule-based anomaly detection across GL and AP sub-ledgers.
Flags outliers (z-score), weekend postings, round-number transactions,
large transactions (top 1% / >3σ), and duplicate AP invoices. Results land
in an auditable `anm_anomaly` table with severity tiers and a resolution
workflow. BPM-callable via `platform.anomaly.*` capability handles.

---

## Competitive Landscape

### SAP S/4HANA — Journal Entry Audit (ACDOCA + SAP Audit Management)

| Dimension | SAP S/4HANA | This module |
|-----------|-------------|-------------|
| Detection methods | Rule-based ABAP checks, SAP Analytics Cloud ML pipelines (add-on) | z-score, round-number, weekend, duplicate, threshold — built-in, no add-on |
| GL outlier detection | Via SAP Audit Management or third-party ACL/IDEA exports | Native, configurable z-score threshold per run |
| AP duplicate detection | MIRO duplicate invoice check (amount+vendor+date window) | Same logic, pairs within 30-day window, exact invoice_number escalates to CRITICAL |
| Scheduling | Batch jobs in SM36; ML in SAP BTP | BPM action registry; can be wired to any scheduler or workflow trigger |
| Data residency | SAP-managed, multi-layer licensing | Tenant-isolated PostgreSQL JSONB evidence store |
| Deployment | 6–18 month S/4HANA rollout | pip install + Alembic migration |
| Cost | Six-figure licence + BASIS team | Open source |

**Gap vs SAP**: SAP integrates continuous-control-monitoring (CCM) dashboards
natively in Fiori. This module exposes raw data; a Fiori-equivalent dashboard
is a future view layer concern.

---

### Oracle Fusion — Advanced Financial Controls (AFCS)

| Dimension | Oracle AFCS | This module |
|-----------|-------------|-------------|
| Journal anomaly | Pre-built "JE Late Posting", "Round Number", "Split Transaction" controls | Same checks; split-transaction detection not yet implemented (roadmap) |
| Duplicate payments | Payables Duplicate Invoice report | Covered — vendor + amount + date window |
| ML scoring | Oracle Intelligent Controls Graph (ICG) | Not ML-based; pure statistical (z-score); ML integration is a future plug point |
| Evidence storage | Oracle Transactional Business Intelligence tables | JSONB evidence column — flexible, queryable with `->>`/`@>` operators |
| Deployment model | Oracle SaaS only | Self-hosted or any PaaS PostgreSQL |

---

### Workiva — Wdesk Risk & Controls

| Dimension | Workiva | This module |
|-----------|---------|-------------|
| Focus | GRC workflow, narrative, sign-off | Detection + resolution workflow |
| Detection | Integrates data from ERP via connectors | Native GL/AP query, no connector layer needed |
| Audit trail | Document-centric, versioned | Row-level: `resolved_by`, `resolved_at`, `resolution` text + domain event log |
| Price | ~$50–120k/year SaaS | Open source |

---

### ACL / Galvanize / Diligent (Analytics-based audit tools)

| Dimension | Diligent Analytics | This module |
|-----------|-------------------|-------------|
| Approach | Extract → analyse in sandbox | In-process analysis inside the ERP transaction boundary |
| Latency | Batch (daily/weekly extracts) | On-demand or event-triggered (journal.posted → detect) |
| Round-number test | Bennett's digit analysis, Benford's Law | Divisibility-by-100000 check (simple, low false-positive rate for AP/GL) |
| Benford's Law | Supported | Not implemented — roadmap item |
| Integration | REST API import/export | Native SQLAlchemy session; zero extract overhead |

---

## Design Decisions

**Why z-score, not IQR or isolation forest?**
z-score is auditor-legible — "this entry is 4.2 standard deviations from the
account mean" is a sentence an external auditor can put in a work-paper.
IQR is similarly explainable but less sensitive to tails. Isolation forest
requires scikit-learn and a labelled training set; plugging it in as an
alternative scorer is a one-method swap once enough labelled anomalies exist.

**Why per-account grouping for GL outliers?**
Accounts have wildly different typical magnitudes (petty cash vs. intercompany
settlement). A global z-score would flag every large-account entry. Per-account
grouping requires ≥5 entries before scoring (configurable) to avoid
single-entry false positives.

**Why `evidence` JSONB rather than typed columns?**
Each anomaly type carries different evidence (z_score+mean+std for outliers;
invoice_numbers for duplicates). A single JSONB column avoids a sparse
multi-column schema and is fully queryable with PostgreSQL operators.

**Severity mapping**
- z > 5σ → CRITICAL
- z > threshold (default 3σ) → HIGH
- Weekend / round-number → MEDIUM / LOW (auditor judgement; low operational risk)
- AP duplicate with exact invoice number → CRITICAL; same amount+window only → HIGH

---

## Roadmap

- Benford's Law first-digit test for AP invoice amounts
- Split-transaction detection (multiple entries summing to round threshold)
- ML anomaly scorer (isolation forest / autoencoder) as optional scorer class
- Fiori/React dashboard view using `get_anomaly_dashboard()` data contract
- Scheduled daily batch via `CronCreate` integration
- SOX / ISAE 3402 control evidence export (PDF, XLSX)
