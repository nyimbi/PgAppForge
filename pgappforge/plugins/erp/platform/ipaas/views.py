"""
pgappforge/plugins/erp/platform/ipaas/views.py

Flask-AppBuilder views for the iPaaS Integration plugin.
"""
from __future__ import annotations
from flask_babel import lazy_gettext as _

import logging

from datetime import datetime, timedelta, timezone

import sqlalchemy as sa
from flask import render_template_string, request
from markupsafe import Markup, escape
from pgappforge import ModelView, expose
from pgappforge.models.sqla.interface import SQLAInterface
from pgappforge.security.decorators import has_access

try:
	from pgappforge.plugins.erp.base import BaseERPView
except ImportError:  # pragma: no cover - compatibility for current package layout
	from pgappforge.plugins.erp.base_view import BaseERPView
from pgappforge.plugins.erp.platform.ipaas.models import (
	ConnectorDefinition,
	ConnectorInstance,
	IntegrationFlow,
	IntegrationRun,
)

log = logging.getLogger(__name__)


class ConnectorDefinitionView(ModelView):
	datamodel = SQLAInterface(ConnectorDefinition)
	list_columns = ['name', 'version', 'protocol', 'auth_type', 'is_builtin']
	show_columns = ['name', 'version', 'protocol', 'auth_type', 'config_schema', 'is_builtin']
	label_columns = {
		'name': _('Connector'),
		'version': _('Version'),
		'protocol': _('Protocol'),
		'auth_type': _('Auth Type'),
		'config_schema': _('Configuration Schema'),
		'is_builtin': _('Built In'),
	}
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class ConnectorInstanceView(ModelView):
	datamodel = SQLAInterface(ConnectorInstance)
	list_columns = ['definition_id', 'name', 'status', 'last_sync_at']
	show_columns = ['definition_id', 'tenant_id', 'name', 'config', 'status', 'last_sync_at']
	label_columns = {
		'definition_id': _('Connector Definition'),
		'tenant_id': _('Tenant'),
		'name': _('Instance'),
		'config': _('Configuration'),
		'status': _('Status'),
		'last_sync_at': _('Last Sync'),
	}
	add_exclude_columns = ['id', 'created_on', 'changed_on', 'config_encrypted']
	edit_exclude_columns = ['id', 'created_on', 'changed_on', 'config_encrypted']


