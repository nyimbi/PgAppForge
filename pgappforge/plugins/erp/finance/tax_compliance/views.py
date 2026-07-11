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
from flask_babel import lazy_gettext as _

import logging
from datetime import datetime, timezone

import sqlalchemy as sa
from flask import abort, jsonify, request

from pgappforge import ModelView, expose
from pgappforge.models.sqla import Model
from pgappforge.models.sqla.interface import SQLAInterface
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


def _format_cents(value: object) -> str:
	try:
		return f"{int(value or 0) / 100:,.2f}"
	except Exception:
		return "0.00"


class ETIMSSubmission(Model):
	"""Read model over the DDL-managed tax submission audit table."""

	__tablename__ = "pgaf_tax_submission"
	__table_args__ = ({"extend_existing": True},)

	id = sa.Column(sa.String(36), primary_key=True)
	tenant_id = sa.Column(sa.String(36), nullable=False)
	invoice_id = sa.Column(sa.String(36), nullable=False)
	authority = sa.Column(sa.String(10), nullable=False)
	status = sa.Column(sa.String(10), nullable=False)
	control_number = sa.Column(sa.String(100), nullable=True)
	error_message = sa.Column(sa.Text, nullable=True)
	created_at = sa.Column(sa.DateTime(timezone=True), nullable=False)

	invoice_number = sa.orm.synonym("invoice_id")
	amount = sa.orm.column_property(sa.literal(0))
	submitted_at = sa.orm.synonym("created_at")
	kra_receipt = sa.orm.synonym("control_number")


class ETIMSSubmissionView(ModelView):
	"""eTIMS submission audit list."""

	datamodel = SQLAInterface(ETIMSSubmission)
	route_base = "/etims/submissions"
	list_columns = ["invoice_number", "amount", "status", "submitted_at", "kra_receipt"]
	search_columns = ["status", "submitted_at", "invoice_number"]
	show_columns = [
		"invoice_id", "tenant_id", "authority", "status",
		"control_number", "error_message", "created_at",
	]
	can_add = False
	can_edit = False
	can_delete = False

	label_columns = {
		"invoice_number": _("Invoice Number"),
		"amount": _("Amount"),
		"status": _("Status"),
		"submitted_at": _("Submitted At"),
		"kra_receipt": _("KRA Receipt"),
	}


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


