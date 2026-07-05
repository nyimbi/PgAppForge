# Tier-1 ERP Feature Gap Analysis

**Purpose**: Exhaustive capability-by-capability comparison of PgAppForge against the 5 Tier-1 ERP systems.
**Date**: 2026-07-04
**Benchmark**: SAP S/4HANA, Oracle Fusion Cloud ERP, Workday, Infor CloudSuite, Microsoft Dynamics 365.
**Grading**: ✅ Full / ⚠️ Partial / ❌ Missing — relative to Tier-1 depth, not baseline accounting packages.

---

## A. Financial Management

*Tier-1 reference: SAP Universal Journal, Oracle Fusion Financials, Workday Financial Management.*

| Capability | Tier-1 ERP Standard | Our Status |
|---|---|---|
| General Ledger | Universal Journal (single ledger, unlimited dimensions, real-time aggregation, multi-GAAP parallel ledgers, in-memory, drill-back to source) | ✅ Full — `finance/gl/` with JSONB dimensional GL, real-time IC, multi-book IFRS/local GAAP; matches Workday/Intacct |
| Accounts Payable | Invoice capture + OCR/AI extraction, 3-way match, payment runs (ACH/SEPA/SWIFT), supplier statements, dynamic discounting, AP anomaly/duplicate ML | ⚠️ Partial — `finance/ap/` + `finance/ap_automation/` implement 3-way match, ISO 20022 payment runs, supplier statement reconciliation, dynamic/early-payment discounts, and regex invoice capture; no trained AP extraction/anomaly ML — infrastructure-deferred |
| Accounts Receivable | ML auto-cash application, collections workflow, dunning, deductions/short-pays, lockbox, customer portal | ⚠️ Partial — `finance/ar/`, `finance/credit_management/`, and `crm/customer_portal/` cover invoices, receipts, aging/dunning, exposure, credit hold, and customer self-service; no trained auto-cash ML, lockbox, or deductions workflow — infrastructure-deferred |
| Treasury & Cash Management | BAM, cash positioning, in-house cash, hedge accounting (IFRS 9), FX risk, intercompany loans, SWIFT MT/ISO 20022, money market | ⚠️ Partial — `finance/treasury/` covers bank accounts, reconciliation, FX deals, MT940/OFX/mobile-money statement import, cash forecasting, and `finance/hedge_accounting/` adds IFRS 9 effectiveness testing/journals; in-house cash and IC loans remain thin |
| Tax (Indirect/Direct) | Vertex/Avalara-grade engine, e-invoicing (Peppol, SAF-T, Brazil NFe, India GST, KE eTIMS), WHT, transfer pricing, country-by-country reporting | ⚠️ Partial — `finance/tax/`, `finance/tax_compliance/`, `platform/edi/`, and `platform/regulatory_reporting/` cover VAT/WHT, SAF-T, Peppol/eTIMS surfaces; no Vertex/Avalara breadth, CbCR, or transfer-pricing documentation |
| Revenue Recognition | ASC 606/IFRS 15 full lifecycle: obligations, SSP, allocation, contract modifications, variable consideration, series POs, POC methods | ✅ Full — `finance/revenue_recognition/` with series PO, OUTPUT/INPUT POC methods, discount allocation |
| Fixed Assets | Multi-book depreciation (tax/book/IFRS), CIP, impairment, asset retirement obligations, IFRS 16 lessee/lessor | ⚠️ Partial — `finance/assets/` covers SL/DDB/SYD/MACRS, CIP/capex, IAS 36 impairment, disposal, and revaluation; `finance/lease_accounting/` covers ROU/liability schedules; ARO still not modeled |
| Consolidation | Multi-entity, multi-currency (CTA/OCI), step acquisitions, minority interest, IC elimination, equity method, journal adjustments | ✅ Full — `finance/consolidation/` with FX translation (IAS 21), CTA posted to OCI, IC elimination, minority interest |
| Budgeting / FP&A | Driver-based planning, rolling forecasts, workforce planning, scenario modeling, predictive forecasting (ML), Adaptive/Anaplan parity | ⚠️ Partial — `finance/fpa/` implements budget cycles/versions, reusable drivers, rolling forecasts, scenario models, KPI targets, and workforce planning integration; trained predictive forecasting remains infrastructure-deferred |
| Period Close | Continuous close, task orchestration, recon certification (BlackLine parity), JE approval, close cockpit, IC matching | ⚠️ Partial — `finance/period_close/` exists with GL period locking; no certification workflow at BlackLine depth |
| Project Accounting | Capitalization, milestone billing, EVM, T&M, multi-currency project P&L | ✅ Full — `projects/` module |
| Grants / Fund Accounting | Restricted/unrestricted funds, FASB ASC 958, donor reporting, encumbrance accounting | ✅ Full — `finance/grants/` (AICPA-grade) |
| Intercompany | Auto-elimination, IC netting, IC invoicing, real-time mirror posting | ✅ Full — `finance/intercompany/` with real-time IC in `post_simple_journal()` |
| Profit Center / Segment | Dimensional P&L, allocation rules, contribution margin | ✅ Full — `finance/profit_center/` |
| Product Costing | Standard/actual costing, variance analysis, material ledger, activity-based costing | ✅ Full — `finance/product_costing/` covers standard/actual cost and variance posting; `finance/material_ledger/` adds period actual costing, movements, actual price determination, FX variance, and settlement |
| Lease Accounting | IFRS 16 / ASC 842 lessee ROU assets, lease liability, lessor, sale-leaseback | ⚠️ Partial — `finance/lease_accounting/` now has standalone IFRS 16/ASC 842 leases, ROU/liability schedules, lessor/lessee type, and modifications; sale-leaseback is not separately modeled |
| Credit Management | Credit limits, live AR exposure, credit hold, bureau integration (TransUnion/CRB) | ⚠️ Partial — `finance/credit_management/` has limits and hold; no bureau API integration |
| Joint Venture Accounting | JV partner billings, carried interest, cash calls, JV ledger | ✅ Full — `finance/joint_venture/` models JV partners, cash calls, partner allocations, and billings against expense journals |

