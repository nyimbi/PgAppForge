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

log = logging.getLogger(__name__)


class RepairOrderView(ModelView):
	from pgappforge.plugins.erp.operations.repair.models import RepairOrder
	datamodel = SQLAInterface(RepairOrder)
	list_columns = ['order_ref', 'customer_name', 'product_name', 'serial_number', 'status', 'assigned_technician_id', 'estimated_cost_cents']
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class WarrantyClaimView(ModelView):
	from pgappforge.plugins.erp.operations.repair.models import WarrantyClaim
	datamodel = SQLAInterface(WarrantyClaim)
	list_columns = ['repair_order_id', 'claim_ref', 'status', 'approved_amount_cents']
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class RepairOrdersDashboardView(BaseERPView):
	route_base = "/operations/repair"

	@expose("/")
	@has_access
	def index(self):
		kpi_html = self.kpi_cards([
			{"label": "Open Orders", "value": 0, "icon": "fa-wrench", "color": "#1a56db"},
			{"label": "In Progress", "value": 0, "icon": "fa-cog fa-spin", "color": "#ff5a1f"},
			{"label": "Completed Today", "value": 0, "icon": "fa-check", "color": "#0e9f6e"},
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
