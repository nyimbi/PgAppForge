"""Compatibility exports for CRM account models."""
from __future__ import annotations

from pgappforge.plugins.erp.crm.sales.models import SalesAccount

Account = SalesAccount

__all__ = ["SalesAccount", "Account"]
