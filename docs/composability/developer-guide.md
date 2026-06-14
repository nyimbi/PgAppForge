# PgAppForge Composability System — Developer Guide

## Overview

A standard ERP stack built from a single monolith expands cleanly until the first third-party plugin arrives. At that point, the classic problems surface: plugin A needs to add a column to plugin B's model; plugin C wants to inject a widget into plugin D's view; the rules engine needs to trigger a workflow, which should emit an event, which should update an analytics metric. Every crossing point becomes a hard dependency. The result is either a tightly coupled ball of spaghetti or a proliferation of one-off integration tables and cron jobs.

PgAppForge's composability system addresses this at the architectural level with twelve distinct integration dimensions grouped into three phases. Rather than requiring plugins to import each other, each primitive provides a *registry* — a neutral meeting point where publishers and consumers register their intent without holding references to each other. The result is a plugin graph that can be understood by reading individual plugin files rather than tracing global import chains.

The architectural philosophy is **fail-isolated, audit-aware composition**. Every primitive in this system applies exception isolation: a handler that raises does not roll back the caller's transaction. Audit trails are written to separate sessions so a blocked business operation does not prevent the audit record from being committed. Permissions are fail-closed: `require_policy` returns 403 when Flask or Flask-Login is unavailable, rather than silently permitting access. These are not accidental properties — they reflect deliberate choices made in each implementation.

All singletons in this system follow the same pattern: a module-level `_registry: Type | None = None` with a `get_X()` accessor that creates on first call. This means plugins can register at import time (module-level code) or in their `initialize()` methods, and the registry will be populated before any request is served. The same accessor is used at query time, so there is never a need to pass registry references through constructor arguments.

---

## Composition Primitives

### 1. Event Router

**Concept**

`pgappforge/events/router.py` provides a glob-pattern publish/subscribe bus. Plugins subscribe to patterns like `finance.*` or `crm.customer.*`. When any code calls `emit()`, all matching handlers are invoked synchronously in the same process. If a SQLAlchemy session is provided, the event is also persisted to `DomainEventLog` in the same transaction, providing durability: an `EventWorker` can replay unprocessed events after a process restart.

**Quick Start**

```python
# In your plugin's module-level code or initialize():
from pgappforge.events.router import get_router
from pgappforge.events.decorators import on_event

# Module-level handler — registered immediately at import time
@on_event('finance.ar.invoice.*')
def handle_ar_event(event_type: str, payload: dict, tenant_id: str) -> None:
	if event_type.endswith('.approved'):
		post_gl_journal(payload, tenant_id)

# Emit from anywhere in your domain service:
from pgappforge.events.router import emit

def approve_invoice(invoice, session):
	invoice.status = 'APPROVED'
	session.flush()
	emit(
		event_type='finance.ar.invoice.approved',
		payload={'invoice_id': invoice.id, 'amount_cents': invoice.total_amount_cents},
		tenant_id=invoice.tenant_id,
		session=session,           # atomic with business transaction
		aggregate_id=invoice.id,
		aggregate_type='ARInvoice',
	)
```

**Glob Patterns Reference**

Patterns use Python `fnmatch` semantics:

| Pattern | Matches |
|---|---|
| `finance.*` | `finance.invoice`, `finance.payment` (single segment) |
| `finance.**` | `finance.ar.invoice.approved` (any depth) via `*` chaining |
| `crm.customer.created` | Exact match only |
| `*.*.approved` | Any two-segment path ending in `.approved` |
| `crm.customer.*` | All CRM customer events |

Note: `fnmatch` treats `.` as an ordinary character, not a separator. The pattern `finance.*` will match `finance.payment` but not `finance.ar.invoice`. Use `finance.*.*` for two-level nesting.

**Durability via DomainEventLog**

Passing `session=` to `emit()` causes the event to be persisted inside the current transaction. If the business operation commits, the event record commits with it. If it rolls back, the event record rolls back too — preventing phantom events for operations that never completed. An `EventWorker` background thread polls `DomainEventLog` for rows with `processed=False` and dispatches to registered handlers, providing at-least-once delivery across process restarts.

Without `session=`, only in-process synchronous dispatch is performed. This is appropriate for events that are purely informational and whose loss is acceptable.

**`@on_event` Decorator**

```python
from pgappforge.events.decorators import on_event

# Module-level: registered at import time
@on_event('payments.transaction.completed')
def on_payment(event_type: str, payload: dict, tenant_id: str) -> None:
	trigger_loyalty_points(payload['customer_id'], payload['amount_cents'], tenant_id)

# Class method: mark the function with _event_patterns;
# register the bound method in post_initialize()
class LoyaltyPlugin:
	@on_event('payments.transaction.completed')
	def on_payment(self, event_type: str, payload: dict, tenant_id: str) -> None:
		...

	def post_initialize(self):
		from pgappforge.events.router import get_router
		get_router().subscribe('payments.transaction.completed', self.on_payment)
```

**Exception Isolation Guarantee**

`EventRouter.dispatch()` wraps each handler call in a `try/except Exception`. A handler that raises logs the exception at `ERROR` level and continues to the next handler. The emitting transaction is never rolled back by a failing handler.

**Production Notes (Multi-Worker)**

In-process handlers run only in the process that called `emit()`. With gunicorn/uvicorn multi-worker deployments, workers do not share the in-process handler registry. For cross-process delivery, always pass `session=` so events are persisted to `DomainEventLog`. Deploy `EventWorker` as a separate process or as a single designated worker. Do not run `EventWorker` in every worker process — it will cause duplicate handler invocations per event.

---

### 2. Model Mixin Registry

**Concept: The `_inherit` Problem**

Odoo's `_inherit` mechanism allows any module to extend any model. SQLAlchemy has no equivalent. Without an injection mechanism, the Trade Finance plugin must either fork the Finance plugin's `ARInvoice` model (creating a maintenance nightmare) or add a separate `TradeFinanceARInvoiceExtension` join table (penalising every query with an outer join).

`ModelMixinRegistry` solves this by queuing mixin classes before SQLAlchemy compiles its mappers. At application startup, `apply_all_mixins()` walks each mixin and uses SQLAlchemy's column attachment API to graft columns and relationships directly onto the target class's `__table__`. Alembic autogenerate sees the resulting mapped class normally and produces correct migration scripts.

**Quick Start**

