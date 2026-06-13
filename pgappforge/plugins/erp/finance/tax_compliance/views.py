"""
pgappforge/plugins/erp/finance/tax_compliance/views.py

Flask views for the Tax Compliance plugin.

Route summary
-------------
TaxComplianceDashboardView   /finance/tax-compliance/
  GET  /                     — compliance status overview dashboard (HTML)
  GET  /status/<invoice_id>  — JSON compliance status for a single invoice
  POST /submit/<invoice_id>  — manual re-submission trigger (JSON response)
"""
from __future__ import annotations

import logging

from flask import abort, jsonify, request

from pgappforge import expose
from pgappforge.plugins.erp.base_view import BaseERPView
from pgappforge.security.decorators import has_access

log = logging.getLogger(__name__)


def _he(s: object) -> str:
	"""Minimal HTML-escape."""
	return (
		str(s)
		.replace("&", "&amp;")
		.replace("<", "&lt;")
		.replace(">", "&gt;")
		.replace('"', "&quot;")
	)


def _get_session():
	try:
		from flask import current_app
		ab = current_app.extensions.get("appbuilder")
		if ab and hasattr(ab, "get_session"):
			return ab.get_session
		db = current_app.extensions.get("sqlalchemy")
		if db:
			return db.session
	except RuntimeError:
		pass
	raise RuntimeError("Cannot obtain database session")


