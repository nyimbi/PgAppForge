"""
ReportForge report generation wizard — 5-step guided report creation.

Steps:
  1. choose_template  — pick a built-in template or start blank
  2. data_source      — write / paste the SQL query, test it
  3. branding         — company name, logo, colors, watermark
  4. preview          — HTML preview of the report with sample data
  5. save             — name the report and save to DB

Accessible at /reportforge/wizard/
"""

from __future__ import annotations

import logging
from typing import Any

from flask import current_app, jsonify, redirect, request, session, url_for
from pgappforge import BaseView, expose
from pgappforge.security.decorators import has_access

log = logging.getLogger(__name__)

_SESS_KEY = "reportforge_wizard"


def _wizard_state() -> dict[str, Any]:
    return session.get(_SESS_KEY, {})


def _save_state(state: dict[str, Any]) -> None:
    session[_SESS_KEY] = state
    session.modified = True


# ── Shared HTML shell ─────────────────────────────────────────────────────────

_SHELL = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>ReportForge Wizard</title>
<link rel="stylesheet"
  href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css">
<link rel="stylesheet"
  href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
<style>
body {{ background:#f4f6fa; font-family:'Segoe UI',Arial,sans-serif; }}
.topbar {{ background:#0066cc; color:#fff; padding:12px 24px;
           display:flex; align-items:center; gap:12px; }}
.topbar h1 {{ font-size:1.1rem; margin:0; font-weight:700; }}
.steps {{ display:flex; gap:0; background:#fff; border-bottom:1px solid #ddd; }}
.step {{ padding:10px 20px; font-size:13px; color:#888; border-bottom:3px solid transparent; }}
.step.active {{ color:#0066cc; border-bottom-color:#0066cc; font-weight:600; }}
.step.done {{ color:#28a745; border-bottom-color:#28a745; }}
.wizard-body {{ max-width:860px; margin:24px auto; padding:0 16px; }}
.card {{ border-radius:10px; box-shadow:0 2px 10px rgba(0,0,0,.08); }}
.template-card {{ cursor:pointer; border:2px solid #e0e0e0; border-radius:8px;
                  padding:16px; text-align:center; transition:all .2s; }}
.template-card:hover, .template-card.selected {{ border-color:#0066cc; background:#f0f6ff; }}
.template-card i {{ font-size:2rem; color:#0066cc; margin-bottom:8px; }}
#sql-ta {{ font-family:monospace; background:#1e1e2e; color:#cdd6f4;
           border-radius:6px; padding:10px; font-size:13px; resize:vertical; }}
.color-preview {{ width:36px; height:36px; border-radius:50%; border:2px solid #ddd;
                  display:inline-block; vertical-align:middle; }}
</style>
</head>
<body>
<div class="topbar">
  <i class="fas fa-magic fa-lg"></i>
  <h1>ReportForge Wizard</h1>
  <span class="ms-auto" style="font-size:12px;opacity:.8">
    Step {step} of 5
  </span>
</div>
<div class="steps">
  {step_nav}
</div>
<div class="wizard-body">
  {body}
</div>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
{extra_js}
</body>
</html>"""


def _step_nav(current: int) -> str:
    labels = [
        (1, "fa-th-large",  "Template"),
        (2, "fa-database",  "Data Source"),
        (3, "fa-palette",   "Branding"),
        (4, "fa-eye",       "Preview"),
        (5, "fa-save",      "Save"),
    ]
    parts = []
    for n, icon, label in labels:
        cls = "active" if n == current else ("done" if n < current else "")
        parts.append(
            f'<div class="step {cls}">'
            f'<i class="fas {icon} me-1"></i>{n}. {label}</div>'
        )
    return "".join(parts)


def _render(step: int, body: str, extra_js: str = "") -> str:
    return _SHELL.format(
        step=step, step_nav=_step_nav(step),
        body=body, extra_js=extra_js,
    )


# ── Step 1: Choose template ───────────────────────────────────────────────────

def _step1_html() -> str:
    from .report_templates import list_templates
    tmpls = list_templates()
    cards = ""
    for t in tmpls:
        cards += (
            f'<div class="col-4 mb-3">'
            f'<div class="template-card" onclick="pick(\'{t["key"]}\')" id="tc-{t["key"]}">'
            f'<i class="fas {t["icon"]}"></i><br>'
            f'<strong>{t["label"]}</strong>'
            f'<div style="font-size:12px;color:#666;margin-top:4px">{t["description"]}</div>'
            f'</div></div>'
        )
    cards += (
        '<div class="col-4 mb-3">'
        '<div class="template-card" onclick="pick(\'blank\')" id="tc-blank">'
        '<i class="fas fa-file"></i><br>'
        '<strong>Blank Report</strong>'
        '<div style="font-size:12px;color:#666;margin-top:4px">Start from scratch.</div>'
        '</div></div>'
    )
    return f"""
<div class="card p-4">
  <h4 class="mb-3"><i class="fas fa-th-large me-2 text-primary"></i>Choose a Template</h4>
  <p class="text-muted">Pick a built-in template or start blank. You can customise everything in the next steps.</p>
  <div class="row">{cards}</div>
  <form method="POST" action="/reportforge/wizard/step/1" id="f1">
    <input type="hidden" name="template_key" id="tkey" value="">
    <div class="d-flex justify-content-end mt-3">
      <button class="btn btn-primary" id="nextbtn" disabled>
        Next &rarr;
      </button>
    </div>
  </form>
</div>"""


def _step1_js() -> str:
    return """<script>
function pick(key) {
  document.querySelectorAll('.template-card').forEach(c => c.classList.remove('selected'));
  document.getElementById('tc-' + key).classList.add('selected');
  document.getElementById('tkey').value = key;
  document.getElementById('nextbtn').disabled = false;
}
</script>"""


# ── Step 2: Data source ───────────────────────────────────────────────────────

def _step2_html(state: dict) -> str:
    sql = state.get("sql", "SELECT * FROM your_table LIMIT 100;")
    return f"""
<div class="card p-4">
  <h4 class="mb-3"><i class="fas fa-database me-2 text-primary"></i>Data Source</h4>
  <p class="text-muted">Write the SQL query that powers this report. Use <code>:param_name</code> for runtime parameters.</p>
  <form method="POST" action="/reportforge/wizard/step/2">
    <textarea id="sql-ta" name="sql" rows="12" class="form-control mb-3"
      placeholder="SELECT * FROM orders WHERE status = :status">{sql}</textarea>
    <div class="d-flex justify-content-between">
      <div>
        <button type="button" class="btn btn-outline-secondary btn-sm" onclick="testQuery()">
          <i class="fas fa-play me-1"></i>Test Query
        </button>
        <button type="button" class="btn btn-outline-secondary btn-sm ms-2" onclick="aiSql()">
          <i class="fas fa-robot me-1"></i>AI Generate
        </button>
      </div>
      <div>
        <a href="/reportforge/wizard/step/back/2" class="btn btn-outline-secondary btn-sm me-2">&larr; Back</a>
        <button class="btn btn-primary">Next &rarr;</button>
      </div>
    </div>
  </form>
  <div id="test-result" class="mt-3" style="display:none">
    <div class="alert" id="test-msg"></div>
    <div id="test-table" style="overflow-x:auto;max-height:200px;font-size:12px"></div>
  </div>
</div>"""


def _step2_js() -> str:
    return """<script>
async function testQuery() {
  const sql = document.getElementById('sql-ta').value;
  const r = await fetch('/reportforge/sql-editor/api/execute', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({sql, limit: 10})
  });
  const d = await r.json();
  const res = document.getElementById('test-result');
  const msg = document.getElementById('test-msg');
  res.style.display = '';
  if (d.error) {
    msg.className = 'alert alert-danger';
    msg.textContent = 'Error: ' + d.error;
    document.getElementById('test-table').innerHTML = '';
  } else {
    msg.className = 'alert alert-success';
    msg.textContent = d.rows.length + ' rows returned (preview of first 10)';
    const tbl = '<table class="table table-sm table-bordered"><thead><tr>' +
      d.columns.map(c => '<th>' + c + '</th>').join('') + '</tr></thead><tbody>' +
      d.rows.map(row => '<tr>' + d.columns.map(c => '<td>' + (row[c]??'') + '</td>').join('') + '</tr>').join('') +
      '</tbody></table>';
    document.getElementById('test-table').innerHTML = tbl;
  }
}
async function aiSql() {
  const p = prompt('Describe what you want to query:');
  if (!p) return;
  const r = await fetch('/reportforge/sql-editor/api/ai-assist', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({prompt: p})
  });
  const d = await r.json();
  if (d.sql) document.getElementById('sql-ta').value = d.sql;
  else alert('AI error: ' + (d.error || 'no SQL returned'));
}
</script>"""


# ── Step 3: Branding ──────────────────────────────────────────────────────────

def _step3_html(state: dict) -> str:
    b = state.get("branding", {})
    return f"""
<div class="card p-4">
  <h4 class="mb-3"><i class="fas fa-palette me-2 text-primary"></i>Branding</h4>
  <form method="POST" action="/reportforge/wizard/step/3">
    <div class="row g-3">
      <div class="col-6">
        <label class="form-label">Company Name</label>
        <input name="company_name" class="form-control" value="{b.get('company_name','')}">
      </div>
      <div class="col-6">
        <label class="form-label">Logo URL <span class="text-muted">(optional)</span></label>
        <input name="logo_url" class="form-control" placeholder="https://…/logo.png"
               value="{b.get('logo_url','')}">
      </div>
      <div class="col-4">
        <label class="form-label">Primary Colour</label>
        <input type="color" name="primary_color" class="form-control form-control-color"
               value="{b.get('primary_color','#003366')}">
      </div>
      <div class="col-4">
        <label class="form-label">Secondary Colour</label>
        <input type="color" name="secondary_color" class="form-control form-control-color"
               value="{b.get('secondary_color','#666666')}">
      </div>
      <div class="col-4">
        <label class="form-label">Watermark Text <span class="text-muted">(optional)</span></label>
        <input name="watermark_text" class="form-control" placeholder="CONFIDENTIAL"
               value="{b.get('watermark_text','')}">
      </div>
      <div class="col-6">
        <label class="form-label">Custom Footer</label>
        <textarea name="custom_footer_html" class="form-control" rows="2"
          placeholder="Page {{page}} · Generated by ReportForge">{b.get('custom_footer_html','')}</textarea>
      </div>
      <div class="col-6">
        <label class="form-label">Custom Header <span class="text-muted">(HTML)</span></label>
        <textarea name="custom_header_html" class="form-control" rows="2"
          placeholder="Optional HTML header content">{b.get('custom_header_html','')}</textarea>
      </div>
    </div>
    <div class="d-flex justify-content-end mt-4 gap-2">
      <a href="/reportforge/wizard/step/back/3" class="btn btn-outline-secondary btn-sm">&larr; Back</a>
      <button class="btn btn-primary">Next &rarr;</button>
    </div>
  </form>
</div>"""


# ── Step 4: Preview ───────────────────────────────────────────────────────────

def _step4_html(preview_html: str, error: str | None = None) -> str:
    content = (
        f'<div class="alert alert-danger">{error}</div>'
        if error else
        f'<div style="border:1px solid #ddd;border-radius:6px;overflow:auto;max-height:500px">'
        f'{preview_html}</div>'
    )
    return f"""
<div class="card p-4">
  <h4 class="mb-3"><i class="fas fa-eye me-2 text-primary"></i>Preview</h4>
  <p class="text-muted">HTML preview using the first few rows. PDF/DOCX output is formatted differently.</p>
  {content}
  <div class="d-flex justify-content-end mt-4 gap-2">
    <a href="/reportforge/wizard/step/back/4" class="btn btn-outline-secondary btn-sm">&larr; Back</a>
    <form method="POST" action="/reportforge/wizard/step/4" style="display:inline">
      <button class="btn btn-primary">Next &rarr; Save</button>
    </form>
  </div>
</div>"""


# ── Step 5: Save ──────────────────────────────────────────────────────────────

def _step5_html(state: dict) -> str:
    default_name = state.get("name", "")
    return f"""
<div class="card p-4">
  <h4 class="mb-3"><i class="fas fa-save me-2 text-primary"></i>Save Your Report</h4>
  <form method="POST" action="/reportforge/wizard/step/5">
    <div class="mb-3">
      <label class="form-label fw-bold">Report Name <span class="text-danger">*</span></label>
      <input name="name" class="form-control" required value="{default_name}"
             placeholder="e.g. Monthly Sales Invoice">
    </div>
    <div class="mb-3">
      <label class="form-label">Description</label>
      <textarea name="description" class="form-control" rows="2"
                placeholder="What does this report show?">{state.get('description','')}</textarea>
    </div>
    <div class="row g-3">
      <div class="col-4">
        <label class="form-label">Paper Size</label>
        <select name="paper_size" class="form-select">
          {''.join(f'<option value="{v}"{" selected" if state.get("paper_size")==v else ""}>{v}</option>'
                   for v in ["A4","LETTER","LEGAL","A3","A5"])}
        </select>
      </div>
      <div class="col-4">
        <label class="form-label">Orientation</label>
        <select name="orientation" class="form-select">
          <option value="portrait">Portrait</option>
          <option value="landscape">Landscape</option>
        </select>
      </div>
    </div>
    <div class="d-flex justify-content-between mt-4">
      <a href="/reportforge/wizard/step/back/5" class="btn btn-outline-secondary btn-sm">&larr; Back</a>
      <button class="btn btn-success btn-lg">
        <i class="fas fa-check me-2"></i>Create Report
      </button>
    </div>
  </form>
</div>"""


# ── Wizard view ───────────────────────────────────────────────────────────────

class ReportWizardView(BaseView):
	"""5-step guided wizard for creating ReportForge reports."""

	route_base   = "/reportforge/wizard"
	default_view = "start"

	@expose("/")
	@expose("/start")
	@has_access
	def start(self):
		_save_state({})
		return _render(1, _step1_html(), _step1_js())

	# ── Step 1 POST ───────────────────────────────────────────────────────
	@expose("/step/1", methods=["POST"])
	@has_access
	def step1_post(self):
		from .report_templates import get_template
		key = request.form.get("template_key", "blank")
		state = _wizard_state()
		state["template_key"] = key
		tmpl = get_template(key)
		if tmpl:
			state["sql"]      = tmpl.get("sample_sql", "")
			state["branding"] = {
				"primary_color":   tmpl.get("primary_color",   "#003366"),
				"secondary_color": tmpl.get("secondary_color", "#666666"),
			}
			state["template_data"] = tmpl
			# Auto-name from template label
			if not state.get("name"):
				state["name"] = tmpl.get("label", "New Report")
		_save_state(state)
		return _render(2, _step2_html(state), _step2_js())

	# ── Step 2 POST ───────────────────────────────────────────────────────
	@expose("/step/2", methods=["POST"])
	@has_access
	def step2_post(self):
		state = _wizard_state()
		state["sql"] = request.form.get("sql", "").strip()
		_save_state(state)
		return _render(3, _step3_html(state))

	# ── Step 3 POST ───────────────────────────────────────────────────────
	@expose("/step/3", methods=["POST"])
	@has_access
	def step3_post(self):
		state = _wizard_state()
		state["branding"] = {
			"company_name":      request.form.get("company_name", ""),
			"logo_url":          request.form.get("logo_url", ""),
			"primary_color":     request.form.get("primary_color", "#003366"),
			"secondary_color":   request.form.get("secondary_color", "#666666"),
			"watermark_text":    request.form.get("watermark_text", ""),
			"custom_header_html":request.form.get("custom_header_html", ""),
			"custom_footer_html":request.form.get("custom_footer_html", ""),
		}
		_save_state(state)
		# Generate preview
		preview_html, error = _generate_preview(state)
		return _render(4, _step4_html(preview_html, error))

	# ── Step 4 POST ───────────────────────────────────────────────────────
	@expose("/step/4", methods=["POST"])
	@has_access
	def step4_post(self):
		state = _wizard_state()
		return _render(5, _step5_html(state))

	# ── Step 5 POST: final save ───────────────────────────────────────────
	@expose("/step/5", methods=["POST"])
	@has_access
	def step5_post(self):
		from flask_login import current_user
		from .models import Report, ReportBand, ReportField, ReportParameter, PaperSize, Orientation
		state = _wizard_state()
		branding = state.get("branding", {})
		paper_raw  = request.form.get("paper_size", "A4")
		orient_raw = request.form.get("orientation", "portrait")
		try:
			paper  = PaperSize(paper_raw)
		except ValueError:
			paper  = PaperSize.A4
		try:
			orient = Orientation(orient_raw)
		except ValueError:
			orient = Orientation.PORTRAIT

		appbuilder = current_app.extensions.get("appbuilder")
		if not appbuilder:
			return "Error: appbuilder not found", 500

		report = Report(
			name=request.form.get("name", "Untitled Report").strip(),
			description=request.form.get("description", "").strip(),
			data_source=state.get("sql", "SELECT 1"),
			is_sql_source=True,
			paper_size=paper,
			orientation=orient,
			company_name=branding.get("company_name", ""),
			logo_url=branding.get("logo_url", ""),
			primary_color=branding.get("primary_color", "#003366"),
			secondary_color=branding.get("secondary_color", "#666666"),
			watermark_text=branding.get("watermark_text", ""),
			custom_header_html=branding.get("custom_header_html", ""),
			custom_footer_html=branding.get("custom_footer_html", ""),
			template_key=state.get("template_key"),
			created_by=getattr(current_user, "id", None),
		)
		appbuilder.session.add(report)
		appbuilder.session.flush()

		# Apply template bands/fields if a template was chosen
		tmpl_data = state.get("template_data")
		if tmpl_data:
			_apply_template_bands(report, tmpl_data, appbuilder.session)

		appbuilder.session.commit()
		_save_state({})  # clear wizard state

		return _render(5, f"""
<div class="card p-4 text-center">
  <i class="fas fa-check-circle fa-4x text-success mb-3"></i>
  <h4>Report Created!</h4>
  <p class="text-muted">Your report <strong>{report.name}</strong> has been saved.</p>
  <div class="d-flex justify-content-center gap-3 mt-3">
    <a href="/reportforge/reports/design/{report.id}"
       class="btn btn-primary"><i class="fas fa-paint-brush me-2"></i>Open in Designer</a>
    <a href="/reportforge/wizard/start"
       class="btn btn-outline-secondary"><i class="fas fa-plus me-2"></i>Create Another</a>
  </div>
</div>""")

	# ── Back navigation ───────────────────────────────────────────────────
	@expose("/step/back/<int:from_step>")
	@has_access
	def step_back(self, from_step: int):
		state = _wizard_state()
		if from_step == 2:
			return _render(1, _step1_html(), _step1_js())
		if from_step == 3:
			return _render(2, _step2_html(state), _step2_js())
		if from_step == 4:
			return _render(3, _step3_html(state))
		if from_step == 5:
			preview_html, error = _generate_preview(state)
			return _render(4, _step4_html(preview_html, error))
		return redirect(url_for("ReportWizardView.start"))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _generate_preview(state: dict) -> tuple[str, str | None]:
	"""Run the SQL and return an HTML preview string."""
	sql = state.get("sql", "").strip()
	branding = state.get("branding", {})
	if not sql:
		return "", "No SQL defined — go back to Step 2."
	try:
		from flask import current_app
		appbuilder = current_app.extensions.get("appbuilder")
		if not appbuilder:
			return "", "appbuilder not found."
		safe_sql = sql.rstrip(";")
		if "LIMIT" not in safe_sql.upper():
			safe_sql += " LIMIT 10"
		import sqlalchemy as sa
		with appbuilder.session.bind.connect() as conn:
			result = conn.execute(sa.text(safe_sql))
			columns = list(result.keys())
			rows = [dict(r._mapping) for r in result]
		# Build HTML
		primary = branding.get("primary_color", "#003366")
		parts = [
			f'<table style="width:100%;border-collapse:collapse;font-size:13px">',
			f'<thead><tr>',
		]
		for col in columns:
			parts.append(
				f'<th style="background:{primary};color:#fff;padding:6px 10px;'
				f'text-align:left">{col}</th>'
			)
		parts.append("</tr></thead><tbody>")
		for i, row in enumerate(rows):
			bg = "#f8f9fa" if i % 2 else "#fff"
			parts.append(f'<tr style="background:{bg}">')
			for col in columns:
				val = row.get(col, "")
				parts.append(f'<td style="padding:5px 10px;border-bottom:1px solid #eee">'
				             f'{val if val is not None else ""}</td>')
			parts.append("</tr>")
		parts.append("</tbody></table>")
		return "".join(parts), None
	except Exception as exc:
		return "", str(exc)


def _apply_template_bands(report, tmpl_data: dict, session) -> None:
	"""Persist the band + field layout from a template dict into the DB."""
	from .models import ReportBand, ReportField, BandType, FieldType
	for pos, band_def in enumerate(tmpl_data.get("bands", [])):
		try:
			btype = BandType(band_def.get("band_type", "detail"))
		except ValueError:
			btype = BandType.DETAIL
		band = ReportBand(
			report_id=report.id,
			band_type=btype,
			position=pos,
			height_mm=float(band_def.get("height_mm", 20)),
			background_color=band_def.get("background_color", "#ffffff"),
		)
		session.add(band)
		session.flush()
		for field_def in band_def.get("fields", []):
			try:
				ftype = FieldType(field_def.get("field_type", "text"))
			except ValueError:
				ftype = FieldType.TEXT
			field = ReportField(
				band_id=band.id,
				field_type=ftype,
				x_mm=float(field_def.get("x_mm", 0)),
				y_mm=float(field_def.get("y_mm", 0)),
				width_mm=float(field_def.get("width_mm", 40)),
				height_mm=float(field_def.get("height_mm", 8)),
				data_binding=field_def.get("data_binding"),
				format_string=field_def.get("format_string"),
				style=field_def.get("style", {}),
			)
			session.add(field)
