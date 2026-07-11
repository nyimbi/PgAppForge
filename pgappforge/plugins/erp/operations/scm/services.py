"""
pgappforge/plugins/erp/operations/scm/services.py

Business logic layer for the Supply Chain Management plugin.

Stateless service class — all state lives in the database session.
All monetary arithmetic uses Decimal — never float.
Session passed explicitly; never committed inside service methods.

GL account codes (Chart of Accounts):
  1140  Inventory
  1150  Inventory In-Transit
  2000  Accounts Payable
"""
from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import sqlalchemy as sa

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# GL account constants
# ---------------------------------------------------------------------------

_GL_INVENTORY           = "1140"
_GL_INVENTORY_TRANSIT   = "1150"
_GL_AP                  = "2000"

# 3-way match tolerance: invoice qty may differ from GRN qty by at most this fraction
_MATCH_TOLERANCE = Decimal("0.02")   # 2 %


def _uuid4() -> str:
	return str(uuid.uuid4())


def _gl_post(entries: list[dict], description: str, session: Any) -> str:
	"""Post GL journal entries; returns journal_id.

	Lazy-imports GL service to avoid hard circular dependency.
	Falls back silently when GL plugin is not loaded.

	Each entry: {account_code, debit_cents, credit_cents, tenant_id, description}
	"""
	journal_id = _uuid4()
	try:
		from pgappforge.plugins.erp.finance.gl.services import GLService  # type: ignore[import]
		GLService.post_journal(
			entries=entries,
			description=description,
			journal_id=journal_id,
			session=session,
		)
	except ImportError:
		log.debug("GL plugin not loaded — skipping journal post: %s (%d entries)", description, len(entries))
	return journal_id


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class SCMServiceError(Exception):
	"""Base error for SCM service layer."""


class SupplierNotFoundError(SCMServiceError):
	pass


class SupplierProductNotFoundError(SCMServiceError):
	pass


class ShipmentNotFoundError(SCMServiceError):
	pass


class RequisitionNotFoundError(SCMServiceError):
	pass


class PurchaseOrderNotFoundError(SCMServiceError):
	pass


class InvalidStatusTransitionError(SCMServiceError):
	pass


class MatchError(SCMServiceError):
	"""Raised when 3-way match fails outside tolerance."""


# ---------------------------------------------------------------------------
# SCMService
# ---------------------------------------------------------------------------

