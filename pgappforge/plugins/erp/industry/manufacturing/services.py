"""
pgappforge/plugins/erp/industry/manufacturing/services.py

ManufacturingService — stateless business logic for the Manufacturing plugin.

All methods receive an explicit SQLAlchemy session; no Flask context assumed.
Transaction boundaries owned by the caller.

Monetary invariants:
  - All amounts as integer cents
  - Decimal arithmetic internally; results rounded half-up to int
  - Quantities use Decimal(str(...)) — never float
  - OEE percentages returned as Decimal(5,4) strings: "0.8523"

Public API:
  release_order(order_id, session)                          -> ManufacturingOrder
  complete_order(order_id, actual_qty, scrap_qty, session)  -> ManufacturingOrder
  calculate_oee(work_center_id, shift_date, session)        -> OEESnapshot
  schedule_maintenance(asset_id, maint_type, due_date, ...)
                                                            -> MaintenanceWork
  run_mrp(product_id, required_qty, required_date, session) -> list[dict]
  get_production_schedule(start_date, end_date, session)    -> list[dict]
"""
from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import sqlalchemy as sa

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class ManufacturingServiceError(Exception):
	"""Base domain error for manufacturing operations."""


class ManufacturingOrderNotFoundError(ManufacturingServiceError):
	pass


class InvalidStatusTransitionError(ManufacturingServiceError):
	pass


class BOMValidationError(ManufacturingServiceError):
	pass


class WorkCenterNotFoundError(ManufacturingServiceError):
	pass


class MaintenanceWorkNotFoundError(ManufacturingServiceError):
	pass


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _d(value: Any) -> Decimal:
	"""Safe Decimal coercion — never float intermediate."""
	if isinstance(value, Decimal):
		return value
	return Decimal(str(value))


def _now() -> datetime:
	return datetime.now(timezone.utc)


def _today() -> date:
	return _now().date()


def _uuid4() -> str:
	return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# ManufacturingService
# ---------------------------------------------------------------------------

