from __future__ import annotations

from pgappforge.plugins.erp.foundation import BasePlugin

__all__ = ["SurveysPlugin"]


class SurveysPlugin(BasePlugin):
	"""Survey Builder module.

	Provides full survey lifecycle: DRAFT → PUBLISHED → CLOSED → ARCHIVED,
	multi-type questions (TEXT, SINGLE/MULTI_CHOICE, RATING_SCALE, NPS,
	BOOLEAN, DATE), branching logic, anonymous response tokens, NPS/eNPS
	computation, and per-question analytics.

	BPM integration allows workflows to create and send surveys, and to
	retrieve aggregated results as workflow context variables.
	"""

	name = "surveys"
	domain = "platform"
	depends_on: list[str] = ["foundation"]

	def register(self, app_builder) -> None:  # type: ignore[override]
		app_builder.add_api(
			"pgappforge.plugins.erp.platform.surveys.views",
			tags=["platform", "surveys", "enps", "feedback", "analytics"],
		)

	def get_models(self) -> list:
		from pgappforge.plugins.erp.platform.surveys.models import (
			Survey,
			SurveyAnswer,
			SurveyQuestion,
			SurveyResponse,
		)
		return [Survey, SurveyQuestion, SurveyResponse, SurveyAnswer]

	def subscribe_to(self) -> list[str]:
		return []
