from __future__ import annotations

from pgappforge import ModelView
from pgappforge.models.sqla.interface import SQLAInterface

from pgappforge.plugins.erp.procurement.sourcing.models import (
	RFQ,
	SupplierBid,
)


class RFQView(ModelView):
	datamodel = SQLAInterface(RFQ)

	list_columns = ['rfq_ref', 'title', 'rfq_type', 'status',
					'submission_deadline', 'entity_id', 'created_by']
	add_exclude_columns = ['id', 'created_at', 'updated_at']
	edit_exclude_columns = ['id', 'created_at', 'updated_at']


class SupplierBidView(ModelView):
	datamodel = SQLAInterface(SupplierBid)

	list_columns = ['rfq_id', 'supplier_id', 'status', 'total_bid_cents',
					'currency_code', 'composite_score', 'delivery_days']
	add_exclude_columns = ['id', 'created_at', 'updated_at']
	edit_exclude_columns = ['id', 'created_at', 'updated_at']


__all__ = [
	'RFQView',
	'SupplierBidView',
]
