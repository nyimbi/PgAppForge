"""
pgappforge/plugins/erp/crm/subscriptions/views.py

Flask-AppBuilder views for the Subscriptions plugin.
"""
from __future__ import annotations
from flask_babel import lazy_gettext as _

import logging

from flask import render_template
from pgappforge import ModelView, expose
from pgappforge.models.sqla.interface import SQLAInterface
from pgappforge.security.decorators import has_access

from pgappforge.plugins.erp.base_view import BaseERPView
from pgappforge.plugins.erp.crm.subscriptions.models import (
	Subscription,
	SubscriptionInvoice,
	SubscriptionPlan,
)

log = logging.getLogger(__name__)


class SubscriptionPlanView(ModelView):
	datamodel = SQLAInterface(SubscriptionPlan)
	list_columns = ['name', 'plan_code', 'billing_interval', 'base_price_cents', 'currency_code', 'is_active']
	label_columns = {
		'name': _('Name'),
		'plan_code': _('Plan Code'),
		'billing_interval': _('Billing Interval'),
		'base_price_cents': _('Base Price Cents'),
		'currency_code': _('Currency Code'),
		'is_active': _('Active'),
	}
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class SubscriptionView(ModelView):
	datamodel = SQLAInterface(Subscription)
	list_columns = ['customer_id', 'plan_id', 'status', 'current_period_start']
	label_columns = {
		'customer_id': _('Customer'),
		'plan_id': _('Plan'),
		'status': _('Status'),
		'current_period_start': _('Current Period Start'),
	}
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class SubscriptionInvoiceView(ModelView):
	datamodel = SQLAInterface(SubscriptionInvoice)
	list_columns = ['subscription_id', 'status', 'amount_cents', 'currency_code', 'due_date']
	label_columns = {
		'subscription_id': _('Subscription'),
		'status': _('Status'),
		'amount_cents': _('Amount Cents'),
		'currency_code': _('Currency Code'),
		'due_date': _('Due Date'),
	}
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class MRRDashboardView(BaseERPView):
	route_base = "/crm/subscriptions"

	@expose("/")
	@has_access
	def index(self):
		try:
			import sqlalchemy as sa
			sess = self._session()
			active_subs = self._count(Subscription, session=sess, status="ACTIVE")
			# MRR: sum base_price_cents of active plans linked to active subscriptions
			mrr_row = sess.execute(
				sa.select(sa.func.coalesce(sa.func.sum(SubscriptionPlan.base_price_cents), 0))
				.select_from(SubscriptionPlan)
				.join(Subscription, Subscription.plan_id == SubscriptionPlan.id)
				.where(Subscription.status == "ACTIVE")
			).scalar_one()
			mrr = int(mrr_row)
			churned = self._count(Subscription, session=sess, status="CANCELLED")
		except Exception:
			active_subs = mrr = churned = 0
		kpi_html = self.kpi_cards([
			{"label": "Active Subscriptions", "value": active_subs, "icon": "fa-repeat", "color": "#1a56db"},
			{"label": "MRR (cents)", "value": mrr, "icon": "fa-money", "color": "#0e9f6e"},
			{"label": "Churned This Month", "value": churned, "icon": "fa-sign-out", "color": "#9e1c00"},
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
