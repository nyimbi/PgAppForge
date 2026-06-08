from __future__ import annotations

import logging

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority
from pgappforge.plugins.erp.hcm.referral.events import (
	ReferralExpiredEvent,
	ReferralHiredEvent,
	ReferralRewardPaidEvent,
	ReferralSubmittedEvent,
)
from pgappforge.plugins.erp.hcm.referral.models import (
	ReferralProgram,
	ReferralReward,
	ReferralSubmission,
)
from pgappforge.plugins.erp.hcm.referral.services import (
	ReferralNotFoundError,
	ReferralService,
	ReferralServiceError,
	ReferralStateError,
)

__all__ = [
	# Plugin entry point
	"ReferralPlugin",
	"create_plugin",
	# Models
	"ReferralProgram",
	"ReferralSubmission",
	"ReferralReward",
	# Events
	"ReferralSubmittedEvent",
	"ReferralHiredEvent",
	"ReferralRewardPaidEvent",
	"ReferralExpiredEvent",
	# Service layer
	"ReferralService",
	"ReferralServiceError",
	"ReferralNotFoundError",
	"ReferralStateError",
]

_log = logging.getLogger(__name__)


class ReferralPlugin(BasePlugin):
	"""HCM Employee Referrals plugin.

	Covers referral programs, submission tracking, status state machine,
	reward eligibility evaluation, approval, and payment.
	"""

	name = "referral"
	domain = "hcm"
	depends_on = ["foundation"]

	metadata = {
		"version": "1.0.0",
		"description": (
			"HCM Employee Referrals — program management, candidate submission "
			"tracking, reward eligibility, approval, and payment workflows"
		),
		"tags": ["erp", "hcm", "referral", "recruitment"],
	}

	permissions = [
		"can_list_referral_programs",
		"can_write_referral_programs",
		"can_list_referral_submissions",
		"can_write_referral_submissions",
		"can_update_referral_status",
		"can_list_referral_rewards",
		"can_approve_referral_rewards",
		"can_mark_referral_reward_paid",
		"can_view_referral_reports",
	]

	def get_events(self) -> list[str]:
		return [
			"hcm.referral.submitted",
			"hcm.referral.hired",
			"hcm.referral.reward.paid",
			"hcm.referral.expired",
		]

	def subscribe_to(self) -> list[str]:
		return [
			"hcm.employee.hired",
			"hcm.employee.terminated",
		]

	def initialize(self) -> None:
		"""Set config defaults and wire event subscriptions."""
		defaults = {
			"REFERRAL_MENU_CATEGORY": "Referrals",
			"REFERRAL_DEFAULT_CURRENCY": "KES",
		}
		if self.appbuilder is not None:
			app = self.appbuilder.get_app()
			for key, value in defaults.items():
				app.config.setdefault(key, value)

		try:
			subscribe("hcm.employee.hired", self._on_employee_hired)
			_log.info("ReferralPlugin: event subscriptions registered")
		except Exception:  # noqa: BLE001
			_log.debug("ReferralPlugin: event bus not available; subscriptions skipped")

		_log.info("ReferralPlugin initialized")

	def register_models(self) -> list:
		return [
			ReferralProgram,
			ReferralSubmission,
			ReferralReward,
		]

	def register_views(self) -> None:
		from pgappforge.plugins.erp.hcm.referral.views import (
			ReferralProgramView,
			ReferralRewardView,
			ReferralSubmissionView,
		)
		cat = self.appbuilder.get_app().config.get("REFERRAL_MENU_CATEGORY", "Referrals") \
			if self.appbuilder is not None else "Referrals"
		self.add_view(ReferralProgramView, "Programs", icon="fa-gift", category=cat)
		self.add_view(ReferralSubmissionView, "Submissions", icon="fa-paper-plane", category=cat)
		self.add_view(ReferralRewardView, "Rewards", icon="fa-award", category=cat)
		_log.info("ReferralPlugin: views registered under %r", cat)

	def setup_rules(self, session: object) -> None:  # type: ignore[override]
		"""Install domain-level validation rulesets via the Rules Engine.

		Three rulesets are registered:
		1. referral.program.active_required — submissions require ACTIVE program.
		2. referral.reward.approved_before_payment — rewards must be APPROVED before PAID.
		3. referral.submission.no_terminal_transition — terminal statuses are immutable.
		"""
		try:
			from pgappforge.plugins.rules.engine import RulesEngine

			engine = RulesEngine(session=session)

			engine.register_ruleset(
				name="referral.program.active_required",
				model="ReferralSubmission",
				rules=[
					{
						"field": "program.status",
						"op": "neq",
						"value": "ACTIVE",
					}
				],
				action="raise_error",
				message=(
					"Referral submissions can only be made to ACTIVE programs."
				),
			)

			engine.register_ruleset(
				name="referral.reward.approved_before_payment",
				model="ReferralReward",
				rules=[
					{
						"field": "status",
						"op": "eq",
						"value": "PENDING",
					}
				],
				action="raise_error",
				message=(
					"Referral rewards must be APPROVED before they can be marked as PAID."
				),
			)

			engine.register_ruleset(
				name="referral.submission.no_terminal_transition",
				model="ReferralSubmission",
				rules=[
					{
						"field": "status",
						"op": "in",
						"value": ["HIRED", "REJECTED", "WITHDRAWN", "EXPIRED"],
					}
				],
				action="raise_error",
				message=(
					"Referral submissions in terminal states (HIRED, REJECTED, WITHDRAWN, EXPIRED) "
					"cannot be updated."
				),
			)

			_log.info("ReferralPlugin: 3 rulesets registered via RulesEngine")

		except Exception as exc:  # noqa: BLE001
			_log.warning("ReferralPlugin.setup_rules: RulesEngine unavailable — %s", exc)

	# ------------------------------------------------------------------
	# Internal event handlers
	# ------------------------------------------------------------------

	def _on_employee_hired(self, event: object) -> None:
		"""Hook: when an employee is hired, check if they arrived via a referral."""
		try:
			employee_email: str = getattr(event, "email", "")
			tenant_id: str = getattr(event, "tenant_id", "")

			if not (employee_email and tenant_id):
				return

			from sqlalchemy import select

			from pgappforge.extensions import db

			svc = ReferralService()
			with db.session() as session:
				# Find any OFFERED submission matching this candidate email
				submissions = session.execute(
					select(ReferralSubmission).where(
						ReferralSubmission.tenant_id == tenant_id,
						ReferralSubmission.candidate_email == employee_email,
						ReferralSubmission.status == "OFFERED",
					)
				).scalars().all()

				for submission in submissions:
					svc.update_status(submission.id, "HIRED", session)

				if submissions:
					session.commit()
					_log.info(
						"Auto-transitioned %d referral submission(s) to HIRED "
						"for email=%s tenant=%s",
						len(submissions), employee_email, tenant_id,
					)
		except Exception as exc:  # noqa: BLE001
			_log.error("_on_employee_hired referral handler failed: %s", exc)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def create_plugin(appbuilder: object, config: dict | None = None) -> ReferralPlugin:
	"""Instantiate and return the ReferralPlugin."""
	plugin = ReferralPlugin(appbuilder=appbuilder)

	if config and appbuilder is not None:
		app = appbuilder.get_app()  # type: ignore[union-attr]
		for key, value in config.items():
			app.config[key] = value

	plugin.initialize()
	return plugin
