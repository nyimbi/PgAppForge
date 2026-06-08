from __future__ import annotations

from flask import render_template
from pgappforge import ModelView, expose, has_access
from pgappforge.models.sqla.interface import SQLAInterface

from pgappforge.plugins.erp.base_view import BaseERPView
from pgappforge.plugins.erp.hcm.benefits.models import (
	BenefitClaim,
	BenefitEnrollment,
	BenefitPlan,
	OpenEnrollmentWindow,
)

__all__ = [
	"BenefitPlanView",
	"BenefitEnrollmentView",
	"BenefitClaimView",
	"BenefitsDashboardView",
]


class BenefitPlanView(ModelView):
	datamodel = SQLAInterface(BenefitPlan)
	list_columns = ["plan_code", "name", "plan_type", "carrier", "is_active", "effective_from"]
	add_exclude_columns = ["id", "created_on", "changed_on", "enrollments"]
	edit_exclude_columns = ["id", "created_on", "changed_on", "enrollments"]
	search_columns = ["plan_code", "name", "plan_type", "carrier"]


class BenefitEnrollmentView(ModelView):
	datamodel = SQLAInterface(BenefitEnrollment)
	list_columns = ["employee_id", "plan", "coverage_tier", "status", "effective_from"]
	add_exclude_columns = ["id", "created_on", "changed_on", "claims", "deductions"]
	edit_exclude_columns = ["id", "created_on", "changed_on", "claims", "deductions"]
	search_columns = ["employee_id", "status"]


class BenefitClaimView(ModelView):
	datamodel = SQLAInterface(BenefitClaim)
	list_columns = ["employee_id", "claim_date", "claimed_amount_cents", "status", "adjudicated_at"]
	add_exclude_columns = ["id", "created_on", "changed_on"]
	edit_exclude_columns = ["id", "created_on", "changed_on"]
	search_columns = ["employee_id", "status", "claim_ref"]


class BenefitsDashboardView(BaseERPView):
	route_base = "/hcm/benefits"

	@expose("/")
	@has_access
	def index(self):
		kpi_html = self.kpi_cards([
			{"label": "Active Plans", "value": 0, "icon": "fa-file-medical", "color": "#1a56db"},
			{"label": "Active Enrollments", "value": 0, "icon": "fa-users", "color": "#0e9f6e"},
			{"label": "Pending Claims", "value": 0, "icon": "fa-clock", "color": "#f59e0b"},
		])
		return render_template(
			"appbuilder/hcm_benefits/enrollment_wizard.html",
			kpi_html=kpi_html,
			appbuilder=self.appbuilder,
		)
