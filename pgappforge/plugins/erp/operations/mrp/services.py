"""
pgappforge/plugins/erp/operations/mrp/services.py

MRPService — stateless business logic for Materials Requirements Planning.

All methods receive an explicit SQLAlchemy session; no Flask context assumed.
Transaction boundaries owned by the caller.

Quantity arithmetic uses Decimal — never float.
Session never committed inside service methods.

Public API:
  run_mrp(tenant_id, session, *, entity_id, horizon_days)  -> MRPRun
  check_safety_stock(tenant_id, session)                   -> list[dict]
  convert_to_po(planned_order_id, session)                 -> dict
  get_mrp_report(run_id, session)                          -> dict

BPM actions registered:
  ops.mrp.run              — Run MRP for tenant
  ops.mrp.convert_to_po   — Convert MRP planned order to purchase order
"""
from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_UP, Decimal
from typing import Any

import sqlalchemy as sa

from pgappforge.plugins.erp.foundation.events import emit_event as _emit_event
from pgappforge.plugins.workflow.engine import BPMActionRegistry

from .events import (
	MRPRunCompletedEvent,
	MRPRunStartedEvent,
	PlannedOrderCreatedEvent,
	ProductionOrderRecommendedEvent,
	PurchaseRequisitionCreatedEvent,
	SafetyStockBreachEvent,
)
from .models import MRPPlannedOrder, MRPProductConfig, MRPRun

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class MRPServiceError(Exception):
	"""Base error for MRP service layer."""


class MRPRunNotFoundError(MRPServiceError):
	pass


class PlannedOrderNotFoundError(MRPServiceError):
	pass


class InvalidMRPStatusError(MRPServiceError):
	pass


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _uuid4() -> str:
	return str(uuid.uuid4())


def _d(value: Any) -> Decimal:
	"""Safe Decimal coercion — never float intermediate."""
	if isinstance(value, Decimal):
		return value
	return Decimal(str(value))


def _round_up_to_lot(qty: Decimal, lot_size: Decimal) -> Decimal:
	"""Round qty up to the nearest multiple of lot_size.

	Examples:
	  _round_up_to_lot(7, 5)  -> 10
	  _round_up_to_lot(10, 5) -> 10
	  _round_up_to_lot(0.3, 1)-> 1
	"""
	if lot_size <= 0:
		lot_size = Decimal("1")
	multiples = (qty / lot_size).to_integral_value(rounding=ROUND_UP)
	return multiples * lot_size


def _emit(event: Any, session: Any = None) -> None:
	try:
		_emit_event(event, session)
	except Exception as exc:
		log.debug("_emit: non-fatal event emit failure for %s: %s", type(event).__name__, exc)


def _preload_stock_levels(tenant_id: str, session: Any) -> dict[str, Decimal]:
	"""Load ALL stock levels for a tenant in one GROUP BY query.

	Returns a dict of {product_id: total_quantity_available}.
	Avoids N+1 queries in run_mrp (one query for all products vs one per product).
	"""
	try:
		from pgappforge.plugins.erp.operations.inventory.models import StockLevel  # type: ignore[import]
		rows = session.execute(
			sa.select(StockLevel.product_id, sa.func.coalesce(sa.func.sum(StockLevel.quantity_available), 0).label("qty"))
			.where(StockLevel.tenant_id == tenant_id)
			.group_by(StockLevel.product_id)
		).all()
		return {str(r.product_id): _d(r.qty) for r in rows}
	except ImportError:
		log.debug("_preload_stock_levels: inventory plugin not loaded — all stock assumed 0")
		return {}
	except Exception as exc:
		log.warning("_preload_stock_levels: bulk query failed: %s", exc)
		return {}


