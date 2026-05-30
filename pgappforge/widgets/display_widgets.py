"""
Display and analytics widgets for pgappforge.

StatCardWidget        — KPI card with mini sparkline + trend arrow
SparklineWidget       — 60px inline trend line for use inside table cells
HeatmapCalendarWidget — GitHub-style contribution heatmap (full year)
EmbeddedChartWidget   — Configurable Chart.js panel (bar/line/pie/doughnut/radar)

All widgets accept rows as list[dict|ORM object] unless noted.
CDN: Chart.js 4 loaded once per page via the shared _cdn constant.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from collections import defaultdict
from markupsafe import Markup

_CHARTJS = (
	'<script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"'
	' crossorigin=""></script>'
)

_PALETTE = [
	"#3498db", "#e74c3c", "#27ae60", "#9b59b6", "#f39c12",
	"#1abc9c", "#e67e22", "#2c3e50", "#16a085", "#8e44ad",
]


def _rv(row, col: str, default=None):
	"""Get value from dict or ORM object."""
	return row.get(col, default) if isinstance(row, dict) else getattr(row, col, default)


def _to_date(val) -> str:
	if val is None:
		return date.today().isoformat()
	if isinstance(val, datetime):
		return val.date().isoformat()
	if isinstance(val, date):
		return val.isoformat()
	return str(val)[:10]


# ─── StatCardWidget ───────────────────────────────────────────────────────────

class StatCardWidget:
	"""KPI summary card with a large number, trend arrow, and mini sparkline.

	Usage in a BaseView::

	    from pgappforge.widgets.display_widgets import StatCardWidget

	    # rows = daily totals for the period (e.g. last 30 days)
	    widget = StatCardWidget(value_col="total_revenue", label="Revenue",
	                            format="currency", trend_col="date",
	                            color="#27ae60", icon="fa-dollar")
	    html = widget.render(rows)

	Args:
	    value_col:   Column containing the KPI value (summed if multiple rows).
	    label:       Display label below the number.
	    format:      "number" | "currency" | "percent" | "integer".
	    trend_col:   Column for the sparkline x-axis (date/time). If given,
	                 renders a mini sparkline of value_col over time.
	    currency:    Currency symbol for "currency" format (default: "$").
	    color:       Accent colour for the icon and sparkline line.
	    icon:        Font Awesome icon class (e.g. "fa-users", "fa-chart-line").
	    compare_col: Optional column for period-over-period comparison value.
	"""

	def __init__(
		self,
		value_col: str = "value",
		label: str = "Metric",
		format: str = "number",
		trend_col: str | None = None,
		currency: str = "$",
		color: str = "#3498db",
		icon: str = "fa-chart-line",
		compare_col: str | None = None,
	) -> None:
		self.value_col = value_col
		self.label = label
		self.format = format
		self.trend_col = trend_col
		self.currency = currency
		self.color = color
		self.icon = icon
		self.compare_col = compare_col

	def _fmt(self, value: float) -> str:
		if self.format == "currency":
			return f"{self.currency}{value:,.2f}"
		if self.format == "percent":
			return f"{value:.1f}%"
		if self.format == "integer":
			return f"{int(value):,}"
		return f"{value:,.2f}" if value != int(value) else f"{int(value):,}"

	def render(self, rows: list, container_id: str = "statcard") -> Markup:
		# Aggregate: if one row → use directly; multiple rows → sum
		values = [float(_rv(r, self.value_col, 0) or 0) for r in rows]
		total = sum(values) if len(values) > 1 else (values[0] if values else 0)

		# Trend sparkline data (time-series)
		sparkline_data: list[float] = []
		if self.trend_col and rows:
			sorted_rows = sorted(rows, key=lambda r: str(_rv(r, self.trend_col, "") or ""))
			sparkline_data = [float(_rv(r, self.value_col, 0) or 0) for r in sorted_rows]

		# Period-over-period trend arrow
		arrow_html = ""
		if self.compare_col and rows:
			compare = float(_rv(rows[-1], self.compare_col, 0) or 0)
			if compare and total != compare:
				pct = (total - compare) / abs(compare) * 100
				up = pct >= 0
				arrow_html = (
					f'<span style="font-size:0.8em;color:{"#27ae60" if up else "#e74c3c"}">'
					f'{"▲" if up else "▼"} {abs(pct):.1f}%</span>'
				)

		cid = container_id
		color = self.color
		spark_json = json.dumps(sparkline_data)
		displayed = self._fmt(total)

		return Markup(f"""
{_CHARTJS}
<div style="background:#fff;border:1px solid #dee2e6;border-radius:6px;
            padding:16px 20px;display:flex;align-items:center;gap:16px;
            box-shadow:0 1px 3px rgba(0,0,0,0.08)">
  <div style="width:48px;height:48px;border-radius:50%;background:{color}22;
              display:flex;align-items:center;justify-content:center;flex-shrink:0">
    <i class="fa {self.icon}" style="font-size:1.4em;color:{color}"></i>
  </div>
  <div style="flex:1;min-width:0">
    <div style="font-size:1.6em;font-weight:700;color:#2c3e50;line-height:1">
      {displayed} {arrow_html}
    </div>
    <div style="font-size:0.82em;color:#6c757d;margin-top:2px">{self.label}</div>
  </div>
  {f'<canvas id="{cid}_spark" width="80" height="40" style="flex-shrink:0"></canvas>' if sparkline_data else ''}
