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
	list_columns = ['name', 'region', 'country_codes', 'is_active']
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class TerritoryAssignmentView(ModelView):
	datamodel = SQLAInterface(TerritoryAssignment)
	list_columns = ['territory_id', 'salesperson_id', 'effective_from', 'effective_to']
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


__all__ = [
	"SalesTerritoryView",
	"TerritoryAssignmentView",
]
