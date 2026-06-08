from __future__ import annotations

from pgappforge import ModelView
from pgappforge.models.sqla.interface import SQLAInterface

from pgappforge.plugins.erp.finance.grants.models import (
	Fund,
	Grant,
	FundBalance,
	GrantExpenditure,
)


class FundView(ModelView):
	datamodel = SQLAInterface(Fund)

	list_columns = ['fund_code', 'name', 'fund_type', 'entity_id', 'is_active']
	add_exclude_columns = ['id', 'created_at', 'updated_at']
	edit_exclude_columns = ['id', 'created_at', 'updated_at']


class GrantView(ModelView):
	datamodel = SQLAInterface(Grant)

	list_columns = ['grant_ref', 'grantor_name', 'fund_id', 'amount_cents',
					'start_date', 'end_date', 'status']
	add_exclude_columns = ['id', 'created_at', 'updated_at']
	edit_exclude_columns = ['id', 'created_at', 'updated_at']


class FundBalanceView(ModelView):
	datamodel = SQLAInterface(FundBalance)

	list_columns = ['fund_id', 'period', 'opening_cents', 'receipts_cents',
					'expenditures_cents', 'closing_cents']
	add_exclude_columns = ['id', 'created_at', 'updated_at']
	edit_exclude_columns = ['id', 'created_at', 'updated_at']


class GrantExpenditureView(ModelView):
	datamodel = SQLAInterface(GrantExpenditure)

	list_columns = ['grant_id', 'period', 'amount_cents', 'indirect_cost_cents',
					'purpose', 'expenditure_date', 'approved_by']
	add_exclude_columns = ['id', 'created_at', 'updated_at']
	edit_exclude_columns = ['id', 'created_at', 'updated_at']


__all__ = [
	'FundView',
	'GrantView',
	'FundBalanceView',
	'GrantExpenditureView',
]
