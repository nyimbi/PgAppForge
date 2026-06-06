from __future__ import annotations

import logging

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority
from pgappforge.plugins.erp.hcm.benefits.events import (
	BenefitClaimAdjudicatedEvent,
	BenefitClaimSubmittedEvent,
	BenefitDeductionsGeneratedEvent,
	BenefitEnrolledEvent,
	BenefitTerminatedEvent,
	OpenEnrollmentOpenedEvent,
)
from pgappforge.plugins.erp.hcm.benefits.models import (
	BenefitClaim,
	BenefitDeduction,
	BenefitEnrollment,
	BenefitPlan,
	OpenEnrollmentWindow,
)
from pgappforge.plugins.erp.hcm.benefits.services import (
	BenefitsService,
	BenefitsServiceError,
	ClaimNotFoundError,
	EnrollmentNotFoundError,
	EnrollmentStateError,
)

__all__ = [
	# Plugin entry point
	"BenefitsPlugin",
	"create_plugin",
	# Models
	"BenefitPlan",
	"BenefitEnrollment",
	"BenefitClaim",
	"BenefitDeduction",
	"OpenEnrollmentWindow",
	# Events
	"BenefitEnrolledEvent",
	"BenefitTerminatedEvent",
	"BenefitClaimSubmittedEvent",
	"BenefitClaimAdjudicatedEvent",
	"BenefitDeductionsGeneratedEvent",
	"OpenEnrollmentOpenedEvent",
	# Service layer
	"BenefitsService",
	"BenefitsServiceError",
	"EnrollmentNotFoundError",
	"EnrollmentStateError",
	"ClaimNotFoundError",
]

_log = logging.getLogger(__name__)


