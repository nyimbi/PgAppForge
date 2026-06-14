# PgAppForge Composability: Build Any ERP Vertical Without the Lock-In

## The Problem: ERP Systems Trap You

Every ERP system on the market promises flexibility. What they deliver is configuration — a set of switches and toggles that let you adjust how their vision of business works, within limits they set, at a price they control.

**The lock-in lifecycle is predictable:**

You buy SAP or Oracle because your CFO recognizes the brand. The implementation partner charges 3× the license cost to configure it. Within 18 months, your business processes have bent to fit the software. When you need something it doesn't do — and you will — the partner quotes 6 months and a number that makes your board wince. You are trapped.

Odoo's composability model is genuinely better: modules communicate, you can extend models, the community builds verticals. But Odoo's technical substrate shows its age. No async Python, no AI agent framework, no first-class tenant isolation. And for African deployments specifically, Odoo treats your market as an afterthought — KRA eTIMS support, Airtel Money reconciliation, SASRA prudential reporting? Community modules of variable quality, if they exist at all.

ERPNext (Frappe) went further on the Africa story and built decent composability primitives. But its policy algebra is shallow — you can define workflows, but you can't express "approve if loan_officer AND (credit_committee OR CEO_override)" as a first-class business object. And its AI story is not a story — it's a dashboard with a chat widget bolted on.

**The Africa-specific gap is structural, not cosmetic.**

African businesses operate in an environment that most ERP vendors have never modeled:

- **Mobile money is the default payment rail.** MTN MoMo, Airtel Money, and M-Pesa collectively process over $1 trillion annually across the continent. An ERP that treats bank transfers as the primary payment mechanism and mobile money as an afterthought creates daily reconciliation hell for finance teams.
- **Tax compliance is real-time.** Kenya's KRA eTIMS mandate requires every invoice to be submitted to a government control unit at time of issue — not at filing. Uganda EFRIS and Zambia ZRA Smart Invoice work similarly. An ERP that submits taxes quarterly was designed for a different continent.
- **Credit bureau integration is mandatory for lenders.** CRB Africa, Metropol, TransUnion Kenya — any SACCO, microfinance institution, or bank that doesn't check these at loan application time is a compliance risk. Most ERP systems have no concept of a credit bureau query.
- **Regulatory reporting schemas are jurisdiction-specific.** SASRA prudential returns (Kenya SACCOs), Bank of Uganda supervisory returns, Central Bank of Kenya CBK-S01 — these are not "configuration." They require domain-specific models, specific metric definitions (PAR30, PAR60, capital adequacy ratios), and often real-time submission via authenticated APIs.

The result: African businesses either buy expensive global ERPs and pay consultants to build Africa-specific bridges, buy cheap local tools that don't scale, or build in-house systems that never quite get maintained. Spreadsheets are still the dominant tool for African SME finance operations — not because people prefer them, but because the software industry has not built the alternative.

---

## PgAppForge Composability: Build What You Need

PgAppForge is built on a different premise: **you should be able to compose any ERP capability from a library of modules without modifying anyone else's code, and without lock-in to any particular module vendor.**

This is not configuration flexibility. It is structural composability — the same kind that made Unix pipelines, npm packages, and Python decorators so productive. Every module is designed to be combined, extended, and replaced.

The paradigm shift is simple to state, hard to execute well:

**Instead of customizing a monolith, you compose from 155 domain service modules.**

A SACCO platform is SACCO core + mobile money + KYC/CRB + eTIMS + SASRA reporting. A trade finance platform is AR + letters of credit + forex management + SWIFT integration + KYC. A hospital management system is patient records + encounter management + pharmacy + insurance billing + NHIF integration. Each capability is a module. Each module communicates through documented contracts. No module needs to know the internals of any other.

This is not aspirational. It is implemented, tested, and deployed.

---

## The 11 Composability Primitives

PgAppForge's composability system is built on 11 specific mechanisms. Each one solves a category of coupling problem that would otherwise force you to fork modules, write patches, or accept limitations.

### 1. Event Router — React to anything, from anywhere, without touching other teams' code

When a loan gets approved, the compliance module needs to know. When a payment is received, the reconciliation module needs to update. When a new employee is onboarded, the payroll module needs to create a record.

