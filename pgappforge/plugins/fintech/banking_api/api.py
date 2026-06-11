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
# CORS — allow cross-origin requests from configured origins
# ---------------------------------------------------------------------------

@BANKING_API_BP.after_request
def _add_cors_headers(response):
	"""Add CORS headers for banking API consumers (mobile apps, web frontends)."""
	try:
		from flask import current_app, request as _req
		allowed_origins = current_app.config.get(
			"BANKING_API_CORS_ORIGINS", "*"
		)
		origin = _req.headers.get("Origin", "")
		if allowed_origins == "*":
			response.headers["Access-Control-Allow-Origin"] = "*"
		elif origin in (allowed_origins if isinstance(allowed_origins, list) else [allowed_origins]):
			response.headers["Access-Control-Allow-Origin"] = origin
			response.headers["Vary"] = "Origin"
		response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
		response.headers["Access-Control-Allow-Headers"] = (
			"Authorization, X-API-Key, Content-Type, Accept"
		)
		response.headers["Access-Control-Max-Age"] = "600"
	except Exception:
		pass
	return response


@BANKING_API_BP.route("/<path:_>", methods=["OPTIONS"])
@BANKING_API_BP.route("/", methods=["OPTIONS"])
def _handle_options(_=None):
	"""Handle CORS preflight requests."""
	from flask import make_response
	resp = make_response("", 204)
	resp.headers["Access-Control-Allow-Origin"] = "*"
	resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
	resp.headers["Access-Control-Allow-Headers"] = "Authorization, X-API-Key, Content-Type"
	return resp


# ---------------------------------------------------------------------------
# OpenAPI 3.0 specification
# ---------------------------------------------------------------------------

