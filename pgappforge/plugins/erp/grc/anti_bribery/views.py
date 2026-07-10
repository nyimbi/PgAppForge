"""
pgappforge/plugins/erp/grc/anti_bribery/views.py

Flask-AppBuilder views for the Anti-Bribery & Corruption plugin.
"""
from __future__ import annotations

import logging

import sqlalchemy as sa
from flask import make_response
from pgappforge import ModelView, expose
from pgappforge.models.sqla.interface import SQLAInterface
from pgappforge.security.decorators import has_access

from pgappforge.plugins.erp.base_view import BaseERPView
from pgappforge.plugins.erp.grc.anti_bribery.models import (
	ConflictOfInterestDeclaration,
	GiftEntertainmentLog,
)

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
		".score-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:14px;margin-bottom:18px}"
		".score-card{border:1px solid #e5e7eb;border-radius:6px;background:#fff;padding:18px 16px}"
		".score-card h4{margin:0 0 8px;font-size:12px;color:#6b7280;text-transform:uppercase;font-weight:700}"
		".score-card .value{font-size:34px;font-weight:800;line-height:1}"
		".score-card p{margin:8px 0 0;color:#6b7280;font-size:12px}"
		".grc-table{width:100%;border-collapse:collapse;background:#fff;margin-bottom:18px}"
		".grc-table th,.grc-table td{border:1px solid #e5e7eb;padding:8px 10px;text-align:left}"
		".grc-table th{background:#f9fafb;font-size:12px;text-transform:uppercase;color:#374151}"
		".badge{display:inline-block;border-radius:4px;padding:2px 8px;font-size:12px;font-weight:700}"
		"</style></head><body>"
		f"{body}</body></html>"
	)


def _pct_color(value: float | None) -> str:
	if value is None:
		return "#6b7280"
	if value >= 90:
		return "#0e9f6e"
	if value >= 75:
		return "#ff5a1f"
	return "#dc2626"


def _count_color(value: int | None) -> str:
	if value is None:
		return "#6b7280"
	if value == 0:
		return "#0e9f6e"
	if value <= 5:
		return "#ff5a1f"
	return "#dc2626"


class GiftEntertainmentLogView(ModelView):
	datamodel = SQLAInterface(GiftEntertainmentLog)
	list_columns = ["given_to_name", "given_to_organization", "gift_type", "value_cents", "gift_date", "status", "is_government_official"]
	label_columns = {
		"given_to_name": "Recipient",
		"given_to_organization": "Organization",
		"gift_type": "Type",
		"value_cents": "Value",
		"gift_date": "Gift Date",
		"status": "Status",
		"is_government_official": "Government Official",
	}
	add_exclude_columns = ["id", "created_on", "changed_on"]
	edit_exclude_columns = ["id", "created_on", "changed_on"]


class ConflictOfInterestDeclarationView(ModelView):
	datamodel = SQLAInterface(ConflictOfInterestDeclaration)
	list_columns = ["employee_id", "description", "declaration_date", "status", "reviewed_at"]
	label_columns = {
		"employee_id": "Employee",
		"description": "Description",
		"declaration_date": "Declared",
		"status": "Status",
		"reviewed_at": "Reviewed",
	}
	add_exclude_columns = ["id", "created_on", "changed_on"]
	edit_exclude_columns = ["id", "created_on", "changed_on"]