In a monolith, you add these dependencies directly — the loan service imports the compliance service, which imports the reconciliation service, and now you have a tangle. In PgAppForge, every module emits events with glob-patterned routing (`finance.*`, `crm.customer.created`, `*.*.approved`), and any other module can subscribe without the emitter knowing. The event is persisted in the same database transaction — no event is lost on process restart. Dead-letter queuing handles failures automatically.

Your team builds a new compliance check for a specific jurisdiction. Zero changes to the AR module that emits invoices.

### 2. Model Mixins — Add fields to any model in the platform from your plugin

Plugin A owns the `ARInvoice` model. Your Trade Finance plugin needs to add a `letter_of_credit_id` field to it. Without Model Mixins, your options are: fork Plugin A, or store the linkage in a separate table with complex joins.

With PgAppForge's `ModelMixinRegistry` (analogous to Odoo's `_inherit` but for pure SQLAlchemy), your Trade Finance plugin registers its mixin before app startup, and the field is added to the existing model and migration automatically. Alembic autogenerate sees it as a normal column. You never touch Plugin A's source.

This is how the platform's 155 domain modules cooperate without source-level coupling.

### 3. Policy Algebra — Express approval rules as business logic, not code

A loan approval workflow at a SACCO might require: loan officer has submitted, AND (credit committee has approved OR CEO has override authority), AND KYC check has passed, AND credit bureau is clear. Expressing this in a standard role-based access control system means writing conditional code that lives in a view method and can't be audited, tested, or reused.

PgAppForge's Policy Algebra lets you write:

```python
approve_loan = AllOf(
    HasRole('loan_officer'),
    AnyOf(HasRole('credit_committee'), HasPermission('credit.ceo_override')),
    KYCCleared(),
    CRBCheckPassed(),
)
```

This policy object is testable, serializable, auditable, and can be attached to any view method with a decorator. It composes with `&` and `|` operators. It evaluates outside of request context for background jobs. Policy logic stays in your domain layer, not buried in view code.

### 4. AI Pipeline — Chain AI reasoning with your business rules and data

PgAppForge ships a LiteLLM gateway that exposes any LLM (GPT-4, Claude, Gemini, local Ollama models) through a unified interface. But the real value is in the pipeline architecture: AI reasoning steps implement a `Runnable` protocol and can be chained with data transformation steps, database lookups, rule evaluations, and business logic.

A credit scoring pipeline might: fetch the loan application → run CRB check → retrieve transaction history from mobile money → invoke an LLM for narrative risk assessment → apply the Policy Algebra approval rule → emit a loan.assessed event. Each step is independently testable. The pipeline itself is a first-class object that can be versioned, A/B tested, and monitored.

This is AI as infrastructure, not AI as a chatbot widget.

### 5. Semantic Metrics — Cross-domain dashboards without custom SQL

A platform admin wants a dashboard showing PAR30 alongside customer acquisition cost alongside HR headcount trend. These metrics live in different modules with different SQL. The standard solution is a data warehouse, custom ETL, and a BI tool — significant infrastructure for what amounts to "I want to see three numbers on one screen."

PgAppForge's Semantic Registry lets each module declare its metrics in a YAML file: name, label, SQL, unit, aggregation type, and dimensional filters. The registry auto-discovers all `semantic.yaml` files at startup. Any dashboard can query any registered metric by name. The NL analytics service uses the registry to ground LLM responses — "what is our PAR30 this quarter?" resolves to the SQL defined in the SACCO module's semantic file, executed against the current tenant's data.

No data warehouse required for operational dashboards.

### 6. View Slots — Embed insights anywhere in the UI, no UI framework expertise needed

You built a loan risk indicator widget. You want it to appear on the customer detail view, the invoice detail view, and the dashboard — views owned by other modules. Without View Slots, you either fork the templates or accept that your widget lives only where you control the code.

PgAppForge's SlotRegistry provides named injection points across all views. Your plugin registers a provider for `customer.detail.sidebar`. Every customer detail view in the platform automatically renders your widget. Standard slot names are documented (`invoice.detail.footer`, `dashboard.kpi.row`, `nav.top.right`) and discoverable. No JavaScript framework knowledge required — you return HTML from a Python function.

