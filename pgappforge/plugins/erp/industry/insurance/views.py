"""
pgappforge/plugins/erp/industry/insurance/views.py

Flask views for the Insurance plugin.

Route summary
-------------
PolicyView                  /ins/policies/
  ├─ GET  /ins/policies/              — list (HTML, currency + date range)
  ├─ GET  /ins/policies/<id>          — detail (JSON)
  ├─ POST /ins/policies/underwrite    — compute risk score + premium quote
  └─ POST /ins/policies/issue         — issue policy from quote

ClaimView                   /ins/claims/
  ├─ GET  /ins/claims/                — list
  ├─ GET  /ins/claims/<id>            — detail
  ├─ POST /ins/claims/                — file a claim
  ├─ POST /ins/claims/<id>/assess     — set assessed amount
  ├─ POST /ins/claims/<id>/approve    — approve claim
  └─ POST /ins/claims/<id>/pay        — pay approved claim

UnderwritingDashboardView   /ins/underwriting/
  └─ GET  /ins/underwriting/dashboard — underwriting metrics (HTML)

ClaimsAnalyticsDashboardView /ins/claims-analytics/
  └─ GET  /ins/claims-analytics/      — claims KPIs (HTML)
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone

import sqlalchemy as sa
from flask import abort, jsonify, make_response, request

from pgappforge import BaseView, expose
from pgappforge.security.decorators import has_access
from pgappforge.plugins.erp.foundation.commons import format_currency
from pgappforge.plugins.erp.foundation.view_helpers import (
	currency_widget,
	date_widget,
	date_range_widget,
	file_widget,
	rich_text_widget,
	select2_widget,
	star_widget,
	chart_widget,
)

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


def _status_badge(status: str) -> str:
	colors = {
		"ACTIVE": "success", "DRAFT": "default", "LAPSED": "warning",
		"CANCELLED": "danger", "EXPIRED": "default",
		"REPORTED": "info", "UNDER_REVIEW": "warning", "APPROVED": "primary",
		"REJECTED": "danger", "PAID": "success", "CLOSED": "default",
	}
	color = colors.get(status.upper(), "default")
	return f"<span class='label label-{color}'>{_he(status)}</span>"


# ---------------------------------------------------------------------------
# PolicyView
# ---------------------------------------------------------------------------

class PolicyView(BaseView):
	"""Insurance Policy CRUD + underwriting/issuance workflow.

	Widgets used:
	  - CurrencyWidget for coverage_amount_cents, annual_premium_cents
	  - DateRangeWidget for coverage_start/coverage_end
	  - Select2Widget for product_type, payment_frequency
	  - StarRatingWidget for risk_score (0–5 mapped from 0.0–1.0)
	"""

	route_base = "/ins/policies"
	default_view = "list"

	widget_config = {
		"coverage_amount_cents": currency_widget("USD"),
		"annual_premium_cents": currency_widget("USD"),
		"coverage_period": date_range_widget(),
		"product_type": select2_widget(["LIFE", "PROPERTY", "CASUALTY", "HEALTH", "LIABILITY"]),
		"payment_frequency": select2_widget(["MONTHLY", "QUARTERLY", "ANNUAL"]),
		"risk_score": star_widget(max_rating=5, readonly=True),
	}

	@expose("/")
	@has_access
	def list(self):
		session = _get_session()
		from pgappforge.plugins.erp.industry.insurance.models import Policy

		tenant_id = request.args.get("tenant_id")
		status = request.args.get("status")

		q = (
			sa.select(Policy)
			.order_by(sa.desc(Policy.created_at))
			.limit(500)
		)
		if tenant_id:
			q = q.where(Policy.tenant_id == tenant_id)
		if status:
			q = q.where(Policy.status == status.upper())

		policies = session.execute(q).scalars().all()

		rows = "".join(
			f"<tr>"
			f"<td>{_he(p.policy_number)}</td>"
			f"<td>{_status_badge(p.status)}</td>"
			f"<td>{_he(p.payment_frequency)}</td>"
			f"<td class='text-right'>{_cents(p.coverage_amount_cents)}</td>"
			f"<td class='text-right'>{_cents(p.annual_premium_cents)} / yr</td>"
			f"<td>{_he(p.coverage_start)} → {_he(p.coverage_end)}</td>"
			f"<td><a href='/ins/policies/{_he(p.id)}' class='btn btn-xs btn-primary'>View</a></td>"
			f"</tr>"
			for p in policies
		)
		html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>Insurance Policies</title>
<link rel="stylesheet" href="https://maxcdn.bootstrapcdn.com/bootstrap/3.3.7/css/bootstrap.min.css">
<style>body{{padding:24px}}</style>
</head><body>
<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">
  <h3>Insurance Policies <small>({len(policies)})</small></h3>
  <div>
    <a href="/ins/underwriting/dashboard" class="btn btn-default btn-sm">Underwriting</a>
    <a href="/ins/claims-analytics/" class="btn btn-default btn-sm" style="margin-left:4px">Claims Analytics</a>
  </div>
</div>
<table class="table table-bordered table-hover table-condensed">
<thead><tr>
  <th>Policy #</th><th>Status</th><th>Frequency</th>
  <th class="text-right">Coverage</th><th class="text-right">Annual Premium</th>
  <th>Period</th><th></th>
</tr></thead>
<tbody>{rows}</tbody></table>
<p style="color:#888;font-size:0.75em">Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}</p>
</body></html>"""
		return make_response(html, 200)

	@expose("/<string:policy_id>")
	@has_access
	def detail(self, policy_id: str):
		session = _get_session()
		from pgappforge.plugins.erp.industry.insurance.models import Policy, Premium, Claim

		policy = session.get(Policy, policy_id)
		if policy is None:
			abort(404)

		premiums = session.execute(
			sa.select(Premium)
			.where(Premium.policy_id == policy_id)
			.order_by(Premium.due_date)
		).scalars().all()

		claims = session.execute(
			sa.select(Claim)
			.where(Claim.policy_id == policy_id)
			.order_by(sa.desc(Claim.incident_date))
		).scalars().all()

		return jsonify({
			"id": policy.id,
			"policy_number": policy.policy_number,
			"product_id": policy.product_id,
			"holder_id": policy.holder_id,
			"insured_party_id": policy.insured_party_id,
			"status": policy.status,
			"coverage_start": policy.coverage_start.isoformat(),
			"coverage_end": policy.coverage_end.isoformat(),
			"coverage_amount_cents": policy.coverage_amount_cents,
			"coverage_amount_display": _cents(policy.coverage_amount_cents),
			"annual_premium_cents": policy.annual_premium_cents,
			"annual_premium_display": _cents(policy.annual_premium_cents),
			"payment_frequency": policy.payment_frequency,
			"exclusions": policy.exclusions,
			"beneficiaries": policy.beneficiaries,
			"agent_id": policy.agent_id,
			"widget_config": self.widget_config,
			"premiums": [
				{
					"id": pr.id,
					"due_date": pr.due_date.isoformat(),
					"amount_cents": pr.amount_cents,
					"amount_display": _cents(pr.amount_cents),
					"status": pr.status,
					"paid_at": pr.paid_at.isoformat() if pr.paid_at else None,
				}
				for pr in premiums
			],
			"claims": [
				{
					"id": c.id,
					"claim_number": c.claim_number,
					"status": c.status,
					"incident_date": c.incident_date.isoformat(),
					"claimed_amount_cents": c.claimed_amount_cents,
					"approved_amount_cents": c.approved_amount_cents,
					"paid_amount_cents": c.paid_amount_cents,
				}
				for c in claims
			],
		})

	@expose("/underwrite", methods=["POST"])
	@has_access
	def underwrite(self):
		"""Compute risk score and premium quote (no policy created)."""
		session = _get_session()
		from pgappforge.plugins.erp.industry.insurance.services import InsuranceService, InsuranceServiceError

		data = request.get_json(silent=True) or {}
		missing = [f for f in ("product_id", "holder_id") if not data.get(f)]
		if missing:
			return jsonify({"ok": False, "error": f"Missing: {missing}"}), 400

		svc = InsuranceService()
		try:
			quote = svc.underwrite_policy(
				product_id=data["product_id"],
				holder_id=data["holder_id"],
				coverage_details=data.get("coverage_details") or data,
				session=session,
			)
			return jsonify({"ok": True, **quote})
		except InsuranceServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 422

	@expose("/issue", methods=["POST"])
	@has_access
	def issue(self):
		"""Issue a policy from underwriting quote details."""
		session = _get_session()
		from pgappforge.plugins.erp.industry.insurance.services import InsuranceService, InsuranceServiceError

		data = request.get_json(silent=True) or {}
		svc = InsuranceService()
		try:
			policy = svc.issue_policy(data, session)
			session.commit()
			return jsonify({
				"ok": True,
				"id": policy.id,
				"policy_number": policy.policy_number,
				"status": policy.status,
				"annual_premium_cents": policy.annual_premium_cents,
			}), 201
		except InsuranceServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 422


