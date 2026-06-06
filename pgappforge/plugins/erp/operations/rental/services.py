"""
pgappforge/plugins/erp/operations/rental/services.py

RentalService — stateless business logic for the Rental Management plugin.

All methods receive an explicit SQLAlchemy 2.x session; no Flask context assumed.
Transaction boundaries owned by the caller.

Monetary invariants:
  - All amounts as integer cents
  - Never float/Numeric for money

Public API:
  create_order(asset_id, start_date, end_date, customer_name, tenant_id, session,
               *, customer_id, customer_email)                                 -> RentalOrder
  start_rental(order_id, session)                                              -> RentalOrder
  return_asset(order_id, return_condition_notes, session,
               *, damage_charge_cents)                                         -> RentalOrder
  cancel_order(order_id, session)                                              -> RentalOrder
  get_availability(asset_id, from_date, to_date, session)                     -> list[dict]
"""
from __future__ import annotations

import logging
import random
import string
import uuid
from datetime import date, datetime, timezone
from typing import Any

import sqlalchemy as sa

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class RentalServiceError(Exception):
	"""Base domain error for Rental operations."""


class RentalNotFoundError(RentalServiceError):
	"""Raised when a RentalOrder cannot be found."""


class RentalAssetNotFoundError(RentalServiceError):
	"""Raised when a RentalAsset cannot be found."""


class RentalStateError(RentalServiceError):
	"""Raised when an operation is invalid for the current order/asset status."""


