"""
pgappforge/plugins/erp/platform/notifications/views.py

Flask-AppBuilder views for notification alert rules.
"""
from __future__ import annotations

from flask_babel import lazy_gettext as _
from pgappforge.models.sqla.interface import SQLAInterface

from pgappforge.plugins.erp.base_view import BaseERPModelView
from pgappforge.plugins.erp.platform.notifications.models import KPIAlertRule


class KPIAlertRuleView(BaseERPModelView):
	"""CRUD view for KPI threshold alert rules."""

	datamodel = SQLAInterface(KPIAlertRule)

	list_title = "KPI Alert Rules"
	show_title = "KPI Alert Rule"
	add_title = "Add KPI Alert Rule"
	edit_title = "Edit KPI Alert Rule"

	list_columns = [
		"name",
		"kpi_key",
		"condition",
		"threshold_value",
		"is_active",
		"last_triggered_at",
		"cooldown_minutes",
	]
	show_columns = [
		"tenant_id",
		"name",
		"kpi_key",
		"condition",
		"threshold_value",
		"notification_channels",
		"recipients",
		"is_active",
		"last_triggered_at",
		"cooldown_minutes",
		"created_at",
		"updated_at",
	]
	add_columns = [
		"tenant_id",
		"name",
		"kpi_key",
		"condition",
		"threshold_value",
		"notification_channels",
		"recipients",
		"is_active",
		"cooldown_minutes",
	]
	edit_columns = [
		"name",
		"kpi_key",
		"condition",
		"threshold_value",
		"notification_channels",
		"recipients",
		"is_active",
		"cooldown_minutes",
	]
	label_columns = {
		"tenant_id": _("Tenant"),
		"name": _("Rule Name"),
		"kpi_key": _("KPI"),
		"condition": _("Condition"),
		"threshold_value": _("Threshold"),
		"notification_channels": _("Channels"),
		"recipients": _("Recipients"),
		"is_active": _("Active"),
		"last_triggered_at": _("Last Triggered"),
		"cooldown_minutes": _("Cooldown Minutes"),
		"created_at": _("Created"),
		"updated_at": _("Updated"),
	}
	search_columns = ["name", "kpi_key", "condition", "is_active"]
	page_size = 30


__all__ = ["KPIAlertRuleView"]
