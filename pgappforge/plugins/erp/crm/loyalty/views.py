"""
pgappforge/plugins/erp/crm/loyalty/views.py

Flask-AppBuilder views for the Loyalty plugin.
"""
from __future__ import annotations

import logging

from pgappforge import ModelView
from pgappforge.models.sqla.interface import SQLAInterface

log = logging.getLogger(__name__)


class LoyaltyProgramView(ModelView):
	from pgappforge.plugins.erp.crm.loyalty.models import LoyaltyProgram
	datamodel = SQLAInterface(LoyaltyProgram)
	list_columns = ['name', 'earn_rate', 'redemption_rate_cents', 'expiry_days', 'is_active']
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class LoyaltyAccountView(ModelView):
	from pgappforge.plugins.erp.crm.loyalty.models import LoyaltyAccount
	datamodel = SQLAInterface(LoyaltyAccount)
	list_columns = ['customer_id', 'program_id', 'tier', 'status', 'points_balance', 'lifetime_points', 'last_activity_at']
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class LoyaltyTransactionView(ModelView):
	from pgappforge.plugins.erp.crm.loyalty.models import LoyaltyTransaction
	datamodel = SQLAInterface(LoyaltyTransaction)
	list_columns = ['account_id', 'transaction_type', 'points', 'balance_after', 'created_at']
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


__all__ = [
	"LoyaltyProgramView",
	"LoyaltyAccountView",
	"LoyaltyTransactionView",
]
