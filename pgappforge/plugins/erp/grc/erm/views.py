"""
pgappforge/plugins/erp/grc/erm/views.py

Flask views for the GRC Enterprise Risk Management (ERM) plugin.
"""
from __future__ import annotations

import logging

import sqlalchemy as sa
from flask import current_app, make_response
from pgappforge import ModelView, expose
from pgappforge.models.sqla.interface import SQLAInterface
from pgappforge.security.decorators import has_access

from pgappforge.plugins.erp.base_view import BaseERPView
from pgappforge.plugins.erp.grc.erm.models import KRI, RiskMitigationAction, RiskRegister

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


def _tenant_id() -> str:
	return str(current_app.config.get("DEFAULT_TENANT_ID", ""))


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
		".grc-kpi{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin:0 0 18px}"
		".grc-card{border:1px solid #e5e7eb;border-radius:6px;background:#fff;padding:14px 16px}"
		".grc-card h4{margin:0 0 8px;font-size:12px;color:#6b7280;text-transform:uppercase;font-weight:700}"
		".grc-card .value{font-size:30px;font-weight:800;line-height:1}"
		".grc-table{width:100%;border-collapse:collapse;background:#fff;margin-bottom:18px}"
		".grc-table th,.grc-table td{border:1px solid #e5e7eb;padding:8px 10px;text-align:left}"
		".grc-table th{background:#f9fafb;font-size:12px;text-transform:uppercase;color:#374151}"
		".heatmap td,.heatmap th{text-align:center;vertical-align:middle}"
		".risk-cell{font-weight:800;color:#fff;min-width:58px;height:46px}"
		".risk-success{background:#0e9f6e}"
		".risk-warning{background:#ff5a1f}"
		".risk-danger{background:#dc2626}"
		".badge-risk{display:inline-block;border-radius:4px;padding:2px 8px;font-size:12px;font-weight:700;color:#fff}"
		"</style></head><body>"
		f"{body}</body></html>"
	)


def _risk_class(likelihood: int, impact: int) -> str:
	score = likelihood * impact
	if score >= 15:
		return "risk-danger"
	if score >= 8:
		return "risk-warning"
	return "risk-success"


def _risk_color(score: int) -> str:
	if score >= 15:
		return "#dc2626"
	if score >= 8:
		return "#ff5a1f"
	return "#0e9f6e"


class RiskRegisterView(ModelView):
	datamodel = SQLAInterface(RiskRegister)
	list_columns = ["name", "category", "likelihood_score", "impact_score", "risk_score", "owner_id", "status", "treatment"]
	label_columns = {
		"name": "Risk",
		"category": "Category",
		"likelihood_score": "Likelihood",
		"impact_score": "Impact",
		"risk_score": "Risk Score",
		"owner_id": "Owner",
		"status": "Status",
		"treatment": "Treatment",
	}
	add_exclude_columns = ["id", "created_at", "updated_at"]
	edit_exclude_columns = ["id", "created_at", "updated_at"]


class RiskMitigationActionView(ModelView):
	datamodel = SQLAInterface(RiskMitigationAction)
	list_columns = ["risk_id", "action", "owner_id", "due_date", "status"]
	label_columns = {
		"risk_id": "Risk",
		"action": "Action",
		"owner_id": "Owner",
		"due_date": "Due Date",
		"status": "Status",
	}
	add_exclude_columns = ["id"]
	edit_exclude_columns = ["id"]


class KRIView(ModelView):
	datamodel = SQLAInterface(KRI)
	list_columns = ["risk_id", "metric_name", "threshold_value", "current_value", "breach_status", "last_checked_at"]
	label_columns = {
		"risk_id": "Risk",
		"metric_name": "Metric",
		"threshold_value": "Threshold",
		"current_value": "Current Value",
		"breach_status": "Breach",
		"last_checked_at": "Last Checked",
	}
	add_exclude_columns = ["id"]
	edit_exclude_columns = ["id"]


