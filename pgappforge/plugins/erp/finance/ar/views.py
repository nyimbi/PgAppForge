"""
pgappforge/plugins/erp/finance/ar/views.py

Flask views for the Accounts Receivable plugin.

All mutating endpoints accept JSON bodies and return JSON.
List/report endpoints return HTML (printable, Bootstrap 3).

Route summary
-------------
ARCustomerView      /ar/customers/
ARInvoiceView       /ar/invoices/
ARPaymentView       /ar/payments/
ARCreditNoteView    /ar/credit-notes/
ARDunningView       /ar/dunning/
ARReportView        /ar/reports/
  ├─ /aging                  — AR Aging Report (HTML)
  ├─ /statement/<customer_id> — Customer Statement (HTML)
  └─ /overdue                — Overdue Invoices Report (HTML)
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone

import sqlalchemy as sa
from flask import abort, jsonify, make_response, request

from pgappforge import expose
from pgappforge.plugins.erp.base_view import BaseERPView
from pgappforge.security.decorators import has_access

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Session helper (identical pattern to foundation)
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
	"""Minimal HTML-escape."""
	return (
		str(s)
		.replace("&", "&amp;")
		.replace("<", "&lt;")
		.replace(">", "&gt;")
		.replace('"', "&quot;")
	)


def _cents_to_display(cents: int | None, currency: str = "USD") -> str:
	"""Format integer cents as a human-readable string, e.g. '1,234.56 USD'."""
	if cents is None:
		return "—"
	major = cents // 100
	minor = abs(cents) % 100
	sign = "-" if cents < 0 else ""
	return f"{sign}{major:,}.{minor:02d} {currency}"


# ---------------------------------------------------------------------------
# ARCustomerView
# ---------------------------------------------------------------------------

class ARCustomerView(BaseERPView):
	"""AR Customer CRUD.

	GET  /ar/customers/                — paginated list (HTML)
	GET  /ar/customers/<id>            — detail (JSON)
	POST /ar/customers/                — create (JSON in/out)
	PUT  /ar/customers/<id>            — update (JSON in/out)
	POST /ar/customers/<id>/credit-hold — place / release credit hold
	GET  /ar/customers/<id>/credit-check?amount=<cents> — credit availability
	"""

	route_base = "/ar/customers"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		session = _get_session()
		from pgappforge.plugins.erp.finance.ar.models import ARCustomer
		tenant_id = request.args.get("tenant_id")
		status = request.args.get("status", "ACTIVE")
		q = (
			sa.select(ARCustomer)
			.where(ARCustomer.status == status.upper())
			.order_by(ARCustomer.account_number)
			.limit(500)
		)
		if tenant_id:
			q = q.where(ARCustomer.tenant_id == tenant_id)
		customers = session.execute(q).scalars().all()

		rows = "".join(
			f"<tr>"
			f"<td>{_he(c.account_number)}</td>"
			f"<td>{_he(c.customer_type)}</td>"
			f"<td>{_he(c.status)}</td>"
			f"<td class='text-right'>{_cents_to_display(c.credit_limit_cents)}</td>"
			f"<td class='text-right'>{_cents_to_display(c.credit_used_cents)}</td>"
			f"<td>{_he('YES' if c.credit_hold else 'no')}</td>"
			f"<td>{c.dunning_level}</td>"
			f"<td>{_he(c.payment_terms_days)} days</td>"
			f"<td><a href='/ar/customers/{_he(c.id)}' class='btn btn-xs btn-primary'>View</a></td>"
			f"</tr>"
			for c in customers
		)
		html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>AR Customers</title>
<link rel="stylesheet" href="https://maxcdn.bootstrapcdn.com/bootstrap/3.3.7/css/bootstrap.min.css">
</head><body style="padding:24px">
<h3>AR Customers <small>({len(customers)})</small></h3>
<table class="table table-bordered table-hover table-condensed">
<thead><tr><th>Account</th><th>Type</th><th>Status</th><th>Credit Limit</th>
<th>Credit Used</th><th>Hold</th><th>Dunning</th><th>Terms</th><th></th></tr></thead>
<tbody>{rows}</tbody></table></body></html>"""
		return make_response(html, 200)

	@expose("/<string:customer_id>")
	@has_access
	def detail(self, customer_id: str):
		session = _get_session()
		from pgappforge.plugins.erp.finance.ar.models import ARCustomer
		c = session.get(ARCustomer, customer_id)
		if c is None:
			abort(404)
		return jsonify({
			"id": c.id,
			"tenant_id": c.tenant_id,
			"party_id": c.party_id,
			"account_number": c.account_number,
			"customer_type": c.customer_type,
			"credit_limit_cents": c.credit_limit_cents,
			"credit_used_cents": c.credit_used_cents,
			"credit_hold": c.credit_hold,
			"payment_terms_days": c.payment_terms_days,
			"dunning_level": c.dunning_level,
			"dunning_blocked": c.dunning_blocked,
			"gl_reconciliation_account": c.gl_reconciliation_account,
			"statement_frequency": c.statement_frequency,
			"last_statement_date": c.last_statement_date.isoformat() if c.last_statement_date else None,
			"risk_score": str(c.risk_score) if c.risk_score is not None else None,
			"status": c.status,
			"billing_address": c.billing_address,
			"contact_email": c.contact_email,
			"contact_phone": c.contact_phone,
			"created_at": c.created_at.isoformat() if c.created_at else None,
			"updated_at": c.updated_at.isoformat() if c.updated_at else None,
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		session = _get_session()
		from pgappforge.plugins.erp.finance.ar.models import ARCustomer
		data = request.get_json(silent=True) or {}
		required = ("tenant_id", "party_id", "account_number")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"ok": False, "error": f"Missing required fields: {missing}"}), 400

		c = ARCustomer(
			tenant_id=data["tenant_id"],
			party_id=data["party_id"],
			account_number=data["account_number"],
			customer_type=(data.get("customer_type") or "CUSTOMER").upper(),
			credit_limit_cents=data.get("credit_limit_cents"),
			credit_used_cents=int(data.get("credit_used_cents") or 0),
			credit_hold=bool(data.get("credit_hold", False)),
			payment_terms_days=int(data.get("payment_terms_days") or 30),
			dunning_level=int(data.get("dunning_level") or 0),
			dunning_blocked=bool(data.get("dunning_blocked", False)),
			gl_reconciliation_account=data.get("gl_reconciliation_account"),
			statement_frequency=(data.get("statement_frequency") or "MONTHLY").upper(),
			risk_score=data.get("risk_score"),
			status=(data.get("status") or "ACTIVE").upper(),
			billing_address=data.get("billing_address") or {},
			contact_email=data.get("contact_email"),
			contact_phone=data.get("contact_phone"),
		)
		session.add(c)
		session.commit()
		return jsonify({"ok": True, "id": c.id}), 201

	@expose("/<string:customer_id>", methods=["PUT"])
	@has_access
	def update(self, customer_id: str):
		session = _get_session()
		from pgappforge.plugins.erp.finance.ar.models import ARCustomer
		c = session.get(ARCustomer, customer_id)
		if c is None:
			abort(404)
		data = request.get_json(silent=True) or {}
		updatable = [
			"customer_type", "credit_limit_cents", "payment_terms_days",
			"dunning_blocked", "gl_reconciliation_account", "statement_frequency",
			"risk_score", "status", "billing_address", "contact_email", "contact_phone",
		]
		changed = []
		for field in updatable:
			if field in data:
				setattr(c, field, data[field])
				changed.append(field)
		c.updated_at = datetime.now(timezone.utc)
		session.commit()
		return jsonify({"ok": True, "changed": changed})

	@expose("/<string:customer_id>/credit-hold", methods=["POST"])
	@has_access
	def set_credit_hold(self, customer_id: str):
		session = _get_session()
		from pgappforge.plugins.erp.finance.ar.models import ARCustomer
		from pgappforge.plugins.erp.finance.ar.events import (
			CreditHoldPlacedEvent, CreditHoldReleasedEvent,
		)
		from pgappforge.plugins.erp.foundation.events import emit_event
		c = session.get(ARCustomer, customer_id)
		if c is None:
			abort(404)
		data = request.get_json(silent=True) or {}
		hold = bool(data.get("credit_hold", True))
		c.credit_hold = hold
		c.updated_at = datetime.now(timezone.utc)
		if hold:
			emit_event(
				CreditHoldPlacedEvent(
					aggregate_id=c.id, aggregate_type="ARCustomer", tenant_id=c.tenant_id,
					customer_id=c.id, account_number=c.account_number,
					credit_used_cents=c.credit_used_cents or 0,
					credit_limit_cents=c.credit_limit_cents or 0,
				),
				session,
			)
		else:
			emit_event(
				CreditHoldReleasedEvent(
					aggregate_id=c.id, aggregate_type="ARCustomer", tenant_id=c.tenant_id,
					customer_id=c.id, account_number=c.account_number,
				),
				session,
			)
		session.commit()
		return jsonify({"ok": True, "credit_hold": hold})

	@expose("/<string:customer_id>/credit-check")
	@has_access
	def credit_check(self, customer_id: str):
		session = _get_session()
		from pgappforge.plugins.erp.finance.ar.services import ARService, ARCustomerNotFoundError
		amount_str = request.args.get("amount", "0")
		try:
			amount_cents = int(amount_str)
		except ValueError:
			return jsonify({"ok": False, "error": "amount must be integer cents"}), 400
		svc = ARService()
		try:
			ok = svc.credit_check(customer_id, amount_cents, session)
			return jsonify({"ok": True, "approved": ok, "amount_cents": amount_cents})
		except ARCustomerNotFoundError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 404


