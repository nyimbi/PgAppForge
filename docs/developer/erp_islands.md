# ERP Islands — Developer Guide

Islands are the interactivity primitive for ERP module pages. They let you ship a
server-rendered skeleton that paints instantly, then progressively enhance the element
with Chart.js, Alpine.js, or any other CDN library — all without a build step.

---

## What is an Island?

An island is an independently-hydrated UI component. The server renders a placeholder
element (the skeleton), and the island runtime picks it up after the DOM is ready,
loads any required CDN libraries, then calls your factory function to wire up the
live component.

Key properties:

- **Zero blocking JS on initial paint.** CDN scripts are only loaded when the element
  is in the document.
- **Isolated.** Each island owns its DOM subtree. A crash in one island does not affect
  others.
- **Idempotent mounting.** `mountAll()` is safe to call multiple times; islands that
  are already mounted are skipped via the `data-island-mounted` guard.

---

## The `data-island` attribute

Any HTML element carrying a `data-island="<name>"` attribute becomes a mountable
island target. `ERPIslands.mountAll()` discovers all such elements on
`DOMContentLoaded` and calls `mount(el)` for each one.

```html
<!-- Server renders this skeleton immediately -->
<div data-island="kpi-sparkline"
     data-endpoint="/api/finance/revenue/sparkline"
     style="min-height:80px">
  <!-- optional skeleton content shown while JS loads -->
  <div class="skeleton-pulse" aria-hidden="true"></div>
</div>
```

Rules:

- `data-island` value must exactly match the name passed to `ERPIslands.register()`.
- Any `data-*` attributes on the element are accessible inside the factory via
  `el.dataset`.
- Elements with `aria-busy="true"` during loading; `aria-busy` is removed (whether
  mount succeeds or fails) in the `finally` handler.

---

## `ERPIslands.register(name, libs, fn)`

Registers an island factory.

```js
ERPIslands.register(name, libs, fn)
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `name` | `string` | Island identifier. Must match `data-island` on the target element. |
| `libs` | `string[]` | Ordered list of CDN library keys to load before invoking `fn`. Valid keys: `"chartjs"`, `"alpine"`, `"sortable"`, `"d3"`. Empty array `[]` is valid if no external libs are needed. |
| `fn` | `Function(el: HTMLElement): void` | Factory function called once all libs are resolved. Receives the island element; libs are available on the global scope (e.g. `window.Chart`, `window.Alpine`). Must be synchronous or return nothing — the runtime does not await a returned promise. |

Registration is typically done in a page-specific `<script>` block or a module loaded
after `erp_islands.js`:

```js
ERPIslands.register('kpi-sparkline', ['chartjs'], function (el) {
  var endpoint = el.dataset.endpoint;
  ERPIslands.fetchJSON(endpoint).then(function (data) {
    var canvas = document.createElement('canvas');
    el.innerHTML = '';
    el.appendChild(canvas);
    new Chart(canvas, {
      type: 'line',
      data: { labels: data.labels, datasets: [{ data: data.values }] },
      options: { plugins: { legend: { display: false } }, scales: { x: { display: false }, y: { display: false } } }
    });
  });
});
```

Guard against double-registration in SPAs or pages that reload partials:

```js
if (!ERPIslands._registry || !ERPIslands._registry['kpi-sparkline']) {
  ERPIslands.register('kpi-sparkline', ['chartjs'], fn);
}
```

---

## Island lifecycle

```
Server response
  └─ HTML with <div data-island="name" ...> skeleton </div>
        │
        ▼
Browser paints skeleton (zero JS required)
        │
        ▼
DOMContentLoaded fires
        │
        ▼
ERPIslands.mountAll() called automatically
        │
        ├─ el.dataset.islandMounted === 'true'? → skip (already mounted)
        │
        ▼
el.setAttribute('aria-busy', 'true')
        │
        ▼
loadLib(lib) for each entry in libs[]
  (deduped — same lib requested by N islands loads only one <script> tag)
        │
  ┌─────┴─────┐
  │  success  │  failure / timeout (10 s)
  │           │
  ▼           ▼
fn(el)    _renderError(el, err)
  │           │
  └─────┬─────┘
        ▼
el.removeAttribute('aria-busy')
```

The `finally` block guarantees `aria-busy` is always cleared, so screen readers never
see a perpetually-busy element.

---

## Error handling

If `fn(el)` throws synchronously, or if any library fails to load (network error,
integrity mismatch, 10-second timeout), `_renderError(el, err)` is called:

```js
function _renderError(el, err) {
  el.innerHTML =
    '<div style="padding:12px;color:#e02424;...">
     <strong>Island failed to mount:</strong> ' + _esc(err.message) + '
     </div>';
}
```

- Error message is HTML-escaped via `_esc()` — no XSS risk from server-provided
  error strings.
- The error is also logged to the browser console via `console.error`.
- Container dimensions are preserved; the error card replaces the skeleton in-place.

If your factory performs async work (fetch, animation frame) and that fails *after*
the mount completes, you are responsible for rendering your own error state inside
the island container.

---

## Islands vs. server-side widgets

Use this table to decide whether to reach for an island or a server-side widget
(`StatCardWidget`, `EmbeddedChartWidget`, etc.).

| Criterion | Server-side widget | Island |
|-----------|-------------------|--------|
| Interactivity | None — static HTML | Required (clicks, live updates, drag-drop) |
| Data size | Small (rendered inline) | Large or streamed (fetched after paint) |
| JS budget | Zero — no client JS | Acceptable — user interaction expected |
| CDN dependency | None | Chart.js / Alpine / D3 / Sortable |
| Render model | SSR — data available at request time | CSR — data fetched asynchronously |
| SEO / crawler visibility | Full (HTML in response) | Skeleton only (content added by JS) |
| Fallback for no-JS users | Works fully | Shows skeleton only |
| Caching | Page-level (Flask cache) | Island-level (HTTP cache on API endpoint) |

**Rule of thumb:** start with a server-side widget. Upgrade to an island only when
you need post-paint interactivity or the data set is too large to embed inline.

---

## Worked example: a KPI trend sparkline island

This example registers an island named `revenue-sparkline` that renders a Chart.js
line chart from a JSON endpoint.

### 1. Server-side: emit the island placeholder

In your ERP view template (`templates/my_module/dashboard.html`):

```html
{% extends "appbuilder/base.html" %}
{% block content %}
<div data-island="revenue-sparkline"
     data-endpoint="{{ url_for('MyModule.revenue_sparkline_api') }}"
     style="min-height:90px;background:#f9fafb;border-radius:8px">
  <!-- Skeleton visible before JS loads -->
  <div style="height:90px;background:linear-gradient(90deg,#f0f0f0 25%,#e0e0e0 50%,#f0f0f0 75%);
              background-size:200% 100%;animation:shimmer 1.2s infinite"></div>
