"""
pgappforge/plugins/erp/finance/ap/services.py

APService — stateless business logic for the Accounts Payable plugin.

All methods receive an explicit SQLAlchemy session; no Flask context assumed.
Transaction boundaries are owned by the caller.

Monetary invariants enforced throughout:
  - All amounts passed in and returned as integer cents (kobo, fils, etc.)
  - Decimal arithmetic used internally for multiplication; result rounded
    half-up to int before storing or returning
  - exchange_rate columns read as Decimal(str(row.exchange_rate)) — never float

Key public methods:
  match_invoice(invoice_id, session)             -> APInvoice
  create_payment_run(supplier_ids, value_date, session) -> APPaymentRun
  reconcile_supplier_statement(supplier_id, lines, session) -> dict
  early_payment_discount(invoice_id, session)    -> int  (cents)
  post_to_gl(invoice_id, session)               -> dict  (GL journal)
  post_grn(grn_id, session)                     -> APGoodsReceipt
  approve_invoice(invoice_id, approver_id, session) -> APInvoice
  apply_payment(invoice_id, payment_id, session) -> APInvoice
"""
from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import sqlalchemy as sa

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class APServiceError(Exception):
	"""Base domain error for AP operations."""


class APSupplierNotFoundError(APServiceError):
	pass


class APInvoiceNotFoundError(APServiceError):
	pass


class APMatchError(APServiceError):
	"""Raised when invoice match fails tolerance checks."""


class APWorkflowError(APServiceError):
	"""Raised for invalid approval workflow transitions."""


class APPaymentError(APServiceError):
	pass


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _cents(decimal_qty: Decimal, unit_cost_cents: int) -> int:
	"""Multiply quantity (Decimal) × unit cost (int cents), round half-up."""
	assert isinstance(unit_cost_cents, int), "unit_cost_cents must be int"
	result = decimal_qty * Decimal(unit_cost_cents)
	return int(result.to_integral_value(rounding=ROUND_HALF_UP))


def _today() -> date:
	return datetime.now(timezone.utc).date()


def _iso20022_pain001(run: Any, payments: list[Any]) -> str:
	"""Generate a minimal ISO 20022 pain.001.001.03 Credit Transfer XML.

	This is a structural skeleton — production use requires a certified
	library (e.g. schwifty + lxml) and bank-specific customisations.
	"""
	lines: list[str] = [
		'<?xml version="1.0" encoding="UTF-8"?>',
		'<Document xmlns="urn:iso:std:iso:20022:tech:xsd:pain.001.001.03">',
		'  <CstmrCdtTrfInitn>',
		'    <GrpHdr>',
		f'      <MsgId>{run.run_number}</MsgId>',
		f'      <CreDtTm>{datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")}</CreDtTm>',
		f'      <NbOfTxs>{run.total_payments}</NbOfTxs>',
		f'      <CtrlSum>{Decimal(run.total_amount_cents) / 100:.2f}</CtrlSum>',
		'      <InitgPty><Nm>PgAppForge AP</Nm></InitgPty>',
		'    </GrpHdr>',
		'    <PmtInf>',
		f'      <PmtInfId>{run.run_number}-PMT</PmtInfId>',
		'      <PmtMtd>TRF</PmtMtd>',
		f'      <ReqdExctnDt>{run.value_date.isoformat()}</ReqdExctnDt>',
		'      <DbtrAcct>',
		f'        <Id><IBAN>{run.bank_account or "UNKNOWN"}</IBAN></Id>',
		'      </DbtrAcct>',
		'      <DbtrAgt>',
		f'        <FinInstnId><BIC>{run.bic or "UNKNOWN"}</BIC></FinInstnId>',
		'      </DbtrAgt>',
	]
	for pmt in payments:
		amount_dec = Decimal(pmt.amount_cents) / 100
		uetr = pmt.uetr or str(uuid.uuid4())
		sup = pmt.supplier
		lines += [
			'      <CdtTrfTxInf>',
			'        <PmtId>',
			f'          <EndToEndId>{uetr}</EndToEndId>',
			'        </PmtId>',
			'        <Amt>',
			f'          <InstdAmt Ccy="{pmt.currency_code}">{amount_dec:.2f}</InstdAmt>',
			'        </Amt>',
			'        <CdtrAgt>',
			f'          <FinInstnId><BIC>{sup.bank_bic or "NOTPROVIDED"}</BIC></FinInstnId>',
			'        </CdtrAgt>',
			'        <Cdtr>',
			f'          <Nm>{sup.bank_account_name or sup.name}</Nm>',
			'        </Cdtr>',
			'        <CdtrAcct>',
			f'          <Id><IBAN>{sup.bank_account_iban or "NOTPROVIDED"}</IBAN></Id>',
			'        </CdtrAcct>',
			'      </CdtTrfTxInf>',
		]
	lines += [
		'    </PmtInf>',
		'  </CstmrCdtTrfInitn>',
		'</Document>',
	]
	return "\n".join(lines)


