"""
pgappforge/plugins/reports/__init__.py

ReportsPlugin — a complete banded report builder rivalling Embarcadero
ReportBuilder, implemented as a first-class PgAppForge plugin.

Features
--------
* Banded report model (title / page-header / column-header / group-header /
  detail / group-footer / summary / page-footer)
* Drag-and-drop WYSIWYG designer (SortableJS, no server-side templates)
* ReportEngine with PDF (reportlab), XLSX (openpyxl), HTML, and CSV output
* Named, typed runtime parameters with automatic coercion
* Group-by support for hierarchical data
* Per-field data binding, format strings, and rich JSONB style metadata

Enabling the plugin
-------------------
Add to your application config::

    PGAPPFORGE_PLUGINS = ["pgappforge.plugins.reports"]

Or instantiate directly::

    from pgappforge.plugins.reports import create_plugin
    plugin = create_plugin(appbuilder)
    plugin.activate()

Configuration keys
------------------
``REPORTS_MENU_CATEGORY`` : str, default "Reports"
    FAB menu category used for all report views.

``REPORTS_PREVIEW_ROW_LIMIT`` : int, default 10
    Maximum rows fetched for HTML preview in the designer.

``REPORTS_DOWNLOAD_ROW_LIMIT`` : int | None, default None (all rows)
    Hard cap on rows included in PDF / XLSX / CSV downloads.
    ``None`` means no limit — use with caution on large datasets.
"""

from __future__ import annotations

import io
import logging
from typing import Any

import sqlalchemy as sa
from datetime import datetime, timezone
from flask import abort, jsonify, make_response, request, send_file

from pgappforge import BaseView, expose
from pgappforge.security.decorators import has_access
from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

from .models import (
	BandType,
	Dashboard,
	DispatchStatus,
	FieldType,
	JobStatus,
	Orientation,
	ParameterType,
	PaperSize,
	Report,
	ReportAccessLog,
	ReportBand,
	ReportCategory,
	ReportDatasource,
	ReportField,
	ReportGrant,
	ReportJob,
	ReportParameter,
	ReportRenderCache,
	ReportShareToken,
	ReportSubscription,
	ReportVersion,
)
from .designer import ReportDesignerView
from .engine import ReportEngine
from .wizard import ReportWizardView
from .sql_editor import SqlEditorView
from .acl import can as _acl_can, log_access as _log_access, check_token, generate_token
from .categories import ReportCategoryView
from .versioning import ReportVersionView
from .dashboard import DashboardView
from .models import (
	ReportDispatch,
	SavedQuery,
)

log = logging.getLogger(__name__)

__allow_unmapped__ = True

# ---------------------------------------------------------------------------
# Default config
# ---------------------------------------------------------------------------

_DEFAULT_CONFIG: dict[str, Any] = {
	"REPORTS_MENU_CATEGORY":      "Reports",
	"REPORTS_PREVIEW_ROW_LIMIT":  10,
	"REPORTS_DOWNLOAD_ROW_LIMIT": None,
}

_CONFIG_SCHEMA: dict[str, Any] = {
	"$schema": "https://json-schema.org/draft/2020-12/schema",
	"title":   "ReportsPlugin configuration",
	"type":    "object",
	"additionalProperties": False,
	"properties": {
		"REPORTS_MENU_CATEGORY": {
			"type":    "string",
			"default": "Reports",
			"description": "FAB menu category for report views.",
		},
		"REPORTS_PREVIEW_ROW_LIMIT": {
			"type":    "integer",
			"minimum": 1,
			"default": 10,
			"description": "Maximum rows shown in the designer HTML preview.",
		},
		"REPORTS_DOWNLOAD_ROW_LIMIT": {
			"type":    ["integer", "null"],
			"default": None,
			"description": "Hard cap on rows in PDF/XLSX/CSV downloads. null = unlimited.",
		},
	},
}

# ---------------------------------------------------------------------------
# ReportListView
# ---------------------------------------------------------------------------

