from __future__ import annotations

from flask import render_template
from pgappforge import ModelView, expose, has_access
from pgappforge.models.sqla.interface import SQLAInterface

from pgappforge.plugins.erp.base_view import BaseERPView
from pgappforge.plugins.erp.hcm.compensation.models import (
	AllowanceDefinition,
	CompensationGrade,
	CompensationPackage,
	CompensationReviewCycle,
)

__all__ = [
	"CompensationGradeView",
	"CompensationPackageView",
	"AllowanceDefinitionView",
	"CompensationDashboardView",
]


class CompensationGradeView(ModelView):
	datamodel = SQLAInterface(CompensationGrade)
	list_columns = ["grade_code", "name", "min_salary_cents", "midpoint_cents", "max_salary_cents", "currency_code", "is_active"]
	add_exclude_columns = ["id", "created_on", "changed_on", "packages"]
	edit_exclude_columns = ["id", "created_on", "changed_on", "packages"]
	search_columns = ["grade_code", "name"]


class CompensationPackageView(ModelView):
	datamodel = SQLAInterface(CompensationPackage)
	list_columns = ["employee_id", "base_salary_cents", "pay_frequency", "package_type", "effective_from", "currency_code"]
	add_exclude_columns = ["id", "created_on", "changed_on"]
	edit_exclude_columns = ["id", "created_on", "changed_on"]
	search_columns = ["employee_id", "package_type"]


class AllowanceDefinitionView(ModelView):
	datamodel = SQLAInterface(AllowanceDefinition)
	list_columns = ["code", "name", "allowance_type", "amount_cents", "is_taxable", "is_active"]
	add_exclude_columns = ["id", "created_on", "changed_on", "employee_allowances"]
	edit_exclude_columns = ["id", "created_on", "changed_on", "employee_allowances"]
	search_columns = ["code", "name", "allowance_type"]


class CompensationDashboardView(BaseERPView):
	route_base = "/hcm/compensation"

	@expose("/")
	@has_access
	def index(self):
		kpi_html = self.kpi_cards([
			{"label": "Active Grades", "value": 0, "icon": "fa-layer-group", "color": "#1a56db"},
			{"label": "Packages This Month", "value": 0, "icon": "fa-money-bill", "color": "#0e9f6e"},
			{"label": "Open Review Cycles", "value": 0, "icon": "fa-sync", "color": "#f59e0b"},
		])
		return render_template(
			"appbuilder/hcm_comp/merit_cycle_dashboard.html",
			kpi_html=kpi_html,
			appbuilder=self.appbuilder,
		)
