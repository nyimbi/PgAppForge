"""
pgappforge/plugins/erp/hcm/payroll/__init__.py

PayrollPlugin — HCM Payroll ERP plugin.

Full payroll lifecycle:
  PayrollCalendar → PayrollRun → Payslip / PayslipLine
  TaxWithholding (per employee/jurisdiction)

Domain: hcm
Depends on: foundation

Events emitted:
  hcm.payroll.run.calculated
  hcm.payroll.run.approved
  hcm.payroll.run.paid
  hcm.payroll.payslip.reversed
  hcm.payroll.gl.posted
  hcm.payroll.statutory.filed

Events consumed:
  hcm.employee.salary_changed   (triggers recalculation checks)
  hcm.employee.terminated       (triggers termination run creation)

Usage
-----
Add to your app config::

    PGAPPFORGE_PLUGINS = [
        "pgappforge.plugins.erp.foundation",
        "pgappforge.plugins.erp.hcm.payroll",
    ]

Or instantiate directly::

    from pgappforge.plugins.erp.hcm.payroll import PayrollPlugin
    plugin = PayrollPlugin(appbuilder)
    plugin.activate()
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class PayrollPlugin(BasePlugin):
	"""HCM Payroll ERP plugin.

	Registers 5 view groups and 3 report endpoints.
	Pre-configures 5 Rules Engine rulesets on first run.
	"""

	name = "payroll"
	domain = "hcm"
	depends_on: list[str] = ["foundation"]

	# ------------------------------------------------------------------
	# Metadata
	# ------------------------------------------------------------------

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="payroll",
			version="1.0.0",
			description=(
				"HCM Payroll — full payroll lifecycle: calendar management, "
				"gross-to-net calculation, statutory deductions, ISO 20022 bank "
				"file generation, GL posting, payslip reversal, annual statutory reporting."
			),
			author="PgAppForge Contributors",
			tags=["erp", "hcm", "payroll", "payslip", "tax", "pension"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_payroll_calendar_list",
				"can_payroll_calendar_write",
				"can_payroll_run_list",
				"can_payroll_run_write",
				"can_payroll_run_calculate",
				"can_payroll_run_approve",
				"can_payroll_run_pay",
				"can_payroll_run_bank_file",
				"can_payroll_run_post_gl",
				"can_payroll_payslip_list",
				"can_payroll_payslip_reverse",
				"can_payroll_tax_withholding_list",
				"can_payroll_tax_withholding_write",
				"can_payroll_reports",
			],
			safe_mode_compatible=True,
		)

	# ------------------------------------------------------------------
	# get_events / subscribe_to
	# ------------------------------------------------------------------

	def get_events(self) -> list[str]:
		return [
			"hcm.payroll.run.calculated",
			"hcm.payroll.run.approved",
			"hcm.payroll.run.paid",
			"hcm.payroll.payslip.reversed",
			"hcm.payroll.gl.posted",
			"hcm.payroll.statutory.filed",
		]

	def subscribe_to(self) -> list[str]:
		return [
			"hcm.employee.salary_changed",
			"hcm.employee.terminated",
		]

	# ------------------------------------------------------------------
	# Lifecycle
	# ------------------------------------------------------------------

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"PAYROLL_MENU_CATEGORY": "Payroll",
			"PAYROLL_DEFAULT_CURRENCY": "USD",
			"PAYROLL_NI_EMPLOYEE_RATE": "0.12",
			"PAYROLL_PENSION_EMPLOYEE_RATE": "0.05",
			"PAYROLL_PENSION_EMPLOYER_RATE": "0.03",
			"PAYROLL_INCOME_TAX_RATE_DEFAULT": "0.20",
		}
		self.config = {**defaults, **self.config}
		log.info("PayrollPlugin initialised (config keys: %s)", list(self.config))

	def register_views(self) -> None:
		from pgappforge.plugins.erp.hcm.payroll.views import (
			PayrollCalendarView,
			PayrollReportView,
			PayrollRunView,
			PayslipView,
			TaxWithholdingView,
		)

		cat = self.config.get("PAYROLL_MENU_CATEGORY", "Payroll")

		self.add_view(PayrollCalendarView, "Pay Calendars", icon="fa-calendar", category=cat)
		self.add_view(PayrollRunView, "Payroll Runs", icon="fa-play-circle", category=cat)
		self.add_view(PayslipView, "Payslips", icon="fa-file-text", category=cat)
		self.add_view(TaxWithholdingView, "Tax Withholding", icon="fa-percent", category=cat)
		self.add_view(PayrollReportView, "Payroll Reports", icon="fa-bar-chart", category=cat)

		log.info("PayrollPlugin: views registered under category %r", cat)

	def register_models(self) -> list:
		from pgappforge.plugins.erp.hcm.payroll.models import (
			PayrollCalendar,
			PayrollRun,
			Payslip,
			PayslipLine,
			TaxWithholding,
		)
		return [PayrollCalendar, PayrollRun, Payslip, PayslipLine, TaxWithholding]

	# ------------------------------------------------------------------
	# Rules Engine pre-configuration
	# ------------------------------------------------------------------

	@staticmethod
	def setup_rules(session: Any) -> None:
		"""Pre-configure 5 Rules Engine rulesets for HCM Payroll domain.

		Idempotent — skips rulesets that already exist.
		"""
		try:
			from pgappforge.plugins.rules.models import Rule, RuleSet
		except ImportError:
			log.debug("PayrollPlugin.setup_rules: rules plugin not available, skipping")
			return

		import sqlalchemy as sa

		RULESETS = [
			{
				"name": "payroll.run.draft_only_calculate",
				"description": "Payroll runs can only be calculated when in DRAFT status",
				"model_name": "PayrollRun",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_non_draft_calculation",
						"trigger_event": "on_before_update",
						"conditions_json": [
							{"field": "_action", "op": "eq", "value": "calculate"},
							{"field": "status", "op": "neq", "value": "DRAFT"},
						],
						"actions_json": [
							{"type": "raise_error",
							 "message": "PayrollRun must be in DRAFT status to calculate"}
						],
					},
				],
			},
			{
				"name": "payroll.run.approve_requires_calculated",
				"description": "Payroll run must be CALCULATED before approval",
				"model_name": "PayrollRun",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_non_calculated_approval",
						"trigger_event": "on_before_update",
						"conditions_json": [
							{"field": "_new_status", "op": "eq", "value": "APPROVED"},
							{"field": "_old_status", "op": "neq", "value": "CALCULATED"},
						],
						"actions_json": [
							{"type": "raise_error",
							 "message": "PayrollRun must be CALCULATED before approval"}
						],
					},
				],
			},
			{
				"name": "payroll.payslip.positive_gross",
				"description": "Payslip gross_pay_cents must be positive for non-reversal payslips",
				"model_name": "Payslip",
				"stop_on_match": True,
				"rules": [
					{
						"name": "require_positive_gross",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "gross_pay_cents", "op": "lte", "value": 0},
							{"field": "status", "op": "neq", "value": "REVERSED"},
						],
						"actions_json": [
							{"type": "raise_error",
							 "message": "Payslip gross_pay_cents must be positive"}
						],
					},
				],
			},
			{
				"name": "payroll.payslip.immutable_after_paid",
				"description": "PAID payslips must not be directly mutated — create reversal instead",
				"model_name": "Payslip",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_paid_payslip_mutation",
						"trigger_event": "on_before_update",
						"conditions_json": [
							{"field": "status", "op": "eq", "value": "PAID"},
							{"field": "_new_status", "op": "neq", "value": "REVERSED"},
						],
						"actions_json": [
							{"type": "raise_error",
							 "message": "PAID payslips are immutable; create a reversal payslip instead"}
						],
					},
				],
			},
			{
				"name": "payroll.tax_withholding.additional_non_negative",
				"description": "Additional withholding amount cannot be negative",
				"model_name": "TaxWithholding",
				"stop_on_match": True,
				"rules": [
					{
						"name": "require_non_negative_additional_withholding",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "additional_withholding_cents", "op": "lt", "value": 0},
						],
						"actions_json": [
							{"type": "raise_error",
							 "message": "additional_withholding_cents cannot be negative"}
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
		log.info("PayrollPlugin.setup_rules: %d rulesets configured", len(RULESETS))


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_plugin(
	appbuilder: Any,
	config: dict[str, Any] | None = None,
) -> PayrollPlugin:
	return PayrollPlugin(appbuilder, config=config or {})


# ---------------------------------------------------------------------------
# Public re-exports
# ---------------------------------------------------------------------------

from pgappforge.plugins.erp.hcm.payroll.models import (  # noqa: E402
	PayrollCalendar,
	PayrollRun,
	Payslip,
	PayslipLine,
	TaxWithholding,
)
from pgappforge.plugins.erp.hcm.payroll.events import (  # noqa: E402
	PayrollRunCalculatedEvent,
	PayrollRunApprovedEvent,
	PayrollRunPaidEvent,
	PayslipReversedEvent,
	PayrollGLPostedEvent,
	StatutoryReportFiledEvent,
)
from pgappforge.plugins.erp.hcm.payroll.services import (  # noqa: E402
	PayrollService,
	PayrollServiceError,
	PayrollRunNotFoundError,
	PayslipNotFoundError,
	PayrollStateError,
	PayrollCalculationError,
)

__all__ = [
	# plugin
	"PayrollPlugin",
	"create_plugin",
	# models
	"PayrollCalendar",
	"PayrollRun",
	"Payslip",
	"PayslipLine",
	"TaxWithholding",
	# events
	"PayrollRunCalculatedEvent",
	"PayrollRunApprovedEvent",
	"PayrollRunPaidEvent",
	"PayslipReversedEvent",
	"PayrollGLPostedEvent",
	"StatutoryReportFiledEvent",
	# services
	"PayrollService",
	"PayrollServiceError",
	"PayrollRunNotFoundError",
	"PayslipNotFoundError",
	"PayrollStateError",
	"PayrollCalculationError",
]
