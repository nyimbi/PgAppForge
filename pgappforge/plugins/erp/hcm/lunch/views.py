from __future__ import annotations

from flask import render_template
from pgappforge import ModelView, expose, has_access
from pgappforge.models.sqla.interface import SQLAInterface

from pgappforge.plugins.erp.base_view import BaseERPView
from pgappforge.plugins.erp.hcm.lunch.models import (
	LunchMenu,
	LunchOrder,
	LunchSupplier,
)

__all__ = [
	"LunchSupplierView",
	"LunchMenuView",
	"LunchOrderView",
	"LunchDashboardView",
]


class LunchSupplierView(ModelView):
	datamodel = SQLAInterface(LunchSupplier)
	list_columns = ["name", "contact_email", "contact_phone", "is_active"]
	add_exclude_columns = ["id", "created_on", "changed_on", "menus"]
	edit_exclude_columns = ["id", "created_on", "changed_on", "menus"]
	search_columns = ["name"]


class LunchMenuView(ModelView):
	datamodel = SQLAInterface(LunchMenu)
	list_columns = ["supplier", "menu_date", "status", "cutoff_time"]
	add_exclude_columns = ["id", "created_on", "changed_on", "orders"]
	edit_exclude_columns = ["id", "created_on", "changed_on", "orders"]
	search_columns = ["menu_date", "status"]


class LunchOrderView(ModelView):
	datamodel = SQLAInterface(LunchOrder)
	list_columns = ["employee_id", "menu", "order_date", "subtotal_cents", "subsidy_cents", "status"]
	add_exclude_columns = ["id", "created_on", "changed_on"]
	edit_exclude_columns = ["id", "created_on", "changed_on"]
	search_columns = ["employee_id", "status"]


class LunchDashboardView(BaseERPView):
	route_base = "/hcm/lunch"

	@expose("/")
	@has_access
	def index(self):
		try:
			from pgappforge.plugins.erp.hcm.lunch.models import (
				LunchMenu,
				LunchOrder,
				LunchSupplier,
			)
			sess = self._session()
			active_suppliers = self._count(LunchSupplier, session=sess, is_active=True)
			published_menus = self._count(LunchMenu, session=sess, status="PUBLISHED")
			placed_orders = self._count(LunchOrder, session=sess, status="PLACED")
		except Exception:
			active_suppliers = published_menus = placed_orders = 0
		kpi_html = self.kpi_cards([
			{"label": "Active Suppliers", "value": active_suppliers, "icon": "fa-store", "color": "#1a56db"},
			{"label": "Published Menus", "value": published_menus, "icon": "fa-utensils", "color": "#0e9f6e"},
			{"label": "Orders Placed", "value": placed_orders, "icon": "fa-shopping-cart", "color": "#f59e0b"},
		])
		return render_template(
			"appbuilder/hcm_lunch/lunch_dashboard.html",
			kpi_html=kpi_html,
			appbuilder=self.appbuilder,
		)