**Domain verdict**: Strongest area. GL, consolidation, RevRec, grants, product costing/material ledger, and JV accounting now match or exceed mid-market Tier-1. Gaps concentrate in ML-driven AP/AR, global tax/e-invoicing breadth, ARO, sale-leaseback depth, and some treasury in-house-cash functions.

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
| EDI / B2B Integration | X12/EDIFACT (850/810/856/940), GS1, AS2/SFTP, supplier network | ⚠️ Partial — `platform/edi/` models trading partners/messages and parses/formats X12, EDIFACT, Peppol, and eTIMS; AS2/SFTP transport and supplier-network depth are not implemented |
| Trade Compliance | Denied party screening, HS/HTS classification, license determination, customs filing | ⚠️ Partial — `procurement/trade_compliance/` implements denied-party screening, HS code mapping, duty estimates, and export-control flags; customs filing/license workflow is incomplete |
| Available-to-Promise (ATP) | Real-time commitment, multi-location allocation, capable-to-promise (CTP) | ✅ Full — `operations/inventory/atp.py` (ATP + CTP using stock + PO + SO demand) |
| Spend Analytics | Spend cube, category management, tail spend analysis, savings tracking | ⚠️ Partial — `procurement/spend_analytics/` computes AP spend cube, supplier/category breakdowns, and tail spend; savings tracking/category management workflow is absent |
| Reverse Logistics / RMA | Return authorization, refurbishment, warranty claims, depot repair | ✅ Full — `operations/repair/` |

**Domain verdict**: Solid procure-to-pay backbone puts us above Odoo, level with NetSuite. EDI, trade compliance, and spend analytics are no longer absent, but remain partial because external networks, filing workflows, and savings management are not Tier-1 depth.

---

## C. Manufacturing

*Tier-1 reference: SAP PP/QM/PLM, Oracle Manufacturing Cloud, Infor M3, Epicor Kinetic.*

