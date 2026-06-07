# SAP Feature Gap Analysis

**Purpose**: Identify SAP capabilities not yet present in PgAppForge, prioritised for East African mid-market relevance.
**Date**: 2026-06-06
**Scope**: SAP S/4HANA, SuccessFactors, Ariba, Concur, Fieldglass, Analytics Cloud, Signavio, Sustainability Cloud

---

## Priority Matrix

| Priority | Criteria |
|---|---|
| 🔴 P1 | Blocking for production go-live in target market |
| 🟠 P2 | Significant competitive disadvantage without it |
| 🟡 P3 | Relevant but addressable with workarounds |
| 🟢 Out of scope | Enterprise-tier or Africa-irrelevant |

---

## Finance (S/4HANA Finance)

| SAP Capability | Our Status | Priority | Notes |
|---|---|---|---|
| Purchase Order management | ✅ Implemented | ~~🔴 P1~~ | SCM module: `create_purchase_order()` + GL posting |
| Goods Receipt | ✅ Implemented | ~~🔴 P1~~ | SCM module: `receive_goods()` with GRN |
| 3-way match (PO / GR / Invoice) | ✅ Implemented | ~~🔴 P1~~ | SCM: `match_supplier_invoice()` with tolerance check |
| Revenue recognition engine (ASC 606 / IFRS 15) | ✅ Implemented | ~~🔴 P1~~ | `finance/revenue_recognition/` — contracts, obligations, allocation |
| Group consolidation + intercompany eliminations | ✅ Implemented | ~~🟠 P2~~ | `finance/consolidation/` — FX translation, IC elimination, minority interest |
| Profit center / segment accounting | ✅ Implemented | ~~🟠 P2~~ | `finance/profit_center/` — dimensional P&L, allocation rules |
| Product cost controlling (standard/actual costing) | ✅ Implemented | ~~🟠 P2~~ | `finance/product_costing/` — BOM-driven standard, variance analysis |
| Credit management / credit exposure tracking | ✅ Implemented | ~~🟠 P2~~ | `finance/credit_management/` — live exposure, credit hold |
| Material ledger (actual costing, parallel currencies) | ❌ Missing | 🟡 P3 | Complex; requires inventory + costing integration |
| Cash flow forecasting (direct method) | Partial (FP&A) | 🟡 P3 | FP&A has planning; no real-time cash flow statement |
| Joint venture / cost sharing accounting | ❌ Missing | 🟢 OOS | Upstream-specific |

**We have**: GL (trial balance, income statement, balance sheet), AP, AR, Assets, Tax, FP&A, Treasury.

---

## Procurement (SAP Ariba)

| SAP Capability | Our Status | Priority | Notes |
|---|---|---|---|
| Purchase Order management | ❌ Missing | 🔴 P1 | See Finance above — same gap |
| Goods Receipt / 3-way match | ❌ Missing | 🔴 P1 | Inventory receipts drive 3-way match |
| Strategic sourcing (RFQ/RFP) | ❌ Missing | 🟠 P2 | Sourcing events, bid evaluation |
| Supplier portal + onboarding workflow | ❌ Missing | 🟠 P2 | KYC + bank detail verification |
| Spend analytics + savings tracking | ❌ Missing | 🟡 P3 | Spend cube on top of PO/AP data |
| Contract compliance vs purchase orders | ❌ Missing | 🟡 P3 | Requires CLM integration with PO |
| Supplier network / B2B portal | ❌ Missing | 🟢 OOS | SAP Business Network is enterprise |

**We have**: SCM (procurement planning), Inventory, Warehouse, CLM (contracts).

---

## HCM (SAP SuccessFactors)

| SAP Capability | Our Status | Priority | Notes |
|---|---|---|---|
| Multi-country statutory payroll | ✅ Kenya + Uganda + Tanzania | ~~🔴 P1~~ | `payroll/ke/`, `payroll/ug/`, `payroll/tz/` — authoritative statutory calculators |
| Equity compensation (stock options, RSUs, ESPP) | ❌ Missing | 🟠 P2 | Vesting schedules, tax withholding on exercise |
| Workforce planning / headcount budgeting | ✅ Implemented | ~~🟠 P2~~ | `hcm/workforce_planning/` — FTE budget, scenarios, GL cost center integration |
| Variable pay / sales incentive management | ✅ Implemented | ~~🟠 P2~~ | `hcm/variable_pay/` — quota, tiered commission, accelerators, BPM-driven approval |
| Contingent workforce management (Fieldglass) | ❌ Missing | 🟡 P3 | SOW, staffing agency, time-and-materials |
| People analytics with ML attrition models | Partial (rules-based flight risk) | 🟡 P3 | We have heuristic scoring; SAP has trained ML models |
| Global employee experience (Qualtrics integration) | ❌ Missing | 🟡 P3 | We have surveys; SAP embeds experience data in HR records |

**We have**: Org, Payroll (KE statutory), Personnel, Talent (succession/9-box), Time, T&E, Benefits, Compensation, LMS, ESS/MSS, HR Analytics, Wellness, Referrals, Lunch.

---

## Supply Chain & Manufacturing (SAP IBP / PP / TM)

