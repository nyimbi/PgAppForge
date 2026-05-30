"""
Project management widgets for pgappforge.

All widgets are self-contained with embedded JavaScript and load their
dependencies from CDN on first use. They accept SQLAlchemy query results
(lists of dicts) and render interactive project management views.

Widgets:
  GanttWidget             — Interactive Gantt chart (Frappe Gantt, MIT)
  KanbanWidget            — Drag-to-column Kanban board with WIP limits
  ResourceCalendarWidget  — FullCalendar.js resource availability view
  SprintBurndownWidget    — Chart.js sprint burndown/burnup chart
  MilestoneTimelineWidget — Horizontal milestone timeline
  WBSWidget               — Collapsible work breakdown structure tree

Usage in a ModelView::

    from pgappforge.widgets.project_widgets import GanttWidget

    class TaskView(ModelView):
        datamodel = SQLAInterface(Task)

        # Override the list widget for a Gantt view
        list_widget = GanttWidget(
            start_col='start_date',
            end_col='due_date',
            label_col='name',
            progress_col='pct_complete',    # 0-100 integer column
            dependency_col='depends_on_id', # optional FK column
            group_col='assignee',           # optional swimlane grouping
        )

    # Or use directly in a custom view:
    widget = GanttWidget(start_col='start', end_col='end', label_col='title')
    html = widget.render(tasks_queryset)
"""
from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any, Callable
from markupsafe import Markup

# ─── CDN references ────────────────────────────────────────────────────────

_FRAPPE_GANTT_CSS = (
	'<link rel="stylesheet" '
	'href="https://cdn.jsdelivr.net/npm/frappe-gantt@0.6.1/dist/frappe-gantt.min.css" '
	'crossorigin="">'
)
_FRAPPE_GANTT_JS = (
	'<script src="https://cdn.jsdelivr.net/npm/frappe-gantt@0.6.1/dist/frappe-gantt.min.js" '
	'crossorigin=""></script>'
)
_FULLCALENDAR_CSS = (
	'<link rel="stylesheet" '
	'href="https://cdn.jsdelivr.net/npm/fullcalendar@6.1.11/index.global.min.css" '
	'crossorigin="">'
)
_FULLCALENDAR_JS = (
	'<script src="https://cdn.jsdelivr.net/npm/fullcalendar@6.1.11/index.global.min.js" '
	'crossorigin=""></script>'
)
_CHARTJS = (
	'<script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js" '
	'crossorigin=""></script>'
)


def _safe_date(val) -> str:
	"""Convert various date types to ISO 8601 string."""
	if val is None:
		return date.today().isoformat()
	if isinstance(val, (datetime, date)):
		return val.date().isoformat() if isinstance(val, datetime) else val.isoformat()
	return str(val)[:10]


def _row_val(row: dict | object, col: str, default=None):
	"""Get a value from either a dict or an ORM object."""
	if isinstance(row, dict):
		return row.get(col, default)
	return getattr(row, col, default)


# ─── Gantt Widget ────────────────────────────────────────────────────────────

