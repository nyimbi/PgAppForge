"""
action_widgets.py — BPM and list-action widgets for PgAppForge.

Widgets
-------
ApprovalButtonWidget  BPM-integrated approve / reject / request-changes panel.
BulkActionWidget      Multi-select toolbar injected into ModelView list pages.
DiffViewerWidget      Side-by-side line diff between two text/JSON field values.
TimelineWidget        Bootstrap 3 vertical timeline from an audit-event list.

All widgets
- Use markupsafe.Markup exclusively (never flask.Markup).
- Are tab-indented throughout.
- Import only from pgappforge, never from pgappforge directly.
- Require no extra JS CDN beyond what FAB already loads (Bootstrap 3, jQuery,
  Font Awesome).  DiffViewerWidget does all diff work in pure Python.
"""

from __future__ import annotations

import difflib
import html
import json
from typing import Any

from markupsafe import Markup

__all__ = [
	"ApprovalButtonWidget",
	"BulkActionWidget",
	"DiffViewerWidget",
	"TimelineWidget",
]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _esc(text: Any) -> str:
	"""HTML-escape a value, coercing to str first."""
	return html.escape(str(text) if text is not None else "")


def _jsbool(v: bool) -> str:
	return "true" if v else "false"


# ---------------------------------------------------------------------------
# 1. ApprovalButtonWidget
# ---------------------------------------------------------------------------

class ApprovalButtonWidget:
	"""
	BPM-integrated approve / reject / request-changes panel.

	Renders as a compact action bar that can be dropped into any show/edit
	template.  Each button opens an inline Bootstrap modal so the user can
	attach a comment before confirming.

	Args:
		instance_id_col  Column name on the row object that holds the BPM
		                 process-instance ID (e.g. ``"process_instance_id"``).
		advance_url      URL that accepts POST ``{instance_id, comment}`` to
		                 advance (approve) the instance.
		reject_url       URL that accepts POST ``{instance_id, comment}`` to
		                 reject the instance.
		require_comment  When True every modal textarea is ``required`` so the
		                 browser blocks submission without a comment.
		step_col         Optional column name on the row object holding the
		                 current step name shown as a status badge.
		                 Defaults to ``"current_step"``.
	"""

	def __init__(
		self,
		instance_id_col: str,
		advance_url: str,
		reject_url: str,
		require_comment: bool = True,
		step_col: str = "current_step",
	) -> None:
		self.instance_id_col = instance_id_col
		self.advance_url = advance_url
		self.reject_url = reject_url
		self.require_comment = require_comment
		self.step_col = step_col

	# ------------------------------------------------------------------
	def render(self, obj: Any) -> Markup:
		"""
		Return HTML for the action bar bound to *obj*.

		Args:
			obj  SQLAlchemy model instance (or any object with the configured
			     column attributes).

		Returns:
			Markup  Safe HTML string ready for ``{{ widget.render(record) | safe }}``.
		"""
		instance_id = _esc(getattr(obj, self.instance_id_col, ""))
		step_name = _esc(getattr(obj, self.step_col, "—"))
		adv_url = _esc(self.advance_url)
		rej_url = _esc(self.reject_url)
		req = "required" if self.require_comment else ""
		uid = f"apw-{instance_id}"  # unique prefix for modal ids on the page

		html_out = f"""
<div class="pgf-approval-widget" style="margin:8px 0;">
  <!-- Step badge -->
  <span class="label label-info" style="font-size:0.9em;margin-right:8px;">
    <i class="fa fa-tasks"></i>&nbsp;{step_name}
  </span>

  <!-- Approve button -->
  <button type="button" class="btn btn-success btn-sm"
          data-toggle="modal" data-target="#{uid}-approve">
    <i class="fa fa-check"></i> Approve
  </button>

  <!-- Reject button -->
  <button type="button" class="btn btn-danger btn-sm"
          data-toggle="modal" data-target="#{uid}-reject">
    <i class="fa fa-times"></i> Reject
  </button>

  <!-- Request changes button -->
  <button type="button" class="btn btn-warning btn-sm"
          data-toggle="modal" data-target="#{uid}-changes">
    <i class="fa fa-pencil"></i> Request Changes
  </button>
</div>

<!-- ── Approve modal ── -->
{_approval_modal(uid, "approve", "Approve", "success", instance_id, adv_url, req,
                 "Approve this step?", "Approval comment")}

<!-- ── Reject modal ── -->
{_approval_modal(uid, "reject", "Reject", "danger", instance_id, rej_url, req,
                 "Reject this step?", "Rejection reason")}

<!-- ── Request-changes modal — also posts to reject_url with action=changes ── -->
{_changes_modal(uid, instance_id, rej_url, req)}
"""
		return Markup(html_out)

	# keep __call__ as alias so the widget can be invoked directly in templates
	def __call__(self, obj: Any, **_kwargs: Any) -> Markup:
		return self.render(obj)


