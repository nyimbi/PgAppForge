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
from pgappforge.plugins.erp.operations.plm.models import (
	EngineeringChangeOrder,
	PlmProduct,
	PlmProductVersion,
)

log = logging.getLogger(__name__)


class PlmProductView(ModelView):
	datamodel = SQLAInterface(PlmProduct)
	list_columns = ['name', 'product_code', 'category', 'lifecycle_stage', 'current_version']
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class PlmProductVersionView(ModelView):
	datamodel = SQLAInterface(PlmProductVersion)
	list_columns = ['product_id', 'version', 'status', 'released_at']
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class EngineeringChangeOrderView(ModelView):
	datamodel = SQLAInterface(EngineeringChangeOrder)
	list_columns = ['eco_ref', 'product_id', 'title', 'status', 'priority', 'effective_date']
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class PLMDashboardView(BaseERPView):
	route_base = "/operations/plm"

	@expose("/")
	@has_access
	def index(self):
		from pgappforge.plugins.erp.operations.plm.models import (
			PlmProduct,
			EngineeringChangeOrder,
			PlmProductVersion,
		)
		import sqlalchemy as _sa

		active_products = self._count(PlmProduct, lifecycle_stage="PRODUCTION")
		released_versions = self._count(PlmProductVersion, status="RELEASED")
		open_ecos: int = 0
		try:
			from flask import current_app
			session = current_app.appbuilder.get_session()
			open_ecos = session.execute(
				_sa.select(_sa.func.count()).select_from(EngineeringChangeOrder).where(
					EngineeringChangeOrder.status.notin_(["IMPLEMENTED", "REJECTED"]),
				)
			).scalar_one() or 0
		except Exception:
			pass

		kpi_html = self.kpi_cards([
			{"label": "Active Products", "value": active_products, "icon": "fa-cube", "color": "#1a56db"},
			{"label": "Open ECOs", "value": open_ecos, "icon": "fa-edit", "color": "#ff5a1f"},
			{"label": "Released Versions", "value": released_versions, "icon": "fa-tag", "color": "#0e9f6e"},
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
