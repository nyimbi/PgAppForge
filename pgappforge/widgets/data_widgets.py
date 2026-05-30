"""
data_widgets.py — four data-centric display/editing widgets for PgAppForge

Widgets
-------
DataGridWidget          Excel-like bulk editor for multiple records
DataImportWidget        Drag-and-drop CSV/XLSX importer with column mapping
EmbeddedMapWidget       Read-only Leaflet pin map for lat/lng datasets
RelationshipGraphWidget Cytoscape.js graph of related records

All widgets:
- Emit self-contained HTML with inline JS (IIFEs) and CSS
- Lazy-guard CDN loads so duplicate instances on one page stay silent
- Use markupsafe.Markup exclusively
- Tab-indented, from __future__ import annotations throughout
"""
from __future__ import annotations

import json
from typing import Any

from markupsafe import Markup

from pgappforge.widgets_postgresql._cdn import (
	LEAFLET_CDN as _LEAFLET_CDN,
	CYTOSCAPE_CDN as _CYTOSCAPE_CDN,
)

__all__ = [
	"DataGridWidget",
	"DataImportWidget",
	"EmbeddedMapWidget",
	"RelationshipGraphWidget",
]

# ── Leaflet.markercluster CDN (pinned to 1.5.3) ─────────────────────────────
_MARKERCLUSTER_CDN = """
<link rel="stylesheet" href="https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.css" crossorigin="">
<link rel="stylesheet" href="https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.Default.css" crossorigin="">
<script src="https://unpkg.com/leaflet.markercluster@1.5.3/dist/leaflet.markercluster.js" crossorigin=""></script>
"""


# ── helpers ──────────────────────────────────────────────────────────────────

def _once(flag: str, body: str) -> str:
	"""Wrap *body* in an IIFE that no-ops if *flag* is already set on window."""
	return f"(function(){{ if(window['{flag}']){{return;}} window['{flag}']=true; {body} }})();"


def _uid(prefix: str, obj_id: Any) -> str:
	return f"{prefix}_{str(obj_id).replace('-', '_')}"


# ─────────────────────────────────────────────────────────────────────────────
# 1. DataGridWidget
# ─────────────────────────────────────────────────────────────────────────────

