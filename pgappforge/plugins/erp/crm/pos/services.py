"""
pgappforge/plugins/erp/crm/pos/services.py

POSService — stateless business logic for Point of Sale operations.

All amounts in integer cents.  No float arithmetic.
Decimal used for tax computations.
The caller owns the transaction boundary (commit/rollback).

Public API
----------
  open_till(session, till_code, cashier_id, opening_float_cents, tenant_id) → POSTill
  create_sale(session, till_id, cashier_id, lines, payments, customer_id, tenant_id) → POSTransaction
  void_transaction(session, txn_id, void_reason, cashier_id, tenant_id) → POSTransaction
  process_return(session, original_txn_id, returned_lines, refund_method, tenant_id) → POSTransaction
  close_till(session, till_id, actual_cash_cents, closed_by, tenant_id) → POSShiftReconciliation
  get_sales_report(session, till_id, from_dt, to_dt, tenant_id) → dict
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import sqlalchemy as sa

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class POSServiceError(Exception):
	"""Base error for POS service operations."""


class TillNotFoundError(POSServiceError):
	"""Till does not exist or belongs to a different tenant."""


class TillStatusError(POSServiceError):
	"""Operation not permitted in current till status."""


class TransactionNotFoundError(POSServiceError):
	"""Transaction does not exist."""


class TransactionStatusError(POSServiceError):
	"""Operation not permitted on transaction in current status."""


class PaymentMismatchError(POSServiceError):
	"""Sum of payment amounts does not equal transaction total."""


# ---------------------------------------------------------------------------
# POSService
# ---------------------------------------------------------------------------

class POSService:
	"""Stateless POS service.  Instantiate once, reuse across requests."""

	# ------------------------------------------------------------------ #
	# Open till
	# ------------------------------------------------------------------ #

	def open_till(
		self,
		session: Any,
		till_code: str,
		cashier_id: str,
		opening_float_cents: int,
		tenant_id: str,
	) -> Any:
		"""Open a till for a new shift.

		Creates the till row if it does not exist; re-opens it if CLOSED.
		Raises TillStatusError if the till is already OPEN.

		Returns POSTill.
		"""
		from pgappforge.plugins.erp.crm.pos.models import POSTill
		from pgappforge.plugins.erp.crm.pos.events import TillOpenedEvent, emit_event

		assert opening_float_cents >= 0, "opening_float_cents must be non-negative"
		assert till_code, "till_code is required"
		assert cashier_id, "cashier_id is required"

		till = session.execute(
			sa.select(POSTill).where(
				POSTill.tenant_id == tenant_id,
				POSTill.till_code == till_code,
			)
		).scalar_one_or_none()

		if till is None:
			till = POSTill(
				tenant_id=tenant_id,
				till_code=till_code,
				name=f"Till {till_code}",
				location="",
				status="CLOSED",
			)
			session.add(till)
			session.flush()

		if till.status == "OPEN":
			raise TillStatusError(f"Till {till_code!r} is already open")

		till.status = "OPEN"
		till.cashier_id = cashier_id
		till.opened_at = datetime.now(timezone.utc)
		till.opening_float_cents = opening_float_cents
		till.total_sales_cents = 0
		till.total_returns_cents = 0
		till.expected_closing_cents = opening_float_cents

		session.flush()

		emit_event(
			TillOpenedEvent(
				aggregate_id=till.id,
				aggregate_type="POSTill",
				tenant_id=tenant_id,
				till_id=till.id,
				till_code=till_code,
				cashier_id=cashier_id,
				opening_float_cents=opening_float_cents,
			),
			session,
		)
		log.info("Opened till %r float=%d cashier=%r", till_code, opening_float_cents, cashier_id)
		return till

	# ------------------------------------------------------------------ #
	# Create sale
	# ------------------------------------------------------------------ #

	def create_sale(
		self,
		session: Any,
		till_id: str,
		cashier_id: str,
		lines: list[dict[str, Any]],
		payments: list[dict[str, Any]],
		customer_id: str | None = None,
		tenant_id: str = "",
	) -> Any:
		"""Create a SALE transaction.

		Each line dict:    {product_code, description?, qty, unit_price_cents, discount_cents?, tax_rate_pct?}
		Each payment dict: {method, amount_cents, reference?}

		Validates that sum(payments.amount_cents) == total_cents.

		GL:
		  DR  Cash/Card/Mpesa  (method-dependent account)   amount_cents
		  CR  sales_revenue    4000                          subtotal_cents
		  CR  VAT_payable      2300                          tax_cents

		Emits SaleCompletedEvent. Updates POSTill.total_sales_cents.

		Returns POSTransaction.
		"""
		from pgappforge.plugins.erp.crm.pos.models import (
			POSPayment,
			POSTransaction,
			POSTransactionLine,
			POSTill,
		)
		from pgappforge.plugins.erp.crm.pos.events import SaleCompletedEvent, emit_event

		assert lines, "lines must not be empty"
		assert payments, "payments must not be empty"
		assert cashier_id, "cashier_id is required"

		till = session.get(POSTill, till_id)
		if till is None:
			raise TillNotFoundError(f"POSTill {till_id!r} not found")
		if till.status != "OPEN":
			raise TillStatusError(f"Till {till.till_code!r} is not open (status={till.status!r})")

		# Build lines
		subtotal = 0
		total_discount = 0
		total_tax = 0
		line_objects: list[POSTransactionLine] = []

		for raw in lines:
			qty = Decimal(str(raw["qty"]))
			unit_price = int(raw["unit_price_cents"])
			discount = int(raw.get("discount_cents", 0))
			tax_rate = Decimal(str(raw.get("tax_rate_pct", 0)))

			gross = int((qty * Decimal(unit_price)).to_integral_value(ROUND_HALF_UP))
			net_before_tax = gross - discount
			tax = int((Decimal(net_before_tax) * tax_rate / Decimal("100")).to_integral_value(ROUND_HALF_UP))
			line_total = net_before_tax + tax

			subtotal += gross
			total_discount += discount
			total_tax += tax

			line_objects.append(POSTransactionLine(
				tenant_id=tenant_id,
				product_code=raw["product_code"],
				description=raw.get("description", raw["product_code"]),
				quantity=qty,
				unit_price_cents=unit_price,
				discount_cents=discount,
				tax_rate_pct=tax_rate,
				tax_cents=tax,
				line_total_cents=line_total,
			))

		total_cents = subtotal - total_discount + total_tax
		payment_total = sum(int(p["amount_cents"]) for p in payments)
		if payment_total != total_cents:
			raise PaymentMismatchError(
				f"Payment total {payment_total} != transaction total {total_cents}"
			)

		receipt_number = self._generate_receipt_number(session, till.till_code)
		now = datetime.now(timezone.utc)

		txn = POSTransaction(
			tenant_id=tenant_id,
			till_id=till_id,
			transaction_type="SALE",
			receipt_number=receipt_number,
			transaction_at=now,
			cashier_id=cashier_id,
			subtotal_cents=subtotal,
			discount_cents=total_discount,
			tax_cents=total_tax,
			total_cents=total_cents,
			status="COMPLETED",
			customer_id=customer_id,
		)
		session.add(txn)
		session.flush()

		for lo in line_objects:
			lo.txn_id = txn.id
			session.add(lo)

		payment_objects: list[POSPayment] = []
		for raw_p in payments:
			po = POSPayment(
				tenant_id=tenant_id,
				txn_id=txn.id,
				payment_method=raw_p["method"],
				amount_cents=int(raw_p["amount_cents"]),
				reference=raw_p.get("reference"),
				status="COMPLETED",
			)
			session.add(po)
			payment_objects.append(po)

		# Update till running totals
		till.total_sales_cents += total_cents
		till.expected_closing_cents = (
			till.opening_float_cents + till.total_sales_cents - till.total_returns_cents
		)

		# GL posting
		try:
			from pgappforge.plugins.erp.finance.gl.services import GLService
			gl = GLService()
			_METHOD_ACCOUNT = {
				"CASH": "1011",
				"CARD": "1012",
				"MPESA": "1013",
				"VOUCHER": "1014",
				"CREDIT": "1200",
			}
			gl_lines: list[dict[str, Any]] = []
			for po in payment_objects:
				acct = _METHOD_ACCOUNT.get(po.payment_method, "1011")
				gl_lines.append({
					"account": acct,
					"debit": po.amount_cents,
					"credit": 0,
					"description": f"POS {po.payment_method} payment",
				})
			gl_lines.append({
				"account": "4000",
				"debit": 0,
				"credit": subtotal - total_discount,
				"description": "Sales revenue",
			})
			if total_tax > 0:
				gl_lines.append({
					"account": "2300",
					"debit": 0,
					"credit": total_tax,
					"description": "VAT payable",
				})
			gl.post_journal(
				{
					"tenant_id": tenant_id,
					"description": f"POS sale {receipt_number}",
					"reference": receipt_number,
					"lines": gl_lines,
				},
				session=session,
			)
		except Exception as exc:
			log.debug("GL post skipped (plugin not loaded): %s", exc)

		session.flush()

		emit_event(
			SaleCompletedEvent(
				aggregate_id=txn.id,
				aggregate_type="POSTransaction",
				tenant_id=tenant_id,
				transaction_id=txn.id,
				till_id=till_id,
				cashier_id=cashier_id,
				receipt_number=receipt_number,
				total_cents=total_cents,
				customer_id=customer_id or "",
			),
			session,
		)
		log.info("Sale %r total=%d till=%r", receipt_number, total_cents, till.till_code)
		return txn

	# ------------------------------------------------------------------ #
	# Void transaction
	# ------------------------------------------------------------------ #

	def void_transaction(
		self,
		session: Any,
		txn_id: str,
		void_reason: str,
		cashier_id: str,
		tenant_id: str,
	) -> Any:
		"""Void a COMPLETED transaction.

		Marks transaction VOIDED. Reverses GL entries. Updates till totals.
		Emits TransactionVoidedEvent.

		Returns updated POSTransaction.
		"""
		from pgappforge.plugins.erp.crm.pos.models import POSTransaction, POSTill
		from pgappforge.plugins.erp.crm.pos.events import TransactionVoidedEvent, emit_event

		assert void_reason, "void_reason is required"

		txn = session.get(POSTransaction, txn_id)
		if txn is None:
			raise TransactionNotFoundError(f"POSTransaction {txn_id!r} not found")
		if txn.status != "COMPLETED":
			raise TransactionStatusError(
				f"Cannot void transaction {txn.receipt_number!r} in status {txn.status!r}"
			)
		if txn.transaction_type != "SALE":
			raise TransactionStatusError("Only SALE transactions can be voided directly")

		original_total = txn.total_cents
		txn.status = "VOIDED"
		txn.void_reason = void_reason

		# Reverse till totals
		till = session.get(POSTill, txn.till_id)
		if till is not None:
			till.total_sales_cents = max(0, till.total_sales_cents - original_total)
			till.expected_closing_cents = (
				till.opening_float_cents + till.total_sales_cents - till.total_returns_cents
			)

		# Reverse GL entries
		try:
			from pgappforge.plugins.erp.finance.gl.services import GLService
			gl = GLService()
			_METHOD_ACCOUNT = {"CASH": "1011", "CARD": "1012", "MPESA": "1013", "VOUCHER": "1014", "CREDIT": "1200"}
			gl_lines: list[dict[str, Any]] = []
			for po in txn.payments:
				acct = _METHOD_ACCOUNT.get(po.payment_method, "1011")
				gl_lines.append({"account": acct, "debit": 0, "credit": po.amount_cents, "description": f"Void reversal {po.payment_method}"})
			revenue_base = txn.subtotal_cents - txn.discount_cents
			gl_lines.append({"account": "4000", "debit": revenue_base, "credit": 0, "description": "Void sales revenue reversal"})
			if txn.tax_cents > 0:
				gl_lines.append({"account": "2300", "debit": txn.tax_cents, "credit": 0, "description": "Void VAT reversal"})
			gl.post_journal(
				{
					"tenant_id": tenant_id,
					"description": f"Void {txn.receipt_number} reason={void_reason}",
					"reference": f"VOID-{txn.receipt_number}",
					"lines": gl_lines,
				},
				session=session,
			)
		except Exception as exc:
			log.debug("GL post skipped: %s", exc)

		session.flush()

		emit_event(
			TransactionVoidedEvent(
				aggregate_id=txn_id,
				aggregate_type="POSTransaction",
				tenant_id=tenant_id,
				transaction_id=txn_id,
				till_id=txn.till_id,
				void_reason=void_reason,
				original_total_cents=original_total,
			),
			session,
		)
		log.info("Voided transaction %r reason=%r", txn.receipt_number, void_reason)
		return txn

	# ------------------------------------------------------------------ #
	# Process return
	# ------------------------------------------------------------------ #

	def process_return(
		self,
		session: Any,
		original_txn_id: str,
		returned_lines: list[dict[str, Any]],
		refund_method: str,
		tenant_id: str,
	) -> Any:
		"""Create a RETURN transaction against an original sale.

		Each returned_line: {product_code, qty, unit_price_cents, discount_cents?, tax_rate_pct?}
		The refund is issued via refund_method (CASH | CARD | MPESA | VOUCHER | CREDIT).

		Reverses revenue and tax GL entries for the returned lines.
		Emits ReturnProcessedEvent.

		Returns the new RETURN POSTransaction.
		"""
		from pgappforge.plugins.erp.crm.pos.models import (
			POSPayment,
			POSTransaction,
			POSTransactionLine,
			POSTill,
		)
		from pgappforge.plugins.erp.crm.pos.events import ReturnProcessedEvent, emit_event

		assert returned_lines, "returned_lines must not be empty"
		assert refund_method, "refund_method is required"

		original = session.get(POSTransaction, original_txn_id)
		if original is None:
			raise TransactionNotFoundError(f"POSTransaction {original_txn_id!r} not found")
		if original.status not in ("COMPLETED",):
			raise TransactionStatusError(
				f"Cannot return against transaction in status {original.status!r}"
			)

		till = session.get(POSTill, original.till_id)
		if till is None:
			raise TillNotFoundError(f"POSTill {original.till_id!r} not found")

		subtotal = 0
		total_discount = 0
		total_tax = 0
		line_objects: list[POSTransactionLine] = []

		for raw in returned_lines:
			qty = Decimal(str(raw["qty"]))
			unit_price = int(raw["unit_price_cents"])
			discount = int(raw.get("discount_cents", 0))
			tax_rate = Decimal(str(raw.get("tax_rate_pct", 0)))

			gross = int((qty * Decimal(unit_price)).to_integral_value(ROUND_HALF_UP))
			net_before_tax = gross - discount
			tax = int((Decimal(net_before_tax) * tax_rate / Decimal("100")).to_integral_value(ROUND_HALF_UP))
			line_total = net_before_tax + tax

			subtotal += gross
			total_discount += discount
			total_tax += tax

			line_objects.append(POSTransactionLine(
				tenant_id=tenant_id,
				product_code=raw["product_code"],
				description=raw.get("description", raw["product_code"]),
				quantity=qty,
				unit_price_cents=unit_price,
				discount_cents=discount,
				tax_rate_pct=tax_rate,
				tax_cents=tax,
				line_total_cents=line_total,
			))

		refund_total = subtotal - total_discount + total_tax
		receipt_number = self._generate_receipt_number(session, till.till_code, prefix="RET")
		now = datetime.now(timezone.utc)

		return_txn = POSTransaction(
			tenant_id=tenant_id,
			till_id=original.till_id,
			transaction_type="RETURN",
			receipt_number=receipt_number,
			transaction_at=now,
			cashier_id=original.cashier_id,
			subtotal_cents=subtotal,
			discount_cents=total_discount,
			tax_cents=total_tax,
			total_cents=refund_total,
			status="COMPLETED",
			customer_id=original.customer_id,
		)
		session.add(return_txn)
		session.flush()

		for lo in line_objects:
			lo.txn_id = return_txn.id
			session.add(lo)

		refund_payment = POSPayment(
			tenant_id=tenant_id,
			txn_id=return_txn.id,
			payment_method=refund_method,
			amount_cents=refund_total,
			status="COMPLETED",
		)
		session.add(refund_payment)

		original.status = "REFUNDED"

		till.total_returns_cents += refund_total
		till.expected_closing_cents = (
			till.opening_float_cents + till.total_sales_cents - till.total_returns_cents
		)

		# Reverse revenue + tax GL
		try:
			from pgappforge.plugins.erp.finance.gl.services import GLService
			gl = GLService()
			_METHOD_ACCOUNT = {"CASH": "1011", "CARD": "1012", "MPESA": "1013", "VOUCHER": "1014", "CREDIT": "1200"}
			refund_acct = _METHOD_ACCOUNT.get(refund_method, "1011")
			gl_lines: list[dict[str, Any]] = [
				{"account": "4000", "debit": subtotal - total_discount, "credit": 0, "description": "Return revenue reversal"},
			]
			if total_tax > 0:
				gl_lines.append({"account": "2300", "debit": total_tax, "credit": 0, "description": "Return VAT reversal"})
			gl_lines.append({"account": refund_acct, "debit": 0, "credit": refund_total, "description": f"Refund via {refund_method}"})
			gl.post_journal(
				{
					"tenant_id": tenant_id,
					"description": f"POS return {receipt_number} for {original.receipt_number}",
					"reference": receipt_number,
					"lines": gl_lines,
				},
				session=session,
			)
		except Exception as exc:
			log.debug("GL post skipped: %s", exc)

		session.flush()

		emit_event(
			ReturnProcessedEvent(
				aggregate_id=return_txn.id,
				aggregate_type="POSTransaction",
				tenant_id=tenant_id,
				return_txn_id=return_txn.id,
				original_txn_id=original_txn_id,
				till_id=original.till_id,
				refund_cents=refund_total,
				refund_method=refund_method,
			),
			session,
		)
		log.info(
			"Return %r refund=%d method=%r original=%r",
			receipt_number, refund_total, refund_method, original.receipt_number,
		)
		return return_txn

	# ------------------------------------------------------------------ #
	# Close till
	# ------------------------------------------------------------------ #

	def close_till(
		self,
		session: Any,
		till_id: str,
		actual_cash_cents: int,
		closed_by: str,
		tenant_id: str,
	) -> Any:
		"""Close a till shift and create a reconciliation record.

		Computes variance = actual_cash - expected_cash.
		Status RECONCILED if variance == 0, else DISCREPANCY.

		GL:
		  DR  Cash        1011  (actual cash banked)
		  CR  POS_float   1013  (close out float account)

		Emits TillClosedEvent. Returns POSShiftReconciliation.
		"""
		from pgappforge.plugins.erp.crm.pos.models import POSShiftReconciliation, POSTransaction, POSTill
		from pgappforge.plugins.erp.crm.pos.events import TillClosedEvent, emit_event

		assert actual_cash_cents >= 0, "actual_cash_cents must be non-negative"
		assert closed_by, "closed_by is required"

		till = session.get(POSTill, till_id)
		if till is None:
			raise TillNotFoundError(f"POSTill {till_id!r} not found")
		if till.status != "OPEN":
			raise TillStatusError(f"Till {till.till_code!r} is not open")

		today = date.today()

		from pgappforge.plugins.erp.crm.pos.models import POSPayment
		card_total = session.execute(
			sa.select(sa.func.coalesce(sa.func.sum(POSPayment.amount_cents), 0))
			.join(POSTransaction, POSTransaction.id == POSPayment.txn_id)
			.where(POSTransaction.till_id == till_id)
			.where(POSTransaction.status == "COMPLETED")
			.where(POSTransaction.transaction_at >= till.opened_at)
			.where(POSPayment.payment_method == "CARD")
			.where(POSPayment.status == "COMPLETED")
		).scalar_one()

		mpesa_total = session.execute(
			sa.select(sa.func.coalesce(sa.func.sum(POSPayment.amount_cents), 0))
			.join(POSTransaction, POSTransaction.id == POSPayment.txn_id)
			.where(POSTransaction.till_id == till_id)
			.where(POSTransaction.status == "COMPLETED")
			.where(POSTransaction.transaction_at >= till.opened_at)
			.where(POSPayment.payment_method == "MPESA")
			.where(POSPayment.status == "COMPLETED")
		).scalar_one()

		txn_count = session.execute(
			sa.select(sa.func.count(POSTransaction.id))
			.where(POSTransaction.till_id == till_id)
			.where(POSTransaction.status == "COMPLETED")
			.where(POSTransaction.transaction_at >= till.opened_at)
		).scalar_one()

		expected_cash = till.expected_closing_cents
		variance = actual_cash_cents - expected_cash
		status = "RECONCILED" if variance == 0 else "DISCREPANCY"

		recon = POSShiftReconciliation(
			tenant_id=tenant_id,
			till_id=till_id,
			shift_date=today,
			opened_by=till.cashier_id or closed_by,
			closed_by=closed_by,
			opening_float_cents=till.opening_float_cents,
			expected_cash_cents=expected_cash,
			actual_cash_cents=actual_cash_cents,
			variance_cents=variance,
			card_total_cents=card_total,
			mpesa_total_cents=mpesa_total,
			transaction_count=txn_count,
			status=status,
		)
		session.add(recon)

		till.status = "CLOSED"
		till.cashier_id = None

		try:
			from pgappforge.plugins.erp.finance.gl.services import GLService
			gl = GLService()
			gl.post_journal(
				{
					"tenant_id": tenant_id,
					"description": f"Till close {till.till_code} {today}",
					"reference": f"TILL-CLOSE-{till.till_code}-{today}",
					"lines": [
						{"account": "1011", "debit": actual_cash_cents, "credit": 0, "description": "Cash banked"},
						{"account": "1013", "debit": 0, "credit": actual_cash_cents, "description": "POS float cleared"},
					],
				},
				session=session,
			)
		except Exception as exc:
			log.debug("GL post skipped: %s", exc)

		session.flush()

		emit_event(
			TillClosedEvent(
				aggregate_id=till_id,
				aggregate_type="POSTill",
				tenant_id=tenant_id,
				till_id=till_id,
				till_code=till.till_code,
				closed_by=closed_by,
				variance_cents=variance,
				transaction_count=txn_count,
				reconciliation_id=recon.id,
			),
			session,
		)
		log.info(
			"Closed till %r variance=%d txn_count=%d status=%r",
			till.till_code, variance, txn_count, status,
		)
		return recon

	# ------------------------------------------------------------------ #
	# Sales report
	# ------------------------------------------------------------------ #

	def get_sales_report(
		self,
		session: Any,
		till_id: str | None = None,
		from_dt: datetime | None = None,
		to_dt: datetime | None = None,
		tenant_id: str = "",
	) -> dict[str, Any]:
		"""Return aggregated sales report.

		Result:
		  {
		    total_sales_cents,
		    transaction_count,
		    avg_basket_cents,
		    by_payment_method: {method: amount_cents},
		    top_products: [{product_code, description, qty, revenue_cents}],
		    voids_count,
		  }
		"""
		from pgappforge.plugins.erp.crm.pos.models import POSPayment, POSTransaction, POSTransactionLine

		q_base = (
			sa.select(POSTransaction)
			.where(POSTransaction.status == "COMPLETED")
			.where(POSTransaction.transaction_type == "SALE")
		)
		if tenant_id:
			q_base = q_base.where(POSTransaction.tenant_id == tenant_id)
		if till_id:
			q_base = q_base.where(POSTransaction.till_id == till_id)
		if from_dt:
			q_base = q_base.where(POSTransaction.transaction_at >= from_dt)
		if to_dt:
			q_base = q_base.where(POSTransaction.transaction_at <= to_dt)

		txns = session.execute(q_base).scalars().all()
		txn_ids = [t.id for t in txns]

		total_sales = sum(t.total_cents for t in txns)
		count = len(txns)
		avg_basket = total_sales // count if count else 0

		# By payment method
		by_method: dict[str, int] = {}
		if txn_ids:
			rows = session.execute(
				sa.select(POSPayment.payment_method, sa.func.sum(POSPayment.amount_cents))
				.where(POSPayment.txn_id.in_(txn_ids))
				.where(POSPayment.status == "COMPLETED")
				.group_by(POSPayment.payment_method)
			).all()
			by_method = {r[0]: int(r[1]) for r in rows}

		# Top products
		top_products: list[dict[str, Any]] = []
		if txn_ids:
			prod_rows = session.execute(
				sa.select(
					POSTransactionLine.product_code,
					POSTransactionLine.description,
					sa.func.sum(POSTransactionLine.quantity).label("total_qty"),
					sa.func.sum(POSTransactionLine.line_total_cents).label("total_revenue"),
				)
				.where(POSTransactionLine.txn_id.in_(txn_ids))
				.group_by(POSTransactionLine.product_code, POSTransactionLine.description)
				.order_by(sa.desc("total_revenue"))
				.limit(10)
			).all()
			top_products = [
				{
					"product_code": r[0],
					"description": r[1],
					"qty": float(r[2]),
					"revenue_cents": int(r[3]),
				}
				for r in prod_rows
			]

		# Voids count
		voids_q = sa.select(sa.func.count(POSTransaction.id)).where(
			POSTransaction.status == "VOIDED"
		)
		if tenant_id:
			voids_q = voids_q.where(POSTransaction.tenant_id == tenant_id)
		if till_id:
			voids_q = voids_q.where(POSTransaction.till_id == till_id)
		if from_dt:
			voids_q = voids_q.where(POSTransaction.transaction_at >= from_dt)
		if to_dt:
			voids_q = voids_q.where(POSTransaction.transaction_at <= to_dt)
		voids_count = session.execute(voids_q).scalar_one()

		return {
			"total_sales_cents": total_sales,
			"transaction_count": count,
			"avg_basket_cents": avg_basket,
			"by_payment_method": by_method,
			"top_products": top_products,
			"voids_count": voids_count,
		}

	# ------------------------------------------------------------------ #
	# Internal helpers
	# ------------------------------------------------------------------ #

	def _generate_receipt_number(self, session: Any, till_code: str, prefix: str = "RCP") -> str:
		"""Generate a sequential receipt number for a till."""
		from pgappforge.plugins.erp.crm.pos.models import POSTransaction
		count = session.execute(
			sa.select(sa.func.count(POSTransaction.id))
		).scalar_one()
		ts = datetime.now(timezone.utc).strftime("%Y%m%d")
		return f"{prefix}-{till_code}-{ts}-{count + 1:05d}"


__all__ = [
	"POSService",
	"POSServiceError",
	"TillNotFoundError",
	"TillStatusError",
	"TransactionNotFoundError",
	"TransactionStatusError",
	"PaymentMismatchError",
]
