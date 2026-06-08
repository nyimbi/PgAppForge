"""
pgappforge/plugins/erp/crm/marketing/views.py

Flask views for the Marketing plugin.

Route summary
-------------
CampaignView         /marketing/campaigns/
EmailTemplateView    /marketing/email-templates/
MarketingListView    /marketing/lists/
MarketingReportView  /marketing/reports/
  ├─ /campaign-performance   — Campaign funnel and ROI (HTML)
  ├─ /lead-pipeline          — Lead → Respond conversion by campaign type (HTML)
  └─ /top-campaigns          — Top campaigns by actual_revenue_cents (HTML)
"""
from __future__ import annotations

import logging

import sqlalchemy as sa
from flask import abort, jsonify, make_response, request

from pgappforge import expose
from pgappforge.plugins.erp.base_view import BaseERPView
from pgappforge.security.decorators import has_access

log = logging.getLogger(__name__)


def _get_session():
	try:
		from flask import current_app
		ab = current_app.extensions.get("appbuilder")
		if ab and hasattr(ab, "get_session"):
			return ab.get_session
		db = current_app.extensions.get("sqlalchemy")
		if db:
			return db.session
	except RuntimeError:
		pass
	raise RuntimeError("Cannot obtain database session")


def _he(s: object) -> str:
	return (
		str(s)
		.replace("&", "&amp;")
		.replace("<", "&lt;")
		.replace(">", "&gt;")
		.replace('"', "&quot;")
	)


def _cents(v: int | None) -> str:
	if v is None:
		return "—"
	return f"{v // 100:,}.{abs(v) % 100:02d}"


# ---------------------------------------------------------------------------
# CampaignView
# ---------------------------------------------------------------------------

class CampaignView(BaseERPView):
	"""Campaign CRUD + activate/complete actions."""

	route_base = "/marketing/campaigns"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.crm.marketing.models import Campaign
		session = _get_session()
		campaigns = session.execute(
			sa.select(Campaign).order_by(Campaign.created_at.desc()).limit(200)
		).scalars().all()
		rows = "".join(
			f"<tr><td>{_he(c.campaign_name)}</td><td>{_he(c.campaign_type)}</td>"
			f"<td>{_he(c.status)}</td><td>{_cents(c.budget_cents)}</td>"
			f"<td>{c.actual_leads}</td>"
			f"<td><a href='/marketing/campaigns/{_he(c.id)}'>Detail</a></td></tr>"
			for c in campaigns
		)
		return make_response(
			f"<html><body><h2>Campaigns</h2><table border='1'>"
			f"<tr><th>Name</th><th>Type</th><th>Status</th><th>Budget</th><th>Leads</th><th></th></tr>"
			f"{rows}</table></body></html>"
		)

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		from pgappforge.plugins.erp.crm.marketing.models import Campaign
		data = request.get_json(force=True) or {}
		for f in ("tenant_id", "campaign_name", "campaign_type"):
			if not data.get(f):
				return jsonify({"error": f"Missing field: {f}"}), 400
		session = _get_session()
		campaign = Campaign(
			tenant_id=data["tenant_id"],
			campaign_name=data["campaign_name"],
			campaign_type=data["campaign_type"],
			status="PLANNING",
			budget_cents=data.get("budget_cents"),
			owner_id=data.get("owner_id"),
			target_audience=data.get("target_audience", {}),
			expected_leads=data.get("expected_leads"),
			expected_revenue_cents=data.get("expected_revenue_cents"),
		)
		session.add(campaign)
		session.commit()
		return jsonify({"id": campaign.id, "campaign_name": campaign.campaign_name}), 201

	@expose("/<string:campaign_id>/activate", methods=["POST"])
	@has_access
	def activate(self, campaign_id: str):
		from pgappforge.plugins.erp.crm.marketing.services import MarketingService, MarketingValidationError, CampaignNotFoundError
		session = _get_session()
		try:
			campaign = MarketingService.activate_campaign(campaign_id, session)
			session.commit()
			return jsonify({"id": campaign.id, "status": campaign.status})
		except CampaignNotFoundError:
			return jsonify({"error": "Campaign not found"}), 404
		except MarketingValidationError as exc:
			session.rollback()
			return jsonify({"error": str(exc)}), 422

	@expose("/<string:campaign_id>/complete", methods=["POST"])
	@has_access
	def complete(self, campaign_id: str):
		from pgappforge.plugins.erp.crm.marketing.services import MarketingService, MarketingValidationError, CampaignNotFoundError
		session = _get_session()
		try:
			campaign = MarketingService.complete_campaign(campaign_id, session)
			session.commit()
			return jsonify({"id": campaign.id, "status": campaign.status})
		except CampaignNotFoundError:
			return jsonify({"error": "Campaign not found"}), 404
		except MarketingValidationError as exc:
			session.rollback()
			return jsonify({"error": str(exc)}), 422

	@expose("/<string:campaign_id>/members", methods=["POST"])
	@has_access
	def add_member(self, campaign_id: str):
		from pgappforge.plugins.erp.crm.marketing.services import MarketingService, MarketingValidationError, CampaignNotFoundError
		data = request.get_json(force=True) or {}
		session = _get_session()
		try:
			member = MarketingService.add_member(
				campaign_id,
				data["party_id"],
				data.get("member_type", "LEAD"),
				session,
				source_campaign_id=data.get("source_campaign_id"),
			)
			session.commit()
			return jsonify({"id": member.id, "status": member.status}), 201
		except CampaignNotFoundError:
			return jsonify({"error": "Campaign not found"}), 404
		except (MarketingValidationError, KeyError) as exc:
			session.rollback()
			return jsonify({"error": str(exc)}), 422

	@expose("/members/<string:member_id>/status", methods=["PATCH"])
	@has_access
	def update_member_status(self, member_id: str):
		from pgappforge.plugins.erp.crm.marketing.services import MarketingService, MarketingValidationError, CampaignMemberNotFoundError
		data = request.get_json(force=True) or {}
		session = _get_session()
		try:
			member = MarketingService.update_member_status(member_id, data.get("status", ""), session)
			session.commit()
			return jsonify({"id": member.id, "status": member.status})
		except CampaignMemberNotFoundError:
			return jsonify({"error": "Member not found"}), 404
		except MarketingValidationError as exc:
			session.rollback()
			return jsonify({"error": str(exc)}), 422


