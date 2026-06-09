"""
pgappforge/plugins/erp/industry/real_estate/portfolio/views.py

Flask views for the Real Estate Portfolio Analytics sub-plugin.

Route summary
-------------
PropertyPortfolioView     /industry/portfolio/portfolios/
  ├─ GET  /               — list active portfolios (HTML)
  └─ GET  /<id>           — portfolio detail deep-dive (HTML)
PropertyDebtView          /industry/portfolio/debts/
  └─ GET  /               — list debt instruments (JSON)
CapExRecordView           /industry/portfolio/capex/
  └─ GET  /               — list capex records (JSON)
InvestorHoldingView       /industry/portfolio/investors/
  └─ GET  /               — list investor holdings (JSON)
DistributionRecordView    /industry/portfolio/distributions/
  └─ GET  /               — list distribution records (JSON)
PortfolioDashboardView    /industry/portfolio/
  └─ GET  /               — KPI dashboard (active portfolios, active debts, pending distributions)
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone

import sqlalchemy as sa
from flask import abort, jsonify, render_template, request

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


def _cents(cents: int | None, currency: str = "USD") -> str:
	if cents is None:
		return "—"
	major = cents // 100
	minor = abs(cents) % 100
	sign = "-" if cents < 0 else ""
	return f"{sign}{major:,}.{minor:02d} {currency}"


def _fmt_display(cents: int | None) -> str:
	"""Human-readable amount for template context, e.g. '$2.50M'."""
	if cents is None:
		return "—"
	v = abs(cents / 100)
	pfx = ("-" if cents < 0 else "") + "$"
	if v >= 1_000_000_000:
		return f"{pfx}{v / 1_000_000_000:.2f}B"
	if v >= 1_000_000:
		return f"{pfx}{v / 1_000_000:.2f}M"
	if v >= 1_000:
		return f"{pfx}{v / 1_000:.1f}k"
	return f"{pfx}{v:.0f}"


# ---------------------------------------------------------------------------
# PropertyPortfolioView — HTML list + detail
# ---------------------------------------------------------------------------

class PropertyPortfolioView(BaseERPView):
	"""Portfolio list and detail with summary analytics."""

	route_base = "/industry/portfolio/portfolios"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		"""Render portfolio list using the dashboard template."""
		from flask import current_app
		session = _get_session()
		tenant_id = request.args.get("tenant_id")
		status = request.args.get("status", "ACTIVE")

		q = (
			sa.select(PropertyPortfolio)
			.order_by(sa.asc(PropertyPortfolio.name))
			.limit(500)
		)
		if tenant_id:
			q = q.where(PropertyPortfolio.tenant_id == tenant_id)
		if status:
			q = q.where(PropertyPortfolio.status == status.upper())

		portfolios = session.execute(q).scalars().all()

		# Live KPI counts
		try:
			active_portfolios = self._count(PropertyPortfolio, status="ACTIVE")
			active_debts = self._count(PropertyDebt, status="ACTIVE")
			pending_distributions = self._count(DistributionRecord, status="DRAFT")
			total_properties = self._count(PortfolioProperty)
		except Exception:
			active_portfolios = active_debts = pending_distributions = total_properties = 0

		kpi_html = self.kpi_cards([
			{
				"label":   "Active Portfolios",
				"value":   active_portfolios,
				"format":  "integer",
				"color":   "#1a56db",
				"icon":    "fa-briefcase",
			},
			{
				"label":   "Active Debt Instruments",
				"value":   active_debts,
				"format":  "integer",
				"color":   "#dc2626",
				"icon":    "fa-bank",
			},
			{
				"label":   "Pending Distributions",
				"value":   pending_distributions,
				"format":  "integer",
				"color":   "#c27803",
				"icon":    "fa-money",
			},
			{
				"label":   "Total Properties",
				"value":   total_properties,
				"format":  "integer",
				"color":   "#057a55",
				"icon":    "fa-building",
			},
		])

		return render_template(
			"appbuilder/re_portfolio/dashboard.html",
			portfolios=portfolios,
			kpi_html=kpi_html,
			appbuilder=current_app.appbuilder,
		)

	@expose("/<string:portfolio_id>")
	@has_access
	def detail(self, portfolio_id: str):
		"""Render individual portfolio deep-dive."""
		from flask import current_app
		session = _get_session()
		portfolio = session.get(PropertyPortfolio, portfolio_id)
		if portfolio is None:
			abort(404)

		tenant_id = request.args.get("tenant_id") or portfolio.tenant_id

		# Aggregate stats for the header strip
		try:
			q_props = (
				sa.select(sa.func.count())
				.select_from(PortfolioProperty)
				.where(PortfolioProperty.portfolio_id == portfolio_id)
			)
			property_count = session.execute(q_props).scalar_one() or 0

			q_aum = (
				sa.select(
					sa.func.coalesce(
						sa.func.sum(PortfolioProperty.current_value_cents), 0
					)
				)
				.where(PortfolioProperty.portfolio_id == portfolio_id)
			)
			aum_cents = int(session.execute(q_aum).scalar_one() or 0)

			q_inv = (
				sa.select(sa.func.count())
				.select_from(InvestorHolding)
				.where(InvestorHolding.portfolio_id == portfolio_id)
				.where(InvestorHolding.status == "ACTIVE")
			)
			investor_count = session.execute(q_inv).scalar_one() or 0

			q_debt = (
				sa.select(sa.func.count())
				.select_from(PropertyDebt)
				.where(PropertyDebt.portfolio_id == portfolio_id)
				.where(PropertyDebt.status == "ACTIVE")
			)
			debt_count = session.execute(q_debt).scalar_one() or 0
		except Exception as exc:
			log.warning("portfolio detail aggregates failed: %s", exc)
			property_count = investor_count = debt_count = 0
			aum_cents = None

		return render_template(
			"appbuilder/re_portfolio/portfolio_detail.html",
			portfolio=portfolio,
			aum_display=_fmt_display(aum_cents),
			property_count=property_count,
			investor_count=investor_count,
			debt_count=debt_count,
			appbuilder=current_app.appbuilder,
		)


# ---------------------------------------------------------------------------
# PropertyDebtView — JSON list
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
					"id":                          d.id,
					"property_id":                 d.property_id,
					"lender_name":                 d.lender_name,
					"loan_type":                   d.loan_type,
					"original_principal_cents":    d.original_principal_cents,
					"original_principal_display":  _cents(d.original_principal_cents),
					"current_balance_cents":        d.current_balance_cents,
					"current_balance_display":     _cents(d.current_balance_cents),
					"interest_rate":               str(d.interest_rate),
					"monthly_payment_cents":       d.monthly_payment_cents,
					"maturity_date":               d.maturity_date.isoformat() if d.maturity_date else None,
					"status":                      d.status,
					"lien_position":               d.lien_position,
				}
				for d in debts
			]
		})


# ---------------------------------------------------------------------------
# CapExRecordView — JSON list
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
					"id":               r.id,
					"property_id":      r.property_id,
					"description":      r.description,
					"capex_cents":      r.capex_cents,
					"capex_display":    _cents(r.capex_cents),
					"capex_date":       r.capex_date.isoformat(),
					"category":         r.category,
					"budget_cents":     r.budget_cents,
					"vendor_name":      r.vendor_name,
					"is_capitalizable": r.is_capitalizable,
				}
				for r in records
			]
		})


# ---------------------------------------------------------------------------
# InvestorHoldingView — JSON list
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
					"id":                 h.id,
					"portfolio_id":       h.portfolio_id,
					"investor_party_id":  h.investor_party_id,
					"ownership_pct":      str(h.ownership_pct),
					"investment_cents":   h.investment_cents,
					"investment_display": _cents(h.investment_cents),
					"since_date":         h.since_date.isoformat(),
					"status":             h.status,
				}
				for h in holdings
			]
		})


# ---------------------------------------------------------------------------
# DistributionRecordView — JSON list
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
					"id":                       d.id,
					"portfolio_id":             d.portfolio_id,
					"period":                   d.period,
					"total_distributable_cents": d.total_distributable_cents,
					"total_display":            _cents(d.total_distributable_cents),
					"status":                   d.status,
					"distributed_at":           d.distributed_at.isoformat() if d.distributed_at else None,
					"allocation_count":         len(d.allocations) if d.allocations else 0,
				}
				for d in dists
			]
		})


# ---------------------------------------------------------------------------
# PortfolioDashboardView — main entry point dashboard
# ---------------------------------------------------------------------------

class PortfolioDashboardView(BaseERPView):
	"""Portfolio Analytics KPI dashboard.

	GET /industry/portfolio/   — live KPI tiles, charts, and pending distributions.
	"""

	route_base = "/industry/portfolio"
	default_view = "index"

	# ------------------------------------------------------------------
	# Per-portfolio data API endpoints
	# All four join through PortfolioProperty to resolve the
	# portfolio → property → debt/capex relationships.
	# ------------------------------------------------------------------

	@expose("/api/portfolio/<string:portfolio_id>/metrics")
	@has_access
	def api_portfolio_metrics(self, portfolio_id: str):
		"""NOI, cap rate, DSCR, IRR aggregates for one portfolio.

		GET /industry/portfolio/api/portfolio/<id>/metrics
		Returns JSON with keys: noi_cents, cap_rate, dscr, irr (all nullable).
		"""
		session = _get_session()
		portfolio = session.get(PropertyPortfolio, portfolio_id)
		if portfolio is None:
			abort(404)

		try:
			from pgappforge.plugins.erp.industry.real_estate.portfolio.services import (
				PortfolioAnalyticsService,
			)
			summary = PortfolioAnalyticsService().get_portfolio_summary(
				portfolio_id=portfolio_id,
				tenant_id=portfolio.tenant_id,
				session=session,
			)
			totals = summary.get("totals", {})
		except Exception as exc:
			log.warning("api_portfolio_metrics: analytics service failed: %s", exc)
			totals = {}

		return jsonify({
			"portfolio_id":  portfolio_id,
			"noi_cents":     totals.get("noi_cents"),
			"cap_rate":      totals.get("cap_rate"),
			"dscr":          totals.get("dscr"),
			"irr":           totals.get("irr"),
			"noi_trend":     totals.get("noi_trend"),
			"cap_rate_trend": totals.get("cap_rate_trend"),
			"dscr_trend":    totals.get("dscr_trend"),
			"irr_trend":     totals.get("irr_trend"),
		})

	@expose("/api/portfolio/<string:portfolio_id>/properties")
	@has_access
	def api_portfolio_properties(self, portfolio_id: str):
		"""Properties belonging to a portfolio with per-property analytics.

		GET /industry/portfolio/api/portfolio/<id>/properties
		Returns JSON list of property rows.
		"""
		session = _get_session()
		portfolio = session.get(PropertyPortfolio, portfolio_id)
		if portfolio is None:
			abort(404)

		q = (
			sa.select(PortfolioProperty)
			.where(PortfolioProperty.portfolio_id == portfolio_id)
			.order_by(sa.desc(PortfolioProperty.current_value_cents))
			.limit(200)
		)
		props = session.execute(q).scalars().all()

		rows = []
		for p in props:
			debt_q = (
				sa.select(
					sa.func.coalesce(sa.func.sum(PropertyDebt.current_balance_cents), 0)
				)
				.where(PropertyDebt.property_id == p.property_id)
				.where(PropertyDebt.status == "ACTIVE")
			)
			debt_balance = int(session.execute(debt_q).scalar_one() or 0)
			rows.append({
				"id":                       p.property_id,
				"address":                  getattr(p, "address", None),
				"property_type":            getattr(p, "property_type", None),
				"acquisition_cost_cents":   p.acquisition_cost_cents,
				"current_value_cents":      p.current_value_cents,
				"debt_balance_cents":       debt_balance,
				"noi_cents":                getattr(p, "noi_cents", None),
				"cap_rate":                 str(p.cap_rate) if getattr(p, "cap_rate", None) is not None else None,
			})
		return jsonify(rows)

	@expose("/api/portfolio/<string:portfolio_id>/debts")
	@has_access
	def api_portfolio_debts(self, portfolio_id: str):
		"""Debt instruments for all properties in a portfolio.

		GET /industry/portfolio/api/portfolio/<id>/debts
		Joins PropertyDebt through PortfolioProperty on property_id.
		"""
		session = _get_session()
		portfolio = session.get(PropertyPortfolio, portfolio_id)
		if portfolio is None:
			abort(404)

		property_ids_q = sa.select(PortfolioProperty.property_id).where(
			PortfolioProperty.portfolio_id == portfolio_id
		)
		property_ids = [r for (r,) in session.execute(property_ids_q).all()]

		if not property_ids:
			return jsonify({"debts": []})

		q = (
			sa.select(PropertyDebt)
			.where(PropertyDebt.property_id.in_(property_ids))
			.order_by(sa.desc(PropertyDebt.current_balance_cents))
			.limit(500)
		)
		debts = session.execute(q).scalars().all()
		return jsonify({
			"debts": [
				{
					"id":                         d.id,
					"property_id":                d.property_id,
					"lender_name":                d.lender_name,
					"loan_type":                  d.loan_type,
					"current_balance_cents":      d.current_balance_cents,
					"interest_rate":              str(d.interest_rate),
					"monthly_payment_cents":      d.monthly_payment_cents,
					"maturity_date":              d.maturity_date.isoformat() if d.maturity_date else None,
					"status":                     d.status,
					"lien_position":              d.lien_position,
					"ltv":                        str(d.ltv) if getattr(d, "ltv", None) is not None else None,
				}
				for d in debts
			]
		})

	@expose("/api/portfolio/<string:portfolio_id>/capex")
	@has_access
	def api_portfolio_capex(self, portfolio_id: str):
		"""CapEx records for all properties in a portfolio.

		GET /industry/portfolio/api/portfolio/<id>/capex
		Joins CapExRecord through PortfolioProperty on property_id.
		"""
		session = _get_session()
		portfolio = session.get(PropertyPortfolio, portfolio_id)
		if portfolio is None:
			abort(404)

		property_ids_q = sa.select(PortfolioProperty.property_id).where(
			PortfolioProperty.portfolio_id == portfolio_id
		)
		property_ids = [r for (r,) in session.execute(property_ids_q).all()]

		if not property_ids:
			return jsonify({"capex_records": []})

		q = (
			sa.select(CapExRecord)
			.where(CapExRecord.property_id.in_(property_ids))
			.order_by(sa.desc(CapExRecord.capex_date))
			.limit(500)
		)
		records = session.execute(q).scalars().all()
		return jsonify({
			"capex_records": [
				{
					"id":               r.id,
					"property_id":      r.property_id,
					"description":      r.description,
					"capex_cents":      r.capex_cents,
					"capex_date":       r.capex_date.isoformat(),
					"category":         r.category,
					"budget_cents":     r.budget_cents,
					"vendor_name":      r.vendor_name,
					"is_capitalizable": r.is_capitalizable,
				}
				for r in records
			]
		})

	@expose("/")
	@has_access
	def index(self):
		"""Portfolio analytics dashboard with live KPIs."""
		from flask import current_app
		session = _get_session()
		tenant_id = request.args.get("tenant_id")

		# Live counts
		try:
			active_portfolios = self._count(PropertyPortfolio, status="ACTIVE")
			active_debts = self._count(PropertyDebt, status="ACTIVE")
			pending_distributions = self._count(DistributionRecord, status="DRAFT")
			total_properties = self._count(PortfolioProperty)
		except Exception:
			active_portfolios = active_debts = pending_distributions = total_properties = 0

		# Aggregate debt outstanding
		try:
			q_debt = sa.select(
				sa.func.coalesce(sa.func.sum(PropertyDebt.current_balance_cents), 0)
			).where(PropertyDebt.status == "ACTIVE")
			if tenant_id:
				q_debt = q_debt.where(PropertyDebt.tenant_id == tenant_id)
			total_debt_cents = int(session.execute(q_debt).scalar_one() or 0)
		except Exception:
			total_debt_cents = 0

		kpi_html = self.kpi_cards([
			{
				"label":   "Active Portfolios",
				"value":   active_portfolios,
				"format":  "integer",
				"color":   "#1a56db",
				"icon":    "fa-briefcase",
			},
			{
				"label":   "Active Debt Instruments",
				"value":   active_debts,
				"format":  "integer",
				"color":   "#dc2626",
				"icon":    "fa-bank",
			},
			{
				"label":   "Pending Distributions",
				"value":   pending_distributions,
				"format":  "integer",
				"color":   "#c27803",
				"icon":    "fa-money",
			},
			{
				"label":   "Total Properties",
				"value":   total_properties,
				"format":  "integer",
				"color":   "#057a55",
				"icon":    "fa-building",
			},
			{
				"label":   "Total Debt Outstanding",
				"value":   total_debt_cents // 100,
				"format":  "currency",
				"color":   "#7e3af2",
				"icon":    "fa-credit-card",
			},
		])

		return render_template(
			"appbuilder/re_portfolio/dashboard.html",
			portfolios=[],
			kpi_html=kpi_html,
			appbuilder=current_app.appbuilder,
		)


__all__ = [
	"PropertyPortfolioView",
	"PropertyDebtView",
	"CapExRecordView",
	"InvestorHoldingView",
	"DistributionRecordView",
	"PortfolioDashboardView",
]
