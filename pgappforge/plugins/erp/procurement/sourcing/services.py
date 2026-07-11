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
from datetime import datetime, timedelta, timezone
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


def current_tenant_id() -> str | None:
	try:
		from pgappforge.multitenancy.middleware import get_current_tenant_id
		tenant_id = get_current_tenant_id()
	except Exception:
		tenant_id = None
	return str(tenant_id) if tenant_id else None


def _tenant_id(explicit_tenant_id: str | None = None) -> str:
	tenant_id = current_tenant_id()
	if tenant_id:
		if explicit_tenant_id and str(explicit_tenant_id) != tenant_id:
			raise ValueError("tenant_id does not match current tenant")
		return tenant_id
	if explicit_tenant_id:
		return str(explicit_tenant_id)
	raise ValueError("Tenant context required")


def _pct(numerator: int, denominator: int) -> Decimal:
	if denominator <= 0:
		return Decimal("0")
	return (Decimal(str(numerator)) / Decimal(str(denominator)) * Decimal("100")).quantize(
		Decimal("0.01"), rounding=ROUND_HALF_UP
	)


def _rfq_category(rfq: Any) -> str | None:
	if getattr(rfq, "category", None):
		return str(rfq.category)
	for item in rfq.items or []:
		if not isinstance(item, dict):
			continue
		for key in ("category", "expense_category", "item_category"):
			if item.get(key):
				return str(item[key])
	return None


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

		tenant_id = _tenant_id(tenant_id)
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
		tenant_id: str | None = None,
	) -> Any:
		"""Transition DRAFT → PUBLISHED and record invited suppliers.

		invited_supplier_ids is a list of supplier_id strings (advisory refs).
		Emits RFQPublishedEvent.
		Returns the updated RFQ.
		"""
		from pgappforge.plugins.erp.procurement.sourcing.models import RFQ
		from pgappforge.plugins.erp.procurement.sourcing.events import RFQPublishedEvent

		tenant_id = _tenant_id(tenant_id)
		rfq = session.execute(
			sa.select(RFQ).where(RFQ.id == rfq_id, RFQ.tenant_id == tenant_id)
		).scalar_one_or_none()
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
		tenant_id: str | None = None,
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

		tenant_id = _tenant_id(tenant_id)
		rfq = session.execute(
			sa.select(RFQ).where(RFQ.id == rfq_id, RFQ.tenant_id == tenant_id)
		).scalar_one_or_none()
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
			SupplierBid.tenant_id == tenant_id,
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
		tenant_id: str | None = None,
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

		tenant_id = _tenant_id(tenant_id)
		rfq = session.execute(
			sa.select(RFQ).where(RFQ.id == rfq_id, RFQ.tenant_id == tenant_id)
		).scalar_one_or_none()
		if rfq is None:
			raise RFQNotFoundError(f"RFQ {rfq_id!r} not found")
		if rfq.status not in ("PUBLISHED", "CLOSED"):
			raise InvalidStatusTransitionError(
				f"evaluate_bids() requires PUBLISHED or CLOSED status, got {rfq.status!r}"
			)

		stmt = sa.select(SupplierBid).where(
			SupplierBid.tenant_id == tenant_id,
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
		tenant_id: str | None = None,
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

		tenant_id = _tenant_id(tenant_id)
		rfq = session.execute(
			sa.select(RFQ).where(RFQ.id == rfq_id, RFQ.tenant_id == tenant_id)
		).scalar_one_or_none()
		if rfq is None:
			raise RFQNotFoundError(f"RFQ {rfq_id!r} not found")
		if rfq.status not in ("CLOSED", "PUBLISHED"):
			raise InvalidStatusTransitionError(
				f"award_rfq() requires CLOSED or PUBLISHED status, got {rfq.status!r}"
			)

		winning_bid = session.execute(
			sa.select(SupplierBid).where(
				SupplierBid.id == winning_bid_id,
				SupplierBid.tenant_id == tenant_id,
				SupplierBid.rfq_id == rfq_id,
			)
		).scalar_one_or_none()
		if winning_bid is None:
			raise BidNotFoundError(f"Bid {winning_bid_id!r} not found on RFQ {rfq_id!r}")

		# Reject all other bids
		stmt = sa.select(SupplierBid).where(
			SupplierBid.tenant_id == tenant_id,
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
			from datetime import date as _date, timedelta as _td
			# Convert bid line_items to SCM PO lines format
			po_lines = [
				{
					"product_code": li.get("item_code", f"ITEM-{i}"),
					"description": li.get("description", ""),
					"ordered_qty": li.get("qty", 1),
					"unit_of_measure": li.get("unit", "EA"),
					"unit_price_cents": li.get("unit_price_cents", 0),
				}
				for i, li in enumerate(winning_bid.line_items or [])
			]
			today = _date.today()
			delivery_days = int(winning_bid.delivery_days or 30)
			# SCMService is an instance method — must instantiate
			po = SCMService().create_purchase_order(
				session=session,
				supplier_id=winning_bid.supplier_id,
				lines=po_lines,
				order_date=today,
				expected_delivery=today + _td(days=delivery_days),
				tenant_id=rfq.tenant_id,
				req_id=rfq.rfq_ref,  # cross-reference to RFQ
			)
			po_id = po.id if po else ""
		except ImportError:
			log.debug("SCM plugin not available — PO creation skipped")
		except Exception as exc:  # noqa: BLE001
			log.warning("PO creation from RFQ award failed: %s", exc)

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
		tenant_id: str | None = None,
	) -> Any:
		"""Cancel an RFQ that has not yet been awarded.

		Emits RFQCancelledEvent.
		Returns the updated RFQ.
		"""
		from pgappforge.plugins.erp.procurement.sourcing.models import RFQ
		from pgappforge.plugins.erp.procurement.sourcing.events import RFQCancelledEvent

		tenant_id = _tenant_id(tenant_id)
		rfq = session.execute(
			sa.select(RFQ).where(RFQ.id == rfq_id, RFQ.tenant_id == tenant_id)
		).scalar_one_or_none()
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

	# ------------------------------------------------------------------
	# 7. start_reverse_auction
	# ------------------------------------------------------------------

	@classmethod
	def start_reverse_auction(
		cls,
		rfq_id: str,
		duration_minutes: int,
		reserve_price_cents: int,
		session: Any,
		tenant_id: str | None = None,
	) -> dict[str, Any]:
		"""Enable reverse-auction bidding for an RFQ."""
		from pgappforge.plugins.erp.procurement.sourcing.models import RFQ

		tenant_id = _tenant_id(tenant_id)
		try:
			duration = int(duration_minutes)
		except (TypeError, ValueError) as exc:
			raise ValueError("duration_minutes must be an integer") from exc
		try:
			reserve = int(reserve_price_cents)
		except (TypeError, ValueError) as exc:
			raise ValueError("reserve_price_cents must be an integer") from exc
		if duration <= 0:
			raise ValueError("duration_minutes must be positive")
		if duration > 10080:
			raise ValueError("duration_minutes must be no greater than 10080")
		if reserve <= 0:
			raise ValueError("reserve_price_cents must be positive")

		rfq = session.execute(
			sa.select(RFQ).where(RFQ.id == rfq_id, RFQ.tenant_id == tenant_id)
		).scalar_one_or_none()
		if rfq is None:
			raise RFQNotFoundError(f"RFQ {rfq_id!r} not found")

		now = _now_utc()
		rfq.auction_mode = True
		rfq.reserve_price_cents = reserve
		rfq.current_best_bid_cents = None
		rfq.auction_bids = []
		rfq.auction_end_time = now + timedelta(minutes=duration)
		session.flush()

		return {
			"rfq_id": rfq.id,
			"auction_mode": bool(rfq.auction_mode),
			"reserve_price_cents": rfq.reserve_price_cents,
			"current_best_bid_cents": rfq.current_best_bid_cents,
			"auction_start_time": now.isoformat(),
			"auction_end_time": rfq.auction_end_time.isoformat(),
			"status": rfq.status,
		}

	# ------------------------------------------------------------------
	# 8. place_auction_bid
	# ------------------------------------------------------------------

	@classmethod
	def place_auction_bid(
		cls,
		rfq_id: str,
		supplier_id: str,
		bid_cents: int,
		session: Any,
		tenant_id: str | None = None,
	) -> dict[str, Any]:
		"""Place a lower reverse-auction bid without going below the reserve floor."""
		from pgappforge.plugins.erp.procurement.sourcing.models import RFQ

		tenant_id = _tenant_id(tenant_id)
		rfq = session.execute(
			sa.select(RFQ).where(RFQ.id == rfq_id, RFQ.tenant_id == tenant_id)
		).scalar_one_or_none()
		if rfq is None:
			raise RFQNotFoundError(f"RFQ {rfq_id!r} not found")
		if not rfq.auction_mode:
			raise ValueError("RFQ is not in auction mode")
		if rfq.auction_end_time is not None and _now_utc() > rfq.auction_end_time:
			raise ValueError("Auction has expired")

		try:
			bid = int(bid_cents)
		except (TypeError, ValueError) as exc:
			raise ValueError("bid_cents must be an integer") from exc
		reserve = int(rfq.reserve_price_cents or 0)
		if bid <= 0:
			raise ValueError("bid_cents must be positive")
		if reserve and bid < reserve:
			raise ValueError("Bid is below reserve_price_cents")
		if rfq.current_best_bid_cents is not None and bid >= int(rfq.current_best_bid_cents):
			raise ValueError("Bid must be lower than the current best bid")

		entry = {
			"supplier_id": str(supplier_id),
			"bid_cents": bid,
			"ts": _now_utc().isoformat(),
		}
		rfq.current_best_bid_cents = bid
		rfq.auction_bids = [*(rfq.auction_bids or []), entry]
		session.flush()

		return {
			"rfq_id": rfq.id,
			"current_best_bid_cents": rfq.current_best_bid_cents,
			"bid_count": len(rfq.auction_bids or []),
			"auction_end_time": rfq.auction_end_time.isoformat() if rfq.auction_end_time else None,
			"leader_supplier_id": supplier_id,
		}

	# ------------------------------------------------------------------
	# 9. close_auction
	# ------------------------------------------------------------------

	@classmethod
	def close_auction(
		cls,
		rfq_id: str,
		session: Any,
		tenant_id: str | None = None,
	) -> dict[str, Any]:
		"""Close an auction, mark the RFQ awarded, and return the lowest bid."""
		from pgappforge.plugins.erp.procurement.sourcing.models import RFQ, RFQAward

		tenant_id = _tenant_id(tenant_id)
		rfq = session.execute(
			sa.select(RFQ).where(RFQ.id == rfq_id, RFQ.tenant_id == tenant_id)
		).scalar_one_or_none()
		if rfq is None:
			raise RFQNotFoundError(f"RFQ {rfq_id!r} not found")

		bids = list(rfq.auction_bids or [])
		if not bids:
			raise ValueError("Auction has no bids")

		winning = min(bids, key=lambda b: int(b.get("bid_cents", 0) or 0))
		winning_bid = int(winning.get("bid_cents", 0) or 0)
		winner_supplier_id = str(winning.get("supplier_id", ""))
		rfq.current_best_bid_cents = winning_bid
		rfq.status = "AWARDED"
		rfq.auction_mode = False

		award = session.execute(
			sa.select(RFQAward).where(
				RFQAward.tenant_id == tenant_id,
				RFQAward.rfq_id == rfq.id,
			)
		).scalar_one_or_none()
		if award is None:
			award = RFQAward(tenant_id=rfq.tenant_id, rfq_id=rfq.id)
			session.add(award)
		award.supplier_id = winner_supplier_id
		award.award_price_cents = winning_bid
		award.award_source = "REVERSE_AUCTION"
		award.award_details = {
			"winning_bid": winning,
			"reserve_price_cents": rfq.reserve_price_cents,
			"bid_count": len(bids),
		}
		award.awarded_at = _now_utc()
		session.flush()

		reserve = int(rfq.reserve_price_cents or 0)
		savings_pct = _pct(max(reserve - winning_bid, 0), reserve) if reserve else Decimal("0")
		return {
			"rfq_id": rfq.id,
			"award_id": award.id,
			"winner_supplier_id": winner_supplier_id,
			"winning_bid_cents": winning_bid,
			"savings_pct": savings_pct,
		}

	# ------------------------------------------------------------------
	# 10. record_savings
	# ------------------------------------------------------------------

	@classmethod
	def record_savings(
		cls,
		rfq_id: str,
		baseline_price_cents: int,
		awarded_price_cents: int,
		session: Any,
		tenant_id: str | None = None,
	) -> dict[str, Any]:
		"""Persist savings achieved on an RFQ award."""
		from pgappforge.plugins.erp.procurement.sourcing.models import ProcurementSavings, RFQ

		tenant_id = _tenant_id(tenant_id)
		rfq = session.execute(
			sa.select(RFQ).where(RFQ.id == rfq_id, RFQ.tenant_id == tenant_id)
		).scalar_one_or_none()
		if rfq is None:
			raise RFQNotFoundError(f"RFQ {rfq_id!r} not found")
		if baseline_price_cents <= 0:
			raise ValueError("baseline_price_cents must be positive")

		savings_cents = int(baseline_price_cents) - int(awarded_price_cents)
		savings_pct = _pct(savings_cents, int(baseline_price_cents))
		record = ProcurementSavings(
			tenant_id=rfq.tenant_id,
			rfq_id=rfq.id,
			baseline_price_cents=int(baseline_price_cents),
			awarded_price_cents=int(awarded_price_cents),
			savings_cents=savings_cents,
			savings_pct=savings_pct,
			category=_rfq_category(rfq),
			recorded_at=_now_utc(),
		)
		session.add(record)
		session.flush()

		return {
			"id": record.id,
			"rfq_id": record.rfq_id,
			"tenant_id": record.tenant_id,
			"baseline_price_cents": record.baseline_price_cents,
			"awarded_price_cents": record.awarded_price_cents,
			"savings_cents": record.savings_cents,
			"savings_pct": record.savings_pct,
			"category": record.category,
			"recorded_at": record.recorded_at,
		}

	# ------------------------------------------------------------------
	# 11. get_savings_report
	# ------------------------------------------------------------------

	@classmethod
	def get_savings_report(
		cls,
		tenant_id: str,
		from_date: datetime,
		to_date: datetime,
		session: Any,
	) -> dict[str, Any]:
		"""Aggregate procurement savings for a tenant/date window."""
		from pgappforge.plugins.erp.procurement.sourcing.models import ProcurementSavings

		tenant_id = _tenant_id(tenant_id)
		rows = list(session.execute(
			sa.select(ProcurementSavings).where(
				ProcurementSavings.tenant_id == tenant_id,
				ProcurementSavings.recorded_at >= from_date,
				ProcurementSavings.recorded_at <= to_date,
			)
		).scalars().all())

		total_savings = sum(int(row.savings_cents or 0) for row in rows)
		by_category: dict[str, int] = {}
		for row in rows:
			category = row.category or "UNCATEGORIZED"
			by_category[category] = by_category.get(category, 0) + int(row.savings_cents or 0)

		top = sorted(rows, key=lambda row: int(row.savings_cents or 0), reverse=True)[:10]
		return {
			"tenant_id": tenant_id,
			"from_date": from_date,
			"to_date": to_date,
			"total_savings_cents": total_savings,
			"savings_by_category": by_category,
			"top_10_rfqs_by_savings": [
				{
					"rfq_id": row.rfq_id,
					"savings_cents": row.savings_cents,
					"savings_pct": row.savings_pct,
					"category": row.category,
					"recorded_at": row.recorded_at,
				}
				for row in top
			],
		}


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

def _bpm_record_id(record_ctx: dict, explicit: str, *keys: str) -> str:
	if explicit:
		return explicit
	for key in keys:
		value = record_ctx.get(key)
		if value:
			return str(value)
	return str(record_ctx.get("record_id") or record_ctx.get("id") or "")


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
			tenant_id=record_ctx.get("tenant_id"),
		)
		return {"status": "ok", **result}
	except Exception as exc:
		log.warning("bpm sourcing.award failed: %s", exc)
		return {"status": "error", "message": str(exc)}