</div>
{"" if not sparkline_data else f"""
<script>
(function() {{
  if (!window.Chart) {{ setTimeout(arguments.callee, 100); return; }}
  new Chart(document.getElementById('{cid}_spark'), {{
    type: 'line',
    data: {{
      labels: {spark_json}.map(function(_,i){{return i;}}),
      datasets: [{{data: {spark_json}, borderColor: '{color}', borderWidth: 2,
                   fill: true, backgroundColor: '{color}22', pointRadius: 0,
                   tension: 0.4}}]
    }},
    options: {{responsive:false,animation:false,
               plugins:{{legend:{{display:false}},tooltip:{{enabled:false}}}},
               scales:{{x:{{display:false}},y:{{display:false}}}}}}
  }});
}})();
</script>"""}
""")


# ─── SparklineWidget ─────────────────────────────────────────────────────────

class SparklineWidget:
	"""Tiny 80×30px trend line for embedding inside list view table cells.

	Does NOT use rows — pass values directly::

	    spark = SparklineWidget(color="#3498db", chart_type="bar")
	    html = spark.render([12, 15, 11, 19, 23, 18, 25])

	Args:
	    color:      Line/bar colour.
	    chart_type: "line" (default) or "bar".
	    width:      Canvas width in pixels.
	    height:     Canvas height in pixels.
	"""

	_id_counter = 0

	def __init__(
		self,
		color: str = "#3498db",
		chart_type: str = "line",
		width: int = 80,
		height: int = 30,
	) -> None:
		self.color = color
		self.chart_type = chart_type
		self.width = width
		self.height = height

	def render(self, values: list[float], container_id: str | None = None) -> Markup:
		SparklineWidget._id_counter += 1
		cid = container_id or f"spark_{SparklineWidget._id_counter}"
		data_json = json.dumps([float(v or 0) for v in values])
		color = self.color
		ct = self.chart_type
		w, h = self.width, self.height

		return Markup(f"""
{_CHARTJS}
<canvas id="{cid}" width="{w}" height="{h}" style="vertical-align:middle"></canvas>
<script>
(function() {{
  if (!window.Chart) {{ setTimeout(arguments.callee, 100); return; }}
  new Chart(document.getElementById('{cid}'), {{
    type: '{ct}',
    data: {{
      labels: {data_json}.map(function(_,i){{return i;}}),
      datasets: [{{data: {data_json}, borderColor: '{color}', borderWidth: 1.5,
                   backgroundColor: '{ct}' === 'bar' ? '{color}88' : '{color}22',
                   pointRadius: 0, fill: true, tension: 0.3}}]
    }},
    options: {{responsive:false,animation:false,
               plugins:{{legend:{{display:false}},tooltip:{{enabled:false}}}},
               scales:{{x:{{display:false}},y:{{display:false}}}}}}
  }});
}})();
</script>""")


# ─── HeatmapCalendarWidget ───────────────────────────────────────────────────

class HeatmapCalendarWidget:
	"""GitHub contribution-style calendar heatmap — full year view.

	Renders a 52-column × 7-row grid where each cell represents one day.
	Cell intensity reflects the activity value for that day.

	Args:
	    date_col:       Column containing ISO date strings or date objects.
	    value_col:      Column containing the numeric activity value.
	    year:           Year to display (default: current year).
	    color_scheme:   "green" | "blue" | "red" | "purple" | "orange".
	    tooltip:        Show date + value on hover.
	    cell_size:      Square size in pixels (default 11).
	"""

	_SCHEMES = {
		"green":  ["#ebedf0", "#9be9a8", "#40c463", "#30a14e", "#216e39"],
		"blue":   ["#ebedf0", "#a8d8f0", "#4ca3d8", "#1a7abf", "#0d4d8a"],
		"red":    ["#ebedf0", "#f0a8a8", "#d84c4c", "#bf1a1a", "#8a0d0d"],
		"purple": ["#ebedf0", "#d2b4f0", "#9b59b6", "#7d3c98", "#512e6b"],
		"orange": ["#ebedf0", "#f0d0a8", "#e67e22", "#ca6f1e", "#935116"],
	}

	def __init__(
		self,
		date_col: str = "date",
		value_col: str = "count",
		year: int | None = None,
		color_scheme: str = "green",
		tooltip: bool = True,
		cell_size: int = 11,
	) -> None:
		self.date_col = date_col
		self.value_col = value_col
		self.year = year or date.today().year
		self.color_scheme = color_scheme
		self.tooltip = tooltip
		self.cell_size = cell_size

	def render(self, rows: list, container_id: str = "heatmap") -> Markup:
		colors = self._SCHEMES.get(self.color_scheme, self._SCHEMES["green"])

		# Build date→value dict for the year
		daily: dict[str, float] = {}
		for row in rows:
			d = _to_date(_rv(row, self.date_col))
			if d[:4] == str(self.year):
				daily[d] = float(_rv(row, self.value_col, 0) or 0)

		max_val = max(daily.values(), default=1)

		def _color(val: float) -> str:
			if not val:
				return colors[0]
			idx = min(4, max(1, int(val / max_val * 4 + 0.5)))
			return colors[idx]

		# Generate the 52×7 grid
		year_start = date(self.year, 1, 1)
		# Pad to Monday start
		start_dow = year_start.weekday()  # 0=Mon
		year_end = date(self.year, 12, 31)

		cells_by_week: list[list[tuple[str, float]]] = []
		current: list[tuple[str, float]] = []

		# Padding for days before Jan 1
		for _ in range(start_dow):
			current.append(("", 0))

		cur = year_start
		while cur <= year_end:
			iso = cur.isoformat()
			current.append((iso, daily.get(iso, 0)))
			if len(current) == 7:
				cells_by_week.append(current)
				current = []
			cur += timedelta(days=1)

		if current:
			while len(current) < 7:
				current.append(("", 0))
			cells_by_week.append(current)

		cs = self.cell_size
		gap = 2
		months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
		          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

		# Build SVG
		svg_w = (cs + gap) * len(cells_by_week) + 30
		svg_h = (cs + gap) * 7 + 30

		rects = []
		for wi, week in enumerate(cells_by_week):
			for di, (iso, val) in enumerate(week):
				if not iso:
					continue
				x = wi * (cs + gap) + 30
				y = di * (cs + gap) + 20
				c = _color(val)
				tip = f'data-tip="{iso}: {int(val)}"' if self.tooltip else ""
				rects.append(
					f'<rect x="{x}" y="{y}" width="{cs}" height="{cs}" rx="2" '
					f'fill="{c}" {tip} style="cursor:default"/>'
				)

		# Month labels
		month_labels = []
		month_seen = set()
		for wi, week in enumerate(cells_by_week):
			for iso, _ in week:
				if iso:
					m = int(iso[5:7])
					if m not in month_seen:
						month_seen.add(m)
						x = wi * (cs + gap) + 30
						month_labels.append(
							f'<text x="{x}" y="15" font-size="9" fill="#6c757d">{months[m-1]}</text>'
						)

		day_labels = []
		for di, lbl in enumerate(["Mon","","Wed","","Fri","",""]):
			if lbl:
				y = di * (cs + gap) + 20 + cs - 1
				day_labels.append(f'<text x="0" y="{y}" font-size="9" fill="#6c757d">{lbl}</text>')

		tip_script = """
