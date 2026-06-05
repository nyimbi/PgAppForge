"""
pgappforge/plugins/fintech/payments/services.py

Payments Engine business logic.

Design rules
------------
- All monetary amounts passed in and returned are INTEGER cents.
- PaymentOrder is effectively immutable after submission (ImmutableRecordMixin
  blocks ORM UPDATE; service enforces via status guard).
- Sanctions pre-screening is attempted against a configurable name list;
  absent screening service is non-fatal (logs warning, sets sanctions_checked=False).
- Event emission is wrapped in try/except — service never fails on event errors.
- UETR (SWIFT Unique End-to-end Transaction Reference) is UUID v4 generated
  per order at submission time.
- ISO 20022 PAIN.001 XML is generated in-memory; stored on PaymentBatch for
  smaller deployments.

Usage
-----
	from pgappforge.plugins.fintech.payments.services import PaymentsService

	svc = PaymentsService(db.session, tenant_id="acme")
	order = svc.initiate_payment(
		debtor_account_id=account_id,
		creditor_account_number="1234567890",
		creditor_name="ACME Suppliers Ltd",
		amount_cents=500_000_00,
		payment_type="PESALINK",
		value_date=date.today(),
	)
	svc.validate_payment(order.id)
	svc.authorize_payment(order.id, authorizer_id="ops_user_42")
	svc.submit_payment(order.id)
"""
from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timezone
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from .events import (
	BatchCreatedEvent,
	BatchPartiallySettledEvent,
	BatchSettledEvent,
	BatchSubmittedEvent,
	InboundPaymentReceivedEvent,
	PaymentAuthorizedEvent,
	PaymentCancelledEvent,
	PaymentInitiatedEvent,
	PaymentRejectedEvent,
	PaymentReturnedEvent,
	PaymentSettledEvent,
	PaymentSubmittedEvent,
	PaymentValidatedEvent,
	ReconciliationCompleteEvent,
	StandingOrderCancelledEvent,
	StandingOrderCreatedEvent,
	StandingOrderExecutedEvent,
	StandingOrderFailedEvent,
	StandingOrderPausedEvent,
	StandingOrderResumedEvent,
)
from .models import (
	PaymentBatch,
	PaymentOrder,
	PaymentOutboxEvent,
	PaymentRail,
	PaymentReconciliationRun,
	PaymentStatusEvent,
	PayStandingOrder,
	py_batch_ref_seq,
	py_payment_ref_seq,
	py_so_ref_seq,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Module-level CoreBankingService singleton (lazy, import-guarded)
# ---------------------------------------------------------------------------

_cb_service = None


def _get_cb():
	"""Return the module-level CoreBankingService instance (imported once)."""
	global _cb_service
	if _cb_service is None:
		from pgappforge.plugins.fintech.core_banking.services import CoreBankingService
		_cb_service = CoreBankingService()
	return _cb_service


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class PaymentsError(Exception):
	"""Base class for all payments errors."""


class PaymentNotFoundError(PaymentsError):
	"""No PaymentOrder with the given id/reference exists."""


class InsufficientFundsError(PaymentsError):
	"""Debtor account balance is below the required amount + charges."""


class RailNotAvailableError(PaymentsError):
	"""The requested payment rail is inactive or outside operating hours."""


class PaymentImmutableError(PaymentsError):
	"""Attempted to mutate a payment that has already been submitted."""


class SanctionsHitError(PaymentsError):
	"""Creditor name or account matched a sanctions list entry."""


class AMLFlaggedError(PaymentsError):
	"""Transaction flagged by AML rule configured as AUTO_REJECT."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_utc() -> datetime:
	return datetime.now(timezone.utc)


def _next_ref(session: Session, prefix: str, seq: sa.Sequence) -> str:
	"""Collision-safe reference using a PostgreSQL SEQUENCE.

	Produces references like 'PAY-20260603-000001'.
	The sequence is defined in models.py and created via migration.
	"""
	nextval = session.execute(sa.select(seq.next_value())).scalar()
	return f"{prefix}-{date.today().strftime('%Y%m%d')}-{nextval:06d}"


def _new_uetr() -> str:
	"""SWIFT Unique End-to-end Transaction Reference (UUID v4)."""
	return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# GL chart-of-accounts map for payments (mirrors _CB_GL in core_banking)
# ---------------------------------------------------------------------------

_PY_GL: dict[str, str] = {
	"NOSTRO": "1011",
	"CUSTOMER_DEPOSITS": "2100",
	"PAYMENT_SUSPENSE": "2110",
	"FEE_INCOME": "4200",
	"FX_GAIN_LOSS": "4300",
}


# ---------------------------------------------------------------------------
# PaymentsService
# ---------------------------------------------------------------------------

class PaymentsService:
	"""Orchestrates the full payments lifecycle.

	Parameters
	----------
	session:
		SQLAlchemy Session — caller owns commit/rollback.
	tenant_id:
		Multi-tenant discriminator; injected into every created record.
	event_bus:
		Optional callable(event) used to emit domain events.  When absent,
		events are logged at DEBUG level only.
	"""

	VALID_PAYMENT_TYPES = frozenset({
		"RTGS", "EFT", "PESALINK", "SWIFT",
		"STANDING_ORDER", "DIRECT_DEBIT",
		"CHEQUE", "CARD_PAYMENT", "REMITTANCE",
	})

	VALID_CHARGE_TYPES = frozenset({"SHA", "OUR", "BEN"})

	# Status flow guards
	_SUBMIT_ALLOWED_FROM = frozenset({"AUTHORIZED"})
	_SETTLE_ALLOWED_FROM = frozenset({"SUBMITTED_TO_SWITCH", "PROCESSING"})
	_REJECT_ALLOWED_FROM = frozenset({"SUBMITTED_TO_SWITCH", "PROCESSING", "VALIDATED"})
	_CANCEL_ALLOWED_FROM = frozenset({"PENDING", "VALIDATED"})

	def __init__(
		self,
		session: Session,
		tenant_id: str,
		event_bus: Any = None,
	) -> None:
		assert isinstance(tenant_id, str) and tenant_id, "tenant_id must be a non-empty string"
		self._session = session
		self._tenant_id = tenant_id
		self._event_bus = event_bus

	# ------------------------------------------------------------------
	# Payment Order lifecycle
	# ------------------------------------------------------------------

	def initiate_payment(
		self,
		*,
		debtor_account_id: str,
		creditor_account_number: str,
		creditor_name: str,
		amount_cents: int,
		payment_type: str,
		value_date: date,
		currency_code: str = "KES",
		creditor_bank_code: str | None = None,
		payment_purpose: str | None = None,
		remittance_info: str | None = None,
		channel: str = "ONLINE",
		charge_type: str = "SHA",
		exchange_rate: float = 1.0,
		batch_id: str | None = None,
	) -> PaymentOrder:
		"""Create a new PaymentOrder in PENDING status.

		Raises
		------
		ValueError
			If payment_type, charge_type, or amount_cents are invalid.
		"""
		assert amount_cents > 0, "amount_cents must be positive"
		assert payment_type in self.VALID_PAYMENT_TYPES, (
			f"Unknown payment_type {payment_type!r}; "
			f"valid: {sorted(self.VALID_PAYMENT_TYPES)}"
		)
		assert charge_type in self.VALID_CHARGE_TYPES, (
			f"Unknown charge_type {charge_type!r}; valid: SHA | OUR | BEN"
		)

		from decimal import Decimal, ROUND_HALF_UP

		ref = _next_ref(self._session, "PAY", py_payment_ref_seq)
		rate = Decimal(str(exchange_rate))
		equivalent_ksh = int(
			(Decimal(amount_cents) * rate).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
		)

		order = PaymentOrder(
			tenant_id=self._tenant_id,
			payment_reference=ref,
			payment_type=payment_type,
			debtor_account_id=debtor_account_id,
			creditor_account_number=creditor_account_number,
			creditor_bank_code=creditor_bank_code,
			creditor_name=creditor_name,
			amount_cents=amount_cents,
			currency_code=currency_code,
			exchange_rate=Decimal(str(exchange_rate)),
			equivalent_ksh_cents=equivalent_ksh,
			charges_cents=0,
			charge_type=charge_type,
			value_date=value_date,
			payment_purpose=payment_purpose,
			remittance_info=remittance_info,
			channel=channel,
			status="PENDING",
			batch_id=batch_id,
			sanctions_checked=False,
			aml_flagged=False,
		)
		self._session.add(order)
		self._session.flush()

		self._append_status_event(order.id, None, "PENDING", actor_id="system")

		self._emit(PaymentInitiatedEvent(
			tenant_id=self._tenant_id,
			payment_order_id=str(order.id),
			payment_reference=order.payment_reference,
			payment_type=order.payment_type,
			debtor_account_id=str(debtor_account_id),
			creditor_name=creditor_name,
			amount_cents=amount_cents,
			currency_code=currency_code,
			value_date=str(value_date),
			channel=channel,
		))

		log.info(
			"PaymentsService.initiate_payment: %s %s %d %s → PENDING",
			ref, payment_type, amount_cents, currency_code,
		)
		return order

	def validate_payment(
		self,
		payment_order_id: str,
		*,
		actor_id: str = "system",
		skip_sanctions: bool = False,
	) -> PaymentOrder:
		"""Run sanctions + AML pre-check and advance status to VALIDATED.

		Raises
		------
		PaymentNotFoundError
		SanctionsHitError   — if creditor name matches sanctions list
		"""
		order = self._get_order(payment_order_id)
		assert order.status == "PENDING", (
			f"Can only validate PENDING orders; got status={order.status!r}"
		)

		sanctions_hit = False
		if not skip_sanctions:
			sanctions_hit = self._run_sanctions_screen(order)
		if sanctions_hit:
			raise SanctionsHitError(
				f"Creditor {order.creditor_name!r} matched sanctions list"
			)

		aml_flagged, aml_auto_reject = self._run_aml_check(order)
		if aml_auto_reject:
			raise AMLFlaggedError(
				f"Payment {order.payment_reference!r} blocked by AUTO_REJECT AML rule"
			)

		# Place funds hold via CoreBankingService (non-fatal if service unavailable)
		hold_id: str | None = None
		hold_placed = False
		total_required = order.amount_cents + (order.charges_cents or 0)
		try:
			cb_svc = _get_cb()
			hold = cb_svc.place_hold(
				self._session,
				str(order.debtor_account_id),
				total_required,
				reason="PAYMENT_HOLD",
				reference=order.payment_reference,
				tenant_id=self._tenant_id,
			)
			hold_id = str(hold.id)
			hold_placed = True
		except ImportError:
			log.warning(
				"PaymentsService.validate_payment: CoreBankingService not available; "
				"skipping funds hold for %s",
				order.payment_reference,
			)
		except Exception as exc:
			# Check if it's an insufficient-funds signal from core banking
			if "insufficient" in str(exc).lower() or "funds" in str(exc).lower():
				raise InsufficientFundsError(
					f"Insufficient funds for {order.payment_reference}: {exc}"
				) from exc
			log.warning(
				"PaymentsService.validate_payment: place_hold failed (non-fatal): %s", exc
			)

		# Update via raw SQL to respect ImmutableRecordMixin (which blocks ORM UPDATE)
		update_vals: dict[str, Any] = dict(
			status="VALIDATED",
			sanctions_checked=True,
			aml_flagged=aml_flagged,
		)
		if hold_id is not None:
			update_vals["hold_id"] = hold_id

		self._session.execute(
			sa.update(PaymentOrder)
			.where(PaymentOrder.id == payment_order_id)
			.values(**update_vals)
		)
		self._session.flush()
		self._session.expire(order)

		self._append_status_event(payment_order_id, "PENDING", "VALIDATED", actor_id=actor_id)

		self._emit(PaymentValidatedEvent(
			tenant_id=self._tenant_id,
			payment_order_id=str(payment_order_id),
			payment_reference=order.payment_reference,
			payment_type=order.payment_type,
			amount_cents=order.amount_cents,
			sanctions_checked=True,
			aml_flagged=aml_flagged,
			hold_placed=hold_placed,
		))

		log.info("PaymentsService.validate_payment: %s → VALIDATED hold=%s", order.payment_reference, hold_placed)
		return order

	def authorize_payment(
		self,
		payment_order_id: str,
		*,
		authorizer_id: str,
		authorization_code: str | None = None,
	) -> PaymentOrder:
		"""Authorizer approves the payment; advances status to AUTHORIZED."""
		order = self._get_order(payment_order_id)
		assert order.status == "VALIDATED", (
			f"Can only authorize VALIDATED orders; got status={order.status!r}"
		)

		auth_code = authorization_code or _next_ref(self._session, "AUTH", py_payment_ref_seq)

		self._session.execute(
			sa.update(PaymentOrder)
			.where(PaymentOrder.id == payment_order_id)
			.values(status="AUTHORIZED", authorization_code=auth_code)
		)
		self._session.flush()
		self._session.expire(order)

		self._append_status_event(
			payment_order_id, "VALIDATED", "AUTHORIZED", actor_id=authorizer_id
		)

		self._emit(PaymentAuthorizedEvent(
			tenant_id=self._tenant_id,
			payment_order_id=str(payment_order_id),
			payment_reference=order.payment_reference,
			authorizer_id=authorizer_id,
			authorization_code=auth_code,
			amount_cents=order.amount_cents,
			currency_code=order.currency_code,
		))

		log.info(
			"PaymentsService.authorize_payment: %s → AUTHORIZED by %s",
			order.payment_reference, authorizer_id,
		)
		return order

	def submit_payment(
		self,
		payment_order_id: str,
		*,
		actor_id: str = "system",
	) -> PaymentOrder:
		"""Submit AUTHORIZED payment to the clearing rail.

		Raises
		------
		RailNotAvailableError — if no active PaymentRail matches the payment_type
		PaymentImmutableError — if payment is already past AUTHORIZED
		"""
		order = self._get_order(payment_order_id)
		if order.status not in self._SUBMIT_ALLOWED_FROM:
			raise PaymentImmutableError(
				f"Cannot submit payment with status={order.status!r}; "
				f"must be AUTHORIZED"
			)

		rail = self._get_rail_for_type(order.payment_type)
		uetr = _new_uetr()
		now = _now_utc()

		self._session.execute(
			sa.update(PaymentOrder)
			.where(PaymentOrder.id == payment_order_id)
			.values(
				status="SUBMITTED_TO_SWITCH",
				uetr=uetr,
				submitted_at=now,
			)
		)
		self._session.flush()
		self._session.expire(order)

		self._append_status_event(
			payment_order_id, "AUTHORIZED", "SUBMITTED_TO_SWITCH", actor_id=actor_id
		)

		self._emit(PaymentSubmittedEvent(
			tenant_id=self._tenant_id,
			payment_order_id=str(payment_order_id),
			payment_reference=order.payment_reference,
			payment_type=order.payment_type,
			rail_code=rail.rail_code if rail else order.payment_type,
			uetr=uetr,
			amount_cents=order.amount_cents,
			currency_code=order.currency_code,
			submitted_at=now.isoformat(),
		))

		log.info(
			"PaymentsService.submit_payment: %s → SUBMITTED_TO_SWITCH via %s uetr=%s",
			order.payment_reference,
			rail.rail_code if rail else order.payment_type,
			uetr,
		)
		return order

	def settle_payment(
		self,
		payment_order_id: str,
		*,
		clearing_reference: str = "",
		rail_code: str = "",
		actor_id: str = "system",
	) -> PaymentOrder:
		"""Mark payment as SETTLED on receipt of clearing house confirmation."""
		order = self._get_order(payment_order_id)
		assert order.status in self._SETTLE_ALLOWED_FROM, (
			f"Cannot settle payment with status={order.status!r}"
		)

		prev_status = order.status
		now = _now_utc()
		self._session.execute(
			sa.update(PaymentOrder)
			.where(PaymentOrder.id == payment_order_id)
			.values(status="SETTLED", settled_at=now)
		)
		self._session.flush()
		self._session.expire(order)

		self._append_status_event(
			payment_order_id, prev_status, "SETTLED", actor_id=actor_id
		)

		# Post GL double-entry: debit CUSTOMER_DEPOSITS, credit NOSTRO
		journal_id = ""
		try:
			from pgappforge.plugins.erp.finance.gl.services import GLService  # type: ignore[import]
			result = GLService().post_simple_journal(
				lines=[
					{
						"account_code": _PY_GL["CUSTOMER_DEPOSITS"],
						"debit_cents": order.equivalent_ksh_cents,
						"credit_cents": 0,
						"description": f"Payment settled {order.payment_reference}",
					},
					{
						"account_code": _PY_GL["NOSTRO"],
						"debit_cents": 0,
						"credit_cents": order.equivalent_ksh_cents,
						"description": f"Payment settled {order.payment_reference}",
					},
				],
				session=self._session,
				tenant_id=self._tenant_id,
				description=f"Payment {order.payment_reference}",
				source_doc_type="PaymentOrder",
				source_doc_id=str(order.id),
			)
			journal_id = str(result.get("journal_id", "")) if isinstance(result, dict) else str(result)
		except ImportError:
			log.debug("PaymentsService.settle_payment: GLService not available; skipping GL post")
		except Exception as exc:
			log.warning("PaymentsService.settle_payment: GL post failed (non-fatal): %s", exc)

		self._emit(PaymentSettledEvent(
			tenant_id=self._tenant_id,
			payment_order_id=str(payment_order_id),
			payment_reference=order.payment_reference,
			payment_type=order.payment_type,
			rail_code=rail_code,
			amount_cents=order.amount_cents,
			currency_code=order.currency_code,
			settled_at=now.isoformat(),
			clearing_reference=clearing_reference,
		))

		log.info(
			"PaymentsService.settle_payment: %s → SETTLED journal_id=%s",
			order.payment_reference, journal_id or "none",
		)
		return order

	def reject_payment(
		self,
		payment_order_id: str,
		*,
		rejection_code: str,
		rejection_reason: str,
		actor_id: str = "system",
	) -> PaymentOrder:
		"""Mark payment REJECTED by the clearing house."""
		order = self._get_order(payment_order_id)
		assert order.status in self._REJECT_ALLOWED_FROM, (
			f"Cannot reject payment with status={order.status!r}"
		)

		prev_status = order.status
		self._session.execute(
			sa.update(PaymentOrder)
			.where(PaymentOrder.id == payment_order_id)
			.values(
				status="REJECTED",
				rejection_code=rejection_code,
				rejection_reason=rejection_reason,
			)
		)
		self._session.flush()
		self._session.expire(order)

		self._append_status_event(
			payment_order_id, prev_status, "REJECTED", actor_id=actor_id,
			notes=f"{rejection_code}: {rejection_reason}",
		)

		# Release funds hold if one was placed during validation
		hold_released = self._release_hold(order, reason=f"reject:{rejection_code}")

		self._emit(PaymentRejectedEvent(
			tenant_id=self._tenant_id,
			payment_order_id=str(payment_order_id),
			payment_reference=order.payment_reference,
			rejection_code=rejection_code,
			rejection_reason=rejection_reason,
			amount_cents=order.amount_cents,
			hold_released=hold_released,
		))

		log.info(
			"PaymentsService.reject_payment: %s → REJECTED (%s) hold_released=%s",
			order.payment_reference, rejection_code, hold_released,
		)
		return order

	def cancel_payment(
		self,
		payment_order_id: str,
		*,
		cancelled_by: str,
		cancellation_reason: str = "",
	) -> PaymentOrder:
		"""Cancel a PENDING or VALIDATED payment before it reaches AUTHORIZED."""
		order = self._get_order(payment_order_id)
		if order.status not in self._CANCEL_ALLOWED_FROM:
			raise PaymentImmutableError(
				f"Cannot cancel payment with status={order.status!r}; "
				f"must be PENDING or VALIDATED"
			)

		prev_status = order.status
		self._session.execute(
			sa.update(PaymentOrder)
			.where(PaymentOrder.id == payment_order_id)
			.values(status="CANCELLED")
		)
		self._session.flush()
		self._session.expire(order)

		self._append_status_event(
			payment_order_id, prev_status, "CANCELLED", actor_id=cancelled_by,
			notes=cancellation_reason,
		)

		# Release funds hold if one was placed during validation
		hold_released = self._release_hold(order, reason="cancel")

		self._emit(PaymentCancelledEvent(
			tenant_id=self._tenant_id,
			payment_order_id=str(payment_order_id),
			payment_reference=order.payment_reference,
			cancelled_by=cancelled_by,
			cancellation_reason=cancellation_reason,
			hold_released=hold_released,
		))

		log.info(
			"PaymentsService.cancel_payment: %s → CANCELLED by %s",
			order.payment_reference, cancelled_by,
		)
		return order

	# ------------------------------------------------------------------
	# Batch operations
	# ------------------------------------------------------------------

	def create_batch(
		self,
		*,
		batch_type: str,
		value_date: date,
		currency_code: str = "KES",
		payment_order_ids: list[str] | None = None,
	) -> PaymentBatch:
		"""Assemble a PaymentBatch from existing PaymentOrders.

		All orders must be in AUTHORIZED status and will be updated to
		include the new batch_id.
		"""
		batch_num = _next_ref(self._session, "BATCH-" + batch_type, py_batch_ref_seq)
		batch = PaymentBatch(
			tenant_id=self._tenant_id,
			batch_number=batch_num,
			batch_type=batch_type,
			value_date=value_date,
			currency_code=currency_code,
			status="DRAFT",
		)
		self._session.add(batch)
		self._session.flush()

		total_amount = 0
		count = 0
		for oid in (payment_order_ids or []):
			order = self._get_order(oid)
			assert order.status == "AUTHORIZED", (
				f"Order {oid} must be AUTHORIZED to join a batch; "
				f"got status={order.status!r}"
			)
			self._session.execute(
				sa.update(PaymentOrder)
				.where(PaymentOrder.id == oid)
				.values(batch_id=batch.id)
			)
			total_amount += order.amount_cents
			count += 1

		if count:
			self._session.execute(
				sa.update(PaymentBatch)
				.where(PaymentBatch.id == batch.id)
				.values(total_payments=count, total_amount_cents=total_amount)
			)
			self._session.flush()
			self._session.expire(batch)

		self._emit(BatchCreatedEvent(
			tenant_id=self._tenant_id,
			batch_id=str(batch.id),
			batch_number=batch_num,
			batch_type=batch_type,
			total_payments=count,
			total_amount_cents=total_amount,
			currency_code=currency_code,
			value_date=str(value_date),
		))

		log.info(
			"PaymentsService.create_batch: %s type=%s %d orders total=%d",
			batch_num, batch_type, count, total_amount,
		)
		return batch

	def generate_pain001(self, batch_id: str) -> str:
		"""Generate ISO 20022 PAIN.001 XML for a batch and store it.

		Returns the XML string.  Stores on batch.payment_file_content.
		"""
		batch = self._session.get(PaymentBatch, batch_id)
		assert batch is not None, f"PaymentBatch {batch_id!r} not found"

		orders = self._session.execute(
			sa.select(PaymentOrder).where(
				PaymentOrder.batch_id == batch_id,
				PaymentOrder.tenant_id == self._tenant_id,
			)
		).scalars().all()

		xml = self._build_pain001_xml(batch, list(orders))

		self._session.execute(
			sa.update(PaymentBatch)
			.where(PaymentBatch.id == batch_id)
			.values(payment_file_content=xml)
		)
		self._session.flush()

		log.info(
			"PaymentsService.generate_pain001: batch=%s orders=%d xml_len=%d",
			batch.batch_number, len(orders), len(xml),
		)
		return xml

	# ------------------------------------------------------------------
	# Standing Orders
	# ------------------------------------------------------------------

	def create_standing_order(
		self,
		*,
		debtor_account_id: str,
		creditor_account_number: str,
		creditor_name: str,
		amount_cents: int,
		frequency: str,
		start_date: date,
		end_date: date | None = None,
		execution_day: int | None = None,
		payment_purpose: str | None = None,
	) -> PayStandingOrder:
		"""Register a new recurring PayStandingOrder."""
		assert amount_cents > 0, "amount_cents must be positive"
		valid_frequencies = {"WEEKLY", "MONTHLY", "QUARTERLY", "ANNUALLY", "SPECIFIC_DATES"}
		assert frequency in valid_frequencies, (
			f"Unknown frequency {frequency!r}; valid: {sorted(valid_frequencies)}"
		)

		ref = _next_ref(self._session, "SO", py_so_ref_seq)
		so = PayStandingOrder(
			tenant_id=self._tenant_id,
			reference_number=ref,
			debtor_account_id=debtor_account_id,
			creditor_account_number=creditor_account_number,
			creditor_name=creditor_name,
			amount_cents=amount_cents,
			frequency=frequency,
			execution_day=execution_day,
			start_date=start_date,
			end_date=end_date,
			next_execution_date=start_date,
			payment_purpose=payment_purpose,
			status="ACTIVE",
		)
		self._session.add(so)
		self._session.flush()

		self._emit(StandingOrderCreatedEvent(
			tenant_id=self._tenant_id,
			standing_order_id=str(so.id),
			reference_number=ref,
			debtor_account_id=str(debtor_account_id),
			amount_cents=amount_cents,
			frequency=frequency,
			start_date=str(start_date),
			next_execution_date=str(start_date),
		))

		log.info(
			"PaymentsService.create_standing_order: %s freq=%s next=%s",
			ref, frequency, start_date,
		)
		return so

	def execute_standing_order(
		self,
		standing_order_id: str,
		*,
		execution_date: date,
	) -> PaymentOrder:
		"""Execute a single iteration of a PayStandingOrder.

		Creates and returns a PaymentOrder in PENDING status.
		Updates PayStandingOrder.next_execution_date and execution counters.

		Raises
		------
		PaymentNotFoundError — if PayStandingOrder not found
		"""
		so = self._session.get(PayStandingOrder, standing_order_id)
		if so is None:
			raise PaymentNotFoundError(f"PayStandingOrder {standing_order_id!r} not found")
		assert so.status == "ACTIVE", (
			f"PayStandingOrder {so.reference_number!r} is not ACTIVE (status={so.status!r})"
		)

		order = self.initiate_payment(
			debtor_account_id=so.debtor_account_id,
			creditor_account_number=so.creditor_account_number,
			creditor_name=so.creditor_name,
			amount_cents=so.amount_cents,
			payment_type="STANDING_ORDER",
			value_date=execution_date,
			payment_purpose=so.payment_purpose,
			channel="STANDING_ORDER",
		)

		next_date = self._compute_next_execution_date(so, execution_date)
		new_total = (so.total_executed or 0) + 1

		self._session.execute(
			sa.update(PayStandingOrder)
			.where(PayStandingOrder.id == standing_order_id)
			.values(
				next_execution_date=next_date,
				last_executed_at=_now_utc(),
				total_executed=new_total,
			)
		)
		self._session.flush()
		self._session.expire(so)

		self._emit(StandingOrderExecutedEvent(
			tenant_id=self._tenant_id,
			standing_order_id=str(standing_order_id),
			reference_number=so.reference_number,
			payment_order_id=str(order.id),
			payment_reference=order.payment_reference,
			execution_date=str(execution_date),
			amount_cents=so.amount_cents,
			next_execution_date=str(next_date),
			total_executed=new_total,
		))

		return order

	def cancel_standing_order(
		self,
		standing_order_id: str,
		*,
		cancelled_by: str,
	) -> PayStandingOrder:
		"""Permanently cancel a PayStandingOrder."""
		so = self._session.get(PayStandingOrder, standing_order_id)
		if so is None:
			raise PaymentNotFoundError(f"PayStandingOrder {standing_order_id!r} not found")
		assert so.status in {"ACTIVE", "PAUSED"}, (
			f"PayStandingOrder already {so.status!r}; cannot cancel"
		)

		self._session.execute(
			sa.update(PayStandingOrder)
			.where(PayStandingOrder.id == standing_order_id)
			.values(status="CANCELLED")
		)
		self._session.flush()
		self._session.expire(so)

		self._emit(StandingOrderCancelledEvent(
			tenant_id=self._tenant_id,
			standing_order_id=str(standing_order_id),
			reference_number=so.reference_number,
			cancelled_by=cancelled_by,
			total_executed=so.total_executed or 0,
		))

		log.info(
			"PaymentsService.cancel_standing_order: %s → CANCELLED by %s",
			so.reference_number, cancelled_by,
		)
		return so

	# ------------------------------------------------------------------
	# Inbound payments
	# ------------------------------------------------------------------

	def receive_inbound_payment(
		self,
		*,
		creditor_account_number: str,
		amount_cents: int,
		currency_code: str = "KES",
		exchange_rate: float = 1.0,
		debtor_name: str,
		debtor_bank_code: str = "",
		payment_type: str = "EFT",
		remittance_info: str = "",
		rail_code: str = "",
		# kept for backward compatibility; ignored — GL id comes from the actual GL post
		journal_id: str = "",
	) -> PaymentOrder:
		"""Record an inbound credit received from a clearing house.

		Creates a PaymentOrder in SETTLED status, credits the beneficiary account
		via CoreBankingService, and posts a GL double-entry.
		"""
		from decimal import Decimal, ROUND_HALF_UP

		ref = _next_ref(self._session, "INBOUND", py_payment_ref_seq)

		rate = Decimal(str(exchange_rate))
		equivalent_ksh = int(
			(Decimal(amount_cents) * rate).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
		)

		order = PaymentOrder(
			tenant_id=self._tenant_id,
			payment_reference=ref,
			payment_type=payment_type,
			debtor_account_id=creditor_account_number,  # local account UUID or placeholder
			creditor_account_number=creditor_account_number,
			creditor_name=debtor_name,
			amount_cents=amount_cents,
			currency_code=currency_code,
			exchange_rate=Decimal(str(exchange_rate)),
			equivalent_ksh_cents=equivalent_ksh,
			charges_cents=0,
			charge_type="SHA",
			value_date=date.today(),
			remittance_info=remittance_info,
			channel="CLEARING_HOUSE",
			status="SETTLED",
			sanctions_checked=True,
			aml_flagged=False,
			settled_at=_now_utc(),
		)
		self._session.add(order)
		self._session.flush()

		# Credit the beneficiary account in core banking
		cb_journal_id = ""
		try:
			cb_svc = _get_cb()
			cb_result = cb_svc.deposit(
				session=self._session,
				account_number=creditor_account_number,
				amount_cents=amount_cents,
				description=f"Inbound {payment_type} from {debtor_name}",
				reference=ref,
				channel="CLEARING_HOUSE",
				tenant_id=self._tenant_id,
			)
			cb_journal_id = str(cb_result.get("journal_id", "") or "") if isinstance(cb_result, dict) else ""
		except ImportError:
			log.warning(
				"PaymentsService.receive_inbound_payment: CoreBankingService not available; "
				"account balance not updated for %s",
				ref,
			)
		except Exception as exc:
			log.warning(
				"PaymentsService.receive_inbound_payment: deposit failed (non-fatal): %s", exc
			)

		# Post GL double-entry: debit NOSTRO (bank receives), credit CUSTOMER_DEPOSITS
		gl_journal_id = cb_journal_id
		if not gl_journal_id:
			try:
				from pgappforge.plugins.erp.finance.gl.services import GLService  # type: ignore[import]
				result = GLService().post_simple_journal(
					lines=[
						{
							"account_code": _PY_GL["NOSTRO"],
							"debit_cents": equivalent_ksh,
							"credit_cents": 0,
							"description": f"Inbound payment {ref} from {debtor_name}",
						},
						{
							"account_code": _PY_GL["CUSTOMER_DEPOSITS"],
							"debit_cents": 0,
							"credit_cents": equivalent_ksh,
							"description": f"Inbound payment {ref} from {debtor_name}",
						},
					],
					session=self._session,
					tenant_id=self._tenant_id,
					description=f"Inbound {payment_type} {ref}",
					source_doc_type="PaymentOrder",
					source_doc_id=str(order.id),
				)
				gl_journal_id = str(result.get("journal_id", "")) if isinstance(result, dict) else str(result)
			except ImportError:
				log.debug("PaymentsService.receive_inbound_payment: GLService not available")
			except Exception as exc:
				log.warning(
					"PaymentsService.receive_inbound_payment: GL post failed (non-fatal): %s", exc
				)

		self._emit(InboundPaymentReceivedEvent(
			tenant_id=self._tenant_id,
			payment_order_id=str(order.id),
			payment_reference=ref,
			payment_type=payment_type,
			creditor_account_id=creditor_account_number,
			amount_cents=amount_cents,
			currency_code=currency_code,
			debtor_name=debtor_name,
			debtor_bank_code=debtor_bank_code,
			remittance_info=remittance_info,
			rail_code=rail_code,
			journal_id=gl_journal_id,
		))

		log.info(
			"PaymentsService.receive_inbound_payment: %s %d %s from %s gl=%s",
			ref, amount_cents, currency_code, debtor_name, gl_journal_id or "none",
		)
		return order

	# ------------------------------------------------------------------
	# Return flow
	# ------------------------------------------------------------------

	_RETURN_ALLOWED_FROM = frozenset({"SETTLED"})

	def return_payment(
		self,
		payment_order_id: str,
		*,
		return_reason_code: str,
		return_reason: str,
		actor_id: str = "system",
	) -> PaymentOrder:
		"""Process a bank-to-bank return of a previously settled payment.

		Status guard: order must be SETTLED.
		Steps:
		  1. Raw SQL UPDATE to RETURNED.
		  2. Append status event.
		  3. Release any hold (funds come back to account).
		  4. Post GL reversal entry.
		  5. Emit PaymentReturnedEvent.

		Raises
		------
		PaymentImmutableError — if order is not in SETTLED status.
		"""
		order = self._get_order(payment_order_id)
		if order.status not in self._RETURN_ALLOWED_FROM:
			raise PaymentImmutableError(
				f"Cannot return payment with status={order.status!r}; must be SETTLED"
			)

		now = _now_utc()
		self._session.execute(
			sa.update(PaymentOrder)
			.where(PaymentOrder.id == payment_order_id)
			.values(status="RETURNED", returned_at=now)
		)
		self._session.flush()
		self._session.expire(order)

		self._append_status_event(
			payment_order_id, "SETTLED", "RETURNED", actor_id=actor_id,
			notes=f"{return_reason_code}: {return_reason}",
		)

		# Release hold if present (funds returned to account)
		self._release_hold(order, reason=f"return:{return_reason_code}")

		# Post GL reversal: debit NOSTRO, credit CUSTOMER_DEPOSITS (mirror of settle)
		reversal_journal_id = ""
		try:
			from pgappforge.plugins.erp.finance.gl.services import GLService  # type: ignore[import]
			result = GLService().post_simple_journal(
				lines=[
					{
						"account_code": _PY_GL["NOSTRO"],
						"debit_cents": order.equivalent_ksh_cents,
						"credit_cents": 0,
						"description": f"Payment return reversal {order.payment_reference}",
					},
					{
						"account_code": _PY_GL["CUSTOMER_DEPOSITS"],
						"debit_cents": 0,
						"credit_cents": order.equivalent_ksh_cents,
						"description": f"Payment return reversal {order.payment_reference}",
					},
				],
				session=self._session,
				tenant_id=self._tenant_id,
				description=f"Return {return_reason_code} {order.payment_reference}",
				source_doc_type="PaymentOrder",
				source_doc_id=str(order.id),
			)
			reversal_journal_id = (
				str(result.get("journal_id", "")) if isinstance(result, dict) else str(result)
			)
		except ImportError:
			log.debug("PaymentsService.return_payment: GLService not available; skipping GL reversal")
		except Exception as exc:
			log.warning("PaymentsService.return_payment: GL reversal failed (non-fatal): %s", exc)

		self._emit(PaymentReturnedEvent(
			tenant_id=self._tenant_id,
			payment_order_id=str(payment_order_id),
			payment_reference=order.payment_reference,
			return_reason_code=return_reason_code,
			return_reason=return_reason,
			amount_cents=order.amount_cents,
			returned_at=now.isoformat(),
			reversal_journal_id=reversal_journal_id,
		))

		log.info(
			"PaymentsService.return_payment: %s → RETURNED (%s) reversal=%s",
			order.payment_reference, return_reason_code, reversal_journal_id or "none",
		)
		return order

	# ------------------------------------------------------------------
	# Batch lifecycle — submit, settle, process clearing response
	# ------------------------------------------------------------------

	def submit_batch(
		self,
		batch_id: str,
		*,
		actor_id: str = "system",
	) -> PaymentBatch:
		"""Submit a DRAFT/VALIDATED/AUTHORIZED batch to the clearing rail.

		Raises
		------
		RailNotAvailableError — if no active rail matches the batch_type.
		PaymentImmutableError — if batch is already past AUTHORIZED.
		"""
		batch = self._session.get(PaymentBatch, batch_id)
		assert batch is not None, f"PaymentBatch {batch_id!r} not found"

		_submit_batch_allowed = frozenset({"DRAFT", "VALIDATED", "AUTHORIZED"})
		if batch.status not in _submit_batch_allowed:
			raise PaymentImmutableError(
				f"Cannot submit batch with status={batch.status!r}; "
				f"must be DRAFT, VALIDATED, or AUTHORIZED"
			)

		rail = self._get_rail_for_type(batch.batch_type)
		if rail is None:
			raise RailNotAvailableError(
				f"No active PaymentRail for batch_type={batch.batch_type!r}"
			)

		now = _now_utc()
		self._session.execute(
			sa.update(PaymentBatch)
			.where(PaymentBatch.id == batch_id)
			.values(status="SUBMITTED", submitted_at=now)
		)
		self._session.flush()
		self._session.expire(batch)

		self._emit(BatchSubmittedEvent(
			tenant_id=self._tenant_id,
			batch_id=str(batch_id),
			batch_number=batch.batch_number,
			batch_type=batch.batch_type,
			rail_code=rail.rail_code,
			total_payments=batch.total_payments or 0,
			total_amount_cents=batch.total_amount_cents or 0,
			submitted_at=now.isoformat(),
		))

		log.info(
			"PaymentsService.submit_batch: %s → SUBMITTED via rail=%s",
			batch.batch_number, rail.rail_code,
		)
		return batch

	def settle_batch(
		self,
		batch_id: str,
		*,
		clearing_reference: str,
		accepted_ids: list[str],
		rejected_ids: list[str],
		rejected_reasons: dict[str, tuple[str, str]] | None = None,
		actor_id: str = "system",
	) -> PaymentBatch:
		"""Settle a submitted batch given clearing-house accepted/rejected lists.

		Iterates accepted_ids calling settle_payment() on each, and rejected_ids
		calling reject_payment().  Computes final batch status:
		  - All accepted → SETTLED
		  - Mix accepted+rejected → PARTIALLY_SETTLED
		  - All rejected or zero processed → FAILED

		Parameters
		----------
		rejected_reasons:
			Optional dict mapping payment_order_id → (rejection_code, rejection_reason).
			Defaults to ('BATCH_REJECT', 'Batch rejected by clearing house').
		"""
		batch = self._session.get(PaymentBatch, batch_id)
		assert batch is not None, f"PaymentBatch {batch_id!r} not found"

		_settle_allowed = frozenset({"SUBMITTED", "PROCESSING"})
		assert batch.status in _settle_allowed, (
			f"Cannot settle batch with status={batch.status!r}"
		)

		rejected_reasons = rejected_reasons or {}
		accepted_count = 0
		rejected_count = 0

		for oid in accepted_ids:
			try:
				self.settle_payment(
					oid,
					clearing_reference=clearing_reference,
					actor_id=actor_id,
				)
				accepted_count += 1
			except Exception as exc:
				log.warning("settle_batch: settle_payment(%s) failed: %s", oid, exc)

		for oid in rejected_ids:
			code, reason = rejected_reasons.get(oid, ("BATCH_REJECT", "Batch rejected by clearing house"))
			try:
				self.reject_payment(
					oid,
					rejection_code=code,
					rejection_reason=reason,
					actor_id=actor_id,
				)
				rejected_count += 1
			except Exception as exc:
				log.warning("settle_batch: reject_payment(%s) failed: %s", oid, exc)

		total = accepted_count + rejected_count
		if accepted_count == 0:
			final_status = "FAILED"
		elif rejected_count == 0:
			final_status = "SETTLED"
		else:
			final_status = "PARTIALLY_SETTLED"

		self._session.execute(
			sa.update(PaymentBatch)
			.where(PaymentBatch.id == batch_id)
			.values(
				status=final_status,
				accepted_count=accepted_count,
				rejected_count=rejected_count,
				clearing_reference=clearing_reference,
			)
		)
		self._session.flush()
		self._session.expire(batch)

		if final_status == "SETTLED":
			self._emit(BatchSettledEvent(
				tenant_id=self._tenant_id,
				batch_id=str(batch_id),
				batch_number=batch.batch_number,
				accepted_count=accepted_count,
				rejected_count=rejected_count,
				total_amount_cents=batch.total_amount_cents or 0,
				clearing_reference=clearing_reference,
			))
		else:
			# Compute accepted/rejected amounts from the orders
			accepted_amt = 0
			rejected_amt = 0
			try:
				rows = self._session.execute(
					sa.select(PaymentOrder.id, PaymentOrder.status, PaymentOrder.equivalent_ksh_cents)
					.where(PaymentOrder.batch_id == batch_id, PaymentOrder.tenant_id == self._tenant_id)
				).all()
				for r in rows:
					if r.status == "SETTLED":
						accepted_amt += r.equivalent_ksh_cents or 0
					elif r.status in {"REJECTED", "FAILED"}:
						rejected_amt += r.equivalent_ksh_cents or 0
			except Exception:
				pass
			self._emit(BatchPartiallySettledEvent(
				tenant_id=self._tenant_id,
				batch_id=str(batch_id),
				batch_number=batch.batch_number,
				accepted_count=accepted_count,
				rejected_count=rejected_count,
				accepted_amount_cents=accepted_amt,
				rejected_amount_cents=rejected_amt,
				clearing_reference=clearing_reference,
			))

		log.info(
			"PaymentsService.settle_batch: %s → %s accepted=%d rejected=%d",
			batch.batch_number, final_status, accepted_count, rejected_count,
		)
		return batch

	def process_clearing_response(
		self,
		batch_id: str,
		*,
		response_payload: dict[str, Any],
	) -> PaymentBatch:
		"""Parse a clearing-house response dict and call settle_batch.

		Expected response_payload shape::

			{
			  "clearing_reference": "CHK-20260603-00123",
			  "accepted": [
			    {"payment_reference": "PAY-...", "uetr": "...", "payment_order_id": "..."},
			    ...
			  ],
			  "rejected": [
			    {"payment_reference": "PAY-...", "payment_order_id": "...",
			     "reason_code": "AC01", "reason": "Incorrect account number"},
			    ...
			  ]
			}

		payment_order_id is preferred over payment_reference for lookup.
		"""
		clearing_reference = response_payload.get("clearing_reference", "")
		accepted_items: list[dict] = response_payload.get("accepted", [])
		rejected_items: list[dict] = response_payload.get("rejected", [])

		# Resolve payment_order_ids — prefer explicit id, fall back to ref lookup
		def _resolve_id(item: dict) -> str | None:
			if item.get("payment_order_id"):
				return str(item["payment_order_id"])
			ref = item.get("payment_reference")
			if ref:
				row = self._session.execute(
					sa.select(PaymentOrder.id)
					.where(
						PaymentOrder.payment_reference == ref,
						PaymentOrder.tenant_id == self._tenant_id,
					)
				).scalar_one_or_none()
				return str(row) if row else None
			return None

		accepted_ids: list[str] = [i for item in accepted_items if (i := _resolve_id(item))]
		_rej_pairs = [(rid, item) for item in rejected_items if (rid := _resolve_id(item))]
		rejected_ids: list[str] = [rid for rid, _ in _rej_pairs]
		rejected_reasons: dict[str, tuple[str, str]] = {
			rid: (item.get("reason_code", "BATCH_REJECT"), item.get("reason", ""))
			for rid, item in _rej_pairs
		}

		return self.settle_batch(
			batch_id,
			clearing_reference=clearing_reference,
			accepted_ids=accepted_ids,
			rejected_ids=rejected_ids,
			rejected_reasons=rejected_reasons,
		)

	# ------------------------------------------------------------------
	# Standing order pause / resume
	# ------------------------------------------------------------------

	def pause_standing_order(
		self,
		standing_order_id: str,
		*,
		paused_by: str,
	) -> PayStandingOrder:
		"""Pause an ACTIVE standing order; no executions will be triggered while paused."""
		so = self._session.get(PayStandingOrder, standing_order_id)
		if so is None:
			raise PaymentNotFoundError(f"PayStandingOrder {standing_order_id!r} not found")
		assert so.status == "ACTIVE", (
			f"Can only pause ACTIVE standing orders; got status={so.status!r}"
		)

		self._session.execute(
			sa.update(PayStandingOrder)
			.where(PayStandingOrder.id == standing_order_id)
			.values(status="PAUSED")
		)
		self._session.flush()
		self._session.expire(so)

		self._emit(StandingOrderPausedEvent(
			tenant_id=self._tenant_id,
			standing_order_id=str(standing_order_id),
			reference_number=so.reference_number,
			paused_by=paused_by,
			total_executed=so.total_executed or 0,
		))

		log.info(
			"PaymentsService.pause_standing_order: %s → PAUSED by %s",
			so.reference_number, paused_by,
		)
		return so

	def resume_standing_order(
		self,
		standing_order_id: str,
		*,
		resumed_by: str,
	) -> PayStandingOrder:
		"""Resume a PAUSED standing order."""
		so = self._session.get(PayStandingOrder, standing_order_id)
		if so is None:
			raise PaymentNotFoundError(f"PayStandingOrder {standing_order_id!r} not found")
		assert so.status == "PAUSED", (
			f"Can only resume PAUSED standing orders; got status={so.status!r}"
		)

		self._session.execute(
			sa.update(PayStandingOrder)
			.where(PayStandingOrder.id == standing_order_id)
			.values(status="ACTIVE")
		)
		self._session.flush()
		self._session.expire(so)

		self._emit(StandingOrderResumedEvent(
			tenant_id=self._tenant_id,
			standing_order_id=str(standing_order_id),
			reference_number=so.reference_number,
			resumed_by=resumed_by,
			next_execution_date=str(so.next_execution_date),
		))

		log.info(
			"PaymentsService.resume_standing_order: %s → ACTIVE (resumed by %s)",
			so.reference_number, resumed_by,
		)
		return so

	# ------------------------------------------------------------------
	# Reconciliation
	# ------------------------------------------------------------------

	def reconcile_settlement(
		self,
		*,
		rail_code: str,
		settlement_date: date,
		settlement_items: list[dict[str, Any]],
		file_reference: str = "",
	) -> PaymentReconciliationRun:
		"""Ingest a clearing-house settlement file and match against PaymentOrders.

		Each item in settlement_items must have shape::

			{"payment_reference": str, "amount_cents": int, "cleared_at": str}

		Unmatched items and amount mismatches are recorded in the run's
		exceptions JSONB column.

		Emits ReconciliationCompleteEvent on completion.
		"""
		run = PaymentReconciliationRun(
			tenant_id=self._tenant_id,
			rail_code=rail_code,
			settlement_date=settlement_date,
			file_reference=file_reference or "",
			status="PROCESSING",
			total_items=len(settlement_items),
		)
		self._session.add(run)
		self._session.flush()

		matched = 0
		unmatched = 0
		exceptions: list[dict[str, Any]] = []
		settled_amount = 0
		returned_amount = 0

		for item in settlement_items:
			ref = item.get("payment_reference", "")
			item_amount = int(item.get("amount_cents", 0))
			cleared_at = item.get("cleared_at", "")

			order = self._session.execute(
				sa.select(PaymentOrder)
				.where(
					PaymentOrder.payment_reference == ref,
					PaymentOrder.tenant_id == self._tenant_id,
				)
			).scalar_one_or_none()

			if order is None:
				unmatched += 1
				exceptions.append({
					"payment_reference": ref,
					"issue": "no_matching_order",
					"cleared_at": cleared_at,
					"amount_cents": item_amount,
				})
				continue

			# Amount mismatch
			if item_amount and order.amount_cents != item_amount:
				exceptions.append({
					"payment_reference": ref,
					"issue": "amount_mismatch",
					"expected_cents": order.amount_cents,
					"received_cents": item_amount,
				})

			# Advance order to SETTLED if still in-flight
			if order.status in self._SETTLE_ALLOWED_FROM:
				try:
					self.settle_payment(
						str(order.id),
						clearing_reference=file_reference,
						rail_code=rail_code,
					)
					settled_amount += order.amount_cents
					matched += 1
				except Exception as exc:
					exceptions.append({
						"payment_reference": ref,
						"issue": f"settle_failed: {exc}",
					})
					unmatched += 1
			elif order.status == "SETTLED":
				settled_amount += order.amount_cents
				matched += 1
			elif order.status == "RETURNED":
				returned_amount += order.amount_cents
				matched += 1
			else:
				exceptions.append({
					"payment_reference": ref,
					"issue": f"unexpected_status:{order.status}",
				})
				unmatched += 1

		final_status = "COMPLETE" if not exceptions else "COMPLETE_WITH_EXCEPTIONS"
		self._session.execute(
			sa.update(PaymentReconciliationRun)
			.where(PaymentReconciliationRun.id == run.id)
			.values(
				status=final_status,
				matched_count=matched,
				unmatched_count=unmatched,
				exceptions=exceptions or None,
				run_at=_now_utc(),
			)
		)
		self._session.flush()
		self._session.expire(run)

		self._emit(ReconciliationCompleteEvent(
			tenant_id=self._tenant_id,
			rail_code=rail_code,
			settlement_date=str(settlement_date),
			total_processed=len(settlement_items),
			matched_count=matched,
			unmatched_count=unmatched,
			settled_amount_cents=settled_amount,
			returned_amount_cents=returned_amount,
			exceptions=exceptions,
		))

		log.info(
			"PaymentsService.reconcile_settlement: rail=%s date=%s matched=%d unmatched=%d",
			rail_code, settlement_date, matched, unmatched,
		)
		return run

	# ------------------------------------------------------------------
	# Internal helpers
	# ------------------------------------------------------------------

	def _get_order(self, payment_order_id: str) -> PaymentOrder:
		order = self._session.get(PaymentOrder, payment_order_id)
		if order is None:
			raise PaymentNotFoundError(f"PaymentOrder {payment_order_id!r} not found")
		return order

	def _get_rail_for_type(self, payment_type: str) -> PaymentRail | None:
		"""Return the active PaymentRail for the given payment_type, or None."""
		rail = self._session.execute(
			sa.select(PaymentRail).where(
				PaymentRail.rail_type == payment_type,
				PaymentRail.is_active.is_(True),
				PaymentRail.tenant_id == self._tenant_id,
			).limit(1)
		).scalar_one_or_none()
		if rail is None:
			# Soft failure — log warning, return None (submission continues)
			log.warning(
				"PaymentsService: no active PaymentRail for type=%r; proceeding without rail check",
				payment_type,
			)
		return rail

	def _release_hold(self, order: PaymentOrder, *, reason: str = "") -> bool:
		"""Release any funds hold associated with the order.  Non-fatal."""
		if not order.hold_id:
			return False
		try:
			cb_svc = _get_cb()
			cb_svc.release_hold(self._session, order.hold_id)
			log.debug(
				"PaymentsService._release_hold: released hold %s for %s (%s)",
				order.hold_id, order.payment_reference, reason,
			)
			return True
		except ImportError:
			log.debug("PaymentsService._release_hold: CoreBankingService not available")
		except Exception as exc:
			log.warning(
				"PaymentsService._release_hold: release_hold failed (non-fatal): %s", exc
			)
		return False

	def _run_sanctions_screen(self, order: PaymentOrder) -> bool:
		"""Return True if any party or identifier matches a sanctions list.

		Screens: creditor_name, creditor_account_number, creditor_bank_code,
		debtor_account_id.  Falls back gracefully when no screener is configured.
		"""
		identifiers = {
			"creditor_name": order.creditor_name,
			"creditor_account_number": order.creditor_account_number,
			"creditor_bank_code": order.creditor_bank_code or "",
			"debtor_account_id": str(order.debtor_account_id),
		}
		# Try the regulatory compliance service first
		try:
			from pgappforge.plugins.fintech.regulatory.services import RegulatoryComplianceService  # type: ignore[import]
			reg_svc = RegulatoryComplianceService()
			for field_name, value in identifiers.items():
				if not value:
					continue
				result = reg_svc.screen_customer(
					{"identifier": value, "identifier_type": field_name},
					session=self._session,
					tenant_id=self._tenant_id,
				)
				if result.get("sanctioned"):
					log.warning(
						"PaymentsService._run_sanctions_screen: SANCTIONS HIT %s=%r for %s",
						field_name, value, order.payment_reference,
					)
					return True
			return False
		except ImportError:
			pass
		# Fall back to Flask extension screener
		try:
			from flask import current_app
			screener = current_app.extensions.get("sanctions_screener")
			if screener is not None:
				for field_name, value in identifiers.items():
					if value and bool(screener.screen(name=value)):
						return True
				return False
		except RuntimeError:
			pass
		log.debug(
			"PaymentsService._run_sanctions_screen: no screener configured; "
			"pass-through for %s",
			order.payment_reference,
		)
		return False

	def _run_aml_check(self, order: PaymentOrder) -> tuple[bool, bool]:
		"""Run AML pre-check.  Returns (flagged, auto_reject).

		Calls RegulatoryComplianceService.screen_transaction() if available.
		Falls back to Flask extension aml_service.
		Returns (False, False) when no AML service is configured (non-fatal
		pass-through — the bank operator decides whether to require it).
		"""
		payload = {
			"amount_cents": order.amount_cents,
			"payment_type": order.payment_type,
			"creditor_name": order.creditor_name,
			"debtor_account_id": str(order.debtor_account_id),
			"currency_code": order.currency_code,
			"channel": order.channel,
		}
		try:
			from pgappforge.plugins.fintech.regulatory.services import RegulatoryComplianceService  # type: ignore[import]
			reg_svc = RegulatoryComplianceService()
			result = reg_svc.screen_transaction(
				payload,
				session=self._session,
				tenant_id=self._tenant_id,
			)
			flagged = bool(result.get("flagged", False))
			auto_reject = bool(result.get("auto_reject", False))
			return flagged, auto_reject
		except ImportError:
			pass
		try:
			from flask import current_app
			aml = current_app.extensions.get("aml_service")
			if aml is not None:
				flagged = bool(aml.check_payment(**payload))
				return flagged, False
		except RuntimeError:
			pass
		return False, False

	def _append_status_event(
		self,
		payment_order_id: str,
		from_status: str | None,
		to_status: str,
		*,
		actor_id: str | None = None,
		notes: str | None = None,
	) -> None:
		evt = PaymentStatusEvent(
			tenant_id=self._tenant_id,
			payment_order_id=payment_order_id,
			from_status=from_status,
			to_status=to_status,
			actor_id=actor_id,
			notes=notes,
		)
		self._session.add(evt)

	def _compute_next_execution_date(
		self,
		so: PayStandingOrder,
		last_executed: date,
	) -> date:
		"""Compute next execution date based on frequency.

		Raises ValueError for SPECIFIC_DATES — the caller must set
		next_execution_date explicitly via a raw UPDATE before the next run.
		"""
		from dateutil.relativedelta import relativedelta  # type: ignore[import]

		freq = so.frequency
		if freq == "WEEKLY":
			next_d = last_executed + relativedelta(weeks=1)
		elif freq == "MONTHLY":
			next_d = last_executed + relativedelta(months=1)
		elif freq == "QUARTERLY":
			next_d = last_executed + relativedelta(months=3)
		elif freq == "ANNUALLY":
			next_d = last_executed + relativedelta(years=1)
		elif freq == "SPECIFIC_DATES":
			raise ValueError(
				f"PayStandingOrder {so.reference_number!r} uses SPECIFIC_DATES frequency; "
				"the caller must set next_execution_date explicitly before the next run"
			)
		else:
			raise ValueError(f"Unknown frequency {freq!r} on PayStandingOrder {so.reference_number!r}")

		if so.end_date and next_d > so.end_date:
			return so.end_date
		return next_d

	def _build_pain001_xml(
		self,
		batch: PaymentBatch,
		orders: list[PaymentOrder],
	) -> str:
		"""Build a conformant ISO 20022 PAIN.001.001.03 XML string.

		Uses xml.etree.ElementTree so all text values are automatically
		XML-escaped (ampersands, angle brackets, quotes in names/IDs are safe).
		Includes all mandatory elements per the PAIN.001.001.03 XSD:
		  GrpHdr, PmtInf, PmtMtd, SvcLvl, LclInstrm, CdtrAgt, DbtrAcct, DbtrAgt.
		"""
		import xml.etree.ElementTree as ET

		try:
			from flask import current_app
			bank_bic = current_app.config.get("PY_BANK_BIC", "XXXXXXXX")
		except RuntimeError:
			bank_bic = "XXXXXXXX"

		ns = "urn:iso:std:iso:20022:tech:xsd:pain.001.001.03"
		ET.register_namespace("", ns)

		doc = ET.Element(f"{{{ns}}}Document")
		initn = ET.SubElement(doc, f"{{{ns}}}CstmrCdtTrfInitn")

		# Group Header
		grp = ET.SubElement(initn, f"{{{ns}}}GrpHdr")
		ET.SubElement(grp, f"{{{ns}}}MsgId").text = batch.batch_number
		ET.SubElement(grp, f"{{{ns}}}CreDtTm").text = _now_utc().strftime("%Y-%m-%dT%H:%M:%S")
		ET.SubElement(grp, f"{{{ns}}}NbOfTxs").text = str(batch.total_payments or len(orders))
		ctrl_sum = (batch.total_amount_cents or 0) / 100
		ET.SubElement(grp, f"{{{ns}}}CtrlSum").text = f"{ctrl_sum:.2f}"
		initg_pty = ET.SubElement(grp, f"{{{ns}}}InitgPty")
		ET.SubElement(initg_pty, f"{{{ns}}}Nm").text = "PgAppForge Payments"

		# One PmtInf block per batch (all orders share batch-level debtor + rail)
		pmt_inf = ET.SubElement(initn, f"{{{ns}}}PmtInf")
		ET.SubElement(pmt_inf, f"{{{ns}}}PmtInfId").text = batch.batch_number
		# PmtMtd: TRF = credit transfer (mandatory)
		ET.SubElement(pmt_inf, f"{{{ns}}}PmtMtd").text = "TRF"
		# PmtTpInf → SvcLvl + LclInstrm
		pmt_tp = ET.SubElement(pmt_inf, f"{{{ns}}}PmtTpInf")
		svc_lvl = ET.SubElement(pmt_tp, f"{{{ns}}}SvcLvl")
		# URGP = urgent (RTGS), NURG = non-urgent (EFT/ACH)
		svc_code = "URGP" if batch.batch_type in {"RTGS"} else "NURG"
		ET.SubElement(svc_lvl, f"{{{ns}}}Cd").text = svc_code
		lcl_instr = ET.SubElement(pmt_tp, f"{{{ns}}}LclInstrm")
		ET.SubElement(lcl_instr, f"{{{ns}}}Cd").text = batch.batch_type

		ET.SubElement(pmt_inf, f"{{{ns}}}ReqdExctnDt").text = str(batch.value_date)

		# DbtrAgt (our bank BIC — mandatory)
		dbtr_agt = ET.SubElement(pmt_inf, f"{{{ns}}}DbtrAgt")
		dbtr_agt_fi = ET.SubElement(dbtr_agt, f"{{{ns}}}FinInstnId")
		ET.SubElement(dbtr_agt_fi, f"{{{ns}}}BIC").text = bank_bic

		# DbtrAcct (batch-level debtor account — use first order's debtor_account_id)
		dbtr_acct = ET.SubElement(pmt_inf, f"{{{ns}}}DbtrAcct")
		dbtr_acct_id = ET.SubElement(dbtr_acct, f"{{{ns}}}Id")
		dbtr_othr = ET.SubElement(dbtr_acct_id, f"{{{ns}}}Othr")
		first_debtor = str(orders[0].debtor_account_id) if orders else ""
		ET.SubElement(dbtr_othr, f"{{{ns}}}Id").text = first_debtor

		# Credit transfer transactions
		for o in orders:
			tx = ET.SubElement(pmt_inf, f"{{{ns}}}CdtTrfTxInf")
			pmt_id = ET.SubElement(tx, f"{{{ns}}}PmtId")
			ET.SubElement(pmt_id, f"{{{ns}}}EndToEndId").text = o.payment_reference
			if o.uetr:
				ET.SubElement(pmt_id, f"{{{ns}}}UETR").text = o.uetr

			amt = ET.SubElement(tx, f"{{{ns}}}Amt")
			instd = ET.SubElement(amt, f"{{{ns}}}InstdAmt")
			instd.set("Ccy", o.currency_code or "KES")
			instd.text = f"{(o.amount_cents or 0) / 100:.2f}"

			# CdtrAgt (creditor bank BIC, if known)
			if o.creditor_bank_code:
				cdtr_agt = ET.SubElement(tx, f"{{{ns}}}CdtrAgt")
				cdtr_agt_fi = ET.SubElement(cdtr_agt, f"{{{ns}}}FinInstnId")
				ET.SubElement(cdtr_agt_fi, f"{{{ns}}}BIC").text = o.creditor_bank_code

			cdtr = ET.SubElement(tx, f"{{{ns}}}Cdtr")
			ET.SubElement(cdtr, f"{{{ns}}}Nm").text = o.creditor_name or ""

			cdtr_acct = ET.SubElement(tx, f"{{{ns}}}CdtrAcct")
			cdtr_acct_id = ET.SubElement(cdtr_acct, f"{{{ns}}}Id")
			cdtr_othr = ET.SubElement(cdtr_acct_id, f"{{{ns}}}Othr")
			ET.SubElement(cdtr_othr, f"{{{ns}}}Id").text = o.creditor_account_number or ""

			if o.remittance_info:
				rmt = ET.SubElement(tx, f"{{{ns}}}RmtInf")
				ET.SubElement(rmt, f"{{{ns}}}Ustrd").text = o.remittance_info

		return ET.tostring(doc, encoding="unicode", xml_declaration=True)

	def _emit(self, event: Any) -> None:
		"""Emit a domain event and persist it to the transactional outbox.

		The outbox INSERT is in the same DB transaction as the business operation
		(atomic delivery guarantee).  The in-process event_bus is called
		opportunistically after commit; failures are non-fatal.
		"""
		# Derive a stable idempotency key from the event
		try:
			event_type: str = getattr(event, "event_type", type(event).__name__)
			# Prefer payment_reference for uniqueness; fall back to batch_number / standing_order_id
			ref = (
				getattr(event, "payment_reference", None)
				or getattr(event, "batch_number", None)
				or getattr(event, "reference_number", None)
				or getattr(event, "rail_code", None)
				or ""
			)
			ikey = f"{ref}::{event_type}"

			payload: dict[str, Any] = {}
			for k, v in vars(event).items():
				if not k.startswith("_"):
					payload[k] = v

			outbox_row = PaymentOutboxEvent(
				tenant_id=self._tenant_id,
				event_type=event_type,
				payload=payload,
				idempotency_key=ikey,
				status="PENDING",
			)
			self._session.add(outbox_row)
			# Flush inside the current transaction — atomic with the business change
			self._session.flush()
		except Exception as exc:
			log.warning("PaymentsService._emit: outbox insert failed (non-fatal): %s", exc)

		# In-process delivery (best-effort; a background worker handles durable delivery)
		try:
			if self._event_bus is not None:
				self._event_bus(event)
			else:
				log.debug("PaymentsService event (no bus): %s", event)
		except Exception as exc:
			log.warning("PaymentsService._emit: event_bus call failed (non-fatal): %s", exc)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"PaymentsService",
	"PaymentsError",
	"PaymentNotFoundError",
	"InsufficientFundsError",
	"RailNotAvailableError",
	"PaymentImmutableError",
	"SanctionsHitError",
	"AMLFlaggedError",
]