def _approval_modal(
	uid: str,
	key: str,
	label: str,
	style: str,
	instance_id: str,
	post_url: str,
	required_attr: str,
	title: str,
	placeholder: str,
) -> str:
	textarea_id = f"{uid}-{key}-comment"
	form_id = f"{uid}-{key}-form"
	return f"""
<div class="modal fade" id="{uid}-{key}" tabindex="-1" role="dialog"
     aria-labelledby="{uid}-{key}-title">
  <div class="modal-dialog" role="document">
    <div class="modal-content">
      <div class="modal-header">
        <button type="button" class="close" data-dismiss="modal">
          <span aria-hidden="true">&times;</span>
        </button>
        <h4 class="modal-title" id="{uid}-{key}-title">{title}</h4>
      </div>
      <form id="{form_id}" method="POST" action="{post_url}">
        <div class="modal-body">
          <input type="hidden" name="instance_id" value="{instance_id}" />
          <div class="form-group">
            <label for="{textarea_id}">Comment</label>
            <textarea id="{textarea_id}" name="comment" class="form-control"
                      rows="4" placeholder="{placeholder}"
                      {required_attr}></textarea>
          </div>
        </div>
        <div class="modal-footer">
          <button type="button" class="btn btn-default"
                  data-dismiss="modal">Cancel</button>
          <button type="submit" class="btn btn-{style}">
            <i class="fa fa-check"></i> {label}
          </button>
        </div>
      </form>
    </div>
  </div>
</div>"""


def _changes_modal(uid: str, instance_id: str, rej_url: str, required_attr: str) -> str:
	textarea_id = f"{uid}-changes-comment"
	return f"""
<div class="modal fade" id="{uid}-changes" tabindex="-1" role="dialog"
     aria-labelledby="{uid}-changes-title">
  <div class="modal-dialog" role="document">
    <div class="modal-content">
      <div class="modal-header">
        <button type="button" class="close" data-dismiss="modal">
          <span aria-hidden="true">&times;</span>
        </button>
        <h4 class="modal-title" id="{uid}-changes-title">Request Changes</h4>
      </div>
      <form method="POST" action="{rej_url}">
        <div class="modal-body">
          <input type="hidden" name="instance_id" value="{instance_id}" />
          <input type="hidden" name="action" value="changes" />
          <div class="form-group">
            <label for="{textarea_id}">What needs to change?</label>
            <textarea id="{textarea_id}" name="comment" class="form-control"
                      rows="4" placeholder="Describe what needs to change…"
                      {required_attr}></textarea>
          </div>
        </div>
        <div class="modal-footer">
          <button type="button" class="btn btn-default"
                  data-dismiss="modal">Cancel</button>
          <button type="submit" class="btn btn-warning">
            <i class="fa fa-pencil"></i> Request Changes
          </button>
        </div>
      </form>
    </div>
  </div>
</div>"""


# ---------------------------------------------------------------------------
# 2. BulkActionWidget
# ---------------------------------------------------------------------------