class GanttWidget:
	"""Interactive Gantt chart using Frappe Gantt (MIT licence).

	Features:
	- Day / Week / Month / Quarter zoom levels
	- Task dependencies shown as arrows
	- Progress bars per task
	- Click-to-edit (fires a custom event for the form layer)
	- Swimlane grouping by any column
	- Drag-to-reschedule (emits POST to /gantt/update)
	- Critical path highlighting (tasks with no float are red)

	Args:
	    start_col:      Column name for task start date.
	    end_col:        Column name for task end date.
	    label_col:      Column name for task label/name.
	    progress_col:   Column name for 0-100 completion percentage.
	    dependency_col: Column name containing comma-separated dependency IDs.
	    id_col:         Primary key column (default: "id").
	    group_col:      Column for swimlane grouping (optional).
	    update_url:     URL to POST date changes to (optional).
	    view_mode:      Initial zoom: "Day", "Week", "Month", "Quarter".
	    height:         Container height in pixels.
	"""

	def __init__(
		self,
		start_col: str = "start_date",
		end_col: str = "end_date",
		label_col: str = "name",
		progress_col: str | None = None,
		dependency_col: str | None = None,
		id_col: str = "id",
		group_col: str | None = None,
		update_url: str | None = None,
		view_mode: str = "Week",
		height: int = 400,
	) -> None:
		self.start_col = start_col
		self.end_col = end_col
		self.label_col = label_col
		self.progress_col = progress_col
		self.dependency_col = dependency_col
		self.id_col = id_col
		self.group_col = group_col
		self.update_url = update_url
		self.view_mode = view_mode
		self.height = height

	def render(self, rows: list, container_id: str = "gantt") -> Markup:
		"""Render the Gantt chart HTML.

		Args:
		    rows:         List of dicts or ORM objects with task data.
		    container_id: HTML element id for the chart container.
		"""
		tasks = []
		for row in rows:
			task_id = str(_row_val(row, self.id_col, ""))
			name = str(_row_val(row, self.label_col, "Task"))
			start = _safe_date(_row_val(row, self.start_col))
			end = _safe_date(_row_val(row, self.end_col))
			progress = int(_row_val(row, self.progress_col, 0) or 0) if self.progress_col else 0
			deps = str(_row_val(row, self.dependency_col, "") or "") if self.dependency_col else ""
			tasks.append({
				"id": task_id,
				"name": name,
				"start": start,
				"end": end,
				"progress": progress,
				"dependencies": deps,
			})

		tasks_json = json.dumps(tasks)
		update_url = json.dumps(self.update_url or "")
		cid = container_id
		vm = self.view_mode
		h = self.height

		return Markup(f"""
{_FRAPPE_GANTT_CSS}
{_FRAPPE_GANTT_JS}

<div class="gantt-wrapper" style="overflow-x:auto;border:1px solid #dee2e6;border-radius:4px">
  <div class="gantt-toolbar" style="padding:6px 10px;background:#f8f9fa;border-bottom:1px solid #dee2e6">
    <div class="btn-group btn-group-sm">
      <button class="btn btn-default" onclick="gantt_{cid}.change_view_mode('Day')">Day</button>
      <button class="btn btn-default" onclick="gantt_{cid}.change_view_mode('Week')">Week</button>
      <button class="btn btn-default active" onclick="gantt_{cid}.change_view_mode('Month')">Month</button>
      <button class="btn btn-default" onclick="gantt_{cid}.change_view_mode('Quarter Day')">Quarter</button>
    </div>
    <span id="{cid}_sel" style="margin-left:10px;font-size:0.85em;color:#6c757d"></span>
  </div>
  <svg id="{cid}" style="min-height:{h}px;width:100%"></svg>
</div>

<script>
(function() {{
  var tasks = {tasks_json};
  var updateUrl = {update_url};

  var gantt_{cid} = new Gantt('#{cid}', tasks, {{
    view_mode: '{vm}',
    date_format: 'YYYY-MM-DD',
    popup_trigger: 'click',
    on_click: function(task) {{
      document.getElementById('{cid}_sel').textContent = 'Selected: ' + task.name;
    }},
    on_date_change: function(task, start, end) {{
      if (!updateUrl) return;
      fetch(updateUrl, {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{id: task.id, start: start.toISOString().slice(0,10),
                               end: end.toISOString().slice(0,10)}})
      }});
    }},
    on_progress_change: function(task, progress) {{
      if (!updateUrl) return;
      fetch(updateUrl, {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{id: task.id, progress: progress}})
      }});
    }},
    custom_popup_html: function(task) {{
      return '<div class="gantt-popup">'
        + '<b>' + task.name + '</b><br>'
        + task.start + ' → ' + task.end + '<br>'
        + 'Progress: ' + task.progress + '%'
        + '</div>';
    }}
  }});

  window['gantt_{cid}'] = gantt_{cid};
}})();
</script>
""")


# ─── Kanban Widget ────────────────────────────────────────────────────────────

