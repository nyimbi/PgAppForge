"""
pgappforge/plugins/erp/crm/sign/views.py

Flask-AppBuilder views for the E-Sign Portal plugin.
"""
from __future__ import annotations

import logging

from flask import render_template
from pgappforge import ModelView, expose
from pgappforge.models.sqla.interface import SQLAInterface
from pgappforge.security.decorators import has_access

from pgappforge.plugins.erp.base_view import BaseERPView

log = logging.getLogger(__name__)


class SignatureRequestView(ModelView):
	from pgappforge.plugins.erp.crm.sign.models import SignatureRequest
	datamodel = SQLAInterface(SignatureRequest)
	list_columns = ['document_title', 'initiator_id', 'status', 'signing_order', 'expires_at']
	add_exclude_columns = ['id', 'created_on', 'changed_on', 'created_at', 'updated_at']
	edit_exclude_columns = ['id', 'created_on', 'changed_on', 'created_at', 'updated_at']


class SignatureSignatoryView(ModelView):
	from pgappforge.plugins.erp.crm.sign.models import SignatureSignatory
	datamodel = SQLAInterface(SignatureSignatory)
	list_columns = ['signer_name', 'signer_email', 'signer_role', 'order_number', 'status', 'signed_at']
	add_exclude_columns = ['id', 'created_on', 'changed_on', 'created_at', 'updated_at', 'access_token', 'signature_image_base64']
	edit_exclude_columns = ['id', 'created_on', 'changed_on', 'created_at', 'updated_at', 'access_token', 'signature_image_base64']


class SignWorkflowView(BaseERPView):
	route_base = "/crm/sign"

	@expose("/")
	@has_access
	def index(self):
		kpi_html = self.kpi_cards([
			{"label": "Pending Requests", "value": 0, "icon": "fa-pencil-square-o", "color": "#ff5a1f"},
			{"label": "Completed", "value": 0, "icon": "fa-check-circle", "color": "#0e9f6e"},
			{"label": "Expired", "value": 0, "icon": "fa-clock-o", "color": "#9e1c00"},
		])
		return render_template(
			"crm_sign_ui/sign_workflow.html",
			kpi_html=kpi_html,
			appbuilder=self.appbuilder,
		)


__all__ = [
	"SignatureRequestView",
	"SignatureSignatoryView",
	"SignWorkflowView",
]
