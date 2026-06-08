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

log = logging.getLogger(__name__)


class TenantProfileView(ModelView):
	from pgappforge.plugins.erp.platform.tenant_control.models import TenantProfile
	datamodel = SQLAInterface(TenantProfile)
	list_columns = ['name', 'plan_tier', 'status', 'trial_ends_at']
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class TenantUsageEventView(ModelView):
	from pgappforge.plugins.erp.platform.tenant_control.models import TenantUsageEvent
	datamodel = SQLAInterface(TenantUsageEvent)
	list_columns = ['tenant_id', 'event_type', 'quantity', 'recorded_at']
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class TenantControlAdminView(BaseERPView):
	route_base = "/platform/tenant-control"

	@expose("/")
	@has_access
	def index(self):
		kpi_html = self.kpi_cards([
			{"label": "Active Tenants", "value": 0, "icon": "fa-building", "color": "#1a56db"},
			{"label": "Trial Tenants", "value": 0, "icon": "fa-hourglass-half", "color": "#ff5a1f"},
			{"label": "Usage Events (24h)", "value": 0, "icon": "fa-bar-chart", "color": "#0e9f6e"},
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
