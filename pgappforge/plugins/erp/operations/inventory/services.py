"""
pgappforge/plugins/erp/operations/inventory/services.py

InventoryService — stateless business logic for the Inventory plugin.

All methods receive an explicit SQLAlchemy session; no Flask context assumed.
Transaction boundaries owned by the caller.

Monetary invariants:
  - All amounts passed in and returned as integer cents
  - Decimal arithmetic used internally; results rounded half-up to int
  - Quantities use Decimal(str(...)) — never float

Public API:
  receive_stock(grn_id, session)                        -> list[StockMovement]
  allocate_stock(order_id, order_type, lines, session)  -> list[StockLevel]
  issue_stock(order_id, order_type, lines, session)     -> list[StockMovement]
  transfer_stock(product_id, qty, from_loc, to_loc, session) -> StockMovement
  adjust_stock(product_id, wh_id, qty_delta, reason, session) -> StockMovement
  get_stock_valuation(warehouse_id, as_of_date, session) -> dict
  calculate_reorder_suggestions(tenant_id, session)     -> list[dict]
  _update_stock_level(product_id, wh_id, loc_id, qty_delta, cost_cents, session)
"""
from __future__ import annotations

import logging
import math
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import sqlalchemy as sa

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class InventoryServiceError(Exception):
	"""Base domain error for inventory operations."""


class StockNotFoundError(InventoryServiceError):
	pass


class InsufficientStockError(InventoryServiceError):
	"""Raised when available quantity < requested quantity."""


class ProductNotFoundError(InventoryServiceError):
	pass


class WarehouseNotFoundError(InventoryServiceError):
	pass


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _d(value: Any) -> Decimal:
	"""Safe Decimal coercion — never float intermediate."""
	if isinstance(value, Decimal):
		return value
	return Decimal(str(value))


def _cents(qty: Decimal, unit_cost_cents: int) -> int:
	"""qty × unit_cost_cents, rounded half-up to int."""
	assert isinstance(unit_cost_cents, int), "unit_cost_cents must be int"
	return int((qty * Decimal(unit_cost_cents)).to_integral_value(rounding=ROUND_HALF_UP))


def _now() -> datetime:
	return datetime.now(timezone.utc)


def _today() -> date:
	return _now().date()


# ---------------------------------------------------------------------------
# InventoryService
# ---------------------------------------------------------------------------