class BulkActionWidget:
	"""
	Multi-select toolbar for ModelView list pages.

	This is a **JS-only** widget: it injects a ``<script>`` block that
	enhances the existing FAB list table at runtime—no server-side template
	changes required.  Drop ``{{ bulk_widget.render(actions) | safe }}``
	anywhere inside the list template (or in a ``{% block tail_js %}`` block).

	Action dict schema
	------------------
	Each entry in *actions* accepts:

	- ``label``    (str, required)  Button label.
	- ``url``      (str, required)  Endpoint that receives
	               ``POST application/json`` body ``{"ids": [...]}``.
	- ``method``   (str, default ``"POST"``)  HTTP method.
	- ``confirm``  (str | None)  If set, ``window.confirm()`` text shown before
	               the request fires.
	- ``icon``     (str | None)  Font Awesome class e.g. ``"fa-trash"``.

	Example::

		bulk = BulkActionWidget()
		html = bulk.render([
		    {"label": "Export CSV", "url": "/export/csv", "icon": "fa-download"},
		    {"label": "Delete",     "url": "/bulk-delete",
		     "confirm": "Delete selected records?", "icon": "fa-trash"},
		])
	"""

	# CSS embedded once per render (idempotent via class guard on the element).
	_CSS = """
.pgf-bulk-toolbar {
  position: fixed;
  bottom: -60px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 1050;
  background: #fff;
  border: 1px solid #ccc;
  border-radius: 4px;
  box-shadow: 0 2px 8px rgba(0,0,0,.25);
  padding: 8px 16px;
  display: flex;
  align-items: center;
  gap: 8px;
  transition: bottom .25s ease;
  white-space: nowrap;
}
.pgf-bulk-toolbar.pgf-bulk-visible { bottom: 24px; }
.pgf-bulk-toolbar .pgf-bulk-count {
  font-weight: bold;
  margin-right: 8px;
  color: #555;
}
.pgf-bulk-cb-all, .pgf-bulk-cb-row { cursor: pointer; }
"""

	def render(self, actions: list[dict[str, Any]]) -> Markup:
		"""
		Return an inline ``<style>`` + ``<script>`` block that enhances the
		current FAB list table.

		Args:
			actions  List of action dicts (see class docstring).

		Returns:
			Markup  Safe HTML/JS block.
		"""
		actions_json = json.dumps(actions, ensure_ascii=False)
		html_out = f"""
<style id="pgf-bulk-style">
{self._CSS}
</style>

<!-- Bulk-action floating toolbar (rendered by BulkActionWidget) -->
<div id="pgf-bulk-toolbar" class="pgf-bulk-toolbar" style="display:none;">
  <span class="pgf-bulk-count"><span id="pgf-bulk-n">0</span> selected</span>
  <div id="pgf-bulk-buttons"></div>
  <button type="button" class="btn btn-default btn-xs" id="pgf-bulk-clear">
    <i class="fa fa-times"></i> Clear
  </button>
</div>

<script>
(function() {{
  // Idempotency guard — only initialise once per page.
  if (window.__pgfBulkInit) return;
  window.__pgfBulkInit = true;

  var ACTIONS = {actions_json};

  // ── DOM helpers ────────────────────────────────────────────────────────
  function q(sel) {{ return document.querySelector(sel); }}
  function qa(sel) {{ return Array.from(document.querySelectorAll(sel)); }}

  // ── Locate list table ─────────────────────────────────────────────────
  // FAB renders the list inside .table-responsive > table or just table
  var table = q('.table-responsive table') || q('table.dataTable') || q('table');
  if (!table) return;

  var thead = table.querySelector('thead tr');
  var tbody = table.querySelector('tbody');
  if (!thead || !tbody) return;

  // ── Inject header checkbox ────────────────────────────────────────────
  var thCb = document.createElement('th');
  thCb.style.width = '28px';
  thCb.innerHTML = '<input type="checkbox" class="pgf-bulk-cb-all" title="Select all">';
  thead.insertBefore(thCb, thead.firstChild);

  // ── Inject row checkboxes ─────────────────────────────────────────────
  qa('tbody tr').forEach(function(row) {{
    var pk = (row.dataset.pk
              || (row.querySelector('[data-pk]') || {{}}).dataset.pk
              || (row.querySelector('a[href]') || {{}}).href.split('/').filter(Boolean).pop()
              || '');
    var td = document.createElement('td');
    td.innerHTML = '<input type="checkbox" class="pgf-bulk-cb-row" value="' + pk + '">';
    row.insertBefore(td, row.firstChild);
  }});

  // ── Build action buttons ──────────────────────────────────────────────
  var btnContainer = q('#pgf-bulk-buttons');
  ACTIONS.forEach(function(action) {{
    var btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'btn btn-default btn-sm';
    var icon = action.icon ? '<i class="fa ' + action.icon + '"></i> ' : '';
    btn.innerHTML = icon + action.label;
    btn.addEventListener('click', function() {{
      var ids = qa('.pgf-bulk-cb-row:checked').map(function(cb) {{ return cb.value; }});
      if (!ids.length) return;
      if (action.confirm && !window.confirm(action.confirm)) return;
      var method = (action.method || 'POST').toUpperCase();
      fetch(action.url, {{
        method: method,
        headers: {{'Content-Type': 'application/json',
                   'X-CSRFToken': (document.cookie.match(/csrf_token=([^;]+)/) || [])[1] || ''}},
        body: JSON.stringify({{ids: ids}})
      }}).then(function(r) {{
        if (r.ok) window.location.reload();
        else r.text().then(function(t) {{ alert('Error: ' + t); }});
      }});
    }});
    btnContainer.appendChild(btn);
  }});

  // ── Toolbar show/hide ─────────────────────────────────────────────────
  var toolbar = q('#pgf-bulk-toolbar');
  toolbar.style.display = 'flex';

  function syncToolbar() {{
    var n = qa('.pgf-bulk-cb-row:checked').length;
    q('#pgf-bulk-n').textContent = n;
    if (n > 0) toolbar.classList.add('pgf-bulk-visible');
    else toolbar.classList.remove('pgf-bulk-visible');
  }}

  // Select-all toggle
  q('.pgf-bulk-cb-all').addEventListener('change', function() {{
    qa('.pgf-bulk-cb-row').forEach(function(cb) {{ cb.checked = this.checked; }}, this);
    syncToolbar();
  }});

  // Individual row toggles
  tbody.addEventListener('change', function(e) {{
    if (e.target.classList.contains('pgf-bulk-cb-row')) syncToolbar();
  }});

  // Clear button
  q('#pgf-bulk-clear').addEventListener('click', function() {{
    qa('.pgf-bulk-cb-row, .pgf-bulk-cb-all').forEach(function(cb) {{ cb.checked = false; }});
    syncToolbar();
  }});
}})();
</script>
"""
		return Markup(html_out)

	def __call__(self, actions: list[dict[str, Any]], **_kwargs: Any) -> Markup:
		return self.render(actions)


