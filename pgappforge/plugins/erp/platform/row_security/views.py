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
from pgappforge.plugins.erp.platform.row_security.models import (
	RowSecurityPolicy,
	SecurityContext,
)

log = logging.getLogger(__name__)


class RowSecurityPolicyView(ModelView):
	datamodel = SQLAInterface(RowSecurityPolicy)
	base_permissions     = ["can_list", "can_show", "can_add", "can_edit"]
	list_columns         = ['name', 'entity_type', 'scope_field', 'role_id', 'is_active']
	add_exclude_columns  = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class SecurityContextView(ModelView):
	datamodel = SQLAInterface(SecurityContext)
	base_permissions     = ["can_list", "can_show"]
	list_columns         = ['entity_type', 'is_active', 'last_computed_at']
	add_exclude_columns  = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']
	show_exclude_columns = ['computed_scope']


class RowSecurityAdminView(BaseERPView):
	route_base = "/platform/row-security"

	@expose("/")
	@has_access
	def index(self):
		try:
			from pgappforge.plugins.erp.platform.row_security.models import RowSecurityPolicy, SecurityContext
			sess = self._session()
			active_policies = self._count(RowSecurityPolicy, session=sess, is_active=True)
			scoped_users = self._count(SecurityContext, session=sess)
		except Exception:
			active_policies = scoped_users = 0
		kpi_html = self.kpi_cards([
			{"label": "Active Policies", "value": active_policies, "icon": "fa-shield", "color": "#1a56db"},
			{"label": "Scoped Users", "value": scoped_users, "icon": "fa-user-secret", "color": "#0e9f6e"},
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