class DataGridWidget:
	"""Excel-like bulk editor for a list of records.

	Args:
		columns:       List of column descriptors, each a dict with keys:
		                 name (str)      — field name / dict key in each row
		                 label (str)     — header label (defaults to name)
		                 type (str)      — "text" | "number" | "date" |
		                                  "boolean" | "select"
		                 editable (bool) — whether the cell is editable
		                 options (list)  — only for type="select"; list of
		                                  {"value": …, "label": …} dicts
		save_url:      POST endpoint that receives
		                 {"changes": [{"id": …, "field": …, "value": …}, …]}
		rows_per_page: Rows shown per page (default 20)

	Usage in a view::

		grid = DataGridWidget(
		    columns=[
		        {"name": "id",     "type": "text",    "editable": False},
		        {"name": "name",   "type": "text",    "editable": True},
		        {"name": "active", "type": "boolean", "editable": True},
		        {"name": "score",  "type": "number",  "editable": True},
		    ],
		    save_url="/api/employees/bulk-save",
		    rows_per_page=25,
		)
		html = grid.render(rows)          # rows = list[dict]
	"""

	def __init__(
		self,
		columns: list[dict[str, Any]],
		save_url: str,
		rows_per_page: int = 20,
	) -> None:
		self.columns = columns
		self.save_url = save_url
		self.rows_per_page = rows_per_page

	def render(self, rows: list[dict[str, Any]]) -> Markup:
		cols_json = json.dumps(self.columns)
		rows_json = json.dumps(rows)
		save_url = self.save_url
		rpp = self.rows_per_page

		html = f"""
<div class="datagrid-widget" id="dg_root" style="font-family:inherit">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
    <span id="dg_status" class="text-muted" style="font-size:0.85em"></span>
    <div>
      <button type="button" class="btn btn-sm btn-default" id="dg_prev">&laquo; Prev</button>
      <span id="dg_page_info" style="margin:0 8px;font-size:0.9em"></span>
      <button type="button" class="btn btn-sm btn-default" id="dg_next">Next &raquo;</button>
      <button type="button" class="btn btn-sm btn-success" id="dg_save" style="margin-left:12px">
        <i class="fa fa-save"></i> Save changes
      </button>
    </div>
  </div>
  <div style="overflow-x:auto">
    <table class="table table-bordered table-condensed" id="dg_table"
           style="width:100%;table-layout:auto">
      <thead id="dg_thead"></thead>
      <tbody id="dg_tbody"></tbody>
    </table>
  </div>
</div>

<style>
.dg-changed {{ background-color:#fff9c4 !important; }}
.dg-cell-edit {{ width:100%;box-sizing:border-box;padding:2px 4px;border:1px solid #aaa;border-radius:2px; }}
.dg-cell {{ cursor:default;padding:4px 6px !important; }}
.dg-cell.editable {{ cursor:cell; }}
</style>

<script>
(function() {{
  var COLS = {cols_json};
  var ALL_ROWS = {rows_json};
  var SAVE_URL = {json.dumps(save_url)};
  var RPP = {rpp};

  var changes = {{}}; // key = rowId+"|"+field  value = {{id,field,value}}
  var currentPage = 1;

  function totalPages() {{
    return Math.max(1, Math.ceil(ALL_ROWS.length / RPP));
  }}

  function pageRows() {{
    var start = (currentPage - 1) * RPP;
    return ALL_ROWS.slice(start, start + RPP);
  }}

  // ── header ────────────────────────────────────────────────────────────────
  function buildHeader() {{
    var thead = document.getElementById('dg_thead');
    var tr = document.createElement('tr');
    COLS.forEach(function(col) {{
      var th = document.createElement('th');
      th.textContent = col.label || col.name;
      th.style.whiteSpace = 'nowrap';
      tr.appendChild(th);
    }});
    thead.innerHTML = '';
    thead.appendChild(tr);
  }}

  // ── body ──────────────────────────────────────────────────────────────────
  function buildBody() {{
    var tbody = document.getElementById('dg_tbody');
    tbody.innerHTML = '';
    var rows = pageRows();
    rows.forEach(function(row) {{
      var tr = document.createElement('tr');
      COLS.forEach(function(col) {{
        var td = document.createElement('td');
        td.className = 'dg-cell' + (col.editable ? ' editable' : '');
        var key = String(row.id) + '|' + col.name;
        if (changes[key]) td.classList.add('dg-changed');
        var val = (changes[key] ? changes[key].value : row[col.name]);
        if (col.editable) {{
          td.title = 'Click to edit';
          td.addEventListener('click', function(e) {{
            if (td.querySelector('.dg-cell-edit')) return;
            startEdit(td, row, col, val);
          }});
        }} else {{
          td.textContent = val == null ? '' : String(val);
        }}
        td.dataset.rowId = row.id;
        td.dataset.field = col.name;
        tr.appendChild(td);
      }});
      tbody.appendChild(tr);
    }});
    updateStatus();
    updatePager();
  }}

  // ── inline editor ─────────────────────────────────────────────────────────
  function startEdit(td, row, col, currentVal) {{
    var input = makeInput(col, currentVal);
    input.className = 'dg-cell-edit';
    td.innerHTML = '';
    td.appendChild(input);
    input.focus();

    function commit() {{
      var newVal = getInputValue(col, input);
      var key = String(row.id) + '|' + col.name;
      changes[key] = {{id: row.id, field: col.name, value: newVal}};
      td.innerHTML = '';
      td.classList.add('dg-changed');
      if (col.type === 'boolean') {{
        td.textContent = newVal ? 'Yes' : 'No';
      }} else {{
        td.textContent = newVal == null ? '' : String(newVal);
      }}
      updateStatus();
    }}

    if (col.type === 'boolean') {{
      input.addEventListener('change', commit);
    }} else {{
      input.addEventListener('blur', commit);
      input.addEventListener('keydown', function(e) {{
        if (e.key === 'Enter') {{ commit(); e.preventDefault(); }}
        if (e.key === 'Tab') {{
          commit();
          // move to next editable cell
          var all = Array.from(document.querySelectorAll('td.editable'));
          var idx = all.indexOf(td);
          if (idx >= 0 && idx + 1 < all.length) {{
            e.preventDefault();
            all[idx + 1].click();
          }}
        }}
      }});
    }}
  }}

  function makeInput(col, val) {{
    var el;
    if (col.type === 'boolean') {{
      el = document.createElement('input');
      el.type = 'checkbox';
      el.checked = !!val;
    }} else if (col.type === 'select') {{
      el = document.createElement('select');
      (col.options || []).forEach(function(opt) {{
        var o = document.createElement('option');
        o.value = opt.value;
        o.textContent = opt.label;
        if (opt.value == val) o.selected = true;
        el.appendChild(o);
      }});
    }} else {{
      el = document.createElement('input');
      el.type = col.type === 'number' ? 'number' : (col.type === 'date' ? 'date' : 'text');
      el.value = val == null ? '' : String(val);
    }}
    return el;
  }}

  function getInputValue(col, input) {{
    if (col.type === 'boolean') return input.checked;
    if (col.type === 'number') return input.value === '' ? null : Number(input.value);
    return input.value;
  }}

  // ── pager & status ────────────────────────────────────────────────────────
  function updateStatus() {{
    var n = Object.keys(changes).length;
    var el = document.getElementById('dg_status');
    el.textContent = n ? (n + ' unsaved change' + (n !== 1 ? 's' : '')) : '';
    el.style.color = n ? '#c0392b' : '';
  }}

  function updatePager() {{
    document.getElementById('dg_page_info').textContent =
      'Page ' + currentPage + ' of ' + totalPages() + ' (' + ALL_ROWS.length + ' rows)';
    document.getElementById('dg_prev').disabled = (currentPage <= 1);
    document.getElementById('dg_next').disabled = (currentPage >= totalPages());
  }}

  document.getElementById('dg_prev').addEventListener('click', function() {{
    if (currentPage > 1) {{ currentPage--; buildBody(); }}
  }});
  document.getElementById('dg_next').addEventListener('click', function() {{
    if (currentPage < totalPages()) {{ currentPage++; buildBody(); }}
  }});

  // ── save ──────────────────────────────────────────────────────────────────
  document.getElementById('dg_save').addEventListener('click', function() {{
    var payload = {{changes: Object.values(changes)}};
    if (!payload.changes.length) {{
      alert('No changes to save.');
      return;
    }}
    var btn = this;
    btn.disabled = true;
    btn.textContent = 'Saving…';
    fetch(SAVE_URL, {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify(payload)
    }})
    .then(function(r) {{
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    }})
    .then(function() {{
      changes = {{}};
      btn.disabled = false;
      btn.innerHTML = '<i class="fa fa-save"></i> Save changes';
      document.querySelectorAll('td.dg-changed').forEach(function(td) {{
        td.classList.remove('dg-changed');
      }});
      updateStatus();
    }})
    .catch(function(err) {{
      btn.disabled = false;
      btn.innerHTML = '<i class="fa fa-save"></i> Save changes';
      alert('Save failed: ' + err.message);
    }});
  }});

  // ── init ──────────────────────────────────────────────────────────────────
  buildHeader();
  buildBody();
}})();
</script>
"""
		return Markup(html)


