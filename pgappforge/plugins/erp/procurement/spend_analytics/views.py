from __future__ import annotations

from pgappforge import ModelView
from pgappforge.models.sqla.interface import SQLAInterface

from pgappforge.plugins.erp.procurement.spend_analytics.models import SpendSnapshot


class SpendSnapshotView(ModelView):
	datamodel = SQLAInterface(SpendSnapshot)

	list_columns = ['period', 'supplier_id', 'supplier_name', 'category',
					'department', 'amount_cents', 'invoice_count']
	add_exclude_columns = ['id', 'created_at', 'updated_at']
	edit_exclude_columns = ['id', 'created_at', 'updated_at']


__all__ = ['SpendSnapshotView']
