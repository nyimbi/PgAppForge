# Tier-1 ERP Feature Gap Analysis

**Purpose**: Exhaustive capability-by-capability comparison of PgAppForge against the 5 Tier-1 ERP systems.
**Date**: 2026-06-07
**Benchmark**: SAP S/4HANA, Oracle Fusion Cloud ERP, Workday, Infor CloudSuite, Microsoft Dynamics 365.
**Grading**: ✅ Full / ⚠️ Partial / ❌ Missing — relative to Tier-1 depth, not baseline accounting packages.

---

## A. Financial Management

*Tier-1 reference: SAP Universal Journal, Oracle Fusion Financials, Workday Financial Management.*

| Capability | Tier-1 ERP Standard | Our Status |
|---|---|---|
| General Ledger | Universal Journal (single ledger, unlimited dimensions, real-time aggregation, multi-GAAP parallel ledgers, in-memory, drill-back to source) | ✅ Full — `finance/gl/` with JSONB dimensional GL, real-time IC, multi-book IFRS/local GAAP; matches Workday/Intacct |
| Accounts Payable | Invoice capture + OCR/AI extraction, 3-way match, payment runs (ACH/SEPA/SWIFT), supplier statements, dynamic discounting, AP anomaly/duplicate ML | ⚠️ Partial — `finance/ap/` + `finance/ap_automation/` with 3-way match and regex OCR; no ML extraction at SAP Concur level; no dynamic discounting |
| Accounts Receivable | ML auto-cash application, collections workflow, dunning, deductions/short-pays, lockbox, customer portal | ⚠️ Partial — `finance/ar/` + `finance/credit_management/` cover dunning, exposure, credit hold; no ML cash application; no short-pay/deductions workflow |
| Treasury & Cash Management | BAM, cash positioning, in-house cash, hedge accounting (IFRS 9), FX risk, intercompany loans, SWIFT MT/ISO 20022, money market | ⚠️ Partial — `finance/treasury/` covers BAM, FX, MM; no hedge accounting ledger; cash forecasting is FP&A-driven, not real-time direct method |
| Tax (Indirect/Direct) | Vertex/Avalara-grade engine, e-invoicing (Peppol, SAF-T, Brazil NFe, India GST, KE eTIMS), WHT, transfer pricing, country-by-country reporting | ⚠️ Partial — `finance/tax/` handles VAT/WHT/multi-jurisdiction; no Peppol/SAF-T/CbCR; no transfer pricing documentation |
| Revenue Recognition | ASC 606/IFRS 15 full lifecycle: obligations, SSP, allocation, contract modifications, variable consideration, series POs, POC methods | ✅ Full — `finance/revenue_recognition/` with series PO, OUTPUT/INPUT POC methods, discount allocation |
| Fixed Assets | Multi-book depreciation (tax/book/IFRS), CIP, impairment, asset retirement obligations, IFRS 16 lessee/lessor | ⚠️ Partial — `finance/assets/` with SL/DDB/SYD/MACRS; IFRS 16 lessee ROU depth unverified; ARO not modeled |
| Consolidation | Multi-entity, multi-currency (CTA/OCI), step acquisitions, minority interest, IC elimination, equity method, journal adjustments | ✅ Full — `finance/consolidation/` with FX translation (IAS 21), CTA posted to OCI, IC elimination, minority interest |
| Budgeting / FP&A | Driver-based planning, rolling forecasts, workforce planning, scenario modeling, predictive forecasting (ML), Adaptive/Anaplan parity | ⚠️ Partial — `finance/fpa/` integrated with `hcm/workforce_planning/`; no ML predictive; no driver library at Adaptive scale |
| Period Close | Continuous close, task orchestration, recon certification (BlackLine parity), JE approval, close cockpit, IC matching | ⚠️ Partial — `finance/period_close/` exists with GL period locking; no certification workflow at BlackLine depth |
| Project Accounting | Capitalization, milestone billing, EVM, T&M, multi-currency project P&L | ✅ Full — `projects/` module |
| Grants / Fund Accounting | Restricted/unrestricted funds, FASB ASC 958, donor reporting, encumbrance accounting | ✅ Full — `finance/grants/` (AICPA-grade) |
| Intercompany | Auto-elimination, IC netting, IC invoicing, real-time mirror posting | ✅ Full — `finance/intercompany/` with real-time IC in `post_simple_journal()` |
| Profit Center / Segment | Dimensional P&L, allocation rules, contribution margin | ✅ Full — `finance/profit_center/` |
| Product Costing | Standard/actual costing, variance analysis, material ledger, activity-based costing | ⚠️ Partial — `finance/product_costing/`; material ledger (actual costing with parallel currencies) absent |
| Lease Accounting | IFRS 16 / ASC 842 lessee ROU assets, lease liability, lessor, sale-leaseback | ⚠️ Partial — IFRS 16 in `crm/contracts/`; standalone lease accounting module absent |
| Credit Management | Credit limits, live AR exposure, credit hold, bureau integration (TransUnion/CRB) | ⚠️ Partial — `finance/credit_management/` has limits and hold; no bureau API integration |
| Joint Venture Accounting | JV partner billings, carried interest, cash calls, JV ledger | ❌ Missing |