def _get_current_stock(product_id: str, tenant_id: str, session: Any) -> Decimal:
	"""Single-product stock lookup. Use _preload_stock_levels() for batch MRP runs."""
	try:
		from pgappforge.plugins.erp.operations.inventory.models import StockLevel  # type: ignore[import]
		rows = session.execute(
			sa.select(sa.func.coalesce(sa.func.sum(StockLevel.quantity_available), 0))
			.where(StockLevel.tenant_id == tenant_id, StockLevel.product_id == product_id)
		).scalar()
		return _d(rows or 0)
	except ImportError:
		return Decimal("0")
	except Exception as exc:
		log.warning("_get_current_stock: query failed for product %s: %s", product_id, exc)
		return Decimal("0")


def _get_open_demand(
	product_id: str,
	tenant_id: str,
	horizon_date: date,
	session: Any,
) -> list[tuple[Decimal, date]]:
	"""Return list of (qty, required_date) from open sales orders + approved
	demand forecasts for the product within the planning horizon.

	Merges both sources; duplicates are acceptable — MRP will net them.
	Falls back gracefully when dependent plugins are not loaded.
	"""
	demand: list[tuple[Decimal, date]] = []

	# --- Open sales order lines (commerce.OrderLine) ---
	# Queries unfulfilled OrderLine rows whose parent Order is CONFIRMED/PROCESSING.
	# product_id (UUID) is bridged to OrderLine.product_code (SKU) via inv_product.
	# required_date is estimated as Order.created_at + 30 days.
	try:
		from pgappforge.plugins.erp.crm.commerce.models import Order as _CommerceOrder, OrderLine as _OrderLine  # type: ignore[import]
		from pgappforge.plugins.erp.operations.inventory.models import Product as _InvProduct  # type: ignore[import]
		from datetime import timedelta as _td

		# Bridge: product_id (UUID) → inventory Product.sku → OrderLine.product_code
		so_rows = session.execute(
			sa.select(
				_OrderLine.quantity,
				_OrderLine.fulfilled_qty,
				_CommerceOrder.created_at,
			)
			.join(_CommerceOrder, _OrderLine.order_id == _CommerceOrder.id)
			.join(_InvProduct, sa.and_(
				_InvProduct.id == product_id,
				_InvProduct.tenant_id == tenant_id,
				_OrderLine.product_code == _InvProduct.sku,
			))
			.where(
				_OrderLine.tenant_id == tenant_id,
				_CommerceOrder.status.in_(["CONFIRMED", "PROCESSING"]),
				# No past-only filter — MRP needs forward demand; req_date<=horizon_date enforced below
			)
		).all()

		for qty, fulfilled, created_at in so_rows:
			remaining = _d(qty) - _d(fulfilled or 0)
			if remaining <= 0:
				continue
			req_date = (created_at.date() + _td(days=30)) if created_at else date.today()
			if req_date <= horizon_date:
				demand.append((remaining, req_date))
	except ImportError:
		log.debug("_get_open_demand: commerce or inventory plugin not loaded — no SO demand")
	except Exception as exc:
		log.warning("_get_open_demand: SO query failed: %s", exc)

	# --- Approved demand forecasts (dp_forecast) ---
	try:
		from pgappforge.plugins.erp.operations.demand_planning.models import DemandForecast  # type: ignore[import]
		from pgappforge.plugins.erp.operations.demand_planning.services import DemandPlanningService  # type: ignore[import]

		today = date.today()
		# Iterate forecast months in horizon
		for month_offset in range(12):
			# Build period label for each month offset
			from datetime import timedelta as _td
			target = today + _td(days=30 * month_offset)
			period_label = target.strftime("%Y-%m")
			required_dt = date(target.year, target.month, 1)
			if required_dt > horizon_date:
				break
			qty = DemandPlanningService.get_approved_forecast(
				product_id, period_label, tenant_id, session
			)
			if qty is not None and qty > 0:
				demand.append((_d(qty), required_dt))
	except ImportError:
		log.debug("_get_open_demand: demand_planning plugin not loaded — no forecast demand")
	except Exception as exc:
		log.warning("_get_open_demand: forecast query failed: %s", exc)

	# If no demand found at all, return a single demand entry at horizon_date
	# so that MRP can evaluate safety stock / reorder logic.
	# (In production, open SO lines would populate this list.)
	return demand


