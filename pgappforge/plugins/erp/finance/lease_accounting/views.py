from __future__ import annotations
from flask_babel import lazy_gettext as _

from pgappforge import ModelView
from pgappforge.models.sqla.interface import SQLAInterface

from pgappforge.plugins.erp.finance.lease_accounting.models import (
	Lease,
	LeasePaymentSchedule,
)


class LeaseView(ModelView):
	datamodel = SQLAInterface(Lease)

	list_columns = ['name', 'lease_type', 'counterparty', 'standard', 'status',
					'start_date', 'end_date', 'lease_liability_cents', 'rou_asset_cents']
	show_columns = ['id', 'name', 'lease_type', 'counterparty', 'start_date',
					'end_date', 'discount_rate', 'currency_code', 'payment_schedule',
					'rou_asset_cents', 'lease_liability_cents', 'status', 'standard']
	label_columns = {
		'name': _('Name'),
		'lease_type': _('Lease Type'),
		'counterparty': _('Counterparty'),
		'standard': _('Standard'),
		'status': _('Status'),
		'start_date': _('Start Date'),
		'end_date': _('End Date'),
		'lease_liability_cents': _('Lease Liability (cents)'),
		'rou_asset_cents': _('ROU Asset (cents)'),
		'discount_rate': _('Discount Rate'),
		'currency_code': _('Currency'),
		'payment_schedule': _('Payment Schedule'),
	}
	search_columns = ['name', 'lease_type', 'counterparty', 'standard', 'status', 'currency_code']
	add_exclude_columns = ['id', 'created_at', 'updated_at']
	edit_exclude_columns = ['id', 'created_at', 'updated_at']


class LeasePaymentScheduleView(ModelView):
	datamodel = SQLAInterface(LeasePaymentSchedule)

	list_columns = ['lease_id', 'period', 'payment_cents', 'interest_cents',
					'principal_cents', 'rou_balance_cents', 'liability_balance_cents',
					'gl_posted']
	show_columns = ['id', 'lease_id', 'period', 'payment_cents', 'interest_cents',
					'principal_cents', 'rou_balance_cents', 'liability_balance_cents',
					'gl_posted']
	label_columns = {
		'lease_id': _('Lease'),
		'period': _('Period'),
		'payment_cents': _('Payment (cents)'),
		'interest_cents': _('Interest (cents)'),
		'principal_cents': _('Principal (cents)'),
		'rou_balance_cents': _('ROU Balance (cents)'),
		'liability_balance_cents': _('Liability Balance (cents)'),
		'gl_posted': _('GL Posted'),
	}
	search_columns = ['lease_id', 'period', 'gl_posted']
	add_exclude_columns = ['id']
	edit_exclude_columns = ['id']


__all__ = [
	'LeaseView',
	'LeasePaymentScheduleView',
]
