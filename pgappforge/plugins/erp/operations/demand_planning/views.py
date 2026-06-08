"""
pgappforge/plugins/erp/operations/demand_planning/views.py

Flask-AppBuilder views for the Demand Planning plugin.
"""
from __future__ import annotations

import logging

from flask import render_template
from pgappforge import ModelView, expose
from pgappforge.models.sqla.interface import SQLAInterface
from pgappforge.security.decorators import has_access

from pgappforge.plugins.erp.base_view import BaseERPView

log = logging.getLogger(__name__)


class DemandForecastView(ModelView):
	from pgappforge.plugins.erp.operations.demand_planning.models import DemandForecast
	datamodel = SQLAInterface(DemandForecast)
	list_columns = ['product_id', 'forecast_method', 'base_period', 'horizon_periods', 'status', 'accuracy_mape']
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class DemandHistoryView(ModelView):
	from pgappforge.plugins.erp.operations.demand_planning.models import DemandHistory
	datamodel = SQLAInterface(DemandHistory)
	list_columns = ['product_id', 'period', 'qty', 'source']
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class DemandPlanningDashboardView(BaseERPView):
	route_base = "/operations/demand-planning"

	@expose("/")
	@has_access
	def index(self):
		kpi_html = self.kpi_cards([
			{"label": "Active Forecasts", "value": 0, "icon": "fa-line-chart", "color": "#1a56db"},
			{"label": "Avg MAPE (%)", "value": 0, "format": "percent", "icon": "fa-bullseye", "color": "#0e9f6e"},
		])
		return render_template(
			"operations_ui/demand_planning.html",
			kpi_html=kpi_html,
			appbuilder=self.appbuilder,
		)


__all__ = [
	"DemandForecastView",
	"DemandHistoryView",
	"DemandPlanningDashboardView",
]
