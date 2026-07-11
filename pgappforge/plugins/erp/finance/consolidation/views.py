from __future__ import annotations
from flask_babel import lazy_gettext as _

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
		'name': _('Name'),
		'reporting_entity_id': _('Reporting Entity'),
		'reporting_currency': _('Reporting Currency'),
		'is_active': _('Active'),
		'description': _('Description'),
		'members': _('Members'),
		'created_at': _('Created At'),
		'updated_at': _('Updated At'),
	}
	search_columns = ['name', 'reporting_entity_id', 'reporting_currency', 'is_active']
	add_exclude_columns = ['id', 'created_at', 'updated_at']
	edit_exclude_columns = ['id', 'created_at', 'updated_at']


class ConsolidationRunView(ModelView):
	datamodel = SQLAInterface(ConsolidationRun)

	list_columns = ['group_id', 'period', 'status', 'started_at',
					'entities_processed', 'eliminations_count']
	show_columns = ['id', 'group_id', 'period', 'status', 'started_at', 'completed_at',
					'entities_processed', 'eliminations_count', 'error_message',
					'result_data', 'created_at', 'updated_at']
	label_columns = {
		'group_id': _('Consolidation Group'),
		'period': _('Period'),
		'status': _('Status'),
		'started_at': _('Started At'),
		'entities_processed': _('Entities Processed'),
		'eliminations_count': _('Eliminations Count'),
		'completed_at': _('Completed At'),
		'error_message': _('Error Message'),
		'result_data': _('Result Data'),
		'created_at': _('Created At'),
		'updated_at': _('Updated At'),
	}
	search_columns = ['group_id', 'period', 'status']
	add_exclude_columns = ['id', 'created_at', 'updated_at']
	edit_exclude_columns = ['id', 'created_at', 'updated_at']


class IntercompanyEliminationView(ModelView):
	datamodel = SQLAInterface(IntercompanyElimination)

	list_columns = ['run_id', 'elimination_type', 'debtor_entity_id',
					'creditor_entity_id', 'amount_cents', 'currency_code']
	show_columns = ['id', 'run_id', 'debtor_entity_id', 'creditor_entity_id',
					'elimination_type', 'amount_cents', 'currency_code',
					'account_code', 'description', 'created_at', 'updated_at']
	label_columns = {
		'run_id': _('Consolidation Run'),
		'elimination_type': _('Elimination Type'),
		'debtor_entity_id': _('Debtor Entity'),
		'creditor_entity_id': _('Creditor Entity'),
		'amount_cents': _('Amount (cents)'),
		'currency_code': _('Currency'),
		'account_code': _('Account Code'),
		'description': _('Description'),
		'created_at': _('Created At'),
		'updated_at': _('Updated At'),
	}
	search_columns = ['run_id', 'elimination_type', 'debtor_entity_id',
					  'creditor_entity_id', 'currency_code', 'account_code']
	add_exclude_columns = ['id', 'created_at', 'updated_at']
	edit_exclude_columns = ['id', 'created_at', 'updated_at']


class MinorityInterestView(ModelView):
	datamodel = SQLAInterface(MinorityInterest)

	list_columns = ['run_id', 'subsidiary_entity_id', 'minority_ownership_pct',
					'subsidiary_equity_cents', 'minority_interest_cents', 'period']
	show_columns = ['id', 'run_id', 'subsidiary_entity_id', 'minority_ownership_pct',
					'subsidiary_equity_cents', 'minority_interest_cents',
					'period', 'created_at', 'updated_at']
	label_columns = {
		'run_id': _('Consolidation Run'),
		'subsidiary_entity_id': _('Subsidiary Entity'),
		'minority_ownership_pct': _('Minority Ownership %'),
		'subsidiary_equity_cents': _('Subsidiary Equity (cents)'),
		'minority_interest_cents': _('Minority Interest (cents)'),
		'period': _('Period'),
		'created_at': _('Created At'),
		'updated_at': _('Updated At'),
	}
	search_columns = ['run_id', 'subsidiary_entity_id', 'period']
	add_exclude_columns = ['id', 'created_at', 'updated_at']
	edit_exclude_columns = ['id', 'created_at', 'updated_at']


__all__ = [
	'ConsolidationGroupView',
	'ConsolidationRunView',
	'IntercompanyEliminationView',
	'MinorityInterestView',
]
