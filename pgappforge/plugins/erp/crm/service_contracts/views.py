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
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class ContractRenewalView(ModelView):
	datamodel = SQLAInterface(ContractRenewal)
	list_columns = ['contract_id', 'renewal_date', 'new_value_cents', 'status']
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


__all__ = [
	"ServiceContractView",
	"ContractRenewalView",
]
