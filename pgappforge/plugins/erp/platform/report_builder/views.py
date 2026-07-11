"""
pgappforge/plugins/erp/platform/report_builder/views.py

ReportBro-backed report designer and PDF renderer.

Routes (all under /platform/reports):
  GET  /                     — list all saved reports for tenant
  GET  /new                  — blank report form (or pick a template)
  GET  /<id>/design          — open ReportBro designer for an existing report
  POST /<id>/save            — save designer JSON back to SavedReport
  POST /<id>/render          — render PDF → file download
  POST /preview              — render from POSTed definition (live preview, no save)
  POST /data-preview         — execute data_source_query and return JSON rows
"""
from __future__ import annotations
from flask_babel import lazy_gettext as _

import json
import logging

from flask import Response, flash, redirect, render_template, request, url_for
from markupsafe import Markup

from pgappforge import expose
from pgappforge.security.decorators import has_access
from pgappforge.plugins.erp.base_view import BaseERPView

log = logging.getLogger(__name__)

_REPORT_TYPES = [
	("standard",    "Standard"),
	("financial",   "Financial"),
	("statistical", "Statistical"),
]

# ------------------------------------------------------------------ #
# Inline HTML helpers (no new template files needed)
# ------------------------------------------------------------------ #

_LIST_HTML = """
<div class="row" style="margin-bottom:1rem">
  <div class="col-md-12">
    <a href="{new_url}" class="btn btn-primary">
      <i class="fa fa-plus"></i>&nbsp; New Report
    </a>
  </div>
</div>
<div class="table-responsive">
  <table class="table table-striped table-hover">
    <thead>
      <tr>
        <th>Name</th><th>Type</th><th>Public</th><th>Template</th>
        <th>Updated</th><th>Actions</th>
      </tr>
    </thead>
    <tbody>
      {rows}
    </tbody>
  </table>
</div>
"""

_LIST_ROW = """
<tr>
  <td><strong>{name}</strong>{desc}</td>
  <td><span class="label label-default">{report_type}</span></td>
  <td>{is_public}</td>
  <td>{is_template}</td>
  <td><small>{updated_at}</small></td>
  <td>
    <a href="{design_url}" class="btn btn-xs btn-primary">
      <i class="fa fa-pencil"></i> Design
    </a>&nbsp;
    <a href="{render_url}" class="btn btn-xs btn-success">
      <i class="fa fa-file-pdf-o"></i> PDF
    </a>
  </td>
</tr>
"""

_DESIGNER_HTML = """
<div class="row">
  <div class="col-md-12">
    <div class="panel panel-default">
      <div class="panel-heading">
        <h3 class="panel-title">
          <i class="fa fa-pencil-square-o"></i>&nbsp; Report Designer — {name}
          &nbsp;<small class="text-muted">powered by ReportBro</small>
        </h3>
      </div>
      <div class="panel-body" style="padding:0">
        <!-- ReportBro designer is loaded via CDN JS/CSS below -->
        <div id="reportbro-designer" style="height:700px;border:0"></div>
      </div>
    </div>
    <!-- Save button outside panel so it's always visible -->
    <button id="btn-save-report" class="btn btn-success" style="margin-right:.5rem">
      <i class="fa fa-save"></i>&nbsp; Save
    </button>
    <a href="{list_url}" class="btn btn-default">
      <i class="fa fa-arrow-left"></i>&nbsp; Back to Reports
    </a>
  </div>
</div>

<!-- ReportBro CDN assets (MIT license) -->
<link rel="stylesheet"
  href="https://cdn.jsdelivr.net/npm/reportbro-designer@3.5.0/dist/reportbro.css">
<script src="https://cdn.jsdelivr.net/npm/jquery@3.7.1/dist/jquery.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/reportbro-designer@3.5.0/dist/reportbro.js"></script>

<script>
(function () {{
  var reportDefinition = {report_definition_json};
  var saveUrl = {save_url_json};
  var dataPreviewUrl = {data_preview_url_json};

  var rb = new ReportBro(document.getElementById("reportbro-designer"), {{
    enableTestData: true,
    reportDefinition: reportDefinition,
    onSave: function (reportDefinition) {{
      $.ajax({{
        url: saveUrl,
        type: "POST",
        contentType: "application/json",
        data: JSON.stringify({{ report_definition: reportDefinition }}),
        success: function (r) {{
          if (r.success) {{
            rb.setModified(false);
            alert("Report saved successfully.");
          }} else {{
            alert("Save failed: " + (r.error || "unknown error"));
          }}
        }},
        error: function () {{ alert("Save request failed."); }}
      }});
    }}
  }});

  document.getElementById("btn-save-report").addEventListener("click", function () {{
    rb.save();
  }});
}})();
</script>
"""