```python
# In trade_finance/__init__.py or trade_finance/mixin_registration.py:

import sqlalchemy as sa
from sqlalchemy.orm import declared_attr
from pgappforge.composition import register_mixin

class TradeFinanceMixin:
	letter_of_credit_id = sa.Column(sa.String(36), nullable=True, index=True)
	lc_expiry_date = sa.Column(sa.Date, nullable=True)
	lc_terms = sa.Column(sa.Text, nullable=True)

	@declared_attr
	def letter_of_credit(cls):
		from pgappforge.plugins.fintech.trade_finance.models import LetterOfCredit
		return sa.orm.relationship(
			LetterOfCredit,
			foreign_keys=[cls.letter_of_credit_id],
			lazy='select',
		)

register_mixin(
	'pgappforge.plugins.erp.finance.ar.models.ARInvoice',
	TradeFinanceMixin,
	priority=10,
)
```

```python
# In the Flask app factory, before db.create_all() or Alembic migration:
from pgappforge.composition import apply_all_mixins

def create_app(config=None):
	app = Flask(__name__)
	db.init_app(app)

	# Register all plugins first — their module-level register_mixin() calls fire at import
	import pgappforge.plugins.fintech.trade_finance  # noqa: F401

	# Then apply all queued mixins before mapper compilation
	with app.app_context():
		apply_all_mixins()
		db.create_all()

	return app
```

**Priority Ordering**

Mixins are applied in ascending priority order (lower number = applied first). Use priority to control which mixin wins when two plugins add a column with the same name (the `_apply_one` implementation skips columns that already exist on `__table__`). Default priority is 50.

**Lifecycle: When to Call `apply_all_mixins()`**

Call it exactly once, inside the app context, after all plugin modules have been imported but before any of the following:
- `db.create_all()`
- `alembic upgrade head` (via the CLI entry point)
- The first SQLAlchemy query

Calling it a second time is a no-op with a warning log. Calling `register_mixin()` after `apply_all_mixins()` has run raises `RuntimeError`.

**SQLAlchemy Constraints**

- Mixin columns must be `sa.Column` instances (not `mapped_column()` from SQLAlchemy 2.x ORM). The implementation uses `__table__.append_column()` which is the lower-level table metadata API, not the declarative ORM layer.
- Relationships must use `@declared_attr` so they are evaluated lazily against the target class rather than at class definition time.
- Plain `Column` objects are shallow-copied before attachment so the same `Column` instance is not shared across multiple tables.

**Example: Adding LC Fields to ARInvoice from Trade Finance Plugin**

```python
# pgappforge/plugins/fintech/trade_finance/__init__.py

import sqlalchemy as sa
from sqlalchemy.orm import declared_attr
from pgappforge.composition import register_mixin

class _ARInvoiceTradeFinanceMixin:
	"""Adds LC fields to ARInvoice for documentary credit transactions."""

	letter_of_credit_id   = sa.Column(sa.String(36), nullable=True, index=True)
	lc_expiry_date        = sa.Column(sa.Date, nullable=True)
	lc_presentation_docs  = sa.Column(sa.JSONB, nullable=True)

	@declared_attr
	def letter_of_credit(cls):
		from pgappforge.plugins.fintech.trade_finance.models import LetterOfCredit
		return sa.orm.relationship(
			LetterOfCredit,
			primaryjoin=f"{cls.__name__}.letter_of_credit_id == LetterOfCredit.id",
			foreign_keys=[cls.letter_of_credit_id],
		)

register_mixin(
	'pgappforge.plugins.erp.finance.ar.models.ARInvoice',
	_ARInvoiceTradeFinanceMixin,
	priority=10,
)
```

After `apply_all_mixins()`, `ARInvoice.__table__.columns` will include `letter_of_credit_id`, `lc_expiry_date`, and `lc_presentation_docs`. Alembic's autogenerate will emit `op.add_column()` calls for these in the next migration.

---

### 3. Sub-workflow Composition

**Concept**

`PgAppForgeWorkflowEngine` supports calling a named workflow from within another workflow's YAML definition using the `call_workflow` step type. The parent workflow suspends at the `call_workflow` step, launches the child as a fully independent instance (with its own instance ID, task records, and DB rows), maps declared output fields from the child back into the parent's context, then advances. The parent instance stores the child's ID under `_sub_instance_{step_id}` in its data dict for audit correlation.

**YAML Syntax**

```yaml
name: sacco_loan_disbursement
steps:
  - id: verify_member
    type: UserTask
    label: "Verify member identity"
    assignee_role: "Loan Officer"

  - id: run_kyc
    type: call_workflow
    workflow: kyc_verification          # must be loaded in same engine instance
    inputs:
      member_id: $member_id             # $field resolves from parent instance.data
      national_id: "{{national_id}}"    # {{field}} template interpolation
    outputs:
      kyc_passed: kyc_result.passed     # dot-path into child's data dict
      kyc_risk_score: kyc_result.score

  - id: loan_committee_approval
    type: UserTask
    label: "Loan committee review"
    assignee_role: "Loan Committee"
    condition: "kyc_passed == True"     # condition evaluated against parent data

  - id: disburse
    type: ServiceTask
    service: "mobile_money.disburse"
    input_map:
      phone: application.phone_number
      amount: approved_amount
```

**Input/Output Mapping**

The `inputs` block maps values from the parent's data dict into the child's initial data. Two substitution syntaxes are supported:

- `$field_name` — direct lookup in `instance.data[field_name]`
- `{{field_name}}` — string template substitution (all `{{...}}` occurrences replaced)
- Literal values — passed as-is

The `outputs` block maps paths from the completed child's data dict back into the parent's data. Path syntax is `step_id.key` — for example, `kyc_result.passed` resolves `instance.data['kyc_result']['passed']` on the child instance.

**Parent-Child Correlation via `parent_instance_id`**

When `engine.start()` is called by a `call_workflow` step, it passes `parent_instance_id=instance.id`. The child stores this in its data dict under `_parent_instance_id`. This allows audit queries to reconstruct the full composition tree:

```sql
SELECT id, workflow_name, data->>'_parent_instance_id' AS parent_id
FROM pgaf_workflow_instance
WHERE data->>'_parent_instance_id' = :parent_id
ORDER BY created_at;
```

---

### 4. Rule → Event Bridge

**Concept**

The rules engine's YAML DSL supports an `emit_event` action type. When a rule fires, instead of (or in addition to) blocking or mutating the record, it can publish a named event to the `EventRouter`. This decouples the rules engine from downstream logic: the rule author declares intent ("when invoice is approved, fire a GL posting event"), and event handlers in other plugins react without needing a reference in the rule YAML.

**YAML Action Syntax**