| Capability | Tier-1 ERP Standard | Our Status |
|---|---|---|
| Production Orders | Order release, operation confirmations, backflushing, scrap reporting, work-in-process | ✅ Full — `operations/production/` |
| Bill of Materials (BOM) | Multi-level, phantom assemblies, alternates, effectivity dates, where-used | ✅ Full — multi-level BOM in `operations/mrp/` |
| Assembly / Kitting | Component consumption, finished goods posting, GL variance | ✅ Full — `operations/assembly/` |
| Routings / Work Centers | Operation sequences, setup/run times, alternate routings, work center capacity | ✅ Full — `operations/production/` models routings/operations, setup/run times, work centers, capacity, and production schedules |
| Advanced Production Scheduling | Finite capacity scheduling, sequence-dependent setup, optimization solvers | ⚠️ Partial — `operations/capacity_scheduling/` provides finite-capacity backward scheduling, capacity leveling, load analysis, and bottleneck detection; no optimization solver or sequence-dependent setup engine |
| Quality Management | Inspection plans, sampling (AQL), SPC, NCR/CAPA, certificates of analysis, supplier quality | ✅ Full — `operations/quality/` |
| MES Integration | OPC-UA, machine telemetry, real-time dashboards, andon, paperless work instructions | ⚠️ Partial — `platform/mes/` registers machines, ingests telemetry, calculates OEE, raises production alerts, and has an OPC-UA polling stub; no full andon/paperless work-instruction layer |
| Product Lifecycle Management | ECN/ECO workflow, BOM versioning, stage gates | ✅ Full — `operations/plm/` |
| Process Manufacturing | Recipe/formula mgmt, batch genealogy, by-products/co-products, potency, EBR (21 CFR Part 11) | ⚠️ Partial — `operations/process_manufacturing/` now implements recipes/formulas, approvals, batch records, ingredient actuals, yield variance, quality checks, and genealogy; potency, by/co-products, and 21 CFR EBR controls remain incomplete |
| Lean Manufacturing | Kanban, heijunka, SMED, value stream mapping | ⚠️ Partial — `operations/lean/` implements Kanban boards/cards, WIP limits, pull signals, and cycle-time metrics; heijunka, SMED, and value-stream mapping are absent |
| EAM / Asset Management | Preventive/predictive maintenance, asset hierarchies, work orders, RCM | ✅ Full — `operations/eam/` |
| Fleet Management | Vehicle tracking, maintenance, fuel, compliance | ✅ Full — `operations/fleet/` |
| Compliance / Traceability | Lot/serial genealogy, recall management, FDA/FSMA, GS1 EPCIS | ✅ Full — `industry/track_trace/` |
| Material Ledger | Actual costing with parallel currencies, price determination | ✅ Full — `finance/material_ledger/` implements costing periods, material ledgers, movement capture, variance accumulation, settlement, actual price determination, and FX variance tracking |

**Domain verdict**: Strong for asset-intensive and mid-market discrete. Finite scheduling, MES, process manufacturing, lean, and material ledger are now present, but advanced optimization, shop-floor UX, and regulated process-manufacturing controls remain below SAP/Infor depth.

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
| Recruiting / ATS | Requisition, sourcing, candidate CRM, interview scheduling, assessments, offer mgmt | ✅ Full — `hcm/recruiting/` and `hcm/talent/` cover requisitions, candidate/application pipeline, interviews, offers, debriefs, onboarding hooks, and recruiting analytics |
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
| Workforce Analytics (ML) | Attrition prediction (ML models), DEI dashboards, pay equity analysis | ⚠️ Partial — `hcm/analytics/` computes headcount, turnover, diversity, cost-per-hire, dashboard snapshots, and rule-based flight risk; trained attrition/pay-equity models remain infrastructure-deferred |
| Performance Review Cycle | Continuous feedback, 360 reviews, calibration, rating distribution mgmt | ✅ Full — `hcm/performance/` and `hcm/talent/` implement review cycles, self/manager/peer/360 reviews, continuous feedback, calibration stats, nine-box, goals, PIPs, and finalisation |
| Position Management | Headcount control, position budgets, vacancy management | ✅ Full — `hcm/position_management/` provides explicit position records, budgets/headcount control, vacancy lifecycle, and org linkage |

**Domain verdict**: Strongest domain. Africa payroll exceeds every Tier-1 in target geos; ATS, performance, and position management are now first-class. Remaining gaps are trained ML analytics and global payroll breadth outside the implemented countries.

