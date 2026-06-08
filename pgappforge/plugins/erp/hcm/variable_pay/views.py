from __future__ import annotations

from flask import render_template
from pgappforge import ModelView, expose, has_access
from pgappforge.models.sqla.interface import SQLAInterface

from pgappforge.plugins.erp.base_view import BaseERPView
from pgappforge.plugins.erp.hcm.variable_pay.models import (
	CommissionPayout,
	EmployeeQuota,
	IncentivePlan,
)

__all__ = [
	"IncentivePlanView",
	"EmployeeQuotaView",
	"CommissionPayoutView",
	"VariablePayDashboardView",
]


class IncentivePlanView(ModelView):
	datamodel = SQLAInterface(IncentivePlan)
	list_columns = ["name", "plan_type", "currency_code", "effective_from", "is_active"]
	add_exclude_columns = ["id", "created_on", "changed_on", "quotas"]
	edit_exclude_columns = ["id", "created_on", "changed_on", "quotas"]
	search_columns = ["name", "plan_type"]


class EmployeeQuotaView(ModelView):
	datamodel = SQLAInterface(EmployeeQuota)
	list_columns = ["employee_id", "plan", "period", "quota_cents", "attained_cents", "attainment_pct", "status"]
	add_exclude_columns = ["id", "created_on", "changed_on", "calculations"]
	edit_exclude_columns = ["id", "created_on", "changed_on", "calculations"]
	search_columns = ["employee_id", "period", "status"]


class CommissionPayoutView(ModelView):
	datamodel = SQLAInterface(CommissionPayout)
	list_columns = ["employee_id", "period", "amount_cents", "status", "approved_by", "paid_at"]
	add_exclude_columns = ["id", "created_on", "changed_on"]
	edit_exclude_columns = ["id", "created_on", "changed_on"]
	search_columns = ["employee_id", "period", "status"]


class VariablePayDashboardView(BaseERPView):
	route_base = "/hcm/variable-pay"

	@expose("/")
	@has_access
	def index(self):
		kpi_html = self.kpi_cards([
			{"label": "Active Plans", "value": 0, "icon": "fa-trophy", "color": "#1a56db"},
			{"label": "Open Quotas", "value": 0, "icon": "fa-bullseye", "color": "#0e9f6e"},
			{"label": "Pending Payouts", "value": 0, "icon": "fa-hand-holding-usd", "color": "#f59e0b"},
		])
		return render_template(
			"appbuilder/hcm_vp/variable_pay_dashboard.html",
			kpi_html=kpi_html,
			appbuilder=self.appbuilder,
		)
