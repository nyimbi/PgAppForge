"""
pgappforge/plugins/erp/platform/analytics_engine/views.py

Flask-AppBuilder views for the Analytics Engine plugin.
"""
from __future__ import annotations

import logging

from flask import render_template
from pgappforge import ModelView, expose
from pgappforge.models.sqla.interface import SQLAInterface
from pgappforge.security.decorators import has_access

from pgappforge.plugins.erp.base_view import BaseERPView
from pgappforge.plugins.erp.platform.analytics_engine.models import (
	AnalyticsCube,
	AnalyticsReport,
)

log = logging.getLogger(__name__)


class AnalyticsCubeView(ModelView):
	datamodel = SQLAInterface(AnalyticsCube)
	list_columns = ['name', 'base_query', 'refresh_schedule', 'last_refreshed', 'is_active']
	show_columns = ['tenant_id', 'name', 'base_query', 'refresh_schedule', 'last_refreshed', 'dimensions', 'measures', 'is_active']
	label_columns = {
		'tenant_id': 'Tenant',
		'name': 'Cube Name',
		'base_query': 'Base Query',
		'refresh_schedule': 'Refresh Schedule',
		'last_refreshed': 'Last Refreshed',
		'dimensions': 'Dimensions',
		'measures': 'Measures',
		'is_active': 'Active',
	}
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class AnalyticsReportView(ModelView):
	datamodel = SQLAInterface(AnalyticsReport)
	list_columns = ['name', 'cube_id', 'filters']
	show_columns = ['cube_id', 'tenant_id', 'name', 'filters', 'group_by', 'order_by', 'limit_rows', 'visualization_type']
	label_columns = {
		'cube_id': 'Cube',
		'tenant_id': 'Tenant',
		'name': 'Report Name',
		'filters': 'Filters',
		'group_by': 'Group By',
		'order_by': 'Order By',
		'limit_rows': 'Row Limit',
		'visualization_type': 'Visualization',
	}
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class AnalyticsDashboardView(BaseERPView):
	route_base = "/platform/analytics"

	@expose("/")
	@has_access
	def index(self):
		try:
			sess = self._session()
			active_cubes = self._count(AnalyticsCube, session=sess, is_active=True)
			reports = self._count(AnalyticsReport, session=sess)
		except Exception:
			active_cubes = reports = 0
		kpi_html = self.kpi_cards([
			{"label": "Active Cubes", "value": active_cubes, "icon": "fa-database", "color": "#1a56db"},
			{"label": "Reports", "value": reports, "icon": "fa-bar-chart", "color": "#0e9f6e"},
		])
		return render_template(
			"platform/analytics_dashboard.html",
			kpi_html=kpi_html,
			appbuilder=self.appbuilder,
		)


__all__ = [
	"AnalyticsCubeView",
	"AnalyticsReportView",
	"AnalyticsDashboardView",
]