@BPMActionRegistry.register("procurement.sourcing.publish_rfq", "Publish an RFQ and invite suppliers")
def _bpm_publish_rfq(
	record_ctx: dict,
	session: Any,
	rfq_id: str = "",
	invited_supplier_ids: list | None = None,
	**kw: Any,
) -> dict:
	try:
		rfq = SourcingService.publish_rfq(
			rfq_id=_bpm_record_id(record_ctx, rfq_id, "rfq_id"),
			invited_supplier_ids=invited_supplier_ids or [],
			session=session,
			tenant_id=record_ctx.get("tenant_id"),
		)
		return {"status": "ok", "rfq_id": rfq.id, "rfq_status": rfq.status}
	except Exception as exc:
		log.warning("bpm sourcing.publish_rfq failed: %s", exc)
		return {"status": "error", "message": str(exc)}


@BPMActionRegistry.register("procurement.sourcing.submit_bid", "Submit a supplier bid for a published RFQ")
def _bpm_submit_bid(
	record_ctx: dict,
	session: Any,
	rfq_id: str = "",
	supplier_id: str = "",
	line_items: list | None = None,
	total_cents: int = 0,
	**kw: Any,
) -> dict:
	try:
		bid = SourcingService.submit_bid(
			rfq_id=_bpm_record_id(record_ctx, rfq_id, "rfq_id"),
			supplier_id=supplier_id or str(record_ctx.get("supplier_id") or ""),
			line_items=line_items or [],
			total_cents=int(total_cents),
			session=session,
			delivery_days=kw.get("delivery_days"),
			validity_days=int(kw.get("validity_days", 30)),
			quality_notes=kw.get("quality_notes"),
			currency_code=kw.get("currency_code", "USD"),
			tenant_id=record_ctx.get("tenant_id"),
		)
		return {"status": "ok", "bid_id": bid.id, "bid_status": bid.status}
	except Exception as exc:
		log.warning("bpm sourcing.submit_bid failed: %s", exc)
		return {"status": "error", "message": str(exc)}


