from __future__ import annotations

from pgappforge import ModelView
from pgappforge.models.sqla.interface import SQLAInterface

from pgappforge.plugins.erp.finance.multi_book.models import (
	AccountingBook,
	BookJournalEntry,
)


class AccountingBookView(ModelView):
	datamodel = SQLAInterface(AccountingBook)

	list_columns = ['name', 'book_type', 'currency_code', 'is_primary', 'is_active', 'entity_id']
	add_exclude_columns = ['id']
	edit_exclude_columns = ['id']


class BookJournalEntryView(ModelView):
	datamodel = SQLAInterface(BookJournalEntry)

	list_columns = ['book_id', 'source_journal_id', 'gl_account', 'period',
					'debit_cents', 'credit_cents', 'is_override']
	add_exclude_columns = ['id']
	edit_exclude_columns = ['id']


__all__ = [
	'AccountingBookView',
	'BookJournalEntryView',
]
