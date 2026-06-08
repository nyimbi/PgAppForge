from __future__ import annotations

from flask import render_template
from pgappforge import ModelView, expose, has_access
from pgappforge.models.sqla.interface import SQLAInterface

from pgappforge.plugins.erp.base_view import BaseERPView
from pgappforge.plugins.erp.hcm.equity_compensation.models import (
	EquityGrant,
	EquityPlan,
	VestingEvent,
)

__all__ = [
	"EquityPlanView",
	"EquityGrantView",
	"VestingEventView",
	"EquityDashboardView",
]


class EquityPlanView(ModelView):
	datamodel = SQLAInterface(EquityPlan)
	list_columns = ["name", "plan_type", "total_shares_authorized", "total_shares_issued", "plan_currency", "is_active"]
	add_exclude_columns = ["id", "created_on", "changed_on", "created_at", "updated_at", "grants"]
	edit_exclude_columns = ["id", "created_on", "changed_on", "created_at", "updated_at", "grants"]
	search_columns = ["name", "plan_type"]


class EquityGrantView(ModelView):
	datamodel = SQLAInterface(EquityGrant)
	list_columns = ["employee_id", "plan", "grant_date", "shares_granted", "vested_shares", "status"]
	add_exclude_columns = ["id", "created_on", "changed_on", "created_at", "updated_at", "vesting_events", "exercises"]
	edit_exclude_columns = ["id", "created_on", "changed_on", "created_at", "updated_at", "vesting_events", "exercises"]
	search_columns = ["employee_id", "status"]


class VestingEventView(ModelView):
	datamodel = SQLAInterface(VestingEvent)
	list_columns = ["grant", "vest_date", "shares_vested", "is_cliff", "is_processed"]
	add_exclude_columns = ["id", "created_on", "changed_on", "created_at", "updated_at"]
	edit_exclude_columns = ["id", "created_on", "changed_on", "created_at", "updated_at"]
	search_columns = ["is_processed"]


class EquityDashboardView(BaseERPView):
	route_base = "/hcm/equity"

	@expose("/")
	@has_access
	def index(self):
		kpi_html = self.kpi_cards([
			{"label": "Active Plans", "value": 0, "icon": "fa-chart-pie", "color": "#1a56db"},
			{"label": "Outstanding Grants", "value": 0, "icon": "fa-gift", "color": "#0e9f6e"},
			{"label": "Vesting This Month", "value": 0, "icon": "fa-unlock", "color": "#f59e0b"},
		])
		return render_template(
			"appbuilder/hcm_equity/equity_dashboard.html",
			kpi_html=kpi_html,
			appbuilder=self.appbuilder,
		)