# ---------------------------------------------------------------------------
# ClaimView
# ---------------------------------------------------------------------------

class ClaimView(BaseView):
	"""Insurance Claim lifecycle view.

	Widgets used:
	  - CurrencyWidget for claimed/assessed/approved/paid amounts
	  - FileUploadWidget for supporting documents
	  - RichTextEditorWidget for incident_description
	"""

	route_base = "/ins/claims"
	default_view = "list"

	widget_config = {
		"claimed_amount_cents": currency_widget("USD"),
		"assessed_amount_cents": currency_widget("USD"),
		"approved_amount_cents": currency_widget("USD"),
		"paid_amount_cents": currency_widget("USD"),
		"documents": file_widget(multiple=True, types=["pdf", "jpg", "png", "docx"]),
		"incident_description": rich_text_widget(height=200),
	}

	@expose("/")
	@has_access
	def list(self):
		session = _get_session()
		from pgappforge.plugins.erp.industry.insurance.models import Claim

		tenant_id = request.args.get("tenant_id")
		status = request.args.get("status")
		policy_id = request.args.get("policy_id")

		q = (
			sa.select(Claim)
			.order_by(sa.desc(Claim.reported_date))
			.limit(500)
		)
		if tenant_id:
			q = q.where(Claim.tenant_id == tenant_id)
		if status:
			q = q.where(Claim.status == status.upper())
		if policy_id:
			q = q.where(Claim.policy_id == policy_id)

		claims = session.execute(q).scalars().all()
		return jsonify({
			"claims": [
				{
					"id": c.id,
					"claim_number": c.claim_number,
					"policy_id": c.policy_id,
					"status": c.status,
					"incident_date": c.incident_date.isoformat(),
					"reported_date": c.reported_date.isoformat(),
					"claimed_amount_cents": c.claimed_amount_cents,
					"claimed_amount_display": _cents(c.claimed_amount_cents),
					"approved_amount_cents": c.approved_amount_cents,
					"paid_amount_cents": c.paid_amount_cents,
				}
				for c in claims
			]
		})

	@expose("/<string:claim_id>")
	@has_access
	def detail(self, claim_id: str):
		session = _get_session()
		from pgappforge.plugins.erp.industry.insurance.models import Claim

		claim = session.get(Claim, claim_id)
		if claim is None:
			abort(404)

		return jsonify({
			"id": claim.id,
			"claim_number": claim.claim_number,
			"policy_id": claim.policy_id,
			"claimant_id": claim.claimant_id,
			"incident_date": claim.incident_date.isoformat(),
			"reported_date": claim.reported_date.isoformat(),
			"claim_type": claim.claim_type,
			"incident_description": claim.incident_description,
			"incident_location": claim.incident_location,
			"claimed_amount_cents": claim.claimed_amount_cents,
			"claimed_amount_display": _cents(claim.claimed_amount_cents),
			"assessed_amount_cents": claim.assessed_amount_cents,
			"approved_amount_cents": claim.approved_amount_cents,
			"paid_amount_cents": claim.paid_amount_cents,
			"status": claim.status,
			"assessor_id": claim.assessor_id,
			"adjudication_notes": claim.adjudication_notes,
			"documents": claim.documents,
			"widget_config": self.widget_config,
		})

	@expose("/", methods=["POST"])
	@has_access
	def file_claim(self):
		"""File a new claim against a policy."""
		session = _get_session()
		from pgappforge.plugins.erp.industry.insurance.services import InsuranceService, InsuranceServiceError

		data = request.get_json(silent=True) or {}
		missing = [f for f in ("policy_id", "claimant_id", "incident_date", "claimed_amount_cents")
		           if not data.get(f) and data.get(f) != 0]
		if missing:
			return jsonify({"ok": False, "error": f"Missing: {missing}"}), 400

		svc = InsuranceService()
		try:
			claim = svc.file_claim(data["policy_id"], data, session)
			session.commit()
			return jsonify({
				"ok": True,
				"id": claim.id,
				"claim_number": claim.claim_number,
				"status": claim.status,
			}), 201
		except InsuranceServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 422

	@expose("/<string:claim_id>/assess", methods=["POST"])
	@has_access
	def assess(self, claim_id: str):
		session = _get_session()
		from pgappforge.plugins.erp.industry.insurance.services import InsuranceService, InsuranceServiceError

		data = request.get_json(silent=True) or {}
		assessed = data.get("assessed_amount_cents")
		if assessed is None:
			return jsonify({"ok": False, "error": "assessed_amount_cents required"}), 400

		svc = InsuranceService()
		try:
			claim = svc.assess_claim(claim_id, int(assessed), session)
			session.commit()
			return jsonify({"ok": True, "status": claim.status, "assessed_amount_cents": claim.assessed_amount_cents})
		except InsuranceServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 422

	@expose("/<string:claim_id>/approve", methods=["POST"])
	@has_access
	def approve(self, claim_id: str):
		session = _get_session()
		from pgappforge.plugins.erp.industry.insurance.services import InsuranceService, InsuranceServiceError

		data = request.get_json(silent=True) or {}
		approved = data.get("approved_amount_cents")
		if approved is None:
			return jsonify({"ok": False, "error": "approved_amount_cents required"}), 400

		svc = InsuranceService()
		try:
			claim = svc.approve_claim(
				claim_id,
				int(approved),
				session,
				assessor_id=data.get("assessor_id", ""),
				notes=data.get("notes", ""),
			)
			session.commit()
			return jsonify({"ok": True, "status": claim.status, "approved_amount_cents": claim.approved_amount_cents})
		except InsuranceServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 422

	@expose("/<string:claim_id>/pay", methods=["POST"])
	@has_access
	def pay(self, claim_id: str):
		session = _get_session()
		from pgappforge.plugins.erp.industry.insurance.services import InsuranceService, InsuranceServiceError

		svc = InsuranceService()
		try:
			result = svc.pay_claim(claim_id, session)
			session.commit()
			return jsonify({"ok": True, **result})
		except InsuranceServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 422


