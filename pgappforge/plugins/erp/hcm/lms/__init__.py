from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

from .events import (
	CertificateIssuedEvent,
	CourseCompletedEvent,
	CoursePublishedEvent,
	EnrollmentCreatedEvent,
	LessonCompletedEvent,
	MandatoryTrainingOverdueEvent,
)
from .models import (
	LmsCertificate,
	LmsCourse,
	LmsEnrollment,
	LmsLesson,
	LmsProgress,
)
from .services import LmsService

__all__ = [
	"LmsPlugin",
	"create_plugin",
]

log = logging.getLogger(__name__)

_LMS_PERMISSIONS = [
	"can_list_courses",
	"can_create_course",
	"can_edit_course",
	"can_delete_course",
	"can_publish_course",
	"can_list_enrollments",
	"can_create_enrollment",
	"can_withdraw_enrollment",
	"can_view_progress",
	"can_complete_lesson",
	"can_list_certificates",
	"can_issue_certificate",
	"can_view_analytics",
	"can_check_compliance",
]

assert len(_LMS_PERMISSIONS) == 14, "Expected exactly 14 LMS permissions"


class LmsPlugin(BasePlugin):
	"""Learning Management System plugin for the HCM domain."""

	name = "lms"
	domain = "hcm"
	depends_on = ["foundation"]

	metadata: dict[str, Any] = {
		"version": "1.0.0",
		"tags": ["erp", "hcm", "lms", "training", "learning"],
		"description": (
			"Full LMS: courses, lessons, enrollments, progress tracking, "
			"certificates, mandatory compliance, and SCORM support."
		),
	}

	def __init__(self, appbuilder: Any, config: dict[str, Any] | None = None) -> None:
		super().__init__(appbuilder, config or {})
		self._service = LmsService()

	# ------------------------------------------------------------------
	# Plugin interface
	# ------------------------------------------------------------------

	def get_permissions(self) -> list[str]:
		return list(_LMS_PERMISSIONS)

	def get_events(self) -> list[type]:
		return [
			CoursePublishedEvent,
			EnrollmentCreatedEvent,
			LessonCompletedEvent,
			CourseCompletedEvent,
			CertificateIssuedEvent,
			MandatoryTrainingOverdueEvent,
		]

	def subscribe_to(self) -> list[str]:
		return [
			"hcm.employee.hired",
			"hcm.employee.role_changed",
		]

	def initialize(self) -> None:
		"""Set default config values and register the menu category."""
		defaults: dict[str, str] = {
			"LMS_MENU_CATEGORY": "Learning & Development",
			"LMS_DEFAULT_PASSING_SCORE": "70",
		}
		for key, value in defaults.items():
			if key not in self.config:
				self.config[key] = value

		if self.appbuilder and hasattr(self.appbuilder, "app"):
			app_config = self.appbuilder.app.config
			for key, value in defaults.items():
				app_config.setdefault(key, value)

		log.info("LmsPlugin initialized with config keys: %s", list(defaults.keys()))

	def register_models(self) -> list[type]:
		return [
			LmsCourse,
			LmsLesson,
			LmsEnrollment,
			LmsProgress,
			LmsCertificate,
		]

	def register_views(self) -> None:
		from pgappforge.plugins.erp.hcm.lms.views import (
			LmsCertificateView,
			LmsCourseView,
			LmsDashboardView,
			LmsEnrollmentView,
		)
		cat = self.config.get("LMS_MENU_CATEGORY", "Learning & Development")
		self.add_view(LmsDashboardView, "Course Catalog", icon="fa-tachometer", category=cat)
		self.add_view(LmsCourseView, "Courses", icon="fa-book", category=cat)
		self.add_view(LmsEnrollmentView, "Enrollments", icon="fa-user-graduate", category=cat)
		self.add_view(LmsCertificateView, "Certificates", icon="fa-certificate", category=cat)
		log.info("LmsPlugin: views registered under %r", cat)

	def setup_rules(self, session: Session) -> None:
		"""
		Create declarative rule-engine rulesets for LMS business constraints.

		Ruleset 1: lms.enrollment.no_duplicate_active
		  - Guard: employee must not have an active enrollment in the same course.

		Ruleset 2: lms.course.published_before_enroll
		  - Guard: course status must be PUBLISHED before allowing enrollment.
		"""
		try:
			from pgappforge.plugins.rules.engine import RuleEngine
			from pgappforge.plugins.rules.models import Rule, RuleSet

			engine = RuleEngine(session=session)

			# --- Ruleset 1: no duplicate active enrollment ---
			no_dup_rules = [
				Rule(
					name="lms.enrollment.no_duplicate_active.check",
					description=(
						"Reject enrollment if employee already has an active "
						"enrollment (ENROLLED or IN_PROGRESS) in the same course."
					),
					condition="enrollment.status in ('ENROLLED', 'IN_PROGRESS')",
					action="raise EnrollmentStateError('Active enrollment already exists')",
					priority=10,
					is_active=True,
				)
			]
			engine.upsert_ruleset(
				RuleSet(
					name="lms.enrollment.no_duplicate_active",
					description="Prevents duplicate active enrollments per employee per course",
					domain="hcm.lms",
					rules=no_dup_rules,
				),
				session=session,
			)

			# --- Ruleset 2: course must be published before enrollment ---
			pub_rules = [
				Rule(
					name="lms.course.published_before_enroll.check",
					description=(
						"Reject enrollment if the course is not in PUBLISHED status."
					),
					condition="course.status != 'PUBLISHED'",
					action="raise EnrollmentStateError('Course is not published')",
					priority=5,
					is_active=True,
				)
			]
			engine.upsert_ruleset(
				RuleSet(
					name="lms.course.published_before_enroll",
					description="Ensures only published courses accept enrollments",
					domain="hcm.lms",
					rules=pub_rules,
				),
				session=session,
			)

			session.flush()
			log.info("LmsPlugin: rule-engine rulesets registered")

		except ImportError:
			log.warning(
				"LmsPlugin.setup_rules: rules engine not available; skipping ruleset registration"
			)
		except Exception as exc:
			log.error("LmsPlugin.setup_rules failed: %s", exc, exc_info=True)
			raise

	# ------------------------------------------------------------------
	# Event handler stubs (called by the event bus on subscribed topics)
	# ------------------------------------------------------------------

	def handle_employee_hired(self, event: Any) -> None:
		"""
		When a new employee is hired, auto-enroll them in any mandatory
		courses that apply to their role. Requires a DB session from the caller.
		"""
		log.info(
			"LmsPlugin received hcm.employee.hired for employee_id=%s",
			getattr(event, "employee_id", "?"),
		)
		# Full implementation would look up mandatory courses matching the
		# employee's role and call LmsService.enroll_employee() for each.

	def handle_employee_role_changed(self, event: Any) -> None:
		"""
		When an employee's role changes, check whether they now fall under
		additional mandatory training obligations.
		"""
		log.info(
			"LmsPlugin received hcm.employee.role_changed for employee_id=%s",
			getattr(event, "employee_id", "?"),
		)
		# Full implementation would diff old vs new mandatory_roles sets
		# and enroll for newly required courses.


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_plugin(
	appbuilder: Any,
	config: dict[str, Any] | None = None,
) -> LmsPlugin:
	"""Instantiate and return the LmsPlugin."""
	plugin = LmsPlugin(appbuilder=appbuilder, config=config)
	plugin.initialize()
	return plugin
