"""
pgappforge/plugins/erp/operations/repair/views.py

Flask-AppBuilder views for the Repair & RMA plugin.
"""
from __future__ import annotations

import logging

from flask import render_template
from pgappforge import ModelView, expose
from pgappforge.models.sqla.interface import SQLAInterface
from pgappforge.security.decorators import has_access

from pgappforge.plugins.erp.base_view import BaseERPView
from pgappforge.plugins.erp.operations.repair.models import RepairOrder, WarrantyClaim

log = logging.getLogger(__name__)


class RepairOrderView(ModelView):
	datamodel = SQLAInterface(RepairOrder)
	list_columns = ['order_ref', 'customer_name', 'product_name', 'serial_number', 'status', 'assigned_technician_id', 'estimated_cost_cents']
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class WarrantyClaimView(ModelView):
	datamodel = SQLAInterface(WarrantyClaim)
	list_columns = ['repair_order_id', 'claim_ref', 'status', 'approved_amount_cents']
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class RepairOrdersDashboardView(BaseERPView):
	route_base = "/operations/repair"

	@expose("/")
	@has_access
	def index(self):
		from pgappforge.plugins.erp.operations.repair.models import RepairOrder
		import sqlalchemy as _sa

		in_progress = self._count(RepairOrder, status="IN_REPAIR")
		completed_today: int = 0
		open_orders: int = 0
		try:
			from flask import current_app
			from datetime import date as _date
			session = current_app.appbuilder.get_session()
			open_orders = session.execute(
				_sa.select(_sa.func.count()).select_from(RepairOrder).where(
					RepairOrder.status.notin_(["RETURNED", "CANCELLED"]),
				)
			).scalar_one() or 0
			today = _date.today()
			completed_today = session.execute(
				_sa.select(_sa.func.count()).select_from(RepairOrder).where(
					RepairOrder.status == "RETURNED",
					_sa.func.date(RepairOrder.returned_at) == today,
				)
			).scalar_one() or 0
		except Exception:
			pass

		kpi_html = self.kpi_cards([
			{"label": "Open Orders", "value": open_orders, "icon": "fa-wrench", "color": "#1a56db"},
			{"label": "In Progress", "value": in_progress, "icon": "fa-cog fa-spin", "color": "#ff5a1f"},
			{"label": "Completed Today", "value": completed_today, "icon": "fa-check", "color": "#0e9f6e"},
		])
		return render_template(
			"operations_ui/repair_orders.html",
			kpi_html=kpi_html,
			appbuilder=self.appbuilder,
		)


__all__ = [
	"RepairOrderView",
	"WarrantyClaimView",
	"RepairOrdersDashboardView",
]
