from __future__ import annotations

from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

from .events import (
	AnnouncementPublishedEvent,
	ExpenseSubmittedEvent,
	LeaveRequestApprovedEvent,
	LeaveRequestRejectedEvent,
	LeaveRequestSubmittedEvent,
	ProfileUpdateRequestedEvent,
)
from .models import (
	Announcement,
	EssDocument,
	LeaveBalance,
	LeaveRequest,
	ProfileUpdateRequest,
)
from .services import SelfServiceService

__all__ = [
	"SelfServicePlugin",
	"create_plugin",
	"SelfServiceService",
	"LeaveRequest",
	"LeaveBalance",
	"ProfileUpdateRequest",
	"EssDocument",
	"Announcement",
	"LeaveRequestSubmittedEvent",
	"LeaveRequestApprovedEvent",
	"LeaveRequestRejectedEvent",
	"ProfileUpdateRequestedEvent",
	"ExpenseSubmittedEvent",
	"AnnouncementPublishedEvent",
]

ESS_MENU_CATEGORY = "Employee Self-Service"
ESS_ANNUAL_LEAVE_DAYS = "21"


class SelfServicePlugin(BasePlugin):
	name = "self_service"
	domain = "hcm"
	depends_on: list[str] = ["foundation"]

	metadata: dict[str, Any] = {
		"version": "1.0.0",
		"tags": ["erp", "hcm", "ess", "mss", "leave", "self-service"],
		"description": (
			"Employee Self-Service and Manager Self-Service portal — "
			"leave management, profile updates, document access, announcements."
		),
		"author": "PgAppForge",
	}

	permissions: list[str] = [
		# Employee permissions
		"ess.leave.submit",
		"ess.leave.cancel_own",
		"ess.leave.view_own",
		"ess.leave.balance.view_own",
		"ess.profile_update.submit",
		"ess.profile_update.view_own",
		"ess.document.view_own",
		"ess.announcement.view",
		# Manager permissions
		"ess.leave.approve",
		"ess.leave.reject",
		"ess.leave.view_reports",
		"ess.profile_update.review",
		"ess.manager_dashboard.view",
		# Admin / HR permissions
		"ess.announcement.publish",
		"ess.document.manage",
		"ess.leave.balance.manage",
	]

	def get_events(self) -> list[type]:
		return [
			LeaveRequestSubmittedEvent,
			LeaveRequestApprovedEvent,
			LeaveRequestRejectedEvent,
			ProfileUpdateRequestedEvent,
			ExpenseSubmittedEvent,
			AnnouncementPublishedEvent,
		]

	def subscribe_to(self) -> list[str]:
		return [
			"hcm.employee.hired",
			"hcm.payroll.payslip.generated",
		]

	def initialize(self, appbuilder: Any, config: dict[str, Any] | None = None) -> None:
		cfg = config or {}
		appbuilder.app.config.setdefault("ESS_MENU_CATEGORY", ESS_MENU_CATEGORY)
		appbuilder.app.config.setdefault(
			"ESS_ANNUAL_LEAVE_DAYS",
			cfg.get("ESS_ANNUAL_LEAVE_DAYS", ESS_ANNUAL_LEAVE_DAYS),
		)
		appbuilder.app.config.setdefault("ESS_SICK_LEAVE_DAYS", cfg.get("ESS_SICK_LEAVE_DAYS", "10"))
		appbuilder.app.config.setdefault(
			"ESS_MATERNITY_LEAVE_DAYS", cfg.get("ESS_MATERNITY_LEAVE_DAYS", "90")
		)
		appbuilder.app.config.setdefault(
			"ESS_PATERNITY_LEAVE_DAYS", cfg.get("ESS_PATERNITY_LEAVE_DAYS", "14")
		)

	def register_models(self) -> list[type]:
		return [
			LeaveRequest,
			LeaveBalance,
			ProfileUpdateRequest,
			EssDocument,
			Announcement,
		]

	def register_views(self, appbuilder: Any) -> None:
		# Views are registered lazily to avoid circular imports at module load time.
		# Import here so they only load when appbuilder is ready.
		try:
			from .views import (  # type: ignore[import]
				AnnouncementView,
				EssDocumentView,
				LeaveBalanceView,
				LeaveRequestView,
				ProfileUpdateRequestView,
			)
			appbuilder.add_view(
				LeaveRequestView,
				"My Leave Requests",
				icon="fa-calendar",
				category=ESS_MENU_CATEGORY,
			)
			appbuilder.add_view(
				LeaveBalanceView,
				"Leave Balances",
				icon="fa-balance-scale",
				category=ESS_MENU_CATEGORY,
			)
			appbuilder.add_view(
				ProfileUpdateRequestView,
				"Profile Updates",
				icon="fa-user-edit",
				category=ESS_MENU_CATEGORY,
			)
			appbuilder.add_view(
				EssDocumentView,
				"My Documents",
				icon="fa-file-alt",
				category=ESS_MENU_CATEGORY,
			)
			appbuilder.add_view(
				AnnouncementView,
				"Announcements",
				icon="fa-bullhorn",
				category=ESS_MENU_CATEGORY,
			)
		except ImportError:
			# views.py not yet implemented — safe to skip during early bootstrap
			pass

	def setup_rules(self, session: Any) -> None:
		"""Register business rule sets for ESS leave and announcement workflows."""
		engine = RuleEngine.get_instance()

		# Ruleset 1: Leave request auto-approval for short single-day sick leave
		engine.register_ruleset(
			name="ess.leave.auto_approve_sick",
			description=(
				"Auto-approve single-day sick leave requests if employee has sufficient balance "
				"and no prior rejection in rolling 30 days."
			),
			rules=[
				{
					"id": "rule_sick_single_day_auto_approve",
					"condition": (
						"leave_type == 'SICK' and days_requested <= 1.0 "
						"and balance_available >= days_requested"
					),
					"action": "auto_approve",
					"priority": 10,
				},
			],
			session=session,
		)

		# Ruleset 2: Announcement expiry — auto-unpublish expired announcements
		engine.register_ruleset(
			name="ess.announcement.expiry",
			description=(
				"Automatically mark announcements as expired when expires_at has passed."
			),
			rules=[
				{
					"id": "rule_announcement_expire",
					"condition": "expires_at is not None and expires_at < now()",
					"action": "set_expired",
					"priority": 5,
				},
			],
			session=session,
		)


def create_plugin(
	appbuilder: Any,
	config: dict[str, Any] | None = None,
) -> SelfServicePlugin:
	"""Factory used by the plugin registry to instantiate and wire up SelfServicePlugin."""
	plugin = SelfServicePlugin()
	plugin.initialize(appbuilder, config)
	return plugin