### 7. GraphQL Federation — Unified API across independently deployed modules

Each module exposes its domain entities as federated GraphQL types. The Trade Finance module extends the AR Invoice type with LC fields. The CRM module extends the Customer type with lifetime value. An Apollo Router or Cosmo gateway merges all registered types into a single supergraph.

This means external systems — mobile apps, partner integrations, reporting tools — query a single GraphQL endpoint and get a unified view of your business, even if the modules are deployed as separate services.

### 8. PDL Extends — Schema-driven capability composition in YAML

The PgAppForge Domain Language (PDL) lets you define your entire data model in YAML and generate SQLAlchemy models, Alembic migrations, FAB views, REST API stubs, and pytest fixtures deterministically — no LLM required. The `extends` directive lets one PDL schema inherit and augment another, the same way CSS classes extend base styles.

The visual PDL Entity Designer ships 588 pre-built capability models — every concept from `SACCO.LoanProduct` to `TradeFinance.LetterOfCredit` to `Insurance.ClaimSettlement`. Compose your data model by selecting capabilities and extending them, then generate the entire application stack from YAML.

### 9. Cross-Tenant Aggregation — SaaS platform metrics without bypassing security

Running PgAppForge as a multi-tenant SaaS platform means PostgreSQL Row-Level Security is active everywhere. Platform operators need to aggregate metrics across tenants for billing, capacity planning, and compliance reporting — but they can't bypass RLS for every query.

The `CrossTenantAggregator` and `SystemSession` context manager provide a controlled, audited pathway for cross-tenant queries. Every cross-tenant operation is logged with the requesting user ID, reason, and timestamp. The RLS policies recognize the `SYSTEM` sentinel and allow platform-level reads. No security bypass, full audit trail, clean API.

### 10. Rules Engine — No-code business rules that actually work

The Rules Engine provides a visual builder for configuring conditional logic without code changes: "If payment amount > KES 500,000 AND customer tier = 'Standard', then flag for compliance review AND notify the compliance officer." Rules are stored in the database, evaluated at model lifecycle events, and logged for audit.

Unlike most no-code rule builders, PgAppForge's Rules Engine integrates with the Event Router (rules can emit events) and Policy Algebra (rules can invoke policy checks). It's not isolated — it participates in the same composability fabric as everything else.

### 11. Plugin Scheduler — Background jobs as first-class platform citizens

Scheduled tasks — loan aging runs, mobile money reconciliation, regulatory report generation, credit bureau batch checks — need to run reliably, be observable, and interact safely with the rest of the platform. PgAppForge's scheduler integrates with the event system: jobs can emit events, subscribe to external triggers, and participate in the tenant context. Failure handling, retry logic, and dead-lettering are platform concerns, not concerns for every job author.

---

## Use Case Matrix

| Industry | Core Modules | Compose With | Compliance Layer | Result |
|---|---|---|---|---|
| **SACCO / DT-SACCO** | SACCO core, member mgmt, loan book | Mobile Money (MTN/Airtel), CRB Africa, FOSA module | KRA eTIMS, SASRA prudential returns | Full deposit-taking SACCO platform with SASRA compliance |
| **Trade Finance** | AR, AP, GL | Letters of Credit, SWIFT MT, FX Management | KYC/AML, goAML reporting | Bank-grade trade finance platform |
| **Microfinance** | Lending, collections | Mobile Money, CRB check, group lending | EFRIS (Uganda), ZRA Smart Invoice | MFI platform compliant across EA markets |
| **Insurance** | Policy admin, claims | Mobile Money premium collection, CRB | NHIF integration, IRA reporting | Full P&C or life insurer platform |
| **Hospital / Clinic** | Patient records, encounters | NHIF/SHA billing, pharmacy, lab | MOH reporting, DRG coding | Health information system with national health scheme billing |
| **Manufacturing SME** | Inventory, BOM, production | Supplier portal, quality control | eTIMS on sales invoices, customs integration | ERP for Kenyan/Ugandan manufacturer |
| **Retail Chain** | POS, inventory, loyalty | Mobile Money, gift cards, e-commerce | eTIMS on every receipt | Omnichannel retail with real-time tax compliance |
| **Logistics / Transport** | Fleet, routes, delivery | Track & trace, fuel management | Motor Vehicle Act compliance, KEBS | Last-mile logistics with full asset tracking |
| **Agritech / Off-taker** | Farmer registry, produce buying | Mobile Money disbursement, warehouse receipts | AFEX integration, warehouse receipt financing | Structured commodity finance platform |
| **Government / Public Sector** | Budget control, procurement | Grant management, citizen services | IFMIS integration, OAG audit trail | Government ERP with full accountability controls |

