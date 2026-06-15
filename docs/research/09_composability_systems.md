# Composable Systems Research — PgAppForge Gap Analysis

**Date:** 2026-06-14  
**Scope:** Deep survey of composability patterns across 7 system families;
full audit of PgAppForge's 12 composability dimensions; ranked gap closure plan.

---

## 1. Universal Principles of Composable Systems

Drawn from Unix, Haskell, React, Kubernetes, Odoo, dbt, LangChain:

| # | Principle | Canonical example | Anti-pattern |
|---|---|---|---|
| P1 | **Single-purpose units** | Unix commands (`sort`, `grep`) | Monolithic functions with side effects |
| P2 | **Uniform interface** | Unix pipe `|` (bytes); React props; dbt `ref()` | Bespoke coupling between specific units |
| P3 | **Late binding / open extension** | Odoo `_inherit`; Kubernetes CRD; Emacs advice | Hard-coded imports between modules |
| P4 | **Separation of construction from execution** | Terraform plan/apply; LangChain LCEL chain | Mixing side effects into composition operators |
| P5 | **Declared dependencies, resolved externally** | Nix flakes; dbt `ref()`; Terraform providers | Global singletons, runtime `import` |
| P6 | **Algebraic closure** — composition of units is still a unit | Haskell monoids; React: `<A><B/></A>` is still JSX | Composition that produces a different type |
| P7 | **Explicit contracts at boundaries** | OpenAPI; dbt contracts; TypeScript interfaces | Duck typing across module boundaries |

---

## 2. Best-in-Class Systems by Composability Dimension

### 2.1 Plugin / Module Composition
**Best: Odoo (Python)**

Odoo's module system is the most compositionally powerful in the ERP world:
- `_inherit = 'model.name'` — any module can extend any model's fields, methods, defaults
- `_inherits = {'hr.employee': 'employee_id'}` — delegation inheritance; embed another model's identity
- View inheritance via `<xpath expr="//field[@name='partner_id']" position="after">` — inject UI into any view at any position
- `post_init_hook` / `uninstall_hook` — lifecycle composition
- Access rights composed via CSV rules that stack across modules
- Computed fields that cross module boundaries (e.g., payroll adding computed wage to HR employee)

**Key insight:** Odoo's composability primitive is the **model name string** — a loose coupling that allows any module to extend any other module's surface without a direct Python import.

### 2.2 Schema / Model Composition
**Best: dbt (SQL)**

- `ref('model_name')` — declare a dependency; dbt resolves at compile time into a DAG
- `source('schema', 'table')` — typed access to raw data
- Semantic layer (`metrics`, `entities`, `dimensions`) — composable business logic on top of SQL
- `dbt contracts` — explicit column-level type guarantees at composition boundaries
- Packages — reuse semantic definitions across projects

**Key insight:** dbt's composability primitive is the **named model string** + explicit DAG. The DAG enforces that composition is acyclic and resolves execution order automatically.

### 2.3 UI / View Composition
**Best: React + Radix UI (headless components)**

- Component = `(props) => VNode` — pure function, no side effects
- Composition operator = JSX nesting — algebraically closed (JSX in JSX is still JSX)
- Radix UI's **headless components** (slots, compound components) — style-free behaviour containers any design system can compose into
- Module Federation — compose UI components from independently deployed services at runtime
- `children as function` / render props — inversion of control for composition

**Key insight:** The headless pattern (Radix, react-aria) separates **behaviour** from **presentation** — enabling composability across design systems.

### 2.4 Event / Workflow Composition
**Best: LangChain LCEL + Kafka Streams**

LangChain LCEL (Expression Language):
- `Runnable` protocol: any object with `.invoke()`, `.stream()`, `.batch()`, `.astream()`
- `|` operator composes runnables: `prompt | llm | parser` produces a new `Runnable`
- `RunnableParallel(a=chain_a, b=chain_b)` — parallel fan-out, still a `Runnable`
- `RunnablePassthrough`, `RunnableLambda` — adapters that preserve the interface
- `.with_retry()`, `.with_fallbacks()`, `.with_config()` — decorators that don't break composition

