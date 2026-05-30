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
from flask import abort, jsonify, make_response, request, send_file

from pgappforge import BaseView, expose
from pgappforge.security.decorators import has_access
from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

from .models import (
	BandType,
	FieldType,
	Orientation,
	ParameterType,
	PaperSize,
	Report,
	ReportBand,
	ReportField,
	ReportParameter,
)
from .designer import ReportDesignerView
from .engine import ReportEngine

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
				f"   class='btn btn-xs btn-warning' target='_blank'>CSV</a>"
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
		session  = self._get_session()
		params   = {k: v for k, v in request.args.items()}
		limit    = _get_config("REPORTS_PREVIEW_ROW_LIMIT", 10)
		try:
			engine  = ReportEngine(session, preview_row_limit=int(limit))
			html    = engine.generate_html(report_id, params=params)
		except LookupError:
			abort(404)
		except Exception as exc:
			log.exception("run failed for report_id=%s", report_id)
			html = f"<pre style='color:red'>Report error:\n{_he(str(exc))}</pre>"
		return make_response(html, 200)

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
			else:
				abort(400, description=f"Unsupported format: {fmt!r}. Use pdf, xlsx, or csv.")
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
			name        = "reports",
			version     = "0.1.0",
			description = (
				"Banded report builder: drag-and-drop designer, "
				"PDF/XLSX/HTML/CSV output, parameters, grouping."
			),
			author      = "PgAppForge Contributors",
			tags        = ["reports", "pdf", "excel", "banded", "designer"],
			priority    = PluginPriority.NORMAL,
			permissions = [
				"can_reports_list",
				"can_reports_run",
				"can_reports_download",
				"can_reports_designer",
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
				"reports plugin: openpyxl not installed — "
				"XLSX generation will raise RuntimeError at request time"
			)

		log.info("reports plugin: initialized")

	# ------------------------------------------------------------------ #
	# Views                                                               #
	# ------------------------------------------------------------------ #

	def register_views(self) -> None:
		category = self.config.get("REPORTS_MENU_CATEGORY", "Reports")

		self.add_view(
			ReportListView,
			"Reports",
			icon     = "fa-file-text-o",
			category = category,
		)
		self.add_view(
			ReportDesignerView,
			"Report Designer",
			icon     = "fa-pencil-square-o",
			category = category,
		)
		self.add_view_no_menu(ReportPreviewView)
		log.info("reports plugin: views registered under category %r", category)

	# ------------------------------------------------------------------ #
	# Models                                                              #
	# ------------------------------------------------------------------ #

	def register_models(self) -> list:
		"""Return model classes for Alembic autogenerate discovery."""
		return [Report, ReportBand, ReportField, ReportParameter]

	# ------------------------------------------------------------------ #
	# Config schema                                                       #
	# ------------------------------------------------------------------ #

	def get_config_schema(self) -> dict:
		return _CONFIG_SCHEMA


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _he(text: str) -> str:
	return (
		str(text)
		.replace("&", "&amp;")
		.replace("<", "&lt;")
		.replace(">", "&gt;")
		.replace('"', "&quot;")
	)


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