_OPENAPI_SPEC: dict = {
	"openapi": "3.0.3",
	"info": {
		"title": "PgAppForge Banking API",
		"version": "1.0.0",
		"description": (
			"Consumer Banking REST API — mobile banking and internet banking endpoints. "
			"Exposes account balance, statement, mini-statement, fund transfer, and "
			"product catalogue.  Authentication via Bearer token or X-API-Key header."
		),
		"contact": {
			"name": "PgAppForge Contributors",
		},
	},
	"servers": [
		{"url": "/api/v1/banking", "description": "Banking API v1"},
	],
	"components": {
		"securitySchemes": {
			"BearerAuth": {
				"type": "http",
				"scheme": "bearer",
				"description": "Bearer token validated against BANKING_API_KEYS or BANKING_API_MASTER_KEY",
			},
			"ApiKey": {
				"type": "apiKey",
				"in": "header",
				"name": "X-API-Key",
				"description": "API key header validated against BANKING_API_KEYS or BANKING_API_MASTER_KEY",
			},
		},
		"schemas": {
			"OkEnvelope": {
				"type": "object",
				"properties": {
					"status": {"type": "string", "example": "ok"},
					"data": {"type": "object"},
					"timestamp": {"type": "string", "format": "date-time"},
				},
				"required": ["status", "data", "timestamp"],
			},
			"ErrorEnvelope": {
				"type": "object",
				"properties": {
					"status": {"type": "string", "example": "error"},
					"error": {"type": "string"},
					"code": {"type": "string"},
					"timestamp": {"type": "string", "format": "date-time"},
				},
				"required": ["status", "error", "code", "timestamp"],
			},
			"BalanceData": {
				"type": "object",
				"properties": {
					"account_number": {"type": "string", "example": "20260601-HQ0001-00000001"},
					"available_balance": {"type": "string", "example": "1234.56"},
					"current_balance": {"type": "string", "example": "1234.56"},
					"currency": {"type": "string", "example": "KES"},
					"status": {"type": "string", "example": "ACTIVE"},
					"product_code": {"type": "string", "example": "SAVINGS-KES"},
				},
				"required": ["account_number", "available_balance", "current_balance", "currency", "status", "product_code"],
			},
			"StatementEntry": {
				"type": "object",
				"properties": {
					"date": {"type": "string", "format": "date"},
					"description": {"type": "string"},
					"debit": {"type": "string", "example": "0.00"},
					"credit": {"type": "string", "example": "500.00"},
					"balance": {"type": "string", "example": "1234.56"},
					"reference": {"type": "string"},
				},
			},
			"StatementData": {
				"type": "object",
				"properties": {
					"account_number": {"type": "string"},
					"from_date": {"type": "string", "format": "date"},
					"to_date": {"type": "string", "format": "date"},
					"entries": {
						"type": "array",
						"items": {"$ref": "#/components/schemas/StatementEntry"},
					},
				},
				"required": ["account_number", "from_date", "to_date", "entries"],
			},
			"MiniStatementData": {
				"type": "object",
				"properties": {
					"account_number": {"type": "string"},
					"entries": {
						"type": "array",
						"maxItems": 5,
						"items": {"$ref": "#/components/schemas/StatementEntry"},
					},
				},
				"required": ["account_number", "entries"],
			},
			"TransferRequest": {
				"type": "object",
				"properties": {
					"from_account": {
						"type": "string",
						"description": "Source account number",
						"example": "20260601-HQ0001-00000001",
					},
					"to_account": {
						"type": "string",
						"description": "Destination account number",
						"example": "20260601-HQ0001-00000002",
					},
					"amount": {
						"type": "string",
						"description": "Transfer amount as a decimal string in major-currency units",
						"example": "500.00",
					},
					"currency": {
						"type": "string",
						"description": "ISO 4217 currency code (informational; validation via product)",
						"example": "KES",
						"default": "KES",
					},
					"reference": {
						"type": "string",
						"description": "Optional caller-supplied reference (e.g. invoice number)",
						"example": "INV-2026-001",
					},
					"description": {
						"type": "string",
						"description": "Optional human-readable narration",
						"example": "Rent payment",
					},
				},
				"required": ["from_account", "to_account", "amount"],
			},
			"TransferData": {
				"type": "object",
				"properties": {
					"journal_id": {"type": "string"},
					"from_account": {"type": "string"},
					"to_account": {"type": "string"},
					"amount": {"type": "string"},
					"currency": {"type": "string"},
					"status": {"type": "string", "example": "COMPLETED"},
				},
				"required": ["journal_id", "from_account", "to_account", "amount", "currency", "status"],
			},
			"ProductItem": {
				"type": "object",
				"properties": {
					"product_code": {"type": "string", "example": "SAVINGS-KES"},
					"name": {"type": "string", "example": "KES Savings Account"},
					"type": {"type": "string", "example": "SAVINGS"},
					"currency": {"type": "string", "example": "KES"},
					"interest_rate_pct": {"type": "string", "example": "3.50"},
				},
				"required": ["product_code", "name", "type", "currency", "interest_rate_pct"],
			},
			"ProductsData": {
				"type": "object",
				"properties": {
					"products": {
						"type": "array",
						"items": {"$ref": "#/components/schemas/ProductItem"},
					},
				},
				"required": ["products"],
			},
		},
		"responses": {
			"Unauthorized": {
				"description": "Authentication required or invalid credentials",
				"content": {
					"application/json": {
						"schema": {"$ref": "#/components/schemas/ErrorEnvelope"},
					},
				},
			},
			"NotFound": {
				"description": "Requested resource not found",
				"content": {
					"application/json": {
						"schema": {"$ref": "#/components/schemas/ErrorEnvelope"},
					},
				},
			},
			"BadRequest": {
				"description": "Invalid request parameters or body",
				"content": {
					"application/json": {
						"schema": {"$ref": "#/components/schemas/ErrorEnvelope"},
					},
				},
			},
		},
	},
	"security": [
		{"BearerAuth": []},
		{"ApiKey": []},
	],
	"paths": {
		"/health": {
			"get": {
				"operationId": "healthCheck",
				"summary": "Liveness probe",
				"description": "Returns service health status.  No authentication required.",
				"tags": ["Health"],
				"security": [],
				"responses": {
					"200": {
						"description": "Service is healthy",
						"content": {
							"application/json": {
								"schema": {
									"type": "object",
									"properties": {
										"status": {"type": "string", "example": "ok"},
										"service": {"type": "string", "example": "PgAppForge Banking API v1"},
									},
								},
							},
						},
					},
				},
			},
		},
		"/accounts/{account_number}/balance": {
			"get": {
				"operationId": "getBalance",
				"summary": "Get account balance",
				"description": (
					"Returns available and current balance for the specified account. "
					"All monetary amounts are decimal strings in major-currency units (e.g. \"1234.56\")."
				),
				"tags": ["Accounts"],
				"parameters": [
					{
						"name": "account_number",
						"in": "path",
						"required": True,
						"description": "Account number",
						"schema": {"type": "string", "example": "20260601-HQ0001-00000001"},
					},
				],
				"responses": {
					"200": {
						"description": "Account balance",
						"content": {
							"application/json": {
								"schema": {
									"allOf": [
										{"$ref": "#/components/schemas/OkEnvelope"},
										{
											"type": "object",
											"properties": {
												"data": {"$ref": "#/components/schemas/BalanceData"},
											},
										},
									],
								},
							},
						},
					},
					"401": {"$ref": "#/components/responses/Unauthorized"},
					"404": {"$ref": "#/components/responses/NotFound"},
				},
			},
		},
		"/accounts/{account_number}/statement": {
			"get": {
				"operationId": "getStatement",
				"summary": "Get full account statement",
				"description": (
					"Returns a paginated list of transaction entries for the specified date range. "
					"Defaults to the last 30 days with up to 50 rows."
				),
				"tags": ["Accounts"],
				"parameters": [
					{
						"name": "account_number",
						"in": "path",
						"required": True,
						"description": "Account number",
						"schema": {"type": "string", "example": "20260601-HQ0001-00000001"},
					},
					{
						"name": "from",
						"in": "query",
						"required": False,
						"description": "Start date (ISO 8601 YYYY-MM-DD); defaults to 30 days ago",
						"schema": {"type": "string", "format": "date", "example": "2026-05-01"},
					},
					{
						"name": "to",
						"in": "query",
						"required": False,
						"description": "End date (ISO 8601 YYYY-MM-DD); defaults to today",
						"schema": {"type": "string", "format": "date", "example": "2026-05-31"},
					},
					{
						"name": "limit",
						"in": "query",
						"required": False,
						"description": "Maximum number of rows to return (default 50, max 500)",
						"schema": {"type": "integer", "minimum": 1, "maximum": 500, "default": 50},
					},
				],
				"responses": {
					"200": {
						"description": "Account statement",
						"content": {
							"application/json": {
								"schema": {
									"allOf": [
										{"$ref": "#/components/schemas/OkEnvelope"},
										{
											"type": "object",
											"properties": {
												"data": {"$ref": "#/components/schemas/StatementData"},
											},
										},
									],
								},
							},
						},
					},
					"401": {"$ref": "#/components/responses/Unauthorized"},
					"404": {"$ref": "#/components/responses/NotFound"},
				},
			},
		},
		"/accounts/{account_number}/mini-statement": {
			"get": {
				"operationId": "getMiniStatement",
				"summary": "Get mini statement (last 5 transactions)",
				"description": "Returns the last 5 transactions for the account as a quick-view summary.",
				"tags": ["Accounts"],
				"parameters": [
					{
						"name": "account_number",
						"in": "path",
						"required": True,
						"description": "Account number",
						"schema": {"type": "string", "example": "20260601-HQ0001-00000001"},
					},
				],
				"responses": {
					"200": {
						"description": "Mini statement",
						"content": {
							"application/json": {
								"schema": {
									"allOf": [
										{"$ref": "#/components/schemas/OkEnvelope"},
										{
											"type": "object",
											"properties": {
												"data": {"$ref": "#/components/schemas/MiniStatementData"},
											},
										},
									],
								},
							},
						},
					},
					"401": {"$ref": "#/components/responses/Unauthorized"},
					"404": {"$ref": "#/components/responses/NotFound"},
				},
			},
		},
		"/transfers": {
			"post": {
				"operationId": "initiateTransfer",
				"summary": "Initiate a fund transfer",
				"description": (
					"Executes a synchronous fund transfer between two accounts within the authenticated tenant. "
					"Returns HTTP 201 on success.  Domain errors (insufficient funds, frozen account, "
					"daily limit exceeded, AML block) are returned as 400 TRANSFER_FAILED."
				),
				"tags": ["Transfers"],
				"requestBody": {
					"required": True,
					"content": {
						"application/json": {
							"schema": {"$ref": "#/components/schemas/TransferRequest"},
						},
					},
				},
				"responses": {
					"201": {
						"description": "Transfer completed successfully",
						"content": {
							"application/json": {
								"schema": {
									"allOf": [
										{"$ref": "#/components/schemas/OkEnvelope"},
										{
											"type": "object",
											"properties": {
												"data": {"$ref": "#/components/schemas/TransferData"},
											},
										},
									],
								},
							},
						},
					},
					"400": {"$ref": "#/components/responses/BadRequest"},
					"401": {"$ref": "#/components/responses/Unauthorized"},
				},
			},
		},
		"/products": {
			"get": {
				"operationId": "listProducts",
				"summary": "List active banking products",
				"description": "Returns all active products available to the authenticated tenant, ordered by product code.",
				"tags": ["Products"],
				"responses": {
					"200": {
						"description": "Product catalogue",
						"content": {
							"application/json": {
								"schema": {
									"allOf": [
										{"$ref": "#/components/schemas/OkEnvelope"},
										{
											"type": "object",
											"properties": {
												"data": {"$ref": "#/components/schemas/ProductsData"},
											},
										},
									],
								},
							},
						},
					},
					"401": {"$ref": "#/components/responses/Unauthorized"},
				},
			},
		},
	},
}


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


