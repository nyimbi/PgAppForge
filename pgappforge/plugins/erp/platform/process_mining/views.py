"""
pgappforge/plugins/erp/platform/process_mining/views.py

Flask views for the Platform / Process Mining plugin.

Registered views:
  ProcessMiningDashboardView  — process instance duration timeline summary
  ProcessMiningDefinitionView — definition CRUD/list metadata
"""
from __future__ import annotations
from flask_babel import lazy_gettext as _

import logging
from datetime import datetime, timezone

import sqlalchemy as sa
from flask import render_template_string
from markupsafe import Markup, escape

from pgappforge import ModelView, expose
from pgappforge.models.sqla.interface import SQLAInterface
from pgappforge.security.decorators import has_access

try:
	from pgappforge.plugins.erp.base import BaseERPView
except ImportError:  # pragma: no cover - compatibility for current package layout
	from pgappforge.plugins.erp.base_view import BaseERPView
from pgappforge.plugins.erp.platform.process_mining.models import ProcessMiningDefinition

log = logging.getLogger(__name__)


class ProcessMiningDefinitionView(ModelView):
	datamodel = SQLAInterface(ProcessMiningDefinition)
	list_columns = ['name', 'event_types', 'last_run', 'metrics']
	show_columns = ['tenant_id', 'name', 'event_types', 'last_run', 'metrics']
	label_columns = {
		'tenant_id': _('Tenant'),
		'name': _('Definition'),
		'event_types': _('Event Types'),
		'last_run': _('Last Run'),
		'metrics': _('Latest Metrics'),
	}
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


# ---------------------------------------------------------------------------
# ProcessMiningDashboardView
# ---------------------------------------------------------------------------

class ProcessMiningDashboardView(BaseERPView):
	"""Process mining timeline summary over workflow process instances."""
	route_base = "/platform/process-mining"
	default_view = "index"

	@expose("/")
	@has_access
	def index(self):
		try:
			rows, message = self._timeline_rows()
		except Exception as exc:
			log.exception("ProcessMiningDashboardView.index: failed to load timeline data")
			rows = []
			message = f"Process timeline unavailable: {exc}"

		kpi_html = self.kpi_cards([
			{"label": "Process Groups", "value": len({r["process_definition"] for r in rows}), "icon": "fa-sitemap", "color": "#1a56db"},
			{"label": "Instance Rows", "value": sum(r["instance_count"] for r in rows), "icon": "fa-list", "color": "#0e9f6e"},
			{"label": "Status Buckets", "value": len(rows), "icon": "fa-tags", "color": "#7e3af2"},
		])
		return render_template_string(
			_PROCESS_MINING_TEMPLATE,
			kpi_html=kpi_html,
			timeline_table_html=self._timeline_table(rows, message),
			appbuilder=self.appbuilder,
		)

	def _timeline_rows(self) -> tuple[list[dict], str]:
		try:
			from pgappforge.plugins.workflow.models import ProcessDefinition, ProcessInstance
		except Exception as exc:
			return [], f"ProcessInstance model unavailable: {exc}"

		session = self._session()
		stmt = (
			sa.select(
				ProcessDefinition.name.label("process_definition"),
				ProcessInstance.status,
				ProcessInstance.started_at,
				ProcessInstance.completed_at,
			)
			.join(ProcessDefinition, ProcessInstance.definition_id == ProcessDefinition.id)
			.order_by(ProcessDefinition.name, ProcessInstance.status, ProcessInstance.started_at)
		)
		rows = session.execute(stmt).all()
		now = datetime.now(timezone.utc)
		groups: dict[tuple[str, str], dict] = {}
		for row in rows:
			process_name = row.process_definition or "Unassigned"
			status = row.status or "unknown"
			key = (process_name, status)
			group = groups.setdefault(
				key,
				{
					"process_definition": process_name,
					"status": status,
					"durations": [],
					"instance_count": 0,
				},
			)
			group["instance_count"] += 1
			duration = self._duration_seconds(row.started_at, row.completed_at, now)
			if duration is not None:
				group["durations"].append(duration)

		timeline_rows: list[dict] = []
		for group in groups.values():
			durations = group.pop("durations")
			if durations:
				group["avg_duration_seconds"] = round(sum(durations) / len(durations), 2)
				group["min_duration"] = round(min(durations), 2)
				group["max_duration"] = round(max(durations), 2)
			else:
				group["avg_duration_seconds"] = 0
				group["min_duration"] = 0
				group["max_duration"] = 0
			timeline_rows.append(group)
		return timeline_rows, ""

	@staticmethod
	def _duration_seconds(started_at, completed_at, now: datetime) -> float | None:
		if started_at is None:
			return None
		start = ProcessMiningDashboardView._aware(started_at)
		end = ProcessMiningDashboardView._aware(completed_at) if completed_at else now
		return max((end - start).total_seconds(), 0.0)

	@staticmethod
	def _aware(value: datetime) -> datetime:
		if value.tzinfo is None:
			return value.replace(tzinfo=timezone.utc)
		return value

	def _timeline_table(self, rows: list[dict], message: str) -> Markup:
		body: list[str] = []
		for row in rows:
			body.append(
				"<tr>"
				f"<td>{escape(row['process_definition'])}</td>"
				f"<td>{self._status_indicator(row['status'])}</td>"
				f"<td>{row['instance_count']}</td>"
				f"<td>{row['avg_duration_seconds']}</td>"
				f"<td>{row['min_duration']}</td>"
				f"<td>{row['max_duration']}</td>"
				"</tr>"
			)
		if not body:
			text = message or "No process instances found."
			body.append(f"<tr><td colspan='6' class='text-center text-muted'>{escape(text)}</td></tr>")
		return Markup(
			"<div class='table-responsive'>"
			"<table class='table table-striped table-condensed'>"
			"<thead><tr><th>Process Definition</th><th>Status</th><th>Instance Count</th>"
			"<th>Avg Duration Seconds</th><th>Min Duration</th><th>Max Duration</th></tr></thead>"
			f"<tbody>{''.join(body)}</tbody>"
			"</table></div>"
		)

	@staticmethod
	def _status_indicator(status: str) -> Markup:
		status_key = (status or "unknown").lower()
		colors = {
			"active": "#1a56db",
			"running": "#1a56db",
			"completed": "#0e9f6e",
			"failed": "#9e1c00",
			"error": "#9e1c00",
			"cancelled": "#6b7280",
			"suspended": "#d97706",
		}
		color = colors.get(status_key, "#6b7280")
		return Markup(
			f"<span style='display:inline-flex;align-items:center;gap:6px;'>"
			f"<span style='width:9px;height:9px;border-radius:50%;background:{color};display:inline-block;'></span>"
			f"{escape(status)}</span>"
		)


ProcessMiningView = ProcessMiningDashboardView


_PROCESS_MINING_TEMPLATE = """
{% extends "appbuilder/erp/base_erp.html" %}
{% block title %}Process Mining Timeline - {{ appbuilder.app_name }}{% endblock %}
{% block page_header %}
<div class="erp-page-header">
	<h1 class="erp-page-title">Process Mining Timeline</h1>
	<p class="erp-page-subtitle">Process instance duration by definition and status</p>
</div>
{% endblock %}
{% block content %}
<div class="erp-island">
	{{ kpi_html | safe }}
	<h3 style="margin:0 0 12px;font-size:16px;">Instance Timeline</h3>
	{{ timeline_table_html | safe }}
</div>
{% endblock %}
"""


__all__ = [
	"ProcessMiningDefinitionView",
	"ProcessMiningDashboardView",
	"ProcessMiningView",
]
