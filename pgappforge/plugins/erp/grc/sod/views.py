"""
pgappforge/plugins/erp/grc/sod/views.py

Flask views for the GRC Segregation of Duties (SoD) plugin.

Registered views:
  SodAnalyzerView  — dashboard + bulk_scan endpoint
"""
from __future__ import annotations

import logging

import sqlalchemy as sa
from flask import current_app, jsonify

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
# SodAnalyzerView
# ---------------------------------------------------------------------------

class SodAnalyzerView(BaseERPView):
	"""SoD conflict analyzer — dashboard and bulk scan.

	GET  /grc/sod/            — conflict dashboard (HTML)
	POST /grc/sod/bulk_scan   — trigger full-population scan, returns JSON
	"""

	route_base = "/grc/sod"
	default_view = "dashboard"

	@expose("/")
	@has_access
	def dashboard(self):
		from flask import render_template
		conflicts = []
		try:
			from pgappforge.plugins.erp.grc.sod.models import SodViolation
			session = _get_session()
			q = (
				sa.select(SodViolation)
				.where(SodViolation.tenant_id == _tenant_id())
				.order_by(sa.desc(SodViolation.detected_at))
				.limit(500)
			)
			conflicts = session.execute(q).scalars().all()
		except Exception:
			log.exception("SodAnalyzerView.dashboard: failed to load violations")
			conflicts = []

		# ── Compute violation summary stats ─────────────────────────────
		total_violations = len(conflicts)
		critical_count = sum(1 for c in conflicts if getattr(c, "risk_level", "").lower() == "critical")
		high_count = sum(1 for c in conflicts if getattr(c, "risk_level", "").lower() == "high")
		resolved = sum(1 for c in conflicts if getattr(c, "status", "").lower() in ("remediated", "accepted", "risk_accepted"))

		kpi_html = self.kpi_cards([
			{
				"value": total_violations,
				"label": "Total Violations",
				"format": "integer",
				"icon": "fa-exclamation-triangle",
				"color": "#e02424",
			},
			{
				"value": critical_count,
				"label": "Critical",
				"format": "integer",
				"icon": "fa-ban",
				"color": "#7f1d1d",
			},
			{
				"value": high_count,
				"label": "High Risk",
				"format": "integer",
				"icon": "fa-fire",
				"color": "#ff5a1f",
			},
			{
				"value": resolved,
				"label": "Resolved",
				"format": "integer",
				"icon": "fa-check-circle",
				"color": "#0e9f6e",
			},
		])

		# ── Risk distribution doughnut ───────────────────────────────────
		medium_count = sum(1 for c in conflicts if getattr(c, "risk_level", "").lower() == "medium")
		low_count = max(0, total_violations - critical_count - high_count - medium_count)
		risk_data = [
			{"risk_level": "Critical", "count": critical_count},
			{"risk_level": "High",     "count": high_count},
			{"risk_level": "Medium",   "count": medium_count},
			{"risk_level": "Low",      "count": low_count},
		]
		chart_html = self.chart(
			risk_data,
			chart_type="doughnut",
			x_col="risk_level",
			y_col="count",
			title="Risk Distribution",
			height=200,
		)

		return render_template(
			"grc/sod_dashboard.html",
			conflicts=conflicts,
			kpi_html=kpi_html,
			chart_html=chart_html,
		)

	@expose("/bulk_scan", methods=["POST"])
	@has_access
	def bulk_scan(self):
		try:
			from pgappforge.plugins.erp.grc.sod.services import SodAnalyzerService
			session = _get_session()
			result = SodAnalyzerService().bulk_scan(session, tenant_id=_tenant_id())
			session.commit()
			return jsonify({"ok": True, "result": result})
		except Exception as exc:
			log.exception("SodAnalyzerView.bulk_scan: scan failed")
			return jsonify({"ok": False, "error": str(exc)}), 500


SodAnalyzerDashboardView = SodAnalyzerView

__all__ = ["SodAnalyzerView", "SodAnalyzerDashboardView"]
