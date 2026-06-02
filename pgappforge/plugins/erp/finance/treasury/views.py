"""
pgappforge/plugins/erp/finance/treasury/views.py

Flask views for the Treasury plugin.

Routes:
  BankAccountView       GET/POST /treasury/accounts/
                        GET      /treasury/accounts/<id>
  FXDealView            GET/POST /treasury/fx-deals/
                        POST     /treasury/fx-deals/<id>/settle
  BankStatementView     GET/POST /treasury/statements/
                        POST     /treasury/statements/<id>/reconcile
  TreasuryReportView    GET      /treasury/reports/cash-position
                        GET      /treasury/reports/fx-exposure
                        GET      /treasury/reports/bank-balances
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from decimal import Decimal

import sqlalchemy as sa
from flask import abort, jsonify, make_response, request

from pgappforge import BaseView, expose
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


def _he(s: str) -> str:
	return (
		str(s)
		.replace("&", "&amp;")
		.replace("<", "&lt;")
		.replace(">", "&gt;")
		.replace('"', "&quot;")
	)


def _fmt(v: int | None) -> str:
	if v is None:
		return ""
	return f"{v:,}"


# ---------------------------------------------------------------------------
# BankAccountView
# ---------------------------------------------------------------------------

class BankAccountView(BaseView):
	"""Bank account master CRUD.

	GET  /treasury/accounts/        — list (JSON)
	GET  /treasury/accounts/<id>    — detail (JSON)
	POST /treasury/accounts/        — create (JSON)
	"""

	route_base = "/treasury/accounts"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.finance.treasury.models import BankAccount
		session = _get_session()
		tenant_id = request.args.get("tenant_id")
		q = sa.select(BankAccount).order_by(BankAccount.bank_name, BankAccount.account_number)
		if tenant_id:
			q = q.where(BankAccount.tenant_id == tenant_id)
		accounts = session.execute(q).scalars().all()
		return jsonify({
			"bank_accounts": [
				{
					"id": a.id,
					"account_number": a.account_number,
					"bank_name": a.bank_name,
					"bank_bic": a.bank_bic,
					"currency_code": a.currency_code,
					"account_type": a.account_type,
					"gl_account": a.gl_account,
					"balance_cents": a.balance_cents,
					"available_balance_cents": a.available_balance_cents,
					"is_active": a.is_active,
					"last_reconciled_date": str(a.last_reconciled_date) if a.last_reconciled_date else None,
				}
				for a in accounts
			]
		})

	@expose("/<string:account_id>")
	@has_access
	def detail(self, account_id: str):
		from pgappforge.plugins.erp.finance.treasury.models import BankAccount
		session = _get_session()
		a = session.get(BankAccount, account_id)
		if a is None:
			abort(404)
		return jsonify({
			"id": a.id,
			"account_number": a.account_number,
			"bank_name": a.bank_name,
			"bank_bic": a.bank_bic,
			"iban": a.iban,
			"currency_code": a.currency_code,
			"account_type": a.account_type,
			"gl_account": a.gl_account,
			"balance_cents": a.balance_cents,
			"available_balance_cents": a.available_balance_cents,
			"overdraft_limit_cents": a.overdraft_limit_cents,
			"is_active": a.is_active,
			"is_default": a.is_default,
			"last_reconciled_date": str(a.last_reconciled_date) if a.last_reconciled_date else None,
			"metadata": a.metadata_,
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		from pgappforge.plugins.erp.finance.treasury.services import (
			TreasuryService, BankAccountDetails, TreasuryServiceError,
		)
		session = _get_session()
		data = request.get_json(silent=True) or {}
		required = ("tenant_id", "account_number", "bank_name", "currency_code", "gl_account")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"ok": False, "error": f"missing: {missing}"}), 400
		try:
			details = BankAccountDetails(
				tenant_id=data["tenant_id"],
				account_number=data["account_number"],
				bank_name=data["bank_name"],
				currency_code=data["currency_code"],
				gl_account=data["gl_account"],
				account_type=(data.get("account_type") or "CURRENT").upper(),
				bank_bic=data.get("bank_bic"),
				iban=data.get("iban"),
				overdraft_limit_cents=data.get("overdraft_limit_cents"),
				is_default=bool(data.get("is_default", False)),
				metadata=data.get("metadata"),
			)
			acct = TreasuryService().create_bank_account(details, session)
			session.commit()
			return jsonify({"ok": True, "id": acct.id}), 201
		except (TreasuryServiceError, AssertionError) as exc:
			return jsonify({"ok": False, "error": str(exc)}), 400


# ---------------------------------------------------------------------------
# FXDealView
# ---------------------------------------------------------------------------

class FXDealView(BaseView):
	"""FX deal CRUD + settlement.

	GET  /treasury/fx-deals/              — list (JSON)
	GET  /treasury/fx-deals/<id>          — detail (JSON)
	POST /treasury/fx-deals/              — book deal (JSON)
	POST /treasury/fx-deals/<id>/settle   — settle deal
	POST /treasury/fx-deals/mtm           — mark-to-market all open deals
	"""

	route_base = "/treasury/fx-deals"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.finance.treasury.models import FXDeal
		session = _get_session()
		tenant_id = request.args.get("tenant_id")
		status = request.args.get("status")
		q = (
			sa.select(FXDeal)
			.order_by(sa.desc(FXDeal.created_at))
			.limit(200)
		)
		if tenant_id:
			q = q.where(FXDeal.tenant_id == tenant_id)
		if status:
			q = q.where(FXDeal.status == status.upper())
		deals = session.execute(q).scalars().all()
		return jsonify({
			"fx_deals": [
				{
					"id": d.id,
					"deal_reference": d.deal_reference,
					"deal_type": d.deal_type,
					"buy_currency": d.buy_currency,
					"sell_currency": d.sell_currency,
					"buy_amount_cents": d.buy_amount_cents,
					"sell_amount_cents": d.sell_amount_cents,
					"contracted_rate": str(d.contracted_rate),
					"settlement_date": str(d.settlement_date) if d.settlement_date else None,
					"hedge_designation": d.hedge_designation,
					"status": d.status,
					"mtm_value_cents": d.mtm_value_cents,
				}
				for d in deals
			]
		})

	@expose("/<string:deal_id>")
	@has_access
	def detail(self, deal_id: str):
		from pgappforge.plugins.erp.finance.treasury.models import FXDeal
		session = _get_session()
		d = session.get(FXDeal, deal_id)
		if d is None:
			abort(404)
		return jsonify({
			"id": d.id,
			"deal_reference": d.deal_reference,
			"deal_type": d.deal_type,
			"buy_currency": d.buy_currency,
			"sell_currency": d.sell_currency,
			"buy_amount_cents": d.buy_amount_cents,
			"sell_amount_cents": d.sell_amount_cents,
			"contracted_rate": str(d.contracted_rate),
			"market_rate": str(d.market_rate) if d.market_rate else None,
			"settlement_date": str(d.settlement_date) if d.settlement_date else None,
			"trade_date": str(d.trade_date) if d.trade_date else None,
			"counterparty_id": d.counterparty_id,
			"hedge_designation": d.hedge_designation,
			"status": d.status,
			"mtm_value_cents": d.mtm_value_cents,
			"notes": d.notes,
			"metadata": d.metadata_,
		})

	@expose("/", methods=["POST"])
	@has_access
	def book(self):
		from pgappforge.plugins.erp.finance.treasury.services import (
			TreasuryService, FXDealDetails, TreasuryServiceError,
		)
		session = _get_session()
		data = request.get_json(silent=True) or {}
		required = ("tenant_id", "deal_type", "buy_currency", "sell_currency",
		            "buy_amount_cents", "sell_amount_cents", "contracted_rate", "settlement_date")
		missing = [f for f in required if data.get(f) is None]
		if missing:
			return jsonify({"ok": False, "error": f"missing: {missing}"}), 400
		try:
			details = FXDealDetails(
				tenant_id=data["tenant_id"],
				deal_type=data["deal_type"].upper(),
				buy_currency=data["buy_currency"],
				sell_currency=data["sell_currency"],
				buy_amount_cents=int(data["buy_amount_cents"]),
				sell_amount_cents=int(data["sell_amount_cents"]),
				contracted_rate=Decimal(str(data["contracted_rate"])),
				settlement_date=date.fromisoformat(data["settlement_date"]),
				counterparty_id=data.get("counterparty_id"),
				buy_bank_account_id=data.get("buy_bank_account_id"),
				sell_bank_account_id=data.get("sell_bank_account_id"),
				hedge_designation=(data.get("hedge_designation") or "NONE").upper(),
				hedged_item_id=data.get("hedged_item_id"),
				hedged_item_type=data.get("hedged_item_type"),
				deal_reference=data.get("deal_reference"),
				notes=data.get("notes"),
			)
			deal = TreasuryService().book_fx_deal(details, session)
			session.commit()
			return jsonify({"ok": True, "id": deal.id, "deal_reference": deal.deal_reference}), 201
		except (TreasuryServiceError, AssertionError) as exc:
			return jsonify({"ok": False, "error": str(exc)}), 400

	@expose("/<string:deal_id>/settle", methods=["POST"])
	@has_access
	def settle(self, deal_id: str):
		from pgappforge.plugins.erp.finance.treasury.services import TreasuryService, TreasuryServiceError
		session = _get_session()
		try:
			deal = TreasuryService().settle_fx_deal(deal_id, session)
			session.commit()
			return jsonify({"ok": True, "deal_reference": deal.deal_reference, "status": deal.status})
		except TreasuryServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 400

	@expose("/mtm", methods=["POST"])
	@has_access
	def mark_to_market(self):
		from pgappforge.plugins.erp.finance.treasury.services import TreasuryService
		session = _get_session()
		data = request.get_json(silent=True) or {}
		results = TreasuryService().mark_to_market_hedges(
			session, tenant_id=data.get("tenant_id")
		)
		session.commit()
		return jsonify({"ok": True, "deals_updated": len(results), "results": results})


# ---------------------------------------------------------------------------
# BankStatementView
# ---------------------------------------------------------------------------

class BankStatementView(BaseView):
	"""Bank statement import and reconciliation.

	GET  /treasury/statements/              — list statements (JSON)
	POST /treasury/statements/              — import statement header + lines (JSON)
	POST /treasury/statements/<id>/reconcile — run auto-reconciliation
	GET  /treasury/statements/<id>/lines    — list lines (JSON)
	"""

	route_base = "/treasury/statements"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.finance.treasury.models import BankStatement
		session = _get_session()
		tenant_id = request.args.get("tenant_id")
		q = sa.select(BankStatement).order_by(sa.desc(BankStatement.statement_date)).limit(100)
		if tenant_id:
			q = q.where(BankStatement.tenant_id == tenant_id)
		stmts = session.execute(q).scalars().all()
		return jsonify({
			"statements": [
				{
					"id": s.id,
					"bank_account_id": s.bank_account_id,
					"statement_date": str(s.statement_date) if s.statement_date else None,
					"opening_balance_cents": s.opening_balance_cents,
					"closing_balance_cents": s.closing_balance_cents,
					"status": s.status,
				}
				for s in stmts
			]
		})

	@expose("/", methods=["POST"])
	@has_access
	def import_statement(self):
		"""Import a bank statement with lines."""
		from pgappforge.plugins.erp.finance.treasury.models import BankStatement, BankStatementLine
		session = _get_session()
		data = request.get_json(silent=True) or {}
		required = ("tenant_id", "bank_account_id", "statement_date",
		            "opening_balance_cents", "closing_balance_cents")
		missing = [f for f in required if data.get(f) is None]
		if missing:
			return jsonify({"ok": False, "error": f"missing: {missing}"}), 400
		stmt = BankStatement(
			tenant_id=data["tenant_id"],
			bank_account_id=data["bank_account_id"],
			statement_date=date.fromisoformat(data["statement_date"]),
			opening_balance_cents=int(data["opening_balance_cents"]),
			closing_balance_cents=int(data["closing_balance_cents"]),
			status="IMPORTED",
			import_reference=data.get("import_reference"),
		)
		session.add(stmt)
		session.flush()
		lines_data = data.get("lines") or []
		for ld in lines_data:
			line = BankStatementLine(
				statement_id=stmt.id,
				transaction_date=date.fromisoformat(ld["transaction_date"]),
				value_date=date.fromisoformat(ld["value_date"]) if ld.get("value_date") else None,
				description=ld.get("description", ""),
				amount_cents=int(ld["amount_cents"]),
				is_debit=bool(ld["is_debit"]),
				bank_reference=ld.get("bank_reference"),
				match_status="UNMATCHED",
			)
			session.add(line)
		session.commit()
		return jsonify({"ok": True, "id": stmt.id, "lines_imported": len(lines_data)}), 201

	@expose("/<string:stmt_id>/reconcile", methods=["POST"])
	@has_access
	def reconcile(self, stmt_id: str):
		from pgappforge.plugins.erp.finance.treasury.models import BankStatement
		from pgappforge.plugins.erp.finance.treasury.services import TreasuryService, TreasuryServiceError
		session = _get_session()
		stmt = session.get(BankStatement, stmt_id)
		if stmt is None:
			abort(404)
		try:
			result = TreasuryService().run_bank_reconciliation(
				stmt.bank_account_id, stmt_id, session,
			)
			session.commit()
			return jsonify({"ok": True, **result})
		except TreasuryServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 400

	@expose("/<string:stmt_id>/lines")
	@has_access
	def lines(self, stmt_id: str):
		from pgappforge.plugins.erp.finance.treasury.models import BankStatementLine
		session = _get_session()
		rows = session.execute(
			sa.select(BankStatementLine)
			.where(BankStatementLine.statement_id == stmt_id)
			.order_by(BankStatementLine.transaction_date)
		).scalars().all()
		return jsonify({
			"lines": [
				{
					"id": r.id,
					"transaction_date": str(r.transaction_date),
					"value_date": str(r.value_date) if r.value_date else None,
					"description": r.description,
					"amount_cents": r.amount_cents,
					"is_debit": r.is_debit,
					"bank_reference": r.bank_reference,
					"match_status": r.match_status,
					"matched_document_type": r.matched_document_type,
					"matched_document_id": r.matched_document_id,
					"exception_reason": r.exception_reason,
				}
				for r in rows
			]
		})


# ---------------------------------------------------------------------------
# TreasuryReportView (3 reports)
# ---------------------------------------------------------------------------

class TreasuryReportView(BaseView):
	"""Treasury reports.

	GET /treasury/reports/cash-position   — Daily cash position table (HTML)
	GET /treasury/reports/fx-exposure     — Open FX deals exposure (HTML)
	GET /treasury/reports/bank-balances   — Bank account balances summary (HTML)
	"""

	route_base = "/treasury/reports"
	default_view = "bank_balances"

	@expose("/cash-position")
	@has_access
	def cash_position(self):
		"""Daily cash position report for last 30 days."""
		from pgappforge.plugins.erp.finance.treasury.models import BankAccount, CashPosition
		session = _get_session()
		tenant_id = request.args.get("tenant_id")

		q = (
			sa.select(CashPosition, BankAccount.account_number, BankAccount.currency_code)
			.join(BankAccount, CashPosition.bank_account_id == BankAccount.id)
			.order_by(sa.desc(CashPosition.position_date), BankAccount.account_number)
			.limit(300)
		)
		if tenant_id:
			q = q.where(CashPosition.tenant_id == tenant_id)
		rows = session.execute(q).all()

		table_rows = "".join(
			f"<tr>"
			f"<td>{_he(str(r.position_date) if r.CashPosition.position_date else '')}</td>"
			f"<td>{_he(r.account_number)}</td>"
			f"<td>{_he(r.currency_code)}</td>"
			f"<td style='text-align:right'>{_fmt(r.CashPosition.opening_balance_cents)}</td>"
			f"<td style='text-align:right'>{_fmt(r.CashPosition.receipts_cents)}</td>"
			f"<td style='text-align:right'>{_fmt(r.CashPosition.payments_cents)}</td>"
			f"<td style='text-align:right'><strong>{_fmt(r.CashPosition.closing_balance_cents)}</strong></td>"
			f"<td style='text-align:right;color:#666'>{_fmt(r.CashPosition.forecast_balance_cents)}</td>"
			f"</tr>"
			for r in rows
		)
		html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>Cash Position</title>
<link rel="stylesheet" href="https://maxcdn.bootstrapcdn.com/bootstrap/3.3.7/css/bootstrap.min.css">
<style>body{{padding:24px}}</style></head><body>
<h3>Daily Cash Position Report</h3>
<table class="table table-bordered table-condensed table-hover" style="font-size:0.85em">
<thead><tr><th>Date</th><th>Account</th><th>CCY</th>
<th style="text-align:right">Opening</th><th style="text-align:right">Receipts</th>
<th style="text-align:right">Payments</th><th style="text-align:right">Closing</th>
<th style="text-align:right">Forecast</th></tr></thead>
<tbody>{table_rows}</tbody></table>
<p style="color:#888;font-size:0.75em">Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}</p>
</body></html>"""
		return make_response(html, 200)

	@expose("/fx-exposure")
	@has_access
	def fx_exposure(self):
		"""Open FX deal exposure report."""
		from pgappforge.plugins.erp.finance.treasury.models import FXDeal
		session = _get_session()
		tenant_id = request.args.get("tenant_id")
		q = (
			sa.select(FXDeal)
			.where(FXDeal.status == "OPEN")
			.order_by(FXDeal.settlement_date)
		)
		if tenant_id:
			q = q.where(FXDeal.tenant_id == tenant_id)
		deals = session.execute(q).scalars().all()

		table_rows = "".join(
			f"<tr>"
			f"<td>{_he(d.deal_reference)}</td>"
			f"<td>{_he(d.deal_type)}</td>"
			f"<td>{_he(d.sell_currency)}</td>"
			f"<td style='text-align:right'>{_fmt(d.sell_amount_cents)}</td>"
			f"<td>{_he(d.buy_currency)}</td>"
			f"<td style='text-align:right'>{_fmt(d.buy_amount_cents)}</td>"
			f"<td style='text-align:right'>{_he(str(d.contracted_rate))}</td>"
			f"<td>{_he(str(d.settlement_date) if d.settlement_date else '')}</td>"
			f"<td>{_he(d.hedge_designation)}</td>"
			f"<td style='text-align:right'>{_fmt(d.mtm_value_cents)}</td>"
			f"</tr>"
			for d in deals
		)
		html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>FX Exposure</title>
