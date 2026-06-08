"""
pgappforge/plugins/erp/platform/row_security/views.py

Flask-AppBuilder views for the Row-Level Security plugin.
"""
from __future__ import annotations

import logging

from flask import render_template
from pgappforge import ModelView, expose
from pgappforge.models.sqla.interface import SQLAInterface
from pgappforge.security.decorators import has_access

from pgappforge.plugins.erp.base_view import BaseERPView

log = logging.getLogger(__name__)


class RowSecurityPolicyView(ModelView):
	from pgappforge.plugins.erp.platform.row_security.models import RowSecurityPolicy
	datamodel = SQLAInterface(RowSecurityPolicy)
	list_columns = ['name', 'entity_type', 'scope_field', 'role_id', 'is_active']
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class SecurityContextView(ModelView):
	from pgappforge.plugins.erp.platform.row_security.models import SecurityContext
	datamodel = SQLAInterface(SecurityContext)
	list_columns = ['user_id', 'computed_scope']
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class RowSecurityAdminView(BaseERPView):
	route_base = "/platform/row-security"

	@expose("/")
	@has_access
	def index(self):
		kpi_html = self.kpi_cards([
			{"label": "Active Policies", "value": 0, "icon": "fa-shield", "color": "#1a56db"},
			{"label": "Scoped Users", "value": 0, "icon": "fa-user-secret", "color": "#0e9f6e"},
		])
		return render_template(
			"platform_admin/row_security_admin.html",
			kpi_html=kpi_html,
			appbuilder=self.appbuilder,
		)


__all__ = [
	"RowSecurityPolicyView",
	"SecurityContextView",
	"RowSecurityAdminView",
]