class IntegrationFlowView(ModelView):
	datamodel = SQLAInterface(IntegrationFlow)
	list_columns = ['name', 'trigger_type', 'source_connector_id', 'target_connector_id', 'is_active']
	show_columns = [
		'tenant_id',
		'name',
		'trigger_type',
		'source_connector_id',
		'target_connector_id',
		'mapping',
		'is_active',
	]
	label_columns = {
		'tenant_id': _('Tenant'),
		'name': _('Flow Name'),
		'trigger_type': _('Trigger'),
		'source_connector_id': _('Source'),
		'target_connector_id': _('Destination'),
		'mapping': _('Field Mapping'),
		'is_active': _('Active'),
	}
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class IPaaSFlowsDashboardView(BaseERPView):
	route_base = "/platform/ipaas"

	@expose("/")
	@has_access
	def index(self):
		sess = self._session()
		flows: list[IntegrationFlow] = []
		latest_runs: dict[str, IntegrationRun] = {}
		connector_names: dict[str, str] = {}
		try:
			cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
			total_flows = self._scalar_count(sess, IntegrationFlow)
			active_flows = self._scalar_count(
				sess,
				IntegrationFlow,
				IntegrationFlow.is_active.is_(True),
			)
			failed_runs = self._scalar_count(
				sess,
				IntegrationRun,
				IntegrationRun.status == "FAILED",
				IntegrationRun.started_at >= cutoff,
			)
			connectors = self._scalar_count(sess, ConnectorInstance)
			flows = list(
				sess.execute(
					sa.select(IntegrationFlow)
					.order_by(IntegrationFlow.name)
					.limit(50)
				).scalars()
			)
			connector_names = self._connector_names(sess, flows)
			latest_runs = self._latest_runs(sess, flows)
		except Exception:
			log.exception("IPaaSFlowsDashboardView.index: failed to load dashboard data")
			total_flows = active_flows = connectors = failed_runs = 0
		kpi_html = self.kpi_cards([
			{"label": "Total Flows", "value": total_flows, "icon": "fa-random", "color": "#374151"},
			{"label": "Active Flows", "value": active_flows, "icon": "fa-exchange", "color": "#1a56db"},
			{"label": "Connectors", "value": connectors, "icon": "fa-plug", "color": "#0e9f6e"},
			{"label": "Failed Runs (24h)", "value": failed_runs, "icon": "fa-times-circle", "color": "#9e1c00"},
		])
		status_table_html = self._status_table(flows, connector_names, latest_runs)
		return render_template_string(
			_IPAAS_DASHBOARD_TEMPLATE,
			kpi_html=kpi_html,
			status_table_html=status_table_html,
			canvas_url="canvas",
			appbuilder=self.appbuilder,
		)

	@expose("/canvas")
	@has_access
	def integration_canvas(self):
		sess = self._session()
		flow_id = (request.args.get("flow_id") or "").strip()
		try:
			stmt = sa.select(IntegrationFlow).order_by(IntegrationFlow.name)
			if flow_id:
				stmt = stmt.where(IntegrationFlow.id == flow_id)
			flows = list(sess.execute(stmt.limit(50)).scalars())
			connector_names = self._connector_names(sess, flows)
			canvas_html = self._canvas(flows, connector_names)
		except Exception:
			log.exception("IPaaSFlowsDashboardView.integration_canvas: failed to load canvas")
			canvas_html = Markup("<p class='text-muted'>No integration canvas data is available.</p>")
		return render_template_string(
			_IPAAS_CANVAS_TEMPLATE,
			canvas_html=canvas_html,
			appbuilder=self.appbuilder,
		)

	@staticmethod
	def _scalar_count(session, model, *criteria) -> int:
		stmt = sa.select(sa.func.count()).select_from(model)
		if criteria:
			stmt = stmt.where(*criteria)
		return int(session.execute(stmt).scalar_one() or 0)

	@staticmethod
	def _connector_names(session, flows: list[IntegrationFlow]) -> dict[str, str]:
		connector_ids = {
			connector_id
			for flow in flows
			for connector_id in (flow.source_connector_id, flow.target_connector_id)
			if connector_id
		}
		if not connector_ids:
			return {}
		rows = session.execute(
			sa.select(ConnectorInstance.id, ConnectorInstance.name)
			.where(ConnectorInstance.id.in_(connector_ids))
		).all()
		return {row.id: row.name for row in rows}

	@staticmethod
	def _latest_runs(session, flows: list[IntegrationFlow]) -> dict[str, IntegrationRun]:
		flow_ids = [flow.id for flow in flows if flow.id]
		if not flow_ids:
			return {}
		runs = session.execute(
			sa.select(IntegrationRun)
			.where(IntegrationRun.flow_id.in_(flow_ids))
			.order_by(IntegrationRun.started_at.desc())
		).scalars()
		latest: dict[str, IntegrationRun] = {}
		for run in runs:
			latest.setdefault(run.flow_id, run)
		return latest

	def _status_table(
		self,
		flows: list[IntegrationFlow],
		connector_names: dict[str, str],
		latest_runs: dict[str, IntegrationRun],
	) -> Markup:
		rows: list[str] = []
		for flow in flows:
			run = latest_runs.get(flow.id)
			source = connector_names.get(flow.source_connector_id, flow.source_connector_id or "-")
			destination = connector_names.get(flow.target_connector_id, flow.target_connector_id or "-")
			status = self._flow_status(flow, run)
			last_run = self._format_dt(getattr(run, "completed_at", None) or getattr(run, "started_at", None))
			rows.append(
				"<tr>"
				f"<td>{escape(flow.name or '-')}</td>"
				f"<td>{escape(source)}</td>"
				f"<td>{escape(destination)}</td>"
				f"<td>{escape(last_run)}</td>"
				f"<td>{self._status_badge(status)}</td>"
				"</tr>"
			)
		if not rows:
			rows.append("<tr><td colspan='5' class='text-center text-muted'>No integration flows configured.</td></tr>")
		return Markup(
			"<div class='table-responsive'>"
			"<table class='table table-striped table-condensed'>"
			"<thead><tr><th>Flow name</th><th>Source</th><th>Destination</th><th>Last run</th><th>Status</th></tr></thead>"
			f"<tbody>{''.join(rows)}</tbody>"
			"</table></div>"
		)

	def _canvas(self, flows: list[IntegrationFlow], connector_names: dict[str, str]) -> Markup:
		lines: list[Markup] = []
		for flow in flows:
			source = connector_names.get(flow.source_connector_id, flow.source_connector_id or "Source")
			destination = connector_names.get(flow.target_connector_id, flow.target_connector_id or "Destination")
			lines.append(
				Markup(
					f"{escape(flow.name or 'Unnamed flow')}\n"
					f"  {escape(source)} &rarr; [Mapper] &rarr; [Filter] &rarr; {escape(destination)}"
				)
			)
		if not lines:
			return Markup("<p class='text-muted'>No integration flows configured.</p>")
		body = Markup("\n\n").join(lines)
		return Markup(
			"<pre style='white-space:pre-wrap;background:#f8fafc;border:1px solid #e5e7eb;"
			"border-radius:6px;padding:16px;font-size:13px;line-height:1.7;'>"
		) + body + Markup("</pre>")

	@staticmethod
	def _flow_status(flow: IntegrationFlow, run: IntegrationRun | None) -> str:
		if run is not None and str(run.status or "").upper() == "FAILED":
			return "FAILED"
		if getattr(flow, "is_active", False):
			return "ACTIVE"
		return "INACTIVE"

	@staticmethod
	def _format_dt(value) -> str:
		if value is None:
			return "Never"
		if hasattr(value, "strftime"):
			return value.strftime("%Y-%m-%d %H:%M")
		return str(value)

	@staticmethod
	def _status_badge(status: str) -> Markup:
		styles = {
			"ACTIVE": ("Active", "#0e9f6e"),
			"FAILED": ("Failed", "#9e1c00"),
			"INACTIVE": ("Inactive", "#6b7280"),
		}
		label, color = styles.get(status.upper(), (status.title(), "#6b7280"))
		return Markup(
			f"<span style='display:inline-block;border-radius:999px;padding:2px 9px;"
			f"font-size:11px;font-weight:700;color:#fff;background:{color};'>{escape(label)}</span>"
		)