class ReportListView(BaseView):
	"""
	Simple report catalogue — lists all saved reports with run/download links.

	Registered at ``/reports/`` by the plugin.
	"""

	route_base   = "/reports"
	default_view = "index"

	@expose("/")
	@has_access
	def index(self):
		session = self._get_session()
		reports = session.execute(
			sa.select(Report).order_by(Report.name)
		).scalars().all()

		rows = ""
		for r in reports:
			rows += (
				f"<tr>"
				f"<td>{r.id}</td>"
				f"<td>{_he(r.name)}</td>"
				f"<td>{_he(r.description or '')}</td>"
				f"<td>{r.paper_size.value} / {r.orientation.value}</td>"
				f"<td>"
				f"<a href='/reports/run/{r.id}' class='btn btn-xs btn-primary'>Run</a> "
				f"<a href='/reports/designer/{r.id}' class='btn btn-xs btn-default'>Design</a> "
				f"<a href='/reports/download/{r.id}?format=pdf' "
				f"   class='btn btn-xs btn-danger' target='_blank'>PDF</a> "
				f"<a href='/reports/download/{r.id}?format=xlsx' "
				f"   class='btn btn-xs btn-success' target='_blank'>XLSX</a> "
				f"<a href='/reports/download/{r.id}?format=csv' "
				f"   class='btn btn-xs btn-warning' target='_blank'>CSV</a> "
				f"<a href='/reports/download/{r.id}?format=docx' "
				f"   class='btn btn-xs btn-info' target='_blank'>DOCX</a> "
				f"<button onclick=\"dispatchDlg({r.id})\" "
				f"   class='btn btn-xs btn-default'><i class='fa fa-envelope'></i> Email</button>"
				f"</td>"
				f"</tr>"
			)

		html = f"""\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Reports</title>
  <link rel="stylesheet"
        href="https://maxcdn.bootstrapcdn.com/bootstrap/3.3.7/css/bootstrap.min.css">
  <link rel="stylesheet"
        href="https://maxcdn.bootstrapcdn.com/font-awesome/4.7.0/css/font-awesome.min.css">
</head>
<body style="padding:30px">
  <h2><i class="fa fa-file-text-o"></i> Reports</h2>
  <a href="/reports/designer/" class="btn btn-default btn-sm">
    <i class="fa fa-pencil"></i> Designer
  </a>
  <hr>
  <table class="table table-bordered table-hover table-condensed">
    <thead>
      <tr>
        <th>#</th><th>Name</th><th>Description</th>
        <th>Paper</th><th>Actions</th>
      </tr>
    </thead>
    <tbody>{rows}</tbody>
  </table>
</body>
</html>"""
		return make_response(html, 200)

	def _get_session(self):
		if hasattr(self, "appbuilder") and self.appbuilder is not None:
			if hasattr(self.appbuilder, "get_session"):
				return self.appbuilder.get_session
		from flask import current_app
		db = current_app.extensions.get("sqlalchemy")
		if db is not None:
			return db.session
		raise RuntimeError("Cannot obtain database session")


# ---------------------------------------------------------------------------
# ReportPreviewView  (GET /reports/run/<id>)
# ---------------------------------------------------------------------------