# ---------------------------------------------------------------------------
# 3. DiffViewerWidget
# ---------------------------------------------------------------------------

class DiffViewerWidget:
	"""
	Side-by-side field diff between two record versions.

	Compares the values stored in *left_col* and *right_col* on a model
	instance.  If both values are valid JSON they are pretty-printed before
	diffing; otherwise they are treated as plain multi-line text.

	All diff computation is done in pure Python (``difflib``); no extra JS or
	CDN is needed.

	Args:
		left_col    Attribute name for the "before" / older version.
		right_col   Attribute name for the "after" / newer version.
		left_label  Column header for the left pane (default: ``"Before"``).
		right_label Column header for the right pane (default: ``"After"``).

	Colour coding (CSS background)
	------------------------------
	- Added lines   ``#d4edda`` (Bootstrap success-light green)
	- Removed lines ``#f8d7da`` (Bootstrap danger-light red)
	- Changed lines ``#fff3cd`` (Bootstrap warning-light yellow)
	- Unchanged     ``#f8f9fa`` (Bootstrap light grey)
	"""

	# Tag constants returned by difflib.SequenceMatcher
	_EQUAL   = "equal"
	_INSERT  = "insert"
	_DELETE  = "delete"
	_REPLACE = "replace"

	# Background colours indexed by tag
	_LEFT_COLOURS: dict[str, str] = {
		_EQUAL:   "#f8f9fa",
		_DELETE:  "#f8d7da",
		_REPLACE: "#fff3cd",
		_INSERT:  "",          # left side blank for pure insertions
	}
	_RIGHT_COLOURS: dict[str, str] = {
		_EQUAL:   "#f8f9fa",
		_INSERT:  "#d4edda",
		_REPLACE: "#fff3cd",
		_DELETE:  "",          # right side blank for pure deletions
	}

	def __init__(
		self,
		left_col: str,
		right_col: str,
		left_label: str = "Before",
		right_label: str = "After",
	) -> None:
		self.left_col = left_col
		self.right_col = right_col
		self.left_label = left_label
		self.right_label = right_label

	# ------------------------------------------------------------------
	def render(self, obj: Any) -> Markup:
		"""
		Return HTML for the diff viewer bound to *obj*.

		Args:
			obj  Model instance (or any object with the configured column attrs).

		Returns:
			Markup  Safe HTML string.
		"""
		left_raw  = getattr(obj, self.left_col,  "") or ""
		right_raw = getattr(obj, self.right_col, "") or ""

		left_text  = self._normalise(left_raw)
		right_text = self._normalise(right_raw)

		left_lines  = left_text.splitlines()
		right_lines = right_text.splitlines()

		rows = self._diff_rows(left_lines, right_lines)

		left_label  = _esc(self.left_label)
		right_label = _esc(self.right_label)

		header = f"""
<div class="pgf-diff-viewer">
  <div class="row">
    <div class="col-xs-6">
      <h5 class="pgf-diff-label"
          style="font-weight:bold;border-bottom:2px solid #ccc;padding-bottom:4px;">
        <i class="fa fa-file-o"></i>&nbsp;{left_label}
      </h5>
    </div>
    <div class="col-xs-6">
      <h5 class="pgf-diff-label"
          style="font-weight:bold;border-bottom:2px solid #ccc;padding-bottom:4px;">
        <i class="fa fa-file-text-o"></i>&nbsp;{right_label}
      </h5>
    </div>
  </div>
  <div class="row">
    <div class="col-xs-12">
      <table class="table table-condensed pgf-diff-table"
             style="font-family:monospace;font-size:0.85em;table-layout:fixed;width:100%;">
        <tbody>
"""
		body_rows: list[str] = []
		for left_line, right_line, tag in rows:
			l_bg = self._LEFT_COLOURS.get(tag, "#f8f9fa")
			r_bg = self._RIGHT_COLOURS.get(tag, "#f8f9fa")
			l_cell = f'<td style="background:{l_bg};white-space:pre-wrap;word-break:break-all;width:50%;padding:1px 4px;">{_esc(left_line)}</td>'
			r_cell = f'<td style="background:{r_bg};white-space:pre-wrap;word-break:break-all;width:50%;padding:1px 4px;">{_esc(right_line)}</td>'
			body_rows.append(f"<tr>{l_cell}{r_cell}</tr>")

		footer = """
        </tbody>
      </table>
    </div>
  </div>
</div>"""

		return Markup(header + "\n".join(body_rows) + footer)

	def __call__(self, obj: Any, **_kwargs: Any) -> Markup:
		return self.render(obj)

	# ------------------------------------------------------------------
	# Private helpers
	# ------------------------------------------------------------------

	@staticmethod
	def _normalise(value: Any) -> str:
		"""Pretty-print if JSON-parseable, else return as-is."""
		text = str(value) if not isinstance(value, str) else value
		try:
			parsed = json.loads(text)
			return json.dumps(parsed, indent=2, ensure_ascii=False)
		except (json.JSONDecodeError, ValueError):
			return text

	def _diff_rows(
		self,
		left_lines: list[str],
		right_lines: list[str],
	) -> list[tuple[str, str, str]]:
		"""
		Return a list of ``(left_line, right_line, tag)`` triples aligned for
		side-by-side display using ``difflib.SequenceMatcher``.
		"""
		matcher = difflib.SequenceMatcher(None, left_lines, right_lines, autojunk=False)
		rows: list[tuple[str, str, str]] = []

		for tag, i1, i2, j1, j2 in matcher.get_opcodes():
			left_chunk  = left_lines[i1:i2]
			right_chunk = right_lines[j1:j2]

			if tag == self._EQUAL:
				for l, r in zip(left_chunk, right_chunk):
					rows.append((l, r, self._EQUAL))

			elif tag == self._DELETE:
				for l in left_chunk:
					rows.append((l, "", self._DELETE))

			elif tag == self._INSERT:
				for r in right_chunk:
					rows.append(("", r, self._INSERT))

			elif tag == self._REPLACE:
				# Pad the shorter side with empty strings.
				max_len = max(len(left_chunk), len(right_chunk))
				for idx in range(max_len):
					l = left_chunk[idx]  if idx < len(left_chunk)  else ""
					r = right_chunk[idx] if idx < len(right_chunk) else ""
					rows.append((l, r, self._REPLACE))

		return rows