Kafka Streams:
- `KStream.filter().map().groupByKey().aggregate()` — composable stateful operators
- Topology builder — explicit DAG of stream processors
- State stores shared across operators within a topology

**Key insight:** The magic is the **uniform interface** (`Runnable`) + **operator overloading** (`|`). Every composed unit has the exact same interface as its parts.

### 2.5 Permission / Policy Composition
**Best: AWS IAM + Open Policy Agent (OPA)**

AWS IAM policy algebra:
- Policies compose via `Allow`/`Deny` statements; `Deny` always wins (explicit deny > allow)
- `Resource` patterns (`arn:aws:s3:::bucket/*`) compose with wildcards
- `Condition` blocks — additional predicates that AND with the statement
- `aws:PrincipalTag` — attribute-based access; tags compose as facts

OPA Rego:
- Rules are composable Horn clauses: `allow { condition_a; condition_b }` is AND
- `allow := true` from any rule is OR
- Packages import each other; policies compose across packages
- Data documents (context) separate from policy logic

**Key insight:** Good permission systems are **monotone** — adding more policies can only expand or restrict, never break existing grants. OPA's Rego is declarative (no side effects in policy logic).

### 2.6 Data / Report Composition
**Best: dbt semantic layer + Apache Superset**

- `metric` definitions in dbt — computed once, referenced everywhere
- `entity` + `measure` + `dimension` — building blocks that compose into any slice/dice query
- Superset's computed columns, virtual datasets — compose raw tables into analytical views
- Cube.js: pre-aggregation + measures compose algebraically (additive, non-additive classification)

**Key insight:** Report composability requires knowing the **aggregation type** of each measure (additive sums, non-additive ratios, semi-additive stock quantities). Systems that track this allow safe composition.

### 2.7 AI Agent Composition
**Best: LangGraph (stateful) + DSPy (optimizable)**

LangGraph:
- `StateGraph` — nodes are functions, edges are conditionals
- State is typed (TypedDict) — contracts at every node boundary
- `add_node`, `add_conditional_edges` — DAG composition
- `interrupt_before` / `interrupt_after` — human-in-the-loop at any point
- Subgraphs — compose graphs into larger graphs (recursive composition)

DSPy:
- `Module` with `forward()` — composable like PyTorch `nn.Module`
- `dspy.Predict`, `dspy.ChainOfThought`, `dspy.ReAct` — composable reasoning strategies
- Optimizer (MIPROv2, BootstrapFewShot) — automatically improves any composed pipeline

**Key insight:** LangGraph's key innovation is **typed shared state** — every node reads/writes to a typed dict, so composition preserves schema contracts. DSPy's key innovation is **optimizable modules** — composition doesn't prevent automatic improvement.

---

## 3. PgAppForge Composability Audit

### Dimension-by-Dimension Gap Matrix

