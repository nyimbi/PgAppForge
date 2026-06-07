"""
pgappforge/plugins/erp/operations/transport/services.py

TransportService — stateless business logic for the Transport Management plugin.

All methods receive an explicit SQLAlchemy 2.x session; no Flask context assumed.
Transaction boundaries owned by the caller.

Monetary invariants:
  - All amounts passed in and returned as integer cents
  - Decimal arithmetic used internally; results rounded half-up to int

Freight computation logic (compute_freight):
  PER_KG   — rate_cents * weight_kg
  FLAT     — rate_cents (fixed regardless of weight)
  PER_UNIT — rate_cents * weight_kg  (weight treated as unit count when no unit qty given)
  PER_CBM  — rate_cents * volume_cbm (falls back to weight when volume absent)

Status transitions:
  create_shipment  → PLANNED
  book_carrier     → BOOKED
  dispatch         → DISPATCHED  (requires BOOKED)
  record_delivery  → DELIVERED   (requires DISPATCHED or IN_TRANSIT)

BPM registrations:
  ops.transport.create_shipment
  ops.transport.dispatch

Public API:
  create_shipment(origin_address, destination_address, tenant_id, session, ...)  -> Shipment
  book_carrier(shipment_id, carrier_id, session)                                 -> Shipment
  dispatch(shipment_id, driver_id, session, *, vehicle_id=None)                  -> Shipment
  record_delivery(shipment_id, pod_ref, session)                                 -> Shipment
  add_tracking_event(shipment_id, location, status_note, session)                -> Shipment
  compute_freight(carrier_id, origin_zone, destination_zone, weight_kg, ...)     -> int
  update_carrier_performance(carrier_id, period, tenant_id, session)             -> Carrier
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import sqlalchemy as sa

from pgappforge.plugins.workflow.engine import BPMActionRegistry

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class TransportServiceError(Exception):
	"""Base domain error for Transport operations."""


class ShipmentNotFoundError(TransportServiceError):
	pass


class CarrierNotFoundError(TransportServiceError):
	pass


class InvalidStatusTransitionError(TransportServiceError):
	pass


class FreightRateNotFoundError(TransportServiceError):
	pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cents(value: Any) -> int:
	return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _dec(value: Any) -> Decimal:
	return Decimal(str(value))


def _now_utc() -> datetime:
	return datetime.now(timezone.utc)


def _emit(event: Any, session: Any = None) -> None:
	try:
		from pgappforge.plugins.erp.foundation.events import emit_event as _emit_event
		_emit_event(event, session)
	except Exception as exc:  # noqa: BLE001
		log.debug("Event emission skipped: %s", exc)


def _generate_shipment_ref(session: Any, tenant_id: str) -> str:
	"""Generate SHP-YYYYMMDD-NNNNN reference, unique per tenant."""
	from pgappforge.plugins.erp.operations.transport.models import Shipment
	today_str = _now_utc().strftime("%Y%m%d")
	prefix = f"SHP-{today_str}-"
	stmt = (
		sa.select(sa.func.count(Shipment.id))
		.where(
			Shipment.tenant_id == tenant_id,
			Shipment.shipment_ref.like(f"{prefix}%"),
		)
	)
	count = int(session.execute(stmt).scalar() or 0)
	return f"{prefix}{count + 1:05d}"


# ---------------------------------------------------------------------------
# TransportService
# ---------------------------------------------------------------------------

class TransportService:
	"""Stateless service — all methods are classmethods; instantiation optional."""

	# ------------------------------------------------------------------
	# 1. create_shipment
	# ------------------------------------------------------------------

	@classmethod
	def create_shipment(
		cls,
		origin_address: str,
		destination_address: str,
		tenant_id: str,
		session: Any,
		*,
		source_type: str | None = None,
		source_id: str | None = None,
		carrier_id: str | None = None,
		weight_kg: Any | None = None,
		volume_cbm: Any | None = None,
		origin_zone: str | None = None,
		destination_zone: str | None = None,
		planned_dispatch_date: Any | None = None,
		planned_delivery_date: Any | None = None,
		currency_code: str = "USD",
	) -> Any:
		"""Create a new Shipment in PLANNED status.

		Generates shipment_ref automatically.
		Emits ShipmentCreatedEvent.
		Returns the persisted Shipment.
		"""
		from pgappforge.plugins.erp.operations.transport.models import Shipment, SOURCE_DOC_TYPES
		from pgappforge.plugins.erp.operations.transport.events import ShipmentCreatedEvent

		if source_type and source_type not in SOURCE_DOC_TYPES:
			raise TransportServiceError(
				f"Invalid source_type {source_type!r}. Choose from {SOURCE_DOC_TYPES}"
			)

		ref = _generate_shipment_ref(session, tenant_id)

		shipment = Shipment(
			tenant_id=tenant_id,
			shipment_ref=ref,
			source_document_type=source_type,
			source_document_id=source_id,
			carrier_id=carrier_id,
			origin_address=origin_address,
			destination_address=destination_address,
			origin_zone=origin_zone,
			destination_zone=destination_zone,
			status="PLANNED",
			weight_kg=_dec(weight_kg) if weight_kg is not None else None,
			volume_cbm=_dec(volume_cbm) if volume_cbm is not None else None,
			freight_cost_cents=0,
			currency_code=currency_code,
			planned_dispatch_date=planned_dispatch_date,
			planned_delivery_date=planned_delivery_date,
			tracking_events=[],
		)
		session.add(shipment)
		session.flush()

		_emit(
			ShipmentCreatedEvent(
				aggregate_id=shipment.id,
				aggregate_type="Shipment",
				tenant_id=tenant_id,
				shipment_id=shipment.id,
				origin=origin_address,
				destination=destination_address,
				carrier_id=carrier_id or "",
			),
			session,
		)

		log.info("Shipment created: %s tenant=%s", ref, tenant_id)
		return shipment

	# ------------------------------------------------------------------
	# 2. book_carrier
	# ------------------------------------------------------------------

	@classmethod
	def book_carrier(
		cls,
		shipment_id: str,
		carrier_id: str,
		session: Any,
	) -> Any:
		"""Assign a carrier to a shipment, compute freight cost, transition to BOOKED.

		Looks up the best matching FreightRate for the shipment's zones and weight.
		Emits FreightCostComputedEvent.
		Returns the updated Shipment.
		"""
		from pgappforge.plugins.erp.operations.transport.models import Carrier, Shipment
		from pgappforge.plugins.erp.operations.transport.events import FreightCostComputedEvent

		shipment = session.get(Shipment, shipment_id)
		if shipment is None:
			raise ShipmentNotFoundError(f"Shipment {shipment_id!r} not found")
		if shipment.status not in ("PLANNED", "BOOKED"):
			raise InvalidStatusTransitionError(
				f"Cannot book carrier on shipment in status {shipment.status!r}"
			)

		carrier = session.get(Carrier, carrier_id)
		if carrier is None or carrier.tenant_id != shipment.tenant_id:
			raise CarrierNotFoundError(f"Carrier {carrier_id!r} not found")
		if not carrier.is_active:
			raise TransportServiceError(f"Carrier {carrier_id!r} is inactive")

		# Compute freight
		rate_id = ""
		cost_cents = 0
		if shipment.origin_zone and shipment.destination_zone:
			try:
				cost_cents, rate_id = cls._find_best_rate(
					carrier_id=carrier_id,
					origin_zone=shipment.origin_zone,
					destination_zone=shipment.destination_zone,
					weight_kg=shipment.weight_kg,
					volume_cbm=shipment.volume_cbm,
					tenant_id=shipment.tenant_id,
					session=session,
				)
			except FreightRateNotFoundError:
				log.info(
					"No freight rate found for %s→%s carrier=%s — freight_cost_cents stays 0",
					shipment.origin_zone, shipment.destination_zone, carrier_id,
				)

		shipment.carrier_id = carrier_id
		shipment.status = "BOOKED"
		shipment.freight_cost_cents = cost_cents
		session.flush()

		if rate_id:
			_emit(
				FreightCostComputedEvent(
					aggregate_id=shipment.id,
					aggregate_type="Shipment",
					tenant_id=shipment.tenant_id,
					shipment_id=shipment.id,
					cost_cents=cost_cents,
					rate_id=rate_id,
				),
				session,
			)

		log.info(
			"Carrier %s booked for shipment %s, freight=%d¢",
			carrier_id, shipment.shipment_ref, cost_cents,
		)
		return shipment

	@classmethod
	def _find_best_rate(
		cls,
		carrier_id: str,
		origin_zone: str,
		destination_zone: str,
		weight_kg: Any | None,
		volume_cbm: Any | None,
		tenant_id: str,
		session: Any,
	) -> tuple[int, str]:
		"""Return (cost_cents, rate_id) for the best matching FreightRate.

		Matching priority:
		  1. Exact zone pair + weight bracket that contains weight_kg
		  2. FLAT rate for zone pair (weight-independent)
		  3. Any rate for zone pair (broadest bracket first)

		Raises FreightRateNotFoundError when no rate exists.
		"""
		from pgappforge.plugins.erp.operations.transport.models import FreightRate
		from datetime import date

		today = date.today()
		stmt = (
			sa.select(FreightRate)
			.where(
				FreightRate.carrier_id == carrier_id,
				FreightRate.origin_zone == origin_zone,
				FreightRate.destination_zone == destination_zone,
				FreightRate.effective_from <= today,
				sa.or_(
					FreightRate.effective_to == None,  # noqa: E711
					FreightRate.effective_to >= today,
				),
			)
			.order_by(FreightRate.weight_kg_min.desc())
		)
		rates = session.execute(stmt).scalars().all()

		if not rates:
			raise FreightRateNotFoundError(
				f"No freight rate for {origin_zone}→{destination_zone} carrier={carrier_id}"
			)

		w = _dec(weight_kg) if weight_kg is not None else _dec(0)
		v = _dec(volume_cbm) if volume_cbm is not None else _dec(0)

		# Try to find a weight-bracket match
		for rate in rates:
			min_kg = _dec(rate.weight_kg_min)
			max_kg = _dec(rate.weight_kg_max) if rate.weight_kg_max is not None else None

			bracket_ok = (w >= min_kg) and (max_kg is None or w <= max_kg)
			if not bracket_ok and rate.rate_type != "FLAT":
				continue

			cost = cls._apply_rate(rate, w, v)
			return cost, rate.id

		# Fallback: first available rate
		rate = rates[0]
		cost = cls._apply_rate(rate, w, v)
		return cost, rate.id

	@staticmethod
	def _apply_rate(rate: Any, weight_kg: Decimal, volume_cbm: Decimal) -> int:
		"""Compute freight cost in cents for a single FreightRate row."""
		r = _dec(rate.rate_cents)
		if rate.rate_type == "FLAT":
			return _cents(r)
		elif rate.rate_type == "PER_KG":
			return _cents(r * weight_kg)
		elif rate.rate_type == "PER_UNIT":
			# unit count approximated by weight when no explicit qty
			return _cents(r * weight_kg)
		elif rate.rate_type == "PER_CBM":
			return _cents(r * volume_cbm) if volume_cbm > 0 else _cents(r * weight_kg)
		return _cents(r)

	# ------------------------------------------------------------------
	# 3. dispatch
	# ------------------------------------------------------------------

	@classmethod
	def dispatch(
		cls,
		shipment_id: str,
		driver_id: str,
		session: Any,
		*,
		vehicle_id: str | None = None,
	) -> Any:
		"""Transition a BOOKED shipment to DISPATCHED.

		Sets actual_dispatch_at to now().
		Emits ShipmentDispatchedEvent.
		Returns the updated Shipment.
		"""
		from pgappforge.plugins.erp.operations.transport.models import Shipment
		from pgappforge.plugins.erp.operations.transport.events import ShipmentDispatchedEvent

		shipment = session.get(Shipment, shipment_id)
		if shipment is None:
			raise ShipmentNotFoundError(f"Shipment {shipment_id!r} not found")
		if shipment.status != "BOOKED":
			raise InvalidStatusTransitionError(
				f"dispatch() requires BOOKED status, got {shipment.status!r}"
			)

		now = _now_utc()
		shipment.status = "DISPATCHED"
		shipment.driver_id = driver_id
		shipment.vehicle_id = vehicle_id
		shipment.actual_dispatch_at = now
		session.flush()

		_emit(
			ShipmentDispatchedEvent(
				aggregate_id=shipment.id,
				aggregate_type="Shipment",
				tenant_id=shipment.tenant_id,
				shipment_id=shipment.id,
				dispatched_at=now.isoformat(),
				driver_id=driver_id,
			),
			session,
		)

		log.info("Shipment %s dispatched, driver=%s", shipment.shipment_ref, driver_id)
		return shipment

	# ------------------------------------------------------------------
	# 4. record_delivery
	# ------------------------------------------------------------------

	@classmethod
	def record_delivery(
		cls,
		shipment_id: str,
		pod_ref: str,
		session: Any,
	) -> Any:
		"""Transition DISPATCHED or IN_TRANSIT → DELIVERED.

		Sets actual_delivery_at to now().
		Emits ShipmentDeliveredEvent.
		Returns the updated Shipment.
		"""
		from pgappforge.plugins.erp.operations.transport.models import Shipment
		from pgappforge.plugins.erp.operations.transport.events import ShipmentDeliveredEvent

		shipment = session.get(Shipment, shipment_id)
		if shipment is None:
			raise ShipmentNotFoundError(f"Shipment {shipment_id!r} not found")
		if shipment.status not in ("DISPATCHED", "IN_TRANSIT"):
			raise InvalidStatusTransitionError(
				f"record_delivery() requires DISPATCHED or IN_TRANSIT, got {shipment.status!r}"
			)

		now = _now_utc()
		shipment.status = "DELIVERED"
		shipment.pod_ref = pod_ref
		shipment.actual_delivery_at = now
		session.flush()

		_emit(
			ShipmentDeliveredEvent(
				aggregate_id=shipment.id,
				aggregate_type="Shipment",
				tenant_id=shipment.tenant_id,
				shipment_id=shipment.id,
				delivered_at=now.isoformat(),
				pod_ref=pod_ref,
			),
			session,
		)

		log.info("Shipment %s delivered, pod_ref=%s", shipment.shipment_ref, pod_ref)
		return shipment

	# ------------------------------------------------------------------
	# 5. add_tracking_event
	# ------------------------------------------------------------------

	@classmethod
	def add_tracking_event(
		cls,
		shipment_id: str,
		location: str,
		status_note: str,
		session: Any,
	) -> Any:
		"""Append a tracking event to Shipment.tracking_events.

		Each event: {timestamp, location, status, notes}.
		Returns the updated Shipment.
		"""
		from pgappforge.plugins.erp.operations.transport.models import Shipment

		shipment = session.get(Shipment, shipment_id)
		if shipment is None:
			raise ShipmentNotFoundError(f"Shipment {shipment_id!r} not found")

		now = _now_utc()
		events: list[dict] = list(shipment.tracking_events or [])
		events.append({
			"timestamp": now.isoformat(),
			"location": location,
			"status": shipment.status,
			"notes": status_note,
		})
		shipment.tracking_events = events
		session.flush()

		log.debug(
			"Tracking event added to %s: location=%r status=%r",
			shipment.shipment_ref, location, status_note,
		)
		return shipment

	# ------------------------------------------------------------------
	# 6. compute_freight
	# ------------------------------------------------------------------

	@classmethod
	def compute_freight(
		cls,
		carrier_id: str,
		origin_zone: str,
		destination_zone: str,
		weight_kg: Any,
		tenant_id: str,
		session: Any,
		*,
		volume_cbm: Any | None = None,
	) -> int:
		"""Return freight cost in integer cents for given parameters.

		Does not mutate any row — pure calculation from FreightRate table.
		Raises FreightRateNotFoundError when no matching rate exists.
		"""
		cost, _ = cls._find_best_rate(
			carrier_id=carrier_id,
			origin_zone=origin_zone,
			destination_zone=destination_zone,
			weight_kg=weight_kg,
			volume_cbm=volume_cbm,
			tenant_id=tenant_id,
			session=session,
		)
		return cost

	# ------------------------------------------------------------------
	# 7. update_carrier_performance
	# ------------------------------------------------------------------

	@classmethod
	def update_carrier_performance(
		cls,
		carrier_id: str,
		period: str,
		tenant_id: str,
		session: Any,
	) -> Any:
		"""Recompute a carrier's on_time_delivery_rate_pct from delivered shipments.

		period is used only for the emitted event (e.g. "2025-Q1").
		on_time = DELIVERED shipments where actual_delivery_at <= planned_delivery_date.
		Updates Carrier.on_time_delivery_rate_pct.
		Emits CarrierPerformanceUpdatedEvent.
		Returns the updated Carrier.
		"""
		from pgappforge.plugins.erp.operations.transport.models import Carrier, Shipment
		from pgappforge.plugins.erp.operations.transport.events import CarrierPerformanceUpdatedEvent

		carrier = session.get(Carrier, carrier_id)
		if carrier is None or carrier.tenant_id != tenant_id:
			raise CarrierNotFoundError(f"Carrier {carrier_id!r} not found")

		# Count delivered shipments for this carrier
		total_stmt = sa.select(sa.func.count(Shipment.id)).where(
			Shipment.carrier_id == carrier_id,
			Shipment.tenant_id == tenant_id,
			Shipment.status == "DELIVERED",
			Shipment.actual_delivery_at != None,  # noqa: E711
		)
		total = int(session.execute(total_stmt).scalar() or 0)

		on_time_rate = _dec(100)
		if total > 0:
			# On-time: delivered on or before planned date
			on_time_stmt = sa.select(sa.func.count(Shipment.id)).where(
				Shipment.carrier_id == carrier_id,
				Shipment.tenant_id == tenant_id,
				Shipment.status == "DELIVERED",
				Shipment.actual_delivery_at != None,  # noqa: E711
				Shipment.planned_delivery_date != None,  # noqa: E711
				sa.func.date(Shipment.actual_delivery_at) <= Shipment.planned_delivery_date,
			)
			on_time_count = int(session.execute(on_time_stmt).scalar() or 0)

			on_time_rate = (
				(_dec(on_time_count) / _dec(total) * _dec(100))
				.quantize(_dec("0.01"), rounding=ROUND_HALF_UP)
			)

		carrier.on_time_delivery_rate_pct = on_time_rate
		session.flush()

		_emit(
			CarrierPerformanceUpdatedEvent(
				aggregate_id=carrier.id,
				aggregate_type="Carrier",
				tenant_id=tenant_id,
				carrier_id=carrier_id,
				on_time_rate_pct=str(on_time_rate),
				period=period,
			),
			session,
		)

		log.info(
			"Carrier %s performance updated: on_time=%s%% (period=%s)",
			carrier_id, on_time_rate, period,
		)
		return carrier


# ---------------------------------------------------------------------------
# BPM Action registrations
# ---------------------------------------------------------------------------

@BPMActionRegistry.register("ops.transport.create_shipment", "Create a new transport shipment")
def _bpm_create_shipment(
	record_ctx: dict,
	session: Any,
	origin_address: str = "",
	destination_address: str = "",
	source_type: str | None = None,
	source_id: str | None = None,
	carrier_id: str | None = None,
	weight_kg: Any = None,
	origin_zone: str | None = None,
	destination_zone: str | None = None,
	**kw: Any,
) -> dict:
	try:
		from pgappforge.plugins.erp.operations.transport.services import TransportService
	except ImportError:
		return {"status": "error", "message": "transport plugin not installed"}
	tenant_id = record_ctx.get("tenant_id", "")
	try:
		shipment = TransportService.create_shipment(
			origin_address=origin_address,
			destination_address=destination_address,
			tenant_id=tenant_id,
			session=session,
			source_type=source_type,
			source_id=source_id,
			carrier_id=carrier_id,
			weight_kg=weight_kg,
			origin_zone=origin_zone,
			destination_zone=destination_zone,
		)
		return {"status": "ok", "shipment_id": shipment.id, "shipment_ref": shipment.shipment_ref}
	except Exception as exc:
		log.warning("bpm transport.create_shipment failed: %s", exc)
		return {"status": "error", "message": str(exc)}


@BPMActionRegistry.register("ops.transport.dispatch", "Dispatch a booked shipment to a driver")
def _bpm_dispatch(
	record_ctx: dict,
	session: Any,
	shipment_id: str = "",
	driver_id: str = "",
	vehicle_id: str | None = None,
	**kw: Any,
) -> dict:
	try:
		from pgappforge.plugins.erp.operations.transport.services import TransportService
	except ImportError:
		return {"status": "error", "message": "transport plugin not installed"}
	try:
		shipment = TransportService.dispatch(
			shipment_id=shipment_id,
			driver_id=driver_id,
			session=session,
			vehicle_id=vehicle_id,
		)
		return {
			"status": "ok",
			"shipment_id": shipment.id,
			"shipment_ref": shipment.shipment_ref,
			"new_status": shipment.status,
		}
	except Exception as exc:
		log.warning("bpm transport.dispatch failed: %s", exc)
		return {"status": "error", "message": str(exc)}


__all__ = [
	"TransportService",
	"TransportServiceError",
	"ShipmentNotFoundError",
	"CarrierNotFoundError",
	"InvalidStatusTransitionError",
	"FreightRateNotFoundError",
]
