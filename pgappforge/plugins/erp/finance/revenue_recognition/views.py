from __future__ import annotations

from pgappforge import ModelView
from pgappforge.models.sqla.interface import SQLAInterface

from pgappforge.plugins.erp.finance.revenue_recognition.models import (
	RevRecContract,
	RevRecObligation,
	RevRecJournalEntry,
)


class RevRecContractView(ModelView):
	datamodel = SQLAInterface(RevRecContract)

	list_columns = ['customer_id', 'contract_ref', 'contract_date', 'status',
					'total_transaction_price_cents', 'source_module']
	add_exclude_columns = ['id', 'created_at', 'updated_at']
	edit_exclude_columns = ['id', 'created_at', 'updated_at']


class RevRecObligationView(ModelView):
	datamodel = SQLAInterface(RevRecObligation)

	list_columns = ['contract_id', 'description', 'satisfaction_type', 'status',
					'allocated_transaction_price_cents', 'satisfied_cents', 'remaining_cents']
	add_exclude_columns = ['id', 'created_at', 'updated_at']
	edit_exclude_columns = ['id', 'created_at', 'updated_at']


class RevRecJournalEntryView(ModelView):
	datamodel = SQLAInterface(RevRecJournalEntry)

	list_columns = ['contract_id', 'obligation_id', 'period', 'recognized_cents',
					'revenue_account', 'deferred_revenue_account', 'created_at']
	add_exclude_columns = ['id', 'created_at']
	edit_exclude_columns = ['id', 'created_at']


__all__ = [
	'RevRecContractView',
	'RevRecObligationView',
	'RevRecJournalEntryView',
]