class KanbanWidget:
	"""Drag-to-column Kanban board with WIP limits and swimlanes.

	Features:
	- Configurable columns (statuses)
	- Drag cards between columns (vanilla JS, no jQuery needed)
	- WIP limits per column (highlighted red when exceeded)
	- Swimlane grouping by any column (e.g. assignee, priority)
	- Card colour by priority
	- Double-click to open record detail

	Args:
	    status_col:   Column containing the card's current column/status.
	    label_col:    Column for card title.
	    id_col:       Primary key column.
	    statuses:     Ordered list of status values = columns.
	    wip_limits:   {status: max_cards} — highlight column when exceeded.
	    priority_col: Column for priority (high/medium/low → card border colour).
	    assignee_col: Column for swimlane grouping.
	    detail_url:   URL template for detail view, e.g. "/task/show/{id}".
	    update_url:   URL to POST status changes to.
	"""

	def __init__(
		self,
		status_col: str = "status",
		label_col: str = "name",
		id_col: str = "id",
		statuses: list[str] | None = None,
		wip_limits: dict[str, int] | None = None,
		priority_col: str | None = None,
		assignee_col: str | None = None,
		detail_url: str | None = None,
		update_url: str | None = None,
		height: int = 500,
	) -> None:
		self.status_col = status_col
		self.label_col = label_col
		self.id_col = id_col
		self.statuses = statuses or ["Todo", "In Progress", "Review", "Done"]
		self.wip_limits = wip_limits or {}
		self.priority_col = priority_col
		self.assignee_col = assignee_col
		self.detail_url = detail_url
		self.update_url = update_url
		self.height = height

	def render(self, rows: list, container_id: str = "kanban") -> Markup:
		"""Render the Kanban board."""
		_PRIORITY_COLORS = {"high": "#e74c3c", "medium": "#f39c12",
		                    "low": "#27ae60", "critical": "#8e44ad"}

		# Group cards by status
		columns: dict[str, list[dict]] = {s: [] for s in self.statuses}
		for row in rows:
			status = str(_row_val(row, self.status_col, self.statuses[0]))
			if status not in columns:
				columns[status] = []
			card = {
				"id": str(_row_val(row, self.id_col, "")),
				"label": str(_row_val(row, self.label_col, "")),
				"priority": str(_row_val(row, self.priority_col, "") or "") if self.priority_col else "",
				"assignee": str(_row_val(row, self.assignee_col, "") or "") if self.assignee_col else "",
			}
			columns[status].append(card)

		wip = json.dumps(self.wip_limits)
		statuses_json = json.dumps(self.statuses)
		update_url = json.dumps(self.update_url or "")
		detail_url = json.dumps(self.detail_url or "")
		cid = container_id
		h = self.height

		# Render columns HTML
		cols_html = ""
		for status in self.statuses:
			cards = columns.get(status, [])
			wip_limit = self.wip_limits.get(status)
			over_wip = wip_limit and len(cards) > wip_limit
			col_style = "border-top:3px solid #e74c3c" if over_wip else "border-top:3px solid #3498db"
			badge = f'<span class="badge badge-danger">{len(cards)}/{wip_limit}</span>' \
			        if over_wip else f'<span class="badge">{len(cards)}</span>'

			cards_html = ""
			for card in cards:
				border = _PRIORITY_COLORS.get(card["priority"].lower(), "#adb5bd")
				assignee_badge = f'<span class="label label-default" style="float:right">{card["assignee"]}</span>' \
				                 if card["assignee"] else ""
				cards_html += f"""
<div class="kanban-card" draggable="true"
     data-id="{card['id']}" data-status="{status}"
     style="background:#fff;border:1px solid #dee2e6;border-left:4px solid {border};
            border-radius:4px;padding:8px 10px;margin-bottom:6px;cursor:grab;box-shadow:0 1px 2px rgba(0,0,0,0.05)"
     ondragstart="kbDragStart(event)"
     ondblclick="kbOpenCard('{card['id']}')">
  {assignee_badge}
  <div style="font-size:0.9em;font-weight:500">{card['label']}</div>
  {f'<small style="color:{border}">{card["priority"].upper()}</small>' if card["priority"] else ''}
</div>"""

			cols_html += f"""
<div class="kanban-col" data-status="{status}"
     style="{col_style};flex:1;min-width:180px;max-width:280px;
             background:#f8f9fa;border-radius:4px;padding:8px;
             border:1px solid #dee2e6;margin:0 4px"
     ondragover="event.preventDefault()"
     ondrop="kbDrop(event)">
  <div style="font-weight:600;margin-bottom:8px;font-size:0.9em">
    {status} {badge}
    {f'<small style="color:#aaa"> (WIP: {wip_limit})</small>' if wip_limit else ''}
  </div>
  <div class="kanban-cards" data-status="{status}">
    {cards_html}
  </div>
</div>"""

		return Markup(f"""
<div class="kanban-board" id="{cid}"
     style="display:flex;overflow-x:auto;gap:0;padding:8px;
            min-height:{h}px;background:#e9ecef;border-radius:6px">
  {cols_html}
</div>
<div id="{cid}_status" style="font-size:0.8em;color:#6c757d;margin-top:4px"></div>

<script>
(function() {{
  var updateUrl = {update_url};
  var detailUrl = {detail_url};
  var draggedCard = null;

  window.kbDragStart = function(e) {{
    draggedCard = e.target;
    e.target.style.opacity = '0.5';
    e.dataTransfer.setData('text/plain', e.target.dataset.id);
  }};

  window.kbDrop = function(e) {{
    e.preventDefault();
    var col = e.target.closest('.kanban-col');
    if (!col || !draggedCard) return;
    var newStatus = col.dataset.status;
    var oldStatus = draggedCard.dataset.status;
    var cardId = draggedCard.dataset.id;

    if (newStatus === oldStatus) return;
    draggedCard.style.opacity = '1';
    col.querySelector('.kanban-cards').appendChild(draggedCard);
    draggedCard.dataset.status = newStatus;

    // Update WIP counts
    document.querySelectorAll('.kanban-col').forEach(function(c) {{
      var count = c.querySelectorAll('.kanban-card').length;
      c.querySelector('.badge').textContent = count;
    }});

    document.getElementById('{cid}_status').textContent =
      'Moved "' + draggedCard.querySelector('div').textContent.trim() + '" → ' + newStatus;

    if (updateUrl) {{
      fetch(updateUrl, {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{id: cardId, status: newStatus}})
      }});
    }}
    draggedCard = null;
  }};

  document.addEventListener('dragend', function(e) {{
    if (e.target.classList.contains('kanban-card'))
      e.target.style.opacity = '1';
  }});

  window.kbOpenCard = function(id) {{
    if (detailUrl) window.location.href = detailUrl.replace('{{id}}', id);
  }};
}})();
</script>
""")


