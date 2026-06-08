"""
pgappforge/plugins/erp/crm/subscriptions/views.py

Flask-AppBuilder views for the Subscriptions plugin.
"""
from __future__ import annotations

import logging

from flask import render_template
from pgappforge import ModelView, expose
from pgappforge.models.sqla.interface import SQLAInterface
from pgappforge.security.decorators import has_access

from pgappforge.plugins.erp.base_view import BaseERPView

log = logging.getLogger(__name__)


class SubscriptionPlanView(ModelView):
	from pgappforge.plugins.erp.crm.subscriptions.models import SubscriptionPlan
	datamodel = SQLAInterface(SubscriptionPlan)
	list_columns = ['name', 'plan_code', 'billing_interval', 'base_price_cents', 'currency_code', 'is_active']
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class SubscriptionView(ModelView):
	from pgappforge.plugins.erp.crm.subscriptions.models import Subscription
	datamodel = SQLAInterface(Subscription)
	list_columns = ['customer_id', 'plan_id', 'status', 'current_period_start']
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class SubscriptionInvoiceView(ModelView):
	from pgappforge.plugins.erp.crm.subscriptions.models import SubscriptionInvoice
	datamodel = SQLAInterface(SubscriptionInvoice)
	list_columns = ['subscription_id', 'status', 'amount_cents', 'currency_code', 'due_date']
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class MRRDashboardView(BaseERPView):
	route_base = "/crm/subscriptions"

	@expose("/")
	@has_access
	def index(self):
		kpi_html = self.kpi_cards([
			{"label": "Active Subscriptions", "value": 0, "icon": "fa-repeat", "color": "#1a56db"},
			{"label": "MRR (cents)", "value": 0, "icon": "fa-money", "color": "#0e9f6e"},
			{"label": "Churned This Month", "value": 0, "icon": "fa-sign-out", "color": "#9e1c00"},
		])
		return render_template(
			"crm_subs/mrr_dashboard.html",
			kpi_html=kpi_html,
			appbuilder=self.appbuilder,
		)


__all__ = [
	"SubscriptionPlanView",
	"SubscriptionView",
	"SubscriptionInvoiceView",
	"MRRDashboardView",
]