```yaml
# In a RuleSet YAML definition:
- name: invoice_approved_gl_post
  trigger_event: on_update
  conditions:
    - field: status
      op: "="
      value: APPROVED
    - field: status
      op: "!="
      value: $previous_status
      logic: AND
  actions:
    - type: emit_event
      event: finance.gl.journal_entry.required
      payload:
        invoice_id: $id
        amount_cents: $total_amount_cents
        tenant_id: $tenant_id
        direction: credit
```

The `event` field is the event type string passed to `EventRouter.dispatch()`. The `payload` dict supports the same `$field` and `{{template}}` interpolation as conditions — values are resolved from the model's column dict at evaluation time.

**Payload Template Syntax**

Both `$field` and `{{field}}` resolve against the record's column dictionary built by `_record_to_dict()`:

```yaml
payload:
  reference: "INV-{{id}}-{{tenant_id}}"    # string with multiple substitutions
  amount: $total_amount_cents               # direct field lookup
  note: "Approved by {{approved_by}}"
```

**Dry-Run Simulation**

`RulesEngine.evaluate_dry()` returns a summary dict that includes `would_emit_events: list[dict]` — the list of `emit_event` action dicts that would fire if the rule conditions are met, without actually calling `emit()`. Use this in tests to assert rule behaviour without wiring up the full event bus:

```python
from pgappforge.plugins.rules.engine import get_rules_engine

result = get_rules_engine().evaluate_dry(
	model_name='ARInvoice',
	event='on_update',
	record=invoice,
	session=session,
)

assert result['would_emit_events'] == [{
	'type': 'emit_event',
	'event': 'finance.gl.journal_entry.required',
	'payload': {'invoice_id': '$id', 'amount_cents': '$total_amount_cents', ...},
}]
```

---

### 5. Permission Algebra

**Concept**

Flask-AppBuilder's RBAC model is flat: a user has roles, roles have permissions. There is no native way to express compound conditions like "must be a loan officer AND (must be a manager OR must hold the credit.override permission)". The `security/policies.py` module introduces Policy objects — pure predicates with algebraic combinators — that compose into arbitrarily complex access policies without custom imperative code.

**Primitives**

| Class | Signature | Description |
|---|---|---|
| `HasRole` | `HasRole('loan_officer')` | True if user has the named FAB role |
| `HasPermission` | `HasPermission('credit.approve')` | True if FAB security manager grants access to the named permission |
| `IsOwner` | `IsOwner('owner_id')` | True if `user.id == context['owner_id']` |
| `IsAuthenticated` | `IsAuthenticated()` | True if user is not None and `is_authenticated` |
| `IsAdmin` | `IsAdmin()` | True if `user.is_admin` or user has `Admin` role |
| `Lambda` | `Lambda(lambda u, ctx: ...)` | Wrap any callable as a policy |

Pre-built policy constants: `ALLOW_ALL`, `DENY_ALL`, `AUTH_ONLY`, `ADMIN_ONLY`.

**Combinators**

```python
from pgappforge.security.policies import AllOf, AnyOf, Not, HasRole, HasPermission

# Operator overloading
full_access = HasRole('Admin') | HasRole('SuperUser')
restricted  = HasRole('Auditor') & ~HasRole('Suspended')

# Equivalent long form
full_access = AnyOf(HasRole('Admin'), HasRole('SuperUser'))
restricted  = AllOf(HasRole('Auditor'), Not(HasRole('Suspended')))
```

`AllOf` short-circuits on the first False result. `AnyOf` short-circuits on the first True result. `Not` evaluates its child and inverts. No side effects: policy evaluation is a pure predicate over `(user, context)`.

**`@require_policy` Decorator**

```python
from pgappforge.security.policies import require_policy, AllOf, AnyOf, HasRole, HasPermission, IsOwner

loan_approval_policy = AllOf(
	HasRole('loan_officer'),
	AnyOf(
		HasRole('manager'),
		HasPermission('credit.credit_committee_override'),
	),
)

class LoanView(ModelView):

	@expose('/approve/<int:pk>', methods=['POST'])
	@require_policy(
		loan_approval_policy,
		context_fn=lambda self: {'loan_id': request.view_args.get('pk')},
	)
	def approve(self, pk):
		...
```

If the policy check fails, `require_policy` calls `flask.abort(403)`. If Flask or Flask-Login is not importable, it raises `RuntimeError` (fail-closed). The `context_fn` argument is called with the view instance as the first positional argument; its return value becomes the `context` dict passed to `policy.check()`.

**Examples**

```python
# SACCO loan approval: must be loan officer AND (manager OR committee override)
approve_loan = AllOf(
	HasRole('loan_officer'),
	AnyOf(HasRole('manager'), HasPermission('credit.credit_committee_override')),
)

# Committee quorum: at least one committee member — the three-member list is OR'd
committee_quorum = AnyOf(
	HasRole('credit_committee_chair'),
	HasRole('credit_committee_member'),
	HasRole('risk_officer'),
)

# Owner-only access: the record owner OR an admin
owner_or_admin = IsOwner('created_by_id') | IsAdmin()

# Direct evaluation outside a request context (e.g. in a workflow step):
if approve_loan.check(current_user, context={'loan_id': loan.id, 'tenant_id': tid}):
	...
```

---

### 6. PDL Schema Extension

**Concept**

The Plugin Definition Language (PDL) is PgAppForge's YAML-based code generator. A PDL YAML file declares entities with fields; the generator emits SQLAlchemy models, Alembic migrations, FAB views, REST API endpoints, and test scaffolding. The `extends` field on a `PDLEntity` allows an entity to inherit the fields of an existing SQLAlchemy model without redeclaring them, then add or override selected fields. The code generator always calls `all_fields()`, which merges parent fields with local fields (local fields shadow parent fields with the same name).

**YAML Syntax**

```yaml
version: "1.0"
namespace: pgappforge.plugins.fintech.trade_finance

entities:
  - name: LCBackedARInvoice
    table: fin_lc_backed_ar_invoice
    description: "AR Invoice variant backed by a Letter of Credit"
    extends: pgappforge.plugins.erp.finance.ar.models.ARInvoice
    fields:
      # These LOCAL fields shadow or add to the parent
      - name: letter_of_credit_id
        type: uuid
        fk: fin_letter_of_credit.id
        nullable: false
        indexed: true
        label: "Letter of Credit"
      - name: lc_presentation_status
        type: enum
        choices: [PENDING, PRESENTED, ACCEPTED, REJECTED]
        default: PENDING
    generate: [model, migration, view, api]
```

**Field Resolution Order**

`PDLEntity.all_fields()` calls `resolve_parent_fields()` to introspect `parent.__table__.columns` (excluding `id`, `tenant_id`, `created_at`, `updated_at` which every entity gets from standard scaffolding), then appends local fields. If a local field has the same `name` as a parent field, the parent field is dropped. This mirrors Python's MRO: local definitions always win.

