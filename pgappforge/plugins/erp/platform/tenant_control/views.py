"""
pgappforge/plugins/erp/platform/tenant_control/views.py

Flask-AppBuilder views for the Tenant Control plugin.
"""
from __future__ import annotations

import logging

from flask import render_template
from pgappforge import ModelView, expose
from pgappforge.models.sqla.interface import SQLAInterface
from pgappforge.security.decorators import has_access

from pgappforge.plugins.erp.base_view import BaseERPView
from pgappforge.plugins.erp.platform.tenant_control.models import (
	TenantProfile,
	TenantUsageEvent,
)

log = logging.getLogger(__name__)


class TenantProfileView(ModelView):
	datamodel = SQLAInterface(TenantProfile)
	base_permissions       = ["can_list", "can_show"]
	list_columns           = ['name', 'plan_tier', 'status', 'trial_ends_at']
	add_exclude_columns    = ['id', 'created_on', 'changed_on', 'billing_hyperion_customer_id']
	edit_exclude_columns   = ['id', 'created_on', 'changed_on', 'billing_hyperion_customer_id']
	show_exclude_columns   = ['billing_hyperion_customer_id', 'feature_flags', 'usage_stats']


class TenantUsageEventView(ModelView):
	datamodel = SQLAInterface(TenantUsageEvent)
	base_permissions     = ["can_list", "can_show"]
	list_columns         = ['tenant_id', 'event_type', 'quantity', 'recorded_at']
	add_exclude_columns  = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class TenantControlAdminView(BaseERPView):
	route_base = "/platform/tenant-control"

	@expose("/")
	@has_access
	def index(self):
		try:
			from pgappforge.plugins.erp.platform.tenant_control.models import TenantProfile, TenantUsageEvent
			sess = self._session()
			active_tenants = self._count(TenantProfile, session=sess, status="ACTIVE")
			trial_tenants = self._count(TenantProfile, session=sess, status="TRIAL")
			usage_events = self._count(TenantUsageEvent, session=sess)
		except Exception:
			active_tenants = trial_tenants = usage_events = 0
		kpi_html = self.kpi_cards([
			{"label": "Active Tenants", "value": active_tenants, "icon": "fa-building", "color": "#1a56db"},
			{"label": "Trial Tenants", "value": trial_tenants, "icon": "fa-hourglass-half", "color": "#ff5a1f"},
			{"label": "Usage Events (24h)", "value": usage_events, "icon": "fa-bar-chart", "color": "#0e9f6e"},
		])
		return render_template(
			"platform_admin/tenant_control_admin.html",
			kpi_html=kpi_html,
			appbuilder=self.appbuilder,
		)


__all__ = [
	"TenantProfileView",
	"TenantUsageEventView",
	"TenantControlAdminView",
]