</div>
{% endblock %}

{% block tail_js %}
{{ super() }}
<script src="{{ url_for('static', filename='appbuilder/js/erp_islands.js') }}"></script>
<script>
ERPIslands.register('revenue-sparkline', ['chartjs'], function (el) {
  var endpoint = el.dataset.endpoint;

  ERPIslands.fetchJSON(endpoint).then(function (payload) {
    // payload: { labels: ["Jan","Feb",...], values: [120000, 135000, ...] }
    el.innerHTML = '<canvas></canvas>';
    var canvas = el.querySelector('canvas');
    new Chart(canvas, {
      type: 'line',
      data: {
        labels: payload.labels,
        datasets: [{
          data:            payload.values,
          borderColor:     '#1a56db',
          backgroundColor: 'rgba(26,86,219,0.08)',
          borderWidth:     2,
          pointRadius:     0,
          tension:         0.4,
          fill:            true
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false }, tooltip: { mode: 'index' } },
        scales:  { x: { display: false }, y: { display: false } }
      }
    });
  }).catch(function (err) {
    el.innerHTML = '<p style="color:#e02424;font-size:12px">Failed to load sparkline</p>';
    console.error('revenue-sparkline:', err);
  });
});
</script>
{% endblock %}
```

### 2. Server-side: API endpoint

```python
from flask import jsonify
from pgappforge.plugins.erp.base_view import BaseERPView

class MyModule(BaseERPView):
    @expose('/revenue/sparkline')
    @has_access
    def revenue_sparkline_api(self):
        rows = self._session().execute(
            "SELECT to_char(month,'Mon') AS label, total FROM revenue_monthly ORDER BY month DESC LIMIT 12"
        ).fetchall()
        rows = list(reversed(rows))
        return jsonify(labels=[r.label for r in rows], values=[r.total for r in rows])
```

---

## Adding a new CDN library

Open `/pgappforge/static/appbuilder/js/erp_islands.js` and add an entry to the
`CDN` object near the top of the IIFE:

```js
var CDN = {
  alpine:   { url: '...', integrity: 'sha384-...', crossOrigin: 'anonymous' },
  chartjs:  { url: '...', integrity: 'sha384-...', crossOrigin: 'anonymous' },
  sortable: { url: '...', integrity: 'sha384-...', crossOrigin: 'anonymous' },
  d3:       { url: '...', integrity: 'sha384-...', crossOrigin: 'anonymous' },
  // NEW:
  flatpickr: {
    url:         'https://cdn.jsdelivr.net/npm/flatpickr@4.6.13/dist/flatpickr.min.js',
    integrity:   'sha384-<YOUR_COMPUTED_HASH>',
    crossOrigin: 'anonymous'
  }
};
```

Steps:

1. Pin an exact version in the URL (never `@latest`).
2. Compute the SRI hash (see next section) and place it in `integrity`.
3. Add the library name to the `libs` array in any island that needs it.
4. If the library exposes a stylesheet, add a parallel `<link rel="stylesheet">`
   entry — the current runtime only handles JS. Open an issue if CSS lazy-loading
   is needed.

---

## CDN integrity hashes

Every CDN entry **must** carry a `sha384` SRI hash. Loading unsigned third-party
scripts in production is a supply-chain attack vector.

### Computing the hash

```bash
curl -sL "https://cdn.jsdelivr.net/npm/flatpickr@4.6.13/dist/flatpickr.min.js" \
  | openssl dgst -sha384 -binary \
  | openssl base64 -A \
  | sed 's/^/sha384-/'
```

Or use the official SRI hash generator at <https://www.srihash.org/>.

### Verification checklist

- [ ] Hash computed from the exact byte stream at the pinned URL.
- [ ] `integrity` attribute value begins with `sha384-`.
- [ ] `crossOrigin` is `"anonymous"` (required for SRI checking by the browser).
- [ ] Hash re-verified when bumping the library version.
- [ ] Never set `integrity: null` or omit the field — `loadLib` does not enforce this
      at runtime but browsers will skip the integrity check silently.

### Why sha384?

sha256 hashes are accepted by browsers but sha384 provides a larger security margin
at negligible performance cost. sha512 is also valid but produces longer strings with
no practical benefit for this use case.