class GiftsRegisterDashboardView(BaseERPView):
	route_base = "/grc/anti-bribery"

	@expose("/")
	@has_access
	def index(self):
		training_completion_pct: float | None = None
		vendor_screening_pct: float | None = None
		open_investigations: int | None = None
		pending_gifts = 0
		government_gifts = 0
		pending_coi = 0
		recent_gifts: list[GiftEntertainmentLog] = []
		recent_coi: list[ConflictOfInterestDeclaration] = []

		try:
			sess = self._session()
			pending_gifts = self._count(GiftEntertainmentLog, session=sess, status="PENDING")
			government_gifts = self._count(GiftEntertainmentLog, session=sess, is_government_official=True)
			pending_coi = self._count(ConflictOfInterestDeclaration, session=sess, status="PENDING")
			recent_gifts = sess.execute(
				sa.select(GiftEntertainmentLog)
				.order_by(sa.desc(GiftEntertainmentLog.gift_date))
				.limit(10)
			).scalars().all()
			recent_coi = sess.execute(
				sa.select(ConflictOfInterestDeclaration)
				.order_by(sa.desc(ConflictOfInterestDeclaration.declaration_date))
				.limit(10)
			).scalars().all()
		except Exception:
			log.exception("GiftsRegisterDashboardView.index: failed to load gifts register data")

		# TODO: Query TrainingCompletion once an ABAC training completion model exists in this plugin.
		# TODO: Query ThirdPartyAssessment once vendor assessment/screening fields exist in this plugin.
		# TODO: Query IncidentReport once anti-bribery investigation records exist in this plugin.
		scorecard_html = self._scorecard(training_completion_pct, vendor_screening_pct, open_investigations)
		kpi_html = self.kpi_cards([
			{"label": "Pending Gifts", "value": pending_gifts, "format": "integer", "icon": "fa-gift", "color": "#ff5a1f" if pending_gifts else "#0e9f6e"},
			{"label": "Govt Official Gifts", "value": government_gifts, "format": "integer", "icon": "fa-exclamation-triangle", "color": "#dc2626" if government_gifts else "#0e9f6e"},
			{"label": "Pending COI", "value": pending_coi, "format": "integer", "icon": "fa-balance-scale", "color": "#ff5a1f" if pending_coi else "#0e9f6e"},
		])
		body = (
			"<h3>Anti-Bribery Compliance Scorecard</h3>"
			"<p class=\"text-muted\">ABAC training, high-risk vendor screening, and investigation KPIs.</p>"
			f"{scorecard_html}"
			f"{kpi_html}"
			f"{self._gifts_table(recent_gifts)}"
			f"{self._coi_table(recent_coi)}"
		)
		return make_response(_page_html("Anti-Bribery Compliance Scorecard", body), 200)

	def _scorecard(self, training_completion_pct: float | None, vendor_screening_pct: float | None, open_investigations: int | None) -> str:
		values = [
			("ABAC Training Complete", "N/A" if training_completion_pct is None else f"{training_completion_pct:.1f}%", _pct_color(training_completion_pct), "TrainingCompletion model not found"),
			("High-Risk Vendors Screened", "N/A" if vendor_screening_pct is None else f"{vendor_screening_pct:.1f}%", _pct_color(vendor_screening_pct), "ThirdPartyAssessment model not found"),
			("Open Investigations", "N/A" if open_investigations is None else str(open_investigations), _count_color(open_investigations), "IncidentReport model not found"),
		]
		return (
			"<div class=\"score-grid\">"
			+ "".join(
				"<div class=\"score-card\">"
				f"<h4>{_he(label)}</h4>"
				f"<div class=\"value\" style=\"color:{color}\">{_he(value)}</div>"
				f"<p>{_he(note)}</p>"
				"</div>"
				for label, value, color, note in values
			)
			+ "</div>"
		)

	def _gifts_table(self, gifts: list[GiftEntertainmentLog]) -> str:
		rows = [
			"<h4>Recent Gifts and Entertainment</h4>",
			"<table class=\"grc-table\">",
			"<thead><tr><th>Recipient</th><th>Organization</th><th>Type</th><th>Value</th><th>Date</th><th>Status</th><th>Govt Official</th></tr></thead>",
			"<tbody>",
		]
		if not gifts:
			rows.append("<tr><td colspan=\"7\" class=\"text-muted\">No gifts or entertainment entries found.</td></tr>")
		for gift in gifts:
			rows.append(
				"<tr>"
				f"<td>{_he(getattr(gift, 'given_to_name', ''))}</td>"
				f"<td>{_he(getattr(gift, 'given_to_organization', ''))}</td>"
				f"<td>{_he(getattr(gift, 'gift_type', ''))}</td>"
				f"<td>{_he(getattr(gift, 'currency_code', '') or '')} {_he((getattr(gift, 'value_cents', 0) or 0) / 100)}</td>"
				f"<td>{_he(getattr(gift, 'gift_date', ''))}</td>"
				f"<td>{_he(getattr(gift, 'status', ''))}</td>"
				f"<td>{'Yes' if getattr(gift, 'is_government_official', False) else 'No'}</td>"
				"</tr>"
			)
		rows.append("</tbody></table>")
		return "".join(rows)

	def _coi_table(self, declarations: list[ConflictOfInterestDeclaration]) -> str:
		rows = [
			"<h4>Conflict of Interest Declarations</h4>",
			"<table class=\"grc-table\">",
			"<thead><tr><th>Employee</th><th>Description</th><th>Declared</th><th>Status</th><th>Reviewed</th></tr></thead>",
			"<tbody>",
		]
		if not declarations:
			rows.append("<tr><td colspan=\"5\" class=\"text-muted\">No COI declarations found.</td></tr>")
		for declaration in declarations:
			rows.append(
				"<tr>"
				f"<td>{_he(getattr(declaration, 'employee_id', ''))}</td>"
				f"<td>{_he(getattr(declaration, 'description', ''))}</td>"
				f"<td>{_he(getattr(declaration, 'declaration_date', ''))}</td>"
				f"<td>{_he(getattr(declaration, 'status', ''))}</td>"
				f"<td>{_he(getattr(declaration, 'reviewed_at', '') or '')}</td>"
				"</tr>"
			)
		rows.append("</tbody></table>")
		return "".join(rows)


AntiBriberyDashboardView = GiftsRegisterDashboardView

__all__ = [
	"GiftEntertainmentLogView",
	"ConflictOfInterestDeclarationView",
	"GiftsRegisterDashboardView",
	"AntiBriberyDashboardView",
]