<script>
document.querySelectorAll('[data-tip]').forEach(function(el) {
  el.addEventListener('mouseenter', function(e) {
    var tip = document.getElementById('hm_tip');
    if (!tip) { tip = document.createElement('div'); tip.id = 'hm_tip';
      tip.style.cssText = 'position:fixed;background:rgba(0,0,0,0.8);color:#fff;padding:3px 7px;border-radius:3px;font-size:11px;pointer-events:none;z-index:9999';
      document.body.appendChild(tip); }
    tip.textContent = el.dataset.tip;
    tip.style.display = 'block';
  });
  el.addEventListener('mousemove', function(e) {
    var tip = document.getElementById('hm_tip');
    if (tip) { tip.style.left = (e.clientX+12)+'px'; tip.style.top = (e.clientY-20)+'px'; }
  });
  el.addEventListener('mouseleave', function() {
    var tip = document.getElementById('hm_tip'); if (tip) tip.style.display='none';
  });
});
</script>""" if self.tooltip else ""

		legend_rects = "".join(
			f'<rect x="{i*16}" y="0" width="{cs}" height="{cs}" rx="2" fill="{c}"/>'
			for i, c in enumerate(colors)
		)

		return Markup(f"""
<div id="{container_id}" style="overflow-x:auto">
  <svg width="{svg_w}" height="{svg_h}" xmlns="http://www.w3.org/2000/svg">
    {"".join(month_labels)}
    {"".join(day_labels)}
    {"".join(rects)}
    <g transform="translate(30, {svg_h - 14})">
      <text x="-2" y="{cs}" font-size="9" fill="#6c757d">Less</text>
      <g transform="translate(25,0)">{legend_rects}</g>
      <text x="{25 + len(colors)*16 + 4}" y="{cs}" font-size="9" fill="#6c757d">More</text>
    </g>
  </svg>
