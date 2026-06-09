"""
pgappforge/plugins/erp/platform/ipaas/views.py

Flask-AppBuilder views for the iPaaS Integration plugin.
"""
from __future__ import annotations

import logging

from flask import render_template
from pgappforge import ModelView, expose
from pgappforge.models.sqla.interface import SQLAInterface
from pgappforge.security.decorators import has_access

from pgappforge.plugins.erp.base_view import BaseERPView
from pgappforge.plugins.erp.platform.ipaas.models import (
	ConnectorDefinition,
	ConnectorInstance,
	IntegrationFlow,
)

log = logging.getLogger(__name__)


class ConnectorDefinitionView(ModelView):
	datamodel = SQLAInterface(ConnectorDefinition)
	list_columns = ['name', 'version', 'protocol', 'auth_type', 'is_active']
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class ConnectorInstanceView(ModelView):
	datamodel = SQLAInterface(ConnectorInstance)
	list_columns = ['definition_id', 'name', 'status', 'last_sync_at']
	add_exclude_columns = ['id', 'created_on', 'changed_on', 'config_encrypted']
	edit_exclude_columns = ['id', 'created_on', 'changed_on', 'config_encrypted']


class IntegrationFlowView(ModelView):
	datamodel = SQLAInterface(IntegrationFlow)
	list_columns = ['name', 'source_connector_id', 'target_connector_id', 'status', 'schedule']
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class IPaaSFlowsDashboardView(BaseERPView):
	route_base = "/platform/ipaas"

	@expose("/")
	@has_access
	def index(self):
		try:
			from pgappforge.plugins.erp.platform.ipaas.models import IntegrationFlow, ConnectorInstance, IntegrationRun
			sess = self._session()
			active_flows = self._count(IntegrationFlow, session=sess, is_active=True)
			connectors = self._count(ConnectorInstance, session=sess, status="ACTIVE")
			failed_runs = self._count(IntegrationRun, session=sess, status="FAILED")
		except Exception:
			active_flows = connectors = failed_runs = 0
		kpi_html = self.kpi_cards([
			{"label": "Active Flows", "value": active_flows, "icon": "fa-exchange", "color": "#1a56db"},
			{"label": "Connectors", "value": connectors, "icon": "fa-plug", "color": "#0e9f6e"},
			{"label": "Failed Runs (24h)", "value": failed_runs, "icon": "fa-times-circle", "color": "#9e1c00"},
		])
		return render_template(
			"platform_admin/ipaas_flows.html",
			kpi_html=kpi_html,
			appbuilder=self.appbuilder,
		)


__all__ = [
	"ConnectorDefinitionView",
	"ConnectorInstanceView",
	"IntegrationFlowView",
	"IPaaSFlowsDashboardView",
]
