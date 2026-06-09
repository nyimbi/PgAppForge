"""
pgappforge/plugins/erp/operations/mrp/views.py

Flask-AppBuilder views for the MRP plugin.
"""
from __future__ import annotations

import logging

from flask import render_template
from pgappforge import ModelView, expose
from pgappforge.models.sqla.interface import SQLAInterface
from pgappforge.security.decorators import has_access

from pgappforge.plugins.erp.base_view import BaseERPView
from pgappforge.plugins.erp.operations.mrp.models import (
	MRPProductConfig,
	MRPPlannedOrder,
	MRPRun,
)

log = logging.getLogger(__name__)


class MRPProductConfigView(ModelView):
	datamodel = SQLAInterface(MRPProductConfig)
	list_columns = ['product_id', 'reorder_point', 'safety_stock', 'lot_size', 'lead_time_days']
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class MRPPlannedOrderView(ModelView):
	datamodel = SQLAInterface(MRPPlannedOrder)
	list_columns = ['product_id', 'qty', 'planned_date', 'order_type', 'status']
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class MRPRunView(ModelView):
	datamodel = SQLAInterface(MRPRun)
	list_columns = ['period', 'horizon_days', 'status', 'started_at', 'completed_at', 'planned_orders_count']
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class MRPDashboardView(BaseERPView):
	route_base = "/operations/mrp"

	@expose("/")
	@has_access
	def index(self):
		import sqlalchemy as _sa
		from datetime import date as _date

		planned_orders = self._count(MRPPlannedOrder, status="PLANNED")
		open_runs = self._count(MRPRun, status="IN_PROGRESS")
		overdue_orders: int = 0
		try:
			from flask import current_app
			session = current_app.appbuilder.get_session()
			overdue_orders = session.execute(
				_sa.select(_sa.func.count()).select_from(MRPPlannedOrder).where(
					MRPPlannedOrder.status == "PLANNED",
					MRPPlannedOrder.required_date < _date.today(),
				)
			).scalar_one() or 0
		except Exception:
			pass

		kpi_html = self.kpi_cards([
			{"label": "Planned Orders", "value": planned_orders, "icon": "fa-cogs", "color": "#1a56db"},
			{"label": "Open MRP Runs", "value": open_runs, "icon": "fa-refresh", "color": "#0e9f6e"},
			{"label": "Overdue Orders", "value": overdue_orders, "icon": "fa-exclamation-triangle", "color": "#9e1c00"},
		])
		return render_template(
			"operations_ui/mrp_dashboard.html",
			kpi_html=kpi_html,
			appbuilder=self.appbuilder,
		)


__all__ = [
	"MRPProductConfigView",
	"MRPPlannedOrderView",
	"MRPRunView",
	"MRPDashboardView",
]
