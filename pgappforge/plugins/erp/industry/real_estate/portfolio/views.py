"""
pgappforge/plugins/erp/industry/real_estate/portfolio/views.py

Flask views for the Real Estate Portfolio Analytics sub-plugin.

Route summary
-------------
PropertyPortfolioView     /industry/portfolio/portfolios/
  ├─ GET  /               — list active portfolios
  └─ GET  /<id>           — portfolio detail with summary analytics
PropertyDebtView          /industry/portfolio/debts/
  └─ GET  /               — list debt instruments
CapExRecordView           /industry/portfolio/capex/
  └─ GET  /               — list capex records
InvestorHoldingView       /industry/portfolio/investors/
  └─ GET  /               — list investor holdings
DistributionRecordView    /industry/portfolio/distributions/
  └─ GET  /               — list distribution records
PortfolioDashboardView    /industry/portfolio/
  └─ GET  /dashboard      — KPI dashboard (active portfolios, active debts, pending distributions)
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import sqlalchemy as sa
from flask import abort, jsonify, make_response, request

from pgappforge import BaseView, expose
from pgappforge.security.decorators import has_access
from pgappforge.plugins.erp.base_view import BaseERPView, BaseERPModelView
from pgappforge.plugins.erp.industry.real_estate.portfolio.models import (
	PropertyPortfolio,
	PortfolioProperty,
	PropertyDebt,
	DebtPayment,
	CapExRecord,
	InvestorHolding,
	DistributionRecord,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _get_session():
	from flask import current_app
	ab = current_app.extensions.get("appbuilder")
	if ab and hasattr(ab, "get_session"):
		return ab.get_session
	db = current_app.extensions.get("sqlalchemy")
	if db:
		return db.session
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
# PropertyPortfolioView
# ---------------------------------------------------------------------------

class PropertyPortfolioView(BaseERPView):
	"""Portfolio list and detail with summary analytics."""

	route_base = "/industry/portfolio/portfolios"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		session = _get_session()
		tenant_id = request.args.get("tenant_id")
		status = request.args.get("status", "ACTIVE")

		q = sa.select(PropertyPortfolio).order_by(sa.asc(PropertyPortfolio.name)).limit(500)
		if tenant_id:
			q = q.where(PropertyPortfolio.tenant_id == tenant_id)
		if status:
			q = q.where(PropertyPortfolio.status == status.upper())

		portfolios = session.execute(q).scalars().all()

		rows = "".join(
			f"<tr>"
			f"<td>{_he(p.name)}</td>"
			f"<td><span class='badge badge-{'success' if p.status == 'ACTIVE' else 'secondary'}'>"
			f"{_he(p.status)}</span></td>"
			f"<td>{_he(p.description or '—')}</td>"
			f"<td><a href='/industry/portfolio/portfolios/{_he(p.id)}' class='btn btn-xs btn-primary'>View</a></td>"
			f"</tr>"
			for p in portfolios
		)
		html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>Portfolios</title>
<link rel="stylesheet" href="https://maxcdn.bootstrapcdn.com/bootstrap/3.3.7/css/bootstrap.min.css">
<style>body{{padding:24px}}.badge-success{{background:#27ae60}}.badge-secondary{{background:#7f8c8d}}</style>
</head><body>
<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">
  <h3>Portfolios <small>({len(portfolios)})</small></h3>
  <a href="/industry/portfolio/dashboard" class="btn btn-default btn-sm">Dashboard</a>
</div>
<table class="table table-bordered table-hover table-condensed">
<thead><tr><th>Name</th><th>Status</th><th>Description</th><th></th></tr></thead>
<tbody>{rows}</tbody></table>
<p style="color:#888;font-size:0.75em">Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}</p>
</body></html>"""
		return make_response(html, 200)

	@expose("/<string:portfolio_id>")
	@has_access
	def detail(self, portfolio_id: str):
		session = _get_session()
		portfolio = session.get(PropertyPortfolio, portfolio_id)
		if portfolio is None:
			abort(404)

		tenant_id = request.args.get("tenant_id") or portfolio.tenant_id
		try:
			from pgappforge.plugins.erp.industry.real_estate.portfolio.services import (
				PortfolioAnalyticsService,
			)
			summary = PortfolioAnalyticsService().get_portfolio_summary(
				portfolio_id=portfolio_id,
				tenant_id=tenant_id,
				session=session,
			)
		except Exception as exc:
			log.warning("PortfolioDashboard.detail: summary failed: %s", exc)
			summary = {"properties": [], "totals": {}}

		return jsonify({
			"id": portfolio.id,
			"tenant_id": portfolio.tenant_id,
			"name": portfolio.name,
			"description": portfolio.description,
			"status": portfolio.status,
			"summary": summary,
		})


