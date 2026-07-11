"""
pgappforge/plugins/erp/platform/scheduler/views.py

Flask-AppBuilder views for the Batch Scheduler plugin.

ScheduledJobView      — full CRUD on scheduled job definitions
JobRunLogView         — read-only log viewer (list + show)
SchedulerDashboardView — live KPI tiles + status breakdown chart
"""
from __future__ import annotations
from flask_babel import lazy_gettext as _

import logging

from flask import render_template
from pgappforge import ModelView, expose
from pgappforge.models.sqla.interface import SQLAInterface
from pgappforge.security.decorators import has_access

from pgappforge.plugins.erp.base_view import BaseERPModelView, BaseERPView
from pgappforge.plugins.erp.platform.scheduler.models import JobRunLog, ScheduledJob

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ScheduledJobView
# ---------------------------------------------------------------------------

class ScheduledJobView(BaseERPModelView):
	"""CRUD view for scheduled job definitions.

	Operators can toggle is_active, adjust frequency, or update method kwargs
	without touching code.  The id, audit, and run-stat columns are managed
	by the service and hidden from the form.
	"""

	datamodel = SQLAInterface(ScheduledJob)

	list_title = "Scheduled Jobs"
	show_title = "Job Detail"
	add_title = "Register Job"
	edit_title = "Edit Job"

	list_columns = [
		"name",
		"frequency",
		"is_active",
		"last_run_at",
		"last_run_status",
		"next_run_at",
	]
	show_columns = [
		"name",
		"description",
		"frequency",
		"cron_expression",
		"plugin_path",
		"service_class",
		"method_name",
		"method_kwargs",
		"is_active",
		"last_run_at",
		"last_run_status",
		"last_run_error",
		"next_run_at",
		"run_count",
		"failure_count",
	]
	add_columns = [
		"name",
		"description",
		"frequency",
		"cron_expression",
		"plugin_path",
		"service_class",
		"method_name",
		"method_kwargs",
		"is_active",
	]
	edit_columns = [
		"description",
		"frequency",
		"cron_expression",
		"plugin_path",
		"service_class",
		"method_name",
		"method_kwargs",
		"is_active",
	]

	# Exclude generated/audit fields from forms
	add_exclude_columns = ["id", "created_on", "changed_on", "last_run_at",
	                       "last_run_status", "last_run_error", "next_run_at",
	                       "run_count", "failure_count", "run_logs"]
	edit_exclude_columns = ["id", "created_on", "changed_on", "tenant_id",
	                        "last_run_at", "last_run_status", "last_run_error",
	                        "next_run_at", "run_count", "failure_count", "run_logs"]

	label_columns = {
		"name": _("Job Name"),
		"frequency": _("Frequency"),
		"is_active": _("Active"),
		"last_run_at": _("Last Run"),
		"last_run_status": _("Last Status"),
		"next_run_at": _("Next Run"),
		"plugin_path": _("Module Path"),
		"service_class": _("Service Class"),
		"method_name": _("Method"),
		"method_kwargs": _("Extra kwargs (JSON)"),
		"cron_expression": _("Cron Expression"),
		"run_count": _("Total Runs"),
		"failure_count": _("Failures"),
		"last_run_error": _("Last Error"),
	}

	search_columns = ["name", "frequency", "last_run_status", "is_active"]
	page_size = 30


# ---------------------------------------------------------------------------
# JobRunLogView
# ---------------------------------------------------------------------------

class JobRunLogView(BaseERPModelView):
	"""Read-only view of job execution logs.

	Only list + show are permitted — run logs are append-only ledger entries.
	"""

	datamodel = SQLAInterface(JobRunLog)

	base_permissions = ["can_list", "can_show"]

	list_title = "Job Run Logs"
	show_title = "Run Log Detail"

	list_columns = [
		"job_id",
		"started_at",
		"status",
		"duration_ms",
		"records_processed",
	]
	show_columns = [
		"job_id",
		"started_at",
		"finished_at",
		"status",
		"duration_ms",
		"records_processed",
		"error_message",
	]

	label_columns = {
		"job_id": _("Job"),
		"started_at": _("Started"),
		"finished_at": _("Finished"),
		"status": _("Status"),
		"duration_ms": _("Duration (ms)"),
		"records_processed": _("Records"),
		"error_message": _("Error"),
	}

	search_columns = ["status", "job_id"]
	page_size = 50


# ---------------------------------------------------------------------------
# SchedulerDashboardView
# ---------------------------------------------------------------------------

class SchedulerDashboardView(BaseERPView):
	"""Live scheduler overview — KPI tiles + success/failure chart.

	Route base: /platform/scheduler
	"""

	route_base = "/platform/scheduler"

	@expose("/")
	@has_access
	def index(self):
		sess = self._session()

		# KPI counts
		total_jobs = self._count(ScheduledJob, session=sess)
		active_jobs = self._count(ScheduledJob, session=sess, is_active=True)
		failed_jobs = self._count(ScheduledJob, session=sess, last_run_status="FAILED")
		running_jobs = self._count(ScheduledJob, session=sess, last_run_status="RUNNING")

		# Recent run log summary (last 30 run log rows)
		import sqlalchemy as sa
		recent_logs: list[dict] = []
		try:
			rows = sess.execute(
				sa.select(JobRunLog)
				.order_by(JobRunLog.started_at.desc())
				.limit(30)
			).scalars().all()
			recent_logs = [
				{
					"job_id": r.job_id,
					"started_at": r.started_at.strftime("%Y-%m-%d %H:%M") if r.started_at else "",
					"status": r.status,
					"duration_ms": r.duration_ms or 0,
					"records_processed": r.records_processed,
				}
				for r in rows
			]
		except Exception:
			pass

		# Status breakdown chart data
		status_counts: list[dict] = []
		for status in ("SUCCESS", "FAILED", "RUNNING"):
			cnt = self._count(JobRunLog, session=sess, status=status)
			status_counts.append({"label": status, "value": cnt})

		kpi_html = self.kpi_cards([
			{"label": "Total Jobs", "value": total_jobs, "icon": "fa-calendar", "color": "#1a56db"},
			{"label": "Active Jobs", "value": active_jobs, "icon": "fa-check-circle", "color": "#0e9f6e"},
			{"label": "Failed Jobs", "value": failed_jobs, "icon": "fa-exclamation-triangle", "color": "#e02424"},
			{"label": "Running Now", "value": running_jobs, "icon": "fa-spinner", "color": "#d97706"},
		])

		chart_html = self.chart(
			rows=status_counts,
			chart_type="doughnut",
			x_col="label",
			y_col="value",
			title="Run Log Status Breakdown",
			height=260,
		)

		return render_template(
			"platform/scheduler_dashboard.html",
			kpi_html=kpi_html,
			chart_html=chart_html,
			recent_logs=recent_logs,
			appbuilder=self.appbuilder,
		)


__all__ = [
	"ScheduledJobView",
	"JobRunLogView",
	"SchedulerDashboardView",
]