class SCMService:
	"""Stateless Supply Chain Management service.

	All methods accept an explicit SQLAlchemy session and tenant_id.
	No commits are performed inside — the caller controls the transaction.
	"""

	# ------------------------------------------------------------------
	# 1. create_supplier
	# ------------------------------------------------------------------

	def create_supplier(
		self,
		session: Any,
		data: dict[str, Any],
		tenant_id: str,
	) -> Any:
		"""Create and persist a new Supplier record.

		data keys (all optional except supplier_code, name):
		  supplier_code, name, supplier_type, status, payment_terms_days,
		  currency_code, lead_time_days, min_order_qty, credit_limit_cents,
		  rating, country_code, party_id, preferred, notes, metadata_

		Returns the new Supplier instance (not yet committed).
		"""
		from pgappforge.plugins.erp.operations.scm.models import Supplier
		from pgappforge.plugins.erp.operations.scm.events import SupplierCreatedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		supplier = Supplier(
			tenant_id=tenant_id,
			supplier_code=data["supplier_code"],
			name=data["name"],
			supplier_type=data.get("supplier_type", "DISTRIBUTOR"),
			status=data.get("status", "ACTIVE"),
			payment_terms_days=int(data.get("payment_terms_days", 30)),
			currency_code=data.get("currency_code", "USD"),
			lead_time_days=int(data.get("lead_time_days", 14)),
			min_order_qty=Decimal(str(data.get("min_order_qty", 1))),
			credit_limit_cents=int(data.get("credit_limit_cents", 0)),
			rating=Decimal(str(data["rating"])) if data.get("rating") is not None else None,
			country_code=data.get("country_code"),
			party_id=data.get("party_id"),
			preferred=bool(data.get("preferred", False)),
			is_active=bool(data.get("is_active", True)),
			notes=data.get("notes"),
			metadata_=data.get("metadata_") or {},
		)
		session.add(supplier)
		session.flush()

		emit_event(
			SupplierCreatedEvent(
				aggregate_id=supplier.id,
				aggregate_type="Supplier",
				tenant_id=tenant_id,
				supplier_id=supplier.id,
				supplier_code=supplier.supplier_code,
				name=supplier.name,
				party_id=supplier.party_id or "",
			),
			session,
		)
		log.info("SCMService.create_supplier: created %r tenant=%s", supplier.supplier_code, tenant_id)
		return supplier

	# ------------------------------------------------------------------
	# 2. create_purchase_requisition
	# ------------------------------------------------------------------

	def create_purchase_requisition(
		self,
		session: Any,
		requester_id: str,
		department_id: str,
		items: list[dict],
		required_by: date,
		tenant_id: str,
	) -> Any:
		"""Create a PurchaseRequisition in DRAFT status.

		items: list of {product_code, qty, estimated_unit_cost_cents, justification}

		Returns the new PurchaseRequisition (not yet committed).
		"""
		from pgappforge.plugins.erp.operations.scm.models import PurchaseRequisition

		if not items:
			raise SCMServiceError("Purchase requisition must have at least one item")

		req = PurchaseRequisition(
			tenant_id=tenant_id,
			requester_id=requester_id,
			department_id=department_id,
			req_date=date.today(),
			required_by=required_by,
			status="DRAFT",
			items=list(items),
		)
		session.add(req)
		session.flush()
		log.info("SCMService.create_purchase_requisition: %s tenant=%s items=%d", req.id, tenant_id, len(items))
		return req

	# ------------------------------------------------------------------
	# 3. approve_requisition
	# ------------------------------------------------------------------

	def approve_requisition(
		self,
		session: Any,
		req_id: str,
		approver_id: str,
		tenant_id: str,
	) -> Any:
		"""Transition a PurchaseRequisition SUBMITTED → APPROVED.

		Raises InvalidStatusTransitionError if status is not SUBMITTED.
		Returns the updated requisition.
		"""
		from pgappforge.plugins.erp.operations.scm.models import PurchaseRequisition

		req = session.get(PurchaseRequisition, req_id)
		if req is None or req.tenant_id != tenant_id:
			raise RequisitionNotFoundError(f"PurchaseRequisition {req_id!r} not found for tenant {tenant_id!r}")

		if req.status != "SUBMITTED":
			raise InvalidStatusTransitionError(
				f"Cannot approve requisition in status {req.status!r}; expected SUBMITTED"
			)

		req.status = "APPROVED"
		req.approved_by = approver_id
		req.approved_at = datetime.now(timezone.utc)
		req.updated_at = datetime.now(timezone.utc)
		log.info("SCMService.approve_requisition: %s approved by %s", req_id, approver_id)
		return req

	# ------------------------------------------------------------------
	# 4. create_purchase_order
	# ------------------------------------------------------------------

	def create_purchase_order(
		self,
		session: Any,
		supplier_id: str,
		lines: list[dict],
		order_date: date,
		expected_delivery: date,
		tenant_id: str,
		req_id: str | None = None,
	) -> Any:
		"""Create a PurchaseOrder with lines and post GL on confirmation.

		lines: list of {product_code, description, ordered_qty, unit_of_measure,
		                 unit_price_cents, [line_number]}

		GL on creation (status SENT):
		  DR inventory_in_transit "1150"   total_amount_cents
		  CR accounts_payable      "2000"  total_amount_cents

		Returns the new PurchaseOrder (not yet committed).
		"""
		from pgappforge.plugins.erp.operations.scm.models import (
			PurchaseOrder,
			POLine,
			Supplier,
		)

		if not lines:
			raise SCMServiceError("Purchase order must have at least one line")

		supplier = session.get(Supplier, supplier_id)
		if supplier is None or supplier.tenant_id != tenant_id:
			raise SupplierNotFoundError(f"Supplier {supplier_id!r} not found for tenant {tenant_id!r}")

		if supplier.status in ("SUSPENDED", "BLACKLISTED"):
			raise SCMServiceError(
				f"Cannot create PO for supplier {supplier.supplier_code!r} with status {supplier.status!r}"
			)

		# Generate sequential PO number
		po_number = self._next_po_number(session, tenant_id)

		po = PurchaseOrder(
			tenant_id=tenant_id,
			po_number=po_number,
			supplier_id=supplier_id,
			requisition_id=req_id,
			order_date=order_date,
			expected_delivery_date=expected_delivery,
			status="DRAFT",
			currency_code=supplier.currency_code,
			payment_terms_days=supplier.payment_terms_days,
			total_amount_cents=0,
		)
		session.add(po)
		session.flush()

		total_cents = 0
		for idx, line_data in enumerate(lines, start=1):
			ordered_qty = Decimal(str(line_data["ordered_qty"]))
			unit_price = int(line_data["unit_price_cents"])
			line_total = int((ordered_qty * Decimal(unit_price)).to_integral_value(ROUND_HALF_UP))
			line_num = int(line_data.get("line_number", idx))

			po_line = POLine(
				po_id=po.id,
				line_number=line_num,
				product_code=line_data["product_code"],
				description=line_data.get("description"),
				ordered_qty=ordered_qty,
				received_qty=Decimal("0"),
				invoiced_qty=Decimal("0"),
				unit_of_measure=line_data.get("unit_of_measure", "EA"),
				unit_price_cents=unit_price,
				line_total_cents=line_total,
				status="OPEN",
			)
			session.add(po_line)
			total_cents += line_total

		po.total_amount_cents = total_cents
		po.status = "SENT"
		po.updated_at = datetime.now(timezone.utc)

		# GL: DR inventory_in_transit CR accounts_payable
		_gl_post(
			[
				{
					"account_code": _GL_INVENTORY_TRANSIT,
					"debit_cents": total_cents,
					"credit_cents": 0,
					"tenant_id": tenant_id,
					"description": f"PO {po_number} — inventory in transit",
				},
				{
					"account_code": _GL_AP,
					"debit_cents": 0,
					"credit_cents": total_cents,
					"tenant_id": tenant_id,
					"description": f"PO {po_number} — accounts payable",
				},
			],
			f"Purchase Order {po_number} confirmation",
			session,
		)

		log.info(
			"SCMService.create_purchase_order: %s supplier=%s lines=%d total=%d¢ tenant=%s",
			po_number, supplier_id, len(lines), total_cents, tenant_id,
		)
		return po

	# ------------------------------------------------------------------
	# 5. receive_goods
	# ------------------------------------------------------------------

	def receive_goods(
		self,
		session: Any,
		po_id: str,
		received_lines: list[dict],
		received_by: str,
		tenant_id: str,
	) -> Any:
		"""Record a Goods Receipt against a PurchaseOrder.

		received_lines: list of {po_line_id, received_qty, accepted_qty,
		                          rejected_qty, [rejection_reason], [lot_number], [expiry_date]}

		Updates POLine.received_qty. If all lines fully received, PO status → RECEIVED.

		GL:
		  DR inventory          "1140"  accepted_total_cents
		  CR inventory_transit  "1150"  accepted_total_cents

		Returns the new GoodsReceipt (not yet committed).
		"""
		from pgappforge.plugins.erp.operations.scm.models import (
			PurchaseOrder,
			POLine,
			GoodsReceipt,
			GoodsReceiptLine,
		)

		po = session.get(PurchaseOrder, po_id)
		if po is None or po.tenant_id != tenant_id:
			raise PurchaseOrderNotFoundError(f"PurchaseOrder {po_id!r} not found for tenant {tenant_id!r}")

		if po.status in ("CANCELLED", "CLOSED"):
			raise InvalidStatusTransitionError(
				f"Cannot receive goods against PO {po.po_number!r} with status {po.status!r}"
			)

		grn_number = self._next_grn_number(session, tenant_id)
		grn = GoodsReceipt(
			tenant_id=tenant_id,
			po_id=po_id,
			grn_number=grn_number,
			received_date=date.today(),
			received_by=received_by,
			status="POSTED",
		)
		session.add(grn)
		session.flush()

		accepted_total_cents = 0

		for line_data in received_lines:
			pol = session.get(POLine, line_data["po_line_id"])
			if pol is None or pol.po_id != po_id:
				raise SCMServiceError(
					f"POLine {line_data['po_line_id']!r} does not belong to PO {po_id!r}"
				)

			received_qty = Decimal(str(line_data["received_qty"]))
			accepted_qty = Decimal(str(line_data["accepted_qty"]))
			rejected_qty = Decimal(str(line_data.get("rejected_qty", 0)))

			expiry_raw = line_data.get("expiry_date")
			expiry_date: date | None = None
			if isinstance(expiry_raw, date):
				expiry_date = expiry_raw
			elif expiry_raw:
				expiry_date = date.fromisoformat(str(expiry_raw))

			grn_line = GoodsReceiptLine(
				grn_id=grn.id,
				po_line_id=pol.id,
				received_qty=received_qty,
				accepted_qty=accepted_qty,
				rejected_qty=rejected_qty,
				rejection_reason=line_data.get("rejection_reason"),
				lot_number=line_data.get("lot_number"),
				expiry_date=expiry_date,
			)
			session.add(grn_line)

			# Update POLine cumulative received qty and status
			pol.received_qty = Decimal(str(pol.received_qty or 0)) + received_qty
			pol.updated_at = datetime.now(timezone.utc)
			if pol.received_qty >= pol.ordered_qty:
				pol.status = "RECEIVED"
			elif pol.received_qty > 0:
				pol.status = "PARTIAL"

			# Accepted quantity drives inventory value DR
			accepted_total_cents += int(
				(accepted_qty * Decimal(str(pol.unit_price_cents))).to_integral_value(ROUND_HALF_UP)
			)

		# Update PO status
		all_lines = session.execute(
			sa.select(POLine).where(POLine.po_id == po_id)
		).scalars().all()
		open_lines = [l for l in all_lines if l.status not in ("RECEIVED", "CANCELLED")]
		if not open_lines:
			po.status = "RECEIVED"
		else:
			po.status = "PARTIAL"
		po.updated_at = datetime.now(timezone.utc)

		# GL: DR inventory CR inventory_in_transit
		if accepted_total_cents > 0:
			_gl_post(
				[
					{
						"account_code": _GL_INVENTORY,
						"debit_cents": accepted_total_cents,
						"credit_cents": 0,
						"tenant_id": tenant_id,
						"description": f"GRN {grn_number} — inventory receipt",
					},
					{
						"account_code": _GL_INVENTORY_TRANSIT,
						"debit_cents": 0,
						"credit_cents": accepted_total_cents,
						"tenant_id": tenant_id,
						"description": f"GRN {grn_number} — clear inventory in transit",
					},
				],
				f"Goods Receipt {grn_number}",
				session,
			)

		log.info(
			"SCMService.receive_goods: %s po=%s lines=%d accepted=%d¢ tenant=%s",
			grn_number, po_id, len(received_lines), accepted_total_cents, tenant_id,
		)
		return grn

	# ------------------------------------------------------------------
	# 6. match_supplier_invoice
	# ------------------------------------------------------------------

	def match_supplier_invoice(
		self,
		session: Any,
		po_id: str,
		invoice_data: dict,
		tenant_id: str,
	) -> Any:
		"""Register a supplier invoice and run 3-way match.

		invoice_data keys:
		  invoice_number, invoice_date (date|str), due_date (date|str),
		  currency_code, subtotal_cents, tax_cents, total_cents

		3-way match logic:
		  For each POLine: compare ordered_qty vs total GRN accepted_qty vs invoice-implied qty.
		  invoice_qty_per_line = total_cents / PO total * line_total (proportional allocation).
		  If |grn_qty - invoiced_qty| / grn_qty <= tolerance (2%): MATCHED → APPROVED.
		  Else: DISPUTED with notes.

		Returns the new SupplierInvoice.
		"""
		from pgappforge.plugins.erp.operations.scm.models import (
			PurchaseOrder,
			POLine,
			GoodsReceipt,
			GoodsReceiptLine,
			SupplierInvoice,
		)

		po = session.get(PurchaseOrder, po_id)
		if po is None or po.tenant_id != tenant_id:
			raise PurchaseOrderNotFoundError(f"PurchaseOrder {po_id!r} not found for tenant {tenant_id!r}")

		inv_date = invoice_data["invoice_date"]
		if not isinstance(inv_date, date):
			inv_date = date.fromisoformat(str(inv_date))
		due_date = invoice_data["due_date"]
		if not isinstance(due_date, date):
			due_date = date.fromisoformat(str(due_date))

		latest_grn = session.execute(
			sa.select(GoodsReceipt)
			.where(GoodsReceipt.po_id == po_id)
			.order_by(sa.desc(GoodsReceipt.received_date), sa.desc(GoodsReceipt.created_at))
			.limit(1)
		).scalar_one_or_none()

		invoice = SupplierInvoice(
			tenant_id=tenant_id,
			po_id=po_id,
			grn_id=latest_grn.id if latest_grn else invoice_data.get("grn_id"),
			supplier_id=po.supplier_id,
			invoice_number=invoice_data["invoice_number"],
			invoice_date=inv_date,
			due_date=due_date,
			currency_code=invoice_data.get("currency_code", po.currency_code),
			subtotal_cents=int(invoice_data["subtotal_cents"]),
			tax_cents=int(invoice_data.get("tax_cents", 0)),
			total_cents=int(invoice_data["total_cents"]),
			status="RECEIVED",
		)
		session.add(invoice)
		session.flush()

		# Retrieve PO lines and GRN totals for matching
		po_lines = session.execute(
			sa.select(POLine).where(POLine.po_id == po_id, POLine.status != "CANCELLED")
		).scalars().all()

		po_total = sum(int(l.line_total_cents) for l in po_lines) or 1  # guard div/0

		mismatch_notes: list[str] = []

		for pol in po_lines:
			# Sum all accepted_qty for this POLine across all GRNs
			grn_accepted = session.execute(
				sa.select(sa.func.coalesce(sa.func.sum(GoodsReceiptLine.accepted_qty), 0)).where(
					GoodsReceiptLine.po_line_id == pol.id
				)
			).scalar() or Decimal("0")
			grn_accepted = Decimal(str(grn_accepted))

			# Proportional invoice quantity allocation
			line_fraction = Decimal(str(pol.line_total_cents)) / Decimal(str(po_total))
			inv_line_value = Decimal(str(invoice.total_cents)) * line_fraction
			# Implied invoiced qty = inv_line_value / unit_price
			if pol.unit_price_cents and int(pol.unit_price_cents) > 0:
				inv_qty = inv_line_value / Decimal(str(pol.unit_price_cents))
			else:
				inv_qty = Decimal("0")

			if grn_accepted == 0:
				if inv_qty > Decimal("0.001"):
					mismatch_notes.append(
						f"Line {pol.line_number} product={pol.product_code}: "
						f"no GRN receipts but invoice implies qty={inv_qty:.3f}"
					)
				continue

			variance = abs(grn_accepted - inv_qty) / grn_accepted
			if variance > _MATCH_TOLERANCE:
				mismatch_notes.append(
					f"Line {pol.line_number} product={pol.product_code}: "
					f"grn_accepted={grn_accepted:.3f} inv_qty={inv_qty:.3f} "
					f"variance={variance*100:.1f}% > {_MATCH_TOLERANCE*100:.0f}% tolerance"
				)

		if mismatch_notes:
			invoice.status = "DISPUTED"
			invoice.match_notes = "; ".join(mismatch_notes)
			log.warning(
				"SCMService.match_supplier_invoice: invoice=%s DISPUTED — %s",
				invoice.invoice_number, invoice.match_notes,
			)
		else:
			invoice.status = "APPROVED"
			invoice.match_notes = "3-way match passed"
			# Advance PO to INVOICED if previously RECEIVED
			if po.status == "RECEIVED":
				po.status = "INVOICED"
				po.updated_at = datetime.now(timezone.utc)
			log.info(
				"SCMService.match_supplier_invoice: invoice=%s APPROVED po=%s",
				invoice.invoice_number, po_id,
			)

		invoice.updated_at = datetime.now(timezone.utc)
		return invoice

	# ------------------------------------------------------------------
	# 7. advance_to_next_step
	# ------------------------------------------------------------------

	def advance_to_next_step(self, record_id: str, session: Any) -> Any:
		"""Advance one SCM P2P document to its next lightweight workflow state."""
		from pgappforge.plugins.erp.operations.scm.models import (
			GoodsReceipt,
			PurchaseOrder,
			PurchaseRequisition,
			SupplierInvoice,
		)

		models = (PurchaseRequisition, PurchaseOrder, GoodsReceipt, SupplierInvoice)
		record = None
		for model in models:
			record = session.get(model, record_id)
			if record is not None:
				break
		if record is None:
			raise SCMServiceError(f"P2P record {record_id!r} not found")

		transitions = {
			"PurchaseRequisition": {
				"DRAFT": "SUBMITTED",
				"SUBMITTED": "APPROVED",
				"APPROVED": "PARTIALLY_ORDERED",
				"PARTIALLY_ORDERED": "ORDERED",
			},
			"PurchaseOrder": {
				"DRAFT": "SENT",
				"SENT": "ACKNOWLEDGED",
				"ACKNOWLEDGED": "PARTIAL",
				"PARTIAL": "RECEIVED",
				"RECEIVED": "INVOICED",
				"INVOICED": "CLOSED",
			},
			"GoodsReceipt": {
				"DRAFT": "CONFIRMED",
				"CONFIRMED": "POSTED",
			},
			"SupplierInvoice": {
				"RECEIVED": "MATCHED",
				"MATCHED": "APPROVED",
			},
		}
		model_name = record.__class__.__name__
		current = getattr(record, "status", None) or "DRAFT"
		next_status = transitions.get(model_name, {}).get(current)
		if not next_status:
			raise InvalidStatusTransitionError(
				f"No P2P advance transition from {model_name}.{current}"
			)
		record.status = next_status
		record.updated_at = datetime.now(timezone.utc)
		if model_name == "PurchaseRequisition" and next_status == "APPROVED":
			record.approved_at = record.approved_at or datetime.now(timezone.utc)
		session.flush()
		return record

	# ------------------------------------------------------------------
	# 8. get_supplier_performance
	# ------------------------------------------------------------------

	def get_supplier_performance(
		self,
		session: Any,
		supplier_id: str,
		from_date: date,
		to_date: date,
		tenant_id: str,
	) -> dict[str, Any]:
		"""Return structured supplier performance KPIs for the given period.

		Returns:
		  {
		    on_time_delivery_pct: Decimal,
		    quality_rejection_rate_pct: Decimal,
		    avg_lead_time_days: Decimal,
		    total_spend_cents: int,
		    po_count: int,
		  }
		"""
		from pgappforge.plugins.erp.operations.scm.models import (
			Supplier,
			PurchaseOrder,
			GoodsReceipt,
			GoodsReceiptLine,
			POLine,
			ShipmentTracking,
		)

		supplier = session.get(Supplier, supplier_id)
		if supplier is None or supplier.tenant_id != tenant_id:
			raise SupplierNotFoundError(f"Supplier {supplier_id!r} not found for tenant {tenant_id!r}")

		# POs closed in period
		pos = session.execute(
			sa.select(PurchaseOrder).where(
				PurchaseOrder.supplier_id == supplier_id,
				PurchaseOrder.tenant_id == tenant_id,
				PurchaseOrder.order_date >= from_date,
				PurchaseOrder.order_date <= to_date,
			)
		).scalars().all()

		po_count = len(pos)
		total_spend_cents = sum(int(p.total_amount_cents or 0) for p in pos)

		# On-time delivery: shipments delivered on or before ETA
		shipments = session.execute(
			sa.select(ShipmentTracking).where(
				ShipmentTracking.supplier_id == supplier_id,
				ShipmentTracking.tenant_id == tenant_id,
				ShipmentTracking.status == "DELIVERED",
				ShipmentTracking.actual_arrival >= from_date,
				ShipmentTracking.actual_arrival <= to_date,
			)
		).scalars().all()

		on_time_delivery_pct = Decimal("100.00")
		if shipments:
			on_time = sum(
				1 for s in shipments
				if s.actual_arrival and s.estimated_arrival
				and s.actual_arrival <= s.estimated_arrival
			)
			on_time_delivery_pct = (
				Decimal(on_time) / Decimal(len(shipments)) * Decimal("100")
			).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

		# Quality rejection rate from GRN lines
		grns = session.execute(
			sa.select(GoodsReceipt).where(
				GoodsReceipt.tenant_id == tenant_id,
				GoodsReceipt.po_id.in_([p.id for p in pos]),
			)
		).scalars().all()

		total_received = Decimal("0")
		total_rejected = Decimal("0")
		lead_time_days_list: list[int] = []

		for grn in grns:
			grn_lines = session.execute(
				sa.select(GoodsReceiptLine).where(GoodsReceiptLine.grn_id == grn.id)
			).scalars().all()
			for gl in grn_lines:
				total_received += Decimal(str(gl.received_qty or 0))
				total_rejected += Decimal(str(gl.rejected_qty or 0))

		# Avg lead time: order_date → received_date
		for grn in grns:
			po = next((p for p in pos if p.id == grn.po_id), None)
			if po and grn.received_date and po.order_date:
				lead_time_days_list.append((grn.received_date - po.order_date).days)

		quality_rejection_rate_pct = Decimal("0.00")
		if total_received > 0:
			quality_rejection_rate_pct = (
				total_rejected / total_received * Decimal("100")
			).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

		avg_lead_time_days = Decimal("0.0")
		if lead_time_days_list:
			avg_lead_time_days = (
				Decimal(sum(lead_time_days_list)) / Decimal(len(lead_time_days_list))
			).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)

		return {
			"on_time_delivery_pct": on_time_delivery_pct,
			"quality_rejection_rate_pct": quality_rejection_rate_pct,
			"avg_lead_time_days": avg_lead_time_days,
			"total_spend_cents": total_spend_cents,
			"po_count": po_count,
		}

	# ------------------------------------------------------------------
	# 8. run_demand_forecast
	# ------------------------------------------------------------------

	def run_demand_forecast(
		self,
		session: Any,
		product_code: str,
		periods: int = 3,
		tenant_id: str = "",
	) -> list[Any]:
		"""Compute and persist demand forecasts using 3-month simple moving average.

		Looks at actual_qty from existing DemandForecast rows for the last 3
		completed months. Inserts new DemandForecast rows for the next `periods`
		months. Uses INSERT … ON CONFLICT DO UPDATE to be idempotent.

		Returns list of new/updated DemandForecast records.
		"""
		from pgappforge.plugins.erp.operations.scm.models import DemandForecast

		today = date.today()
		# First day of current month
		current_month_start = today.replace(day=1)

		# Collect last 3 months of actuals
		history_rows = session.execute(
			sa.select(DemandForecast).where(
				DemandForecast.tenant_id == tenant_id,
				DemandForecast.product_code == product_code,
				DemandForecast.period_month < current_month_start,
				DemandForecast.actual_qty.is_not(None),
			).order_by(DemandForecast.period_month.desc()).limit(3)
		).scalars().all()

		if history_rows:
			actuals = [Decimal(str(r.actual_qty)) for r in history_rows]
			moving_avg = (sum(actuals) / Decimal(len(actuals))).quantize(
				Decimal("0.001"), rounding=ROUND_HALF_UP
			)
		else:
			moving_avg = Decimal("0.000")
			log.debug(
				"run_demand_forecast: no actuals for product=%s tenant=%s, forecast=0",
				product_code, tenant_id,
			)

		results: list[Any] = []
		for i in range(periods):
			# Advance month by i
			year = current_month_start.year
			month = current_month_start.month + i
			while month > 12:
				month -= 12
				year += 1
			period = date(year, month, 1)

			# Upsert: update forecast_qty if row exists, insert if not
			existing = session.execute(
				sa.select(DemandForecast).where(
					DemandForecast.tenant_id == tenant_id,
					DemandForecast.product_code == product_code,
					DemandForecast.period_month == period,
				)
			).scalar_one_or_none()

			if existing is not None:
				existing.forecast_qty = moving_avg
				existing.forecast_method = "MOVING_AVG"
				existing.updated_at = datetime.now(timezone.utc)
				results.append(existing)
			else:
				fc = DemandForecast(
					tenant_id=tenant_id,
					product_code=product_code,
					period_month=period,
					forecast_qty=moving_avg,
					forecast_method="MOVING_AVG",
				)
				session.add(fc)
				session.flush()
				results.append(fc)

		log.info(
			"SCMService.run_demand_forecast: product=%s periods=%d avg=%.3f tenant=%s",
			product_code, periods, moving_avg, tenant_id,
		)
		return results

	# ------------------------------------------------------------------
	# 9. get_procurement_dashboard
	# ------------------------------------------------------------------

	def get_procurement_dashboard(
		self,
		session: Any,
		tenant_id: str,
	) -> dict[str, Any]:
		"""Return operational procurement metrics for the dashboard.

		Returns:
		  {
		    open_pos: int,
		    pending_grns: int,          # POs in SENT/ACKNOWLEDGED/PARTIAL needing GRN
		    overdue_pos: int,           # POs past expected_delivery_date, not RECEIVED/CLOSED/CANCELLED
		    total_committed_cents: int, # sum of total_amount_cents for open POs
		    suppliers_by_status: {ACTIVE: n, QUALIFIED: n, SUSPENDED: n, BLACKLISTED: n},
		    spend_by_supplier: [{supplier_id, po_number_sample, total_spend_cents}],  # top 5
		  }
		"""
		from pgappforge.plugins.erp.operations.scm.models import (
			PurchaseOrder,
			Supplier,
		)

		today = date.today()

		# Open POs (not terminal)
		open_pos_rows = session.execute(
			sa.select(PurchaseOrder).where(
				PurchaseOrder.tenant_id == tenant_id,
				PurchaseOrder.status.not_in(["CLOSED", "CANCELLED"]),
			)
		).scalars().all()
		open_pos = len(open_pos_rows)
		total_committed_cents = sum(int(p.total_amount_cents or 0) for p in open_pos_rows)

		# Pending GRNs = POs in SENT/ACKNOWLEDGED/PARTIAL
		pending_grns = sum(
			1 for p in open_pos_rows if p.status in ("SENT", "ACKNOWLEDGED", "PARTIAL")
		)

		# Overdue POs = open POs past expected_delivery_date
		overdue_pos = sum(
			1 for p in open_pos_rows
			if p.expected_delivery_date and p.expected_delivery_date < today
			and p.status not in ("RECEIVED", "INVOICED", "CLOSED", "CANCELLED")
		)

		# Suppliers by status
		sup_status_rows = session.execute(
			sa.select(Supplier.status, sa.func.count(Supplier.id)).where(
				Supplier.tenant_id == tenant_id
			).group_by(Supplier.status)
		).all()
		suppliers_by_status: dict[str, int] = {r[0]: r[1] for r in sup_status_rows}

		# Top 5 suppliers by spend (from open+recent POs)
		spend_map: dict[str, int] = {}
		for p in open_pos_rows:
			spend_map[p.supplier_id] = spend_map.get(p.supplier_id, 0) + int(p.total_amount_cents or 0)
		top5 = sorted(spend_map.items(), key=lambda x: x[1], reverse=True)[:5]
		spend_by_supplier = [
			{"supplier_id": sid, "total_spend_cents": total}
			for sid, total in top5
		]

		return {
			"open_pos": open_pos,
			"pending_grns": pending_grns,
			"overdue_pos": overdue_pos,
			"total_committed_cents": total_committed_cents,
			"suppliers_by_status": suppliers_by_status,
			"spend_by_supplier": spend_by_supplier,
		}

	# ------------------------------------------------------------------
	# Supplier management (pre-existing, preserved)
	# ------------------------------------------------------------------

	def get_preferred_source(
		self,
		product_id: str,
		tenant_id: str,
		required_qty: Decimal,
		as_of: date | None,
		session: Any,
	) -> Any | None:
		"""Return the preferred SupplierProduct for product_id valid on as_of.

		Selects preferred=True first; falls back to lowest price_cents.
		Respects minimum_quantity constraint.
		Returns None if no valid sourcing record exists.
		"""
		from pgappforge.plugins.erp.operations.scm.models import SupplierProduct, Supplier

		target_date = as_of or date.today()
		q = (
			sa.select(SupplierProduct)
			.join(Supplier, SupplierProduct.supplier_id == Supplier.id)
			.where(
				SupplierProduct.product_id == product_id,
				SupplierProduct.tenant_id == tenant_id,
				Supplier.is_active == True,
				SupplierProduct.valid_from <= target_date,
				sa.or_(
					SupplierProduct.valid_to.is_(None),
					SupplierProduct.valid_to >= target_date,
				),
				SupplierProduct.minimum_quantity <= required_qty,
			)
			.order_by(
				sa.desc(SupplierProduct.is_preferred),
				SupplierProduct.price_cents,
			)
			.limit(1)
		)
		return session.execute(q).scalar_one_or_none()

	def approve_supplier(
		self,
		supplier_id: str,
		approved_by: str,
		session: Any,
	) -> Any:
		"""Mark a supplier as preferred=True.  Emits SupplierApprovedEvent."""
		from pgappforge.plugins.erp.operations.scm.models import Supplier
		from pgappforge.plugins.erp.operations.scm.events import SupplierApprovedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		supplier = session.get(Supplier, supplier_id)
		if supplier is None:
			raise SupplierNotFoundError(f"Supplier {supplier_id!r} not found")

		supplier.preferred = True
		supplier.is_active = True
		supplier.updated_at = datetime.now(timezone.utc)
		emit_event(
			SupplierApprovedEvent(
				aggregate_id=supplier_id,
				aggregate_type="Supplier",
				tenant_id=supplier.tenant_id,
				supplier_id=supplier_id,
				supplier_code=supplier.supplier_code,
				approved_by=approved_by,
			),
			session,
		)
		return supplier

	def refresh_supplier_kpis(
		self,
		supplier_id: str,
		period_days: int,
		session: Any,
	) -> Any:
		"""Recompute on_time_delivery_pct and quality_score from shipment/NCR history.

		on_time_delivery_pct: percentage of DELIVERED shipments where
		  actual_arrival <= estimated_arrival in the period.

		quality_score: 100 - (rejected_qty / inspected_qty * 100) averaged
		  over QualityInspection records linked to this supplier's GRNs.

		rating: simple composite = (otd + quality) / 2, scaled to 0-10.

		Emits SupplierKPIUpdatedEvent.
		"""
		from pgappforge.plugins.erp.operations.scm.models import Supplier, ShipmentTracking
		from pgappforge.plugins.erp.operations.scm.events import SupplierKPIUpdatedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		supplier = session.get(Supplier, supplier_id)
		if supplier is None:
			raise SupplierNotFoundError(f"Supplier {supplier_id!r} not found")

		since = date.today() - timedelta(days=period_days)

		# OTD calculation from shipment history
		shipments = session.execute(
			sa.select(ShipmentTracking).where(
				ShipmentTracking.supplier_id == supplier_id,
				ShipmentTracking.status == "DELIVERED",
				ShipmentTracking.actual_arrival >= since,
			)
		).scalars().all()

		otd_pct = Decimal("100.00")
		if shipments:
			on_time = sum(
				1 for s in shipments
				if s.actual_arrival and s.estimated_arrival
				and s.actual_arrival <= s.estimated_arrival
			)
			otd_pct = (Decimal(on_time) / Decimal(len(shipments)) * Decimal("100")).quantize(
				Decimal("0.01"), rounding=ROUND_HALF_UP
			)

		# Quality score — try to pull from QC plugin (soft dep)
		quality_score = Decimal("100.00")
		try:
			from pgappforge.plugins.erp.operations.quality.models import QualityInspection
			insp_rows = session.execute(
				sa.select(QualityInspection).where(
					QualityInspection.tenant_id == supplier.tenant_id,
					QualityInspection.reference_type == "APGoodsReceipt",
					QualityInspection.status.in_(["PASSED", "FAILED"]),
					QualityInspection.inspection_date >= since,
				)
			).scalars().all()
			if insp_rows:
				total_inspected = sum(Decimal(str(r.inspected_quantity)) for r in insp_rows)
				total_rejected = sum(Decimal(str(r.rejected_quantity)) for r in insp_rows)
				if total_inspected > 0:
					quality_score = (
						(total_inspected - total_rejected) / total_inspected * Decimal("100")
					).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
		except ImportError:
			log.debug("SCMService.refresh_supplier_kpis: QC plugin not loaded, quality_score=100")

		# Composite rating 0-10
		rating = ((otd_pct + quality_score) / Decimal("2") / Decimal("10")).quantize(
			Decimal("0.1"), rounding=ROUND_HALF_UP
		)

		supplier.on_time_delivery_pct = otd_pct
		supplier.quality_score = quality_score
		supplier.rating = rating
		supplier.updated_at = datetime.now(timezone.utc)

		emit_event(
			SupplierKPIUpdatedEvent(
				aggregate_id=supplier_id,
				aggregate_type="Supplier",
				tenant_id=supplier.tenant_id,
				supplier_id=supplier_id,
				supplier_code=supplier.supplier_code,
				rating=str(rating),
				on_time_delivery_pct=str(otd_pct),
				quality_score=str(quality_score),
				period_days=period_days,
			),
			session,
		)
		return supplier

	# ------------------------------------------------------------------
	# Shipment tracking (pre-existing, preserved)
	# ------------------------------------------------------------------

	def add_shipment_event(
		self,
		shipment_id: str,
		status: str,
		location: str,
		note: str,
		session: Any,
	) -> Any:
		"""Append a milestone event to ShipmentTracking.events JSONB array.

		If status is a valid terminal status (DELIVERED, EXCEPTION, RETURNED),
		updates shipment.status and emits the appropriate domain event.
		"""
		from pgappforge.plugins.erp.operations.scm.models import ShipmentTracking
		from pgappforge.plugins.erp.operations.scm.events import (
			ShipmentStatusChangedEvent,
			ShipmentDeliveredEvent,
			ShipmentExceptionEvent,
		)
		from pgappforge.plugins.erp.foundation.events import emit_event

		shipment = session.get(ShipmentTracking, shipment_id)
		if shipment is None:
			raise ShipmentNotFoundError(f"ShipmentTracking {shipment_id!r} not found")

		now_iso = datetime.now(timezone.utc).isoformat()
		old_status = shipment.status

		# Append to JSONB array (SQLAlchemy won't track list mutation — reassign)
		events = list(shipment.events or [])
		events.append({"ts": now_iso, "status": status, "location": location, "note": note})
		shipment.events = events
		shipment.updated_at = datetime.now(timezone.utc)

		emit_event(
			ShipmentStatusChangedEvent(
				aggregate_id=shipment_id,
				aggregate_type="ShipmentTracking",
				tenant_id=shipment.tenant_id,
				shipment_id=shipment_id,
				carrier=shipment.carrier,
				tracking_number=shipment.tracking_number,
				old_status=old_status,
				new_status=status,
				location=location,
				note=note,
			),
			session,
		)

		if status == "DELIVERED":
			actual_today = date.today()
			shipment.status = "DELIVERED"
			shipment.actual_arrival = actual_today
			days_var = 0
			if shipment.estimated_arrival:
				days_var = (actual_today - shipment.estimated_arrival).days
			emit_event(
				ShipmentDeliveredEvent(
					aggregate_id=shipment_id,
					aggregate_type="ShipmentTracking",
					tenant_id=shipment.tenant_id,
					shipment_id=shipment_id,
					carrier=shipment.carrier,
					tracking_number=shipment.tracking_number,
					supplier_id=shipment.supplier_id or "",
					destination_warehouse_id=shipment.destination_warehouse_id or "",
					actual_arrival=actual_today.isoformat(),
					estimated_arrival=shipment.estimated_arrival.isoformat() if shipment.estimated_arrival else "",
					days_variance=days_var,
				),
				session,
			)
		elif status == "EXCEPTION":
			shipment.status = "EXCEPTION"
			emit_event(
				ShipmentExceptionEvent(
					aggregate_id=shipment_id,
					aggregate_type="ShipmentTracking",
					tenant_id=shipment.tenant_id,
					shipment_id=shipment_id,
					carrier=shipment.carrier,
					tracking_number=shipment.tracking_number,
					exception_description=note,
					location=location,
				),
				session,
			)
		elif status == "RETURNED":
			shipment.status = "RETURNED"

		return shipment

	def get_overdue_shipments(
		self,
		tenant_id: str,
		session: Any,
	) -> list[Any]:
		"""Return IN_TRANSIT shipments past their estimated_arrival date."""
		from pgappforge.plugins.erp.operations.scm.models import ShipmentTracking

		today = date.today()
		return session.execute(
			sa.select(ShipmentTracking).where(
				ShipmentTracking.tenant_id == tenant_id,
				ShipmentTracking.status == "IN_TRANSIT",
				ShipmentTracking.estimated_arrival < today,
			).order_by(ShipmentTracking.estimated_arrival)
		).scalars().all()

	# ------------------------------------------------------------------
	# Private helpers
	# ------------------------------------------------------------------

	@staticmethod
	def _next_po_number(session: Any, tenant_id: str) -> str:
		"""Generate the next PO number for the tenant: PO-YYYYMMDD-NNNN."""
		from pgappforge.plugins.erp.operations.scm.models import PurchaseOrder
		count = session.execute(
			sa.select(sa.func.count(PurchaseOrder.id)).where(PurchaseOrder.tenant_id == tenant_id)
		).scalar() or 0
		today_str = date.today().strftime("%Y%m%d")
		return f"PO-{today_str}-{count + 1:04d}"

	@staticmethod
	def _next_grn_number(session: Any, tenant_id: str) -> str:
		"""Generate the next GRN number for the tenant: GRN-YYYYMMDD-NNNN."""
		from pgappforge.plugins.erp.operations.scm.models import GoodsReceipt
		count = session.execute(
			sa.select(sa.func.count(GoodsReceipt.id)).where(GoodsReceipt.tenant_id == tenant_id)
		).scalar() or 0
		today_str = date.today().strftime("%Y%m%d")
		return f"GRN-{today_str}-{count + 1:04d}"


__all__ = [
	"SCMService",
	"SCMServiceError",
	"SupplierNotFoundError",
	"SupplierProductNotFoundError",
	"ShipmentNotFoundError",
	"RequisitionNotFoundError",
	"PurchaseOrderNotFoundError",
	"InvalidStatusTransitionError",
	"MatchError",
]
