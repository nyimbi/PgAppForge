"""Compatibility exports for CRM account views."""
from __future__ import annotations

from pgappforge.plugins.erp.crm.sales.views import SalesAccountView

AccountView = SalesAccountView

__all__ = ["SalesAccountView", "AccountView"]