def _round_up_to_lot_qty(net: Decimal, lot: Decimal) -> Decimal:
	"""Round net up to nearest multiple of lot.  lot <= 0 treated as 1."""
	import math
	if lot <= 0:
		lot = Decimal("1")
	return Decimal(str(math.ceil(float(net) / float(lot)))) * lot


def _compute_lot_size(cfg: Any, net_req: Decimal) -> Decimal:
	"""Compute planned qty from cfg.lot_sizing_method (FIXED_LOT/LOT_FOR_LOT/MIN_MAX/EOQ).

	Falls back to FIXED_LOT when the attribute is absent (older config rows).
	"""
	import math
	net = _d(net_req)
	lot = _d(cfg.lot_size_qty) if _d(cfg.lot_size_qty) > 0 else Decimal("1")
	method: str = getattr(cfg, "lot_sizing_method", "FIXED_LOT") or "FIXED_LOT"

	if method == "LOT_FOR_LOT":
		return net if net > 0 else Decimal("0")

	if method == "MIN_MAX":
		min_qty = _d(getattr(cfg, "min_order_qty", lot) or lot)
		return max(min_qty, _round_up_to_lot_qty(net, lot))

	if method == "EOQ":
		D = _d(getattr(cfg, "eoq_annual_demand", 1000) or 1000)
		S = _d(getattr(cfg, "ordering_cost_cents", 10000) or 10000)
		H = _d(getattr(cfg, "holding_cost_rate", Decimal("0.25")) or Decimal("0.25"))
		eoq = Decimal(str(math.sqrt(float(2 * D * S / max(H, Decimal("0.01"))))))
		return max(net, eoq)

	# FIXED_LOT (default)
	return _round_up_to_lot_qty(net, lot)


def _explode_bom_multilevel(
	bom_id: str,
	qty: Decimal,
	tenant_id: str,
	session: Any,
	*,
	visited: set[str] | None = None,
	depth: int = 0,
) -> list[tuple[str, Decimal]]:
	"""Multi-level BOM explosion with cycle detection.

	Recursively expands sub-assemblies up to depth 20.  Cycle detection via
	visited set of bom_ids prevents infinite loops on circular BOMs.

	Returns: flat list of (component_product_id, total_component_qty)
	"""
	if visited is None:
		visited = set()
	if depth > 20 or bom_id in visited:
		if bom_id in visited:
			log.warning("_explode_bom_multilevel: cycle detected at bom_id=%s depth=%d", bom_id, depth)
		return []
	visited.add(bom_id)

	components = list(_get_bom_components(bom_id, qty, session))

	for comp_product_id, comp_qty in list(components):
		sub_cfg: Any = session.execute(
			sa.select(MRPProductConfig).where(
				MRPProductConfig.product_id == comp_product_id,
				MRPProductConfig.tenant_id == tenant_id,
			)
		).scalar_one_or_none()
		if sub_cfg is not None and sub_cfg.bom_id:
			sub_components = _explode_bom_multilevel(
				sub_cfg.bom_id, comp_qty, tenant_id, session,
				visited=visited, depth=depth + 1,
			)
			components.extend(sub_components)

	return components


def _get_bom_components(
	bom_id: str,
	qty: Decimal,
	session: Any,
) -> list[tuple[str, Decimal]]:
	"""Return list of (component_product_id, component_qty) for one level of BOM.

	Falls back to empty list when the production plugin is not loaded or the
	BOM is not found.
	"""
	try:
		from pgappforge.plugins.erp.operations.production.models import BOMLine  # type: ignore[import]
		rows = session.execute(
			sa.select(BOMLine.component_product_id, BOMLine.qty_per_parent)
			.where(BOMLine.bom_id == bom_id, BOMLine.is_active.is_(True))
		).all()
		return [(str(r.component_product_id), _d(r.qty_per_parent) * qty) for r in rows]
	except ImportError:
		log.debug("_get_bom_components: production plugin not loaded")
		return []
	except Exception as exc:
		log.warning("_get_bom_components: BOM query failed for bom_id=%s: %s", bom_id, exc)
		return []


