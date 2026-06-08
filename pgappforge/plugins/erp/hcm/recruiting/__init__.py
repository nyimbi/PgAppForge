"""
pgappforge/plugins/erp/hcm/recruiting/__init__.py

RecruitingPlugin — HCM Applicant Tracking System (ATS) ERP plugin.

Full-cycle recruiting from requisition through offer acceptance:
  JobRequisition → JobApplication → InterviewSchedule → OfferLetter

Domain: hcm
Depends on: foundation

Events emitted:
  hcm.recruiting.requisition.posted
  hcm.recruiting.application.received
  hcm.recruiting.interview.scheduled
  hcm.recruiting.offer.extended
  hcm.recruiting.offer.accepted
  hcm.recruiting.requisition.filled

Events consumed:
  hcm.employee.hired

Usage
-----
Add to your app config::

    PGAPPFORGE_PLUGINS = [
        "pgappforge.plugins.erp.foundation",
        "pgappforge.plugins.erp.hcm.recruiting",
    ]

Or instantiate directly::

    from pgappforge.plugins.erp.hcm.recruiting import RecruitingPlugin
    plugin = RecruitingPlugin(appbuilder)
    plugin.activate()
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class RecruitingPlugin(BasePlugin):
	"""HCM Applicant Tracking System ERP plugin.

	Manages end-to-end recruiting: requisitions, applications, interviews,
	offers, and automatic onboarding journey kickoff on hire.

	Auto-subscribes to hcm.employee.hired to close requisitions on hire events
	arriving from external HRIS sources.
	"""

	name = "recruiting"
	domain = "hcm"
	depends_on: list[str] = ["foundation"]

	# ------------------------------------------------------------------
	# Metadata
	# ------------------------------------------------------------------

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="recruiting",
			version="1.0.0",
			description=(
				"HCM Applicant Tracking System — full-cycle recruiting from requisition "
				"through offer acceptance. Manages job postings, candidate pipelines, "
				"interview scheduling, offer letters, and automatic onboarding trigger. "
				"Includes pipeline analytics and recruiting dashboard KPIs."
			),
			author="PgAppForge Contributors",
			tags=["hcm", "recruiting", "ats", "applicant-tracking", "hiring", "talent-acquisition"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_requisition_list",
				"can_requisition_write",
				"can_requisition_post",
				"can_application_list",
				"can_application_advance",
				"can_interview_schedule",
				"can_interview_feedback",
				"can_offer_create",
				"can_offer_accept",
				"can_recruiting_reports",
			],
			safe_mode_compatible=True,
		)

	# ------------------------------------------------------------------
	# get_events / subscribe_to
	# ------------------------------------------------------------------

	def get_events(self) -> list[str]:
		return [
			"hcm.recruiting.requisition.posted",
			"hcm.recruiting.application.received",
			"hcm.recruiting.interview.scheduled",
			"hcm.recruiting.offer.extended",
			"hcm.recruiting.offer.accepted",
			"hcm.recruiting.requisition.filled",
		]

	def subscribe_to(self) -> list[str]:
		return ["hcm.employee.hired"]

	# ------------------------------------------------------------------
	# Lifecycle
	# ------------------------------------------------------------------

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"RECRUITING_DEFAULT_CURRENCY": "KES",
			"RECRUITING_AUTO_TRIGGER_ONBOARDING": True,
			"RECRUITING_AUTO_REQUISITION_ON_VACATE": True,
		}
		self.config = {**defaults, **self.config}
		log.info("RecruitingPlugin initialised (config keys: %s)", list(self.config))

	def register_models(self) -> list:
		from pgappforge.plugins.erp.hcm.recruiting.models import (
			JobRequisition,
			JobApplication,
			InterviewSchedule,
			OfferLetter,
		)
		return [JobRequisition, JobApplication, InterviewSchedule, OfferLetter]

	def register_views(self) -> None:
		from pgappforge.plugins.erp.hcm.recruiting.views import (
			InterviewScheduleView,
			JobApplicationView,
			JobRequisitionView,
			OfferLetterView,
			RecruitingDashboardView,
		)
		cat = self.config.get("RECRUITING_MENU_CATEGORY", "Recruiting")
		self.add_view(RecruitingDashboardView, "Dashboard", icon="fa-tachometer", category=cat)
		self.add_view(JobRequisitionView, "Requisitions", icon="fa-briefcase", category=cat)
		self.add_view(JobApplicationView, "Applications", icon="fa-file-alt", category=cat)
		self.add_view(InterviewScheduleView, "Interviews", icon="fa-comments", category=cat)
		self.add_view(OfferLetterView, "Offers", icon="fa-handshake", category=cat)
		log.info("RecruitingPlugin: views registered under %r", cat)

	# ------------------------------------------------------------------
	# Event handlers
	# ------------------------------------------------------------------

	def on_employee_hired(self, event: Any, session: Any) -> None:
		"""No-op consumer: hiring originates inside this plugin via accept_offer()."""
		log.debug(
			"RecruitingPlugin.on_employee_hired: event received for employee=%s",
			getattr(event, "employee_id", "?"),
		)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_plugin(
	appbuilder: Any,
	config: dict[str, Any] | None = None,
) -> RecruitingPlugin:
	return RecruitingPlugin(appbuilder, config=config or {})


# ---------------------------------------------------------------------------
# Public re-exports
# ---------------------------------------------------------------------------

from pgappforge.plugins.erp.hcm.recruiting.models import (  # noqa: E402
	JobRequisition,
	JobApplication,
	InterviewSchedule,
	OfferLetter,
)
from pgappforge.plugins.erp.hcm.recruiting.events import (  # noqa: E402
	RequisitionPostedEvent,
	ApplicationReceivedEvent,
	InterviewScheduledEvent,
	OfferExtendedEvent,
	OfferAcceptedEvent,
	RequisitionFilledEvent,
)
from pgappforge.plugins.erp.hcm.recruiting.services import (  # noqa: E402
	RecruitingService,
	RecruitingServiceError,
	RequisitionNotFoundError,
	ApplicationNotFoundError,
	InterviewNotFoundError,
	OfferNotFoundError,
	RecruitingStateError,
)

__all__ = [
	# plugin
	"RecruitingPlugin",
	"create_plugin",
	# models
	"JobRequisition",
	"JobApplication",
	"InterviewSchedule",
	"OfferLetter",
	# events
	"RequisitionPostedEvent",
	"ApplicationReceivedEvent",
	"InterviewScheduledEvent",
	"OfferExtendedEvent",
	"OfferAcceptedEvent",
	"RequisitionFilledEvent",
	# services
	"RecruitingService",
	"RecruitingServiceError",
	"RequisitionNotFoundError",
	"ApplicationNotFoundError",
	"InterviewNotFoundError",
	"OfferNotFoundError",
	"RecruitingStateError",
]
