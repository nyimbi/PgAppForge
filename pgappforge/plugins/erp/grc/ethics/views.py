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
from pgappforge.plugins.erp.grc.ethics.models import EthicsCase, EthicsReport

log = logging.getLogger(__name__)


class EthicsReportView(ModelView):
	datamodel = SQLAInterface(EthicsReport)
	list_columns = ['category', 'severity', 'status', 'is_anonymous', 'occurred_at', 'location']
	add_exclude_columns    = ['id', 'created_on', 'changed_on', 'anonymous_token', 'reporter_contact']
	edit_exclude_columns   = ['id', 'created_on', 'changed_on', 'anonymous_token', 'reporter_contact']
	show_exclude_columns   = ['anonymous_token', 'reporter_contact', 'ip_address', 'user_agent']
	search_exclude_columns = ['anonymous_token', 'reporter_contact']


class EthicsCaseView(ModelView):
	datamodel = SQLAInterface(EthicsCase)
	list_columns         = ['case_ref', 'status', 'assigned_to', 'opened_at', 'closed_at']
	add_exclude_columns  = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']
	show_exclude_columns = ['id']


class EthicsHotlineDashboardView(BaseERPView):
	route_base = "/grc/ethics"

	@expose("/")
	@has_access
	def index(self):
		try:
			sess = self._session()
			open_reports = self._count(EthicsReport, session=sess, status="SUBMITTED")
			active_cases = self._count(EthicsReport, session=sess, status="UNDER_INVESTIGATION")
			resolved = self._count(EthicsReport, session=sess, status="RESOLVED")
		except Exception:
			open_reports = active_cases = resolved = 0
		kpi_html = self.kpi_cards([
			{"label": "Open Reports", "value": open_reports, "icon": "fa-flag", "color": "#9e1c00"},
			{"label": "Active Cases", "value": active_cases, "icon": "fa-folder-open", "color": "#ff5a1f"},
			{"label": "Resolved (30d)", "value": resolved, "icon": "fa-check-circle", "color": "#0e9f6e"},
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
