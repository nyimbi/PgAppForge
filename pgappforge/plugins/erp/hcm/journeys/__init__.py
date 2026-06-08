"""
pgappforge/plugins/erp/hcm/journeys/__init__.py

JourneysPlugin — HCM Employee Journeys ERP plugin.

Structured task-driven journeys for key employee lifecycle events:
  JourneyTemplate → Journey → JourneyTask

Domain: hcm
Depends on: foundation

Events emitted:
  hcm.journeys.started
  hcm.journeys.task.completed
  hcm.journeys.task.skipped
  hcm.journeys.completed
  hcm.journeys.overdue

Events consumed:
  hcm.employee.hired        (triggers ONBOARDING journey)
  hcm.employee.terminated   (triggers OFFBOARDING journey)

Usage
-----
Add to your app config::

    PGAPPFORGE_PLUGINS = [
        "pgappforge.plugins.erp.foundation",
        "pgappforge.plugins.erp.hcm.journeys",
    ]

Or instantiate directly::

    from pgappforge.plugins.erp.hcm.journeys import JourneysPlugin
    plugin = JourneysPlugin(appbuilder)
    plugin.activate()
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class JourneysPlugin(BasePlugin):
	"""HCM Employee Journeys ERP plugin.

	Manages structured onboarding, offboarding, transfer, role-change, and
	promotion journeys with dependency-aware task sequencing.

	Auto-subscribes to hcm.employee.hired and hcm.employee.terminated to
	start journeys automatically when employees are hired or terminated.
	"""

	name = "journeys"
	domain = "hcm"
	depends_on: list[str] = ["foundation"]

	# ------------------------------------------------------------------
	# Metadata
	# ------------------------------------------------------------------

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="journeys",
			version="1.0.0",
			description=(
				"HCM Employee Journeys — structured task-driven lifecycle journeys: "
				"onboarding, offboarding, transfer, role change, and promotion. "
				"Dependency-aware task sequencing, overdue detection, and automatic "
				"journey completion with a 15-task default onboarding template."
			),
			author="PgAppForge Contributors",
			tags=["hcm", "journeys", "onboarding", "offboarding", "workday", "employee-experience"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_journey_template_list",
				"can_journey_template_write",
				"can_journey_list",
				"can_journey_start",
				"can_journey_cancel",
				"can_journey_task_complete",
				"can_journey_task_skip",
				"can_journey_reports",
				"can_journey_overdue_view",
			],
			safe_mode_compatible=True,
		)

	# ------------------------------------------------------------------
	# get_events / subscribe_to
	# ------------------------------------------------------------------

	def get_events(self) -> list[str]:
		return [
			"hcm.journeys.started",
			"hcm.journeys.task.completed",
			"hcm.journeys.task.skipped",
			"hcm.journeys.completed",
			"hcm.journeys.overdue",
		]

	def subscribe_to(self) -> list[str]:
		return [
			"hcm.employee.hired",
			"hcm.employee.terminated",
		]

	# ------------------------------------------------------------------
	# Lifecycle
	# ------------------------------------------------------------------

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"JOURNEYS_MENU_CATEGORY": "HR",
			"JOURNEYS_AUTO_START_ONBOARDING": True,
			"JOURNEYS_AUTO_START_OFFBOARDING": True,
			"JOURNEYS_OVERDUE_NOTIFY": True,
		}
		self.config = {**defaults, **self.config}
		log.info("JourneysPlugin initialised (config keys: %s)", list(self.config))

	def register_models(self) -> list:
		from pgappforge.plugins.erp.hcm.journeys.models import (
			JourneyTemplate,
			Journey,
			JourneyTask,
		)
		return [JourneyTemplate, Journey, JourneyTask]

	def register_views(self) -> None:
		from pgappforge.plugins.erp.hcm.journeys.views import (
			JourneysDashboardView,
			JourneyTaskView,
			JourneyTemplateView,
			JourneyView,
		)
		cat = self.config.get("JOURNEYS_MENU_CATEGORY", "HR")
		self.add_view(JourneysDashboardView, "Journeys", icon="fa-tachometer", category=cat)
		self.add_view(JourneyTemplateView, "Journey Templates", icon="fa-copy", category=cat)
		self.add_view(JourneyView, "Active Journeys", icon="fa-route", category=cat)
		self.add_view(JourneyTaskView, "Journey Tasks", icon="fa-tasks", category=cat)
		log.info("JourneysPlugin: views registered under %r", cat)

	# ------------------------------------------------------------------
	# Event handlers (auto-start journeys on hire/termination)
	# ------------------------------------------------------------------

	def on_employee_hired(self, event: Any, session: Any) -> None:
		"""Auto-start ONBOARDING journey when hcm.employee.hired is received."""
		if not self.config.get("JOURNEYS_AUTO_START_ONBOARDING", True):
			return
		try:
			from pgappforge.plugins.erp.hcm.journeys.services import JourneyService
			from datetime import date
			svc = JourneyService()
			employee_id = getattr(event, "employee_id", None)
			tenant_id = getattr(event, "tenant_id", None)
			hire_date_str = getattr(event, "hire_date", None)
			if not employee_id or not tenant_id:
				log.warning("JourneysPlugin.on_employee_hired: missing employee_id or tenant_id")
				return
			trigger_date = (
				date.fromisoformat(hire_date_str) if hire_date_str else date.today()
			)
			svc.start_journey(
				employee_id=employee_id,
				journey_type="ONBOARDING",
				trigger_date=trigger_date,
				tenant_id=tenant_id,
				session=session,
			)
		except Exception as exc:
			log.warning("JourneysPlugin.on_employee_hired: failed to start journey: %s", exc)

	def on_employee_terminated(self, event: Any, session: Any) -> None:
		"""Auto-start OFFBOARDING journey when hcm.employee.terminated is received."""
		if not self.config.get("JOURNEYS_AUTO_START_OFFBOARDING", True):
			return
		try:
			from pgappforge.plugins.erp.hcm.journeys.services import JourneyService
			from datetime import date
			svc = JourneyService()
			employee_id = getattr(event, "employee_id", None)
			tenant_id = getattr(event, "tenant_id", None)
			termination_date_str = getattr(event, "termination_date", None)
			if not employee_id or not tenant_id:
				log.warning("JourneysPlugin.on_employee_terminated: missing employee_id or tenant_id")
				return
			trigger_date = (
				date.fromisoformat(termination_date_str) if termination_date_str else date.today()
			)
			svc.start_journey(
				employee_id=employee_id,
				journey_type="OFFBOARDING",
				trigger_date=trigger_date,
				tenant_id=tenant_id,
				session=session,
			)
		except Exception as exc:
			log.warning("JourneysPlugin.on_employee_terminated: failed to start journey: %s", exc)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_plugin(
	appbuilder: Any,
	config: dict[str, Any] | None = None,
) -> JourneysPlugin:
	return JourneysPlugin(appbuilder, config=config or {})


# ---------------------------------------------------------------------------
# Public re-exports
# ---------------------------------------------------------------------------

from pgappforge.plugins.erp.hcm.journeys.models import (  # noqa: E402
	JourneyTemplate,
	Journey,
	JourneyTask,
)
from pgappforge.plugins.erp.hcm.journeys.events import (  # noqa: E402
	JourneyStartedEvent,
	JourneyTaskCompletedEvent,
	JourneyTaskSkippedEvent,
	JourneyCompletedEvent,
	JourneyOverdueTaskEvent,
)
from pgappforge.plugins.erp.hcm.journeys.services import (  # noqa: E402
	JourneyService,
	JourneyServiceError,
	JourneyNotFoundError,
	JourneyTaskNotFoundError,
	JourneyStateError,
)

__all__ = [
	# plugin
	"JourneysPlugin",
	"create_plugin",
	# models
	"JourneyTemplate",
	"Journey",
	"JourneyTask",
	# events
	"JourneyStartedEvent",
	"JourneyTaskCompletedEvent",
	"JourneyTaskSkippedEvent",
	"JourneyCompletedEvent",
	"JourneyOverdueTaskEvent",
	# services
	"JourneyService",
	"JourneyServiceError",
	"JourneyNotFoundError",
	"JourneyTaskNotFoundError",
	"JourneyStateError",
]
