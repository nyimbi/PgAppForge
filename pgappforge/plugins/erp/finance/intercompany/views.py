from __future__ import annotations

from pgappforge import ModelView
from pgappforge.models.sqla.interface import SQLAInterface

from pgappforge.plugins.erp.finance.intercompany.models import (
	ICOutboxTransaction,
	ICInboxTransaction,
)


class ICOutboxView(ModelView):
	datamodel = SQLAInterface(ICOutboxTransaction)

	list_columns = ['source_entity_id', 'target_entity_id', 'transaction_type',
					'status', 'sent_at', 'correlation_id']
	add_exclude_columns = ['id', 'created_at', 'updated_at']
	edit_exclude_columns = ['id', 'created_at', 'updated_at']


class ICInboxView(ModelView):
	datamodel = SQLAInterface(ICInboxTransaction)

	list_columns = ['source_entity_id', 'target_entity_id', 'transaction_type',
					'status', 'processed_at', 'correlation_id']
	add_exclude_columns = ['id', 'created_at', 'updated_at']
	edit_exclude_columns = ['id', 'created_at', 'updated_at']


__all__ = [
	'ICOutboxView',
	'ICInboxView',
]