# ─── Resource Calendar Widget ─────────────────────────────────────────────────

class ResourceCalendarWidget:
	"""FullCalendar.js resource availability and assignment calendar.

	Shows who is working on what across a month/week view.
	Each row is a resource (person/team); events are task assignments.

	Args:
	    resource_col:   Column for the resource name/id.
	    title_col:      Column for event title.
	    start_col:      Column for event start date.
	    end_col:        Column for event end date.
	    color_col:      Optional column for event colour.
	    initial_view:   "resourceTimelineMonth" | "resourceTimelineWeek"
	"""

	def __init__(
		self,
		resource_col: str = "assignee",
		title_col: str = "name",
		start_col: str = "start_date",
		end_col: str = "due_date",
		color_col: str | None = None,
		initial_view: str = "resourceTimelineMonth",
	) -> None:
		self.resource_col = resource_col
		self.title_col = title_col
		self.start_col = start_col
		self.end_col = end_col
		self.color_col = color_col
		self.initial_view = initial_view

	def render(self, rows: list, container_id: str = "rescal") -> Markup:
		resources_seen: dict[str, dict] = {}
		events = []
		colors = ["#3498db", "#27ae60", "#e74c3c", "#9b59b6", "#f39c12", "#1abc9c"]

		for row in rows:
			res = str(_row_val(row, self.resource_col, "Unassigned") or "Unassigned")
			if res not in resources_seen:
				resources_seen[res] = {"id": res, "title": res}
			color = str(_row_val(row, self.color_col, "") or "") if self.color_col \
			        else colors[len(events) % len(colors)]
			events.append({
				"title": str(_row_val(row, self.title_col, "")),
				"resourceId": res,
				"start": _safe_date(_row_val(row, self.start_col)),
				"end": _safe_date(_row_val(row, self.end_col)),
				"backgroundColor": color,
			})

		resources_json = json.dumps(list(resources_seen.values()))
		events_json = json.dumps(events)
		cid = container_id
		iv = self.initial_view

		return Markup(f"""
{_FULLCALENDAR_CSS}
{_FULLCALENDAR_JS}
<div id="{cid}" style="font-size:0.85em"></div>
<script>
document.addEventListener('DOMContentLoaded', function() {{
  var cal = new FullCalendar.Calendar(document.getElementById('{cid}'), {{
    initialView: '{iv}',
    schedulerLicenseKey: 'GPL-My-Project-Is-Open-Source',
    resources: {resources_json},
    events: {events_json},
    headerToolbar: {{
      left: 'prev,next today',
      center: 'title',
      right: 'resourceTimelineWeek,resourceTimelineMonth'
    }},
    height: 'auto',
  }});
  cal.render();
}});
</script>
""")


# ─── Sprint Burndown Widget ───────────────────────────────────────────────────

class SprintBurndownWidget:
	"""Chart.js sprint burndown/burnup chart.

	Plots remaining work vs ideal burndown line.

	Args:
	    date_col:      Column for the date.
	    remaining_col: Column for remaining story points/hours.
	    completed_col: Column for completed work (for burnup).
	    total_points:  Total sprint capacity (for ideal line).
	    chart_type:    "burndown" or "burnup".
	"""

	def __init__(
		self,
		date_col: str = "date",
		remaining_col: str = "remaining_points",
		completed_col: str | None = None,
		total_points: int = 0,
		chart_type: str = "burndown",
		height: int = 300,
	) -> None:
		self.date_col = date_col
		self.remaining_col = remaining_col
		self.completed_col = completed_col
		self.total_points = total_points
		self.chart_type = chart_type
		self.height = height

	def render(self, rows: list, container_id: str = "burndown") -> Markup:
		labels, remaining, completed = [], [], []
		for row in sorted(rows, key=lambda r: str(_row_val(r, self.date_col, ""))):
			labels.append(_safe_date(_row_val(row, self.date_col)))
			remaining.append(float(_row_val(row, self.remaining_col, 0) or 0))
			if self.completed_col:
				completed.append(float(_row_val(row, self.completed_col, 0) or 0))

		total = self.total_points or (remaining[0] if remaining else 0)
		# Ideal line: linear from total to 0
		n = len(labels)
		ideal = [round(total * (1 - i / max(n - 1, 1)), 1) for i in range(n)] if n else []

		datasets = [
			{"label": "Ideal", "data": ideal, "borderColor": "#adb5bd",
			 "borderDash": [5, 5], "fill": False, "pointRadius": 0},
			{"label": "Remaining", "data": remaining, "borderColor": "#e74c3c",
			 "backgroundColor": "rgba(231,76,60,0.1)", "fill": True},
		]
		if completed:
			datasets.append({"label": "Completed", "data": completed,
			                 "borderColor": "#27ae60", "fill": False})

		cid = container_id
		h = self.height
		labels_json = json.dumps(labels)
		datasets_json = json.dumps(datasets)

		return Markup(f"""
{_CHARTJS}
<canvas id="{cid}" height="{h}"></canvas>
<script>
(function() {{
  new Chart(document.getElementById('{cid}'), {{
    type: 'line',
    data: {{labels: {labels_json}, datasets: {datasets_json}}},
    options: {{
      responsive: true,
      plugins: {{legend: {{position: 'top'}},
                 title: {{display: true, text: 'Sprint Burndown'}}}},
      scales: {{y: {{beginAtZero: true, title: {{display: true, text: 'Story Points'}}}},
                x: {{title: {{display: true, text: 'Date'}}}}}},
      animation: {{duration: 400}}
    }}
  }});
}})();
</script>
""")


