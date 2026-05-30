"""
pgappforge/plugins/reports/designer.py

ReportDesignerView — drag-and-drop banded report layout editor.

Endpoints registered under /reports/designer:
    GET  /reports/designer/             → list all reports
    GET  /reports/designer/<id>         → open the canvas for report <id>
    POST /reports/designer/<id>/band    → add a band
    DELETE /reports/designer/<id>/band/<band_id>  → remove a band
    POST /reports/designer/<id>/field   → add a field to a band
    PUT  /reports/designer/<id>/field/<fid>       → update field position/props
    DELETE /reports/designer/<id>/field/<fid>     → remove a field
    GET  /reports/designer/<id>/preview → HTML preview (first 10 rows)
    GET  /reports/designer/<id>/columns → JSON list of SQL column names

The canvas UI is self-contained HTML + JavaScript (Bootstrap 3 + SortableJS
from CDN).  No server-side templates are required.
"""

from __future__ import annotations

import json
import logging
import textwrap
from typing import Any

from flask import abort, jsonify, make_response, request, url_for

from pgappforge import BaseView, expose
from pgappforge.security.decorators import has_access

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# HTML/CSS/JS helpers
# ---------------------------------------------------------------------------

_CDN = {
	"bootstrap_css":   "https://maxcdn.bootstrapcdn.com/bootstrap/3.3.7/css/bootstrap.min.css",
	"bootstrap_js":    "https://maxcdn.bootstrapcdn.com/bootstrap/3.3.7/js/bootstrap.min.js",
	"jquery":          "https://code.jquery.com/jquery-3.7.1.min.js",
	"sortablejs":      "https://cdn.jsdelivr.net/npm/sortablejs@1.15.2/Sortable.min.js",
	"fa_css":          "https://maxcdn.bootstrapcdn.com/font-awesome/4.7.0/css/font-awesome.min.css",
}

_BAND_TYPES = [
	"title", "page_header", "column_header",
	"group_header", "detail", "group_footer",
	"summary", "page_footer",
]

_FIELD_TYPES = [
	("text",      "fa-font",        "Text"),
	("number",    "fa-hashtag",     "Number"),
	("date",      "fa-calendar",    "Date"),
	("image",     "fa-picture-o",   "Image"),
	("line",      "fa-minus",       "Line"),
	("box",       "fa-square-o",    "Box"),
	("chart",     "fa-bar-chart",   "Chart"),
	("subreport", "fa-file-text-o", "Subreport"),
]