# ---------------------------------------------------------------------------
# 4. TimelineWidget
# ---------------------------------------------------------------------------

# Default icon and colour per action type.
_ACTION_META: dict[str, tuple[str, str]] = {
	"create":  ("fa-plus-circle",  "#5cb85c"),   # Bootstrap success green
	"update":  ("fa-pencil-square","#5bc0de"),   # Bootstrap info blue
	"delete":  ("fa-trash",        "#d9534f"),   # Bootstrap danger red
	"comment": ("fa-comment",      "#aaaaaa"),   # grey
}
_FALLBACK_META = ("fa-circle", "#777777")


class TimelineWidget:
	"""
	Bootstrap 3 vertical timeline built from an audit-event list.

	Args:
		events  List of event dicts.  Each dict may contain:

		- ``timestamp``   (str | datetime)  Display timestamp.
		- ``user``        (str)  Username or display name.
		- ``action``      (str)  One of ``create``, ``update``, ``delete``,
		                  ``comment``, or any custom string (falls back to grey
		                  circle icon).
		- ``description`` (str)  Body text for the event card.
		- ``icon``        (str | None)  Override Font Awesome class
		                  e.g. ``"fa-lock"``.  Takes priority over action default.

	Usage::

		timeline = TimelineWidget()
		html = timeline.render(events)
	"""

	_CSS = """
<style id="pgf-timeline-style">
.pgf-timeline { position: relative; padding: 0; list-style: none; }
.pgf-timeline::before {
  content: '';
  position: absolute;
  top: 0; bottom: 0; left: 18px;
  width: 2px;
  background: #e0e0e0;
}
.pgf-timeline-item { position: relative; margin-bottom: 20px; padding-left: 52px; }
.pgf-timeline-icon {
  position: absolute;
  left: 0; top: 0;
  width: 36px; height: 36px;
  border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  color: #fff;
  font-size: 14px;
  box-shadow: 0 1px 3px rgba(0,0,0,.3);
}
.pgf-timeline-body {
  background: #fff;
  border: 1px solid #ddd;
  border-radius: 4px;
  padding: 8px 12px;
}
.pgf-timeline-header {
  display: flex; justify-content: space-between; align-items: baseline;
  flex-wrap: wrap; gap: 4px;
}
.pgf-timeline-user  { font-weight: bold; color: #333; }
.pgf-timeline-ts    { font-size: 0.8em; color: #888; }
.pgf-timeline-desc  { margin-top: 4px; color: #555; }
.pgf-timeline-badge {
  display: inline-block;
  font-size: 0.75em;
  padding: 1px 6px;
  border-radius: 10px;
  color: #fff;
  margin-left: 6px;
  vertical-align: middle;
}
</style>
"""

	def render(self, events: list[dict[str, Any]]) -> Markup:
		"""
		Return Bootstrap 3 vertical timeline HTML for *events*.

		Args:
			events  List of event dicts (see class docstring).

		Returns:
			Markup  Safe HTML string.
		"""
		if not events:
			return Markup(
				'<p class="text-muted"><i class="fa fa-clock-o"></i>'
				" No history available.</p>"
			)

		items: list[str] = []
		for event in events:
			action      = str(event.get("action", "")).lower()
			icon_cls, colour = _ACTION_META.get(action, _FALLBACK_META)
			# Caller-supplied icon takes priority.
			override_icon = event.get("icon")
			if override_icon:
				icon_cls = override_icon

			timestamp   = _esc(event.get("timestamp", ""))
			user        = _esc(event.get("user", ""))
			description = _esc(event.get("description", ""))
			action_esc  = _esc(action) if action else ""

			badge_html = (
				f'<span class="pgf-timeline-badge" style="background:{colour};">'
				f'{action_esc}</span>'
				if action_esc else ""
			)

			item = f"""
<li class="pgf-timeline-item">
  <div class="pgf-timeline-icon" style="background:{colour};">
    <i class="fa {icon_cls}"></i>
  </div>
  <div class="pgf-timeline-body">
    <div class="pgf-timeline-header">
      <span class="pgf-timeline-user">
        <i class="fa fa-user-o" style="color:#aaa;"></i>&nbsp;{user}
        {badge_html}
      </span>
      <span class="pgf-timeline-ts">
        <i class="fa fa-clock-o" style="color:#aaa;"></i>&nbsp;{timestamp}
      </span>
    </div>
    {"<p class='pgf-timeline-desc'>" + description + "</p>" if description else ""}
  </div>
</li>"""
			items.append(item)

		return Markup(
			self._CSS
			+ '\n<ul class="pgf-timeline">\n'
			+ "\n".join(items)
			+ "\n</ul>"
		)

	def __call__(self, events: list[dict[str, Any]], **_kwargs: Any) -> Markup:
		return self.render(events)