# ---------------------------------------------------------------------------
# UnderwritingDashboardView
# ---------------------------------------------------------------------------

class UnderwritingDashboardView(BaseView):
	"""Underwriting metrics dashboard.

	GET /ins/underwriting/dashboard — active policies by product type, avg risk, premium revenue
	"""

	route_base = "/ins/underwriting"
	default_view = "dashboard"

	widget_config = {
		"premium_chart": chart_widget("bar"),
		"risk_distribution": chart_widget("doughnut"),
	}

	@expose("/dashboard")
	@has_access
	def dashboard(self):
		session = _get_session()
		from pgappforge.plugins.erp.industry.insurance.models import Policy, InsuranceProduct, PolicyHolder

		tenant_id = request.args.get("tenant_id")

		# Policies by status
		status_q = (
			sa.select(
				Policy.status,
				sa.func.count(Policy.id).label("count"),
				sa.func.coalesce(sa.func.sum(Policy.annual_premium_cents), 0).label("premium_sum"),
				sa.func.coalesce(sa.func.sum(Policy.coverage_amount_cents), 0).label("coverage_sum"),
			)
			.group_by(Policy.status)
			.order_by(Policy.status)
		)
		if tenant_id:
			status_q = status_q.where(Policy.tenant_id == tenant_id)
		status_rows = session.execute(status_q).all()

		status_table = "".join(
			f"<tr>"
			f"<td>{_status_badge(r.status)}</td>"
			f"<td class='text-right'>{r.count}</td>"
			f"<td class='text-right'>{_cents(int(r.premium_sum))}</td>"
			f"<td class='text-right'>{_cents(int(r.coverage_sum))}</td>"
			f"</tr>"
			for r in status_rows
		)

		# Holder risk score distribution
		risk_q = sa.select(
			sa.func.avg(PolicyHolder.risk_score).label("avg_risk"),
			sa.func.count(PolicyHolder.id).label("count"),
		)
		if tenant_id:
			risk_q = risk_q.where(PolicyHolder.tenant_id == tenant_id)
		risk_row = session.execute(risk_q).one_or_none()
		avg_risk = round(float(risk_row.avg_risk or 0), 4) if risk_row else 0.0

		# Total active premium revenue
		active_premium = session.execute(
			sa.select(sa.func.coalesce(sa.func.sum(Policy.annual_premium_cents), 0))
			.where(Policy.status == "ACTIVE")
			.where(Policy.tenant_id == tenant_id if tenant_id else sa.true())
		).scalar() or 0

		html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>Underwriting Dashboard</title>
