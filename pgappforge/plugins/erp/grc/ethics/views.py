"""
pgappforge/plugins/erp/grc/ethics/views.py

Flask-AppBuilder views for the Ethics & Hotline plugin.
"""
from __future__ import annotations

import logging

from flask import render_template
from pgappforge import ModelView, expose
from pgappforge.models.sqla.interface import SQLAInterface
from pgappforge.security.decorators import has_access

from pgappforge.plugins.erp.base_view import BaseERPView

log = logging.getLogger(__name__)


class EthicsReportView(ModelView):
	from pgappforge.plugins.erp.grc.ethics.models import EthicsReport
	datamodel = SQLAInterface(EthicsReport)
	list_columns = ['category', 'severity', 'status', 'is_anonymous', 'occurred_at', 'location']
	add_exclude_columns = ['id', 'created_on', 'changed_on', 'anonymous_token', 'reporter_contact']
	edit_exclude_columns = ['id', 'created_on', 'changed_on', 'anonymous_token', 'reporter_contact']


class EthicsCaseView(ModelView):
	from pgappforge.plugins.erp.grc.ethics.models import EthicsCase
	datamodel = SQLAInterface(EthicsCase)
	list_columns = ['report_id', 'case_ref', 'status', 'assigned_to', 'opened_at', 'closed_at']
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class EthicsHotlineDashboardView(BaseERPView):
	route_base = "/grc/ethics"

	@expose("/")
	@has_access
	def index(self):
		kpi_html = self.kpi_cards([
			{"label": "Open Reports", "value": 0, "icon": "fa-flag", "color": "#9e1c00"},
			{"label": "Active Cases", "value": 0, "icon": "fa-folder-open", "color": "#ff5a1f"},
			{"label": "Resolved (30d)", "value": 0, "icon": "fa-check-circle", "color": "#0e9f6e"},
		])
		return render_template(
			"grc_ethics/ethics_hotline.html",
			kpi_html=kpi_html,
			appbuilder=self.appbuilder,
		)


__all__ = [
	"EthicsReportView",
	"EthicsCaseView",
	"EthicsHotlineDashboardView",
]