---

## E. Customer Relationship Management

*Tier-1 reference: Salesforce, SAP Sales/Service Cloud, Dynamics 365 CE, Oracle CX.*

| Capability | Tier-1 ERP Standard | Our Status |
|---|---|---|
| Sales Force Automation | Lead/opp pipeline, account/contact, activity auto-capture (Einstein), forecast roll-up, territory mgmt | ⚠️ Partial — `crm/sales/`; no AI activity capture; territory mgmt basic |
| Marketing Automation | Multi-channel campaigns, journey builder, lead scoring, ABM, attribution | ✅ Full — `crm/marketing/` + `crm/marketing_automation/` |
| Service / Case Management | Omnichannel routing, knowledge base, SLAs, escalation, swarming, voice/CTI, chatbots | ✅ Full — `crm/service/` |
| CPQ | Guided selling, constraint-based config, pricing rules, approvals, proposal generation | ✅ Full — `crm/cpq/` implements configurable products with constraint validation, pricing rules, bundles, quote lines, discount approval workflow, and proposal/quote lifecycle |
| Commerce | Headless commerce, OMS, PIM, personalization, B2B account hierarchies, punch-out catalogs | ⚠️ Partial — `crm/commerce/` + `crm/pos/`; cXML punch-out + PIM absent |
| Customer Portal | Self-service, invoice payment, order tracking, statement download | ✅ Full — `crm/customer_portal/` with Hyperion-X payment integration |
| Field Service Management | Crew/skill dispatch, route optimization, mobile, IoT-triggered orders, parts logistics | ⚠️ Partial — `crm/field_service/` now covers work orders, service contracts/SLAs, technician skills, skill-match dispatch ranking, parts, preventive maintenance, route optimization, and feedback; IoT-triggered orders/native mobile remain absent |
| Subscriptions / Recurring Billing | Plans, usage tiers (GRADUATED/VOLUME/STAIRSTEP), dunning, MRR/ARR, RevRec | ✅ Full — `crm/subscriptions/` with usage tiers |
| E-Sign / CLM | Contract lifecycle, clause library, multi-party signing, DocuSeal (self-hosted, MIT) | ✅ Full — `crm/contracts/` + `crm/sign/` with real DocuSeal API integration |
| Events Management | Event creation, ticketing, registration, check-in, sponsors | ✅ Full — `crm/events/` |
| Appointments / Booking | Service catalog, staff availability, online booking, reminders | ✅ Full — `crm/appointments/` |
| Service Contracts | Recurring maintenance billing, SLA tracking, auto-invoice, asset coverage | ✅ Full — `crm/service_contracts/` |
| POS | Mobile POS, offline, tender types, mobile money (M-Pesa, MTN MoMo) | ✅ Full — `crm/pos/` (mobile money exceeds all Tier-1) |
| AI/ML CRM Intelligence | Lead/opp scoring (Einstein), next-best-action, conversational AI, sentiment analysis | ⚠️ Partial — `crm/sales/` has rule-based lead scoring and `platform/ml_predictions/` adds CRM lead scoring/next-action recommendations; trained models, sentiment analysis, and conversational AI are infrastructure-deferred |
| Partner Relationship Management (PRM) | Channel partner portal, deal registration, MDF, partner training | ⚠️ Partial — `crm/prm/` implements partner accounts/tiers, deal registration/approval, MDF requests/approval, and partner metrics; partner training is a placeholder and portal depth is not Tier-1 |
| Loyalty / CDP | Tier programs, points engine, identity resolution, audience builder | ✅ Full — `crm/loyalty/` implements points/tier programs, earning/redemption and liability; `analytics/cdp/` adds identity edges, unified profiles, segmentation, and audience-style cohorts |

**Domain verdict**: Broad CRM footprint matches Dynamics 365 CE in breadth. CPQ and loyalty/CDP are now full. AI intelligence and PRM are present but partial; FSM remains strong mid-market with IoT/native-mobile gaps.

---

## F. Analytics & Reporting

*Tier-1 reference: SAP Analytics Cloud + Signavio, Oracle Analytics Cloud, Workday Prism + Adaptive.*