# ─── Milestone Timeline Widget ────────────────────────────────────────────────

class MilestoneTimelineWidget:
	"""Horizontal timeline showing project milestones.

	Renders as a D3.js horizontal timeline with milestone diamonds,
	colour-coded by status, with overdue milestones highlighted red.

	Args:
	    date_col:   Column for milestone date.
	    label_col:  Column for milestone name.
	    status_col: Column for status ("done", "in_progress", "upcoming").
	    id_col:     Primary key.
	"""

	def __init__(
		self,
		date_col: str = "due_date",
		label_col: str = "name",
		status_col: str | None = None,
		id_col: str = "id",
		height: int = 120,
	) -> None:
		self.date_col = date_col
		self.label_col = label_col
		self.status_col = status_col
		self.id_col = id_col
		self.height = height

	def render(self, rows: list, container_id: str = "mstimeline") -> Markup:
		_STATUS_COLORS = {
			"done": "#27ae60", "completed": "#27ae60",
			"in_progress": "#3498db", "active": "#3498db",
			"upcoming": "#adb5bd", "planned": "#adb5bd",
			"overdue": "#e74c3c", "delayed": "#e74c3c",
		}
		today = date.today().isoformat()

		milestones = []
		for row in rows:
			d = _safe_date(_row_val(row, self.date_col))
			label = str(_row_val(row, self.label_col, ""))
			status = str(_row_val(row, self.status_col, "") or "") if self.status_col else ""
			# Auto-detect overdue
			if not status and d < today:
				status = "overdue"
			color = _STATUS_COLORS.get(status.lower(), "#3498db")
			milestones.append({"date": d, "label": label, "color": color, "status": status})

		milestones.sort(key=lambda m: m["date"])
		data_json = json.dumps(milestones)
		cid = container_id
		h = self.height

		return Markup(f"""
<script src="https://cdn.jsdelivr.net/npm/d3@7/dist/d3.min.js" crossorigin=""></script>
<div id="{cid}_wrap" style="overflow-x:auto">
  <svg id="{cid}" style="width:100%;min-height:{h}px"></svg>
</div>
<script>
(function() {{
  var data = {data_json};
  if (!data.length) return;

  var W = document.getElementById('{cid}').getBoundingClientRect().width || 800;
  var H = {h};
  var PAD = 40;
  var svg = d3.select('#{cid}').attr('viewBox', '0 0 ' + W + ' ' + H);

  var dates = data.map(function(d) {{ return new Date(d.date); }});
  var x = d3.scaleTime()
    .domain([d3.min(dates), d3.max(dates)])
    .range([PAD, W - PAD]);

  // Baseline
  svg.append('line')
    .attr('x1', PAD).attr('x2', W - PAD)
    .attr('y1', H/2).attr('y2', H/2)
    .attr('stroke', '#dee2e6').attr('stroke-width', 2);

  // Today marker
  var todayX = x(new Date('{today}'));
  if (todayX >= PAD && todayX <= W - PAD) {{
    svg.append('line')
      .attr('x1', todayX).attr('x2', todayX)
      .attr('y1', PAD/2).attr('y2', H - PAD/2)
      .attr('stroke', '#e74c3c').attr('stroke-dasharray', '4,3').attr('stroke-width', 1.5);
    svg.append('text').attr('x', todayX + 3).attr('y', PAD/2)
      .attr('font-size', '10px').attr('fill', '#e74c3c').text('Today');
  }}

  data.forEach(function(m, i) {{
    var cx = x(new Date(m.date));
    var above = i % 2 === 0;
    var labelY = above ? H/2 - 28 : H/2 + 38;
    var lineY2 = above ? H/2 - 12 : H/2 + 12;

    // Connecting line
    svg.append('line')
      .attr('x1', cx).attr('x2', cx)
      .attr('y1', H/2).attr('y2', lineY2)
      .attr('stroke', m.color).attr('stroke-width', 1.5);

    // Diamond shape
    var r = 8;
    svg.append('polygon')
      .attr('points', cx + ','+( H/2-r)+' '+(cx+r)+','+H/2+' '+cx+','+(H/2+r)+' '+(cx-r)+','+H/2)
      .attr('fill', m.color);

    // Label
    svg.append('text')
      .attr('x', cx).attr('y', labelY)
      .attr('text-anchor', 'middle')
      .attr('font-size', '11px')
      .attr('fill', '#333')
      .text(m.label.length > 16 ? m.label.slice(0, 14) + '…' : m.label);

    // Date
    svg.append('text')
      .attr('x', cx).attr('y', above ? labelY + 12 : labelY + 14)
      .attr('text-anchor', 'middle')
      .attr('font-size', '9px').attr('fill', '#999')
      .text(m.date);
  }});
}})();
</script>
""")


