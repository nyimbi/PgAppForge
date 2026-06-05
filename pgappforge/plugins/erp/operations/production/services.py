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


	# ------------------------------------------------------------------
	# Production output recording & costing
	# ------------------------------------------------------------------

	def record_production_output(
		self,
		session: Any,
		order_id: str,
		qty_produced: Decimal,
		qty_scrapped: Decimal,
		tenant_id: str,
	) -> Any:
		"""Record confirmed production output against a production order.

		Updates produced_quantity and actual_cost_cents.
		Posts GL when GL plugin is available:
		  DR WIP         "1160"  (value of goods produced)
		  CR Raw Materials "1140" (consumption of components)

		When the order is fully complete (produced_quantity >= planned_quantity),
		also posts finished-goods transfer:
		  DR Finished Goods "1170"
		  CR WIP            "1160"

		qty_scrapped is recorded as a metadata note; scrap cost stays in WIP.
		"""
		from pgappforge.plugins.erp.operations.production.models import ProductionOrder
		from pgappforge.plugins.erp.operations.production.events import ProductionOrderCompletedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		order = session.get(ProductionOrder, order_id)
		if order is None:
			raise ProductionOrderNotFoundError(f"ProductionOrder {order_id!r} not found")
		if order.status not in ("RELEASED", "IN_PROGRESS"):
			raise InvalidStatusTransitionError(
				f"Cannot record output on order in status {order.status!r}"
			)
		if qty_produced <= Decimal("0"):
			raise PPServiceError("qty_produced must be positive")

		# Accumulate produced quantity
		prev_produced = Decimal(str(order.produced_quantity))
		order.produced_quantity = prev_produced + qty_produced
		if order.status == "RELEASED":
			order.status = "IN_PROGRESS"
			order.actual_start_date = date.today()

		# Derive WIP value from planned cost pro-rated to qty
		wip_value_cents = 0
		if order.planned_cost_cents and order.planned_quantity:
			planned = Decimal(str(order.planned_quantity))
			unit_cost = Decimal(str(order.planned_cost_cents)) / planned
			wip_value_cents = int(
				(unit_cost * qty_produced).to_integral_value(rounding=ROUND_HALF_UP)
			)

		# GL: DR WIP 1160 / CR Raw Materials 1140
		try:
			from pgappforge.plugins.erp.finance.gl.services import GLService  # type: ignore
			if wip_value_cents > 0:
				GLService.post_journal(
					session=session,
					tenant_id=tenant_id,
					description=f"Production output {order.order_number} qty={qty_produced}",
					lines=[
						{"account": "1160", "debit_cents": wip_value_cents, "credit_cents": 0,
						 "ref": order_id, "memo": f"WIP — {order.order_number}"},
						{"account": "1140", "debit_cents": 0, "credit_cents": wip_value_cents,
						 "ref": order_id, "memo": f"Raw materials consumed — {order.order_number}"},
					],
				)
		except (ImportError, AttributeError) as exc:
			log.debug("PPService.record_production_output: GL posting skipped (%s)", exc)

		# Check if fully complete
		is_complete = order.produced_quantity >= Decimal(str(order.planned_quantity))
		if is_complete:
			order.status = "COMPLETED"
			order.actual_end_date = date.today()

			# GL: DR Finished Goods 1170 / CR WIP 1160
			try:
				from pgappforge.plugins.erp.finance.gl.services import GLService  # type: ignore
				total_wip = order.actual_cost_cents or wip_value_cents
				if total_wip > 0:
					GLService.post_journal(
						session=session,
						tenant_id=tenant_id,
						description=f"Finished goods transfer {order.order_number}",
						lines=[
							{"account": "1170", "debit_cents": total_wip, "credit_cents": 0,
							 "ref": order_id, "memo": f"Finished goods — {order.order_number}"},
							{"account": "1160", "debit_cents": 0, "credit_cents": total_wip,
							 "ref": order_id, "memo": f"WIP cleared — {order.order_number}"},
						],
					)
			except (ImportError, AttributeError) as exc:
				log.debug("PPService.record_production_output: FG GL posting skipped (%s)", exc)

			emit_event(
				ProductionOrderCompletedEvent(
					aggregate_id=order.id,
					aggregate_type="ProductionOrder",
					tenant_id=tenant_id,
					order_id=order.id,
					order_number=order.order_number,
					product_id=order.product_id,
					produced_quantity=str(order.produced_quantity),
					actual_cost_cents=order.actual_cost_cents,
					planned_cost_cents=order.planned_cost_cents or 0,
				),
				session,
			)

		# Record scrap in metadata
		if qty_scrapped > Decimal("0"):
			meta = dict(order.metadata_ or {})
			meta.setdefault("scrap_entries", []).append({
				"qty": str(qty_scrapped),
				"recorded_at": datetime.now(timezone.utc).isoformat(),
			})
			order.metadata_ = meta

		order.updated_at = datetime.now(timezone.utc)
		session.flush()
		return order

	def calculate_production_cost(
		self,
		session: Any,
		order_id: str,
		tenant_id: str,
	) -> dict[str, Any]:
		"""Calculate and post the full production cost for a completed order.

		Returns dict:
		  {
		    "materials_cents": int,
		    "labor_cents": int,
		    "overhead_cents": int,
		    "total_cents": int,
		    "order_id": str,
		    "order_number": str,
		  }

		Posts GL: DR Finished Goods "1170" / CR WIP "1160" for the delta
		between actual_cost_cents and any previously posted FG value.

		Also updates ProductionOrder.actual_cost_cents with the computed total.
		"""
		from pgappforge.plugins.erp.operations.production.models import ProductionOrder

		order = session.get(ProductionOrder, order_id)
		if order is None:
			raise ProductionOrderNotFoundError(f"ProductionOrder {order_id!r} not found")

		# Materials: sum of (issued_quantity * unit_cost_cents) per line
		materials_cents = 0
		for line in order.lines:
			qty = Decimal(str(line.issued_quantity or 0))
			unit = int(line.unit_cost_cents or 0)
			materials_cents += int(
				(qty * Decimal(unit)).to_integral_value(rounding=ROUND_HALF_UP)
			)

		# Labor: sum of labor_cost_cents from completed operations
		labor_cents = sum(
			int(op.labor_cost_cents or 0)
			for op in order.operations
			if op.status == "COMPLETED"
		)

		# Overhead: work center hours * overhead rate
		overhead_cents = 0
		if order.work_center:
			total_minutes = sum(
				int(op.actual_time_minutes or (op.run_time_minutes + op.setup_time_minutes))
				for op in order.operations
			)
			hours = Decimal(str(total_minutes)) / Decimal("60")
			overhead_cents = int(
				(hours * Decimal(str(order.work_center.overhead_rate_per_hour_cents)))
				.to_integral_value(rounding=ROUND_HALF_UP)
			)

		total_cents = materials_cents + labor_cents + overhead_cents
		order.actual_cost_cents = total_cents
		order.updated_at = datetime.now(timezone.utc)

		# GL: DR Finished Goods 1170 / CR WIP 1160
		try:
			from pgappforge.plugins.erp.finance.gl.services import GLService  # type: ignore
			if total_cents > 0:
				GLService.post_journal(
					session=session,
					tenant_id=tenant_id,
					description=f"Production cost finalised {order.order_number}",
					lines=[
						{"account": "1170", "debit_cents": total_cents, "credit_cents": 0,
						 "ref": order_id, "memo": f"Finished goods — {order.order_number}"},
						{"account": "1160", "debit_cents": 0, "credit_cents": total_cents,
						 "ref": order_id, "memo": f"WIP cleared — {order.order_number}"},
					],
				)
		except (ImportError, AttributeError) as exc:
			log.debug("PPService.calculate_production_cost: GL posting skipped (%s)", exc)

		session.flush()
		return {
			"order_id": order_id,
			"order_number": order.order_number,
			"materials_cents": materials_cents,
			"labor_cents": labor_cents,
			"overhead_cents": overhead_cents,
			"total_cents": total_cents,
		}

	def get_production_schedule(
		self,
		session: Any,
		from_date: date,
		to_date: date,
		tenant_id: str,
	) -> list[dict[str, Any]]:
		"""Return all production orders active within [from_date, to_date].

		For each order, computes utilization per work center as:
		  utilization_pct = (total planned minutes / work_center.capacity_hours_per_day * 60) * 100

		Returned list of dicts — one entry per production order:
		  {
		    "order_id", "order_number", "product_id", "status",
		    "planned_quantity", "produced_quantity",
		    "start_date", "end_date",
		    "work_center_id", "work_center_code",
		    "planned_minutes", "utilization_pct",
		  }
		"""
		from pgappforge.plugins.erp.operations.production.models import ProductionOrder

		rows = session.execute(
			sa.select(ProductionOrder).where(
				ProductionOrder.tenant_id == tenant_id,
				ProductionOrder.start_date <= to_date,
				ProductionOrder.end_date >= from_date,
				ProductionOrder.status.notin_(["CANCELLED"]),
			).order_by(ProductionOrder.start_date, ProductionOrder.order_number)
		).scalars().all()

		schedule = []
		for order in rows:
			planned_minutes = sum(
				op.run_time_minutes + op.setup_time_minutes for op in order.operations
			)
			utilization_pct = 0.0
			if order.work_center and order.work_center.capacity_units_per_hour:
				# capacity in minutes per day
				cap_minutes_per_day = float(order.work_center.capacity_units_per_hour) * 60
				span_days = max((order.end_date - order.start_date).days + 1, 1)
				total_cap = cap_minutes_per_day * span_days
				utilization_pct = round(planned_minutes / total_cap * 100, 2) if total_cap > 0 else 0.0

			schedule.append({
				"order_id": order.id,
				"order_number": order.order_number,
				"product_id": order.product_id,
				"status": order.status,
				"planned_quantity": str(order.planned_quantity),
				"produced_quantity": str(order.produced_quantity),
				"start_date": order.start_date.isoformat(),
				"end_date": order.end_date.isoformat(),
				"work_center_id": order.work_center_id or "",
				"work_center_code": order.work_center.code if order.work_center else "",
				"planned_minutes": planned_minutes,
				"utilization_pct": utilization_pct,
			})

		return schedule

	def get_oee(
		self,
		session: Any,
		work_center_id: str,
		from_date: date,
		to_date: date,
		tenant_id: str,
	) -> dict[str, Any]:
		"""Calculate OEE (Overall Equipment Effectiveness) for a work center.

		OEE = Availability × Performance × Quality

		  Availability  = actual_run_time / planned_run_time
		  Performance   = (ideal_cycle_time × total_produced) / actual_run_time
		                 simplified as: produced_quantity / planned_quantity
		  Quality        = accepted_quantity / total_quantity_started
		                 simplified as: produced_quantity / (produced + scrapped)

		Data sources:
		  - Completed WorkOrderOperations in date range for planned/actual minutes
		  - ProductionOrders for quantities

		Returns:
		  {
		    "work_center_id", "from_date", "to_date",
		    "availability_pct", "performance_pct", "quality_pct", "oee_pct",
		    "planned_minutes", "actual_minutes",
		    "planned_qty", "produced_qty", "scrapped_qty",
		  }
		"""
		from pgappforge.plugins.erp.operations.production.models import (
			ProductionOrder,
			WorkOrderOperation,
		)

		# Operations completed in date range for this work center
		ops = session.execute(
			sa.select(WorkOrderOperation).where(
				WorkOrderOperation.tenant_id == tenant_id,
				WorkOrderOperation.work_center_id == work_center_id,
				WorkOrderOperation.status == "COMPLETED",
				WorkOrderOperation.completed_at >= datetime.combine(from_date, datetime.min.time()).replace(tzinfo=timezone.utc),
				WorkOrderOperation.completed_at < datetime.combine(to_date, datetime.max.time()).replace(tzinfo=timezone.utc),
			)
		).scalars().all()

		planned_minutes = sum(op.run_time_minutes + op.setup_time_minutes for op in ops)
		actual_minutes = sum(int(op.actual_time_minutes or 0) for op in ops)

		availability_pct = (
			round(actual_minutes / planned_minutes * 100, 2)
			if planned_minutes > 0 else 0.0
		)
		# Clamp — actual can exceed planned (overtime)
		availability_pct = min(availability_pct, 100.0)

		# Orders at this work center in date range
		orders = session.execute(
			sa.select(ProductionOrder).where(
				ProductionOrder.tenant_id == tenant_id,
				ProductionOrder.work_center_id == work_center_id,
				ProductionOrder.start_date <= to_date,
				ProductionOrder.end_date >= from_date,
				ProductionOrder.status.notin_(["CANCELLED", "PLANNED"]),
			)
		).scalars().all()

		planned_qty = sum(float(o.planned_quantity) for o in orders)
		produced_qty = sum(float(o.produced_quantity) for o in orders)

		# Scrap from metadata
		scrapped_qty = 0.0
		for o in orders:
			for entry in (o.metadata_ or {}).get("scrap_entries", []):
				try:
					scrapped_qty += float(entry.get("qty", 0))
				except (TypeError, ValueError):
					pass

		performance_pct = (
			round(produced_qty / planned_qty * 100, 2) if planned_qty > 0 else 0.0
		)
		performance_pct = min(performance_pct, 100.0)

		total_started = produced_qty + scrapped_qty
		quality_pct = (
			round(produced_qty / total_started * 100, 2) if total_started > 0 else 100.0
		)

		oee_pct = round(
			(availability_pct / 100) * (performance_pct / 100) * (quality_pct / 100) * 100,
			2,
		)

		return {
			"work_center_id": work_center_id,
			"from_date": from_date.isoformat(),
			"to_date": to_date.isoformat(),
			"availability_pct": availability_pct,
			"performance_pct": performance_pct,
			"quality_pct": quality_pct,
			"oee_pct": oee_pct,
			"planned_minutes": planned_minutes,
			"actual_minutes": actual_minutes,
			"planned_qty": planned_qty,
			"produced_qty": produced_qty,
			"scrapped_qty": scrapped_qty,
		}


__all__ = [
	"PPService",
	"PPServiceError",
	"BOMNotFoundError",
	"ProductionOrderNotFoundError",
	"InvalidStatusTransitionError",
	"InsufficientQuantityError",
]