# ---------------------------------------------------------------------------
# ARInvoiceView
# ---------------------------------------------------------------------------

class ARInvoiceView(BaseERPView):
	"""AR Invoice CRUD + business actions.

	GET  /ar/invoices/                    — paginated list (HTML)
	GET  /ar/invoices/<id>               — detail (JSON)
	POST /ar/invoices/                    — create draft (JSON)
	POST /ar/invoices/<id>/lines         — add line (JSON)
	POST /ar/invoices/<id>/issue         — DRAFT → ISSUED
	POST /ar/invoices/<id>/dispute       — mark DISPUTED
	POST /ar/invoices/<id>/write-off     — write off bad debt
	POST /ar/invoices/<id>/cancel        — cancel DRAFT invoice
	"""

	route_base = "/ar/invoices"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		session = _get_session()
		from pgappforge.plugins.erp.finance.ar.models import ARInvoice
		tenant_id = request.args.get("tenant_id")
		status = request.args.get("status")
		customer_id = request.args.get("customer_id")
		q = (
			sa.select(ARInvoice)
			.order_by(sa.desc(ARInvoice.invoice_date), ARInvoice.invoice_number)
			.limit(500)
		)
		if tenant_id:
			q = q.where(ARInvoice.tenant_id == tenant_id)
		if status:
			q = q.where(ARInvoice.status == status.upper())
		if customer_id:
			q = q.where(ARInvoice.customer_id == customer_id)
		invoices = session.execute(q).scalars().all()

		rows = "".join(
			f"<tr>"
			f"<td>{_he(inv.invoice_number)}</td>"
			f"<td>{_he(inv.invoice_date)}</td>"
			f"<td>{_he(inv.due_date)}</td>"
			f"<td>{_he(inv.status)}</td>"
			f"<td class='text-right'>{_cents_to_display(inv.total_cents, inv.currency_code)}</td>"
			f"<td class='text-right'>{_cents_to_display(inv.balance_due_cents, inv.currency_code)}</td>"
			f"<td><a href='/ar/invoices/{_he(inv.id)}' class='btn btn-xs btn-primary'>View</a></td>"
			f"</tr>"
			for inv in invoices
		)
		html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>AR Invoices</title>