**Domain verdict**: Strongest area. GL, consolidation, RevRec, grants match or exceed mid-market Tier-1. Gaps concentrated in (a) material ledger, (b) hedge accounting, (c) ML-driven AP/AR, (d) global e-invoicing breadth, (e) lease module.

---

## B. Procurement & Supply Chain

*Tier-1 reference: SAP Ariba + S/4 MM, Oracle SCM Cloud, Infor Nexus.*

| Capability | Tier-1 ERP Standard | Our Status |
|---|---|---|
| Purchase Order Management | Catalog/free-text, blanket/scheduling/contract POs, release strategy, multi-tier approval, change orders, electronic dispatch | ✅ Full — `operations/scm/` with PO + GR + 3-way match |
| Goods Receipt / 3-Way Match | GRN, partial receipts, quality hold, tolerance config, automatic invoice block | ✅ Full |
| Requisition / Procure-to-Pay | Self-service requisitions, catalog punch-in/out (cXML), guided buying, budget check, P-card | ⚠️ Partial — `procurement/` exists; no cXML punch-out; guided buying depth unclear |
| MRP / Material Requirements Planning | Multi-level BOM explosion, net requirements, lot sizing (LOT-FOR-LOT/EOQ/MIN-MAX), time-phased, MPS | ✅ Full — `operations/mrp/` with multi-level DFS BOM + all lot sizing methods |
| Demand Planning / Forecasting | Statistical forecasting (MA/ES/HW), consensus planning, marketing/sales collaboration, what-if scenarios | ⚠️ Partial — `operations/demand_planning/` with Holt-Winters; no consensus planning workflow; not SAP IBP-grade |
| Strategic Sourcing | RFx (RFI/RFQ/RFP), reverse auctions, bid analytics, award optimization, savings tracking | ⚠️ Partial — `procurement/sourcing/` with weighted scoring; no reverse auction; no savings tracker |
| Supplier Management | Onboarding/KYC, sanctions screening, supplier 360, performance scorecards, sustainability ratings | ⚠️ Partial — `procurement/supplier_portal/` with KYC and scoring; no sanctions/watchlist API |
| Contract Lifecycle Management | Clause library, AI extraction, obligation tracking, renewal alerts, eSig | ✅ Full — `crm/contracts/` + `crm/sign/` (DocuSeal) |
| Inventory Management | Multi-location, lot/serial/batch, cycle counting, ABC analysis, consignment, vendor-managed, drop-ship | ✅ Full — `operations/inventory/` with FIFO/LIFO/Weighted-Avg/Standard costing |
| Transfer Orders | Inter-location inventory transfers with in-transit status | ✅ Full — `operations/inventory/services.py` |
| Warehouse Management | Wave/zone/batch picking, slotting optimization, labor mgmt, voice/RF, yard mgmt, cross-dock | ⚠️ Partial — `operations/warehouse/` has basics; slotting + labor mgmt absent |
| Transportation Management | Multi-leg routing, carrier rate shopping, freight audit, dock scheduling, fleet mgmt | ⚠️ Partial — `operations/transport/` + `operations/fleet/`; route optimization (VRP) absent |
| EDI / B2B Integration | X12/EDIFACT (850/810/856/940), GS1, AS2/SFTP, supplier network | ❌ Missing — no EDI module |
| Trade Compliance | Denied party screening, HS/HTS classification, license determination, customs filing | ❌ Missing — no global trade compliance module |
| Available-to-Promise (ATP) | Real-time commitment, multi-location allocation, capable-to-promise (CTP) | ✅ Full — `operations/inventory/atp.py` (ATP + CTP using stock + PO + SO demand) |
| Spend Analytics | Spend cube, category management, tail spend analysis, savings tracking | ❌ Missing |
| Reverse Logistics / RMA | Return authorization, refurbishment, warranty claims, depot repair | ✅ Full — `operations/repair/` |

