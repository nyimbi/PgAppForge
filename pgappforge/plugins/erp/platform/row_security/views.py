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
	show_columns         = ['tenant_id', 'name', 'entity_type', 'scope_field', 'allowed_values', 'role_id', 'is_active', 'description', 'created_at', 'updated_at']
	label_columns        = {
		'tenant_id': 'Tenant',
		'name': 'Policy Name',
		'entity_type': 'Entity Type',
		'scope_field': 'Scope Field',
		'allowed_values': 'Allowed Values',
		'role_id': 'Role',
		'is_active': 'Active',
		'description': 'Description',
		'created_at': 'Created',
		'updated_at': 'Updated',
	}
	add_exclude_columns  = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class SecurityContextView(ModelView):
	datamodel = SQLAInterface(SecurityContext)
	base_permissions     = ["can_list", "can_show"]
	list_columns         = ['tenant_id', 'user_id', 'computed_at', 'expires_at']
	show_columns         = ['tenant_id', 'user_id', 'computed_scope', 'computed_at', 'expires_at']
	label_columns        = {
		'tenant_id': 'Tenant',
		'user_id': 'User',
		'computed_scope': 'Computed Scope',
		'computed_at': 'Computed At',
		'expires_at': 'Expires At',
	}
	add_exclude_columns  = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


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