Every row in this table is a composition, not a custom build. The capability modules exist; the Africa compliance connectors exist; the composability primitives wire them together. A focused team can ship a production SACCO platform in 8–12 weeks using PgAppForge — versus 18–24 months building from scratch.

---

## Comparison vs. Competitors

Honest assessment, focused on what matters for Africa-market deployments.

| Dimension | PgAppForge | Odoo 17 | ERPNext / Frappe | SAP Business One |
|---|---|---|---|---|
| **Africa compliance** | Native: eTIMS, EFRIS, ZRA, SASRA, goAML | Community modules, variable quality | Partial Kenya, no Uganda/Zambia | Professional services only, expensive |
| **Mobile money** | 10 connectors: MTN MoMo, Airtel, M-Pesa, Flutterwave, Pesapal, Paystack, AfricasTalking | None native | None native | None |
| **Composability depth** | 11 primitives including Policy Algebra, AI Pipeline, GraphQL Federation | `_inherit`, computed fields, QWeb | DocType hooks, Python controllers | None — modules are monolithic |
| **Policy algebra** | Composable AllOf/AnyOf/Not objects, testable, serializable | Approval workflows (sequential only) | Workflow states (limited composition) | Authorization groups (flat) |
| **AI integration** | LiteLLM gateway, RAG, NL analytics grounded in Semantic Registry, composable AI pipelines | Odoo AI (GPT-4 chatbot) | None native | SAP Joule (early, expensive) |
| **Async Python** | Full async throughout | Sync only | Sync only | N/A (Java/.NET) |
| **PDL code generation** | YAML → model + migration + view + API + tests + Dockerfile + K8s | No equivalent | Desk → form (no migration gen) | Configuration wizard |
| **Multi-tenancy** | PostgreSQL RLS, cross-tenant aggregation | Database-per-tenant or shared | Database-per-tenant | Database-per-instance |
| **License model** | Open source core + commercial modules | Community (LGPL) + Enterprise | MIT + Enterprise | Proprietary |
| **Typical Africa deployment cost** | Open source core free; commercial modules from $X/month | $25–50/user/month + implementation | Free + implementation | $60–100/user/month + implementation |

Key observations:

- **Odoo is the closest technical competitor** — better composability than SAP or ERPNext, large community, decent Python. But no async, no AI pipeline architecture, no Africa-native compliance. For teams that need composability and already know Python, PgAppForge is faster to extend and easier to reason about.
- **ERPNext/Frappe has better Africa traction** but the technical architecture limits composability at scale. The policy algebra is particularly weak — complex approval hierarchies require custom Python, which breaks upgradability.
- **SAP is not a realistic competitor** for most African SME deployments at the technical level — the TCO is prohibitive. It remains a reference point for enterprise feature completeness.
- **No competitor has native mobile money depth.** This is not a small feature gap — for a Kenyan SACCO, mobile money reconciliation is daily critical path work. Having 10 integrated connectors versus "you'll need a consultant to build that bridge" is a structural advantage.

---

## Customer Success Story Templates

### Story 1: Umoja SACCO — Nairobi, Kenya

Umoja SACCO had 8,000 members across three branches and was running their loan book on a combination of Excel and an aging desktop application that hadn't been updated since 2019. The accounting team was spending 3 days per month manually reconciling M-Pesa and Airtel Money statements against loan repayments. The SASRA compliance team was manually compiling the quarterly prudential returns from multiple spreadsheets — a process that took two weeks and introduced errors.

They composed a PgAppForge deployment in 10 weeks: SACCO core for member records and loan management, the mobile money connector for M-Pesa and Airtel Money automated reconciliation, CRB Africa integration for credit checks at loan application time, the SASRA reporting module for automated prudential return generation, and eTIMS for tax invoice compliance.