_NEW_REPORT_HTML = """
<div class="row">
  <div class="col-md-8 col-md-offset-2">
    <div class="panel panel-default">
      <div class="panel-heading">
        <h3 class="panel-title">
          <i class="fa fa-plus"></i>&nbsp; New Report
        </h3>
      </div>
      <div class="panel-body">
        <form method="POST" action="{save_url}">
          <div class="form-group">
            <label>Report Name <span class="text-danger">*</span></label>
            <input name="name" type="text" class="form-control" required
                   placeholder="e.g. Monthly Sales Report">
          </div>
          <div class="form-group">
            <label>Description</label>
            <textarea name="description" class="form-control" rows="2"></textarea>
          </div>
          <div class="form-group">
            <label>Report Type</label>
            <select name="report_type" class="form-control">
              {type_options}
            </select>
          </div>
          <div class="form-group">
            <label>Data Source SQL Query</label>
            <textarea name="data_source_query" class="form-control" rows="4"
              placeholder="SELECT ... FROM ...  (optional)"></textarea>
            <p class="help-block">SELECT-only. Leave blank for static/manually entered data.</p>
          </div>
          <div class="checkbox">
            <label>
              <input type="checkbox" name="is_public" value="1">
              Public — visible to all users in this tenant
            </label>
          </div>
          <div class="checkbox">
            <label>
              <input type="checkbox" name="is_template" value="1">
              Save as template
            </label>
          </div>
          <hr>
          <button type="submit" class="btn btn-primary">
            <i class="fa fa-pencil"></i>&nbsp; Create &amp; Open Designer
          </button>
          <a href="{list_url}" class="btn btn-default">Cancel</a>
        </form>
      </div>
    </div>
  </div>
</div>
"""


def _bool_badge(val: bool) -> str:
	if val:
		return '<span class="label label-success">Yes</span>'
	return '<span class="label label-default">No</span>'


