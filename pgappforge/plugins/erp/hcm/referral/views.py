from __future__ import annotations

from pgappforge import ModelView
from pgappforge.models.sqla.interface import SQLAInterface

from pgappforge.plugins.erp.hcm.referral.models import (
	ReferralProgram,
	ReferralReward,
	ReferralSubmission,
)

__all__ = [
	"ReferralProgramView",
	"ReferralSubmissionView",
	"ReferralRewardView",
]


class ReferralProgramView(ModelView):
	datamodel = SQLAInterface(ReferralProgram)
	list_columns = ["name", "status", "reward_amount_cents", "reward_type", "starts_at", "ends_at"]
	add_exclude_columns = ["id", "created_on", "changed_on", "submissions"]
	edit_exclude_columns = ["id", "created_on", "changed_on", "submissions"]
	search_columns = ["name", "status"]


class ReferralSubmissionView(ModelView):
	datamodel = SQLAInterface(ReferralSubmission)
	list_columns = ["referrer_id", "candidate_name", "candidate_email", "position", "status", "submitted_at"]
	add_exclude_columns = ["id", "created_on", "changed_on", "reward"]
	edit_exclude_columns = ["id", "created_on", "changed_on", "reward"]
	search_columns = ["referrer_id", "candidate_name", "status"]


class ReferralRewardView(ModelView):
	datamodel = SQLAInterface(ReferralReward)
	list_columns = ["referrer_id", "reward_amount_cents", "reward_type", "status", "approved_by", "paid_at"]
	add_exclude_columns = ["id", "created_on", "changed_on"]
	edit_exclude_columns = ["id", "created_on", "changed_on"]
	search_columns = ["referrer_id", "status"]