class ReportPreviewView(BaseView):
	"""
	Run endpoint — renders and returns HTML preview in the browser.

	Also serves as the entry point for the designer's iframe preview.
	GET /reports/run/<id>[?param1=value1&…]
	"""

	route_base   = "/reports"
	default_view = "run"

	@expose("/run/<int:report_id>")
	@has_access
	def run(self, report_id: int):
		"""
		Run endpoint. When the report has ReportParameter rows and none are
		supplied in the query string, renders a parameter-prompt form first.
		"""
		from .models import Report
		import sqlalchemy as sa
		session = self._get_session()
		report  = session.execute(sa.select(Report).where(Report.id == report_id)).scalar_one_or_none()
		if report is None:
			abort(404)

		# ACL check
		try:
			from flask_login import current_user
			if not _acl_can(current_user, report, "run", session):
				abort(403)
			_log_access(session, getattr(current_user, "id", None), report_id,
			            "run", dict(request.args), request.remote_addr)
		except Exception:
			pass

		params = {k: v for k, v in request.args.items()}

		# Check if required params are missing → show prompt form
		missing_required = [
			p for p in report.parameters
			if p.required and p.name not in params
		]
		all_params = list(report.parameters)

		if all_params and not params:
			# No params supplied at all — show the prompt form
			return make_response(self._param_prompt_html(report), 200)

		limit = _get_config("REPORTS_PREVIEW_ROW_LIMIT", 10)
		try:
			engine = ReportEngine(session, preview_row_limit=int(limit))
			html   = engine.generate_html(report_id, params=params)
		except LookupError:
			abort(404)
		except Exception as exc:
			log.exception("run failed for report_id=%s", report_id)
			html = f"<pre style='color:red'>Report error:\n{_he(str(exc))}</pre>"
		return make_response(html, 200)

	def _param_prompt_html(self, report) -> str:
		"""Render a parameter-prompt form for reports with runtime parameters."""
		fields = ""
		for p in report.parameters:
			input_type = {
				"date": "date", "boolean": "checkbox",
				"integer": "number", "float": "number",
			}.get(p.param_type.value if hasattr(p.param_type, "value") else str(p.param_type), "text")
			label   = _he(p.label or p.name.replace("_", " ").title())
			name    = _he(p.name)
			defval  = _he(p.default_value or "")
			req     = "required" if p.required else ""
			req_star = '<span class="text-danger"> *</span>' if p.required else ""
			fields += (
				f'<div class="mb-3">'
				f'<label class="form-label fw-bold">{label}{req_star}</label>'
				f'<input type="{input_type}" name="{name}" class="form-control" '
				f'value="{defval}" {req}>'
				f'</div>'
			)
		return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css">
</head><body style="padding:30px;background:#f4f6fa">
<div style="max-width:500px;margin:0 auto;background:#fff;padding:30px;border-radius:8px;box-shadow:0 2px 8px rgba(0,0,0,.1)">
<h4 class="mb-3">{_he(report.name)}</h4>
<p class="text-muted">This report requires parameters. Fill them in and click Run.</p>
<form method="GET">
  {fields}
  <button class="btn btn-primary w-100">Run Report</button>
