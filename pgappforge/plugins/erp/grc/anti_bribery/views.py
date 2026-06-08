"""
pgappforge/plugins/erp/grc/anti_bribery/views.py

Flask-AppBuilder views for the Anti-Bribery & Corruption plugin.
"""
from __future__ import annotations

import logging

from flask import render_template
from pgappforge import ModelView, expose
from pgappforge.models.sqla.interface import SQLAInterface
from pgappforge.security.decorators import has_access

from pgappforge.plugins.erp.base_view import BaseERPView

log = logging.getLogger(__name__)


class GiftEntertainmentLogView(ModelView):
	from pgappforge.plugins.erp.grc.anti_bribery.models import GiftEntertainmentLog
	datamodel = SQLAInterface(GiftEntertainmentLog)
	list_columns = ['given_to_name', 'given_to_organization', 'gift_type', 'value_cents', 'given_date', 'direction', 'status', 'is_government_official']
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class ConflictOfInterestDeclarationView(ModelView):
	from pgappforge.plugins.erp.grc.anti_bribery.models import ConflictOfInterestDeclaration
	datamodel = SQLAInterface(ConflictOfInterestDeclaration)
	list_columns = ['employee_id', 'conflict_type', 'description', 'status', 'declared_at']
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class GiftsRegisterDashboardView(BaseERPView):
	route_base = "/grc/anti-bribery"

	@expose("/")
	@has_access
	def index(self):
		kpi_html = self.kpi_cards([
			{"label": "Pending Approval", "value": 0, "icon": "fa-gift", "color": "#ff5a1f"},
			{"label": "Govt Official Gifts", "value": 0, "icon": "fa-exclamation-triangle", "color": "#9e1c00"},
			{"label": "COI Declarations", "value": 0, "icon": "fa-user-times", "color": "#1a56db"},
		])
		return render_template(
			"grc_antibribery/gifts_register.html",
			kpi_html=kpi_html,
			appbuilder=self.appbuilder,
		)


__all__ = [
	"GiftEntertainmentLogView",
	"ConflictOfInterestDeclarationView",
	"GiftsRegisterDashboardView",
]
