"""
pgappforge/plugins/erp/crm/territory_management/views.py

Flask-AppBuilder views for the Territory Management plugin.
"""
from __future__ import annotations

import logging

from pgappforge import ModelView
from pgappforge.models.sqla.interface import SQLAInterface
from pgappforge.plugins.erp.crm.territory_management.models import (
	SalesTerritory,
	TerritoryAssignment,
)

log = logging.getLogger(__name__)


class SalesTerritoryView(ModelView):
	datamodel = SQLAInterface(SalesTerritory)
	list_columns = ['name', 'region', 'rules', 'is_active']
	label_columns = {
		'name': 'Name',
		'region': 'Region',
		'rules': 'Rules',
		'is_active': 'Is Active',
	}
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class TerritoryAssignmentView(ModelView):
	datamodel = SQLAInterface(TerritoryAssignment)
	list_columns = ['territory_id', 'salesperson_id', 'effective_from', 'effective_to']
	label_columns = {
		'territory_id': 'Territory Id',
		'salesperson_id': 'Salesperson Id',
		'effective_from': 'Effective From',
		'effective_to': 'Effective To',
	}
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


__all__ = [
	"SalesTerritoryView",
	"TerritoryAssignmentView",
]
