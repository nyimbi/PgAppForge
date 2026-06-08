from __future__ import annotations

from pgappforge import ModelView
from pgappforge.models.sqla.interface import SQLAInterface

from pgappforge.plugins.erp.hcm.wellness.models import (
	WellnessCheckIn,
	WellnessEnrollment,
	WellnessProgram,
)

__all__ = [
	"WellnessProgramView",
	"WellnessEnrollmentView",
	"WellnessCheckInView",
]


class WellnessProgramView(ModelView):
	datamodel = SQLAInterface(WellnessProgram)
	list_columns = ["name", "program_type", "status", "provider", "start_date", "is_voluntary"]
	add_exclude_columns = ["id", "created_on", "changed_on", "enrollments"]
	edit_exclude_columns = ["id", "created_on", "changed_on", "enrollments"]
	search_columns = ["name", "program_type", "status"]


class WellnessEnrollmentView(ModelView):
	datamodel = SQLAInterface(WellnessEnrollment)
	list_columns = ["employee_id", "program", "status", "enrolled_at", "completed_at"]
	add_exclude_columns = ["id", "created_on", "changed_on"]
	edit_exclude_columns = ["id", "created_on", "changed_on"]
	search_columns = ["employee_id", "status"]


class WellnessCheckInView(ModelView):
	datamodel = SQLAInterface(WellnessCheckIn)
	list_columns = ["employee_id", "check_in_date", "wellbeing_score", "stress_level", "anonymous"]
	add_exclude_columns = ["id", "created_on", "changed_on"]
	edit_exclude_columns = ["id", "created_on", "changed_on"]
	search_columns = ["employee_id"]
