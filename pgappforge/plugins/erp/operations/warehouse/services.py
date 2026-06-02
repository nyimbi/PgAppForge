"""
pgappforge/plugins/erp/operations/warehouse/services.py

WarehouseService — stateless business logic for the Warehouse Management plugin.

Orchestrates pick, putaway, and stock count workflows.
Delegates actual stock movements to InventoryService.

Public API:
  create_picklist(order_id, order_type, lines, warehouse_id, session) -> PickList
  assign_picklist(picklist_id, user_id, session)                      -> PickList
  record_pick(picklist_id, line_id, qty_picked, session)              -> PickListLine
  complete_picklist(picklist_id, session)                             -> PickList
  create_putaway_task(grn_id, product_id, qty, session)               -> PutawayTask
  complete_putaway(putaway_task_id, actual_location_id, session)      -> PutawayTask
  suggest_putaway_location(product_id, warehouse_id, session)         -> str|None
  start_stock_count(warehouse_id, count_type, session)                -> StockCount
  record_count(stock_count_id, line_id, counted_qty, session)         -> StockCountLine
  complete_stock_count(stock_count_id, session)                       -> StockCount
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

import sqlalchemy as sa

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class WarehouseServiceError(Exception):
	"""Base domain error for WMS operations."""


class PickListNotFoundError(WarehouseServiceError):
	pass


class PutawayNotFoundError(WarehouseServiceError):
	pass


class StockCountNotFoundError(WarehouseServiceError):
	pass


class InvalidStatusTransitionError(WarehouseServiceError):
	pass


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _d(value: Any) -> Decimal:
	if isinstance(value, Decimal):
		return value
	return Decimal(str(value))


def _now() -> datetime:
	return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# WarehouseService
# ---------------------------------------------------------------------------

class WarehouseService:
	"""Stateless WMS domain service.

	All public methods accept an explicit SQLAlchemy Session.
	No Flask context assumed.
	"""

	# ------------------------------------------------------------------
	# PickList management
	# ------------------------------------------------------------------

	def create_picklist(
		self,
		order_id: str,
		order_type: str,
		lines: list[dict],
		warehouse_id: str,
		session: Any,
		tenant_id: str = "",
		priority: int = 5,
		due_by: datetime | None = None,
	) -> Any:
		"""Create a PickList for an outbound order.

		lines format:
		  [{"product_id": str, "quantity_requested": str/Decimal,
		    "location_id": str|None, "lot_number": str|None,
		    "serial_number": str|None}, ...]

		Emits PickListCreatedEvent.

		Returns:
			PickList instance (not committed).
		"""
		from pgappforge.plugins.erp.operations.warehouse.models import PickList, PickListLine
		from pgappforge.plugins.erp.operations.warehouse.events import PickListCreatedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		if order_type not in ("SALES_ORDER", "TRANSFER", "PRODUCTION"):
			raise WarehouseServiceError(f"Invalid order_type {order_type!r}")

		if not lines:
			raise WarehouseServiceError("PickList requires at least one line")

		pl = PickList(
			tenant_id=tenant_id,
			warehouse_id=warehouse_id,
			order_type=order_type,
			order_id=order_id,
			status="PENDING",
			priority=priority,
			due_by=due_by,
		)
		session.add(pl)
		session.flush()

		for line in lines:
			session.add(PickListLine(
				tenant_id=tenant_id,
				picklist_id=pl.id,
				product_id=str(line["product_id"]),
				location_id=str(line["location_id"]) if line.get("location_id") else None,
				quantity_requested=_d(line["quantity_requested"]),
				quantity_picked=Decimal("0"),
				lot_number=line.get("lot_number"),
				serial_number=line.get("serial_number"),
				status="PENDING",
			))

		emit_event(
			PickListCreatedEvent(
				aggregate_id=pl.id,
				aggregate_type="PickList",
				tenant_id=tenant_id,
				picklist_id=pl.id,
				warehouse_id=warehouse_id,
				order_type=order_type,
				order_id=order_id,
				line_count=len(lines),
				priority=priority,
			),
			session,
		)

		log.info(
			"WarehouseService.create_picklist: pl=%s order=%s type=%s lines=%d",
			pl.id, order_id, order_type, len(lines),
		)
		return pl

	def assign_picklist(self, picklist_id: str, user_id: str, session: Any) -> Any:
		"""Assign a PickList to a warehouse operative.

		Transitions status: PENDING → ASSIGNED.
		"""
		from pgappforge.plugins.erp.operations.warehouse.models import PickList

		pl = session.get(PickList, picklist_id)
		if pl is None:
			raise PickListNotFoundError(f"PickList {picklist_id!r} not found")
		if pl.status != "PENDING":
			raise InvalidStatusTransitionError(
				f"PickList {picklist_id!r} status={pl.status!r}; must be PENDING to assign"
			)

		pl.assigned_to = user_id
		pl.status = "ASSIGNED"
		pl.updated_at = _now()

		log.info("WarehouseService.assign_picklist: pl=%s user=%s", picklist_id, user_id)
		return pl

	def record_pick(
		self,
		picklist_id: str,
		line_id: str,
		qty_picked: Any,
		session: Any,
	) -> Any:
		"""Record quantity picked for a single PickListLine.

		Transitions PickList status to IN_PROGRESS if still ASSIGNED.
		Sets PickListLine.status:
		  PARTIAL   if qty_picked < quantity_requested
		  COMPLETED if qty_picked >= quantity_requested
		"""
		from pgappforge.plugins.erp.operations.warehouse.models import PickList, PickListLine

		pl = session.get(PickList, picklist_id)
		if pl is None:
			raise PickListNotFoundError(f"PickList {picklist_id!r} not found")
		if pl.status not in ("ASSIGNED", "IN_PROGRESS"):
			raise InvalidStatusTransitionError(
				f"PickList {picklist_id!r} must be ASSIGNED or IN_PROGRESS to record picks"
			)

		line = session.get(PickListLine, line_id)
		if line is None or str(line.picklist_id) != str(picklist_id):
			raise WarehouseServiceError(f"PickListLine {line_id!r} not found on picklist {picklist_id!r}")

		qty = _d(qty_picked)
		assert qty >= 0, "qty_picked must be non-negative"

		line.quantity_picked = qty
		if qty >= _d(line.quantity_requested):
			line.status = "COMPLETED"
		else:
			line.status = "PARTIAL"
		line.updated_at = _now()

		# Advance picklist to IN_PROGRESS
		if pl.status == "ASSIGNED":
			pl.status = "IN_PROGRESS"
			pl.updated_at = _now()

		return line

	def complete_picklist(self, picklist_id: str, session: Any) -> Any:
		"""Mark a PickList COMPLETED and delegate stock issuance to InventoryService.

		All lines must be COMPLETED or SKIPPED.
		Calls InventoryService.pick_and_ship().

		Returns:
			PickList with status=COMPLETED.
		"""
		from pgappforge.plugins.erp.operations.warehouse.models import PickList
		from pgappforge.plugins.erp.operations.inventory.services import InventoryService
		from pgappforge.plugins.erp.operations.warehouse.events import PickListCompletedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		pl = session.get(PickList, picklist_id)
		if pl is None:
			raise PickListNotFoundError(f"PickList {picklist_id!r} not found")
		if pl.status not in ("IN_PROGRESS", "ASSIGNED"):
			raise InvalidStatusTransitionError(
				f"PickList {picklist_id!r} must be IN_PROGRESS; got {pl.status!r}"
			)

		incomplete = [
			l for l in pl.lines
			if l.status not in ("COMPLETED", "SKIPPED")
			and _d(l.quantity_requested) > 0
		]
		if incomplete:
			raise WarehouseServiceError(
				f"PickList {picklist_id!r} has {len(incomplete)} incomplete line(s); "
				"complete or skip all lines before closing"
			)

		inv_svc = InventoryService()
		inv_svc.pick_and_ship(picklist_id, session)

		emit_event(
			PickListCompletedEvent(
				aggregate_id=picklist_id,
				aggregate_type="PickList",
				tenant_id=pl.tenant_id,
				picklist_id=picklist_id,
				warehouse_id=str(pl.warehouse_id),
				order_type=pl.order_type,
				order_id=str(pl.order_id),
				picked_by=str(pl.assigned_to) if pl.assigned_to else "",
			),
			session,
		)

		log.info("WarehouseService.complete_picklist: pl=%s", picklist_id)
		return pl

	# ------------------------------------------------------------------
	# Putaway management
	# ------------------------------------------------------------------

	def create_putaway_task(
		self,
		grn_id: str,
		product_id: str,
		quantity: Any,
		session: Any,
		warehouse_id: str = "",
		tenant_id: str = "",
		lot_number: str | None = None,
		expiry_date: Any = None,
	) -> Any:
		"""Create a PutawayTask for stock received on a GRN.

		Automatically suggests a putaway location based on product and
		warehouse location types.

		Returns:
			PutawayTask instance.
		"""
		from pgappforge.plugins.erp.operations.warehouse.models import PutawayTask

		suggested_loc = self.suggest_putaway_location(product_id, warehouse_id, session)

		task = PutawayTask(
			tenant_id=tenant_id,
			warehouse_id=warehouse_id,
			grn_id=grn_id,
			product_id=product_id,
			quantity=_d(quantity),
			lot_number=lot_number,
			expiry_date=expiry_date,
			suggested_location_id=suggested_loc,
			actual_location_id=None,
			status="PENDING",
		)
		session.add(task)
		session.flush()

		log.info(
			"WarehouseService.create_putaway_task: task=%s grn=%s product=%s qty=%s",
			task.id, grn_id, product_id, quantity,
		)
		return task

	def complete_putaway(
		self,
		putaway_task_id: str,
		actual_location_id: str,
		completed_by: str,
		session: Any,
	) -> Any:
		"""Complete a PutawayTask by recording the actual location.

		Creates a TRANSFER StockMovement from the RECEIVE staging location
		to actual_location_id directly (no monkey-patching).

		Emits PutawayCompletedEvent.
		"""
		from pgappforge.plugins.erp.operations.warehouse.models import PutawayTask
		from pgappforge.plugins.erp.operations.inventory.models import (
			WarehouseLocation, StockMovement, StockLevel,
		)
		from pgappforge.plugins.erp.operations.inventory.services import _cents, _now as _inv_now
		from pgappforge.plugins.erp.operations.inventory.events import StockTransferredEvent
		from pgappforge.plugins.erp.operations.warehouse.events import PutawayCompletedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event
		from decimal import Decimal as _D

		task = session.get(PutawayTask, putaway_task_id)
		if task is None:
			raise PutawayNotFoundError(f"PutawayTask {putaway_task_id!r} not found")
		if task.status not in ("PENDING", "IN_PROGRESS"):
			raise InvalidStatusTransitionError(
				f"PutawayTask {putaway_task_id!r} status={task.status!r}; cannot complete"
			)

		product_id = str(task.product_id)
		warehouse_id = str(task.warehouse_id)
		tenant_id = str(task.tenant_id)

		# Find RECEIVE staging location in this warehouse
		receive_loc = session.execute(
			sa.select(WarehouseLocation)
			.where(WarehouseLocation.warehouse_id == warehouse_id)
			.where(WarehouseLocation.location_type == "RECEIVE")
			.where(WarehouseLocation.is_active.is_(True))
			.limit(1)
		).scalar_one_or_none()

		from_loc_id = str(receive_loc.id) if receive_loc else None

		# Look up average cost for valuation
		sl = session.execute(
			sa.select(StockLevel)
			.where(StockLevel.product_id == product_id)
			.where(StockLevel.warehouse_id == warehouse_id)
			.where(StockLevel.tenant_id == tenant_id)
			.limit(1)
		).scalar_one_or_none()
		avg_cost = sl.average_cost_cents if sl else 0

		qty = _D(str(task.quantity))
		movement = StockMovement(
			tenant_id=tenant_id,
			product_id=product_id,
			warehouse_id=warehouse_id,
			from_location_id=from_loc_id,
			to_location_id=actual_location_id,
			movement_type="TRANSFER",
			quantity=qty,
			direction=1,
			unit_cost_cents=avg_cost,
			total_cost_cents=_cents(qty, avg_cost),
			lot_number=task.lot_number,
			expiry_date=task.expiry_date,
			reference_type="MANUAL",
			reference_id=putaway_task_id,
			notes=f"Putaway task {putaway_task_id}",
			moved_by=completed_by,
			moved_at=_inv_now(),
		)
		session.add(movement)
		session.flush()

		emit_event(
			StockTransferredEvent(
				aggregate_id=movement.id,
				aggregate_type="StockMovement",
				tenant_id=tenant_id,
				movement_id=movement.id,
				product_id=product_id,
				warehouse_id=warehouse_id,
				from_location_id=from_loc_id or "",
				to_location_id=actual_location_id,
				quantity=str(qty),
				lot_number=task.lot_number or "",
			),
			session,
		)

		task.actual_location_id = actual_location_id
		task.status = "COMPLETED"
		task.completed_by = completed_by
		task.completed_at = _now()
		task.updated_at = _now()

		emit_event(
			PutawayCompletedEvent(
				aggregate_id=putaway_task_id,
				aggregate_type="PutawayTask",
				tenant_id=str(task.tenant_id),
				putaway_task_id=putaway_task_id,
				warehouse_id=str(task.warehouse_id),
				product_id=str(task.product_id),
				quantity=str(task.quantity),
				from_location_id=from_loc_id or "",
				actual_location_id=actual_location_id,
				lot_number=task.lot_number or "",
				completed_by=completed_by,
			),
			session,
		)

		log.info("WarehouseService.complete_putaway: task=%s loc=%s", putaway_task_id, actual_location_id)
		return task

	def suggest_putaway_location(
		self,
		product_id: str,
		warehouse_id: str,
		session: Any,
	) -> str | None:
		"""Return the best available BULK or PICK location for putaway.

		Simple strategy: prefer PICK locations with available capacity,
		fall back to BULK.  Returns location id or None if none found.
		"""
		from pgappforge.plugins.erp.operations.inventory.models import WarehouseLocation

		for loc_type in ("PICK", "BULK"):
			loc = session.execute(
				sa.select(WarehouseLocation)
				.where(WarehouseLocation.warehouse_id == warehouse_id)
				.where(WarehouseLocation.location_type == loc_type)
				.where(WarehouseLocation.is_active.is_(True))
				.order_by(WarehouseLocation.aisle, WarehouseLocation.rack, WarehouseLocation.bin)
				.limit(1)
			).scalar_one_or_none()
			if loc is not None:
				return str(loc.id)
		return None

	# ------------------------------------------------------------------
	# Stock Count management
	# ------------------------------------------------------------------

	def start_stock_count(
		self,
		warehouse_id: str,
		count_type: str,
		session: Any,
		tenant_id: str = "",
	) -> Any:
		"""Delegate to InventoryService.run_stock_count() and return the count.

		count_type: FULL | CYCLE | SPOT
		"""
		from pgappforge.plugins.erp.operations.inventory.services import InventoryService

		if count_type not in ("FULL", "CYCLE", "SPOT"):
			raise WarehouseServiceError(f"Invalid count_type {count_type!r}")

		inv_svc = InventoryService()
		count = inv_svc.run_stock_count(warehouse_id, session)
		count.count_type = count_type  # override default FULL if needed

		log.info("WarehouseService.start_stock_count: wh=%s type=%s count=%s", warehouse_id, count_type, count.id)
		return count

	def record_count(
		self,
		stock_count_id: str,
		line_id: str,
		counted_qty: Any,
		session: Any,
	) -> Any:
		"""Record the operative's physical count for a StockCountLine.

		Updates:
		  counted_quantity = counted_qty
		  variance = counted_qty - expected_quantity
		  variance_value_cents = variance × average_cost_cents (from StockLevel)

		Returns updated StockCountLine.
		"""
		from pgappforge.plugins.erp.operations.warehouse.models import StockCount, StockCountLine
		from pgappforge.plugins.erp.operations.inventory.models import StockLevel

		count = session.get(StockCount, stock_count_id)
		if count is None:
			raise StockCountNotFoundError(f"StockCount {stock_count_id!r} not found")
		if count.status != "IN_PROGRESS":
			raise InvalidStatusTransitionError(
				f"StockCount {stock_count_id!r} must be IN_PROGRESS to record counts; got {count.status!r}"
			)

		line = session.get(StockCountLine, line_id)
		if line is None or str(line.stock_count_id) != str(stock_count_id):
			raise WarehouseServiceError(f"StockCountLine {line_id!r} not found on count {stock_count_id!r}")

		qty = _d(counted_qty)
		variance = qty - _d(line.expected_quantity)

		# Look up average cost for variance valuation
		sl_q = (
			sa.select(StockLevel)
			.where(StockLevel.product_id == line.product_id)
			.where(StockLevel.tenant_id == count.tenant_id)
		)
		if line.location_id:
			sl_q = sl_q.where(StockLevel.location_id == line.location_id)
		sl = session.execute(sl_q).scalar_one_or_none()
		avg_cost = sl.average_cost_cents if sl else 0

		variance_cents = int(
			(abs(variance) * Decimal(avg_cost)).to_integral_value(rounding=ROUND_HALF_UP)
		)
		if variance < 0:
			variance_cents = -variance_cents

		line.counted_quantity = qty
		line.variance = variance
		line.variance_value_cents = variance_cents
		line.updated_at = _now()

		return line

	def complete_stock_count(self, stock_count_id: str, session: Any) -> Any:
		"""Mark a StockCount COMPLETED (ready for management review and approval).

		All lines must have been counted (counted_quantity not NULL).
		Computes total_variance_value_cents for the header.

		Emits StockCountReadyEvent.
		"""
		from pgappforge.plugins.erp.operations.warehouse.models import StockCount
		from pgappforge.plugins.erp.operations.warehouse.events import StockCountReadyEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		count = session.get(StockCount, stock_count_id)
		if count is None:
			raise StockCountNotFoundError(f"StockCount {stock_count_id!r} not found")
		if count.status != "IN_PROGRESS":
			raise InvalidStatusTransitionError(
				f"StockCount {stock_count_id!r} must be IN_PROGRESS; got {count.status!r}"
			)

		uncounted = [l for l in count.lines if l.counted_quantity is None]
		if uncounted:
			raise WarehouseServiceError(
				f"StockCount {stock_count_id!r} has {len(uncounted)} uncounted line(s)"
			)

		total_var_cents = sum(l.variance_value_cents for l in count.lines)
		lines_with_variance = sum(1 for l in count.lines if l.variance != 0)

		count.total_variance_value_cents = total_var_cents
		count.status = "COMPLETED"
		count.updated_at = _now()

		emit_event(
			StockCountReadyEvent(
				aggregate_id=stock_count_id,
				aggregate_type="StockCount",
				tenant_id=str(count.tenant_id),
				stock_count_id=stock_count_id,
				warehouse_id=str(count.warehouse_id),
				lines_with_variance=lines_with_variance,
				total_variance_value_cents=total_var_cents,
			),
			session,
		)

		log.info(
			"WarehouseService.complete_stock_count: count=%s variance=%d¢ lines_adj=%d",
			stock_count_id, total_var_cents, lines_with_variance,
		)
		return count


__all__ = [
	"WarehouseService",
	"WarehouseServiceError",
	"PickListNotFoundError",
	"PutawayNotFoundError",
	"StockCountNotFoundError",
	"InvalidStatusTransitionError",
]