def _css() -> str:
	return textwrap.dedent("""\
		<style>
		html, body { height: 100%; margin: 0; padding: 0; }
		body { font-family: Arial, sans-serif; font-size: 13px; background: #f4f4f4; }

		/* ── layout ─────────────────────────────────────────────────── */
		#designer-root { display: flex; height: 100vh; overflow: hidden; }
		#panel-left  { width: 200px; min-width: 180px; background: #2c3e50; color: #ecf0f1;
		               display: flex; flex-direction: column; flex-shrink: 0; }
		#panel-canvas{ flex: 1; overflow-y: auto; background: #ccc; padding: 20px; }
		#panel-right { width: 260px; min-width: 240px; background: #fff; border-left: 1px solid #ddd;
		               overflow-y: auto; flex-shrink: 0; }

		/* ── left sidebar ─────────────────────────────────────────────── */
		#panel-left h5 { margin: 0; padding: 12px 14px; background: #1a252f;
		                 font-size: 11px; text-transform: uppercase; letter-spacing: 1px; }
		.band-item { display: flex; align-items: center; justify-content: space-between;
		             padding: 7px 12px; border-bottom: 1px solid #3d5166; cursor: pointer; }
		.band-item:hover { background: #3d5166; }
		.band-item.active { background: #2980b9; }
		.band-item .badge { background: #7f8c8d; font-size: 10px; }
		#btn-add-band { margin: 8px; }
		.field-palette { padding: 8px; }
		.field-palette h6 { font-size: 10px; text-transform: uppercase;
		                    letter-spacing: 1px; color: #95a5a6; margin: 8px 0 4px; }
		.palette-item { display: flex; align-items: center; gap: 6px;
		                padding: 5px 8px; border-radius: 4px; cursor: grab;
		                user-select: none; }
		.palette-item:hover { background: #3d5166; }
		.palette-item i { width: 14px; text-align: center; }

		/* ── canvas ──────────────────────────────────────────────────── */
		.rpt-page { background: #fff; width: 210mm; min-height: 297mm;
		            margin: 0 auto; box-shadow: 0 3px 12px rgba(0,0,0,.3);
		            position: relative; }
		.rpt-page.landscape { width: 297mm; min-height: 210mm; }
		.rpt-band { position: relative; border: 1px dashed #aaa; min-height: 20px;
		            box-sizing: border-box; transition: border-color .2s; }
		.rpt-band:hover { border-color: #2980b9; }
		.rpt-band.active { border-color: #e74c3c; border-style: solid; }
		.rpt-band-label { position: absolute; left: 2px; top: 2px;
		                  font-size: 9px; color: #999; text-transform: uppercase;
		                  letter-spacing: .5px; pointer-events: none; }
		.rpt-field-el { position: absolute; border: 1px solid transparent; box-sizing: border-box;
		                cursor: move; display: flex; align-items: center; overflow: hidden;
		                font-size: 11px; padding: 1px 3px; }
		.rpt-field-el:hover  { border-color: #3498db; }
		.rpt-field-el.active { border-color: #e74c3c; box-shadow: 0 0 0 1px #e74c3c; }
		.rpt-field-el.type-line { border-top: 1px solid #333 !important; height: 2px !important; }
		.rpt-field-el.type-box  { border: 1px solid #333 !important; background: transparent; }
		.handle-resize { position: absolute; right: 0; bottom: 0; width: 8px; height: 8px;
		                 cursor: se-resize; background: #3498db; opacity: .6; }

		/* ── right panel ─────────────────────────────────────────────── */
		#panel-right h5 { margin: 0; padding: 10px 14px; background: #ecf0f1;
		                  border-bottom: 1px solid #ddd; font-size: 12px; }
		.prop-section { padding: 10px 14px; border-bottom: 1px solid #eee; }
		.prop-section label { font-size: 11px; font-weight: 600; color: #555; display: block; margin-bottom: 3px; }
		.prop-section input, .prop-section select, .prop-section textarea {
		    width: 100%; box-sizing: border-box; padding: 4px 6px;
		    border: 1px solid #ccc; border-radius: 3px; font-size: 12px; }
		.prop-section textarea { height: 56px; resize: vertical; }
		.prop-section .row { margin: 0 -4px; }
		.prop-section .col-xs-6 { padding: 0 4px; }
		.prop-btn { margin-top: 6px; width: 100%; }

		/* ── toolbar ─────────────────────────────────────────────────── */
		#toolbar { display: flex; align-items: center; gap: 8px; padding: 8px 16px;
		           background: #34495e; color: #fff; }
		#toolbar h4 { margin: 0; font-size: 14px; flex: 1; }
		#toolbar .btn { padding: 4px 12px; font-size: 12px; }

		/* ── preview overlay ─────────────────────────────────────────── */
		#preview-pane { display: none; position: fixed; top: 0; left: 0; right: 0; bottom: 0;
		                background: rgba(0,0,0,.6); z-index: 1000; overflow: auto; padding: 20px; }
		#preview-inner { background: #fff; max-width: 960px; margin: 0 auto; border-radius: 4px;
		                 overflow: hidden; }
		#preview-inner iframe { width: 100%; height: 70vh; border: none; }
		#preview-close { float: right; margin: 8px; }

		/* ── sortable ghost ──────────────────────────────────────────── */
		.sortable-ghost { opacity: .3; background: #3498db; }
		</style>
	""")


