"""
pgappforge/plugins/erp/crm/customer_portal/views.py

Flask-AppBuilder views for the Customer Portal plugin.
"""
from __future__ import annotations

import logging

from flask import render_template
from pgappforge import ModelView, expose
from pgappforge.models.sqla.interface import SQLAInterface
from pgappforge.security.decorators import has_access

from pgappforge.plugins.erp.base_view import BaseERPView

log = logging.getLogger(__name__)


class CustomerPortalUserView(ModelView):
	from pgappforge.plugins.erp.crm.customer_portal.models import CustomerPortalUser
	datamodel = SQLAInterface(CustomerPortalUser)
	list_columns = ['customer_id', 'email', 'is_active', 'last_login_at', 'failed_login_count']
	add_exclude_columns = ['id', 'created_on', 'changed_on', 'password_hash']
	edit_exclude_columns = ['id', 'created_on', 'changed_on', 'password_hash']


class PortalPaymentView(ModelView):
	from pgappforge.plugins.erp.crm.customer_portal.models import PortalPayment
	datamodel = SQLAInterface(PortalPayment)
	list_columns = ['customer_id', 'amount_cents', 'payment_method', 'reference', 'status', 'initiated_at']
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class CustomerPortalDashboardView(BaseERPView):
	route_base = "/crm/portal"

	@expose("/")
	@has_access
	def index(self):
		kpi_html = self.kpi_cards([
			{"label": "Active Users", "value": 0, "icon": "fa-users", "color": "#1a56db"},
			{"label": "Active Sessions", "value": 0, "icon": "fa-sign-in", "color": "#0e9f6e"},
			{"label": "Payments Today", "value": 0, "icon": "fa-credit-card", "color": "#ff5a1f"},
		])
		return render_template(
			"crm_portal/customer_portal.html",
			kpi_html=kpi_html,
			appbuilder=self.appbuilder,
		)


__all__ = [
	"CustomerPortalUserView",
	"PortalPaymentView",
	"CustomerPortalDashboardView",
]
