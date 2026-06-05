"""
pgappforge/plugins/erp/industry/life_sciences/__init__.py

LifeSciencesPlugin — Life Sciences Cloud ERP plugin.

Provides:
  - ClinicalTrial         (protocol, phases, arms, endpoints)
  - TrialSubject          (enrollment, randomization, arm assignment; GxP IMMUTABLE once signed)
  - TrialEvent            (AE/SAE/DOSING/VISIT/LAB; GxP IMMUTABLE — corrections are new rows)
  - RegulatorySubmission  (IND/NDA/BLA/MAA/CTA; IMMUTABLE once APPROVED)

Business rules enforced:
  - TrialEvent rows are NEVER updated (GxP audit trail)
  - RegulatorySubmission rows are IMMUTABLE once status=APPROVED
  - SAE events auto-trigger regulatory authority notification
  - Arm randomization uses permuted block design
  - grc.controls.test.failed subscription triggers audit for active clinical studies

Events emitted:
  ls.trial.enrolled
  ls.adverse_event.reported
  ls.submission.filed
  ls.approval.received
  ls.trial.completed

Events consumed:
  grc.controls.test.failed  (triggers audit for clinical studies)

Usage
-----
    PGAPPFORGE_PLUGINS = [
        "pgappforge.plugins.erp.foundation",
        "pgappforge.plugins.erp.industry.life_sciences",
    ]
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class LifeSciencesPlugin(BasePlugin):
	"""Life Sciences Cloud ERP plugin.

	Class-level routing metadata:
	    name       = "life_sciences"
	    domain     = "industry"
	    depends_on = ["foundation", "grc.controls", "grc.privacy"]
	"""

	name = "life_sciences"
	domain = "industry"
	depends_on: list[str] = ["foundation", "grc.controls", "grc.privacy"]

	# ------------------------------------------------------------------
	# BasePlugin.metadata
	# ------------------------------------------------------------------

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="life_sciences",
			version="1.0.0",
			description=(
				"Life Sciences Cloud — GxP-compliant clinical trial management, "
				"subject enrollment with permuted-block randomization, adverse event "
				"(AE/SAE) reporting, pharmacovigilance signal detection, and "
				"multi-authority regulatory submission tracking (FDA/EMA/MHRA/PMDA)."
			),
			author="PgAppForge Contributors",
			tags=["erp", "industry", "life-sciences", "clinical-trials", "gxp", "pharmacovigilance"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_ls_trial_read",
				"can_ls_trial_write",
				"can_ls_trial_approve",
				"can_ls_subject_read",
				"can_ls_subject_write",
				"can_ls_subject_pii_read",   # national_id and sensitive demographics
				"can_ls_event_read",
				"can_ls_event_write",
				"can_ls_sae_report",
				"can_ls_submission_read",
				"can_ls_submission_write",
				"can_ls_submission_approve",
				"can_ls_safety_dashboard",
				"can_ls_reports",
			],
			safe_mode_compatible=True,
		)

	# ------------------------------------------------------------------
	# ERP plugin contract
	# ------------------------------------------------------------------

	def get_events(self) -> list[str]:
		"""Events this plugin emits."""
		return [
			"ls.trial.enrolled",
			"ls.adverse_event.reported",
			"ls.submission.filed",
			"ls.approval.received",
			"ls.trial.completed",
			# canonical event names from events.py
			"life_sciences.trial.subject_enrolled",
			"life_sciences.trial.sae_reported",
			"life_sciences.submission.approved",
			"life_sciences.trial.completed",
		]

	def subscribe_to(self) -> list[str]:
		"""Events this plugin consumes.

		grc.controls.test.failed triggers a GxP audit review for any
		active clinical study that references the failed control.
		"""
		return [
			"grc.controls.test.failed",
		]

	# ------------------------------------------------------------------
	# Lifecycle
	# ------------------------------------------------------------------

	def initialize(self) -> None:
		"""Merge config defaults."""
		defaults: dict[str, Any] = {
			"LS_MENU_CATEGORY": "Life Sciences",
			"LS_SAE_REPORTING_WINDOW_HOURS": 24,       # expedited SAE: 24h for fatal/life-threatening
			"LS_SAE_NON_FATAL_WINDOW_HOURS": 168,      # 7 days for non-fatal SAEs
			"LS_DEFAULT_RANDOMIZATION_RATIO": "1:1",
			"LS_SEED_RULES_ON_INIT": True,
		}
		self.config = {**defaults, **self.config}
		log.info("LifeSciencesPlugin initialised (config keys: %s)", list(self.config))

	def post_initialize(self) -> None:
		"""Seed rules after tables exist."""
		if self.config.get("LS_SEED_RULES_ON_INIT", True):
			self._try_setup_rules()

	def register_views(self) -> None:
		"""Register Life Sciences views under the configured menu category."""
		from pgappforge.plugins.erp.industry.life_sciences.views import (
			ClinicalTrialView,
			TrialSubjectView,
			TrialEventView,
			RegulatorySubmissionView,
			AdverseEventDashboardView,
		)

		cat = self.config.get("LS_MENU_CATEGORY", "Life Sciences")

		self.add_view(
			ClinicalTrialView,
			"Clinical Trials",
			icon="fa-flask",
			category=cat,
		)
		self.add_view(
			TrialSubjectView,
			"Trial Subjects",
			icon="fa-user",
			category=cat,
		)
		self.add_view(
			TrialEventView,
			"Trial Events",
			icon="fa-exclamation-triangle",
			category=cat,
		)
		self.add_view(
			RegulatorySubmissionView,
			"Regulatory Submissions",
			icon="fa-file-text-o",
			category=cat,
		)
		self.add_view(
			AdverseEventDashboardView,
			"Safety Dashboard",
			icon="fa-heartbeat",
			category=cat,
		)

		log.info("LifeSciencesPlugin: views registered under category %r", cat)

	def register_models(self) -> list:
		"""Model classes for Alembic autogenerate discovery."""
		from pgappforge.plugins.erp.industry.life_sciences.models import (
			ClinicalTrial,
			TrialSubject,
			TrialEvent,
			RegulatorySubmission,
		)
		return [ClinicalTrial, TrialSubject, TrialEvent, RegulatorySubmission]

	# ------------------------------------------------------------------
	# Rules Engine pre-configuration
	# ------------------------------------------------------------------

	@staticmethod
	def setup_rules(session: Any) -> None:
		"""Pre-configure domain rulesets for the Life Sciences plugin.

		Idempotent — skips rulesets that already exist.
		"""
		try:
			from pgappforge.plugins.rules.models import Rule, RuleSet
		except ImportError:
			log.debug("LifeSciencesPlugin.setup_rules: rules plugin not available, skipping")
			return

		import sqlalchemy as sa

		RULESETS = [
			{
				"name": "ls.subject.no_enroll_terminated_trial",
				"description": "Block enrollment into a TERMINATED or WITHDRAWN trial",
				"model_name": "TrialSubject",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_enroll_bad_trial_status",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "trial.status", "op": "in", "value": ["TERMINATED", "WITHDRAWN", "COMPLETED"]},
						],
						"actions_json": [
							{
								"type": "raise_error",
								"message": "Cannot enroll subject: trial status must be RECRUITING or ACTIVE.",
							}
						],
					},
				],
			},
			{
				"name": "ls.event.immutable_after_creation",
				"description": "TrialEvent rows must never be updated (GxP audit trail)",
				"model_name": "TrialEvent",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_event_update",
						"trigger_event": "on_before_update",
						"conditions_json": [
							{"field": "id", "op": "is_not", "value": None},
						],
						"actions_json": [
							{
								"type": "raise_error",
								"message": (
									"TrialEvent records are immutable (GxP). "
									"To correct, create a new CORRECTION event referencing the original."
								),
							}
						],
					},
				],
			},
			{
				"name": "ls.submission.immutable_after_approval",
				"description": "RegulatorySubmission is immutable once APPROVED",
				"model_name": "RegulatorySubmission",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_approved_submission_update",
						"trigger_event": "on_before_update",
						"conditions_json": [
							{"field": "status", "op": "eq", "value": "APPROVED"},
						],
						"actions_json": [
							{
								"type": "raise_error",
								"message": (
									"RegulatorySubmission is APPROVED and immutable. "
									"Create a variation or new submission for changes."
								),
							}
						],
					},
				],
			},
			{
				"name": "ls.trial.enrollment_cap",
				"description": "Block enrollment if enrolled_count >= enrollment_target",
				"model_name": "TrialSubject",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_over_enrollment",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "trial.enrolled_count", "op": "gte", "value": "{{trial.enrollment_target}}"},
							{"field": "trial.enrollment_target", "op": "gt", "value": 0},
						],
						"actions_json": [
							{
								"type": "raise_error",
								"message": "Enrollment target reached. Cannot enroll additional subjects.",
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
		log.info(
			"LifeSciencesPlugin.setup_rules: %d rulesets configured", len(RULESETS)
		)

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
			log.warning(
				"LifeSciencesPlugin._try_setup_rules failed (non-fatal): %s", exc
			)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_plugin(
	appbuilder: Any,
	config: dict[str, Any] | None = None,
) -> LifeSciencesPlugin:
	return LifeSciencesPlugin(appbuilder, config=config or {})


# ---------------------------------------------------------------------------
# Public API re-exports
# ---------------------------------------------------------------------------

from pgappforge.plugins.erp.industry.life_sciences.models import (  # noqa: E402
	ClinicalTrial,
	TrialSubject,
	TrialEvent,
	RegulatorySubmission,
)
from pgappforge.plugins.erp.industry.life_sciences.events import (  # noqa: E402
	TrialSubjectEnrolledEvent,
	SAEReportedEvent,
	RegulatorySubmissionApprovedEvent,
	ClinicalTrialCompletedEvent,
)
from pgappforge.plugins.erp.industry.life_sciences.services import (  # noqa: E402
	LifeSciencesService,
	LifeSciencesError,
	TrialNotFoundError,
	SubjectNotFoundError,
	EligibilityError,
	DuplicateSubjectError,
	TrialStatusError,
	SubmissionNotFoundError,
)

__all__ = [
	# plugin
	"LifeSciencesPlugin",
	"create_plugin",
	# models
	"ClinicalTrial",
	"TrialSubject",
	"TrialEvent",
	"RegulatorySubmission",
	# events
	"TrialSubjectEnrolledEvent",
	"SAEReportedEvent",
	"RegulatorySubmissionApprovedEvent",
	"ClinicalTrialCompletedEvent",
	# services
	"LifeSciencesService",
	"LifeSciencesError",
	"TrialNotFoundError",
	"SubjectNotFoundError",
	"EligibilityError",
	"DuplicateSubjectError",
	"TrialStatusError",
	"SubmissionNotFoundError",
]