def _js(report_id: int, api_base: str) -> str:
	"""Return the designer JavaScript as a string."""
	return textwrap.dedent(f"""\
		<script>
		const REPORT_ID  = {report_id};
		const API_BASE   = "{api_base}";

		// ── state ────────────────────────────────────────────────────────
		let activeBandId  = null;
		let activeFieldId = null;
		let dragFieldType = null;     // type being dragged from palette
		const MM_TO_PX = 3.7795;     // 1 mm ≈ 3.78 px at 96 dpi

		// ── helpers ──────────────────────────────────────────────────────
		function apiFetch(method, path, body) {{
		    const opts = {{ method, headers: {{'Content-Type':'application/json'}} }};
		    if (body) opts.body = JSON.stringify(body);
		    return fetch(API_BASE + path, opts).then(r => r.json());
		}}

		function mmToPx(mm) {{ return mm * MM_TO_PX; }}
		function pxToMm(px) {{ return px / MM_TO_PX; }}

		// ── band selection ────────────────────────────────────────────────
		function selectBand(bandId) {{
		    activeBandId = bandId;
		    activeFieldId = null;
		    document.querySelectorAll('.rpt-band').forEach(el =>
		        el.classList.toggle('active', el.dataset.bandId == bandId));
		    document.querySelectorAll('.band-item').forEach(el =>
		        el.classList.toggle('active', el.dataset.bandId == bandId));
		    showBandProps(bandId);
		}}

		function showBandProps(bandId) {{
		    const band = document.querySelector(`.rpt-band[data-band-id="${{bandId}}"]`);
		    if (!band) return;
		    document.getElementById('props-title').textContent = 'Band Properties';
		    document.getElementById('props-content').innerHTML = `
		        <div class="prop-section">
		          <label>Band Type</label>
		          <span class="badge">${{band.dataset.bandType}}</span>
		        </div>
		        <div class="prop-section">
		          <label>Height (mm)</label>
		          <input type="number" id="prop-band-height" value="${{band.dataset.height}}" step="1" min="4">
		        </div>
		        <div class="prop-section">
		          <label>Background Color</label>
		          <input type="color" id="prop-band-bg" value="${{band.dataset.bg || '#ffffff'}}">
		        </div>
		        <div class="prop-section">
		          <button class="btn btn-xs btn-primary prop-btn" onclick="applyBandProps(${{bandId}})">Apply</button>
		          <button class="btn btn-xs btn-danger prop-btn" onclick="removeBand(${{bandId}})">Remove Band</button>
		        </div>
		    `;
		}}

		function applyBandProps(bandId) {{
		    const height = parseFloat(document.getElementById('prop-band-height').value);
		    const bg     = document.getElementById('prop-band-bg').value;
		    const band   = document.querySelector(`.rpt-band[data-band-id="${{bandId}}"]`);
		    if (!band) return;
		    band.style.minHeight  = mmToPx(height) + 'px';
		    band.dataset.height   = height;
		    band.style.background = bg;
		    band.dataset.bg       = bg;
		    apiFetch('PATCH', `/band/${{bandId}}`, {{ height_mm: height, background_color: bg }});
		}}

		// ── add / remove bands ────────────────────────────────────────────
		function addBand() {{
		    const sel = document.getElementById('new-band-type');
		    if (!sel) return;
		    const bandType = sel.value;
		    apiFetch('POST', `/band`, {{ report_id: REPORT_ID, band_type: bandType, height_mm: 20 }})
		        .then(data => {{
		            if (data.band) renderBand(data.band);
		        }});
		}}

		function removeBand(bandId) {{
		    if (!confirm('Remove this band and all its fields?')) return;
		    apiFetch('DELETE', `/band/${{bandId}}`)
		        .then(() => {{
		            document.querySelector(`.rpt-band[data-band-id="${{bandId}}"]`)?.remove();
		            document.querySelector(`.band-item[data-band-id="${{bandId}}"]`)?.remove();
		            if (activeBandId == bandId) activeBandId = null;
		        }});
		}}

		function renderBand(band) {{
		    // Canvas element
		    const canvas = document.getElementById('rpt-canvas');
		    const el = document.createElement('div');
		    el.className = 'rpt-band';
		    el.dataset.bandId   = band.id;
		    el.dataset.bandType = band.band_type;
		    el.dataset.height   = band.height_mm;
		    el.dataset.bg       = band.background_color;
		    el.style.minHeight  = mmToPx(band.height_mm) + 'px';
		    el.style.background = band.background_color;
		    el.innerHTML = `<span class="rpt-band-label">${{band.band_type}}</span>`;
		    el.addEventListener('click', e => {{
		        if (e.target.classList.contains('rpt-field-el') ||
		            e.target.closest('.rpt-field-el')) return;
		        selectBand(band.id);
		    }});
		    // Allow drop from palette
		    el.addEventListener('dragover', e => e.preventDefault());
		    el.addEventListener('drop', e => {{
		        e.preventDefault();
		        const rect   = el.getBoundingClientRect();
		        const x_mm   = pxToMm(e.clientX - rect.left);
		        const y_mm   = pxToMm(e.clientY - rect.top);
		        addField(band.id, dragFieldType, x_mm, y_mm, el);
		    }});
		    canvas.appendChild(el);

		    // Sidebar entry
		    const sidebar = document.getElementById('band-list');
		    const li = document.createElement('div');
		    li.className = 'band-item';
		    li.dataset.bandId = band.id;
		    li.innerHTML = `<span>${{band.band_type}}</span>
		        <span class="badge">${{band.id}}</span>`;
		    li.addEventListener('click', () => selectBand(band.id));
		    sidebar.appendChild(li);
		}}

		// ── field palette drag ────────────────────────────────────────────
		document.querySelectorAll('.palette-item').forEach(item => {{
		    item.addEventListener('dragstart', e => {{
		        dragFieldType = item.dataset.ftype;
		        e.dataTransfer.effectAllowed = 'copy';
		    }});
		}});

		// ── add / update / remove fields ──────────────────────────────────
		function addField(bandId, ftype, x_mm, y_mm, bandEl) {{
		    const body = {{
		        band_id: bandId, field_type: ftype,
		        x_mm, y_mm, width_mm: 40, height_mm: 8,
		        style: {{}}
		    }};
		    apiFetch('POST', `/field`, body).then(data => {{
		        if (data.field) renderField(data.field, bandEl);
		    }});
		}}

		function renderField(field, bandEl) {{
		    const el = document.createElement('div');
		    el.className = `rpt-field-el type-${{field.field_type}}`;
		    el.dataset.fieldId = field.id;
		    el.style.left    = mmToPx(field.x_mm)      + 'px';
		    el.style.top     = mmToPx(field.y_mm)      + 'px';
		    el.style.width   = mmToPx(field.width_mm)  + 'px';
		    el.style.height  = mmToPx(field.height_mm) + 'px';
		    el.title         = field.data_binding || field.field_type;
		    el.textContent   = field.style?.text || field.data_binding || `[${{field.field_type}}]`;
		    el.innerHTML    += '<div class="handle-resize"></div>';

		    makeDraggable(el, bandEl, field);
		    makeResizable(el, field);
		    el.addEventListener('click', e => {{
		        e.stopPropagation();
		        selectField(field.id, field);
		    }});
		    bandEl.appendChild(el);
		}}

		function selectField(fieldId, field) {{
		    activeFieldId = fieldId;
		    document.querySelectorAll('.rpt-field-el').forEach(el =>
		        el.classList.toggle('active', el.dataset.fieldId == fieldId));
		    showFieldProps(field);
		}}

		function showFieldProps(field) {{
		    document.getElementById('props-title').textContent = 'Field Properties';
		    document.getElementById('props-content').innerHTML = `
		        <div class="prop-section">
		          <label>Data Binding</label>
		          <input type="text" id="prop-binding" value="${{field.data_binding || ''}}"
		                 placeholder="SQL column name">
		        </div>
		        <div class="prop-section">
		          <label>Format String</label>
		          <input type="text" id="prop-format" value="${{field.format_string || ''}}"
		                 placeholder="e.g. {{:,.2f}}">
		        </div>
		        <div class="prop-section">
		          <label>Static Text</label>
		          <input type="text" id="prop-text" value="${{field.style?.text || ''}}">
		        </div>
		        <div class="prop-section row">
		          <div class="col-xs-6">
		            <label>X (mm)</label>
		            <input type="number" id="prop-x" value="${{field.x_mm.toFixed(1)}}" step="0.5">
		          </div>
		          <div class="col-xs-6">
		            <label>Y (mm)</label>
		            <input type="number" id="prop-y" value="${{field.y_mm.toFixed(1)}}" step="0.5">
		          </div>
		        </div>
		        <div class="prop-section row">
		          <div class="col-xs-6">
		            <label>Width (mm)</label>
		            <input type="number" id="prop-w" value="${{field.width_mm.toFixed(1)}}" step="0.5">
		          </div>
		          <div class="col-xs-6">
		            <label>Height (mm)</label>
		            <input type="number" id="prop-h" value="${{field.height_mm.toFixed(1)}}" step="0.5">
		          </div>
		        </div>
		        <div class="prop-section">
		          <label>Font Size</label>
		          <input type="number" id="prop-fs" value="${{field.style?.font_size || 10}}" min="6" max="72">
		        </div>
		        <div class="prop-section row">
		          <div class="col-xs-6">
		            <label>Color</label>
		            <input type="color" id="prop-color" value="${{field.style?.color || '#000000'}}">
		          </div>
		          <div class="col-xs-6">
		            <label>BG Color</label>
		            <input type="color" id="prop-bg" value="${{field.style?.bg_color || '#ffffff'}}">
		          </div>
		        </div>
		        <div class="prop-section">
		          <label>Align</label>
		          <select id="prop-align">
		            <option value="left">Left</option>
		            <option value="center">Center</option>
		            <option value="right">Right</option>
		          </select>
		        </div>
		        <div class="prop-section">
		          <button class="btn btn-xs btn-primary prop-btn" onclick="applyFieldProps(${{field.id}})">Apply</button>
		          <button class="btn btn-xs btn-danger  prop-btn" onclick="removeField(${{field.id}})">Remove</button>
		        </div>
		    `;
		    document.getElementById('prop-align').value = field.style?.align || 'left';
		}}

		function applyFieldProps(fieldId) {{
		    const body = {{
		        data_binding:  document.getElementById('prop-binding').value || null,
		        format_string: document.getElementById('prop-format').value  || null,
		        x_mm:   parseFloat(document.getElementById('prop-x').value),
		        y_mm:   parseFloat(document.getElementById('prop-y').value),
		        width_mm:  parseFloat(document.getElementById('prop-w').value),
		        height_mm: parseFloat(document.getElementById('prop-h').value),
		        style: {{
		            text:      document.getElementById('prop-text').value,
		            font_size: parseInt(document.getElementById('prop-fs').value),
		            color:     document.getElementById('prop-color').value,
		            bg_color:  document.getElementById('prop-bg').value,
		            align:     document.getElementById('prop-align').value,
		        }}
		    }};
		    apiFetch('PUT', `/field/${{fieldId}}`, body).then(() => {{
		        const el = document.querySelector(`.rpt-field-el[data-field-id="${{fieldId}}"]`);
		        if (!el) return;
		        el.style.left   = mmToPx(body.x_mm)      + 'px';
		        el.style.top    = mmToPx(body.y_mm)      + 'px';
		        el.style.width  = mmToPx(body.width_mm)  + 'px';
		        el.style.height = mmToPx(body.height_mm) + 'px';
		        const label = el.querySelector('.handle-resize');
		        el.childNodes[0].textContent = body.style.text || body.data_binding || '';
		    }});
		}}

		function removeField(fieldId) {{
		    apiFetch('DELETE', `/field/${{fieldId}}`).then(() => {{
		        document.querySelector(`.rpt-field-el[data-field-id="${{fieldId}}"]`)?.remove();
		        activeFieldId = null;
		        document.getElementById('props-content').innerHTML = '<p class="text-muted" style="padding:14px">Select an element</p>';
		    }});
		}}

		// ── drag-move field ───────────────────────────────────────────────
		function makeDraggable(el, bandEl, field) {{
		    let startX, startY, origLeft, origTop;
		    el.addEventListener('mousedown', e => {{
		        if (e.target.classList.contains('handle-resize')) return;
		        e.preventDefault();
		        startX   = e.clientX; startY = e.clientY;
		        origLeft = el.offsetLeft; origTop = el.offsetTop;
		        function onMove(e) {{
		            const dx = e.clientX - startX, dy = e.clientY - startY;
		            el.style.left = (origLeft + dx) + 'px';
		            el.style.top  = (origTop  + dy) + 'px';
		        }}
		        function onUp() {{
		            field.x_mm = pxToMm(el.offsetLeft);
		            field.y_mm = pxToMm(el.offsetTop);
		            apiFetch('PUT', `/field/${{field.id}}`, {{ x_mm: field.x_mm, y_mm: field.y_mm }});
		            document.removeEventListener('mousemove', onMove);
		            document.removeEventListener('mouseup',  onUp);
		        }}
		        document.addEventListener('mousemove', onMove);
		        document.addEventListener('mouseup',  onUp);
		    }});
		}}

		// ── resize field ──────────────────────────────────────────────────
		function makeResizable(el, field) {{
		    const handle = el.querySelector('.handle-resize');
		    handle.addEventListener('mousedown', e => {{
		        e.preventDefault(); e.stopPropagation();
		        const startX = e.clientX, startY = e.clientY;
		        const origW  = el.offsetWidth, origH = el.offsetHeight;
		        function onMove(e) {{
		            el.style.width  = Math.max(20, origW + e.clientX - startX) + 'px';
		            el.style.height = Math.max(10, origH + e.clientY - startY) + 'px';
		        }}
		        function onUp() {{
		            field.width_mm  = pxToMm(el.offsetWidth);
		            field.height_mm = pxToMm(el.offsetHeight);
		            apiFetch('PUT', `/field/${{field.id}}`, {{
		                width_mm:  field.width_mm,
		                height_mm: field.height_mm
		            }});
		            document.removeEventListener('mousemove', onMove);
		            document.removeEventListener('mouseup',  onUp);
		        }}
		        document.addEventListener('mousemove', onMove);
		        document.addEventListener('mouseup',  onUp);
		    }});
		}}

		// ── preview ───────────────────────────────────────────────────────
		function openPreview() {{
		    const pane = document.getElementById('preview-pane');
		    const iframe = document.getElementById('preview-frame');
		    iframe.src = API_BASE + '/preview';
		    pane.style.display = 'block';
		}}
		function closePreview() {{
		    document.getElementById('preview-pane').style.display = 'none';
		    document.getElementById('preview-frame').src = '';
		}}

		// ── keyboard shortcuts ────────────────────────────────────────────
		document.addEventListener('keydown', e => {{
		    if (e.key === 'Delete' && activeFieldId) removeField(activeFieldId);
		    if (e.key === 'Escape') closePreview();
		}});
		</script>
	""")


