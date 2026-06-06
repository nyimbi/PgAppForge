"""
pgappforge/plugins/erp/operations/repair/services.py

RepairService — stateless business logic for the Repair / RMA plugin.

All methods receive an explicit SQLAlchemy 2.x session; no Flask context assumed.
Transaction boundaries owned by the caller.

Monetary invariants:
  - All amounts as integer cents
  - Never float/Numeric for money

Public API:
  create_order(customer_name, product_name, problem_description, tenant_id, session,
               *, customer_email, customer_id, serial_number, entity_id)       -> RepairOrder
  assign_technician(order_id, technician_id, session)                          -> RepairOrder
  record_diagnosis(order_id, diagnosis, session, *, estimated_cost_cents)      -> RepairOrder
  complete_repair(order_id, technician_id, session,
                  *, actual_cost_cents, parts_used)                            -> RepairOrder
  return_to_customer(order_id, session)                                        -> RepairOrder
  create_warranty_claim(product_name, serial_number, customer_name,
                        claim_description, tenant_id, session)                 -> WarrantyClaim
"""
from __future__ import annotations

import logging
import random
import string
import uuid
from datetime import datetime, timezone
from typing import Any

import sqlalchemy as sa

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class RepairServiceError(Exception):
	"""Base domain error for Repair operations."""


class RepairNotFoundError(RepairServiceError):
	"""Raised when a RepairOrder cannot be found."""


