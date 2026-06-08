"""
pgappforge/plugins/erp/operations/rental/views.py

Flask-AppBuilder views for the Rental plugin.
"""
from __future__ import annotations

import logging

from flask import render_template
from pgappforge import ModelView, expose
from pgappforge.models.sqla.interface import SQLAInterface
from pgappforge.security.decorators import has_access

from pgappforge.plugins.erp.base_view import BaseERPView

log = logging.getLogger(__name__)


class RentalAssetView(ModelView):
	from pgappforge.plugins.erp.operations.rental.models import RentalAsset
	datamodel = SQLAInterface(RentalAsset)
	list_columns = ['name', 'asset_code', 'category', 'status', 'daily_rate_cents', 'condition_rating']
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class RentalOrderView(ModelView):
	from pgappforge.plugins.erp.operations.rental.models import RentalOrder
	datamodel = SQLAInterface(RentalOrder)
	list_columns = ['order_ref', 'customer_id', 'asset_id', 'status', 'rental_start', 'rental_end', 'total_amount_cents']
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class RentalOrdersDashboardView(BaseERPView):
	route_base = "/operations/rental"

	@expose("/")
	@has_access
	def index(self):
		kpi_html = self.kpi_cards([
			{"label": "Active Rentals", "value": 0, "icon": "fa-cubes", "color": "#1a56db"},
			{"label": "Available Assets", "value": 0, "icon": "fa-check-square", "color": "#0e9f6e"},
			{"label": "Overdue Returns", "value": 0, "icon": "fa-clock-o", "color": "#9e1c00"},
		])
		return render_template(
			"operations_ui/rental_orders.html",
			kpi_html=kpi_html,
			appbuilder=self.appbuilder,
		)


__all__ = [
	"RentalAssetView",
	"RentalOrderView",
	"RentalOrdersDashboardView",
]