| Capability | Tier-1 ERP Standard | Our Status |
|---|---|---|
| Financial Statements | Trial balance, P&L, balance sheet, cash flow, comparative, multi-book, drill-back | ✅ Full — GL module produces all standard statements |
| Dimensional Financial Analysis | P&L by any combination of dimensions (department, project, grant, fund, location) | ✅ Full — `finance/gl/dimension_service.py` with JSONB @> containment |
| Statistical KPI Reporting | Non-monetary accounts (headcount, sq ft, hours) on financial reports | ✅ Full — `finance/gl/` statistical accounts |
| Management Reporting | Departmental P&L, KPI scorecards, board packs | ✅ Full — `platform/report_builder/`, `analytics/operational/`, and dimensional GL provide saved report definitions, PDF rendering, KPI snapshots, dashboards, and departmental/board-pack reporting |
| OLAP / Ad-hoc BI | In-memory cubes, semantic layer, drag-drop exploration, self-service BI (Power BI/Tableau parity) | ⚠️ Partial — `platform/analytics_engine/` defines/query cubes and `platform/nl_analytics/` adds semantic SQL assistance; no dedicated OLAP warehouse/in-memory BI tier — infrastructure-deferred |
| Embedded Analytics | In-app KPIs, contextual analytics on every screen, real-time dashboards | ⚠️ Partial — `platform/anomaly_detection/` + `finance/gl/realtime.py`; not embedded on every entity record |
| Real-time GL Analytics | Live P&L without batch run, O(accounts) not O(entries) | ✅ Full — `finance/gl/realtime.py` (RealtimeGLService) |
| Predictive Analytics | Time-series forecasting, anomaly detection, classification (churn/attrition) | ⚠️ Partial — `analytics/predictive/` has model registry/prediction/anomaly records and `platform/ml_predictions/` has rule/embedding-based AP, HR, CRM, GL, and inventory predictions; trained model serving remains infrastructure-deferred |
| GL Anomaly Detection | Journal outlier detection (z-score), weekend postings, round numbers | ✅ Full — `platform/anomaly_detection/` |
| AP Duplicate Detection | ML-powered duplicate invoice identification | ⚠️ Partial — `platform/ml_predictions/` can use embedding similarity for duplicate invoices and `finance/ap_automation/` has capture logs; production ML/model infrastructure remains infrastructure-deferred |
| HR Analytics | Headcount, turnover, DEI, comp-ratio, attrition prediction | ⚠️ Partial — `hcm/analytics/` covers headcount, turnover, diversity, cost-per-hire, dashboard snapshots, and rule-based flight risk; trained attrition/pay-equity models remain infrastructure-deferred |
| Supply Chain Analytics | Demand sensing, inventory turns, supplier OTD, OTIF | ⚠️ Partial — individual module dashboards; no unified SCM analytics layer |
| Process Mining | Event log ingestion, process discovery, conformance checking, variant analysis (Celonis/Signavio parity) | ✅ Full — `platform/process_mining/` discovers process graphs from event logs, computes metrics, detects variants/bottlenecks, and checks conformance |
| Process Simulation | Discrete-event simulation of process variants, what-if modeling | ❌ Missing |
| Data Warehouse / Lakehouse | Native cloud DW (Prism, Oracle ADW), data sharing, semantic model | ❌ Missing — PostgreSQL is OLTP; no dedicated analytics tier |
| Regulatory Reporting | XBRL, country-specific statutory (SARS, KRA iTax, FIRS, GRA, RRA) | ⚠️ Partial — `platform/regulatory_reporting/` adds SAF-T and CSRD services and statutory payroll outputs exist; XBRL and broad country filing packs remain incomplete |
| Carbon / ESG Analytics | GHG scope 1-3, CSRD, TCFD reporting, intensity ratios | ⚠️ Partial — `platform/carbon/` and `grc/sustainability/` cover scope 1-3 records/reports, factors, offsets, ESG metrics, and CSRD service output; TCFD/intensity reporting remains below SAP depth |

**Domain verdict**: Still the largest strategic gap vs modern Tier-1, but no longer operational-only: report builder, analytics cubes, NL analytics, predictive registries, and process mining now exist. True OLAP/lakehouse and trained ML serving remain infrastructure-deferred.

