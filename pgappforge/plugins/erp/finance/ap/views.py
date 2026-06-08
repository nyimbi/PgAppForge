"""
pgappforge/plugins/erp/finance/ap/views.py

Flask views for the Accounts Payable plugin.

Registered views:
  APSupplierView          — CRUD + approve/block actions
  APPurchaseOrderView     — CRUD + approve/send/close actions
  APGoodsReceiptView      — CRUD + post GRN action
  APInvoiceView           — CRUD + match/approve/dispute actions
  APPaymentRunView        — CRUD + approve/transmit actions
  APReportView            — 3 canned reports:
                            * AP Aging
                            * Supplier Payment History
                            * Invoice Matching Status

All mutating endpoints: POST/PUT JSON → JSON.
List/detail: HTML for FAB list rendering; JSON available via ?format=json.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import sqlalchemy as sa
from flask import abort, jsonify, make_response, request

from pgappforge import expose
from pgappforge.plugins.erp.base_view import BaseERPView
from pgappforge.security.decorators import has_access

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared helpers
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


def _page_html(title: str, body: str) -> str:
	return (
		f'<!DOCTYPE html><html><head><meta charset="utf-8"><title>{title}</title>'
		'<link rel="stylesheet" href="https://maxcdn.bootstrapcdn.com/bootstrap/3.3.7/css/bootstrap.min.css">'
		'<style>body{padding:24px} @media print{.noprint{display:none}}</style>'
		f'</head><body>{body}</body></html>'
	)


# ---------------------------------------------------------------------------
# APSupplierView
# ---------------------------------------------------------------------------

class APSupplierView(BaseERPView):
	"""Supplier master CRUD.

	GET  /ap/suppliers/              — list (HTML or JSON)
	GET  /ap/suppliers/<id>          — detail (JSON)
	POST /ap/suppliers/              — create (JSON)
	PUT  /ap/suppliers/<id>          — update (JSON)
	POST /ap/suppliers/<id>/approve  — set approved_supplier=True
	POST /ap/suppliers/<id>/block    — set status=blocked
	"""

	route_base = "/ap/suppliers"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.finance.ap.models import APSupplier
		session = _get_session()
		q = sa.select(APSupplier).order_by(APSupplier.name)
		tenant_id = request.args.get("tenant_id")
		if tenant_id:
			q = q.where(APSupplier.tenant_id == tenant_id)
		status_filter = request.args.get("status")
		if status_filter:
			q = q.where(APSupplier.status == status_filter)
		suppliers = session.execute(q.limit(500)).scalars().all()

		if request.args.get("format") == "json":
			return jsonify({"suppliers": [
				{
					"id": s.id, "account_number": s.account_number,
					"name": s.name, "status": s.status,
					"payment_terms_days": s.payment_terms_days,
					"currency_code": s.currency_code,
					"approved_supplier": s.approved_supplier,
				}
				for s in suppliers
			]})

		rows = "".join(
			f"<tr>"
			f"<td>{_he(s.account_number)}</td>"
			f"<td>{_he(s.name)}</td>"
			f"<td>{_he(s.currency_code)}</td>"
			f"<td>{_he(s.payment_terms_days)}</td>"
			f"<td>{'<span class=\"label label-success\">Yes</span>' if s.approved_supplier else '<span class=\"label label-danger\">No</span>'}</td>"
			f"<td><span class=\"label label-{'success' if s.status=='active' else 'warning'}\">{_he(s.status)}</span></td>"
			f"<td><a href='/ap/suppliers/{_he(s.id)}' class='btn btn-xs btn-primary'>View</a></td>"
			f"</tr>"
			for s in suppliers
		)
		body = (
			'<div class="noprint"><h3>Suppliers</h3>'
			'<a href="/ap/suppliers/?status=active" class="btn btn-xs btn-default">Active</a> '
			'<a href="/ap/suppliers/?status=blocked" class="btn btn-xs btn-danger">Blocked</a> '
			'<a href="/ap/suppliers/" class="btn btn-xs btn-default">All</a></div>'
			'<table class="table table-bordered table-condensed table-hover">'
			'<thead><tr><th>Account</th><th>Name</th><th>CCY</th><th>Terms (d)</th>'
			'<th>Approved</th><th>Status</th><th></th></tr></thead>'
			f'<tbody>{rows}</tbody></table>'
		)
		return make_response(_page_html("Suppliers", body), 200)

	@expose("/<string:supplier_id>")
	@has_access
	def detail(self, supplier_id: str):
		from pgappforge.plugins.erp.finance.ap.models import APSupplier
		session = _get_session()
		sup = session.get(APSupplier, supplier_id)
		if sup is None:
			abort(404)
		return jsonify({
			"id": sup.id, "tenant_id": sup.tenant_id,
			"party_id": sup.party_id, "account_number": sup.account_number,
			"name": sup.name, "supplier_type": sup.supplier_type,
			"status": sup.status, "currency_code": sup.currency_code,
			"payment_terms_days": sup.payment_terms_days,
			"payment_method": sup.payment_method,
			"bank_account_iban": sup.bank_account_iban,
			"bank_bic": sup.bank_bic, "bank_account_name": sup.bank_account_name,
			"tax_id": sup.tax_id, "vat_number": sup.vat_number,
			"w9_on_file": sup.w9_on_file, "reporting_1099": sup.reporting_1099,
			"approved_supplier": sup.approved_supplier,
			"gl_payable_account": sup.gl_payable_account,
			"credit_rating": sup.credit_rating,
			"dynamic_discounting_eligible": sup.dynamic_discounting_eligible,
			"early_payment_discount_pct": str(sup.early_payment_discount_pct),
			"early_payment_days": sup.early_payment_days,
			"contact_email": sup.contact_email,
			"created_at": sup.created_at.isoformat() if sup.created_at else None,
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		from pgappforge.plugins.erp.finance.ap.models import APSupplier
		session = _get_session()
		data = request.get_json(silent=True) or {}
		required = ("tenant_id", "account_number", "name")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"ok": False, "error": f"missing: {missing}"}), 400
		sup = APSupplier(
			tenant_id=data["tenant_id"],
			account_number=data["account_number"],
			name=data["name"],
			party_id=data.get("party_id"),
			supplier_type=data.get("supplier_type"),
			currency_code=data.get("currency_code", "USD"),
			payment_terms_days=int(data.get("payment_terms_days", 30)),
			payment_method=data.get("payment_method"),
			bank_account_iban=data.get("bank_account_iban"),
			bank_bic=data.get("bank_bic"),
			bank_account_name=data.get("bank_account_name"),
			tax_id=data.get("tax_id"),
			vat_number=data.get("vat_number"),
			w9_on_file=bool(data.get("w9_on_file", False)),
			reporting_1099=bool(data.get("reporting_1099", False)),
			gl_payable_account=data.get("gl_payable_account"),
			approved_supplier=bool(data.get("approved_supplier", True)),
			dynamic_discounting_eligible=bool(data.get("dynamic_discounting_eligible", False)),
			early_payment_discount_pct=data.get("early_payment_discount_pct", 0),
			early_payment_days=int(data.get("early_payment_days", 0)),
			contact_email=data.get("contact_email"),
			contact_phone=data.get("contact_phone"),
			address=data.get("address") or {},
		)
		session.add(sup)
		session.commit()
		return jsonify({"ok": True, "id": sup.id}), 201

	@expose("/<string:supplier_id>", methods=["PUT"])
	@has_access
	def update(self, supplier_id: str):
		from pgappforge.plugins.erp.finance.ap.models import APSupplier
		session = _get_session()
		sup = session.get(APSupplier, supplier_id)
		if sup is None:
			abort(404)
		data = request.get_json(silent=True) or {}
		updatable = [
			"name", "supplier_type", "currency_code", "payment_terms_days",
			"payment_method", "bank_account_iban", "bank_bic", "bank_account_name",
			"tax_id", "vat_number", "w9_on_file", "reporting_1099",
			"gl_payable_account", "approved_supplier", "credit_rating",
			"dynamic_discounting_eligible", "early_payment_discount_pct",
			"early_payment_days", "contact_email", "contact_phone", "address",
		]
		changed = [f for f in updatable if f in data]
		for f in changed:
			setattr(sup, f, data[f])
		sup.updated_at = datetime.now(timezone.utc)
		session.commit()
		return jsonify({"ok": True, "changed": changed})

	@expose("/<string:supplier_id>/approve", methods=["POST"])
	@has_access
	def approve(self, supplier_id: str):
		from pgappforge.plugins.erp.finance.ap.models import APSupplier
		from pgappforge.plugins.erp.finance.ap.events import SupplierApprovedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event
		session = _get_session()
		sup = session.get(APSupplier, supplier_id)
		if sup is None:
			abort(404)
		sup.approved_supplier = True
		sup.status = "active"
		sup.updated_at = datetime.now(timezone.utc)
		emit_event(
			SupplierApprovedEvent(
				aggregate_id=supplier_id,
				aggregate_type="APSupplier",
				tenant_id=sup.tenant_id,
				supplier_id=supplier_id,
				account_number=sup.account_number,
			),
			session,
		)
		session.commit()
		return jsonify({"ok": True, "approved_supplier": True})

	@expose("/<string:supplier_id>/block", methods=["POST"])
	@has_access
	def block(self, supplier_id: str):
		from pgappforge.plugins.erp.finance.ap.models import APSupplier
		session = _get_session()
		sup = session.get(APSupplier, supplier_id)
		if sup is None:
			abort(404)
		sup.approved_supplier = False
		sup.status = "blocked"
		sup.updated_at = datetime.now(timezone.utc)
		session.commit()
		return jsonify({"ok": True, "status": "blocked"})


# ---------------------------------------------------------------------------
# APPurchaseOrderView
# ---------------------------------------------------------------------------

class APPurchaseOrderView(BaseERPView):
	"""Purchase order CRUD + lifecycle actions.

	GET  /ap/purchase-orders/              — list
	GET  /ap/purchase-orders/<id>          — detail
	POST /ap/purchase-orders/              — create
	PUT  /ap/purchase-orders/<id>          — update (DRAFT only)
	POST /ap/purchase-orders/<id>/approve  — PENDING_APPROVAL → APPROVED
	POST /ap/purchase-orders/<id>/send     — APPROVED → SENT
	POST /ap/purchase-orders/<id>/cancel   — → CANCELLED
	"""

	route_base = "/ap/purchase-orders"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.finance.ap.models import APPurchaseOrder
		session = _get_session()
		q = sa.select(APPurchaseOrder).order_by(sa.desc(APPurchaseOrder.order_date))
		if request.args.get("tenant_id"):
			q = q.where(APPurchaseOrder.tenant_id == request.args["tenant_id"])
		if request.args.get("status"):
			q = q.where(APPurchaseOrder.status == request.args["status"])
		if request.args.get("supplier_id"):
			q = q.where(APPurchaseOrder.supplier_id == request.args["supplier_id"])
		orders = session.execute(q.limit(500)).scalars().all()

		if request.args.get("format") == "json":
			return jsonify({"purchase_orders": [
				{
					"id": po.id, "po_number": po.po_number,
					"supplier_id": po.supplier_id,
					"order_date": po.order_date.isoformat() if po.order_date else None,
					"total_cents": po.total_cents,
					"currency_code": po.currency_code,
					"status": po.status,
				}
				for po in orders
			]})

		rows = "".join(
			f"<tr>"
			f"<td>{_he(po.po_number)}</td>"
			f"<td>{_he(po.order_date)}</td>"
			f"<td>{_he(po.currency_code)} {po.total_cents / 100:,.2f}</td>"
			f"<td><span class='label label-info'>{_he(po.status)}</span></td>"
			f"<td><a href='/ap/purchase-orders/{_he(po.id)}' class='btn btn-xs btn-primary'>View</a></td>"
			f"</tr>"
			for po in orders
		)
		body = (
			'<h3>Purchase Orders</h3>'
			'<table class="table table-bordered table-condensed table-hover">'
			'<thead><tr><th>PO Number</th><th>Order Date</th><th>Total</th><th>Status</th><th></th></tr></thead>'
			f'<tbody>{rows}</tbody></table>'
		)
		return make_response(_page_html("Purchase Orders", body), 200)

	@expose("/<string:po_id>")
	@has_access
	def detail(self, po_id: str):
		from pgappforge.plugins.erp.finance.ap.models import APPurchaseOrder
		session = _get_session()
		po = session.get(APPurchaseOrder, po_id)
		if po is None:
			abort(404)
		return jsonify({
			"id": po.id, "po_number": po.po_number,
			"supplier_id": po.supplier_id,
			"order_date": po.order_date.isoformat() if po.order_date else None,
			"delivery_date": po.delivery_date.isoformat() if po.delivery_date else None,
			"currency_code": po.currency_code,
			"subtotal_cents": po.subtotal_cents,
			"tax_cents": po.tax_cents, "total_cents": po.total_cents,
			"received_cents": po.received_cents, "invoiced_cents": po.invoiced_cents,
			"paid_cents": po.paid_cents, "status": po.status,
			"lines": [
				{
					"id": l.id, "line_number": l.line_number,
					"description": l.description, "quantity": str(l.quantity),
					"uom": l.uom, "unit_cost_cents": l.unit_cost_cents,
					"line_amount_cents": l.line_amount_cents,
					"quantity_received": str(l.quantity_received),
					"quantity_invoiced": str(l.quantity_invoiced),
					"status": l.status,
				}
				for l in po.lines
			],
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		from pgappforge.plugins.erp.finance.ap.models import APPurchaseOrder, APPOLine
		from datetime import date as date_type
		session = _get_session()
		data = request.get_json(silent=True) or {}
		required = ("tenant_id", "supplier_id", "order_date", "lines")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"ok": False, "error": f"missing: {missing}"}), 400

		order_date = date_type.fromisoformat(data["order_date"])
		delivery_date = date_type.fromisoformat(data["delivery_date"]) if data.get("delivery_date") else None

		lines_data = data["lines"]
		if not lines_data:
			return jsonify({"ok": False, "error": "at least one line required"}), 400

		subtotal = 0
		tax = int(data.get("tax_cents", 0))
		po_lines = []
		for i, ld in enumerate(lines_data, start=1):
			qty = __import__("decimal").Decimal(str(ld["quantity"]))
			uc = int(ld["unit_cost_cents"])
			from decimal import Decimal as D, ROUND_HALF_UP as RHU
			la = int((D(str(qty)) * D(uc)).to_integral_value(rounding=RHU))
			subtotal += la
			po_lines.append((i, ld, la))

		po = APPurchaseOrder(
			tenant_id=data["tenant_id"],
			po_number=data.get("po_number") or f"PO-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
			supplier_id=data["supplier_id"],
			requisitioner_id=data.get("requisitioner_id"),
			order_date=order_date,
			delivery_date=delivery_date,
			currency_code=data.get("currency_code", "USD"),
			subtotal_cents=subtotal,
			tax_cents=tax,
			total_cents=subtotal + tax,
			status="DRAFT",
			notes=data.get("notes"),
		)
		session.add(po)
		session.flush()

		for i, ld, la in po_lines:
			session.add(APPOLine(
				tenant_id=data["tenant_id"],
				po_id=po.id,
				line_number=i,
				description=ld["description"],
				quantity=ld["quantity"],
				uom=ld.get("uom"),
				unit_cost_cents=int(ld["unit_cost_cents"]),
				line_amount_cents=la,
				gl_expense_account=ld.get("gl_expense_account"),
				cost_center=ld.get("cost_center"),
				project_code=ld.get("project_code"),
			))

		session.commit()
		return jsonify({"ok": True, "id": po.id, "total_cents": po.total_cents}), 201

	@expose("/<string:po_id>/approve", methods=["POST"])
	@has_access
	def approve(self, po_id: str):
		from pgappforge.plugins.erp.finance.ap.models import APPurchaseOrder
		session = _get_session()
		po = session.get(APPurchaseOrder, po_id)
		if po is None:
			abort(404)
		if po.status not in ("DRAFT", "PENDING_APPROVAL"):
			return jsonify({"ok": False, "error": f"Cannot approve PO in status {po.status!r}"}), 400
		data = request.get_json(silent=True) or {}
		po.approved_by = data.get("approved_by")
		po.approval_date = datetime.now(timezone.utc)
		po.status = "APPROVED"
		po.updated_at = datetime.now(timezone.utc)
		session.commit()
		return jsonify({"ok": True, "status": "APPROVED"})

	@expose("/<string:po_id>/send", methods=["POST"])
	@has_access
	def send(self, po_id: str):
		from pgappforge.plugins.erp.finance.ap.models import APPurchaseOrder
		session = _get_session()
		po = session.get(APPurchaseOrder, po_id)
		if po is None:
			abort(404)
		if po.status != "APPROVED":
			return jsonify({"ok": False, "error": "PO must be APPROVED before sending"}), 400
		po.status = "SENT"
		po.updated_at = datetime.now(timezone.utc)
		session.commit()
		return jsonify({"ok": True, "status": "SENT"})

	@expose("/<string:po_id>/cancel", methods=["POST"])
	@has_access
	def cancel(self, po_id: str):
		from pgappforge.plugins.erp.finance.ap.models import APPurchaseOrder
		session = _get_session()
		po = session.get(APPurchaseOrder, po_id)
		if po is None:
			abort(404)
		if po.status in ("RECEIVED", "CLOSED", "PAID"):
			return jsonify({"ok": False, "error": f"Cannot cancel PO in status {po.status!r}"}), 400
		po.status = "CANCELLED"
		po.updated_at = datetime.now(timezone.utc)
		session.commit()
		return jsonify({"ok": True, "status": "CANCELLED"})


# ---------------------------------------------------------------------------
# APGoodsReceiptView
# ---------------------------------------------------------------------------

class APGoodsReceiptView(BaseERPView):
	"""GRN CRUD + posting.

	GET  /ap/grn/              — list
	GET  /ap/grn/<id>          — detail
	POST /ap/grn/              — create GRN with lines
	POST /ap/grn/<id>/post     — post confirmed GRN (updates PO quantity)
	"""

	route_base = "/ap/grn"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.finance.ap.models import APGoodsReceipt
		session = _get_session()
		q = sa.select(APGoodsReceipt).order_by(sa.desc(APGoodsReceipt.received_date))
		if request.args.get("supplier_id"):
			q = q.where(APGoodsReceipt.supplier_id == request.args["supplier_id"])
		if request.args.get("status"):
			q = q.where(APGoodsReceipt.status == request.args["status"])
		grns = session.execute(q.limit(500)).scalars().all()
		return jsonify({"grns": [
			{
				"id": g.id, "grn_number": g.grn_number,
				"supplier_id": g.supplier_id,
				"received_date": g.received_date.isoformat() if g.received_date else None,
				"status": g.status,
			}
			for g in grns
		]})

	@expose("/<string:grn_id>")
	@has_access
	def detail(self, grn_id: str):
		from pgappforge.plugins.erp.finance.ap.models import APGoodsReceipt
		session = _get_session()
		grn = session.get(APGoodsReceipt, grn_id)
		if grn is None:
			abort(404)
		return jsonify({
			"id": grn.id, "grn_number": grn.grn_number,
			"po_id": grn.po_id, "supplier_id": grn.supplier_id,
			"received_date": grn.received_date.isoformat() if grn.received_date else None,
			"status": grn.status,
			"lines": [
				{
					"id": l.id, "po_line_id": l.po_line_id,
					"quantity_received": str(l.quantity_received),
					"quantity_accepted": str(l.quantity_accepted),
					"quantity_rejected": str(l.quantity_rejected),
					"rejection_reason": l.rejection_reason,
					"unit_cost_cents": l.unit_cost_cents,
				}
				for l in grn.lines
			],
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		from pgappforge.plugins.erp.finance.ap.models import APGoodsReceipt, APGRNLine
		from datetime import date as date_type
		session = _get_session()
		data = request.get_json(silent=True) or {}
		required = ("tenant_id", "supplier_id", "received_date", "lines")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"ok": False, "error": f"missing: {missing}"}), 400

		received_date = date_type.fromisoformat(data["received_date"])
		grn = APGoodsReceipt(
			tenant_id=data["tenant_id"],
			grn_number=data.get("grn_number") or f"GRN-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
			po_id=data.get("po_id"),
			supplier_id=data["supplier_id"],
			received_by=data.get("received_by"),
			received_date=received_date,
			warehouse_id=data.get("warehouse_id"),
			status="DRAFT",
			notes=data.get("notes"),
		)
		session.add(grn)
		session.flush()

		for ld in data["lines"]:
			qr = ld["quantity_received"]
			qa = ld.get("quantity_accepted", qr)
			qrej = ld.get("quantity_rejected", 0)
			session.add(APGRNLine(
				tenant_id=data["tenant_id"],
				grn_id=grn.id,
				po_line_id=ld.get("po_line_id"),
				description=ld.get("description"),
				quantity_received=qr,
				quantity_accepted=qa,
				quantity_rejected=qrej,
				rejection_reason=ld.get("rejection_reason"),
				unit_cost_cents=ld.get("unit_cost_cents"),
			))

		session.commit()
		return jsonify({"ok": True, "id": grn.id}), 201

	@expose("/<string:grn_id>/post", methods=["POST"])
	@has_access
	def post_grn(self, grn_id: str):
		from pgappforge.plugins.erp.finance.ap.services import APService, APServiceError
		session = _get_session()
		svc = APService()
		try:
			grn = svc.post_grn(grn_id, session)
			session.commit()
			return jsonify({"ok": True, "status": grn.status})
		except APServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 400


# ---------------------------------------------------------------------------
# APInvoiceView
# ---------------------------------------------------------------------------

class APInvoiceView(BaseERPView):
	"""Invoice CRUD + matching + approval.

	GET  /ap/invoices/                   — list
	GET  /ap/invoices/<id>               — detail
	POST /ap/invoices/                   — create
	POST /ap/invoices/<id>/match         — run match_invoice()
	POST /ap/invoices/<id>/approve       — record approval decision
	POST /ap/invoices/<id>/dispute       — set status=DISPUTED
	POST /ap/invoices/<id>/post-gl       — post to GL
	"""

	route_base = "/ap/invoices"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.finance.ap.models import APInvoice
		session = _get_session()
		q = sa.select(APInvoice).order_by(sa.desc(APInvoice.invoice_date))
		for field, col in (
			("tenant_id", APInvoice.tenant_id),
			("supplier_id", APInvoice.supplier_id),
			("status", APInvoice.status),
			("match_status", APInvoice.match_status),
		):
			val = request.args.get(field)
			if val:
				q = q.where(col == val)
		invoices = session.execute(q.limit(500)).scalars().all()

		if request.args.get("format") == "json":
			return jsonify({"invoices": [
				{
					"id": i.id,
					"invoice_number_supplier": i.invoice_number_supplier,
					"supplier_id": i.supplier_id,
					"invoice_date": i.invoice_date.isoformat() if i.invoice_date else None,
					"due_date": i.due_date.isoformat() if i.due_date else None,
					"total_cents": i.total_cents, "paid_cents": i.paid_cents,
					"match_status": i.match_status,
					"approval_status": i.approval_status,
					"status": i.status,
				}
				for i in invoices
			]})

		rows = "".join(
			f"<tr>"
			f"<td>{_he(i.invoice_number_supplier)}</td>"
			f"<td>{_he(i.invoice_date)}</td>"
			f"<td>{_he(i.due_date)}</td>"
			f"<td>{_he(i.currency_code)} {i.total_cents / 100:,.2f}</td>"
			f"<td>{_he(i.match_status)}</td>"
			f"<td>{_he(i.approval_status)}</td>"
			f"<td><span class='label label-{'success' if i.status=='PAID' else 'default'}'>{_he(i.status)}</span></td>"
			f"<td><a href='/ap/invoices/{_he(i.id)}' class='btn btn-xs btn-primary'>View</a></td>"
			f"</tr>"
			for i in invoices
		)
		body = (
			'<h3>AP Invoices</h3>'
			'<table class="table table-bordered table-condensed table-hover">'
			'<thead><tr><th>Inv #</th><th>Date</th><th>Due</th><th>Total</th>'
			'<th>Match</th><th>Approval</th><th>Status</th><th></th></tr></thead>'
			f'<tbody>{rows}</tbody></table>'
		)
		return make_response(_page_html("AP Invoices", body), 200)

	@expose("/<string:invoice_id>")
	@has_access
	def detail(self, invoice_id: str):
		from pgappforge.plugins.erp.finance.ap.models import APInvoice
		session = _get_session()
		inv = session.get(APInvoice, invoice_id)
		if inv is None:
			abort(404)
		return jsonify({
			"id": inv.id, "tenant_id": inv.tenant_id,
			"invoice_number_supplier": inv.invoice_number_supplier,
			"supplier_id": inv.supplier_id, "po_id": inv.po_id, "grn_id": inv.grn_id,
			"invoice_date": inv.invoice_date.isoformat() if inv.invoice_date else None,
			"due_date": inv.due_date.isoformat() if inv.due_date else None,
			"currency_code": inv.currency_code,
			"exchange_rate": str(inv.exchange_rate),
			"subtotal_cents": inv.subtotal_cents, "discount_cents": inv.discount_cents,
			"tax_cents": inv.tax_cents, "total_cents": inv.total_cents,
			"paid_cents": inv.paid_cents,
			"match_status": inv.match_status,
			"approval_status": inv.approval_status,
			"status": inv.status,
			"payment_run_id": inv.payment_run_id,
			"lines": [
				{
					"id": l.id, "line_number": l.line_number,
					"description": l.description,
					"quantity": str(l.quantity) if l.quantity else None,
					"unit_cost_cents": l.unit_cost_cents,
					"line_amount_cents": l.line_amount_cents,
					"tax_cents": l.tax_cents,
					"gl_expense_account": l.gl_expense_account,
					"cost_center": l.cost_center,
				}
				for l in inv.lines
			],
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		from pgappforge.plugins.erp.finance.ap.models import APInvoice, APInvoiceLine, APSupplier
		from datetime import date as date_type
		session = _get_session()
		data = request.get_json(silent=True) or {}
		required = ("tenant_id", "supplier_id", "invoice_number_supplier", "invoice_date", "lines")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"ok": False, "error": f"missing: {missing}"}), 400

		supplier = session.get(APSupplier, data["supplier_id"])
		if supplier is None:
			return jsonify({"ok": False, "error": "supplier not found"}), 404
		if not supplier.approved_supplier:
			return jsonify({"ok": False, "error": "supplier is not approved"}), 400

		invoice_date = date_type.fromisoformat(data["invoice_date"])
		from datetime import timedelta
		due_date = date_type.fromisoformat(data["due_date"]) if data.get("due_date") \
			else invoice_date + timedelta(days=supplier.payment_terms_days)

		from decimal import Decimal as D, ROUND_HALF_UP as RHU
		lines_data = data["lines"]
		subtotal = 0
		tax_total = 0
		inv_lines = []
		for i, ld in enumerate(lines_data, start=1):
			la = int(ld["line_amount_cents"])
			tc = int(ld.get("tax_cents", 0))
			subtotal += la
			tax_total += tc
			inv_lines.append((i, ld, la, tc))

		discount = int(data.get("discount_cents", 0))
		total = subtotal - discount + tax_total

		inv = APInvoice(
			tenant_id=data["tenant_id"],
			invoice_number_supplier=data["invoice_number_supplier"],
			supplier_id=data["supplier_id"],
			po_id=data.get("po_id"),
			grn_id=data.get("grn_id"),
			invoice_date=invoice_date,
			due_date=due_date,
			currency_code=data.get("currency_code", supplier.currency_code),
			exchange_rate=data.get("exchange_rate", 1),
			subtotal_cents=subtotal,
			discount_cents=discount,
			tax_cents=tax_total,
			total_cents=total,
			gl_payable_account=data.get("gl_payable_account") or supplier.gl_payable_account,
			status="RECEIVED",
		)
		session.add(inv)
		session.flush()

		for i, ld, la, tc in inv_lines:
			session.add(APInvoiceLine(
				tenant_id=data["tenant_id"],
				invoice_id=inv.id,
				line_number=i,
				po_line_id=ld.get("po_line_id"),
				grn_line_id=ld.get("grn_line_id"),
				description=ld["description"],
				quantity=ld.get("quantity"),
				uom=ld.get("uom"),
				unit_cost_cents=ld.get("unit_cost_cents"),
				line_amount_cents=la,
				tax_category=ld.get("tax_category"),
				tax_rate=ld.get("tax_rate", 0),
				tax_cents=tc,
				gl_expense_account=ld.get("gl_expense_account"),
				cost_center=ld.get("cost_center"),
				project_code=ld.get("project_code"),
			))

		# Update PO invoiced_cents if linked
		if inv.po_id and inv.purchase_order:
			inv.purchase_order.invoiced_cents += total

		session.commit()
		return jsonify({"ok": True, "id": inv.id, "total_cents": total}), 201

	@expose("/<string:invoice_id>/match", methods=["POST"])
	@has_access
	def match(self, invoice_id: str):
		from pgappforge.plugins.erp.finance.ap.services import APService, APServiceError
		session = _get_session()
		svc = APService()
		try:
			inv = svc.match_invoice(invoice_id, session)
			session.commit()
			return jsonify({
				"ok": True,
				"match_status": inv.match_status,
				"exceptions": inv.metadata_.get("match_exceptions", []),
			})
		except APServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 400

	@expose("/<string:invoice_id>/approve", methods=["POST"])
	@has_access
	def approve(self, invoice_id: str):
		from pgappforge.plugins.erp.finance.ap.services import APService, APServiceError
		session = _get_session()
		data = request.get_json(silent=True) or {}
		approver_id = data.get("approver_id")
		if not approver_id:
			return jsonify({"ok": False, "error": "approver_id required"}), 400
		svc = APService()
		try:
			inv = svc.approve_invoice(invoice_id, approver_id, session, comments=data.get("comments", ""))
			session.commit()
			return jsonify({"ok": True, "approval_status": inv.approval_status, "status": inv.status})
		except APServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 400

	@expose("/<string:invoice_id>/dispute", methods=["POST"])
	@has_access
	def dispute(self, invoice_id: str):
		from pgappforge.plugins.erp.finance.ap.models import APInvoice
		from pgappforge.plugins.erp.finance.ap.events import InvoiceDisputedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event
		session = _get_session()
		inv = session.get(APInvoice, invoice_id)
		if inv is None:
			abort(404)
		data = request.get_json(silent=True) or {}
		reason = data.get("reason", "")
		inv.status = "DISPUTED"
		inv.updated_at = datetime.now(timezone.utc)
		emit_event(
			InvoiceDisputedEvent(
				aggregate_id=invoice_id,
				aggregate_type="APInvoice",
				tenant_id=inv.tenant_id,
				invoice_id=invoice_id,
				supplier_id=inv.supplier_id,
				reason=reason,
			),
			session,
		)
		session.commit()
		return jsonify({"ok": True, "status": "DISPUTED"})

	@expose("/<string:invoice_id>/post-gl", methods=["POST"])
	@has_access
	def post_gl(self, invoice_id: str):
		from pgappforge.plugins.erp.finance.ap.services import APService, APServiceError
		session = _get_session()
		svc = APService()
		try:
			journal = svc.post_to_gl(invoice_id, session)
			session.commit()
			return jsonify({"ok": True, "journal": journal})
		except APServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 400


# ---------------------------------------------------------------------------
# APPaymentRunView
# ---------------------------------------------------------------------------

class APPaymentRunView(BaseERPView):
	"""Payment run management.

	GET  /ap/payment-runs/               — list
	GET  /ap/payment-runs/<id>           — detail + ISO 20022 XML
	POST /ap/payment-runs/               — create run (calls APService.create_payment_run)
	POST /ap/payment-runs/<id>/approve   — DRAFT → APPROVED
	POST /ap/payment-runs/<id>/transmit  — APPROVED → TRANSMITTED
	"""

	route_base = "/ap/payment-runs"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.finance.ap.models import APPaymentRun
		session = _get_session()
		q = sa.select(APPaymentRun).order_by(sa.desc(APPaymentRun.run_date))
		runs = session.execute(q.limit(200)).scalars().all()
		return jsonify({"payment_runs": [
			{
				"id": r.id, "run_number": r.run_number,
				"run_date": r.run_date.isoformat() if r.run_date else None,
				"value_date": r.value_date.isoformat() if r.value_date else None,
				"total_payments": r.total_payments,
				"total_amount_cents": r.total_amount_cents,
				"currency_code": r.currency_code,
				"status": r.status,
			}
			for r in runs
		]})

	@expose("/<string:run_id>")
	@has_access
	def detail(self, run_id: str):
		from pgappforge.plugins.erp.finance.ap.models import APPaymentRun
		session = _get_session()
		run = session.get(APPaymentRun, run_id)
		if run is None:
			abort(404)
		include_xml = request.args.get("xml") == "1"
		result = {
			"id": run.id, "run_number": run.run_number,
			"run_date": run.run_date.isoformat() if run.run_date else None,
			"value_date": run.value_date.isoformat() if run.value_date else None,
			"bank_account": run.bank_account, "bic": run.bic,
			"currency_code": run.currency_code,
			"total_payments": run.total_payments,
			"total_amount_cents": run.total_amount_cents,
			"payment_file_ref": run.payment_file_ref,
			"status": run.status,
			"payments": [
				{
					"id": p.id, "supplier_id": p.supplier_id,
					"amount_cents": p.amount_cents, "currency_code": p.currency_code,
					"uetr": p.uetr, "status": p.status,
				}
				for p in run.payments
			],
		}
		if include_xml:
			result["iso20022_xml"] = run.iso20022_xml
		return jsonify(result)

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		from pgappforge.plugins.erp.finance.ap.services import APService, APServiceError
		from datetime import date as date_type
		session = _get_session()
		data = request.get_json(silent=True) or {}
		required = ("supplier_ids", "value_date", "tenant_id")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"ok": False, "error": f"missing: {missing}"}), 400
		svc = APService()
		try:
			run = svc.create_payment_run(
				supplier_ids=data["supplier_ids"],
				value_date=date_type.fromisoformat(data["value_date"]),
				session=session,
				tenant_id=data["tenant_id"],
				bank_account=data.get("bank_account", ""),
				bic=data.get("bic", ""),
				currency_code=data.get("currency_code", "USD"),
			)
			session.commit()
			return jsonify({
				"ok": True, "id": run.id, "run_number": run.run_number,
				"total_payments": run.total_payments,
				"total_amount_cents": run.total_amount_cents,
			}), 201
		except APServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 400

	@expose("/<string:run_id>/approve", methods=["POST"])
	@has_access
	def approve(self, run_id: str):
		from pgappforge.plugins.erp.finance.ap.models import APPaymentRun
		session = _get_session()
		run = session.get(APPaymentRun, run_id)
		if run is None:
			abort(404)
		if run.status != "DRAFT":
			return jsonify({"ok": False, "error": f"Run status is {run.status!r}; must be DRAFT"}), 400
		data = request.get_json(silent=True) or {}
		run.approved_by = data.get("approved_by")
		run.approved_at = datetime.now(timezone.utc)
		run.status = "APPROVED"
		run.updated_at = datetime.now(timezone.utc)
		session.commit()
		return jsonify({"ok": True, "status": "APPROVED"})

	@expose("/<string:run_id>/transmit", methods=["POST"])
	@has_access
	def transmit(self, run_id: str):
		from pgappforge.plugins.erp.finance.ap.models import APPaymentRun
		session = _get_session()
		run = session.get(APPaymentRun, run_id)
		if run is None:
			abort(404)
		if run.status != "APPROVED":
			return jsonify({"ok": False, "error": f"Run must be APPROVED before transmission; got {run.status!r}"}), 400
		run.status = "TRANSMITTED"
		run.updated_at = datetime.now(timezone.utc)
		session.commit()
		return jsonify({"ok": True, "status": "TRANSMITTED"})


# ---------------------------------------------------------------------------
# APReportView — 3 canned reports
# ---------------------------------------------------------------------------

class APReportView(BaseERPView):
	"""AP canned reports.

	GET /ap/reports/aging            — AP Aging (current/30/60/90+ days overdue)
	GET /ap/reports/payment-history  — Supplier payment history
	GET /ap/reports/matching-status  — Invoice matching status summary
	"""

	route_base = "/ap/reports"
	default_view = "aging"

	@expose("/aging")
	@has_access
	def aging(self):
		"""AP Aging report — buckets invoices by days overdue."""
		from pgappforge.plugins.erp.finance.ap.models import APInvoice, APSupplier
		session = _get_session()
		today = datetime.now(timezone.utc).date()
		tenant_id = request.args.get("tenant_id")

		# --- KPI summary ---
		total_suppliers = session.execute(
			sa.select(sa.func.count(APSupplier.id))
		).scalar() or 0
		pending_invoices = session.execute(
			sa.select(sa.func.count(APInvoice.id)).where(
				APInvoice.status.notin_(["PAID", "CANCELLED"])
			)
		).scalar() or 0
		overdue_amount_cents = session.execute(
			sa.select(sa.func.coalesce(
				sa.func.sum(APInvoice.total_cents - APInvoice.paid_cents), 0
			)).where(
				APInvoice.status.notin_(["PAID", "CANCELLED"]),
				APInvoice.due_date < today,
			)
		).scalar() or 0
		kpi_html = self.kpi_cards([
			{"label": "Total Suppliers", "value": total_suppliers,
			 "format": "integer", "color": "#1a56db", "icon": "fa-truck"},
			{"label": "Pending Invoices", "value": pending_invoices,
			 "format": "integer", "color": "#e3a008", "icon": "fa-file-invoice"},
			{"label": "Overdue (cents)", "value": overdue_amount_cents,
			 "format": "integer", "color": "#e02424", "icon": "fa-exclamation-circle"},
		])

		q = (
			sa.select(APInvoice, APSupplier)
			.join(APSupplier, APInvoice.supplier_id == APSupplier.id)
			.where(APInvoice.status.notin_(["PAID", "CANCELLED"]))
			.order_by(APInvoice.due_date)
		)
		if tenant_id:
			q = q.where(APInvoice.tenant_id == tenant_id)

		rows_raw = session.execute(q).all()

		# Bucket: current, 1-30, 31-60, 61-90, 91+
		buckets = {"current": [], "1_30": [], "31_60": [], "61_90": [], "91_plus": []}
		for inv, sup in rows_raw:
			due = inv.due_date
			if hasattr(due, "date"):
				due = due.date()
			overdue = (today - due).days
			outstanding = inv.total_cents - inv.paid_cents
			row_data = {
				"invoice_id": inv.id,
				"invoice_number": inv.invoice_number_supplier,
				"supplier": sup.name,
				"due_date": due.isoformat(),
				"overdue_days": overdue,
				"outstanding_cents": outstanding,
				"currency": inv.currency_code,
			}
			if overdue <= 0:
				buckets["current"].append(row_data)
			elif overdue <= 30:
				buckets["1_30"].append(row_data)
			elif overdue <= 60:
				buckets["31_60"].append(row_data)
			elif overdue <= 90:
				buckets["61_90"].append(row_data)
			else:
				buckets["91_plus"].append(row_data)

		if request.args.get("format") == "json":
			return jsonify({
				"report": "ap_aging",
				"as_of": today.isoformat(),
				"buckets": buckets,
			})

		def _bucket_html(label: str, items: list) -> str:
			if not items:
				return f"<h5>{_he(label)} — none</h5>"
			total = sum(i["outstanding_cents"] for i in items)
			trs = "".join(
				f"<tr><td>{_he(i['supplier'])}</td><td>{_he(i['invoice_number'])}</td>"
				f"<td>{_he(i['due_date'])}</td><td class='text-danger'>{i['overdue_days']}</td>"
				f"<td class='text-right'>{_he(i['currency'])} {i['outstanding_cents'] / 100:,.2f}</td></tr>"
				for i in items
			)
			total_row = f"<tr class='info'><td colspan='4'><strong>Subtotal</strong></td><td class='text-right'><strong>{total / 100:,.2f}</strong></td></tr>"
			return (
				f"<h5 style='margin-top:16px'>{_he(label)}</h5>"
				f"<table class='table table-condensed table-bordered' style='font-size:0.82em'>"
				f"<thead><tr><th>Supplier</th><th>Invoice #</th><th>Due Date</th><th>Days Overdue</th><th>Outstanding</th></tr></thead>"
				f"<tbody>{trs}{total_row}</tbody></table>"
			)

		sections = (
			_bucket_html("Current (not yet due)", buckets["current"]) +
			_bucket_html("1-30 Days Overdue", buckets["1_30"]) +
			_bucket_html("31-60 Days Overdue", buckets["31_60"]) +
			_bucket_html("61-90 Days Overdue", buckets["61_90"]) +
			_bucket_html("91+ Days Overdue", buckets["91_plus"])
		)

		grand_total = sum(
			sum(i["outstanding_cents"] for i in bucket)
			for bucket in buckets.values()
		)

		body = (
			f'<div class="noprint"><h3>AP Aging Report — as of {today}</h3>'
			f'<button onclick="window.print()" class="btn btn-xs btn-primary">Print</button></div>'
			f'{kpi_html}'
			f'{sections}'
			f'<p><strong>Grand Total Outstanding: {grand_total / 100:,.2f}</strong></p>'
			f'<p style="color:#888;font-size:0.75em">Generated {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}</p>'
		)
		return make_response(_page_html("AP Aging Report", body), 200)

	@expose("/payment-history")
	@has_access
	def payment_history(self):
		"""Supplier payment history — last 90 days by default."""
		from pgappforge.plugins.erp.finance.ap.models import APPayment, APSupplier
		from datetime import timedelta
		session = _get_session()
		tenant_id = request.args.get("tenant_id")
		supplier_id = request.args.get("supplier_id")
		days = int(request.args.get("days", 90))
		since = datetime.now(timezone.utc).date() - timedelta(days=days)

		q = (
			sa.select(APPayment, APSupplier)
			.join(APSupplier, APPayment.supplier_id == APSupplier.id)
			.where(APPayment.payment_date >= since)
			.order_by(sa.desc(APPayment.payment_date))
		)
		if tenant_id:
			q = q.where(APPayment.tenant_id == tenant_id)
		if supplier_id:
			q = q.where(APPayment.supplier_id == supplier_id)

		rows_raw = session.execute(q.limit(1000)).all()

		if request.args.get("format") == "json":
			return jsonify({"payments": [
				{
					"id": p.id, "supplier": s.name,
					"payment_date": p.payment_date.isoformat() if p.payment_date else None,
					"amount_cents": p.amount_cents, "currency_code": p.currency_code,
					"status": p.status, "bank_reference": p.bank_reference, "uetr": p.uetr,
				}
				for p, s in rows_raw
			]})

		trs = "".join(
			f"<tr>"
			f"<td>{_he(p.payment_date)}</td>"
			f"<td>{_he(s.name)}</td>"
			f"<td class='text-right'>{_he(p.currency_code)} {p.amount_cents / 100:,.2f}</td>"
			f"<td><span class='label label-{'success' if p.status=='CONFIRMED' else 'default'}'>{_he(p.status)}</span></td>"
			f"<td style='font-size:0.75em'>{_he(p.uetr or '')}</td>"
			f"</tr>"
			for p, s in rows_raw
		)
		total = sum(p.amount_cents for p, _ in rows_raw)

		body = (
			f'<h3>Payment History — last {days} days</h3>'
			f'<table class="table table-bordered table-condensed table-hover">'
			f'<thead><tr><th>Date</th><th>Supplier</th><th>Amount</th><th>Status</th><th>UETR</th></tr></thead>'
			f'<tbody>{trs}'
			f'<tr class="info"><td colspan="2"><strong>Total</strong></td>'
			f'<td class="text-right"><strong>{total / 100:,.2f}</strong></td><td colspan="2"></td></tr>'
			f'</tbody></table>'
			f'<p style="color:#888;font-size:0.75em">Generated {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}</p>'
		)
		return make_response(_page_html("AP Payment History", body), 200)

	@expose("/matching-status")
	@has_access
	def matching_status(self):
		"""Invoice matching status summary — counts per match_status bucket."""
		from pgappforge.plugins.erp.finance.ap.models import APInvoice
		session = _get_session()
		tenant_id = request.args.get("tenant_id")

		q = (
			sa.select(
				APInvoice.match_status,
				APInvoice.approval_status,
				sa.func.count().label("count"),
				sa.func.sum(APInvoice.total_cents).label("total_cents"),
			)
			.where(APInvoice.status.notin_(["PAID", "CANCELLED"]))
			.group_by(APInvoice.match_status, APInvoice.approval_status)
			.order_by(APInvoice.match_status)
		)
		if tenant_id:
			q = q.where(APInvoice.tenant_id == tenant_id)

		rows = session.execute(q).all()

		data = [
			{
				"match_status": r.match_status,
				"approval_status": r.approval_status,
				"count": r.count,
				"total_cents": r.total_cents or 0,
			}
			for r in rows
		]

		if request.args.get("format") == "json":
			return jsonify({"matching_status": data})

		trs = "".join(
			f"<tr>"
			f"<td>{_he(r['match_status'])}</td>"
			f"<td>{_he(r['approval_status'])}</td>"
			f"<td class='text-right'>{r['count']}</td>"
			f"<td class='text-right'>{r['total_cents'] / 100:,.2f}</td>"
			f"</tr>"
			for r in data
		)
		body = (
			'<h3>Invoice Matching Status</h3>'
			'<table class="table table-bordered table-condensed">'
			'<thead><tr><th>Match Status</th><th>Approval Status</th><th>Count</th><th>Total Amount</th></tr></thead>'
			f'<tbody>{trs}</tbody></table>'
			f'<p style="color:#888;font-size:0.75em">Generated {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}</p>'
		)
		return make_response(_page_html("Matching Status", body), 200)


__all__ = [
	"APSupplierView",
	"APPurchaseOrderView",
	"APGoodsReceiptView",
	"APInvoiceView",
	"APPaymentRunView",
	"APReportView",
]
