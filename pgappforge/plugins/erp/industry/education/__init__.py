"""
pgappforge/plugins/erp/industry/education/__init__.py

EducationPlugin — Education Cloud ERP plugin.

Provides:
  - Student        (GPA tracking, enrollment status, advisor assignment)
  - Course         (catalogue, prerequisites, capacity management)
  - Enrollment     (student-course-term, grades, attendance)
  - Intervention   (early-alert, risk scoring, action plans)

Business rules enforced:
  - GPA computed as weighted average of grade_points × credits across COMPLETED enrollments
  - At-risk detection: GPA < threshold OR attendance_pct < threshold
  - Intervention triggers must resolve within configured SLA

Events emitted:
  edu.student.enrolled
  edu.student.at_risk
  edu.course.completed
  edu.intervention.triggered
  edu.grade.posted

Events consumed:
  hcm.talent.application.received  (staff hiring — pre-populate instructor shell)

Usage
-----
    PGAPPFORGE_PLUGINS = [
        "pgappforge.plugins.erp.foundation",
        "pgappforge.plugins.erp.industry.education",
    ]
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class EducationPlugin(BasePlugin):
	"""Education Cloud ERP plugin.

	Class-level routing metadata:
	    name       = "education"
	    domain     = "industry"
	    depends_on = ["foundation", "hcm.personnel"]
	"""

	name = "education"
	domain = "industry"
	depends_on: list[str] = ["foundation", "hcm.personnel"]

	# ------------------------------------------------------------------
	# BasePlugin.metadata
	# ------------------------------------------------------------------

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="education",
			version="1.0.0",
			description=(
				"Education Cloud — student lifecycle management, course catalogue, "
				"enrollment processing, GPA computation, early-alert interventions, "
				"and academic transcript generation."
			),
			author="PgAppForge Contributors",
			tags=["erp", "industry", "education", "student", "academic", "lms"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_edu_student_read",
				"can_edu_student_write",
				"can_edu_student_enroll",
				"can_edu_student_graduate",
				"can_edu_course_read",
				"can_edu_course_write",
				"can_edu_enrollment_read",
				"can_edu_enrollment_write",
				"can_edu_grade_post",
				"can_edu_intervention_read",
				"can_edu_intervention_write",
				"can_edu_intervention_resolve",
				"can_edu_transcript_generate",
				"can_edu_reports",
			],
			safe_mode_compatible=True,
		)

	# ------------------------------------------------------------------
	# ERP plugin contract
	# ------------------------------------------------------------------

	def get_events(self) -> list[str]:
		"""Events this plugin emits."""
		return [
			"edu.student.enrolled",
			"edu.student.at_risk",
			"edu.course.completed",
			"edu.intervention.triggered",
			"edu.grade.posted",
		]

	def subscribe_to(self) -> list[str]:
		"""Events this plugin consumes."""
		return [
			"hcm.talent.application.received",  # Pre-populate instructor shell on staff hire
		]

	# ------------------------------------------------------------------
	# Lifecycle
	# ------------------------------------------------------------------

	def initialize(self) -> None:
		"""Merge config defaults."""
		defaults: dict[str, Any] = {
			"EDUCATION_MENU_CATEGORY": "Education Cloud",
			"EDUCATION_SEED_RULES_ON_INIT": True,
			"EDUCATION_AT_RISK_GPA_THRESHOLD": "2.0",
			"EDUCATION_AT_RISK_ATTENDANCE_THRESHOLD": "75",
		}
		self.config = {**defaults, **self.config}
		log.info("EducationPlugin initialised (config keys: %s)", list(self.config))

	def post_initialize(self) -> None:
		"""Seed rules after tables exist."""
		if self.config.get("EDUCATION_SEED_RULES_ON_INIT", True):
			self._try_setup_rules()

	def register_views(self) -> None:
		"""Register Education views under the configured menu category."""
		from pgappforge.plugins.erp.industry.education.views import (
			AtRiskDashboardView,
			CourseView,
			EnrollmentView,
			InterventionView,
			StudentView,
		)

		cat = self.config.get("EDUCATION_MENU_CATEGORY", "Education Cloud")

		self.add_view(
			StudentView,
			"Students",
			icon="fa-graduation-cap",
			category=cat,
		)
		self.add_view(
			CourseView,
			"Courses",
			icon="fa-book",
			category=cat,
		)
		self.add_view(
			EnrollmentView,
			"Enrollments",
			icon="fa-list-alt",
			category=cat,
		)
		self.add_view(
			InterventionView,
			"Interventions",
			icon="fa-exclamation-triangle",
			category=cat,
		)
		self.add_view(
			AtRiskDashboardView,
			"At-Risk Dashboard",
			icon="fa-dashboard",
			category=cat,
		)

		log.info("EducationPlugin: views registered under category %r", cat)

	def register_models(self) -> list:
		"""Model classes for Alembic autogenerate discovery."""
		from pgappforge.plugins.erp.industry.education.models import (
			Course,
			Enrollment,
			Intervention,
			Student,
		)
		return [Student, Course, Enrollment, Intervention]

	# ------------------------------------------------------------------
	# Rules Engine pre-configuration
	# ------------------------------------------------------------------

	@staticmethod
	def setup_rules(session: Any) -> None:
		"""Pre-configure rulesets for Education domain rules.

		Idempotent — skips rulesets that already exist.
		"""
		try:
			from pgappforge.plugins.rules.models import Rule, RuleSet
		except ImportError:
			log.debug("EducationPlugin.setup_rules: rules plugin not available, skipping")
			return

		import sqlalchemy as sa

		RULESETS = [
			{
				"name": "education.enrollment.capacity_check",
				"description": "Block enrollment when course capacity is reached",
				"model_name": "Enrollment",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_over_capacity",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "course.capacity", "op": "is_not_null", "value": None},
							{"field": "course.current_enrollment", "op": "gte", "value": "{{course.capacity}}"},
						],
						"actions_json": [
							{
								"type": "raise_error",
								"message": (
									"Course has reached maximum enrollment capacity. "
									"Contact the registrar to request a capacity override."
								),
							}
						],
					},
				],
			},
			{
				"name": "education.enrollment.no_duplicate_term",
				"description": "Block re-enrolling in the same course in the same term",
				"model_name": "Enrollment",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_duplicate_enrollment",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{
								"field": "_duplicate_enrollment_exists",
								"op": "eq",
								"value": True,
							},
						],
						"actions_json": [
							{
								"type": "raise_error",
								"message": (
									"Student is already enrolled in this course for the specified term."
								),
							}
						],
					},
				],
			},
			{
				"name": "education.grade.immutable_after_submit",
				"description": "Warn when a submitted grade is being changed",
				"model_name": "Enrollment",
				"stop_on_match": False,
				"rules": [
					{
						"name": "warn_grade_mutation",
						"trigger_event": "on_before_update",
						"conditions_json": [
							{"field": "_old_grade_submitted_at", "op": "is_not_null", "value": None},
							{"field": "_changed_fields", "op": "contains", "value": "grade"},
						],
						"actions_json": [
							{
								"type": "log",
								"level": "WARNING",
								"message": (
									"Enrollment {{id}}: grade modified after submission — "
									"ensure grade change form has been approved."
								),
							}
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
		log.info("EducationPlugin.setup_rules: %d rulesets configured", len(RULESETS))

	# ------------------------------------------------------------------
	# Internal helpers
	# ------------------------------------------------------------------

	def _try_setup_rules(self) -> None:
		try:
			from flask import current_app
			ab = current_app.extensions.get("appbuilder")
			if ab is None:
				return
			session = ab.get_session
			self.setup_rules(session)
			session.commit()
		except RuntimeError:
			pass
		except Exception as exc:
			log.warning("EducationPlugin._try_setup_rules failed (non-fatal): %s", exc)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_plugin(
	appbuilder: Any,
	config: dict[str, Any] | None = None,
) -> EducationPlugin:
	return EducationPlugin(appbuilder, config=config or {})


# ---------------------------------------------------------------------------
# Public API re-exports
# ---------------------------------------------------------------------------

from pgappforge.plugins.erp.industry.education.models import (  # noqa: E402
	Course,
	Enrollment,
	Intervention,
	Student,
)
from pgappforge.plugins.erp.industry.education.events import (  # noqa: E402
	GradeSubmittedEvent,
	StudentAtRiskEvent,
	StudentEnrolledEvent,
	StudentGraduatedEvent,
)
from pgappforge.plugins.erp.industry.education.services import (  # noqa: E402
	EducationService,
	EducationServiceError,
	CourseNotFoundError,
	EnrollmentNotFoundError,
	StudentNotFoundError,
	DuplicateEnrollmentError,
	CourseAtCapacityError,
	GradeAlreadySubmittedError,
)

__all__ = [
	# plugin
	"EducationPlugin",
	"create_plugin",
	# models
	"Student",
	"Course",
	"Enrollment",
	"Intervention",
	# events
	"StudentEnrolledEvent",
	"StudentAtRiskEvent",
	"StudentGraduatedEvent",
	"GradeSubmittedEvent",
	# services
	"EducationService",
	"EducationServiceError",
	"StudentNotFoundError",
	"CourseNotFoundError",
	"EnrollmentNotFoundError",
	"DuplicateEnrollmentError",
	"CourseAtCapacityError",
	"GradeAlreadySubmittedError",
]
