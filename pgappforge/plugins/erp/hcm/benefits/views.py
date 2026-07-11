from __future__ import annotations
from flask_babel import lazy_gettext as _

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
	label_columns = {"plan_code": _("Plan Code"), "name": _("Name"), "plan_type": _("Plan Type"), "carrier": _("Carrier"), "is_active": _("Is Active"), "effective_from": _("Effective From")}
	show_columns = ["plan_code", "name", "plan_type", "carrier", "is_active", "effective_from", "employee_premium_cents", "employer_premium_cents", "coverage_tiers", "effective_to", "country_code", "statutory_nhif", "metadata_"]
	add_exclude_columns = ["id", "created_on", "changed_on", "enrollments"]
	edit_exclude_columns = ["id", "created_on", "changed_on", "enrollments"]
	search_columns = ["plan_code", "name", "plan_type", "carrier"]


class BenefitEnrollmentView(ModelView):
	datamodel = SQLAInterface(BenefitEnrollment)
	list_columns = ["employee_id", "plan", "coverage_tier", "status", "effective_from"]
	label_columns = {"employee_id": _("Employee"), "plan": _("Plan"), "coverage_tier": _("Coverage Tier"), "status": _("Status"), "effective_from": _("Effective From")}
	show_columns = ["employee_id", "plan", "coverage_tier", "status", "effective_from", "effective_to", "enrolled_by", "enrolled_at", "waiver_reason"]
	add_exclude_columns = ["id", "created_on", "changed_on", "claims", "deductions"]
	edit_exclude_columns = ["id", "created_on", "changed_on", "claims", "deductions"]
	search_columns = ["employee_id", "status"]


class BenefitClaimView(ModelView):
	datamodel = SQLAInterface(BenefitClaim)
	list_columns = ["employee_id", "claim_date", "claimed_amount_cents", "status", "adjudicated_at"]
	label_columns = {"employee_id": _("Employee"), "claim_date": _("Claim Date"), "claimed_amount_cents": _("Claimed Amount (KES)"), "status": _("Status"), "adjudicated_at": _("Adjudicated At")}
	show_columns = ["employee_id", "claim_date", "claimed_amount_cents", "status", "adjudicated_at", "claim_ref", "service_date", "approved_amount_cents", "denial_reason", "attachments", "enrollment"]
	add_exclude_columns = ["id", "created_on", "changed_on"]
	edit_exclude_columns = ["id", "created_on", "changed_on"]
	search_columns = ["employee_id", "status", "claim_ref"]


class BenefitsDashboardView(BaseERPView):
	route_base = "/hcm/benefits"

	@expose("/")
	@has_access
	def index(self):
		try:
			from pgappforge.plugins.erp.hcm.benefits.models import (
				BenefitClaim,
				BenefitEnrollment,
				BenefitPlan,
			)
			sess = self._session()
			active_plans = self._count(BenefitPlan, session=sess, is_active=True)
			active_enrollments = self._count(BenefitEnrollment, session=sess, status="ACTIVE")
			pending_claims = self._count(BenefitClaim, session=sess, status="SUBMITTED")
		except Exception:
			active_plans = active_enrollments = pending_claims = 0
		kpi_html = self.kpi_cards([
			{"label": "Active Plans", "value": active_plans, "icon": "fa-file-medical", "color": "#1a56db"},
			{"label": "Active Enrollments", "value": active_enrollments, "icon": "fa-users", "color": "#0e9f6e"},
			{"label": "Pending Claims", "value": pending_claims, "icon": "fa-clock", "color": "#f59e0b"},
		])
		return render_template(
			"appbuilder/hcm_benefits/enrollment_wizard.html",
			kpi_html=kpi_html,
			appbuilder=self.appbuilder,
		)
