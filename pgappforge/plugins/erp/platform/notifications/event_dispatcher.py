"""
pgappforge/plugins/erp/platform/notifications/event_dispatcher.py

Routes domain events to the notification service.
Subscribe to business events and send appropriate notifications.

Activated by adding NotificationDispatcherPlugin to PGAPPFORGE_PLUGINS.
Config keys:
  NOTIFY_LOAN_APPROVED       = True
  NOTIFY_INVOICE_CREATED     = True
  NOTIFY_PAYROLL_PROCESSED   = True
  NOTIFY_MEMBER_APPROVED     = True
  NOTIFY_LOW_STOCK           = True
  NOTIFY_CHANNELS            = ["email"]   # email, sms, whatsapp, push
"""

from __future__ import annotations
import logging
from typing import Any
log = logging.getLogger(__name__)


def _cfg(key, default=None):
	try:
		from flask import current_app
		return current_app.config.get(key, default)
	except RuntimeError:
		return default


def _notify(recipient_id, subject, body, *, channels=None, metadata=None):
	"""Send notification via the alerting service. Non-fatal."""
	try:
		from pgappforge.alerting.notification_service import NotificationService
		svc = NotificationService()
		configured_channels = channels or _cfg("NOTIFY_CHANNELS", ["email"])
		svc.send_notification(
			recipient_id=recipient_id,
			subject=subject,
			body=body,
			channels=configured_channels,
			metadata=metadata or {},
		)
	except Exception as exc:
		log.debug("Notification dispatch failed (non-fatal): %s", exc)


# ── Event handlers ────────────────────────────────────────────────────────────

def on_loan_approved(event):
	"""Send notification when a loan is approved."""
	if not _cfg("NOTIFY_LOAN_APPROVED", True):
		return
	applicant_id = getattr(event, "applicant_id", "") or getattr(event, "customer_id", "")
	amount = getattr(event, "amount_cents", 0)
	amount_fmt = f"{amount/100:,.2f}" if amount else "—"
	_notify(
		recipient_id=str(applicant_id),
		subject="Your Loan Application Has Been Approved",
		body=(
			f"Congratulations! Your loan application for {amount_fmt} has been approved. "
			"Please log in to review the terms and next steps."
		),
		metadata={"event_type": "lending.loan.approved", "loan_id": str(getattr(event, "aggregate_id", ""))},
	)


def on_invoice_created(event):
	"""Notify accounts payable team when a new invoice is created."""
	if not _cfg("NOTIFY_INVOICE_CREATED", True):
		return
	supplier_id = getattr(event, "supplier_id", "") or getattr(event, "vendor_id", "")
	amount = getattr(event, "amount_cents", 0)
	_notify(
		recipient_id=str(supplier_id),
		subject="Invoice Received",
		body=f"An invoice for {amount/100:,.2f} has been received and is pending approval.",
		metadata={"event_type": "finance.ap.invoice.created"},
	)


def on_payroll_processed(event):
	"""Notify each employee when their payslip is ready."""
	if not _cfg("NOTIFY_PAYROLL_PROCESSED", True):
		return
	employee_id = getattr(event, "employee_id", "")
	period = getattr(event, "period", "")
	_notify(
		recipient_id=str(employee_id),
		subject=f"Your Payslip for {period} is Ready",
		body=f"Your payslip for {period} has been processed. Log in to view and download it.",
		metadata={"event_type": "hcm.payroll.payslip.created", "period": period},
	)


def on_member_approved(event):
	"""Notify new club/SACCO members when their application is approved."""
	if not _cfg("NOTIFY_MEMBER_APPROVED", True):
		return
	member_id = getattr(event, "member_id", "") or getattr(event, "aggregate_id", "")
	membership_number = getattr(event, "membership_number", "")
	_notify(
		recipient_id=str(member_id),
		subject="Welcome — Membership Approved",
		body=(
			f"Your membership application has been approved. "
			f"Your membership number is {membership_number}. "
			"Welcome aboard!"
		),
		metadata={"event_type": "member.approved"},
	)


def on_low_stock(event):
	"""Alert procurement when stock falls below reorder point."""
	if not _cfg("NOTIFY_LOW_STOCK", True):
		return
	product_id = getattr(event, "product_id", "")
	product_name = getattr(event, "product_name", str(product_id))
	qty = getattr(event, "current_qty", 0)
	_notify(
		recipient_id="procurement_manager",
		subject=f"Low Stock Alert: {product_name}",
		body=f"Stock for {product_name} has fallen to {qty} units, below the reorder point. Please raise a purchase order.",
		metadata={"event_type": "inventory.stock.low", "product_id": str(product_id)},
	)


def on_payment_failed(event):
	"""Alert finance when a payment fails."""
	_notify(
		recipient_id="finance_manager",
		subject="Payment Failed",
		body=f"Payment {getattr(event,'payment_reference','')} failed: {getattr(event,'reason','')}",
		metadata={"event_type": "finance.payment.failed"},
	)


def on_member_charge_posted(event):
	"""Notify club member when a charge is posted to their account."""
	if not _cfg("NOTIFY_MEMBER_CHARGES", False):  # opt-in, off by default
		return
	member_id = getattr(event, "member_id", "")
	amount = getattr(event, "amount_cents", 0)
	charge_type = getattr(event, "charge_type", "")
	_notify(
		recipient_id=str(member_id),
		subject=f"Charge Posted to Your Account",
		body=f"A {charge_type} charge of {amount/100:,.2f} has been posted to your account.",
		metadata={"event_type": "club.member.charged"},
	)


# ── Subscription registry ────────────────────────────────────────────────────

EVENT_HANDLERS = {
	"lending.loan.approved":           on_loan_approved,
	"finance.ap.invoice.created":      on_invoice_created,
	"hcm.payroll.payslip.created":     on_payroll_processed,
	"club.member.approved":            on_member_approved,
	"sacco.member.approved":           on_member_approved,
	"inventory.stock.reorder_point":   on_low_stock,
	"finance.payment.failed":          on_payment_failed,
	"club.member.charged":             on_member_charge_posted,
}


def register_all_subscriptions() -> int:
	"""Subscribe all handlers to the event bus. Returns count registered."""
	try:
		from pgappforge.plugins.erp.foundation.events import subscribe
		registered = 0
		for event_type, handler in EVENT_HANDLERS.items():
			try:
				subscribe(event_type, handler)
				registered += 1
			except Exception as exc:
				log.debug("Could not subscribe %s: %s", event_type, exc)
		return registered
	except ImportError as exc:
		log.debug("Event bus not available: %s", exc)
		return 0


__all__ = ["register_all_subscriptions", "EVENT_HANDLERS", "_notify"]
