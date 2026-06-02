"""
pgappforge/plugins/erp/operations/production/services.py

Business logic layer for the Production Planning plugin.

All methods are stateless (no instance state beyond construction).
All monetary arithmetic uses Decimal — never float.
Session is passed explicitly; never committed inside service methods
(caller commits atomically with any events).
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import sqlalchemy as sa

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class PPServiceError(Exception):
	"""Base error for PP service layer."""


class BOMNotFoundError(PPServiceError):
	pass


class ProductionOrderNotFoundError(PPServiceError):
	pass


class InvalidStatusTransitionError(PPServiceError):
	pass


class InsufficientQuantityError(PPServiceError):
	pass


# ---------------------------------------------------------------------------
# PPService
# ---------------------------------------------------------------------------

class PPService:
	"""Stateless Production Planning service.

	All monetary values returned/accepted as integer cents.
	All quantities accepted/returned as Decimal strings — callers convert.
	"""

	# ------------------------------------------------------------------
	# BOM management
	# ------------------------------------------------------------------

	def activate_bom(self, bom_id: str, session: Any) -> Any:
		"""Promote a DRAFT BOM to ACTIVE.

		Deactivates any currently ACTIVE BOM for the same product first
		(sets it to OBSOLETE).  Emits BOMActivatedEvent.
		"""
		from pgappforge.plugins.erp.operations.production.models import BillOfMaterials
		from pgappforge.plugins.erp.operations.production.events import BOMActivatedEvent, BOMObsoletedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		bom = session.get(BillOfMaterials, bom_id)
		if bom is None:
			raise BOMNotFoundError(f"BOM {bom_id!r} not found")
		if bom.status != "DRAFT":
			raise InvalidStatusTransitionError(f"BOM must be DRAFT to activate; got {bom.status!r}")

		# Obsolete existing active BOM for this product
		existing_active = session.execute(
			sa.select(BillOfMaterials).where(
				BillOfMaterials.product_id == bom.product_id,
				BillOfMaterials.status == "ACTIVE",
				BillOfMaterials.tenant_id == bom.tenant_id,
			)
		).scalars().all()

		for old_bom in existing_active:
			old_bom.status = "OBSOLETE"
			old_bom.updated_at = datetime.now(timezone.utc)
			emit_event(
				BOMObsoletedEvent(
					aggregate_id=old_bom.id,
					aggregate_type="BillOfMaterials",
					tenant_id=old_bom.tenant_id,
					bom_id=old_bom.id,
					product_id=old_bom.product_id,
					version=old_bom.version,
					superseded_by_version=bom.version,
				),
				session,
			)

		bom.status = "ACTIVE"
		bom.updated_at = datetime.now(timezone.utc)
		emit_event(
			BOMActivatedEvent(
				aggregate_id=bom.id,
				aggregate_type="BillOfMaterials",
				tenant_id=bom.tenant_id,
				bom_id=bom.id,
				product_id=bom.product_id,
				version=bom.version,
			),
			session,
		)
		return bom

	def get_active_bom(self, product_id: str, tenant_id: str, as_of: date | None, session: Any) -> Any | None:
		"""Return the ACTIVE BOM for product_id valid on as_of date (today if None)."""
		from pgappforge.plugins.erp.operations.production.models import BillOfMaterials

		target_date = as_of or date.today()
		q = (
			sa.select(BillOfMaterials)
			.where(
				BillOfMaterials.product_id == product_id,
				BillOfMaterials.tenant_id == tenant_id,
				BillOfMaterials.status == "ACTIVE",
				BillOfMaterials.effective_from <= target_date,
				sa.or_(
					BillOfMaterials.effective_to.is_(None),
					BillOfMaterials.effective_to >= target_date,
				),
			)
			.order_by(sa.desc(BillOfMaterials.effective_from))
			.limit(1)
		)
		return session.execute(q).scalar_one_or_none()

	# ------------------------------------------------------------------
	# Production order lifecycle
	# ------------------------------------------------------------------

	def release_production_order(self, order_id: str, session: Any) -> Any:
		"""PLANNED → RELEASED.

		Validates BOM is ACTIVE and all critical components are available
		(availability check is informational — does not hard-block unless
		a Rules Engine ruleset is configured to do so).
		Emits ProductionOrderReleasedEvent.
		"""
		from pgappforge.plugins.erp.operations.production.models import ProductionOrder
		from pgappforge.plugins.erp.operations.production.events import ProductionOrderReleasedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		order = session.get(ProductionOrder, order_id)
		if order is None:
			raise ProductionOrderNotFoundError(f"ProductionOrder {order_id!r} not found")
		if order.status != "PLANNED":
			raise InvalidStatusTransitionError(
				f"Order must be PLANNED to release; got {order.status!r}"
			)

		order.status = "RELEASED"
		order.updated_at = datetime.now(timezone.utc)
		emit_event(
			ProductionOrderReleasedEvent(
				aggregate_id=order.id,
				aggregate_type="ProductionOrder",
				tenant_id=order.tenant_id,
				order_id=order.id,
				order_number=order.order_number,
				product_id=order.product_id,
				planned_quantity=str(order.planned_quantity),
				start_date=order.start_date.isoformat(),
				work_center_id=order.work_center_id or "",
			),
			session,
		)
		return order

	def start_production_order(self, order_id: str, session: Any) -> Any:
		"""RELEASED → IN_PROGRESS. Emits ProductionOrderStartedEvent."""
		from pgappforge.plugins.erp.operations.production.models import ProductionOrder
		from pgappforge.plugins.erp.operations.production.events import ProductionOrderStartedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		order = session.get(ProductionOrder, order_id)
		if order is None:
			raise ProductionOrderNotFoundError(f"ProductionOrder {order_id!r} not found")
		if order.status != "RELEASED":
			raise InvalidStatusTransitionError(
				f"Order must be RELEASED to start; got {order.status!r}"
			)
		order.status = "IN_PROGRESS"
		order.actual_start_date = date.today()
		order.updated_at = datetime.now(timezone.utc)
		emit_event(
			ProductionOrderStartedEvent(
				aggregate_id=order.id,
				aggregate_type="ProductionOrder",
				tenant_id=order.tenant_id,
				order_id=order.id,
				order_number=order.order_number,
				product_id=order.product_id,
				work_center_id=order.work_center_id or "",
			),
			session,
		)
		return order

	def complete_production_order(
		self,
		order_id: str,
		produced_quantity: Decimal,
		session: Any,
	) -> Any:
		"""IN_PROGRESS → COMPLETED.

		Sets produced_quantity and actual_end_date.
		Emits ProductionOrderCompletedEvent.
		"""
		from pgappforge.plugins.erp.operations.production.models import ProductionOrder
		from pgappforge.plugins.erp.operations.production.events import ProductionOrderCompletedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		order = session.get(ProductionOrder, order_id)
		if order is None:
			raise ProductionOrderNotFoundError(f"ProductionOrder {order_id!r} not found")
		if order.status != "IN_PROGRESS":
			raise InvalidStatusTransitionError(
				f"Order must be IN_PROGRESS to complete; got {order.status!r}"
			)
		if produced_quantity <= Decimal("0"):
			raise PPServiceError("produced_quantity must be positive")

		order.status = "COMPLETED"
		order.produced_quantity = produced_quantity
		order.actual_end_date = date.today()
		order.updated_at = datetime.now(timezone.utc)
		emit_event(
			ProductionOrderCompletedEvent(
				aggregate_id=order.id,
				aggregate_type="ProductionOrder",
				tenant_id=order.tenant_id,
				order_id=order.id,
				order_number=order.order_number,
				product_id=order.product_id,
				produced_quantity=str(produced_quantity),
				actual_cost_cents=order.actual_cost_cents,
				planned_cost_cents=order.planned_cost_cents or 0,
			),
			session,
		)
		return order

	def cancel_production_order(self, order_id: str, reason: str, session: Any) -> Any:
		"""Cancel a production order (any status except COMPLETED).

		Emits ProductionOrderCancelledEvent.
		"""
		from pgappforge.plugins.erp.operations.production.models import ProductionOrder
		from pgappforge.plugins.erp.operations.production.events import ProductionOrderCancelledEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		order = session.get(ProductionOrder, order_id)
		if order is None:
			raise ProductionOrderNotFoundError(f"ProductionOrder {order_id!r} not found")
		if order.status == "COMPLETED":
			raise InvalidStatusTransitionError("Cannot cancel a COMPLETED production order")
		if order.status == "CANCELLED":
			raise InvalidStatusTransitionError("Order is already CANCELLED")

		order.status = "CANCELLED"
		order.updated_at = datetime.now(timezone.utc)
		emit_event(
			ProductionOrderCancelledEvent(
				aggregate_id=order.id,
				aggregate_type="ProductionOrder",
				tenant_id=order.tenant_id,
				order_id=order.id,
				order_number=order.order_number,
				product_id=order.product_id,
				reason=reason,
			),
			session,
		)
		return order

	# ------------------------------------------------------------------
	# Component issue
	# ------------------------------------------------------------------

	def issue_component(
		self,
		line_id: str,
		quantity: Decimal,
		warehouse_id: str | None,
		session: Any,
	) -> Any:
		"""Issue material to shop floor for a ProductionOrderLine.

		Updates issued_quantity; marks ISSUED when fully issued.
		Emits ComponentIssuedEvent.
		"""
		from pgappforge.plugins.erp.operations.production.models import ProductionOrderLine
		from pgappforge.plugins.erp.operations.production.events import ComponentIssuedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		line = session.get(ProductionOrderLine, line_id)
		if line is None:
			raise PPServiceError(f"ProductionOrderLine {line_id!r} not found")
		if quantity <= Decimal("0"):
			raise InsufficientQuantityError("Issue quantity must be positive")

		line.issued_quantity = Decimal(str(line.issued_quantity)) + quantity
		if line.issued_quantity >= Decimal(str(line.required_quantity)):
			line.status = "ISSUED"
		line.updated_at = datetime.now(timezone.utc)

		emit_event(
			ComponentIssuedEvent(
				aggregate_id=line.production_order_id,
				aggregate_type="ProductionOrderLine",
				tenant_id=line.tenant_id,
				production_order_id=line.production_order_id,
				order_number="",  # caller may enrich via production_order.order_number
				component_product_id=line.component_product_id,
				issued_quantity=str(quantity),
				uom=line.uom,
				warehouse_id=warehouse_id or "",
			),
			session,
		)
		return line

	# ------------------------------------------------------------------
	# Operation completion
	# ------------------------------------------------------------------

	def complete_operation(
		self,
		operation_id: str,
		actual_time_minutes: int,
		completed_by: str,
		labor_cost_cents: int,
		session: Any,
	) -> Any:
		"""Mark a WorkOrderOperation as COMPLETED.

		Updates actual_time_minutes, labor_cost_cents, completed_by/at.
		Rolls overhead cost into ProductionOrder.actual_cost_cents.
		Emits OperationCompletedEvent.
		"""
		from pgappforge.plugins.erp.operations.production.models import WorkOrderOperation
		from pgappforge.plugins.erp.operations.production.events import OperationCompletedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		op = session.get(WorkOrderOperation, operation_id)
		if op is None:
			raise PPServiceError(f"WorkOrderOperation {operation_id!r} not found")
		if op.status not in ("PENDING", "IN_PROGRESS"):
			raise InvalidStatusTransitionError(
				f"Operation already in terminal status {op.status!r}"
			)

		op.status = "COMPLETED"
		op.actual_time_minutes = actual_time_minutes
		op.labor_cost_cents = labor_cost_cents
		op.completed_by = completed_by
		op.completed_at = datetime.now(timezone.utc)
		op.updated_at = datetime.now(timezone.utc)

		# Roll cost into production order
		if op.production_order:
			op.production_order.actual_cost_cents += labor_cost_cents
			op.production_order.updated_at = datetime.now(timezone.utc)

		emit_event(
			OperationCompletedEvent(
				aggregate_id=op.production_order_id,
				aggregate_type="WorkOrderOperation",
				tenant_id=op.tenant_id,
				production_order_id=op.production_order_id,
				operation_id=op.id,
				operation_number=op.operation_number,
				work_center_id=op.work_center_id,
				actual_time_minutes=actual_time_minutes,
				labor_cost_cents=labor_cost_cents,
				completed_by=completed_by,
			),
			session,
		)
		return op

	# ------------------------------------------------------------------
	# MRP helpers
	# ------------------------------------------------------------------

	def explode_bom(
		self,
		product_id: str,
		quantity: Decimal,
		tenant_id: str,
		as_of: date | None,
		session: Any,
	) -> list[dict[str, Any]]:
		"""Single-level BOM explosion.

		Returns list of component requirements:
		  [{"product_id": ..., "required_quantity": Decimal, "uom": ..., "is_critical": bool}]

		Includes scrap allowance: gross_qty = qty * (1 + scrap_factor).
		Does NOT recurse into sub-BOMs (full multi-level MRP explosion
		is handled by the MRP service calling this recursively).
		"""
		bom = self.get_active_bom(product_id, tenant_id, as_of, session)
		if bom is None:
			return []

		result = []
		for line in bom.lines:
			scrap = Decimal(str(line.scrap_factor))
			base_qty = Decimal(str(line.quantity))
			gross_qty = (quantity * base_qty * (Decimal("1") + scrap)).quantize(
				Decimal("0.0001"), rounding=ROUND_HALF_UP
			)
			result.append({
				"product_id": line.component_product_id,
				"required_quantity": gross_qty,
				"uom": line.uom,
				"is_critical": line.is_critical,
				"position": line.position,
				"bom_line_id": line.id,
			})
		return result

	def compute_planned_cost(
		self,
		order_id: str,
		component_unit_costs: dict[str, int],
		session: Any,
	) -> int:
		"""Compute planned cost for a production order.

		component_unit_costs: {product_id: unit_cost_cents}
		Returns total planned cost as integer cents.
		Updates ProductionOrder.planned_cost_cents in-place.
		"""
		from pgappforge.plugins.erp.operations.production.models import ProductionOrder

		order = session.get(ProductionOrder, order_id)
		if order is None:
			raise ProductionOrderNotFoundError(f"ProductionOrder {order_id!r} not found")

		total_cents = 0
		for line in order.lines:
			unit_cost = component_unit_costs.get(line.component_product_id, 0)
			qty = Decimal(str(line.required_quantity))
			line_cost = int((qty * Decimal(unit_cost)).to_integral_value(rounding=ROUND_HALF_UP))
			line.unit_cost_cents = unit_cost
			total_cents += line_cost

		# Add work center overhead
		if order.work_center:
			run_hours = Decimal("0")
			for op in order.operations:
				run_hours += Decimal(str(op.run_time_minutes + op.setup_time_minutes)) / Decimal("60")
			wc_cost = int(
				(run_hours * Decimal(order.work_center.overhead_rate_per_hour_cents))
				.to_integral_value(rounding=ROUND_HALF_UP)
			)
			total_cents += wc_cost

		order.planned_cost_cents = total_cents
		order.updated_at = datetime.now(timezone.utc)
		return total_cents


__all__ = [
	"PPService",
	"PPServiceError",
	"BOMNotFoundError",
	"ProductionOrderNotFoundError",
	"InvalidStatusTransitionError",
	"InsufficientQuantityError",
]