<link rel="stylesheet" href="https://maxcdn.bootstrapcdn.com/bootstrap/3.3.7/css/bootstrap.min.css">
<style>body{{padding:24px}}</style></head><body>
<h3>Open FX Deal Exposure</h3>
<table class="table table-bordered table-condensed table-hover" style="font-size:0.85em">
<thead><tr><th>Reference</th><th>Type</th><th>Sell CCY</th>
<th style="text-align:right">Sell Amt</th><th>Buy CCY</th>
<th style="text-align:right">Buy Amt</th><th style="text-align:right">Rate</th>
<th>Settlement</th><th>Hedge</th><th style="text-align:right">MTM</th></tr></thead>
<tbody>{table_rows}</tbody></table>
<p style="color:#888;font-size:0.75em">{len(deals)} open deals — Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}</p>
</body></html>"""
		return make_response(html, 200)

	@expose("/bank-balances")
	@has_access
	def bank_balances(self):
		"""Bank account balances summary."""
		from pgappforge.plugins.erp.finance.treasury.models import BankAccount
		session = _get_session()
		tenant_id = request.args.get("tenant_id")
		q = (
			sa.select(BankAccount)
			.where(BankAccount.is_active.is_(True))
			.order_by(BankAccount.currency_code, BankAccount.bank_name)
		)
		if tenant_id:
			q = q.where(BankAccount.tenant_id == tenant_id)
		accounts = session.execute(q).scalars().all()

		table_rows = "".join(
			f"<tr>"
			f"<td>{_he(a.bank_name)}</td>"
			f"<td>{_he(a.account_number)}</td>"
			f"<td>{_he(a.currency_code)}</td>"
			f"<td>{_he(a.account_type)}</td>"
			f"<td style='text-align:right'><strong>{_fmt(a.balance_cents)}</strong></td>"
			f"<td style='text-align:right'>{_fmt(a.available_balance_cents)}</td>"
			f"<td>{_he(str(a.last_reconciled_date) if a.last_reconciled_date else 'Never')}</td>"
			f"</tr>"
			for a in accounts
		)
		html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>Bank Balances</title>
<link rel="stylesheet" href="https://maxcdn.bootstrapcdn.com/bootstrap/3.3.7/css/bootstrap.min.css">
<style>body{{padding:24px}}</style></head><body>
<h3>Bank Account Balances</h3>
<p style="color:#888">As at {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}</p>
<table class="table table-bordered table-condensed table-hover">
<thead><tr><th>Bank</th><th>Account No.</th><th>CCY</th><th>Type</th>
<th style="text-align:right">Balance</th><th style="text-align:right">Available</th>
<th>Last Reconciled</th></tr></thead>
<tbody>{table_rows}</tbody></table>
<p style="color:#888;font-size:0.75em">{len(accounts)} active accounts</p>
</body></html>"""
		return make_response(html, 200)


__all__ = [
	"BankAccountView",
	"FXDealView",
	"BankStatementView",
	"TreasuryReportView",
]