</form>
</div></body></html>"""

	@expose("/download/<int:report_id>")
	@has_access
	def download(self, report_id: int):
		"""
		Download endpoint — streams PDF, XLSX, or CSV.

		Query params:
		    format : pdf | xlsx | csv   (default: pdf)
		    <param_name> : values forwarded to the report engine as parameters
		"""
		fmt     = request.args.get("format", "pdf").lower()
		params  = {k: v for k, v in request.args.items() if k != "format"}
		session = self._get_session()
		engine  = ReportEngine(session)
		# ACL + audit log
		try:
			from flask_login import current_user
			import sqlalchemy as sa
			report_check = session.execute(
				sa.select(Report).where(Report.id == report_id)
			).scalar_one_or_none()
			if report_check is None:
				abort(404)
			if not _acl_can(current_user, report_check, "download", session):
				abort(403)
			_log_access(session, getattr(current_user, "id", None), report_id,
			            "download", {k: v for k, v in request.args.items() if k != "format"},
			            request.remote_addr, fmt=fmt)
		except Exception:
			pass  # degrade gracefully if auth unavailable

		try:
			if fmt == "pdf":
				data     = engine.generate_pdf(report_id, params=params)
				buf      = io.BytesIO(data)
				return send_file(
					buf,
					mimetype             = "application/pdf",
					as_attachment        = True,
					download_name        = f"report_{report_id}.pdf",
				)
			elif fmt == "xlsx":
				data = engine.generate_excel(report_id, params=params)
				buf  = io.BytesIO(data)
				return send_file(
					buf,
					mimetype             = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
					as_attachment        = True,
					download_name        = f"report_{report_id}.xlsx",
				)
			elif fmt == "csv":
				csv_str  = engine.generate_csv(report_id, params=params)
				response = make_response(csv_str)
				response.headers["Content-Type"]        = "text/csv; charset=utf-8"
				response.headers["Content-Disposition"] = (
					f'attachment; filename="report_{report_id}.csv"'
				)
				return response
			elif fmt == "docx":
				from .docx_export import generate_docx
				report = engine._load_report(report_id)
				rows   = engine.fetch_rows(report_id, params=params)
				data   = generate_docx(report, rows)
				buf    = io.BytesIO(data)
				return send_file(
					buf,
					mimetype             = "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
					as_attachment        = True,
					download_name        = f"report_{report_id}.docx",
				)
			else:
				abort(400, description=f"Unsupported format: {fmt!r}. Use pdf, xlsx, csv, or docx.")
		except LookupError:
			abort(404)
		except RuntimeError as exc:
			# Missing optional dep — tell the user
			return make_response(
				f"<pre style='color:red'>{_he(str(exc))}</pre>", 500
			)
		except Exception as exc:
			log.exception("download failed for report_id=%s fmt=%s", report_id, fmt)
			abort(500)

	@expose("/dispatch/<int:report_id>", methods=["POST"])
	@has_access
	def dispatch(self, report_id: int):
		"""Email a rendered report to one or more recipients."""
		from flask import current_app
		from .dispatch import dispatch_now
		to_email  = request.form.get("to_email", "").strip()
		subject   = request.form.get("subject", "").strip()
		body_text = request.form.get("body_text", "").strip()
		fmt       = request.form.get("format", "pdf").lower()
		if not to_email:
			return jsonify({"ok": False, "error": "to_email is required"}), 400
		session = self._get_session()
		engine  = ReportEngine(session)
		try:
			report = engine._load_report(report_id)
		except LookupError:
			abort(404)
		try:
			d = dispatch_now(
				report=report,
				to_email=to_email,
				subject=subject or f"Report: {report.name}",
				body_text=body_text,
				export_format=fmt,
				params={k: v for k, v in request.form.items()
				        if k not in ("to_email", "subject", "body_text", "format")},
				engine=engine,
				session=session,
				app=current_app,
			)
			if d.status.value == "sent":
				return jsonify({"ok": True, "message": f"Sent to {to_email}"})
			return jsonify({"ok": False, "error": d.error_message or "send failed"}), 500
		except Exception as exc:
			log.exception("dispatch failed report_id=%s", report_id)
			return jsonify({"ok": False, "error": str(exc)}), 500

	# ── Share token ────────────────────────────────────────────────────────

	@expose("/share/<token>")
	def share(self, token: str):
		"""Public share-link endpoint. No login required; token controls access."""
		session = self._get_session()
		report, params = check_token(token, session)
		_log_access(session, None, report.id, "token", params, request.remote_addr)
		engine = ReportEngine(session, preview_row_limit=10)
		html   = engine.generate_html(report.id, params=params)
		return make_response(html, 200)

	@expose("/share/create/<int:report_id>", methods=["POST"])
	@has_access
	def share_create(self, report_id: int):
		"""Create a share token. Returns JSON {ok, token, url}."""
		from flask_login import current_user
		session   = self._get_session()
		max_uses  = request.form.get("max_uses")
		expires   = request.form.get("expires_hours")
		params    = {k: v for k, v in request.form.items()
		             if k not in ("max_uses", "expires_hours")}
		token_str = generate_token(
			session, report_id=report_id,
			created_by=getattr(current_user, "id", None),
			max_uses=int(max_uses) if max_uses else None,
			expires_hours=int(expires) if expires else 24,
			params=params or None,
		)
		return jsonify({"ok": True, "token": token_str, "url": f"/reports/share/{token_str}"})

	# ── Embedded widget ────────────────────────────────────────────────────

	@expose("/embed/<token>")
	def embed(self, token: str):
		"""Stripped iframe-safe HTML. Validates via share token."""
		session = self._get_session()
		report, params = check_token(token, session)
		_log_access(session, None, report.id, "embed", params, request.remote_addr)
		engine = ReportEngine(session, preview_row_limit=50)
		inner  = engine.generate_html(report.id, params=params)
		html = (
			'<!DOCTYPE html><html><head><meta charset="UTF-8">'
			'<style>body{margin:0;padding:8px;font-family:sans-serif}</style>'
			f'</head><body>{inner}</body></html>'
		)
		return make_response(html, 200)

	# ── ACL management ─────────────────────────────────────────────────────

	@expose("/acl/<int:report_id>")
	@has_access
	def acl_list(self, report_id: int):
		"""List grants for a report."""
		import sqlalchemy as sa
		session = self._get_session()
		grants  = session.execute(
			sa.select(ReportGrant).where(ReportGrant.report_id == report_id)
		).scalars().all()
		return jsonify({"grants": [
			{"id": g.id, "principal_type": g.principal_type,
			 "principal_id": g.principal_id, "permission": g.permission}
			for g in grants
		]})

	@expose("/acl/<int:report_id>", methods=["POST"])
	@has_access
	def acl_add(self, report_id: int):
		"""Add a grant. Body: {principal_type, principal_id, permission}."""
		from flask_login import current_user
		data           = request.get_json(silent=True) or {}
		principal_type = data.get("principal_type", "user")
		principal_id   = int(data.get("principal_id", 0))
		permission     = data.get("permission", "view")
		if permission not in ("view", "run", "download", "edit"):
			return jsonify({"ok": False, "error": "invalid permission"}), 400
		session = self._get_session()
		g = ReportGrant(
			report_id=report_id,
			principal_type=principal_type,
			principal_id=principal_id,
			permission=permission,
			granted_by=getattr(current_user, "id", None),
		)
		session.add(g)
		session.commit()
		return jsonify({"ok": True, "id": g.id})

	@expose("/acl/<int:report_id>/<int:grant_id>", methods=["DELETE"])
	@has_access
	def acl_remove(self, report_id: int, grant_id: int):
		"""Remove a grant by id."""
		session = self._get_session()
		g = session.get(ReportGrant, grant_id)
		if g is None or g.report_id != report_id:
			abort(404)
		session.delete(g)
		session.commit()
		return jsonify({"ok": True})

	# ── Subscriptions ─────────────────────────────────────────────────────

	@expose("/subscribe/<int:report_id>", methods=["POST"])
	@has_access
	def subscribe(self, report_id: int):
		"""Subscribe current user to recurring report delivery."""
		from flask_login import current_user
		from .models import ReportSubscription
		session   = self._get_session()
		frequency = request.form.get("frequency", "FREQ=WEEKLY;BYDAY=MO")
		fmt       = request.form.get("format", "pdf")
		params    = {k: v for k, v in request.form.items()
		             if k not in ("frequency", "format")}
		uid = getattr(current_user, "id", None)
		if uid is None:
			return jsonify({"ok": False, "error": "login required"}), 401
		# Compute first run
		from datetime import timedelta
		first_run = None
		try:
			from .subscriptions import _next_occurrence
			from datetime import timezone
			first_run = _next_occurrence(frequency, datetime.now(timezone.utc))
		except Exception:
			from datetime import timezone
			first_run = datetime.now(timezone.utc) + timedelta(days=1)
		sub = ReportSubscription(
			report_id=report_id, user_id=uid,
			format=fmt, frequency=frequency,
			params_json=params, next_run_at=first_run,
		)
		session.add(sub)
		session.commit()
		return jsonify({"ok": True, "id": sub.id, "next_run_at": str(first_run)})

	@expose("/unsubscribe/<int:subscription_id>", methods=["POST"])
	@has_access
	def unsubscribe(self, subscription_id: int):
		"""Deactivate a subscription."""
		from flask_login import current_user
		from .models import ReportSubscription
		import sqlalchemy as sa
		session = self._get_session()
		sub = session.get(ReportSubscription, subscription_id)
		if sub is None:
			abort(404)
		uid = getattr(current_user, "id", None)
		if sub.user_id != uid:
			abort(403)
		sub.is_active = False
		session.commit()
		return jsonify({"ok": True})

	# ── Background render jobs ─────────────────────────────────────────────

	@expose("/render-async/<int:report_id>", methods=["POST"])
	@has_access
	def render_async(self, report_id: int):
		"""
		Enqueue a background render job. Returns {job_id} immediately.
		Poll GET /reports/jobs/<job_id>/status for result.
		"""
		from flask_login import current_user
		from .models import ReportJob, JobStatus
		import sqlalchemy as sa
		session = self._get_session()
		fmt     = request.form.get("format", "pdf")
		params  = {k: v for k, v in request.form.items() if k != "format"}
		job = ReportJob(
			report_id=report_id,
			format=fmt,
			params_json=params,
			status=JobStatus.PENDING,
			created_by=getattr(current_user, "id", None),
		)
		session.add(job)
		session.commit()
		# Kick off background thread
		self._run_job_async(job.id)
		return jsonify({"ok": True, "job_id": job.id})

	@expose("/jobs/<int:job_id>/status")
	@has_access
	def job_status(self, job_id: int):
		"""Poll render job status."""
		from .models import ReportJob
		import sqlalchemy as sa
		session = self._get_session()
		job = session.get(ReportJob, job_id)
		if job is None:
			abort(404)
		result = {"status": job.status.value, "error": job.error}
		if job.result_token:
			result["download_url"] = f"/reports/share/{job.result_token}"
		return jsonify(result)

	def _run_job_async(self, job_id: int) -> None:
		"""Spawn a daemon thread to render the report and store a share token."""
		import threading
		from flask import copy_current_request_context

		@copy_current_request_context
		def _run():
			from .models import ReportJob, JobStatus
			from .engine import ReportEngine
			from .acl import generate_token
			from datetime import datetime, timezone
			import sqlalchemy as sa
			session = self._get_session()
			job = session.get(ReportJob, job_id)
			if not job:
				return
			try:
				job.status = JobStatus.RUNNING
				session.commit()
				engine = ReportEngine(session)
				if job.format == "pdf":
					data = engine.generate_pdf(job.report_id, job.params_json)
					ext  = "pdf"
				elif job.format == "xlsx":
					data = engine.generate_excel(job.report_id, job.params_json)
					ext  = "xlsx"
				else:
					data = engine.generate_csv(job.report_id, job.params_json).encode()
					ext  = "csv"
				# Store as share token (15 min TTL, 1 use)
				from .models import ReportShareToken
				import secrets
				tok_str  = secrets.token_urlsafe(24)
				from datetime import timedelta
				expires  = datetime.now(timezone.utc) + timedelta(minutes=15)
				tok = ReportShareToken(
					token=tok_str, report_id=job.report_id,
					max_uses=1, uses_remaining=1,
					expires_at=expires,
					params_json=job.params_json or {},
					created_by=job.created_by,
				)
				session.add(tok)
				job.result_token = tok_str
				job.status       = JobStatus.DONE
				job.finished_at  = datetime.now(timezone.utc)
				session.commit()
			except Exception as exc:
				log.exception("ReportForge job %s failed", job_id)
				job.status = JobStatus.FAILED
				job.error  = str(exc)
				session.commit()

		threading.Thread(target=_run, daemon=True).start()

	def _get_session(self):
		if hasattr(self, "appbuilder") and self.appbuilder is not None:
			if hasattr(self.appbuilder, "get_session"):
				return self.appbuilder.get_session
		from flask import current_app
		db = current_app.extensions.get("sqlalchemy")
		if db is not None:
			return db.session
		raise RuntimeError("Cannot obtain database session")


# ---------------------------------------------------------------------------
# ReportsPlugin
# ---------------------------------------------------------------------------

class ReportsPlugin(BasePlugin):
	"""
	Banded report builder plugin for PgAppForge.

	Lifecycle::

	    plugin = ReportsPlugin(appbuilder, config={...})
	    plugin.activate()   # initialize() → register_views()
	    plugin.deactivate()

	Views registered:
	    ReportListView     → /reports/
	    ReportPreviewView  → /reports/run/<id>, /reports/download/<id>
	    ReportDesignerView → /reports/designer/…
	"""

	# ------------------------------------------------------------------ #
	# Metadata                                                            #
	# ------------------------------------------------------------------ #

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name        = "reportforge",
			version     = "1.0.0",
			description = (
				"ReportForge — professional report builder with WYSIWYG designer, "
				"branding, watermarks, DOCX/PDF/XLSX/CSV export, email dispatch, "
				"AI text augmentation, business templates (invoice, quote, statement, "
				"business letter), report generation wizard, and visual SQL editor."
			),
			author      = "PgAppForge Contributors",
			tags        = ["reports", "reportforge", "pdf", "docx", "excel", "banded",
			               "designer", "invoice", "wizard", "sql-editor", "ai"],
			priority    = PluginPriority.NORMAL,
			permissions = [
				"can_reports_list",
				"can_reports_run",
				"can_reports_download",
				"can_reports_designer",
				"can_reports_dispatch",
				"can_access_sql_editor",
			],
			safe_mode_compatible = True,
			example_config       = _DEFAULT_CONFIG,
		)

	# ------------------------------------------------------------------ #
	# Lifecycle                                                           #
	# ------------------------------------------------------------------ #

	def initialize(self) -> None:
		"""Merge defaults and validate optional dep availability."""
		merged      = {**_DEFAULT_CONFIG, **self.config}
		self.config = merged

		# Runtime capability checks
		try:
			import reportlab  # noqa: F401
		except ImportError:
			log.warning(
				"reports plugin: reportlab not installed — "
				"PDF generation will raise RuntimeError at request time"
			)
		try:
			import openpyxl  # noqa: F401
		except ImportError:
			log.warning(
				"reportforge: openpyxl not installed — "
				"XLSX generation will raise RuntimeError at request time"
			)
		try:
			import docx  # noqa: F401
		except ImportError:
			log.info(
				"reportforge: python-docx not installed — "
				"DOCX export disabled (pip install python-docx to enable)"
			)

		log.info("ReportForge plugin: initialized")

	# ------------------------------------------------------------------ #
	# Views                                                               #
	# ------------------------------------------------------------------ #

	def register_views(self) -> None:
		category = self.config.get("REPORTS_MENU_CATEGORY", "ReportForge")

		self.add_view(
			ReportListView,
			"Reports",
			icon     = "fa-file-text-o",
			category = category,
		)
		self.add_view(
			ReportWizardView,
			"New Report (Wizard)",
			icon     = "fa-magic",
			category = category,
		)
		self.add_view(
			ReportDesignerView,
			"Report Designer",
			icon     = "fa-pencil-square-o",
			category = category,
		)
		self.add_view(
			SqlEditorView,
			"SQL Query Editor",
			icon     = "fa-database",
			category = category,
		)
		self.add_view(
			ReportCategoryView,
			"Categories",
			icon     = "fa-folder",
			category = category,
		)
		self.add_view(
			DashboardView,
			"Dashboards",
			icon     = "fa-th-large",
			category = category,
		)
		self.add_view_no_menu(ReportPreviewView)
		self.add_view_no_menu(ReportVersionView)
		log.info("ReportForge plugin: views registered under category %r", category)

	# ------------------------------------------------------------------ #
	# Models                                                              #
	# ------------------------------------------------------------------ #

	def register_models(self) -> list:
		"""Return model classes for Alembic autogenerate discovery."""
		return [Report, ReportBand, ReportField, ReportParameter,
		        ReportDispatch, SavedQuery,
		        ReportDatasource, ReportCategory, ReportGrant,
		        ReportAccessLog, ReportShareToken, ReportVersion,
		        ReportSubscription, Dashboard, ReportRenderCache, ReportJob]

	# ------------------------------------------------------------------ #
	# Config schema                                                       #
	# ------------------------------------------------------------------ #

	def get_config_schema(self) -> dict:
		return _CONFIG_SCHEMA


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

from ._utils import _he


def _get_config(key: str, default: Any = None) -> Any:
	"""Read a config value from Flask's current_app.config."""
	try:
		from flask import current_app
		return current_app.config.get(key, default)
	except RuntimeError:
		return default


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_plugin(
	appbuilder,
	config: dict[str, Any] | None = None,
) -> ReportsPlugin:
	"""
	Construct and return a ReportsPlugin bound to *appbuilder*.

	Does **not** call ``activate()``::

	    plugin = create_plugin(appbuilder, config={"REPORTS_MENU_CATEGORY": "BI"})
	    plugin.activate()
	"""
	return ReportsPlugin(appbuilder, config=config or {})


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	# plugin
	"ReportsPlugin",
	"create_plugin",
	# models
	"Report",
	"ReportBand",
	"ReportField",
	"ReportParameter",
	"BandType",
	"FieldType",
	"PaperSize",
	"Orientation",
	"ParameterType",
	# views
	"ReportListView",
	"ReportPreviewView",
	"ReportDesignerView",
	# engine
	"ReportEngine",
]
