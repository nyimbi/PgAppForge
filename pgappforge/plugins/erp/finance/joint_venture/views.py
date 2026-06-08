from __future__ import annotations

from pgappforge import ModelView
from pgappforge.models.sqla.interface import SQLAInterface

from pgappforge.plugins.erp.finance.joint_venture.models import (
	JointVenture,
	JvCashCall,
	JvBillingStatement,
)


class JointVentureView(ModelView):
	datamodel = SQLAInterface(JointVenture)

	list_columns = ['venture_code', 'venture_name', 'venture_type',
					'accounting_method', 'status', 'currency_code', 'effective_date']
	add_exclude_columns = ['id', 'created_at', 'updated_at']
	edit_exclude_columns = ['id', 'created_at', 'updated_at']


class JVCashCallView(ModelView):
	datamodel = SQLAInterface(JvCashCall)

	list_columns = ['venture_id', 'call_reference', 'call_date', 'due_date',
					'total_amount_cents', 'status']
	add_exclude_columns = ['id', 'created_at']
	edit_exclude_columns = ['id', 'created_at']


class JVBillingRecordView(ModelView):
	datamodel = SQLAInterface(JvBillingStatement)

	list_columns = ['venture_id', 'partner_id', 'billing_period',
					'total_billed_cents', 'partner_share_cents', 'status']
	add_exclude_columns = ['id', 'created_at']
	edit_exclude_columns = ['id', 'created_at']


__all__ = [
	'JointVentureView',
	'JVCashCallView',
	'JVBillingRecordView',
]