@BPMActionRegistry.register("procurement.sourcing.evaluate_bids", "Evaluate submitted bids for an RFQ")
def _bpm_evaluate_bids(
	record_ctx: dict,
	session: Any,
	rfq_id: str = "",
	**kw: Any,
) -> dict:
	try:
		bids = SourcingService.evaluate_bids(
			rfq_id=_bpm_record_id(record_ctx, rfq_id, "rfq_id"),
			session=session,
			tenant_id=record_ctx.get("tenant_id"),
		)
		winner = bids[0] if bids else None
		return {
			"status": "ok",
			"bid_count": len(bids),
			"winning_bid_id": winner.id if winner else "",
		}
	except Exception as exc:
		log.warning("bpm sourcing.evaluate_bids failed: %s", exc)
		return {"status": "error", "message": str(exc)}


@BPMActionRegistry.register("procurement.sourcing.cancel_rfq", "Cancel an RFQ before award")
def _bpm_cancel_rfq(
	record_ctx: dict,
	session: Any,
	rfq_id: str = "",
	reason: str = "",
	**kw: Any,
) -> dict:
	try:
		rfq = SourcingService.cancel_rfq(
			rfq_id=_bpm_record_id(record_ctx, rfq_id, "rfq_id"),
			reason=reason or str(kw.get("message") or "Cancelled by workflow"),
			session=session,
			tenant_id=record_ctx.get("tenant_id"),
		)
		return {"status": "ok", "rfq_id": rfq.id, "rfq_status": rfq.status}
	except Exception as exc:
		log.warning("bpm sourcing.cancel_rfq failed: %s", exc)
		return {"status": "error", "message": str(exc)}


@BPMActionRegistry.register("procurement.sourcing.close_auction", "Close a reverse auction and select the lowest bid")
def _bpm_close_auction(
	record_ctx: dict,
	session: Any,
	rfq_id: str = "",
	**kw: Any,
) -> dict:
	try:
		result = SourcingService.close_auction(
			rfq_id=_bpm_record_id(record_ctx, rfq_id, "rfq_id"),
			session=session,
			tenant_id=record_ctx.get("tenant_id"),
		)
		return {"status": "ok", **result}
	except Exception as exc:
		log.warning("bpm sourcing.close_auction failed: %s", exc)
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
