"""Compatibility package for CRM opportunity views and models."""
from __future__ import annotations

from pgappforge.plugins.erp.crm.sales.models import Opportunity
from pgappforge.plugins.erp.crm.sales.views import OpportunityView

__all__ = ["Opportunity", "OpportunityView"]
