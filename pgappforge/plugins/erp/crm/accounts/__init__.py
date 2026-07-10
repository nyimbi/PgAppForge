"""Compatibility package for CRM account views and models."""
from __future__ import annotations

from pgappforge.plugins.erp.crm.sales.models import SalesAccount
from pgappforge.plugins.erp.crm.sales.views import SalesAccountView

Account = SalesAccount
AccountView = SalesAccountView

__all__ = ["SalesAccount", "SalesAccountView", "Account", "AccountView"]
