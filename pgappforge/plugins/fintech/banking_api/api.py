"""
pgappforge/plugins/fintech/banking_api/api.py

Consumer Banking REST API — Flask Blueprint.

Endpoints (all under /api/v1/banking):
  GET  /health
  GET  /accounts/<account_number>/balance
  GET  /accounts/<account_number>/statement?from=&to=&limit=
  GET  /accounts/<account_number>/mini-statement
  POST /transfers
  GET  /products

Authentication
--------------
Every protected endpoint requires ONE of:
  Authorization: Bearer <token>   — validated against BANKING_API_KEYS or BANKING_API_MASTER_KEY
  X-API-Key: <key>                — same lookup

Sets flask.g.tenant_id and flask.g.customer_id on success.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from functools import wraps
from typing import Any

import sqlalchemy as sa
from flask import Blueprint, g, jsonify, request

log = logging.getLogger(__name__)

BANKING_API_BP = Blueprint("banking_api", __name__, url_prefix="/api/v1/banking")


# ---------------------------------------------------------------------------
# Session helper
# ---------------------------------------------------------------------------

def _get_session() -> Any:
	try:
		from flask import current_app
		return current_app.appbuilder.get_session
	except Exception as exc:
		raise RuntimeError(f"No database session available: {exc}") from exc


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

class AuthError(Exception):
	"""Raised by _validate_api_key when credentials are missing or invalid."""


def _validate_api_key(key: str) -> None:
	"""Validate *key* against BANKING_API_KEYS map or BANKING_API_MASTER_KEY.

	On success sets flask.g.tenant_id and flask.g.customer_id.
	Raises AuthError on any failure.
	"""
	if not key:
		raise AuthError("No credentials provided")

	try:
		from flask import current_app
		cfg = current_app.config

		# Per-key lookup: {api_key: {tenant_id, customer_id}}
		valid_keys: dict[str, dict[str, str]] = cfg.get("BANKING_API_KEYS", {})
		if key in valid_keys:
			entry = valid_keys[key]
			g.tenant_id = entry.get("tenant_id", "default")
			g.customer_id = entry.get("customer_id", "")
			return

		# Master key (admin / testing)
		master = cfg.get("BANKING_API_MASTER_KEY", "")
		if master and key == master:
			g.tenant_id = cfg.get("CB_TENANT_ID", "default")
			g.customer_id = ""
			return

		raise AuthError("Invalid API key")

	except AuthError:
		raise
	except Exception as exc:
		raise AuthError(f"Auth validation failed: {exc}") from exc


def _require_auth(f):
	"""Decorator: validates Bearer token or X-API-Key header."""
	@wraps(f)
	def wrapper(*args, **kwargs):
		try:
			auth_header = request.headers.get("Authorization", "")
			api_key = request.headers.get("X-API-Key", "")

			if auth_header.startswith("Bearer "):
				token = auth_header[7:]
				# Try dedicated X-API-Key first; fall back to the Bearer value.
				_validate_api_key(api_key or token)
			elif api_key:
				_validate_api_key(api_key)
			else:
				return _err("Authentication required", "AUTH_REQUIRED", 401)

			return f(*args, **kwargs)

		except AuthError as exc:
			return _err(str(exc), "UNAUTHORIZED", 401)
		except Exception as exc:
			log.error("Auth middleware unexpected error: %s", exc, exc_info=True)
			return _err("Internal server error", "INTERNAL_ERROR", 500)

	return wrapper


# ---------------------------------------------------------------------------
# Response helpers
# ---------------------------------------------------------------------------

def _ok(data: dict, status: int = 200):
	return jsonify({
		"status": "ok",
		"data": data,
		"timestamp": datetime.now(timezone.utc).isoformat(),
	}), status


def _err(message: str, code: str, status: int = 400):
	return jsonify({
		"status": "error",
		"error": message,
		"code": code,
		"timestamp": datetime.now(timezone.utc).isoformat(),
	}), status


# ---------------------------------------------------------------------------
# Health check (unauthenticated)
# ---------------------------------------------------------------------------

@BANKING_API_BP.route("/health", methods=["GET"])
def health():
	"""GET /api/v1/banking/health — liveness probe (no auth required)."""
	return jsonify({
		"status": "ok",
		"service": "PgAppForge Banking API v1",
	}), 200


# ---------------------------------------------------------------------------
# Account balance
# ---------------------------------------------------------------------------

@BANKING_API_BP.route("/accounts/<account_number>/balance", methods=["GET"])
@_require_auth
def get_balance(account_number: str):
	"""GET /api/v1/banking/accounts/{account_number}/balance

	Returns::

	    {account_number, available_balance, current_balance, currency,
	     status, product_code}

	All monetary amounts are decimal strings in major-currency units (e.g. "1234.56").
	"""
	try:
		session = _get_session()
		from pgappforge.plugins.fintech.core_banking.models import Account

		account = session.execute(
			sa.select(Account).where(
				Account.account_number == account_number,
				Account.tenant_id == g.tenant_id,
			)
		).scalar_one_or_none()

		if account is None:
			return _err("Account not found", "ACCOUNT_NOT_FOUND", 404)

		return _ok({
			"account_number": account_number,
			"available_balance": str(Decimal(str(account.available_balance_cents)) / 100),
			"current_balance": str(Decimal(str(account.current_balance_cents)) / 100),
			"currency": account.currency_code,
			"status": account.status,
			"product_code": account.product_code,
		})

	except Exception as exc:
		log.error("get_balance %s: %s", account_number, exc, exc_info=True)
		return _err(str(exc), "INTERNAL_ERROR", 500)


# ---------------------------------------------------------------------------
# Full statement
# ---------------------------------------------------------------------------

@BANKING_API_BP.route("/accounts/<account_number>/statement", methods=["GET"])
@_require_auth
def get_statement(account_number: str):
	"""GET /api/v1/banking/accounts/{account_number}/statement

	Query params:
	  from   — ISO date (YYYY-MM-DD); defaults to 30 days ago
	  to     — ISO date (YYYY-MM-DD); defaults to today
	  limit  — max rows returned (default 50, max 500)

	Returns::

	    {account_number, from_date, to_date, entries: [...]}

	Each entry: {date, description, debit, credit, balance, reference}
	"""
	try:
		from datetime import date, timedelta

		from_date_str = request.args.get("from", "")
		to_date_str = request.args.get("to", "")
		limit = min(int(request.args.get("limit", 50)), 500)

		to_date = date.fromisoformat(to_date_str) if to_date_str else date.today()
		from_date = (
			date.fromisoformat(from_date_str)
			if from_date_str
			else (to_date - timedelta(days=30))
		)

		session = _get_session()
		from pgappforge.plugins.fintech.core_banking.services import CoreBankingService

		svc = CoreBankingService()
		statement = svc.generate_statement(
			account_number=account_number,
			tenant_id=g.tenant_id,
			session=session,
			from_date=from_date,
			to_date=to_date,
		)
		# Honour the caller's limit if the service doesn't apply one itself.
		if "entries" in statement and isinstance(statement["entries"], list):
			statement["entries"] = statement["entries"][:limit]

		return _ok(statement)

	except Exception as exc:
		log.error("get_statement %s: %s", account_number, exc, exc_info=True)
		return _err(str(exc), "STATEMENT_ERROR", 500)


# ---------------------------------------------------------------------------
# Mini statement (last 5 transactions)
# ---------------------------------------------------------------------------

@BANKING_API_BP.route("/accounts/<account_number>/mini-statement", methods=["GET"])
@_require_auth
def mini_statement(account_number: str):
	"""GET /api/v1/banking/accounts/{account_number}/mini-statement

	Returns the last 5 transactions for the account.
	"""
	try:
		session = _get_session()
		from pgappforge.plugins.fintech.core_banking.services import CoreBankingService

		svc = CoreBankingService()
		result = svc.get_mini_statement(account_number, g.tenant_id, session)
		return _ok(result)

	except Exception as exc:
		log.error("mini_statement %s: %s", account_number, exc, exc_info=True)
		return _err(str(exc), "MINI_STATEMENT_ERROR", 500)


# ---------------------------------------------------------------------------
# Fund transfer
# ---------------------------------------------------------------------------

@BANKING_API_BP.route("/transfers", methods=["POST"])
@_require_auth
def initiate_transfer():
	"""POST /api/v1/banking/transfers

	Request body (JSON)::

	    {
	        "from_account": "20260601-HQ0001-00000001",
	        "to_account":   "20260601-HQ0001-00000002",
	        "amount":       "500.00",
	        "currency":     "KES",          // informational — validation via product
	        "reference":    "INV-2026-001", // optional
	        "description":  "Rent payment"  // optional
	    }

	Returns (HTTP 201)::

	    {journal_id, from_account, to_account, amount, currency, status}

	Errors:
	  400 VALIDATION_ERROR — missing required fields
	  400 INVALID_AMOUNT   — amount ≤ 0
	  400 TRANSFER_FAILED  — any CoreBankingService exception (insufficient funds,
	                          frozen account, daily limit, AML block, etc.)
	"""
	try:
		body: dict = request.get_json(force=True, silent=True) or {}

		from_account = str(body.get("from_account", "")).strip()
		to_account = str(body.get("to_account", "")).strip()
		amount_raw = str(body.get("amount", "")).strip()
		currency = str(body.get("currency", "KES")).strip()
		reference = str(body.get("reference", "")).strip()
		description = str(body.get("description", "")).strip()

		if not from_account or not to_account or not amount_raw:
			return _err(
				"from_account, to_account, and amount are required",
				"VALIDATION_ERROR",
				400,
			)

		try:
			amount_decimal = Decimal(amount_raw)
		except Exception:
			return _err(f"Invalid amount: {amount_raw!r}", "INVALID_AMOUNT", 400)

		if amount_decimal <= 0:
			return _err("Amount must be positive", "INVALID_AMOUNT", 400)

		amount_cents = int(amount_decimal * 100)

		session = _get_session()
		from pgappforge.plugins.fintech.core_banking.services import CoreBankingService

		svc = CoreBankingService()
		result = svc.transfer(
			source_account_number=from_account,
			dest_account_number=to_account,
			amount_cents=amount_cents,
			tenant_id=g.tenant_id,
			session=session,
			channel="API",
			reference=reference,
			description=description,
		)
		session.commit()

		return _ok({
			"journal_id": result.get("journal_id", ""),
			"from_account": from_account,
			"to_account": to_account,
			"amount": amount_raw,
			"currency": currency,
			"status": "COMPLETED",
		}, status=201)

	except Exception as exc:
		log.error("initiate_transfer: %s", exc, exc_info=True)
		# Surface domain errors with their message so mobile clients can act on them.
		return _err(str(exc), "TRANSFER_FAILED", 400)


# ---------------------------------------------------------------------------
# Product catalogue
# ---------------------------------------------------------------------------

@BANKING_API_BP.route("/products", methods=["GET"])
@_require_auth
def list_products():
	"""GET /api/v1/banking/products

	Returns all active products for the authenticated tenant.

	Each product::

	    {product_code, name, type, currency, interest_rate_pct}
	"""
	try:
		from pgappforge.plugins.fintech.core_banking.models import BankProduct

		session = _get_session()
		products = session.execute(
			sa.select(BankProduct).where(
				BankProduct.tenant_id == g.tenant_id,
				BankProduct.is_active.is_(True),
			).order_by(BankProduct.product_code)
		).scalars().all()

		return _ok({
			"products": [
				{
					"product_code": p.product_code,
					"name": p.product_name,
					"type": p.product_type,
					"currency": p.currency_code,
					"interest_rate_pct": str(p.interest_rate_pa or 0),
				}
				for p in products
			]
		})

	except Exception as exc:
		log.error("list_products: %s", exc, exc_info=True)
		return _err(str(exc), "PRODUCTS_ERROR", 500)
