from __future__ import annotations

from pgappforge import ModelView
from pgappforge.models.sqla.interface import SQLAInterface

from pgappforge.plugins.erp.hcm.analytics.models import (
	HrAnalyticsReport,
	HrAnalyticsSnapshot,
	HrFlightRiskScore,
)

__all__ = [
	"HrAnalyticsSnapshotView",
	"HrFlightRiskScoreView",
	"HrAnalyticsReportView",
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
