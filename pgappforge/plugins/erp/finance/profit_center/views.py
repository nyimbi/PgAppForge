from __future__ import annotations

from pgappforge import ModelView
from pgappforge.models.sqla.interface import SQLAInterface

from pgappforge.plugins.erp.finance.profit_center.models import (
	ProfitCenter,
	ProfitCenterJournal,
	ProfitCenterAllocationRule,
)


class ProfitCenterView(ModelView):
	datamodel = SQLAInterface(ProfitCenter)

	list_columns = ['code', 'name', 'entity_id', 'manager_id', 'is_active', 'budget_annual_cents']
	add_exclude_columns = ['id', 'created_at', 'updated_at']
	edit_exclude_columns = ['id', 'created_at', 'updated_at']


class ProfitCenterJournalView(ModelView):
	datamodel = SQLAInterface(ProfitCenterJournal)

	list_columns = ['profit_center_id', 'gl_account', 'period', 'debit_cents', 'credit_cents']
	add_exclude_columns = ['id', 'created_at', 'updated_at']
	edit_exclude_columns = ['id', 'created_at', 'updated_at']


class ProfitCenterAllocationRuleView(ModelView):
	datamodel = SQLAInterface(ProfitCenterAllocationRule)

	list_columns = ['name', 'source_profit_center_id', 'allocation_method', 'is_active']
	add_exclude_columns = ['id', 'created_at', 'updated_at']
	edit_exclude_columns = ['id', 'created_at', 'updated_at']


class ProfitCenterReportView(ModelView):
	datamodel = SQLAInterface(ProfitCenterJournal)

	list_title = 'PC Report — Journals'
	list_columns = ['profit_center_id', 'gl_account', 'period', 'debit_cents',
					'credit_cents', 'reference_id']
	add_exclude_columns = ['id', 'created_at', 'updated_at']
	edit_exclude_columns = ['id', 'created_at', 'updated_at']


__all__ = [
	'ProfitCenterView',
	'ProfitCenterJournalView',
	'ProfitCenterAllocationRuleView',
	'ProfitCenterReportView',
]