# ---------------------------------------------------------------------------
# EmailTemplateView
# ---------------------------------------------------------------------------

class EmailTemplateView(BaseERPView):
	"""Email Template CRUD."""

	route_base = "/marketing/email-templates"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.crm.marketing.models import EmailTemplate
		session = _get_session()
		templates = session.execute(
			sa.select(EmailTemplate).order_by(EmailTemplate.name)
		).scalars().all()
		rows = "".join(
			f"<tr><td>{_he(t.name)}</td><td>{_he(t.subject)}</td>"
			f"<td>{_he(t.sender_name)}</td><td>{_he(t.sender_email)}</td>"
			f"<td>{'Active' if t.is_active else 'Inactive'}</td></tr>"
			for t in templates
		)
		return make_response(
			f"<html><body><h2>Email Templates</h2><table border='1'>"
			f"<tr><th>Name</th><th>Subject</th><th>From Name</th><th>From Email</th><th>Status</th></tr>"
			f"{rows}</table></body></html>"
		)


# ---------------------------------------------------------------------------
# MarketingListView
# ---------------------------------------------------------------------------

class MarketingListView(BaseERPView):
	"""Marketing List CRUD."""

	route_base = "/marketing/lists"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.crm.marketing.models import MarketingList
		session = _get_session()
		lists = session.execute(
			sa.select(MarketingList).order_by(MarketingList.name)
		).scalars().all()
		rows = "".join(
			f"<tr><td>{_he(ml.name)}</td><td>{_he(ml.list_type)}</td>"
			f"<td>{ml.member_count}</td>"
			f"<td>{_he(ml.last_updated_at.isoformat() if ml.last_updated_at else '')}</td></tr>"
			for ml in lists
		)
		return make_response(
			f"<html><body><h2>Marketing Lists</h2><table border='1'>"
			f"<tr><th>Name</th><th>Type</th><th>Members</th><th>Last Updated</th></tr>"
			f"{rows}</table></body></html>"
		)


# ---------------------------------------------------------------------------
# MarketingReportView — 3 ReportForge-compatible report endpoints
# ---------------------------------------------------------------------------

