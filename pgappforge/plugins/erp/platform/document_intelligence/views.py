"""
pgappforge/plugins/erp/platform/document_intelligence/views.py

Upload view for Document Intelligence — file upload form + extraction result display.
Route: /platform/document-intelligence
"""
from __future__ import annotations

import logging

from flask import render_template, request, redirect, url_for, flash
from markupsafe import Markup

from pgappforge import expose
from pgappforge.security.decorators import has_access
from pgappforge.plugins.erp.base_view import BaseERPView

log = logging.getLogger(__name__)

_DOCUMENT_TYPES = [
	("invoice", "Invoice"),
	("national_id", "National ID / Passport"),
	("payslip", "Payslip"),
	("bank_statement", "Bank Statement"),
]

_UPLOAD_FORM_HTML = """
<div class="row">
  <div class="col-md-8 col-md-offset-2">
    <div class="panel panel-default">
      <div class="panel-heading"><h3 class="panel-title">
        <i class="fa fa-file-text-o"></i>&nbsp; Upload Document for Extraction
      </h3></div>
      <div class="panel-body">
        <form method="POST" enctype="multipart/form-data" action="{action_url}">
          <div class="form-group">
            <label for="doc_type">Document Type</label>
            <select name="document_type" id="doc_type" class="form-control" required>
              {type_options}
            </select>
          </div>
          <div class="form-group">
            <label for="doc_file">Document File (PDF, PNG, JPG, JPEG)</label>
            <input type="file" name="document_file" id="doc_file"
                   accept=".pdf,.png,.jpg,.jpeg" class="form-control" required>
            <p class="help-block">Maximum 10 MB. Supported: PDF, PNG, JPG.</p>
          </div>
          <button type="submit" class="btn btn-primary">
            <i class="fa fa-magic"></i>&nbsp; Extract
          </button>
        </form>
      </div>
    </div>
  </div>
</div>
"""

_RESULT_HTML = """
<div class="row">
  <div class="col-md-10 col-md-offset-1">
    <div class="panel panel-{panel_class}">
      <div class="panel-heading">
        <h3 class="panel-title">
          <i class="fa {icon}"></i>&nbsp; Extraction Result — {doc_type_label}
        </h3>
      </div>
      <div class="panel-body">
        {status_badge}
        <dl class="dl-horizontal" style="margin-top:1rem">
          {field_rows}
        </dl>
        <hr>
        <p class="text-muted" style="font-size:0.85em">
          Model: <strong>{model_used}</strong> &nbsp;|&nbsp;
          Confidence: <strong>{confidence_pct}%</strong>
        </p>
        <a href="{upload_url}" class="btn btn-default btn-sm">
          <i class="fa fa-upload"></i>&nbsp; Upload Another
        </a>
      </div>
    </div>
  </div>
</div>
"""


def _render_field_rows(fields: dict) -> str:
	rows = []
	for key, val in fields.items():
		label = key.replace("_", " ").title()
		if isinstance(val, list):
			val_html = "<ul>" + "".join(f"<li>{item}</li>" for item in val) + "</ul>"
		elif val is None:
			val_html = '<span class="text-muted">—</span>'
		else:
			val_html = str(val)
		rows.append(f"<dt>{label}</dt><dd>{val_html}</dd>")
	return "\n".join(rows)


