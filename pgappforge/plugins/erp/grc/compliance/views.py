"""
pgappforge/plugins/erp/grc/compliance/views.py

Compliance calendar view for due-date prioritisation.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

import sqlalchemy as sa
from flask import current_app, jsonify, make_response, request
from pgappforge import expose
from pgappforge.security.decorators import has_access

from pgappforge.plugins.erp.base_view import BaseERPView

log = logging.getLogger(__name__)


def _get_session():
	try:
		ab = current_app.extensions.get("appbuilder")
		if ab and hasattr(ab, "get_session"):
			session = ab.get_session
			return session() if callable(session) else session
		db = current_app.extensions.get("sqlalchemy")
		if db:
			return db.session
	except RuntimeError:
		pass
	raise RuntimeError("Cannot obtain database session")


def _he(value: object) -> str:
	return (
		str(value if value is not None else "")
		.replace("&", "&amp;")
		.replace("<", "&lt;")
		.replace(">", "&gt;")
		.replace('"', "&quot;")
	)


def _page_html(title: str, body: str) -> str:
	return (
		f'<!DOCTYPE html><html><head><meta charset="utf-8"><title>{_he(title)}</title>'
		'<link rel="stylesheet" href="https://maxcdn.bootstrapcdn.com/bootstrap/3.3.7/css/bootstrap.min.css">'
		"<style>"
		"body{padding:24px}"
		".grc-table{width:100%;border-collapse:collapse;background:#fff;margin-bottom:18px}"
		".grc-table th,.grc-table td{border:1px solid #e5e7eb;padding:8px 10px;text-align:left}"
		".grc-table th{background:#f9fafb;font-size:12px;text-transform:uppercase;color:#374151}"
		".badge-priority{display:inline-block;border-radius:4px;padding:2px 8px;font-size:12px;font-weight:700;color:#fff}"
		".priority-overdue{background:#dc2626}"
		".priority-week{background:#ff5a1f}"
		".priority-upcoming{background:#1a56db}"
		"</style></head><body>"
		f"{body}</body></html>"
	)


def _obligation_model():
	try:
		from pgappforge.plugins.erp.grc.compliance import models
	except Exception:
		return None
	return getattr(models, "ComplianceObligation", None)


def _as_date(value: object) -> date | None:
	if isinstance(value, datetime):
		return value.date()
	if isinstance(value, date):
		return value
	return None


def _display_value(row: object, names: tuple[str, ...], fallback: str = "") -> str:
	for name in names:
		if hasattr(row, name):
			value = getattr(row, name)
			if value:
				return str(value)
	return fallback


_DENIED_PARTY_LISTS = ("OFAC", "UN", "EU", "AU")


class ComplianceCalendarView(BaseERPView):
	route_base = "/grc/compliance/calendar"
	default_view = "index"

	@expose("/")
	@has_access
	def index(self):
		obligations: list[object] = []
		todo = ""
		model = _obligation_model()
		if model is None or not hasattr(model, "due_date"):
			# TODO: Wire this query to ComplianceObligation once the model exists.
			todo = "ComplianceObligation with due_date is not defined yet."
		else:
			try:
				session = _get_session()
				tenant_id = request.args.get("tenant_id") or str(current_app.config.get("DEFAULT_TENANT_ID", ""))
				q = sa.select(model).order_by(model.due_date)
				if tenant_id and hasattr(model, "tenant_id"):
					q = q.where(model.tenant_id == tenant_id)
				if hasattr(model, "status"):
					q = q.where(~model.status.in_(("COMPLETED", "CLOSED", "completed", "closed")))
				obligations = session.execute(q).scalars().all()
			except Exception:
				log.exception("ComplianceCalendarView.index: failed to load obligations")
				obligations = []

		body = (
			"<h3>Compliance Calendar</h3>"
			"<p class=\"text-muted\">Overdue, due-this-week, and upcoming obligations sorted by due date.</p>"
			f"{self._calendar_table(obligations, todo)}"
		)
		return make_response(_page_html("Compliance Calendar", body), 200)

	def _calendar_table(self, obligations: list[object], todo: str = "") -> str:
		today = date.today()
		week_end = today + timedelta(days=7)
		classified: list[tuple[int, str, str, object]] = []
		for row in obligations:
			due_date = _as_date(getattr(row, "due_date", None))
			if due_date is None:
				continue
			if due_date < today:
				classified.append((0, "Overdue", "priority-overdue", row))
			elif due_date <= week_end:
				classified.append((1, "Due This Week", "priority-week", row))
			else:
				classified.append((2, "Upcoming", "priority-upcoming", row))
		classified.sort(key=lambda item: (item[0], _as_date(getattr(item[3], "due_date", None)) or date.max))

		rows = [
			"<table class=\"grc-table\">",
			"<thead><tr><th>Priority</th><th>Obligation</th><th>Due Date</th><th>Owner</th><th>Status</th></tr></thead>",
			"<tbody>",
		]
		if todo:
			rows.append(f"<tr><td colspan=\"5\" class=\"text-muted\">TODO: {_he(todo)}</td></tr>")
		elif not classified:
			rows.append("<tr><td colspan=\"5\" class=\"text-muted\">No compliance obligations found.</td></tr>")
		for _, label, css_class, row in classified:
			due_date = _as_date(getattr(row, "due_date", None))
			rows.append(
				"<tr>"
				f"<td><span class=\"badge-priority {css_class}\">{_he(label)}</span></td>"
				f"<td>{_he(_display_value(row, ('name', 'title', 'obligation_name', 'description'), 'Obligation'))}</td>"
				f"<td>{_he(due_date.isoformat() if due_date else '')}</td>"
				f"<td>{_he(_display_value(row, ('owner', 'owner_id', 'responsible_id'), ''))}</td>"
				f"<td>{_he(_display_value(row, ('status',), ''))}</td>"
				"</tr>"
			)
		rows.append("</tbody></table>")
		return "".join(rows)


class DeniedPartyDashboardView(BaseERPView):
	"""Denied-party screening dashboard.

	No denied-party ORM model exists in this repo yet, so metrics are zero-safe
	stubs until a screening/match/list-update model is added.
	"""

	route_base = "/grc/denied-party"
	default_view = "dashboard"

	@expose("/dashboard")
	@has_access
	def dashboard(self):
		metrics = {
			"screenings_today": 0,
			"pending_matches": 0,
			"false_positive_rate_pct": 0.0,
			"todo": "TODO: wire DeniedPartyScreening / SanctionsListUpdate models when available.",
		}
		list_updates = [
			{
				"list_name": name,
				"last_updated": None,
				"status": "TODO",
			}
			for name in _DENIED_PARTY_LISTS
		]

		if request.args.get("format") == "json":
			return jsonify({**metrics, "list_updates": list_updates})

		rows = "".join(
			"<tr>"
			f"<td>{_he(row['list_name'])}</td>"
			f"<td>{_he(row['last_updated'] or 'Not connected')}</td>"
			f"<td>{_he(row['status'])}</td>"
			"</tr>"
			for row in list_updates
		)
		body = (
			"<h3>Denied-Party Screening</h3>"
			"<div class=\"row\">"
			f"<div class=\"col-sm-4\"><div class=\"well\"><strong>Screenings Today</strong><br>{metrics['screenings_today']}</div></div>"
			f"<div class=\"col-sm-4\"><div class=\"well\"><strong>Pending Matches</strong><br>{metrics['pending_matches']}</div></div>"
			f"<div class=\"col-sm-4\"><div class=\"well\"><strong>False Positive Rate</strong><br>{metrics['false_positive_rate_pct']:.2f}%</div></div>"
			"</div>"
			f"<p class=\"text-muted\">{_he(metrics['todo'])}</p>"
			"<table class=\"grc-table\">"
			"<thead><tr><th>List</th><th>Last Updated</th><th>Status</th></tr></thead>"
			f"<tbody>{rows}</tbody></table>"
		)
		return make_response(_page_html("Denied-Party Screening", body), 200)


__all__ = ["ComplianceCalendarView", "DeniedPartyDashboardView"]
