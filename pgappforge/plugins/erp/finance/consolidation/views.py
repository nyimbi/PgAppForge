from __future__ import annotations

from pgappforge import ModelView
from pgappforge.models.sqla.interface import SQLAInterface

from pgappforge.plugins.erp.finance.consolidation.models import (
	ConsolidationGroup,
	ConsolidationRun,
	IntercompanyElimination,
	MinorityInterest,
)


class ConsolidationGroupView(ModelView):
	datamodel = SQLAInterface(ConsolidationGroup)

	list_columns = ['name', 'reporting_entity_id', 'reporting_currency', 'is_active']
	show_columns = ['id', 'name', 'description', 'reporting_entity_id',
					'reporting_currency', 'is_active', 'members', 'created_at',
					'updated_at']
	label_columns = {
		'name': 'Name',
		'reporting_entity_id': 'Reporting Entity',
		'reporting_currency': 'Reporting Currency',
		'is_active': 'Active',
		'description': 'Description',
		'members': 'Members',
		'created_at': 'Created At',
		'updated_at': 'Updated At',
	}
	add_exclude_columns = ['id', 'created_at', 'updated_at']
	edit_exclude_columns = ['id', 'created_at', 'updated_at']


class ConsolidationRunView(ModelView):
	datamodel = SQLAInterface(ConsolidationRun)

	list_columns = ['group_id', 'period', 'status', 'started_at',
					'entities_processed', 'eliminations_count']
	show_columns = ['id', 'period', 'status', 'started_at', 'completed_at',
					'entities_processed', 'eliminations_count', 'error_message',
					'result_data', 'created_at', 'updated_at']
	label_columns = {
		'group_id': 'Consolidation Group',
		'period': 'Period',
		'status': 'Status',
		'started_at': 'Started At',
		'entities_processed': 'Entities Processed',
		'eliminations_count': 'Eliminations Count',
		'completed_at': 'Completed At',
		'error_message': 'Error Message',
		'result_data': 'Result Data',
		'created_at': 'Created At',
		'updated_at': 'Updated At',
	}
	add_exclude_columns = ['id', 'created_at', 'updated_at']
	edit_exclude_columns = ['id', 'created_at', 'updated_at']


class IntercompanyEliminationView(ModelView):
	datamodel = SQLAInterface(IntercompanyElimination)

	list_columns = ['run_id', 'elimination_type', 'debtor_entity_id',
					'creditor_entity_id', 'amount_cents', 'currency_code']
	show_columns = ['id', 'debtor_entity_id', 'creditor_entity_id',
					'elimination_type', 'amount_cents', 'currency_code',
					'account_code', 'description', 'created_at', 'updated_at']
	label_columns = {
		'run_id': 'Consolidation Run',
		'elimination_type': 'Elimination Type',
		'debtor_entity_id': 'Debtor Entity',
		'creditor_entity_id': 'Creditor Entity',
		'amount_cents': 'Amount (cents)',
		'currency_code': 'Currency',
		'account_code': 'Account Code',
		'description': 'Description',
		'created_at': 'Created At',
		'updated_at': 'Updated At',
	}
	add_exclude_columns = ['id', 'created_at', 'updated_at']
	edit_exclude_columns = ['id', 'created_at', 'updated_at']


class MinorityInterestView(ModelView):
	datamodel = SQLAInterface(MinorityInterest)

	list_columns = ['run_id', 'subsidiary_entity_id', 'minority_ownership_pct',
					'subsidiary_equity_cents', 'minority_interest_cents', 'period']
	show_columns = ['id', 'subsidiary_entity_id', 'minority_ownership_pct',
					'subsidiary_equity_cents', 'minority_interest_cents',
					'period', 'created_at', 'updated_at']
	label_columns = {
		'run_id': 'Consolidation Run',
		'subsidiary_entity_id': 'Subsidiary Entity',
		'minority_ownership_pct': 'Minority Ownership %',
		'subsidiary_equity_cents': 'Subsidiary Equity (cents)',
		'minority_interest_cents': 'Minority Interest (cents)',
		'period': 'Period',
		'created_at': 'Created At',
		'updated_at': 'Updated At',
	}
	add_exclude_columns = ['id', 'created_at', 'updated_at']
	edit_exclude_columns = ['id', 'created_at', 'updated_at']


__all__ = [
	'ConsolidationGroupView',
	'ConsolidationRunView',
	'IntercompanyEliminationView',
	'MinorityInterestView',
]