class ErmDashboardView(BaseERPView):
	"""ERM risk register dashboard with 5x5 heat map."""

	route_base = "/grc/erm"
	default_view = "dashboard"

	@expose("/")
	@has_access
	def dashboard(self):
		session = _get_session()
		tenant_id = _tenant_id()
		grid: dict[int, dict[int, int]] = {
			likelihood: {impact: 0 for impact in range(1, 6)}
			for likelihood in range(1, 6)
		}
		top_risks: list[RiskRegister] = []
		total_risks = 0
		critical_count = 0
		high_count = 0
		kri_breach_count = 0

		try:
			group_q = (
				sa.select(
					RiskRegister.likelihood_score,
					RiskRegister.impact_score,
					sa.func.count(RiskRegister.id).label("risk_count"),
				)
				.where(
					RiskRegister.likelihood_score.between(1, 5),
					RiskRegister.impact_score.between(1, 5),
				)
				.group_by(RiskRegister.likelihood_score, RiskRegister.impact_score)
			)
			if tenant_id:
				group_q = group_q.where(RiskRegister.tenant_id == tenant_id)
			for row in session.execute(group_q).all():
				likelihood = int(row.likelihood_score or 0)
				impact = int(row.impact_score or 0)
				if likelihood in grid and impact in grid[likelihood]:
					grid[likelihood][impact] = int(row.risk_count or 0)

			top_q = sa.select(RiskRegister).order_by(sa.desc(RiskRegister.risk_score)).limit(5)
			count_q = sa.select(sa.func.count()).select_from(RiskRegister)
			critical_q = (
				sa.select(sa.func.count())
				.select_from(RiskRegister)
				.where(RiskRegister.risk_score >= 15)
			)
			high_q = (
				sa.select(sa.func.count())
				.select_from(RiskRegister)
				.where(RiskRegister.risk_score >= 8, RiskRegister.risk_score < 15)
			)
			if tenant_id:
				top_q = top_q.where(RiskRegister.tenant_id == tenant_id)
				count_q = count_q.where(RiskRegister.tenant_id == tenant_id)
				critical_q = critical_q.where(RiskRegister.tenant_id == tenant_id)
				high_q = high_q.where(RiskRegister.tenant_id == tenant_id)
			top_risks = session.execute(top_q).scalars().all()
			total_risks = session.execute(count_q).scalar() or 0
			critical_count = session.execute(critical_q).scalar() or 0
			high_count = session.execute(high_q).scalar() or 0
		except Exception:
			log.exception("ErmDashboardView.dashboard: failed to load risk heat map")

		try:
			kri_q = sa.select(sa.func.count()).select_from(KRI).where(KRI.breach_status.is_(True))
			if tenant_id:
				kri_q = (
					kri_q
					.join(RiskRegister, KRI.risk_id == RiskRegister.id)
					.where(RiskRegister.tenant_id == tenant_id)
				)
			kri_breach_count = session.execute(kri_q).scalar() or 0
		except Exception:
			log.exception("ErmDashboardView.dashboard: failed to load KRI breach count")

		kpi_html = self.kpi_cards([
			{"value": total_risks, "label": "Total Risks", "format": "integer", "icon": "fa-shield", "color": "#1a56db"},
			{"value": critical_count, "label": "Danger Zone", "format": "integer", "icon": "fa-exclamation-circle", "color": "#dc2626"},
			{"value": high_count, "label": "Warning Zone", "format": "integer", "icon": "fa-fire", "color": "#ff5a1f"},
			{"value": kri_breach_count, "label": "KRI Breaches", "format": "integer", "icon": "fa-tachometer", "color": "#dc2626" if kri_breach_count else "#0e9f6e"},
		])

		heatmap_html = self._heatmap_table(grid)
		top_risks_html = self._top_risks_table(top_risks)
		body = (
			"<h3>Enterprise Risk Management</h3>"
			"<p class=\"text-muted\">Risk heat map grouped by likelihood and impact.</p>"
			f"{kpi_html}"
			f"{heatmap_html}"
			f"{top_risks_html}"
		)
		return make_response(_page_html("ERM Risk Heat Map", body), 200)

	def _heatmap_table(self, grid: dict[int, dict[int, int]]) -> str:
		rows = [
			"<table class=\"grc-table heatmap\">",
			"<thead><tr><th>Likelihood \\ Impact</th><th>1</th><th>2</th><th>3</th><th>4</th><th>5</th></tr></thead>",
			"<tbody>",
		]
		for likelihood in range(5, 0, -1):
			rows.append(f"<tr><th>{likelihood}</th>")
			for impact in range(1, 6):
				count = grid[likelihood][impact]
				score = likelihood * impact
				rows.append(
					f"<td class=\"risk-cell {_risk_class(likelihood, impact)}\" "
					f"title=\"Likelihood {likelihood}, impact {impact}, score {score}\">"
					f"{count}</td>"
				)
			rows.append("</tr>")
		rows.append("</tbody></table>")
		rows.append(
			"<p class=\"text-muted\">Color bands: green success below 8, orange warning from 8 to 14, red danger at 15 and above.</p>"
		)
		return "".join(rows)

	def _top_risks_table(self, risks: list[RiskRegister]) -> str:
		rows = [
			"<h4>Top 5 High-Risk Items</h4>",
			"<table class=\"grc-table\">",
			"<thead><tr><th>Risk</th><th>Category</th><th>Likelihood</th><th>Impact</th><th>Score</th><th>Status</th></tr></thead>",
			"<tbody>",
		]
		if not risks:
			rows.append("<tr><td colspan=\"6\" class=\"text-muted\">No risks registered.</td></tr>")
		for risk in risks:
			score = int(getattr(risk, "risk_score", 0) or 0)
			rows.append(
				"<tr>"
				f"<td>{_he(getattr(risk, 'name', ''))}</td>"
				f"<td>{_he(getattr(risk, 'category', ''))}</td>"
				f"<td>{_he(getattr(risk, 'likelihood_score', ''))}</td>"
				f"<td>{_he(getattr(risk, 'impact_score', ''))}</td>"
				f"<td><span class=\"badge-risk\" style=\"background:{_risk_color(score)}\">{score}</span></td>"
				f"<td>{_he(getattr(risk, 'status', ''))}</td>"
				"</tr>"
			)
		rows.append("</tbody></table>")
		return "".join(rows)


ERMDashboardView = ErmDashboardView
ERMHeatMapView = ErmDashboardView

__all__ = [
	"RiskRegisterView",
	"RiskMitigationActionView",
	"KRIView",
	"ErmDashboardView",
	"ERMDashboardView",
	"ERMHeatMapView",
]