# ─────────────────────────────────────────────────────────────────────────────
# 2. DataImportWidget
# ─────────────────────────────────────────────────────────────────────────────

class DataImportWidget:
	"""Drag-and-drop CSV / Excel importer with server-side parsing.

	Four-step wizard rendered entirely client-side:
	  Step 1  File drop zone (CSV or XLSX)
	  Step 2  Column mapping (detected file headers → model fields)
	  Step 3  Validation preview (first 10 rows + any errors returned by server)
	  Step 4  Confirm or rollback

	The widget reads the file in the browser and POSTs the raw bytes to the
	server; all parsing happens server-side.

	Required server endpoints
	-------------------------
	POST preview_url
	    Request body (multipart):  file=<bytes>, mapping=<json>
	    Response JSON:
	        {
	            "columns": ["col1", …],      # detected on first call (no mapping yet)
	            "rows":    [[…], …],          # first 10 parsed rows
	            "errors":  ["row 3: …", …]   # validation messages
	        }

	POST commit_url
	    Request body (multipart):  file=<bytes>, mapping=<json>
	    Response JSON:
	        {"imported": 42}   or   {"error": "…"}

	Args:
		preview_url:   Endpoint for step-2/3 preview
		commit_url:    Endpoint for step-4 commit
		model_fields:  List of model field names the user can map to.
		               Each entry is either a plain str or a dict
		               {"name": …, "label": …}.

	Usage::

		widget = DataImportWidget(
		    preview_url="/import/employees/preview",
		    commit_url="/import/employees/commit",
		    model_fields=["first_name", "last_name", "email", "department"],
		)
		html = widget.render()
	"""

	def __init__(
		self,
		preview_url: str,
		commit_url: str,
		model_fields: list[str | dict[str, str]] | None = None,
	) -> None:
		self.preview_url = preview_url
		self.commit_url = commit_url
		self.model_fields = model_fields or []

	def render(self) -> Markup:
		# Normalise model_fields to [{name, label}, …]
		fields: list[dict[str, str]] = []
		for f in self.model_fields:
			if isinstance(f, str):
				fields.append({"name": f, "label": f})
			else:
				fields.append({"name": f.get("name", ""), "label": f.get("label", f.get("name", ""))})

		fields_json = json.dumps(fields)
		preview_url = self.preview_url
		commit_url = self.commit_url

		html = f"""
<div class="di-widget" id="di_root">

  <style>
  #di_root .di-step {{ display:none; }}
  #di_root .di-step.active {{ display:block; }}
  #di_dropzone {{
    border:2px dashed #adb5bd; border-radius:8px; padding:40px;
    text-align:center; cursor:pointer; transition:background 0.2s;
  }}
  #di_dropzone.drag-over {{ background:#e8f4fd; border-color:#0d6efd; }}
  #di_dropzone input[type=file] {{ display:none; }}
  .di-mapping-row {{ display:flex; align-items:center; margin-bottom:6px; gap:8px; }}
  .di-mapping-row label {{ min-width:160px; font-weight:500; }}
  .di-preview-table {{ font-size:0.82em; width:100%; overflow-x:auto; display:block; }}
  .di-preview-table table {{ width:100%; border-collapse:collapse; }}
  .di-preview-table td, .di-preview-table th {{ border:1px solid #dee2e6; padding:3px 6px; white-space:nowrap; }}
  .di-error {{ color:#c0392b; font-size:0.85em; margin-top:4px; }}
  .di-steps-nav {{ margin-bottom:16px; }}
  .di-steps-nav .step-badge {{
    display:inline-block; width:24px; height:24px; line-height:24px;
    border-radius:50%; text-align:center; font-size:0.8em; font-weight:700;
    background:#dee2e6; color:#495057; margin-right:4px;
  }}
  .di-steps-nav .step-badge.done {{ background:#198754; color:#fff; }}
  .di-steps-nav .step-badge.active {{ background:#0d6efd; color:#fff; }}
  </style>

  <!-- step nav -->
  <div class="di-steps-nav">
    <span class="step-badge active" id="di_badge_1">1</span> Upload &nbsp;
    <span class="step-badge" id="di_badge_2">2</span> Map columns &nbsp;
    <span class="step-badge" id="di_badge_3">3</span> Preview &nbsp;
    <span class="step-badge" id="di_badge_4">4</span> Confirm
  </div>

  <!-- Step 1: drop zone -->
  <div class="di-step active" id="di_step1">
    <div id="di_dropzone">
      <i class="fa fa-cloud-upload fa-3x" style="color:#adb5bd;margin-bottom:8px"></i>
      <p style="margin:0;color:#6c757d">Drag &amp; drop a CSV or XLSX file here, or click to browse</p>
      <p style="margin:4px 0 0;font-size:0.8em;color:#adb5bd">Accepted: .csv, .xlsx</p>
      <input type="file" id="di_file_input" accept=".csv,.xlsx">
    </div>
    <div class="di-error" id="di_step1_err"></div>
  </div>

  <!-- Step 2: column mapping -->
  <div class="di-step" id="di_step2">
    <p class="text-muted" style="font-size:0.9em">
      Map each column detected in your file to the corresponding model field.
      Leave "— skip —" to ignore that column.
    </p>
    <div id="di_mapping_rows"></div>
    <div class="di-error" id="di_step2_err"></div>
    <div style="margin-top:12px">
      <button type="button" class="btn btn-default btn-sm" id="di_back2">&#8592; Back</button>
      <button type="button" class="btn btn-primary btn-sm" id="di_preview_btn">Preview import</button>
    </div>
  </div>

  <!-- Step 3: preview -->
  <div class="di-step" id="di_step3">
    <div class="di-preview-table" id="di_preview_table"></div>
    <ul class="di-error" id="di_preview_errors" style="margin-top:8px;list-style:disc;padding-left:20px"></ul>
    <div style="margin-top:12px">
      <button type="button" class="btn btn-default btn-sm" id="di_back3">&#8592; Back</button>
      <button type="button" class="btn btn-success btn-sm" id="di_confirm_btn">Confirm import</button>
    </div>
  </div>

  <!-- Step 4: result -->
  <div class="di-step" id="di_step4">
    <div id="di_result_msg"></div>
    <div style="margin-top:12px">
      <button type="button" class="btn btn-default btn-sm" id="di_restart_btn">Import another file</button>
    </div>
  </div>

</div>

<script>
(function() {{
  var PREVIEW_URL = {json.dumps(preview_url)};
  var COMMIT_URL  = {json.dumps(commit_url)};
  var MODEL_FIELDS = {fields_json};

  var _file = null;
  var _detectedCols = [];
  var _mapping = {{}};  // fileCol -> modelField

  // ── step helpers ──────────────────────────────────────────────────────────
  function goStep(n) {{
    [1,2,3,4].forEach(function(i) {{
      document.getElementById('di_step' + i).classList.toggle('active', i === n);
      var b = document.getElementById('di_badge_' + i);
      b.classList.toggle('active', i === n);
      b.classList.toggle('done', i < n);
    }});
  }}

  // ── step 1: drop zone ─────────────────────────────────────────────────────
  var dropzone = document.getElementById('di_dropzone');
  var fileInput = document.getElementById('di_file_input');

  dropzone.addEventListener('click', function() {{ fileInput.click(); }});

  dropzone.addEventListener('dragover', function(e) {{
    e.preventDefault(); dropzone.classList.add('drag-over');
  }});
  dropzone.addEventListener('dragleave', function() {{
    dropzone.classList.remove('drag-over');
  }});
  dropzone.addEventListener('drop', function(e) {{
    e.preventDefault(); dropzone.classList.remove('drag-over');
    var f = e.dataTransfer.files[0];
    if (f) handleFile(f);
  }});
  fileInput.addEventListener('change', function() {{
    if (this.files[0]) handleFile(this.files[0]);
  }});

  function handleFile(f) {{
    var ok = /\\.(csv|xlsx)$/i.test(f.name);
    if (!ok) {{
      document.getElementById('di_step1_err').textContent = 'Only .csv and .xlsx files are accepted.';
      return;
    }}
    document.getElementById('di_step1_err').textContent = '';
    _file = f;
    // Send file to server to detect columns (no mapping yet)
    sendPreview(null, function(data) {{
      _detectedCols = data.columns || [];
      buildMappingRows();
      goStep(2);
    }}, function(err) {{
      document.getElementById('di_step1_err').textContent = 'Error: ' + err;
    }});
  }}

  // ── step 2: mapping ───────────────────────────────────────────────────────
  function buildMappingRows() {{
    var container = document.getElementById('di_mapping_rows');
    container.innerHTML = '';
    _detectedCols.forEach(function(col) {{
      var row = document.createElement('div');
      row.className = 'di-mapping-row';
      var lbl = document.createElement('label');
      lbl.textContent = col;
      var sel = document.createElement('select');
      sel.className = 'form-control input-sm';
      sel.style.maxWidth = '240px';
      var skip = document.createElement('option');
      skip.value = ''; skip.textContent = '— skip —';
      sel.appendChild(skip);
      MODEL_FIELDS.forEach(function(mf) {{
        var opt = document.createElement('option');
        opt.value = mf.name;
        opt.textContent = mf.label;
        // Auto-match by name (case-insensitive)
        if (mf.name.toLowerCase() === col.toLowerCase()) opt.selected = true;
        sel.appendChild(opt);
      }});
      sel.dataset.fileCol = col;
      row.appendChild(lbl);
      row.appendChild(sel);
      container.appendChild(row);
    }});
  }}

  document.getElementById('di_back2').addEventListener('click', function() {{ goStep(1); }});

  document.getElementById('di_preview_btn').addEventListener('click', function() {{
    // Collect mapping
    _mapping = {{}};
    document.querySelectorAll('#di_mapping_rows select').forEach(function(sel) {{
      if (sel.value) _mapping[sel.dataset.fileCol] = sel.value;
    }});
    sendPreview(_mapping, function(data) {{
      renderPreview(data);
      goStep(3);
    }}, function(err) {{
      document.getElementById('di_step2_err').textContent = 'Error: ' + err;
    }});
  }});

  // ── step 3: preview ───────────────────────────────────────────────────────
  function renderPreview(data) {{
    var rows = data.rows || [];
    var cols = data.columns || Object.keys(_mapping);
    var errEl = document.getElementById('di_preview_errors');
    errEl.innerHTML = '';
    (data.errors || []).forEach(function(e) {{
      var li = document.createElement('li'); li.textContent = e; errEl.appendChild(li);
    }});

    var tbl = '<table><thead><tr>' +
      cols.map(function(c) {{ return '<th>' + _esc(c) + '</th>'; }}).join('') +
      '</tr></thead><tbody>';
    rows.slice(0, 10).forEach(function(r) {{
      tbl += '<tr>' + r.map(function(v) {{ return '<td>' + _esc(String(v ?? '')) + '</td>'; }}).join('') + '</tr>';
    }});
    tbl += '</tbody></table>';
    if (rows.length > 10) tbl += '<p class="text-muted" style="font-size:0.8em">Showing first 10 of ' + rows.length + ' rows.</p>';
    document.getElementById('di_preview_table').innerHTML = tbl;
  }}

  document.getElementById('di_back3').addEventListener('click', function() {{ goStep(2); }});

  document.getElementById('di_confirm_btn').addEventListener('click', function() {{
    var btn = this; btn.disabled = true; btn.textContent = 'Importing…';
    var fd = new FormData();
    fd.append('file', _file);
    fd.append('mapping', JSON.stringify(_mapping));
    fetch(COMMIT_URL, {{method:'POST', body:fd}})
      .then(function(r) {{ return r.json(); }})
      .then(function(data) {{
        var msg = document.getElementById('di_result_msg');
        if (data.error) {{
          msg.innerHTML = '<div class="alert alert-danger"><i class="fa fa-times"></i> ' + _esc(data.error) + '</div>';
        }} else {{
          msg.innerHTML = '<div class="alert alert-success"><i class="fa fa-check"></i> Successfully imported ' + (data.imported || 0) + ' records.</div>';
        }}
        btn.disabled = false; btn.textContent = 'Confirm import';
        goStep(4);
      }})
      .catch(function(err) {{
        btn.disabled = false; btn.textContent = 'Confirm import';
        alert('Import failed: ' + err.message);
      }});
  }});

  document.getElementById('di_restart_btn').addEventListener('click', function() {{
    _file = null; _detectedCols = []; _mapping = {{}};
    document.getElementById('di_mapping_rows').innerHTML = '';
    document.getElementById('di_preview_table').innerHTML = '';
    document.getElementById('di_preview_errors').innerHTML = '';
    document.getElementById('di_result_msg').innerHTML = '';
    document.getElementById('di_step1_err').textContent = '';
    goStep(1);
  }});

  // ── shared helpers ────────────────────────────────────────────────────────
  function sendPreview(mapping, onOk, onErr) {{
    var fd = new FormData();
    fd.append('file', _file);
    if (mapping) fd.append('mapping', JSON.stringify(mapping));
    fetch(PREVIEW_URL, {{method:'POST', body:fd}})
      .then(function(r) {{
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
      }})
      .then(onOk)
      .catch(function(e) {{ onErr(e.message); }});
  }}

  function _esc(s) {{
    return String(s)
      .replace(/&/g,'&amp;').replace(/</g,'&lt;')
      .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }}
}})();
</script>
"""
		return Markup(html)