```python
from pgappforge.pdl.schema import PDLEntity, PDLField

entity = PDLEntity(
	name='LCBackedARInvoice',
	table='fin_lc_backed_ar_invoice',
	extends='pgappforge.plugins.erp.finance.ar.models.ARInvoice',
	fields=[PDLField(name='letter_of_credit_id', type='uuid', nullable=False)],
)

# Returns parent columns + letter_of_credit_id (overriding parent if same name)
all_fields = entity.all_fields()
```

**Code Generation**

The code generator calls `entity.all_fields()` rather than `entity.fields` for every artifact — model, migration, view column list, API schema, and test fixtures. This means the generated model will have all inherited columns without redeclaring them in the YAML. The generated Alembic migration will only contain `op.add_column()` calls for fields not already in the parent table.

If `extends` is a plain name (no dots), `resolve_parent_fields()` returns `[]` and intra-schema resolution is the responsibility of the caller. Use dotted paths to existing mapped SQLAlchemy models for reliable introspection.

---

### 7. Semantic Metric Registry

**Concept: Aggregation Types Matter**

Naive analytics implementations aggregate everything with `SUM`. This produces incorrect results for non-additive measures: summing average invoice amounts across regions gives a meaningless number; the correct query must re-average from raw rows. The `MetricRegistry` enforces aggregation semantics at registration time by requiring an explicit `agg` type on every metric declaration.

**Additive vs Non-Additive**

| `agg` type | Is additive? | Safe to sum across groups? | Notes |
|---|---|---|---|
| `sum` | Yes | Yes | Revenue, payments, payroll cost |
| `count` | Yes | Yes | Invoice count, headcount |
| `avg` | No | No | Average DSO, average loan size |
| `last_value` | Semi | Within partition only | Balance, inventory level |
| `distinct` | No | No | Unique customers, unique SKUs |

`Metric.is_additive()` returns `True` only for `sum` and `count`. `MetricRegistry.query()` logs an `INFO` warning when a non-additive metric is queried with a `group_by` argument.

**Registration**

```python
from pgappforge.analytics.metrics import register_metric, Metric

# Called in plugin __init__.py or in a plugin setup() function:
register_metric(Metric(
	name='finance.ar.revenue',
	label='AR Revenue',
	plugin='finance.ar',
	model_path='pgappforge.plugins.erp.finance.ar.models.ARInvoice',
	field='total_amount_cents',
	agg='sum',
	unit='cents',
	filters={'status': 'PAID'},
	description='Sum of paid AR invoice amounts in cents',
))

register_metric(Metric(
	name='hcm.headcount',
	label='Active Headcount',
	plugin='hcm.personnel',
	model_path='pgappforge.plugins.erp.hcm.personnel.models.Employee',
	field='id',
	agg='count',
	filters={'employment_status': 'ACTIVE'},
))

register_metric(Metric(
	name='finance.ar.avg_invoice_size',
	label='Average Invoice Size',
	plugin='finance.ar',
	model_path='pgappforge.plugins.erp.finance.ar.models.ARInvoice',
	field='total_amount_cents',
	agg='avg',
	unit='cents',
))
```

**Querying Across Plugins**

```python
from pgappforge.analytics.metrics import query_metrics

# Query multiple metrics together — results keyed by metric name
results = query_metrics(
	metrics=['finance.ar.revenue', 'hcm.headcount', 'crm.deals_won'],
	group_by=['tenant_id'],
	filters={'fiscal_year': '2026'},
	tenant_id='tenant-abc',
	session=session,
)
# results == {
#     'finance.ar.revenue':  [{'tenant_id': 'tenant-abc', 'finance.ar.revenue': 4820000}],
#     'hcm.headcount':       [{'tenant_id': 'tenant-abc', 'hcm.headcount': 142}],
#     'crm.deals_won':       [{'tenant_id': 'tenant-abc', 'crm.deals_won': 37}],
# }
```

Each metric executes its own SQL query. The caller joins results on common `group_by` keys. This avoids generating a single omnibus query across unrelated tables and makes plugin metrics independently cacheable.

**Warning System for Non-Additive Cross-Group Queries**

When `is_additive()` is `False` and `group_by` is non-empty, `MetricRegistry.query()` logs:

```
INFO MetricRegistry: metric 'finance.ar.avg_invoice_size' (agg=avg) is non-additive — do not sum values across groups
```

This is a warning, not an error — the query still executes. Callers are responsible for using the returned values correctly (display as-is, not summed).

---

### 8. View Slot Injection

**Concept**

FAB views are Jinja2 templates rendered server-side. Plugin B cannot inject a loyalty points widget into Plugin A's customer detail view without modifying Plugin A's template file. The `SlotRegistry` solves this with named injection points: Plugin A's template includes `{{ render_slot('customer.detail.sidebar', {'customer_id': customer.id}) }}`; Plugin B registers a provider for that slot name. When the template renders, all registered providers for that slot are called in priority order and their HTML output is concatenated.

**`@slot_provider` Decorator**

```python
from pgappforge.ui.slots import slot_provider

# Called in plugin __init__.py — registered at import time:

@slot_provider('customer.detail.sidebar', priority=30)
def loyalty_balance_widget(context: dict) -> str:
	customer_id = context.get('customer_id', '')
	if not customer_id:
		return ''
	points = get_loyalty_points(customer_id)
	return f'<div class="card loyalty-widget"><div class="card-body">Loyalty Points: <strong>{points}</strong></div></div>'

@slot_provider('customer.detail.sidebar', priority=50)
def credit_score_widget(context: dict) -> str:
	customer_id = context.get('customer_id', '')
	score = get_credit_score(customer_id)
	return f'<div class="card credit-widget"><div class="card-body">Credit Score: <strong>{score}</strong></div></div>'
```

**Priority-Based Rendering**

Lower priority value = rendered first (appears higher on the page). Default priority is 50. Providers for the same slot are sorted by priority at registration time. When two providers have equal priority, they render in registration order.

**Exception Isolation**

`SlotRegistry.render()` wraps each provider call in `try/except Exception`. A provider that raises logs the exception at `ERROR` level and continues to the next provider. The page still renders; only the failing widget's output is absent.

**Jinja2 Integration**

```python
# In the Flask app factory:
from pgappforge.ui.slots import register_slot_extension

def create_app(config=None):
	app = Flask(__name__)
	# ...
	register_slot_extension(app.jinja_env)
	return app
```