**Domain verdict**: Solid procure-to-pay backbone puts us above Odoo, level with NetSuite. Major gaps: EDI/B2B network, global trade compliance, advanced WMS, spend analytics.

---

## C. Manufacturing

*Tier-1 reference: SAP PP/QM/PLM, Oracle Manufacturing Cloud, Infor M3, Epicor Kinetic.*

| Capability | Tier-1 ERP Standard | Our Status |
|---|---|---|
| Production Orders | Order release, operation confirmations, backflushing, scrap reporting, work-in-process | ✅ Full — `operations/production/` |
| Bill of Materials (BOM) | Multi-level, phantom assemblies, alternates, effectivity dates, where-used | ✅ Full — multi-level BOM in `operations/mrp/` |
| Assembly / Kitting | Component consumption, finished goods posting, GL variance | ✅ Full — `operations/assembly/` |
| Routings / Work Centers | Operation sequences, setup/run times, alternate routings, work center capacity | ⚠️ Partial — implied in production module; depth unverified |
| Advanced Production Scheduling | Finite capacity scheduling, sequence-dependent setup, optimization solvers | ❌ Missing — confirmed absent |
| Quality Management | Inspection plans, sampling (AQL), SPC, NCR/CAPA, certificates of analysis, supplier quality | ✅ Full — `operations/quality/` |
| MES Integration | OPC-UA, machine telemetry, real-time dashboards, andon, paperless work instructions | ❌ Missing — no MES connector |
| Product Lifecycle Management | ECN/ECO workflow, BOM versioning, stage gates | ✅ Full — `operations/plm/` |
| Process Manufacturing | Recipe/formula mgmt, batch genealogy, by-products/co-products, potency, EBR (21 CFR Part 11) | ⚠️ Partial — scaffolding in industry modules; not at Infor M3/SAP PP-PI depth |
| Lean Manufacturing | Kanban, heijunka, SMED, value stream mapping | ❌ Missing |
| EAM / Asset Management | Preventive/predictive maintenance, asset hierarchies, work orders, RCM | ✅ Full — `operations/eam/` |
| Fleet Management | Vehicle tracking, maintenance, fuel, compliance | ✅ Full — `operations/fleet/` |
| Compliance / Traceability | Lot/serial genealogy, recall management, FDA/FSMA, GS1 EPCIS | ✅ Full — `industry/track_trace/` |
| Material Ledger | Actual costing with parallel currencies, price determination | ❌ Missing |

**Domain verdict**: Strong for asset-intensive and mid-market discrete. Weak for process industries (no recipe management) and Industry 4.0 (no MES, no finite scheduler).

---

## D. Human Capital Management

*Tier-1 reference: Workday HCM, SAP SuccessFactors, Oracle HCM Cloud.*

