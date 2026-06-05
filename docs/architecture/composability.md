# Plugin Composability Contract

Every plugin in the PgAppForge ERP suite is a self-contained unit that can be
installed independently or composed with other plugins. This document defines
the 10-point contract that all plugins must follow.

Reference implementations: `pgappforge/plugins/erp/__init__.py` (`install_all`),
`pgappforge/plugins/base_plugin.py` (`BasePlugin`), and any plugin `__init__.py`.

---

## Point 1 — Plugin Class Structure

Every plugin is a `BasePlugin` subclass registered in `ERP_GROUPS` in
`pgappforge/plugins/erp/__init__.py`.

```python
# pgappforge/plugins/erp/finance/gl/__init__.py
from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

class GLPlugin(BasePlugin):

    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="finance.gl",
            version="1.0.0",
            description="General Ledger: chart of accounts, journals, periods, budgets.",
            author="PgAppForge",
            priority=PluginPriority.HIGH,
        )

    def initialize(self) -> None:
        self.register_views()

    def register_views(self) -> None:
        from pgappforge.plugins.erp.finance.gl.views import (
            GLAccountView, GLJournalBatchView, GLPeriodView,
        )
        self.add_view(GLAccountView,      "Chart of Accounts", category="Finance")
        self.add_view(GLJournalBatchView, "Journal Batches",   category="Finance")
        self.add_view(GLPeriodView,       "GL Periods",        category="Finance")
```

The plugin is registered in `ERP_GROUPS` under its logical group:

```python
# pgappforge/plugins/erp/__init__.py
"finance.gl": {
    "key": "finance.gl",
    "module": "pgappforge.plugins.erp.finance.gl",
    "class_name": "GLPlugin",
    "description": "General Ledger: chart of accounts, journals, periods, budgets.",
}
```

---

## Point 2 — register_models() → list[type]

Every plugin exposes its SQLAlchemy model classes so Alembic autogenerate can
discover them. Return only classes owned by this plugin — do not return models
from other plugins even if you query them.

```python
class GLPlugin(BasePlugin):

    def register_models(self) -> list[type]:
        from pgappforge.plugins.erp.finance.gl.models import (
            GLAccount, GLCostCenter, GLFiscalYear, GLPeriod,
            GLJournalBatch, GLJournalEntry, GLJournalLine,
            GLAccountBalance, GLBudget,
        )
        return [
            GLAccount, GLCostCenter, GLFiscalYear, GLPeriod,
            GLJournalBatch, GLJournalEntry, GLJournalLine,
            GLAccountBalance, GLBudget,
        ]
```

All models must use:
- `UUID(as_uuid=False)` PKs with `server_default=sa.text("gen_random_uuid()")`
- `DateTime(timezone=True)` for all timestamps
- `tenant_id UUID NOT NULL` on every table
- `AuditMixin` on every mutable entity

---

## Point 3 — get_events() → list[str]

Return every dotted event-name string that this plugin emits. The names are
registered in `COMPOSABILITY_MAP` in `pgappforge/plugins/erp/__init__.py` and
used by `event_emitters()` / `event_consumers()` introspection helpers.

```python
class GLPlugin(BasePlugin):

    def get_events(self) -> list[str]:
        return [
            "gl.journal.posted",
            "gl.batch.posted",
            "gl.journal.reversed",
            "gl.period.closed",
        ]
```

Naming convention: `<domain>.<entity>.<past_tense_verb>` using dots, all
lowercase, no spaces.

---

## Point 4 — subscribe_to() → list[str]

Return the event names this plugin listens for. The plugin manager routes
incoming events to `handle_event(event_name, payload, session)` on activation.

```python
class PayrollPlugin(BasePlugin):

    def subscribe_to(self) -> list[str]:
        # Payroll listens for timesheet approvals to include in payrun
        return [
            "hcm.time.timesheet.approved",
            "hcm.personnel.employee.terminated",
        ]

    def handle_event(self, event_name: str, payload: dict, session) -> None:
        if event_name == "hcm.time.timesheet.approved":
            # Mark timesheet eligible for inclusion in next payrun
            ...
        elif event_name == "hcm.personnel.employee.terminated":
            # Flag final pay calculation required
            ...
```

If a plugin does not consume any events, return an empty list — do not omit
the method.

---

## Point 5 — activate(app, db, appbuilder) → None / bool

