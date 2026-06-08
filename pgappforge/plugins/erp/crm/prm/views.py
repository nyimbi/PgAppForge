"""
pgappforge/plugins/erp/crm/prm/views.py

Flask-AppBuilder views for the Partner Relationship Management plugin.
"""
from __future__ import annotations

import logging

from pgappforge import ModelView
from pgappforge.models.sqla.interface import SQLAInterface

log = logging.getLogger(__name__)


class PartnerAccountView(ModelView):
	from pgappforge.plugins.erp.crm.prm.models import PartnerAccount
	datamodel = SQLAInterface(PartnerAccount)
	list_columns = ['company_name', 'partner_code', 'partner_tier', 'region', 'country_code', 'status', 'ytd_revenue_cents']
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class DealRegistrationView(ModelView):
	from pgappforge.plugins.erp.crm.prm.models import DealRegistration
	datamodel = SQLAInterface(DealRegistration)
	list_columns = ['partner_id', 'opportunity_name', 'customer_name', 'estimated_value_cents', 'actual_value_cents']
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class MDFRequestView(ModelView):
	from pgappforge.plugins.erp.crm.prm.models import MDFRequest
	datamodel = SQLAInterface(MDFRequest)
	list_columns = ['partner_id', 'amount_cents', 'status']
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


__all__ = [
	"PartnerAccountView",
	"DealRegistrationView",
	"MDFRequestView",
]
