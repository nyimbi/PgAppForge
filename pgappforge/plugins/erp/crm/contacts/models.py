"""Compatibility exports for CRM contact models."""
from __future__ import annotations

from pgappforge.plugins.erp.crm.sales.models import SalesContact

Contact = SalesContact

__all__ = ["SalesContact", "Contact"]