# ─────────────────────────────────────────────────────────────────────────────
# 3. EmbeddedMapWidget
# ─────────────────────────────────────────────────────────────────────────────

class EmbeddedMapWidget:
	"""Read-only Leaflet map that pins every row by its lat/lng columns.

	Clusters markers automatically at low zoom levels using
	Leaflet.markercluster. Clicking a pin opens a popup with the label and
	any additional columns specified in *popup_cols*.

	Args:
		lat_col:    Name of the latitude key in each row dict.
		lng_col:    Name of the longitude key in each row dict.
		label_col:  Name of the key used as the popup heading / pin tooltip.
		popup_cols: Additional field names to show in each popup body.
		height:     Map height in pixels (default 400).

	Usage::

		map_widget = EmbeddedMapWidget(
		    lat_col="latitude",
		    lng_col="longitude",
		    label_col="name",
		    popup_cols=["city", "country", "status"],
		    height=450,
		)
		html = map_widget.render(rows)   # rows = list[dict]
	"""

	def __init__(
		self,
		lat_col: str,
		lng_col: str,
		label_col: str,
		popup_cols: list[str] | None = None,
		height: int = 400,
	) -> None:
		self.lat_col = lat_col
		self.lng_col = lng_col
		self.label_col = label_col
		self.popup_cols = popup_cols or []
		self.height = height

	def render(self, rows: list[dict[str, Any]]) -> Markup:
		# Serialise only the fields we need — keeps payload small
		needed = {self.lat_col, self.lng_col, self.label_col} | set(self.popup_cols)
		slim_rows: list[dict[str, Any]] = [
			{k: v for k, v in row.items() if k in needed}
			for row in rows
		]

		rows_json = json.dumps(slim_rows)
		lat_col = json.dumps(self.lat_col)
		lng_col = json.dumps(self.lng_col)
		label_col = json.dumps(self.label_col)
		popup_cols_json = json.dumps(self.popup_cols)
		height = self.height

		html = f"""
{_LEAFLET_CDN}
{_MARKERCLUSTER_CDN}

<div id="emw_map" style="height:{height}px;border:1px solid #dee2e6;border-radius:4px"></div>

<script>
(function() {{
  var ROWS = {rows_json};
  var LAT  = {lat_col};
  var LNG  = {lng_col};
  var LABEL = {label_col};
  var POPUP_COLS = {popup_cols_json};

  document.addEventListener('DOMContentLoaded', function() {{
    var map = L.map('emw_map').setView([20, 0], 2);
    L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
      attribution: '&copy; OpenStreetMap contributors',
      maxZoom: 19
    }}).addTo(map);

    var cluster = L.markerClusterGroup();

    ROWS.forEach(function(row) {{
      var lat = parseFloat(row[LAT]);
      var lng = parseFloat(row[LNG]);
      if (isNaN(lat) || isNaN(lng)) return;

      var label = row[LABEL] != null ? String(row[LABEL]) : '';
      var popupHtml = '<strong>' + _esc(label) + '</strong>';
      POPUP_COLS.forEach(function(col) {{
        if (row[col] != null) {{
          popupHtml += '<br><span style="color:#6c757d;font-size:0.85em">' +
            _esc(col) + ':</span> ' + _esc(String(row[col]));
        }}
      }});

      var marker = L.marker([lat, lng], {{title: label}});
      marker.bindPopup(popupHtml);
      cluster.addLayer(marker);
    }});

    map.addLayer(cluster);

    // Fit bounds if we have points
    if (cluster.getLayers().length) {{
      try {{ map.fitBounds(cluster.getBounds().pad(0.1)); }} catch(e) {{}}
    }}
  }});

  function _esc(s) {{
    return String(s)
      .replace(/&/g,'&amp;').replace(/</g,'&lt;')
      .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }}
}})();
</script>
"""
		return Markup(html)


