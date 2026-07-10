"""Compatibility package for CRM lead views and models."""
from __future__ import annotations

from pgappforge.plugins.erp.crm.sales.models import Lead
from pgappforge.plugins.erp.crm.sales.views import LeadView

__all__ = ["Lead", "LeadView"]
