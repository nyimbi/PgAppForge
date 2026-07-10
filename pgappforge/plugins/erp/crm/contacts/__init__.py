"""Compatibility package for CRM contact views and models."""
from __future__ import annotations

from pgappforge.plugins.erp.crm.sales.models import SalesContact
from pgappforge.plugins.erp.crm.sales.views import SalesContactView

Contact = SalesContact
ContactView = SalesContactView

__all__ = ["SalesContact", "SalesContactView", "Contact", "ContactView"]
