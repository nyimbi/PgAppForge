from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

from .events import (
	InternalCandidateFoundEvent,
	LearningRecommendedEvent,
	SkillDefinedEvent,
	SkillEndorsedEvent,
	SkillGapIdentifiedEvent,
)
from .models import (
	EmployeeSkill,
	JobRequiredSkill,
	Skill,
	SkillCategory,
	SkillDomain,
)
from .services import SkillsService

__all__ = [
	"SkillsPlugin",
	"create_plugin",
]

log = logging.getLogger(__name__)


class SkillsPlugin(BasePlugin):
	"""Skills Taxonomy plugin for the HCM domain.

	Provides skill definition, endorsement, gap analysis, internal candidate
	matching, and LMS-integrated learning recommendations.
	"""

	name = "skills"
	domain = "hcm"
	depends_on: list[str] = ["foundation"]

	metadata: dict[str, Any] = {
		"version": "1.0.0",
		"description": (
			"Skills taxonomy: skill domains, categories, employee endorsements, "
			"job requirement mapping, gap analysis, internal mobility scoring, "
			"and LMS-linked learning recommendations."
		),
		"tags": [
			"hcm",
			"skills",
			"talent",
			"opportunity-graph",
			"workday",
			"workforce-planning",
		],
	}

	def __init__(self, appbuilder: Any, config: dict[str, Any] | None = None) -> None:
		super().__init__(appbuilder, config or {})
		self._service = SkillsService()

	# ------------------------------------------------------------------
	# Plugin interface
	# ------------------------------------------------------------------

	def get_events(self) -> list[type]:
		return [
			SkillDefinedEvent,
			SkillEndorsedEvent,
			SkillGapIdentifiedEvent,
			InternalCandidateFoundEvent,
			LearningRecommendedEvent,
		]

	def subscribe_to(self) -> list[str]:
		return [
			"hcm.employee.role_changed",
			"hcm.employee.hired",
		]

	def initialize(self) -> None:
		"""Set default config values."""
		defaults: dict[str, str] = {
			"SKILLS_MENU_CATEGORY": "Talent & Skills",
		}
		for key, value in defaults.items():
			if key not in self.config:
				self.config[key] = value

		if self.appbuilder and hasattr(self.appbuilder, "app"):
			app_config = self.appbuilder.app.config
			for key, value in defaults.items():
				app_config.setdefault(key, value)

		log.info("SkillsPlugin initialized")

	def register_models(self) -> list[type]:
		return [
			SkillDomain,
			SkillCategory,
			Skill,
			EmployeeSkill,
			JobRequiredSkill,
		]

	def register_views(self) -> list[Any]:
		"""Register Flask-AppBuilder views. Stub — views not yet implemented."""
		return []

	# ------------------------------------------------------------------
	# Event handler stubs
	# ------------------------------------------------------------------

	def _on_hcm_employee_hired(self, event: Any) -> None:
		"""On hire: could trigger initial skill gap analysis for onboarding role."""
		log.info(
			"SkillsPlugin received hcm.employee.hired for employee_id=%s",
			getattr(event, "employee_id", "?"),
		)

	def _on_hcm_employee_role_changed(self, event: Any) -> None:
		"""On role change: trigger skill gap re-analysis for new position."""
		log.info(
			"SkillsPlugin received hcm.employee.role_changed for employee_id=%s",
			getattr(event, "employee_id", "?"),
		)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_plugin(
	appbuilder: Any,
	config: dict[str, Any] | None = None,
) -> SkillsPlugin:
	"""Instantiate and return the SkillsPlugin."""
	plugin = SkillsPlugin(appbuilder=appbuilder, config=config)
	plugin.initialize()
	return plugin