The `activate()` method is called by `install_all()`. It runs the full plugin
lifecycle: `pre_initialize()` → `initialize()` → `post_initialize()` →
`register_views()`. The `BasePlugin.activate()` implementation handles the
lifecycle and returns `True` on success, `False` on error (with logging).

```python
# Calling convention from install_all():
plugin = GLPlugin(appbuilder, config=cfg)
ok = plugin.activate()   # returns bool; never raises in non-strict mode
```

Within `initialize()`, plugins may call `appbuilder.get_app` to access the
Flask app and `appbuilder.get_session` to access the scoped DB session. They
must not assume a request context exists.

---

## Point 6 — Monetary Amounts: INTEGER CENTS in BigInteger

**All monetary values stored in the database are integer cents (or minor
currency units), stored in `BigInteger` columns. Never use `float` or
`Numeric` for money.**

```python
# Correct — integer cents
amount_cents = Column(BigInteger, nullable=False, default=0)

# Wrong — float (rounding errors accumulate)
amount = Column(Float, nullable=False, default=0.0)

# Wrong — Numeric (acceptable for rates/quantities, not money storage)
amount = Column(Numeric(12, 2), nullable=False, default=0)
```

Intermediate arithmetic uses `decimal.Decimal` with `ROUND_HALF_UP`:

```python
from decimal import Decimal, ROUND_HALF_UP

def _rc(d: Decimal) -> int:
    """Round Decimal → int cents."""
    return int(d.to_integral_value(rounding=ROUND_HALF_UP))

# Example: 12.5% of 100,000 cents
tax = _rc(Decimal("100000") * Decimal("0.125"))  # → 12500
```

Display conversion for APIs: divide by 100 and format as a string with two
decimal places. Never store the divided value.

---

## Point 7 — GL Integration: Lazy Import GLBridgeMixin._post_to_gl() in try/except

Plugins that need to post accounting entries use `GLService.post_simple_journal()`
or the `GLBridgeMixin._post_to_gl()` helper. The import is lazy and wrapped in
`try/except` so the plugin degrades gracefully if the GL plugin is not installed.

```python
# In any plugin service that posts to GL
def _post_to_gl(
    self,
    lines: list[dict],
    session,
    tenant_id: str,
    description: str,
    source_doc_id: str = "",
) -> str | None:
    """Post a balanced journal to GL. Non-fatal if GL plugin absent."""
    try:
        from pgappforge.plugins.erp.finance.gl.services import GLService
        from pgappforge.plugins.erp.finance.gl.constants import (
            CASH_AND_NOSTRO, AR_CONTROL,   # import what you need
        )
        return GLService().post_simple_journal(
            lines=lines,
            session=session,
            tenant_id=tenant_id,
            description=description,
            source_doc_id=source_doc_id,
        )
    except ImportError:
        # GL plugin not installed — skip posting silently
        return None
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning(
            "_post_to_gl failed (non-fatal): %s", exc
        )
        return None
```

`post_simple_journal()` returns `None` (not an error) when no open GL period
exists for the tenant. This is expected during initial setup.

Account codes must be resolved via `_resolve_gl()` before passing to GL, to
honour per-tenant `cb_gl_mapping` overrides:

```python
from pgappforge.plugins.erp.finance.gl.constants import AR_CONTROL, REVENUE_SERVICES

ar_code  = self._resolve_gl(AR_CONTROL,       session, tenant_id)
rev_code = self._resolve_gl(REVENUE_SERVICES, session, tenant_id)

lines = [
    {"account_code": ar_code,  "debit_cents": amount, "credit_cents": 0},
    {"account_code": rev_code, "debit_cents": 0,       "credit_cents": amount},
]
```

---

## Point 8 — Events: emit_event() Wrapped in try/except (Non-Fatal)

Event emission must never crash a transaction. Wrap every `emit_event()` call
in `try/except`:

```python
from pgappforge.plugins.erp.finance.gl.events import emit_event

def post_invoice(self, invoice_id: str, session) -> dict:
    # ... core business logic ...
    invoice.status = "SENT"
    session.flush()

    # Event emission is fire-and-forget — non-fatal
    try:
        from pgappforge.plugins.erp.finance.ar.events import InvoiceIssuedEvent
        emit_event(
            InvoiceIssuedEvent(
                aggregate_id=invoice_id,
                aggregate_type="ARInvoice",
                tenant_id=invoice.tenant_id,
                invoice_id=invoice_id,
                amount_cents=invoice.total_cents,
            ),
            session,
        )
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("emit_event failed: %s", exc)

    return {"invoice_id": invoice_id, "status": "SENT"}
```

