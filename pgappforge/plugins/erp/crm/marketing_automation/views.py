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
from pgappforge.plugins.erp.crm.marketing_automation.models import (
	CampaignAttribution,
	CampaignContact,
	LeadScore,
	MarketingCampaign,
	MarketingSequence,
)

log = logging.getLogger(__name__)


class MarketingCampaignView(ModelView):
	datamodel = SQLAInterface(MarketingCampaign)
	list_columns = ['name', 'campaign_type', 'status', 'start_date', 'end_date', 'budget_cents']
	label_columns = {
		'name': 'Name',
		'campaign_type': 'Campaign Type',
		'status': 'Status',
		'start_date': 'Start Date',
		'end_date': 'End Date',
		'budget_cents': 'Budget Cents',
	}
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class MarketingSequenceView(ModelView):
	datamodel = SQLAInterface(MarketingSequence)
	list_columns = ['campaign_id', 'step_number', 'step_type', 'delay_hours', 'subject_line']
	label_columns = {
		'campaign_id': 'Campaign',
		'step_number': 'Step Number',
		'step_type': 'Step Type',
		'delay_hours': 'Delay Hours',
		'subject_line': 'Subject Line',
	}
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class CampaignContactView(ModelView):
	datamodel = SQLAInterface(CampaignContact)
	list_columns = ['campaign_id', 'contact_id', 'email', 'status', 'enrolled_at', 'current_step']
	label_columns = {
		'campaign_id': 'Campaign',
		'contact_id': 'Contact',
		'email': 'Email',
		'status': 'Status',
		'enrolled_at': 'Enrolled At',
		'current_step': 'Current Step',
	}
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class LeadScoreView(ModelView):
	datamodel = SQLAInterface(LeadScore)
	list_columns = ['contact_id', 'score', 'grade', 'converted', 'last_activity_at']
	label_columns = {
		'contact_id': 'Contact',
		'score': 'Score',
		'grade': 'Grade',
		'converted': 'Converted',
		'last_activity_at': 'Last Activity At',
	}
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class CampaignAttributionView(ModelView):
	datamodel = SQLAInterface(CampaignAttribution)
	list_columns = ['campaign_id', 'contact_id', 'revenue_cents', 'attribution_model', 'attributed_at']
	label_columns = {
		'campaign_id': 'Campaign',
		'contact_id': 'Contact',
		'revenue_cents': 'Revenue Cents',
		'attribution_model': 'Attribution Model',
		'attributed_at': 'Attributed At',
	}
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class MarketingDashboardView(BaseERPView):
	route_base = "/crm/marketing"

	@expose("/")
	@has_access
	def index(self):
		try:
			from pgappforge.plugins.erp.crm.marketing_automation.models import MarketingCampaign, CampaignContact, LeadScore
			import sqlalchemy as sa
			sess = self._session()
			active_campaigns = self._count(MarketingCampaign, session=sess, status="ACTIVE")
			enrolled_contacts = self._count(CampaignContact, session=sess, status="ENROLLED")
			avg_score_row = sess.execute(
				sa.select(sa.func.coalesce(sa.func.avg(LeadScore.score), 0))
			).scalar_one()
			avg_lead_score = int(avg_score_row)
		except Exception:
			active_campaigns = enrolled_contacts = avg_lead_score = 0
		kpi_html = self.kpi_cards([
			{"label": "Active Campaigns", "value": active_campaigns, "icon": "fa-bullhorn", "color": "#1a56db"},
			{"label": "Enrolled Contacts", "value": enrolled_contacts, "icon": "fa-users", "color": "#0e9f6e"},
			{"label": "Avg Lead Score", "value": avg_lead_score, "icon": "fa-star", "color": "#ff5a1f"},
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
