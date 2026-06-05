# PgAppForge Rules Engine

The Rules Engine provides declarative, database-driven business logic that runs automatically on model events — no code changes required. Rules are created and managed through the Visual Rule Designer, validated in real time, and visualised as Mermaid flow diagrams.

---

## Table of Contents

1. [Quick Start](#quick-start)
2. [Concepts](#concepts)
3. [Rule Structure](#rule-structure)
4. [Conditions](#conditions)
5. [Actions](#actions)
6. [Advanced Value Syntax](#advanced-value-syntax)
7. [Stop Flags](#stop-flags)
8. [Engine API](#engine-api)
9. [Visual Rule Designer](#visual-rule-designer)
10. [Validator](#validator)
11. [Visualizer](#visualizer)
12. [REST API Reference](#rest-api-reference)
13. [RulesMixin Integration](#rulesmixin-integration)
14. [Error Types](#error-types)
15. [Examples](#examples)

---

## Quick Start

### 1. Attach `RulesMixin` to your model

```python
from pgappforge.plugins.rules.mixin import RulesMixin
from pgappforge.plugins.audit import AuditMixin
from pgappforge.models.sqla import Model

class Invoice(RulesMixin, AuditMixin, Model):
    __tablename__ = "invoice"
    _rules_mutable_fields = frozenset({"status", "approved_by", "notes"})
    # ... columns
```

### 2. Open the Visual Designer

Navigate to **Rules Engine Builder** (`/rules/`), click **New RuleSet**, set the **Model Name** to `Invoice`, and add your first rule.

### 3. Create a rule

- **Trigger**: `on_create`
- **Condition**: `amount_cents` `=` `0`
- **Action**: `block` — *Amount must be greater than zero*

### 4. Test it

Click **Test** in the designer modal, paste `{"amount_cents": 0}` as sample data, and see the dry-run result confirming the block would fire.

---

## Concepts

| Concept | Description |
|---------|-------------|
| **RuleSet** | Container for one or more rules applied to a model. Has a priority (lower = first), an enabled flag, and a `stop_on_match` flag. |
| **Rule** | A single if-then statement: trigger event + conditions + actions. Has `stop_after_actions` flag. |
| **Trigger Event** | When the rule fires: `on_create`, `on_update`, `on_delete`, `on_field_change:<field>`. |
| **Conditions** | Zero or more field comparisons that must all pass (AND by default, OR supported). Empty conditions = always match. |
| **Actions** | One or more operations executed when conditions pass: block, set_field, add_error, send_email, call_webhook, create_record, start_workflow. |

---

## Rule Structure

Rules are stored as JSON in the database (`RuleSet` and `Rule` models):

```json
{
  "name": "Block zero-amount invoices",
  "trigger_event": "on_create",
  "conditions_json": [
    {"field": "amount_cents", "op": "=", "value": 0}
  ],
  "actions_json": [
    {"type": "block", "message": "Invoice amount must be greater than zero"}
  ],
  "enabled": true,
  "order": 10,
  "stop_after_actions": false
}
```

---

## Conditions

Each condition is a dict with three required keys:

| Key | Type | Description |
|-----|------|-------------|
| `field` | string | Attribute name on the record |
| `op` | string | Comparison operator (see table below) |
| `value` | any | The value to compare against. Supports [advanced syntax](#advanced-value-syntax). |
| `logic` | string | `"AND"` (default) or `"OR"` |

### Supported Operators

| Operator | Meaning |
|----------|---------|
| `=` | Equal |
| `!=` | Not equal |
| `>` | Greater than |
| `<` | Less than |
| `>=` | Greater than or equal |
| `<=` | Less than or equal |
| `contains` | String/list contains |
| `starts_with` | String starts with |
| `ends_with` | String ends with |
| `in` | Value is in list |
| `not_in` | Value is not in list |
| `is_null` | Field is null/None |
| `is_not_null` | Field is not null/None |
| `regex` | String matches regex pattern |

### AND / OR Logic

Conditions with `"logic": "AND"` (the default) are all required. Conditions with `"logic": "OR"` are grouped together and at least one must pass. The overall result is: *(all AND conditions pass)* AND *(at least one OR condition passes, if any OR conditions exist)*.

```json
[
  {"field": "status", "op": "=", "value": "DRAFT"},
  {"field": "amount_cents", "op": ">", "value": 0, "logic": "AND"},
  {"field": "type", "op": "=", "value": "INVOICE", "logic": "OR"},
  {"field": "type", "op": "=", "value": "CREDIT_NOTE", "logic": "OR"}
]
```

---

## Actions

### `block`
Prevents the record from being saved. Raises `RulesValidationError`.

```json
{"type": "block", "message": "Amount must be positive"}
```

### `add_error`
Raises a field-level `RulesFieldError(field, message)`. Callers can catch this to display per-field validation errors.

```json
{"type": "add_error", "field": "email", "message": "Email is already registered"}
```

### `set_field`
Mutates a field on the record (only if the field is in `_rules_mutable_fields`).

```json
{"type": "set_field", "field": "status", "value": "APPROVED"}
```

The `value` supports [advanced value syntax](#advanced-value-syntax).

### `send_email`
Logs an email notification (stub — wire to your email provider).

```json
{"type": "send_email", "to": "finance@company.com", "subject": "Invoice approved", "body": "Invoice {{invoice_number}} has been approved."}
```

### `call_webhook`
POSTs a JSON payload to a webhook URL (URL must be in `FAB_RULES_WEBHOOK_ALLOWLIST`).

```json
{"type": "call_webhook", "url": "https://api.example.com/hooks/invoice", "payload": {"event": "approved"}}
```

**Security**: Only HTTPS URLs in the configured allowlist are accepted. Private/loopback IPs are rejected.

### `create_record`
Declaratively creates a new record of another model.

```json
{"type": "create_record", "model": "AuditLog", "fields": {"action": "APPROVED", "ref_id": "$id"}}
```

### `start_workflow`
Triggers a workflow process.

```json
{"type": "start_workflow", "workflow_type": "approval_workflow", "ref_id": "$id"}
```

---

## Advanced Value Syntax

The `value` field in conditions and `set_field` actions supports three forms:

| Syntax | Meaning | Example |
|--------|---------|---------|
| Plain | Literal value | `"APPROVED"`, `0`, `true` |
| `$field` | Read from the record's context | `"$status"` → value of `record.status` |
| `{{field}}` | String template interpolation | `"Hello {{first_name}}"` |

### Examples

**Field-to-field comparison** (approve if amount equals approved_amount):
```json
{"field": "amount_cents", "op": "=", "value": "$approved_amount_cents"}
```

**Template in set_field**:
```json
{"type": "set_field", "field": "notes", "value": "Approved by {{approved_by}} on {{approved_at}}"}
```

**Designer shortcut**: Click the **ƒ** button next to any value input to cycle through `plain → $field → {{field}}`.

---

## Stop Flags

Two flags control early termination of rule processing:

### `rule.ruleset.stop_on_match`

When set to `True` on a **RuleSet**, processing halts after the **first rule that matches** (conditions pass) and executes successfully. Useful for priority-ordered rules where only the highest-priority matching rule should apply.

```python
ruleset.stop_on_match = True
```

### `rule.stop_after_actions`

When set to `True` on an individual **Rule**, processing halts after that rule's actions execute successfully, regardless of other rules in the set.

---

## Engine API

### `RulesEngine.evaluate(model_name, event, record, session=None)`

Live evaluation. Executes all matching rules, mutates the record, raises `RulesValidationError` (or `RulesFieldError`) on block/add_error.

```python
from pgappforge.plugins.rules.engine import get_rules_engine

engine = get_rules_engine()
engine.evaluate("Invoice", "on_create", invoice_obj, session=db.session)
```

Called automatically by `RulesMixin` on SQLAlchemy events (`before_insert`, `before_update`, `before_delete`).

### `RulesEngine.evaluate_dry(model_name, event, record, session=None)`

Simulation — **no mutations, no raises**. Returns a structured dict describing what would happen.

```python
result = engine.evaluate_dry("Invoice", "on_create", invoice_obj, session=db.session)
```

**Return value:**

```python
{
    "would_block": False,          # True if any block/add_error action fires
    "block_message": "",           # Message from the blocking action
    "block_field": None,           # Field name for add_error, None for block
    "would_set": {                 # Fields that would be mutated
        "status": "APPROVED"
    },
    "would_send_emails": [...],    # List of send_email action dicts
    "would_call_webhooks": [...],  # List of call_webhook action dicts
    "would_create_records": [...], # List of create_record action dicts
    "would_start_workflows": [...],# List of start_workflow action dicts
    "rules_matched": [             # Names of rules whose conditions passed
        "Auto-approve small invoices"
    ]
}
```

### `_resolve_value(value, context)`

Module-level helper. Resolves `$field` references and `{{template}}` strings against a context dict.

```python
from pgappforge.plugins.rules.engine import _resolve_value

_resolve_value("$status", {"status": "ACTIVE"})      # → "ACTIVE"
_resolve_value("Hello {{name}}", {"name": "Alice"})  # → "Hello Alice"
_resolve_value(42, {})                                # → 42 (passthrough)
```

---

## Visual Rule Designer

**URL**: `/rules/`

The designer provides a three-tab interface:

### Designer Tab

- **RuleSet form**: name, model name, priority, description, `stop_on_match` flag
- **Conditions builder**: click **+ Add Condition** for each condition row; ƒ button for advanced value syntax
- **Actions builder**: click **+ Add Action**; type dropdown reveals type-specific parameter fields:
  - `block` → message
  - `add_error` → field + message
  - `set_field` → field + value (with ƒ button)
  - `send_email` → to + subject + body
  - `call_webhook` → url + payload JSON
  - `create_record` → model + fields JSON
  - `start_workflow` → workflow_type

### Validator Tab

Real-time syntax validation with per-row feedback:

- 🟢 Green badge — condition/action is valid
- 🔴 Red badge — missing required field or invalid operator
- Tab link shows error count when any issues exist
- Validation fires automatically 500ms after any field change

### Visualizer Tab

Renders a Mermaid flowchart of the current ruleset:

- Diamond nodes (◇) for rules — labelled with name and trigger event
- Rectangle nodes (□) for actions — labelled with type-specific description
- `|conditions match|` edges to action nodes
- `|no match|` edges to the next rule, ending at an `END` terminal
- Click **Visualize** on any ruleset row for the page-level diagram

---

## Validator

**Endpoint**: `POST /rules/api/validate`

Validates condition/action JSON syntax without running against a real record.

**Request**:
```json
{
  "conditions": [
    {"field": "amount_cents", "op": "=", "value": 0}
  ],
  "actions": [
    {"type": "block", "message": "Amount must be positive"}
  ]
}
```

**Response** (valid):
```json
{"valid": true, "errors": []}
```

**Response** (invalid):
```json
{
  "valid": false,
  "errors": [
    {"path": "conditions[0].op", "message": "Unknown operator 'eq' — use '='"},
    {"path": "actions[1].message", "message": "Required for action type 'block'"}
  ]
}
```

---

## Visualizer

**Endpoint**: `GET /rules/api/visualize/<ruleset_id>`

Returns a Mermaid flowchart diagram string.

**Response**:
```json
{
  "mermaid": "flowchart TD\n    START([RuleSet: Invoice Rules]) --> R1\n    R1{Rule: Block zero-amount\\non_create} -->|conditions match| A1_0[block: Amount must be positive]\n    ..."
}
```

Render with Mermaid.js 10+:
```javascript
const { svg } = await mermaid.render("diagramId", result.mermaid);
document.getElementById("container").innerHTML = svg;
```

---

## REST API Reference

All endpoints require `has_access` (FAB authentication).

| Method | URL | Description |
|--------|-----|-------------|
| `GET` | `/rules/` | Rule designer UI |
| `GET` | `/rules/api/rulesets` | List all rule sets |
| `POST` | `/rules/api/rulesets` | Create rule set + first rule |
| `GET` | `/rules/api/rulesets/<id>` | Get rule set with rules |
| `PUT` | `/rules/api/rulesets/<id>` | Update rule set |
| `DELETE` | `/rules/api/rulesets/<id>` | Delete rule set |
| `POST` | `/rules/api/rules` | Create standalone rule |
| `PUT` | `/rules/api/rules/<id>` | Update rule |
| `DELETE` | `/rules/api/rules/<id>` | Delete rule |
| `POST` | `/rules/api/validate` | Validate conditions/actions JSON |
| `POST` | `/rules/api/test` | Dry-run against sample record |
| `GET` | `/rules/api/visualize/<id>` | Get Mermaid diagram for rule set |
| `GET` | `/rules/api/export/<id>` | Export rule set as JSON |
| `POST` | `/rules/api/import` | Import rule set from JSON |

### `POST /rules/api/test`

```json
{
  "ruleset_id": 1,
  "event": "on_create",
  "record": {
    "amount_cents": 0,
    "status": "DRAFT",
    "type": "INVOICE"
  }
}
```

**Response**: full `evaluate_dry()` result (see [Engine API](#engine-api)).

---

## RulesMixin Integration

### Attaching to a model

```python
from pgappforge.plugins.rules.mixin import RulesMixin

class MyModel(RulesMixin, AuditMixin, Model):
    __tablename__ = "my_model"

    # Allowlist of fields that set_field actions may mutate.
    # If not set, ALL fields are mutable (permissive mode).
    _rules_mutable_fields = frozenset({"status", "approved_by", "notes"})
```

### What happens automatically

`RulesMixin` registers SQLAlchemy event listeners:
- `before_insert` → calls `evaluate("on_create", record)`
- `before_update` → calls `evaluate("on_update", record)`
- `before_delete` → calls `evaluate("on_delete", record)`
- Field changes → calls `evaluate("on_field_change:<field>", record)` for changed fields

### Manual evaluation

```python
from pgappforge.plugins.rules.engine import get_rules_engine

# Fire rules programmatically
engine = get_rules_engine()
try:
    engine.evaluate("Invoice", "on_create", invoice, session=db.session)
except RulesValidationError as e:
    flash(str(e), "error")
    return render_template("invoice/new.html")
```

### Dry-run before save (preflight check)

```python
result = engine.evaluate_dry("Invoice", "on_create", invoice, session=db.session)
if result["would_block"]:
    return jsonify({"error": result["block_message"]}), 422
if result["would_set"]:
    # Show user what fields would be auto-set
    flash(f"Fields will be automatically set: {result['would_set']}", "info")
```

---

## Error Types

### `RulesValidationError`

Base exception raised when a `block` action fires.

```python
from pgappforge.plugins.rules.engine import RulesValidationError

try:
    engine.evaluate(...)
except RulesValidationError as e:
    print(e)  # "Amount must be positive"
```

### `RulesFieldError(RulesValidationError)`

Field-level validation error raised when an `add_error` action fires.

```python
from pgappforge.plugins.rules.engine import RulesFieldError

try:
    engine.evaluate(...)
except RulesFieldError as e:
    print(e.field_name)   # "email"
    print(e.message)      # "Email is already registered"
    print(str(e))         # "email: Email is already registered"
```

`RulesFieldError` is a subclass of `RulesValidationError`, so existing `except RulesValidationError` handlers catch it too.

---

## Examples

### Example 1: Auto-approve small invoices

```json
{
  "name": "Auto-approve invoices under KES 10,000",
  "trigger_event": "on_create",
  "conditions_json": [
    {"field": "amount_cents", "op": "<", "value": 1000000},
    {"field": "status", "op": "=", "value": "PENDING"}
  ],
  "actions_json": [
    {"type": "set_field", "field": "status", "value": "APPROVED"},
    {"type": "set_field", "field": "approved_by", "value": "SYSTEM"}
  ]
}
```

### Example 2: Mandatory senior approval for large amounts

```json
{
  "name": "Require senior approval for invoices over KES 500,000",
  "trigger_event": "on_create",
  "conditions_json": [
    {"field": "amount_cents", "op": ">=", "value": 50000000}
  ],
  "actions_json": [
    {"type": "block", "message": "Invoices over KES 500,000 require senior manager approval. Please submit via the approval workflow."}
  ]
}
```

### Example 3: Field-level email validation

```json
{
  "name": "Validate email format",
  "trigger_event": "on_create",
  "conditions_json": [
    {"field": "email", "op": "regex", "value": "^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$", "logic": "AND"},
    {"field": "email", "op": "is_not_null"}
  ],
  "actions_json": []
}
```

Wait — conditions should indicate WHEN to run the add_error. Invert:

```json
{
  "name": "Block invalid email",
  "trigger_event": "on_create",
  "conditions_json": [
    {"field": "email", "op": "is_not_null"},
    {"field": "email", "op": "regex", "value": "^(?![^@\\s]+@[^@\\s]+\\.[^@\\s]+$).+"}
  ],
  "actions_json": [
    {"type": "add_error", "field": "email", "message": "Please enter a valid email address"}
  ]
}
```

### Example 4: Cross-field comparison (field-to-field)

```json
{
  "name": "Ensure delivery date is after order date",
  "trigger_event": "on_create",
  "conditions_json": [
    {"field": "delivery_date", "op": "<", "value": "$order_date"}
  ],
  "actions_json": [
    {"type": "add_error", "field": "delivery_date", "message": "Delivery date must be after the order date"}
  ]
}
```

### Example 5: Webhook notification on status change

```json
{
  "name": "Notify ERP when invoice paid",
  "trigger_event": "on_field_change:status",
  "conditions_json": [
    {"field": "status", "op": "=", "value": "PAID"}
  ],
  "actions_json": [
    {"type": "call_webhook", "url": "https://erp.company.com/hooks/invoice-paid", "payload": {"invoice_id": "$id", "amount": "$amount_cents"}}
  ]
}
```

### Example 6: Stop on first match (priority rules)

Create three rule sets with `stop_on_match = True`:
1. **VIP Customer Rule** (priority 10): if `customer_tier = "VIP"` → `set_field status = "EXPRESS_PROCESS"`
2. **Large Order Rule** (priority 20): if `amount_cents >= 50000000` → `set_field status = "SENIOR_REVIEW"`
3. **Standard Rule** (priority 100): → `set_field status = "STANDARD"`

Each ruleset has `stop_on_match = True`. The highest-priority matching rule wins.

---

## Configuration

| Config Key | Default | Description |
|------------|---------|-------------|
| `FAB_RULES_WEBHOOK_ALLOWLIST` | `[]` | List of allowed webhook hostnames. Must be set to enable `call_webhook` actions. |

```python
# In Flask config
FAB_RULES_WEBHOOK_ALLOWLIST = ["api.company.com", "hooks.slack.com"]
```

---

## DSL Import/Export

Rule sets can be exported to JSON and imported via the designer UI or REST API:

```bash
# Export
curl -H "Authorization: Bearer <token>" \
  http://localhost:5000/rules/api/export/1 > invoice_rules.json

# Import
curl -X POST -H "Content-Type: application/json" \
  -H "Authorization: Bearer <token>" \
  -d @invoice_rules.json \
  http://localhost:5000/rules/api/import
```

The DSL module (`pgappforge/plugins/rules/dsl.py`) provides a Python API for programmatic rule set construction for seeding.