class BenefitsPlugin(BasePlugin):
	"""HCM Benefits Administration plugin.

	Covers Kenya NHIF integration, open enrollment windows, claims
	adjudication, and payroll deduction generation.
	"""

	name = "benefits"
	domain = "hcm"
	depends_on = ["foundation"]

	metadata = {
		"version": "1.0.0",
		"description": (
			"HCM Benefits Administration — Kenya NHIF integration, "
			"open enrollment, claims, payroll deduction generation"
		),
		"tags": ["erp", "hcm", "benefits", "nhif", "insurance"],
	}

	permissions = [
		# Plan management
		"can_list_benefit_plans",
		"can_write_benefit_plans",
		# Enrollment management
		"can_list_benefit_enrollments",
		"can_write_benefit_enrollments",
		"can_approve_benefit_enrollments",
		# Claims management
		"can_list_benefit_claims",
		"can_write_benefit_claims",
		"can_approve_benefit_claims",
		# Deductions
		"can_list_benefit_deductions",
		"can_write_benefit_deductions",
		"can_approve_benefit_deductions",
		# Reporting
		"can_view_benefits_reports",
		"can_export_benefits_reports",
		# Open enrollment administration
		"can_manage_open_enrollment",
	]

	def get_events(self) -> list[str]:
		return [
			"hcm.benefits.enrolled",
			"hcm.benefits.terminated",
			"hcm.benefits.claim.submitted",
			"hcm.benefits.claim.adjudicated",
			"hcm.benefits.deductions.generated",
			"hcm.benefits.open_enrollment.opened",
		]

	def subscribe_to(self) -> list[str]:
		return [
			"hcm.employee.terminated",
			"hcm.payroll.run.calculated",
		]

	def initialize(self) -> None:
		"""Set config defaults and wire up event subscriptions."""
		defaults = {
			"BENEFITS_MENU_CATEGORY": "Benefits",
			"BENEFITS_DEFAULT_CURRENCY": "KES",
		}
		if self.appbuilder is not None:
			app = self.appbuilder.get_app()
			for key, value in defaults.items():
				app.config.setdefault(key, value)

		# Wire event subscriptions if an event bus is available
		try:

			subscribe("hcm.employee.terminated", self._on_employee_terminated)
			subscribe("hcm.payroll.run.calculated", self._on_payroll_run_calculated)
			_log.info("BenefitsPlugin: event subscriptions registered")
		except Exception:  # noqa: BLE001
			_log.debug("BenefitsPlugin: event bus not available; subscriptions skipped")

		_log.info("BenefitsPlugin initialized (currency=%s)", defaults["BENEFITS_DEFAULT_CURRENCY"])

	def register_models(self) -> list:
		return [
			BenefitPlan,
			BenefitEnrollment,
			BenefitClaim,
			BenefitDeduction,
			OpenEnrollmentWindow,
		]

	def register_views(self) -> None:
		"""Register FAB views — deferred until view classes are implemented."""
		_log.info(
			"BenefitsPlugin.register_views: view registration pending implementation"
		)

	def setup_rules(self, session: object) -> None:  # type: ignore[override]
		"""Install domain-level validation rulesets via the Rules Engine.

		Three rulesets are registered:
		1. benefits.enrollment.no_duplicate_active — prevents duplicate active enrollments.
		2. benefits.claim.active_enrollment_required — claims require an active enrollment.
		3. benefits.deduction.immutable_after_processed — blocks mutations on PROCESSED deductions.
		"""
		try:
			from pgappforge.plugins.rules.engine import RulesEngine

			engine = RulesEngine(session=session)

			# Ruleset 1: no duplicate active enrollment
			engine.register_ruleset(
				name="benefits.enrollment.no_duplicate_active",
				model="BenefitEnrollment",
				rules=[
					{
						"field": "status",
						"op": "eq",
						"value": "ACTIVE",
					}
				],
				action="raise_error",
				message=(
					"An ACTIVE enrollment already exists for this employee and plan. "
					"Terminate the existing enrollment before creating a new one."
				),
			)

			# Ruleset 2: claim requires active enrollment
			engine.register_ruleset(
				name="benefits.claim.active_enrollment_required",
				model="BenefitClaim",
				rules=[
					{
						"field": "enrollment.status",
						"op": "neq",
						"value": "ACTIVE",
					}
				],
				action="raise_error",
				message=(
					"Claims can only be submitted against an ACTIVE enrollment."
				),
			)

			# Ruleset 3: PROCESSED deductions are immutable
			engine.register_ruleset(
				name="benefits.deduction.immutable_after_processed",
				model="BenefitDeduction",
				rules=[
					{
						"field": "status",
						"op": "eq",
						"value": "PROCESSED",
					}
				],
				action="raise_error",
				message=(
					"PROCESSED deductions cannot be modified. "
					"Create a REVERSED deduction instead."
				),
			)

			_log.info("BenefitsPlugin: 3 rulesets registered via RulesEngine")

		except Exception as exc:  # noqa: BLE001
			_log.warning(
				"BenefitsPlugin.setup_rules: RulesEngine unavailable — %s", exc
			)

	# ------------------------------------------------------------------
	# Internal event handlers
	# ------------------------------------------------------------------

	def _on_employee_terminated(self, event: object) -> None:
		"""Auto-terminate all ACTIVE enrollments when an employee is terminated."""
		try:
			from pgappforge.extensions import db

			employee_id: str = getattr(event, "employee_id", "")
			tenant_id: str = getattr(event, "tenant_id", "")
			termination_date = getattr(event, "termination_date", None)

			if not (employee_id and tenant_id):
				_log.warning("_on_employee_terminated: missing employee_id or tenant_id in event")
				return

			svc = BenefitsService()
			from sqlalchemy import select

			with db.session() as session:
				active = session.execute(
					select(BenefitEnrollment).where(
						BenefitEnrollment.tenant_id == tenant_id,
						BenefitEnrollment.employee_id == employee_id,
						BenefitEnrollment.status == "ACTIVE",
					)
				).scalars().all()

				for enrollment in active:
					svc.terminate_enrollment(
						enrollment.id,
						termination_date,
						"employee_terminated",
						session,
					)
				session.commit()
				_log.info(
					"Auto-terminated %d enrollments for employee=%s", len(active), employee_id
				)
		except Exception as exc:  # noqa: BLE001
			_log.error("_on_employee_terminated handler failed: %s", exc)

	def _on_payroll_run_calculated(self, event: object) -> None:
		"""Generate benefit deductions when a payroll run is calculated."""
		try:
			from pgappforge.extensions import db

			period: str = getattr(event, "period", "")
			tenant_id: str = getattr(event, "tenant_id", "")

			if not (period and tenant_id):
				_log.warning("_on_payroll_run_calculated: missing period or tenant_id in event")
				return

			svc = BenefitsService()
			with db.session() as session:
				deductions = svc.generate_deductions(period, tenant_id, session)
				session.commit()
				_log.info(
					"Auto-generated %d deductions for period=%s tenant=%s",
					len(deductions), period, tenant_id,
				)
		except Exception as exc:  # noqa: BLE001
			_log.error("_on_payroll_run_calculated handler failed: %s", exc)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def create_plugin(appbuilder: object, config: dict | None = None) -> BenefitsPlugin:
	"""Instantiate and return the BenefitsPlugin.

	Args:
		appbuilder: The FAB AppBuilder instance.
		config: Optional override dict merged into app config before initialize().

	Returns:
		A fully constructed BenefitsPlugin ready for registration.
	"""
	plugin = BenefitsPlugin(appbuilder=appbuilder)

	if config and appbuilder is not None:
		app = appbuilder.get_app()  # type: ignore[union-attr]
		for key, value in config.items():
			app.config[key] = value

	plugin.initialize()
	return plugin
