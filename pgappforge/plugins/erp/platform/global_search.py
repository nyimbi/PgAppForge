"""
ERP global search service and view.

Search is intentionally model-optional: each entity is imported dynamically and
searched independently so missing plugins do not break the platform search page.
"""
from __future__ import annotations

import html
import importlib
import logging
from typing import Any

import sqlalchemy as sa
from flask import jsonify, request
from markupsafe import Markup

from pgappforge import expose
from pgappforge.plugins.erp.base_view import BaseERPView
from pgappforge.security.decorators import has_access

log = logging.getLogger(__name__)


ENTITY_CONFIGS: tuple[dict[str, Any], ...] = (
	{
		"entity": "Project",
		"label": "Projects",
		"module": "pgappforge.plugins.erp.projects.models",
		"class_name": "Project",
		"title_fields": ("code", "name"),
		"search_fields": ("code", "name", "description", "status", "project_type", "risk_level", "currency_code"),
		"url_base": "/projects/projects",
	},
	{
		"entity": "Risk",
		"label": "Risks",
		"module": "pgappforge.plugins.erp.projects.models",
		"class_name": "ProjectRisk",
		"title_fields": ("title", "status"),
		"search_fields": ("title", "description", "mitigation", "status"),
		"url_base": "/projects/risks",
	},
	{
		"entity": "Invoice",
		"label": "Invoices",
		"module": "pgappforge.plugins.erp.projects.models",
		"class_name": "ProjectInvoice",
		"title_fields": ("invoice_number", "status"),
		"search_fields": ("invoice_number", "invoice_type", "status", "notes", "gl_journal_id"),
		"url_base": "/projects/invoices",
	},
	{
		"entity": "Supplier",
		"label": "Suppliers",
		"module": "pgappforge.plugins.erp.operations.scm.models",
		"class_name": "Supplier",
		"title_fields": ("supplier_code", "name"),
		"search_fields": ("supplier_code", "name", "supplier_type", "status", "country_code"),
		"url_base": "/scm/suppliers",
	},
	{
		"entity": "Employee",
		"label": "Employees",
		"module": "pgappforge.plugins.erp.hcm.personnel.models",
		"class_name": "Employee",
		"title_fields": ("employee_number", "employment_status"),
		"search_fields": (
			"employee_number",
			"employment_type",
			"employment_status",
			"cost_center_code",
			"background_check_status",
			"background_check_provider",
			"background_check_ref",
			"termination_reason",
		),
		"url_base": "/hcm/personnel/employees",
	},
	{
		"entity": "Opportunity",
		"label": "Opportunities",
		"module": "pgappforge.plugins.erp.crm.sales.models",
		"class_name": "Opportunity",
		"title_fields": ("opportunity_name", "stage"),
		"search_fields": (
			"opportunity_name",
			"stage",
			"forecast_category",
			"currency_code",
			"lead_source",
			"type",
			"reason_won",
			"reason_lost",
			"competitor",
		),
		"url_base": "/crm/opportunities",
	},
)


def _current_tenant_id() -> Any | None:
	try:
		from pgappforge.models.tenant_context import get_current_tenant_id
		return get_current_tenant_id()
	except Exception:
		return None


def _get_session() -> Any | None:
	try:
		from flask import current_app
		ab = current_app.extensions.get("appbuilder") or getattr(current_app, "appbuilder", None)
		if ab and hasattr(ab, "get_session"):
			session = ab.get_session
			return session() if callable(session) else session
		db = current_app.extensions.get("sqlalchemy")
		if db is not None:
			return db.session
	except Exception:
		return None
	return None


def _load_model(config: dict[str, Any]) -> type | None:
	try:
		module = importlib.import_module(config["module"])
		return getattr(module, config["class_name"])
	except Exception as exc:
		log.debug("Global search skipped %s: %s", config.get("entity"), exc)
		return None


def _string_value(row: Any, field: str) -> str:
	value = getattr(row, field, None)
	if value is None:
		return ""
	return str(value)


def _result_title(row: Any, fields: tuple[str, ...]) -> str:
	values = [_string_value(row, field) for field in fields]
	values = [value for value in values if value]
	if values:
		return " - ".join(values)
	row_id = getattr(row, "id", "")
	return str(row_id) if row_id else "Untitled"


def _result_snippet(row: Any, fields: tuple[str, ...], title: str) -> str:
	values: list[str] = []
	for field in fields:
		value = _string_value(row, field)
		if value and value not in title and value not in values:
			values.append(value)
	return " | ".join(values[:3])