| Dimension | Status | Current Mechanism | Gap |
|---|---|---|---|
| **1. Plugin composition** | ✅ GOOD | `depends_on` list; `install_all()` topological sort; `subscribe_to()` + `_EVENT_BUS` | No version constraints on deps; no capability negotiation |
| **2. Model composition** | ✅ CLOSED | Each plugin owns its models; no cross-plugin field injection | CLOSED — ModelMixinRegistry (`pgappforge/composition/mixins.py`) |
| **3. View injection** | ✅ CLOSED | `register_views()` adds only the plugin's own views | CLOSED — ViewSlotRegistry (`pgappforge/ui/slots.py`) |
| **4. Event composition** | ✅ CLOSED | `DomainEventLog` (durable) + `_EVENT_BUS` (in-process); `subscribe_to()` naming convention | CLOSED — EventRouter + @on_event + EventWorker (durable, multi-worker safe) |
| **5. Workflow composition** | ✅ CLOSED | YAML engine + BPM action registry | CLOSED — sub-workflow, event triggers, parallel branches |
| **6. Rule composition** | ✅ CLOSED | Rules engine per model via YAML DSL | CLOSED — EventRuleEngine for cross-model event-triggered rules |
| **7. API composition** | ✅ CLOSED | Each plugin registers independent REST endpoints | CLOSED — GraphQL federation (`pgappforge/graphql/federation.py`) |
| **8. Permission composition** | ✅ CLOSED | FAB's flat RBAC (role → permission strings) | CLOSED — PolicyAlgebra with AND/OR/NOT + attribute conditions (`pgappforge/security/policies.py`) |
| **9. Schema composition** | ✅ CLOSED | PDL schemas are standalone; no `extends` or `mixin` | CLOSED — PDL `extends` + mixin inheritance (`pgappforge/pdl/schema.py`) |
| **10. Report composition** | ✅ CLOSED | `AnalyticsEngine` defines cubes per tenant | CLOSED — MetricRegistry + DerivedMetric + formula evaluator (`pgappforge/analytics/metrics.py`) |
| **11. AI agent composition** | ✅ CLOSED | LiteLLM gateway + `NLAnalyticsService` separately | CLOSED — composable AI pipeline with typed state (`pgappforge/ai/pipeline.py`) |
| **12. Multi-tenant composition** | ✅ CLOSED | PostgreSQL RLS + `TenantControlService` | CLOSED — CrossTenantAggregator + SystemSession |

---

## 4. Systems We Cannot Currently Compose

**All 14 failure scenarios resolved as of 2026-06-15.**

~~1. **Loyalty + Mobile Money payout**: Cannot compose `LoyaltyService.redeem_points()` → `AirtelMoneyService.disburse()` without writing a one-off service. No reactive pipeline.~~

~~2. **SACCO loan + Insurance check**: Cannot write a rule "if member applies for loan, AND their insurance policy is lapsed, BLOCK". Rules are model-scoped; this crosses SACCO + Insurtech boundaries.~~

~~3. **HCM payroll + Tax compliance**: Cannot auto-trigger eTIMS payslip submission when payroll is processed. Would need manual wiring; no event pipeline.~~

~~4. **CRM customer + AR invoice + Loyalty balance** in one API call: Three separate REST endpoints; no GraphQL federation or batch API.~~

~~5. **Extended AR invoice from another plugin**: If Trade Finance wants to add `letter_of_credit_id` to `ARInvoice`, it must fork `ar/models.py` — no `_inherit` equivalent.~~

~~6. **Cross-domain report**: "Show me total revenue (Finance) by sales rep (CRM) with their headcount cost (HCM)" — three cube sources; analytics engine cannot join across cubes.~~

~~7. **Permission: approve_loan AND (is_loan_officer OR has_credit_committee_role)**: FAB RBAC is flat; AND conditions on roles are impossible without code.~~

~~8. **Sub-workflow**: SACCO member onboarding workflow cannot call the KYC workflow as a sub-process; they must be two separate flat workflows.~~

~~9. **Composed PDL schema**: Cannot `extend: finance.ar.ARInvoice` in a PDL schema to inherit its fields and add customs — every PDL entity is standalone.~~

~~10. **Multi-tenant SaaS report**: Platform admin cannot aggregate "total revenue across all tenants" without bypassing RLS.~~

~~11. **AI agent chain**: Cannot compose an "NL query → SQL → BI chart" agent with a "validate result → explain in business language" agent using a uniform interface.~~

~~12. **UI widget from plugin B in plugin A's dashboard**: `ERPPlugin_A.DashboardView` cannot embed `ERPPlugin_B.KPIWidget` — no slot/injection mechanism.~~

~~13. **Rule that fires a workflow**: Business rules cannot trigger a workflow instance start. The rules engine and workflow engine are disconnected.~~

~~14. **Computed cross-plugin field**: Cannot define a computed field on `Customer` that reads from `LoyaltyAccount.points_balance` without modifying `Customer` directly.~~

---

## 5. Gap Severity Ranking

Ranking formula: **Business Impact** (1-5) × **Frequency of need** (1-5) × **Implementation feasibility** (1-5, inverted — harder = lower score)

