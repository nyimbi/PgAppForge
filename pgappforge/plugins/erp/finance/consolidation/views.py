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
	add_exclude_columns = ['id', 'created_at', 'updated_at']
	edit_exclude_columns = ['id', 'created_at', 'updated_at']


class ConsolidationRunView(ModelView):
	datamodel = SQLAInterface(ConsolidationRun)

	list_columns = ['group_id', 'period', 'status', 'started_at',
					'entities_processed', 'eliminations_count']
	add_exclude_columns = ['id', 'created_at', 'updated_at']
	edit_exclude_columns = ['id', 'created_at', 'updated_at']


class IntercompanyEliminationView(ModelView):
	datamodel = SQLAInterface(IntercompanyElimination)

	list_columns = ['run_id', 'elimination_type', 'debtor_entity_id',
					'creditor_entity_id', 'amount_cents', 'currency_code']
	add_exclude_columns = ['id', 'created_at', 'updated_at']
	edit_exclude_columns = ['id', 'created_at', 'updated_at']


class MinorityInterestView(ModelView):
	datamodel = SQLAInterface(MinorityInterest)

	list_columns = ['run_id', 'subsidiary_entity_id', 'minority_ownership_pct',
					'subsidiary_equity_cents', 'minority_interest_cents', 'period']
	add_exclude_columns = ['id', 'created_at', 'updated_at']
	edit_exclude_columns = ['id', 'created_at', 'updated_at']


__all__ = [
	'ConsolidationGroupView',
	'ConsolidationRunView',
	'IntercompanyEliminationView',
	'MinorityInterestView',
]
