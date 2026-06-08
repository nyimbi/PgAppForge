from __future__ import annotations

from pgappforge import ModelView
from pgappforge.models.sqla.interface import SQLAInterface

from pgappforge.plugins.erp.hcm.lunch.models import (
	LunchMenu,
	LunchOrder,
	LunchSupplier,
)

__all__ = [
	"LunchSupplierView",
	"LunchMenuView",
	"LunchOrderView",
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
