"""
pgappforge/plugins/erp/projects/__init__.py

Project Management and PSA plugin — WBS, EVM, project billing, IFRS 15 revenue recognition.

Full project lifecycle:
  Program → Project → WBSElement (hierarchy)
  ProjectResource (allocation) → ProjectTimesheet (time capture) → ProjectInvoice (billing)
  ProjectMilestone (milestone billing) → revenue recognition (IFRS 15)
  ProjectRisk (risk register) → ChangeOrder (scope management)

Domain: projects
Depends on: foundation

Events emitted:
  projects.project.created
  projects.timesheet.approved
  projects.invoice.generated
  projects.revenue.recognised
  projects.change_order.approved
  projects.risk.raised

Events consumed:
  hcm.employee.terminated   (flag open timesheets for reassignment)
  finance.period.closed     (trigger IFRS 15 recognition run)

Usage
-----
Add to your app config::

    PGAPPFORGE_PLUGINS = [
        "pgappforge.plugins.erp.foundation",
        "pgappforge.plugins.erp.projects",
    ]

Or instantiate directly::

    from pgappforge.plugins.erp.projects import ProjectsPlugin
    plugin = ProjectsPlugin(appbuilder)
    plugin.activate()
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class ProjectsPlugin(BasePlugin):
	"""Project Management and PSA ERP plugin.

	Registers views for programmes, projects, WBS, resources, timesheets,
	milestones, risks, change orders, and invoices.
	Pre-configures Rules Engine rulesets on first activate().
	"""

	name = "projects"
	domain = "projects"
	depends_on: list[str] = ["foundation"]

	# ------------------------------------------------------------------
	# Metadata
	# ------------------------------------------------------------------

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="projects",
			version="1.0.0",
			description=(
				"Project Management and PSA — full project lifecycle: "
				"WBS decomposition, resource allocation, timesheet capture, "
				"EVM (CPI/SPI/EAC), milestone billing, T&M invoicing, "
				"IFRS 15 revenue recognition (POC/Milestone/Completed Contract), "
				"risk register, and change order management."
			),
			author="PgAppForge Contributors",
			tags=["erp", "projects", "psa", "evm", "billing", "ifrs15", "wbs"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_program_list",
				"can_program_write",
				"can_project_list",
				"can_project_write",
				"can_project_portfolio",
				"can_wbs_list",
				"can_wbs_write",
				"can_resource_list",
				"can_resource_write",
				"can_timesheet_list",
				"can_timesheet_write",
				"can_timesheet_approve",
				"can_milestone_list",
				"can_milestone_write",
				"can_risk_list",
				"can_risk_write",
				"can_change_order_list",
				"can_change_order_approve",
				"can_invoice_list",
				"can_invoice_generate",
				"can_revenue_recognise",
				"can_evm_report",
				"can_utilization_report",
			],
			safe_mode_compatible=True,
		)

	# ------------------------------------------------------------------
	# get_events / subscribe_to
	# ------------------------------------------------------------------

	def get_events(self) -> list[str]:
		return [
			"projects.project.created",
			"projects.timesheet.approved",
			"projects.invoice.generated",
			"projects.revenue.recognised",
			"projects.change_order.approved",
			"projects.risk.raised",
		]

	def subscribe_to(self) -> list[str]:
		return [
			"hcm.employee.terminated",
			"finance.period.closed",
		]

	# ------------------------------------------------------------------
	# Lifecycle
	# ------------------------------------------------------------------

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"PROJECTS_MENU_CATEGORY": "Projects",
			"PROJECTS_DEFAULT_CURRENCY": "KES",
			"PROJECTS_DEFAULT_PAYMENT_TERMS_DAYS": 30,
			"PROJECTS_EVM_HEALTH_GREEN_THRESHOLD": "0.9",
			"PROJECTS_EVM_HEALTH_AMBER_THRESHOLD": "0.75",
			"PROJECTS_REVENUE_DEFAULT_METHOD": "POC",
		}
		self.config = {**defaults, **self.config}
		log.info("ProjectsPlugin initialised (config keys: %s)", list(self.config))

	def register_views(self) -> None:
		# Views registered lazily to avoid circular imports at plugin load time.
		# Only import when appbuilder is present (non-test contexts).
		try:
			from pgappforge.plugins.erp.projects.views import (  # type: ignore
				ProgramView,
				ProjectView,
				WBSElementView,
				ProjectResourceView,
				ProjectTimesheetView,
				ProjectMilestoneView,
				ProjectRiskView,
				ChangeOrderView,
				ProjectInvoiceView,
				ProjectPortfolioReportView,
				EVMReportView,
				ResourceUtilizationReportView,
			)
		except ImportError:
			log.debug("ProjectsPlugin.register_views: views module not yet created; skipping")
			return

		from pgappforge.plugins.erp.projects.api import (
			ProgramRestApi,
			ProjectRestApi,
			WBSElementRestApi,
			ProjectResourceRestApi,
			ProjectTimesheetRestApi,
			ProjectMilestoneRestApi,
			ProjectRiskRestApi,
			ChangeOrderRestApi,
			ProjectInvoiceRestApi,
		)

		cat = self.config.get("PROJECTS_MENU_CATEGORY", "Projects")

		for api_class in (
			ProgramRestApi,
			ProjectRestApi,
			WBSElementRestApi,
			ProjectResourceRestApi,
			ProjectTimesheetRestApi,
			ProjectMilestoneRestApi,
			ProjectRiskRestApi,
			ChangeOrderRestApi,
			ProjectInvoiceRestApi,
		):
			self.appbuilder.add_api(api_class)

		self.add_view(ProgramView, "Programmes", icon="fa-sitemap", category=cat)
		self.add_view(ProjectView, "Projects", icon="fa-briefcase", category=cat)
		self.add_view(WBSElementView, "Work Breakdown", icon="fa-list-ol", category=cat)
		self.add_view(ProjectResourceView, "Resources", icon="fa-users", category=cat)
		self.add_view(ProjectTimesheetView, "Timesheets", icon="fa-clock-o", category=cat)
		self.add_view(ProjectMilestoneView, "Milestones", icon="fa-flag", category=cat)
		self.add_view(ProjectRiskView, "Risk Register", icon="fa-exclamation-triangle", category=cat)
		self.add_view(ChangeOrderView, "Change Orders", icon="fa-exchange", category=cat)
		self.add_view(ProjectInvoiceView, "Invoices", icon="fa-file-text-o", category=cat)
		self.add_view(ProjectPortfolioReportView, "Portfolio", icon="fa-bar-chart", category=cat)
		self.add_view(EVMReportView, "EVM Dashboard", icon="fa-line-chart", category=cat)
		self.add_view(ResourceUtilizationReportView, "Utilization", icon="fa-tachometer", category=cat)

		log.info("ProjectsPlugin: views registered under category %r", cat)

	def register_models(self) -> list:
		from pgappforge.plugins.erp.projects.models import (
			Program,
			Project,
			WBSElement,
			ProjectResource,
			ProjectTimesheet,
			ProjectMilestone,
			ProjectRisk,
			ChangeOrder,
			ProjectInvoice,
		)
		return [
			Program,
			Project,
			WBSElement,
			ProjectResource,
			ProjectTimesheet,
			ProjectMilestone,
			ProjectRisk,
			ChangeOrder,
			ProjectInvoice,
		]

	# ------------------------------------------------------------------
	# Rules Engine pre-configuration
	# ------------------------------------------------------------------

	@staticmethod
	def setup_rules(session: Any) -> None:
		"""Pre-configure Rules Engine rulesets for the Projects domain.

		Idempotent — skips rulesets that already exist.
		"""
		try:
			from pgappforge.plugins.rules.models import Rule, RuleSet
		except ImportError:
			log.debug("ProjectsPlugin.setup_rules: rules plugin not available, skipping")
			return

		import sqlalchemy as sa

		RULESETS = [
			{
				"name": "projects.project.no_log_time_on_closed",
				"description": "Block time logging on COMPLETED or CANCELLED projects",
				"model_name": "ProjectTimesheet",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_time_on_closed_project",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "_project_status", "op": "in",
							 "value": ["COMPLETED", "CANCELLED"]},
						],
						"actions_json": [
							{"type": "raise_error",
							 "message": "Cannot log time on a COMPLETED or CANCELLED project"},
						],
					},
				],
			},
			{
				"name": "projects.timesheet.approve_only_submitted",
				"description": "Timesheets must be SUBMITTED before approval",
				"model_name": "ProjectTimesheet",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_approve_non_submitted",
						"trigger_event": "on_before_update",
						"conditions_json": [
							{"field": "_new_status", "op": "eq", "value": "APPROVED"},
							{"field": "status", "op": "neq", "value": "SUBMITTED"},
						],
						"actions_json": [
							{"type": "raise_error",
							 "message": "Timesheet must be SUBMITTED before approval"},
						],
					},
				],
			},
			{
				"name": "projects.timesheet.immutable_when_billed",
				"description": "BILLED timesheets cannot be modified",
				"model_name": "ProjectTimesheet",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_billed_timesheet_mutation",
						"trigger_event": "on_before_update",
						"conditions_json": [
							{"field": "status", "op": "eq", "value": "BILLED"},
						],
						"actions_json": [
							{"type": "raise_error",
							 "message": "BILLED timesheets are immutable"},
						],
					},
				],
			},
			{
				"name": "projects.change_order.approve_only_submitted",
				"description": "Change orders must be SUBMITTED before approval",
				"model_name": "ChangeOrder",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_approve_non_submitted_co",
						"trigger_event": "on_before_update",
						"conditions_json": [
							{"field": "_new_status", "op": "eq", "value": "APPROVED"},
							{"field": "status", "op": "neq", "value": "SUBMITTED"},
						],
						"actions_json": [
							{"type": "raise_error",
							 "message": "ChangeOrder must be SUBMITTED before approval"},
						],
					},
				],
			},
			{
				"name": "projects.risk.score_bounds",
				"description": "Risk probability and impact must be between 1 and 5",
				"model_name": "ProjectRisk",
				"stop_on_match": True,
				"rules": [
					{
						"name": "probability_in_range",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "probability", "op": "lt", "value": 1},
						],
						"actions_json": [
							{"type": "raise_error", "message": "Risk probability must be >= 1"},
						],
					},
					{
						"name": "impact_in_range",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "impact", "op": "gt", "value": 5},
						],
						"actions_json": [
							{"type": "raise_error", "message": "Risk impact must be <= 5"},
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
		log.info("ProjectsPlugin.setup_rules: %d rulesets configured", len(RULESETS))


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_plugin(
	appbuilder: Any,
	config: dict[str, Any] | None = None,
) -> ProjectsPlugin:
	return ProjectsPlugin(appbuilder, config=config or {})


# ---------------------------------------------------------------------------
# Public re-exports
# ---------------------------------------------------------------------------

from pgappforge.plugins.erp.projects.models import (  # noqa: E402
	Program,
	Project,
	WBSElement,
	ProjectResource,
	ProjectTimesheet,
	ProjectMilestone,
	ProjectRisk,
	ChangeOrder,
	ProjectInvoice,
)
from pgappforge.plugins.erp.projects.events import (  # noqa: E402
	ProjectCreatedEvent,
	TimesheetApprovedEvent,
	InvoiceGeneratedEvent,
	RevenueRecognisedEvent,
	ChangeOrderApprovedEvent,
	RiskRaisedEvent,
)
from pgappforge.plugins.erp.projects.services import (  # noqa: E402
	ProjectService,
	ProjectServiceError,
	ProjectNotFoundError,
	WBSElementNotFoundError,
	ResourceNotFoundError,
	TimesheetNotFoundError,
	MilestoneNotFoundError,
	ChangeOrderNotFoundError,
	ProjectStateError,
	ProjectBillingError,
	ProjectRevenueError,
)

__all__ = [
	# plugin
	"ProjectsPlugin",
	"create_plugin",
	# models
	"Program",
	"Project",
	"WBSElement",
	"ProjectResource",
	"ProjectTimesheet",
	"ProjectMilestone",
	"ProjectRisk",
	"ChangeOrder",
	"ProjectInvoice",
	# events
	"ProjectCreatedEvent",
	"TimesheetApprovedEvent",
	"InvoiceGeneratedEvent",
	"RevenueRecognisedEvent",
	"ChangeOrderApprovedEvent",
	"RiskRaisedEvent",
	# service + exceptions
	"ProjectService",
	"ProjectServiceError",
	"ProjectNotFoundError",
	"WBSElementNotFoundError",
	"ResourceNotFoundError",
	"TimesheetNotFoundError",
	"MilestoneNotFoundError",
	"ChangeOrderNotFoundError",
	"ProjectStateError",
	"ProjectBillingError",
	"ProjectRevenueError",
]
