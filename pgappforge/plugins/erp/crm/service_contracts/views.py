"""
pgappforge/plugins/erp/crm/service_contracts/views.py

Flask-AppBuilder views for the Service Contracts plugin.
"""
from __future__ import annotations

import logging

from pgappforge import ModelView
from pgappforge.models.sqla.interface import SQLAInterface
from pgappforge.plugins.erp.crm.service_contracts.models import (
	ContractRenewal,
	ServiceContract,
)

log = logging.getLogger(__name__)


class ServiceContractView(ModelView):
	datamodel = SQLAInterface(ServiceContract)
	list_columns = ['contract_ref', 'customer_id', 'title', 'contract_type', 'status', 'start_date', 'end_date', 'contract_value_cents']
	label_columns = {
		'contract_ref': 'Contract Ref',
		'customer_id': 'Customer',
		'title': 'Title',
		'contract_type': 'Contract Type',
		'status': 'Status',
		'start_date': 'Start Date',
		'end_date': 'End Date',
		'contract_value_cents': 'Contract Value Cents',
	}
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class ContractRenewalView(ModelView):
	datamodel = SQLAInterface(ContractRenewal)
	list_columns = ['contract_id', 'old_end_date', 'new_end_date', 'renewal_value_cents', 'renewed_by']
	label_columns = {
		'contract_id': 'Contract',
		'old_end_date': 'Old End Date',
		'new_end_date': 'New End Date',
		'renewal_value_cents': 'Renewal Value Cents',
		'renewed_by': 'Renewed By',
	}
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


__all__ = [
	"ServiceContractView",
	"ContractRenewalView",
]
