"""Full ATS — applicant tracking with Africa job board hooks."""
from __future__ import annotations
from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority


class RecruitingPlugin(BasePlugin):
	name = "recruiting"
	domain = "hcm"
	depends_on: list[str] = ["foundation"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="recruiting",
			version="1.0.0",
			description="Full ATS — job requisitions, applications, interviews, offers, Africa job boards",
			author="PgAppForge Contributors",
			tags=["hcm", "recruiting", "ats", "talent"],
			priority=PluginPriority.NORMAL,
		)

	def initialize(self) -> None: pass
	def get_events(self) -> list[str]: return ["hcm.recruiting.offer_accepted", "hcm.recruiting.application_received"]
	def subscribe_to(self) -> list[str]: return []
	def register_models(self) -> list: from pgappforge.plugins.erp.hcm.recruiting import models; return [models.JobRequisition, models.JobApplication, models.InterviewSchedule, models.OfferLetter]
	def register_views(self) -> None: pass


__all__ = ["RecruitingPlugin"]