def _list_html(reports: list[dict[str, Any]]) -> str:
	rows = ""
	for r in reports:
		rows += (
			f'<tr>'
			f'<td>{r["id"]}</td>'
			f'<td><a href="{r["id"]}">{_he(r["name"])}</a></td>'
			f'<td>{_he(r.get("description") or "")}</td>'
			f'<td>{_he(r.get("paper_size", "A4"))} / {_he(r.get("orientation", "portrait"))}</td>'
			f'<td>'
			f'<a href="{r["id"]}" class="btn btn-xs btn-primary">Design</a> '
			f'</td>'
			f'</tr>'
		)
	return textwrap.dedent(f"""\
		<!DOCTYPE html><html lang="en"><head>
		<meta charset="utf-8">
		<title>Report Designer — Reports</title>
		<link rel="stylesheet" href="{_CDN['bootstrap_css']}">
		<link rel="stylesheet" href="{_CDN['fa_css']}">
		</head><body style="padding:30px">
		<h2><i class="fa fa-file-text-o"></i> Report Designer</h2>
		<a href="new" class="btn btn-success btn-sm"><i class="fa fa-plus"></i> New Report</a>
		<hr>
		<table class="table table-bordered table-hover table-condensed">
		<thead><tr><th>#</th><th>Name</th><th>Description</th><th>Paper</th><th></th></tr></thead>
		<tbody>{rows}</tbody>
		</table>
		</body></html>
	""")