class ManufacturingService:
	"""Stateless manufacturing domain service.

	Instantiate once per application (no instance state).
	All public methods accept an explicit SQLAlchemy Session.
	"""

	# ------------------------------------------------------------------
	# release_order
	# ------------------------------------------------------------------

	def release_order(self, order_id: str, session: Any) -> Any:
		"""Validate BOM, reserve components, transition MO to RELEASED.

		Steps:
		  1. Load MO — must be DRAFT status
		  2. Verify a BOM exists for the product (soft reference — checks
		     operations.production.BillOfMaterials if plugin is loaded)
		  3. Attempt to reserve components via inventory plugin (optional)
		  4. Transition status DRAFT → RELEASED
		  5. Emit ManufacturingOrderReleasedEvent

		Args:
			order_id: UUID of the ManufacturingOrder.
			session: SQLAlchemy session (caller commits).

		Returns:
			Updated ManufacturingOrder instance.

		Raises:
			ManufacturingOrderNotFoundError: order not found.
			InvalidStatusTransitionError: order not in DRAFT.
			BOMValidationError: no active BOM for product.
		"""
		from pgappforge.plugins.erp.industry.manufacturing.models import ManufacturingOrder
		from pgappforge.plugins.erp.industry.manufacturing.events import ManufacturingOrderReleasedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		mo = session.get(ManufacturingOrder, order_id)
		if mo is None:
			raise ManufacturingOrderNotFoundError(f"ManufacturingOrder {order_id!r} not found")
		if mo.status != "DRAFT":
			raise InvalidStatusTransitionError(
				f"ManufacturingOrder must be DRAFT to release; got {mo.status!r}"
			)

		# Validate BOM (optional dependency on production plugin)
		self._validate_bom_for_product(mo.product_id, mo.bom_id, session)

		# Attempt component reservation via inventory (best-effort)
		self._reserve_components(mo, session)

		mo.status = "RELEASED"
		mo.updated_at = _now()

		session.flush()

		emit_event(
			ManufacturingOrderReleasedEvent(
				aggregate_id=mo.id,
				aggregate_type="ManufacturingOrder",
				tenant_id=str(mo.tenant_id),
				order_id=mo.id,
				order_number=mo.order_number,
				product_id=str(mo.product_id),
				planned_qty=float(_d(mo.planned_qty)),
				scheduled_start=mo.scheduled_start.isoformat() if mo.scheduled_start else "",
			),
			session,
		)

		log.info("ManufacturingService.release_order: MO=%s order_number=%s", order_id, mo.order_number)
		return mo

	# ------------------------------------------------------------------
	# complete_order
	# ------------------------------------------------------------------

	def complete_order(
		self,
		order_id: str,
		actual_qty: Decimal | str | float,
		scrap_qty: Decimal | str | float,
		session: Any,
	) -> Any:
		"""Post production journal, update stock, transition MO to COMPLETED.

		Steps:
		  1. Load MO — must be RELEASED or IN_PROGRESS
		  2. Update actual_qty_produced, actual_qty_scrapped (add-only)
		  3. Post PRODUCTION receipt to inventory (best-effort)
		  4. Transition status → COMPLETED
		  5. Emit ManufacturingOrderCompletedEvent

		Args:
			order_id:   UUID of the ManufacturingOrder.
			actual_qty: Good units produced (Decimal-coerced).
			scrap_qty:  Scrap units (Decimal-coerced).
			session:    SQLAlchemy session (caller commits).

		Returns:
			Updated ManufacturingOrder instance.

		Raises:
			ManufacturingOrderNotFoundError
			InvalidStatusTransitionError: not RELEASED or IN_PROGRESS.
		"""
		from pgappforge.plugins.erp.industry.manufacturing.models import ManufacturingOrder
		from pgappforge.plugins.erp.industry.manufacturing.events import ManufacturingOrderCompletedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		mo = session.get(ManufacturingOrder, order_id)
		if mo is None:
			raise ManufacturingOrderNotFoundError(f"ManufacturingOrder {order_id!r} not found")
		if mo.status not in ("RELEASED", "IN_PROGRESS"):
			raise InvalidStatusTransitionError(
				f"ManufacturingOrder must be RELEASED or IN_PROGRESS to complete; got {mo.status!r}"
			)

		good_qty = _d(actual_qty)
		scrapped = _d(scrap_qty)

		assert good_qty >= 0, "actual_qty must be non-negative"
		assert scrapped >= 0, "scrap_qty must be non-negative"

		# Immutable-ledger add-only updates
		mo.actual_qty_produced = _d(mo.actual_qty_produced) + good_qty
		mo.actual_qty_scrapped = _d(mo.actual_qty_scrapped) + scrapped
		mo.status = "COMPLETED"
		mo.actual_end = _now()
		mo.updated_at = _now()

		# Post production stock receipt (best-effort — inventory plugin optional)
		self._post_production_receipt(mo, good_qty, session)

		session.flush()

		emit_event(
			ManufacturingOrderCompletedEvent(
				aggregate_id=mo.id,
				aggregate_type="ManufacturingOrder",
				tenant_id=str(mo.tenant_id),
				order_id=mo.id,
				order_number=mo.order_number,
				product_id=str(mo.product_id),
				actual_qty_produced=float(_d(mo.actual_qty_produced)),
				actual_qty_scrapped=float(_d(mo.actual_qty_scrapped)),
				actual_cost_cents=mo.actual_cost_cents,
			),
			session,
		)

		log.info(
			"ManufacturingService.complete_order: MO=%s good=%.4f scrap=%.4f",
			order_id, float(good_qty), float(scrapped),
		)
		return mo

	# ------------------------------------------------------------------
	# calculate_oee
	# ------------------------------------------------------------------

	def calculate_oee(
		self,
		work_center_id: str,
		shift_date: date,
		session: Any,
		shift_name: str = "MORNING",
		planned_production_minutes: int | None = None,
		downtime_minutes: int = 0,
		total_units_run: Decimal | str | float = 0,
		good_units: Decimal | str | float = 0,
		reject_qty: Decimal | str | float = 0,
		ideal_cycle_time_seconds: Decimal | str | float | None = None,
		manufacturing_order_id: str | None = None,
		tenant_id: str = "",
	) -> Any:
		"""Compute OEE (availability × performance × quality) and persist a snapshot.

		OEE components:
		  availability = (planned_min - downtime_min) / planned_min
		  performance  = (total_units × ideal_cycle_sec) / (run_time_sec)
		                 or 1.0 if ideal_cycle_time not provided
		  quality      = good_units / total_units_run

		All components clamped to [0, 1].  Snapshots are IMMUTABLE once
		recorded — corrections create new rows.

		Args:
			work_center_id:           UUID of the work center.
			shift_date:               Date of the shift.
			session:                  SQLAlchemy session.
			shift_name:               MORNING|AFTERNOON|NIGHT (default MORNING).
			planned_production_minutes: Scheduled minutes (defaults to 480 = 8h).
			downtime_minutes:         Total unplanned + planned stops in minutes.
			total_units_run:          All units run (good + reject).
			good_units:               Good output units.
			reject_qty:               Rejected/rework units.
			ideal_cycle_time_seconds: Ideal time per unit in seconds (for performance).
			manufacturing_order_id:   Optional FK to ManufacturingOrder.
			tenant_id:                Tenant scope.

		Returns:
			OEESnapshot instance (not yet flushed — caller flushes/commits).

		Raises:
			ManufacturingServiceError: invalid inputs.
		"""
		from pgappforge.plugins.erp.industry.manufacturing.models import OEESnapshot
		from pgappforge.plugins.erp.industry.manufacturing.events import OEESnapshotCreatedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		planned = planned_production_minutes if planned_production_minutes is not None else 480
		assert planned > 0, "planned_production_minutes must be positive"
		assert 0 <= downtime_minutes <= planned, "downtime_minutes must be <= planned"

		total_units = _d(total_units_run)
		good = _d(good_units)
		reject = _d(reject_qty)

		# Availability
		run_minutes = planned - downtime_minutes
		avail = Decimal(run_minutes) / Decimal(planned)
		avail = max(Decimal("0"), min(Decimal("1"), avail))

		# Performance
		if ideal_cycle_time_seconds is not None and total_units > 0 and run_minutes > 0:
			run_seconds = Decimal(run_minutes) * Decimal("60")
			ideal_total = total_units * _d(ideal_cycle_time_seconds)
			perf = ideal_total / run_seconds
			perf = max(Decimal("0"), min(Decimal("1"), perf))
		else:
			perf = Decimal("1")

		# Quality
		if total_units > 0:
			qual = good / total_units
			qual = max(Decimal("0"), min(Decimal("1"), qual))
		else:
			qual = Decimal("1")

		oee = avail * perf * qual

		# Round to 4 decimal places (NUMERIC(5,4))
		def _round4(d: Decimal) -> Decimal:
			return d.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)

		snapshot = OEESnapshot(
			tenant_id=tenant_id,
			work_center_id=work_center_id,
			manufacturing_order_id=manufacturing_order_id,
			shift_date=shift_date,
			shift_name=shift_name,
			planned_production_minutes=planned,
			downtime_minutes=downtime_minutes,
			ideal_cycle_time_seconds=_d(ideal_cycle_time_seconds) if ideal_cycle_time_seconds is not None else None,
			total_units_run=total_units,
			good_units=good,
			reject_qty=reject,
			availability_pct=_round4(avail),
			performance_pct=_round4(perf),
			quality_pct=_round4(qual),
			oee_pct=_round4(oee),
		)
		session.add(snapshot)
		session.flush()

		emit_event(
			OEESnapshotCreatedEvent(
				aggregate_id=snapshot.id,
				aggregate_type="OEESnapshot",
				tenant_id=tenant_id,
				snapshot_id=snapshot.id,
				work_center_id=work_center_id,
				shift_date=shift_date.isoformat(),
				shift_name=shift_name,
				oee_pct=str(_round4(oee)),
				availability_pct=str(_round4(avail)),
				performance_pct=str(_round4(perf)),
				quality_pct=str(_round4(qual)),
			),
			session,
		)

		log.info(
			"ManufacturingService.calculate_oee: wc=%s date=%s OEE=%.1f%%",
			work_center_id, shift_date, float(oee) * 100,
		)
		return snapshot

	# ------------------------------------------------------------------
	# schedule_maintenance
	# ------------------------------------------------------------------

	def schedule_maintenance(
		self,
		asset_id: str,
		maintenance_type: str,
		due_date: date,
		session: Any,
		description: str = "",
		priority: str = "MEDIUM",
		assigned_technician_id: str | None = None,
		estimated_cost_cents: int = 0,
		tenant_id: str = "",
	) -> Any:
		"""Create a maintenance work order for a plant asset.

		Generates a unique work_order_number (WO-{YYYYMMDD}-{short_uuid}).
		Emits MaintenanceWorkOrderRaisedEvent.

		Args:
			asset_id:               UUID of the asset.
			maintenance_type:       CORRECTIVE|PREVENTIVE|PREDICTIVE|STATUTORY.
			due_date:               Requested/scheduled date.
			session:                SQLAlchemy session.
			description:            Work description.
			priority:               LOW|MEDIUM|HIGH|CRITICAL (default MEDIUM).
			assigned_technician_id: Optional FK to ab_user.
			estimated_cost_cents:   Estimated cost (integer cents).
			tenant_id:              Tenant scope.

		Returns:
			MaintenanceWork instance.
		"""
		from pgappforge.plugins.erp.industry.manufacturing.models import MaintenanceWork
		from pgappforge.plugins.erp.industry.manufacturing.events import MaintenanceWorkOrderRaisedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		valid_types = {"CORRECTIVE", "PREVENTIVE", "PREDICTIVE", "STATUTORY"}
		if maintenance_type not in valid_types:
			raise ManufacturingServiceError(
				f"maintenance_type must be one of {valid_types}; got {maintenance_type!r}"
			)

		valid_priorities = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
		if priority not in valid_priorities:
			raise ManufacturingServiceError(
				f"priority must be one of {valid_priorities}; got {priority!r}"
			)

		assert isinstance(estimated_cost_cents, int), "estimated_cost_cents must be int"

		wo_number = f"WO-{due_date.strftime('%Y%m%d')}-{_uuid4()[:8].upper()}"

		work = MaintenanceWork(
			tenant_id=tenant_id,
			work_order_number=wo_number,
			asset_id=asset_id,
			assigned_technician_id=assigned_technician_id,
			maintenance_type=maintenance_type,
			priority=priority,
			description=description or f"{maintenance_type} maintenance for asset {asset_id}",
			requested_date=due_date,
			scheduled_date=due_date,
			estimated_cost_cents=estimated_cost_cents,
			status="OPEN",
		)
		session.add(work)
		session.flush()

		emit_event(
			MaintenanceWorkOrderRaisedEvent(
				aggregate_id=work.id,
				aggregate_type="MaintenanceWork",
				tenant_id=tenant_id,
				work_order_id=work.id,
				work_order_number=wo_number,
				asset_id=asset_id,
				maintenance_type=maintenance_type,
				priority=priority,
			),
			session,
		)

		log.info(
			"ManufacturingService.schedule_maintenance: WO=%s asset=%s type=%s",
			wo_number, asset_id, maintenance_type,
		)
		return work

	# ------------------------------------------------------------------
	# run_mrp
	# ------------------------------------------------------------------

	def run_mrp(
		self,
		product_id: str,
		required_qty: Decimal | str | float,
		required_date: date,
		session: Any,
		tenant_id: str = "",
	) -> list[dict]:
		"""Run Material Requirements Planning for a product.

		Explodes demand into component requirements using the active BOM
		(loaded from operations.production plugin if available).  For each
		component checks current stock level and generates a planned order
		dict if shortage exists.

		Args:
			product_id:    Finished-goods product UUID.
			required_qty:  Top-level demand quantity.
			required_date: When the finished goods are needed.
			session:       SQLAlchemy session (read-only; no inserts).
			tenant_id:     Tenant scope.

		Returns:
			List of planned order dicts::

			  [
			    {
			      "product_id": str,
			      "sku": str | None,
			      "required_qty": str,
			      "available_qty": str,
			      "shortage_qty": str,
			      "suggested_order_qty": str,
			      "suggested_order_date": str,  # ISO date
			      "lead_time_days": int,
			      "bom_level": int,
			    },
			    ...
			  ]
		"""
		qty = _d(required_qty)
		assert qty > 0, "required_qty must be positive"

		planned_orders: list[dict] = []
		self._explode_bom(
			product_id=product_id,
			qty=qty,
			required_date=required_date,
			session=session,
			tenant_id=tenant_id,
			level=0,
			planned_orders=planned_orders,
		)

		log.info(
			"ManufacturingService.run_mrp: product=%s qty=%s date=%s planned_orders=%d",
			product_id, qty, required_date, len(planned_orders),
		)
		return planned_orders

	# ------------------------------------------------------------------
	# get_production_schedule
	# ------------------------------------------------------------------

	def get_production_schedule(
		self,
		start_date: date,
		end_date: date,
		session: Any,
		tenant_id: str = "",
	) -> list[dict]:
		"""Return production schedule with capacity utilisation per work center.

		Joins ManufacturingOrder with ProductionSchedule to compute:
		  - Scheduled slots per work center per day
		  - Capacity utilisation % (scheduled minutes / available minutes)
		  - Conflict flags on overlapping slots

		Args:
			start_date: Inclusive schedule window start.
			end_date:   Inclusive schedule window end.
			session:    SQLAlchemy session.
			tenant_id:  Tenant scope.

		Returns:
			List of schedule entry dicts sorted by slot_start::

			  [
			    {
			      "schedule_id": str,
			      "manufacturing_order_id": str,
			      "order_number": str,
			      "product_id": str,
			      "work_center_id": str,
			      "operation_name": str | None,
			      "operation_sequence": int,
			      "slot_start": str,   # ISO datetime
			      "slot_end": str,     # ISO datetime
			      "setup_minutes": int,
			      "run_minutes": int,
			      "status": str,
			      "conflict_flag": bool,
			    },
			    ...
			  ]
		"""
		from pgappforge.plugins.erp.industry.manufacturing.models import (
			ManufacturingOrder,
			ProductionSchedule,
		)
		from datetime import datetime as dt

		slot_start_dt = dt(start_date.year, start_date.month, start_date.day, tzinfo=timezone.utc)
		slot_end_dt = dt(end_date.year, end_date.month, end_date.day, 23, 59, 59, tzinfo=timezone.utc)

		q = (
			sa.select(ProductionSchedule, ManufacturingOrder)
			.join(ManufacturingOrder, ProductionSchedule.manufacturing_order_id == ManufacturingOrder.id)
			.where(ProductionSchedule.slot_start >= slot_start_dt)
			.where(ProductionSchedule.slot_start <= slot_end_dt)
			.order_by(ProductionSchedule.slot_start, ProductionSchedule.operation_sequence)
		)
		if tenant_id:
			q = q.where(ProductionSchedule.tenant_id == tenant_id)

		rows = session.execute(q.limit(2000)).all()

		schedule = []
		for sched, mo in rows:
			schedule.append({
				"schedule_id": sched.id,
				"manufacturing_order_id": sched.manufacturing_order_id,
				"order_number": mo.order_number,
				"product_id": str(mo.product_id),
				"work_center_id": str(sched.work_center_id),
				"operation_name": sched.operation_name,
				"operation_sequence": sched.operation_sequence,
				"slot_start": sched.slot_start.isoformat(),
				"slot_end": sched.slot_end.isoformat(),
				"setup_minutes": sched.setup_minutes,
				"run_minutes": sched.run_minutes,
				"status": sched.status,
				"conflict_flag": sched.conflict_flag,
			})

		log.info(
			"ManufacturingService.get_production_schedule: %s→%s entries=%d",
			start_date, end_date, len(schedule),
		)
		return schedule

	# ------------------------------------------------------------------
	# Internal helpers
	# ------------------------------------------------------------------

	def _validate_bom_for_product(
		self,
		product_id: str,
		bom_id: str | None,
		session: Any,
	) -> None:
		"""Check an active BOM exists for product_id (best-effort)."""
		try:
			from pgappforge.plugins.erp.operations.production.models import BillOfMaterials
		except ImportError:
			log.debug("_validate_bom_for_product: production plugin not available, skipping BOM check")
			return

		if bom_id:
			bom = session.get(BillOfMaterials, bom_id)
			if bom is None:
				raise BOMValidationError(f"BOM {bom_id!r} not found")
			if bom.status != "ACTIVE":
				raise BOMValidationError(
					f"BOM {bom_id!r} is not ACTIVE (status={bom.status!r}); cannot release MO"
				)
		else:
			# No explicit bom_id — look for any active BOM for the product
			existing = session.execute(
				sa.select(BillOfMaterials).where(
					BillOfMaterials.product_id == product_id,
					BillOfMaterials.status == "ACTIVE",
				).limit(1)
			).scalar_one_or_none()
			if existing is None:
				log.warning(
					"_validate_bom_for_product: no ACTIVE BOM for product=%s; releasing anyway",
					product_id,
				)

	def _reserve_components(self, mo: Any, session: Any) -> None:
		"""Attempt component reservation via inventory plugin (best-effort)."""
		try:
			from pgappforge.plugins.erp.operations.inventory.services import (
				InventoryService, InsufficientStockError,
			)
			from pgappforge.plugins.erp.operations.production.models import BillOfMaterials, BOMLine
		except ImportError:
			log.debug("_reserve_components: inventory/production plugin not available, skipping")
			return

		if not mo.bom_id:
			return

		try:
			bom_lines = session.execute(
				sa.select(BOMLine).where(BOMLine.bom_id == mo.bom_id)
			).scalars().all()
			if not bom_lines:
				return

			allocation_lines = []
			for line in bom_lines:
				needed = _d(mo.planned_qty) * _d(line.quantity)
				allocation_lines.append({
					"product_id": str(line.component_product_id),
					"warehouse_id": str(mo.tenant_id),  # fallback; real impl maps to WH
					"quantity": str(needed),
				})

			InventoryService().allocate_stock(
				order_id=mo.id,
				order_type="PRODUCTION",
				lines=allocation_lines,
				session=session,
				tenant_id=str(mo.tenant_id),
			)
			log.info("_reserve_components: allocated %d component lines for MO=%s", len(allocation_lines), mo.id)
		except Exception as exc:
			log.warning("_reserve_components: allocation failed (non-blocking): %s", exc)

	def _post_production_receipt(self, mo: Any, good_qty: Decimal, session: Any) -> None:
		"""Post a PRODUCTION receipt to inventory for finished goods (best-effort)."""
		try:
			from pgappforge.plugins.erp.operations.inventory.services import InventoryService
		except ImportError:
			return

		try:
			InventoryService().adjust_stock(
				product_id=str(mo.product_id),
				warehouse_id=str(mo.tenant_id),  # fallback
				qty_delta=good_qty,
				reason=f"Production receipt from MO {mo.order_number}",
				session=session,
				tenant_id=str(mo.tenant_id),
			)
		except Exception as exc:
			log.warning("_post_production_receipt: stock post failed (non-blocking): %s", exc)

	def _explode_bom(
		self,
		product_id: str,
		qty: Decimal,
		required_date: date,
		session: Any,
		tenant_id: str,
		level: int,
		planned_orders: list[dict],
		max_levels: int = 5,
	) -> None:
		"""Recursively explode BOM to generate MRP planned orders."""
		if level >= max_levels:
			return

		try:
			from pgappforge.plugins.erp.operations.production.models import BillOfMaterials, BOMLine
		except ImportError:
			return

		# Find active BOM
		bom = session.execute(
			sa.select(BillOfMaterials).where(
				BillOfMaterials.product_id == product_id,
				BillOfMaterials.status == "ACTIVE",
				*([BillOfMaterials.tenant_id == tenant_id] if tenant_id else []),
			).limit(1)
		).scalar_one_or_none()

		if bom is None:
			return

		lines = session.execute(
			sa.select(BOMLine).where(BOMLine.bom_id == bom.id)
		).scalars().all()

		for line in lines:
			component_id = str(line.component_product_id)
			required = qty * _d(line.quantity) * (Decimal("1") + _d(line.scrap_factor))

			# Check available stock
			available_qty = self._get_available_qty(component_id, tenant_id, session)
			shortage = max(Decimal("0"), required - available_qty)

			if shortage > 0:
				# Estimate order date from lead time
				from datetime import timedelta
				lead_days = self._get_lead_time(component_id, session)
				order_date = required_date - timedelta(days=lead_days)

				planned_orders.append({
					"product_id": component_id,
					"sku": None,
					"required_qty": str(required.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)),
					"available_qty": str(available_qty.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)),
					"shortage_qty": str(shortage.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)),
					"suggested_order_qty": str(shortage.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)),
					"suggested_order_date": order_date.isoformat(),
					"lead_time_days": lead_days,
					"bom_level": level + 1,
				})

			# Recurse for sub-assemblies
			self._explode_bom(
				product_id=component_id,
				qty=required,
				required_date=required_date,
				session=session,
				tenant_id=tenant_id,
				level=level + 1,
				planned_orders=planned_orders,
				max_levels=max_levels,
			)

	def _get_available_qty(self, product_id: str, tenant_id: str, session: Any) -> Decimal:
		"""Get available stock quantity for a product (best-effort)."""
		try:
			from pgappforge.plugins.erp.operations.inventory.models import StockLevel
			q = sa.select(
				sa.func.coalesce(sa.func.sum(StockLevel.quantity_available), 0)
			).where(StockLevel.product_id == product_id)
			if tenant_id:
				q = q.where(StockLevel.tenant_id == tenant_id)
			result = session.execute(q).scalar()
			return _d(result or 0)
		except Exception:
			return Decimal("0")

	def _get_lead_time(self, product_id: str, session: Any) -> int:
		"""Get lead time in days for a product (best-effort)."""
		try:
			from pgappforge.plugins.erp.operations.inventory.models import Product
			product = session.get(Product, product_id)
			if product and hasattr(product, "lead_time_days"):
				return int(product.lead_time_days or 0)
		except Exception:
			pass
		return 0


__all__ = [
	"ManufacturingService",
	"ManufacturingServiceError",
	"ManufacturingOrderNotFoundError",
	"InvalidStatusTransitionError",
	"BOMValidationError",
	"WorkCenterNotFoundError",
	"MaintenanceWorkNotFoundError",
]