# ─────────────────────────────────────────────────────────────────────────────
# 4. RelationshipGraphWidget
# ─────────────────────────────────────────────────────────────────────────────

class RelationshipGraphWidget:
	"""Cytoscape.js graph showing how a record connects to related records.

	Renders a 300 px-high interactive graph where:
	- The centre node is the current record
	- Each relationship spawns an async fetch to *related_url*; the response
	  must be a JSON array of ``{"id": …, "label": …, "url": …}`` objects
	- Edges are labelled with the relationship label
	- Clicking an outer node navigates to its ``url``

	Args:
		record_id:     ID of the current record (used as the centre node id).
		model_name:    Display name for the centre node (e.g. "Employee").
		relationships: List of relationship descriptors::

		                   [
		                       {
		                           "label":       "Projects",
		                           "related_url": "/api/employees/42/projects",
		                           "icon":        "fa-briefcase",   # optional
		                       },
		                       …
		                   ]

		               Each *related_url* must return JSON::

		                   [{"id": "proj-1", "label": "Alpha", "url": "/projects/1"}, …]

		height:        Graph height in pixels (default 300).

	Usage::

		graph = RelationshipGraphWidget(
		    record_id=42,
		    model_name="Employee",
		    relationships=[
		        {"label": "Teams",    "related_url": "/api/employees/42/teams",    "icon": "fa-users"},
		        {"label": "Projects", "related_url": "/api/employees/42/projects", "icon": "fa-briefcase"},
		    ],
		)
		html = graph.render()
	"""

	def __init__(
		self,
		record_id: Any,
		model_name: str,
		relationships: list[dict[str, Any]],
		height: int = 300,
	) -> None:
		self.record_id = record_id
		self.model_name = model_name
		self.relationships = relationships
		self.height = height

	def render(self) -> Markup:
		rels_json = json.dumps(self.relationships)
		record_id = json.dumps(str(self.record_id))
		model_name = json.dumps(self.model_name)
		height = self.height
		# Unique container id so multiple widgets on a page don't collide
		cid = f"rgw_{str(self.record_id).replace('-', '_')}"

		html = f"""
{_CYTOSCAPE_CDN}

<div id="{cid}" style="height:{height}px;border:1px solid #dee2e6;border-radius:4px;background:#fafafa"></div>
<div id="{cid}_legend" style="font-size:0.78em;color:#6c757d;margin-top:4px"></div>

<script>
(function() {{
  var RECORD_ID  = {record_id};
  var MODEL_NAME = {model_name};
  var RELS       = {rels_json};
  var CID        = {json.dumps(cid)};

  document.addEventListener('DOMContentLoaded', function() {{
    var elements = [
      {{data: {{id: 'centre', label: MODEL_NAME, type: 'centre'}}}}
    ];

    var cy = cytoscape({{
      container: document.getElementById(CID),
      elements: elements,
      style: [
        {{
          selector: 'node[type="centre"]',
          style: {{
            'background-color': '#0d6efd',
            'label': 'data(label)',
            'color': '#fff',
            'text-valign': 'center',
            'text-halign': 'center',
            'font-size': '11px',
            'width': 72,
            'height': 72,
            'font-weight': 'bold'
          }}
        }},
        {{
          selector: 'node[type="related"]',
          style: {{
            'background-color': '#198754',
            'label': 'data(label)',
            'color': '#fff',
            'text-valign': 'center',
            'text-halign': 'center',
            'font-size': '10px',
            'width': 56,
            'height': 56',
            'cursor': 'pointer'
          }}
        }},
        {{
          selector: 'edge',
          style: {{
            'label': 'data(label)',
            'font-size': '9px',
            'color': '#495057',
            'line-color': '#adb5bd',
            'target-arrow-color': '#adb5bd',
            'target-arrow-shape': 'triangle',
            'curve-style': 'bezier',
            'text-rotation': 'autorotate',
            'text-background-color': '#fafafa',
            'text-background-opacity': 1,
            'text-background-padding': '2px'
          }}
        }}
      ],
      layout: {{name: 'preset'}},
      userZoomingEnabled: true,
      userPanningEnabled: true,
      boxSelectionEnabled: false,
      autoungrabify: true
    }});

    // Click outer node → navigate
    cy.on('tap', 'node[type="related"]', function(e) {{
      var nodeUrl = e.target.data('url');
      if (nodeUrl) window.location.href = nodeUrl;
    }});

    // Load relationships asynchronously and add nodes
    var legend = document.getElementById(CID + '_legend');
    var relColors = ['#198754','#0dcaf0','#fd7e14','#6f42c1','#d63384','#20c997'];
    var relEdgeCount = 0;

    RELS.forEach(function(rel, ri) {{
      fetch(rel.related_url)
        .then(function(r) {{
          if (!r.ok) throw new Error('HTTP ' + r.status);
          return r.json();
        }})
        .then(function(nodes) {{
          nodes.forEach(function(n, ni) {{
            var nodeId = 'rel_' + ri + '_' + ni;
            cy.add([
              {{
                group: 'nodes',
                data: {{
                  id: nodeId,
                  label: n.label || String(n.id),
                  type: 'related',
                  url: n.url || null
                }}
              }},
              {{
                group: 'edges',
                data: {{
                  id: 'e_' + ri + '_' + ni,
                  source: 'centre',
                  target: nodeId,
                  label: rel.label
                }}
              }}
            ]);
            relEdgeCount++;
          }});

          // Re-layout after each batch so nodes spread nicely
          cy.layout({{
            name: 'concentric',
            concentric: function(node) {{
              return node.data('type') === 'centre' ? 2 : 1;
            }},
            levelWidth: function() {{ return 1; }},
            minNodeSpacing: 20,
            animate: true,
            animationDuration: 300
          }}).run();

          // Update legend
          var legItems = RELS.map(function(r2, i2) {{
            var icon = r2.icon ? '<i class="fa ' + r2.icon + '"></i> ' : '';
            return icon + r2.label;
          }});
          legend.innerHTML = 'Relationships: ' + legItems.join(' &nbsp;|&nbsp; ');
        }})
        .catch(function(err) {{
          console.warn('RelationshipGraphWidget: failed to load', rel.related_url, err);
        }});
    }});
  }});
}})();
</script>
"""
		return Markup(html)