class DocumentIntelligenceView(BaseERPView):
	route_base = "/platform/document-intelligence"

	@expose("/")
	@has_access
	def index(self):
		type_options = "\n".join(
			f'<option value="{v}">{l}</option>' for v, l in _DOCUMENT_TYPES
		)
		upload_url = url_for("DocumentIntelligenceView.index")
		form_html = _UPLOAD_FORM_HTML.format(
			action_url=url_for("DocumentIntelligenceView.extract"),
			type_options=type_options,
		)
		kpi_html = self._recent_kpis()
		return render_template(
			"appbuilder/general/document_intelligence.html",
			form_html=Markup(form_html),
			kpi_html=kpi_html,
			result_html=None,
			appbuilder=self.appbuilder,
		)

	@expose("/extract", methods=["POST"])
	@has_access
	def extract(self):
		from pgappforge.plugins.erp.platform.document_intelligence.services import (
			DocumentIntelligenceService,
		)

		doc_file = request.files.get("document_file")
		document_type = request.form.get("document_type", "invoice")

		if not doc_file or doc_file.filename == "":
			flash("No file uploaded.", "warning")
			return redirect(url_for("DocumentIntelligenceView.index"))

		file_bytes = doc_file.read()
		if len(file_bytes) > 10 * 1024 * 1024:
			flash("File too large. Maximum 10 MB.", "danger")
			return redirect(url_for("DocumentIntelligenceView.index"))

		mime_type = doc_file.content_type or "application/octet-stream"
		svc = DocumentIntelligenceService()
		result = svc.extract(
			file_bytes=file_bytes,
			document_type=document_type,
			mime_type=mime_type,
		)

		# Optionally persist
		try:
			session = self._session()
			svc.save_extraction(
				result,
				reference_type="upload",
				reference_id="",
				tenant_id=self._tenant_id(),
				session=session,
			)
		except Exception as exc:
			log.debug("Extraction persist skipped: %s", exc)

		doc_type_label = dict(_DOCUMENT_TYPES).get(document_type, document_type)
		upload_url = url_for("DocumentIntelligenceView.index")

		if result.get("success"):
			fields = result.get("extracted_fields", {})
			result_html = _RESULT_HTML.format(
				panel_class="success",
				icon="fa-check-circle",
				doc_type_label=doc_type_label,
				status_badge='<span class="label label-success">Extraction Successful</span>',
				field_rows=_render_field_rows(fields),
				model_used=result.get("model_used", ""),
				confidence_pct=int((result.get("confidence", 0) or 0) * 100),
				upload_url=upload_url,
			)
		else:
			result_html = _RESULT_HTML.format(
				panel_class="danger",
				icon="fa-times-circle",
				doc_type_label=doc_type_label,
				status_badge='<span class="label label-danger">Extraction Failed</span>',
				field_rows=f"<dt>Error</dt><dd>{result.get('error', 'Unknown error')}</dd>",
				model_used="—",
				confidence_pct=0,
				upload_url=upload_url,
			)

		type_options = "\n".join(
			f'<option value="{v}"{"selected" if v == document_type else ""}>{l}</option>'
			for v, l in _DOCUMENT_TYPES
		)
		form_html = _UPLOAD_FORM_HTML.format(
			action_url=url_for("DocumentIntelligenceView.extract"),
			type_options=type_options,
		)
		kpi_html = self._recent_kpis()
		return render_template(
			"appbuilder/general/document_intelligence.html",
			form_html=Markup(form_html),
			kpi_html=kpi_html,
			result_html=Markup(result_html),
			appbuilder=self.appbuilder,
		)

	def _recent_kpis(self) -> Markup:
		try:
			import sqlalchemy as sa
			sess = self._session()
			total = sess.execute(sa.text(
				"SELECT COUNT(*) FROM pgaf_document_extraction"
			)).scalar() or 0
			invoices = sess.execute(sa.text(
				"SELECT COUNT(*) FROM pgaf_document_extraction WHERE document_type = 'invoice'"
			)).scalar() or 0
			kyc = sess.execute(sa.text(
				"SELECT COUNT(*) FROM pgaf_document_extraction WHERE document_type = 'national_id'"
			)).scalar() or 0
		except Exception:
			total = invoices = kyc = 0

		return self.kpi_cards([
			{"label": "Total Extractions", "value": total, "icon": "fa-file-text-o", "color": "#1a56db"},
			{"label": "Invoices Processed", "value": invoices, "icon": "fa-file-invoice", "color": "#057a55"},
			{"label": "KYC Documents", "value": kyc, "icon": "fa-id-card", "color": "#9061f9"},
		])


__all__ = ["DocumentIntelligenceView"]