class GlobalSearchService:
	"""Search ERP records with PostgreSQL ILIKE filters."""

	def __init__(self, session: Any | None = None) -> None:
		self.session = session

	def search(self, q: str, tenant_id: Any | None = None, limit_per_entity: int = 5) -> list[dict[str, Any]]:
		query_text = (q or "").strip()
		if len(query_text) < 3:
			return []

		session = self.session or _get_session()
		if session is None:
			return []
		if callable(session):
			session = session()

		effective_tenant_id = tenant_id if tenant_id is not None else _current_tenant_id()
		results: list[dict[str, Any]] = []
		for config in ENTITY_CONFIGS:
			try:
				results.extend(
					self._search_entity(
						session=session,
						config=config,
						q=query_text,
						tenant_id=effective_tenant_id,
						limit=limit_per_entity,
					)
				)
			except Exception as exc:
				log.warning("Global search failed for %s: %s", config.get("entity"), exc)
		return results

	def _search_entity(
		self,
		*,
		session: Any,
		config: dict[str, Any],
		q: str,
		tenant_id: Any | None,
		limit: int,
	) -> list[dict[str, Any]]:
		model = _load_model(config)
		if model is None:
			return []

		pattern = f"%{q}%"
		conditions: list[Any] = []
		for field_name in config["search_fields"]:
			if hasattr(model, field_name):
				conditions.append(sa.cast(getattr(model, field_name), sa.String).ilike(pattern))
		if not conditions:
			return []

		query = session.query(model).filter(sa.or_(*conditions))
		if tenant_id is not None and hasattr(model, "tenant_id"):
			query = query.filter(getattr(model, "tenant_id") == tenant_id)

		rows = query.limit(limit).all()
		return [self._serialize(config, row) for row in rows]

	def _serialize(self, config: dict[str, Any], row: Any) -> dict[str, Any]:
		title = _result_title(row, config["title_fields"])
		snippet = _result_snippet(row, config["search_fields"], title)
		row_id = getattr(row, "id", None)
		url_base = str(config.get("url_base") or "").rstrip("/")
		return {
			"entity": config["entity"],
			"entity_type": config["entity"],
			"label": config["label"],
			"id": str(row_id) if row_id is not None else "",
			"title": title,
			"snippet": snippet,
			"url": f"{url_base}/{row_id}" if url_base and row_id is not None else url_base,
		}


def _html_results(q: str, results: list[dict[str, Any]], message: str) -> str:
	escaped_q = html.escape(q)
	rows: list[str] = []
	for result in results:
		rows.append(
			"<tr>"
			f"<td>{html.escape(result.get('label', ''))}</td>"
			f"<td><a href=\"{html.escape(result.get('url', ''))}\">{html.escape(result.get('title', ''))}</a></td>"
			f"<td>{html.escape(result.get('snippet', ''))}</td>"
			"</tr>"
		)
	body = "".join(rows) if rows else "<tr><td colspan=\"3\" class=\"text-muted\">No results</td></tr>"
	return f"""
<div class="container-fluid">
	<div class="row">
		<div class="col-md-12">
			<h2>ERP Search</h2>
			<form method="GET" action="/erp/search/" class="form-inline" role="search" style="margin: 20px 0;">
				<div class="input-group" style="width:100%;max-width:720px;">
					<input type="text" name="q" value="{escaped_q}" class="form-control input-lg" placeholder="Search ERP records" autofocus>
					<span class="input-group-btn">
						<button class="btn btn-primary btn-lg" type="submit">
							<span class="glyphicon glyphicon-search"></span>
							Search
						</button>
					</span>
				</div>
			</form>
			<p class="text-muted">{html.escape(message)}</p>
			<table class="table table-striped table-hover">
				<thead>
					<tr>
						<th style="width:18%;">Entity</th>
						<th style="width:32%;">Record</th>
						<th>Match</th>
					</tr>
				</thead>
				<tbody>{body}</tbody>
			</table>
		</div>
	</div>
</div>
"""


class GlobalSearchView(BaseERPView):
	"""Global ERP search page and JSON API."""

	route_base = "/erp/search"
	default_view = "index"

	@expose("/", methods=["GET"])
	@has_access
	def index(self):
		q = request.args.get("q", "").strip()
		results: list[dict[str, Any]] = []
		message = "Enter at least 3 characters to search."
		if q and len(q) >= 3:
			results = GlobalSearchService().search(q)
			message = f"{len(results)} result(s) for {q!r}."
		content = _html_results(q, results, message)
		return self.render_template("appbuilder/general/model/edit.html", content=Markup(content))

	@expose("/api/", methods=["GET"])
	@has_access
	def api(self):
		q = request.args.get("q", "").strip()
		if len(q) < 3:
			return jsonify({"q": q, "results": [], "total": 0, "message": "Query must be at least 3 characters."})
		results = GlobalSearchService().search(q)
		return jsonify({"q": q, "results": results, "total": len(results)})


__all__ = ["GlobalSearchService", "GlobalSearchView", "ENTITY_CONFIGS"]