class RepairStateError(RepairServiceError):
	"""Raised when an operation is invalid for the current order status."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> datetime:
	return datetime.now(timezone.utc)


def _uuid4() -> str:
	return str(uuid.uuid4())


def _order_ref() -> str:
	"""Generate a short repair reference, e.g. RPR-X4K9M."""
	suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
	return f"RPR-{suffix}"


# ---------------------------------------------------------------------------
# RepairService
# ---------------------------------------------------------------------------

class RepairService:
	"""Stateless Repair / RMA business logic.

	Instantiate once per request/task; pass an explicit SQLAlchemy 2.x session
	to every method.  Caller owns commit/rollback.
	"""

	# ------------------------------------------------------------------
	# 1. create_order
	# ------------------------------------------------------------------

	@staticmethod
	def create_order(
		customer_name: str,
		product_name: str,
		problem_description: str,
		tenant_id: str,
		session: Any,
		*,
		customer_email: str | None = None,
		customer_id: str | None = None,
		customer_phone: str | None = None,
		serial_number: str | None = None,
		entity_id: str | None = None,
		promised_by: Any | None = None,
	) -> Any:
		"""Register a new repair order.

		Generates a unique order_ref and emits RepairOrderCreatedEvent.

		Returns:
			RepairOrder — flushed but not committed.
		"""
		from pgappforge.plugins.erp.operations.repair.models import RepairOrder
		from pgappforge.plugins.erp.operations.repair.events import RepairOrderCreatedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		assert customer_name, "customer_name is required"
		assert product_name, "product_name is required"
		assert problem_description, "problem_description is required"
		assert tenant_id, "tenant_id is required"

		# Ensure uniqueness — retry up to 5 times on collision (extremely unlikely)
		for _ in range(5):
			ref = _order_ref()
			existing = session.execute(
				sa.select(RepairOrder).where(
					RepairOrder.tenant_id == tenant_id,
					RepairOrder.order_ref == ref,
				)
			).scalar_one_or_none()
			if existing is None:
				break
		else:
			raise RepairServiceError("Failed to generate unique order_ref after 5 attempts")

		order = RepairOrder(
			tenant_id=tenant_id,
			order_ref=ref,
			customer_name=customer_name,
			customer_email=customer_email,
			customer_id=customer_id,
			customer_phone=customer_phone,
			product_name=product_name,
			serial_number=serial_number,
			problem_description=problem_description,
			entity_id=entity_id,
			promised_by=promised_by,
			status="RECEIVED",
		)
		session.add(order)
		session.flush()

		emit_event(
			RepairOrderCreatedEvent(
				aggregate_id=order.id,
				aggregate_type="RepairOrder",
				order_id=order.id,
				customer_id=customer_id or "",
				product_name=product_name,
				tenant_id=tenant_id,
			),
			session,
		)
		log.info(
			"RepairService.create_order: %s %r tenant=%s product=%r",
			order.id, ref, tenant_id, product_name,
		)
		return order

	# ------------------------------------------------------------------
	# 2. assign_technician
	# ------------------------------------------------------------------

	@staticmethod
	def assign_technician(
		order_id: str,
		technician_id: str,
		session: Any,
	) -> Any:
		"""Assign a technician and advance RECEIVED → DIAGNOSING.

		Returns:
			RepairOrder — flushed but not committed.

		Raises:
			RepairNotFoundError, RepairStateError
		"""
		from pgappforge.plugins.erp.operations.repair.models import RepairOrder

		assert technician_id, "technician_id is required"

		order = session.get(RepairOrder, order_id)
		if order is None:
			raise RepairNotFoundError(f"RepairOrder {order_id} not found")
		if order.status not in ("RECEIVED", "DIAGNOSING"):
			raise RepairStateError(
				f"Cannot assign technician to order in status {order.status!r}"
			)

		order.assigned_technician_id = technician_id
		if order.status == "RECEIVED":
			order.status = "DIAGNOSING"
		order.updated_at = _now()
		session.flush()

		log.info(
			"RepairService.assign_technician: order=%s tech=%s status→DIAGNOSING",
			order_id, technician_id,
		)
		return order

	# ------------------------------------------------------------------
	# 3. record_diagnosis
	# ------------------------------------------------------------------

	@staticmethod
	def record_diagnosis(
		order_id: str,
		diagnosis: str,
		session: Any,
		*,
		estimated_cost_cents: int | None = None,
	) -> Any:
		"""Record technician diagnosis and optional cost estimate.

		Emits RepairDiagnosedEvent.

		Returns:
			RepairOrder — flushed but not committed.
		"""
		from pgappforge.plugins.erp.operations.repair.models import RepairOrder
		from pgappforge.plugins.erp.operations.repair.events import RepairDiagnosedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		assert diagnosis, "diagnosis is required"

		order = session.get(RepairOrder, order_id)
		if order is None:
			raise RepairNotFoundError(f"RepairOrder {order_id} not found")
		if order.status not in ("DIAGNOSING", "RECEIVED"):
			raise RepairStateError(
				f"Cannot record diagnosis on order in status {order.status!r}"
			)

		now = _now()
		order.diagnosis = diagnosis
		order.diagnosis_at = now
		if estimated_cost_cents is not None:
			assert estimated_cost_cents >= 0, "estimated_cost_cents must be non-negative"
			order.estimated_cost_cents = estimated_cost_cents
		order.updated_at = now
		session.flush()

		emit_event(
			RepairDiagnosedEvent(
				aggregate_id=order.id,
				aggregate_type="RepairOrder",
				order_id=order.id,
				technician_id=order.assigned_technician_id or "",
				diagnosis=diagnosis,
				estimated_cost_cents=estimated_cost_cents or 0,
				tenant_id=order.tenant_id,
			),
			session,
		)
		log.info("RepairService.record_diagnosis: order=%s est=%s¢", order_id, estimated_cost_cents)
		return order

	# ------------------------------------------------------------------
	# 4. complete_repair
	# ------------------------------------------------------------------

	@staticmethod
	def complete_repair(
		order_id: str,
		technician_id: str,
		session: Any,
		*,
		actual_cost_cents: int | None = None,
		parts_used: list[dict[str, Any]] | None = None,
	) -> Any:
		"""Mark repair work as complete and advance to QC → READY_FOR_PICKUP.

		Accepts orders in status: DIAGNOSING | AWAITING_PARTS | IN_REPAIR
		Transitions: → QC → READY_FOR_PICKUP (single hop for simplicity;
		QC is implicit — extend if a separate QC approval step is needed).

		Emits RepairCompletedEvent.

		Returns:
			RepairOrder — flushed but not committed.
		"""
		from pgappforge.plugins.erp.operations.repair.models import RepairOrder
		from pgappforge.plugins.erp.operations.repair.events import RepairCompletedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		order = session.get(RepairOrder, order_id)
		if order is None:
			raise RepairNotFoundError(f"RepairOrder {order_id} not found")

		allowed = {"DIAGNOSING", "AWAITING_PARTS", "IN_REPAIR", "QC"}
		if order.status not in allowed:
			raise RepairStateError(
				f"Cannot complete repair for order in status {order.status!r}"
			)

		if actual_cost_cents is not None:
			assert actual_cost_cents >= 0, "actual_cost_cents must be non-negative"

		now = _now()
		order.assigned_technician_id = technician_id
		if actual_cost_cents is not None:
			order.actual_cost_cents = actual_cost_cents
		if parts_used is not None:
			order.parts_used = parts_used
		order.status = "READY_FOR_PICKUP"
		order.completed_at = now
		order.updated_at = now
		session.flush()

		emit_event(
			RepairCompletedEvent(
				aggregate_id=order.id,
				aggregate_type="RepairOrder",
				order_id=order.id,
				technician_id=technician_id,
				actual_cost_cents=actual_cost_cents or 0,
				tenant_id=order.tenant_id,
			),
			session,
		)
		log.info(
			"RepairService.complete_repair: order=%s actual=%s¢ status→READY_FOR_PICKUP",
			order_id, actual_cost_cents,
		)
		return order

	# ------------------------------------------------------------------
	# 5. return_to_customer
	# ------------------------------------------------------------------

	@staticmethod
	def return_to_customer(
		order_id: str,
		session: Any,
	) -> Any:
		"""Mark the unit as returned to the customer.

		Advances READY_FOR_PICKUP → RETURNED.
		Emits RepairReturnedToCustomerEvent.

		Returns:
			RepairOrder — flushed but not committed.
		"""
		from pgappforge.plugins.erp.operations.repair.models import RepairOrder
		from pgappforge.plugins.erp.operations.repair.events import RepairReturnedToCustomerEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		order = session.get(RepairOrder, order_id)
		if order is None:
			raise RepairNotFoundError(f"RepairOrder {order_id} not found")
		if order.status != "READY_FOR_PICKUP":
			raise RepairStateError(
				f"Cannot return order in status {order.status!r}; expected READY_FOR_PICKUP"
			)

		now = _now()
		order.status = "RETURNED"
		order.returned_at = now
		order.updated_at = now
		session.flush()

		emit_event(
			RepairReturnedToCustomerEvent(
				aggregate_id=order.id,
				aggregate_type="RepairOrder",
				order_id=order.id,
				customer_id=order.customer_id or "",
				return_date=now.date().isoformat(),
				tenant_id=order.tenant_id,
			),
			session,
		)
		log.info("RepairService.return_to_customer: order=%s → RETURNED", order_id)
		return order

	# ------------------------------------------------------------------
	# 6. create_warranty_claim
	# ------------------------------------------------------------------

	@staticmethod
	def create_warranty_claim(
		product_name: str,
		serial_number: str | None,
		customer_name: str,
		claim_description: str,
		tenant_id: str,
		session: Any,
		*,
		customer_email: str | None = None,
		purchase_date: Any | None = None,
		warranty_expiry_date: Any | None = None,
		repair_order_id: str | None = None,
	) -> Any:
		"""Open a new warranty claim.

		Emits WarrantyClaimCreatedEvent.

		Returns:
			WarrantyClaim — flushed but not committed.
		"""
		from pgappforge.plugins.erp.operations.repair.models import WarrantyClaim
		from pgappforge.plugins.erp.operations.repair.events import WarrantyClaimCreatedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		assert product_name, "product_name is required"
		assert customer_name, "customer_name is required"
		assert claim_description, "claim_description is required"
		assert tenant_id, "tenant_id is required"

		claim = WarrantyClaim(
			tenant_id=tenant_id,
			repair_order_id=repair_order_id,
			product_name=product_name,
			serial_number=serial_number,
			customer_name=customer_name,
			customer_email=customer_email,
			purchase_date=purchase_date,
			warranty_expiry_date=warranty_expiry_date,
			claim_description=claim_description,
			status="OPEN",
		)
		session.add(claim)
		session.flush()

		emit_event(
			WarrantyClaimCreatedEvent(
				aggregate_id=claim.id,
				aggregate_type="WarrantyClaim",
				claim_id=claim.id,
				order_id=repair_order_id or "",
				serial_number=serial_number or "",
				tenant_id=tenant_id,
			),
			session,
		)
		log.info(
			"RepairService.create_warranty_claim: %s product=%r tenant=%s",
			claim.id, product_name, tenant_id,
		)
		return claim

	# ------------------------------------------------------------------
	# 7. cancel_order
	# ------------------------------------------------------------------

	@staticmethod
	def cancel_order(
		order_id: str,
		session: Any,
		*,
		reason: str | None = None,
	) -> Any:
		"""Cancel a repair order.

		Only orders in status RECEIVED | DIAGNOSING | AWAITING_PARTS can be cancelled.

		Returns:
			RepairOrder — flushed but not committed.
		"""
		from pgappforge.plugins.erp.operations.repair.models import RepairOrder

		order = session.get(RepairOrder, order_id)
		if order is None:
			raise RepairNotFoundError(f"RepairOrder {order_id} not found")

		cancellable = {"RECEIVED", "DIAGNOSING", "AWAITING_PARTS"}
		if order.status not in cancellable:
			raise RepairStateError(
				f"Cannot cancel order in status {order.status!r}"
			)

		now = _now()
		order.status = "CANCELLED"
		if reason:
			order.notes = f"{order.notes or ''}\nCancelled: {reason}".strip()
		order.updated_at = now
		session.flush()

		log.info("RepairService.cancel_order: order=%s → CANCELLED reason=%r", order_id, reason)
		return order


__all__ = [
	"RepairService",
	"RepairServiceError",
	"RepairNotFoundError",
	"RepairStateError",
]