---

## G. Platform & Integration

*Tier-1 reference: SAP BTP, Oracle OCI/OIC, Workday Extend, MuleSoft, Power Platform.*

| Capability | Tier-1 ERP Standard | Our Status |
|---|---|---|
| REST / OpenAPI | Full surface, OAuth 2/OIDC, rate limiting, versioning, sandbox, developer portal | ✅ Full — FAB provides ModelRestApi with OpenAPI; auth via OAuth/OIDC |
| Workflow / BPM | BPMN 2.0, human tasks, escalation, parallel/inclusive gateways, DMN decisions, visual modeler | ✅ Full — `plugins/workflow/` with BPMN 2.0 designer + BPMActionRegistry; 29 open capabilities (genuine architectural advantage) |
| Rules Engine | Visual rules, decision tables, simulation, version control (BRF+/SAP equivalent) | ✅ Full — `plugins/rules/` with engine, mixin, DSL, scheduler, CLI, visual builder — exceeds SAP BRF+ in programmability |
| Event Bus / Streaming | Internal event bus, CloudEvents; external event mesh (Kafka/Solace) | ⚠️ Partial — in-process events with foundation/events.py; no external event mesh |
| Integration Platform (iPaaS) | Pre-built connector marketplace (2,000+ SAP, 500+ Oracle), visual integration designer | ⚠️ Partial — `platform/ipaas/` models connector definitions/instances, integration flows, mapping, and run history; no connector marketplace or visual integration designer |
| EDI Adapter | EDIFACT/X12 translator, AS2 transport, mapping studio | ⚠️ Partial — `platform/edi/` parses/formats X12, EDIFACT, Peppol, and eTIMS with partner/message models; AS2/SFTP transport and mapping studio are absent |
| Mobile (Native) | Native iOS/Android apps, offline sync, push notifications, biometric auth | ⚠️ Partial — web responsive; no confirmed native mobile shell |
| Low-Code / Citizen Dev | Drag-drop app builder (Power Apps, SAP Build, Workday Extend), custom objects, no-code forms | ⚠️ Partial — FAB auto-CRUD is developer-low-code; no business-user visual app builder |
| Multi-Tenant SaaS Control Plane | Tenant isolation, per-tenant config, blue/green upgrades, usage metering, chargeback | ⚠️ Partial — `platform/row_security/` provides data scoping and `platform/tenant_control/` adds tenant lifecycle, usage events, plan limits, and billing customer reference; blue/green upgrade orchestration and chargeback remain thin |
| Identity & SSO | SAML/OIDC, SCIM provisioning, MFA, conditional access, JIT roles | ✅ Full — `platform/identity/` + FAB security manager |
| Document Management | Versioning, OCR, classification, retention policies, eSign integration | ✅ Full — `platform/documents/` + `crm/sign/` (DocuSeal) |
| Communication Hub | Email (SMTP), SMS, WhatsApp Cloud API (real HTTP), in-app Discuss, social | ✅ Full — `platform/email/`, `platform/whatsapp/` (with real Cloud API dispatch), `platform/discuss/`, `platform/social/` |
| Row-Level Security | Dimension + role-based data scoping within tenant | ✅ Full — `platform/row_security/` |
| Developer Tooling | SDKs, sandbox, migration tools, CI/CD hooks | ⚠️ Partial — CLI for rules/FAB; no SDK marketplace |
| Internationalization | 30+ languages, RTL, locale-aware formatting, calendar variants | ⚠️ Partial — Flask-Babel framework; coverage breadth unclear |
| Telemetry / Observability | APM, structured logging, distributed tracing, SLO dashboards | ⚠️ Partial — `platform/observability/` adds OpenTelemetry tracing/metrics helpers and OTLP export when SDK is installed; SLO dashboards/APM product integration remain external |
| Audit Trail | Tamper-evident, immutable ledger, who/what/when/where on every mutation | ✅ Full — AuditMixin on every model; tamper-evident hash chain recommended |