| SAP Capability | Our Status | Priority | Notes |
|---|---|---|---|
| MRP / Materials Requirements Planning | ✅ Implemented | ~~🔴 P1~~ | `operations/mrp/` — BOM explosion, net requirements, planned orders, purchase req auto-creation |
| Goods Receipt (inventory inbound) | ✅ Implemented | ~~🔴 P1~~ | SCM module `receive_goods()` with accepted/rejected qty and GL |
| Production planning with capacity constraints | Partial (Production module) | 🟠 P2 | We have BOM/work orders; no finite capacity scheduler |
| Demand planning / forecasting | ❌ Missing | 🟠 P2 | Statistical forecasting, consensus planning |
| Transportation management | ❌ Missing | 🟡 P3 | Route optimization, carrier management, freight costing |
| Advanced available-to-promise (ATP) | ❌ Missing | 🟡 P3 | Real-time inventory commitment across locations |
| Extended Warehouse Management (slotting, wave picking) | Partial (WMS) | 🟡 P3 | Our WMS handles basics; no slotting/labor mgmt |

**We have**: Inventory, Production, Quality, SCM (planning), Warehouse (WMS), EAM, Fleet.

---

## Customer Experience (SAP Sales / Service / Commerce Cloud)

| SAP Capability | Our Status | Priority | Notes |
|---|---|---|---|
| Full CRM with pipeline + AI scoring | Partial (Sales, Marketing, Service) | 🟠 P2 | We have modules but no unified Einstein-equivalent scoring |
| Configure-Price-Quote at enterprise scale | Partial (CPQ) | 🟡 P3 | Our CPQ works; SAP CPQ handles constraint-based config at scale |
| B2B Commerce with punch-out catalogs | Partial (Commerce) | 🟡 P3 | Missing punch-out (cXML), punchout catalog management |
| Field Service with IoT / asset telemetry | Partial (FSM) | 🟡 P3 | Our FSM lacks crew optimization + IoT sensor integration |

**We have**: Sales, Marketing, Service, CPQ, Commerce, Field Service, CLM, POS.

---

## Analytics & AI (SAP Analytics Cloud)

| SAP Capability | Our Status | Priority | Notes |
|---|---|---|---|
| Unified BI + financial planning on one canvas | Partial (FP&A) | 🟠 P2 | FP&A plans; no embedded BI exploration layer |
| Embedded AI anomaly detection (AP duplicates, GL outliers) | ❌ Missing | 🟠 P2 | SAP flags duplicate invoices, anomalous journal entries automatically |
| Predictive financial scenarios | ❌ Missing | 🟡 P3 | Driver-based rolling forecasts with ML |
| Process mining (SAP Signavio) | ❌ Missing | 🟡 P3 | Discover actual vs designed process flows from event logs |
| Business process simulation | ❌ Missing | 🟡 P3 | What-if on process variants |

**We have**: FP&A, GL financial statements, HR Analytics, Rules Engine (custom logic).

---

## Sustainability (SAP Sustainability Cloud)

| SAP Capability | Our Status | Priority | Notes |
|---|---|---|---|
| GHG scope 1-2-3 carbon tracking | ❌ Missing | 🟡 P3 | Growing requirement; mandatory for large listed companies |
| CSRD / EU taxonomy reporting | ❌ Missing | 🟢 OOS | EU-regulated; not yet Africa-relevant |
| Product carbon footprint (PCF) | ❌ Missing | 🟢 OOS | Requires BOM + production integration |
| Water / waste tracking | ❌ Missing | 🟢 OOS | Manufacturing-specific |

---

## Integration Platform (SAP Integration Suite / BTP)

| SAP Capability | Our Status | Priority | Notes |
|---|---|---|---|
| Pre-built connectors (2,000+) | Partial (WhatsApp, pswitch) | 🟠 P2 | We have custom adapters; no connector marketplace |
| iPaaS / API management | ❌ Missing | 🟡 P3 | SAP BTP provides managed API gateway |
| Enterprise event mesh | ❌ Missing | 🟡 P3 | Our events are in-process; no external event streaming |
| Low-code application development | ❌ Missing | 🟢 OOS | SAP Build; out of scope for ERP core |

---

## Where We Match or Exceed SAP

| Domain | Assessment |
|---|---|
| Kenya statutory payroll (PAYE 2024/25, NSSF Act 2013, SHIF 2.75%, Housing Levy 1.5%) | **Exceed** — SAP KE payroll is a wrapper; ours is authoritative |
| Mobile Money (M-Pesa / Africa) | **Exceed** — SAP has no native MM module; we have full ISO 8583 + SWIFT + MM |
| SACCO / cooperative banking | **Exceed** — niche not covered by SAP |
| Rules engine composability | **Exceed** — SAP has BRF+ but our rules engine is more programmable and visualizable |
| BPM open capability registry | **Novel** — `BPMActionRegistry` with 29 capabilities; no direct SAP equivalent |
| Deployment cost | **Exceed by 100×** — SAP S/4HANA licenses alone: $500K–$10M+; ours: zero license fee |
| Time-to-value | **Exceed** — SAP implementations take 18–36 months; we target weeks |

---

## Recommended Build Sequence (East Africa Focus)

```
Phase 1 — Unblocking (P1, ~3 months)
  1. Purchase Orders + Goods Receipt
  2. 3-way match engine (PO / GR / Invoice in AP)
  3. MRP (demand-driven replenishment)
  4. Revenue recognition engine (ASC 606 / IFRS 15)

Phase 2 — Competitive Parity (P2, ~3 months)
  5. Uganda + Tanzania statutory payroll
  6. Group consolidation + intercompany eliminations
  7. Profit center accounting
  8. Supplier portal + strategic sourcing (RFQ)
  9. Workforce planning / headcount budgeting

Phase 3 — Differentiation (P3, ~6 months)
  10. Variable pay / incentive management
  11. Demand planning / statistical forecasting
  12. Embedded anomaly detection (AP duplicates, GL outliers)
  13. Carbon / GHG tracking (proactive positioning)
  14. iPaaS connector framework
```

---

*Generated from codebase analysis + SAP product documentation. Review against latest SAP release notes quarterly.*