<link rel="stylesheet" href="https://maxcdn.bootstrapcdn.com/bootstrap/3.3.7/css/bootstrap.min.css">
</head><body style="padding:24px">
<h3>AR Invoices <small>({len(invoices)})</small></h3>
<table class="table table-bordered table-hover table-condensed">
<thead><tr><th>Invoice #</th><th>Date</th><th>Due</th><th>Status</th>
<th>Total</th><th>Balance Due</th><th></th></tr></thead>
<tbody>{rows}</tbody></table></body></html>"""
		return make_response(html, 200)

	@expose("/<string:invoice_id>")
	@has_access
	def detail(self, invoice_id: str):
		session = _get_session()
		from pgappforge.plugins.erp.finance.ar.models import ARInvoice, ARInvoiceLine
		inv = session.get(ARInvoice, invoice_id)
		if inv is None:
			abort(404)
		lines = session.execute(
			sa.select(ARInvoiceLine)
			.where(ARInvoiceLine.invoice_id == invoice_id)
			.order_by(ARInvoiceLine.line_number)
		).scalars().all()
		return jsonify({
			"id": inv.id,
			"invoice_number": inv.invoice_number,
			"customer_id": inv.customer_id,
			"invoice_date": inv.invoice_date.isoformat() if inv.invoice_date else None,
			"due_date": inv.due_date.isoformat() if inv.due_date else None,
			"billing_period_start": inv.billing_period_start.isoformat() if inv.billing_period_start else None,
			"billing_period_end": inv.billing_period_end.isoformat() if inv.billing_period_end else None,
			"currency_code": inv.currency_code,
			"exchange_rate": str(inv.exchange_rate) if inv.exchange_rate is not None else None,
			"subtotal_cents": inv.subtotal_cents,
			"discount_cents": inv.discount_cents,
			"tax_cents": inv.tax_cents,
			"total_cents": inv.total_cents,
			"paid_cents": inv.paid_cents,
			"balance_due_cents": inv.balance_due_cents,
			"write_off_cents": inv.write_off_cents,
			"status": inv.status,
			"gl_revenue_account": inv.gl_revenue_account,
			"gl_ar_account": inv.gl_ar_account,
			"po_reference": inv.po_reference,
			"contract_reference": inv.contract_reference,
			"dispute_reason": inv.dispute_reason,
			"write_off_date": inv.write_off_date.isoformat() if inv.write_off_date else None,
			"write_off_reason": inv.write_off_reason,
			"paid_date": inv.paid_date.isoformat() if inv.paid_date else None,
			"dunning_level": inv.dunning_level,
			"notes": inv.notes,
			"lines": [
				{
					"id": ln.id,
					"line_number": ln.line_number,
					"description": ln.description,
					"quantity": str(ln.quantity),
					"uom": ln.uom,
					"unit_price_cents": ln.unit_price_cents,
					"discount_pct": str(ln.discount_pct),
					"line_amount_cents": ln.line_amount_cents,
					"tax_category": ln.tax_category,
					"tax_rate": str(ln.tax_rate),
					"tax_cents": ln.tax_cents,
					"gl_revenue_account": ln.gl_revenue_account,
					"cost_center": ln.cost_center,
					"project_code": ln.project_code,
				}
				for ln in lines
			],
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		session = _get_session()
		from pgappforge.plugins.erp.finance.ar.models import ARInvoice
		data = request.get_json(silent=True) or {}
		required = ("tenant_id", "customer_id", "invoice_number", "invoice_date", "due_date")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"ok": False, "error": f"Missing: {missing}"}), 400

		inv_date = date.fromisoformat(data["invoice_date"])
		due_date = date.fromisoformat(data["due_date"])

		inv = ARInvoice(
			tenant_id=data["tenant_id"],
			customer_id=data["customer_id"],
			invoice_number=data["invoice_number"],
			invoice_date=inv_date,
			due_date=due_date,
			billing_period_start=date.fromisoformat(data["billing_period_start"]) if data.get("billing_period_start") else None,
			billing_period_end=date.fromisoformat(data["billing_period_end"]) if data.get("billing_period_end") else None,
			currency_code=(data.get("currency_code") or "USD").upper(),
			exchange_rate=data.get("exchange_rate", 1),
			discount_cents=int(data.get("discount_cents") or 0),
			gl_revenue_account=data.get("gl_revenue_account"),
			gl_ar_account=data.get("gl_ar_account"),
			po_reference=data.get("po_reference"),
			contract_reference=data.get("contract_reference"),
			billing_reference_id=data.get("billing_reference_id"),
			notes=data.get("notes"),
			delivery_address=data.get("delivery_address") or {},
			status="DRAFT",
		)
		session.add(inv)
		session.commit()
		return jsonify({"ok": True, "id": inv.id}), 201

	@expose("/<string:invoice_id>/lines", methods=["POST"])
	@has_access
	def add_line(self, invoice_id: str):
		session = _get_session()
		from pgappforge.plugins.erp.finance.ar.models import ARInvoice, ARInvoiceLine
		from decimal import Decimal, ROUND_HALF_UP
		inv = session.get(ARInvoice, invoice_id)
		if inv is None:
			abort(404)
		if inv.status != "DRAFT":
			return jsonify({"ok": False, "error": "Lines can only be added to DRAFT invoices"}), 400

		data = request.get_json(silent=True) or {}
		required = ("description", "quantity", "unit_price_cents")
		missing = [f for f in required if data.get(f) is None]
		if missing:
			return jsonify({"ok": False, "error": f"Missing: {missing}"}), 400

		# Compute next line number
		max_line = session.execute(
			sa.select(sa.func.coalesce(sa.func.max(ARInvoiceLine.line_number), 0))
			.where(ARInvoiceLine.invoice_id == invoice_id)
		).scalar() or 0
		line_num = max_line + 1

		qty = Decimal(str(data["quantity"]))
		unit_price = int(data["unit_price_cents"])
		discount_pct = Decimal(str(data.get("discount_pct") or 0))
		tax_rate = Decimal(str(data.get("tax_rate") or 0))

		line_amount = int((qty * unit_price * (1 - discount_pct / 100)).to_integral_value(ROUND_HALF_UP))
		tax_cents = int((line_amount * tax_rate / 100).to_integral_value(ROUND_HALF_UP))

		ln = ARInvoiceLine(
			tenant_id=inv.tenant_id,
			invoice_id=invoice_id,
			line_number=line_num,
			description=data["description"],
			quantity=qty,
			uom=data.get("uom"),
			unit_price_cents=unit_price,
			discount_pct=discount_pct,
			line_amount_cents=line_amount,
			tax_category=data.get("tax_category"),
			tax_rate=tax_rate,
			tax_cents=tax_cents,
			gl_revenue_account=data.get("gl_revenue_account") or inv.gl_revenue_account,
			cost_center=data.get("cost_center"),
			project_code=data.get("project_code"),
			department=data.get("department"),
			product_id=data.get("product_id"),
			product_sku=data.get("product_sku"),
			delivery_date=date.fromisoformat(data["delivery_date"]) if data.get("delivery_date") else None,
		)
		session.add(ln)
		session.commit()
		return jsonify({"ok": True, "id": ln.id, "line_number": line_num,
		                "line_amount_cents": line_amount, "tax_cents": tax_cents}), 201

	@expose("/<string:invoice_id>/issue", methods=["POST"])
	@has_access
	def issue(self, invoice_id: str):
		session = _get_session()
		from pgappforge.plugins.erp.finance.ar.services import ARService, ARServiceError
		svc = ARService()
		try:
			inv = svc.issue_invoice(invoice_id, session)
			session.commit()
			return jsonify({
				"ok": True, "id": inv.id, "status": inv.status,
				"total_cents": inv.total_cents, "balance_due_cents": inv.balance_due_cents,
			})
		except ARServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 422

	@expose("/<string:invoice_id>/dispute", methods=["POST"])
	@has_access
	def dispute(self, invoice_id: str):
		session = _get_session()
		from pgappforge.plugins.erp.finance.ar.models import ARInvoice
		from pgappforge.plugins.erp.finance.ar.events import InvoiceDisputedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event
		inv = session.get(ARInvoice, invoice_id)
		if inv is None:
			abort(404)
		if inv.status not in ("ISSUED", "PARTIAL", "OVERDUE"):
			return jsonify({"ok": False, "error": f"Cannot dispute invoice in status {inv.status!r}"}), 400
		data = request.get_json(silent=True) or {}
		reason = data.get("reason", "")
		inv.status = "DISPUTED"
		inv.dispute_reason = reason
		inv.updated_at = datetime.now(timezone.utc)
		emit_event(
			InvoiceDisputedEvent(
				aggregate_id=inv.id, aggregate_type="ARInvoice", tenant_id=inv.tenant_id,
				invoice_id=inv.id, invoice_number=inv.invoice_number,
				customer_id=inv.customer_id, dispute_reason=reason,
				disputed_cents=inv.balance_due_cents,
			),
			session,
		)
		session.commit()
		return jsonify({"ok": True, "status": "DISPUTED"})

	@expose("/<string:invoice_id>/write-off", methods=["POST"])
	@has_access
	def write_off(self, invoice_id: str):
		session = _get_session()
		from pgappforge.plugins.erp.finance.ar.services import ARService, ARServiceError
		data = request.get_json(silent=True) or {}
		reason = data.get("reason", "")
		svc = ARService()
		try:
			inv = svc.write_off(invoice_id, reason, session)
			session.commit()
			return jsonify({"ok": True, "status": inv.status, "write_off_cents": inv.write_off_cents})
		except ARServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 422

	@expose("/<string:invoice_id>/cancel", methods=["POST"])
	@has_access
	def cancel(self, invoice_id: str):
		session = _get_session()
		from pgappforge.plugins.erp.finance.ar.models import ARInvoice
		inv = session.get(ARInvoice, invoice_id)
		if inv is None:
			abort(404)
		if inv.status != "DRAFT":
			return jsonify({"ok": False, "error": "Only DRAFT invoices can be cancelled"}), 400
		inv.status = "CANCELLED"
		inv.updated_at = datetime.now(timezone.utc)
		session.commit()
		return jsonify({"ok": True, "status": "CANCELLED"})


# ---------------------------------------------------------------------------
# ARPaymentView
# ---------------------------------------------------------------------------

class ARPaymentView(BaseERPView):
	"""AR Payment CRUD + allocation.

	GET  /ar/payments/                  — list (HTML)
	GET  /ar/payments/<id>              — detail (JSON)
	POST /ar/payments/                  — create payment record (JSON)
	POST /ar/payments/<id>/allocate     — apply payment to invoices (JSON)
	POST /ar/payments/<id>/return       — mark payment as RETURNED
	"""

	route_base = "/ar/payments"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		session = _get_session()
		from pgappforge.plugins.erp.finance.ar.models import ARPayment
		tenant_id = request.args.get("tenant_id")
		status = request.args.get("status")
		q = (
			sa.select(ARPayment)
			.order_by(sa.desc(ARPayment.payment_date))
			.limit(500)
		)
		if tenant_id:
			q = q.where(ARPayment.tenant_id == tenant_id)
		if status:
			q = q.where(ARPayment.status == status.upper())
		payments = session.execute(q).scalars().all()

		rows = "".join(
			f"<tr>"
			f"<td>{_he(p.payment_number)}</td>"
			f"<td>{_he(p.payment_date)}</td>"
			f"<td>{_he(p.payment_method)}</td>"
			f"<td class='text-right'>{_cents_to_display(p.amount_cents, p.currency_code)}</td>"
			f"<td>{_he(p.status)}</td>"
			f"<td>{_he(p.bank_reference or '')}</td>"
			f"<td><a href='/ar/payments/{_he(p.id)}' class='btn btn-xs btn-primary'>View</a></td>"
			f"</tr>"
			for p in payments
		)
		html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>AR Payments</title>
<link rel="stylesheet" href="https://maxcdn.bootstrapcdn.com/bootstrap/3.3.7/css/bootstrap.min.css">
</head><body style="padding:24px">
<h3>AR Payments <small>({len(payments)})</small></h3>
<table class="table table-bordered table-hover table-condensed">
<thead><tr><th>Payment #</th><th>Date</th><th>Method</th><th>Amount</th>
<th>Status</th><th>Bank Ref</th><th></th></tr></thead>
<tbody>{rows}</tbody></table></body></html>"""
		return make_response(html, 200)

	@expose("/<string:payment_id>")
	@has_access
	def detail(self, payment_id: str):
		session = _get_session()
		from pgappforge.plugins.erp.finance.ar.models import ARPayment, ARAllocation
		p = session.get(ARPayment, payment_id)
		if p is None:
			abort(404)
		allocs = session.execute(
			sa.select(ARAllocation).where(ARAllocation.payment_id == payment_id)
		).scalars().all()
		return jsonify({
			"id": p.id,
			"payment_number": p.payment_number,
			"customer_id": p.customer_id,
			"payment_date": p.payment_date.isoformat() if p.payment_date else None,
			"payment_method": p.payment_method,
			"currency_code": p.currency_code,
			"amount_cents": p.amount_cents,
			"exchange_rate": str(p.exchange_rate) if p.exchange_rate is not None else None,
			"bank_reference": p.bank_reference,
			"bank_account_iban": p.bank_account_iban,
			"bank_bic": p.bank_bic,
			"remittance_info": p.remittance_info,
			"deposited_date": p.deposited_date.isoformat() if p.deposited_date else None,
			"status": p.status,
			"allocations": [
				{
					"id": a.id,
					"invoice_id": a.invoice_id,
					"allocation_date": a.allocation_date.isoformat() if a.allocation_date else None,
					"allocated_cents": a.allocated_cents,
					"discount_taken_cents": a.discount_taken_cents,
				}
				for a in allocs
			],
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		session = _get_session()
		from pgappforge.plugins.erp.finance.ar.models import ARPayment
		from pgappforge.plugins.erp.finance.ar.events import PaymentReceivedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event
		data = request.get_json(silent=True) or {}
		required = ("tenant_id", "customer_id", "payment_number", "payment_date", "amount_cents")
		missing = [f for f in required if data.get(f) is None]
		if missing:
			return jsonify({"ok": False, "error": f"Missing: {missing}"}), 400

		p = ARPayment(
			tenant_id=data["tenant_id"],
			customer_id=data["customer_id"],
			payment_number=data["payment_number"],
			payment_date=date.fromisoformat(data["payment_date"]),
			payment_method=(data.get("payment_method") or "WIRE").upper(),
			currency_code=(data.get("currency_code") or "USD").upper(),
			amount_cents=int(data["amount_cents"]),
			exchange_rate=data.get("exchange_rate", 1),
			bank_reference=data.get("bank_reference"),
			bank_account_iban=data.get("bank_account_iban"),
			bank_bic=data.get("bank_bic"),
			remittance_info=data.get("remittance_info"),
			deposited_date=date.fromisoformat(data["deposited_date"]) if data.get("deposited_date") else None,
			status="UNALLOCATED",
		)
		session.add(p)
		session.flush()
		emit_event(
			PaymentReceivedEvent(
				aggregate_id=p.id, aggregate_type="ARPayment", tenant_id=p.tenant_id,
				payment_id=p.id, payment_number=p.payment_number,
				customer_id=p.customer_id, amount_cents=p.amount_cents,
				currency_code=p.currency_code, payment_method=p.payment_method,
				payment_date=p.payment_date.isoformat(),
			),
			session,
		)
		session.commit()
		return jsonify({"ok": True, "id": p.id}), 201

	@expose("/<string:payment_id>/allocate", methods=["POST"])
	@has_access
	def allocate(self, payment_id: str):
		session = _get_session()
		from pgappforge.plugins.erp.finance.ar.services import ARService, ARServiceError
		data = request.get_json(silent=True) or {}
		allocations = data.get("allocations", [])
		if not allocations:
			return jsonify({"ok": False, "error": "allocations list is required"}), 400
		svc = ARService()
		try:
			p = svc.apply_payment(payment_id, allocations, session)
			session.commit()
			return jsonify({"ok": True, "status": p.status})
		except ARServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 422

	@expose("/<string:payment_id>/return", methods=["POST"])
	@has_access
	def mark_returned(self, payment_id: str):
		session = _get_session()
		from pgappforge.plugins.erp.finance.ar.models import ARPayment
		p = session.get(ARPayment, payment_id)
		if p is None:
			abort(404)
		if p.status == "ALLOCATED":
			return jsonify({"ok": False, "error": "Cannot return a fully allocated payment"}), 400
		p.status = "RETURNED"
		p.updated_at = datetime.now(timezone.utc)
		session.commit()
		return jsonify({"ok": True, "status": "RETURNED"})


# ---------------------------------------------------------------------------
# ARCreditNoteView
# ---------------------------------------------------------------------------

class ARCreditNoteView(BaseERPView):
	"""AR Credit Note CRUD + application.

	GET  /ar/credit-notes/             — list (JSON)
	GET  /ar/credit-notes/<id>         — detail (JSON)
	POST /ar/credit-notes/             — create credit note (JSON)
	POST /ar/credit-notes/<id>/apply   — apply to invoice (JSON)
	"""

	route_base = "/ar/credit-notes"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		session = _get_session()
		from pgappforge.plugins.erp.finance.ar.models import ARCreditNote
		tenant_id = request.args.get("tenant_id")
		q = sa.select(ARCreditNote).order_by(sa.desc(ARCreditNote.issue_date)).limit(500)
		if tenant_id:
			q = q.where(ARCreditNote.tenant_id == tenant_id)
		cns = session.execute(q).scalars().all()
		return jsonify({
			"credit_notes": [
				{
					"id": cn.id,
					"credit_note_number": cn.credit_note_number,
					"customer_id": cn.customer_id,
					"issue_date": cn.issue_date.isoformat() if cn.issue_date else None,
					"total_cents": cn.total_cents,
					"applied_cents": cn.applied_cents,
					"status": cn.status,
					"reason": cn.reason,
					"currency_code": cn.currency_code,
				}
				for cn in cns
			]
		})

	@expose("/<string:cn_id>")
	@has_access
	def detail(self, cn_id: str):
		session = _get_session()
		from pgappforge.plugins.erp.finance.ar.models import ARCreditNote
		cn = session.get(ARCreditNote, cn_id)
		if cn is None:
			abort(404)
		return jsonify({
			"id": cn.id,
			"credit_note_number": cn.credit_note_number,
			"customer_id": cn.customer_id,
			"original_invoice_id": cn.original_invoice_id,
			"issue_date": cn.issue_date.isoformat() if cn.issue_date else None,
			"reason": cn.reason,
			"currency_code": cn.currency_code,
			"total_cents": cn.total_cents,
			"applied_cents": cn.applied_cents,
			"status": cn.status,
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		session = _get_session()
		from pgappforge.plugins.erp.finance.ar.services import ARService, ARServiceError
		data = request.get_json(silent=True) or {}
		svc = ARService()
		try:
			cn = svc.create_credit_note(data, session)
			session.commit()
			return jsonify({"ok": True, "id": cn.id}), 201
		except ARServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 422

	@expose("/<string:cn_id>/apply", methods=["POST"])
	@has_access
	def apply(self, cn_id: str):
		session = _get_session()
		from pgappforge.plugins.erp.finance.ar.services import ARService, ARServiceError
		data = request.get_json(silent=True) or {}
		invoice_id = data.get("invoice_id")
		amount_cents = data.get("amount_cents")
		if not invoice_id or amount_cents is None:
			return jsonify({"ok": False, "error": "invoice_id and amount_cents required"}), 400
		svc = ARService()
		try:
			inv = svc.apply_credit_note(cn_id, invoice_id, int(amount_cents), session)
			session.commit()
			return jsonify({"ok": True, "invoice_status": inv.status, "balance_due_cents": inv.balance_due_cents})
		except ARServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 422


# ---------------------------------------------------------------------------
# ARDunningView
# ---------------------------------------------------------------------------

class ARDunningView(BaseERPView):
	"""Dunning run management.

	GET  /ar/dunning/runs               — list runs (JSON)
	POST /ar/dunning/runs               — trigger a dunning run (JSON)
	GET  /ar/dunning/runs/<id>/events   — events for a run (JSON)
	POST /ar/dunning/runs/<id>/update-overdue — mark overdue invoices
	"""

	route_base = "/ar/dunning"
	default_view = "list_runs"

	@expose("/runs")
	@has_access
	def list_runs(self):
		session = _get_session()
		from pgappforge.plugins.erp.finance.ar.models import ARDunningRun
		tenant_id = request.args.get("tenant_id")
		q = sa.select(ARDunningRun).order_by(sa.desc(ARDunningRun.run_date)).limit(100)
		if tenant_id:
			q = q.where(ARDunningRun.tenant_id == tenant_id)
		runs = session.execute(q).scalars().all()
		return jsonify({
			"runs": [
				{
					"id": r.id,
					"run_date": r.run_date.isoformat() if r.run_date else None,
					"dunning_level": r.dunning_level,
					"batch_size": r.batch_size,
					"emails_sent": r.emails_sent,
					"status": r.status,
				}
				for r in runs
			]
		})

	@expose("/runs", methods=["POST"])
	@has_access
	def trigger_run(self):
		session = _get_session()
		from pgappforge.plugins.erp.finance.ar.services import ARService, ARServiceError
		data = request.get_json(silent=True) or {}
		tenant_id = data.get("tenant_id")
		dunning_level = data.get("dunning_level", 1)
		as_of_date_str = data.get("as_of_date")
		if not tenant_id:
			return jsonify({"ok": False, "error": "tenant_id required"}), 400
		as_of_date = date.fromisoformat(as_of_date_str) if as_of_date_str else date.today()
		svc = ARService()
		try:
			run = svc.run_dunning(int(dunning_level), tenant_id, session, as_of_date=as_of_date)
			session.commit()
			return jsonify({
				"ok": True, "id": run.id, "status": run.status,
				"batch_size": run.batch_size, "emails_sent": run.emails_sent,
			}), 201
		except ARServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 422

	@expose("/runs/<string:run_id>/events")
	@has_access
	def run_events(self, run_id: str):
		session = _get_session()
		from pgappforge.plugins.erp.finance.ar.models import ARDunningEvent
		events = session.execute(
			sa.select(ARDunningEvent)
			.where(ARDunningEvent.dunning_run_id == run_id)
			.order_by(ARDunningEvent.created_at)
		).scalars().all()
		return jsonify({
			"events": [
				{
					"id": e.id,
					"customer_id": e.customer_id,
					"amount_overdue_cents": e.amount_overdue_cents,
					"method": e.method,
					"sent_at": e.sent_at.isoformat() if e.sent_at else None,
					"outcome": e.outcome,
					"promise_to_pay_date": e.promise_to_pay_date.isoformat() if e.promise_to_pay_date else None,
					"invoice_ids": e.invoice_ids,
				}
				for e in events
			]
		})

	@expose("/update-overdue", methods=["POST"])
	@has_access
	def update_overdue(self):
		"""Mark ISSUED/PARTIAL invoices past due_date as OVERDUE."""
		session = _get_session()
		from pgappforge.plugins.erp.finance.ar.services import ARService
		data = request.get_json(silent=True) or {}
		tenant_id = data.get("tenant_id")
		as_of_date_str = data.get("as_of_date")
		if not tenant_id:
			return jsonify({"ok": False, "error": "tenant_id required"}), 400
		as_of_date = date.fromisoformat(as_of_date_str) if as_of_date_str else date.today()
		svc = ARService()
		n = svc.update_overdue_statuses(tenant_id, as_of_date, session)
		session.commit()
		return jsonify({"ok": True, "updated": n})


# ---------------------------------------------------------------------------
# ARReportView  — 3 canned reports
# ---------------------------------------------------------------------------

class ARReportView(BaseERPView):
	"""Standard AR reports.

	GET /ar/reports/aging                         — AR Aging Report (HTML)
	GET /ar/reports/statement/<customer_id>       — Customer Statement (HTML)
	GET /ar/reports/overdue                        — Overdue Invoices Report (HTML)
	POST /ar/reports/aging-snapshot               — Run aging computation (JSON)
	"""

	route_base = "/ar/reports"
	default_view = "aging"

	# ------------------------------------------------------------------
	# Report 1: AR Aging
	# ------------------------------------------------------------------

	@expose("/aging")
	@has_access
	def aging(self):
		"""AR Aging Report — latest snapshot per customer."""
		session = _get_session()
		from pgappforge.plugins.erp.finance.ar.models import ARAging, ARCustomer, ARInvoice
		tenant_id = request.args.get("tenant_id")

		# --- KPI summary ---
		today = date.today()
		total_customers = session.execute(
			sa.select(sa.func.count(ARCustomer.id)).where(ARCustomer.status == "ACTIVE")
		).scalar() or 0
		outstanding_cents = session.execute(
			sa.select(sa.func.coalesce(sa.func.sum(ARInvoice.balance_due_cents), 0)).where(
				ARInvoice.balance_due_cents > 0,
				ARInvoice.status.not_in(["CANCELLED", "PAID", "WRITTEN_OFF"]),
			)
		).scalar() or 0
		overdue_cents = session.execute(
			sa.select(sa.func.coalesce(sa.func.sum(ARInvoice.balance_due_cents), 0)).where(
				ARInvoice.balance_due_cents > 0,
				ARInvoice.due_date < today,
				ARInvoice.status.not_in(["CANCELLED", "PAID", "WRITTEN_OFF"]),
			)
		).scalar() or 0
		avg_payment_days_row = session.execute(
			sa.select(sa.func.avg(
				sa.func.extract("day", sa.func.age(ARInvoice.paid_date, ARInvoice.invoice_date))
			)).where(ARInvoice.paid_date.is_not(None))
		).scalar()
		avg_payment_days = int(avg_payment_days_row or 0)
		kpi_html = self.kpi_cards([
			{"label": "Active Customers", "value": total_customers,
			 "format": "integer", "color": "#1a56db", "icon": "fa-users"},
			{"label": "Outstanding (cents)", "value": outstanding_cents,
			 "format": "integer", "color": "#0e9f6e", "icon": "fa-file-invoice-dollar"},
			{"label": "Overdue (cents)", "value": overdue_cents,
			 "format": "integer", "color": "#e02424", "icon": "fa-exclamation-triangle"},
			{"label": "Avg Payment Days", "value": avg_payment_days,
			 "format": "integer", "color": "#7e3af2", "icon": "fa-clock"},
		])

		# Latest snapshot date
		max_date_sq = (
			sa.select(
				ARAging.customer_id,
				sa.func.max(ARAging.snapshot_date).label("max_date"),
			)
			.group_by(ARAging.customer_id)
			.subquery()
		)
		q = (
			sa.select(ARAging, ARCustomer.account_number)
			.join(
				max_date_sq,
				sa.and_(
					ARAging.customer_id == max_date_sq.c.customer_id,
					ARAging.snapshot_date == max_date_sq.c.max_date,
				),
			)
			.join(ARCustomer, ARAging.customer_id == ARCustomer.id)
			.order_by(sa.desc(ARAging.total_outstanding_cents))
		)
		if tenant_id:
			q = q.where(ARAging.tenant_id == tenant_id)

		rows_data = session.execute(q).all()

		def r(cents: int) -> str:
			return _cents_to_display(cents)

		total_current = sum(row.ARAging.current_cents for row in rows_data)
		total_1_30 = sum(row.ARAging.days_1_30 for row in rows_data)
		total_31_60 = sum(row.ARAging.days_31_60 for row in rows_data)
		total_61_90 = sum(row.ARAging.days_61_90 for row in rows_data)
		total_91_120 = sum(row.ARAging.days_91_120 for row in rows_data)
		total_over_120 = sum(row.ARAging.over_120 for row in rows_data)
		grand_total = sum(row.ARAging.total_outstanding_cents for row in rows_data)

		table_rows = "".join(
			f"<tr>"
			f"<td>{_he(row.account_number)}</td>"
			f"<td class='text-right'>{r(row.ARAging.current_cents)}</td>"
			f"<td class='text-right'>{r(row.ARAging.days_1_30)}</td>"
			f"<td class='text-right'>{r(row.ARAging.days_31_60)}</td>"
			f"<td class='text-right'>{r(row.ARAging.days_61_90)}</td>"
			f"<td class='text-right'>{r(row.ARAging.days_91_120)}</td>"
			f"<td class='text-right'>{r(row.ARAging.over_120)}</td>"
			f"<td class='text-right'><strong>{r(row.ARAging.total_outstanding_cents)}</strong></td>"
			f"</tr>"
			for row in rows_data
		)
		totals_row = (
			f"<tr class='active'><td><strong>TOTAL</strong></td>"
			f"<td class='text-right'><strong>{r(total_current)}</strong></td>"
			f"<td class='text-right'><strong>{r(total_1_30)}</strong></td>"
			f"<td class='text-right'><strong>{r(total_31_60)}</strong></td>"
			f"<td class='text-right'><strong>{r(total_61_90)}</strong></td>"
			f"<td class='text-right'><strong>{r(total_91_120)}</strong></td>"
			f"<td class='text-right'><strong>{r(total_over_120)}</strong></td>"
			f"<td class='text-right'><strong>{r(grand_total)}</strong></td>"
			f"</tr>"
		)
		html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>AR Aging Report</title>
<link rel="stylesheet" href="https://maxcdn.bootstrapcdn.com/bootstrap/3.3.7/css/bootstrap.min.css">
<style>body{{padding:24px}} @media print{{.noprint{{display:none}}}}</style>
</head><body>
{kpi_html}
<div class="noprint" style="margin-bottom:12px">
  <h3>AR Aging Report</h3>
  <button onclick="window.print()" class="btn btn-xs btn-primary">Print / PDF</button>
</div>
<table class="table table-bordered table-condensed table-hover" style="font-size:0.85em">
<thead><tr>
  <th>Customer</th><th class="text-right">Current</th>
  <th class="text-right">1–30 days</th><th class="text-right">31–60 days</th>
  <th class="text-right">61–90 days</th><th class="text-right">91–120 days</th>
  <th class="text-right">&gt;120 days</th><th class="text-right">Total</th>
</tr></thead>
<tbody>{table_rows}{totals_row}</tbody></table>
<p style="color:#888;font-size:0.75em">
  Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} — {len(rows_data)} customers
</p></body></html>"""
		return make_response(html, 200)

	# ------------------------------------------------------------------
	# Aging snapshot trigger
	# ------------------------------------------------------------------

	@expose("/aging-snapshot", methods=["POST"])
	@has_access
	def aging_snapshot(self):
		session = _get_session()
		from pgappforge.plugins.erp.finance.ar.services import ARService
		data = request.get_json(silent=True) or {}
		tenant_id = data.get("tenant_id")
		as_of_date_str = data.get("as_of_date")
		if not tenant_id:
			return jsonify({"ok": False, "error": "tenant_id required"}), 400
		as_of_date = date.fromisoformat(as_of_date_str) if as_of_date_str else date.today()
		svc = ARService()
		snaps = svc.run_aging(as_of_date, tenant_id, session)
		session.commit()
		return jsonify({"ok": True, "snapshots_created": len(snaps), "as_of_date": as_of_date.isoformat()})

	# ------------------------------------------------------------------
	# Report 2: Customer Statement
	# ------------------------------------------------------------------

	@expose("/statement/<string:customer_id>")
	@has_access
	def statement(self, customer_id: str):
		"""Customer Statement Report — period-based."""
		session = _get_session()
		from pgappforge.plugins.erp.finance.ar.services import ARService, ARCustomerNotFoundError

		period_start_str = request.args.get("from")
		period_end_str = request.args.get("to")
		today = date.today()
		# Default: current month
		period_start = date.fromisoformat(period_start_str) if period_start_str else today.replace(day=1)
		period_end = date.fromisoformat(period_end_str) if period_end_str else today

		svc = ARService()
		try:
			stmt = svc.generate_statement(customer_id, period_start, period_end, session)
		except ARCustomerNotFoundError as exc:
			abort(404)

		cust = stmt["customer"]
		inv_rows = "".join(
			f"<tr>"
			f"<td>{_he(inv['invoice_date'] or '')}</td>"
			f"<td>{_he(inv['invoice_number'])}</td>"
			f"<td>{_he(inv['due_date'] or '')}</td>"
			f"<td>{_he(inv['status'])}</td>"
			f"<td class='text-right'>{_cents_to_display(inv['total_cents'], inv['currency_code'])}</td>"
			f"<td class='text-right'>{_cents_to_display(inv['paid_cents'], inv['currency_code'])}</td>"
			f"<td class='text-right'>{_cents_to_display(inv['balance_due_cents'], inv['currency_code'])}</td>"
			f"</tr>"
			for inv in stmt["invoices"]
		)
		pay_rows = "".join(
			f"<tr>"
			f"<td>{_he(p['payment_date'] or '')}</td>"
			f"<td>{_he(p['payment_number'])}</td>"
			f"<td>{_he(p['payment_method'])}</td>"
			f"<td class='text-right'>{_cents_to_display(p['amount_cents'], p['currency_code'])}</td>"
			f"<td>{_he(p['status'])}</td>"
			f"</tr>"
			for p in stmt["payments"]
		)

		html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>Customer Statement — {_he(cust['account_number'])}</title>
<link rel="stylesheet" href="https://maxcdn.bootstrapcdn.com/bootstrap/3.3.7/css/bootstrap.min.css">
<style>body{{padding:24px}} @media print{{.noprint{{display:none}}}}</style>
</head><body>
<div style="display:flex;justify-content:space-between;margin-bottom:16px">
  <div>
    <h3>Account Statement</h3>
    <p>Account: <strong>{_he(cust['account_number'])}</strong><br>
    Period: {_he(stmt['period_start'])} to {_he(stmt['period_end'])}<br>
    Terms: Net {_he(cust['payment_terms_days'])} days</p>
  </div>
  <div class="text-right">
    <button class="btn btn-sm btn-primary noprint" onclick="window.print()">Print</button><br>
    <p>Opening balance: <strong>{_cents_to_display(stmt['opening_balance_cents'])}</strong><br>
    Closing balance: <strong>{_cents_to_display(stmt['closing_balance_cents'])}</strong></p>
  </div>
</div>
<h5>Invoices</h5>
<table class="table table-condensed table-bordered" style="font-size:0.85em">
<thead><tr><th>Date</th><th>Invoice #</th><th>Due</th><th>Status</th>
<th class="text-right">Total</th><th class="text-right">Paid</th>
<th class="text-right">Balance</th></tr></thead>
<tbody>{inv_rows or '<tr><td colspan="7" class="text-center text-muted">No invoices in period</td></tr>'}</tbody>
</table>
<h5>Payments Received</h5>
<table class="table table-condensed table-bordered" style="font-size:0.85em">
<thead><tr><th>Date</th><th>Payment #</th><th>Method</th>
<th class="text-right">Amount</th><th>Status</th></tr></thead>
<tbody>{pay_rows or '<tr><td colspan="5" class="text-center text-muted">No payments in period</td></tr>'}</tbody>
</table>
<p style="color:#888;font-size:0.75em">
  Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}
</p></body></html>"""
		return make_response(html, 200)

	# ------------------------------------------------------------------
	# Report 3: Overdue Invoices
	# ------------------------------------------------------------------

	@expose("/overdue")
	@has_access
	def overdue(self):
		"""Overdue Invoices Report — all invoices past due date with balance."""
		session = _get_session()
		from pgappforge.plugins.erp.finance.ar.models import ARInvoice, ARCustomer
		tenant_id = request.args.get("tenant_id")
		today = date.today()

		q = (
			sa.select(ARInvoice, ARCustomer.account_number)
			.join(ARCustomer, ARInvoice.customer_id == ARCustomer.id)
			.where(ARInvoice.balance_due_cents > 0)
			.where(ARInvoice.due_date < today)
			.where(ARInvoice.status.not_in(["CANCELLED", "PAID", "WRITTEN_OFF"]))
			.order_by(ARInvoice.due_date, ARCustomer.account_number)
		)
		if tenant_id:
			q = q.where(ARInvoice.tenant_id == tenant_id)

		rows_data = session.execute(q).all()

		table_rows = "".join(
			f"<tr>"
			f"<td>{_he(row.account_number)}</td>"
			f"<td>{_he(row.ARInvoice.invoice_number)}</td>"
			f"<td>{_he(row.ARInvoice.invoice_date)}</td>"
			f"<td>{_he(row.ARInvoice.due_date)}</td>"
			f"<td>{(today - row.ARInvoice.due_date).days}</td>"
			f"<td>{_he(row.ARInvoice.status)}</td>"
			f"<td class='text-right'>{_cents_to_display(row.ARInvoice.total_cents, row.ARInvoice.currency_code)}</td>"
			f"<td class='text-right'><strong>{_cents_to_display(row.ARInvoice.balance_due_cents, row.ARInvoice.currency_code)}</strong></td>"
			f"<td>{row.ARInvoice.dunning_level}</td>"
			f"</tr>"
			for row in rows_data
		)
		grand_total_overdue = sum(row.ARInvoice.balance_due_cents for row in rows_data)

		html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>Overdue Invoices</title>
<link rel="stylesheet" href="https://maxcdn.bootstrapcdn.com/bootstrap/3.3.7/css/bootstrap.min.css">
<style>body{{padding:24px}} @media print{{.noprint{{display:none}}}}</style>
</head><body>
<div class="noprint" style="margin-bottom:12px">
  <h3>Overdue Invoices Report <small>as of {today.isoformat()}</small></h3>
  <button onclick="window.print()" class="btn btn-xs btn-primary">Print / PDF</button>
</div>
<table class="table table-bordered table-condensed table-hover" style="font-size:0.85em">
<thead><tr>
  <th>Customer</th><th>Invoice #</th><th>Invoice Date</th><th>Due Date</th>
  <th>Days Late</th><th>Status</th><th class="text-right">Total</th>
  <th class="text-right">Balance Due</th><th>Dunning</th>
</tr></thead>
<tbody>{table_rows}</tbody>
<tfoot><tr class="active">
  <td colspan="7"><strong>Grand Total Overdue</strong></td>
  <td class="text-right"><strong>{_cents_to_display(grand_total_overdue)}</strong></td>
  <td></td>
</tr></tfoot>
</table>
<p style="color:#888;font-size:0.75em">
  {len(rows_data)} overdue invoices — Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}
</p></body></html>"""
		return make_response(html, 200)


__all__ = [
	"ARCustomerView",
	"ARInvoiceView",
	"ARPaymentView",
	"ARCreditNoteView",
	"ARDunningView",
	"ARReportView",
]