This adds `render_slot` as a global function in the Jinja2 environment. Templates call it as:

```jinja2
{# In customer_detail.html: #}
<div class="row">
    <div class="col-md-8">
        {# main content #}
    </div>
    <div class="col-md-4">
        {{ render_slot('customer.detail.sidebar', {'customer_id': customer.id}) }}
    </div>
</div>
```

The return value is a `markupsafe.Markup` instance (already escaped), so it renders without double-escaping.

**Well-Known Slot Names Reference**

| Constant | Slot Name | Location |
|---|---|---|
| `SLOT_CUSTOMER_DETAIL_SIDEBAR` | `customer.detail.sidebar` | Sidebar on customer detail view |
| `SLOT_CUSTOMER_LIST_ACTIONS` | `customer.list.actions` | Action buttons in customer list |
| `SLOT_INVOICE_DETAIL_FOOTER` | `invoice.detail.footer` | Footer area on invoice detail |
| `SLOT_DASHBOARD_KPI_ROW` | `dashboard.kpi.row` | Additional KPI cards on home dashboard |
| `SLOT_NAV_TOP_RIGHT` | `nav.top.right` | Top-right navigation items |
| *(convention)* | `{domain}.{model}.detail.tab` | Additional tab in any detail view |

Use the module-level constants from `pgappforge.ui.slots` rather than raw strings to get typo safety.

---

### 9. AI Composable Pipeline

**Concept: The Runnable Protocol**

`pgappforge/ai/pipeline.py` implements an LCEL-inspired (LangChain Expression Language) `Runnable` protocol. Every pipeline step implements a single method: `invoke(input, **kwargs) -> output`. Steps compose sequentially via `.pipe(other)` or the `|` operator. The output of step N is the input to step N+1. Steps compose in parallel via `.parallel(**branches)`, which fans a single input out to multiple named branches and returns a dict of results.

The design is deliberately untyped at the protocol boundary — `input: Any, output: Any`. Individual step classes document their expected types in docstrings, but nothing enforces them at runtime. This keeps pipelines flexible: a `FormatStep` that converts a dict to a string can be slotted between a `SQLStep` and an `LLMStep` without needing adapters.

**Sequential Composition: `pipe()` and `|`**

```python
from pgappforge.ai.pipeline import LLMStep, SQLStep, FormatStep, Composable

# Equivalent forms:
pipeline = SQLStep(query="SELECT * FROM fin_ar_invoice WHERE tenant_id = :tenant_id LIMIT 10")
pipeline = pipeline | FormatStep(template="Invoices: {value}")
pipeline = pipeline | LLMStep(system="You are a finance analyst. Summarise the invoice data.")

# Or inline:
pipeline = (
	SQLStep(query="SELECT id, status, total_amount_cents FROM fin_ar_invoice WHERE tenant_id = :tenant_id LIMIT 10")
	| FormatStep(template="{value}")
	| LLMStep(
		system="Summarise these invoices in one sentence, including total amount.",
		model='gpt-4o-mini',
		max_tokens=256,
	)
)

result = pipeline.invoke({'tenant_id': 'tenant-abc'}, session=session)
# result is a string from the LLM
```

**Parallel Composition: `parallel()`**

```python
from pgappforge.ai.pipeline import SQLStep, LLMStep, Lambda

# Fan out to two independent branches, collect results:
pipeline = (
	SQLStep(query="SELECT * FROM fin_ar_invoice WHERE tenant_id = :tenant_id LIMIT 20")
	.parallel(
		summary=LLMStep(system="Summarise invoice trends in 2 sentences."),
		risk_flags=LLMStep(system="Identify any overdue or high-value invoices. List them."),
	)
)

result = pipeline.invoke({'tenant_id': 'tenant-abc'}, session=session)
# result == {'summary': '...', 'risk_flags': '...'}
```

**Built-in Steps**

| Step | Input | Output | Notes |
|---|---|---|---|
| `LLMStep(system, model, max_tokens)` | str or any (converted to str) | str | Requires `litellm`; reads `LITELLM_BASE_URL` and `LITELLM_API_KEY` env |
| `SQLStep(query)` | dict of named params | `list[dict]` | Requires `session=` kwarg |
| `RuleStep(tenant_id, event)` | SQLAlchemy model instance | same instance (possibly mutated) | Raises `RulesValidationError` on block |
| `WorkflowStep(workflow_name, tenant_id)` | dict | `WorkflowInstance` | Uses a fresh engine instance |
| `FormatStep(template)` | dict | str | Python `str.format(**data)` |
| `Lambda(fn)` | any | any | Wrap arbitrary callable |
| `Passthrough()` | any | same | Identity; useful in parallel branches |

**Building a Full NL→SQL→Explain Pipeline**

```python
from pgappforge.ai.pipeline import LLMStep, SQLStep, FormatStep, Lambda
import sqlalchemy as sa

# Step 1: translate natural language question to SQL
nl_to_sql = LLMStep(
	system=(
		"You are a SQL expert for a PostgreSQL ERP schema. "
		"Given a natural language question, return ONLY valid SQL. No explanation."
	),
	model='gpt-4o-mini',
)

# Step 2: execute the generated SQL (the input is the SQL string from step 1)
def run_generated_sql(sql_str: str, session=None, **kwargs) -> list[dict]:
	try:
		result = session.execute(sa.text(sql_str))
		keys = list(result.keys())
		return [dict(zip(keys, row)) for row in result.fetchall()]
	except Exception as exc:
		return [{'error': str(exc)}]

execute_sql = Lambda(run_generated_sql, name='execute_generated_sql')

# Step 3: explain the results
explain = LLMStep(
	system="You are a business analyst. Explain the following query results in plain English.",
	model='gpt-4o-mini',
	max_tokens=512,
)

nl_to_results_pipeline = nl_to_sql | execute_sql | explain

answer = nl_to_results_pipeline.invoke(
	"How many overdue invoices does each tenant have?",
	session=session,
)
```

---

### 10. Cross-Tenant Aggregation

**Concept and Safety Model**

PgAppForge uses PostgreSQL Row-Level Security (RLS) policies keyed on the `app.tenant_id` session variable. Every query in a normal request is automatically scoped to the current tenant. Platform admins (SaaS operators) need cross-tenant visibility for billing, capacity planning, and fraud detection — but must not bypass RLS ad-hoc in application code.

`SystemSession` is a context manager that sets `app.tenant_id` to the `SYSTEM` sentinel that RLS policies already recognise as a bypass signal, writes an audit record before activating the bypass, and restores the original context on exit. All cross-tenant queries must be wrapped in `SystemSession`. The `CrossTenantAggregator` methods only make sense inside this context.

