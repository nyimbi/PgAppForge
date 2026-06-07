"""
pgappforge/plugins/erp/procurement/sourcing/services.py

SourcingService — stateless business logic for the Strategic Sourcing plugin.

All methods receive an explicit SQLAlchemy 2.x session; no Flask context assumed.
Transaction boundaries owned by the caller.

Monetary invariants:
  - All amounts in integer cents — never float

Evaluation formula (evaluate_bids):
  price_score   = (min_price / bid_price) * 100
  delivery_score = (1 / delivery_days) * 100  (higher score for faster delivery)
  composite = (price_score * price_weight/100)
            + (technical_score * quality_weight/100)
            + (delivery_score * delivery_weight/100)
  Weights sourced from RFQ.evaluation_criteria; default {60, 20, 20}.

Status transitions:
  create_rfq   → DRAFT
  publish_rfq  → PUBLISHED
  evaluate_bids  [internal] PUBLISHED → CLOSED
  award_rfq    → AWARDED (winning bid AWARDED, others REJECTED)
  cancel_rfq   → CANCELLED

BPM registrations:
  procurement.sourcing.create_rfq
  procurement.sourcing.award

Public API:
  create_rfq(title, items, tenant_id, session, ...)        -> RFQ
  publish_rfq(rfq_id, invited_supplier_ids, session)       -> RFQ
  submit_bid(rfq_id, supplier_id, line_items, ...)         -> SupplierBid
  evaluate_bids(rfq_id, session)                           -> list[SupplierBid]
  award_rfq(rfq_id, winning_bid_id, session)               -> dict
  cancel_rfq(rfq_id, reason, session)                      -> RFQ
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import sqlalchemy as sa

from pgappforge.plugins.workflow.engine import BPMActionRegistry

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class SourcingServiceError(Exception):
	"""Base domain error for Sourcing operations."""


class RFQNotFoundError(SourcingServiceError):
	pass


class BidNotFoundError(SourcingServiceError):
	pass


class InvalidStatusTransitionError(SourcingServiceError):
	pass


class DeadlinePassedError(SourcingServiceError):
	pass


class DuplicateBidError(SourcingServiceError):
	pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _dec(value: Any) -> Decimal:
	return Decimal(str(value))


def _now_utc() -> datetime:
	return datetime.now(timezone.utc)


def _emit(event: Any, session: Any = None) -> None:
	try:
		from pgappforge.plugins.erp.foundation.events import emit_event as _emit_event
		_emit_event(event, session)
	except Exception as exc:  # noqa: BLE001
		log.debug("Event emission skipped: %s", exc)


def _generate_rfq_ref(session: Any, tenant_id: str) -> str:
	from pgappforge.plugins.erp.procurement.sourcing.models import RFQ
	today_str = _now_utc().strftime("%Y%m%d")
	prefix = f"RFQ-{today_str}-"
	stmt = (
		sa.select(sa.func.count(RFQ.id))
		.where(RFQ.tenant_id == tenant_id, RFQ.rfq_ref.like(f"{prefix}%"))
	)
	count = int(session.execute(stmt).scalar() or 0)
	return f"{prefix}{count + 1:05d}"


# ---------------------------------------------------------------------------
# SourcingService
# ---------------------------------------------------------------------------

class SourcingService:
	"""Stateless service — all methods are classmethods; instantiation optional."""

	# ------------------------------------------------------------------
	# 1. create_rfq
	# ------------------------------------------------------------------

	@classmethod
	def create_rfq(
		cls,
		title: str,
		items: list[dict[str, Any]],
		tenant_id: str,
		session: Any,
		*,
		rfq_type: str = "COMPETITIVE",
		description: str | None = None,
		submission_deadline: datetime | None = None,
		evaluation_criteria: dict[str, Any] | None = None,
		entity_id: str | None = None,
		created_by: str | None = None,
	) -> Any:
		"""Create an RFQ in DRAFT status.

		items must be a non-empty list of dicts:
		  [{item_code, description, qty, unit, estimated_unit_price_cents}]
		evaluation_criteria defaults to {price_weight:60, quality_weight:20, delivery_weight:20}.
		Emits RFQCreatedEvent.
		Returns the persisted RFQ.
		"""
		from pgappforge.plugins.erp.procurement.sourcing.models import RFQ, RFQ_TYPES
		from pgappforge.plugins.erp.procurement.sourcing.events import RFQCreatedEvent

		if not title.strip():
			raise SourcingServiceError("RFQ title cannot be empty")
		if not items:
			raise SourcingServiceError("RFQ must have at least one item")
		if rfq_type not in RFQ_TYPES:
			raise SourcingServiceError(f"Invalid rfq_type {rfq_type!r}. Choose from {RFQ_TYPES}")

		criteria = evaluation_criteria or {"price_weight": 60, "quality_weight": 20, "delivery_weight": 20}
		_validate_criteria(criteria)

		ref = _generate_rfq_ref(session, tenant_id)

		rfq = RFQ(
			tenant_id=tenant_id,
			title=title.strip(),
			description=description,
			rfq_ref=ref,
			rfq_type=rfq_type,
			status="DRAFT",
			submission_deadline=submission_deadline,
			evaluation_criteria=criteria,
			items=items,
			invited_suppliers=[],
			entity_id=entity_id,
			created_by=created_by,
		)
		session.add(rfq)
		session.flush()

		_emit(
			RFQCreatedEvent(
				aggregate_id=rfq.id,
				aggregate_type="RFQ",
				tenant_id=tenant_id,
				rfq_id=rfq.id,
				title=rfq.title,
				items=items,
			),
			session,
		)

		log.info("RFQ created: %s tenant=%s type=%s", ref, tenant_id, rfq_type)
		return rfq

	# ------------------------------------------------------------------
	# 2. publish_rfq
	# ------------------------------------------------------------------

	@classmethod
	def publish_rfq(
		cls,
		rfq_id: str,
		invited_supplier_ids: list[str],
		session: Any,
	) -> Any:
		"""Transition DRAFT → PUBLISHED and record invited suppliers.

		invited_supplier_ids is a list of supplier_id strings (advisory refs).
		Emits RFQPublishedEvent.
		Returns the updated RFQ.
		"""
		from pgappforge.plugins.erp.procurement.sourcing.models import RFQ
		from pgappforge.plugins.erp.procurement.sourcing.events import RFQPublishedEvent

		rfq = session.get(RFQ, rfq_id)
		if rfq is None:
			raise RFQNotFoundError(f"RFQ {rfq_id!r} not found")
		if rfq.status != "DRAFT":
			raise InvalidStatusTransitionError(
				f"publish_rfq() requires DRAFT status, got {rfq.status!r}"
			)
		if not invited_supplier_ids:
			raise SourcingServiceError("At least one supplier must be invited")

		rfq.invited_suppliers = list(invited_supplier_ids)
		rfq.status = "PUBLISHED"
		session.flush()

		_emit(
			RFQPublishedEvent(
				aggregate_id=rfq.id,
				aggregate_type="RFQ",
				tenant_id=rfq.tenant_id,
				rfq_id=rfq.id,
				invited_supplier_count=len(invited_supplier_ids),
			),
			session,
		)

		log.info(
			"RFQ %s published, %d suppliers invited",
			rfq.rfq_ref, len(invited_supplier_ids),
		)
		return rfq

	# ------------------------------------------------------------------
	# 3. submit_bid
	# ------------------------------------------------------------------

	@classmethod
	def submit_bid(
		cls,
		rfq_id: str,
		supplier_id: str,
		line_items: list[dict[str, Any]],
		total_cents: int,
		session: Any,
		*,
		delivery_days: int | None = None,
		validity_days: int = 30,
		quality_notes: str | None = None,
		currency_code: str = "USD",
	) -> Any:
		"""Submit a supplier bid for an RFQ.

		Validates:
		  - RFQ is in PUBLISHED status
		  - submission_deadline has not passed (when set)
		  - No duplicate bid from this supplier
		Emits BidSubmittedEvent.
		Returns the persisted SupplierBid.
		"""
		from pgappforge.plugins.erp.procurement.sourcing.models import RFQ, SupplierBid
		from pgappforge.plugins.erp.procurement.sourcing.events import BidSubmittedEvent

		rfq = session.get(RFQ, rfq_id)
		if rfq is None:
			raise RFQNotFoundError(f"RFQ {rfq_id!r} not found")
		if rfq.status != "PUBLISHED":
			raise InvalidStatusTransitionError(
				f"Bids can only be submitted to PUBLISHED RFQs, got {rfq.status!r}"
			)

		# Check deadline
		if rfq.submission_deadline is not None and _now_utc() > rfq.submission_deadline:
			raise DeadlinePassedError(
				f"RFQ {rfq.rfq_ref} submission deadline has passed: {rfq.submission_deadline}"
			)

		# Duplicate check
		dup_stmt = sa.select(sa.func.count(SupplierBid.id)).where(
			SupplierBid.rfq_id == rfq_id,
			SupplierBid.supplier_id == supplier_id,
		)
		if int(session.execute(dup_stmt).scalar() or 0) > 0:
			raise DuplicateBidError(
				f"Supplier {supplier_id!r} already has a bid on RFQ {rfq.rfq_ref}"
			)

		if total_cents <= 0:
			raise SourcingServiceError("total_cents must be positive")

		bid = SupplierBid(
			tenant_id=rfq.tenant_id,
			rfq_id=rfq_id,
			supplier_id=supplier_id,
			submitted_at=_now_utc(),
			status="SUBMITTED",
			total_bid_cents=total_cents,
			currency_code=currency_code,
			validity_days=validity_days,
			delivery_days=delivery_days,
			quality_notes=quality_notes,
			line_items=line_items,
		)
		session.add(bid)
		session.flush()

		_emit(
			BidSubmittedEvent(
				aggregate_id=bid.id,
				aggregate_type="SupplierBid",
				tenant_id=rfq.tenant_id,
				rfq_id=rfq_id,
				supplier_id=supplier_id,
				bid_id=bid.id,
				total_cents=total_cents,
			),
			session,
		)

		log.info(
			"Bid %s submitted by supplier %s for RFQ %s, total=%d¢",
			bid.id, supplier_id, rfq.rfq_ref, total_cents,
		)
		return bid

	# ------------------------------------------------------------------
	# 4. evaluate_bids
	# ------------------------------------------------------------------

	@classmethod
	def evaluate_bids(
		cls,
		rfq_id: str,
		session: Any,
	) -> list[Any]:
		"""Score all SUBMITTED bids and identify the best.

		Scoring:
		  price_score     = (min_bid_price / bid_price) * 100
		  delivery_score  = (1 / delivery_days) * 100  (0 when delivery_days is None)
		  composite       = price_score*(price_w/100)
		                  + technical_score*(quality_w/100)
		                  + delivery_score*(delivery_w/100)
		  technical_score defaults to 50 when not set.

		Sets composite_score on all bids and status to EVALUATED.
		Transitions RFQ to CLOSED.
		Emits BidEvaluatedEvent for the highest-scoring bid.
		Returns list of all evaluated bids sorted by composite_score desc.
		"""
		from pgappforge.plugins.erp.procurement.sourcing.models import RFQ, SupplierBid
		from pgappforge.plugins.erp.procurement.sourcing.events import BidEvaluatedEvent

		rfq = session.get(RFQ, rfq_id)
		if rfq is None:
			raise RFQNotFoundError(f"RFQ {rfq_id!r} not found")
		if rfq.status not in ("PUBLISHED", "CLOSED"):
			raise InvalidStatusTransitionError(
				f"evaluate_bids() requires PUBLISHED or CLOSED status, got {rfq.status!r}"
			)

		stmt = sa.select(SupplierBid).where(
			SupplierBid.rfq_id == rfq_id,
			SupplierBid.status.in_(["SUBMITTED", "EVALUATED"]),
		)
		bids: list[Any] = list(session.execute(stmt).scalars().all())

		if not bids:
			raise SourcingServiceError(f"No bids to evaluate for RFQ {rfq.rfq_ref}")

		criteria = rfq.evaluation_criteria or {}
		price_w = _dec(criteria.get("price_weight", 60))
		quality_w = _dec(criteria.get("quality_weight", 20))
		delivery_w = _dec(criteria.get("delivery_weight", 20))

		# Minimum bid price for price_score normalization
		min_price = min(_dec(b.total_bid_cents) for b in bids)

		for bid in bids:
			bid_price = _dec(bid.total_bid_cents)
			price_score = (min_price / bid_price * _dec(100)) if bid_price > 0 else _dec(0)

			tech_score = _dec(bid.technical_score) if bid.technical_score is not None else _dec(50)

			if bid.delivery_days and int(bid.delivery_days) > 0:
				delivery_score = (_dec(1) / _dec(bid.delivery_days) * _dec(100))
			else:
				delivery_score = _dec(0)

			composite = (
				price_score * (price_w / _dec(100))
				+ tech_score * (quality_w / _dec(100))
				+ delivery_score * (delivery_w / _dec(100))
			).quantize(_dec("0.01"), rounding=ROUND_HALF_UP)

			bid.composite_score = composite
			bid.status = "EVALUATED"

		session.flush()

		# Sort by composite descending
		bids.sort(key=lambda b: _dec(b.composite_score or 0), reverse=True)

		# Transition RFQ to CLOSED
		rfq.status = "CLOSED"
		session.flush()

		# Emit for winning bid
		winner = bids[0]
		_emit(
			BidEvaluatedEvent(
				aggregate_id=rfq.id,
				aggregate_type="RFQ",
				tenant_id=rfq.tenant_id,
				rfq_id=rfq_id,
				winning_bid_id=winner.id,
				supplier_id=winner.supplier_id,
				award_cents=winner.total_bid_cents,
			),
			session,
		)

		log.info(
			"Bids evaluated for RFQ %s: %d bids, winner=%s (score=%s)",
			rfq.rfq_ref, len(bids), winner.id, winner.composite_score,
		)
		return bids

	# ------------------------------------------------------------------
	# 5. award_rfq
	# ------------------------------------------------------------------

	@classmethod
	def award_rfq(
		cls,
		rfq_id: str,
		winning_bid_id: str,
		session: Any,
	) -> dict[str, Any]:
		"""Award the RFQ to a winning bid and raise a purchase order.

		Marks winning bid as AWARDED, all others as REJECTED.
		Transitions RFQ to AWARDED.
		Calls SCMService.create_purchase_order() with winning bid line items.
		Emits PurchaseOrderAwardedEvent.
		Returns dict with rfq_id, winning_bid_id, po_id, supplier_id, total_cents.
		"""
		from pgappforge.plugins.erp.procurement.sourcing.models import RFQ, SupplierBid
		from pgappforge.plugins.erp.procurement.sourcing.events import PurchaseOrderAwardedEvent

		rfq = session.get(RFQ, rfq_id)
		if rfq is None:
			raise RFQNotFoundError(f"RFQ {rfq_id!r} not found")
		if rfq.status not in ("CLOSED", "PUBLISHED"):
			raise InvalidStatusTransitionError(
				f"award_rfq() requires CLOSED or PUBLISHED status, got {rfq.status!r}"
			)

		winning_bid = session.get(SupplierBid, winning_bid_id)
		if winning_bid is None or winning_bid.rfq_id != rfq_id:
			raise BidNotFoundError(f"Bid {winning_bid_id!r} not found on RFQ {rfq_id!r}")

		# Reject all other bids
		stmt = sa.select(SupplierBid).where(
			SupplierBid.rfq_id == rfq_id,
			SupplierBid.id != winning_bid_id,
		)
		other_bids = session.execute(stmt).scalars().all()
		for bid in other_bids:
			bid.status = "REJECTED"

		winning_bid.status = "AWARDED"
		rfq.status = "AWARDED"
		session.flush()

		# Create purchase order via SCM plugin (best-effort)
		po_id = ""
		try:
			from pgappforge.plugins.erp.operations.scm.services import SCMService
			po_lines = [
				{
					"item_code": li.get("item_code", ""),
					"description": "",
					"quantity": li.get("qty", 1),
					"unit_cost_cents": li.get("unit_price_cents", 0),
					"currency_code": winning_bid.currency_code,
				}
				for li in (winning_bid.line_items or [])
			]
			po = SCMService.create_purchase_order(
				session=session,
				supplier_id=winning_bid.supplier_id,
				lines=po_lines,
				tenant_id=rfq.tenant_id,
				reference=rfq.rfq_ref,
				currency_code=winning_bid.currency_code,
			)
			po_id = po.id if po else ""
		except Exception as exc:  # noqa: BLE001
			log.info("SCM plugin not available or PO creation failed (%s) — continuing", exc)

		_emit(
			PurchaseOrderAwardedEvent(
				aggregate_id=rfq.id,
				aggregate_type="RFQ",
				tenant_id=rfq.tenant_id,
				rfq_id=rfq_id,
				po_id=po_id,
				supplier_id=winning_bid.supplier_id,
				total_cents=winning_bid.total_bid_cents,
			),
			session,
		)

		log.info(
			"RFQ %s awarded to supplier %s, bid=%s, total=%d¢, po=%s",
			rfq.rfq_ref, winning_bid.supplier_id, winning_bid_id,
			winning_bid.total_bid_cents, po_id,
		)
		return {
			"rfq_id": rfq_id,
			"rfq_ref": rfq.rfq_ref,
			"winning_bid_id": winning_bid_id,
			"supplier_id": winning_bid.supplier_id,
			"total_cents": winning_bid.total_bid_cents,
			"po_id": po_id,
		}

	# ------------------------------------------------------------------
	# 6. cancel_rfq
	# ------------------------------------------------------------------

	@classmethod
	def cancel_rfq(
		cls,
		rfq_id: str,
		reason: str,
		session: Any,
	) -> Any:
		"""Cancel an RFQ that has not yet been awarded.

		Emits RFQCancelledEvent.
		Returns the updated RFQ.
		"""
		from pgappforge.plugins.erp.procurement.sourcing.models import RFQ
		from pgappforge.plugins.erp.procurement.sourcing.events import RFQCancelledEvent

		rfq = session.get(RFQ, rfq_id)
		if rfq is None:
			raise RFQNotFoundError(f"RFQ {rfq_id!r} not found")
		if rfq.status == "AWARDED":
			raise InvalidStatusTransitionError("Cannot cancel an already-awarded RFQ")
		if rfq.status == "CANCELLED":
			return rfq  # idempotent

		rfq.status = "CANCELLED"
		session.flush()

		_emit(
			RFQCancelledEvent(
				aggregate_id=rfq.id,
				aggregate_type="RFQ",
				tenant_id=rfq.tenant_id,
				rfq_id=rfq_id,
				reason=reason,
			),
			session,
		)

		log.info("RFQ %s cancelled: %s", rfq.rfq_ref, reason)
		return rfq


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _validate_criteria(criteria: dict[str, Any]) -> None:
	"""Assert evaluation weights are present and positive."""
	for key in ("price_weight", "quality_weight", "delivery_weight"):
		if key not in criteria:
			raise SourcingServiceError(f"evaluation_criteria missing key {key!r}")
		if _dec(criteria[key]) < 0:
			raise SourcingServiceError(f"evaluation_criteria[{key!r}] must be non-negative")


# ---------------------------------------------------------------------------
# BPM Action registrations
# ---------------------------------------------------------------------------

@BPMActionRegistry.register("procurement.sourcing.create_rfq", "Create a Request for Quotation in DRAFT status")
def _bpm_create_rfq(
	record_ctx: dict,
	session: Any,
	title: str = "",
	items: list | None = None,
	rfq_type: str = "COMPETITIVE",
	description: str | None = None,
	submission_deadline: str | None = None,
	**kw: Any,
) -> dict:
	try:
		from pgappforge.plugins.erp.procurement.sourcing.services import SourcingService
	except ImportError:
		return {"status": "error", "message": "sourcing plugin not installed"}
	tenant_id = record_ctx.get("tenant_id", "")
	try:
		deadline = None
		if submission_deadline:
			deadline = datetime.fromisoformat(submission_deadline)
		rfq = SourcingService.create_rfq(
			title=title,
			items=items or [],
			tenant_id=tenant_id,
			session=session,
			rfq_type=rfq_type,
			description=description,
			submission_deadline=deadline,
		)
		return {"status": "ok", "rfq_id": rfq.id, "rfq_ref": rfq.rfq_ref}
	except Exception as exc:
		log.warning("bpm sourcing.create_rfq failed: %s", exc)
		return {"status": "error", "message": str(exc)}


@BPMActionRegistry.register("procurement.sourcing.award", "Award an RFQ to the winning bid")
def _bpm_award(
	record_ctx: dict,
	session: Any,
	rfq_id: str = "",
	winning_bid_id: str = "",
	**kw: Any,
) -> dict:
	try:
		from pgappforge.plugins.erp.procurement.sourcing.services import SourcingService
	except ImportError:
		return {"status": "error", "message": "sourcing plugin not installed"}
	try:
		result = SourcingService.award_rfq(
			rfq_id=rfq_id,
			winning_bid_id=winning_bid_id,
			session=session,
		)
		return {"status": "ok", **result}
	except Exception as exc:
		log.warning("bpm sourcing.award failed: %s", exc)
		return {"status": "error", "message": str(exc)}


__all__ = [
	"SourcingService",
	"SourcingServiceError",
	"RFQNotFoundError",
	"BidNotFoundError",
	"InvalidStatusTransitionError",
	"DeadlinePassedError",
	"DuplicateBidError",
]