class MarketingReportView(BaseERPView):
	"""Marketing reports."""

	route_base = "/marketing/reports"

	@expose("/dashboard")
	@has_access
	def dashboard(self):
		"""Marketing dashboard — KPIs."""
		from pgappforge.plugins.erp.crm.marketing.models import Campaign, CampaignMember
		from datetime import datetime, timezone, timedelta
		session = _get_session()
		tenant_id = request.args.get("tenant_id")
		now = datetime.now(timezone.utc)
		month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

		q_active = sa.select(sa.func.count(Campaign.id)).where(Campaign.status == "ACTIVE")
		q_enrolled = sa.select(sa.func.count(CampaignMember.id))
		q_conv = sa.select(
			sa.func.coalesce(sa.func.avg(
				sa.cast(CampaignMember.status == "RESPONDED", sa.Integer) * 100
			), 0)
		)
		q_leads = sa.select(sa.func.count(CampaignMember.id)).where(
			CampaignMember.created_at >= month_start
		)
		if tenant_id:
			q_active = q_active.where(Campaign.tenant_id == tenant_id)
			# join through campaign for member queries
			campaign_ids = sa.select(Campaign.id).where(Campaign.tenant_id == tenant_id).scalar_subquery()
			q_enrolled = q_enrolled.where(CampaignMember.campaign_id.in_(campaign_ids))
			q_conv = q_conv.where(CampaignMember.campaign_id.in_(campaign_ids))
			q_leads = q_leads.where(CampaignMember.campaign_id.in_(campaign_ids))

		active_campaigns = int(session.execute(q_active).scalar() or 0)
		total_enrolled = int(session.execute(q_enrolled).scalar() or 0)
		avg_conversion_rate_pct = float(session.execute(q_conv).scalar() or 0)
		leads_this_month = int(session.execute(q_leads).scalar() or 0)

		kpi_html = self.kpi_cards([
			{"label": "Active Campaigns", "value": active_campaigns, "format": "integer", "color": "#1a56db", "icon": "fa-bullhorn"},
			{"label": "Total Enrolled", "value": total_enrolled, "format": "integer", "color": "#057a55", "icon": "fa-users"},
			{"label": "Avg Conversion Rate", "value": avg_conversion_rate_pct, "format": "percent", "color": "#9061f9", "icon": "fa-percentage"},
			{"label": "Leads This Month", "value": leads_this_month, "format": "integer", "color": "#d97706", "icon": "fa-user-plus"},
		])

		return make_response(
			f"<html><head><meta charset='utf-8'><title>Marketing Dashboard</title>"
			f"<link rel='stylesheet' href='https://maxcdn.bootstrapcdn.com/bootstrap/3.3.7/css/bootstrap.min.css'>"
			f"</head><body style='padding:24px'>"
			f"<h3>Marketing Dashboard</h3>{kpi_html}</body></html>"
		)

	@expose("/campaign-performance")
	@has_access
	def campaign_performance(self):
		from pgappforge.plugins.erp.crm.marketing.services import MarketingService, CampaignNotFoundError
		campaign_id = request.args.get("campaign_id", "")
		if not campaign_id:
			return make_response("<html><body><p>?campaign_id= required</p></body></html>"), 400
		session = _get_session()
		try:
			report = MarketingService.campaign_performance_report(campaign_id, session)
		except CampaignNotFoundError:
			return make_response("<html><body><p>Campaign not found</p></body></html>"), 404

		funnel_rows = "".join(
			f"<tr><td>{_he(k)}</td><td>{v}</td></tr>"
			for k, v in report["funnel"].items()
		)
		return make_response(
			f"<html><body><h2>Campaign Performance: {_he(report['campaign_name'])}</h2>"
			f"<p>Status: {_he(report['status'])} | Total Members: {report['total_members']}</p>"
			f"<p>Open Rate: {report['open_rate_pct']}% | Click Rate: {report['click_rate_pct']}%</p>"
			f"<p>Cost: {_cents(report['actual_cost_cents'])} | Revenue: {_cents(report['actual_revenue_cents'])}"
			f" | ROI: {report['roi_pct']}%</p>"
			f"<table border='1'><tr><th>Stage</th><th>Count</th></tr>{funnel_rows}</table>"
			f"</body></html>"
		)

	@expose("/lead-pipeline")
	@has_access
	def lead_pipeline(self):
		from pgappforge.plugins.erp.crm.marketing.models import Campaign, CampaignMember
		import sqlalchemy.func as func
		session = _get_session()
		rows_data = session.execute(
			sa.select(
				Campaign.campaign_type,
				CampaignMember.status,
				func.count(CampaignMember.id).label("cnt"),
			)
			.join(Campaign, Campaign.id == CampaignMember.campaign_id)
			.group_by(Campaign.campaign_type, CampaignMember.status)
		).all()

		by_type: dict[str, dict[str, int]] = {}
		for r in rows_data:
			by_type.setdefault(r.campaign_type, {})[r.status] = r.cnt

		rows = ""
		for ct, counts in sorted(by_type.items()):
			sent = sum(counts.values())
			responded = counts.get("RESPONDED", 0)
			conv = round(responded / sent * 100, 1) if sent else 0
			rows += f"<tr><td>{_he(ct)}</td><td>{sent}</td><td>{responded}</td><td>{conv}%</td></tr>"

		return make_response(
			f"<html><body><h2>Lead Pipeline by Campaign Type</h2><table border='1'>"
			f"<tr><th>Type</th><th>Sent</th><th>Responded</th><th>Conv. Rate</th></tr>"
			f"{rows}</table></body></html>"
		)

	@expose("/top-campaigns")
	@has_access
	def top_campaigns(self):
		from pgappforge.plugins.erp.crm.marketing.models import Campaign
		session = _get_session()
		tenant_id = request.args.get("tenant_id", "")
		q = sa.select(Campaign).order_by(Campaign.actual_revenue_cents.desc()).limit(20)
		if tenant_id:
			q = q.where(Campaign.tenant_id == tenant_id)
		campaigns = session.execute(q).scalars().all()
		rows = "".join(
			f"<tr><td>{_he(c.campaign_name)}</td><td>{_he(c.campaign_type)}</td>"
			f"<td>{_cents(c.actual_revenue_cents)}</td><td>{_cents(c.actual_cost_cents)}</td>"
			f"<td>{c.actual_leads}</td></tr>"
			for c in campaigns
		)
		return make_response(
			f"<html><body><h2>Top Campaigns by Revenue</h2><table border='1'>"
			f"<tr><th>Name</th><th>Type</th><th>Revenue</th><th>Cost</th><th>Leads</th></tr>"
			f"{rows}</table></body></html>"
		)
