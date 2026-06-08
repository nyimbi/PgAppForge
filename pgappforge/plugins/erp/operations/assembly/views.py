"""
pgappforge/plugins/erp/operations/assembly/views.py

Flask-AppBuilder views for the Assembly plugin.
"""
from __future__ import annotations

import logging

from flask import render_template
from pgappforge import ModelView, expose
from pgappforge.models.sqla.interface import SQLAInterface
from pgappforge.security.decorators import has_access

from pgappforge.plugins.erp.base_view import BaseERPView

log = logging.getLogger(__name__)


class AssemblyOrderView(ModelView):
	from pgappforge.plugins.erp.operations.assembly.models import AssemblyOrder
	datamodel = SQLAInterface(AssemblyOrder)
	list_columns = ['output_product_id', 'output_qty', 'status', 'planned_date', 'standard_cost_cents', 'actual_cost_cents']
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class AssemblyLineView(ModelView):
	from pgappforge.plugins.erp.operations.assembly.models import AssemblyLine
	datamodel = SQLAInterface(AssemblyLine)
	list_columns = ['name', 'code', 'status', 'capacity_units_per_hour']
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class AssemblyOrdersDashboardView(BaseERPView):
	route_base = "/operations/assembly"

	@expose("/")
	@has_access
	def index(self):
		kpi_html = self.kpi_cards([
			{"label": "Open Orders", "value": 0, "icon": "fa-puzzle-piece", "color": "#1a56db"},
			{"label": "In Progress", "value": 0, "icon": "fa-cog", "color": "#ff5a1f"},
			{"label": "Completed Today", "value": 0, "icon": "fa-check", "color": "#0e9f6e"},
		])
		return render_template(
			"operations_ui/assembly_orders.html",
			kpi_html=kpi_html,
			appbuilder=self.appbuilder,
		)


__all__ = [
	"AssemblyOrderView",
	"AssemblyLineView",
	"AssemblyOrdersDashboardView",
]
