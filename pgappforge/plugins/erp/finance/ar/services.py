"""
pgappforge/plugins/erp/finance/ar/services.py

ARService — stateless business logic for the Accounts Receivable plugin.

All methods accept an explicit SQLAlchemy session (SA 2.x execute() pattern).
No session.commit() inside service methods — callers own the transaction boundary.

Monetary invariant: ALL amounts are integer cents throughout. Float is never used.

Key methods
-----------
  issue_invoice(invoice_id, session)
      DRAFT → ISSUED; validates; posts GL journal entry (DR AR / CR Revenue).

  apply_payment(payment_id, allocations, session)
      Allocates payment to invoices; updates paid_cents/balance_due_cents;
      marks invoices PAID when balance reaches zero.

  run_aging(as_of_date, tenant_id, session) -> list[ARAging]
      Computes aging buckets for all active customers; inserts new ARAging rows.

  run_dunning(dunning_level, tenant_id, session) -> ARDunningRun
      Creates a dunning run; emits CustomerOverdueEvent per customer.

  write_off(invoice_id, reason, session)
      Sets invoice WRITTEN_OFF; adjusts balance; emits InvoiceWrittenOffEvent.

  generate_statement(customer_id, period_start, period_end, session) -> dict
      Returns structured statement data (caller renders to PDF via ReportForge).

  create_credit_note(data, session) -> ARCreditNote
      Creates a credit note; optionally links to an original invoice.

  apply_credit_note(credit_note_id, invoice_id, amount_cents, session)
      Applies (part of) a credit note against an invoice balance.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

import sqlalchemy as sa

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class ARServiceError(Exception):
	"""Base exception for AR service layer errors."""


class ARInvoiceNotFoundError(ARServiceError):
	pass


class ARCustomerNotFoundError(ARServiceError):
	pass


class ARPaymentNotFoundError(ARServiceError):
	pass


class ARValidationError(ARServiceError):
	"""Business rule violation — surfaces as HTTP 422 in views."""


class ARCreditNoteNotFoundError(ARServiceError):
	pass


# ---------------------------------------------------------------------------
# ARService
# ---------------------------------------------------------------------------

class ARService:
	"""Stateless AR business logic.

	Instantiate per-request or as a singleton — no instance state.

	All monetary arithmetic uses int (cents). Decimal is used only for
	intermediate exchange rate multiplication, then rounded to int.
	"""

	# ------------------------------------------------------------------
	# issue_invoice
	# ------------------------------------------------------------------

	def issue_invoice(self, invoice_id: str, session: Any) -> Any:
		"""Transition invoice DRAFT → ISSUED.

		Validations:
		  - Invoice must exist and be in DRAFT status.
		  - At least one line must exist.
		  - Customer must not be on credit hold.
		  - total_cents must equal subtotal - discount + tax.

		Side-effects (within caller's transaction):
		  - Recomputes total_cents, balance_due_cents from lines.
		  - Sets status = ISSUED.
		  - Emits InvoiceIssuedEvent (persists to DomainEventLog).
		  - Posts GL journal entry stub (DR AR / CR Revenue) via _post_gl_journal.

		Returns the updated ARInvoice instance.
		"""
		from pgappforge.plugins.erp.finance.ar.models import ARInvoice, ARInvoiceLine, ARCustomer
		from pgappforge.plugins.erp.finance.ar.events import InvoiceIssuedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		invoice = session.get(ARInvoice, invoice_id)
		if invoice is None:
			raise ARInvoiceNotFoundError(f"Invoice {invoice_id!r} not found")
		if invoice.status != "DRAFT":
			raise ARValidationError(
				f"Invoice {invoice.invoice_number!r} is {invoice.status!r}, not DRAFT"
			)

		customer = session.get(ARCustomer, invoice.customer_id)
		if customer is None:
			raise ARCustomerNotFoundError(f"Customer {invoice.customer_id!r} not found")
		if customer.credit_hold:
			raise ARValidationError(
				f"Customer {customer.account_number!r} is on credit hold"
			)

		# Recompute totals from lines
		lines = session.execute(
			sa.select(ARInvoiceLine).where(ARInvoiceLine.invoice_id == invoice_id)
		).scalars().all()
		if not lines:
			raise ARValidationError("Invoice must have at least one line before issuing")

		subtotal = sum(ln.line_amount_cents for ln in lines)
		tax = sum(ln.tax_cents for ln in lines)
		total = subtotal - invoice.discount_cents + tax

		invoice.subtotal_cents = subtotal
		invoice.tax_cents = tax
		invoice.total_cents = total
		invoice.balance_due_cents = total - invoice.paid_cents - invoice.write_off_cents
		invoice.status = "ISSUED"
		invoice.updated_at = datetime.now(timezone.utc)

		# Update customer credit exposure
		customer.credit_used_cents = (customer.credit_used_cents or 0) + total

		# GL journal stub (DR AR / CR Revenue)
		self._post_gl_journal(
			tenant_id=invoice.tenant_id,
			reference=invoice.invoice_number,
			debit_account=invoice.gl_ar_account or "AR_CONTROL",
			credit_account=invoice.gl_revenue_account or "REVENUE",
			amount_cents=total,
			currency_code=invoice.currency_code,
			effective_date=invoice.invoice_date,
			description=f"Invoice {invoice.invoice_number}",
			session=session,
		)

		emit_event(
			InvoiceIssuedEvent(
				aggregate_id=invoice.id,
				aggregate_type="ARInvoice",
				tenant_id=invoice.tenant_id,
				invoice_id=invoice.id,
				invoice_number=invoice.invoice_number,
				customer_id=invoice.customer_id,
				total_cents=invoice.total_cents,
				currency_code=invoice.currency_code,
				due_date=invoice.due_date.isoformat() if invoice.due_date else "",
				gl_ar_account=invoice.gl_ar_account or "",
				gl_revenue_account=invoice.gl_revenue_account or "",
			),
			session,
		)

		log.info(
			"ARService.issue_invoice: %r issued, total=%d cents",
			invoice.invoice_number, invoice.total_cents,
		)
		return invoice

	# ------------------------------------------------------------------
	# apply_payment
	# ------------------------------------------------------------------

	def apply_payment(
		self,
		payment_id: str,
		allocations: list[dict],
		session: Any,
	) -> Any:
		"""Allocate a payment to one or more invoices.

		allocations: list of dicts::
		    [
		        {
		            "invoice_id": "<uuid>",
		            "allocated_cents": 5000,
		            "discount_taken_cents": 0,   # optional
		        },
		        ...
		    ]

		Validations:
		  - Payment must exist and not be RETURNED.
		  - Sum of allocated_cents must not exceed payment.amount_cents minus
		    already-allocated amounts.
		  - Each invoice must belong to the same customer.
		  - Each invoice must have sufficient balance_due_cents.

		Side-effects:
		  - Inserts ARAllocation rows (append-only, never updated).
		  - Updates invoice paid_cents, balance_due_cents, status.
		  - Updates payment status (PARTIAL / ALLOCATED).
		  - Emits PaymentAllocatedEvent.
		  - Emits InvoicePaidEvent for fully paid invoices.
		  - Reduces customer.credit_used_cents for paid amounts.
		"""
		from pgappforge.plugins.erp.finance.ar.models import (
			ARPayment, ARInvoice, ARAllocation, ARCustomer,
		)
		from pgappforge.plugins.erp.finance.ar.events import (
			PaymentAllocatedEvent, InvoicePaidEvent,
		)
		from pgappforge.plugins.erp.foundation.events import emit_event

		payment = session.get(ARPayment, payment_id)
		if payment is None:
			raise ARPaymentNotFoundError(f"Payment {payment_id!r} not found")
		if payment.status == "RETURNED":
			raise ARValidationError(f"Payment {payment.payment_number!r} is RETURNED")

		# Already allocated amount for this payment
		already_alloc = session.execute(
			sa.select(sa.func.coalesce(sa.func.sum(ARAllocation.allocated_cents), 0))
			.where(ARAllocation.payment_id == payment_id)
		).scalar() or 0

		total_new = sum(a.get("allocated_cents", 0) for a in allocations)
		available = payment.amount_cents - already_alloc
		if total_new > available:
			raise ARValidationError(
				f"Allocations total {total_new}¢ exceeds available {available}¢ "
				f"(payment {payment.payment_number!r})"
			)

		alloc_date = date.today()
		invoice_ids_touched: list[str] = []

		for alloc_def in allocations:
			inv_id = alloc_def["invoice_id"]
			alloc_cents = int(alloc_def["allocated_cents"])
			discount_cents = int(alloc_def.get("discount_taken_cents", 0))

			invoice = session.get(ARInvoice, inv_id)
			if invoice is None:
				raise ARInvoiceNotFoundError(f"Invoice {inv_id!r} not found")
			if invoice.customer_id != payment.customer_id:
				raise ARValidationError(
					f"Invoice {inv_id!r} belongs to a different customer"
				)
			if invoice.status in ("CANCELLED", "WRITTEN_OFF"):
				raise ARValidationError(
					f"Invoice {invoice.invoice_number!r} is {invoice.status!r}"
				)

			effective_alloc = alloc_cents + discount_cents
			if effective_alloc > invoice.balance_due_cents:
				raise ARValidationError(
					f"Allocation {effective_alloc}¢ exceeds invoice balance "
					f"{invoice.balance_due_cents}¢ for {invoice.invoice_number!r}"
				)

			# Insert immutable allocation row
			row = ARAllocation(
				tenant_id=payment.tenant_id,
				payment_id=payment_id,
				invoice_id=inv_id,
				allocation_date=alloc_date,
				allocated_cents=alloc_cents,
				discount_taken_cents=discount_cents,
			)
			session.add(row)

			# Update invoice
			invoice.paid_cents += alloc_cents + discount_cents
			invoice.balance_due_cents = (
				invoice.total_cents - invoice.paid_cents - invoice.write_off_cents
			)
			invoice.updated_at = datetime.now(timezone.utc)

			if invoice.balance_due_cents <= 0:
				invoice.status = "PAID"
				invoice.paid_date = alloc_date
				# Reduce credit exposure
				customer = session.get(ARCustomer, invoice.customer_id)
				if customer:
					customer.credit_used_cents = max(
						0, (customer.credit_used_cents or 0) - invoice.total_cents
					)
				emit_event(
					InvoicePaidEvent(
						aggregate_id=invoice.id,
						aggregate_type="ARInvoice",
						tenant_id=invoice.tenant_id,
						invoice_id=invoice.id,
						invoice_number=invoice.invoice_number,
						customer_id=invoice.customer_id,
						total_cents=invoice.total_cents,
						paid_cents=invoice.paid_cents,
						currency_code=invoice.currency_code,
						paid_date=alloc_date.isoformat(),
					),
					session,
				)
			elif invoice.status == "ISSUED" or invoice.status == "OVERDUE":
				invoice.status = "PARTIAL"

			invoice_ids_touched.append(inv_id)

		# Update payment status
		total_allocated_now = already_alloc + total_new
		if total_allocated_now >= payment.amount_cents:
			payment.status = "ALLOCATED"
		else:
			payment.status = "PARTIAL"
		payment.updated_at = datetime.now(timezone.utc)

		emit_event(
			PaymentAllocatedEvent(
				aggregate_id=payment_id,
				aggregate_type="ARPayment",
				tenant_id=payment.tenant_id,
				payment_id=payment_id,
				payment_number=payment.payment_number,
				customer_id=payment.customer_id,
				allocated_cents=total_new,
				invoice_ids=invoice_ids_touched,
			),
			session,
		)

		log.info(
			"ARService.apply_payment: %r allocated %d¢ across %d invoices",
			payment.payment_number, total_new, len(invoice_ids_touched),
		)
		return payment

	# ------------------------------------------------------------------
	# run_aging
	# ------------------------------------------------------------------

	def run_aging(
		self,
		as_of_date: date,
		tenant_id: str,
		session: Any,
	) -> list[Any]:
		"""Compute aging buckets for all active customers in tenant.

		Inserts a new ARAging row per customer (append-only; does NOT delete old rows).

		Bucket logic (days overdue = as_of_date - due_date):
		  current    : balance_due > 0 and due_date >= as_of_date
		  1-30       : 1  <= days_overdue <= 30
		  31-60      : 31 <= days_overdue <= 60
		  61-90      : 61 <= days_overdue <= 90
		  91-120     : 91 <= days_overdue <= 120
		  over_120   : days_overdue > 120

		Returns list of newly created ARAging rows.
		"""
		from pgappforge.plugins.erp.finance.ar.models import ARCustomer, ARInvoice, ARAging
		from pgappforge.plugins.erp.finance.ar.events import AgingSnapshotCreatedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		customers = session.execute(
			sa.select(ARCustomer)
			.where(ARCustomer.tenant_id == tenant_id)
			.where(ARCustomer.status == "ACTIVE")
		).scalars().all()

		snapshots: list[ARAging] = []
		total_outstanding = 0

		for customer in customers:
			invoices = session.execute(
				sa.select(ARInvoice)
				.where(ARInvoice.customer_id == customer.id)
				.where(ARInvoice.balance_due_cents > 0)
				.where(ARInvoice.status.not_in(["CANCELLED", "WRITTEN_OFF", "PAID"]))
			).scalars().all()

			buckets = {
				"current_cents": 0,
				"days_1_30": 0,
				"days_31_60": 0,
				"days_61_90": 0,
				"days_91_120": 0,
				"over_120": 0,
			}

			for inv in invoices:
				bal = inv.balance_due_cents
				if inv.due_date >= as_of_date:
					buckets["current_cents"] += bal
				else:
					days_late = (as_of_date - inv.due_date).days
					if days_late <= 30:
						buckets["days_1_30"] += bal
					elif days_late <= 60:
						buckets["days_31_60"] += bal
					elif days_late <= 90:
						buckets["days_61_90"] += bal
					elif days_late <= 120:
						buckets["days_91_120"] += bal
					else:
						buckets["over_120"] += bal

			cust_total = sum(buckets.values())
			total_outstanding += cust_total

			snap = ARAging(
				tenant_id=tenant_id,
				customer_id=customer.id,
				snapshot_date=as_of_date,
				currency_code=customer.billing_address.get("currency", "USD") if customer.billing_address else "USD",
				total_outstanding_cents=cust_total,
				**buckets,
			)
			session.add(snap)
			snapshots.append(snap)

		emit_event(
			AgingSnapshotCreatedEvent(
				aggregate_id=tenant_id,
				aggregate_type="Tenant",
				tenant_id=tenant_id,
				snapshot_date=as_of_date.isoformat(),
				customers_snapshotted=len(snapshots),
				total_outstanding_cents=total_outstanding,
			),
			session,
		)

		log.info(
			"ARService.run_aging: %d customers snapshotted, total=%d¢",
			len(snapshots), total_outstanding,
		)
		return snapshots

	# ------------------------------------------------------------------
	# run_dunning
	# ------------------------------------------------------------------

	def run_dunning(
		self,
		dunning_level: int,
		tenant_id: str,
		session: Any,
		as_of_date: date | None = None,
	) -> Any:
		"""Create a dunning run for customers at or above dunning_level.

		Selects customers with overdue invoices who are not dunning_blocked.
		Creates ARDunningRun + one ARDunningEvent per qualifying customer.
		Emits CustomerOverdueEvent per customer.

		Returns the created ARDunningRun.
		"""
		from pgappforge.plugins.erp.finance.ar.models import (
			ARCustomer, ARInvoice, ARDunningRun, ARDunningEvent,
		)
		from pgappforge.plugins.erp.finance.ar.events import (
			CustomerOverdueEvent, DunningRunCompletedEvent,
		)
		from pgappforge.plugins.erp.foundation.events import emit_event

		today = as_of_date or date.today()

		run = ARDunningRun(
			tenant_id=tenant_id,
			run_date=today,
			dunning_level=dunning_level,
			status="RUNNING",
		)
		session.add(run)
		session.flush()  # get run.id

		# Customers with overdue invoices, not blocked
		subq = (
			sa.select(ARInvoice.customer_id)
			.where(ARInvoice.tenant_id == tenant_id)
			.where(ARInvoice.balance_due_cents > 0)
			.where(ARInvoice.due_date < today)
			.where(ARInvoice.status.not_in(["CANCELLED", "WRITTEN_OFF", "PAID"]))
			.distinct()
			.subquery()
		)
		customers = session.execute(
			sa.select(ARCustomer)
			.where(ARCustomer.tenant_id == tenant_id)
			.where(ARCustomer.id.in_(sa.select(subq)))
			.where(ARCustomer.dunning_blocked.is_(False))
			.where(ARCustomer.status == "ACTIVE")
		).scalars().all()

		emails_sent = 0
		total_overdue = 0

		for customer in customers:
			# Get overdue invoices for this customer
			overdue_invoices = session.execute(
				sa.select(ARInvoice)
				.where(ARInvoice.customer_id == customer.id)
				.where(ARInvoice.balance_due_cents > 0)
				.where(ARInvoice.due_date < today)
				.where(ARInvoice.status.not_in(["CANCELLED", "WRITTEN_OFF", "PAID"]))
				.order_by(ARInvoice.due_date)
			).scalars().all()

			if not overdue_invoices:
				continue

			overdue_cents = sum(inv.balance_due_cents for inv in overdue_invoices)
			invoice_ids = [inv.id for inv in overdue_invoices]
			oldest_due = min(inv.due_date for inv in overdue_invoices)

			event = ARDunningEvent(
				tenant_id=tenant_id,
				dunning_run_id=run.id,
				customer_id=customer.id,
				invoice_ids=invoice_ids,
				amount_overdue_cents=overdue_cents,
				method="EMAIL",
				contact_email=customer.contact_email or "",
			)
			session.add(event)

			# Escalate dunning level on customer
			customer.dunning_level = max(customer.dunning_level, dunning_level)
			customer.updated_at = datetime.now(timezone.utc)

			# Update per-invoice dunning level
			for inv in overdue_invoices:
				inv.dunning_level = max(inv.dunning_level, dunning_level)
				inv.last_dunning_date = today
				inv.status = "OVERDUE"
				inv.updated_at = datetime.now(timezone.utc)

			total_overdue += overdue_cents
			emails_sent += 1  # stub — real impl integrates email provider

			emit_event(
				CustomerOverdueEvent(
					aggregate_id=customer.id,
					aggregate_type="ARCustomer",
					tenant_id=tenant_id,
					customer_id=customer.id,
					account_number=customer.account_number,
					overdue_cents=overdue_cents,
					currency_code="USD",
					oldest_due_date=oldest_due.isoformat(),
					dunning_level=dunning_level,
				),
				session,
			)

		run.batch_size = len(customers)
		run.emails_sent = emails_sent
		run.status = "COMPLETED"
		run.updated_at = datetime.now(timezone.utc)

		emit_event(
			DunningRunCompletedEvent(
				aggregate_id=run.id,
				aggregate_type="ARDunningRun",
				tenant_id=tenant_id,
				dunning_run_id=run.id,
				dunning_level=dunning_level,
				customers_contacted=len(customers),
				emails_sent=emails_sent,
				total_overdue_cents=total_overdue,
			),
			session,
		)

		log.info(
			"ARService.run_dunning: level=%d, customers=%d, emails=%d, overdue=%d¢",
			dunning_level, len(customers), emails_sent, total_overdue,
		)
		return run

	# ------------------------------------------------------------------
	# write_off
	# ------------------------------------------------------------------

	def write_off(
		self,
		invoice_id: str,
		reason: str,
		session: Any,
		write_off_date: date | None = None,
	) -> Any:
		"""Write off outstanding balance on an invoice as bad debt.

		Side-effects:
		  - Sets invoice status = WRITTEN_OFF.
		  - Sets write_off_cents = balance_due_cents before write-off.
		  - Sets balance_due_cents = 0.
		  - Posts GL journal: DR Bad Debt Expense / CR AR Control.
		  - Emits InvoiceWrittenOffEvent.
		  - Reduces customer credit_used_cents.
		"""
		from pgappforge.plugins.erp.finance.ar.models import ARInvoice, ARCustomer
		from pgappforge.plugins.erp.finance.ar.events import InvoiceWrittenOffEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		invoice = session.get(ARInvoice, invoice_id)
		if invoice is None:
			raise ARInvoiceNotFoundError(f"Invoice {invoice_id!r} not found")
		if invoice.status in ("PAID", "CANCELLED", "WRITTEN_OFF"):
			raise ARValidationError(
				f"Invoice {invoice.invoice_number!r} cannot be written off: status={invoice.status!r}"
			)
		if invoice.balance_due_cents <= 0:
			raise ARValidationError(
				f"Invoice {invoice.invoice_number!r} has no outstanding balance"
			)

		wo_date = write_off_date or date.today()
		wo_cents = invoice.balance_due_cents

		invoice.write_off_cents += wo_cents
		invoice.balance_due_cents = 0
		invoice.status = "WRITTEN_OFF"
		invoice.write_off_date = wo_date
		invoice.write_off_reason = reason
		invoice.updated_at = datetime.now(timezone.utc)

		# Reduce credit exposure
		customer = session.get(ARCustomer, invoice.customer_id)
		if customer:
			customer.credit_used_cents = max(
				0, (customer.credit_used_cents or 0) - invoice.total_cents
			)

		# GL journal stub: DR Bad Debt / CR AR
		self._post_gl_journal(
			tenant_id=invoice.tenant_id,
			reference=f"WO-{invoice.invoice_number}",
			debit_account="BAD_DEBT_EXPENSE",
			credit_account=invoice.gl_ar_account or "AR_CONTROL",
			amount_cents=wo_cents,
			currency_code=invoice.currency_code,
			effective_date=wo_date,
			description=f"Write-off: {invoice.invoice_number} — {reason}",
			session=session,
		)

		emit_event(
			InvoiceWrittenOffEvent(
				aggregate_id=invoice.id,
				aggregate_type="ARInvoice",
				tenant_id=invoice.tenant_id,
				invoice_id=invoice.id,
				invoice_number=invoice.invoice_number,
				customer_id=invoice.customer_id,
				write_off_cents=wo_cents,
				currency_code=invoice.currency_code,
				reason=reason,
				write_off_date=wo_date.isoformat(),
			),
			session,
		)

		log.info(
			"ARService.write_off: %r written off %d¢, reason=%r",
			invoice.invoice_number, wo_cents, reason,
		)
		return invoice

	# ------------------------------------------------------------------
	# create_credit_note
	# ------------------------------------------------------------------

	def create_credit_note(
		self,
		data: dict,
		session: Any,
	) -> Any:
		"""Create an ARCreditNote.

		data keys:
		  customer_id, credit_note_number, issue_date (date|str), reason,
		  total_cents (int), currency_code,
		  original_invoice_id (optional)

		Returns the created ARCreditNote.
		"""
		from pgappforge.plugins.erp.finance.ar.models import ARCreditNote, ARCustomer
		from pgappforge.plugins.erp.finance.ar.events import CreditNoteIssuedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		customer_id = data["customer_id"]
		customer = session.get(ARCustomer, customer_id)
		if customer is None:
			raise ARCustomerNotFoundError(f"Customer {customer_id!r} not found")

		issue_date = data["issue_date"]
		if isinstance(issue_date, str):
			issue_date = date.fromisoformat(issue_date)

		cn = ARCreditNote(
			tenant_id=customer.tenant_id,
			credit_note_number=data["credit_note_number"],
			customer_id=customer_id,
			original_invoice_id=data.get("original_invoice_id"),
			issue_date=issue_date,
			reason=data["reason"],
			currency_code=data.get("currency_code", "USD"),
			total_cents=int(data["total_cents"]),
			status="OPEN",
		)
		session.add(cn)
		session.flush()

		emit_event(
			CreditNoteIssuedEvent(
				aggregate_id=cn.id,
				aggregate_type="ARCreditNote",
				tenant_id=cn.tenant_id,
				credit_note_id=cn.id,
				credit_note_number=cn.credit_note_number,
				customer_id=customer_id,
				original_invoice_id=cn.original_invoice_id or "",
				total_cents=cn.total_cents,
				currency_code=cn.currency_code,
				reason=cn.reason,
			),
			session,
		)
		return cn

	# ------------------------------------------------------------------
	# apply_credit_note
	# ------------------------------------------------------------------

	def apply_credit_note(
		self,
		credit_note_id: str,
		invoice_id: str,
		amount_cents: int,
		session: Any,
	) -> Any:
		"""Apply (part of) a credit note against an invoice balance.

		Creates an ARAllocation row (using a sentinel payment concept via direct
		balance adjustment — credit notes are not payments, so we adjust the
		invoice balance directly and record the application on the credit note).

		Returns the updated ARInvoice.
		"""
		from pgappforge.plugins.erp.finance.ar.models import ARCreditNote, ARInvoice

		cn = session.get(ARCreditNote, credit_note_id)
		if cn is None:
			raise ARCreditNoteNotFoundError(f"Credit note {credit_note_id!r} not found")
		if cn.status in ("APPLIED", "CANCELLED"):
			raise ARValidationError(f"Credit note {cn.credit_note_number!r} is {cn.status!r}")

		available = cn.total_cents - cn.applied_cents
		if amount_cents > available:
			raise ARValidationError(
				f"Amount {amount_cents}¢ exceeds available credit note balance {available}¢"
			)

		invoice = session.get(ARInvoice, invoice_id)
		if invoice is None:
			raise ARInvoiceNotFoundError(f"Invoice {invoice_id!r} not found")
		if invoice.customer_id != cn.customer_id:
			raise ARValidationError("Credit note and invoice belong to different customers")
		if amount_cents > invoice.balance_due_cents:
			raise ARValidationError(
				f"Amount {amount_cents}¢ exceeds invoice balance {invoice.balance_due_cents}¢"
			)

		# Apply to invoice
		invoice.paid_cents += amount_cents
		invoice.balance_due_cents = (
			invoice.total_cents - invoice.paid_cents - invoice.write_off_cents
		)
		if invoice.balance_due_cents <= 0:
			invoice.status = "PAID"
			invoice.paid_date = date.today()
		elif invoice.status in ("ISSUED", "OVERDUE"):
			invoice.status = "PARTIAL"
		invoice.updated_at = datetime.now(timezone.utc)

		# Apply to credit note
		cn.applied_cents += amount_cents
		if cn.applied_cents >= cn.total_cents:
			cn.status = "APPLIED"
		else:
			cn.status = "PARTIAL"
		cn.updated_at = datetime.now(timezone.utc)

		log.info(
			"ARService.apply_credit_note: CN %r applied %d¢ to invoice %r",
			cn.credit_note_number, amount_cents, invoice.invoice_number,
		)
		return invoice

	# ------------------------------------------------------------------
	# generate_statement
	# ------------------------------------------------------------------

	def generate_statement(
		self,
		customer_id: str,
		period_start: date,
		period_end: date,
		session: Any,
	) -> dict:
		"""Return structured statement data for a customer covering a date range.

		The caller renders this to PDF via ReportForge or the HTML report view.

		Returns a dict with:
		  customer: dict
		  invoices: list[dict]   — all issued invoices in period
		  payments: list[dict]   — all payments in period
		  opening_balance_cents: int
		  closing_balance_cents: int
		  period_start: str
		  period_end: str
		"""
		from pgappforge.plugins.erp.finance.ar.models import (
			ARCustomer, ARInvoice, ARPayment,
		)

		customer = session.get(ARCustomer, customer_id)
		if customer is None:
			raise ARCustomerNotFoundError(f"Customer {customer_id!r} not found")

		invoices = session.execute(
			sa.select(ARInvoice)
			.where(ARInvoice.customer_id == customer_id)
			.where(ARInvoice.invoice_date >= period_start)
			.where(ARInvoice.invoice_date <= period_end)
			.where(ARInvoice.status != "CANCELLED")
			.order_by(ARInvoice.invoice_date, ARInvoice.invoice_number)
		).scalars().all()

		payments = session.execute(
			sa.select(ARPayment)
			.where(ARPayment.customer_id == customer_id)
			.where(ARPayment.payment_date >= period_start)
			.where(ARPayment.payment_date <= period_end)
			.where(ARPayment.status != "RETURNED")
			.order_by(ARPayment.payment_date)
		).scalars().all()

		# Opening balance: balance_due on invoices issued before period_start
		opening_rows = session.execute(
			sa.select(sa.func.coalesce(sa.func.sum(ARInvoice.balance_due_cents), 0))
			.where(ARInvoice.customer_id == customer_id)
			.where(ARInvoice.invoice_date < period_start)
			.where(ARInvoice.balance_due_cents > 0)
		).scalar()
		opening_balance = opening_rows or 0

		period_invoiced = sum(inv.total_cents for inv in invoices)
		period_paid = sum(p.amount_cents for p in payments)
		closing_balance = opening_balance + period_invoiced - period_paid

		return {
			"customer": {
				"id": customer.id,
				"account_number": customer.account_number,
				"contact_email": customer.contact_email,
				"billing_address": customer.billing_address,
				"payment_terms_days": customer.payment_terms_days,
			},
			"period_start": period_start.isoformat(),
			"period_end": period_end.isoformat(),
			"opening_balance_cents": opening_balance,
			"closing_balance_cents": closing_balance,
			"invoices": [
				{
					"invoice_number": inv.invoice_number,
					"invoice_date": inv.invoice_date.isoformat() if inv.invoice_date else None,
					"due_date": inv.due_date.isoformat() if inv.due_date else None,
					"total_cents": inv.total_cents,
					"paid_cents": inv.paid_cents,
					"balance_due_cents": inv.balance_due_cents,
					"status": inv.status,
					"currency_code": inv.currency_code,
				}
				for inv in invoices
			],
			"payments": [
				{
					"payment_number": p.payment_number,
					"payment_date": p.payment_date.isoformat() if p.payment_date else None,
					"amount_cents": p.amount_cents,
					"currency_code": p.currency_code,
					"payment_method": p.payment_method,
					"status": p.status,
				}
				for p in payments
			],
		}

	# ------------------------------------------------------------------
	# update_overdue_statuses
	# ------------------------------------------------------------------

	def update_overdue_statuses(
		self,
		tenant_id: str,
		as_of_date: date,
		session: Any,
	) -> int:
		"""Mark ISSUED/PARTIAL invoices past due_date as OVERDUE.

		Typically called daily by a scheduler. Returns count of invoices updated.
		"""
		from pgappforge.plugins.erp.finance.ar.models import ARInvoice

		result = session.execute(
			sa.update(ARInvoice)
			.where(ARInvoice.tenant_id == tenant_id)
			.where(ARInvoice.due_date < as_of_date)
			.where(ARInvoice.status.in_(["ISSUED", "PARTIAL"]))
			.where(ARInvoice.balance_due_cents > 0)
			.values(status="OVERDUE", updated_at=datetime.now(timezone.utc))
		)
		n = result.rowcount
		log.info("ARService.update_overdue_statuses: marked %d invoices OVERDUE", n)
		return n

	# ------------------------------------------------------------------
	# credit_check
	# ------------------------------------------------------------------

	def credit_check(self, customer_id: str, amount_cents: int, session: Any) -> bool:
		"""Return True if customer can take on additional credit of amount_cents.

		False if credit_hold is set or if limit would be breached.
		None credit_limit_cents = unlimited.
		"""
		from pgappforge.plugins.erp.finance.ar.models import ARCustomer

		customer = session.get(ARCustomer, customer_id)
		if customer is None:
			raise ARCustomerNotFoundError(f"Customer {customer_id!r} not found")
		if customer.credit_hold:
			return False
		if customer.credit_limit_cents is None:
			return True
		return (customer.credit_used_cents + amount_cents) <= customer.credit_limit_cents

	# ------------------------------------------------------------------
	# Internal helpers
	# ------------------------------------------------------------------

	def _post_gl_journal(
		self,
		tenant_id: str,
		reference: str,
		debit_account: str,
		credit_account: str,
		amount_cents: int,
		currency_code: str,
		effective_date: date,
		description: str,
		session: Any,
	) -> None:
		"""Post a GL journal entry if the GL plugin is loaded.

		Gracefully skips if the GL plugin is not available — AR can operate
		without GL integration (useful during dev/test).
		"""
		try:
			from pgappforge.plugins.erp.finance.gl.models import GLJournalEntry  # type: ignore[import]
			entry = GLJournalEntry(
				tenant_id=tenant_id,
				reference=reference,
				debit_account=debit_account,
				credit_account=credit_account,
				amount_cents=amount_cents,
				currency_code=currency_code,
				effective_date=effective_date,
				description=description,
				source_plugin="ar",
			)
			session.add(entry)
		except ImportError:
			log.debug(
				"_post_gl_journal: GL plugin not available — skipping journal for %r", reference
			)
		except Exception as exc:
			log.warning("_post_gl_journal: failed for %r: %s", reference, exc)


__all__ = [
	"ARService",
	"ARServiceError",
	"ARInvoiceNotFoundError",
	"ARCustomerNotFoundError",
	"ARPaymentNotFoundError",
	"ARValidationError",
	"ARCreditNoteNotFoundError",
]
