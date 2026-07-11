from __future__ import annotations
from flask_babel import lazy_gettext as _

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
	list_columns = ["grade_code", "name", "currency_code", "is_active"]
	label_columns = {"grade_code": _("Grade Code"), "name": _("Name"), "min_salary_cents": _("Min Salary (KES)"), "midpoint_cents": _("Midpoint (KES)"), "max_salary_cents": _("Max Salary (KES)"), "currency_code": _("Currency Code"), "is_active": _("Is Active")}
	show_columns = ["grade_code", "name", "min_salary_cents", "midpoint_cents", "max_salary_cents", "currency_code", "is_active", "effective_from", "effective_to"]
	add_exclude_columns = ["id", "created_on", "changed_on", "packages"]
	edit_exclude_columns = ["id", "created_on", "changed_on", "packages"]
	search_columns = ["grade_code", "name"]


class CompensationPackageView(ModelView):
	datamodel = SQLAInterface(CompensationPackage)
	list_columns = ["employee_id", "pay_frequency", "package_type", "effective_from", "currency_code"]
	label_columns = {"employee_id": _("Employee"), "base_salary_cents": _("Base Salary (KES)"), "pay_frequency": _("Pay Frequency"), "package_type": _("Package Type"), "effective_from": _("Effective From"), "currency_code": _("Currency Code")}
	show_columns = ["employee_id", "base_salary_cents", "pay_frequency", "package_type", "effective_from", "currency_code", "effective_to", "approved_by", "approved_at", "notes", "metadata_", "grade"]
	add_exclude_columns = ["id", "created_on", "changed_on"]
	edit_exclude_columns = ["id", "created_on", "changed_on"]
	search_columns = ["employee_id", "package_type"]


class AllowanceDefinitionView(ModelView):
	datamodel = SQLAInterface(AllowanceDefinition)
	list_columns = ["code", "name", "allowance_type", "amount_cents", "is_taxable", "is_active"]
	label_columns = {"code": _("Code"), "name": _("Name"), "allowance_type": _("Allowance Type"), "amount_cents": _("Amount (KES)"), "is_taxable": _("Is Taxable"), "is_active": _("Is Active")}
	show_columns = ["code", "name", "allowance_type", "amount_cents", "is_taxable", "is_active", "percentage_of_basic", "is_pensionable", "currency_code"]
	add_exclude_columns = ["id", "created_on", "changed_on", "employee_allowances"]
	edit_exclude_columns = ["id", "created_on", "changed_on", "employee_allowances"]
	search_columns = ["code", "name", "allowance_type"]


class CompensationDashboardView(BaseERPView):
	route_base = "/hcm/compensation"

	@expose("/")
	@has_access
	def index(self):
		try:
			from pgappforge.plugins.erp.hcm.compensation.models import (
				CompensationGrade,
				CompensationReviewCycle,
			)
			sess = self._session()
			active_grades = self._count(CompensationGrade, session=sess, is_active=True)
			open_cycles = self._count(CompensationReviewCycle, session=sess, status="IN_PROGRESS")
		except Exception:
			active_grades = open_cycles = 0
		kpi_html = self.kpi_cards([
			{"label": "Active Grades", "value": active_grades, "icon": "fa-layer-group", "color": "#1a56db"},
			{"label": "Open Review Cycles", "value": open_cycles, "icon": "fa-sync", "color": "#f59e0b"},
		])
		return render_template(
			"appbuilder/hcm_comp/merit_cycle_dashboard.html",
			kpi_html=kpi_html,
			appbuilder=self.appbuilder,
		)
