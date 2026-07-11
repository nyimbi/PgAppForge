"""
pgappforge/plugins/erp/platform/data_quality/views.py

Dashboard view for cross-domain ERP data-quality monitoring.
"""
from __future__ import annotations

import logging

from flask import jsonify, render_template
from pgappforge.baseviews import expose
from pgappforge.security.decorators import has_access

from pgappforge.plugins.erp.base_view import BaseERPView
from pgappforge.plugins.erp.platform.data_quality.services import DataQualityService

log = logging.getLogger(__name__)


class DataQualityDashboardView(BaseERPView):
	"""Cross-domain data-quality dashboard."""

	route_base = "/platform/data-quality"

	@expose("/")
	@has_access
	def index(self):
		summary = self._load_summary()
		kpi_html = self.kpi_cards([
			{
				"label": "Overall Quality",
				"value": summary["overall_score"],
				"format": "percent",
				"icon": "fa-check-circle",
				"color": "#0e9f6e",
			},
			{
				"label": "Completeness",
				"value": summary["completeness_score"],
				"format": "percent",
				"icon": "fa-tasks",
				"color": "#1a56db",
			},
			{
				"label": "Duplicate Groups",
				"value": summary["duplicate_groups"],
				"icon": "fa-copy",
				"color": "#e3a008",
			},
			{
				"label": "Stale Records",
				"value": summary["stale_records"],
				"icon": "fa-clock-o",
				"color": "#e02424",
			},
		])
		domain_chart_html = self.chart(
			rows=[
				{"label": row["domain"], "value": row["score"]}
				for row in summary["domain_scores"]
			],
			chart_type="bar",
			x_col="label",
			y_col="value",
			title="Completeness by Domain",
		) if summary["domain_scores"] else ""
		return render_template(
			"platform/data_quality_dashboard.html",
			kpi_html=kpi_html,
			domain_chart_html=domain_chart_html,
			summary=summary,
			appbuilder=self.appbuilder,
		)

	@expose("/api/summary")
	@has_access
	def api_summary(self):
		return jsonify(self._load_summary())

	def _load_summary(self) -> dict:
		try:
			return DataQualityService().get_quality_summary(
				self._session(),
				self._tenant_id(),
			)
		except Exception as exc:
			log.debug("DataQualityDashboardView failed to load summary", exc_info=True)
			return {
				"generated_at": "",
				"tenant_id": self._tenant_id(),
				"model_count": 0,
				"total_records": 0,
				"overall_score": 0.0,
				"completeness_score": 0.0,
				"duplicate_score": 0.0,
				"stale_score": 0.0,
				"domain_scores": [],
				"completeness": [],
				"duplicates": [],
				"duplicate_groups": 0,
				"duplicate_records": 0,
				"stale": [],
				"stale_records": 0,
				"errors": [str(exc)],
			}


__all__ = ["DataQualityDashboardView"]
