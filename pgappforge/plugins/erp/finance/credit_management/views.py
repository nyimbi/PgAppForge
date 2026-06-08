from __future__ import annotations

from pgappforge import ModelView
from pgappforge.models.sqla.interface import SQLAInterface

from pgappforge.plugins.erp.finance.credit_management.models import (
	CustomerCreditProfile,
	CreditExposureComponent,
)


class CreditProfileView(ModelView):
	datamodel = SQLAInterface(CustomerCreditProfile)

	list_columns = ['customer_id', 'credit_limit_cents', 'current_exposure_cents',
					'available_credit_cents', 'credit_rating', 'is_on_hold', 'currency_code']
	add_exclude_columns = ['id', 'created_at', 'updated_at']
	edit_exclude_columns = ['id', 'created_at', 'updated_at']


class CreditExposureView(ModelView):
	datamodel = SQLAInterface(CreditExposureComponent)

	list_columns = ['profile_id', 'source_type', 'source_id', 'amount_cents',
					'due_date', 'is_overdue']
	add_exclude_columns = ['id', 'created_at', 'updated_at']
	edit_exclude_columns = ['id', 'created_at', 'updated_at']


class CreditHoldView(ModelView):
	datamodel = SQLAInterface(CustomerCreditProfile)

	list_title = 'Credit Holds'
	list_columns = ['customer_id', 'is_on_hold', 'hold_reason',
					'hold_placed_by', 'hold_placed_at', 'credit_limit_cents']
	add_exclude_columns = ['id', 'created_at', 'updated_at']
	edit_exclude_columns = ['id', 'created_at', 'updated_at']


class OverdueCustomerView(ModelView):
	datamodel = SQLAInterface(CreditExposureComponent)

	list_title = 'Overdue Customers'
	list_columns = ['profile_id', 'source_type', 'source_id',
					'amount_cents', 'due_date', 'is_overdue']
	add_exclude_columns = ['id', 'created_at', 'updated_at']
	edit_exclude_columns = ['id', 'created_at', 'updated_at']


class CreditCheckView(ModelView):
	datamodel = SQLAInterface(CustomerCreditProfile)

	list_title = 'Credit Check'
	list_columns = ['customer_id', 'credit_limit_cents', 'current_exposure_cents',
					'available_credit_cents', 'credit_rating', 'is_on_hold']
	add_exclude_columns = ['id', 'created_at', 'updated_at']
	edit_exclude_columns = ['id', 'created_at', 'updated_at']


__all__ = [
	'CreditProfileView',
	'CreditExposureView',
	'CreditHoldView',
	'OverdueCustomerView',
	'CreditCheckView',
]