class ETIMSDashboardView(BaseERPView):
	"""Kenya eTIMS KPI dashboard and retry endpoint."""

	route_base = "/etims"
	default_view = "index"

	@expose("/")
	@has_access
	def index(self):
		stats = {
			"pending": 0,
			"submitted": 0,
			"accepted": 0,
			"rejected": 0,
		}
		recent_rows: list[dict[str, object]] = []

		try:
			session = _get_session()
			if callable(session):
				session = session()

			rows = session.execute(
				sa.text(
					"SELECT UPPER(status) AS status, COUNT(*)"
					" FROM pgaf_tax_submission"
					" WHERE UPPER(authority) IN ('KE', 'ETIMS')"
					" GROUP BY UPPER(status)"
				)
			).fetchall()
			for status, count in rows:
				key = self._status_bucket(str(status or ""))
				if key:
					stats[key] += int(count or 0)

			recent_rows = self._recent_submissions(session)
		except Exception as exc:
			log.debug("ETIMSDashboardView.index: stats query failed — %s", exc)

		if request.args.get("format") == "json":
			return jsonify({"kpis": stats, "recent_submissions": recent_rows})

		kpi_html = self.kpi_cards([
			{"label": "Pending", "value": stats["pending"], "format": "integer", "color": "#f59e0b", "icon": "fa-clock-o"},
			{"label": "Submitted", "value": stats["submitted"], "format": "integer", "color": "#1a56db", "icon": "fa-paper-plane"},
			{"label": "Accepted", "value": stats["accepted"], "format": "integer", "color": "#057a55", "icon": "fa-check-circle"},
			{"label": "Rejected", "value": stats["rejected"], "format": "integer", "color": "#c81e1e", "icon": "fa-times-circle"},
		])
		table_rows = "".join(
			"<tr>"
			f"<td>{_he(row.get('invoice_number') or '')}</td>"
			f"<td class='text-right'>{_he(_format_cents(row.get('amount')))}</td>"
			f"<td>{_he(row.get('status') or '')}</td>"
			f"<td>{_he(row.get('submitted_at') or '')}</td>"
			f"<td><code>{_he(row.get('kra_receipt') or '')}</code></td>"
			"</tr>"
			for row in recent_rows
		)
		html = f"""
		<div class='container-fluid' style='padding:1.5rem'>
			<h2 style='margin-bottom:1rem'><i class='fa fa-receipt'></i>&nbsp; eTIMS Dashboard</h2>
			{kpi_html}
			<div class='panel panel-default'>
				<div class='panel-heading'><strong>Recent 20 Submissions</strong></div>
				<div class='panel-body' style='padding:0;overflow-x:auto'>
					<table class='table table-striped table-condensed' style='margin:0'>
						<thead>
							<tr>
								<th>Invoice Number</th><th class='text-right'>Amount</th><th>Status</th>
								<th>Submitted At</th><th>KRA Receipt</th>
							</tr>
						</thead>
						<tbody>{table_rows or '<tr><td colspan=5 style="text-align:center;padding:2rem;color:#888">No eTIMS submissions yet</td></tr>'}</tbody>
					</table>
				</div>
			</div>
		</div>
		"""
		from markupsafe import Markup
		return self.render_template("appbuilder/general/model/edit.html", content=Markup(html))

	@expose("/retry/<invoice_id>", methods=["POST"])
	@has_access
	def retry(self, invoice_id: str):
		from flask import current_app
		from pgappforge.plugins.erp.finance.tax_compliance.services import TaxComplianceService

		body: dict = request.get_json(silent=True) if request.is_json else {}
		body = body or {}
		tenant_id = body.get("tenant_id") or current_app.config.get("DEFAULT_TENANT_ID", "")
		if not tenant_id:
			return jsonify({"ok": False, "error": "tenant_id required"}), 400

		try:
			session = _get_session()
			if callable(session):
				session = session()
			result = TaxComplianceService().submit_invoice(
				invoice_id,
				str(tenant_id),
				session,
				force_resubmit=True,
			)
			try:
				session.commit()
			except Exception:
				pass
			return jsonify({"ok": bool(result.get("submitted")), "result": result})
		except Exception as exc:
			log.warning("ETIMSDashboardView.retry(%s) failed: %s", invoice_id, exc)
			return jsonify({"ok": False, "error": str(exc)}), 500

	def _status_bucket(self, status: str) -> str | None:
		if status in {"PENDING", "QUEUED", "DRAFT", "NEW"}:
			return "pending"
		if status in {"SUBMITTED", "SENT", "IN_PROGRESS"}:
			return "submitted"
		if status in {"SUCCESS", "ACCEPTED", "APPROVED"}:
			return "accepted"
		if status in {"FAILED", "REJECTED", "ERROR"}:
			return "rejected"
		return None

	def _recent_submissions(self, session) -> list[dict[str, object]]:
		try:
			rows = session.execute(
				sa.text(
					"SELECT s.invoice_id,"
					" COALESCE(i.invoice_number, s.invoice_id) AS invoice_number,"
					" COALESCE(i.total_cents, 0) AS amount,"
					" s.status,"
					" s.created_at AS submitted_at,"
					" COALESCE(s.control_number, i.tax_control_number, '') AS kra_receipt"
					" FROM pgaf_tax_submission s"
					" LEFT JOIN ar_invoice i ON CAST(i.id AS VARCHAR) = s.invoice_id"
					" WHERE UPPER(s.authority) IN ('KE', 'ETIMS')"
					" ORDER BY s.created_at DESC LIMIT 20"
				)
			).mappings().all()
		except Exception:
			rows = session.execute(
				sa.text(
					"SELECT invoice_id, invoice_id AS invoice_number, 0 AS amount,"
					" status, created_at AS submitted_at,"
					" COALESCE(control_number, '') AS kra_receipt"
					" FROM pgaf_tax_submission"
					" WHERE UPPER(authority) IN ('KE', 'ETIMS')"
					" ORDER BY created_at DESC LIMIT 20"
				)
			).mappings().all()

		return [
			{
				"invoice_number": row["invoice_number"],
				"amount": int(row["amount"] or 0),
				"status": row["status"],
				"submitted_at": (
					row["submitted_at"].isoformat()
					if isinstance(row["submitted_at"], datetime)
					else str(row["submitted_at"] or "")
				),
				"kra_receipt": row["kra_receipt"],
			}
			for row in rows
		]


__all__ = ["TaxComplianceDashboardView", "ETIMSDashboardView", "ETIMSSubmissionView"]
