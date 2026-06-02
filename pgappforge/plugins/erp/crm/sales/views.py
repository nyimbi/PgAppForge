"""
pgappforge/plugins/erp/crm/sales/views.py

Flask views for the Sales Force Automation (SFA) plugin.

Route summary
-------------
SalesAccountView      /crm/accounts/
SalesContactView      /crm/contacts/
LeadView              /crm/leads/
OpportunityView       /crm/opportunities/
ActivityView          /crm/activities/
SalesReportView       /crm/reports/
  ├─ /pipeline          — Pipeline by Stage (HTML)
  ├─ /forecast          — Forecast Summary (HTML)
  └─ /leaderboard       — Rep Leaderboard (HTML)
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone

import sqlalchemy as sa
from flask import abort, jsonify, make_response, request

from pgappforge import BaseView, expose
from pgappforge.security.decorators import has_access

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


def _cents(cents: int | None, currency: str = "USD") -> str:
	if cents is None:
		return "—"
	major = cents // 100
	minor = abs(cents) % 100
	sign = "-" if cents < 0 else ""
	return f"{sign}{major:,}.{minor:02d} {currency}"


# ---------------------------------------------------------------------------
# SalesAccountView
# ---------------------------------------------------------------------------

class SalesAccountView(BaseView):
	"""Sales Account CRUD.

	GET  /crm/accounts/                  — list (HTML)
	GET  /crm/accounts/<id>              — detail (JSON)
	POST /crm/accounts/                  — create (JSON)
	PUT  /crm/accounts/<id>              — update (JSON)
	"""

	route_base = "/crm/accounts"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		session = _get_session()
		from pgappforge.plugins.erp.crm.sales.models import SalesAccount
		tenant_id = request.args.get("tenant_id")
		account_type = request.args.get("account_type")
		q = (
			sa.select(SalesAccount)
			.where(SalesAccount.status == "ACTIVE")
			.order_by(SalesAccount.name)
			.limit(500)
		)
		if tenant_id:
			q = q.where(SalesAccount.tenant_id == tenant_id)
		if account_type:
			q = q.where(SalesAccount.account_type == account_type.upper())
		accounts = session.execute(q).scalars().all()

		rows = "".join(
			f"<tr>"
			f"<td>{_he(a.name)}</td>"
			f"<td>{_he(a.account_type)}</td>"
			f"<td>{_he(a.industry or '—')}</td>"
			f"<td class='text-right'>{_cents(a.annual_revenue_cents)}</td>"
			f"<td class='text-right'>{_he(a.health_score or '—')}</td>"
			f"<td class='text-right'>{_he(a.churn_risk_score or '—')}</td>"
			f"<td><a href='/crm/accounts/{_he(a.id)}' class='btn btn-xs btn-primary'>View</a></td>"
			f"</tr>"
			for a in accounts
		)
		html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>Sales Accounts</title>
<link rel="stylesheet" href="https://maxcdn.bootstrapcdn.com/bootstrap/3.3.7/css/bootstrap.min.css">
</head><body style="padding:24px">
<h3>Sales Accounts <small>({len(accounts)})</small></h3>
<table class="table table-bordered table-hover table-condensed">
<thead><tr><th>Name</th><th>Type</th><th>Industry</th><th>Annual Revenue</th>
<th>Health</th><th>Churn Risk</th><th></th></tr></thead>
<tbody>{rows}</tbody></table></body></html>"""
		return make_response(html, 200)

	@expose("/<string:account_id>")
	@has_access
	def detail(self, account_id: str):
		session = _get_session()
		from pgappforge.plugins.erp.crm.sales.models import SalesAccount
		a = session.get(SalesAccount, account_id)
		if a is None:
			abort(404)
		return jsonify({
			"id": a.id,
			"tenant_id": a.tenant_id,
			"name": a.name,
			"account_number": a.account_number,
			"account_type": a.account_type,
			"industry": a.industry,
			"website": a.website,
			"phone": a.phone,
			"email": a.email,
			"annual_revenue_cents": a.annual_revenue_cents,
			"employee_count": a.employee_count,
			"parent_account_id": a.parent_account_id,
			"owner_id": a.owner_id,
			"health_score": str(a.health_score) if a.health_score is not None else None,
			"churn_risk_score": str(a.churn_risk_score) if a.churn_risk_score is not None else None,
			"lifetime_value_cents": a.lifetime_value_cents,
			"nps_score": a.nps_score,
			"billing_address": a.billing_address,
			"shipping_address": a.shipping_address,
			"status": a.status,
			"created_at": a.created_at.isoformat() if a.created_at else None,
			"updated_at": a.updated_at.isoformat() if a.updated_at else None,
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		session = _get_session()
		from pgappforge.plugins.erp.crm.sales.models import SalesAccount
		data = request.get_json(silent=True) or {}
		missing = [f for f in ("tenant_id", "name") if not data.get(f)]
		if missing:
			return jsonify({"ok": False, "error": f"Missing: {missing}"}), 400
		a = SalesAccount(
			tenant_id=data["tenant_id"],
			name=data["name"],
			account_number=data.get("account_number"),
			account_type=(data.get("account_type") or "PROSPECT").upper(),
			industry=data.get("industry"),
			website=data.get("website"),
			phone=data.get("phone"),
			email=data.get("email"),
			annual_revenue_cents=data.get("annual_revenue_cents"),
			employee_count=data.get("employee_count"),
			parent_account_id=data.get("parent_account_id"),
			owner_id=data.get("owner_id"),
			health_score=data.get("health_score"),
			nps_score=data.get("nps_score"),
			billing_address=data.get("billing_address") or {},
			shipping_address=data.get("shipping_address") or {},
			description=data.get("description"),
			status="ACTIVE",
		)
		session.add(a)
		session.commit()
		return jsonify({"ok": True, "id": a.id}), 201

	@expose("/<string:account_id>", methods=["PUT"])
	@has_access
	def update(self, account_id: str):
		session = _get_session()
		from pgappforge.plugins.erp.crm.sales.models import SalesAccount
		a = session.get(SalesAccount, account_id)
		if a is None:
			abort(404)
		data = request.get_json(silent=True) or {}
		updatable = [
			"name", "account_type", "industry", "website", "phone", "email",
			"annual_revenue_cents", "employee_count", "owner_id",
			"health_score", "churn_risk_score", "lifetime_value_cents",
			"nps_score", "billing_address", "shipping_address", "description", "status",
		]
		changed = [f for f in updatable if f in data and (setattr(a, f, data[f]) or True)]
		a.updated_at = datetime.now(timezone.utc)
		session.commit()
		return jsonify({"ok": True, "changed": changed})


# ---------------------------------------------------------------------------
# SalesContactView
# ---------------------------------------------------------------------------

class SalesContactView(BaseView):
	"""Sales Contact CRUD.

	GET  /crm/contacts/          — list (HTML)
	GET  /crm/contacts/<id>      — detail (JSON)
	POST /crm/contacts/          — create (JSON)
	PUT  /crm/contacts/<id>      — update (JSON)
	"""

	route_base = "/crm/contacts"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		session = _get_session()
		from pgappforge.plugins.erp.crm.sales.models import SalesContact
		tenant_id = request.args.get("tenant_id")
		account_id = request.args.get("account_id")
		q = (
			sa.select(SalesContact)
			.where(SalesContact.status == "ACTIVE")
			.order_by(SalesContact.last_name, SalesContact.first_name)
			.limit(500)
		)
		if tenant_id:
			q = q.where(SalesContact.tenant_id == tenant_id)
		if account_id:
			q = q.where(SalesContact.account_id == account_id)
		contacts = session.execute(q).scalars().all()

		rows = "".join(
			f"<tr>"
			f"<td>{_he(c.first_name)} {_he(c.last_name)}</td>"
			f"<td>{_he(c.title or '—')}</td>"
			f"<td>{_he(c.department or '—')}</td>"
			f"<td>{_he(c.seniority or '—')}</td>"
			f"<td>{'✓' if c.is_decision_maker else ''}</td>"
			f"<td>{_he(c.email or '—')}</td>"
			f"<td>{_he(c.engagement_score or '—')}</td>"
			f"<td><a href='/crm/contacts/{_he(c.id)}' class='btn btn-xs btn-primary'>View</a></td>"
			f"</tr>"
			for c in contacts
		)
		html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>Sales Contacts</title>
<link rel="stylesheet" href="https://maxcdn.bootstrapcdn.com/bootstrap/3.3.7/css/bootstrap.min.css">
</head><body style="padding:24px">
<h3>Sales Contacts <small>({len(contacts)})</small></h3>
<table class="table table-bordered table-hover table-condensed">
<thead><tr><th>Name</th><th>Title</th><th>Department</th><th>Seniority</th>
<th>Decision Maker</th><th>Email</th><th>Engagement</th><th></th></tr></thead>
<tbody>{rows}</tbody></table></body></html>"""
		return make_response(html, 200)

	@expose("/<string:contact_id>")
	@has_access
	def detail(self, contact_id: str):
		session = _get_session()
		from pgappforge.plugins.erp.crm.sales.models import SalesContact
		c = session.get(SalesContact, contact_id)
		if c is None:
			abort(404)
		return jsonify({
			"id": c.id,
			"tenant_id": c.tenant_id,
			"account_id": c.account_id,
			"first_name": c.first_name,
			"last_name": c.last_name,
			"title": c.title,
			"department": c.department,
			"seniority": c.seniority,
			"email": c.email,
			"phone": c.phone,
			"mobile": c.mobile,
			"linkedin_url": c.linkedin_url,
			"is_decision_maker": c.is_decision_maker,
			"is_influencer": c.is_influencer,
			"opted_out_email": c.opted_out_email,
			"opted_out_phone": c.opted_out_phone,
			"owner_id": c.owner_id,
			"last_activity_at": c.last_activity_at.isoformat() if c.last_activity_at else None,
			"engagement_score": str(c.engagement_score) if c.engagement_score is not None else None,
			"status": c.status,
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		session = _get_session()
		from pgappforge.plugins.erp.crm.sales.models import SalesContact
		data = request.get_json(silent=True) or {}
		missing = [f for f in ("tenant_id", "first_name", "last_name") if not data.get(f)]
		if missing:
			return jsonify({"ok": False, "error": f"Missing: {missing}"}), 400
		c = SalesContact(
			tenant_id=data["tenant_id"],
			account_id=data.get("account_id"),
			first_name=data["first_name"],
			last_name=data["last_name"],
			salutation=data.get("salutation"),
			title=data.get("title"),
			department=data.get("department"),
			email=data.get("email"),
			phone=data.get("phone"),
			mobile=data.get("mobile"),
			linkedin_url=data.get("linkedin_url"),
			seniority=data.get("seniority"),
			is_decision_maker=bool(data.get("is_decision_maker", False)),
			is_influencer=bool(data.get("is_influencer", False)),
			owner_id=data.get("owner_id"),
			status="ACTIVE",
		)
		session.add(c)
		session.commit()
		return jsonify({"ok": True, "id": c.id}), 201

	@expose("/<string:contact_id>", methods=["PUT"])
	@has_access
	def update(self, contact_id: str):
		session = _get_session()
		from pgappforge.plugins.erp.crm.sales.models import SalesContact
		c = session.get(SalesContact, contact_id)
		if c is None:
			abort(404)
		data = request.get_json(silent=True) or {}
		updatable = [
			"title", "department", "seniority", "email", "phone", "mobile",
			"linkedin_url", "is_decision_maker", "is_influencer",
			"opted_out_email", "opted_out_phone", "owner_id", "status",
		]
		changed = [f for f in updatable if f in data and (setattr(c, f, data[f]) or True)]
		c.updated_at = datetime.now(timezone.utc)
		session.commit()
		return jsonify({"ok": True, "changed": changed})


# ---------------------------------------------------------------------------
# LeadView
# ---------------------------------------------------------------------------

class LeadView(BaseView):
	"""Lead CRUD + scoring + conversion.

	GET  /crm/leads/                 — list (HTML)
	GET  /crm/leads/<id>             — detail (JSON)
	POST /crm/leads/                 — create (JSON)
	PUT  /crm/leads/<id>             — update status/assignment (JSON)
	POST /crm/leads/<id>/score       — re-score lead
	POST /crm/leads/<id>/convert     — convert to account/contact/opportunity
	POST /crm/leads/<id>/disqualify  — mark DISQUALIFIED
	"""

	route_base = "/crm/leads"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		session = _get_session()
		from pgappforge.plugins.erp.crm.sales.models import Lead
		tenant_id = request.args.get("tenant_id")
		status = request.args.get("status")
		q = (
			sa.select(Lead)
			.order_by(sa.desc(Lead.score), sa.desc(Lead.created_at))
			.limit(500)
		)
		if tenant_id:
			q = q.where(Lead.tenant_id == tenant_id)
		if status:
			q = q.where(Lead.status == status.upper())
		leads = session.execute(q).scalars().all()

		rows = "".join(
			f"<tr>"
			f"<td>{_he(l.first_name or '')} {_he(l.last_name or '')}</td>"
			f"<td>{_he(l.company or '—')}</td>"
			f"<td>{_he(l.source or '—')}</td>"
			f"<td>{_he(l.status)}</td>"
			f"<td><strong>{l.score}</strong></td>"
			f"<td>{_he(l.grade or '—')}</td>"
			f"<td>{_he(l.email or '—')}</td>"
			f"<td><a href='/crm/leads/{_he(l.id)}' class='btn btn-xs btn-primary'>View</a></td>"
			f"</tr>"
			for l in leads
		)
		html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>Leads</title>
<link rel="stylesheet" href="https://maxcdn.bootstrapcdn.com/bootstrap/3.3.7/css/bootstrap.min.css">
</head><body style="padding:24px">
<h3>Leads <small>({len(leads)})</small></h3>
<table class="table table-bordered table-hover table-condensed">
<thead><tr><th>Name</th><th>Company</th><th>Source</th><th>Status</th>
<th>Score</th><th>Grade</th><th>Email</th><th></th></tr></thead>
<tbody>{rows}</tbody></table></body></html>"""
		return make_response(html, 200)

	@expose("/<string:lead_id>")
	@has_access
	def detail(self, lead_id: str):
		session = _get_session()
		from pgappforge.plugins.erp.crm.sales.models import Lead
		l = session.get(Lead, lead_id)
		if l is None:
			abort(404)
		return jsonify({
			"id": l.id,
			"tenant_id": l.tenant_id,
			"first_name": l.first_name,
			"last_name": l.last_name,
			"company": l.company,
			"title": l.title,
			"email": l.email,
			"phone": l.phone,
			"source": l.source,
			"campaign_id": l.campaign_id,
			"utm_source": l.utm_source,
			"utm_medium": l.utm_medium,
			"utm_campaign": l.utm_campaign,
			"score": l.score,
			"grade": l.grade,
			"status": l.status,
			"assigned_to": l.assigned_to,
			"converted_at": l.converted_at.isoformat() if l.converted_at else None,
			"converted_account_id": l.converted_account_id,
			"converted_contact_id": l.converted_contact_id,
			"converted_opportunity_id": l.converted_opportunity_id,
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		session = _get_session()
		from pgappforge.plugins.erp.crm.sales.models import Lead
		from pgappforge.plugins.erp.crm.sales.events import LeadCreatedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event
		data = request.get_json(silent=True) or {}
		if not data.get("tenant_id"):
			return jsonify({"ok": False, "error": "tenant_id required"}), 400
		l = Lead(
			tenant_id=data["tenant_id"],
			first_name=data.get("first_name"),
			last_name=data.get("last_name"),
			company=data.get("company"),
			title=data.get("title"),
			email=data.get("email"),
			phone=data.get("phone"),
			source=(data.get("source") or "OTHER").upper(),
			campaign_id=data.get("campaign_id"),
			utm_source=data.get("utm_source"),
			utm_medium=data.get("utm_medium"),
			utm_campaign=data.get("utm_campaign"),
			score=int(data.get("score") or 0),
			status="NEW",
			assigned_to=data.get("assigned_to"),
			description=data.get("description"),
		)
		session.add(l)
		session.flush()
		emit_event(
			LeadCreatedEvent(
				aggregate_id=l.id, aggregate_type="Lead", tenant_id=l.tenant_id,
				lead_id=l.id, source=l.source or "", email=l.email or "",
				assigned_to=l.assigned_to or "",
			),
			session,
		)
		session.commit()
		return jsonify({"ok": True, "id": l.id}), 201

	@expose("/<string:lead_id>", methods=["PUT"])
	@has_access
	def update(self, lead_id: str):
		session = _get_session()
		from pgappforge.plugins.erp.crm.sales.models import Lead
		l = session.get(Lead, lead_id)
		if l is None:
			abort(404)
		data = request.get_json(silent=True) or {}
		updatable = ["status", "assigned_to", "description", "campaign_id",
		             "utm_source", "utm_medium", "utm_campaign"]
		changed = [f for f in updatable if f in data and (setattr(l, f, data[f]) or True)]
		l.updated_at = datetime.now(timezone.utc)
		session.commit()
		return jsonify({"ok": True, "changed": changed})

	@expose("/<string:lead_id>/score", methods=["POST"])
	@has_access
	def score(self, lead_id: str):
		session = _get_session()
		from pgappforge.plugins.erp.crm.sales.services import SalesService, SalesServiceError
		svc = SalesService()
		try:
			new_score = svc.score_lead(lead_id, session)
			session.commit()
			return jsonify({"ok": True, "score": new_score})
		except SalesServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 422

	@expose("/<string:lead_id>/convert", methods=["POST"])
	@has_access
	def convert(self, lead_id: str):
		session = _get_session()
		from pgappforge.plugins.erp.crm.sales.services import SalesService, SalesServiceError
		data = request.get_json(silent=True) or {}
		svc = SalesService()
		try:
			result = svc.convert_lead(lead_id, data, session)
			session.commit()
			return jsonify({"ok": True, **result}), 201
		except SalesServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 422

	@expose("/<string:lead_id>/disqualify", methods=["POST"])
	@has_access
	def disqualify(self, lead_id: str):
		session = _get_session()
		from pgappforge.plugins.erp.crm.sales.models import Lead
		from pgappforge.plugins.erp.crm.sales.events import LeadDisqualifiedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event
		l = session.get(Lead, lead_id)
		if l is None:
			abort(404)
		if l.status in ("CONVERTED", "DISQUALIFIED"):
			return jsonify({"ok": False, "error": f"Lead already {l.status}"}), 400
		data = request.get_json(silent=True) or {}
		reason = data.get("reason", "")
		l.status = "DISQUALIFIED"
		l.updated_at = datetime.now(timezone.utc)
		emit_event(
			LeadDisqualifiedEvent(
				aggregate_id=lead_id, aggregate_type="Lead", tenant_id=l.tenant_id,
				lead_id=lead_id, reason=reason,
			),
			session,
		)
		session.commit()
		return jsonify({"ok": True, "status": "DISQUALIFIED"})


# ---------------------------------------------------------------------------
# OpportunityView
# ---------------------------------------------------------------------------

class OpportunityView(BaseView):
	"""Opportunity CRUD + stage management.

	GET  /crm/opportunities/                — list (HTML)
	GET  /crm/opportunities/<id>            — detail (JSON)
	POST /crm/opportunities/               — create (JSON)
	PUT  /crm/opportunities/<id>            — update fields (JSON)
	POST /crm/opportunities/<id>/advance   — advance stage (JSON)
	"""

	route_base = "/crm/opportunities"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		session = _get_session()
		from pgappforge.plugins.erp.crm.sales.models import Opportunity
		tenant_id = request.args.get("tenant_id")
		stage = request.args.get("stage")
		owner_id = request.args.get("owner_id")
		q = (
			sa.select(Opportunity)
			.order_by(sa.desc(Opportunity.amount_cents), Opportunity.expected_close_date)
			.limit(500)
		)
		if tenant_id:
			q = q.where(Opportunity.tenant_id == tenant_id)
		if stage:
			q = q.where(Opportunity.stage == stage.upper())
		if owner_id:
			q = q.where(Opportunity.owner_id == owner_id)
		opps = session.execute(q).scalars().all()

		rows = "".join(
			f"<tr>"
			f"<td>{_he(o.opportunity_name)}</td>"
			f"<td>{_he(o.stage)}</td>"
			f"<td>{_he(o.forecast_category or '—')}</td>"
			f"<td class='text-right'>{_cents(o.amount_cents, o.currency_code)}</td>"
			f"<td>{o.probability}%</td>"
			f"<td>{_he(o.expected_close_date or '—')}</td>"
			f"<td><a href='/crm/opportunities/{_he(o.id)}' class='btn btn-xs btn-primary'>View</a></td>"
			f"</tr>"
			for o in opps
		)
		html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>Opportunities</title>
<link rel="stylesheet" href="https://maxcdn.bootstrapcdn.com/bootstrap/3.3.7/css/bootstrap.min.css">
</head><body style="padding:24px">
<h3>Opportunities <small>({len(opps)})</small></h3>
<table class="table table-bordered table-hover table-condensed">
<thead><tr><th>Name</th><th>Stage</th><th>Forecast</th><th>Amount</th>
<th>Probability</th><th>Close Date</th><th></th></tr></thead>
<tbody>{rows}</tbody></table></body></html>"""
		return make_response(html, 200)

	@expose("/<string:opp_id>")
	@has_access
	def detail(self, opp_id: str):
		session = _get_session()
		from pgappforge.plugins.erp.crm.sales.models import Opportunity
		o = session.get(Opportunity, opp_id)
		if o is None:
			abort(404)
		return jsonify({
			"id": o.id,
			"tenant_id": o.tenant_id,
			"account_id": o.account_id,
			"contact_id": o.contact_id,
			"opportunity_name": o.opportunity_name,
			"stage": o.stage,
			"amount_cents": o.amount_cents,
			"currency_code": o.currency_code,
			"probability": o.probability,
			"forecast_category": o.forecast_category,
			"expected_close_date": o.expected_close_date.isoformat() if o.expected_close_date else None,
			"owner_id": o.owner_id,
			"lead_source": o.lead_source,
			"type": o.type,
			"reason_won": o.reason_won,
			"reason_lost": o.reason_lost,
			"competitor": o.competitor,
			"einstein_score": str(o.einstein_score) if o.einstein_score is not None else None,
			"next_step": o.next_step,
			"closed_at": o.closed_at.isoformat() if o.closed_at else None,
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		session = _get_session()
		from pgappforge.plugins.erp.crm.sales.models import Opportunity
		from pgappforge.plugins.erp.crm.sales.services import _STAGE_PROBABILITY, _STAGE_FORECAST
		from pgappforge.plugins.erp.crm.sales.events import OpportunityCreatedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event
		data = request.get_json(silent=True) or {}
		missing = [f for f in ("tenant_id", "account_id", "opportunity_name") if not data.get(f)]
		if missing:
			return jsonify({"ok": False, "error": f"Missing: {missing}"}), 400
		stage = (data.get("stage") or "PROSPECTING").upper()
		o = Opportunity(
			tenant_id=data["tenant_id"],
			account_id=data["account_id"],
			contact_id=data.get("contact_id"),
			opportunity_name=data["opportunity_name"],
			stage=stage,
			amount_cents=data.get("amount_cents"),
			currency_code=(data.get("currency_code") or "USD").upper(),
			probability=int(data.get("probability") or _STAGE_PROBABILITY.get(stage, 10)),
			forecast_category=data.get("forecast_category") or _STAGE_FORECAST.get(stage, "PIPELINE"),
			expected_close_date=date.fromisoformat(data["expected_close_date"]) if data.get("expected_close_date") else None,
			owner_id=data.get("owner_id"),
			lead_source=data.get("lead_source"),
			type=data.get("type"),
			next_step=data.get("next_step"),
			description=data.get("description"),
		)
		session.add(o)
		session.flush()
		emit_event(
			OpportunityCreatedEvent(
				aggregate_id=o.id, aggregate_type="Opportunity", tenant_id=o.tenant_id,
				opportunity_id=o.id, account_id=o.account_id,
				opportunity_name=o.opportunity_name,
				amount_cents=o.amount_cents or 0, currency_code=o.currency_code,
				stage=o.stage, owner_id=o.owner_id or "",
			),
			session,
		)
		session.commit()
		return jsonify({"ok": True, "id": o.id}), 201

	@expose("/<string:opp_id>", methods=["PUT"])
	@has_access
	def update(self, opp_id: str):
		session = _get_session()
		from pgappforge.plugins.erp.crm.sales.models import Opportunity
		o = session.get(Opportunity, opp_id)
		if o is None:
			abort(404)
		data = request.get_json(silent=True) or {}
		updatable = [
			"opportunity_name", "amount_cents", "currency_code", "probability",
			"forecast_category", "owner_id", "lead_source", "type",
			"next_step", "description", "einstein_score", "competitor",
		]
		if "expected_close_date" in data:
			o.expected_close_date = date.fromisoformat(data["expected_close_date"]) if data["expected_close_date"] else None
		changed = [f for f in updatable if f in data and (setattr(o, f, data[f]) or True)]
		o.updated_at = datetime.now(timezone.utc)
		session.commit()
		return jsonify({"ok": True, "changed": changed})

	@expose("/<string:opp_id>/advance", methods=["POST"])
	@has_access
	def advance(self, opp_id: str):
		session = _get_session()
		from pgappforge.plugins.erp.crm.sales.services import SalesService, SalesServiceError
		data = request.get_json(silent=True) or {}
		new_stage = data.get("stage")
		if not new_stage:
			return jsonify({"ok": False, "error": "stage required"}), 400
		svc = SalesService()
		try:
			opp = svc.advance_stage(
				opp_id, new_stage, session,
				reason=data.get("reason", ""),
				competitor=data.get("competitor", ""),
			)
			session.commit()
			return jsonify({
				"ok": True, "stage": opp.stage,
				"probability": opp.probability,
				"forecast_category": opp.forecast_category,
			})
		except SalesServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 422


# ---------------------------------------------------------------------------
# ActivityView
# ---------------------------------------------------------------------------

class ActivityView(BaseView):
	"""Activity log CRUD.

	GET  /crm/activities/         — list (JSON)
	POST /crm/activities/         — log activity (JSON)
	PUT  /crm/activities/<id>     — update status/outcome (JSON)
	"""

	route_base = "/crm/activities"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		session = _get_session()
		from pgappforge.plugins.erp.crm.sales.models import Activity
		tenant_id = request.args.get("tenant_id")
		opportunity_id = request.args.get("opportunity_id")
		account_id = request.args.get("account_id")
		q = (
			sa.select(Activity)
			.order_by(sa.desc(Activity.activity_date))
			.limit(200)
		)
		if tenant_id:
			q = q.where(Activity.tenant_id == tenant_id)
		if opportunity_id:
			q = q.where(Activity.opportunity_id == opportunity_id)
		if account_id:
			q = q.where(Activity.account_id == account_id)
		acts = session.execute(q).scalars().all()
		return jsonify({
			"activities": [
				{
					"id": a.id,
					"activity_type": a.activity_type,
					"subject": a.subject,
					"status": a.status,
					"direction": a.direction,
					"outcome": a.outcome,
					"duration_minutes": a.duration_minutes,
					"activity_date": a.activity_date.isoformat() if a.activity_date else None,
					"contact_id": a.contact_id,
					"account_id": a.account_id,
					"opportunity_id": a.opportunity_id,
					"owner_id": a.owner_id,
				}
				for a in acts
			]
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		session = _get_session()
		from pgappforge.plugins.erp.crm.sales.services import SalesService, SalesServiceError
		data = request.get_json(silent=True) or {}
		svc = SalesService()
		try:
			act = svc.record_activity(data, session)
			session.commit()
			return jsonify({"ok": True, "id": act.id}), 201
		except SalesServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 422

	@expose("/<string:activity_id>", methods=["PUT"])
	@has_access
	def update(self, activity_id: str):
		session = _get_session()
		from pgappforge.plugins.erp.crm.sales.models import Activity
		a = session.get(Activity, activity_id)
		if a is None:
			abort(404)
		data = request.get_json(silent=True) or {}
		for f in ("status", "outcome", "duration_minutes", "description"):
			if f in data:
				setattr(a, f, data[f])
		a.updated_at = datetime.now(timezone.utc)
		session.commit()
		return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# SalesReportView — 3 standard reports
# ---------------------------------------------------------------------------

class SalesReportView(BaseView):
	"""Standard sales reports.

	GET /crm/reports/pipeline          — Pipeline by Stage (HTML)
	GET /crm/reports/forecast          — Forecast Summary (HTML)
	GET /crm/reports/leaderboard       — Rep Leaderboard (HTML)
	"""

	route_base = "/crm/reports"
	default_view = "pipeline"

	# ------------------------------------------------------------------
	# Report 1: Pipeline by Stage
	# ------------------------------------------------------------------

	@expose("/pipeline")
	@has_access
	def pipeline(self):
		"""Pipeline by Stage — count and value per stage."""
		session = _get_session()
		from pgappforge.plugins.erp.crm.sales.models import Opportunity

		tenant_id = request.args.get("tenant_id")
		q = (
			sa.select(
				Opportunity.stage,
				sa.func.count(Opportunity.id).label("deal_count"),
				sa.func.coalesce(sa.func.sum(Opportunity.amount_cents), 0).label("total_cents"),
				sa.func.coalesce(
					sa.func.sum(
						Opportunity.amount_cents * Opportunity.probability / 100
					), 0
				).label("weighted_cents"),
			)
			.where(Opportunity.stage.not_in(["CLOSED_WON", "CLOSED_LOST"]))
			.group_by(Opportunity.stage)
			.order_by(Opportunity.stage)
		)
		if tenant_id:
			q = q.where(Opportunity.tenant_id == tenant_id)

		rows_data = session.execute(q).all()
		table_rows = "".join(
			f"<tr>"
			f"<td>{_he(r.stage)}</td>"
			f"<td class='text-right'>{r.deal_count}</td>"
			f"<td class='text-right'>{_cents(int(r.total_cents))}</td>"
			f"<td class='text-right'>{_cents(int(r.weighted_cents))}</td>"
			f"</tr>"
			for r in rows_data
		)
		total_deals = sum(r.deal_count for r in rows_data)
		total_value = sum(int(r.total_cents) for r in rows_data)
		total_weighted = sum(int(r.weighted_cents) for r in rows_data)

		html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>Sales Pipeline</title>
<link rel="stylesheet" href="https://maxcdn.bootstrapcdn.com/bootstrap/3.3.7/css/bootstrap.min.css">
<style>body{{padding:24px}} @media print{{.noprint{{display:none}}}}</style>
</head><body>
<div class="noprint" style="margin-bottom:12px">
  <h3>Sales Pipeline by Stage</h3>
  <button onclick="window.print()" class="btn btn-xs btn-primary">Print</button>
</div>
<table class="table table-bordered table-condensed">
<thead><tr><th>Stage</th><th class="text-right">Deals</th>
<th class="text-right">Total Value</th><th class="text-right">Weighted Value</th></tr></thead>
<tbody>{table_rows}</tbody>
<tfoot><tr class="active">
  <td><strong>TOTAL</strong></td>
  <td class="text-right"><strong>{total_deals}</strong></td>
  <td class="text-right"><strong>{_cents(total_value)}</strong></td>
  <td class="text-right"><strong>{_cents(total_weighted)}</strong></td>
</tr></tfoot>
</table>
<p style="color:#888;font-size:0.75em">Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}</p>
</body></html>"""
		return make_response(html, 200)

	# ------------------------------------------------------------------
	# Report 2: Forecast Summary
	# ------------------------------------------------------------------

	@expose("/forecast")
	@has_access
	def forecast(self):
		"""Forecast Summary — pipeline/best_case/commit/closed by owner."""
		session = _get_session()
		from pgappforge.plugins.erp.crm.sales.models import SalesForecast

		tenant_id = request.args.get("tenant_id")
		period_id = request.args.get("period_id")
		q = sa.select(SalesForecast).where(SalesForecast.submitted_at.isnot(None))
		if tenant_id:
			q = q.where(SalesForecast.tenant_id == tenant_id)
		if period_id:
			q = q.where(SalesForecast.period_id == period_id)
		q = q.order_by(sa.desc(SalesForecast.submitted_at)).limit(200)
		forecasts = session.execute(q).scalars().all()

		rows = "".join(
			f"<tr>"
			f"<td>{_he(f.owner_id)}</td>"
			f"<td>{_he(f.period_id)}</td>"
			f"<td class='text-right'>{_cents(f.pipeline_cents)}</td>"
			f"<td class='text-right'>{_cents(f.best_case_cents)}</td>"
			f"<td class='text-right'>{_cents(f.commit_cents)}</td>"
			f"<td class='text-right'>{_cents(f.closed_cents)}</td>"
			f"<td class='text-right'>{_cents(f.ai_forecast_cents) if f.ai_forecast_cents else '—'}</td>"
			f"<td>{_he(f.submitted_at.strftime('%Y-%m-%d') if f.submitted_at else '—')}</td>"
			f"</tr>"
			for f in forecasts
		)
		html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>Sales Forecast</title>
<link rel="stylesheet" href="https://maxcdn.bootstrapcdn.com/bootstrap/3.3.7/css/bootstrap.min.css">
<style>body{{padding:24px}}</style>
</head><body>
<h3>Sales Forecast Summary</h3>
<table class="table table-bordered table-condensed table-hover">
<thead><tr><th>Owner</th><th>Period</th><th class="text-right">Pipeline</th>
<th class="text-right">Best Case</th><th class="text-right">Commit</th>
<th class="text-right">Closed</th><th class="text-right">AI Forecast</th>
<th>Submitted</th></tr></thead>
<tbody>{rows}</tbody></table>
<p style="color:#888;font-size:0.75em">Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}</p>
</body></html>"""
		return make_response(html, 200)

	# ------------------------------------------------------------------
	# Report 3: Rep Leaderboard
	# ------------------------------------------------------------------

	@expose("/leaderboard")
	@has_access
	def leaderboard(self):
		"""Rep Leaderboard — closed won deals ranked by revenue."""
		session = _get_session()
		from pgappforge.plugins.erp.crm.sales.models import Opportunity

		tenant_id = request.args.get("tenant_id")
		since = request.args.get("since")

		q = (
			sa.select(
				Opportunity.owner_id,
				sa.func.count(Opportunity.id).label("deals_won"),
				sa.func.coalesce(sa.func.sum(Opportunity.amount_cents), 0).label("revenue_cents"),
			)
			.where(Opportunity.stage == "CLOSED_WON")
			.group_by(Opportunity.owner_id)
			.order_by(sa.desc(sa.func.sum(Opportunity.amount_cents)))
			.limit(50)
		)
		if tenant_id:
			q = q.where(Opportunity.tenant_id == tenant_id)
		if since:
			q = q.where(Opportunity.closed_at >= datetime.fromisoformat(since))

		rows_data = session.execute(q).all()
		table_rows = "".join(
			f"<tr>"
			f"<td>{i + 1}</td>"
			f"<td>{_he(r.owner_id)}</td>"
			f"<td class='text-right'>{r.deals_won}</td>"
			f"<td class='text-right'><strong>{_cents(int(r.revenue_cents))}</strong></td>"
			f"</tr>"
			for i, r in enumerate(rows_data)
		)
		html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>Sales Leaderboard</title>
<link rel="stylesheet" href="https://maxcdn.bootstrapcdn.com/bootstrap/3.3.7/css/bootstrap.min.css">
<style>body{{padding:24px}}</style>
</head><body>
<h3>Sales Rep Leaderboard — Closed Won</h3>
<table class="table table-bordered table-condensed table-hover">
<thead><tr><th>#</th><th>Rep</th><th class="text-right">Deals Won</th>
<th class="text-right">Revenue</th></tr></thead>
<tbody>{table_rows}</tbody></table>
<p style="color:#888;font-size:0.75em">Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}</p>
</body></html>"""
		return make_response(html, 200)


__all__ = [
	"SalesAccountView",
	"SalesContactView",
	"LeadView",
	"OpportunityView",
	"ActivityView",
	"SalesReportView",
]
