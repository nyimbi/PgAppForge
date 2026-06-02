"""
pgappforge/plugins/erp/industry/financial_services/views.py

Flask views for the Financial Services Cloud plugin.

Views:
  FinancialClientView        — CRUD + KYC approval + risk reclassification
  PortfolioAccountView       — CRUD + account transaction endpoint
  FinancialProductView       — CRUD for product catalogue
  ClientHoldingView          — Read-only holding snapshots
  SanctionsScreeningView     — Screen + clear + AML watchlist
  FinServReportView          — 3 reports: Portfolio Summary, AML Watchlist,
                               Product Exposure
"""
from __future__ import annotations

import logging
from datetime import date

import sqlalchemy as sa
from flask import abort, jsonify, request

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
	raise RuntimeError("Cannot obtain database session outside app context")


def _svc():
	from pgappforge.plugins.erp.industry.financial_services.services import (
		FinancialServicesService,
	)
	return FinancialServicesService()


# ---------------------------------------------------------------------------
# FinancialClientView
# ---------------------------------------------------------------------------

class FinancialClientView(BaseView):
	"""Financial client CRUD + KYC / risk-profile business actions.

	GET  /finserv/clients/                    — list (tenant-scoped)
	GET  /finserv/clients/<id>                — detail
	POST /finserv/clients/                    — onboard client (kyc=PENDING)
	POST /finserv/clients/<id>/approve-kyc   — approve KYC
	POST /finserv/clients/<id>/risk-profile  — reclassify risk profile
	"""

	route_base = "/finserv/clients"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.industry.financial_services.models import FinancialClient
		session = _get_session()
		tenant_id = request.args.get("tenant_id")
		q = sa.select(FinancialClient).order_by(FinancialClient.client_number)
		if tenant_id:
			q = q.where(FinancialClient.tenant_id == tenant_id)
		clients = session.execute(q).scalars().all()
		return jsonify([
			{
				"id": c.id,
				"client_number": c.client_number,
				"client_type": c.client_type,
				"risk_profile": c.risk_profile,
				"kyc_status": c.kyc_status,
				"total_aum_cents": c.total_aum_cents,
			}
			for c in clients
		])

	@expose("/<string:client_id>")
	@has_access
	def detail(self, client_id: str):
		from pgappforge.plugins.erp.industry.financial_services.models import FinancialClient
		session = _get_session()
		client = session.get(FinancialClient, client_id)
		if client is None:
			abort(404, f"FinancialClient {client_id!r} not found")
		return jsonify({
			"id": client.id,
			"tenant_id": client.tenant_id,
			"party_id": client.party_id,
			"client_number": client.client_number,
			"client_type": client.client_type,
			"risk_profile": client.risk_profile,
			"kyc_status": client.kyc_status,
			"kyc_completed_at": client.kyc_completed_at.isoformat() if client.kyc_completed_at else None,
			"aml_score": str(client.aml_score) if client.aml_score is not None else None,
			"sanctions_screened_at": (
				client.sanctions_screened_at.isoformat()
				if client.sanctions_screened_at else None
			),
			"relationship_manager_id": client.relationship_manager_id,
			"onboarded_at": client.onboarded_at.isoformat() if client.onboarded_at else None,
			"total_aum_cents": client.total_aum_cents,
			"net_worth_cents": client.net_worth_cents,
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		session = _get_session()
		data = request.get_json(force=True) or {}
		required = ("tenant_id", "party_id", "client_number", "client_type")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"error": f"Missing required fields: {missing}"}), 400
		try:
			result = _svc().onboard_client(
				tenant_id=data["tenant_id"],
				party_id=data["party_id"],
				client_number=data["client_number"],
				client_type=data["client_type"],
				risk_profile=data.get("risk_profile", "MEDIUM"),
				relationship_manager_id=data.get("relationship_manager_id"),
				session=session,
			)
			session.commit()
			return jsonify(result), 201
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422

	@expose("/<string:client_id>/approve-kyc", methods=["POST"])
	@has_access
	def approve_kyc(self, client_id: str):
		session = _get_session()
		data = request.get_json(force=True) or {}
		try:
			result = _svc().approve_kyc(
				client_id, session, changed_by=data.get("changed_by", "")
			)
			session.commit()
			return jsonify(result)
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422

	@expose("/<string:client_id>/risk-profile", methods=["POST"])
	@has_access
	def change_risk_profile(self, client_id: str):
		session = _get_session()
		data = request.get_json(force=True) or {}
		if not data.get("risk_profile"):
			return jsonify({"error": "risk_profile required"}), 400
		try:
			result = _svc().change_risk_profile(
				client_id,
				data["risk_profile"],
				session,
				rationale=data.get("rationale", ""),
				changed_by=data.get("changed_by", ""),
			)
			session.commit()
			return jsonify(result)
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422


# ---------------------------------------------------------------------------
# PortfolioAccountView
# ---------------------------------------------------------------------------