class ReportBuilderView(BaseERPView):
	route_base = "/platform/reports"

	# ---------------------------------------------------------------- #
	# List
	# ---------------------------------------------------------------- #

	@expose("/")
	@has_access
	def index(self):
		svc = self._svc()
		sess = self._session()
		reports = svc.list_reports(self._tenant_id(), sess)

		rows_html = ""
		for r in reports:
			desc = f"<br><small class='text-muted'>{r['description']}</small>" if r.get("description") else ""
			rows_html += _LIST_ROW.format(
				name=r["name"],
				desc=desc,
				report_type=r["report_type"],
				is_public=_bool_badge(r["is_public"]),
				is_template=_bool_badge(r["is_template"]),
				updated_at=(r["updated_at"] or "")[:16],
				design_url=url_for("ReportBuilderView.design", report_id=r["id"]),
				render_url=url_for("ReportBuilderView.render_pdf_view", report_id=r["id"]),
			)

		list_html = _LIST_HTML.format(
			new_url=url_for("ReportBuilderView.new_report"),
			rows=rows_html or '<tr><td colspan="6" class="text-center text-muted">No reports yet. Create one!</td></tr>',
		)

		kpi_html = self._kpis(reports)
		return render_template(
			"appbuilder/general/report_builder.html",
			list_html=Markup(list_html),
			kpi_html=kpi_html,
			appbuilder=self.appbuilder,
			page_title=_("Report Builder"),
		)

	# ---------------------------------------------------------------- #
	# New report form
	# ---------------------------------------------------------------- #

	@expose("/new", methods=["GET"])
	@has_access
	def new_report(self):
		type_options = "\n".join(
			f'<option value="{v}">{l}</option>' for v, l in _REPORT_TYPES
		)
		form_html = _NEW_REPORT_HTML.format(
			save_url=url_for("ReportBuilderView.create_report"),
			list_url=url_for("ReportBuilderView.index"),
			type_options=type_options,
		)
		return render_template(
			"appbuilder/general/report_builder.html",
			list_html=Markup(form_html),
			kpi_html=Markup(""),
			appbuilder=self.appbuilder,
			page_title=_("New Report"),
		)

	@expose("/new", methods=["POST"])
	@has_access
	def create_report(self):
		svc = self._svc()
		sess = self._session()
		name = request.form.get("name", "").strip()
		if not name:
			flash("Report name is required.", "warning")
			return redirect(url_for("ReportBuilderView.new_report"))

		try:
			from flask_login import current_user
			user_id = str(getattr(current_user, "id", ""))
		except Exception:
			user_id = ""

		report_id = svc.save_report(
			tenant_id=self._tenant_id(),
			name=name,
			report_definition={},
			session=sess,
			description=request.form.get("description") or None,
			report_type=request.form.get("report_type", "standard"),
			is_public=bool(request.form.get("is_public")),
			is_template=bool(request.form.get("is_template")),
			data_source_query=request.form.get("data_source_query") or None,
			created_by=user_id or None,
		)
		sess.commit()
		flash(f"Report '{name}' created. Open the designer to build your layout.", "success")
		return redirect(url_for("ReportBuilderView.design", report_id=report_id))

	# ---------------------------------------------------------------- #
	# Designer
	# ---------------------------------------------------------------- #

	@expose("/<string:report_id>/design")
	@has_access
	def design(self, report_id: str):
		import sqlalchemy as sa
		from pgappforge.plugins.erp.platform.report_builder.models import SavedReport

		sess = self._session()
		report = sess.execute(
			sa.select(SavedReport).where(
				SavedReport.id == report_id,
				SavedReport.tenant_id == self._tenant_id(),
			)
		).scalar_one_or_none()

		if report is None:
			flash("Report not found.", "danger")
			return redirect(url_for("ReportBuilderView.index"))

		designer_html = _DESIGNER_HTML.format(
			name=report.name,
			report_definition_json=json.dumps(report.report_definition or {}),
			save_url_json=json.dumps(url_for("ReportBuilderView.save_design", report_id=report_id)),
			data_preview_url_json=json.dumps(url_for("ReportBuilderView.data_preview")),
			list_url=url_for("ReportBuilderView.index"),
		)
		return render_template(
			"appbuilder/general/report_builder.html",
			list_html=Markup(designer_html),
			kpi_html=Markup(""),
			appbuilder=self.appbuilder,
			page_title=f"Design: {report.name}",
		)

	@expose("/<string:report_id>/save", methods=["POST"])
	@has_access
	def save_design(self, report_id: str):
		"""AJAX endpoint — accepts JSON {report_definition: {...}}."""
		payload = request.get_json(silent=True) or {}
		definition = payload.get("report_definition")
		if definition is None:
			return {"success": False, "error": "Missing report_definition"}, 400

		svc = self._svc()
		sess = self._session()
		try:
			import sqlalchemy as sa
			from pgappforge.plugins.erp.platform.report_builder.models import SavedReport

			report = sess.execute(
				sa.select(SavedReport).where(
					SavedReport.id == report_id,
					SavedReport.tenant_id == self._tenant_id(),
				)
			).scalar_one_or_none()

			if report is None:
				return {"success": False, "error": "Report not found"}, 404

			report.report_definition = definition
			sess.commit()
			log.info("Report %s saved by user (definition updated)", report_id)
			return {"success": True}
		except Exception as exc:
			log.error("save_design failed: %s", exc)
			return {"success": False, "error": str(exc)}, 500

	# ---------------------------------------------------------------- #
	# PDF Render
	# ---------------------------------------------------------------- #

	@expose("/<string:report_id>/render", methods=["GET", "POST"])
	@has_access
	def render_pdf_view(self, report_id: str):
		"""Render report as PDF and return as file download."""
		svc = self._svc()
		sess = self._session()
		try:
			pdf_bytes = svc.render_pdf(
				report_id=report_id,
				tenant_id=self._tenant_id(),
				session=sess,
			)
		except ValueError as exc:
			flash(str(exc), "danger")
			return redirect(url_for("ReportBuilderView.index"))

		if pdf_bytes is None:
			flash(
				"PDF generation unavailable. Install reportbro-lib: pip install reportbro-lib",
				"warning",
			)
			return redirect(url_for("ReportBuilderView.index"))

		return Response(
			pdf_bytes,
			mimetype="application/pdf",
			headers={
				"Content-Disposition": f'attachment; filename="report_{report_id}.pdf"',
				"Content-Length": str(len(pdf_bytes)),
			},
		)

	@expose("/preview", methods=["POST"])
	@has_access
	def preview(self):
		"""Live preview — render POSTed definition without saving.

		Accepts JSON: {report_definition: {...}, data: {...}}
		Returns PDF bytes or JSON error.
		"""
		payload = request.get_json(silent=True) or {}
		definition = payload.get("report_definition", {})
		data = payload.get("data", {})

		svc = self._svc()
		pdf_bytes = svc.render_pdf_from_definition(definition, data)
		if pdf_bytes is None:
			return {"error": "reportbro-lib not installed or render failed"}, 503

		return Response(
			pdf_bytes,
			mimetype="application/pdf",
			headers={"Content-Disposition": 'inline; filename="preview.pdf"'},
		)

	@expose("/data-preview", methods=["POST"])
	@has_access
	def data_preview(self):
		"""Execute a SQL query and return JSON rows for designer data preview.

		Accepts JSON: {sql: "SELECT ..."}
		Returns: {rows: [...], columns: [...], error: null}
		"""
		payload = request.get_json(silent=True) or {}
		sql = payload.get("sql", "").strip()
		if not sql:
			return {"rows": [], "columns": [], "error": "No SQL provided"}, 400

		svc = self._svc()
		sess = self._session()
		try:
			rows = svc.get_data_for_report(sql, sess)
			columns = list(rows[0].keys()) if rows else []
			return {"rows": rows, "columns": columns, "error": None}
		except ValueError as exc:
			return {"rows": [], "columns": [], "error": str(exc)}, 400
		except Exception as exc:
			return {"rows": [], "columns": [], "error": str(exc)}, 500

	# ---------------------------------------------------------------- #
	# Helpers
	# ---------------------------------------------------------------- #

	def _svc(self):
		from pgappforge.plugins.erp.platform.report_builder.services import ReportBuilderService
		return ReportBuilderService()

	def _kpis(self, reports: list[dict]) -> Markup:
		total = len(reports)
		public = sum(1 for r in reports if r.get("is_public"))
		templates = sum(1 for r in reports if r.get("is_template"))
		return self.kpi_cards([
			{"label": "Total Reports", "value": total,     "icon": "fa-file-pdf-o",  "color": "#1a56db"},
			{"label": "Public",        "value": public,    "icon": "fa-globe",        "color": "#057a55"},
			{"label": "Templates",     "value": templates, "icon": "fa-copy",         "color": "#9061f9"},
		])


__all__ = ["ReportBuilderView"]
