from __future__ import annotations

from flask import render_template
from pgappforge import ModelView, expose, has_access
from pgappforge.models.sqla.interface import SQLAInterface

from pgappforge.plugins.erp.base_view import BaseERPView
from pgappforge.plugins.erp.hcm.analytics.models import (
	HrAnalyticsReport,
	HrAnalyticsSnapshot,
	HrFlightRiskScore,
)

__all__ = [
	"HrAnalyticsSnapshotView",
	"HrFlightRiskScoreView",
	"HrAnalyticsReportView",
	"HrAnalyticsDashboardView",
]


class HrAnalyticsSnapshotView(ModelView):
	datamodel = SQLAInterface(HrAnalyticsSnapshot)
	list_columns = ["snapshot_type", "period", "entity_id", "computed_at"]
	add_exclude_columns = ["id", "created_on", "changed_on", "created_at", "updated_at"]
	edit_exclude_columns = ["id", "created_on", "changed_on", "created_at", "updated_at"]
	search_columns = ["snapshot_type", "period"]


class HrFlightRiskScoreView(ModelView):
	datamodel = SQLAInterface(HrFlightRiskScore)
	list_columns = ["employee_id", "score", "risk_level", "is_current", "computed_at"]
	add_exclude_columns = ["id", "created_on", "changed_on", "created_at", "updated_at"]
	edit_exclude_columns = ["id", "created_on", "changed_on", "created_at", "updated_at"]
	search_columns = ["employee_id", "risk_level"]


class HrAnalyticsReportView(ModelView):
	datamodel = SQLAInterface(HrAnalyticsReport)
	list_columns = ["report_type", "title", "period", "generated_by", "generated_at"]
	add_exclude_columns = ["id", "created_on", "changed_on", "created_at", "updated_at"]
	edit_exclude_columns = ["id", "created_on", "changed_on", "created_at", "updated_at"]
	search_columns = ["report_type", "title", "period"]


class HrAnalyticsDashboardView(BaseERPView):
	route_base = "/hcm/analytics"

	@expose("/")
	@has_access
	def index(self):
		try:
			from pgappforge.plugins.erp.hcm.analytics.models import (
				HrAnalyticsReport,
				HrAnalyticsSnapshot,
				HrFlightRiskScore,
			)
			sess = self._session()
			total_snapshots = self._count(HrAnalyticsSnapshot, session=sess)
			high_risk_employees = self._count(HrFlightRiskScore, session=sess, risk_level="HIGH", is_current=True)
			critical_risk_employees = self._count(HrFlightRiskScore, session=sess, risk_level="CRITICAL", is_current=True)
			total_reports = self._count(HrAnalyticsReport, session=sess)
		except Exception:
			total_snapshots = high_risk_employees = critical_risk_employees = total_reports = 0
		kpi_html = self.kpi_cards([
			{"label": "Snapshots", "value": total_snapshots, "icon": "fa-database", "color": "#1a56db"},
			{"label": "High Flight Risk", "value": high_risk_employees, "icon": "fa-exclamation-triangle", "color": "#e02424"},
			{"label": "Critical Flight Risk", "value": critical_risk_employees, "icon": "fa-fire", "color": "#7e3af2"},
			{"label": "Reports Generated", "value": total_reports, "icon": "fa-file-chart-line", "color": "#0e9f6e"},
		])
		return render_template(
			"appbuilder/hcm_analytics/analytics_dashboard.html",
			kpi_html=kpi_html,
			appbuilder=self.appbuilder,
		)