| Capability | Tier-1 ERP Standard | Our Status |
|---|---|---|
| Core HR / Personnel Records | Worker record, position mgmt, org chart, effective-dated history, global core HR | ✅ Full — `hcm/personnel/` + `hcm/org/` |
| Worker Timeline | Point-in-time state reconstruction, attribute history across all domains | ✅ Full — `hcm/personnel/timeline.py` (WorkerTimelineService) |
| Global Payroll | 50–100+ country statutory engines, gross-to-net, retro, off-cycle, year-end, garnishments | ⚠️ Partial — Authoritative 8 African countries (KE/UG/TZ/RW/NG/GH/ZA/ET); exceeds Tier-1 in target geos; zero coverage outside Africa |
| Benefits Administration | Open enrollment, life events, ACA reporting, dependent verification, carrier EDI feeds | ⚠️ Partial — `hcm/benefits/`; no carrier EDI 834; ACA US-specific reporting absent |
| Talent Management | Performance reviews, succession planning, 9-box, calibration, goal cascade, OKRs | ✅ Full — `hcm/talent/` |
| Learning Management (LMS) | SCORM/xAPI, learning paths, certifications, compliance training, adaptive learning | ✅ Full — `hcm/lms/` |
| Recruiting / ATS | Requisition, sourcing, candidate CRM, interview scheduling, assessments, offer mgmt | ⚠️ Partial — `hcm/referral/` + `hcm/journeys/` provide pieces; no full ATS pipeline (Greenhouse parity) |
| Time & Attendance | Time entry, schedules, shift bidding, time-off, leave accruals, biometric integration | ✅ Full — `hcm/time/` |
| Compensation Management | Salary planning, merit cycles, bonus, equity refresh, comp statements | ✅ Full — `hcm/compensation/` |
| Variable Pay / ICM | Quota mgmt, multi-tier commission, accelerators, splits, clawbacks, manager rollup | ✅ Full — `hcm/variable_pay/` with splits, clawbacks, team rollup |
| Equity Compensation | RSU/ISO/NSO/ESPP, vesting schedules (cliff + graded), exercise, withholding tax | ✅ Full — `hcm/equity_compensation/` |
| Workforce Planning | Headcount budget, scenario modeling, FTE, attrition forecasting | ✅ Full — `hcm/workforce_planning/` |
| Skills Taxonomy / Opportunity Graph | Skills taxonomy, proficiency levels, skill gaps, internal mobility, LMS integration | ✅ Full — `hcm/skills/` (3-tier taxonomy, find_internal_candidates, recommend_learning) |
| Employee Journeys | Onboarding/offboarding task orchestration, dependency graph, 15-task templates | ✅ Full — `hcm/journeys/` |
| Contingent Workforce | SOW, staffing suppliers, timesheets, rate cards, total workforce view | ✅ Full — `hcm/contingent/` |
| Self-Service (ESS/MSS) | Mobile-first, life events, manager approvals, announcements | ✅ Full — `hcm/self_service/` |
| Travel & Expense | OCR receipts, policy enforcement, corporate card, multi-currency | ✅ Full — `hcm/travel_expense/` |
| Wellness / Engagement | Pulse surveys, EAP, wellbeing scores | ✅ Full — `hcm/wellness/` + `platform/surveys/` |
| Workforce Analytics (ML) | Attrition prediction (ML models), DEI dashboards, pay equity analysis | ⚠️ Partial — `hcm/analytics/` rules-based; no trained ML models |
| Performance Review Cycle | Continuous feedback, 360 reviews, calibration, rating distribution mgmt | ⚠️ Partial — `hcm/talent/` has 9-box; continuous feedback cycle depth unclear |
| Position Management | Headcount control, position budgets, vacancy management | ⚠️ Partial — personnel module handles employees; explicit position mgmt budget control absent |

**Domain verdict**: Strongest domain. Africa payroll exceeds every Tier-1 in target geos. Breadth approaches Workday. Gaps: ML-driven analytics, global payroll breadth, full ATS.

---

## E. Customer Relationship Management

*Tier-1 reference: Salesforce, SAP Sales/Service Cloud, Dynamics 365 CE, Oracle CX.*