**`SystemSession` Context Manager**

```python
from pgappforge.multitenancy.aggregation import SystemSession, CrossTenantAggregator

# Only valid with a platform admin user — enforce this in calling code:
with SystemSession(
	session,
	caller_user_id=current_user.id,
	reason='Monthly billing run — aggregate transaction counts',
) as sys_session:
	agg = CrossTenantAggregator()
	summary = agg.get_platform_summary(sys_session)
	txn_counts = agg.compute_metric_across_tenants(
		table='fin_mobile_transaction',
		field='id',
		agg='count',
		session=sys_session,
	)
# After the with block, app.tenant_id is reset to '' (empty)
```

`SystemSession` writes a row to `platform_cross_tenant_audit` before yielding. This table records `caller_user_id`, `reason`, and `accessed_at`. If the table does not exist (non-production environments), the write is silently skipped.

**SQL Injection Safety**

`compute_metric_across_tenants()` uses `sa.text()` with f-string interpolation for table and field names. Before interpolation, both `table` and `field` are validated with an alphanumeric-plus-underscore allowlist:

```python
if not all(c.isalnum() or c == '_' for c in table):
	raise ValueError(f"Unsafe table name: {table!r}")
```

This prevents SQL injection via table or field names. The `agg` parameter is checked against a hardcoded allowlist: `{'count', 'sum', 'avg', 'max', 'min'}`. Never pass user-supplied strings directly as `table`, `field`, or `agg` without pre-validation against your own schema allowlist.

**`CrossTenantAggregator` API**

```python
agg = CrossTenantAggregator()

# List all active/trial tenants
tenants = agg.list_active_tenants(session)   # ['tenant-001', 'tenant-002', ...]

# Aggregate a field by tenant
invoice_counts = agg.compute_metric_across_tenants(
	table='fin_ar_invoice',
	field='id',
	agg='count',
	session=session,
)  # {'tenant-001': 1420, 'tenant-002': 387, ...}

# Get a full platform KPI summary
summary = agg.get_platform_summary(session)
# {
#     'total_tenants': 47,
#     'tenants_by_status': {'ACTIVE': 41, 'TRIAL': 5, 'SUSPENDED': 1},
#     'total_ar_invoices': 182401,
#     'total_mobile_txns': 94821,
# }
```

**Audit Trail**

Every entry into `SystemSession` writes to `platform_cross_tenant_audit`. Query this table to audit all cross-tenant access:

```sql
SELECT caller_user_id, reason, accessed_at
FROM platform_cross_tenant_audit
ORDER BY accessed_at DESC
LIMIT 100;
```

---

### 11. GraphQL Federation

**Concept: Apollo Federation v2**

PgAppForge plugins expose domain entities as independently deployable GraphQL subgraphs using Apollo Federation v2. The `FederationRegistry` is the central catalogue: each plugin registers its domain types with their `@key` fields. The registry generates Federation v2 SDL that can be published to Apollo Studio, Cosmo, or Hive for supergraph composition.

Each subgraph is an independently deployable FastAPI or Flask service. The supergraph gateway (Apollo Router or Cosmo) routes field queries to the owning subgraph and stitches results together. Plugins reference each other's types by name without direct code imports.

**`FederationRegistry`**

```python
from pgappforge.graphql.federation import get_federation_registry

registry = get_federation_registry()

# Inspect what has been registered:
for entry in registry.list_types():
	print(f"{entry.name} (plugin={entry.plugin}, keys={entry.key_fields})")

# Generate the SDL:
sdl = registry.build_schema_sdl()
print(sdl)
```

**`@federated_type` Decorator**

The decorator registers a class with the global `FederationRegistry` and annotates it with `_federation_key` and `_federation_plugin` attributes. Use it in plugin `models_gql.py` files or anywhere the GraphQL schema is defined:

```python
from pgappforge.graphql.federation import federated_type

@federated_type(key='id', plugin='finance.ar')
class ARInvoice:
	"""Accounts Receivable invoice entity."""
	id: str
	tenant_id: str
	total_amount_cents: int
	status: str
	customer_id: str

@federated_type(key='id', plugin='crm')
class Customer:
	"""CRM customer entity."""
	id: str
	name: str
	email: str
```

**SDL Generation**

`build_schema_sdl()` generates valid Apollo Federation v2 SDL:

```graphql
extend schema @link(url: "https://specs.apollo.dev/federation/v2.0", import: ["@key", "@shareable", "@external"])

"""Accounts Receivable invoice entity."""
type ARInvoice @key(fields: "id") {
    id: String!
    tenant_id: String!
    total_amount_cents: Int!
    status: String!
    customer_id: String!
}

"""CRM customer entity."""
type Customer @key(fields: "id") {
    id: String!
    name: String!
    email: String!
}
```

**Strawberry Integration**

`build_strawberry_schema()` wraps all registered types with `strawberry.federation.type()` and returns a `strawberry.federation.schema.Schema` with `enable_federation_2=True`. Mount this in a FastAPI app:

```python
from pgappforge.graphql.federation import get_federation_registry
import strawberry
from strawberry.fastapi import GraphQLRouter
from fastapi import FastAPI

# Import plugins so their @federated_type decorators fire:
import pgappforge.plugins.erp.finance.ar.models_gql  # noqa: F401
import pgappforge.plugins.erp.crm.models_gql          # noqa: F401

schema = get_federation_registry().build_strawberry_schema()
app = FastAPI()
app.include_router(GraphQLRouter(schema), prefix='/graphql')
```

---

## Composition Patterns Cookbook

### 1. Payment Completed → Post GL Journal + Notify Customer

```python
# pgappforge/plugins/fintech/payments/__init__.py

from pgappforge.events.decorators import on_event
from pgappforge.events.router import emit

@on_event('payments.transaction.completed')
def on_payment_completed(event_type: str, payload: dict, tenant_id: str) -> None:
	# Fire GL posting event — GL plugin handles its own logic
	emit(
		event_type='finance.gl.journal_entry.required',
		payload={
			'amount_cents': payload['amount_cents'],
			'reference': payload['transaction_id'],
			'direction': 'debit',
			'account_code': '1100',  # Cash
		},
		tenant_id=tenant_id,
	)
	# Fire notification event — notifications plugin handles its own logic
	emit(
		event_type='notifications.email.required',
		payload={
			'template': 'payment_receipt',
			'recipient_id': payload['customer_id'],
			'amount_cents': payload['amount_cents'],
		},
		tenant_id=tenant_id,
	)
```

