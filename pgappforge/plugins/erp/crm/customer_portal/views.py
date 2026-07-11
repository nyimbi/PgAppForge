"""
pgappforge/plugins/erp/crm/customer_portal/views.py

Flask-AppBuilder views for the Customer Portal plugin.
"""
from __future__ import annotations
from flask_babel import lazy_gettext as _

import logging

from flask import render_template
from pgappforge import ModelView, expose
from pgappforge.models.sqla.interface import SQLAInterface
from pgappforge.security.decorators import has_access

from pgappforge.plugins.erp.base_view import BaseERPView
from pgappforge.plugins.erp.crm.customer_portal.models import CustomerPortalUser, PortalPayment

log = logging.getLogger(__name__)


class CustomerPortalUserView(ModelView):
	datamodel = SQLAInterface(CustomerPortalUser)
	list_columns = ['customer_id', 'email', 'is_active', 'last_login_at', 'failed_login_count']
	label_columns = {
		'customer_id': _('Customer'),
		'email': _('Email'),
		'is_active': _('Active'),
		'last_login_at': _('Last Login At'),
		'failed_login_count': _('Failed Login Count'),
	}
	add_exclude_columns = ['id', 'created_on', 'changed_on', 'password_hash']
	edit_exclude_columns = ['id', 'created_on', 'changed_on', 'password_hash']


class PortalPaymentView(ModelView):
	datamodel = SQLAInterface(PortalPayment)
	list_columns = ['customer_id', 'amount_cents', 'payment_method', 'reference', 'status', 'initiated_at']
	label_columns = {
		'customer_id': _('Customer'),
		'amount_cents': _('Amount Cents'),
		'payment_method': _('Payment Method'),
		'reference': _('Reference'),
		'status': _('Status'),
		'initiated_at': _('Initiated At'),
	}
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class CustomerPortalDashboardView(BaseERPView):
	route_base = "/crm/portal"

	@expose("/")
	@has_access
	def index(self):
		try:
			from pgappforge.plugins.erp.crm.customer_portal.models import CustomerPortalUser, PortalSession, PortalPayment
			sess = self._session()
			active_users = self._count(CustomerPortalUser, session=sess, is_active=True)
			active_sessions = self._count(PortalSession, session=sess, is_revoked=False)
			pending_payments = self._count(PortalPayment, session=sess, status="PENDING")
		except Exception:
			active_users = active_sessions = pending_payments = 0
		kpi_html = self.kpi_cards([
			{"label": "Active Users", "value": active_users, "icon": "fa-users", "color": "#1a56db"},
			{"label": "Active Sessions", "value": active_sessions, "icon": "fa-sign-in", "color": "#0e9f6e"},
			{"label": "Payments Today", "value": pending_payments, "icon": "fa-credit-card", "color": "#ff5a1f"},
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
