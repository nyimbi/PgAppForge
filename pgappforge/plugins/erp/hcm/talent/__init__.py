"""
pgappforge/plugins/erp/hcm/talent/__init__.py

TalentPlugin — HCM Talent Management ERP plugin.

Full talent lifecycle:
  Requisition → Candidate → Application → Interview → Offer
  PerformanceReview (annual/mid-year/probation/360)
  TrainingCourse → TrainingEnrollment

Domain: hcm
Depends on: foundation

Events emitted:
  hcm.talent.requisition.approved
  hcm.talent.requisition.filled
  hcm.talent.application.stage_changed
  hcm.talent.offer.sent
  hcm.talent.offer.accepted
  hcm.talent.offer.declined
  hcm.talent.review.finalised
  hcm.talent.training.completed

Events consumed:
  hcm.employee.created        (auto-creates probation review)
  hcm.payroll.run.paid        (can trigger merit raise review window)

Usage
-----
Add to your app config::

    PGAPPFORGE_PLUGINS = [
        "pgappforge.plugins.erp.foundation",
        "pgappforge.plugins.erp.hcm.talent",
    ]

Or instantiate directly::

    from pgappforge.plugins.erp.hcm.talent import TalentPlugin
    plugin = TalentPlugin(appbuilder)
    plugin.activate()
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class TalentPlugin(BasePlugin):
	"""HCM Talent Management ERP plugin.

	Registers 8 view groups and 3 report endpoints.
	Pre-configures 5 Rules Engine rulesets on first run.
	"""

	name = "talent"
	domain = "hcm"
	depends_on: list[str] = ["foundation"]

	# ------------------------------------------------------------------
	# Metadata
	# ------------------------------------------------------------------

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="talent",
			version="1.0.0",
			description=(
				"HCM Talent Management — full talent lifecycle: requisition approval, "
				"candidate tracking, interview scheduling, offer management, "
				"performance reviews (ANNUAL/MID_YEAR/PROBATION/360), "
				"training course catalogue and enrollment."
			),
			author="PgAppForge Contributors",
			tags=["erp", "hcm", "talent", "recruitment", "performance", "training"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_talent_requisition_list",
				"can_talent_requisition_write",
				"can_talent_requisition_approve",
				"can_talent_candidate_list",
				"can_talent_candidate_write",
				"can_talent_application_list",
				"can_talent_application_write",
				"can_talent_application_advance",
				"can_talent_interview_list",
				"can_talent_interview_write",
				"can_talent_interview_complete",
				"can_talent_offer_list",
				"can_talent_offer_write",
				"can_talent_offer_approve",
				"can_talent_review_list",
				"can_talent_review_write",
				"can_talent_review_finalise",
				"can_talent_training_list",
				"can_talent_training_write",
				"can_talent_reports",
			],
			safe_mode_compatible=True,
		)

	# ------------------------------------------------------------------
	# get_events / subscribe_to
	# ------------------------------------------------------------------

	def get_events(self) -> list[str]:
		return [
			"hcm.talent.requisition.approved",
			"hcm.talent.requisition.filled",
			"hcm.talent.application.stage_changed",
			"hcm.talent.offer.sent",
			"hcm.talent.offer.accepted",
			"hcm.talent.offer.declined",
			"hcm.talent.review.finalised",
			"hcm.talent.training.completed",
		]

	def subscribe_to(self) -> list[str]:
		return [
			"hcm.employee.created",
			"hcm.payroll.run.paid",
		]

	# ------------------------------------------------------------------
	# Lifecycle
	# ------------------------------------------------------------------

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"TALENT_MENU_CATEGORY": "Talent",
			"TALENT_DEFAULT_CURRENCY": "USD",
			"TALENT_OFFER_EXPIRY_DAYS": 14,
			"TALENT_INTERVIEW_DEFAULT_DURATION_MINUTES": 60,
		}
		self.config = {**defaults, **self.config}
		log.info("TalentPlugin initialised (config keys: %s)", list(self.config))

	def register_views(self) -> None:
		from pgappforge.plugins.erp.hcm.talent.views import (
			ApplicationView,
			CandidateView,
			InterviewView,
			OfferView,
			PerformanceReviewView,
			RequisitionView,
			TalentReportView,
			TrainingView,
		)

		cat = self.config.get("TALENT_MENU_CATEGORY", "Talent")

		self.add_view(RequisitionView, "Requisitions", icon="fa-clipboard", category=cat)
		self.add_view(CandidateView, "Candidates", icon="fa-users", category=cat)
		self.add_view(ApplicationView, "Applications", icon="fa-inbox", category=cat)
		self.add_view(InterviewView, "Interviews", icon="fa-comments", category=cat)
		self.add_view(OfferView, "Offers", icon="fa-handshake-o", category=cat)
		self.add_view(PerformanceReviewView, "Performance Reviews", icon="fa-star", category=cat)
		self.add_view(TrainingView, "Training", icon="fa-graduation-cap", category=cat)
		self.add_view(TalentReportView, "Talent Reports", icon="fa-bar-chart", category=cat)

		log.info("TalentPlugin: views registered under category %r", cat)

	def register_models(self) -> list:
		from pgappforge.plugins.erp.hcm.talent.models import (
			Application,
			Candidate,
			CareerPath,
			Certification,
			Competency,
			CompetencyProfile,
			Goal,
			Interview,
			InterviewDebrief,
			NineBoxPlacement,
			Offer,
			TalentOnboardingPlan,
			OnboardingTask,
			PerformanceCycle,
			PerformanceReview,
			PIP,
			PIPCheckin,
			Requisition,
			ReviewParticipant,
			SuccessionPlan,
			SuccessorCandidate,
			Survey,
			SurveyQuestion,
			TalentSurveyResponse,
			TrainingCourse,
			TrainingEnrollment,
		)
		return [
			Requisition,
			Candidate,
			Application,
			Interview,
			InterviewDebrief,
			Offer,
			PerformanceReview,
			PerformanceCycle,
			ReviewParticipant,
			Goal,
			PIP,
			PIPCheckin,
			SuccessionPlan,
			SuccessorCandidate,
			NineBoxPlacement,
			Competency,
			CompetencyProfile,
			CareerPath,
			Survey,
			SurveyQuestion,
			TalentSurveyResponse,
			Certification,
			TrainingCourse,
			TrainingEnrollment,
			TalentOnboardingPlan,
			OnboardingTask,
		]

	# ------------------------------------------------------------------
	# Rules Engine pre-configuration
	# ------------------------------------------------------------------

	@staticmethod
	def setup_rules(session: Any) -> None:
		"""Pre-configure 5 Rules Engine rulesets for HCM Talent domain.

		Idempotent — skips rulesets that already exist.
		"""
		try:
			from pgappforge.plugins.rules.models import Rule, RuleSet
		except ImportError:
			log.debug("TalentPlugin.setup_rules: rules plugin not available, skipping")
			return

		import sqlalchemy as sa

		RULESETS = [
			{
				"name": "talent.requisition.salary_range_valid",
				"description": "salary_range_max must exceed salary_range_min",
				"model_name": "Requisition",
				"stop_on_match": True,
				"rules": [
					{
						"name": "require_valid_salary_range",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "salary_range_min_cents", "op": "gt", "value": 0},
							{"field": "salary_range_max_cents", "op": "lte", "value": "__salary_range_min_cents__"},
						],
						"actions_json": [
							{"type": "raise_error",
							 "message": "salary_range_max_cents must be greater than salary_range_min_cents"}
						],
					},
				],
			},
			{
				"name": "talent.application.require_posted_requisition",
				"description": "Applications only accepted for POSTED or IN_PROGRESS requisitions",
				"model_name": "Application",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_closed_requisition_application",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "requisition.status", "op": "not_in",
							 "value": ["POSTED", "IN_PROGRESS"]},
						],
						"actions_json": [
							{"type": "raise_error",
							 "message": "Cannot apply to a requisition that is not POSTED or IN_PROGRESS"}
						],
					},
				],
			},
			{
				"name": "talent.offer.positive_salary",
				"description": "Offer base_salary_cents must be positive",
				"model_name": "Offer",
				"stop_on_match": True,
				"rules": [
					{
						"name": "require_positive_offer_salary",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "base_salary_cents", "op": "lte", "value": 0},
						],
						"actions_json": [
							{"type": "raise_error",
							 "message": "Offer base_salary_cents must be greater than zero"}
						],
					},
				],
			},
			{
				"name": "talent.offer.expiry_after_start",
				"description": "Offer expiry_date must be before start_date",
				"model_name": "Offer",
				"stop_on_match": True,
				"rules": [
					{
						"name": "require_expiry_before_start",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "expiry_date", "op": "gte", "value": "__start_date__"},
						],
						"actions_json": [
							{"type": "raise_error",
							 "message": "Offer expiry_date must be before start_date"}
						],
					},
				],
			},
			{
				"name": "talent.review.rating_range",
				"description": "Performance review overall_rating must be between 1.0 and 5.0",
				"model_name": "PerformanceReview",
				"stop_on_match": True,
				"rules": [
					{
						"name": "validate_rating_range",
						"trigger_event": "on_before_update",
						"conditions_json": [
							{"field": "overall_rating", "op": "not_null", "value": None},
							{"field": "overall_rating", "op": "not_between", "value": [1.0, 5.0]},
						],
						"actions_json": [
							{"type": "raise_error",
							 "message": "overall_rating must be between 1.0 and 5.0"}
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
		log.info("TalentPlugin.setup_rules: %d rulesets configured", len(RULESETS))


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_plugin(
	appbuilder: Any,
	config: dict[str, Any] | None = None,
) -> TalentPlugin:
	return TalentPlugin(appbuilder, config=config or {})


# ---------------------------------------------------------------------------
# Public re-exports
# ---------------------------------------------------------------------------

from pgappforge.plugins.erp.hcm.talent.models import (  # noqa: E402
	Application,
	Candidate,
	CareerPath,
	Certification,
	Competency,
	CompetencyProfile,
	Goal,
	Interview,
	InterviewDebrief,
	NineBoxPlacement,
	Offer,
	TalentOnboardingPlan,
	OnboardingTask,
	PerformanceCycle,
	PerformanceReview,
	PIP,
	PIPCheckin,
	Requisition,
	ReviewParticipant,
	SuccessionPlan,
	SuccessorCandidate,
	Survey,
	SurveyQuestion,
	TalentSurveyResponse,
	TrainingCourse,
	TrainingEnrollment,
)
from pgappforge.plugins.erp.hcm.talent.events import (  # noqa: E402
	ApplicationStageChangedEvent,
	OfferAcceptedEvent,
	OfferDeclinedEvent,
	OfferSentEvent,
	PerformanceReviewFinalisedEvent,
	RequisitionApprovedEvent,
	RequisitionFilledEvent,
	TrainingCompletedEvent,
)
from pgappforge.plugins.erp.hcm.talent.services import (  # noqa: E402
	TalentService,
	TalentServiceError,
	RequisitionNotFoundError,
	ApplicationNotFoundError,
	OfferNotFoundError,
	ReviewNotFoundError,
	EnrollmentNotFoundError,
	TalentStateError,
	TalentValidationError,
	GoalNotFoundError,
	PIPNotFoundError,
	SuccessionPlanNotFoundError,
	CycleNotFoundError,
)

__all__ = [
	# plugin
	"TalentPlugin",
	"create_plugin",
	# models — original
	"Requisition",
	"Candidate",
	"Application",
	"Interview",
	"Offer",
	"PerformanceReview",
	"TrainingCourse",
	"TrainingEnrollment",
	# models — OKR / Goals
	"Goal",
	# models — 360 appraisal
	"PerformanceCycle",
	"ReviewParticipant",
	# models — PIP
	"PIP",
	"PIPCheckin",
	# models — Succession
	"SuccessionPlan",
	"SuccessorCandidate",
	# models — HiPo
	"NineBoxPlacement",
	# models — Competency framework
	"Competency",
	"CompetencyProfile",
	# models — Career pathing
	"CareerPath",
	# models — Surveys
	"Survey",
	"SurveyQuestion",
	"TalentSurveyResponse",
	# models — L&D certifications
	"Certification",
	# models — Onboarding
	"TalentOnboardingPlan",
	"OnboardingTask",
	# models — Interview debrief
	"InterviewDebrief",
	# events
	"RequisitionApprovedEvent",
	"RequisitionFilledEvent",
	"ApplicationStageChangedEvent",
	"OfferSentEvent",
	"OfferAcceptedEvent",
	"OfferDeclinedEvent",
	"PerformanceReviewFinalisedEvent",
	"TrainingCompletedEvent",
	# services
	"TalentService",
	"TalentServiceError",
	"RequisitionNotFoundError",
	"ApplicationNotFoundError",
	"OfferNotFoundError",
	"ReviewNotFoundError",
	"EnrollmentNotFoundError",
	"TalentStateError",
	"TalentValidationError",
	"GoalNotFoundError",
	"PIPNotFoundError",
	"SuccessionPlanNotFoundError",
	"CycleNotFoundError",
]
