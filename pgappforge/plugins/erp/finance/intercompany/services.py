"""
pgappforge/plugins/erp/finance/intercompany/services.py

IntercompanyService — stateless business logic for Intercompany Posting.

All methods receive an explicit SQLAlchemy session; no Flask context assumed.
Transaction boundaries owned by the caller.

Monetary invariants:
  - All amounts passed in and returned as integer cents (BigInteger)
  - Decimal arithmetic used internally; results rounded ROUND_HALF_UP to int
  - All period strings: ISO date format 'YYYY-MM-DD'

BPM registrations:
  finance.intercompany.send   — Send intercompany transaction to counterpart entity
  finance.intercompany.accept — Accept and post intercompany transaction

Public API:
  send_transaction(source_entity_id, target_entity_id, transaction_type,
                   document_data, tenant_id, session, *, correlation_id=None)
                   -> ICOutboxTransaction
  accept_transaction(inbox_id, session) -> ICInboxTransaction
  reject_transaction(inbox_id, reason, session) -> ICInboxTransaction
  get_inbox(entity_id, tenant_id, session) -> list[ICInboxTransaction]
  reconcile_ic_balances(entity_a, entity_b, period, tenant_id, session) -> dict
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import sqlalchemy as sa

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# BPM action registry (best-effort)
# ---------------------------------------------------------------------------

def _register(action_id: str, description: str):
	"""Decorator: register method as a BPM-callable action if plugin is loaded."""
	def decorator(fn):
		try:
			from pgappforge.plugins.bpm import register as bpm_register
			bpm_register(action_id, description)(fn)
		except Exception:
			pass
		return fn
	return decorator


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class IntercompanyServiceError(Exception):
	"""Base domain error for intercompany operations."""


class ICTransactionNotFoundError(IntercompanyServiceError):
	pass


class ICInvalidStatusError(IntercompanyServiceError):
	pass


class ICUnsupportedTransactionTypeError(IntercompanyServiceError):
	pass


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _uuid4() -> str:
	return str(uuid.uuid4())


def _d(value: Any) -> Decimal:
	"""Safe Decimal coercion — never float intermediate."""
	if isinstance(value, Decimal):
		return value
	return Decimal(str(value))


def _now() -> datetime:
	return datetime.now(timezone.utc)


def _emit(event: Any, session: Any = None) -> None:
	"""Emit domain event; swallow all errors to protect the business transaction."""
	try:
		from pgappforge.plugins.erp.foundation.events import emit_event
		emit_event(event, session)
	except Exception as exc:
		log.debug("IntercompanyService._emit: non-fatal event emission failure: %s", exc)


# ---------------------------------------------------------------------------
# IntercompanyService
# ---------------------------------------------------------------------------

class IntercompanyService:
	"""Stateless intercompany posting domain service.

	Instantiate once per application (no instance state).
	All public methods accept an explicit SQLAlchemy Session.

	Architecture:
	  send_transaction() creates BOTH the outbox (source) and inbox (target)
	  records atomically in the same session.  This works for same-tenant
	  multi-entity setups where all entities share one database.  For
	  cross-tenant/cross-database IC, replace inbox creation with an async
	  message queue dispatch.
	"""

	# ------------------------------------------------------------------
	# send_transaction
	# ------------------------------------------------------------------

	@_register(
		"finance.intercompany.send",
		"Send intercompany transaction to counterpart entity",
	)
	def send_transaction(
		self,
		source_entity_id: str,
		target_entity_id: str,
		transaction_type: str,
		document_data: dict[str, Any],
		tenant_id: str,
		session: Any,
		*,
		correlation_id: str | None = None,
	) -> Any:
		"""Create and send an IC transaction from source to target entity.

		Creates ICOutboxTransaction (source) and ICInboxTransaction (target)
		atomically. Both are set to SENT/PENDING respectively.

		Args:
			source_entity_id: Sending entity (soft FK to entity registry).
			target_entity_id: Receiving entity (soft FK to entity registry).
			transaction_type: One of PO_MIRROR / SO_MIRROR / JOURNAL_MIRROR / PAYMENT_MIRROR.
			document_data: Serialisable dict representing the source document.
			tenant_id: Tenant scoping string.
			session: SQLAlchemy session (caller commits).
			correlation_id: Optional shared ID; auto-generated UUID4 if None.

		Returns:
			The created ICOutboxTransaction instance (status=SENT).

		Raises:
			ICUnsupportedTransactionTypeError: transaction_type not in allowed set.
			IntercompanyServiceError: source_entity_id == target_entity_id.
		"""
		from pgappforge.plugins.erp.finance.intercompany.models import (
			ICOutboxTransaction, ICInboxTransaction,
		)
		from pgappforge.plugins.erp.finance.intercompany.events import (
			ICTransactionSentEvent,
		)

		_VALID_TYPES = {"PO_MIRROR", "SO_MIRROR", "JOURNAL_MIRROR", "PAYMENT_MIRROR"}
		if transaction_type not in _VALID_TYPES:
			raise ICUnsupportedTransactionTypeError(
				f"transaction_type {transaction_type!r} not in {_VALID_TYPES}"
			)
		if source_entity_id == target_entity_id:
			raise IntercompanyServiceError(
				"source_entity_id and target_entity_id must differ"
			)

		corr_id = correlation_id or _uuid4()
		now = _now()

		outbox = ICOutboxTransaction(
			tenant_id=tenant_id,
			source_entity_id=source_entity_id,
			target_entity_id=target_entity_id,
			transaction_type=transaction_type,
			document_data=document_data,
			status="SENT",
			sent_at=now,
			correlation_id=corr_id,
		)
		session.add(outbox)
		session.flush()  # populate outbox.id

		inbox = ICInboxTransaction(
			tenant_id=tenant_id,
			outbox_id=outbox.id,
			source_entity_id=source_entity_id,
			target_entity_id=target_entity_id,
			transaction_type=transaction_type,
			document_data=document_data,
			status="PENDING",
			correlation_id=corr_id,
		)
		session.add(inbox)

		log.info(
			"IntercompanyService.send_transaction: outbox=%s type=%s %s→%s corr=%s",
			outbox.id, transaction_type, source_entity_id, target_entity_id, corr_id,
		)

		_emit(
			ICTransactionSentEvent(
				aggregate_id=outbox.id,
				aggregate_type="ICOutboxTransaction",
				tenant_id=tenant_id,
				outbox_id=outbox.id,
				source_entity_id=source_entity_id,
				target_entity_id=target_entity_id,
				transaction_type=transaction_type,
			),
			session,
		)

		return outbox

	# ------------------------------------------------------------------
	# accept_transaction
	# ------------------------------------------------------------------

	@_register(
		"finance.intercompany.accept",
		"Accept and post intercompany transaction",
	)
	def accept_transaction(self, inbox_id: str, session: Any) -> Any:
		"""Accept an IC inbox transaction and create the mirror document.

		Mirror document creation by transaction_type:
		  PO_MIRROR      → create sales order at target entity
		  SO_MIRROR      → create purchase order at target entity
		  JOURNAL_MIRROR → post reversed GL journal at target entity
		  PAYMENT_MIRROR → post payment to AR/AP at target entity

		Args:
			inbox_id: UUID string of the ICInboxTransaction to accept.
			session: SQLAlchemy session (caller commits).

		Returns:
			The updated ICInboxTransaction (status=ACCEPTED).

		Raises:
			ICTransactionNotFoundError: inbox not found.
			ICInvalidStatusError: inbox not in PENDING status.
		"""
		from pgappforge.plugins.erp.finance.intercompany.models import (
			ICInboxTransaction, ICOutboxTransaction,
		)
		from pgappforge.plugins.erp.finance.intercompany.events import (
			ICTransactionAcceptedEvent,
		)

		inbox = session.execute(
			sa.select(ICInboxTransaction).where(ICInboxTransaction.id == inbox_id)
		).scalar_one_or_none()

		if inbox is None:
			raise ICTransactionNotFoundError(f"ICInboxTransaction {inbox_id!r} not found")

		if inbox.status != "PENDING":
			raise ICInvalidStatusError(
				f"ICInboxTransaction {inbox_id!r} status={inbox.status!r}; must be PENDING"
			)

		# Create mirror document at target entity
		created_document_id = self._create_mirror_document(
			transaction_type=inbox.transaction_type,
			document_data=inbox.document_data,
			target_entity_id=inbox.target_entity_id,
			tenant_id=inbox.tenant_id,
			session=session,
		)

		now = _now()
		inbox.status = "ACCEPTED"
		inbox.created_document_id = created_document_id
		inbox.processed_at = now

		# Update outbox status
		if inbox.outbox_id:
			outbox = session.execute(
				sa.select(ICOutboxTransaction).where(
					ICOutboxTransaction.id == inbox.outbox_id
				)
			).scalar_one_or_none()
			if outbox is not None:
				outbox.status = "ACCEPTED"
				outbox.response_at = now

		log.info(
			"IntercompanyService.accept_transaction: inbox=%s type=%s doc=%s",
			inbox_id, inbox.transaction_type, created_document_id,
		)

		_emit(
			ICTransactionAcceptedEvent(
				aggregate_id=inbox_id,
				aggregate_type="ICInboxTransaction",
				tenant_id=inbox.tenant_id,
				inbox_id=inbox_id,
				outbox_id=inbox.outbox_id or "",
				created_document_id=created_document_id or "",
			),
			session,
		)

		return inbox

	# ------------------------------------------------------------------
	# reject_transaction
	# ------------------------------------------------------------------

	def reject_transaction(self, inbox_id: str, reason: str, session: Any) -> Any:
		"""Reject an IC inbox transaction.

		Args:
			inbox_id: UUID string of the ICInboxTransaction to reject.
			reason: Human-readable rejection reason.
			session: SQLAlchemy session (caller commits).

		Returns:
			The updated ICInboxTransaction (status=REJECTED).

		Raises:
			ICTransactionNotFoundError: inbox not found.
			ICInvalidStatusError: inbox not in PENDING status.
		"""
		from pgappforge.plugins.erp.finance.intercompany.models import (
			ICInboxTransaction, ICOutboxTransaction,
		)
		from pgappforge.plugins.erp.finance.intercompany.events import (
			ICTransactionRejectedEvent,
		)

		inbox = session.execute(
			sa.select(ICInboxTransaction).where(ICInboxTransaction.id == inbox_id)
		).scalar_one_or_none()

		if inbox is None:
			raise ICTransactionNotFoundError(f"ICInboxTransaction {inbox_id!r} not found")

		if inbox.status != "PENDING":
			raise ICInvalidStatusError(
				f"ICInboxTransaction {inbox_id!r} status={inbox.status!r}; must be PENDING to reject"
			)

		now = _now()
		inbox.status = "REJECTED"
		inbox.processed_at = now

		# Update outbox
		if inbox.outbox_id:
			outbox = session.execute(
				sa.select(ICOutboxTransaction).where(
					ICOutboxTransaction.id == inbox.outbox_id
				)
			).scalar_one_or_none()
			if outbox is not None:
				outbox.status = "REJECTED"
				outbox.response_at = now
				outbox.rejection_reason = reason

		log.info(
			"IntercompanyService.reject_transaction: inbox=%s reason=%r", inbox_id, reason
		)

		_emit(
			ICTransactionRejectedEvent(
				aggregate_id=inbox_id,
				aggregate_type="ICInboxTransaction",
				tenant_id=inbox.tenant_id,
				outbox_id=inbox.outbox_id or "",
				reason=reason,
			),
			session,
		)

		return inbox

	# ------------------------------------------------------------------
	# get_inbox
	# ------------------------------------------------------------------

	def get_inbox(
		self,
		entity_id: str,
		tenant_id: str,
		session: Any,
	) -> list[Any]:
		"""Return all PENDING inbox transactions for entity_id.

		Args:
			entity_id: The receiving entity's ID.
			tenant_id: Tenant scoping string.
			session: SQLAlchemy session.

		Returns:
			List of ICInboxTransaction instances with status=PENDING.
		"""
		from pgappforge.plugins.erp.finance.intercompany.models import ICInboxTransaction

		return session.execute(
			sa.select(ICInboxTransaction).where(
				ICInboxTransaction.target_entity_id == entity_id,
				ICInboxTransaction.tenant_id == tenant_id,
				ICInboxTransaction.status == "PENDING",
			).order_by(ICInboxTransaction.created_at.asc())
		).scalars().all()

	# ------------------------------------------------------------------
	# reconcile_ic_balances
	# ------------------------------------------------------------------

	def reconcile_ic_balances(
		self,
		entity_a: str,
		entity_b: str,
		period: str,
		tenant_id: str,
		session: Any,
	) -> dict[str, Any]:
		"""Reconcile intercompany balances between entity_a and entity_b for a period.

		Compares:
		  - entity_a's outbound ACCEPTED transactions to entity_b (A's receivable from B)
		  - entity_b's outbound ACCEPTED transactions to entity_a (B's payable to A)

		A matched pair agrees when both sides report the same net document amount.
		Divergences are recorded when the amounts disagree beyond zero tolerance.

		Args:
			entity_a: First entity ID.
			entity_b: Second entity ID.
			period: ISO date string 'YYYY-MM-DD' (typically first day of the period).
			        Transactions created in the same calendar month are included.
			tenant_id: Tenant scoping string.
			session: SQLAlchemy session.

		Returns:
			{
			  "matched": int,
			  "unmatched": int,
			  "divergences": [{"outbox_id": str, "inbox_id": str,
			                   "amount_a_cents": int, "amount_b_cents": int}],
			  "entity_a": str,
			  "entity_b": str,
			  "period": str,
			}
		"""
		from pgappforge.plugins.erp.finance.intercompany.models import (
			ICOutboxTransaction, ICInboxTransaction,
		)
		from pgappforge.plugins.erp.finance.intercompany.events import (
			ICReconciliationRunEvent, ICDivergenceDetectedEvent,
		)

		# Parse period to get month window
		try:
			from datetime import date
			period_date = date.fromisoformat(period)
			month_start = period_date.replace(day=1)
			# next month start for exclusive upper bound
			if period_date.month == 12:
				month_end = period_date.replace(year=period_date.year + 1, month=1, day=1)
			else:
				month_end = period_date.replace(month=period_date.month + 1, day=1)
		except ValueError as exc:
			raise IntercompanyServiceError(
				f"period {period!r} must be ISO date format YYYY-MM-DD"
			) from exc

		# Fetch ACCEPTED outbox from A→B
		a_to_b = session.execute(
			sa.select(ICOutboxTransaction).where(
				ICOutboxTransaction.tenant_id == tenant_id,
				ICOutboxTransaction.source_entity_id == entity_a,
				ICOutboxTransaction.target_entity_id == entity_b,
				ICOutboxTransaction.status == "ACCEPTED",
				ICOutboxTransaction.sent_at >= sa.cast(month_start.isoformat(), sa.DateTime(timezone=True)),
				ICOutboxTransaction.sent_at < sa.cast(month_end.isoformat(), sa.DateTime(timezone=True)),
			)
		).scalars().all()

		# Fetch ACCEPTED outbox from B→A
		b_to_a = session.execute(
			sa.select(ICOutboxTransaction).where(
				ICOutboxTransaction.tenant_id == tenant_id,
				ICOutboxTransaction.source_entity_id == entity_b,
				ICOutboxTransaction.target_entity_id == entity_a,
				ICOutboxTransaction.status == "ACCEPTED",
				ICOutboxTransaction.sent_at >= sa.cast(month_start.isoformat(), sa.DateTime(timezone=True)),
				ICOutboxTransaction.sent_at < sa.cast(month_end.isoformat(), sa.DateTime(timezone=True)),
			)
		).scalars().all()

		# Build correlation maps: correlation_id → outbox
		a_corr: dict[str, Any] = {
			tx.correlation_id: tx for tx in a_to_b if tx.correlation_id
		}
		b_corr: dict[str, Any] = {
			tx.correlation_id: tx for tx in b_to_a if tx.correlation_id
		}

		all_corr_ids = set(a_corr) | set(b_corr)
		matched = 0
		divergences: list[dict[str, Any]] = []

		for corr_id in all_corr_ids:
			tx_a = a_corr.get(corr_id)
			tx_b = b_corr.get(corr_id)

			amount_a = self._extract_amount_cents(tx_a.document_data) if tx_a else 0
			amount_b = self._extract_amount_cents(tx_b.document_data) if tx_b else 0

			if tx_a and tx_b and amount_a == amount_b:
				matched += 1
			else:
				divergences.append({
					"correlation_id": corr_id,
					"outbox_a_id": tx_a.id if tx_a else None,
					"outbox_b_id": tx_b.id if tx_b else None,
					"amount_a_cents": amount_a,
					"amount_b_cents": amount_b,
				})
				_emit(
					ICDivergenceDetectedEvent(
						aggregate_id=corr_id,
						aggregate_type="ICReconciliation",
						tenant_id=tenant_id,
						entity_a=entity_a,
						entity_b=entity_b,
						amount_a_cents=amount_a,
						amount_b_cents=amount_b,
					),
					session,
				)

		unmatched = len(divergences)

		log.info(
			"IntercompanyService.reconcile_ic_balances: %s↔%s period=%s "
			"matched=%d unmatched=%d",
			entity_a, entity_b, period, matched, unmatched,
		)

		_emit(
			ICReconciliationRunEvent(
				aggregate_id=f"{entity_a}:{entity_b}:{period}",
				aggregate_type="ICReconciliation",
				tenant_id=tenant_id,
				entity_id=entity_a,
				matched_count=matched,
				unmatched_count=unmatched,
			),
			session,
		)

		return {
			"matched": matched,
			"unmatched": unmatched,
			"divergences": divergences,
			"entity_a": entity_a,
			"entity_b": entity_b,
			"period": period,
		}

	# ------------------------------------------------------------------
	# Internal: mirror document creation
	# ------------------------------------------------------------------

	def _create_mirror_document(
		self,
		transaction_type: str,
		document_data: dict[str, Any],
		target_entity_id: str,
		tenant_id: str,
		session: Any,
	) -> str | None:
		"""Create the appropriate mirror document for a given IC transaction type.

		Returns:
			created_document_id (str) or None if creation is not possible.

		This is a dispatch table: each handler is a best-effort soft import.
		If the target plugin is not loaded, the method returns a synthetic ID
		and logs at DEBUG to avoid blocking the accept workflow.
		"""
		handlers = {
			"PO_MIRROR": self._mirror_po_as_so,
			"SO_MIRROR": self._mirror_so_as_po,
			"JOURNAL_MIRROR": self._mirror_journal,
			"PAYMENT_MIRROR": self._mirror_payment,
		}
		handler = handlers.get(transaction_type)
		if handler is None:
			raise ICUnsupportedTransactionTypeError(
				f"No mirror handler for transaction_type {transaction_type!r}"
			)
		return handler(document_data, target_entity_id, tenant_id, session)

	def _mirror_po_as_so(
		self,
		document_data: dict[str, Any],
		target_entity_id: str,
		tenant_id: str,
		session: Any,
	) -> str | None:
		"""PO_MIRROR: create a sales order at the target entity from a PO payload."""
		try:
			from pgappforge.plugins.erp.operations.scm.services import SCMService
			so_id = SCMService().create_sales_order_from_ic(
				document_data=document_data,
				entity_id=target_entity_id,
				tenant_id=tenant_id,
				session=session,
			)
			return str(so_id)
		except ImportError:
			log.debug("_mirror_po_as_so: SCM plugin not loaded; returning stub ID")
			return f"IC-SO-{_uuid4()}"
		except Exception as exc:
			log.debug("_mirror_po_as_so: SO creation failed: %s", exc)
			return None

	def _mirror_so_as_po(
		self,
		document_data: dict[str, Any],
		target_entity_id: str,
		tenant_id: str,
		session: Any,
	) -> str | None:
		"""SO_MIRROR: create a purchase order at the target entity from an SO payload."""
		try:
			from pgappforge.plugins.erp.operations.scm.services import SCMService
			po_id = SCMService().create_purchase_order_from_ic(
				document_data=document_data,
				entity_id=target_entity_id,
				tenant_id=tenant_id,
				session=session,
			)
			return str(po_id)
		except ImportError:
			log.debug("_mirror_so_as_po: SCM plugin not loaded; returning stub ID")
			return f"IC-PO-{_uuid4()}"
		except Exception as exc:
			log.debug("_mirror_so_as_po: PO creation failed: %s", exc)
			return None

	def _mirror_journal(
		self,
		document_data: dict[str, Any],
		target_entity_id: str,
		tenant_id: str,
		session: Any,
	) -> str | None:
		"""JOURNAL_MIRROR: post a reversed GL journal at the target entity."""
		try:
			from pgappforge.plugins.erp.finance.gl.services import GLService
			# Reverse debit/credit for the mirror entry
			lines = document_data.get("lines", [])
			reversed_lines = [
				{
					"account": line["account"],
					"debit_cents": line.get("credit_cents", 0),
					"credit_cents": line.get("debit_cents", 0),
				}
				for line in lines
			]
			je_id = GLService().post_journal(
				tenant_id=tenant_id,
				description=document_data.get("description", "IC Journal Mirror"),
				lines=reversed_lines,
				reference_type="IC_MIRROR",
				reference_id=document_data.get("reference_id", ""),
				session=session,
			)
			return str(je_id)
		except ImportError:
			log.debug("_mirror_journal: GL plugin not loaded; returning stub ID")
			return f"IC-JE-{_uuid4()}"
		except Exception as exc:
			log.debug("_mirror_journal: GL journal failed: %s", exc)
			return None

	def _mirror_payment(
		self,
		document_data: dict[str, Any],
		target_entity_id: str,
		tenant_id: str,
		session: Any,
	) -> str | None:
		"""PAYMENT_MIRROR: post a payment to AR/AP at the target entity."""
		try:
			from pgappforge.plugins.erp.finance.ar.services import ARService
			pmt_id = ARService().post_ic_payment(
				document_data=document_data,
				entity_id=target_entity_id,
				tenant_id=tenant_id,
				session=session,
			)
			return str(pmt_id)
		except ImportError:
			log.debug("_mirror_payment: AR plugin not loaded; returning stub ID")
			return f"IC-PMT-{_uuid4()}"
		except Exception as exc:
			log.debug("_mirror_payment: payment posting failed: %s", exc)
			return None

	# ------------------------------------------------------------------
	# Internal: extract canonical amount from document_data
	# ------------------------------------------------------------------

	@staticmethod
	def _extract_amount_cents(document_data: dict[str, Any] | None) -> int:
		"""Extract a canonical total amount in cents from document_data for reconciliation.

		Tries, in order:
		  document_data["amount_cents"]
		  sum of document_data["lines"][*]["debit_cents"]
		  sum of document_data["lines"][*]["unit_cost_cents"] * qty

		Returns 0 if no amount can be determined.
		"""
		if not document_data:
			return 0

		if "amount_cents" in document_data:
			return int(document_data["amount_cents"])

		lines = document_data.get("lines", [])
		if lines:
			debit_sum = sum(int(ln.get("debit_cents", 0)) for ln in lines)
			if debit_sum:
				return debit_sum
			# PO/SO lines: unit_cost_cents × qty
			line_sum = 0
			for ln in lines:
				uc = int(ln.get("unit_cost_cents", 0))
				qty = Decimal(str(ln.get("qty", 0)))
				line_sum += int(
					(qty * Decimal(uc)).to_integral_value(rounding=ROUND_HALF_UP)
				)
			return line_sum

		return 0


__all__ = [
	"IntercompanyService",
	"IntercompanyServiceError",
	"ICTransactionNotFoundError",
	"ICInvalidStatusError",
	"ICUnsupportedTransactionTypeError",
]
