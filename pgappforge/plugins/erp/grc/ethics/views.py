"""
pgappforge/plugins/erp/grc/ethics/views.py

Flask-AppBuilder views for the Ethics & Hotline plugin.
"""
from __future__ import annotations
from flask_babel import lazy_gettext as _

import logging
from datetime import datetime, timedelta, timezone

import sqlalchemy as sa
from flask import make_response, render_template
from pgappforge import ModelView, expose
from pgappforge.models.sqla.interface import SQLAInterface
from pgappforge.security.decorators import has_access

from pgappforge.plugins.erp.base_view import BaseERPView
from pgappforge.plugins.erp.grc.ethics.models import EthicsCase, EthicsReport

log = logging.getLogger(__name__)


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
		".status-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin-bottom:18px}"
		".status-card{border:1px solid #e5e7eb;border-radius:6px;background:#fff;padding:14px 16px}"
		".status-card h4{margin:0 0 6px;font-size:12px;color:#6b7280;text-transform:uppercase;font-weight:700}"
		".status-card .value{font-size:30px;font-weight:800;line-height:1}"
		".badge-overdue{display:inline-block;border-radius:4px;background:#dc2626;color:#fff;padding:2px 8px;font-size:12px;font-weight:700}"
		"</style></head><body>"
		f"{body}</body></html>"
	)


class EthicsReportView(ModelView):
	datamodel = SQLAInterface(EthicsReport)
	list_columns = ["category", "severity", "status", "submitted_at"]
	label_columns = {
		"category": _("Category"),
		"severity": _("Severity"),
		"status": _("Status"),
		"submitted_at": _("Submitted"),
	}
	add_exclude_columns = ["id", "submitted_at"]
	edit_exclude_columns = ["id", "submitted_at"]
	show_exclude_columns = ["anonymous_token_hash"]
	search_exclude_columns = ["anonymous_token_hash"]


class EthicsCaseView(ModelView):
	datamodel = SQLAInterface(EthicsCase)
	list_columns = ["report_id", "status", "assigned_to", "opened_at", "closed_at"]
	label_columns = {
		"report_id": _("Report"),
		"status": _("Status"),
		"assigned_to": _("Investigator"),
		"opened_at": _("Opened"),
		"closed_at": _("Closed"),
	}
	add_exclude_columns = ["id", "opened_at"]
	edit_exclude_columns = ["id", "opened_at"]
	show_exclude_columns = ["id"]


class EthicsHotlineDashboardView(BaseERPView):
	route_base = "/grc/ethics"

	@expose("/")
	@has_access
	def index(self):
		return render_template(
			"grc_ethics/ethics_hotline.html",
			appbuilder=self.appbuilder,
		)


class EthicsDashboardView(BaseERPView):
	route_base = "/grc/ethics/dashboard"

	@expose("/")
	@has_access
	def index(self):
		total_cases = 0
		by_status = {"new": 0, "investigating": 0, "closed": 0}
		avg_days_to_close = 0.0
		overdue_cases: list[EthicsCase] = []

		try:
			sess = self._session()
			total_cases = sess.execute(sa.select(sa.func.count()).select_from(EthicsCase)).scalar() or 0
			status_rows = sess.execute(
				sa.select(EthicsCase.status, sa.func.count(EthicsCase.id).label("count"))
				.group_by(EthicsCase.status)
			).all()
			for row in status_rows:
				status = str(row.status or "").lower()
				count = int(row.count or 0)
				if status in ("new", "open"):
					by_status["new"] += count
				elif status in ("investigating", "under_investigation", "in_progress"):
					by_status["investigating"] += count
				elif status in ("closed", "resolved"):
					by_status["closed"] += count

			closed_rows = sess.execute(
				sa.select(EthicsCase.opened_at, EthicsCase.closed_at)
				.where(EthicsCase.opened_at.isnot(None), EthicsCase.closed_at.isnot(None))
			).all()
			durations = [
				(row.closed_at - row.opened_at).total_seconds() / 86400
				for row in closed_rows
				if row.opened_at and row.closed_at and row.closed_at >= row.opened_at
			]
			avg_days_to_close = round(sum(durations) / len(durations), 1) if durations else 0.0

			cutoff = datetime.now(timezone.utc) - timedelta(days=30)
			overdue_cases = sess.execute(
				sa.select(EthicsCase)
				.where(
					EthicsCase.opened_at <= cutoff,
					~EthicsCase.status.in_(("CLOSED", "RESOLVED", "closed", "resolved")),
				)
				.order_by(EthicsCase.opened_at)
				.limit(25)
			).scalars().all()
		except Exception:
			log.exception("EthicsDashboardView.index: failed to load ethics case metrics")

		kpi_html = self.kpi_cards([
			{"label": "Total Cases", "value": total_cases, "format": "integer", "icon": "fa-folder-open", "color": "#1a56db"},
			{"label": "New", "value": by_status["new"], "format": "integer", "icon": "fa-flag", "color": "#ff5a1f"},
			{"label": "Investigating", "value": by_status["investigating"], "format": "integer", "icon": "fa-search", "color": "#1c64f2"},
			{"label": "Avg Days to Close", "value": avg_days_to_close, "format": "number", "icon": "fa-clock", "color": "#0e9f6e" if avg_days_to_close <= 30 else "#dc2626"},
		])
		body = (
			"<h3>Ethics Case Dashboard</h3>"
			"<p class=\"text-muted\">Reporter identity is not shown in the case tracker.</p>"
			f"{kpi_html}"
			f"{self._status_cards(by_status)}"
			f"{self._investigation_tracker(overdue_cases)}"
		)
		return make_response(_page_html("Ethics Case Dashboard", body), 200)

	def _status_cards(self, by_status: dict[str, int]) -> str:
		return (
			"<div class=\"status-grid\">"
			+ "".join(
				"<div class=\"status-card\">"
				f"<h4>{_he(label.replace('_', ' '))}</h4>"
				f"<div class=\"value\">{count}</div>"
				"</div>"
				for label, count in by_status.items()
			)
			+ "</div>"
		)

	def _investigation_tracker(self, cases: list[EthicsCase]) -> str:
		rows = [
			"<h4>Investigation Tracker</h4>",
			"<table class=\"grc-table\">",
			"<thead><tr><th>Case</th><th>Status</th><th>Investigator</th><th>Opened</th><th>Flag</th></tr></thead>",
			"<tbody>",
		]
		if not cases:
			rows.append("<tr><td colspan=\"5\" class=\"text-muted\">No cases are open beyond 30 days.</td></tr>")
		for case in cases:
			opened_at = getattr(case, "opened_at", None)
			rows.append(
				"<tr>"
				f"<td>{_he(getattr(case, 'id', ''))}</td>"
				f"<td>{_he(getattr(case, 'status', ''))}</td>"
				f"<td>{_he(getattr(case, 'assigned_to', '') or 'Unassigned')}</td>"
				f"<td>{_he(opened_at.date().isoformat() if opened_at else '')}</td>"
				"<td><span class=\"badge-overdue\">Overdue &gt; 30 days</span></td>"
				"</tr>"
			)
		rows.append("</tbody></table>")
		return "".join(rows)


__all__ = [
	"EthicsReportView",
	"EthicsCaseView",
	"EthicsHotlineDashboardView",
	"EthicsDashboardView",
]
