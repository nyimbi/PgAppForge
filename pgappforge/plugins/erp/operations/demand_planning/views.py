"""
pgappforge/plugins/erp/operations/demand_planning/views.py

Flask-AppBuilder views for the Demand Planning plugin.
"""
from __future__ import annotations

import json
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
		from pgappforge.plugins.erp.operations.demand_planning.models import DemandForecast, DemandHistory
		import sqlalchemy as _sa

		active_forecasts = self._count(DemandForecast, status="APPROVED")
		avg_mape: float = 0.0
		chart_data = {"labels": [], "actual": [], "forecast": []}
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

			period_rows = session.execute(
				_sa.select(DemandHistory.period)
				.distinct()
				.order_by(DemandHistory.period.desc())
				.limit(12)
			).all()
			periods = list(reversed([row[0] for row in period_rows if row[0]]))

			if periods:
				history_rows = session.execute(
					_sa.select(
						DemandHistory.product_id,
						DemandHistory.period,
						_sa.func.sum(DemandHistory.actual_qty).label("actual_qty"),
					)
					.where(DemandHistory.period.in_(periods))
					.group_by(DemandHistory.product_id, DemandHistory.period)
				).all()

				actual_by_period = {period: 0.0 for period in periods}
				actual_keys: set[tuple[str, str]] = set()
				product_ids: set[str] = set()
				for row in history_rows:
					product_id = str(row.product_id)
					period = str(row.period)
					actual_by_period[period] = actual_by_period.get(period, 0.0) + float(row.actual_qty or 0)
					actual_keys.add((product_id, period))
					product_ids.add(product_id)

				forecast_by_key: dict[tuple[str, str], float] = {}
				if product_ids:
					forecasts = session.execute(
						_sa.select(DemandForecast)
						.where(DemandForecast.status == "APPROVED")
						.where(DemandForecast.product_id.in_(product_ids))
						.order_by(DemandForecast.updated_at.desc())
					).scalars().all()
					for forecast in forecasts:
						for entry in forecast.periods or []:
							period = str(entry.get("period", ""))
							key = (str(forecast.product_id), period)
							if period not in periods or key not in actual_keys or key in forecast_by_key:
								continue
							forecast_by_key[key] = float(entry.get("forecast_qty") or 0)

				forecast_by_period = {period: 0.0 for period in periods}
				for (_product_id, period), forecast_qty in forecast_by_key.items():
					forecast_by_period[period] = forecast_by_period.get(period, 0.0) + forecast_qty

				chart_data = {
					"labels": periods,
					"actual": [actual_by_period.get(period, 0.0) for period in periods],
					"forecast": [forecast_by_period.get(period, 0.0) for period in periods],
				}
		except Exception:
			pass

		kpi_html = self.kpi_cards([
			{"label": "Active Forecasts", "value": active_forecasts, "icon": "fa-line-chart", "color": "#1a56db"},
			{"label": "Avg MAPE (%)", "value": avg_mape, "format": "percent", "icon": "fa-bullseye", "color": "#0e9f6e"},
		])
		return render_template(
			"operations_ui/demand_planning.html",
			kpi_html=kpi_html,
			chart_data=chart_data,
			forecast_chart_json=json.dumps(chart_data),
			forecast_chart=json.dumps(chart_data),
			appbuilder=self.appbuilder,
		)


__all__ = [
	"DemandForecastView",
	"DemandHistoryView",
	"DemandPlanningDashboardView",
]