| Rank | Gap | Impact | Frequency | Feasibility | Score | Why urgent |
|---|---|---|---|---|---|---|
| 1 | **Cross-plugin event pipeline** (durable, multi-worker, filter/map) | 5 | 5 | 4 | 100 | Every fintech integration (M-Pesa → reconcile GL → notify customer) needs this |
| 2 | **Model composition via SQLAlchemy mixins** (`_inherit` equivalent) | 5 | 5 | 4 | 100 | Trade Finance, Club management, any vertical extending core models |
| 3 | **Sub-workflow composition** (workflow calls workflow) | 4 | 5 | 5 | 100 | KYC → onboarding → loan → insurance is today's most common workflow |
| 4 | **Rule → event → workflow trigger** (cross-engine wiring) | 5 | 4 | 4 | 80 | "When invoice approved, start payment workflow" needs no code |
| 5 | **Permission algebra** (AND/OR/NOT on roles) | 4 | 4 | 5 | 80 | Loan approval needs committee quorum; current RBAC cannot express it |
| 6 | **PDL schema extension** (`extends:` keyword) | 4 | 4 | 5 | 80 | PDL-first workflow: extend vendor model with Africa-specific fields |
| 7 | **Semantic metric layer** (named metrics, aggregation types) | 4 | 3 | 3 | 36 | Cross-plugin BI without raw SQL joins |
| 8 | **View slot injection** (plugin B injects into plugin A's view) | 3 | 4 | 3 | 36 | AI copilot sidebar in any view; loyalty balance in customer view |
| 9 | **AI agent Runnable interface** (LCEL-equivalent) | 4 | 3 | 3 | 36 | Composable NL → SQL → explain → chart pipelines |
| 10 | **GraphQL federation** (cross-plugin unified API) | 3 | 2 | 2 | 12 | Nice-to-have; mobile apps benefit most |

---

## 6. Architectural Patterns to Adopt

| Gap | Pattern to adopt | Reference implementation |
|---|---|---|
| Cross-plugin events | **Durable event router** with filter/map DSL; outbox pattern for multi-worker | Kafka Streams topology; LangChain `RunnablePassthrough` |
| Model composition | **SQLAlchemy mixin registry** — plugins register mixins; foundation applies them at mapper init | Odoo `_inherit`; Django abstract models |
| Sub-workflow | **Named workflow references** in YAML step type `call_workflow:` | AWS Step Functions; Prefect sub-flows |
| Rule → event trigger | **Action type: `emit_event`** in rules DSL | Salesforce Process Builder → Platform Events |
| Permission algebra | **Policy objects** with `__and__`, `__or__`, `__invert__`; evaluate against request context | OPA Rego; django-rules |
| PDL extends | **`extends:` keyword** in PDL YAML that copies + overrides parent fields | dbt `ref()`; Nix `lib.mkMerge` |
| Semantic metrics | **`MetricRegistry`** with declared aggregation type (additive/non-additive) | dbt semantic layer; Cube.js |
| View slots | **`@slot` decorator** + `SlotRegistry`; views declare named slots; plugins fill them | Web Components `<slot>`; Odoo `<xpath>` |
| AI Runnable | **`Composable` protocol** with `invoke()`, `pipe()`, `parallel()` | LangChain `Runnable`; PyTorch `nn.Module` |

---

## 7. Implementation Plan

### Phase 1 — Foundation (implement now, ~5 days)

These 5 features unlock all downstream composition:

**P1.1: Durable cross-plugin event router** (`pgappforge/events/`)
- `EventRouter` class: subscribe handlers by event pattern glob (`finance.*.posted`)
- Persists to `DomainEventLog`; worker polls with exponential back-off + dead-letter queue
- `@on_event('finance.ar.invoice.approved')` decorator on any plugin method
- Files: `pgappforge/events/router.py`, `pgappforge/events/worker.py`, `pgappforge/events/decorators.py`

**P1.2: SQLAlchemy model mixin registry** (`pgappforge/composition/mixins.py`)
- `ModelMixinRegistry` — plugins call `register_mixin(target_model, MixinClass)`
- `apply_all_mixins()` called at app startup before mapper configuration
- Works by adding columns/relationships to the target model's `__table__` before SQLAlchemy compiles mappers
- Files: `pgappforge/composition/mixins.py`, `pgappforge/composition/__init__.py`

**P1.3: Sub-workflow composition** (extend `pgappforge/workflow/engine.py`)
- New step type: `call_workflow: workflow_name` with `inputs:` and `outputs:` mapping
- `PgAppForgeWorkflowEngine.start()` accepts `parent_instance_id` for correlation
- Files: `pgappforge/workflow/engine.py` (extend), `pgappforge/workflow/yaml_dsl.py` (extend)

**P1.4: Rule → event trigger action** (extend `pgappforge/plugins/rules/engine.py`)
- New action type: `emit_event: 'event.type'` with `payload:` template (using `_resolve_value`)
- Calls `emit_event()` from `erp.foundation.events` after rule fires
- Files: `pgappforge/plugins/rules/engine.py` (add action handler)

**P1.5: Permission algebra objects** (`pgappforge/security/policies.py`)
- `Policy` base class with `check(user, context) -> bool`
- `AllOf(*policies)`, `AnyOf(*policies)`, `Not(policy)` combinators
- `HasRole(role_name)`, `HasPermission(perm)`, `IsOwner(field)` primitives
- `@require_policy(AllOf(HasRole('loan_officer'), AnyOf(HasRole('manager'), HasPermission('credit.override'))))` decorator
- Files: `pgappforge/security/policies.py`, `pgappforge/security/decorators.py` (extend)

### Phase 2 — Expressiveness (1-2 weeks)

**P2.1: PDL `extends:` keyword**
- `entity: LoyalCustomer extends: crm.Customer` — inherit parent fields, can override
- Files: `pgappforge/pdl/schema.py` (extend `PDLEntity`), `pgappforge/pdl/generators.py`

**P2.2: Semantic metric registry** (`pgappforge/analytics/metrics.py`)
- `Metric(name, model, field, agg_type: Literal['sum','avg','count','last_value'])`
- `MetricRegistry.register()`, `MetricRegistry.query(metric_names, filters, group_by)`
- Drives the visual analytics engine; safe cross-plugin composition
- Files: `pgappforge/analytics/metrics.py`, register hooks in ERP plugins

**P2.3: View slot injection** (`pgappforge/ui/slots.py`)
- `SlotRegistry` — global registry of named slot providers
- `@slot_provider('customer.detail.sidebar')` — plugin registers a render function
- `{% render_slot 'customer.detail.sidebar' %}` — Jinja2 template tag
- Files: `pgappforge/ui/slots.py`, `pgappforge/templates/jinja2_ext.py`

### Phase 3 — Advanced (3-4 weeks)

**P3.1: AI Composable pipeline** (`pgappforge/ai/pipeline.py`)
- `Composable` protocol: `invoke(input) -> output`, `pipe(other) -> Composable`, `parallel(**branches) -> Composable`
- Built-in: `LLMStep`, `SQLStep`, `RuleStep`, `WorkflowStep`, `ChartStep`
- Files: `pgappforge/ai/pipeline.py`, `pgappforge/ai/steps.py`

**P3.2: Cross-tenant aggregation** (`pgappforge/multitenancy/aggregation.py`)
- `SystemSession` context manager: bypasses RLS for platform-admin queries
- `CrossTenantMetric` — aggregate a metric across all tenants with proper audit logging
- Files: `pgappforge/multitenancy/aggregation.py`

**P3.3: GraphQL federation stub** (`pgappforge/graphql/federation.py`)
- Extend existing `pgappforge/graphql/` to emit `@key` directives for entity federation
- Each plugin exposes its entities as federated GraphQL types
- Files: `pgappforge/graphql/federation.py`

---

## 8. Sources

- Odoo technical documentation: https://www.odoo.com/documentation/17.0/developer/reference/backend/orm.html
- LangChain LCEL docs: https://python.langchain.com/docs/concepts/lcel/
- LangGraph: https://langchain-ai.github.io/langgraph/
- dbt semantic layer: https://docs.getdbt.com/docs/build/semantic-layer
- MACH Alliance: https://machalliance.org/
- Open Policy Agent: https://www.openpolicyagent.org/docs/latest/
- AWS IAM policy evaluation logic: https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_policies_evaluation-logic.html
- Kubernetes Crossplane XRDs: https://docs.crossplane.io/latest/concepts/composite-resources/
- NixOS module system: https://nixos.org/manual/nixos/stable/#sec-writing-modules
- PgAppForge codebase — direct audit of:
  - `pgappforge/plugins/base_plugin.py` (plugin interface)
  - `pgappforge/plugins/erp/foundation/events.py` (event system)
  - `pgappforge/workflow/engine.py` (workflow engine)
  - `pgappforge/plugins/rules/engine.py` (rules engine)
  - `pgappforge/pdl/schema.py` (schema DSL)
  - `pgappforge/multitenancy/rls.py` (multi-tenancy)

---

## 9. Implementation Status (as of 2026-06-15)

All 12 composability dimensions are now ✅ CLOSED.

| Feature | File | Status |
|---|---|---|
| P1.1 Cross-plugin EventRouter | pgappforge/events/router.py + decorators.py | ✅ |
| P1.1+ Durable EventWorker | pgappforge/events/worker.py | ✅ |
| P1.2 ModelMixinRegistry | pgappforge/composition/mixins.py | ✅ |
| P1.3 Sub-workflow | pgappforge/workflow/engine.py (call_workflow step) | ✅ |
| P1.3+ Workflow event triggers | pgappforge/workflow/triggers.py | ✅ |
| P1.3+ Workflow parallel branches | pgappforge/workflow/engine.py (parallel step) | ✅ |
| P1.4 Rule → event action | pgappforge/plugins/rules/engine.py | ✅ |
| P1.5 Permission algebra | pgappforge/security/policies.py | ✅ |
| P2.1 PDL extends | pgappforge/pdl/schema.py | ✅ |
| P2.2 Semantic metric registry | pgappforge/analytics/metrics.py | ✅ |
| P2.2+ Derived metrics | pgappforge/analytics/metrics.py (DerivedMetric) | ✅ |
| P2.3 View slot injection | pgappforge/ui/slots.py | ✅ |
| P3.1 AI composable pipeline | pgappforge/ai/pipeline.py | ✅ |
| P3.2 Cross-tenant aggregation | pgappforge/multitenancy/aggregation.py | ✅ |
| P3.3 GraphQL federation | pgappforge/graphql/federation.py | ✅ |
| P4.4 Cross-model event rules | pgappforge/plugins/rules/event_rules.py | ✅ |

---

## Open Questions

1. ~~Should the model mixin registry use SQLAlchemy events (`mapper_configured`) or modify `__table__` directly?~~ **Resolved** — uses `__table__.append_column()` directly (before mapper config). Alembic note: call `apply_all_mixins()` before `db.init_app()` to ensure Alembic sees columns.
2. ~~Should the durable event router use a background thread, a Celery worker, or a FastAPI background task?~~ **Resolved** — EventWorker uses a daemon thread polling `DomainEventLog` with `SELECT FOR UPDATE SKIP LOCKED`. For high-throughput deployments, swap the daemon thread for a Celery beat task by subclassing `EventWorker` and overriding `_drain()`.
3. ~~Should permission policies be evaluated at the Python level (decorator) or pushed to PostgreSQL (RLS policy with additional conditions)?~~ **Resolved** — Python-level decorator (`@require_policy`). RLS pushdown deferred: would require Postgres function per policy, high complexity, low added security for the auth model used.
4. ~~Should PDL `extends:` generate a new table (composition) or reuse the parent table with an INNER JOIN (inheritance)?~~ **Resolved** — field-level inheritance (fields merged into same table). True table inheritance (PostgreSQL `INHERITS`) deferred: Alembic support is poor and SQLAlchemy's concrete table inheritance is complex for PDL use cases.
