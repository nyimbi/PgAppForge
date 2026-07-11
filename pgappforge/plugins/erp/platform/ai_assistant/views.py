"""
pgappforge/plugins/erp/platform/ai_assistant/views.py

Views for platform AI assistant administration.
"""
from __future__ import annotations
from flask_babel import lazy_gettext as _

from pgappforge import ModelView
from pgappforge.models.sqla.interface import SQLAInterface

from .models import AuditLog


class AIAuditTrailView(ModelView):
	"""Read-only AI tool audit trail."""

	datamodel = SQLAInterface(AuditLog)
	list_columns = ["timestamp", "user_display", "tool_name", "action", "result_summary"]
	label_columns = {
		"timestamp": _("Timestamp"),
		"user_display": _("User"),
		"tool_name": _("Tool"),
		"action": _("Action"),
		"result_summary": _("Result"),
	}
	default_order = ("timestamp", "desc")
	page_size = 50


__all__ = ["AIAuditTrailView"]