Neither the GL plugin nor the notifications plugin import the payments plugin. The payments plugin does not import them. The two downstream plugins register their handlers against `finance.gl.*` and `notifications.email.*` patterns independently.

### 2. Trade Finance: Add LC Fields to ARInvoice Without Modifying Finance Plugin

See [Model Mixin Registry — Quick Start](#2-model-mixin-registry) above. Summary: define a mixin class with the columns and relationships, call `register_mixin()` at module import time, call `apply_all_mixins()` in the app factory before `db.create_all()`.

```python
# trade_finance/__init__.py
register_mixin(
	'pgappforge.plugins.erp.finance.ar.models.ARInvoice',
	TradeFinanceMixin,
	priority=10,
)
```

### 3. SACCO Loan Approval with Quorum Permission

```python
from pgappforge.security.policies import AllOf, AnyOf, HasRole, HasPermission, require_policy

# Quorum: chair OR any two committee members
# Represented as: chair OR (member AND risk_officer) — approximation of n-of-m
loan_approval_policy = AllOf(
	HasRole('loan_officer'),
	AnyOf(
		HasRole('credit_committee_chair'),
		AllOf(HasRole('credit_committee_member'), HasRole('risk_officer')),
		HasPermission('credit.emergency_override'),
	),
)

class SaccoLoanView(ModelView):
	@expose('/approve/<int:pk>', methods=['POST'])
	@require_policy(loan_approval_policy)
	def approve(self, pk):
		loan = self.datamodel.get(pk)
		loan.status = 'APPROVED'
		self.datamodel.edit(loan)
```

### 4. Cross-Domain Dashboard: Revenue + Headcount Cost + Pipeline Value

```python
from pgappforge.analytics.metrics import register_metric, query_metrics, Metric

# Each plugin registers its metrics at startup:
# finance.ar plugin:
register_metric(Metric(name='finance.ar.revenue', ..., agg='sum'))
# hcm plugin:
register_metric(Metric(name='hcm.payroll_cost', ..., agg='sum'))
# crm plugin:
register_metric(Metric(name='crm.pipeline_value', ..., agg='sum'))

# Dashboard view queries all three:
def get_executive_dashboard(tenant_id: str, session) -> dict:
	results = query_metrics(
		metrics=['finance.ar.revenue', 'hcm.payroll_cost', 'crm.pipeline_value'],
		tenant_id=tenant_id,
		session=session,
	)
	return {
		'revenue_cents':    results['finance.ar.revenue'][0].get('finance.ar.revenue', 0),
		'payroll_cost_cents': results['hcm.payroll_cost'][0].get('hcm.payroll_cost', 0),
		'pipeline_value_cents': results['crm.pipeline_value'][0].get('crm.pipeline_value', 0),
	}
```

### 5. AI Copilot Sidebar in Any View

```python
from pgappforge.ui.slots import slot_provider

@slot_provider('invoice.detail.footer', priority=90)
def ai_copilot_widget(context: dict) -> str:
	invoice_id = context.get('invoice_id', '')
	return f'''
<div class="card ai-copilot mt-3" id="ai-copilot-{invoice_id}">
    <div class="card-header">AI Insights</div>
    <div class="card-body">
        <div id="ai-summary-{invoice_id}" hx-get="/api/ai/invoice-summary/{invoice_id}"
             hx-trigger="load" hx-swap="innerHTML">
            Loading...
        </div>
    </div>
</div>'''
```

The view template requires no changes beyond including `{{ render_slot('invoice.detail.footer', {'invoice_id': invoice.id}) }}`.

### 6. NL → SQL → Summarise Pipeline

See [AI Composable Pipeline — Building a Full NL→SQL→Explain Pipeline](#9-ai-composable-pipeline) above.

### 7. Loyalty Points Earned Event → Mobile Money Cashback

```python
from pgappforge.events.decorators import on_event
from pgappforge.plugins.fintech.mobile_money.service import initiate_cashback

@on_event('crm.loyalty.points_redeemed')
def trigger_mobile_money_cashback(event_type: str, payload: dict, tenant_id: str) -> None:
	customer_id   = payload.get('customer_id')
	points        = payload.get('points_redeemed', 0)
	phone_number  = payload.get('phone_number')

	# Convert points to cash at configured rate
	cashback_cents = points * 10  # 10 cents per point

	if cashback_cents > 0 and phone_number:
		initiate_cashback(
			phone_number=phone_number,
			amount_cents=cashback_cents,
			reference=f"LOYALTY-{customer_id}",
			tenant_id=tenant_id,
		)
```

The CRM loyalty plugin emits `crm.loyalty.points_redeemed` without any knowledge that a mobile money integration exists. The mobile money plugin registers this handler independently. Neither plugin imports the other.

---

## Testing Your Compositions

Each primitive has a natural testing boundary. The pattern is consistent: instantiate the primitive directly (not via the singleton), exercise it against real objects, assert on outcomes.

**EventRouter**

```python
def test_event_handler_invoked():
	from pgappforge.events.router import EventRouter
	router = EventRouter()
	calls = []
	router.subscribe('finance.*', lambda event_type, payload, tenant_id: calls.append(event_type))
	router.dispatch('finance.invoice.approved', {'id': '123'}, tenant_id='t1')
	assert calls == ['finance.invoice.approved']

def test_failing_handler_does_not_block_next():
	from pgappforge.events.router import EventRouter
	router = EventRouter()
	calls = []
	router.subscribe('test.*', lambda **kw: (_ for _ in ()).throw(RuntimeError('boom')))
	router.subscribe('test.*', lambda event_type, **kw: calls.append(event_type))
	router.dispatch('test.event', {}, tenant_id='t1')
	assert calls == ['test.event']  # second handler still ran
```

**ModelMixinRegistry**

```python
def test_mixin_adds_column(app_context, base_model):
	import sqlalchemy as sa
	from pgappforge.composition.mixins import ModelMixinRegistry

	class MyMixin:
		extra_field = sa.Column(sa.String(50), nullable=True)

	registry = ModelMixinRegistry()
	registry.register('tests.fixtures.models.SimpleModel', MyMixin)
	count = registry.apply_all()

	from tests.fixtures.models import SimpleModel
	assert 'extra_field' in {c.name for c in SimpleModel.__table__.columns}
	assert count == 1
```

**RulesEngine (dry run)**

```python
async def test_emit_event_action_dry_run(session, invoice):
	from pgappforge.plugins.rules.engine import RulesEngine
	engine = RulesEngine(session_factory=lambda: session)
	# Load a rule with emit_event action for model ARInvoice...
	result = engine.evaluate_dry('ARInvoice', 'on_update', invoice, session=session)
	assert any(a['event'] == 'finance.gl.journal_entry.required'
	           for a in result['would_emit_events'])
```

**Permission Algebra**

```python
def test_allof_short_circuits():
	from pgappforge.security.policies import AllOf, HasRole
	from unittest.mock import MagicMock

	user = MagicMock()
	user.roles = [MagicMock(name='loan_officer')]

	policy = AllOf(HasRole('loan_officer'), HasRole('manager'))
	assert policy.check(user) is False

def test_anyof_passes_on_first_match():
	from pgappforge.security.policies import AnyOf, HasRole
	from unittest.mock import MagicMock

	user = MagicMock()
	user.roles = [MagicMock(name='manager')]
	policy = AnyOf(HasRole('loan_officer'), HasRole('manager'))
	assert policy.check(user) is True
```

**MetricRegistry**

```python
def test_metric_query_returns_aggregated_rows(session):
	from pgappforge.analytics.metrics import MetricRegistry, Metric
	registry = MetricRegistry()
	registry.register(Metric(
		name='test.revenue',
		label='Test Revenue',
		plugin='test',
		model_path='pgappforge.plugins.erp.finance.ar.models.ARInvoice',
		field='total_amount_cents',
		agg='sum',
		filters={'status': 'PAID'},
	))
	results = registry.query(['test.revenue'], tenant_id='t1', session=session)
	assert 'test.revenue' in results
	assert isinstance(results['test.revenue'], list)
```

**SlotRegistry**

```python
def test_slot_renders_multiple_providers():
	from pgappforge.ui.slots import SlotRegistry
	registry = SlotRegistry()
	registry.register_provider('test.slot', lambda ctx: '<p>A</p>', priority=10)
	registry.register_provider('test.slot', lambda ctx: '<p>B</p>', priority=20)
	output = str(registry.render('test.slot', {}))
	assert '<p>A</p>' in output
	assert '<p>B</p>' in output
	assert output.index('<p>A</p>') < output.index('<p>B</p>')

def test_failing_provider_does_not_break_slot():
	from pgappforge.ui.slots import SlotRegistry
	registry = SlotRegistry()
	registry.register_provider('test.slot', lambda ctx: (_ for _ in ()).throw(RuntimeError()), priority=10)
	registry.register_provider('test.slot', lambda ctx: '<p>OK</p>', priority=20)
	output = str(registry.render('test.slot', {}))
	assert '<p>OK</p>' in output
```

---

## Anti-Patterns and Gotchas

**1. Circular Event Loops**

`emit()` fires handlers synchronously in the calling thread. If handler A emits event X, and handler B (subscribed to X) emits event Y, and handler A is also subscribed to Y, you have an infinite loop. This will exhaust the stack. Detect this during development by adding call depth counters. Avoid it architecturally by ensuring event types form a DAG: downstream events should belong to a different domain than upstream events (e.g. `payments.*` → `notifications.*` is fine; `payments.*` → `payments.*` is a red flag).

**2. Registering Mixins After Mapper Compilation**

`register_mixin()` raises `RuntimeError` if called after `apply_all_mixins()` has run. If you see this error in production, a plugin module is being imported lazily (inside a view function or request handler) rather than at startup. Fix: ensure all plugin imports happen in the app factory before `apply_all_mixins()` is called.

**3. `apply_all_mixins()` Called Too Late**

If `apply_all_mixins()` is called after `db.create_all()` or after the first SQLAlchemy query, SQLAlchemy's mapper may already be compiled. Columns added after mapper compilation will not appear in ORM queries (they'll be invisible to `session.query(ARInvoice).all()`). The table metadata will be correct but the mapped class will not reflect the new columns. Always call `apply_all_mixins()` before any ORM access.

**4. Policy Fail-Closed in All Environments**

`require_policy()` calls `flask.abort(403)` on policy failure — even in development. There is no `DEBUG` bypass. If you are seeing unexpected 403s during development, check that `current_user` has the correct roles. Use `policy.check(current_user, context)` directly in the Flask shell to diagnose.

**5. `emit()` Without Session Is Not Durable**

Calling `emit()` without a `session` argument gives in-process synchronous dispatch only. If the process restarts before the handler completes, the event is lost. This is correct for low-stakes notifications but wrong for financial events (GL postings, payment reconciliation). Always pass `session=` for events that must not be lost.

**6. Non-Additive Metrics Summed Across Groups**

`query_metrics()` logs a warning but does not prevent you from summing `avg` or `distinct` metrics across groups. If you build a dashboard that sums `finance.ar.avg_invoice_size` across regions, the number will be mathematically wrong (it is the sum of averages, not the average of all rows). Check `Metric.is_additive()` before displaying aggregated values; for non-additive metrics, display each group's value separately or fetch from raw queries.

**7. Slot Providers That Return `None`**

If a slot provider returns `None` (implicit return from a function that fell through all branches), `SlotRegistry.render()` will silently skip it (`if result:` is the check). This is intentional. But if you expect a provider to always render something and it is silently absent, add an explicit `return ''` at the end of every code path and add a test.

**8. `call_workflow` Sub-Instances Are Synchronous**

`_execute_call_workflow()` calls `engine.start()` synchronously and blocks until the child workflow either completes or reaches its first `UserTask`. For workflows that complete fully in one pass (all `ServiceTask` steps), this is fine. For child workflows that contain `UserTask` steps, the parent workflow will advance past the `call_workflow` step immediately, storing the child instance ID, but the child will remain in `WAITING` state. The parent's `outputs` mapping will only reflect the child's state at the moment `start()` returns. For truly asynchronous child workflows (requiring human tasks), do not use `call_workflow` — instead emit an event and handle the correlation in the event handler.

**9. `SystemSession` Does Not Grant DB Superuser Privileges**

`SystemSession` sets the PostgreSQL session variable `app.tenant_id = 'SYSTEM'`. It only works if your RLS policies are written to check this sentinel. It does not grant `SUPERUSER` or `BYPASSRLS` PostgreSQL privileges. If your RLS policies use `current_setting('app.tenant_id')` and explicitly allow `SYSTEM`, it works. If your RLS policies use `SET ROLE tenant_user` or other mechanisms, `SystemSession` will have no effect. Verify your RLS policy definitions before relying on this in production.

**10. FederationRegistry Types Are Module-Level Singletons**

`@federated_type` registers with the global registry at class definition time. If a plugin module is imported more than once (e.g. during testing, by reloading modules), the type will be registered twice and the second registration overwrites the first with a warning log. In tests, use a local `FederationRegistry()` instance rather than the global singleton to avoid cross-test contamination.