def _he(text: str) -> str:
	"""HTML-escape."""
	return (
		str(text)
		.replace("&", "&amp;")
		.replace("<", "&lt;")
		.replace(">", "&gt;")
		.replace('"', "&quot;")
	)


# ---------------------------------------------------------------------------
# View
# ---------------------------------------------------------------------------

class ReportDesignerView(BaseView):
	"""
	Drag-and-drop banded report layout editor.

	Registered at ``/reports/designer`` by the ReportsPlugin.
	"""

	route_base  = "/reports/designer"
	default_view = "index"

	# ------------------------------------------------------------------ #
	# List / CRUD routes                                                  #
	# ------------------------------------------------------------------ #

	@expose("/")
	@has_access
	def index(self):
		"""List all reports."""
		session = self._get_session()
		from .models import Report
		reports = session.execute(
			__import__("sqlalchemy").select(Report).order_by(Report.name)
		).scalars().all()
		data = [
			{
				"id":          r.id,
				"name":        r.name,
				"description": r.description,
				"paper_size":  r.paper_size.value,
				"orientation": r.orientation.value,
			}
			for r in reports
		]
		return make_response(_list_html(data), 200)

	@expose("/<int:report_id>")
	@has_access
	def canvas(self, report_id: int):
		"""Render the designer canvas for a specific report."""
		session = self._get_session()
		from .models import Report, BandType
		report  = session.get(Report, report_id)
		if report is None:
			abort(404)

		api_base = f"/reports/designer/{report_id}"
		orient   = report.orientation.value
		bands    = report.band_list()

		# Build initial band JS data
		bands_json = json.dumps([
			{
				"id":               b.id,
				"band_type":        b.band_type.value,
				"height_mm":        b.height_mm,
				"background_color": b.background_color,
			}
			for b in bands
		])

		# Build initial field JS data grouped by band
		fields_by_band: dict[int, list[dict]] = {}
		for b in bands:
			fields_by_band[b.id] = [
				{
					"id":           f.id,
					"band_id":      f.band_id,
					"field_type":   f.field_type.value,
					"x_mm":         f.x_mm,
					"y_mm":         f.y_mm,
					"width_mm":     f.width_mm,
					"height_mm":    f.height_mm,
					"data_binding": f.data_binding,
					"format_string":f.format_string,
					"style":        f.style or {},
				}
				for f in b.field_list()
			]

		band_types_opts = "".join(
			f'<option value="{bt}">{bt.replace("_"," ").title()}</option>'
			for bt in _BAND_TYPES
		)
		palette_items = "".join(
			f'<div class="palette-item" draggable="true" data-ftype="{ft}" title="{label}">'
			f'<i class="fa {icon}"></i> {label}</div>'
			for ft, icon, label in _FIELD_TYPES
		)

		html = textwrap.dedent(f"""\
			<!DOCTYPE html>
			<html lang="en">
			<head>
			  <meta charset="utf-8">
			  <title>Designer: {_he(report.name)}</title>
			  <link rel="stylesheet" href="{_CDN['bootstrap_css']}">
			  <link rel="stylesheet" href="{_CDN['fa_css']}">
			  {_css()}
			</head>
			<body>
			<div id="toolbar">
			  <h4><i class="fa fa-pencil-square-o"></i> {_he(report.name)}</h4>
			  <a href="/reports/designer/" class="btn btn-default btn-sm">
			    <i class="fa fa-arrow-left"></i> Reports
			  </a>
			  <button class="btn btn-info btn-sm" onclick="openPreview()">
			    <i class="fa fa-eye"></i> Preview
			  </button>
			  <a href="/reports/download/{report_id}?format=pdf"
			     class="btn btn-danger btn-sm" target="_blank">
			    <i class="fa fa-file-pdf-o"></i> PDF
			  </a>
			  <a href="/reports/download/{report_id}?format=xlsx"
			     class="btn btn-success btn-sm" target="_blank">
			    <i class="fa fa-file-excel-o"></i> XLSX
			  </a>
			  <a href="/reports/download/{report_id}?format=csv"
			     class="btn btn-warning btn-sm" target="_blank">
			    <i class="fa fa-file-text-o"></i> CSV
			  </a>
			</div>
			<div id="designer-root">

			  <!-- left: band list + field palette -->
			  <div id="panel-left">
			    <h5><i class="fa fa-bars"></i> Bands</h5>
			    <div id="band-list"></div>
			    <div style="padding:8px;border-top:1px solid #3d5166;margin-top:8px">
			      <select id="new-band-type" class="form-control input-sm" style="margin-bottom:6px">
			        {band_types_opts}
			      </select>
			      <button class="btn btn-xs btn-success" style="width:100%" onclick="addBand()">
			        <i class="fa fa-plus"></i> Add Band
			      </button>
			    </div>
			    <h5 style="margin-top:12px"><i class="fa fa-th"></i> Fields</h5>
			    <div class="field-palette">
			      <h6>Drag onto canvas</h6>
			      {palette_items}
			    </div>
			  </div>

			  <!-- centre: canvas -->
			  <div id="panel-canvas">
			    <div id="rpt-canvas" class="rpt-page {orient}"></div>
			  </div>

			  <!-- right: properties -->
			  <div id="panel-right">
			    <h5 id="props-title"><i class="fa fa-sliders"></i> Properties</h5>
			    <div id="props-content">
			      <p class="text-muted" style="padding:14px">Select an element to edit</p>
			    </div>
			  </div>
			</div>

			<!-- preview overlay -->
			<div id="preview-pane">
			  <div id="preview-inner">
			    <button id="preview-close" class="btn btn-default btn-sm" onclick="closePreview()">
			      <i class="fa fa-times"></i> Close
			    </button>
			    <h4 style="padding:10px 14px;margin:0">Preview — first 10 rows</h4>
			    <iframe id="preview-frame" src=""></iframe>
			  </div>
			</div>

			<script src="{_CDN['jquery']}"></script>
			<script src="{_CDN['bootstrap_js']}"></script>
			<script src="{_CDN['sortablejs']}"></script>
			{_js(report_id, api_base)}
			<script>
			// ── hydrate canvas from server data ───────────────────────────
			(function() {{
			    const bands  = {bands_json};
			    const fByBand = {json.dumps(fields_by_band)};
			    bands.forEach(band => {{
			        renderBand(band);
			        const bandEl = document.querySelector(`.rpt-band[data-band-id="${{band.id}}"]`);
			        if (!bandEl) return;
			        const fields = fByBand[band.id] || [];
			        fields.forEach(f => renderField(f, bandEl));
			    }});

			    // make band list sortable (re-orders bands on canvas)
			    Sortable.create(document.getElementById('band-list'), {{
			        animation: 150,
			        onEnd: function(evt) {{
			            const bandId   = evt.item.dataset.bandId;
			            const newIndex = evt.newIndex;
			            fetch(API_BASE + '/band/' + bandId + '/reorder', {{
			                method: 'POST',
			                headers: {{'Content-Type':'application/json'}},
			                body: JSON.stringify({{ position: newIndex }})
			            }});
			        }}
			    }});
			}})();
			</script>
			</body></html>
		""")
		return make_response(html, 200)

	# ------------------------------------------------------------------ #
	# Band API                                                            #
	# ------------------------------------------------------------------ #

	@expose("/<int:report_id>/band", methods=("POST",))
	@has_access
	def add_band(self, report_id: int):
		session   = self._get_session()
		from .models import Report, ReportBand, BandType
		report    = session.get(Report, report_id)
		if report is None:
			abort(404)

		data      = request.get_json(force=True) or {}
		band_type = data.get("band_type", "detail")
		try:
			bt = BandType(band_type)
		except ValueError:
			bt = BandType.DETAIL

		# Position = current max + 1
		existing  = report.band_list()
		position  = max((b.position for b in existing), default=-1) + 1

		band = ReportBand(
			report_id        = report_id,
			band_type        = bt,
			position         = position,
			height_mm        = float(data.get("height_mm", 20)),
			background_color = data.get("background_color", "#ffffff"),
		)
		session.add(band)
		session.commit()
		session.refresh(band)

		return jsonify({
			"band": {
				"id":               band.id,
				"band_type":        band.band_type.value,
				"height_mm":        band.height_mm,
				"background_color": band.background_color,
				"position":         band.position,
			}
		})

	@expose("/<int:report_id>/band/<int:band_id>", methods=("DELETE",))
	@has_access
	def remove_band(self, report_id: int, band_id: int):
		session = self._get_session()
		from .models import ReportBand
		band    = session.get(ReportBand, band_id)
		if band is None or band.report_id != report_id:
			abort(404)
		session.delete(band)
		session.commit()
		return jsonify({"ok": True})

	@expose("/<int:report_id>/band/<int:band_id>", methods=("PATCH",))
	@has_access
	def update_band(self, report_id: int, band_id: int):
		session = self._get_session()
		from .models import ReportBand
		band    = session.get(ReportBand, band_id)
		if band is None or band.report_id != report_id:
			abort(404)
		data = request.get_json(force=True) or {}
		if "height_mm"        in data: band.height_mm        = float(data["height_mm"])
		if "background_color" in data: band.background_color = data["background_color"]
		session.commit()
		return jsonify({"ok": True})

	@expose("/<int:report_id>/band/<int:band_id>/reorder", methods=("POST",))
	@has_access
	def reorder_band(self, report_id: int, band_id: int):
		session  = self._get_session()
		from .models import ReportBand, Report
		import sqlalchemy as sa
		band     = session.get(ReportBand, band_id)
		if band is None or band.report_id != report_id:
			abort(404)
		data     = request.get_json(force=True) or {}
		position = int(data.get("position", band.position))
		band.position = position
		session.commit()
		return jsonify({"ok": True})

	# ------------------------------------------------------------------ #
	# Field API                                                           #
	# ------------------------------------------------------------------ #

	@expose("/<int:report_id>/field", methods=("POST",))
	@has_access
	def add_field(self, report_id: int):
		session   = self._get_session()
		from .models import ReportBand, ReportField, FieldType
		data      = request.get_json(force=True) or {}
		band_id   = data.get("band_id")
		band      = session.get(ReportBand, band_id)
		if band is None or band.report_id != report_id:
			abort(404)

		try:
			ft = FieldType(data.get("field_type", "text"))
		except ValueError:
			ft = FieldType.TEXT

		field = ReportField(
			band_id       = band_id,
			field_type    = ft,
			x_mm          = float(data.get("x_mm", 0)),
			y_mm          = float(data.get("y_mm", 0)),
			width_mm      = float(data.get("width_mm", 40)),
			height_mm     = float(data.get("height_mm", 8)),
			data_binding  = data.get("data_binding"),
			format_string = data.get("format_string"),
			style         = data.get("style", {}),
		)
		session.add(field)
		session.commit()
		session.refresh(field)

		return jsonify({
			"field": {
				"id":           field.id,
				"band_id":      field.band_id,
				"field_type":   field.field_type.value,
				"x_mm":         field.x_mm,
				"y_mm":         field.y_mm,
				"width_mm":     field.width_mm,
				"height_mm":    field.height_mm,
				"data_binding": field.data_binding,
				"format_string":field.format_string,
				"style":        field.style or {},
			}
		})

	@expose("/<int:report_id>/field/<int:field_id>", methods=("PUT",))
	@has_access
	def update_field(self, report_id: int, field_id: int):
		session = self._get_session()
		from .models import ReportField
		field   = session.get(ReportField, field_id)
		if field is None:
			abort(404)
		# Verify ownership
		if field.band.report_id != report_id:
			abort(404)
		data = request.get_json(force=True) or {}
		if "x_mm"          in data: field.x_mm          = float(data["x_mm"])
		if "y_mm"          in data: field.y_mm          = float(data["y_mm"])
		if "width_mm"      in data: field.width_mm      = float(data["width_mm"])
		if "height_mm"     in data: field.height_mm     = float(data["height_mm"])
		if "data_binding"  in data: field.data_binding  = data["data_binding"]
		if "format_string" in data: field.format_string = data["format_string"]
		if "style"         in data:
			existing = dict(field.style or {})
			existing.update(data["style"])
			field.style = existing
		session.commit()
		return jsonify({"ok": True})

	@expose("/<int:report_id>/field/<int:field_id>", methods=("DELETE",))
	@has_access
	def remove_field(self, report_id: int, field_id: int):
		session = self._get_session()
		from .models import ReportField
		field   = session.get(ReportField, field_id)
		if field is None:
			abort(404)
		session.delete(field)
		session.commit()
		return jsonify({"ok": True})

	# ------------------------------------------------------------------ #
	# Preview                                                             #
	# ------------------------------------------------------------------ #

	@expose("/<int:report_id>/preview")
	@has_access
	def preview(self, report_id: int):
		"""Return HTML preview of the report (first 10 rows of data)."""
		session = self._get_session()
		from .engine import ReportEngine
		params  = {k: v for k, v in request.args.items()}
		try:
			engine  = ReportEngine(session, preview_row_limit=10)
			html    = engine.generate_html(report_id, params=params)
		except Exception as exc:
			log.exception("preview failed for report_id=%s", report_id)
			html = f"<pre style='color:red'>Preview error: {_he(str(exc))}</pre>"
		return make_response(html, 200)

	@expose("/<int:report_id>/columns")
	@has_access
	def columns(self, report_id: int):
		"""Return JSON list of column names from the datasource (limit 0 rows)."""
		session = self._get_session()
		from .models import Report
		from sqlalchemy import text
		report  = session.get(Report, report_id)
		if report is None:
			abort(404)
		try:
			if report.is_sql_source:
				result = session.execute(
					text(f"SELECT * FROM ({report.data_source}) __c LIMIT 0")
				)
				cols = list(result.keys())
			else:
				cols = []
		except Exception as exc:
			log.warning("columns fetch failed for report_id=%s: %s", report_id, exc)
			cols = []
		return jsonify({"columns": cols})

	# ------------------------------------------------------------------ #
	# Session helper                                                      #
	# ------------------------------------------------------------------ #

	def _get_session(self):
		"""Retrieve the SQLAlchemy session from the appbuilder / Flask-SQLAlchemy."""
		if hasattr(self, "appbuilder") and self.appbuilder is not None:
			if hasattr(self.appbuilder, "get_session"):
				return self.appbuilder.get_session
		# Fallback: use Flask-SQLAlchemy's db.session via current_app
		from flask import current_app
		db = current_app.extensions.get("sqlalchemy")
		if db is not None:
			return db.session
		raise RuntimeError(
			"Cannot obtain database session — ensure Flask-SQLAlchemy is configured"
		)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = ["ReportDesignerView"]
