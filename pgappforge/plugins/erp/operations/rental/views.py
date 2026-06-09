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
from pgappforge.plugins.erp.operations.rental.models import RentalAsset, RentalOrder

log = logging.getLogger(__name__)


class RentalAssetView(ModelView):
	datamodel = SQLAInterface(RentalAsset)
	list_columns = ['name', 'asset_code', 'category', 'status', 'daily_rate_cents', 'condition_rating']
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class RentalOrderView(ModelView):
	datamodel = SQLAInterface(RentalOrder)
	list_columns = ['order_ref', 'customer_id', 'asset_id', 'status', 'rental_start', 'rental_end', 'total_amount_cents']
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class RentalOrdersDashboardView(BaseERPView):
	route_base = "/operations/rental"

	@expose("/")
	@has_access
	def index(self):
		from pgappforge.plugins.erp.operations.rental.models import RentalOrder, RentalAsset
		import sqlalchemy as _sa

		active_rentals = self._count(RentalOrder, status="ACTIVE")
		available_assets = self._count(RentalAsset, status="AVAILABLE")
		overdue_returns: int = 0
		try:
			from flask import current_app
			from datetime import date as _date
			session = current_app.appbuilder.get_session()
			overdue_returns = session.execute(
				_sa.select(_sa.func.count()).select_from(RentalOrder).where(
					RentalOrder.status == "ACTIVE",
					RentalOrder.end_date < _date.today(),
					RentalOrder.actual_return_date.is_(None),
				)
			).scalar_one() or 0
		except Exception:
			pass

		kpi_html = self.kpi_cards([
			{"label": "Active Rentals", "value": active_rentals, "icon": "fa-cubes", "color": "#1a56db"},
			{"label": "Available Assets", "value": available_assets, "icon": "fa-check-square", "color": "#0e9f6e"},
			{"label": "Overdue Returns", "value": overdue_returns, "icon": "fa-clock-o", "color": "#9e1c00"},
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
