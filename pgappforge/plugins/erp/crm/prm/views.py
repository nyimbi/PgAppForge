"""
pgappforge/plugins/erp/crm/prm/views.py

Flask-AppBuilder views for the Partner Relationship Management plugin.
"""
from __future__ import annotations

import logging

from pgappforge import ModelView
from pgappforge.models.sqla.interface import SQLAInterface
from pgappforge.plugins.erp.crm.prm.models import (
	DealRegistration,
	MDFRequest,
	PartnerAccount,
)

log = logging.getLogger(__name__)


class PartnerAccountView(ModelView):
	datamodel = SQLAInterface(PartnerAccount)
	list_columns = ['company_name', 'partner_code', 'partner_tier', 'region', 'country_code', 'status', 'ytd_revenue_cents']
	label_columns = {
		'company_name': 'Company Name',
		'partner_code': 'Partner Code',
		'partner_tier': 'Partner Tier',
		'region': 'Region',
		'country_code': 'Country Code',
		'status': 'Status',
		'ytd_revenue_cents': 'YTD Revenue Cents',
	}
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class DealRegistrationView(ModelView):
	datamodel = SQLAInterface(DealRegistration)
	list_columns = ['partner_id', 'opportunity_name', 'customer_name', 'estimated_value_cents', 'actual_value_cents']
	label_columns = {
		'partner_id': 'Partner Id',
		'opportunity_name': 'Opportunity Name',
		'customer_name': 'Customer Name',
		'estimated_value_cents': 'Estimated Value Cents',
		'actual_value_cents': 'Actual Value Cents',
	}
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class MDFRequestView(ModelView):
	datamodel = SQLAInterface(MDFRequest)
	list_columns = ['partner_id', 'campaign_name', 'amount_requested_cents', 'approved_cents', 'period', 'status']
	label_columns = {
		'partner_id': 'Partner Id',
		'campaign_name': 'Campaign Name',
		'amount_requested_cents': 'Amount Requested Cents',
		'approved_cents': 'Approved Cents',
		'period': 'Period',
		'status': 'Status',
	}
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


__all__ = [
	"PartnerAccountView",
	"DealRegistrationView",
	"MDFRequestView",
]
