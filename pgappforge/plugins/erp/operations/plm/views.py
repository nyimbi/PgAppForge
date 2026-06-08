"""
pgappforge/plugins/erp/operations/plm/views.py

Flask-AppBuilder views for the Product Lifecycle Management plugin.
"""
from __future__ import annotations

import logging

from flask import render_template
from pgappforge import ModelView, expose
from pgappforge.models.sqla.interface import SQLAInterface
from pgappforge.security.decorators import has_access

from pgappforge.plugins.erp.base_view import BaseERPView

log = logging.getLogger(__name__)


class PlmProductView(ModelView):
	from pgappforge.plugins.erp.operations.plm.models import PlmProduct
	datamodel = SQLAInterface(PlmProduct)
	list_columns = ['name', 'product_code', 'category', 'lifecycle_stage', 'current_version']
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class PlmProductVersionView(ModelView):
	from pgappforge.plugins.erp.operations.plm.models import PlmProductVersion
	datamodel = SQLAInterface(PlmProductVersion)
	list_columns = ['product_id', 'version', 'status', 'released_at']
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class EngineeringChangeOrderView(ModelView):
	from pgappforge.plugins.erp.operations.plm.models import EngineeringChangeOrder
	datamodel = SQLAInterface(EngineeringChangeOrder)
	list_columns = ['eco_ref', 'product_id', 'title', 'status', 'priority', 'effective_date']
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class PLMDashboardView(BaseERPView):
	route_base = "/operations/plm"

	@expose("/")
	@has_access
	def index(self):
		kpi_html = self.kpi_cards([
			{"label": "Active Products", "value": 0, "icon": "fa-cube", "color": "#1a56db"},
			{"label": "Open ECOs", "value": 0, "icon": "fa-edit", "color": "#ff5a1f"},
			{"label": "Released Versions", "value": 0, "icon": "fa-tag", "color": "#0e9f6e"},
		])
		return render_template(
			"operations_ui/plm_dashboard.html",
			kpi_html=kpi_html,
			appbuilder=self.appbuilder,
		)


__all__ = [
	"PlmProductView",
	"PlmProductVersionView",
	"EngineeringChangeOrderView",
	"PLMDashboardView",
]
