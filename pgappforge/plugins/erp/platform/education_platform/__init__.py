"""
pgappforge/plugins/erp/platform/education_platform/__init__.py

Education Platform plugin — LMS/tools integration layer.

NOT the Education industry plugin (student records).
Covers: LTI 1.3, SCORM, xAPI, AICC tool registration; learning object
catalogue; learning paths; learner activity (xAPI event log); verifiable
credentials (W3C VC / IMS Open Badges).

Events emitted:
  education.lms_tool.registered
  education.learner_activity.started / completed
  education.credential.issued / revoked
  education.learning_path.assigned

Events consumed:
  party.created  — pre-populate learner roster
  identity.role.assigned — trigger mandatory path assignment

Usage
-----
    PGAPPFORGE_PLUGINS = ["pgappforge.plugins.erp.platform.education_platform"]
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class EducationPlatformPlugin(BasePlugin):
	"""Education Platform plugin — LMS/tools integration and credentialing."""

	name = "platform.education_platform"
	domain = "platform"
	depends_on: list[str] = ["foundation"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="platform.education_platform",
			version="1.0.0",
			description=(
				"Education Platform — LTI 1.3 / SCORM / xAPI / AICC tool integration, "
				"learning object catalogue, learning paths, xAPI learner activity log, "
				"and W3C Verifiable Credentials / IMS Open Badges issuance."
			),
			author="PgAppForge Contributors",
			tags=[
				"education", "lms", "lti", "xapi", "scorm", "credentials",
				"open-badges", "elearning", "edtech",
			],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_edu_tools_read",
				"can_edu_tools_write",
				"can_edu_objects_read",
				"can_edu_objects_write",
				"can_edu_paths_read",
				"can_edu_paths_write",
				"can_edu_activity_read",
				"can_edu_activity_write",
				"can_edu_credentials_read",
				"can_edu_credentials_issue",
				"can_edu_lti_launch",
			],
			safe_mode_compatible=True,
		)

	def get_events(self) -> list[str]:
		return [
			"education.lms_tool.registered",
			"education.learner_activity.started",
			"education.learner_activity.completed",
			"education.credential.issued",
			"education.credential.revoked",
			"education.learning_path.assigned",
		]

	def subscribe_to(self) -> list[str]:
		return [
			"party.created",
			"identity.role.assigned",
		]

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"EDU_MENU_CATEGORY": "Education",
			"EDU_LTI_PLATFORM_ISS": "",
			"EDU_CREDENTIAL_BASE_URL": "/credentials/verify",
			"EDU_RECOMMENDATION_LIMIT": 5,
		}
		self.config = {**defaults, **self.config}
		log.info("EducationPlatformPlugin initialised")

	def register_views(self) -> None:
		from pgappforge.plugins.erp.platform.education_platform.views import (
			LMSToolView,
			LearningObjectView,
			LearningPathView,
			LearnerActivityView,
			CredentialView,
			LTILaunchView,
			RecommendationView,
		)
		cat = self.config.get("EDU_MENU_CATEGORY", "Education")
		self.add_view(LMSToolView, "LMS Tools", icon="fa-plug", category=cat)
		self.add_view(LearningObjectView, "Learning Objects", icon="fa-book", category=cat)
		self.add_view(LearningPathView, "Learning Paths", icon="fa-road", category=cat)
		self.add_view(CredentialView, "Credentials", icon="fa-certificate", category=cat)
		self.add_view(RecommendationView, "Recommendations", icon="fa-lightbulb-o", category=cat)
		self.add_view_no_menu(LearnerActivityView)
		self.add_view_no_menu(LTILaunchView)
		log.info("EducationPlatformPlugin: views registered under %r", cat)

	def register_models(self) -> list:
		from pgappforge.plugins.erp.platform.education_platform.models import (
			LMSTool,
			LearningObject,
			LearningPath,
			PathItem,
			LearnerActivity,
			VerifiableCredential,
			EduIssuedCredential,
		)
		return [
			LMSTool,
			LearningObject,
			LearningPath,
			PathItem,
			LearnerActivity,
			VerifiableCredential,
			EduIssuedCredential,
		]

	@staticmethod
	def setup_rules(session: Any) -> None:
		"""Pre-configure validation rulesets for the Education Platform domain."""
		try:
			from pgappforge.plugins.rules.models import Rule, RuleSet
		except ImportError:
			return

		import sqlalchemy as sa

		RULESETS = [
			{
				"name": "edu.lms_tool.type_valid",
				"description": "tool_type must be LTI_1P3|SCORM|XAPI|AICC",
				"model_name": "LMSTool",
				"stop_on_match": True,
				"rules": [
					{
						"name": "validate_tool_type",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{
								"field": "tool_type",
								"op": "not_in",
								"value": ["LTI_1P3", "SCORM", "XAPI", "AICC"],
							}
						],
						"actions_json": [
							{
								"type": "raise_error",
								"message": "tool_type must be LTI_1P3, SCORM, XAPI, or AICC",
							}
						],
					}
				],
			},
			{
				"name": "edu.learning_object.type_valid",
				"description": "lo_type must be MODULE|QUIZ|ASSIGNMENT|VIDEO|READING|SIMULATION",
				"model_name": "LearningObject",
				"stop_on_match": True,
				"rules": [
					{
						"name": "validate_lo_type",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{
								"field": "lo_type",
								"op": "not_in",
								"value": [
									"MODULE", "QUIZ", "ASSIGNMENT",
									"VIDEO", "READING", "SIMULATION",
								],
							}
						],
						"actions_json": [
							{
								"type": "raise_error",
								"message": (
									"lo_type must be MODULE, QUIZ, ASSIGNMENT, "
									"VIDEO, READING, or SIMULATION"
								),
							}
						],
					}
				],
			},
			{
				"name": "edu.learner_activity.progress_range",
				"description": "progress_pct must be 0–100",
				"model_name": "LearnerActivity",
				"stop_on_match": True,
				"rules": [
					{
						"name": "validate_progress_pct",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{
								"field": "progress_pct",
								"op": "gt",
								"value": 100,
							}
						],
						"actions_json": [
							{
								"type": "raise_error",
								"message": "progress_pct must be between 0 and 100",
							}
						],
					}
				],
			},
			{
				"name": "edu.credential.type_valid",
				"description": "credential_type must be CERTIFICATE|BADGE|DEGREE|LICENSE",
				"model_name": "VerifiableCredential",
				"stop_on_match": True,
				"rules": [
					{
						"name": "validate_credential_type",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{
								"field": "credential_type",
								"op": "not_in",
								"value": ["CERTIFICATE", "BADGE", "DEGREE", "LICENSE"],
							}
						],
						"actions_json": [
							{
								"type": "raise_error",
								"message": (
									"credential_type must be CERTIFICATE, BADGE, DEGREE, or LICENSE"
								),
							}
						],
					}
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
		log.info(
			"EducationPlatformPlugin.setup_rules: %d rulesets configured",
			len(RULESETS),
		)


def create_plugin(
	appbuilder: Any,
	config: dict[str, Any] | None = None,
) -> EducationPlatformPlugin:
	return EducationPlatformPlugin(appbuilder, config=config or {})


from pgappforge.plugins.erp.platform.education_platform.models import (  # noqa: E402
	LMSTool,
	LearningObject,
	LearningPath,
	PathItem,
	LearnerActivity,
	VerifiableCredential,
	EduIssuedCredential,
)
from pgappforge.plugins.erp.platform.education_platform.services import (  # noqa: E402
	EducationPlatformService,
	EducationPlatformError,
	LMSToolNotFoundError,
	LearningObjectNotFoundError,
	LearningPathNotFoundError,
	CredentialNotFoundError,
	CredentialExpiredError,
	CredentialRevokedError,
)

__all__ = [
	"EducationPlatformPlugin",
	"create_plugin",
	# models
	"LMSTool",
	"LearningObject",
	"LearningPath",
	"PathItem",
	"LearnerActivity",
	"VerifiableCredential",
	"EduIssuedCredential",
	# service
	"EducationPlatformService",
	"EducationPlatformError",
	"LMSToolNotFoundError",
	"LearningObjectNotFoundError",
	"LearningPathNotFoundError",
	"CredentialNotFoundError",
	"CredentialExpiredError",
	"CredentialRevokedError",
]
