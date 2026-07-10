"""Compatibility exports for CRM contact views."""
from __future__ import annotations

from pgappforge.plugins.erp.crm.sales.views import SalesContactView

ContactView = SalesContactView

__all__ = ["SalesContactView", "ContactView"]