# ---------------------------------------------------------------------------
# PropertyDebtView
# ---------------------------------------------------------------------------

class PropertyDebtView(BaseERPView):
	"""Debt instrument list with outstanding balances."""

	route_base = "/industry/portfolio/debts"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		session = _get_session()
		tenant_id = request.args.get("tenant_id")
		property_id = request.args.get("property_id")
		status = request.args.get("status")

		q = (
			sa.select(PropertyDebt)
			.order_by(sa.desc(PropertyDebt.current_balance_cents))
			.limit(500)
		)
		if tenant_id:
			q = q.where(PropertyDebt.tenant_id == tenant_id)
		if property_id:
			q = q.where(PropertyDebt.property_id == property_id)
		if status:
			q = q.where(PropertyDebt.status == status.upper())

		debts = session.execute(q).scalars().all()
		return jsonify({
			"debts": [
				{
					"id": d.id,
					"property_id": d.property_id,
					"lender_name": d.lender_name,
					"loan_type": d.loan_type,
					"original_principal_cents": d.original_principal_cents,
					"original_principal_display": _cents(d.original_principal_cents),
					"current_balance_cents": d.current_balance_cents,
					"current_balance_display": _cents(d.current_balance_cents),
					"interest_rate": str(d.interest_rate),
					"monthly_payment_cents": d.monthly_payment_cents,
					"maturity_date": d.maturity_date.isoformat() if d.maturity_date else None,
					"status": d.status,
					"lien_position": d.lien_position,
				}
				for d in debts
			]
		})


# ---------------------------------------------------------------------------
# CapExRecordView
# ---------------------------------------------------------------------------

class CapExRecordView(BaseERPView):
	"""Capital expenditure record list."""

	route_base = "/industry/portfolio/capex"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		session = _get_session()
		tenant_id = request.args.get("tenant_id")
		property_id = request.args.get("property_id")
		category = request.args.get("category")

		q = (
			sa.select(CapExRecord)
			.order_by(sa.desc(CapExRecord.capex_date))
			.limit(500)
		)
		if tenant_id:
			q = q.where(CapExRecord.tenant_id == tenant_id)
		if property_id:
			q = q.where(CapExRecord.property_id == property_id)
		if category:
			q = q.where(CapExRecord.category == category.upper())

		records = session.execute(q).scalars().all()
		return jsonify({
			"capex_records": [
				{
					"id": r.id,
					"property_id": r.property_id,
					"description": r.description,
					"capex_cents": r.capex_cents,
					"capex_display": _cents(r.capex_cents),
					"capex_date": r.capex_date.isoformat(),
					"category": r.category,
					"budget_cents": r.budget_cents,
					"vendor_name": r.vendor_name,
					"is_capitalizable": r.is_capitalizable,
				}
				for r in records
			]
		})


# ---------------------------------------------------------------------------
# InvestorHoldingView
# ---------------------------------------------------------------------------

class InvestorHoldingView(BaseERPView):
	"""Investor holding list with ownership percentages."""

	route_base = "/industry/portfolio/investors"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		session = _get_session()
		tenant_id = request.args.get("tenant_id")
		portfolio_id = request.args.get("portfolio_id")
		status = request.args.get("status")

		q = (
			sa.select(InvestorHolding)
			.order_by(sa.desc(InvestorHolding.ownership_pct))
			.limit(500)
		)
		if tenant_id:
			q = q.where(InvestorHolding.tenant_id == tenant_id)
		if portfolio_id:
			q = q.where(InvestorHolding.portfolio_id == portfolio_id)
		if status:
			q = q.where(InvestorHolding.status == status.upper())

		holdings = session.execute(q).scalars().all()
		return jsonify({
			"holdings": [
				{
					"id": h.id,
					"portfolio_id": h.portfolio_id,
					"investor_party_id": h.investor_party_id,
					"ownership_pct": str(h.ownership_pct),
					"investment_cents": h.investment_cents,
					"investment_display": _cents(h.investment_cents),
					"since_date": h.since_date.isoformat(),
					"status": h.status,
				}
				for h in holdings
			]
		})


# ---------------------------------------------------------------------------
# DistributionRecordView
# ---------------------------------------------------------------------------