# ---------------------------------------------------------------------------
# OpenAPI spec endpoint (public, no auth)
# ---------------------------------------------------------------------------

@BANKING_API_BP.route("/openapi.json", methods=["GET"])
def openapi_spec():
	"""GET /api/v1/banking/openapi.json — returns the OpenAPI 3.0 spec (no auth required)."""
	return jsonify(_OPENAPI_SPEC), 200


# ---------------------------------------------------------------------------
# Swagger UI (public, no auth)
# ---------------------------------------------------------------------------

@BANKING_API_BP.route("/docs", methods=["GET"])
def swagger_ui():
	"""GET /api/v1/banking/docs — minimal Swagger UI HTML page (no auth required)."""
	html = """<!DOCTYPE html>
<html><head><title>Banking API</title>
<meta charset="utf-8"/>
<link rel="stylesheet" href="https://unpkg.com/swagger-ui-dist@5/swagger-ui.css"/>
</head><body>
<div id="swagger-ui"></div>
<script src="https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
<script>
SwaggerUIBundle({url:"/api/v1/banking/openapi.json",dom_id:"#swagger-ui",
presets:[SwaggerUIBundle.presets.apis,SwaggerUIBundle.SwaggerUIStandalonePreset],
layout:"BaseLayout"});
</script></body></html>"""
	from flask import make_response
	resp = make_response(html, 200)
	resp.headers["Content-Type"] = "text/html; charset=utf-8"
	return resp
