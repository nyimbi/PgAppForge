from __future__ import annotations
from flask_babel import lazy_gettext as _

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
	label_columns = {"name": _("Name"), "cycle_type": _("Cycle Type"), "start_date": _("Start Date"), "end_date": _("End Date"), "status": _("Status")}
	show_columns = ["name", "cycle_type", "start_date", "end_date", "status", "review_form", "created_at", "updated_at"]
	add_exclude_columns = ["id", "created_on", "changed_on", "created_at", "updated_at", "reviews", "goals"]
	edit_exclude_columns = ["id", "created_on", "changed_on", "created_at", "updated_at", "reviews", "goals"]
	search_columns = ["name", "cycle_type", "status"]


class PerformanceReviewView(ModelView):
	datamodel = SQLAInterface(PerformanceReview)
	list_columns = ["employee_id", "reviewer_id", "review_type", "overall_rating", "status", "submitted_at"]
	label_columns = {"employee_id": _("Employee"), "reviewer_id": _("Reviewer"), "review_type": _("Review Type"), "overall_rating": _("Overall Rating"), "status": _("Status"), "submitted_at": _("Submitted At")}
	show_columns = ["employee_id", "reviewer_id", "review_type", "overall_rating", "status", "submitted_at", "competency_scores", "strengths", "development_areas", "development_notes", "created_at", "updated_at", "cycle"]
	add_exclude_columns = ["id", "created_on", "changed_on", "created_at", "updated_at"]
	edit_exclude_columns = ["id", "created_on", "changed_on", "created_at", "updated_at"]
	search_columns = ["employee_id", "reviewer_id", "review_type", "status"]


class GoalView(ModelView):
	datamodel = SQLAInterface(Goal)
	list_columns = ["employee_id", "title", "goal_type", "period", "progress_pct", "status"]
	label_columns = {"employee_id": _("Employee"), "title": _("Title"), "goal_type": _("Goal Type"), "period": _("Period"), "progress_pct": _("Progress (%)"), "status": _("Status")}
	show_columns = ["employee_id", "title", "goal_type", "period", "progress_pct", "status", "description", "key_results", "weight_pct", "created_at", "updated_at", "cycle"]
	add_exclude_columns = ["id", "created_on", "changed_on", "created_at", "updated_at"]
	edit_exclude_columns = ["id", "created_on", "changed_on", "created_at", "updated_at"]
	search_columns = ["employee_id", "title", "period", "status"]


class PerformanceDashboardView(BaseERPView):
	route_base = "/hcm/performance"

	@expose("/")
	@has_access
	def index(self):
		try:
			from pgappforge.plugins.erp.hcm.performance.models import (
				Goal,
				PerformanceCycle,
				PerformanceReview,
			)
			sess = self._session()
			active_cycles = self._count(PerformanceCycle, session=sess, status="ACTIVE")
			reviews_pending = self._count(PerformanceReview, session=sess, status="SUBMITTED")
			goals_active = self._count(Goal, session=sess, status="ACTIVE")
		except Exception:
			active_cycles = reviews_pending = goals_active = 0
		kpi_html = self.kpi_cards([
			{"label": "Active Cycles", "value": active_cycles, "icon": "fa-sync-alt", "color": "#1a56db"},
			{"label": "Reviews Submitted", "value": reviews_pending, "icon": "fa-clipboard-list", "color": "#f59e0b"},
			{"label": "Active Goals", "value": goals_active, "icon": "fa-bullseye", "color": "#0e9f6e"},
		])
		return render_template(
			"appbuilder/hcm/performance_okr.html",
			kpi_html=kpi_html,
			appbuilder=self.appbuilder,
		)