**Domain verdict**: Platform plumbing (auth, APIs, BPM, rules, communication, tenant control, observability, EDI/iPaaS primitives) is strong and a genuine differentiator. The open BPMActionRegistry has no Tier-1 equivalent. Gaps: connector marketplace, event mesh, low-code for business users, native mobile, and integration design tooling.

---

## H. Compliance & Risk

*Tier-1 reference: SAP GRC, Oracle Risk Management Cloud, Workday Risk & Controls.*

| Capability | Tier-1 ERP Standard | Our Status |
|---|---|---|
| GRC Framework | Risk register, control catalogue, COSO/ISO 31000 mapping, maturity assessment | ✅ Full — `grc/controls/` and `grc/erm/` implement control frameworks/catalogue, tests, risk registers, KRIs, heat maps, findings, dashboards, and policy records |
| SOX Compliance | RCM (risk-control matrix), control testing workflow, deficiency tracking, SOX attestation | ⚠️ Partial — `grc/controls/` covers SOX-style frameworks, controls, control tests, findings, and dashboards; formal SOX attestation workflow is not modeled |
| Segregation of Duties (SoD) | Sensitive access analysis, conflict matrix, simulation before role grant, continuous monitoring (SAP Access Control / Pathlock parity) | ✅ Full — `grc/sod/` implements conflict catalogue seeding, user analysis, role-grant simulation, bulk scans, violation records, and risk acceptance/mitigation |
| Audit Management | Audit universe, planning, fieldwork, workpapers, findings tracking, follow-up | ⚠️ Partial — generic audit trail; no integrated audit management platform |
| Continuous Auditing | Rule-based transaction monitoring, KCI dashboards, fraud detection | ⚠️ Partial — rules engine could power this; no pre-built monitor library |
| Enterprise Risk Management | Risk register, heat maps, KRI monitoring, scenario analysis, Monte Carlo | ✅ Full — `grc/erm/` provides risk register, mitigation actions, heat maps, KRI thresholds, and KRI breach monitoring |
| Whistleblower / Ethics | Anonymous reporting, case management, investigations | ✅ Full — `grc/ethics/` implements anonymous token-hashed reports, ethics cases, and follow-up case handling |
| Data Privacy (GDPR/CCPA/PDPA) | Consent management, DSAR fulfillment, data discovery, retention rules, breach notification | ✅ Full — `grc/privacy/` |
| Anti-Money Laundering / KYC | Watchlist screening (OFAC/UN/EU), PEP detection, transaction monitoring, SAR filing | ⚠️ Partial — `industry/financial_services/` + `fintech/regulatory/` cover basics; depth vs Actimize/SAS unclear |
| Anti-Bribery / FCPA | Third-party due diligence, gift register, conflict-of-interest declarations | ✅ Full — `grc/anti_bribery/` implements gift/entertainment logging, high-value/government-official flagging, conflict declarations, and exposure summaries |
| ESG / Sustainability | GHG Scope 1/2/3, CSRD/EU taxonomy, TCFD, product carbon footprint, social/governance metrics | ⚠️ Partial — `platform/carbon/` with Kenya emission factors; CSRD report format not at SAP Sustainability Control Tower depth |
| Tax Compliance / E-Invoicing | Real-time tax authority APIs (KE eTIMS, Brazil SEFAZ, India GST), SAF-T, Peppol | ⚠️ Partial — multi-jurisdiction tax module; KE eTIMS likely; global e-invoicing network absent |
| Export Controls / Trade | Denied party screening, ECCN classification, export license determination | ⚠️ Partial — `procurement/trade_compliance/` covers denied-party screening and HS/export-control flags; ECCN and export-license determination remain incomplete |
| Records Management | Retention schedules, legal hold, disposition, DoD 5015.2 | ⚠️ Partial — document management provides basics |
| Cybersecurity GRC | SIEM integration, vulnerability management, incident response, NIST mapping | ⚠️ Partial — `industry/cybersecurity/` scaffolding; specialized SIEM not our domain |
| Policy Management | Policy lifecycle, attestation workflow, training linkage, version control | ⚠️ Partial — documents + BPM composable; no dedicated policy module |
| Board / Regulatory Reporting | Board pack automation, XBRL filing, regulatory submissions | ⚠️ Partial — GL reports + FP&A; XBRL absent |