| Capability | Tier-1 ERP Standard | Our Status |
|---|---|---|
| Sales Force Automation | Lead/opp pipeline, account/contact, activity auto-capture (Einstein), forecast roll-up, territory mgmt | ⚠️ Partial — `crm/sales/`; no AI activity capture; territory mgmt basic |
| Marketing Automation | Multi-channel campaigns, journey builder, lead scoring, ABM, attribution | ✅ Full — `crm/marketing/` + `crm/marketing_automation/` |
| Service / Case Management | Omnichannel routing, knowledge base, SLAs, escalation, swarming, voice/CTI, chatbots | ✅ Full — `crm/service/` |
| CPQ | Guided selling, constraint-based config, pricing rules, approvals, proposal generation | ⚠️ Partial — `crm/cpq/`; constraint-based configurator at SAP CPQ scale absent |
| Commerce | Headless commerce, OMS, PIM, personalization, B2B account hierarchies, punch-out catalogs | ⚠️ Partial — `crm/commerce/` + `crm/pos/`; cXML punch-out + PIM absent |
| Customer Portal | Self-service, invoice payment, order tracking, statement download | ✅ Full — `crm/customer_portal/` with Hyperion-X payment integration |
| Field Service Management | Crew/skill dispatch, route optimization, mobile, IoT-triggered orders, parts logistics | ⚠️ Partial — `crm/field_service/`; crew optimization + IoT absent |
| Subscriptions / Recurring Billing | Plans, usage tiers (GRADUATED/VOLUME/STAIRSTEP), dunning, MRR/ARR, RevRec | ✅ Full — `crm/subscriptions/` with usage tiers |
| E-Sign / CLM | Contract lifecycle, clause library, multi-party signing, DocuSeal (self-hosted, MIT) | ✅ Full — `crm/contracts/` + `crm/sign/` with real DocuSeal API integration |
| Events Management | Event creation, ticketing, registration, check-in, sponsors | ✅ Full — `crm/events/` |
| Appointments / Booking | Service catalog, staff availability, online booking, reminders | ✅ Full — `crm/appointments/` |
| Service Contracts | Recurring maintenance billing, SLA tracking, auto-invoice, asset coverage | ✅ Full — `crm/service_contracts/` |
| POS | Mobile POS, offline, tender types, mobile money (M-Pesa, MTN MoMo) | ✅ Full — `crm/pos/` (mobile money exceeds all Tier-1) |
| AI/ML CRM Intelligence | Lead/opp scoring (Einstein), next-best-action, conversational AI, sentiment analysis | ❌ Missing |
| Partner Relationship Management (PRM) | Channel partner portal, deal registration, MDF, partner training | ❌ Missing |
| Loyalty / CDP | Tier programs, points engine, identity resolution, audience builder | ⚠️ Partial — `analytics/cdp/` scaffolding; loyalty engine not modeled |

**Domain verdict**: Broad CRM footprint matches Dynamics 365 CE in breadth. Major gap: AI scoring/intelligence. CPQ and FSM at mid-market depth, not enterprise.

---

## F. Analytics & Reporting

*Tier-1 reference: SAP Analytics Cloud + Signavio, Oracle Analytics Cloud, Workday Prism + Adaptive.*

| Capability | Tier-1 ERP Standard | Our Status |
|---|---|---|
| Financial Statements | Trial balance, P&L, balance sheet, cash flow, comparative, multi-book, drill-back | ✅ Full — GL module produces all standard statements |
| Dimensional Financial Analysis | P&L by any combination of dimensions (department, project, grant, fund, location) | ✅ Full — `finance/gl/dimension_service.py` with JSONB @> containment |
| Statistical KPI Reporting | Non-monetary accounts (headcount, sq ft, hours) on financial reports | ✅ Full — `finance/gl/` statistical accounts |
| Management Reporting | Departmental P&L, KPI scorecards, board packs | ⚠️ Partial — dimensional GL supports it; no pre-built report library |
| OLAP / Ad-hoc BI | In-memory cubes, semantic layer, drag-drop exploration, self-service BI (Power BI/Tableau parity) | ❌ Missing — no embedded OLAP; no analytics warehouse layer |
| Embedded Analytics | In-app KPIs, contextual analytics on every screen, real-time dashboards | ⚠️ Partial — `platform/anomaly_detection/` + `finance/gl/realtime.py`; not embedded on every entity record |
| Real-time GL Analytics | Live P&L without batch run, O(accounts) not O(entries) | ✅ Full — `finance/gl/realtime.py` (RealtimeGLService) |
| Predictive Analytics | Time-series forecasting, anomaly detection, classification (churn/attrition) | ⚠️ Partial — `analytics/predictive/` + `analytics/ai/` scaffolding; statistical models only |
| GL Anomaly Detection | Journal outlier detection (z-score), weekend postings, round numbers | ✅ Full — `platform/anomaly_detection/` |
| AP Duplicate Detection | ML-powered duplicate invoice identification | ⚠️ Partial — rule-based vendor+amount+date proximity; no ML |
| HR Analytics | Headcount, turnover, DEI, comp-ratio, attrition prediction | ⚠️ Partial — `hcm/analytics/` rules-based; no ML attrition models |
| Supply Chain Analytics | Demand sensing, inventory turns, supplier OTD, OTIF | ⚠️ Partial — individual module dashboards; no unified SCM analytics layer |
| Process Mining | Event log ingestion, process discovery, conformance checking, variant analysis (Celonis/Signavio parity) | ❌ Missing — distinct product category |
| Process Simulation | Discrete-event simulation of process variants, what-if modeling | ❌ Missing |
| Data Warehouse / Lakehouse | Native cloud DW (Prism, Oracle ADW), data sharing, semantic model | ❌ Missing — PostgreSQL is OLTP; no dedicated analytics tier |
| Regulatory Reporting | XBRL, country-specific statutory (SARS, KRA iTax, FIRS, GRA, RRA) | ⚠️ Partial — statutory payroll outputs present; unified statutory reporting dashboard absent |
| Carbon / ESG Analytics | GHG scope 1-3, CSRD, TCFD reporting, intensity ratios | ⚠️ Partial — `platform/carbon/` with Kenya factors; CSRD format not at SAP Sustainability Control Tower depth |