class TaxComplianceDashboardView(BaseERPView):
	"""Tax compliance status overview and manual submission trigger.

	Mounted at /finance/tax-compliance/.
	"""

	route_base = "/finance/tax-compliance"
	default_view = "index"

	# ------------------------------------------------------------------
	# GET /  — overview dashboard
	# ------------------------------------------------------------------

	@expose("/")
	@has_access
	def index(self):
		"""Render a compliance status overview: submitted / failed / pending counts."""
		from flask import current_app

		country = current_app.config.get("COMPLIANCE_COUNTRY", "—").upper()
		enabled = current_app.config.get("TAX_COMPLIANCE_ENABLED", False)

		submitted_count = 0
		failed_count = 0
		recent_rows: list[dict] = []

		try:
			import sqlalchemy as sa
			session = _get_session()
			if callable(session):
				session = session()

			submitted_count = session.execute(
				sa.text(
					"SELECT COUNT(*) FROM pgaf_tax_submission WHERE status = 'SUCCESS'"
				)
			).scalar_one() or 0

			failed_count = session.execute(
				sa.text(
					"SELECT COUNT(*) FROM pgaf_tax_submission WHERE status = 'FAILED'"
				)
			).scalar_one() or 0

			rows = session.execute(
				sa.text(
					"SELECT invoice_id, authority, status, control_number,"
					" error_message, created_at"
					" FROM pgaf_tax_submission ORDER BY created_at DESC LIMIT 20"
				)
			).fetchall()
			recent_rows = [
				dict(zip(
					("invoice_id", "authority", "status", "control_number", "error", "created_at"),
					r,
				))
				for r in rows
			]
		except Exception as exc:
			log.debug("TaxComplianceDashboardView.index: stats query failed — %s", exc)

		kpi_html = self.kpi_cards([
			{
				"label": "Submitted",
				"value": submitted_count,
				"format": "integer",
				"color": "#057a55",
				"icon": "fa-check-circle",
			},
			{
				"label": "Failed",
				"value": failed_count,
				"format": "integer",
				"color": "#c81e1e",
				"icon": "fa-times-circle",
			},
		])

		# Build recent submissions table
		table_rows = ""
		for r in recent_rows:
			status_color = "#057a55" if r["status"] == "SUCCESS" else "#c81e1e"
			table_rows += (
				f"<tr>"
				f"<td><code>{_he(str(r['invoice_id'])[:12])}…</code></td>"
				f"<td>{_he(r['authority'] or '—')}</td>"
				f"<td style='color:{status_color};font-weight:600'>{_he(r['status'])}</td>"
				f"<td><code>{_he(r['control_number'] or '—')}</code></td>"
				f"<td style='color:#888;font-size:.85em'>{_he(r['error'] or '')}</td>"
				f"<td style='font-size:.85em'>{_he(str(r['created_at'])[:19])}</td>"
				f"</tr>"
			)

		enabled_badge = (
			"<span style='color:#057a55'>&#10003; enabled</span>"
			if enabled
			else "<span style='color:#c81e1e'>&#10007; disabled</span>"
		)

		html = f"""
		<div class='container-fluid' style='padding:1.5rem'>
			<h2 style='margin-bottom:1rem'>
				<i class='fa fa-shield-alt'></i>&nbsp; Tax Compliance
				<small style='font-size:.6em;color:#888'>country: {_he(country)} &nbsp;|&nbsp; {enabled_badge}</small>
			</h2>
			{kpi_html}
			<div class='panel panel-default'>
				<div class='panel-heading'><strong>Recent Submissions</strong></div>
				<div class='panel-body' style='padding:0;overflow-x:auto'>
					<table class='table table-striped table-condensed' style='margin:0'>
						<thead>
							<tr>
								<th>Invoice ID</th><th>Authority</th><th>Status</th>
								<th>Control #</th><th>Error</th><th>Submitted At</th>
							</tr>
						</thead>
						<tbody>{table_rows or '<tr><td colspan=6 style="text-align:center;padding:2rem;color:#888">No submissions yet</td></tr>'}</tbody>
					</table>
				</div>
			</div>
		</div>
		"""
		from markupsafe import Markup
		return self.render_template("appbuilder/general/model/edit.html", content=Markup(html))

	# ------------------------------------------------------------------
	# GET /status/<invoice_id>  — JSON status for one invoice
	# ------------------------------------------------------------------

	@expose("/status/<invoice_id>")
	@has_access
	def status(self, invoice_id: str):
		"""Return JSON compliance status for the given invoice ID."""
		from pgappforge.plugins.erp.finance.tax_compliance.services import TaxComplianceService
		try:
			session = _get_session()
			if callable(session):
				session = session()
			svc = TaxComplianceService()
			data = svc.get_compliance_status(invoice_id, session)
			return jsonify(data)
		except Exception as exc:
			log.warning("status(%s) failed: %s", invoice_id, exc)
			return jsonify({
				"invoice_id": invoice_id,
				"submissions": [],
				"compliant": False,
				"error": str(exc),
			}), 500

	# ------------------------------------------------------------------
	# POST /submit/<invoice_id>  — manual submission trigger
	# ------------------------------------------------------------------

	@expose("/submit/<invoice_id>", methods=["POST"])
	@has_access
	def submit(self, invoice_id: str):
		"""Manually trigger (or re-trigger) tax compliance submission for an invoice.

		Accepts optional JSON body::

		    {"tenant_id": "...", "force_resubmit": true}

		Returns JSON result dict from TaxComplianceService.submit_invoice().
		"""
		from flask import current_app
		from pgappforge.plugins.erp.finance.tax_compliance.services import TaxComplianceService

		body: dict = {}
		if request.is_json:
			try:
				body = request.get_json(silent=True) or {}
			except Exception:
				pass

		tenant_id = (
			body.get("tenant_id")
			or current_app.config.get("DEFAULT_TENANT_ID", "")
		)
		force_resubmit: bool = bool(body.get("force_resubmit", False))

		try:
			session = _get_session()
			if callable(session):
				session = session()

			svc = TaxComplianceService()
			result = svc.submit_invoice(
				invoice_id,
				str(tenant_id),
				session,
				force_resubmit=force_resubmit,
			)
			try:
				session.commit()
			except Exception:
				pass

			http_status = 200 if result.get("submitted") else 422
			return jsonify(result), http_status

		except Exception as exc:
			log.warning("submit(%s) failed: %s", invoice_id, exc)
			return jsonify({
				"submitted": False,
				"authority": None,
				"control_number": None,
				"error": str(exc),
			}), 500


__all__ = ["TaxComplianceDashboardView"]