class InventoryService:
	"""Stateless inventory domain service.

	Instantiate once per application (no instance state).
	All public methods accept an explicit SQLAlchemy Session.
	"""

	# ------------------------------------------------------------------
	# receive_stock
	# ------------------------------------------------------------------

	def receive_stock(self, grn_id: str, session: Any) -> list[Any]:
		"""Post stock receipts from a confirmed GRN into inventory.

		For each accepted GRN line:
		  1. Creates an immutable StockMovement (type=RECEIPT, direction=1)
		  2. Updates StockLevel (quantity_on_hand, average_cost_cents)
		  3. Emits StockReceivedEvent
		  4. Checks reorder point → may emit StockLowEvent

		GRN is referenced by a soft FK — this service does not depend on the
		AP plugin's APGoodsReceipt model.  It reads the GRN from a shared dict
		contract or falls back to direct model import when AP is loaded.

		Args:
			grn_id: UUID of the goods receipt (APGoodsReceipt or inv_grn).
			session: SQLAlchemy session (caller commits).

		Returns:
			List of StockMovement instances created.

		Raises:
			InventoryServiceError: GRN not found or not in accepted status.
		"""
		from pgappforge.plugins.erp.operations.inventory.models import (
			StockMovement, StockLevel, Product, Warehouse, CostLayer,
		)
		from pgappforge.plugins.erp.operations.inventory.events import (
			StockReceivedEvent, StockLowEvent,
		)
		from pgappforge.plugins.erp.foundation.events import emit_event

		# Try to load GRN from AP plugin first (optional dependency)
		grn = None
		grn_lines: list[Any] = []
		try:
			from pgappforge.plugins.erp.finance.ap.models import APGoodsReceipt
			grn = session.get(APGoodsReceipt, grn_id)
			if grn is not None:
				grn_lines = grn.lines
		except ImportError:
			pass

		if grn is None:
			raise InventoryServiceError(f"GRN {grn_id!r} not found")

		if grn.status not in ("CONFIRMED", "ACCEPTED", "PARTIAL", "POSTED"):
			raise InventoryServiceError(
				f"GRN {grn_id!r} status={grn.status!r}; must be CONFIRMED/ACCEPTED before receiving stock"
			)

		movements: list[Any] = []

		for line in grn_lines:
			accepted = _d(line.quantity_accepted or line.quantity_received or 0)
			if accepted <= 0:
				continue

			unit_cost = int(line.unit_cost_cents or 0)
			total_cost = _cents(accepted, unit_cost)

			# Determine product and warehouse
			product_id = str(line.product_id) if hasattr(line, "product_id") else None
			warehouse_id = str(grn.warehouse_id) if hasattr(grn, "warehouse_id") else None
			location_id = str(line.location_id) if hasattr(line, "location_id") and line.location_id else None

			if not product_id or not warehouse_id:
				log.warning("receive_stock: skipping line missing product_id or warehouse_id")
				continue

			# Validate product exists
			product = session.get(Product, product_id)
			if product is None:
				raise ProductNotFoundError(f"Product {product_id!r} not found for GRN line")

			# Validate lot/serial requirements
			if product.is_lot_tracked and not getattr(line, "lot_number", None):
				raise InventoryServiceError(
					f"Product {product.sku!r} is lot-tracked but lot_number not provided in GRN line"
				)
			if product.is_serial_tracked and not getattr(line, "serial_number", None):
				raise InventoryServiceError(
					f"Product {product.sku!r} is serial-tracked but serial_number not provided in GRN line"
				)

			lot_number = getattr(line, "lot_number", None)
			expiry_date = getattr(line, "expiry_date", None)
			tenant_id = str(grn.tenant_id)

			# Create immutable StockMovement
			movement = StockMovement(
				tenant_id=tenant_id,
				product_id=product_id,
				warehouse_id=warehouse_id,
				from_location_id=None,
				to_location_id=location_id,
				movement_type="RECEIPT",
				quantity=accepted,
				direction=1,
				unit_cost_cents=unit_cost,
				total_cost_cents=total_cost,
				lot_number=lot_number,
				serial_number=getattr(line, "serial_number", None),
				expiry_date=expiry_date,
				reference_type="PO",
				reference_id=str(grn.po_id) if getattr(grn, "po_id", None) else None,
				notes=f"GRN {getattr(grn, 'grn_number', grn_id)} receipt",
				moved_by=str(grn.received_by) if getattr(grn, "received_by", None) else None,
				moved_at=_now(),
			)
			session.add(movement)
			session.flush()  # populate movement.id

			# Update StockLevel
			sl = self._update_stock_level(
				product_id=product_id,
				warehouse_id=warehouse_id,
				location_id=location_id,
				lot_number=lot_number,
				expiry_date=expiry_date,
				qty_delta=accepted,
				unit_cost_cents=unit_cost,
				direction=1,
				tenant_id=tenant_id,
				session=session,
			)

			# Create cost layer for FIFO/LIFO tracking
			session.add(CostLayer(
				tenant_id=tenant_id,
				product_id=product_id,
				warehouse_id=warehouse_id,
				received_qty=accepted,
				unit_cost_cents=unit_cost,
				remaining_qty=accepted,
				source_grn_id=grn_id,
			))

			movements.append(movement)

			emit_event(
				StockReceivedEvent(
					aggregate_id=movement.id,
					aggregate_type="StockMovement",
					tenant_id=tenant_id,
					movement_id=movement.id,
					product_id=product_id,
					warehouse_id=warehouse_id,
					location_id=location_id or "",
					quantity=str(accepted),
					unit_cost_cents=unit_cost,
					total_cost_cents=total_cost,
					lot_number=lot_number or "",
					expiry_date=expiry_date.isoformat() if expiry_date else "",
					reference_type="PO",
					reference_id=str(grn.po_id) if getattr(grn, "po_id", None) else "",
				),
				session,
			)

			# Check reorder point
			self._check_reorder(product, sl, tenant_id, session, emit_event)

		log.info("InventoryService.receive_stock: GRN=%s movements=%d", grn_id, len(movements))
		return movements

	# ------------------------------------------------------------------
	# allocate_stock
	# ------------------------------------------------------------------

	def allocate_stock(
		self,
		order_id: str,
		order_type: str,
		lines: list[dict],
		session: Any,
		tenant_id: str = "",
	) -> list[Any]:
		"""Reserve (soft-allocate) stock for an outbound order.

		Increments quantity_reserved and decrements quantity_available on
		matching StockLevel rows.  Does NOT create StockMovement rows —
		that happens at issue_stock() time.

		lines format:
		  [{"product_id": str, "warehouse_id": str, "quantity": str/Decimal,
		    "location_id": str|None, "lot_number": str|None}, ...]

		Args:
			order_id: UUID of the source order (SO, transfer, production order).
			order_type: "SALES_ORDER" | "TRANSFER" | "PRODUCTION"
			lines: List of allocation requests.
			session: SQLAlchemy session.
			tenant_id: Tenant scope.

		Returns:
			List of updated StockLevel instances.

		Raises:
			InsufficientStockError: If available qty < requested qty for any line.
		"""
		from pgappforge.plugins.erp.operations.inventory.models import StockLevel, Product

		updated_levels: list[Any] = []

		for line in lines:
			product_id = str(line["product_id"])
			warehouse_id = str(line["warehouse_id"])
			qty = _d(line["quantity"])
			location_id = str(line["location_id"]) if line.get("location_id") else None
			lot_number = line.get("lot_number")

			assert qty > 0, f"Allocation quantity must be positive; got {qty}"

			# Find matching StockLevel
			q = (
				sa.select(StockLevel)
				.where(StockLevel.product_id == product_id)
				.where(StockLevel.warehouse_id == warehouse_id)
			)
			if tenant_id:
				q = q.where(StockLevel.tenant_id == tenant_id)
			if location_id:
				q = q.where(StockLevel.location_id == location_id)
			if lot_number:
				q = q.where(StockLevel.lot_number == lot_number)

			sl = session.execute(q).scalar_one_or_none()
			if sl is None:
				raise StockNotFoundError(
					f"No StockLevel for product={product_id!r} warehouse={warehouse_id!r}"
					+ (f" location={location_id!r}" if location_id else "")
				)

			avail = _d(sl.quantity_available)
			if avail < qty:
				product = session.get(Product, product_id)
				sku = product.sku if product else product_id
				raise InsufficientStockError(
					f"Insufficient stock for {sku!r}: available={avail} requested={qty}"
				)

			sl.quantity_reserved = _d(sl.quantity_reserved) + qty
			sl.quantity_available = _d(sl.quantity_on_hand) - sl.quantity_reserved
			sl.updated_at = _now()
			updated_levels.append(sl)

		log.info(
			"InventoryService.allocate_stock: order=%s type=%s lines=%d",
			order_id, order_type, len(lines),
		)
		return updated_levels

	# ------------------------------------------------------------------
	# issue_stock (pick and ship)
	# ------------------------------------------------------------------

	def issue_stock(
		self,
		order_id: str,
		order_type: str,
		lines: list[dict],
		session: Any,
		tenant_id: str = "",
		issued_by: str | None = None,
	) -> list[Any]:
		"""Issue stock against an order, creating ISSUE StockMovement rows.

		Decrements quantity_on_hand and quantity_reserved on StockLevel.
		Creates an immutable StockMovement per line (type=ISSUE, direction=-1).
		Emits StockIssuedEvent per line.

		lines format same as allocate_stock.

		Raises:
			InsufficientStockError: on_hand < requested.
		"""
		from pgappforge.plugins.erp.operations.inventory.models import (
			StockLevel, StockMovement, Product,
		)
		from pgappforge.plugins.erp.operations.inventory.events import StockIssuedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		movements: list[Any] = []

		for line in lines:
			product_id = str(line["product_id"])
			warehouse_id = str(line["warehouse_id"])
			qty = _d(line["quantity"])
			location_id = str(line["location_id"]) if line.get("location_id") else None
			lot_number = line.get("lot_number")

			assert qty > 0, "Issue quantity must be positive"

			# Validate lot tracking
			product = session.get(Product, product_id)
			if product and product.is_lot_tracked and not lot_number:
				raise InventoryServiceError(
					f"Product {product.sku!r} is lot-tracked; lot_number required for issue"
				)

			# Find StockLevel
			q = (
				sa.select(StockLevel)
				.where(StockLevel.product_id == product_id)
				.where(StockLevel.warehouse_id == warehouse_id)
			)
			if tenant_id:
				q = q.where(StockLevel.tenant_id == tenant_id)
			if location_id:
				q = q.where(StockLevel.location_id == location_id)
			if lot_number:
				q = q.where(StockLevel.lot_number == lot_number)

			sl = session.execute(q).scalar_one_or_none()
			if sl is None:
				raise StockNotFoundError(
					f"No StockLevel for product={product_id!r} wh={warehouse_id!r}"
				)

			on_hand = _d(sl.quantity_on_hand)
			if on_hand < qty:
				sku = product.sku if product else product_id
				raise InsufficientStockError(
					f"Insufficient stock for {sku!r}: on_hand={on_hand} requested={qty}"
				)

			unit_cost = sl.average_cost_cents
			total_cost = _cents(qty, unit_cost)

			# Create ISSUE movement (immutable)
			movement = StockMovement(
				tenant_id=tenant_id or sl.tenant_id,
				product_id=product_id,
				warehouse_id=warehouse_id,
				from_location_id=location_id,
				to_location_id=None,
				movement_type="ISSUE",
				quantity=qty,
				direction=-1,
				unit_cost_cents=unit_cost,
				total_cost_cents=total_cost,
				lot_number=lot_number,
				serial_number=line.get("serial_number"),
				reference_type=self._order_type_to_ref(order_type),
				reference_id=order_id,
				moved_by=issued_by,
				moved_at=_now(),
			)
			session.add(movement)

			# Update StockLevel
			sl.quantity_on_hand = on_hand - qty
			reserved = _d(sl.quantity_reserved)
			# Reduce reservation if it was pre-allocated
			if reserved >= qty:
				sl.quantity_reserved = reserved - qty
			else:
				sl.quantity_reserved = Decimal("0")
			sl.quantity_available = _d(sl.quantity_on_hand) - _d(sl.quantity_reserved)
			sl.last_movement_at = _now()
			sl.last_movement_date = _today()
			sl.updated_at = _now()
			if product is not None:
				product.qty_issued_ytd = _d(product.qty_issued_ytd or 0) + qty
				product.updated_at = _now()

			movements.append(movement)

			session.flush()

			emit_event(
				StockIssuedEvent(
					aggregate_id=movement.id,
					aggregate_type="StockMovement",
					tenant_id=tenant_id or sl.tenant_id,
					movement_id=movement.id,
					product_id=product_id,
					warehouse_id=warehouse_id,
					from_location_id=location_id or "",
					quantity=str(qty),
					unit_cost_cents=unit_cost,
					total_cost_cents=total_cost,
					lot_number=lot_number or "",
					reference_type=self._order_type_to_ref(order_type),
					reference_id=order_id,
				),
				session,
			)

		log.info(
			"InventoryService.issue_stock: order=%s type=%s movements=%d",
			order_id, order_type, len(movements),
		)
		return movements

	# ------------------------------------------------------------------
	# pick_and_ship (warehouse façade — delegates to issue_stock)
	# ------------------------------------------------------------------

	def pick_and_ship(self, picklist_id: str, session: Any) -> list[Any]:
		"""Complete a PickList: issue stock for all COMPLETED pick lines.

		Reads the PickList and its lines from the WMS plugin, then calls
		issue_stock() for lines that have been fully picked.

		Args:
			picklist_id: UUID of the PickList.
			session: SQLAlchemy session.

		Returns:
			List of StockMovement rows created.
		"""
		from pgappforge.plugins.erp.operations.warehouse.models import PickList

		pl = session.get(PickList, picklist_id)
		if pl is None:
			raise InventoryServiceError(f"PickList {picklist_id!r} not found")
		if pl.status not in ("IN_PROGRESS", "COMPLETED"):
			raise InventoryServiceError(
				f"PickList {picklist_id!r} must be IN_PROGRESS or COMPLETED; got {pl.status!r}"
			)

		lines = [
			{
				"product_id": line.product_id,
				"warehouse_id": str(pl.warehouse_id),
				"quantity": line.quantity_picked,
				"location_id": line.location_id,
				"lot_number": line.lot_number,
				"serial_number": line.serial_number,
			}
			for line in pl.lines
			if _d(line.quantity_picked) > 0
		]

		if not lines:
			raise InventoryServiceError(f"PickList {picklist_id!r} has no picked quantities")

		movements = self.issue_stock(
			order_id=str(pl.order_id),
			order_type=pl.order_type,
			lines=lines,
			session=session,
			tenant_id=pl.tenant_id,
		)

		pl.status = "COMPLETED"
		pl.updated_at = _now()
		return movements

	# ------------------------------------------------------------------
	# run_stock_count
	# ------------------------------------------------------------------

	def run_stock_count(self, warehouse_id: str, session: Any) -> Any:
		"""Freeze stock levels and populate a new FULL StockCount with expected quantities.

		Creates a StockCount header (status=IN_PROGRESS) and one StockCountLine
		per (product, location) in the warehouse with non-zero quantity_on_hand.

		Args:
			warehouse_id: UUID of the warehouse to count.
			session: SQLAlchemy session.

		Returns:
			StockCount instance.
		"""
		from pgappforge.plugins.erp.operations.warehouse.models import StockCount, StockCountLine
		from pgappforge.plugins.erp.operations.inventory.models import StockLevel
		from pgappforge.plugins.erp.operations.warehouse.events import StockCountStartedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		# Resolve tenant from warehouse
		from pgappforge.plugins.erp.operations.inventory.models import Warehouse
		wh = session.get(Warehouse, warehouse_id)
		if wh is None:
			raise WarehouseNotFoundError(f"Warehouse {warehouse_id!r} not found")

		tenant_id = wh.tenant_id

		# Fetch all stock levels for this warehouse
		stock_levels = session.execute(
			sa.select(StockLevel)
			.where(StockLevel.warehouse_id == warehouse_id)
			.where(StockLevel.tenant_id == tenant_id)
			.where(StockLevel.quantity_on_hand > 0)
		).scalars().all()

		count = StockCount(
			tenant_id=tenant_id,
			warehouse_id=warehouse_id,
			count_date=_today(),
			count_type="FULL",
			status="IN_PROGRESS",
		)
		session.add(count)
		session.flush()

		for sl in stock_levels:
			line = StockCountLine(
				tenant_id=tenant_id,
				stock_count_id=count.id,
				product_id=sl.product_id,
				location_id=sl.location_id,
				lot_number=sl.lot_number,
				expiry_date=sl.expiry_date,
				expected_quantity=sl.quantity_on_hand,
				counted_quantity=None,
				variance=Decimal("0"),
				variance_value_cents=0,
			)
			session.add(line)

		emit_event(
			StockCountStartedEvent(
				aggregate_id=count.id,
				aggregate_type="StockCount",
				tenant_id=str(tenant_id),
				stock_count_id=count.id,
				warehouse_id=warehouse_id,
				count_type="FULL",
				count_date=_today().isoformat(),
			),
			session,
		)

		log.info(
			"InventoryService.run_stock_count: wh=%s lines=%d",
			warehouse_id, len(stock_levels),
		)
		return count

	# ------------------------------------------------------------------
	# approve_stock_count
	# ------------------------------------------------------------------

	def approve_stock_count(
		self,
		stock_count_id: str,
		approved_by: str,
		session: Any,
	) -> Any:
		"""Approve a completed stock count and post COUNT_ADJUSTMENT movements.

		For every line with variance != 0:
		  - Creates an immutable StockMovement (type=COUNT_ADJUSTMENT)
		  - direction=1 if variance > 0 (gain), direction=-1 if variance < 0 (loss)
		  - Updates StockLevel.quantity_on_hand

		Sets StockCount.status = APPROVED.
		Emits StockCountApprovedEvent.

		Returns updated StockCount.
		"""
		from pgappforge.plugins.erp.operations.warehouse.models import StockCount, StockCountLine
		from pgappforge.plugins.erp.operations.inventory.models import StockMovement, StockLevel
		from pgappforge.plugins.erp.operations.inventory.events import StockCountApprovedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		count = session.get(StockCount, stock_count_id)
		if count is None:
			raise InventoryServiceError(f"StockCount {stock_count_id!r} not found")
		if count.status != "COMPLETED":
			raise InventoryServiceError(
				f"StockCount {stock_count_id!r} must be COMPLETED before approval; got {count.status!r}"
			)

		total_variance_cents = 0
		lines_adjusted = 0

		for line in count.lines:
			if line.counted_quantity is None:
				continue
			variance = _d(line.counted_quantity) - _d(line.expected_quantity)
			if variance == 0:
				continue

			# Calculate variance value
			# Look up current average cost for this product
			sl_q = (
				sa.select(StockLevel)
				.where(StockLevel.product_id == line.product_id)
				.where(StockLevel.warehouse_id == count.warehouse_id)
			)
			if line.location_id:
				sl_q = sl_q.where(StockLevel.location_id == line.location_id)
			sl = session.execute(sl_q).scalar_one_or_none()
			avg_cost = sl.average_cost_cents if sl else 0

			variance_cents = _cents(abs(variance), avg_cost)
			if variance < 0:
				variance_cents = -variance_cents
			total_variance_cents += variance_cents

			# Update count line
			line.variance = variance
			line.variance_value_cents = variance_cents

			direction = 1 if variance > 0 else -1
			movement = StockMovement(
				tenant_id=count.tenant_id,
				product_id=line.product_id,
				warehouse_id=count.warehouse_id,
				from_location_id=line.location_id if direction == -1 else None,
				to_location_id=line.location_id if direction == 1 else None,
				movement_type="COUNT_ADJUSTMENT",
				quantity=abs(variance),
				direction=direction,
				unit_cost_cents=avg_cost,
				total_cost_cents=abs(variance_cents),
				lot_number=line.lot_number,
				expiry_date=line.expiry_date,
				reference_type="MANUAL",
				reference_id=stock_count_id,
				notes=f"Stock count {stock_count_id} adjustment",
				moved_by=approved_by,
				moved_at=_now(),
			)
			session.add(movement)

			# Update StockLevel
			if sl is not None:
				sl.quantity_on_hand = _d(sl.quantity_on_hand) + variance
				sl.quantity_available = _d(sl.quantity_on_hand) - _d(sl.quantity_reserved)
				sl.last_movement_at = _now()
				sl.updated_at = _now()

			lines_adjusted += 1

		count.status = "APPROVED"
		count.approved_by = approved_by
		count.approved_at = _now()
		count.total_variance_value_cents = total_variance_cents
		count.updated_at = _now()

		session.flush()

		emit_event(
			StockCountApprovedEvent(
				aggregate_id=stock_count_id,
				aggregate_type="StockCount",
				tenant_id=str(count.tenant_id),
				stock_count_id=stock_count_id,
				warehouse_id=str(count.warehouse_id),
				count_type=count.count_type,
				lines_adjusted=lines_adjusted,
				total_variance_value_cents=total_variance_cents,
				approved_by=approved_by,
			),
			session,
		)

		log.info(
			"InventoryService.approve_stock_count: count=%s adjusted=%d variance=%d¢",
			stock_count_id, lines_adjusted, total_variance_cents,
		)
		return count

	# ------------------------------------------------------------------
	# get_stock_valuation
	# ------------------------------------------------------------------

	def get_stock_valuation(
		self,
		warehouse_id: str,
		as_of_date: date | None,
		session: Any,
		tenant_id: str = "",
	) -> dict:
		"""Compute inventory valuation for a warehouse as of a given date.

		Uses StockLevel.average_cost_cents × quantity_on_hand for current
		valuation.  For historical as_of_date, reconstructs from StockMovement
		event log (slower — only triggered when as_of_date != today).

		Returns:
		  {
		    "warehouse_id": str,
		    "as_of_date": str,       # ISO date
		    "total_value_cents": int,
		    "lines": [
		      {"product_id", "sku", "quantity_on_hand", "average_cost_cents",
		       "total_value_cents", "currency_code"},
		      ...
		    ],
		    "computed_at": str,      # ISO timestamp
		  }
		"""
		from pgappforge.plugins.erp.operations.inventory.models import StockLevel, Product

		as_of = as_of_date or _today()
		use_historical = as_of < _today()

		if use_historical:
			return self._get_historical_valuation(warehouse_id, as_of, session, tenant_id)

		# Current valuation from StockLevel
		q = (
			sa.select(StockLevel, Product)
			.join(Product, StockLevel.product_id == Product.id)
			.where(StockLevel.warehouse_id == warehouse_id)
			.where(StockLevel.quantity_on_hand > 0)
		)
		if tenant_id:
			q = q.where(StockLevel.tenant_id == tenant_id)

		rows = session.execute(q).all()

		lines = []
		total_cents = 0
		for sl, prod in rows:
			qty = _d(sl.quantity_on_hand)
			cost = sl.average_cost_cents
			line_value = _cents(qty, cost)
			total_cents += line_value
			lines.append({
				"product_id": sl.product_id,
				"sku": prod.sku,
				"name": prod.name,
				"quantity_on_hand": str(qty),
				"average_cost_cents": cost,
				"total_value_cents": line_value,
				"currency_code": prod.currency_code,
				"location_id": sl.location_id,
				"lot_number": sl.lot_number,
			})

		assert isinstance(total_cents, int), "total_cents must be int"

		return {
			"warehouse_id": warehouse_id,
			"as_of_date": as_of.isoformat(),
			"total_value_cents": total_cents,
			"lines": lines,
			"computed_at": _now().isoformat(),
		}

	def _get_historical_valuation(
		self,
		warehouse_id: str,
		as_of: date,
		session: Any,
		tenant_id: str,
	) -> dict:
		"""Reconstruct stock valuation as of as_of date from StockMovement log."""
		from pgappforge.plugins.erp.operations.inventory.models import StockMovement, Product

		cutoff = datetime(as_of.year, as_of.month, as_of.day, 23, 59, 59, tzinfo=timezone.utc)

		# Aggregate net quantity and weighted cost per product/location
		q = (
			sa.select(
				StockMovement.product_id,
				StockMovement.to_location_id,
				sa.func.sum(
					StockMovement.quantity * StockMovement.direction
				).label("net_qty"),
				sa.func.sum(
					StockMovement.total_cost_cents * StockMovement.direction
				).label("net_cost_cents"),
			)
			.where(StockMovement.warehouse_id == warehouse_id)
			.where(StockMovement.moved_at <= cutoff)
			.group_by(StockMovement.product_id, StockMovement.to_location_id)
		)
		if tenant_id:
			q = q.where(StockMovement.tenant_id == tenant_id)

		rows = session.execute(q).all()

		lines = []
		total_cents = 0
		for row in rows:
			net_qty = _d(row.net_qty or 0)
			if net_qty <= 0:
				continue
			net_cost = int(row.net_cost_cents or 0)
			avg_cost = int(Decimal(net_cost) / net_qty) if net_qty > 0 else 0
			line_value = _cents(net_qty, avg_cost)
			total_cents += line_value

			product = session.get(Product, row.product_id)
			lines.append({
				"product_id": str(row.product_id),
				"sku": product.sku if product else "?",
				"name": product.name if product else "?",
				"quantity_on_hand": str(net_qty),
				"average_cost_cents": avg_cost,
				"total_value_cents": line_value,
				"location_id": str(row.to_location_id) if row.to_location_id else None,
			})

		assert isinstance(total_cents, int), "total_cents must be int"
		return {
			"warehouse_id": warehouse_id,
			"as_of_date": as_of.isoformat(),
			"total_value_cents": total_cents,
			"lines": lines,
			"computed_at": _now().isoformat(),
			"method": "historical_reconstruction",
		}

	# ------------------------------------------------------------------
	# calculate_reorder_suggestions
	# ------------------------------------------------------------------

	def calculate_reorder_suggestions(
		self,
		tenant_id: str,
		session: Any,
	) -> list[dict]:
		"""Identify products that have crossed their reorder point.

		Joins StockLevel with Product on the same tenant.
		Returns products where:
		  quantity_available <= reorder_point AND is_active=True

		Returns:
		  [
		    {
		      "product_id": str,
		      "sku": str,
		      "name": str,
		      "warehouse_id": str,
		      "quantity_available": str,
		      "reorder_point": str,
		      "reorder_quantity": str,
		      "lead_time_days": int,
		      "estimated_cost_cents": int,  # reorder_quantity × cost_price_cents
		    },
		    ...
		  ]
		"""
		from pgappforge.plugins.erp.operations.inventory.models import StockLevel, Product

		q = (
			sa.select(StockLevel, Product)
			.join(Product, StockLevel.product_id == Product.id)
			.where(StockLevel.tenant_id == tenant_id)
			.where(Product.tenant_id == tenant_id)
			.where(Product.is_active.is_(True))
			.where(Product.reorder_point > 0)
			.where(StockLevel.quantity_available <= Product.reorder_point)
		)

		rows = session.execute(q).all()

		suggestions = []
		for sl, prod in rows:
			reorder_qty = _d(prod.reorder_quantity)
			est_cost = _cents(reorder_qty, prod.cost_price_cents)
			assert isinstance(est_cost, int), "estimated_cost_cents must be int"
			suggestions.append({
				"product_id": str(sl.product_id),
				"sku": prod.sku,
				"name": prod.name,
				"warehouse_id": str(sl.warehouse_id),
				"quantity_available": str(_d(sl.quantity_available)),
				"reorder_point": str(_d(prod.reorder_point)),
				"reorder_quantity": str(reorder_qty),
				"lead_time_days": prod.lead_time_days,
				"estimated_cost_cents": est_cost,
				"currency_code": prod.currency_code,
				"valuation_method": prod.valuation_method,
			})

		suggestions.sort(key=lambda x: x["sku"])
		log.info(
			"InventoryService.calculate_reorder_suggestions: tenant=%s suggestions=%d",
			tenant_id, len(suggestions),
		)
		return suggestions

	# ------------------------------------------------------------------
	# get_abc_analysis
	# ------------------------------------------------------------------

	def get_abc_analysis(self, tenant_id: str, session: Any) -> dict:
		"""Return ABC inventory classification by annual consumption value.

		annual_consumption_value = qty_issued_ytd × cost_price_cents.
		A covers the top 20% of items by count, B the next 30%, C the rest.
		"""
		from pgappforge.plugins.erp.operations.inventory.models import Product

		q = (
			sa.select(Product)
			.where(Product.tenant_id == tenant_id)
			.where(Product.is_active.is_(True))
		)
		products = session.execute(q).scalars().all()
		values: list[tuple[Any, int]] = []
		for product in products:
			value_cents = _cents(_d(product.qty_issued_ytd or 0), int(product.cost_price_cents or 0))
			values.append((product, value_cents))

		values.sort(key=lambda item: item[1], reverse=True)
		total_count = len(values)
		total_value_cents = int(sum(value for _, value in values))
		if total_count == 0:
			return {
				"A": 0,
				"B": 0,
				"C": 0,
				"A_value_cents": 0,
				"total_value_cents": 0,
			}

		a_count = min(total_count, max(1, math.ceil(total_count * 0.20)))
		b_count = min(total_count - a_count, math.ceil(total_count * 0.30))
		c_count = total_count - a_count - b_count
		a_value_cents = int(sum(value for _, value in values[:a_count]))

		return {
			"A": int(a_count),
			"B": int(b_count),
			"C": int(c_count),
			"A_value_cents": a_value_cents,
			"total_value_cents": total_value_cents,
		}

	# ------------------------------------------------------------------
	# _update_stock_level (internal)
	# ------------------------------------------------------------------

	def _update_stock_level(
		self,
		product_id: str,
		warehouse_id: str,
		location_id: str | None,
		lot_number: str | None,
		expiry_date: Any,
		qty_delta: Decimal,
		unit_cost_cents: int,
		direction: int,  # 1 or -1
		tenant_id: str,
		session: Any,
	) -> Any:
		"""Upsert StockLevel and update weighted average cost.

		For RECEIPT (direction=1), recomputes average_cost_cents using:
		  new_avg = (old_qty × old_avg + qty_delta × unit_cost) / new_qty

		For ISSUE/WRITE_OFF (direction=-1), average_cost is unchanged.
		"""
		from pgappforge.plugins.erp.operations.inventory.models import StockLevel

		assert direction in (1, -1), "direction must be 1 or -1"
		assert isinstance(unit_cost_cents, int), "unit_cost_cents must be int"

		q = (
			sa.select(StockLevel)
			.where(StockLevel.product_id == product_id)
			.where(StockLevel.warehouse_id == warehouse_id)
			.where(StockLevel.tenant_id == tenant_id)
		)
		if location_id:
			q = q.where(StockLevel.location_id == location_id)
		else:
			q = q.where(StockLevel.location_id.is_(None))
		if lot_number:
			q = q.where(StockLevel.lot_number == lot_number)
		else:
			q = q.where(StockLevel.lot_number.is_(None))

		sl = session.execute(q).scalar_one_or_none()

		if sl is None:
			sl = StockLevel(
				tenant_id=tenant_id,
				product_id=product_id,
				warehouse_id=warehouse_id,
				location_id=location_id,
				lot_number=lot_number,
				expiry_date=expiry_date,
				quantity_on_hand=Decimal("0"),
				quantity_reserved=Decimal("0"),
				quantity_available=Decimal("0"),
				quantity_in_transit=Decimal("0"),
				average_cost_cents=0,
				receipt_date=_today(),
				last_movement_date=_today(),
			)
			session.add(sl)

		old_qty = _d(sl.quantity_on_hand)
		old_avg = sl.average_cost_cents
		new_qty = old_qty + (qty_delta * direction)

		if direction == 1 and new_qty > 0 and unit_cost_cents > 0:
			# Weighted average recomputation
			new_avg = int(
				(
					(old_qty * Decimal(old_avg) + qty_delta * Decimal(unit_cost_cents))
					/ new_qty
				).to_integral_value(rounding=ROUND_HALF_UP)
			)
			sl.average_cost_cents = new_avg

		sl.quantity_on_hand = new_qty
		sl.quantity_available = new_qty - _d(sl.quantity_reserved)
		sl.last_movement_at = _now()
		sl.last_movement_date = _today()
		if direction == 1 and not sl.receipt_date:
			sl.receipt_date = _today()
		sl.updated_at = _now()

		return sl

	# ------------------------------------------------------------------
	# _check_reorder (internal)
	# ------------------------------------------------------------------

	def _check_reorder(
		self,
		product: Any,
		stock_level: Any,
		tenant_id: str,
		session: Any,
		emit_event: Any,
	) -> None:
		"""Emit StockLowEvent if quantity_available <= reorder_point."""
		from pgappforge.plugins.erp.operations.inventory.events import StockLowEvent

		if not product or not product.reorder_point:
			return
		if _d(stock_level.quantity_available) <= _d(product.reorder_point):
			emit_event(
				StockLowEvent(
					aggregate_id=str(product.id),
					aggregate_type="Product",
					tenant_id=tenant_id,
					product_id=str(product.id),
					warehouse_id=str(stock_level.warehouse_id),
					quantity_available=str(_d(stock_level.quantity_available)),
					reorder_point=str(_d(product.reorder_point)),
					reorder_quantity=str(_d(product.reorder_quantity)),
					lead_time_days=product.lead_time_days,
				),
				session,
			)

	# ------------------------------------------------------------------
	# _order_type_to_ref (internal)
	# ------------------------------------------------------------------

	@staticmethod
	def _order_type_to_ref(order_type: str) -> str:
		mapping = {
			"SALES_ORDER": "SO",
			"TRANSFER": "TRANSFER",
			"PRODUCTION": "MANUAL",
		}
		return mapping.get(order_type, "MANUAL")

	# ------------------------------------------------------------------
	# create_transfer_order
	# ------------------------------------------------------------------

	def create_transfer_order(
		self,
		from_location_id: str,
		to_location_id: str,
		lines: list[dict],
		tenant_id: str,
		session: Any,
		*,
		notes: str | None = None,
	) -> Any:
		"""Create a transfer order between two locations.

		lines: [{"product_id": str, "qty": str|Decimal, "unit_cost_cents": int, "lot_number": str|None}]

		Does NOT immediately move stock — call ship_transfer() to deduct from
		the source and receive_transfer() to credit the destination.

		Returns:
			TransferOrder instance (status=DRAFT).
		"""
		from pgappforge.plugins.erp.operations.inventory.models import TransferOrder

		ref = f"TO-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
		order = TransferOrder(
			tenant_id=tenant_id,
			transfer_ref=ref,
			from_location_id=from_location_id,
			to_location_id=to_location_id,
			lines=lines,
			status="DRAFT",
			notes=notes,
		)
		session.add(order)
		session.flush()
		log.info(
			"InventoryService.create_transfer_order: ref=%s from=%s to=%s lines=%d",
			ref, from_location_id, to_location_id, len(lines),
		)
		return order

	# ------------------------------------------------------------------
	# ship_transfer
	# ------------------------------------------------------------------

	def ship_transfer(
		self,
		transfer_id: str,
		session: Any,
	) -> Any:
		"""Ship a transfer order — deduct stock from the source location.

		Transition: DRAFT → SHIPPED (stock now in-transit).

		Decrements quantity_on_hand / quantity_available on the source
		StockLevel for each line.  Does not yet credit the destination —
		that happens in receive_transfer().

		Raises:
			ValueError: TransferOrder not found or not in DRAFT status.
			InsufficientStockError: Source has insufficient on-hand quantity.
		"""
		from pgappforge.plugins.erp.operations.inventory.models import TransferOrder

		order = session.execute(
			sa.select(TransferOrder).where(TransferOrder.id == transfer_id)
		).scalar_one_or_none()
		if order is None:
			raise ValueError(f"TransferOrder {transfer_id!r} not found")
		if order.status != "DRAFT":
			raise ValueError(f"Cannot ship TransferOrder in status {order.status!r}")

		for line in order.lines:
			qty = _d(str(line["qty"]))
			assert qty > 0, f"Transfer line qty must be positive; got {qty}"
			self._update_stock_level(
				product_id=str(line["product_id"]),
				warehouse_id=str(order.from_location_id),
				location_id=None,
				lot_number=line.get("lot_number"),
				expiry_date=None,
				qty_delta=qty,
				unit_cost_cents=int(line.get("unit_cost_cents", 0)),
				direction=-1,
				tenant_id=str(order.tenant_id),
				session=session,
			)

		order.status = "SHIPPED"
		order.shipped_at = datetime.now(timezone.utc)
		order.updated_at = datetime.now(timezone.utc)
		session.flush()
		log.info("InventoryService.ship_transfer: id=%s", transfer_id)
		return order

	# ------------------------------------------------------------------
	# receive_transfer
	# ------------------------------------------------------------------

	def receive_transfer(
		self,
		transfer_id: str,
		session: Any,
	) -> Any:
		"""Receive a transfer order — add stock to the destination location.

		Transition: SHIPPED → RECEIVED.

		Credits quantity_on_hand / quantity_available on the destination
		StockLevel for each line and updates weighted average cost.

		Raises:
			ValueError: TransferOrder not found or not in SHIPPED status.
		"""
		from pgappforge.plugins.erp.operations.inventory.models import TransferOrder, CostLayer

		order = session.execute(
			sa.select(TransferOrder).where(TransferOrder.id == transfer_id)
		).scalar_one_or_none()
		if order is None:
			raise ValueError(f"TransferOrder {transfer_id!r} not found")
		if order.status != "SHIPPED":
			raise ValueError(f"Cannot receive TransferOrder in status {order.status!r}")

		for line in order.lines:
			qty = _d(str(line["qty"]))
			assert qty > 0, f"Transfer line qty must be positive; got {qty}"
			unit_cost = int(line.get("unit_cost_cents", 0))
			self._update_stock_level(
				product_id=str(line["product_id"]),
				warehouse_id=str(order.to_location_id),
				location_id=None,
				lot_number=line.get("lot_number"),
				expiry_date=None,
				qty_delta=qty,
				unit_cost_cents=unit_cost,
				direction=1,
				tenant_id=str(order.tenant_id),
				session=session,
			)
			# Record cost layer at destination for FIFO/LIFO continuity
			if unit_cost > 0:
				session.add(CostLayer(
					tenant_id=str(order.tenant_id),
					product_id=str(line["product_id"]),
					warehouse_id=str(order.to_location_id),
					received_qty=qty,
					unit_cost_cents=unit_cost,
					remaining_qty=qty,
					source_grn_id=None,
				))

		order.status = "RECEIVED"
		order.received_at = datetime.now(timezone.utc)
		order.updated_at = datetime.now(timezone.utc)
		session.flush()
		log.info("InventoryService.receive_transfer: id=%s", transfer_id)
		return order


__all__ = [
	"InventoryService",
	"InventoryServiceError",
	"InsufficientStockError",
	"StockNotFoundError",
	"ProductNotFoundError",
	"WarehouseNotFoundError",
]