</div>
{tip_script}""")


# ─── EmbeddedChartWidget ──────────────────────────────────────────────────────

class EmbeddedChartWidget:
	"""Configurable Chart.js panel — use anywhere without a custom view.

	Auto-aggregates: when multiple rows have the same x value, sums y values.

	Args:
	    chart_type:    "bar" | "line" | "pie" | "doughnut" | "radar".
	    x_col:         Column for the x-axis (categories / labels).
	    y_col:         Column for the y-axis (numeric values).
	    group_col:     Column for series grouping (produces multi-dataset chart).
	    title:         Chart title displayed above.
	    x_label:       X-axis label.
	    y_label:       Y-axis label.
	    color_scheme:  "palette" (default) | "single" (all same colour).
	    height:        Container height in pixels.
	    legend:        Show legend (default True for grouped charts).
	"""

	def __init__(
		self,
		chart_type: str = "bar",
		x_col: str = "label",
		y_col: str = "value",
		group_col: str | None = None,
		title: str = "",
		x_label: str = "",
		y_label: str = "",
		color_scheme: str = "palette",
		height: int = 300,
		legend: bool | None = None,
	) -> None:
		self.chart_type = chart_type
		self.x_col = x_col
		self.y_col = y_col
		self.group_col = group_col
		self.title = title
		self.x_label = x_label
		self.y_label = y_label
		self.color_scheme = color_scheme
		self.height = height
		self.legend = legend

	def render(self, rows: list, container_id: str = "echart") -> Markup:
		if not rows:
			return Markup(f'<div class="text-muted" style="padding:20px">No data</div>')

		is_pie = self.chart_type in ("pie", "doughnut")

		if self.group_col:
			# Multi-dataset: group by group_col, x_col gives labels
			groups: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
			labels_order: list[str] = []
			for row in rows:
				x = str(_rv(row, self.x_col, "") or "")
				g = str(_rv(row, self.group_col, "") or "Other")
				v = float(_rv(row, self.y_col, 0) or 0)
				if x not in labels_order:
					labels_order.append(x)
				groups[g][x] += v

			datasets = []
			for i, (g, vals) in enumerate(groups.items()):
				color = _PALETTE[i % len(_PALETTE)]
				datasets.append({
					"label": g,
					"data": [vals.get(x, 0) for x in labels_order],
					"backgroundColor": color + "cc",
					"borderColor": color,
					"borderWidth": 1,
				})
			labels = labels_order
		else:
			# Single dataset: aggregate by x_col
			agg: dict[str, float] = defaultdict(float)
			order: list[str] = []
			for row in rows:
				x = str(_rv(row, self.x_col, "") or "")
				v = float(_rv(row, self.y_col, 0) or 0)
				if x not in order:
					order.append(x)
				agg[x] += v

			labels = order
			colors = [_PALETTE[i % len(_PALETTE)] for i in range(len(labels))]
			datasets = [{
				"label": self.y_col,
				"data": [agg[x] for x in labels],
				"backgroundColor": [c + "cc" for c in colors] if is_pie else _PALETTE[0] + "cc",
				"borderColor": colors if is_pie else _PALETTE[0],
				"borderWidth": 1,
			}]

		show_legend = self.legend if self.legend is not None else (bool(self.group_col) or is_pie)
		cid = container_id
		h = self.height
		ct = self.chart_type
		labels_json = json.dumps(labels)
		datasets_json = json.dumps(datasets)
		title_cfg = json.dumps({"display": bool(self.title), "text": self.title})

		scales_cfg = "{}" if is_pie or ct == "radar" else json.dumps({
			"x": {"title": {"display": bool(self.x_label), "text": self.x_label}},
			"y": {"title": {"display": bool(self.y_label), "text": self.y_label},
			      "beginAtZero": True},
		})

		return Markup(f"""
{_CHARTJS}
<canvas id="{cid}" height="{h}"></canvas>
<script>
(function() {{
  if (!window.Chart) {{ setTimeout(arguments.callee, 100); return; }}
  new Chart(document.getElementById('{cid}'), {{
    type: '{ct}',
    data: {{labels: {labels_json}, datasets: {datasets_json}}},
    options: {{
      responsive: true,
      plugins: {{
        legend: {{display: {'true' if show_legend else 'false'}}},
        title: {title_cfg}
      }},
      scales: {scales_cfg},
      animation: {{duration: 300}}
    }}
  }});
}})();
</script>""")


__all__ = [
	"StatCardWidget",
	"SparklineWidget",
	"HeatmapCalendarWidget",
	"EmbeddedChartWidget",
]
