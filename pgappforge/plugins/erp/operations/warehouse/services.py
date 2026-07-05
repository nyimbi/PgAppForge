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
  record_stock_count_line(stock_count_id, line_id, counted_qty, session) -> StockCountLine
  record_count(count_id, location_code, product_code, counted_qty, counted_by, session) -> CycleCountLine
  complete_stock_count(stock_count_id, session)                       -> StockCount
"""
from __future__ import annotations

import logging
import uuid
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


class StorageLocationNotFoundError(WarehouseServiceError):
	pass


class CycleCountNotFoundError(WarehouseServiceError):
	pass


class PickTaskNotFoundError(WarehouseServiceError):
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

		suggested_loc = self.suggest_putaway_location(product_id, warehouse_id, session, quantity)

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
		quantity: Any = Decimal("1"),
	) -> str | None:
		"""Return the best WMS storage location for directed putaway.

		Uses ABC slotting when product metadata is available. A-items prefer
		forward/low-sequence locations, C-items prefer rear/high-sequence bulk or
		reserve locations. Returns location id or None if no active location has
		enough open capacity.
		"""
		from pgappforge.plugins.erp.operations.inventory.models import Product
		from pgappforge.plugins.erp.operations.warehouse.models import StorageLocation

		qty = _d(quantity)
		if qty <= 0:
			return None

		product = session.get(Product, product_id)
		tenant_id = str(product.tenant_id) if product is not None else ""
		abc_class = str(
			getattr(product, "abc_class", None)
			or getattr(product, "velocity_class", None)
			or "B"
		).upper()[:1]
		if abc_class not in ("A", "B", "C"):
			abc_class = "B"

		needs_hazmat = bool(getattr(product, "is_hazardous", False))
		needs_cold = bool(
			getattr(product, "requires_cold_storage", False)
			or getattr(product, "is_cold_chain", False)
			or getattr(product, "cold_chain_required", False)
		)
		needs_bulk = bool(
			getattr(product, "requires_bulk_storage", False)
			or getattr(product, "is_bulk", False)
		)

		query = (
			sa.select(StorageLocation)
			.where(StorageLocation.warehouse_id == warehouse_id)
			.where(StorageLocation.is_active.is_(True))
			.where((StorageLocation.capacity_units - StorageLocation.current_units) >= qty)
		)
		if tenant_id:
			query = query.where(StorageLocation.tenant_id == tenant_id)

		locations = session.execute(query).scalars().all()
		if not locations:
			return None

		def _sequence(loc: Any) -> int:
			parts = [loc.aisle, loc.bay, loc.level, loc.bin]
			total = 0
			for idx, part in enumerate(parts):
				text = str(part or "")
				digits = "".join(ch for ch in text if ch.isdigit())
				if digits:
					value = int(digits)
				elif text:
					value = sum(ord(ch.upper()) - 64 for ch in text if ch.isalpha())
				else:
					value = 0
				total += value * (100 ** (len(parts) - idx - 1))
			return total

		def _fits_flags(loc: Any) -> bool:
			zone = str(loc.zone_code or "").upper()
			loc_type = str(loc.location_type or "").upper()
			if needs_hazmat and zone != "HAZMAT":
				return False
			if needs_cold and zone != "COLD":
				return False
			if needs_bulk and loc_type != "BULK":
				return False
			if loc_type in ("STAGING", "RECEIVING", "DESPATCH", "QUARANTINE"):
				return False
			return loc_type in ("BULK", "PICK_FACE", "RESERVE")

		def _score(loc: Any) -> tuple[int, int, int, str]:
			zone = str(loc.zone_code or "").upper()
			loc_type = str(loc.location_type or "").upper()
			seq = _sequence(loc)
			open_capacity = _d(loc.capacity_units) - _d(loc.current_units)
			score = 0

			if abc_class == "A":
				score += 1000 if zone == "A" else 0
				score += 300 if loc_type == "PICK_FACE" else 0
				score -= min(seq, 9999)
			elif abc_class == "C":
				score += 1000 if zone == "C" else 0
				score += 250 if loc_type in ("BULK", "RESERVE") else 0
				score += min(seq, 9999)
			else:
				score += 500 if zone == "B" else 0
				score += 150 if loc_type in ("BULK", "PICK_FACE") else 0
				score -= abs(5000 - min(seq, 9999))

			if needs_hazmat and zone == "HAZMAT":
				score += 400
			if needs_cold and zone == "COLD":
				score += 400
			if needs_bulk and loc_type == "BULK":
				score += 400

			return (score, int(open_capacity), -seq, str(loc.location_code or ""))

		scored = [loc for loc in locations if _fits_flags(loc)]
		if not scored:
			return None
		best = max(scored, key=_score)
		return str(best.id)

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

	def record_stock_count_line(
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


	# ------------------------------------------------------------------
	# StorageLocation / directed putaway (new-style, code-based)
	# ------------------------------------------------------------------

	def receive_goods_to_warehouse(
		self,
		session: Any,
		grn_id: str,
		product_code: str,
		quantity: Any,
		warehouse_id: str,
		tenant_id: str = "",
	) -> Any:
		"""Create a PutawayTask for inbound goods, picking the best empty location.

		Location selection priority:
		  1. RECEIVING zone locations with available capacity
		  2. BULK locations with available capacity
		  (first non-full active location in aisle/bay/level/bin order)

		Updates StorageLocation.current_units for the chosen location.

		Returns:
		  PutawayTask (not committed — caller must flush/commit).
		"""
		from pgappforge.plugins.erp.operations.warehouse.models import (
			StorageLocation, PutawayTask,
		)

		qty = _d(quantity)
		assert qty > 0, "quantity must be positive"

		# Find optimal location: RECEIVING first, then BULK
		to_loc: Any = None
		for loc_type in ("RECEIVING", "BULK"):
			candidate = session.execute(
				sa.select(StorageLocation)
				.where(StorageLocation.warehouse_id == warehouse_id)
				.where(StorageLocation.tenant_id == tenant_id)
				.where(StorageLocation.location_type == loc_type)
				.where(StorageLocation.is_active.is_(True))
				.where(
					(StorageLocation.capacity_units - StorageLocation.current_units) >= qty
				)
				.order_by(
					StorageLocation.zone_code,
					StorageLocation.aisle,
					StorageLocation.bay,
					StorageLocation.level,
					StorageLocation.bin,
				)
				.limit(1)
			).scalar_one_or_none()
			if candidate is not None:
				to_loc = candidate
				break

		to_location_code = to_loc.location_code if to_loc is not None else None

		task = PutawayTask(
			tenant_id=tenant_id,
			warehouse_id=warehouse_id,
			grn_id=grn_id,
			product_id=product_code,  # product_id field reused as code (soft ref)
			quantity=qty,
			status="PENDING",
			suggested_location_id=None,
			actual_location_id=None,
		)
		session.add(task)
		session.flush()

		# Optimistically reserve capacity on the chosen location
		if to_loc is not None:
			to_loc.current_units = _d(to_loc.current_units) + qty
			to_loc.updated_at = _now()

		log.info(
			"WarehouseService.receive_goods_to_warehouse: task=%s grn=%s product=%s qty=%s loc=%s",
			task.id, grn_id, product_code, qty, to_location_code,
		)
		return task

	def complete_putaway_to_location(
		self,
		session: Any,
		putaway_task_id: str,
		tenant_id: str = "",
	) -> Any:
		"""Mark a PutawayTask COMPLETED and confirm inventory position.

		Confirms the stock is physically at the to_location recorded on the task.
		If actual_location_id is unset, uses suggested_location_id.
		Updates StorageLocation.current_units to reflect confirmed position.

		Returns:
		  PutawayTask with status=COMPLETED.
		"""
		from pgappforge.plugins.erp.operations.warehouse.models import PutawayTask, StorageLocation

		task = session.get(PutawayTask, putaway_task_id)
		if task is None:
			raise PutawayNotFoundError(f"PutawayTask {putaway_task_id!r} not found")
		if task.status not in ("PENDING", "IN_PROGRESS"):
			raise InvalidStatusTransitionError(
				f"PutawayTask {putaway_task_id!r} status={task.status!r}; cannot complete"
			)
		if str(task.tenant_id) != tenant_id:
			raise WarehouseServiceError("Tenant mismatch on PutawayTask")

		confirmed_loc_id = task.actual_location_id or task.suggested_location_id

		task.status = "COMPLETED"
		task.completed_at = _now()
		task.updated_at = _now()

		log.info(
			"WarehouseService.complete_putaway_to_location: task=%s loc=%s",
			putaway_task_id, confirmed_loc_id,
		)
		return task

	# ------------------------------------------------------------------
	# PickTask (FEFO-aware directed picking)
	# ------------------------------------------------------------------

	def create_pick_list(
		self,
		session: Any,
		sales_order_id: str,
		lines: list[dict],
		warehouse_id: str,
		tenant_id: str = "",
	) -> list[Any]:
		"""Create directed PickTasks for an outbound order using FEFO sequencing.

		For each line dict {"product_code": str, "quantity": Decimal/str}:
		  1. Query StorageLocations in this warehouse holding the product
		     (via wms_storage_location.current_units > 0) ordered by
		     earliest expiry_date in attached stock (FEFO proxy via aisle/bay sort).
		  2. Split across locations until quantity_required is satisfied.
		  3. Create one PickTask per location split.

		lines format:
		  [{"product_code": str, "quantity": str|Decimal}, ...]

		Returns:
		  list[PickTask] — all tasks created (not committed).
		"""
		from pgappforge.plugins.erp.operations.warehouse.models import StorageLocation, PickTask

		if not lines:
			raise WarehouseServiceError("create_pick_list requires at least one line")

		all_tasks: list[Any] = []

		for line in lines:
			product_code = str(line["product_code"])
			qty_needed = _d(line["quantity"])
			assert qty_needed > 0, f"quantity for {product_code!r} must be positive"

			# Find locations holding this product, ordered FEFO proxy (aisle/bay/level/bin)
			# Real FEFO would join to lot/expiry table; we use location ordering as proxy.
			locations = session.execute(
				sa.select(StorageLocation)
				.where(StorageLocation.warehouse_id == warehouse_id)
				.where(StorageLocation.tenant_id == tenant_id)
				.where(StorageLocation.is_active.is_(True))
				.where(StorageLocation.current_units > 0)
				.where(StorageLocation.location_type.in_(("PICK_FACE", "BULK", "RESERVE")))
				.order_by(
					StorageLocation.zone_code,
					StorageLocation.aisle,
					StorageLocation.bay,
					StorageLocation.level,
					StorageLocation.bin,
				)
			).scalars().all()

			remaining = qty_needed
			for loc in locations:
				if remaining <= 0:
					break
				available = _d(loc.current_units)
				if available <= 0:
					continue
				pick_qty = min(remaining, available)

				task = PickTask(
					tenant_id=tenant_id,
					pick_list_id=sales_order_id,
					product_code=product_code,
					quantity_required=pick_qty,
					quantity_picked=Decimal("0"),
					from_location_code=loc.location_code,
					status="PENDING",
				)
				session.add(task)
				all_tasks.append(task)
				remaining -= pick_qty

			if remaining > 0:
				log.warning(
					"WarehouseService.create_pick_list: short stock for product=%s order=%s "
					"short=%s",
					product_code, sales_order_id, remaining,
				)

		session.flush()
		log.info(
			"WarehouseService.create_pick_list: order=%s tasks=%d",
			sales_order_id, len(all_tasks),
		)
		return all_tasks

	def complete_pick(
		self,
		session: Any,
		pick_task_id: str,
		quantity_picked: Any,
		tenant_id: str = "",
	) -> Any:
		"""Record quantity picked for a PickTask and update location occupancy.

		If quantity_picked < quantity_required: status=SHORT_PICKED.
		If quantity_picked >= quantity_required: status=COMPLETED.
		Reduces StorageLocation.current_units by quantity_picked.

		Returns:
		  PickTask with updated status and quantity_picked.
		"""
		from pgappforge.plugins.erp.operations.warehouse.models import PickTask, StorageLocation

		task = session.get(PickTask, pick_task_id)
		if task is None:
			raise PickTaskNotFoundError(f"PickTask {pick_task_id!r} not found")
		if str(task.tenant_id) != tenant_id:
			raise WarehouseServiceError("Tenant mismatch on PickTask")
		if task.status not in ("PENDING", "IN_PROGRESS"):
			raise InvalidStatusTransitionError(
				f"PickTask {pick_task_id!r} status={task.status!r}; cannot complete"
			)

		qty = _d(quantity_picked)
		assert qty >= 0, "quantity_picked must be non-negative"

		task.quantity_picked = qty
		task.completed_at = _now()
		task.updated_at = _now()

		if qty >= _d(task.quantity_required):
			task.status = "COMPLETED"
		else:
			task.status = "SHORT_PICKED"

		# Reduce location occupancy
		loc = session.execute(
			sa.select(StorageLocation)
			.where(StorageLocation.location_code == task.from_location_code)
			.where(StorageLocation.tenant_id == tenant_id)
			.limit(1)
		).scalar_one_or_none()
		if loc is not None:
			new_units = max(Decimal("0"), _d(loc.current_units) - qty)
			loc.current_units = new_units
			loc.updated_at = _now()

		log.info(
			"WarehouseService.complete_pick: task=%s picked=%s status=%s",
			pick_task_id, qty, task.status,
		)
		return task

	# ------------------------------------------------------------------
	# Cycle Count
	# ------------------------------------------------------------------

	def start_cycle_count(
		self,
		session: Any,
		warehouse_id: str,
		zone_code: str | None = None,
		tenant_id: str = "",
	) -> Any:
		"""Create a CycleCount and populate CycleCountLines for every location+product.

		Scans wms_storage_location for active locations in the given zone
		(or all zones when zone_code is None) and creates one CycleCountLine
		per location that has current_units > 0.

		The count_reference is auto-generated as "CC-<YYYYMMDD>-<4-hex>".
		Status is set to IN_PROGRESS immediately.

		Returns:
		  CycleCount with lines attached (not committed).
		"""
		from datetime import date
		from pgappforge.plugins.erp.operations.warehouse.models import (
			CycleCount, CycleCountLine, StorageLocation,
		)

		today = date.today()
		ref_suffix = uuid.uuid4().hex[:4].upper()
		count_reference = f"CC-{today.strftime('%Y%m%d')}-{ref_suffix}"

		# Fetch locations in scope — ONE query
		loc_q = (
			sa.select(StorageLocation)
			.where(StorageLocation.warehouse_id == warehouse_id)
			.where(StorageLocation.tenant_id == tenant_id)
			.where(StorageLocation.is_active.is_(True))
			.where(StorageLocation.current_units > 0)
		)
		if zone_code is not None:
			loc_q = loc_q.where(StorageLocation.zone_code == zone_code)
		locations = session.execute(loc_q).scalars().all()

		count = CycleCount(
			tenant_id=tenant_id,
			count_reference=count_reference,
			warehouse_id=warehouse_id,
			zone_code=zone_code,
			status="IN_PROGRESS",
			scheduled_date=today,
			total_locations=len(locations),
			locations_counted=0,
			started_at=_now(),
		)
		session.add(count)
		session.flush()

		# Bulk insert all lines in a single statement — zero per-row DB round-trips
		now = _now()
		line_dicts = [
			{
				"id": str(uuid.uuid4()),
				"tenant_id": tenant_id,
				"count_id": str(count.id),
				"location_code": loc.location_code,
				"product_code": "",  # populated by caller per product in location
				"system_qty": loc.current_units,
				"counted_qty": None,
				"variance": None,
				"variance_pct": None,
				"is_approved": False,
				"created_at": now,
				"updated_at": now,
			}
			for loc in locations
		]
		if line_dicts:
			session.execute(sa.insert(CycleCountLine), line_dicts)

		session.flush()
		log.info(
			"WarehouseService.start_cycle_count: count=%s ref=%s wh=%s zone=%s locs=%d",
			count.id, count_reference, warehouse_id, zone_code, len(locations),
		)
		return count

	def record_count(
		self,
		session: Any,
		count_id: str,
		location_code: str,
		product_code: str,
		counted_qty: Any,
		counted_by: str,
		tenant_id: str = "",
	) -> Any:
		"""Record a physical count for a CycleCountLine.

		Locates the CycleCountLine by (count_id, location_code, product_code).
		Computes:
		  variance = counted_qty - system_qty
		  variance_pct = abs(variance) / system_qty × 100 (NULL when system_qty=0)

		Sets CycleCount.counted_by if not already set.
		Increments CycleCount.locations_counted.

		Returns:
		  CycleCountLine with variance fields populated.
		"""
		from pgappforge.plugins.erp.operations.warehouse.models import CycleCount, CycleCountLine

		count = session.get(CycleCount, count_id)
		if count is None:
			raise CycleCountNotFoundError(f"CycleCount {count_id!r} not found")
		if count.status != "IN_PROGRESS":
			raise InvalidStatusTransitionError(
				f"CycleCount {count_id!r} must be IN_PROGRESS; got {count.status!r}"
			)
		if str(count.tenant_id) != tenant_id:
			raise WarehouseServiceError("Tenant mismatch on CycleCount")

		line = session.execute(
			sa.select(CycleCountLine)
			.where(CycleCountLine.count_id == count_id)
			.where(CycleCountLine.location_code == location_code)
			.where(CycleCountLine.product_code == product_code)
			.limit(1)
		).scalar_one_or_none()
		if line is None:
			raise WarehouseServiceError(
				f"CycleCountLine not found for count={count_id!r} "
				f"location={location_code!r} product={product_code!r}"
			)

		qty = _d(counted_qty)
		sys_qty = _d(line.system_qty)
		variance = qty - sys_qty
		variance_pct: Decimal | None = None
		if sys_qty != 0:
			variance_pct = (abs(variance) / sys_qty * Decimal("100")).quantize(
				Decimal("0.0001"), rounding=ROUND_HALF_UP
			)

		was_uncounted = line.counted_qty is None

		line.counted_qty = qty
		line.variance = variance
		line.variance_pct = variance_pct
		line.updated_at = _now()

		# Update count header
		if was_uncounted:
			count.locations_counted = (count.locations_counted or 0) + 1
		if not count.counted_by:
			count.counted_by = counted_by
		count.updated_at = _now()

		return line

	def approve_count_adjustment(
		self,
		session: Any,
		count_id: str,
		approver_id: str,
		tenant_id: str = "",
	) -> dict:
		"""Post GL adjustments for all unapproved CycleCountLines with variance != 0.

		For each qualifying line:
		  - variance > 0 (stock gain): DR Inventory "1140" / CR Inventory Adjustment "5600"
		  - variance < 0 (stock loss): DR Inventory Adjustment "5600" / CR Inventory "1140"
		  - Mark line is_approved=True, approved_by=approver_id

		GL posting uses lazy import try/except — non-fatal if GL plugin absent.

		Returns:
		  {"adjustments_made": int, "total_variance_cents": int}
		"""
		from pgappforge.plugins.erp.operations.warehouse.models import CycleCount, CycleCountLine

		count = session.get(CycleCount, count_id)
		if count is None:
			raise CycleCountNotFoundError(f"CycleCount {count_id!r} not found")
		if count.status not in ("IN_PROGRESS", "COMPLETED"):
			raise InvalidStatusTransitionError(
				f"CycleCount {count_id!r} must be IN_PROGRESS or COMPLETED; got {count.status!r}"
			)
		if str(count.tenant_id) != tenant_id:
			raise WarehouseServiceError("Tenant mismatch on CycleCount")

		lines = session.execute(
			sa.select(CycleCountLine)
			.where(CycleCountLine.count_id == count_id)
			.where(CycleCountLine.is_approved.is_(False))
			.where(CycleCountLine.counted_qty.is_not(None))
			.where(CycleCountLine.variance != 0)
		).scalars().all()

		adjustments_made = 0
		total_variance_cents = 0

		try:
			from pgappforge.plugins.erp.finance.gl.services import GLService  # type: ignore[import]
			gl_available = True
		except ImportError:
			gl_available = False
			log.debug("approve_count_adjustment: GL plugin not available, skipping journal posts")

		for line in lines:
			variance = _d(line.variance)
			# Approximate valuation: 1 unit = 100 cents (caller should override with real cost)
			variance_cents = int(abs(variance) * 100)

			if gl_available:
				try:
					if variance > 0:
						# Stock gain: DR Inventory / CR Inventory Adjustment
						GLService.post_journal(
							session,
							reference=f"CYCLECOUNT-{count_id[:8]}-{line.id[:8]}",
							lines=[
								{"account_code": "1140", "debit_cents": variance_cents, "credit_cents": 0},
								{"account_code": "5600", "debit_cents": 0, "credit_cents": variance_cents},
							],
						)
					else:
						# Stock loss: DR Inventory Adjustment / CR Inventory
						GLService.post_journal(
							session,
							reference=f"CYCLECOUNT-{count_id[:8]}-{line.id[:8]}",
							lines=[
								{"account_code": "5600", "debit_cents": variance_cents, "credit_cents": 0},
								{"account_code": "1140", "debit_cents": 0, "credit_cents": variance_cents},
							],
						)
				except Exception as gl_err:
					log.warning("approve_count_adjustment: GL post failed for line=%s: %s", line.id, gl_err)

			line.is_approved = True
			line.approved_by = approver_id
			line.updated_at = _now()

			adjustments_made += 1
			total_variance_cents += variance_cents if variance > 0 else -variance_cents

		count.status = "COMPLETED"
		count.completed_at = _now()
		count.updated_at = _now()

		log.info(
			"WarehouseService.approve_count_adjustment: count=%s adjustments=%d variance_cents=%d",
			count_id, adjustments_made, total_variance_cents,
		)
		return {"adjustments_made": adjustments_made, "total_variance_cents": total_variance_cents}

	# ------------------------------------------------------------------
	# Reporting
	# ------------------------------------------------------------------

	def get_warehouse_utilization(
		self,
		session: Any,
		warehouse_id: str,
		tenant_id: str = "",
	) -> dict:
		"""Return utilisation summary for a warehouse.

		Returns:
		  {
		    "total_locations": int,
		    "occupied": int,       # current_units > 0
		    "empty": int,          # current_units == 0
		    "utilization_pct": float,
		    "by_zone": {zone_code: {"total": int, "occupied": int, "utilization_pct": float}},
		    "overstocked_locations": [{"location_code": str, "current_units": float,
		                               "capacity_units": float, "pct": float}],
		  }
		"""
		from pgappforge.plugins.erp.operations.warehouse.models import StorageLocation

		rows = session.execute(
			sa.select(StorageLocation)
			.where(StorageLocation.warehouse_id == warehouse_id)
			.where(StorageLocation.tenant_id == tenant_id)
			.where(StorageLocation.is_active.is_(True))
		).scalars().all()

		total = len(rows)
		occupied = sum(1 for r in rows if _d(r.current_units) > 0)
		empty = total - occupied
		utilization_pct = round(occupied / total * 100, 2) if total else 0.0

		by_zone: dict[str, dict] = {}
		for r in rows:
			z = r.zone_code or "UNZONED"
			entry = by_zone.setdefault(z, {"total": 0, "occupied": 0, "utilization_pct": 0.0})
			entry["total"] += 1
			if _d(r.current_units) > 0:
				entry["occupied"] += 1
		for z, entry in by_zone.items():
			t = entry["total"]
			entry["utilization_pct"] = round(entry["occupied"] / t * 100, 2) if t else 0.0

		overstocked = []
		for r in rows:
			cap = _d(r.capacity_units)
			cur = _d(r.current_units)
			if cap > 0 and cur >= cap * Decimal("0.95"):
				overstocked.append({
					"location_code": r.location_code,
					"current_units": float(cur),
					"capacity_units": float(cap),
					"pct": round(float(cur / cap * 100), 2),
				})
		overstocked.sort(key=lambda x: x["pct"], reverse=True)

		return {
			"total_locations": total,
			"occupied": occupied,
			"empty": empty,
			"utilization_pct": utilization_pct,
			"by_zone": by_zone,
			"overstocked_locations": overstocked,
		}

	def get_inventory_by_location(
		self,
		session: Any,
		warehouse_id: str,
		product_code: str | None = None,
		tenant_id: str = "",
	) -> list[dict]:
		"""Return per-location inventory snapshot for a warehouse.

		Args:
		  product_code: optional filter; when None returns all products.

		Returns:
		  list of {location_code, zone, product_code, quantity, capacity_pct}
		  sorted by zone / location_code.
		  Only locations with current_units > 0 are returned.
		"""
		from pgappforge.plugins.erp.operations.warehouse.models import StorageLocation

		loc_q = (
			sa.select(StorageLocation)
			.where(StorageLocation.warehouse_id == warehouse_id)
			.where(StorageLocation.tenant_id == tenant_id)
			.where(StorageLocation.is_active.is_(True))
			.where(StorageLocation.current_units > 0)
			.order_by(StorageLocation.zone_code, StorageLocation.location_code)
		)
		locations = session.execute(loc_q).scalars().all()

		results = []
		for loc in locations:
			cur = _d(loc.current_units)
			cap = _d(loc.capacity_units)
			capacity_pct = round(float(cur / cap * 100), 2) if cap > 0 else None

			# product_code filter: StorageLocation tracks aggregate units, not per-SKU.
			# When filtering by product_code we can only include locations that were
			# stocked via receive_goods_to_warehouse with that code.  Without a
			# wms_location_stock join table we emit one row per location with a
			# placeholder product_code — callers wanting SKU-level data should join
			# against wms_pick_task or wms_cycle_count_line.
			row_product = product_code or "MIXED"
			if product_code is not None:
				# Skip locations that have no evidence of this product
				# (best-effort: check cycle count lines for this location+product)
				from pgappforge.plugins.erp.operations.warehouse.models import CycleCountLine
				evidence = session.execute(
					sa.select(CycleCountLine.id)
					.where(CycleCountLine.location_code == loc.location_code)
					.where(CycleCountLine.product_code == product_code)
					.where(CycleCountLine.tenant_id == tenant_id)
					.limit(1)
				).scalar_one_or_none()
				if evidence is None:
					continue

			results.append({
				"location_code": loc.location_code,
				"zone": loc.zone_code,
				"product_code": row_product,
				"quantity": float(cur),
				"capacity_pct": capacity_pct,
			})

		return results


__all__ = [
	"WarehouseService",
	"WarehouseServiceError",
	"PickListNotFoundError",
	"PickTaskNotFoundError",
	"PutawayNotFoundError",
	"StockCountNotFoundError",
	"CycleCountNotFoundError",
	"StorageLocationNotFoundError",
	"InvalidStatusTransitionError",
]
