from __future__ import annotations

from pgappforge import ModelView
from pgappforge.models.sqla.interface import SQLAInterface

from pgappforge.plugins.erp.finance.lease_accounting.models import (
	Lease,
	LeasePaymentSchedule,
)


class LeaseView(ModelView):
	datamodel = SQLAInterface(Lease)

	list_columns = ['lease_reference', 'lessor_name', 'asset_class', 'standard',
					'classification', 'status', 'commencement_date', 'lease_term_months',
					'lease_liability_cents', 'rou_asset_cents']
	add_exclude_columns = ['id', 'created_at', 'updated_at']
	edit_exclude_columns = ['id', 'created_at', 'updated_at']


class LeasePaymentScheduleView(ModelView):
	datamodel = SQLAInterface(LeasePaymentSchedule)

	list_columns = ['lease_id', 'period_number', 'due_date', 'opening_liability_cents',
					'interest_expense_cents', 'payment_cents', 'principal_reduction_cents',
					'closing_liability_cents', 'is_paid']
	add_exclude_columns = ['id']
	edit_exclude_columns = ['id']


__all__ = [
	'LeaseView',
	'LeasePaymentScheduleView',
]
