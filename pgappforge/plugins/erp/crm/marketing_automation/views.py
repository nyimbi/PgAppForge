"""
pgappforge/plugins/erp/crm/marketing_automation/views.py

Flask-AppBuilder views for the Marketing Automation plugin.
"""
from __future__ import annotations

import logging

from flask import render_template
from pgappforge import ModelView, expose
from pgappforge.models.sqla.interface import SQLAInterface
from pgappforge.security.decorators import has_access

from pgappforge.plugins.erp.base_view import BaseERPView

log = logging.getLogger(__name__)


class MarketingCampaignView(ModelView):
	from pgappforge.plugins.erp.crm.marketing_automation.models import MarketingCampaign
	datamodel = SQLAInterface(MarketingCampaign)
	list_columns = ['name', 'campaign_type', 'status', 'start_date', 'end_date', 'budget_cents']
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class MarketingSequenceView(ModelView):
	from pgappforge.plugins.erp.crm.marketing_automation.models import MarketingSequence
	datamodel = SQLAInterface(MarketingSequence)
	list_columns = ['campaign_id', 'step_number', 'step_type', 'delay_hours', 'subject_line']
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class CampaignContactView(ModelView):
	from pgappforge.plugins.erp.crm.marketing_automation.models import CampaignContact
	datamodel = SQLAInterface(CampaignContact)
	list_columns = ['campaign_id', 'contact_id', 'email', 'status', 'enrolled_at', 'current_step']
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class LeadScoreView(ModelView):
	from pgappforge.plugins.erp.crm.marketing_automation.models import LeadScore
	datamodel = SQLAInterface(LeadScore)
	list_columns = ['contact_id', 'score', 'grade', 'converted', 'last_activity_at']
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class CampaignAttributionView(ModelView):
	from pgappforge.plugins.erp.crm.marketing_automation.models import CampaignAttribution
	datamodel = SQLAInterface(CampaignAttribution)
	list_columns = ['campaign_id', 'contact_id', 'revenue_cents', 'attribution_model', 'attributed_at']
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class MarketingDashboardView(BaseERPView):
	route_base = "/crm/marketing"

	@expose("/")
	@has_access
	def index(self):
		kpi_html = self.kpi_cards([
			{"label": "Active Campaigns", "value": 0, "icon": "fa-bullhorn", "color": "#1a56db"},
			{"label": "Enrolled Contacts", "value": 0, "icon": "fa-users", "color": "#0e9f6e"},
			{"label": "Avg Lead Score", "value": 0, "icon": "fa-star", "color": "#ff5a1f"},
		])
		return render_template(
			"crm_admin/marketing_campaigns.html",
			kpi_html=kpi_html,
			appbuilder=self.appbuilder,
		)


__all__ = [
	"MarketingCampaignView",
	"MarketingSequenceView",
	"CampaignContactView",
	"LeadScoreView",
	"CampaignAttributionView",
	"MarketingDashboardView",
]