<link rel="stylesheet" href="https://maxcdn.bootstrapcdn.com/bootstrap/3.3.7/css/bootstrap.min.css">
<style>body{{padding:24px}}.well{{text-align:center;border-radius:4px}}</style>
</head><body>
<h3>Underwriting Dashboard</h3>
<div class="row" style="margin-bottom:20px">
  <div class="col-md-4">
    <div class="well">
      <h4>Annual Premium Revenue (Active)</h4>
      <p class="h2" style="color:#27ae60">{_cents(int(active_premium))}</p>
    </div>
  </div>
  <div class="col-md-4">
    <div class="well">
      <h4>Avg Portfolio Risk Score</h4>
      <p class="h2" style="color:#e67e22">{avg_risk}</p>
    </div>
  </div>
  <div class="col-md-4">
    <div class="well">
      <h4>Active Policy Count</h4>
      <p class="h2">{sum(r.count for r in status_rows if r.status == "ACTIVE")}</p>
    </div>
  </div>
</div>
<h4>Policies by Status</h4>
<table class="table table-bordered table-condensed">
<thead><tr>
  <th>Status</th><th class="text-right">Count</th>
  <th class="text-right">Annual Premium</th><th class="text-right">Total Coverage</th>
</tr></thead>
<tbody>{status_table}</tbody></table>
<p style="color:#888;font-size:0.75em">Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}</p>
</body></html>"""
		return make_response(html, 200)


# ---------------------------------------------------------------------------
# ClaimsAnalyticsDashboardView
# ---------------------------------------------------------------------------

class ClaimsAnalyticsDashboardView(BaseView):
	"""Claims analytics dashboard — KPIs, status breakdown, loss ratio.

	GET /ins/claims-analytics/  — claims KPI dashboard (HTML)
	"""

	route_base = "/ins/claims-analytics"
	default_view = "index"

	widget_config = {
		"claims_chart": chart_widget("bar"),
		"loss_ratio_chart": chart_widget("line"),
	}

	@expose("/")
	@has_access
	def index(self):
		session = _get_session()
		from pgappforge.plugins.erp.industry.insurance.models import Claim, Policy

		tenant_id = request.args.get("tenant_id")

		# Claims by status
		status_q = (
			sa.select(
				Claim.status,
				sa.func.count(Claim.id).label("count"),
				sa.func.coalesce(sa.func.sum(Claim.claimed_amount_cents), 0).label("claimed"),
				sa.func.coalesce(sa.func.sum(Claim.approved_amount_cents), 0).label("approved"),
				sa.func.coalesce(sa.func.sum(Claim.paid_amount_cents), 0).label("paid"),
			)
			.group_by(Claim.status)
			.order_by(Claim.status)
		)
		if tenant_id:
			status_q = status_q.where(Claim.tenant_id == tenant_id)
		status_rows = session.execute(status_q).all()

		total_paid = sum(int(r.paid) for r in status_rows)
		total_claimed = sum(int(r.claimed) for r in status_rows)

		# Loss ratio: total_paid / total_premium_revenue
		total_premium = session.execute(
			sa.select(sa.func.coalesce(sa.func.sum(Policy.annual_premium_cents), 0))
			.where(Policy.status.in_(("ACTIVE", "EXPIRED")))
			.where(Policy.tenant_id == tenant_id if tenant_id else sa.true())
		).scalar() or 0

		loss_ratio = (total_paid / total_premium * 100) if total_premium else 0.0

		claims_table = "".join(
			f"<tr>"
			f"<td>{_status_badge(r.status)}</td>"
			f"<td class='text-right'>{r.count}</td>"
			f"<td class='text-right'>{_cents(int(r.claimed))}</td>"
			f"<td class='text-right'>{_cents(int(r.approved))}</td>"
			f"<td class='text-right'>{_cents(int(r.paid))}</td>"
			f"</tr>"
			for r in status_rows
		)

		# Monthly claims trend (last 12 months)
		monthly_q = (
			sa.select(
				sa.func.date_trunc("month", Claim.reported_date).label("month"),
				sa.func.count(Claim.id).label("count"),
				sa.func.coalesce(sa.func.sum(Claim.paid_amount_cents), 0).label("paid"),
			)
			.group_by(sa.func.date_trunc("month", Claim.reported_date))
			.order_by(sa.func.date_trunc("month", Claim.reported_date).desc())
			.limit(12)
		)
		if tenant_id:
			monthly_q = monthly_q.where(Claim.tenant_id == tenant_id)
		monthly_rows = session.execute(monthly_q).all()

		monthly_table = "".join(
			f"<tr>"
			f"<td>{_he(r.month.strftime('%Y-%m') if r.month else '?')}</td>"
			f"<td class='text-right'>{r.count}</td>"
			f"<td class='text-right'>{_cents(int(r.paid))}</td>"
			f"</tr>"
			for r in monthly_rows
		)

		html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>Claims Analytics</title>
<link rel="stylesheet" href="https://maxcdn.bootstrapcdn.com/bootstrap/3.3.7/css/bootstrap.min.css">
<style>body{{padding:24px}}.well{{text-align:center;border-radius:4px}}</style>
</head><body>
<h3>Claims Analytics Dashboard</h3>
<div class="row" style="margin-bottom:20px">
  <div class="col-md-3">
    <div class="well">
      <h5>Total Claimed</h5>
      <p class="h3">{_cents(total_claimed)}</p>
    </div>
  </div>
  <div class="col-md-3">
    <div class="well">
      <h5>Total Paid</h5>
      <p class="h3" style="color:#e74c3c">{_cents(total_paid)}</p>
    </div>
  </div>
  <div class="col-md-3">
    <div class="well">
      <h5>Loss Ratio</h5>
      <p class="h3" style="color:{'#e74c3c' if loss_ratio > 70 else '#27ae60'}">{loss_ratio:.1f}%</p>
    </div>
  </div>
  <div class="col-md-3">
    <div class="well">
      <h5>Total Claims Filed</h5>
      <p class="h3">{sum(r.count for r in status_rows)}</p>
    </div>
  </div>
</div>
<h4>Claims by Status</h4>
<table class="table table-bordered table-condensed">
<thead><tr>
  <th>Status</th><th class="text-right">Count</th>
  <th class="text-right">Claimed</th><th class="text-right">Approved</th><th class="text-right">Paid</th>
</tr></thead>
<tbody>{claims_table}</tbody></table>
<h4>Monthly Trend (last 12 months)</h4>
<table class="table table-bordered table-condensed">
<thead><tr><th>Month</th><th class="text-right">Claims</th><th class="text-right">Paid</th></tr></thead>
<tbody>{monthly_table}</tbody></table>
<p style="color:#888;font-size:0.75em">Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}</p>
</body></html>"""
		return make_response(html, 200)


__all__ = [
	"PolicyView",
	"ClaimView",
	"UnderwritingDashboardView",
	"ClaimsAnalyticsDashboardView",
]
