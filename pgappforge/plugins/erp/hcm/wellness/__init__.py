from __future__ import annotations

import logging

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority
from pgappforge.plugins.erp.hcm.wellness.events import (
	EapReferralCreatedEvent,
	WellnessCheckInEvent,
	WellnessProgramEnrolledEvent,
	WellnessReportGeneratedEvent,
)
from pgappforge.plugins.erp.hcm.wellness.models import (
	EapReferral,
	WellnessCheckIn,
	WellnessEnrollment,
	WellnessProgram,
)
from pgappforge.plugins.erp.hcm.wellness.services import (
	WellnessNotFoundError,
	WellnessService,
	WellnessServiceError,
	WellnessStateError,
)

__all__ = [
	# Plugin entry point
	"WellnessPlugin",
	"create_plugin",
	# Models
	"WellnessProgram",
	"WellnessEnrollment",
	"WellnessCheckIn",
	"EapReferral",
	# Events
	"WellnessProgramEnrolledEvent",
	"WellnessCheckInEvent",
	"EapReferralCreatedEvent",
	"WellnessReportGeneratedEvent",
	# Service layer
	"WellnessService",
	"WellnessServiceError",
	"WellnessNotFoundError",
	"WellnessStateError",
]

_log = logging.getLogger(__name__)


