from __future__ import annotations

from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority
from pgappforge.plugins.erp.hcm.compensation.events import (
	AllowanceAssignedEvent,
	AllowanceRevokedEvent,
	CompensationPackageCreatedEvent,
	CompensationPackageRevisedEvent,
	DeductionAssignedEvent,
	ReviewCycleApprovedEvent,
)
from pgappforge.plugins.erp.hcm.compensation.models import (
	AllowanceDefinition,
	CompensationGrade,
	CompensationPackage,
	CompensationReviewCycle,
	DeductionDefinition,
	EmployeeAllowance,
	EmployeeDeduction,
)
from pgappforge.plugins.erp.hcm.compensation.services import (
	CompensationBudgetError,
	CompensationNotFoundError,
	CompensationService,
	CompensationServiceError,
	CompensationStateError,
)

__all__ = [
	# Plugin entry point
	"CompensationPlugin",
	"create_plugin",
	# Models
	"CompensationGrade",
	"CompensationPackage",
	"AllowanceDefinition",
	"EmployeeAllowance",
	"DeductionDefinition",
	"EmployeeDeduction",
	"CompensationReviewCycle",
	# Events
	"CompensationPackageCreatedEvent",
	"CompensationPackageRevisedEvent",
	"AllowanceAssignedEvent",
	"AllowanceRevokedEvent",
	"DeductionAssignedEvent",
	"ReviewCycleApprovedEvent",
	# Service + exceptions
	"CompensationService",
	"CompensationServiceError",
	"CompensationNotFoundError",
	"CompensationStateError",
	"CompensationBudgetError",
]


class CompensationPlugin(BasePlugin):
	"""HCM Compensation Management plugin.

	Manages compensation grades, employee packages (immutable ledger), allowances,
	deductions, and review cycles. All monetary values are stored as integer cents.
	"""

	name = "compensation"
	domain = "hcm"
	depends_on = ["foundation"]

	metadata: dict[str, Any] = {
		"version": "1.0.0",
		"tags": ["erp", "hcm", "compensation", "salary", "allowances"],
		"description": (
			"Compensation grade bands, employee salary packages (insert-only ledger), "
			"configurable allowances and deductions, and annual/ad-hoc review cycles."
		),
	}

	permissions: list[str] = [
		# Grades
		"compensation.grade.view",
		"compensation.grade.create",
		"compensation.grade.edit",
		"compensation.grade.delete",
		# Packages
		"compensation.package.view",
		"compensation.package.assign",
		# Allowances
		"compensation.allowance_def.view",
		"compensation.allowance_def.manage",
		"compensation.employee_allowance.view",
		"compensation.employee_allowance.assign",
		"compensation.employee_allowance.revoke",
		# Deductions
		"compensation.deduction_def.view",
		"compensation.deduction_def.manage",
		"compensation.employee_deduction.view",
		"compensation.employee_deduction.assign",
		# Review cycles
		"compensation.review_cycle.manage",
	]

	# ------------------------------------------------------------------
	# Plugin lifecycle
	# ------------------------------------------------------------------

	def initialize(self) -> None:
		"""Apply default configuration values if not already set by the app."""
		defaults: dict[str, Any] = {
			"COMPENSATION_MENU_CATEGORY": "Compensation",
			"COMPENSATION_DEFAULT_CURRENCY": "KES",
		}
		for key, value in defaults.items():
			self.appbuilder.app.config.setdefault(key, value)

	def get_events(self) -> list[type]:
		return [
			CompensationPackageCreatedEvent,
			CompensationPackageRevisedEvent,
			AllowanceAssignedEvent,
			AllowanceRevokedEvent,
			DeductionAssignedEvent,
			ReviewCycleApprovedEvent,
		]

	def subscribe_to(self) -> list[str]:
		return [
			"hcm.employee.hired",
			"hcm.payroll.run.calculated",
		]

	def register_models(self) -> list[type]:
		return [
			CompensationGrade,
			CompensationPackage,
			AllowanceDefinition,
			EmployeeAllowance,
			DeductionDefinition,
			EmployeeDeduction,
			CompensationReviewCycle,
		]

	def register_views(self) -> None:
		from pgappforge.plugins.erp.hcm.compensation.views import (
			AllowanceDefinitionView,
			CompensationDashboardView,
			CompensationGradeView,
			CompensationPackageView,
		)
		import logging
		log = logging.getLogger(__name__)
		cat = self.appbuilder.app.config.get("COMPENSATION_MENU_CATEGORY", "Compensation")
		self.add_view(CompensationDashboardView, "Dashboard", icon="fa-tachometer", category=cat)
		self.add_view(CompensationGradeView, "Grades", icon="fa-layer-group", category=cat)
		self.add_view(CompensationPackageView, "Packages", icon="fa-money-bill", category=cat)
		self.add_view(AllowanceDefinitionView, "Allowances", icon="fa-plus-circle", category=cat)
		log.info("CompensationPlugin: views registered under %r", cat)

	def setup_rules(self, session: Any) -> None:
		"""Install default business rules into the rules engine.

		Three rulesets:
		  1. compensation.deduction.amount_positive  — deduction amount > 0
		  2. compensation.review.budget_not_exceeded — committed <= budget_pool
		  3. compensation.package.not_zero_base_salary — base_salary_cents > 0
		"""
		try:
			from pgappforge.plugins.rules.engine import RulesEngine

			engine = RulesEngine(session=session)

			engine.ensure_ruleset(
				name="compensation.deduction.amount_positive",
				description="Employee deduction amount must be greater than zero.",
				domain="hcm.compensation",
				rules=[
					{
						"name": "deduction_amount_gt_zero",
						"condition": "amount_cents > 0",
						"message": "Deduction amount must be positive (got {amount_cents}).",
						"severity": "ERROR",
					}
				],
			)

			engine.ensure_ruleset(
				name="compensation.review.budget_not_exceeded",
				description="Committed spend in a review cycle must not exceed the budget pool.",
				domain="hcm.compensation",
				rules=[
					{
						"name": "committed_within_budget",
						"condition": "committed_cents <= budget_pool_cents",
						"message": (
							"Committed {committed_cents} cents exceeds budget pool "
							"{budget_pool_cents} cents."
						),
						"severity": "ERROR",
					}
				],
			)

			engine.ensure_ruleset(
				name="compensation.package.not_zero_base_salary",
				description="A compensation package must have a positive base salary.",
				domain="hcm.compensation",
				rules=[
					{
						"name": "base_salary_positive",
						"condition": "base_salary_cents > 0",
						"message": "Base salary must be greater than zero (got {base_salary_cents}).",
						"severity": "ERROR",
					}
				],
			)

		except Exception:
			# Rules engine may not be available in all deployment configurations.
			# Log and continue rather than blocking plugin initialisation.
			import logging
			logging.getLogger(__name__).warning(
				"compensation.setup_rules: rules engine unavailable, skipping ruleset installation",
				exc_info=True,
			)


def create_plugin(appbuilder: Any, config: dict[str, Any] | None = None) -> CompensationPlugin:
	"""Factory function used by the plugin registry to instantiate this plugin."""
	plugin = CompensationPlugin(appbuilder=appbuilder, config=config or {})
	return plugin