class PortfolioAccountView(BaseView):
	"""Portfolio account CRUD + transaction posting.

	GET  /finserv/accounts/               — list
	GET  /finserv/accounts/<id>           — detail
	POST /finserv/accounts/               — open account
	POST /finserv/accounts/<id>/transact — post credit/debit (delta_cents)
	"""

	route_base = "/finserv/accounts"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.industry.financial_services.models import PortfolioAccount
		session = _get_session()
		client_id = request.args.get("client_id")
		q = sa.select(PortfolioAccount).order_by(PortfolioAccount.account_number)
		if client_id:
			q = q.where(PortfolioAccount.client_id == client_id)
		accounts = session.execute(q).scalars().all()
		return jsonify([
			{
				"id": a.id,
				"account_number": a.account_number,
				"client_id": a.client_id,
				"account_type": a.account_type,
				"currency_code": a.currency_code,
				"balance_cents": a.balance_cents,
				"available_balance_cents": a.available_balance_cents,
				"status": a.status,
			}
			for a in accounts
		])

	@expose("/<string:account_id>")
	@has_access
	def detail(self, account_id: str):
		from pgappforge.plugins.erp.industry.financial_services.models import PortfolioAccount
		session = _get_session()
		acct = session.get(PortfolioAccount, account_id)
		if acct is None:
			abort(404)
		return jsonify({
			"id": acct.id,
			"account_number": acct.account_number,
			"client_id": acct.client_id,
			"account_type": acct.account_type,
			"currency_code": acct.currency_code,
			"balance_cents": acct.balance_cents,
			"available_balance_cents": acct.available_balance_cents,
			"status": acct.status,
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		session = _get_session()
		data = request.get_json(force=True) or {}
		required = ("tenant_id", "client_id", "account_number", "account_type")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"error": f"Missing: {missing}"}), 400
		try:
			result = _svc().open_account(
				tenant_id=data["tenant_id"],
				client_id=data["client_id"],
				account_number=data["account_number"],
				account_type=data["account_type"],
				currency_code=data.get("currency_code", "USD"),
				session=session,
			)
			session.commit()
			return jsonify(result), 201
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422

	@expose("/<string:account_id>/transact", methods=["POST"])
	@has_access
	def transact(self, account_id: str):
		"""Post a credit (positive) or debit (negative) to the account.

		Body: {"delta_cents": 50000, "transaction_ref": "TXN-001"}
		"""
		session = _get_session()
		data = request.get_json(force=True) or {}
		delta = data.get("delta_cents")
		if delta is None:
			return jsonify({"error": "delta_cents required"}), 400
		try:
			result = _svc().post_account_transaction(
				account_id,
				int(delta),
				session,
				transaction_ref=data.get("transaction_ref", ""),
			)
			session.commit()
			return jsonify(result)
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422


# ---------------------------------------------------------------------------
# FinancialProductView
# ---------------------------------------------------------------------------

class FinancialProductView(BaseView):
	"""Product catalogue CRUD.

	GET  /finserv/products/    — list
	POST /finserv/products/    — create
	PUT  /finserv/products/<id> — update
	"""

	route_base = "/finserv/products"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.industry.financial_services.models import FinancialProduct
		session = _get_session()
		q = sa.select(FinancialProduct).order_by(FinancialProduct.product_code)
		if request.args.get("active_only") == "true":
			q = q.where(FinancialProduct.is_active.is_(True))
		rows = session.execute(q).scalars().all()
		return jsonify([
			{
				"id": p.id,
				"product_code": p.product_code,
				"product_type": p.product_type,
				"name": p.name,
				"interest_rate_pct": str(p.interest_rate_pct) if p.interest_rate_pct is not None else None,
				"term_months": p.term_months,
				"min_amount_cents": p.min_amount_cents,
				"max_amount_cents": p.max_amount_cents,
				"is_active": p.is_active,
			}
			for p in rows
		])

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		from pgappforge.plugins.erp.industry.financial_services.models import FinancialProduct
		session = _get_session()
		data = request.get_json(force=True) or {}
		required = ("tenant_id", "product_code", "product_type", "name")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"error": f"Missing: {missing}"}), 400
		from decimal import Decimal
		product = FinancialProduct(
			tenant_id=data["tenant_id"],
			product_code=data["product_code"],
			product_type=data["product_type"],
			name=data["name"],
			description=data.get("description"),
			min_amount_cents=int(data.get("min_amount_cents", 0)),
			max_amount_cents=int(data.get("max_amount_cents", 0)),
			interest_rate_pct=Decimal(str(data["interest_rate_pct"])) if data.get("interest_rate_pct") else None,
			term_months=data.get("term_months"),
			risk_category=data.get("risk_category"),
			regulatory_category=data.get("regulatory_category"),
			is_active=data.get("is_active", True),
		)
		session.add(product)
		session.commit()
		return jsonify({"product_id": product.id, "product_code": product.product_code}), 201


# ---------------------------------------------------------------------------
# SanctionsScreeningView
# ---------------------------------------------------------------------------