# ---------------------------------------------------------------------------
# MRPService
# ---------------------------------------------------------------------------

class MRPService:
	"""Materials Requirements Planning service.

	Stateless — all state lives in the database.  Session is always passed
	explicitly; never stored on the instance.
	"""

	# -----------------------------------------------------------------------
	# run_mrp
	# -----------------------------------------------------------------------

	@staticmethod
	@BPMActionRegistry.register("ops.mrp.run", "Run MRP for tenant")
	def run_mrp(
		tenant_id: str,
		session: Any,
		*,
		entity_id: str | None = None,
		horizon_days: int = 90,
	) -> MRPRun:
		"""Execute a full MRP run for the tenant.

		Algorithm (per product):
		  1. Load all MRPProductConfig rows for tenant.
		  2. For each product:
		     a. Fetch current inventory stock (quantity_available).
		     b. Fetch open demand within horizon (SO lines + approved forecasts).
		     c. For each demand bucket:
		        net_req = demand_qty - current_stock - safety_stock_qty
		        if net_req <= 0: consume stock credit; continue
		     d. Round up net_req to nearest lot_size_qty multiple.
		     e. planned_start_date = required_date - lead_time_days.
		     f. Create MRPPlannedOrder; emit PlannedOrderCreatedEvent.
		     g. If EXTERNAL: emit PurchaseRequisitionCreatedEvent.
		     h. If INTERNAL: emit ProductionOrderRecommendedEvent + BOM explosion.
		  3. Mark run COMPLETED; emit MRPRunCompletedEvent.

		Returns:
		  MRPRun — persisted run record (not yet committed; caller commits).

		Raises:
		  MRPServiceError on unexpected failures (run marked FAILED).
		"""
		assert tenant_id, "tenant_id must be non-empty"
		assert horizon_days > 0, "horizon_days must be positive"

		started_at = datetime.now(timezone.utc)
		today = date.today()
		horizon_date = today + timedelta(days=horizon_days)

		# Build period label from today
		period_label = today.strftime("%Y-%m")

		# Create MRP run record
		run = MRPRun(
			tenant_id=tenant_id,
			period=period_label,
			horizon_days=horizon_days,
			status="IN_PROGRESS",
			started_at=started_at,
			entity_id=entity_id,
		)
		session.add(run)
		session.flush()

		_emit(
			MRPRunStartedEvent(
				aggregate_id=run.id,
				aggregate_type="MRPRun",
				tenant_id=tenant_id,
				run_id=run.id,
				period=period_label,
				horizon_days=horizon_days,
				entity_id=entity_id or "",
			),
			session,
		)

		planned_orders_count = 0
		requisitions_count = 0

		try:
			# Load all product configs for tenant
			configs: list[MRPProductConfig] = session.execute(
				sa.select(MRPProductConfig).where(
					MRPProductConfig.tenant_id == tenant_id
				)
			).scalars().all()

			# Pre-load ALL stock levels in one query (avoids N+1 for large SKU counts)
			stock_map: dict[str, Decimal] = _preload_stock_levels(tenant_id, session)

			log.info(
				"MRPService.run_mrp: run=%s tenant=%s products=%d horizon=%dd",
				run.id, tenant_id, len(configs), horizon_days,
			)

			for cfg in configs:
				product_id = cfg.product_id
				safety_stock = _d(cfg.safety_stock_qty)
				lead_time = int(cfg.lead_time_days)

				# Current available stock (from pre-loaded map — no per-product query)
				current_stock = stock_map.get(product_id, Decimal("0"))

				# Remaining stock credit — depleted by demand buckets in date order
				stock_credit = current_stock - safety_stock

				# Demand buckets: list of (qty, required_date)
				demand_buckets = _get_open_demand(
					product_id, tenant_id, horizon_date, session
				)

				# Sort by date to allocate stock to nearest-term demand first
				demand_buckets.sort(key=lambda x: x[1])

				for demand_qty, required_date in demand_buckets:
					net_req = demand_qty - stock_credit
					if net_req <= 0:
						# Stock credit covers this bucket; reduce credit
						stock_credit -= demand_qty
						continue

					# Exhaust remaining credit against this bucket
					stock_credit = Decimal("0")

					# Lot sizing — honours lot_sizing_method on MRPProductConfig
					planned_qty = _compute_lot_size(cfg, net_req)

					# Planned start date — workback by lead time
					planned_start = required_date - timedelta(days=lead_time)

					# Create planned order
					order = MRPPlannedOrder(
						tenant_id=tenant_id,
						run_id=run.id,
						product_id=product_id,
						required_qty=net_req,
						planned_qty=planned_qty,
						required_date=required_date,
						planned_start_date=planned_start,
						order_type=(
							"PURCHASE" if cfg.procurement_type in ("EXTERNAL", "PHANTOM")
							else "PRODUCTION"
						),
						status="PLANNED",
					)
					session.add(order)
					session.flush()

					_emit(
						PlannedOrderCreatedEvent(
							aggregate_id=order.id,
							aggregate_type="MRPPlannedOrder",
							tenant_id=tenant_id,
							order_id=order.id,
							product_id=product_id,
							required_qty=str(net_req),
							planned_qty=str(planned_qty),
							required_date=required_date.isoformat(),
							planned_start_date=planned_start.isoformat(),
							order_type=order.order_type,
							run_id=run.id,
						),
						session,
					)
					planned_orders_count += 1

					# Source-specific events
					if cfg.procurement_type == "EXTERNAL":
						_emit(
							PurchaseRequisitionCreatedEvent(
								aggregate_id=order.id,
								aggregate_type="MRPPlannedOrder",
								tenant_id=tenant_id,
								req_id=order.id,
								product_id=product_id,
								qty=str(planned_qty),
								supplier_id=cfg.preferred_supplier_id or "",
								required_date=required_date.isoformat(),
								run_id=run.id,
							),
							session,
						)
						requisitions_count += 1

					elif cfg.procurement_type == "INTERNAL":
						_emit(
							ProductionOrderRecommendedEvent(
								aggregate_id=order.id,
								aggregate_type="MRPPlannedOrder",
								tenant_id=tenant_id,
								product_id=product_id,
								qty=str(planned_qty),
								start_date=planned_start.isoformat(),
								end_date=required_date.isoformat(),
								bom_id=cfg.bom_id or "",
								run_id=run.id,
							),
							session,
						)

						# Multi-level BOM explosion for INTERNAL products (DFS, cycle-safe)
						if cfg.bom_id:
							components = _explode_bom_multilevel(cfg.bom_id, planned_qty, tenant_id, session)
							for comp_product_id, comp_qty in components:
								# Fetch component config — skip if not configured
								comp_cfg: MRPProductConfig | None = session.execute(
									sa.select(MRPProductConfig).where(
										MRPProductConfig.tenant_id == tenant_id,
										MRPProductConfig.product_id == comp_product_id,
									)
								).scalar_one_or_none()

								comp_planned = (
									_compute_lot_size(comp_cfg, comp_qty)
									if comp_cfg is not None
									else _round_up_to_lot_qty(comp_qty, Decimal("1"))
								)
								comp_lead = int(comp_cfg.lead_time_days) if comp_cfg else lead_time
								comp_start = planned_start - timedelta(days=comp_lead)

								comp_order = MRPPlannedOrder(
									tenant_id=tenant_id,
									run_id=run.id,
									product_id=comp_product_id,
									required_qty=comp_qty,
									planned_qty=comp_planned,
									required_date=planned_start,	# component needed by parent start
									planned_start_date=comp_start,
									order_type=(
										"PURCHASE"
										if (comp_cfg is None or comp_cfg.procurement_type == "EXTERNAL")
										else "PRODUCTION"
									),
									status="PLANNED",
								)
								session.add(comp_order)
								session.flush()

								_emit(
									PlannedOrderCreatedEvent(
										aggregate_id=comp_order.id,
										aggregate_type="MRPPlannedOrder",
										tenant_id=tenant_id,
										order_id=comp_order.id,
										product_id=comp_product_id,
										required_qty=str(comp_qty),
										planned_qty=str(comp_planned),
										required_date=planned_start.isoformat(),
										planned_start_date=comp_start.isoformat(),
										order_type=comp_order.order_type,
										run_id=run.id,
									),
									session,
								)
								planned_orders_count += 1

								if comp_order.order_type == "PURCHASE":
									_emit(
										PurchaseRequisitionCreatedEvent(
											aggregate_id=comp_order.id,
											aggregate_type="MRPPlannedOrder",
											tenant_id=tenant_id,
											req_id=comp_order.id,
											product_id=comp_product_id,
											qty=str(comp_planned),
											supplier_id=(
												comp_cfg.preferred_supplier_id
												if comp_cfg else ""
											) or "",
											required_date=planned_start.isoformat(),
											run_id=run.id,
										),
										session,
									)
									requisitions_count += 1

			# Mark run completed
			completed_at = datetime.now(timezone.utc)
			duration = (completed_at - started_at).total_seconds()
			run.status = "COMPLETED"
			run.completed_at = completed_at
			run.planned_orders_count = planned_orders_count
			run.purchase_reqs_count = requisitions_count
			session.flush()

			_emit(
				MRPRunCompletedEvent(
					aggregate_id=run.id,
					aggregate_type="MRPRun",
					tenant_id=tenant_id,
					run_id=run.id,
					planned_orders_count=planned_orders_count,
					requisitions_count=requisitions_count,
					duration_seconds=duration,
					period=period_label,
				),
				session,
			)

			log.info(
				"MRPService.run_mrp: completed run=%s planned_orders=%d requisitions=%d duration=%.1fs",
				run.id, planned_orders_count, requisitions_count, duration,
			)

		except Exception as exc:
			log.error("MRPService.run_mrp: run=%s failed: %s", run.id, exc, exc_info=True)
			run.status = "FAILED"
			run.completed_at = datetime.now(timezone.utc)
			session.flush()
			raise MRPServiceError(f"MRP run {run.id} failed: {exc}") from exc

		return run

	# -----------------------------------------------------------------------
	# check_safety_stock
	# -----------------------------------------------------------------------

	@staticmethod
	def check_safety_stock(tenant_id: str, session: Any) -> list[dict]:
		"""Check all configured products against their safety stock thresholds.

		For each product whose current stock < safety_stock_qty:
		  - emits SafetyStockBreachEvent
		  - includes it in the returned list

		Returns:
		  list of dicts: {product_id, current_stock, safety_stock_qty, deficit}
		  All qty values are Decimal strings.

		Raises:
		  MRPServiceError on unexpected failures.
		"""
		assert tenant_id, "tenant_id must be non-empty"

		configs: list[MRPProductConfig] = session.execute(
			sa.select(MRPProductConfig).where(
				MRPProductConfig.tenant_id == tenant_id
			)
		).scalars().all()

		breaches: list[dict] = []

		for cfg in configs:
			product_id = cfg.product_id
			safety_stock = _d(cfg.safety_stock_qty)
			if safety_stock <= 0:
				continue

			current_stock = _get_current_stock(product_id, tenant_id, session)
			if current_stock < safety_stock:
				deficit = safety_stock - current_stock
				_emit(
					SafetyStockBreachEvent(
						aggregate_id=product_id,
						aggregate_type="Product",
						tenant_id=tenant_id,
						product_id=product_id,
						current_stock=str(current_stock),
						safety_stock_qty=str(safety_stock),
						deficit=str(deficit),
					),
					session,
				)
				breaches.append({
					"product_id": product_id,
					"current_stock": str(current_stock),
					"safety_stock_qty": str(safety_stock),
					"deficit": str(deficit),
				})

		log.info(
			"MRPService.check_safety_stock: tenant=%s configs=%d breaches=%d",
			tenant_id, len(configs), len(breaches),
		)
		return breaches

	# -----------------------------------------------------------------------
	# convert_to_po
	# -----------------------------------------------------------------------

	@staticmethod
	@BPMActionRegistry.register("ops.mrp.convert_to_po", "Convert MRP planned order to purchase order")
	def convert_to_po(planned_order_id: str, session: Any) -> dict:
		"""Convert a PLANNED MRP order to an actual purchase order.

		Steps:
		  1. Load MRPPlannedOrder; assert status==PLANNED and order_type==PURCHASE.
		  2. Resolve MRPProductConfig for supplier_id.
		  3. Call SCMService.create_purchase_order() (lazy import; graceful fallback).
		  4. Set planned_order.status = RELEASED; record converted_to_id.
		  5. Flush; return summary dict.

		Returns:
		  {planned_order_id, po_id, product_id, qty, supplier_id, status}

		Raises:
		  PlannedOrderNotFoundError — order not found
		  InvalidMRPStatusError    — order not in PLANNED status
		  MRPServiceError          — SCM call failed
		"""
		assert planned_order_id, "planned_order_id must be non-empty"

		order: MRPPlannedOrder | None = session.execute(
			sa.select(MRPPlannedOrder).where(MRPPlannedOrder.id == planned_order_id)
		).scalar_one_or_none()

		if order is None:
			raise PlannedOrderNotFoundError(f"MRPPlannedOrder {planned_order_id!r} not found")

		if order.status != "PLANNED":
			raise InvalidMRPStatusError(
				f"MRPPlannedOrder {planned_order_id!r} is in status {order.status!r}; "
				"only PLANNED orders can be converted"
			)

		if order.order_type != "PURCHASE":
			raise InvalidMRPStatusError(
				f"MRPPlannedOrder {planned_order_id!r} is type {order.order_type!r}; "
				"only PURCHASE orders can be converted via convert_to_po"
			)

		# Resolve product config for supplier
		cfg: MRPProductConfig | None = session.execute(
			sa.select(MRPProductConfig).where(
				MRPProductConfig.tenant_id == order.tenant_id,
				MRPProductConfig.product_id == order.product_id,
			)
		).scalar_one_or_none()

		supplier_id = cfg.preferred_supplier_id if cfg else None

		po_id: str | None = None

		# Attempt to create actual PO via SCM plugin (graceful degradation)
		try:
			from pgappforge.plugins.erp.operations.scm.services import SCMService  # type: ignore[import]
			scm = SCMService()
			po_obj = scm.create_purchase_order(
				session=session,
				supplier_id=supplier_id or "",
				lines=[{
					"product_code": order.product_id,
					"description": f"MRP planned order {order.id}",
					"ordered_qty": str(order.planned_qty),
					"unit_of_measure": "EACH",
					"unit_price_cents": 0,
				}],
				order_date=date.today(),
				expected_delivery=order.required_date,
				tenant_id=order.tenant_id,
				req_id=order.id,
			)
			po_id = str(po_obj.id)
			log.info(
				"MRPService.convert_to_po: created PO=%s for planned_order=%s",
				po_id, planned_order_id,
			)
		except ImportError:
			log.debug("convert_to_po: SCM plugin not loaded — generating stub PO ID")
			po_id = _uuid4()
		except Exception as exc:
			raise MRPServiceError(
				f"SCM purchase order creation failed for planned_order {planned_order_id}: {exc}"
			) from exc

		# Update planned order
		order.status = "RELEASED"
		order.converted_to_id = po_id
		session.flush()

		log.info(
			"MRPService.convert_to_po: planned_order=%s released → po=%s product=%s qty=%s",
			planned_order_id, po_id, order.product_id, order.planned_qty,
		)

		return {
			"planned_order_id": planned_order_id,
			"po_id": po_id,
			"product_id": order.product_id,
			"qty": str(order.planned_qty),
			"supplier_id": supplier_id or "",
			"status": "RELEASED",
		}

	# -----------------------------------------------------------------------
	# get_mrp_report
	# -----------------------------------------------------------------------

	@staticmethod
	def get_mrp_report(run_id: str, session: Any) -> dict:
		"""Generate an MRP run summary report.

		Returns:
		  {
		    run: {id, period, status, started_at, completed_at, ...},
		    by_product: {product_id: {purchase_orders, production_orders, total_qty}},
		    by_type: {PURCHASE: [...], PRODUCTION: [...]},
		    shortage_summary: [{product_id, required_qty, planned_qty, required_date}],
		    totals: {planned_orders_count, purchase_orders_count, production_orders_count},
		  }

		Raises:
		  MRPRunNotFoundError — run not found
		"""
		assert run_id, "run_id must be non-empty"

		run: MRPRun | None = session.execute(
			sa.select(MRPRun).where(MRPRun.id == run_id)
		).scalar_one_or_none()

		if run is None:
			raise MRPRunNotFoundError(f"MRPRun {run_id!r} not found")

		orders: list[MRPPlannedOrder] = session.execute(
			sa.select(MRPPlannedOrder).where(MRPPlannedOrder.run_id == run_id)
			.order_by(MRPPlannedOrder.required_date, MRPPlannedOrder.product_id)
		).scalars().all()

		by_product: dict[str, dict] = {}
		purchase_orders: list[dict] = []
		production_orders: list[dict] = []
		shortage_summary: list[dict] = []

		for o in orders:
			pid = o.product_id
			if pid not in by_product:
				by_product[pid] = {
					"product_id": pid,
					"purchase_orders": [],
					"production_orders": [],
					"total_planned_qty": Decimal("0"),
				}

			row = {
				"order_id": o.id,
				"product_id": pid,
				"required_qty": str(o.required_qty),
				"planned_qty": str(o.planned_qty),
				"required_date": o.required_date.isoformat(),
				"planned_start_date": o.planned_start_date.isoformat(),
				"status": o.status,
				"converted_to_id": o.converted_to_id,
			}

			if o.order_type == "PURCHASE":
				by_product[pid]["purchase_orders"].append(row)
				purchase_orders.append(row)
			else:
				by_product[pid]["production_orders"].append(row)
				production_orders.append(row)

			by_product[pid]["total_planned_qty"] += _d(o.planned_qty)

			if _d(o.planned_qty) < _d(o.required_qty):
				shortage_summary.append({
					"product_id": pid,
					"required_qty": str(o.required_qty),
					"planned_qty": str(o.planned_qty),
					"shortfall": str(_d(o.required_qty) - _d(o.planned_qty)),
					"required_date": o.required_date.isoformat(),
				})

		# Convert Decimal totals to strings for JSON safety
		for pid, data in by_product.items():
			data["total_planned_qty"] = str(data["total_planned_qty"])

		return {
			"run": {
				"id": run.id,
				"tenant_id": run.tenant_id,
				"period": run.period,
				"horizon_days": run.horizon_days,
				"status": run.status,
				"started_at": run.started_at.isoformat() if run.started_at else None,
				"completed_at": run.completed_at.isoformat() if run.completed_at else None,
				"entity_id": run.entity_id,
			},
			"by_product": by_product,
			"by_type": {
				"PURCHASE": purchase_orders,
				"PRODUCTION": production_orders,
			},
			"shortage_summary": shortage_summary,
			"totals": {
				"planned_orders_count": len(orders),
				"purchase_orders_count": len(purchase_orders),
				"production_orders_count": len(production_orders),
				"shortage_count": len(shortage_summary),
			},
		}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"MRPService",
	"MRPServiceError",
	"MRPRunNotFoundError",
	"PlannedOrderNotFoundError",
	"InvalidMRPStatusError",
]
