from __future__ import annotations
from flask_babel import lazy_gettext as _

from flask import render_template
from pgappforge import ModelView, expose, has_access
from pgappforge.models.sqla.interface import SQLAInterface

from pgappforge.plugins.erp.base_view import BaseERPView
from pgappforge.plugins.erp.hcm.referral.models import (
	ReferralProgram,
	ReferralReward,
	ReferralSubmission,
)

__all__ = [
	"ReferralProgramView",
	"ReferralSubmissionView",
	"ReferralRewardView",
	"ReferralDashboardView",
]


class ReferralProgramView(ModelView):
	datamodel = SQLAInterface(ReferralProgram)
	list_columns = ["name", "status", "reward_amount_cents", "reward_type", "starts_at", "ends_at"]
	label_columns = {"name": _("Name"), "status": _("Status"), "reward_amount_cents": _("Reward Amount (KES)"), "reward_type": _("Reward Type"), "starts_at": _("Starts At"), "ends_at": _("Ends At")}
	show_columns = ["name", "status", "reward_amount_cents", "reward_type", "starts_at", "ends_at", "reward_conditions", "eligible_positions"]
	add_exclude_columns = ["id", "created_on", "changed_on", "submissions"]
	edit_exclude_columns = ["id", "created_on", "changed_on", "submissions"]
	search_columns = ["name", "status"]


class ReferralSubmissionView(ModelView):
	datamodel = SQLAInterface(ReferralSubmission)
	list_columns = ["referrer_id", "candidate_name", "candidate_email", "position", "status", "submitted_at"]
	label_columns = {"referrer_id": _("Referrer"), "candidate_name": _("Candidate Name"), "candidate_email": _("Candidate Email"), "position": _("Position"), "status": _("Status"), "submitted_at": _("Submitted At")}
	show_columns = ["referrer_id", "candidate_name", "candidate_email", "position", "status", "submitted_at", "candidate_phone", "resume_url", "notes", "hired_at", "reward_eligible", "program", "reward"]
	add_exclude_columns = ["id", "created_on", "changed_on", "reward"]
	edit_exclude_columns = ["id", "created_on", "changed_on", "reward"]
	search_columns = ["referrer_id", "candidate_name", "status"]


class ReferralRewardView(ModelView):
	datamodel = SQLAInterface(ReferralReward)
	list_columns = ["referrer_id", "reward_amount_cents", "reward_type", "status", "approved_by", "paid_at"]
	label_columns = {"referrer_id": _("Referrer"), "reward_amount_cents": _("Reward Amount (KES)"), "reward_type": _("Reward Type"), "status": _("Status"), "approved_by": _("Approved By"), "paid_at": _("Paid At")}
	show_columns = ["referrer_id", "reward_amount_cents", "reward_type", "status", "approved_by", "paid_at", "approved_at", "payment_ref", "submission"]
	add_exclude_columns = ["id", "created_on", "changed_on"]
	edit_exclude_columns = ["id", "created_on", "changed_on"]
	search_columns = ["referrer_id", "status"]


class ReferralDashboardView(BaseERPView):
	route_base = "/hcm/referrals"

	@expose("/")
	@has_access
	def index(self):
		try:
			from pgappforge.plugins.erp.hcm.referral.models import (
				ReferralProgram,
				ReferralReward,
				ReferralSubmission,
			)
			sess = self._session()
			active_programs = self._count(ReferralProgram, session=sess, status="ACTIVE")
			pending_submissions = self._count(ReferralSubmission, session=sess, status="SUBMITTED")
			pending_rewards = self._count(ReferralReward, session=sess, status="PENDING")
		except Exception:
			active_programs = pending_submissions = pending_rewards = 0
		kpi_html = self.kpi_cards([
			{"label": "Active Programs", "value": active_programs, "icon": "fa-users", "color": "#1a56db"},
			{"label": "Pending Submissions", "value": pending_submissions, "icon": "fa-paper-plane", "color": "#0e9f6e"},
			{"label": "Pending Rewards", "value": pending_rewards, "icon": "fa-gift", "color": "#f59e0b"},
		])
		return render_template(
			"appbuilder/hcm_referral/referral_dashboard.html",
			kpi_html=kpi_html,
			appbuilder=self.appbuilder,
		)
