"""
pgappforge/plugins/erp/crm/loyalty/views.py

Flask-AppBuilder views for the Loyalty plugin.
"""
from __future__ import annotations
from flask_babel import lazy_gettext as _

import logging

from pgappforge import ModelView
from pgappforge.models.sqla.interface import SQLAInterface
from pgappforge.plugins.erp.crm.loyalty.models import (
	LoyaltyProgram,
	LoyaltyAccount,
	LoyaltyTransaction,
)

log = logging.getLogger(__name__)


class LoyaltyProgramView(ModelView):
	datamodel = SQLAInterface(LoyaltyProgram)
	list_columns = ['name', 'program_type', 'points_per_cent', 'redemption_rate_pct', 'is_active']
	label_columns = {
		'name': _('Name'),
		'program_type': _('Program Type'),
		'points_per_cent': _('Points Per Cent'),
		'redemption_rate_pct': _('Redemption Rate Pct'),
		'is_active': _('Is Active'),
	}
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class LoyaltyAccountView(ModelView):
	datamodel = SQLAInterface(LoyaltyAccount)
	list_columns = ['customer_id', 'program_id', 'tier', 'points_balance', 'lifetime_points', 'last_activity_at']
	label_columns = {
		'customer_id': _('Customer Id'),
		'program_id': _('Program Id'),
		'tier': _('Tier'),
		'points_balance': _('Points Balance'),
		'lifetime_points': _('Lifetime Points'),
		'last_activity_at': _('Last Activity At'),
	}
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class LoyaltyTransactionView(ModelView):
	datamodel = SQLAInterface(LoyaltyTransaction)
	list_columns = ['account_id', 'transaction_type', 'points', 'created_at']
	label_columns = {
		'account_id': _('Account Id'),
		'transaction_type': _('Transaction Type'),
		'points': _('Points'),
		'created_at': _('Created At'),
	}
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


__all__ = [
	"LoyaltyProgramView",
	"LoyaltyAccountView",
	"LoyaltyTransactionView",
]