# ---------------------------------------------------------------------------
# APService
# ---------------------------------------------------------------------------

class APService:
	"""Stateless AP domain service.

	Instantiate once per application (no instance state).
	All public methods accept a SQLAlchemy Session as an explicit argument.
	"""

	# ------------------------------------------------------------------
	# Invoice matching
	# ------------------------------------------------------------------

	def match_invoice(self, invoice_id: str, session: Any) -> Any:
		"""Perform 2-way or 3-way match on an invoice.

		2-way match (PO available): verifies invoice line quantities/amounts
		are within tolerance vs. PO lines (±5% or ±500 cents, whichever is
		greater).

		3-way match (PO + GRN available): additionally verifies that GRN
		accepted quantities cover the invoiced quantities.

		On success, sets:
		  - APInvoice.match_status = "2WAY" | "3WAY"
		  - APInvoice.status = "MATCHING" → emits InvoiceMatchedEvent
		  - APPOLine.quantity_invoiced incremented per line

		On failure, sets match_status = "EXCEPTION" and returns the invoice
		with exceptions captured in metadata_.

		Args:
			invoice_id: UUID of the APInvoice to match.
			session: SQLAlchemy session (caller commits).

		Returns:
			Updated APInvoice instance.

		Raises:
			APInvoiceNotFoundError: Invoice not found.
			APMatchError: Structural preconditions not met (e.g. PO closed).
		"""
		from pgappforge.plugins.erp.finance.ap.models import APInvoice, APPOLine
		from pgappforge.plugins.erp.finance.ap.events import InvoiceMatchedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		invoice = session.get(APInvoice, invoice_id)
		if invoice is None:
			raise APInvoiceNotFoundError(f"APInvoice {invoice_id!r} not found")

		if invoice.status in ("PAID", "CANCELLED"):
			raise APMatchError(f"Cannot match invoice in status {invoice.status!r}")

		exceptions: list[dict] = []
		match_type = "UNMATCHED"

		# ---- 2-way match: against PO ----
		if invoice.po_id:
			po = invoice.purchase_order
			if po is None:
				raise APMatchError(f"PO {invoice.po_id!r} not found for invoice {invoice_id!r}")
			if po.status in ("CANCELLED", "CLOSED"):
				raise APMatchError(f"PO {po.po_number!r} is {po.status!r}; cannot match invoice")

			for inv_line in invoice.lines:
				if inv_line.po_line_id is None:
					exceptions.append({
						"line": inv_line.line_number,
						"issue": "no_po_line_linked",
					})
					continue

				po_line = session.get(APPOLine, inv_line.po_line_id)
				if po_line is None:
					exceptions.append({"line": inv_line.line_number, "issue": "po_line_not_found"})
					continue

				# Quantity tolerance: invoiced qty ≤ ordered qty × 1.05
				ordered = Decimal(str(po_line.quantity))
				already_invoiced = Decimal(str(po_line.quantity_invoiced))
				this_line_qty = Decimal(str(inv_line.quantity or 0))
				if already_invoiced + this_line_qty > ordered * Decimal("1.05"):
					exceptions.append({
						"line": inv_line.line_number,
						"issue": "quantity_over_tolerance",
						"ordered": str(ordered),
						"invoiced_before": str(already_invoiced),
						"this_invoice": str(this_line_qty),
					})
					continue

				# Price tolerance: ±5% or ±500 cents
				po_cost = po_line.unit_cost_cents
				inv_cost = inv_line.unit_cost_cents or po_cost
				diff = abs(inv_cost - po_cost)
				tolerance = max(int(po_cost * Decimal("0.05")), 500)
				if diff > tolerance:
					exceptions.append({
						"line": inv_line.line_number,
						"issue": "price_outside_tolerance",
						"po_cost_cents": po_cost,
						"inv_cost_cents": inv_cost,
						"diff_cents": diff,
						"tolerance_cents": tolerance,
					})
					continue

			match_type = "2WAY"

		# ---- 3-way match: additionally check GRN ----
		if invoice.grn_id and match_type == "2WAY":
			grn = invoice.goods_receipt
			if grn is None:
				exceptions.append({"issue": "grn_not_found", "grn_id": invoice.grn_id})
			elif grn.status not in ("CONFIRMED", "POSTED"):
				exceptions.append({"issue": "grn_not_confirmed", "grn_status": grn.status})
			else:
				# Verify each invoice line qty ≤ GRN accepted qty
				for inv_line in invoice.lines:
					if inv_line.grn_line_id is None:
						continue
					grn_line = next(
						(l for l in grn.lines if l.id == inv_line.grn_line_id), None
					)
					if grn_line is None:
						exceptions.append({"line": inv_line.line_number, "issue": "grn_line_not_found"})
						continue
					accepted = Decimal(str(grn_line.quantity_accepted or 0))
					inv_qty = Decimal(str(inv_line.quantity or 0))
					if inv_qty > accepted * Decimal("1.02"):
						exceptions.append({
							"line": inv_line.line_number,
							"issue": "qty_exceeds_grn_accepted",
							"accepted": str(accepted),
							"invoiced": str(inv_qty),
						})
				if not any(e.get("issue", "").startswith("qty_exceeds") or e.get("issue") in ("grn_not_found", "grn_not_confirmed") for e in exceptions):
					match_type = "3WAY"

		# ---- Apply result ----
		if exceptions:
			invoice.match_status = "EXCEPTION"
			invoice.metadata_ = {**invoice.metadata_, "match_exceptions": exceptions}
			log.warning(
				"APService.match_invoice: %d exception(s) on invoice %s",
				len(exceptions), invoice_id,
			)
		else:
			invoice.match_status = match_type
			invoice.status = "MATCHING"
			invoice.metadata_ = {k: v for k, v in invoice.metadata_.items() if k != "match_exceptions"}

			# Update PO line quantity_invoiced
			if invoice.po_id:
				for inv_line in invoice.lines:
					if inv_line.po_line_id:
						po_line = session.get(APPOLine, inv_line.po_line_id)
						if po_line is not None:
							po_line.quantity_invoiced = (
								Decimal(str(po_line.quantity_invoiced))
								+ Decimal(str(inv_line.quantity or 0))
							)

			emit_event(
				InvoiceMatchedEvent(
					aggregate_id=invoice.id,
					aggregate_type="APInvoice",
					tenant_id=invoice.tenant_id,
					invoice_id=invoice.id,
					supplier_id=invoice.supplier_id,
					match_type=match_type,
					total_cents=invoice.total_cents,
					currency=invoice.currency_code,
					po_id=invoice.po_id or "",
					grn_id=invoice.grn_id or "",
				),
				session,
			)

		invoice.updated_at = datetime.now(timezone.utc)
		return invoice

	# ------------------------------------------------------------------
	# Payment run
	# ------------------------------------------------------------------

	def create_payment_run(
		self,
		supplier_ids: list[str],
		value_date: date,
		session: Any,
		tenant_id: str = "",
		bank_account: str = "",
		bic: str = "",
		currency_code: str = "USD",
	) -> Any:
		"""Create an APPaymentRun for the given suppliers, selecting all due invoices.

		Selects all APInvoice rows with:
		  - supplier_id in supplier_ids
		  - status = APPROVED
		  - due_date <= value_date
		  - paid_cents < total_cents

		Applies early payment discount if applicable.
		Generates ISO 20022 pain.001.001.03 XML in run.iso20022_xml.
		Sets invoice.payment_run_id and status = PAYMENT_SCHEDULED.

		Args:
			supplier_ids: UUIDs of suppliers to include.
			value_date: Bank settlement date.
			session: SQLAlchemy session.
			tenant_id: Tenant scope.
			bank_account: Company bank IBAN.
			bic: Company bank BIC.
			currency_code: Run currency (homogeneous runs only).

		Returns:
			APPaymentRun instance (not yet committed).

		Raises:
			APPaymentError: When no eligible invoices found.
		"""
		from pgappforge.plugins.erp.finance.ap.models import (
			APInvoice, APPayment, APPaymentRun,
		)
		from pgappforge.plugins.erp.finance.ap.events import PaymentInitiatedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		assert isinstance(value_date, date), "value_date must be a date"
		assert supplier_ids, "supplier_ids must be non-empty"

		# Select eligible invoices
		q = (
			sa.select(APInvoice)
			.where(APInvoice.supplier_id.in_(supplier_ids))
			.where(APInvoice.status == "APPROVED")
			.where(APInvoice.due_date <= value_date)
			.where(APInvoice.currency_code == currency_code)
			.order_by(APInvoice.due_date)
		)
		if tenant_id:
			q = q.where(APInvoice.tenant_id == tenant_id)

		invoices = session.execute(q).scalars().all()
		eligible = [
			inv for inv in invoices
			if inv.paid_cents < inv.total_cents
		]

		if not eligible:
			raise APPaymentError(
				f"No eligible APPROVED invoices due on or before {value_date} "
				f"for {len(supplier_ids)} supplier(s)"
			)

		# Generate run number
		run_number = f"PAY-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"

		run = APPaymentRun(
			tenant_id=tenant_id,
			run_number=run_number,
			run_date=_today(),
			value_date=value_date,
			bank_account=bank_account,
			bic=bic,
			currency_code=currency_code,
			status="DRAFT",
		)
		session.add(run)
		session.flush()  # populate run.id

		payments: list[Any] = []
		total_cents = 0

		for inv in eligible:
			discount = self.early_payment_discount(inv.id, session, _reference_date=value_date)
			pay_amount = (inv.total_cents - inv.paid_cents) - discount
			assert isinstance(pay_amount, int), "pay_amount must be int"

			if pay_amount <= 0:
				continue

			uetr = str(uuid.uuid4())
			pmt = APPayment(
				tenant_id=tenant_id,
				payment_run_id=run.id,
				supplier_id=inv.supplier_id,
				invoice_id=inv.id,
				payment_date=value_date,
				amount_cents=pay_amount,
				currency_code=currency_code,
				exchange_rate=inv.exchange_rate,
				uetr=uetr,
				status="PENDING",
			)
			session.add(pmt)
			payments.append(pmt)
			total_cents += pay_amount

			if discount > 0:
				inv.early_payment_discount_taken_cents = (
					inv.early_payment_discount_taken_cents + discount
				)

			inv.payment_run_id = run.id
			inv.status = "PAYMENT_SCHEDULED"
			inv.updated_at = datetime.now(timezone.utc)

		if not payments:
			raise APPaymentError("All eligible invoices resulted in zero payment amounts")

		run.total_payments = len(payments)
		run.total_amount_cents = total_cents

		# Flush to populate payment PKs before XML generation
		session.flush()

		# Attach supplier objects (needed by XML generator)
		for pmt in payments:
			_ = pmt.supplier  # trigger lazy load

		run.iso20022_xml = _iso20022_pain001(run, payments)

		emit_event(
			PaymentInitiatedEvent(
				aggregate_id=run.id,
				aggregate_type="APPaymentRun",
				tenant_id=tenant_id,
				payment_run_id=run.id,
				run_number=run_number,
				total_payments=run.total_payments,
				total_amount_cents=total_cents,
				currency=currency_code,
				value_date=value_date.isoformat(),
				iso20022_ref=run.payment_file_ref or "",
			),
			session,
		)

		log.info(
			"APService.create_payment_run: run=%s payments=%d total=%d¢",
			run_number, run.total_payments, total_cents,
		)
		return run

	# ------------------------------------------------------------------
	# Early payment discount
	# ------------------------------------------------------------------

	def early_payment_discount(
		self,
		invoice_id: str,
		session: Any,
		_reference_date: date | None = None,
	) -> int:
		"""Return the early payment discount in cents applicable today.

		Returns 0 if:
		  - Supplier is not dynamic_discounting_eligible
		  - Payment date is beyond early_payment_days from invoice_date
		  - Discount already taken (early_payment_discount_taken_cents > 0)

		Args:
			invoice_id: UUID of the APInvoice.
			session: SQLAlchemy session.
			_reference_date: Override today's date (for testing / payment run).

		Returns:
			Integer cents discount available; 0 if not applicable.
		"""
		from pgappforge.plugins.erp.finance.ap.models import APInvoice

		invoice = session.get(APInvoice, invoice_id)
		if invoice is None:
			raise APInvoiceNotFoundError(f"APInvoice {invoice_id!r} not found")

		supplier = invoice.supplier
		if not supplier.dynamic_discounting_eligible:
			return 0
		if invoice.early_payment_discount_taken_cents > 0:
			return 0

		ref_date = _reference_date or _today()
		invoice_dt = invoice.invoice_date
		if isinstance(invoice_dt, datetime):
			invoice_dt = invoice_dt.date()

		days_elapsed = (ref_date - invoice_dt).days
		if days_elapsed > supplier.early_payment_days:
			return 0

		pct = Decimal(str(supplier.early_payment_discount_pct))
		outstanding = invoice.total_cents - invoice.paid_cents
		discount = int(
			(Decimal(outstanding) * pct / Decimal("100"))
			.to_integral_value(rounding=ROUND_HALF_UP)
		)
		return max(0, discount)

	# ------------------------------------------------------------------
	# GL posting
	# ------------------------------------------------------------------

	def post_to_gl(self, invoice_id: str, session: Any) -> dict[str, Any]:
		"""Create double-entry GL journal for an approved invoice.

		Journal:
		  DR  gl_expense_account  (per invoice line)
		  CR  gl_payable_account  (AP control account from supplier)

		This is a pure service method — it constructs the journal dict and
		emits InvoicePostedToGLEvent.  The GL plugin consumes the event and
		writes the actual GLJournalLine rows.  If no GL plugin is loaded,
		the journal dict is returned for the caller to handle.

		Args:
			invoice_id: UUID of APInvoice (must be status APPROVED).
			session: SQLAlchemy session.

		Returns:
			Dict with journal_id, debit_lines, credit_line.

		Raises:
			APInvoiceNotFoundError: Invoice not found.
			APWorkflowError: Invoice not in APPROVED status.
		"""
		from pgappforge.plugins.erp.finance.ap.models import APInvoice
		from pgappforge.plugins.erp.finance.ap.events import InvoicePostedToGLEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		invoice = session.get(APInvoice, invoice_id)
		if invoice is None:
			raise APInvoiceNotFoundError(f"APInvoice {invoice_id!r} not found")

		if invoice.approval_status != "APPROVED":
			raise APWorkflowError(
				f"Invoice {invoice_id!r} has approval_status={invoice.approval_status!r}; "
				"must be APPROVED before GL posting"
			)

		payable_account = (
			invoice.gl_payable_account
			or invoice.supplier.gl_payable_account
			or "2000"  # default AP control account
		)

		# Build debit lines per expense account
		expense_totals: dict[str, int] = {}
		for line in invoice.lines:
			acct = line.gl_expense_account or "5000"  # default expense
			expense_totals[acct] = expense_totals.get(acct, 0) + line.line_amount_cents + line.tax_cents

		debit_lines = [
			{
				"account": acct,
				"amount_cents": amt,
				"description": f"AP Invoice {invoice.invoice_number_supplier}",
			}
			for acct, amt in expense_totals.items()
		]
		total_debit = sum(d["amount_cents"] for d in debit_lines)

		journal = {
			"journal_id": str(uuid.uuid4()),
			"invoice_id": invoice_id,
			"tenant_id": invoice.tenant_id,
			"currency": invoice.currency_code,
			"exchange_rate": str(invoice.exchange_rate),
			"journal_date": invoice.invoice_date.isoformat() if hasattr(invoice.invoice_date, "isoformat") else str(invoice.invoice_date),
			"debit_lines": debit_lines,
			"credit_line": {
				"account": payable_account,
				"amount_cents": total_debit,
				"description": f"AP Payable — {invoice.supplier.name} inv {invoice.invoice_number_supplier}",
			},
		}

		# Forward to GL plugin if loaded (best-effort)
		try:
			from flask import current_app
			gl = current_app.extensions.get("pgaf_gl")
			if gl is not None:
				gl.post_journal(journal)
		except Exception as exc:
			log.debug("APService.post_to_gl: GL plugin not available (%s)", exc)

		emit_event(
			InvoicePostedToGLEvent(
				aggregate_id=invoice_id,
				aggregate_type="APInvoice",
				tenant_id=invoice.tenant_id,
				invoice_id=invoice_id,
				supplier_id=invoice.supplier_id,
				debit_account=next(iter(expense_totals), "5000"),
				credit_account=payable_account,
				amount_cents=total_debit,
				currency=invoice.currency_code,
			),
			session,
		)

		log.info(
			"APService.post_to_gl: invoice=%s journal=%s total=%d¢",
			invoice_id, journal["journal_id"], total_debit,
		)
		return journal

	# ------------------------------------------------------------------
	# Supplier statement reconciliation
	# ------------------------------------------------------------------

	def reconcile_supplier_statement(
		self,
		supplier_id: str,
		statement_lines: list[dict],
		session: Any,
	) -> dict[str, Any]:
		"""Reconcile a supplier's paper/portal statement against AP ledger.

		Each statement_line dict should contain:
		  {
		    "invoice_number": str,   # supplier's invoice number
		    "invoice_date": str,     # ISO date
		    "amount_cents": int,     # statement amount (integer cents)
		    "currency": str,
		  }

		Matching strategy:
		  1. Exact match on invoice_number_supplier + supplier_id
		  2. Tolerance check: abs(statement - ledger) ≤ max(1% of ledger, 100 cents)

		Returns:
		  {
		    "matched": [{"invoice_id", "invoice_number", "ledger_cents", "statement_cents"}],
		    "unmatched_statement": [statement_lines with no ledger match],
		    "unmatched_ledger": [open AP invoices with no statement line],
		    "disputed": [items outside tolerance],
		    "net_difference_cents": int,
		  }

		Emits SupplierStatementReconciledEvent.
		"""
		from pgappforge.plugins.erp.finance.ap.models import APInvoice, APSupplier
		from pgappforge.plugins.erp.finance.ap.events import SupplierStatementReconciledEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		supplier = session.get(APSupplier, supplier_id)
		if supplier is None:
			raise APSupplierNotFoundError(f"APSupplier {supplier_id!r} not found")

		# Fetch all open invoices for this supplier
		open_invoices = session.execute(
			sa.select(APInvoice)
			.where(APInvoice.supplier_id == supplier_id)
			.where(APInvoice.status.notin_(["PAID", "CANCELLED"]))
		).scalars().all()

		ledger_by_number: dict[str, Any] = {
			inv.invoice_number_supplier: inv for inv in open_invoices
		}

		matched: list[dict] = []
		unmatched_statement: list[dict] = []
		disputed: list[dict] = []
		matched_invoice_ids: set[str] = set()

		for stmt in statement_lines:
			inv_num = str(stmt.get("invoice_number", ""))
			stmt_cents = int(stmt.get("amount_cents", 0))
			assert isinstance(stmt_cents, int), "statement amount_cents must be int"

			invoice = ledger_by_number.get(inv_num)
			if invoice is None:
				unmatched_statement.append(stmt)
				continue

			outstanding = invoice.total_cents - invoice.paid_cents
			diff = abs(stmt_cents - outstanding)
			tolerance = max(int(outstanding * Decimal("0.01")), 100)

			if diff <= tolerance:
				matched.append({
					"invoice_id": invoice.id,
					"invoice_number": inv_num,
					"ledger_cents": outstanding,
					"statement_cents": stmt_cents,
					"diff_cents": stmt_cents - outstanding,
				})
				matched_invoice_ids.add(invoice.id)
			else:
				disputed.append({
					"invoice_id": invoice.id,
					"invoice_number": inv_num,
					"ledger_cents": outstanding,
					"statement_cents": stmt_cents,
					"diff_cents": stmt_cents - outstanding,
					"tolerance_cents": tolerance,
				})

		unmatched_ledger = [
			{
				"invoice_id": inv.id,
				"invoice_number": inv.invoice_number_supplier,
				"outstanding_cents": inv.total_cents - inv.paid_cents,
				"due_date": inv.due_date.isoformat() if hasattr(inv.due_date, "isoformat") else str(inv.due_date),
			}
			for inv in open_invoices
			if inv.id not in matched_invoice_ids
			and inv.id not in {d["invoice_id"] for d in disputed}
		]

		net_difference = sum(m["diff_cents"] for m in matched) + sum(d["diff_cents"] for d in disputed)
		assert isinstance(net_difference, int), "net_difference must be int"

		result = {
			"supplier_id": supplier_id,
			"matched": matched,
			"unmatched_statement": unmatched_statement,
			"unmatched_ledger": unmatched_ledger,
			"disputed": disputed,
			"net_difference_cents": net_difference,
			"currency": supplier.currency_code,
		}

		emit_event(
			SupplierStatementReconciledEvent(
				aggregate_id=supplier_id,
				aggregate_type="APSupplier",
				tenant_id=supplier.tenant_id,
				supplier_id=supplier_id,
				matched_count=len(matched),
				unmatched_count=len(unmatched_statement) + len(unmatched_ledger),
				disputed_count=len(disputed),
				net_difference_cents=net_difference,
				currency=supplier.currency_code,
			),
			session,
		)

		log.info(
			"APService.reconcile_supplier_statement: supplier=%s matched=%d unmatched=%d disputed=%d diff=%d¢",
			supplier_id, len(matched),
			len(unmatched_statement) + len(unmatched_ledger),
			len(disputed), net_difference,
		)
		return result

	# ------------------------------------------------------------------
	# GRN posting
	# ------------------------------------------------------------------

	def post_grn(self, grn_id: str, session: Any) -> Any:
		"""Confirm a GRN and update PO running totals.

		Transitions GRN status DRAFT/QUALITY_HOLD → POSTED.
		Updates APPOLine.quantity_received and APPurchaseOrder.received_cents.
		Auto-transitions PO status to PARTIAL or RECEIVED.

		Args:
			grn_id: UUID of APGoodsReceipt.
			session: SQLAlchemy session.

		Returns:
			Updated APGoodsReceipt.
		"""
		from pgappforge.plugins.erp.finance.ap.models import APGoodsReceipt, APPOLine

		grn = session.get(APGoodsReceipt, grn_id)
		if grn is None:
			raise APServiceError(f"APGoodsReceipt {grn_id!r} not found")
		if grn.status == "POSTED":
			raise APServiceError(f"GRN {grn_id!r} is already POSTED")

		for line in grn.lines:
			accepted = Decimal(str(line.quantity_accepted or line.quantity_received))

			if line.po_line_id:
				po_line = session.get(APPOLine, line.po_line_id)
				if po_line is not None:
					po_line.quantity_received = (
						Decimal(str(po_line.quantity_received)) + accepted
					)
					# Update PO header running total
					if po_line.purchase_order is not None:
						unit_cost = line.unit_cost_cents or po_line.unit_cost_cents
						po_line.purchase_order.received_cents += _cents(accepted, unit_cost)

		# Update PO status
		if grn.po_id and grn.purchase_order:
			po = grn.purchase_order
			total_ordered = sum(
				Decimal(str(l.quantity)) for l in po.lines
			)
			total_received = sum(
				Decimal(str(l.quantity_received)) for l in po.lines
			)
			if total_ordered > 0:
				if total_received >= total_ordered * Decimal("0.99"):
					po.status = "RECEIVED"
				elif total_received > 0:
					po.status = "PARTIAL"

		grn.status = "POSTED"
		grn.updated_at = datetime.now(timezone.utc)
		log.info("APService.post_grn: GRN %s posted", grn_id)
		return grn

	# ------------------------------------------------------------------
	# Approval workflow
	# ------------------------------------------------------------------

	def approve_invoice(
		self,
		invoice_id: str,
		approver_id: str,
		session: Any,
		comments: str = "",
	) -> Any:
		"""Record an approval decision for an invoice.

		Finds the lowest PENDING APApprovalWorkflow row for this approver.
		If all required approval levels are APPROVED, sets:
		  - APInvoice.approval_status = "APPROVED"
		  - APInvoice.status = "APPROVED"
		  - Emits InvoiceApprovedEvent

		Args:
			invoice_id: UUID of APInvoice.
			approver_id: UUID of the approver (ab_user id or UUID).
			session: SQLAlchemy session.
			comments: Optional approval comment.

		Returns:
			Updated APInvoice.
		"""
		from pgappforge.plugins.erp.finance.ap.models import APApprovalWorkflow, APInvoice
		from pgappforge.plugins.erp.finance.ap.events import InvoiceApprovedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		invoice = session.get(APInvoice, invoice_id)
		if invoice is None:
			raise APInvoiceNotFoundError(f"APInvoice {invoice_id!r} not found")

		# Find this approver's pending step
		wf_row = session.execute(
			sa.select(APApprovalWorkflow)
			.where(APApprovalWorkflow.invoice_id == invoice_id)
			.where(APApprovalWorkflow.approver_id == approver_id)
			.where(APApprovalWorkflow.status == "PENDING")
			.order_by(APApprovalWorkflow.approval_level)
			.limit(1)
		).scalar_one_or_none()

		if wf_row is None:
			raise APWorkflowError(
				f"No PENDING approval step for approver {approver_id!r} on invoice {invoice_id!r}"
			)

		# Threshold check
		if wf_row.amount_threshold_cents is not None:
			if invoice.total_cents > wf_row.amount_threshold_cents:
				raise APWorkflowError(
					f"Invoice total {invoice.total_cents}¢ exceeds approver threshold "
					f"{wf_row.amount_threshold_cents}¢"
				)

		wf_row.status = "APPROVED"
		wf_row.actioned_at = datetime.now(timezone.utc)
		wf_row.comments = comments

		# Check if all workflow steps are now approved
		pending_count = session.execute(
			sa.select(sa.func.count())
			.select_from(APApprovalWorkflow)
			.where(APApprovalWorkflow.invoice_id == invoice_id)
			.where(APApprovalWorkflow.status == "PENDING")
		).scalar()

		if pending_count == 0:
			invoice.approval_status = "APPROVED"
			invoice.status = "APPROVED"
			invoice.updated_at = datetime.now(timezone.utc)

			emit_event(
				InvoiceApprovedEvent(
					aggregate_id=invoice_id,
					aggregate_type="APInvoice",
					tenant_id=invoice.tenant_id,
					invoice_id=invoice_id,
					supplier_id=invoice.supplier_id,
					total_cents=invoice.total_cents,
					currency=invoice.currency_code,
					due_date=invoice.due_date.isoformat() if hasattr(invoice.due_date, "isoformat") else str(invoice.due_date),
				),
				session,
			)
			log.info("APService.approve_invoice: invoice %s fully approved", invoice_id)

		return invoice

	# ------------------------------------------------------------------
	# Payment application
	# ------------------------------------------------------------------

	def apply_payment(
		self,
		invoice_id: str,
		payment_id: str,
		session: Any,
	) -> Any:
		"""Apply a confirmed APPayment to an APInvoice.

		Increments invoice.paid_cents by payment.amount_cents.
		If paid_cents >= total_cents, sets invoice.status = PAID.
		Also updates APPurchaseOrder.paid_cents if linked.

		Args:
			invoice_id: UUID of the APInvoice.
			payment_id: UUID of the APPayment.
			session: SQLAlchemy session.

		Returns:
			Updated APInvoice.
		"""
		from pgappforge.plugins.erp.finance.ap.models import APInvoice, APPayment
		from pgappforge.plugins.erp.finance.ap.events import PaymentConfirmedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		invoice = session.get(APInvoice, invoice_id)
		if invoice is None:
			raise APInvoiceNotFoundError(f"APInvoice {invoice_id!r} not found")

		payment = session.get(APPayment, payment_id)
		if payment is None:
			raise APPaymentError(f"APPayment {payment_id!r} not found")

		if payment.status != "CONFIRMED":
			raise APPaymentError(f"APPayment {payment_id!r} status is {payment.status!r}; must be CONFIRMED")

		assert isinstance(payment.amount_cents, int), "amount_cents must be int"
		invoice.paid_cents += payment.amount_cents

		if invoice.paid_cents >= invoice.total_cents:
			invoice.status = "PAID"

		invoice.updated_at = datetime.now(timezone.utc)

		# Update PO paid_cents
		if invoice.po_id and invoice.purchase_order:
			invoice.purchase_order.paid_cents += payment.amount_cents

		emit_event(
			PaymentConfirmedEvent(
				aggregate_id=payment_id,
				aggregate_type="APPayment",
				tenant_id=invoice.tenant_id,
				payment_id=payment_id,
				payment_run_id=payment.payment_run_id or "",
				supplier_id=payment.supplier_id,
				amount_cents=payment.amount_cents,
				currency=payment.currency_code,
				bank_reference=payment.bank_reference or "",
				uetr=payment.uetr or "",
			),
			session,
		)

		log.info(
			"APService.apply_payment: invoice=%s payment=%d¢ new_paid=%d¢ status=%s",
			invoice_id, payment.amount_cents, invoice.paid_cents, invoice.status,
		)
		return invoice


	# ------------------------------------------------------------------
	# get_vendor_statistics
	# ------------------------------------------------------------------

	def get_vendor_statistics(
		self,
		vendor_id: str,
		tenant_id: str,
		session: Any,
	) -> dict:
		"""Live AP statistics for a vendor.

		Returns YTD purchases, outstanding balance, average payment days
		(invoice_date → payment_date via joined APPayment rows), and on-time
		payment rate.

		payment_date comes from APPayment.payment_date (CONFIRMED payments)
		since APInvoice has no paid_at column — we join payments explicitly.
		"""
		from pgappforge.plugins.erp.finance.ap.models import APInvoice, APPayment

		today = _today()
		year_start = today.replace(month=1, day=1)

		invoices = session.execute(
			sa.select(APInvoice)
			.where(APInvoice.supplier_id == vendor_id)
			.where(APInvoice.tenant_id == tenant_id)
			.where(APInvoice.status.not_in(["CANCELLED"]))
		).scalars().all()

		ytd_purchases = 0
		outstanding = 0
		paid_invoice_ids: list[str] = []

		for inv in invoices:
			if inv.invoice_date and inv.invoice_date >= year_start:
				ytd_purchases += inv.total_cents
			if inv.paid_cents < inv.total_cents:
				outstanding += (inv.total_cents - inv.paid_cents)
			if inv.status in ("PAID", "PAYMENT_SCHEDULED"):
				paid_invoice_ids.append(inv.id)

		# Fetch CONFIRMED payments for paid invoices to compute payment days
		payment_days_list: list[int] = []
		on_time_count = 0
		paid_count = 0

		if paid_invoice_ids:
			# Build a lookup: invoice_id → (invoice_date, due_date)
			inv_meta: dict[str, tuple[date, date | None]] = {
				inv.id: (inv.invoice_date, inv.due_date)
				for inv in invoices
				if inv.id in paid_invoice_ids
			}

			payments = session.execute(
				sa.select(APPayment)
				.where(APPayment.supplier_id == vendor_id)
				.where(APPayment.invoice_id.in_(paid_invoice_ids))
				.where(APPayment.status == "CONFIRMED")
			).scalars().all()

			# Group: take first CONFIRMED payment per invoice as settlement date
			settled: dict[str, date] = {}
			for pmt in payments:
				if pmt.invoice_id not in settled:
					settled[pmt.invoice_id] = pmt.payment_date

			for inv_id, pmt_date in settled.items():
				invoice_date, due_date = inv_meta[inv_id]
				paid_count += 1
				days_to_pay = (pmt_date - invoice_date).days
				payment_days_list.append(days_to_pay)
				if due_date is not None and pmt_date <= due_date:
					on_time_count += 1

		return {
			"vendor_id": vendor_id,
			"ytd_purchases_cents": ytd_purchases,
			"outstanding_cents": outstanding,
			"avg_payment_days": (
				sum(payment_days_list) // len(payment_days_list)
				if payment_days_list else 0
			),
			"on_time_payment_rate_pct": (
				round(on_time_count / paid_count * 100) if paid_count else 0
			),
			"invoice_count_ytd": sum(
				1 for inv in invoices
				if inv.invoice_date and inv.invoice_date >= year_start
			),
		}


__all__ = [
	"APService",
	"APServiceError",
	"APSupplierNotFoundError",
	"APInvoiceNotFoundError",
	"APMatchError",
	"APWorkflowError",
	"APPaymentError",
]