Month-to-month M-Pesa reconciliation dropped from 3 days to 4 hours. Quarterly SASRA returns went from a 2-week manual process to a one-click report. CRB integration caught 12% of loan applications with adverse bureau history that would previously have been approved manually.

The CFO noted that the PAR30 metric visible on the KPI dashboard — pulled automatically from the Semantic Registry's SACCO module definitions — gave her a real-time view she'd never had before.

### Story 2: TradePath Capital — Kampala, Uganda

TradePath Capital provides trade finance to Ugandan importers and exporters — letters of credit, documentary collections, and invoice discounting. Their prior system was a combination of a core banking package and custom-built modules that their in-house developer had maintained for 6 years. When that developer left, they were unable to extend the system or fix bugs.

They adopted PgAppForge and composed: GL + AR + AP from the finance modules, Trade Finance for LC management, the EFRIS connector for URA e-invoicing compliance, SWIFT MT message handling for international transfers, and the KYC module for ongoing AML monitoring with goAML suspicious transaction reporting.

The composability story mattered directly: their compliance officer needed to add a new field to the LC model to track Uganda Revenue Authority clearance codes. Using the Model Mixin system, their junior developer added this in a single Python file — no changes to the Trade Finance plugin, no database migration conflicts, no regression testing of unrelated features. That change took 90 minutes, compared to the previous estimate of "several weeks" to do the same in the old system.

Their EFRIS compliance rate went to 100% on day one of the new system — every sales invoice is submitted automatically on approval, before the customer even receives it.

### Story 3: Savannah Health Network — Nairobi + Mombasa

Savannah Health Network operates 4 private hospitals and 12 clinics. They needed a unified HIS across all locations with real-time bed availability, insurance billing (NHIF/SHA), pharmacy management, and consolidated financial reporting.

The composability requirement was architectural: each facility needed to be deployable independently with its own data, but the network management team needed consolidated dashboards across all 16 sites. Cross-tenant aggregation in PgAppForge solved this — facility-level RLS kept patient data segregated, while the `SystemSession` API allowed authorized network staff to pull consolidated occupancy, revenue, and clinical metrics.

They composed: HCM personnel for clinical staff management, the health industry module for patient encounters and clinical documentation, billing with NHIF/SHA integration, pharmacy, and the analytics AI module for clinical trend analysis.

The key win: a network-level dashboard showing real-time occupancy, PAR on outstanding insurance claims, and payroll cost as a percentage of revenue — metrics that previously required a weekly manual consolidation exercise — now updates every 15 minutes automatically from the Semantic Registry's cross-tenant aggregation.

---

## Pricing and Packaging

PgAppForge follows a developer-led open source model.

**Open source core** (MIT license): the composability framework (EventRouter, ModelMixinRegistry, Policy Algebra, Semantic Registry, View Slots, PDL engine), the Flask/SQLAlchemy foundation, the security system, the API scaffolding, and all standard ERP domain modules (Finance, HCM, CRM, Operations, GRC). Build any application on this foundation at no cost.

**Commercial modules**: Africa compliance connectors (eTIMS, EFRIS, ZRA, SASRA, goAML), mobile money connectors (MTN MoMo, Airtel Money, M-Pesa with reconciliation), the visual PDL Entity Designer, AI pipeline infrastructure (LiteLLM gateway, RAG, NL analytics), advanced multi-tenancy features (cross-tenant aggregation, SaaS billing), and selected fintech verticals (Core Banking, SACCO with full regulatory compliance, Trade Finance). Priced per deployment or per module, with startup and SME tiers.

**System integrator partnerships**: SIs who deploy PgAppForge for clients get access to the full commercial module library, implementation support, and a revenue share on client licenses they bring. We target SIs currently delivering ERPNext and Odoo deployments who want a deeper Africa-specific stack.

The open source core is not a stripped demo version — it is a production-capable ERP framework. The commercial modules are additive: if you deploy in Uganda, you need EFRIS. If you're building a SACCO platform, you need SASRA reporting. You pay for the Africa-specific depth that took 18–24 months of research and regulatory engagement to build.

---

*PgAppForge is available at [github.com/pgappforge/fab-ext]. Commercial module pricing and SI partnership inquiries: enterprise@pgappforge.io*
