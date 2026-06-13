"""
pgappforge/fastapi_services/mpesa_webhook.py

M-Pesa C2B async webhook handler.

Safaricom calls the confirmation URL within ~60 s.  This endpoint returns
immediately with {"ResultCode": 0} and fans out to a background task that
routes the payment to the correct business logic:

  M-NNNNN   → SACCO monthly contribution
  INV-*      → AR invoice payment
  LOAN-*     → Loan repayment
  (other)    → logged as unrecognised, not lost

pip install fastapi uvicorn
"""
from __future__ import annotations

import logging
import re

log = logging.getLogger(__name__)

try:
	from fastapi import APIRouter, BackgroundTasks
	from pydantic import BaseModel, Field

	router = APIRouter()

	# ------------------------------------------------------------------ #
	# Safaricom C2B payload schema
	# ------------------------------------------------------------------ #

	class MPesaC2BNotification(BaseModel):
		"""Safaricom C2B confirmation / validation payload.

		Field names match exactly what Safaricom POSTs — camelCase with capital
		initials.  pydantic v2 uses model_config alias_generator or explicit
		Field(alias=...) for non-Python names; here they're valid Python so no
		alias needed.
		"""

		TransactionType: str = ""
		TransID: str = ""
		TransTime: str = ""
		TransAmount: float = Field(default=0.0, ge=0)
		BusinessShortCode: str = ""
		BillRefNumber: str = ""   # member number / invoice ref
		InvoiceNumber: str = ""
		OrgAccountBalance: float = 0.0
		ThirdPartyTransID: str = ""
		MSISDN: str = ""          # sender phone number
		FirstName: str = ""
		MiddleName: str = ""
		LastName: str = ""

	# ------------------------------------------------------------------ #
	# Endpoints
	# ------------------------------------------------------------------ #

	@router.post("/c2b/confirmation")
	async def mpesa_c2b_confirmation(
		notification: MPesaC2BNotification,
		background_tasks: BackgroundTasks,
	):
		"""M-Pesa C2B payment confirmation webhook.

		Safaricom calls this after a customer pays via Paybill or STK Push.
		Must respond within ~60 s — return immediately and process in background.
		"""
		log.info(
			"M-Pesa C2B received: TransID=%s Amount=%.2f MSISDN=%s Ref=%s",
			notification.TransID,
			notification.TransAmount,
			notification.MSISDN,
			notification.BillRefNumber,
		)
		background_tasks.add_task(_process_c2b_payment, notification.dict())
		return {"ResultCode": 0, "ResultDesc": "Accepted"}

	@router.post("/c2b/validation")
	async def mpesa_c2b_validation(notification: MPesaC2BNotification):
		"""M-Pesa payment validation (called before confirmation).

		Return ResultCode=0 to accept, ResultCode=C2B00011 to reject.
		Override to add custom validation (e.g. check BillRefNumber exists).
		"""
		return {"ResultCode": 0, "ResultDesc": "Accepted"}

	@router.get("/stk-push/status/{checkout_request_id}")
	async def stk_push_status(checkout_request_id: str):
		"""Query the status of an STK Push transaction.

		In production, call the Safaricom STK Push query API and return the result.
		"""
		return {
			"checkout_request_id": checkout_request_id,
			"status": "pending",
			"message": "Query the STK Push status from the Safaricom API using your Access Token.",
		}

	# ------------------------------------------------------------------ #
	# Background routing
	# ------------------------------------------------------------------ #

	async def _process_c2b_payment(notification: dict) -> None:
		"""Route M-Pesa payment to the appropriate business logic domain."""
		try:
			bill_ref = notification.get("BillRefNumber", "").upper().strip()
			amount_cents = int(float(notification.get("TransAmount", 0)) * 100)
			msisdn = notification.get("MSISDN", "")
			trans_id = notification.get("TransID", "")

			if re.match(r'^M-\d{4,}$', bill_ref):
				await _route_sacco_contribution(bill_ref, amount_cents, msisdn, trans_id)
			elif bill_ref.startswith("INV-"):
				await _route_invoice_payment(bill_ref, amount_cents, trans_id)
			elif bill_ref.startswith("LOAN-"):
				await _route_loan_repayment(bill_ref, amount_cents, trans_id)
			else:
				log.info(
					"M-Pesa C2B: unrecognised BillRefNumber %r — TransID=%s amount=%d",
					bill_ref, trans_id, amount_cents,
				)
		except Exception as exc:
			log.error("M-Pesa C2B processing failed: %s", exc, exc_info=True)

	async def _route_sacco_contribution(
		member_number: str,
		amount_cents: int,
		msisdn: str,
		trans_id: str,
	) -> None:
		"""Dispatch SACCO monthly contribution to SACCOService."""
		log.info("SACCO contribution: %s  %d cents  from %s", member_number, amount_cents, msisdn)
		import asyncio
		loop = asyncio.get_event_loop()
		await loop.run_in_executor(
			None,
			_sync_process_sacco_contribution,
			member_number,
			amount_cents,
			trans_id,
		)

	def _sync_process_sacco_contribution(
		member_number: str,
		amount_cents: int,
		trans_id: str,
	) -> None:
		"""Synchronous DB write for SACCO contribution (runs in thread-pool executor)."""
		try:
			from flask import current_app
			import sqlalchemy as sa
			from datetime import datetime

			session = current_app.appbuilder.get_session()
			from pgappforge.plugins.fintech.sacco.models import Member  # type: ignore[import]

			member = session.execute(
				sa.select(Member).where(Member.member_number == member_number)
			).scalar_one_or_none()

			if member is None:
				log.warning("SACCO contribution: member %r not found", member_number)
				return

			from pgappforge.plugins.fintech.sacco.services import SACCOService  # type: ignore[import]
			period = datetime.now().strftime("%Y-%m")
			SACCOService().process_monthly_contribution(
				member_id=str(member.id),
				amount_cents=amount_cents,
				period=period,
				session=session,
				tenant_id=str(member.tenant_id),
				source="MPESA_C2B",
				reference=trans_id,
			)
			session.commit()
			log.info("SACCO contribution processed: %s  %d cents", member_number, amount_cents)
		except Exception as exc:
			log.error("SACCO contribution DB write failed: %s", exc, exc_info=True)

	async def _route_invoice_payment(
		invoice_ref: str,
		amount_cents: int,
		trans_id: str,
	) -> None:
		"""Route to AR invoice payment processing."""
		log.info("Invoice payment: ref=%s  amount=%d cents  trans=%s", invoice_ref, amount_cents, trans_id)
		# TODO: call AR module once available
		# await loop.run_in_executor(None, _sync_apply_invoice_payment, invoice_ref, amount_cents, trans_id)

	async def _route_loan_repayment(
		loan_ref: str,
		amount_cents: int,
		trans_id: str,
	) -> None:
		"""Route to loan repayment processing."""
		log.info("Loan repayment: ref=%s  amount=%d cents  trans=%s", loan_ref, amount_cents, trans_id)
		# TODO: call loan module once available

except ImportError:
	# FastAPI not installed — stub router so imports don't fail
	class _StubRouter:  # type: ignore[no-redef]
		def post(self, *a, **k):
			return lambda f: f

		def get(self, *a, **k):
			return lambda f: f

	router = _StubRouter()  # type: ignore[assignment]

__all__ = ["router"]