**Domain verdict**: Largest strategic gap vs modern Tier-1. PgAppForge has operational reporting but no semantic BI layer, no process mining, no embedded ML insights. Closing this requires a distinct analytics stack (DuckDB/Pinot + Metabase/Superset + ML pipelines).

---

## G. Platform & Integration

*Tier-1 reference: SAP BTP, Oracle OCI/OIC, Workday Extend, MuleSoft, Power Platform.*

| Capability | Tier-1 ERP Standard | Our Status |
|---|---|---|
| REST / OpenAPI | Full surface, OAuth 2/OIDC, rate limiting, versioning, sandbox, developer portal | ✅ Full — FAB provides ModelRestApi with OpenAPI; auth via OAuth/OIDC |
| Workflow / BPM | BPMN 2.0, human tasks, escalation, parallel/inclusive gateways, DMN decisions, visual modeler | ✅ Full — `plugins/workflow/` with BPMN 2.0 designer + BPMActionRegistry; 29 open capabilities (genuine architectural advantage) |
| Rules Engine | Visual rules, decision tables, simulation, version control (BRF+/SAP equivalent) | ✅ Full — `plugins/rules/` with engine, mixin, DSL, scheduler, CLI, visual builder — exceeds SAP BRF+ in programmability |
| Event Bus / Streaming | Internal event bus, CloudEvents; external event mesh (Kafka/Solace) | ⚠️ Partial — in-process events with foundation/events.py; no external event mesh |
| Integration Platform (iPaaS) | Pre-built connector marketplace (2,000+ SAP, 500+ Oracle), visual integration designer | ❌ Missing — no connector marketplace; bespoke adapters only |
| EDI Adapter | EDIFACT/X12 translator, AS2 transport, mapping studio | ❌ Missing |
| Mobile (Native) | Native iOS/Android apps, offline sync, push notifications, biometric auth | ⚠️ Partial — web responsive; no confirmed native mobile shell |
| Low-Code / Citizen Dev | Drag-drop app builder (Power Apps, SAP Build, Workday Extend), custom objects, no-code forms | ⚠️ Partial — FAB auto-CRUD is developer-low-code; no business-user visual app builder |
| Multi-Tenant SaaS Control Plane | Tenant isolation, per-tenant config, blue/green upgrades, usage metering, chargeback | ⚠️ Partial — `platform/row_security/` provides RLS; full SaaS control plane not confirmed |
| Identity & SSO | SAML/OIDC, SCIM provisioning, MFA, conditional access, JIT roles | ✅ Full — `platform/identity/` + FAB security manager |
| Document Management | Versioning, OCR, classification, retention policies, eSign integration | ✅ Full — `platform/documents/` + `crm/sign/` (DocuSeal) |
| Communication Hub | Email (SMTP), SMS, WhatsApp Cloud API (real HTTP), in-app Discuss, social | ✅ Full — `platform/email/`, `platform/whatsapp/` (with real Cloud API dispatch), `platform/discuss/`, `platform/social/` |
| Row-Level Security | Dimension + role-based data scoping within tenant | ✅ Full — `platform/row_security/` |
| Developer Tooling | SDKs, sandbox, migration tools, CI/CD hooks | ⚠️ Partial — CLI for rules/FAB; no SDK marketplace |
| Internationalization | 30+ languages, RTL, locale-aware formatting, calendar variants | ⚠️ Partial — Flask-Babel framework; coverage breadth unclear |
| Telemetry / Observability | APM, structured logging, distributed tracing, SLO dashboards | ⚠️ Partial — basic logging; no OTEL integration |
| Audit Trail | Tamper-evident, immutable ledger, who/what/when/where on every mutation | ✅ Full — AuditMixin on every model; tamper-evident hash chain recommended |

