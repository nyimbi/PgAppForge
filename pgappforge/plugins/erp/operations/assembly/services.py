"""
pgappforge/plugins/erp/operations/assembly/services.py

AssemblyService — stateless business logic for Assembly Management.

All methods receive an explicit SQLAlchemy session; no Flask context assumed.
Transaction boundaries owned by the caller.

Monetary invariants:
  - All amounts passed in and returned as integer cents (BigInteger)
  - Decimal arithmetic used internally; results rounded ROUND_HALF_UP to int
  - Quantities use Decimal(str(...)) — never float

BPM registrations:
  ops.assembly.post   — Post assembly order: consume components, add finished goods

Public API:
  create_assembly_order(output_product_id, output_qty, warehouse_id, components,
                        tenant_id, session, *, planned_date=None) -> AssemblyOrder
  post_assembly(order_id, session) -> AssemblyOrder
  cancel_assembly(order_id, reason, session) -> AssemblyOrder
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import sqlalchemy as sa

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# BPM action registry (best-effort, no hard dep on BPM plugin)
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

class AssemblyServiceError(Exception):
	"""Base domain error for assembly operations."""


class AssemblyOrderNotFoundError(AssemblyServiceError):
	pass


class AssemblyInvalidStatusError(AssemblyServiceError):
	pass


class AssemblyInsufficientStockError(AssemblyServiceError):
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
	"""qty × unit_cost_cents, rounded ROUND_HALF_UP to int."""
	assert isinstance(unit_cost_cents, int), "unit_cost_cents must be int"
	return int(
		(qty * Decimal(unit_cost_cents)).to_integral_value(rounding=ROUND_HALF_UP)
	)


def _now() -> datetime:
	return datetime.now(timezone.utc)


def _emit(event: Any, session: Any = None) -> None:
	"""Emit domain event; swallow all errors to protect the business transaction."""
	try:
		from pgappforge.plugins.erp.foundation.events import emit_event
		emit_event(event, session)
	except Exception as exc:
		log.debug("AssemblyService._emit: non-fatal event emission failure: %s", exc)


# ---------------------------------------------------------------------------
# AssemblyService
# ---------------------------------------------------------------------------

class AssemblyService:
	"""Stateless assembly domain service.

	Instantiate once per application (no instance state).
	All public methods accept an explicit SQLAlchemy Session.

	Stock mutations delegate to InventoryService._update_stock_level() via a
	soft import (cross-plugin boundary); if inventory plugin is not loaded the
	service raises AssemblyServiceError to halt posting.
	"""

	# ------------------------------------------------------------------
	# create_assembly_order
	# ------------------------------------------------------------------

	def create_assembly_order(
		self,
		output_product_id: str,
		output_qty: Any,
		warehouse_id: str,
		components: list[dict[str, Any]],
		tenant_id: str,
		session: Any,
		*,
		planned_date: date | None = None,
	) -> Any:
		"""Create a new AssemblyOrder in DRAFT status with component lines.

		Args:
			output_product_id: Soft FK → inv_product.id for the finished good.
			output_qty: Quantity of finished goods to produce (Decimal-coercible).
			warehouse_id: Soft FK → inv_warehouse.id for production warehouse.
			components: List of dicts: [{product_id, planned_qty, unit_cost_cents?}].
			tenant_id: Tenant scoping string.
			session: SQLAlchemy session (caller commits).
			planned_date: Optional target production date.

		Returns:
			The created AssemblyOrder instance (status=DRAFT).

		Raises:
			AssemblyServiceError: If components list is empty or qty <= 0.
		"""
		from pgappforge.plugins.erp.operations.assembly.models import (
			AssemblyOrder, AssemblyLine,
		)
		from pgappforge.plugins.erp.operations.assembly.events import (
			AssemblyOrderCreatedEvent,
		)

		output_qty_d = _d(output_qty)
		assert output_qty_d > 0, "output_qty must be positive"
		assert components, "components list must not be empty"

		# Compute standard_cost_cents = sum(planned_qty × unit_cost_cents)
		standard_cost = 0
		lines_data: list[tuple[str, Decimal, int]] = []
		for comp in components:
			pid = str(comp["product_id"])
			pqty = _d(comp["planned_qty"])
			ucost = int(comp.get("unit_cost_cents", 0))
			assert pqty > 0, f"planned_qty must be positive for component {pid!r}"
			standard_cost += _cents(pqty, ucost)
			lines_data.append((pid, pqty, ucost))

		order = AssemblyOrder(
			tenant_id=tenant_id,
			output_product_id=output_product_id,
			output_qty=output_qty_d,
			warehouse_id=warehouse_id,
			status="DRAFT",
			planned_date=planned_date,
			standard_cost_cents=standard_cost,
			actual_cost_cents=0,
			variance_cents=0,
		)
		session.add(order)
		session.flush()  # populate order.id

		for pid, pqty, ucost in lines_data:
			session.add(AssemblyLine(
				tenant_id=tenant_id,
				order_id=order.id,
				component_product_id=pid,
				planned_qty=pqty,
				actual_qty=None,
				unit_cost_cents=ucost,
				total_cost_cents=0,
			))

		log.info(
			"AssemblyService.create_assembly_order: order=%s product=%s qty=%s lines=%d",
			order.id, output_product_id, output_qty_d, len(lines_data),
		)

		_emit(
			AssemblyOrderCreatedEvent(
				aggregate_id=order.id,
				aggregate_type="AssemblyOrder",
				tenant_id=tenant_id,
				order_id=order.id,
				output_product_id=output_product_id,
				qty=str(output_qty_d),
			),
			session,
		)

		return order

	# ------------------------------------------------------------------
	# post_assembly
	# ------------------------------------------------------------------

	@_register(
		"ops.assembly.post",
		"Post assembly order — consume components and add finished goods",
	)
	def post_assembly(self, order_id: str, session: Any) -> Any:
		"""Post an assembly order: consume components from stock, produce FG.

		Posting steps (all within caller's transaction):
		  1. Load order; assert status in (DRAFT, IN_PROGRESS).
		  2. For each component line:
			 a. Resolve effective consumption qty (actual_qty if set, else planned_qty).
			 b. Consume stock via InventoryService._update_stock_level(..., qty_delta=-qty).
			 c. Determine effective unit cost from StockLevel.average_cost_cents or
				line.unit_cost_cents (whichever is non-zero).
			 d. Set line.actual_qty, line.total_cost_cents.
			 e. Emit AssemblyComponentConsumedEvent.
		  3. Sum actual_cost_cents across lines.
		  4. Add finished goods to stock via InventoryService._update_stock_level(
			   output_product_id, +output_qty, avg_cost=actual_cost/output_qty).
		  5. Compute variance_cents = actual_cost_cents - standard_cost_cents.
		  6. If variance != 0: post GL journal (DR/CR account 5990 Production Variance).
		  7. Set status=POSTED, posted_at=now().
		  8. Emit AssemblyOrderPostedEvent; if variance: emit AssemblyVariancePostedEvent.

		Args:
			order_id: UUID string of the AssemblyOrder to post.
			session: SQLAlchemy session (caller commits).

		Returns:
			The updated AssemblyOrder (status=POSTED).

		Raises:
			AssemblyOrderNotFoundError: order_id not found.
			AssemblyInvalidStatusError: order not in DRAFT/IN_PROGRESS.
			AssemblyInsufficientStockError: insufficient component stock.
		"""
		from pgappforge.plugins.erp.operations.assembly.models import (
			AssemblyOrder, AssemblyLine,
		)
		from pgappforge.plugins.erp.operations.assembly.events import (
			AssemblyOrderPostedEvent,
			AssemblyComponentConsumedEvent,
			AssemblyVariancePostedEvent,
		)

		order = session.execute(
			sa.select(AssemblyOrder).where(AssemblyOrder.id == order_id)
		).scalar_one_or_none()

		if order is None:
			raise AssemblyOrderNotFoundError(f"AssemblyOrder {order_id!r} not found")

		if order.status not in ("DRAFT", "IN_PROGRESS"):
			raise AssemblyInvalidStatusError(
				f"AssemblyOrder {order_id!r} status={order.status!r}; "
				"must be DRAFT or IN_PROGRESS to post"
			)

		tenant_id = order.tenant_id
		warehouse_id = order.warehouse_id

		# Load component lines
		lines = session.execute(
			sa.select(AssemblyLine).where(AssemblyLine.order_id == order_id)
		).scalars().all()

		assert lines, f"AssemblyOrder {order_id!r} has no component lines"

		# Load InventoryService for stock mutations (hard requirement)
		try:
			from pgappforge.plugins.erp.operations.inventory.services import InventoryService
			from pgappforge.plugins.erp.operations.inventory.models import StockLevel
			inv_svc = InventoryService()
		except ImportError as exc:
			raise AssemblyServiceError(
				"Inventory plugin is required for assembly posting but is not loaded"
			) from exc

		total_actual_cents = 0

		for line in lines:
			consume_qty = _d(line.actual_qty if line.actual_qty is not None else line.planned_qty)
			assert consume_qty > 0, (
				f"Component {line.component_product_id!r} consume qty must be positive"
			)

			# Fetch current weighted avg cost from StockLevel (best-effort)
			sl = session.execute(
				sa.select(StockLevel).where(
					StockLevel.product_id == line.component_product_id,
					StockLevel.warehouse_id == warehouse_id,
					StockLevel.tenant_id == tenant_id,
				)
			).scalar_one_or_none()

			effective_unit_cost: int
			if sl is not None and sl.average_cost_cents > 0:
				effective_unit_cost = int(sl.average_cost_cents)
			elif line.unit_cost_cents > 0:
				effective_unit_cost = int(line.unit_cost_cents)
			else:
				effective_unit_cost = 0

			line_cost = _cents(consume_qty, effective_unit_cost)

			# Consume component stock (negative qty_delta)
			try:
				inv_svc._update_stock_level(
					product_id=line.component_product_id,
					warehouse_id=warehouse_id,
					location_id=None,
					lot_number=None,
					expiry_date=None,
					qty_delta=-consume_qty,
					unit_cost_cents=effective_unit_cost,
					direction=-1,
					tenant_id=tenant_id,
					session=session,
				)
			except Exception as exc:
				raise AssemblyInsufficientStockError(
					f"Failed to consume component {line.component_product_id!r} "
					f"qty={consume_qty}: {exc}"
				) from exc

			# Update line with actuals
			line.actual_qty = consume_qty
			line.unit_cost_cents = effective_unit_cost
			line.total_cost_cents = line_cost
			total_actual_cents += line_cost

			_emit(
				AssemblyComponentConsumedEvent(
					aggregate_id=order.id,
					aggregate_type="AssemblyOrder",
					tenant_id=tenant_id,
					order_id=order.id,
					component_id=line.component_product_id,
					qty=str(consume_qty),
					cost_cents=line_cost,
				),
				session,
			)

		# Add finished goods to stock
		output_qty_d = _d(order.output_qty)
		fg_avg_cost_cents: int
		if output_qty_d > 0 and total_actual_cents > 0:
			fg_avg_cost_cents = int(
				(Decimal(total_actual_cents) / output_qty_d).to_integral_value(
					rounding=ROUND_HALF_UP
				)
			)
		else:
			fg_avg_cost_cents = 0

		try:
			inv_svc._update_stock_level(
				product_id=order.output_product_id,
				warehouse_id=warehouse_id,
				location_id=None,
				lot_number=None,
				expiry_date=None,
				qty_delta=output_qty_d,
				unit_cost_cents=fg_avg_cost_cents,
				direction=1,
				tenant_id=tenant_id,
				session=session,
			)
		except Exception as exc:
			raise AssemblyServiceError(
				f"Failed to add finished goods {order.output_product_id!r} "
				f"qty={output_qty_d} to stock: {exc}"
			) from exc

		# Compute variance and post to GL if nonzero
		variance_cents = total_actual_cents - int(order.standard_cost_cents)
		if variance_cents != 0:
			self._post_variance_gl(order, variance_cents, tenant_id, session)

		# Finalise order
		order.actual_cost_cents = total_actual_cents
		order.variance_cents = variance_cents
		order.status = "POSTED"
		order.posted_at = _now()

		log.info(
			"AssemblyService.post_assembly: order=%s posted; actual=%d standard=%d variance=%d",
			order.id, total_actual_cents, order.standard_cost_cents, variance_cents,
		)

		_emit(
			AssemblyOrderPostedEvent(
				aggregate_id=order.id,
				aggregate_type="AssemblyOrder",
				tenant_id=tenant_id,
				order_id=order.id,
				output_product_id=order.output_product_id,
				qty=str(output_qty_d),
				cost_cents=total_actual_cents,
			),
			session,
		)

		if variance_cents != 0:
			_emit(
				AssemblyVariancePostedEvent(
					aggregate_id=order.id,
					aggregate_type="AssemblyOrder",
					tenant_id=tenant_id,
					order_id=order.id,
					variance_cents=variance_cents,
				),
				session,
			)

		return order

	# ------------------------------------------------------------------
	# cancel_assembly
	# ------------------------------------------------------------------

	def cancel_assembly(self, order_id: str, reason: str, session: Any) -> Any:
		"""Cancel an assembly order that has not yet been posted.

		Args:
			order_id: UUID string of the AssemblyOrder to cancel.
			reason: Human-readable cancellation reason.
			session: SQLAlchemy session (caller commits).

		Returns:
			The updated AssemblyOrder (status=CANCELLED).

		Raises:
			AssemblyOrderNotFoundError: order not found.
			AssemblyInvalidStatusError: order is POSTED (cannot cancel).
		"""
		from pgappforge.plugins.erp.operations.assembly.models import AssemblyOrder
		from pgappforge.plugins.erp.operations.assembly.events import AssemblyOrderCancelledEvent

		order = session.execute(
			sa.select(AssemblyOrder).where(AssemblyOrder.id == order_id)
		).scalar_one_or_none()

		if order is None:
			raise AssemblyOrderNotFoundError(f"AssemblyOrder {order_id!r} not found")

		if order.status == "POSTED":
			raise AssemblyInvalidStatusError(
				f"AssemblyOrder {order_id!r} is POSTED; cannot cancel after posting"
			)
		if order.status == "CANCELLED":
			return order  # idempotent

		order.status = "CANCELLED"
		log.info("AssemblyService.cancel_assembly: order=%s reason=%r", order.id, reason)

		_emit(
			AssemblyOrderCancelledEvent(
				aggregate_id=order.id,
				aggregate_type="AssemblyOrder",
				tenant_id=order.tenant_id,
				order_id=order.id,
				reason=reason,
			),
			session,
		)

		return order

	# ------------------------------------------------------------------
	# Internal: GL variance posting
	# ------------------------------------------------------------------

	def _post_variance_gl(
		self,
		order: Any,
		variance_cents: int,
		tenant_id: str,
		session: Any,
	) -> None:
		"""Post production variance to GL account 5990.

		Positive variance (over-cost): DR Production Variance 5990, CR WIP/Assembly Clearing
		Negative variance (under-cost): DR WIP/Assembly Clearing, CR Production Variance 5990

		Non-fatal: GL plugin absence is logged at DEBUG level only.
		"""
		try:
			from pgappforge.plugins.erp.finance.gl.services import GLService
			gl_svc = GLService()
			abs_variance = abs(variance_cents)
			if variance_cents > 0:
				# Over-cost: DR Production Variance / CR WIP Clearing
				dr_acct, cr_acct = "5990", "5980"
			else:
				# Under-cost: DR WIP Clearing / CR Production Variance
				dr_acct, cr_acct = "5980", "5990"
			gl_svc.post_simple_journal(
				lines=[
					{"account_code": dr_acct, "debit_cents": abs_variance, "credit_cents": 0},
					{"account_code": cr_acct, "debit_cents": 0, "credit_cents": abs_variance},
				],
				session=session,
				tenant_id=tenant_id,
				description=f"Assembly variance — order {order.id}",
				source_doc_id=order.id,
				source_doc_type="ASSEMBLY_ORDER",
			)
			log.info(
				"AssemblyService._post_variance_gl: order=%s variance=%d GL posted",
				order.id, variance_cents,
			)
		except ImportError:
			log.debug(
				"AssemblyService._post_variance_gl: GL plugin not loaded; "
				"variance %d for order %s not posted to ledger",
				variance_cents, order.id,
			)
		except Exception as exc:
			log.debug(
				"AssemblyService._post_variance_gl: GL posting failed (non-fatal): %s", exc
			)


__all__ = [
	"AssemblyService",
	"AssemblyServiceError",
	"AssemblyOrderNotFoundError",
	"AssemblyInvalidStatusError",
	"AssemblyInsufficientStockError",
]
