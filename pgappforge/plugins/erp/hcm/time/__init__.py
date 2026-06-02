"""
pgappforge/plugins/erp/hcm/time/__init__.py

TimePlugin — HCM Time & Attendance ERP plugin.

Entities managed:
  ShiftDefinition
  AttendanceRecord
  LeavePolicy → LeaveBalance → LeaveRequest
  Timesheet → TimeEntry

Domain: hcm
Depends on: foundation, hcm.org, hcm.personnel

Events emitted:
  hcm.time.attendance.clocked_in
  hcm.time.attendance.clocked_out
  hcm.time.leave_request.submitted
  hcm.time.leave_request.approved
  hcm.time.leave_request.rejected
  hcm.time.leave_request.cancelled
  hcm.time.timesheet.submitted
  hcm.time.timesheet.approved
  hcm.time.timesheet.rejected

Events consumed:
  hcm.personnel.employee.hired       — initialise leave balance
  hcm.personnel.employee.terminated  — cancel pending leave

Usage::

    PGAPPFORGE_PLUGINS = [
        "pgappforge.plugins.erp.foundation",
        "pgappforge.plugins.erp.hcm.org",
        "pgappforge.plugins.erp.hcm.personnel",
        "pgappforge.plugins.erp.hcm.time",
    ]
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class TimePlugin(BasePlugin):
	"""HCM Time & Attendance plugin.

	Registers 5 view groups (Shifts, Attendance, Leave, Timesheets, Reports).
	Pre-configures 5 Rules Engine rulesets on first run.
	"""

	name = "hcm.time"
	domain = "hcm"
	depends_on: list[str] = ["foundation", "hcm.org", "hcm.personnel"]

	# ------------------------------------------------------------------
	# Metadata
	# ------------------------------------------------------------------

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="hcm.time",
			version="1.0.0",
			description=(
				"HCM Time & Attendance — shift definitions, geo-fenced clock-in/out, "
				"leave policies and balance management, weekly timesheets with "
				"project/cost-centre allocation, and approval workflows."
			),
			author="PgAppForge Contributors",
			tags=["erp", "hcm", "time", "attendance", "leave", "timesheets"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_hcm_time_shift_list",
				"can_hcm_time_shift_write",
				"can_hcm_time_attendance_clock",
				"can_hcm_time_attendance_list",
				"can_hcm_time_leave_submit",
				"can_hcm_time_leave_approve",
				"can_hcm_time_leave_list",
				"can_hcm_time_timesheet_write",
				"can_hcm_time_timesheet_approve",
				"can_hcm_time_reports",
			],
			safe_mode_compatible=True,
		)

	# ------------------------------------------------------------------
	# Events
	# ------------------------------------------------------------------

	def get_events(self) -> list[str]:
		return [
			"hcm.time.attendance.clocked_in",
			"hcm.time.attendance.clocked_out",
			"hcm.time.leave_request.submitted",
			"hcm.time.leave_request.approved",
			"hcm.time.leave_request.rejected",
			"hcm.time.leave_request.cancelled",
			"hcm.time.timesheet.submitted",
			"hcm.time.timesheet.approved",
			"hcm.time.timesheet.rejected",
		]

	def subscribe_to(self) -> list[str]:
		return [
			"hcm.personnel.employee.hired",
			"hcm.personnel.employee.terminated",
		]

	# ------------------------------------------------------------------
	# Lifecycle
	# ------------------------------------------------------------------

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"HCM_TIME_MENU_CATEGORY": "HCM — Time & Attendance",
			"HCM_TIME_STANDARD_HOURS": 8,
			"HCM_TIME_OVERTIME_THRESHOLD": 40,  # weekly hours before OT
		}
		self.config = {**defaults, **self.config}
		log.info("TimePlugin initialised (config keys: %s)", list(self.config))

	def register_views(self) -> None:
		from pgappforge.plugins.erp.hcm.time.views import (
			ShiftDefinitionView,
			AttendanceView,
			LeaveRequestView,
			TimesheetView,
			TimeReportView,
		)

		cat = self.config.get("HCM_TIME_MENU_CATEGORY", "HCM — Time & Attendance")

		self.add_view(ShiftDefinitionView, "Shifts", icon="fa-clock-o", category=cat)
		self.add_view(AttendanceView, "Attendance", icon="fa-check-square-o", category=cat)
		self.add_view(LeaveRequestView, "Leave Requests", icon="fa-calendar", category=cat)
		self.add_view(TimesheetView, "Timesheets", icon="fa-table", category=cat)
		self.add_view(TimeReportView, "Time Reports", icon="fa-bar-chart", category=cat)

		log.info("TimePlugin: views registered under category %r", cat)

	def register_models(self) -> list:
		from pgappforge.plugins.erp.hcm.time.models import (
			ShiftDefinition,
			AttendanceRecord,
			LeavePolicy,
			LeaveBalance,
			LeaveRequest,
			Timesheet,
			TimeEntry,
		)
		return [
			ShiftDefinition,
			AttendanceRecord,
			LeavePolicy,
			LeaveBalance,
			LeaveRequest,
			Timesheet,
			TimeEntry,
		]

	# ------------------------------------------------------------------
	# Rules Engine pre-configuration
	# ------------------------------------------------------------------

	@staticmethod
	def setup_rules(session: Any) -> None:
		"""Pre-configure 5 Rules Engine rulesets for HCM Time domain.

		Idempotent — skips rulesets that already exist.
		"""
		try:
			from pgappforge.plugins.rules.models import Rule, RuleSet
		except ImportError:
			log.debug("TimePlugin.setup_rules: rules plugin not available, skipping")
			return

		import sqlalchemy as sa

		RULESETS = [
			{
				"name": "hcm.time.leave_request.no_past_dates",
				"description": "Leave request start_date must not be in the past",
				"model_name": "LeaveRequest",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_past_leave",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "start_date", "op": "lt", "value": "today"},
						],
						"actions_json": [
							{"type": "raise_error",
							 "message": "Leave request start_date cannot be in the past"}
						],
					},
				],
			},
			{
				"name": "hcm.time.leave_request.end_after_start",
				"description": "Leave end_date must be >= start_date",
				"model_name": "LeaveRequest",
				"stop_on_match": True,
				"rules": [
					{
						"name": "end_gte_start",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "end_date", "op": "lt", "value": "start_date"},
						],
						"actions_json": [
							{"type": "raise_error",
							 "message": "Leave end_date must be >= start_date"}
						],
					},
				],
			},
			{
				"name": "hcm.time.timesheet.week_start_monday",
				"description": "Timesheet week_start must be a Monday",
				"model_name": "Timesheet",
				"stop_on_match": True,
				"rules": [
					{
						"name": "require_monday_week_start",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "week_start.weekday", "op": "neq", "value": 0},
						],
						"actions_json": [
							{"type": "raise_error",
							 "message": "Timesheet week_start must be a Monday"}
						],
					},
				],
			},
			{
				"name": "hcm.time.timesheet.no_edit_approved",
				"description": "Cannot add entries to an APPROVED or SUBMITTED timesheet",
				"model_name": "TimeEntry",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_entry_on_locked_timesheet",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "timesheet.status", "op": "in", "value": ["APPROVED", "SUBMITTED"]},
						],
						"actions_json": [
							{"type": "raise_error",
							 "message": "Cannot add entries to a timesheet in APPROVED or SUBMITTED status"}
						],
					},
				],
			},
			{
				"name": "hcm.time.attendance.no_double_clockin",
				"description": "Employee cannot clock in twice on the same day",
				"model_name": "AttendanceRecord",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_double_clockin",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "clock_in", "op": "neq", "value": None},
							{"field": "_existing_today_record", "op": "eq", "value": True},
						],
						"actions_json": [
							{"type": "raise_error",
							 "message": "Employee already has an attendance record for today"}
						],
					},
				],
			},
		]

		for rs_def in RULESETS:
			existing = session.execute(
				sa.select(RuleSet).where(RuleSet.name == rs_def["name"])
			).scalar_one_or_none()
			if existing is not None:
				continue
			rs = RuleSet(
				name=rs_def["name"],
				description=rs_def["description"],
				model_name=rs_def["model_name"],
				stop_on_match=rs_def.get("stop_on_match", False),
				enabled=True,
			)
			session.add(rs)
			session.flush()
			for r_def in rs_def.get("rules", []):
				session.add(Rule(
					ruleset_id=rs.id,
					name=r_def["name"],
					trigger_event=r_def["trigger_event"],
					conditions_json=r_def["conditions_json"],
					actions_json=r_def["actions_json"],
					enabled=True,
				))
		log.info("TimePlugin.setup_rules: %d rulesets configured", len(RULESETS))


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_plugin(appbuilder: Any, config: dict[str, Any] | None = None) -> TimePlugin:
	"""Construct a TimePlugin without activating it."""
	return TimePlugin(appbuilder, config=config or {})


# ---------------------------------------------------------------------------
# Public re-exports
# ---------------------------------------------------------------------------

from pgappforge.plugins.erp.hcm.time.models import (  # noqa: E402
	ShiftDefinition,
	AttendanceRecord,
	LeavePolicy,
	LeaveBalance,
	LeaveRequest,
	Timesheet,
	TimeEntry,
)
from pgappforge.plugins.erp.hcm.time.events import (  # noqa: E402
	ClockedInEvent,
	ClockedOutEvent,
	LeaveRequestSubmittedEvent,
	LeaveRequestApprovedEvent,
	LeaveRequestRejectedEvent,
	LeaveRequestCancelledEvent,
	TimesheetSubmittedEvent,
	TimesheetApprovedEvent,
	TimesheetRejectedEvent,
)
from pgappforge.plugins.erp.hcm.time.services import (  # noqa: E402
	TimeService,
	TimeServiceError,
	AttendanceError,
	LeaveError,
	TimesheetError,
	working_days,
)

__all__ = [
	# plugin
	"TimePlugin",
	"create_plugin",
	# models
	"ShiftDefinition",
	"AttendanceRecord",
	"LeavePolicy",
	"LeaveBalance",
	"LeaveRequest",
	"Timesheet",
	"TimeEntry",
	# events
	"ClockedInEvent",
	"ClockedOutEvent",
	"LeaveRequestSubmittedEvent",
	"LeaveRequestApprovedEvent",
	"LeaveRequestRejectedEvent",
	"LeaveRequestCancelledEvent",
	"TimesheetSubmittedEvent",
	"TimesheetApprovedEvent",
	"TimesheetRejectedEvent",
	# services
	"TimeService",
	"TimeServiceError",
	"AttendanceError",
	"LeaveError",
	"TimesheetError",
	"working_days",
]