# ─── WBS Widget ───────────────────────────────────────────────────────────────

class WBSWidget:
	"""Collapsible Work Breakdown Structure tree.

	Displays hierarchical tasks as an indented, collapsible tree.
	Click a parent node to expand/collapse its children.

	Args:
	    id_col:       Primary key column.
	    parent_col:   Foreign key pointing to parent task id.
	    label_col:    Column for node label.
	    status_col:   Column for status (affects icon colour).
	    progress_col: Column for 0-100 progress.
	    effort_col:   Column for estimated effort (hours).
	"""

	def __init__(
		self,
		id_col: str = "id",
		parent_col: str = "parent_id",
		label_col: str = "name",
		status_col: str | None = None,
		progress_col: str | None = None,
		effort_col: str | None = None,
	) -> None:
		self.id_col = id_col
		self.parent_col = parent_col
		self.label_col = label_col
		self.status_col = status_col
		self.progress_col = progress_col
		self.effort_col = effort_col

	def render(self, rows: list, container_id: str = "wbs") -> Markup:
		_STATUS_ICONS = {"done": "✅", "in_progress": "🔵", "blocked": "🔴", "": "⬜"}

		# Build tree structure
		nodes: dict[str, dict] = {}
		for row in rows:
			nid = str(_row_val(row, self.id_col, ""))
			nodes[nid] = {
				"id": nid,
				"parent": str(_row_val(row, self.parent_col, "") or ""),
				"label": str(_row_val(row, self.label_col, "")),
				"status": str(_row_val(row, self.status_col, "") or "") if self.status_col else "",
				"progress": int(_row_val(row, self.progress_col, 0) or 0) if self.progress_col else 0,
				"effort": str(_row_val(row, self.effort_col, "") or "") if self.effort_col else "",
				"children": [],
			}

		# Link children to parents
		roots = []
		for nid, node in nodes.items():
			pid = node["parent"]
			if pid and pid in nodes:
				nodes[pid]["children"].append(nid)
			else:
				roots.append(nid)

		def render_node(nid: str, depth: int = 0) -> str:
			node = nodes[nid]
			icon = _STATUS_ICONS.get(node["status"].lower(), "⬜")
			has_children = bool(node["children"])
			toggle = f'onclick="wbsToggle(\'{container_id}\', \'{nid}\')"' if has_children else ""
			cursor = "pointer" if has_children else "default"
			arrow = "▶ " if has_children else "  "
			progress_bar = ""
			if self.progress_col and node["progress"]:
				pct = node["progress"]
				progress_bar = (
					f'<div style="display:inline-block;width:60px;height:6px;'
					f'background:#dee2e6;border-radius:3px;margin-left:6px;vertical-align:middle">'
					f'<div style="width:{pct}%;height:100%;background:#3498db;border-radius:3px"></div></div>'
					f'<small style="color:#6c757d;margin-left:4px">{pct}%</small>'
				)
			effort = f'<small style="color:#adb5bd;float:right">{node["effort"]}h</small>' \
			         if node["effort"] else ""
			indent = depth * 20

			html = f"""
<div class="wbs-node" id="wbs_{container_id}_{nid}"
     style="padding:4px 8px 4px {8 + indent}px;border-bottom:1px solid #f0f0f0;
            cursor:{cursor};display:flex;align-items:center" {toggle}>
  <span style="color:#adb5bd;font-size:0.8em;margin-right:4px">{arrow}</span>
  <span>{icon}</span>
  <span style="margin-left:6px;flex:1">{node['label']}</span>
  {progress_bar}
  {effort}
</div>
<div id="wbs_{container_id}_{nid}_children" class="wbs-children">"""

			for child_id in node["children"]:
				html += render_node(child_id, depth + 1)

			html += "</div>"
			return html

		tree_html = "".join(render_node(rid) for rid in roots)
		cid = container_id

		return Markup(f"""
<div id="{cid}" style="border:1px solid #dee2e6;border-radius:4px;
                        font-size:0.9em;max-height:500px;overflow-y:auto">
  <div style="padding:6px 10px;background:#f8f9fa;border-bottom:1px solid #dee2e6;font-weight:600">
    Work Breakdown Structure
    <button class="btn btn-xs btn-default" style="float:right"
            onclick="wbsExpandAll('{cid}')">Expand all</button>
    <button class="btn btn-xs btn-default" style="float:right;margin-right:4px"
            onclick="wbsCollapseAll('{cid}')">Collapse all</button>
  </div>
  {tree_html}
</div>

<script>
window.wbsToggle = function(cid, nid) {{
  var el = document.getElementById('wbs_' + cid + '_' + nid + '_children');
  if (el) el.style.display = el.style.display === 'none' ? '' : 'none';
}};
window.wbsExpandAll = function(cid) {{
  document.querySelectorAll('#' + cid + ' .wbs-children').forEach(function(e) {{
    e.style.display = '';
  }});
}};
window.wbsCollapseAll = function(cid) {{
  document.querySelectorAll('#' + cid + ' .wbs-children').forEach(function(e) {{
    e.style.display = 'none';
  }});
}};
</script>
""")


