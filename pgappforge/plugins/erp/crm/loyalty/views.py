"""
pgappforge/plugins/erp/crm/loyalty/views.py

Flask-AppBuilder views for the Loyalty plugin.
"""
from __future__ import annotations

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
		'name': 'Name',
		'program_type': 'Program Type',
		'points_per_cent': 'Points Per Cent',
		'redemption_rate_pct': 'Redemption Rate Pct',
		'is_active': 'Active',
	}
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class LoyaltyAccountView(ModelView):
	datamodel = SQLAInterface(LoyaltyAccount)
	list_columns = ['customer_id', 'program_id', 'tier', 'points_balance', 'lifetime_points', 'last_activity_at']
	label_columns = {
		'customer_id': 'Customer',
		'program_id': 'Program',
		'tier': 'Tier',
		'points_balance': 'Points Balance',
		'lifetime_points': 'Lifetime Points',
		'last_activity_at': 'Last Activity At',
	}
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class LoyaltyTransactionView(ModelView):
	datamodel = SQLAInterface(LoyaltyTransaction)
	list_columns = ['account_id', 'transaction_type', 'points', 'created_at']
	label_columns = {
		'account_id': 'Account',
		'transaction_type': 'Transaction Type',
		'points': 'Points',
		'created_at': 'Created At',
	}
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


__all__ = [
	"LoyaltyProgramView",
	"LoyaltyAccountView",
	"LoyaltyTransactionView",
]