_IPAAS_DASHBOARD_TEMPLATE = """
{% extends "appbuilder/erp/base_erp.html" %}
{% block title %}iPaaS Integration Flows - {{ appbuilder.app_name }}{% endblock %}
{% block page_header %}
<div class="erp-page-header">
	<h1 class="erp-page-title">iPaaS Integration Flows</h1>
	<p class="erp-page-subtitle">Connector flow health, recent run status, and canvas preview</p>
</div>
{% endblock %}
{% block content %}
<div class="erp-island">
	{{ kpi_html | safe }}
	<div style="display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;margin-bottom:10px;">
		<h3 style="margin:0;font-size:16px;">Flow Status</h3>
		<a class="btn btn-default btn-sm" href="{{ canvas_url }}"><i class="fa fa-project-diagram"></i> Integration Canvas</a>
	</div>
	{{ status_table_html | safe }}
</div>
{% endblock %}
"""


_IPAAS_CANVAS_TEMPLATE = """
{% extends "appbuilder/erp/base_erp.html" %}
{% block title %}iPaaS Integration Canvas - {{ appbuilder.app_name }}{% endblock %}
{% block page_header %}
<div class="erp-page-header">
	<h1 class="erp-page-title">iPaaS Integration Canvas</h1>
	<p class="erp-page-subtitle">Text flow visualizer for source, mapping, filters, and destination</p>
</div>
{% endblock %}
{% block content %}
<div class="erp-island">
	{{ canvas_html | safe }}
</div>
{% endblock %}
"""


__all__ = [
	"ConnectorDefinitionView",
	"ConnectorInstanceView",
	"IntegrationFlowView",
	"IPaaSFlowsDashboardView",
]