**Domain verdict**: Platform plumbing (auth, APIs, BPM, rules, communication) is strong and a genuine differentiator. The open BPMActionRegistry has no Tier-1 equivalent. Gaps: connector marketplace, event mesh, low-code for business users, native mobile.

---

## H. Compliance & Risk

*Tier-1 reference: SAP GRC, Oracle Risk Management Cloud, Workday Risk & Controls.*

| Capability | Tier-1 ERP Standard | Our Status |
|---|---|---|
| GRC Framework | Risk register, control catalogue, COSO/ISO 31000 mapping, maturity assessment | ⚠️ Partial — `grc/controls/` exists; Tier-1 depth unclear |
| SOX Compliance | RCM (risk-control matrix), control testing workflow, deficiency tracking, SOX attestation | ⚠️ Partial — workflow-able via BPM; no dedicated SOX module |
| Segregation of Duties (SoD) | Sensitive access analysis, conflict matrix, simulation before role grant, continuous monitoring (SAP Access Control / Pathlock parity) | ❌ Missing — significant gap for regulated enterprises |
| Audit Management | Audit universe, planning, fieldwork, workpapers, findings tracking, follow-up | ⚠️ Partial — generic audit trail; no integrated audit management platform |
| Continuous Auditing | Rule-based transaction monitoring, KCI dashboards, fraud detection | ⚠️ Partial — rules engine could power this; no pre-built monitor library |
| Enterprise Risk Management | Risk register, heat maps, KRI monitoring, scenario analysis, Monte Carlo | ❌ Missing |
| Whistleblower / Ethics | Anonymous reporting, case management, investigations | ❌ Missing |
| Data Privacy (GDPR/CCPA/PDPA) | Consent management, DSAR fulfillment, data discovery, retention rules, breach notification | ✅ Full — `grc/privacy/` |
| Anti-Money Laundering / KYC | Watchlist screening (OFAC/UN/EU), PEP detection, transaction monitoring, SAR filing | ⚠️ Partial — `industry/financial_services/` + `fintech/regulatory/` cover basics; depth vs Actimize/SAS unclear |
| Anti-Bribery / FCPA | Third-party due diligence, gift register, conflict-of-interest declarations | ❌ Missing |
| ESG / Sustainability | GHG Scope 1/2/3, CSRD/EU taxonomy, TCFD, product carbon footprint, social/governance metrics | ⚠️ Partial — `platform/carbon/` with Kenya emission factors; CSRD report format not at SAP Sustainability Control Tower depth |
| Tax Compliance / E-Invoicing | Real-time tax authority APIs (KE eTIMS, Brazil SEFAZ, India GST), SAF-T, Peppol | ⚠️ Partial — multi-jurisdiction tax module; KE eTIMS likely; global e-invoicing network absent |
| Export Controls / Trade | Denied party screening, ECCN classification, export license determination | ❌ Missing |
| Records Management | Retention schedules, legal hold, disposition, DoD 5015.2 | ⚠️ Partial — document management provides basics |
| Cybersecurity GRC | SIEM integration, vulnerability management, incident response, NIST mapping | ⚠️ Partial — `industry/cybersecurity/` scaffolding; specialized SIEM not our domain |
| Policy Management | Policy lifecycle, attestation workflow, training linkage, version control | ⚠️ Partial — documents + BPM composable; no dedicated policy module |
| Board / Regulatory Reporting | Board pack automation, XBRL filing, regulatory submissions | ⚠️ Partial — GL reports + FP&A; XBRL absent |