**Domain verdict**: No longer the weakest domain. Privacy, GRC controls, SoD, ERM, ethics, anti-bribery, and sustainability are now concrete modules. Remaining gaps are SOX attestation depth, audit workpapers/planning, export-license determination, XBRL/statutory filing breadth, and specialized AML/SIEM tooling.

---

## Summary Scorecard

| Domain | Breadth | Tier-1 Parity | Strategic Position |
|---|---|---|---|
| **A. Financial Management** | High | Mid-market parity; Tier-1 in GL/ConsoL/RevRec/Grants/JV/Material Ledger | Strong — remaining gaps are ML/tax breadth/treasury edge cases |
| **B. Procurement & SCM** | Medium-high | Mid-market parity; EDI/trade/spend now partial | Solid for services + light mfg; weak for global networks |
| **C. Manufacturing** | Medium-high | Mid-market discrete; finite scheduling/MES/process now partial | Stronger, but still below Epicor/Infor on shop-floor optimization |
| **D. HCM** | High | Exceeds Tier-1 in Africa; thin globally | **Genuine moat** in target geographies |
| **E. CRM** | High | Dynamics 365 CE breadth; AI/PRM partial | Adequate for mid-market; AI depth is the gap |
| **F. Analytics** | Medium | Reporting/process mining present; OLAP/ML infra partial | **Largest strategic gap** vs modern Tier-1 |
| **G. Platform** | High | Open BPM/rules exceeds SAP openness | **Genuine architectural advantage** |
| **H. Compliance & Risk** | Medium-high | Privacy, SoD, ERM, ethics, anti-bribery strong; SOX/audit depth partial | Now viable beyond mid-market except deepest regulated use cases |

---

## Top 10 Gaps by Strategic Impact

| Rank | Gap | Domain | Impact |
|---|---|---|---|
| 1 | **Embedded BI / OLAP analytics layer** | F | Every Tier-1 now competes on analytics; we have cube/semantic primitives but no dedicated OLAP warehouse/self-service BI tier |
| 2 | **AI/ML embedded throughout** | A/E/F | AP duplicate ML, attrition prediction, lead scoring, GL anomalies at depth |
| 3 | **EDI / B2B transport network + connector marketplace** | B/G | Parser/flow primitives exist; lack of AS2/SFTP network and marketplace still slows enterprise integration |
| 4 | **SOX attestation + audit workpaper suite** | H | SoD/ERM exist, but listed-company assurance still needs formal attestation/workpapers |
| 5 | **Advanced scheduling optimization + MES execution UX** | C | Finite scheduling/MES telemetry exist; solver-grade sequencing and shop-floor UI remain gaps |
| 6 | **Global e-invoicing/tax network breadth** | A/H | SAF-T/Peppol/eTIMS surfaces exist; no Vertex/Avalara-grade global network |
| 7 | **Connector marketplace / iPaaS** | G | Slows every enterprise integration sale |
| 8 | **Data warehouse / lakehouse tier** | F | Analytics engine runs on OLTP PostgreSQL; no separate warehouse/lakehouse infrastructure |
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

## Change Log

### 2026-07-04

Rows re-graded: 28 total (`❌→✅`: 7, `❌→⚠️`: 12, `⚠️→✅`: 9, `⚠️→❌`: 0).

- `❌→✅`: Joint Venture Accounting; Material Ledger; Process Mining; Segregation of Duties (SoD); Enterprise Risk Management; Whistleblower / Ethics; Anti-Bribery / FCPA.
- `❌→⚠️`: EDI / B2B Integration; Trade Compliance; Spend Analytics; Advanced Production Scheduling; MES Integration; Lean Manufacturing; AI/ML CRM Intelligence; Partner Relationship Management (PRM); OLAP / Ad-hoc BI; Integration Platform (iPaaS); EDI Adapter; Export Controls / Trade.
- `⚠️→✅`: Product Costing; Routings / Work Centers; Recruiting / ATS; Performance Review Cycle; Position Management; CPQ; Loyalty / CDP; Management Reporting; GRC Framework.

*Last updated: 2026-07-04. Review against Gartner Magic Quadrant (Cloud ERP) and Forrester Wave (ERP) annually.*
