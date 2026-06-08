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

log = logging.getLogger(__name__)


class AnalyticsCubeView(ModelView):
	from pgappforge.plugins.erp.platform.analytics_engine.models import AnalyticsCube
	datamodel = SQLAInterface(AnalyticsCube)
	list_columns = ['name', 'base_query', 'refresh_schedule', 'last_refreshed', 'is_active']
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class AnalyticsReportView(ModelView):
	from pgappforge.plugins.erp.platform.analytics_engine.models import AnalyticsReport
	datamodel = SQLAInterface(AnalyticsReport)
	list_columns = ['name', 'cube_id', 'filters']
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class AnalyticsDashboardView(BaseERPView):
	route_base = "/platform/analytics"

	@expose("/")
	@has_access
	def index(self):
		kpi_html = self.kpi_cards([
			{"label": "Active Cubes", "value": 0, "icon": "fa-database", "color": "#1a56db"},
			{"label": "Reports", "value": 0, "icon": "fa-bar-chart", "color": "#0e9f6e"},
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
