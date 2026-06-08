from __future__ import annotations

from flask import render_template
from pgappforge import ModelView, expose, has_access
from pgappforge.models.sqla.interface import SQLAInterface

from pgappforge.plugins.erp.base_view import BaseERPView
from pgappforge.plugins.erp.hcm.performance.models import (
	Goal,
	PerformanceCycle,
	PerformanceReview,
)

__all__ = [
	"PerformanceCycleView",
	"PerformanceReviewView",
	"GoalView",
	"PerformanceDashboardView",
]


class PerformanceCycleView(ModelView):
	datamodel = SQLAInterface(PerformanceCycle)
	list_columns = ["name", "cycle_type", "start_date", "end_date", "status"]
	add_exclude_columns = ["id", "created_on", "changed_on", "created_at", "updated_at", "reviews", "goals"]
	edit_exclude_columns = ["id", "created_on", "changed_on", "created_at", "updated_at", "reviews", "goals"]
	search_columns = ["name", "cycle_type", "status"]


class PerformanceReviewView(ModelView):
	datamodel = SQLAInterface(PerformanceReview)
	list_columns = ["employee_id", "reviewer_id", "review_type", "overall_rating", "status", "submitted_at"]
	add_exclude_columns = ["id", "created_on", "changed_on", "created_at", "updated_at"]
	edit_exclude_columns = ["id", "created_on", "changed_on", "created_at", "updated_at"]
	search_columns = ["employee_id", "reviewer_id", "review_type", "status"]


class GoalView(ModelView):
	datamodel = SQLAInterface(Goal)
	list_columns = ["employee_id", "title", "goal_type", "period", "progress_pct", "status"]
	add_exclude_columns = ["id", "created_on", "changed_on", "created_at", "updated_at"]
	edit_exclude_columns = ["id", "created_on", "changed_on", "created_at", "updated_at"]
	search_columns = ["employee_id", "title", "period", "status"]


class PerformanceDashboardView(BaseERPView):
	route_base = "/hcm/performance"

	@expose("/")
	@has_access
	def index(self):
		kpi_html = self.kpi_cards([
			{"label": "Active Cycles", "value": 0, "icon": "fa-sync-alt", "color": "#1a56db"},
			{"label": "Reviews Pending", "value": 0, "icon": "fa-clipboard-list", "color": "#f59e0b"},
			{"label": "Goals on Track", "value": 0, "icon": "fa-bullseye", "color": "#0e9f6e"},
		])
		return render_template(
			"appbuilder/hcm/performance_okr.html",
			kpi_html=kpi_html,
			appbuilder=self.appbuilder,
		)