class RentalConflictError(RentalServiceError):
	"""Raised when an asset has a conflicting active rental for the requested dates."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> datetime:
	return datetime.now(timezone.utc)


def _today() -> date:
	return datetime.now(timezone.utc).date()


def _uuid4() -> str:
	return str(uuid.uuid4())


def _order_ref() -> str:
	"""Generate a short rental reference, e.g. RNT-X4K9M2."""
	suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
	return f"RNT-{suffix}"


def _compute_rental_amount(days: int, daily_rate_cents: int) -> int:
	"""Compute rental_amount_cents = days * daily_rate_cents (minimum 1 day)."""
	assert daily_rate_cents >= 0, "daily_rate_cents must be non-negative"
	return max(days, 1) * daily_rate_cents


# ---------------------------------------------------------------------------
# RentalService
# ---------------------------------------------------------------------------

class RentalService:
	"""Stateless Rental Management business logic.

	Instantiate once per request/task; pass an explicit SQLAlchemy 2.x session
	to every method.  Caller owns commit/rollback.
	"""

	# ------------------------------------------------------------------
	# 1. create_order
	# ------------------------------------------------------------------

	@staticmethod
	def create_order(
		asset_id: str,
		start_date: date,
		end_date: date,
		customer_name: str,
		tenant_id: str,
		session: Any,
		*,
		customer_id: str | None = None,
		customer_email: str | None = None,
	) -> Any:
		"""Place a rental order.

		Validates:
		  - Asset exists and is AVAILABLE
		  - No conflicting ACTIVE rental overlaps the requested date range
		  - start_date < end_date

		Computes rental_amount_cents = days * daily_rate_cents.
		Sets asset.status = RENTED.
		Emits RentalOrderCreatedEvent.

		Returns:
			RentalOrder — flushed but not committed.
		"""
		from pgappforge.plugins.erp.operations.rental.models import RentalAsset, RentalOrder
		from pgappforge.plugins.erp.operations.rental.events import RentalOrderCreatedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		assert customer_name, "customer_name is required"
		assert tenant_id, "tenant_id is required"
		assert start_date < end_date, "start_date must be before end_date"

		asset = session.execute(
			sa.select(RentalAsset).where(
				RentalAsset.id == asset_id,
				RentalAsset.tenant_id == tenant_id,
			)
		).scalar_one_or_none()
		if asset is None:
			raise RentalAssetNotFoundError(f"RentalAsset {asset_id} not found")
		if asset.status != "AVAILABLE":
			raise RentalStateError(
				f"Asset {asset_id} is not available (current status: {asset.status!r})"
			)

		# Check for conflicting active rentals
		conflict = session.execute(
			sa.select(RentalOrder).where(
				RentalOrder.asset_id == asset_id,
				RentalOrder.status.in_(("PENDING", "ACTIVE")),
				RentalOrder.start_date < end_date,
				RentalOrder.end_date > start_date,
			)
		).scalar_one_or_none()
		if conflict is not None:
			raise RentalConflictError(
				f"Asset {asset_id} has a conflicting rental {conflict.order_ref!r} "
				f"({conflict.start_date} – {conflict.end_date})"
			)

		days = (end_date - start_date).days
		rental_amount_cents = _compute_rental_amount(days, asset.daily_rate_cents)

		# Unique order ref
		for _ in range(5):
			ref = _order_ref()
			taken = session.execute(
				sa.select(RentalOrder).where(
					RentalOrder.tenant_id == tenant_id,
					RentalOrder.order_ref == ref,
				)
			).scalar_one_or_none()
			if taken is None:
				break
		else:
			raise RentalServiceError("Failed to generate unique order_ref after 5 attempts")

		order = RentalOrder(
			tenant_id=tenant_id,
			asset_id=asset_id,
			customer_id=customer_id,
			customer_name=customer_name,
			customer_email=customer_email,
			order_ref=ref,
			start_date=start_date,
			end_date=end_date,
			status="PENDING",
			daily_rate_cents=asset.daily_rate_cents,
			deposit_amount_cents=asset.deposit_amount_cents,
			deposit_status="PENDING",
			rental_amount_cents=rental_amount_cents,
		)
		session.add(order)

		asset.status = "RENTED"
		asset.updated_at = _now()
		session.flush()

		emit_event(
			RentalOrderCreatedEvent(
				aggregate_id=order.id,
				aggregate_type="RentalOrder",
				order_id=order.id,
				asset_id=asset_id,
				customer_id=customer_id or "",
				start_date=start_date.isoformat(),
				end_date=end_date.isoformat(),
				tenant_id=tenant_id,
			),
			session,
		)
		log.info(
			"RentalService.create_order: %s %r asset=%s %s–%s amount=%d¢",
			order.id, ref, asset_id, start_date, end_date, rental_amount_cents,
		)
		return order

	# ------------------------------------------------------------------
	# 2. start_rental
	# ------------------------------------------------------------------

	@staticmethod
	def start_rental(
		order_id: str,
		session: Any,
	) -> Any:
		"""Activate a PENDING rental order.

		Transitions PENDING → ACTIVE.
		Emits RentalStartedEvent.

		Returns:
			RentalOrder — flushed but not committed.
		"""
		from pgappforge.plugins.erp.operations.rental.models import RentalOrder
		from pgappforge.plugins.erp.operations.rental.events import RentalStartedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		order = session.get(RentalOrder, order_id)
		if order is None:
			raise RentalNotFoundError(f"RentalOrder {order_id} not found")
		if order.status != "PENDING":
			raise RentalStateError(
				f"Cannot start rental in status {order.status!r}; expected PENDING"
			)

		order.status = "ACTIVE"
		order.updated_at = _now()
		session.flush()

		emit_event(
			RentalStartedEvent(
				aggregate_id=order.id,
				aggregate_type="RentalOrder",
				order_id=order.id,
				asset_id=str(order.asset_id),
				start_date=order.start_date.isoformat(),
				tenant_id=order.tenant_id,
			),
			session,
		)
		log.info("RentalService.start_rental: order=%s → ACTIVE", order_id)
		return order

	# ------------------------------------------------------------------
	# 3. return_asset
	# ------------------------------------------------------------------

	@staticmethod
	def return_asset(
		order_id: str,
		return_condition_notes: str,
		session: Any,
		*,
		damage_charge_cents: int = 0,
	) -> Any:
		"""Process asset return.

		Transitions ACTIVE → COMPLETED.
		Sets actual_return_date to today.
		If damage_charge_cents > 0: emits DamageDepositChargedEvent.
		Computes prorated refund if returned early (informational — stored in notes).
		Sets asset.status = AVAILABLE.
		Emits RentalReturnedEvent.

		Returns:
			RentalOrder — flushed but not committed.
		"""
		from pgappforge.plugins.erp.operations.rental.models import RentalAsset, RentalOrder
		from pgappforge.plugins.erp.operations.rental.events import (
			RentalReturnedEvent,
			DamageDepositChargedEvent,
		)
		from pgappforge.plugins.erp.foundation.events import emit_event

		assert damage_charge_cents >= 0, "damage_charge_cents must be non-negative"

		order = session.get(RentalOrder, order_id)
		if order is None:
			raise RentalNotFoundError(f"RentalOrder {order_id} not found")
		if order.status != "ACTIVE":
			raise RentalStateError(
				f"Cannot return asset for order in status {order.status!r}; expected ACTIVE"
			)

		today = _today()
		now = _now()

		# Prorated refund calculation (informational)
		scheduled_days = (order.end_date - order.start_date).days
		actual_days = (today - order.start_date).days
		prorated_notes = ""
		if actual_days < scheduled_days and actual_days > 0:
			unused_days = scheduled_days - actual_days
			prorated_refund = unused_days * order.daily_rate_cents
			prorated_notes = (
				f"\nEarly return: {actual_days} of {scheduled_days} days used. "
				f"Prorated refund: {prorated_refund}¢"
			)

		order.status = "COMPLETED"
		order.actual_return_date = today
		order.return_condition_notes = return_condition_notes
		order.damage_charge_cents = damage_charge_cents
		if prorated_notes:
			order.notes = f"{order.notes or ''}{prorated_notes}".strip()
		order.updated_at = now
		session.flush()

		# Restore asset
		asset = session.get(RentalAsset, order.asset_id)
		if asset is not None:
			asset.status = "AVAILABLE"
			if return_condition_notes:
				# Update condition rating heuristic: reduce by 1 per damage charge tier
				if damage_charge_cents > 0:
					asset.condition_rating = max(1, asset.condition_rating - 1)
			asset.updated_at = now

		session.flush()

		# Damage deposit charge event
		if damage_charge_cents > 0:
			emit_event(
				DamageDepositChargedEvent(
					aggregate_id=order.id,
					aggregate_type="RentalOrder",
					order_id=order.id,
					amount_cents=damage_charge_cents,
					tenant_id=order.tenant_id,
				),
				session,
			)

		emit_event(
			RentalReturnedEvent(
				aggregate_id=order.id,
				aggregate_type="RentalOrder",
				order_id=order.id,
				asset_id=str(order.asset_id),
				return_date=today.isoformat(),
				condition=return_condition_notes or "",
				tenant_id=order.tenant_id,
			),
			session,
		)
		log.info(
			"RentalService.return_asset: order=%s → COMPLETED return_date=%s damage=%d¢",
			order_id, today, damage_charge_cents,
		)
		return order

	# ------------------------------------------------------------------
	# 4. cancel_order
	# ------------------------------------------------------------------

	@staticmethod
	def cancel_order(
		order_id: str,
		session: Any,
	) -> Any:
		"""Cancel a PENDING rental order and restore asset to AVAILABLE.

		Returns:
			RentalOrder — flushed but not committed.

		Raises:
			RentalStateError if order is not PENDING.
		"""
		from pgappforge.plugins.erp.operations.rental.models import RentalAsset, RentalOrder

		order = session.get(RentalOrder, order_id)
		if order is None:
			raise RentalNotFoundError(f"RentalOrder {order_id} not found")
		if order.status != "PENDING":
			raise RentalStateError(
				f"Only PENDING orders can be cancelled; current status: {order.status!r}"
			)

		now = _now()
		order.status = "CANCELLED"
		order.updated_at = now

		asset = session.get(RentalAsset, order.asset_id)
		if asset is not None:
			asset.status = "AVAILABLE"
			asset.updated_at = now

		session.flush()
		log.info("RentalService.cancel_order: order=%s → CANCELLED", order_id)
		return order

	# ------------------------------------------------------------------
	# 5. get_availability
	# ------------------------------------------------------------------

	@staticmethod
	def get_availability(
		asset_id: str,
		from_date: date,
		to_date: date,
		session: Any,
	) -> list[dict[str, Any]]:
		"""Return a list of available date ranges for the asset.

		Subtracts all PENDING/ACTIVE rental windows from [from_date, to_date].

		Returns:
			list of {"from": ISO-date, "to": ISO-date} dicts representing
			contiguous available ranges (exclusive end — like Python ranges).
		"""
		from pgappforge.plugins.erp.operations.rental.models import RentalOrder

		assert from_date <= to_date, "from_date must be <= to_date"

		# Fetch overlapping active/pending orders, ordered by start_date
		blocked = session.execute(
			sa.select(RentalOrder.start_date, RentalOrder.end_date)
			.where(
				RentalOrder.asset_id == asset_id,
				RentalOrder.status.in_(("PENDING", "ACTIVE")),
				RentalOrder.start_date < to_date,
				RentalOrder.end_date > from_date,
			)
			.order_by(RentalOrder.start_date)
		).all()

		# Build free-range list by walking blocked windows
		available: list[dict[str, Any]] = []
		cursor = from_date

		for blk_start, blk_end in blocked:
			# Clamp to query window
			blk_start = max(blk_start, from_date)
			blk_end = min(blk_end, to_date)

			if cursor < blk_start:
				available.append({"from": cursor.isoformat(), "to": blk_start.isoformat()})
			cursor = max(cursor, blk_end)

		if cursor < to_date:
			available.append({"from": cursor.isoformat(), "to": to_date.isoformat()})

		return available


__all__ = [
	"RentalService",
	"RentalServiceError",
	"RentalNotFoundError",
	"RentalAssetNotFoundError",
	"RentalStateError",
	"RentalConflictError",
]
