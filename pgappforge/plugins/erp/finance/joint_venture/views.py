from __future__ import annotations
from flask_babel import lazy_gettext as _

from pgappforge import ModelView
from pgappforge.models.sqla.interface import SQLAInterface

from pgappforge.plugins.erp.finance.joint_venture.models import (
	JointVenture,
	JVCashCall,
	JVBilling,
)


class JointVentureView(ModelView):
	datamodel = SQLAInterface(JointVenture)

	list_columns = ['name', 'operator_entity_id', 'status', 'created_at']
	show_columns = ['id', 'name', 'operator_entity_id', 'partners', 'status',
					'created_at']
	label_columns = {
		'name': _('Name'),
		'operator_entity_id': _('Operator Entity'),
		'status': _('Status'),
		'created_at': _('Created At'),
		'partners': _('Partners'),
	}
	search_columns = ['name', 'operator_entity_id', 'status']
	add_exclude_columns = ['id', 'created_at', 'updated_at']
	edit_exclude_columns = ['id', 'created_at', 'updated_at']


class JVCashCallView(ModelView):
	datamodel = SQLAInterface(JVCashCall)

	list_columns = ['jv_id', 'period', 'total_cents', 'due_date', 'status']
	show_columns = ['id', 'jv_id', 'period', 'total_cents', 'due_date', 'status',
					'distribution', 'created_at']
	label_columns = {
		'jv_id': _('Joint Venture'),
		'period': _('Period'),
		'total_cents': _('Total (cents)'),
		'due_date': _('Due Date'),
		'status': _('Status'),
		'distribution': _('Distribution'),
		'created_at': _('Created At'),
	}
	search_columns = ['jv_id', 'period', 'status']
	add_exclude_columns = ['id', 'created_at']
	edit_exclude_columns = ['id', 'created_at']


class JVBillingRecordView(ModelView):
	datamodel = SQLAInterface(JVBilling)

	list_columns = ['jv_id', 'expense_journal_id', 'period', 'created_at']
	show_columns = ['id', 'jv_id', 'expense_journal_id', 'period', 'distribution',
					'created_at']
	label_columns = {
		'jv_id': _('Joint Venture'),
		'expense_journal_id': _('Expense Journal'),
		'period': _('Period'),
		'created_at': _('Created At'),
		'distribution': _('Distribution'),
	}
	search_columns = ['jv_id', 'expense_journal_id', 'period']
	add_exclude_columns = ['id', 'created_at']
	edit_exclude_columns = ['id', 'created_at']


__all__ = [
	'JointVentureView',
	'JVCashCallView',
	'JVBillingRecordView',
]