class DistributionRecordView(BaseERPView):
	"""Distribution record list."""

	route_base = "/industry/portfolio/distributions"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		session = _get_session()
		tenant_id = request.args.get("tenant_id")
		portfolio_id = request.args.get("portfolio_id")
		status = request.args.get("status")

		q = (
			sa.select(DistributionRecord)
			.order_by(sa.desc(DistributionRecord.period))
			.limit(500)
		)
		if tenant_id:
			q = q.where(DistributionRecord.tenant_id == tenant_id)
		if portfolio_id:
			q = q.where(DistributionRecord.portfolio_id == portfolio_id)
		if status:
			q = q.where(DistributionRecord.status == status.upper())

		dists = session.execute(q).scalars().all()
		return jsonify({
			"distributions": [
				{
					"id": d.id,
					"portfolio_id": d.portfolio_id,
					"period": d.period,
					"total_distributable_cents": d.total_distributable_cents,
					"total_display": _cents(d.total_distributable_cents),
					"status": d.status,
					"distributed_at": d.distributed_at.isoformat() if d.distributed_at else None,
					"allocation_count": len(d.allocations) if d.allocations else 0,
				}
				for d in dists
			]
		})


# ---------------------------------------------------------------------------
# PortfolioDashboardView
# ---------------------------------------------------------------------------

class PortfolioDashboardView(BaseERPView):
	"""Portfolio Analytics KPI dashboard.

	GET /industry/portfolio/dashboard  — live KPI tiles with counts and totals.
	"""

	route_base = "/industry/portfolio"
	default_view = "dashboard"

	@expose("/dashboard")
	@has_access
	def dashboard(self):
		"""Portfolio dashboard with live counts and aggregate analytics."""
		session = _get_session()
		tenant_id = request.args.get("tenant_id")

		# Live counts — uses BaseERPView._count()
		active_portfolios = self._count(PropertyPortfolio, status="ACTIVE")
		active_debts = self._count(PropertyDebt, status="ACTIVE")
		pending_distributions = self._count(DistributionRecord, status="DRAFT")

		# Aggregate debt outstanding
		q_debt = sa.select(
			sa.func.coalesce(sa.func.sum(PropertyDebt.current_balance_cents), 0)
		).where(PropertyDebt.status == "ACTIVE")
		if tenant_id:
			q_debt = q_debt.where(PropertyDebt.tenant_id == tenant_id)
		total_debt_cents = int(session.execute(q_debt).scalar_one() or 0)

		# Aggregate CapEx YTD
		from datetime import date
		today = date.today()
		q_capex = sa.select(
			sa.func.coalesce(sa.func.sum(CapExRecord.capex_cents), 0)
		).where(CapExRecord.capex_date >= date(today.year, 1, 1))
		if tenant_id:
			q_capex = q_capex.where(CapExRecord.tenant_id == tenant_id)
		capex_ytd_cents = int(session.execute(q_capex).scalar_one() or 0)

		kpi_html = self.kpi_cards([
			{
				"label": "Active Portfolios",
				"value": active_portfolios,
				"format": "integer",
				"color": "#1a56db",
				"icon": "fa-briefcase",
			},
			{
				"label": "Active Debt Instruments",
				"value": active_debts,
				"format": "integer",
				"color": "#d9534f",
				"icon": "fa-bank",
			},
			{
				"label": "Pending Distributions",
				"value": pending_distributions,
				"format": "integer",
				"color": "#f0ad4e",
				"icon": "fa-money",
			},
			{
				"label": "Total Debt Outstanding",
				"value": total_debt_cents // 100,
				"format": "currency",
				"color": "#c0392b",
				"icon": "fa-credit-card",
			},
			{
				"label": "CapEx YTD",
				"value": capex_ytd_cents // 100,
				"format": "currency",
				"color": "#27ae60",
				"icon": "fa-wrench",
			},
		])

		html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>Portfolio Analytics Dashboard</title>
<link rel="stylesheet" href="https://maxcdn.bootstrapcdn.com/bootstrap/3.3.7/css/bootstrap.min.css">
<style>body{{padding:24px}}</style>
</head><body>
<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px">
  <h3>Portfolio Analytics Dashboard</h3>
  <a href="/industry/portfolio/portfolios/" class="btn btn-default btn-sm">All Portfolios</a>
</div>
{kpi_html}
<p style="color:#888;font-size:0.75em">Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}</p>
</body></html>"""
		return make_response(html, 200)


__all__ = [
	"PropertyPortfolioView",
	"PropertyDebtView",
	"CapExRecordView",
	"InvestorHoldingView",
	"DistributionRecordView",
	"PortfolioDashboardView",
]
