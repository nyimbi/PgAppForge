# Demand Planning Plugin — Design Comparison

## Scope

Statistical demand forecasting for the PgAppForge ERP suite.

Covers: actual demand history recording (upsert), four forecast methods
(Moving Average, Exponential Smoothing, Holt-Winters additive, Manual),
planner approval workflow, consensus planning support, and MAPE/Bias
accuracy KPI computation.

---

## Alternatives Considered

### Option A — numpy/scipy for Holt-Winters (Rejected)

Industry-standard Python implementations of Holt-Winters use `statsmodels`
(`statsmodels.tsa.holtwinters.ExponentialSmoothing`) or `scipy`.

**Rejected because:**
- Adds a 40+ MB dependency to a server-side ERP plugin.
- `statsmodels` uses float64 internally — incompatible with the codebase's
  Decimal-only arithmetic requirement for all quantity fields.
- The Holt-Winters additive equations are straightforward to implement in
  pure Decimal arithmetic (~80 lines) with no precision loss.
- Deployment targets may lack C extension support (Alpine containers, etc.).

**Trade-off accepted:** The pure-Decimal implementation does not support
multiplicative seasonality or damped trends. These can be added later
without changing the service interface.

### Option B — Separate Forecast Versions Table (Rejected)

Store each forecast iteration as a new version row in a dedicated
`dp_forecast_version` table, with the active version pointer in `dp_forecast`.

**Rejected because:**
- Adds a join on every read.
- The simpler supersede pattern (status=SUPERSEDED) achieves the same audit
  trail with a single table query.
- Version history can be reconstructed from the DomainEventLog if needed.

### Option C — Store Periods as Separate Rows (Rejected)

A normalised `dp_forecast_period` table with one row per (forecast_id, period)
instead of JSONB.

**Rejected because:**
- Adds significant JOIN complexity for the common read path (load all periods
  for a forecast).
- JSONB is the established pattern for variable-length period arrays in this
  codebase (see `inventory.dimensions_cm`, etc.).
- Period data is always read and written as a unit — no need for row-level
  period queries.
- JSONB approach matches the MRP integration pattern: `get_approved_forecast`
  iterates the JSONB array, not a separate table.

### Option D — Forecast Stored as Float (Rejected)

Store `forecast_qty` as `Float` in PostgreSQL.

**Rejected because:**
- Violates the codebase invariant: all quantity fields use Decimal arithmetic.
- Float accumulation errors in Holt-Winters seasonal indices would compound
  over long training histories.
- `Decimal(str(float_value))` coercion introduces hidden precision loss.

### Option E — JSONB Periods with Decimal Column (Hybrid, Rejected)

Store the JSONB periods list but also materialise a `next_period_forecast_qty
Numeric(15,4)` column for fast single-value lookup by the MRP engine.

**Rejected because:**
- Denormalisation with dual write paths risks inconsistency.
- `get_approved_forecast` is already fast (single index scan on tenant_id +
  product_id + status, then iterate a small JSONB array ≤ 24 entries).
- The extra column adds migration complexity for marginal read gain.

---

## Key Design Decisions

### Decision 1 — Pure Decimal Arithmetic Throughout

All smoothing coefficients, historical values, residuals, and forecasts are
`Decimal` from first computation to final storage. The Newton-Raphson square
root in `_std_dev` operates in Decimal space with 25-iteration convergence.

**Rationale:** The codebase prohibits float for any quantity field. Holt-Winters
with float coefficients on 36+ month histories accumulates ~0.5% error in
seasonal indices — acceptable for most use cases, but inconsistent with the
project's precision guarantees.

### Decision 2 — Holt-Winters Falls Back to ES on Short History

When fewer than `2 * season_len` (24 months) of history is available, the
Holt-Winters implementation automatically falls back to single exponential
smoothing rather than raising an error.

**Rationale:** New product launches frequently lack two full years of history.
Raising an error would block the MRP run for those products. ES with alpha=0.3
is a reasonable degraded forecast that planners can override via MANUAL method.

### Decision 3 — Forecast Approval is One-Way

`approve_forecast` transitions DRAFT → APPROVED. There is no "unapprove"
operation. To revise an approved forecast, generate a new one (which supersedes
the old).

**Rationale:** Approved forecasts may already be consumed by MRP runs. Allowing
unapproval would create temporal inconsistency between MRP planned orders and
their demand basis. The supersede pattern maintains a clean audit trail.

### Decision 4 — MAPE/Bias Computed Post-Hoc, Not Stored in History

`compute_accuracy` loads actuals and forecasts at query time rather than storing
accuracy metrics in `dp_history`.

**Rationale:** Accuracy metrics depend on which forecast is being compared against
the actuals — the "best" forecast for a period changes as new forecasts supersede
old ones. On-demand computation ensures the metric always reflects the current
approved forecast.

The exception: `accuracy_mape` is stored on the forecast record after
`compute_accuracy` is called — for display in forecast list views without
re-computation.

### Decision 5 — Period Labels are Strings, Not Dates

`DemandHistory.period` and `DemandForecast.base_period` are VARCHAR(20) strings
(e.g. "2025-06" for monthly, "W24-2025" for weekly).

**Rationale:** Demand planning periods are business planning buckets, not precise
datetime ranges. The period granularity varies by industry (monthly for consumer
goods, weekly for FMCG, quarterly for capital goods). Lexicographic ordering of
YYYY-MM format strings is correct for monthly periods. Non-monthly formats can
use the `_build_period_label` fallback (appends "+N" offset).

---

## Algorithm Accuracy Trade-offs

| Method | Pros | Cons | Best For |
|---|---|---|---|
| MOVING_AVERAGE | Simple, stable, interpretable | Lags trends; constant forecast | Stable demand, no seasonality |
| EXPONENTIAL_SMOOTHING | Handles trend changes | No seasonality | Trending demand, no seasonal pattern |
| HOLT_WINTERS | Handles trend + seasonality | Requires 24+ months; additive only | Seasonal products with clear cycle |
| MANUAL | Full planner control | No algorithmic basis | New products; promotional periods |

Default smoothing parameters (α=0.3, β=0.1, γ=0.2) are industry-typical
starting points. Per-product parameter optimisation (e.g. minimising in-sample
MAPE) is not implemented — it requires iterative optimisation which adds
dependency on an optimiser library.

---

## Schema Choices

| Column | Type | Rationale |
|---|---|---|
| `dp_forecast.periods` | JSONB | Variable-length list; always read/written as unit |
| `dp_forecast.accuracy_mape` | Numeric(8,4) | 4 decimal places sufficient for % values |
| `dp_forecast.approved_at` | DateTime(timezone=True) | Ordering tie-breaker for multi-forecast lookup |
| `dp_history.actual_qty` | Numeric(15,4) | Fractional UOMs (kg, L) must be supported |
| `dp_history.source` | VARCHAR(30) + CHECK | Enum via CHECK; easy to extend without migration |

---

## Integration with MRP

`DemandPlanningService.get_approved_forecast` is the integration point consumed
by `MRPService._get_open_demand`. It returns a `Decimal | None` — the MRP engine
treats `None` as zero demand from the forecast source, relying on safety stock
and open SO lines for net requirements.

The dependency is one-directional: Demand Planning has no import from MRP.
MRP imports Demand Planning (lazy, try/except ImportError). This means Demand
Planning can be deployed without MRP, but MRP without Demand Planning simply
sees zero forecast demand.