**Domain verdict**: Weakest domain. Privacy strong; SOX/SoD/ERM thin. Missing SoD analyzer caps addressable market for regulated enterprises (banks > Tier-2, listed companies, US subsidiaries). For mid-market Africa, this is acceptable triage.

---

## Summary Scorecard

| Domain | Breadth | Tier-1 Parity | Strategic Position |
|---|---|---|---|
| **A. Financial Management** | High | Mid-market parity; Tier-1 in GL/ConsoL/RevRec/Grants | Strong — most gaps closeable with targeted build |
| **B. Procurement & SCM** | Medium-high | Mid-market parity; EDI/ATP/trade compliance gaps | Solid for services + light mfg; weak for global trade |
| **C. Manufacturing** | Medium | Mid-market discrete; weak process + Industry 4.0 | Avoid head-to-head with Epicor Kinetic / Infor M3 |
| **D. HCM** | High | Exceeds Tier-1 in Africa; thin globally | **Genuine moat** in target geographies |
| **E. CRM** | High | Dynamics 365 CE breadth; no AI intelligence layer | Adequate for mid-market; AI scoring is the gap |
| **F. Analytics** | Low-medium | Operational only; no BI/OLAP/process mining/ML | **Largest strategic gap** vs modern Tier-1 |
| **G. Platform** | High | Open BPM/rules exceeds SAP openness | **Genuine architectural advantage** |
| **H. Compliance & Risk** | Low-medium | Privacy strong; SOX/SoD/ERM thin | Caps enterprise market; acceptable for mid-market target |

---

## Top 10 Gaps by Strategic Impact

| Rank | Gap | Domain | Impact |
|---|---|---|---|
| 1 | **Embedded BI / OLAP analytics layer** | F | Every Tier-1 now competes on analytics; we have no semantic layer |
| 2 | **AI/ML embedded throughout** | A/E/F | AP duplicate ML, attrition prediction, lead scoring, GL anomalies at depth |
| 3 | **Segregation of Duties analyzer** | H | Blocks regulated enterprise + listed company sales (SOX, ISAE 3402) |
| 4 | **EDI / B2B network connectors** | B | Blocks manufacturing + retail wholesale verticals |
| 5 | **Material ledger + advanced product costing** | A/C | Blocks process manufacturing and multi-currency manufacturing |
| 6 | **Finite capacity scheduling + MES integration** | C | Blocks discrete manufacturing at factory level |
| 7 | **Connector marketplace / iPaaS** | G | Slows every enterprise integration sale |
| 8 | **Process mining** | F | Modern ERP differentiator (SAP Signavio, Celonis) |
| 9 | **Global payroll beyond 8 African countries** | D | Blocks Pan-African multinationals with EU/US operations |
| 10 | **Native mobile + offline capability** | G | Modern UX expectation; field workers and field service |

---

## Unchanged Competitive Advantages

The following capabilities exceed or are unique vs all 5 Tier-1 systems:

| Capability | Why We Win |
|---|---|
| East/West Africa statutory payroll | KE/UG/TZ/RW/NG/GH/ZA/ET — authoritative, current-year rates |
| Mobile Money (M-Pesa / MTN MoMo / Airtel) | No Tier-1 has native mobile money integration |
| SACCO / cooperative banking | Niche not covered by any Tier-1 |
| BPMActionRegistry (open capability bus) | No Tier-1 has an open, namespaced capability registry |
| Zero license cost | SAP: $500K–$10M+; Workday: $150/emp/yr; PgAppForge: infrastructure only |
| Self-hosted / data residency | All Tier-1 are SaaS-only; critical for African regulators |
| DocuSeal (self-hosted eSign) | Replaces $30K+/yr DocuSign with MIT-licensed equivalent |
| Hyperion-X payment processing | Deep Africa payment rails (ISO 8583 + SWIFT + Mobile Money) |

---

*Last updated: 2026-06-07. Review against Gartner Magic Quadrant (Cloud ERP) and Forrester Wave (ERP) annually.*
