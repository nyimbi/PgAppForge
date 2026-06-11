"""
pgappforge/plugins/erp/platform/scheduler/__init__.py

SchedulerPlugin — batch job scheduling for fintech/ERP operations.

Domain:   platform
Depends:  foundation

Provides a persistent ScheduledJob registry and JobRunLog ledger.
Call ``BatchSchedulerService().run_due_jobs(tenant_id, session)`` from any
periodic trigger (APScheduler beat, Celery beat, OS cron, CLI command).

Events emitted
--------------
  (none — scheduler is infrastructure; individual jobs emit their own events)

Standard jobs seeded at startup
--------------------------------
  core_banking.daily_interest      DAILY  — interest accrual
  core_banking.dormancy_check      DAILY  — mark dormant accounts
  core_banking.expire_holds        DAILY  — expire stale holds
  lending.daily_aging              DAILY  — NPA classification
  lending.standing_orders          DAILY  — standing order repayments
  mobile_money.dormancy            DAILY  — dormant wallet marking
  mobile_money.eod_reconciliation  DAILY  — EOD reconciliation
  clubs.monthly_statements         MONTHLY — member statement generation
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class SchedulerPlugin(BasePlugin):
	"""Batch Scheduler plugin.

	Provides a persistent registry of scheduled jobs (ScheduledJob) and an
	append-only run log (JobRunLog).  The plugin seeds the standard fintech
	batch jobs on first activation and exposes admin views for operators to
	monitor and control jobs without code changes.
	"""

	name = "scheduler"
	domain = "platform"
	depends_on: list[str] = ["foundation"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="scheduler",
			version="1.0.0",
			description=(
				"Batch Scheduler — persistent job registry, sequential execution engine, "
				"append-only run log, and admin dashboard for fintech/ERP batch operations."
			),
			author="PgAppForge Contributors",
			tags=[
				"platform", "scheduler", "batch", "cron",
				"core-banking", "lending", "mobile-money",
			],
			priority=PluginPriority.HIGH,
			permissions=[
				"can_scheduler_read",
				"can_scheduler_write",
				"can_scheduler_run",
			],
			safe_mode_compatible=True,
		)

	def get_events(self) -> list[str]:
		# Scheduler itself does not emit domain events; delegated services do.
		return []

	def subscribe_to(self) -> list[str]:
		return []

	def activate(self) -> None:
		self.initialize()

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"SCHEDULER_TENANT_ID": "default",
			"SCHEDULER_SEED_JOBS": True,
		}
		self.config = {**defaults, **self.config}
		log.info("SchedulerPlugin initialised")

	def post_initialize(self) -> None:
		super().post_initialize()
		if self.config.get("SCHEDULER_SEED_JOBS", True):
			self._try_seed_jobs()

	def register_views(self) -> None:
		from pgappforge.plugins.erp.platform.scheduler.views import (
			JobRunLogView,
			ScheduledJobView,
			SchedulerDashboardView,
		)
		cat = self.config.get("SCHEDULER_MENU_CATEGORY", "Platform")
		self.add_view(
			SchedulerDashboardView,
			"Scheduler Dashboard",
			icon="fa-clock-o",
			category=cat,
		)
		self.add_view(
			ScheduledJobView,
			"Scheduled Jobs",
			icon="fa-calendar",
			category=cat,
		)
		self.add_view(
			JobRunLogView,
			"Job Run Logs",
			icon="fa-history",
			category=cat,
		)
		log.info("SchedulerPlugin: views registered under %r", cat)

	def register_models(self) -> list:
		from pgappforge.plugins.erp.platform.scheduler.models import (
			JobRunLog,
			ScheduledJob,
		)
		return [ScheduledJob, JobRunLog]

	# ------------------------------------------------------------------
	# Seed helpers
	# ------------------------------------------------------------------

	def _try_seed_jobs(self) -> None:
		"""Attempt to seed standard batch jobs against the live DB.

		Non-fatal: any exception (missing tables, no app context, etc.) is
		logged at DEBUG and swallowed so the plugin activates regardless.
		"""
		try:
			from flask import current_app
			session = current_app.appbuilder.get_session()
			tenant_id = self.config.get("SCHEDULER_TENANT_ID", "default")
			from pgappforge.plugins.erp.platform.scheduler.services import BatchSchedulerService
			n = BatchSchedulerService().seed_standard_jobs(tenant_id, session)
			session.commit()
			log.info("SchedulerPlugin: seeded %d standard batch jobs for tenant %r", n, tenant_id)
		except Exception as exc:
			log.debug("SchedulerPlugin._try_seed_jobs skipped (non-fatal): %s", exc)


def create_plugin(
	appbuilder: Any,
	config: dict[str, Any] | None = None,
) -> SchedulerPlugin:
	return SchedulerPlugin(appbuilder, config=config or {})


# ---------------------------------------------------------------------------
# Public re-exports
# ---------------------------------------------------------------------------

from pgappforge.plugins.erp.platform.scheduler.models import (  # noqa: E402
	JobRunLog,
	ScheduledJob,
)
from pgappforge.plugins.erp.platform.scheduler.services import (  # noqa: E402
	BatchSchedulerService,
)

__all__ = [
	"SchedulerPlugin",
	"create_plugin",
	"ScheduledJob",
	"JobRunLog",
	"BatchSchedulerService",
]