class SanctionsScreeningView(BaseView):
	"""Sanctions screening operations.

	POST /finserv/sanctions/screen          — run screening
	POST /finserv/sanctions/<id>/clear      — clear a POTENTIAL_MATCH
	GET  /finserv/sanctions/watchlist       — AML watchlist
	"""

	route_base = "/finserv/sanctions"
	default_view = "watchlist"

	@expose("/screen", methods=["POST"])
	@has_access
	def screen(self):
		session = _get_session()
		data = request.get_json(force=True) or {}
		required = ("tenant_id", "party_id", "list_type")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"error": f"Missing: {missing}"}), 400
		try:
			result = _svc().screen_sanctions(
				tenant_id=data["tenant_id"],
				party_id=data["party_id"],
				list_type=data["list_type"],
				match_found=bool(data.get("match_found", False)),
				match_score=data.get("match_score"),
				match_details=data.get("match_details", {}),
				session=session,
			)
			session.commit()
			return jsonify(result), 201
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422

	@expose("/<string:screening_id>/clear", methods=["POST"])
	@has_access
	def clear(self, screening_id: str):
		session = _get_session()
		data = request.get_json(force=True) or {}
		cleared_by = data.get("cleared_by_user_id")
		if cleared_by is None:
			return jsonify({"error": "cleared_by_user_id required"}), 400
		try:
			result = _svc().clear_sanctions_match(screening_id, int(cleared_by), session)
			session.commit()
			return jsonify(result)
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422

	@expose("/watchlist")
	@has_access
	def watchlist(self):
		session = _get_session()
		tenant_id = request.args.get("tenant_id")
		if not tenant_id:
			return jsonify({"error": "tenant_id query param required"}), 400
		rows = _svc().get_aml_watchlist(tenant_id, session)
		return jsonify(rows)


# ---------------------------------------------------------------------------
# FinServReportView  (Portfolio Summary, AML Watchlist, Product Exposure)
# ---------------------------------------------------------------------------

class FinServReportView(BaseView):
	"""Canned Financial Services reports.

	GET /finserv/reports/                              — report index
	GET /finserv/reports/portfolio/<client_id>         — portfolio summary
	GET /finserv/reports/aml-watchlist                 — AML / sanctions watchlist
	GET /finserv/reports/product-exposure              — product type exposure summary
	"""

	route_base = "/finserv/reports"
	default_view = "index"

	@expose("/")
	@has_access
	def index(self):
		return jsonify({
			"reports": [
				{
					"name": "Client Portfolio Summary",
					"endpoint": "/finserv/reports/portfolio/<client_id>?as_of_date=YYYY-MM-DD",
				},
				{
					"name": "AML Watchlist",
					"endpoint": "/finserv/reports/aml-watchlist?tenant_id=<id>",
				},
				{
					"name": "Product Exposure",
					"endpoint": "/finserv/reports/product-exposure?tenant_id=<id>",
				},
			]
		})

	@expose("/portfolio/<string:client_id>")
	@has_access
	def portfolio_summary(self, client_id: str):
		session = _get_session()
		raw_date = request.args.get("as_of_date")
		as_of = date.fromisoformat(raw_date) if raw_date else date.today()
		try:
			result = _svc().get_client_portfolio_summary(client_id, as_of, session)
			return jsonify(result)
		except Exception as exc:
			return jsonify({"error": str(exc)}), 404

	@expose("/aml-watchlist")
	@has_access
	def aml_watchlist(self):
		session = _get_session()
		tenant_id = request.args.get("tenant_id")
		if not tenant_id:
			return jsonify({"error": "tenant_id required"}), 400
		rows = _svc().get_aml_watchlist(tenant_id, session)
		return jsonify({"tenant_id": tenant_id, "watchlist": rows, "count": len(rows)})

	@expose("/product-exposure")
	@has_access
	def product_exposure(self):
		"""Aggregate count and AUM by product_type across active accounts."""
		from pgappforge.plugins.erp.industry.financial_services.models import (
			PortfolioAccount, FinancialClient,
		)
		from sqlalchemy import func
		session = _get_session()
		tenant_id = request.args.get("tenant_id")

		q = (
			sa.select(
				PortfolioAccount.account_type,
				sa.func.count(PortfolioAccount.id).label("count"),
				sa.func.sum(PortfolioAccount.balance_cents).label("total_balance_cents"),
			)
			.where(PortfolioAccount.status != "CLOSED")
			.group_by(PortfolioAccount.account_type)
			.order_by(sa.func.sum(PortfolioAccount.balance_cents).desc())
		)
		if tenant_id:
			q = q.where(PortfolioAccount.tenant_id == tenant_id)

		rows = session.execute(q).all()
		return jsonify({
			"tenant_id": tenant_id,
			"exposure": [
				{
					"account_type": r.account_type,
					"account_count": r.count,
					"total_balance_cents": r.total_balance_cents or 0,
				}
				for r in rows
			],
		})


__all__ = [
	"FinancialClientView",
	"PortfolioAccountView",
	"FinancialProductView",
	"SanctionsScreeningView",
	"FinServReportView",
]