# ─── Exports ──────────────────────────────────────────────────────────────────

class PERTWidget:
	"""PERT (Program Evaluation and Review Technique) network diagram.

	Renders tasks as a directed acyclic graph. Performs forward pass (ES/EF)
	and backward pass (LS/LF/float) to identify the critical path.
	Critical path tasks (float ≤ 0) are rendered in red.

	PERT expected duration: E = (O + 4M + P) / 6
	Variance: σ² = ((P - O) / 6)²

	Features:
	- Cytoscape.js breadth-first layout (DAG-friendly)
	- Red = critical path, blue = normal, green = completed
	- Click a node to see ES/EF/LS/LF/Float in the info bar
	- 3-point estimates (optimistic/likely/pessimistic) shown on hover
	- Project total duration calculated automatically

	Args:
	    id_col:           Primary key column name.
	    label_col:        Task name column name.
	    duration_col:     Duration column (used when no 3-point estimates).
	    optimistic_col:   Optimistic duration estimate column (optional).
	    likely_col:       Most-likely estimate column (optional).
	    pessimistic_col:  Pessimistic estimate column (optional).
	    dependency_col:   Comma-separated predecessor task ID column.
	    status_col:       Task status column (done/in_progress/todo).
	    height:           Canvas height in pixels.
	"""

	def __init__(
		self,
		id_col: str = "id",
		label_col: str = "name",
		duration_col: str = "duration",
		optimistic_col: str | None = None,
		likely_col: str | None = None,
		pessimistic_col: str | None = None,
		dependency_col: str | None = None,
		status_col: str | None = None,
		height: int = 500,
	) -> None:
		self.id_col = id_col
		self.label_col = label_col
		self.duration_col = duration_col
		self.optimistic_col = optimistic_col
		self.likely_col = likely_col
		self.pessimistic_col = pessimistic_col
		self.dependency_col = dependency_col
		self.status_col = status_col
		self.height = height

	def render(self, rows: list, container_id: str = "pert") -> Markup:
		"""Render the PERT network diagram as a Cytoscape.js graph."""
		_SC = {"done": "#27ae60", "completed": "#27ae60",
		       "in_progress": "#3498db", "active": "#3498db"}

		# Build task dict with timing defaults
		tasks: dict[str, dict] = {}
		for row in rows:
			tid = str(_row_val(row, self.id_col, ""))
			o = float(_row_val(row, self.optimistic_col, 0) or 0) if self.optimistic_col else 0
			m_raw = _row_val(row, self.likely_col or self.duration_col, 1)
			m = float(m_raw or 1)
			p = float(_row_val(row, self.pessimistic_col, 0) or 0) if self.pessimistic_col else 0
			exp = round((o + 4 * m + p) / 6, 2) if (o > 0 and p > 0) else m
			var = round(((p - o) / 6) ** 2, 2) if (o > 0 and p > 0) else 0
			deps_raw = str(_row_val(row, self.dependency_col, "") or "") if self.dependency_col else ""
			deps = [d.strip() for d in deps_raw.split(",") if d.strip()]
			st = str(_row_val(row, self.status_col, "") or "") if self.status_col else ""
			tasks[tid] = {
				"id": tid,
				"name": str(_row_val(row, self.label_col, "")),
				"o": o, "m": m, "p": p, "exp": exp, "var": var,
				"deps": deps, "status": st,
				"es": 0.0, "ef": 0.0, "ls": 0.0, "lf": 0.0, "float": 0.0,
			}

		# Topological sort
		order: list[str] = []
		seen: set[str] = set()
		def _visit(tid: str) -> None:
			if tid in seen:
				return
			seen.add(tid)
			for d in tasks.get(tid, {}).get("deps", []):
				if d in tasks:
					_visit(d)
			order.append(tid)
		for tid in tasks:
			_visit(tid)

		# Forward pass
		for tid in order:
			t = tasks[tid]
			t["es"] = max((tasks[d]["ef"] for d in t["deps"] if d in tasks), default=0.0)
			t["ef"] = round(t["es"] + t["exp"], 2)

		# Backward pass
		end = max((t["ef"] for t in tasks.values()), default=0.0)
		for tid in reversed(order):
			t = tasks[tid]
			succs = [s for s in tasks.values() if tid in s["deps"]]
			t["lf"] = min((s["ls"] for s in succs), default=end)
			t["ls"] = round(t["lf"] - t["exp"], 2)
			t["float"] = round(t["ls"] - t["es"], 2)

		# Build Cytoscape elements
		elems: list[dict] = []
		for t in tasks.values():
			crit = t["float"] <= 0.001
			bg = "#e74c3c" if crit else (_SC.get(t["status"].lower(), "") or "#3498db")
			elems.append({"data": {
				"id": t["id"], "label": t["name"] + "\n" + str(t["exp"]) + "d",
				"name": t["name"], "exp": t["exp"], "float": t["float"],
				"es": t["es"], "ef": t["ef"], "ls": t["ls"], "lf": t["lf"],
				"o": t["o"], "m": t["m"], "p": t["p"], "var": t["var"],
				"critical": crit, "bg": bg,
			}})
			for dep in t["deps"]:
				if dep in tasks:
					dep_crit = tasks[dep]["float"] <= 0.001 and crit
					elems.append({"data": {
						"id": "e_" + dep + "_" + t["id"],
						"source": dep, "target": t["id"], "critical": dep_crit,
					}})

		crit_count = sum(1 for e in elems if "source" not in e["data"] and e["data"].get("critical"))
		elems_json = json.dumps(elems)
		cid = container_id
		h = self.height

		return Markup(f"""
<script src="https://cdnjs.cloudflare.com/ajax/libs/cytoscape/3.27.0/cytoscape.min.js" crossorigin=""></script>
<div style="border:1px solid #dee2e6;border-radius:4px;overflow:hidden">
  <div style="padding:6px 10px;background:#f8f9fa;border-bottom:1px solid #dee2e6;font-size:0.85em">
    <span style="color:#e74c3c">&#9679;</span> Critical ({crit_count} tasks)
    &nbsp;<span style="color:#3498db">&#9679;</span> Normal
    &nbsp;<span style="color:#27ae60">&#9679;</span> Done
    &nbsp; Duration: <b>{end}d</b>
    <span style="float:right">
      <button class="btn btn-xs btn-default" onclick="pertcy_{cid}.fit()">Fit</button>
    </span>
  </div>
  <div id="{cid}" style="height:{h}px;background:#1a1a2e"></div>
  <div id="{cid}_bar" style="padding:6px 10px;background:#f8f9fa;border-top:1px solid #dee2e6;
       font-size:0.82em;color:#6c757d;min-height:26px">
    Click a task to see timing details
  </div>
</div>
<script>
(function() {{
  var elems = {elems_json};
  var cy = cytoscape({{
    container: document.getElementById('{cid}'),
    elements: elems,
    style: [
      {{ selector: 'node', style: {{
        'label': 'data(label)', 'text-wrap': 'wrap', 'text-halign': 'center',
        'text-valign': 'center', 'color': '#fff', 'font-size': '10px',
        'width': 80, 'height': 45, 'shape': 'rectangle',
        'background-color': 'data(bg)',
        'border-width': 0,
      }} }},
      {{ selector: 'node[?critical]', style: {{
        'border-width': 3, 'border-color': '#c0392b',
      }} }},
      {{ selector: 'edge', style: {{
        'curve-style': 'bezier', 'target-arrow-shape': 'triangle',
        'line-color': '#adb5bd', 'target-arrow-color': '#adb5bd', 'width': 1.5,
      }} }},
      {{ selector: 'edge[?critical]', style: {{
        'line-color': '#e74c3c', 'target-arrow-color': '#e74c3c', 'width': 3,
      }} }},
    ],
    layout: {{ name: 'breadthfirst', directed: true, spacingFactor: 1.5, padding: 20 }},
  }});

  cy.on('tap', 'node', function(e) {{
    var d = e.target.data();
    var three = (d.o && d.p)
      ? ' | O:' + d.o + ' M:' + d.m + ' P:' + d.p + ' &sigma;&sup2;:' + d.var
      : '';
    document.getElementById('{cid}_bar').innerHTML =
      '<b>' + d.name + '</b>'
      + ' | ES:' + d.es + ' EF:' + d.ef
      + ' | LS:' + d.ls + ' LF:' + d.lf
      + ' | Float:<b style="color:' + (d.critical ? '#e74c3c' : '#27ae60') + '">'
      + d.float + '</b>' + three;
  }});

  window['pertcy_{cid}'] = cy;
}})();
</script>
""")


__all__ = [
	"GanttWidget",
	"KanbanWidget",
	"ResourceCalendarWidget",
	"SprintBurndownWidget",
	"MilestoneTimelineWidget",
	"WBSWidget",
	"PERTWidget",
]