class WellnessPlugin(BasePlugin):
	"""HCM Employee Wellness plugin.

	Covers wellness programs, enrollment tracking, daily check-ins with
	automatic risk flagging, EAP referrals, and org-level reporting.
	"""

	name = "wellness"
	domain = "hcm"
	depends_on = ["foundation"]

	metadata = {
		"version": "1.0.0",
		"description": (
			"HCM Employee Wellness — program management, enrollment, daily "
			"wellbeing check-ins with burnout/stress detection, EAP referrals, "
			"and aggregate org wellness reporting"
		),
		"tags": ["erp", "hcm", "wellness", "eap", "mental-health"],
	}

	permissions = [
		"can_list_wellness_programs",
		"can_write_wellness_programs",
		"can_list_wellness_enrollments",
		"can_write_wellness_enrollments",
		"can_list_wellness_checkins",
		"can_write_wellness_checkins",
		"can_list_eap_referrals",
		"can_write_eap_referrals",
		"can_view_wellness_reports",
		"can_export_wellness_reports",
	]

	def get_events(self) -> list[str]:
		return [
			"hcm.wellness.enrolled",
			"hcm.wellness.checkin",
			"hcm.wellness.eap.referral",
			"hcm.wellness.report.generated",
		]

	def subscribe_to(self) -> list[str]:
		return [
			"hcm.employee.terminated",
			"hcm.employee.hired",
		]

	def initialize(self) -> None:
		"""Set config defaults and wire event subscriptions."""
		defaults = {
			"WELLNESS_MENU_CATEGORY": "Wellness",
			"WELLNESS_BURNOUT_SCORE_THRESHOLD": 3,
			"WELLNESS_HIGH_STRESS_THRESHOLD": 8,
			"WELLNESS_BURNOUT_ENERGY_THRESHOLD": 2,
		}
		if self.appbuilder is not None:
			app = self.appbuilder.get_app()
			for key, value in defaults.items():
				app.config.setdefault(key, value)

		try:
			subscribe("hcm.employee.terminated", self._on_employee_terminated)
			subscribe("hcm.employee.hired", self._on_employee_hired)
			_log.info("WellnessPlugin: event subscriptions registered")
		except Exception:  # noqa: BLE001
			_log.debug("WellnessPlugin: event bus not available; subscriptions skipped")

		_log.info("WellnessPlugin initialized")

	def register_models(self) -> list:
		return [
			WellnessProgram,
			WellnessEnrollment,
			WellnessCheckIn,
			EapReferral,
		]

	def register_views(self) -> None:
		from pgappforge.plugins.erp.hcm.wellness.views import (
			WellnessCheckInView,
			WellnessEnrollmentView,
			WellnessProgramView,
		)
		cat = self.config.get("WELLNESS_MENU_CATEGORY", "Wellness") if self.appbuilder is None else \
			self.appbuilder.get_app().config.get("WELLNESS_MENU_CATEGORY", "Wellness")
		self.add_view(WellnessProgramView, "Programs", icon="fa-heartbeat", category=cat)
		self.add_view(WellnessEnrollmentView, "Enrollments", icon="fa-user-plus", category=cat)
		self.add_view(WellnessCheckInView, "Check-Ins", icon="fa-clipboard-check", category=cat)
		_log.info("WellnessPlugin: views registered under %r", cat)

	def setup_rules(self, session: object) -> None:  # type: ignore[override]
		"""Install domain-level validation rulesets via the Rules Engine.

		Three rulesets are registered:
		1. wellness.program.active_required_for_enrollment — enrollments require ACTIVE program.
		2. wellness.enrollment.no_duplicate_active — one active enrollment per employee/program.
		3. wellness.checkin.score_range — wellbeing scores must be 1-10.
		"""
		try:
			from pgappforge.plugins.rules.engine import RulesEngine

			engine = RulesEngine(session=session)

			engine.register_ruleset(
				name="wellness.program.active_required_for_enrollment",
				model="WellnessEnrollment",
				rules=[
					{
						"field": "program.status",
						"op": "neq",
						"value": "ACTIVE",
					}
				],
				action="raise_error",
				message=(
					"Wellness enrollments can only be created for ACTIVE programs."
				),
			)

			engine.register_ruleset(
				name="wellness.enrollment.no_duplicate_active",
				model="WellnessEnrollment",
				rules=[
					{
						"field": "status",
						"op": "eq",
						"value": "ACTIVE",
					}
				],
				action="raise_error",
				message=(
					"An ACTIVE enrollment already exists for this employee and program. "
					"Complete or withdraw the existing enrollment first."
				),
			)

			engine.register_ruleset(
				name="wellness.checkin.score_range",
				model="WellnessCheckIn",
				rules=[
					{
						"field": "wellbeing_score",
						"op": "range",
						"value": [1, 10],
					}
				],
				action="raise_error",
				message=(
					"Wellbeing score must be an integer between 1 and 10 inclusive."
				),
			)

			_log.info("WellnessPlugin: 3 rulesets registered via RulesEngine")

		except Exception as exc:  # noqa: BLE001
			_log.warning("WellnessPlugin.setup_rules: RulesEngine unavailable — %s", exc)

	# ------------------------------------------------------------------
	# Internal event handlers
	# ------------------------------------------------------------------

	def _on_employee_terminated(self, event: object) -> None:
		"""Withdraw all ACTIVE wellness enrollments for a terminated employee."""
		try:
			from sqlalchemy import select

			from pgappforge.extensions import db

			employee_id: str = getattr(event, "employee_id", "")
			tenant_id: str = getattr(event, "tenant_id", "")

			if not (employee_id and tenant_id):
				return

			with db.session() as session:
				active = session.execute(
					select(WellnessEnrollment).where(
						WellnessEnrollment.tenant_id == tenant_id,
						WellnessEnrollment.employee_id == employee_id,
						WellnessEnrollment.status == "ACTIVE",
					)
				).scalars().all()

				from pgappforge.plugins.erp.hcm.wellness.services import _now_utc
				now = _now_utc()
				for enrollment in active:
					enrollment.status = "WITHDRAWN"
					enrollment.completed_at = now

				session.commit()
				_log.info(
					"Auto-withdrew %d wellness enrollments for employee=%s",
					len(active), employee_id,
				)
		except Exception as exc:  # noqa: BLE001
			_log.error("_on_employee_terminated wellness handler failed: %s", exc)

	def _on_employee_hired(self, event: object) -> None:
		"""Auto-enroll new hires in mandatory (non-voluntary) wellness programs."""
		try:
			from sqlalchemy import select

			from pgappforge.extensions import db

			employee_id: str = getattr(event, "employee_id", "")
			tenant_id: str = getattr(event, "tenant_id", "")

			if not (employee_id and tenant_id):
				return

			svc = WellnessService()
			with db.session() as session:
				mandatory_programs = session.execute(
					select(WellnessProgram).where(
						WellnessProgram.tenant_id == tenant_id,
						WellnessProgram.status == "ACTIVE",
						WellnessProgram.is_voluntary.is_(False),
					)
				).scalars().all()

				enrolled_count = 0
				for program in mandatory_programs:
					try:
						svc.enroll_employee(employee_id, program.id, tenant_id, session)
						enrolled_count += 1
					except Exception as inner_exc:  # noqa: BLE001
						_log.debug(
							"Could not auto-enroll employee=%s in program=%s: %s",
							employee_id, program.id, inner_exc,
						)

				if enrolled_count:
					session.commit()
					_log.info(
						"Auto-enrolled employee=%s in %d mandatory wellness program(s)",
						employee_id, enrolled_count,
					)
		except Exception as exc:  # noqa: BLE001
			_log.error("_on_employee_hired wellness handler failed: %s", exc)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def create_plugin(appbuilder: object, config: dict | None = None) -> WellnessPlugin:
	"""Instantiate and return the WellnessPlugin."""
	plugin = WellnessPlugin(appbuilder=appbuilder)

	if config and appbuilder is not None:
		app = appbuilder.get_app()  # type: ignore[union-attr]
		for key, value in config.items():
			app.config[key] = value

	plugin.initialize()
	return plugin