`emit_event()` writes to the `erp_domain_event_log` table (append-only) and
optionally dispatches to `platform.events` subscriptions. Both operations are
non-transactional from the caller's perspective.

---

## Point 9 — Model Requirements

Every model in a plugin must satisfy all of the following:

| Requirement | Pattern |
|-------------|---------|
| UUID PK | `id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))` |
| tenant_id | `tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)` |
| created_at | `Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))` |
| updated_at | `Column(DateTime(timezone=True), nullable=False, default=..., onupdate=..., server_default=sa.text("NOW()"))` |
| AuditMixin | `class MyModel(AuditMixin, Model):` |
| Table prefix | Distinct per plugin, e.g. `gl_`, `ap_`, `proj_`, `te_`, `eam_`, `fleet_`, `fpa_`, `clm_` |
| `extend_existing` | `__table_args__ = (..., {"extend_existing": True})` |

Immutable event/ledger rows (e.g. `GLJournalLine`, `MeterReading`) omit
`updated_at` deliberately — they must never be updated after creation.

```python
class GLJournalLine(AuditMixin, Model):
    # ... columns ...
    created_at = Column(DateTime(timezone=True), ...)
    # No updated_at — journal lines are immutable once posted
```

---

## Point 10 — Multi-Tenancy: Every Query MUST Filter by tenant_id

**There are no exceptions.** Every `select()` that touches tenant-owned data
must include a `WHERE tenant_id = :tenant_id` clause.

```python
# Correct
rows = session.execute(
    select(GLJournalBatch).where(
        GLJournalBatch.tenant_id == tenant_id,
        GLJournalBatch.status == "DRAFT",
    )
).scalars().all()

# Wrong — returns data from all tenants
rows = session.execute(
    select(GLJournalBatch).where(GLJournalBatch.status == "DRAFT")
).scalars().all()
```

Lookup tables that are globally shared (e.g. `erp_currency`, `erp_country`,
`erp_code_table`) are exempt from tenant filtering, but all transactional and
configuration tables require it.

Cross-plugin references that use advisory UUIDs (no hard FK constraint across
plugin boundaries) must still filter by tenant_id on the owning side:

```python
# fleet_driver.employee_id is advisory — no FK to hcm_employee
# But fleet queries are still filtered by tenant_id
driver = session.execute(
    select(Driver).where(
        Driver.tenant_id == tenant_id,
        Driver.employee_id == employee_id,
    )
).scalar_one_or_none()
```

---

## Install Ordering

`install_all()` in `pgappforge/plugins/erp/__init__.py` respects topological
order based on `depends_on` metadata:

```
foundation → platform → finance → operations → crm → hcm → grc → analytics → industry
```

Within each group, plugins activate in declaration order. The `depends_on`
field in `ERP_GROUPS` documents group-level dependencies; individual plugins
within a group may have finer-grained service-layer dependencies that are
resolved lazily via `try/except ImportError`.

```python
from pgappforge.plugins.erp import install_all

# Activate all plugins
results = install_all(appbuilder)

# Cherry-pick groups
results = install_all(appbuilder, groups=["foundation", "finance"])

# Exclude specific plugins
results = install_all(appbuilder, skip=["industry.health", "grc.sustainability"])

# Strict mode — raise on first failure (useful in CI)
results = install_all(appbuilder, strict=True)
```

---

## Composability Map

The `COMPOSABILITY_MAP` dict in `pgappforge/plugins/erp/__init__.py` documents
every cross-plugin event wire:

```python
from pgappforge.plugins.erp import COMPOSABILITY_MAP, event_consumers, event_emitters

# Who emits ar.invoice.paid?
emitters = event_emitters("ar.invoice.paid")
# → ["finance.ar"]

# Who consumes ar.invoice.paid?
consumers = event_consumers("ar.invoice.paid")
# → ["analytics.operational", "analytics.cdp", "crm.sales", ...]
```

Use `COMPOSABILITY_MAP` to visualise data flows, validate upgrade ordering, or
generate architecture diagrams from code.
