from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

from .events import (
	ContingentSpendEvent,
	ContingentWorkerOnboardedEvent,
	SowCompletedEvent,
	SowCreatedEvent,
	TimesheetApprovedEvent,
)
from .models import (
	ContingentTimesheet,
	ContingentWorker,
	StaffingAgency,
	StatementOfWork,
)
from .services import ContingentWorkforceService

__all__ = [
	"ContingentWorkforcePlugin",
	"create_plugin",
]

log = logging.getLogger(__name__)


class ContingentWorkforcePlugin(BasePlugin):
	"""Contingent Workforce plugin for the HCM domain.

	Manages contractors, freelancers, SOW workers, and temps: onboarding,
	statements of work, timesheet submission/approval, spend analytics,
	and total workforce composition reporting.
	"""

	name = "contingent"
	domain = "hcm"
	depends_on: list[str] = ["foundation"]

	metadata: dict[str, Any] = {
		"version": "1.0.0",
		"description": (
			"Contingent workforce management: staffing agencies, contractor onboarding, "
			"statements of work with milestone tracking, timesheet submission and approval, "
			"spend analytics by worker type, and total workforce headcount composition."
		),
		"tags": [
			"hcm",
			"contingent",
			"contractor",
			"sow",
			"staffing",
			"workday-vndly",
		],
	}

	def __init__(self, appbuilder: Any, config: dict[str, Any] | None = None) -> None:
		super().__init__(appbuilder, config or {})
		self._service = ContingentWorkforceService()

	# ------------------------------------------------------------------
	# Plugin interface
	# ------------------------------------------------------------------

	def get_events(self) -> list[type]:
		return [
			ContingentWorkerOnboardedEvent,
			SowCreatedEvent,
			TimesheetApprovedEvent,
			ContingentSpendEvent,
			SowCompletedEvent,
		]

	def subscribe_to(self) -> list[str]:
		return [
			"hcm.employee.terminated",
		]

	def initialize(self) -> None:
		"""Set default config values."""
		defaults: dict[str, str] = {
			"CONTINGENT_MENU_CATEGORY": "Contingent Workforce",
			"CONTINGENT_DEFAULT_RATE_UNIT": "DAILY",
		}
		for key, value in defaults.items():
			if key not in self.config:
				self.config[key] = value

		if self.appbuilder and hasattr(self.appbuilder, "app"):
			app_config = self.appbuilder.app.config
			for key, value in defaults.items():
				app_config.setdefault(key, value)

		log.info("ContingentWorkforcePlugin initialized")

	def register_models(self) -> list[type]:
		return [
			StaffingAgency,
			ContingentWorker,
			StatementOfWork,
			ContingentTimesheet,
		]

	def register_views(self) -> list[Any]:
		"""Register Flask-AppBuilder views. Stub — views not yet implemented."""
		return []

	# ------------------------------------------------------------------
	# Event handler stubs
	# ------------------------------------------------------------------

	def _on_hcm_employee_terminated(self, event: Any) -> None:
		"""On employee termination: flag any active contingent engagements for review."""
		log.info(
			"ContingentWorkforcePlugin received hcm.employee.terminated for employee_id=%s",
			getattr(event, "employee_id", "?"),
		)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_plugin(
	appbuilder: Any,
	config: dict[str, Any] | None = None,
) -> ContingentWorkforcePlugin:
	"""Instantiate and return the ContingentWorkforcePlugin."""
	plugin = ContingentWorkforcePlugin(appbuilder=appbuilder, config=config)
	plugin.initialize()
	return plugin
