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
from pgappforge.plugins.erp.operations.demand_planning.models import (
	DemandForecast,
	DemandHistory,
)

log = logging.getLogger(__name__)


class DemandForecastView(ModelView):
	datamodel = SQLAInterface(DemandForecast)
	list_columns = ['product_id', 'forecast_method', 'base_period', 'horizon_periods', 'status', 'accuracy_mape']
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class DemandHistoryView(ModelView):
	datamodel = SQLAInterface(DemandHistory)
	list_columns = ['product_id', 'period', 'qty', 'source']
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class DemandPlanningDashboardView(BaseERPView):
	route_base = "/operations/demand-planning"

	@expose("/")
	@has_access
	def index(self):
		from pgappforge.plugins.erp.operations.demand_planning.models import DemandForecast
		import sqlalchemy as _sa

		active_forecasts = self._count(DemandForecast, status="APPROVED")
		avg_mape: float = 0.0
		try:
			from flask import current_app
			session = current_app.appbuilder.get_session()
			val = session.execute(
				_sa.select(_sa.func.avg(DemandForecast.accuracy_mape)).select_from(
					DemandForecast
				).where(
					DemandForecast.status == "APPROVED",
					DemandForecast.accuracy_mape.isnot(None),
				)
			).scalar()
			avg_mape = float(val or 0)
		except Exception:
			pass

		kpi_html = self.kpi_cards([
			{"label": "Active Forecasts", "value": active_forecasts, "icon": "fa-line-chart", "color": "#1a56db"},
			{"label": "Avg MAPE (%)", "value": avg_mape, "format": "percent", "icon": "fa-bullseye", "color": "#0e9f6e"},
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
