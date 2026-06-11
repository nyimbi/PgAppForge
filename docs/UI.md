# UI Architecture & UX Design

PgAppForge's UI is built on three interlocking layers: an **islands architecture runtime**, a **CSS design-token system**, and a **server-side widget API**. Together they deliver world-class UX with no build pipeline and no frontend framework dependency.

---

## 1. Islands Architecture — no build step

The interactive layer is a 176-line vanilla JavaScript runtime (`pgappforge/static/appbuilder/js/erp_islands.js`). Each interactive component is a self-contained "island" that follows a strict lifecycle:

```
Server renders skeleton HTML  →  aria-busy=true  →  CDN libs loaded lazily
→  factory function called  →  aria-busy=false  →  live content
```

**Registration** (in any template's `<script>` block):
```javascript
ERPIslands.register('revenueChart', ['chartjs'], function (el) {
    new Chart(el.querySelector('canvas'), { type: 'bar', data: { ... } })
})
```

**Auto-mounting** happens at `DOMContentLoaded`:
```javascript
ERPIslands.mountAll()  // finds every [data-island] element, calls register()
```

### CDN library loading

Islands declare which libraries they need. The runtime loads them on demand, exactly once per page:

| Library | Alias | Used by |
|---|---|---|
| Chart.js 4.4.3 | `chartjs` | KPI charts, bar/line/donut |
| D3 7.9.0 | `d3` | Heatmaps, portfolio cap-rate matrix |
| SortableJS 1.15.2 | `sortable` | Kanban boards (maintenance, LOI pipeline) |
| Alpine.js 3.14.0 | `alpine` | Reactive forms, toggle panels |

All four CDN scripts carry **`integrity` (sha384) and `crossorigin` attributes** — supply-chain attack protection. A `Promise.race` with a **10-second timeout** ensures no island hangs forever on a slow CDN.

**Deduplication**: if two islands both need Chart.js, the second call returns the cached Promise immediately — no double download.

### Skeleton-first rendering

Every island has a Jinja2-rendered skeleton visible before JavaScript runs:

```html
<div data-island="pmRentRollSummary" class="erp-island">
  <!-- Server renders this immediately — instant paint -->
  <div class="erp-kpi-grid">
    {% for _ in range(4) %}
    <div class="erp-card">
      <div class="erp-skeleton erp-skeleton-text short"></div>
      <div class="erp-skeleton erp-skeleton-text wide" style="height:28px"></div>
    </div>
    {% endfor %}
  </div>
  <!-- Island runtime replaces this with live content -->
</div>
```

The skeleton uses CSS shimmer animation (`erp-skeleton`) that respects `prefers-reduced-motion`. FCP is the server response time — not CDN load + JS parse time.

---

## 2. Design System — `erp_islands.css` (838 lines)

A single CSS file defines **24 design tokens** as CSS custom properties at `:root`:

```css
:root {
  /* Colour palette */
  --erp-primary:     #1a56db;    --erp-primary-lt:  #e8f0fe;
  --erp-success:     #0e9f6e;    --erp-success-lt:  #def7ec;
  --erp-warning:     #ff5a1f;    --erp-warning-lt:  #fff3cd;
  --erp-danger:      #e02424;    --erp-danger-lt:   #fde8e8;
  --erp-neutral:     #6b7280;    --erp-neutral-lt:  #f3f4f6;

  /* Surface & typography */
  --erp-surface:     #ffffff;    --erp-border:      #e5e7eb;
  --erp-text:        #111827;    --erp-text-muted:  #6b7280;
  --erp-font:        -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;

  /* Shape & elevation */
  --erp-radius:      6px;        --erp-radius-lg:   10px;
  --erp-shadow-sm:   0 1px 3px rgba(0,0,0,.08);
  --erp-shadow:      0 4px 6px -1px rgba(0,0,0,.10);
  --erp-shadow-lg:   0 10px 15px -3px rgba(0,0,0,.10);
  --erp-transition:  150ms ease;
}
```

Every component reads from these tokens. **Theming is a single override**:

```python
# config.py — landing page accent colour
LANDING_ACCENT_COLOR = "#7c3aed"   # purple — overrides --erp-primary at page level
```

### Core utility classes

| Class | Purpose |
|---|---|
| `.erp-card` | Elevated surface, `var(--erp-radius)`, `var(--erp-shadow-sm)` |
| `.erp-kpi-grid` | `auto-fill, minmax(200px, 1fr)` responsive grid |
| `.erp-skeleton` | Shimmer placeholder (respects `prefers-reduced-motion`) |
| `.erp-island` | Container for an island component; sets `position: relative` |
| `.erp-page-header` | Page title + subtitle block |
| `.erp-chart-wrap` | Chart container with title + shadow |
| `.erp-feed` / `.erp-feed-item` | Activity feed list |
| `.erp-mb-24` | `margin-bottom: 24px` spacing token |

---

## 3. Server-side widget system — `BaseERPView`

Every ERP dashboard view inherits `BaseERPView` (`pgappforge/plugins/erp/base_view.py`, 408 lines), which provides **5 server-rendered widget helpers** and **3 utility methods**:

### Widget helpers

All helpers return `Markup` objects — safe pre-rendered HTML for `{{ widget | safe }}` in templates.

#### `kpi_cards(kpis)` — Stat tiles

```python
kpi_html = self.kpi_cards([
    {"label": "Active Loans",   "value": self._count(Loan, status="ACTIVE"),  "icon": "fa-money", "color": "#0e9f6e"},
    {"label": "PAR 30",         "value": "4.2%",  "icon": "fa-warning",        "color": "#ff5a1f", "trend": "▲ 0.3%"},
    {"label": "New Today",      "value": 12,      "icon": "fa-plus-circle",    "color": "#1a56db"},
])
```

XSS-safe: `color` validated against `^#[0-9a-fA-F]{6}$`; `icon` validated against `^fa-[a-z0-9-]+$`. Any invalid value falls back to a safe default.

#### `chart(rows, chart_type, x_col, y_col)` — Embedded chart

```python
chart_html = self.chart(monthly_data, chart_type="line", x_col="month", y_col="amount")
```

Supported types: `bar`, `line`, `pie`, `doughnut`, `radar`, `polarArea`. Optional `group_col` for multi-series.

#### `approval_buttons(obj, advance_url, reject_url)` — BPM workflow

```python
approval_html = self.approval_buttons(
    payroll_run,
    advance_url="/workflow/advance",
    reject_url="/workflow/reject",
    instance_id_col="process_instance_id",
)
```

Renders Approve / Reject buttons wired to the BPM engine. Only shown when `obj.process_instance_id` is set.

#### `data_grid(rows, columns, save_url)` — Inline bulk edit

```python
grid_html = self.data_grid(
    rows=timesheets,
    columns=[{"key": "hours", "label": "Hours", "type": "number", "editable": True}],
    save_url="/api/timesheets/bulk-update",
)
```

#### `heatmap_calendar(rows, date_col, value_col)` — Activity heatmap

```python
heatmap_html = self.heatmap_calendar(daily_counts, date_col="date", value_col="count")
```

GitHub-style contribution calendar using D3. Used for: payroll run history, GL posting frequency, member check-in patterns.

### Utility methods

| Method | Returns |
|---|---|
| `_count(Model, session=None, **filters)` | `int` — live count, returns `0` on any error |
| `_session()` | Active SQLAlchemy session from `appbuilder.get_session()` |
| `_tenant_id()` | `str` — `DEFAULT_TENANT_ID` from Flask config |

### `BaseERPModelView` — Uniform CRUD

```python
class BaseERPModelView(ModelView):
    _AUDIT = ("id", "created_on", "changed_on", "created_at", "updated_at")
    add_exclude_columns  = list(_AUDIT)
    edit_exclude_columns = list(_AUDIT)
    page_size = 50
```

All 129 ERP module list views inherit this — consistent audit field exclusion, consistent pagination, without per-module boilerplate.

---

## 4. Template hierarchy

**184 templates** across all modules follow a strict hierarchy:

```
pgappforge/templates/appbuilder/
├── erp/
│   ├── base_erp.html          ← navbar, flash messages, CSS/JS bundle
│   └── home_dashboard.html    ← KPI island + revenue chart + activity feed
├── finance/                   ← trial balance, GL drill-down
├── hcm/                       ← payroll dashboard, payslip template
├── re_pm/                     ← rent roll, maintenance kanban
├── re_commercial/             ← CAM reconciliation, LOI pipeline
├── re_portfolio/              ← portfolio analytics, investor statement
├── apg/                       ← APG capability portal (proxy rendering)
├── landing/                   ← editable deployment landing page
└── ...                        ← 25+ domain template directories
```

**25 templates** carry `data-island` attributes. Named islands include:

| Island | Domain | Libraries |
|---|---|---|
| `erpKpiDashboard` | Home | — (pure JS) |
| `erpRevenueChart` | Home | `chartjs` |
| `pmRentRollChart` | Property Mgmt | `chartjs` |
| `pmKanban` | Property Mgmt | `sortable` |
| `capRateHeatmap` | RE Portfolio | `d3` |
| `loiPipeline` | Commercial RE | `sortable` |
| `camVarianceChart` | Commercial RE | `chartjs` |
| `analyticsConversionFunnel` | Analytics | `chartjs` |
| `apgEvaluate` | APG Bridge | — (fetch API) |
| `landingStats` | Landing Page | — (count-up) |

---

## 5. UX enhancements by design

### Perceived performance
Skeletons paint in the first HTTP response. Users see layout structure immediately — no blank white page while JavaScript evaluates. First Contentful Paint equals server response time.

### Zero build pipeline
New island: 6 lines of JavaScript in a `<script>` tag. No webpack, no `npm install`, no CI rebuild. Edit → browser refresh is the entire dev loop.

### Graceful degradation
- CDN unreachable: skeleton stays (no broken layout, no JS error)
- LLM unavailable: NLP/ML features return deterministic stubs
- APG offline: portal shows disabled state, all ERP functionality unchanged
- No JavaScript: FAB server-rendered tables still work

### Consistent visual language
24 CSS tokens mean every new module — written by any developer at any time — automatically uses the same shadow depth, border radius, and colour palette. The APG portal, the banking dashboard, and the payroll KPI tiles look like they were designed together.

### Security-first
- **SRI hashes** on all 4 CDN scripts
- **XSS validation** on all widget inputs (color regex, icon regex)
- **`tenant_id` on every dashboard query** — cross-tenant data leakage prevented
- **`base_permissions=["can_list","can_show"]`** on all sensitive read-only views
- **CORS locked** to configured origins on banking REST API

### Accessibility
- `aria-busy=true/false` on every loading island
- Skeleton shimmer respects `prefers-reduced-motion`
- All chart canvases have `aria-label` and `role="img"`
- Keyboard navigation preserved (FAB's built-in tab order)

---

## 6. Adding a new island

```python
# views.py — dashboard view
class MyModuleDashboardView(BaseERPView):
    route_base = "/my-module"

    @expose("/")
    @has_access
    def index(self):
        kpi_html = self.kpi_cards([
            {"label": "Total", "value": self._count(MyModel), "icon": "fa-chart-bar"},
        ])
        return render_template("appbuilder/my_module/dashboard.html",
                               kpi_html=kpi_html, appbuilder=self.appbuilder)
```

```html
<!-- templates/appbuilder/my_module/dashboard.html -->
{% extends "appbuilder/erp/base_erp.html" %}
{% block content %}

{{ kpi_html | safe }}

<div data-island="myTrendChart" class="erp-island erp-mb-24">
  <!-- Skeleton -->
  <div class="erp-skeleton" style="height:200px; border-radius:var(--erp-radius)"></div>
</div>

<script>
ERPIslands.register('myTrendChart', ['chartjs'], function (el) {
  fetch('/api/my-module/trend')
    .then(r => r.json())
    .then(data => {
      el.innerHTML = '<canvas></canvas>'
      new Chart(el.querySelector('canvas'), { type: 'line', data: data })
    })
})
</script>
{% endblock %}
```

See `docs/developer/erp_islands.md` for the full island authoring guide.
