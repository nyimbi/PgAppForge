"""
pgappforge/plugins/erp/grc/erm/views.py

Flask views for the GRC Enterprise Risk Management (ERM) plugin.

Registered views:
  ErmDashboardView  — risk register dashboard with KRI summary
"""
from __future__ import annotations

import logging

import sqlalchemy as sa
from flask import current_app

from pgappforge.plugins.erp.base_view import BaseERPView
from pgappforge import expose
from pgappforge.security.decorators import has_access

log = logging.getLogger(__name__)


def _get_session():
	try:
		ab = current_app.extensions.get("appbuilder")
		if ab and hasattr(ab, "get_session"):
			return ab.get_session
		db = current_app.extensions.get("sqlalchemy")
		if db:
			return db.session
	except RuntimeError:
		pass
	raise RuntimeError("Cannot obtain database session")


def _tenant_id() -> str:
	return str(current_app.config.get("DEFAULT_TENANT_ID", ""))


# ---------------------------------------------------------------------------
# ErmDashboardView
# ---------------------------------------------------------------------------

class ErmDashboardView(BaseERPView):
	"""ERM risk register dashboard.

	GET /grc/erm/  — renders risk register with associated KRIs
	"""

	route_base = "/grc/erm"
	default_view = "dashboard"

	@expose("/")
	@has_access
	def dashboard(self):
		from flask import render_template

		risks = []
		kris = []
		heatmap_data = {}

		try:
			from pgappforge.plugins.erp.grc.erm.models import RiskRegister
			session = _get_session()
			q = (
				sa.select(RiskRegister)
				.where(RiskRegister.tenant_id == _tenant_id())
				.order_by(sa.desc(RiskRegister.risk_score))
				.limit(200)
			)
			risks = session.execute(q).scalars().all()
		except Exception:
			log.exception("ErmDashboardView.dashboard: failed to load risks")
			risks = []

		try:
			from pgappforge.plugins.erp.grc.erm.models import KRI, RiskRegister
			session = _get_session()
			q = (
				sa.select(KRI)
				.join(RiskRegister, KRI.risk_id == RiskRegister.id)
				.where(RiskRegister.tenant_id == _tenant_id())
				.order_by(KRI.metric_name)
				.limit(200)
			)
			kris = session.execute(q).scalars().all()
		except Exception:
			log.exception("ErmDashboardView.dashboard: failed to load KRIs")
			kris = []

		try:
			from pgappforge.plugins.erp.grc.erm.services import ERMService
			session = _get_session()
			heatmap_data = ERMService().get_heat_map(_tenant_id(), session)
		except Exception:
			log.exception("ErmDashboardView.dashboard: failed to build heat map")
			heatmap_data = {}

		# ── KPI summary ──────────────────────────────────────────────────
		total_risks = len(risks)
		critical_count = sum(
			1 for r in risks if (getattr(r, "risk_score", 0) or 0) >= 20
		)
		high_count = sum(
			1 for r in risks
			if 10 <= (getattr(r, "risk_score", 0) or 0) < 20
		)
		kri_breach_count = sum(
			1 for k in kris
			if (getattr(k, "threshold_value", None) is not None
				and (getattr(k, "current_value", 0) or 0) > k.threshold_value)
		)

		kpi_html = self.kpi_cards([
			{
				"value": critical_count,
				"label": "Critical Risks",
				"format": "integer",
				"icon": "fa-exclamation-circle",
				"color": "#dc2626",
			},
			{
				"value": high_count,
				"label": "High Risks",
				"format": "integer",
				"icon": "fa-fire",
				"color": "#ea580c",
			},
			{
				"value": total_risks,
				"label": "Total Risks",
				"format": "integer",
				"icon": "fa-shield",
				"color": "#1c64f2",
			},
			{
				"value": kri_breach_count,
				"label": "KRI Breaches",
				"format": "integer",
				"icon": "fa-tachometer",
				"color": "#dc2626" if kri_breach_count else "#0e9f6e",
			},
		])

		# ── Risk by category bar chart ────────────────────────────────────
		category_counts: dict[str, int] = {}
		for r in risks:
			cat = getattr(r, "category", "Unknown") or "Unknown"
			category_counts[cat] = category_counts.get(cat, 0) + 1

		chart_data = [
			{"category": cat, "count": count}
			for cat, count in sorted(category_counts.items(), key=lambda x: -x[1])
		]
		chart_html = self.chart(
			chart_data,
			chart_type="bar",
			x_col="category",
			y_col="count",
			title="Risks by Category",
			height=240,
		)

		return render_template(
			"grc/erm_dashboard.html",
			risks=risks,
			kris=kris,
			kri_breach_count=kri_breach_count,
			heatmap_data=heatmap_data,
			kpi_html=kpi_html,
			chart_html=chart_html,
		)


ERMDashboardView = ErmDashboardView

__all__ = ["ErmDashboardView", "ERMDashboardView"]
