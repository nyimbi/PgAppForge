"""
pgappforge/plugins/erp/industry/oil_gas/services.py

OilGasService — stateless business logic for the Oil & Gas plugin.

All methods accept an explicit SQLAlchemy Session; callers own transaction
boundaries.  No Flask context assumed — safe for background jobs and CLI.

Cost amounts are always integer cents.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy import func, select

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class OilGasServiceError(Exception):
	"""Base error for Oil & Gas domain violations."""


class FacilityNotFoundError(OilGasServiceError):
	"""No Facility with the given id."""


class AssetNotFoundError(OilGasServiceError):
	"""No Asset with the given id."""


class InvalidProductTypeError(OilGasServiceError):
	"""product_type value is not in the allowed set."""


VALID_PRODUCT_TYPES = frozenset({
	"CRUDE_OIL", "GAS", "LNG", "REFINED_PRODUCT", "NGL",
})

VALID_WORK_TYPES = frozenset({
	"PREVENTIVE", "CORRECTIVE", "CONDITION_BASED", "TURNAROUND",
})


# ---------------------------------------------------------------------------
# OilGasService
# ---------------------------------------------------------------------------

class OilGasService:
	"""Stateless service for Oil & Gas operations.

	Instantiate once per app (or per request).  All methods accept a
	SQLAlchemy Session as their last positional argument; callers own
	transaction boundaries (commit/rollback).
	"""

	# ------------------------------------------------------------------
	# OEE calculation
	# ------------------------------------------------------------------

	def calculate_oee(
		self,
		facility_id: str,
		session: Any,
		period_days: int = 30,
	) -> dict:
		"""Calculate Overall Equipment Effectiveness for a facility.

		OEE = Availability × Performance × Quality

		Returns a dict with keys:
		  period_days, total_calendar_hours, total_downtime_hours,
		  availability_pct, production_records, avg_daily_quantity,
		  downtime_events, oee_pct (simplified: availability × 100)

		Raises FacilityNotFoundError if facility_id not found.
		"""
		from pgappforge.plugins.erp.industry.oil_gas.models import (
			Facility, ProductionRecord,
		)

		facility = session.get(Facility, facility_id)
		if facility is None:
			raise FacilityNotFoundError(f"Facility {facility_id!r} not found")

		cutoff = date.today() - timedelta(days=period_days)

		rows = session.execute(
			select(ProductionRecord)
			.where(
				ProductionRecord.facility_id == facility_id,
				ProductionRecord.production_date >= cutoff,
			)
			.order_by(ProductionRecord.production_date)
		).scalars().all()

		total_calendar_hours = period_days * 24
		total_downtime_hours = sum(
			float(r.downtime_hours or 0) for r in rows
		)
		available_hours = total_calendar_hours - total_downtime_hours
		availability_pct = (
			(available_hours / total_calendar_hours * 100)
			if total_calendar_hours > 0
			else 0.0
		)

		# Aggregate production by product type
		production_by_type: dict[str, float] = {}
		for r in rows:
			production_by_type.setdefault(str(r.product_type), 0.0)
			production_by_type[str(r.product_type)] += float(r.quantity or 0)

		avg_daily = sum(production_by_type.values()) / period_days if period_days > 0 else 0.0

		return {
			"facility_id": facility_id,
			"facility_code": facility.facility_code,
			"period_days": period_days,
			"total_calendar_hours": total_calendar_hours,
			"total_downtime_hours": round(total_downtime_hours, 2),
			"available_hours": round(available_hours, 2),
			"availability_pct": round(availability_pct, 2),
			"production_records": len(rows),
			"production_by_type": production_by_type,
			"avg_daily_quantity": round(avg_daily, 4),
			"downtime_events": sum(1 for r in rows if float(r.downtime_hours or 0) > 0),
			# Simplified OEE: availability only (performance/quality need rated capacity)
			"oee_pct": round(availability_pct, 2),
		}

	# ------------------------------------------------------------------
	# Preventive maintenance scheduling
	# ------------------------------------------------------------------

	def schedule_preventive_maintenance(
		self,
		asset_id: str,
		session: Any,
		frequency_days: int,
		horizon_days: int = 365,
		tenant_id: str = "",
		description: str = "Scheduled preventive maintenance",
		estimated_cost_cents: int = 0,
	) -> list:
		"""Generate a series of preventive MaintenanceWork orders.

		Creates work orders at frequency_days intervals from today out to
		horizon_days.  Skips dates where an existing PLANNED/APPROVED PM
		already exists within ±3 days.

		Returns the list of newly created (unsaved) MaintenanceWork instances.
		Caller must session.add_all() and commit.
		"""
		from pgappforge.plugins.erp.industry.oil_gas.models import (
			Asset, MaintenanceWork,
		)

		asset = session.get(Asset, asset_id)
		if asset is None:
			raise AssetNotFoundError(f"Asset {asset_id!r} not found")

		today = date.today()
		schedule_dates: list[date] = []
		cursor = today + timedelta(days=frequency_days)
		limit = today + timedelta(days=horizon_days)
		while cursor <= limit:
			schedule_dates.append(cursor)
			cursor += timedelta(days=frequency_days)

		# Fetch existing PM work orders to avoid duplicates
		existing = session.execute(
			select(MaintenanceWork.scheduled_start)
			.where(
				MaintenanceWork.asset_id == asset_id,
				MaintenanceWork.work_type == "PREVENTIVE",
				MaintenanceWork.status.in_(["PLANNED", "APPROVED"]),
			)
		).scalars().all()
		existing_dates = {
			d.date() if hasattr(d, "date") else d
			for d in existing
		}

		orders: list[MaintenanceWork] = []
		seq = 1
		for sched_date in schedule_dates:
			# Skip if an existing PM is within 3 days
			conflict = any(
				abs((sched_date - ex).days) <= 3
				for ex in existing_dates
			)
			if conflict:
				continue

			wo_number = (
				f"PM-{asset.tag_number}-"
				f"{sched_date.strftime('%Y%m%d')}-{seq:03d}"
			)
			wo = MaintenanceWork(
				tenant_id=tenant_id or str(asset.tenant_id),
				work_order_number=wo_number,
				asset_id=asset_id,
				work_type="PREVENTIVE",
				description=description,
				scheduled_start=datetime(
					sched_date.year, sched_date.month, sched_date.day,
					8, 0, tzinfo=timezone.utc,
				),
				scheduled_end=datetime(
					sched_date.year, sched_date.month, sched_date.day,
					17, 0, tzinfo=timezone.utc,
				),
				estimated_cost_cents=estimated_cost_cents,
				status="PLANNED",
				safety_requirements={},
			)
			orders.append(wo)
			seq += 1

		log.info(
			"schedule_preventive_maintenance: asset=%r freq=%d days → %d orders",
			asset_id, frequency_days, len(orders),
		)
		return orders

	# ------------------------------------------------------------------
	# Record production
	# ------------------------------------------------------------------

	def record_production(
		self,
		facility_id: str,
		product_type: str,
		quantity: Decimal,
		unit: str,
		session: Any,
		production_date: date | None = None,
		quality: dict | None = None,
		downtime_hours: Decimal = Decimal("0"),
		downtime_reason: str | None = None,
		tenant_id: str = "",
	):
		"""Create a ProductionRecord and emit a ProductionRecordedEvent.

		Returns the newly created (unsaved) ProductionRecord.
		Caller must session.add() and commit.
		"""
		from pgappforge.plugins.erp.industry.oil_gas.models import (
			Facility, ProductionRecord,
		)
		from pgappforge.plugins.erp.industry.oil_gas.events import (
			ProductionRecordedEvent, emit_event,
		)

		if product_type not in VALID_PRODUCT_TYPES:
			raise InvalidProductTypeError(
				f"product_type {product_type!r} must be one of {sorted(VALID_PRODUCT_TYPES)}"
			)

		facility = session.get(Facility, facility_id)
		if facility is None:
			raise FacilityNotFoundError(f"Facility {facility_id!r} not found")

		prod_date = production_date or date.today()

		rec = ProductionRecord(
			tenant_id=tenant_id or str(facility.tenant_id),
			facility_id=facility_id,
			production_date=prod_date,
			product_type=product_type,
			quantity=quantity,
			unit=unit,
			quality_parameters=quality or {},
			downtime_hours=downtime_hours,
			downtime_reason=downtime_reason,
		)

		emit_event(
			"oil_gas.production.recorded",
			"ProductionRecord",
			str(facility_id),
			{
				"facility_id": facility_id,
				"production_date": prod_date.isoformat(),
				"product_type": product_type,
				"quantity": str(quantity),
				"unit": unit,
			},
			session,
			tenant_id=tenant_id or str(facility.tenant_id),
		)

		log.info(
			"record_production: facility=%r date=%s product=%r qty=%s %s",
			facility_id, prod_date, product_type, quantity, unit,
		)
		return rec

	# ------------------------------------------------------------------
	# Asset criticality assessment
	# ------------------------------------------------------------------

	def assess_criticality(
		self,
		asset_id: str,
		session: Any,
	) -> dict:
		"""Score asset criticality and recommend maintenance priority.

		Scoring factors:
		  - Criticality tier (A=10, B=6, C=2)
		  - Open incident count (×2 per incident, max 20)
		  - Overdue maintenance work orders (×3 per WO, max 15)
		  - HAZOP open action items (×1 per item, max 10)
		  - Days since last completed maintenance (>90 days → +5)

		Returns dict: asset_id, tag_number, criticality, score (0-60),
		  maintenance_priority (URGENT/HIGH/MEDIUM/LOW), factors.
		"""
		from pgappforge.plugins.erp.industry.oil_gas.models import (
			Asset, MaintenanceWork, IncidentReport, HAZOPReview,
		)

		asset = session.get(Asset, asset_id)
		if asset is None:
			raise AssetNotFoundError(f"Asset {asset_id!r} not found")

		score = 0
		factors: dict[str, Any] = {}

		# Criticality base score
		crit_score = {"A": 10, "B": 6, "C": 2}.get(str(asset.criticality), 2)
		score += crit_score
		factors["criticality_score"] = crit_score

		# Open incidents at the parent facility
		incident_count = session.execute(
			select(func.count()).where(
				IncidentReport.facility_id == asset.facility_id,
				IncidentReport.status != "CLOSED",
			)
		).scalar_one()
		incident_score = min(incident_count * 2, 20)
		score += incident_score
		factors["open_incidents"] = incident_count
		factors["incident_score"] = incident_score

		# Overdue maintenance work orders
		now = datetime.now(timezone.utc)
		overdue_count = session.execute(
			select(func.count()).where(
				MaintenanceWork.asset_id == asset_id,
				MaintenanceWork.status.in_(["PLANNED", "APPROVED"]),
				MaintenanceWork.scheduled_end < now,
			)
		).scalar_one()
		overdue_score = min(overdue_count * 3, 15)
		score += overdue_score
		factors["overdue_work_orders"] = overdue_count
		factors["overdue_score"] = overdue_score

		# HAZOP open action items
		hazop_rows = session.execute(
			select(HAZOPReview).where(
				HAZOPReview.asset_id == asset_id,
				HAZOPReview.status != "CLOSED",
			)
		).scalars().all()
		open_actions = sum(
			sum(
				1 for a in (h.action_items or [])
				if isinstance(a, dict) and a.get("status") not in ("CLOSED", "COMPLETED")
			)
			for h in hazop_rows
		)
		hazop_score = min(open_actions, 10)
		score += hazop_score
		factors["open_hazop_actions"] = open_actions
		factors["hazop_score"] = hazop_score

		# Days since last completed maintenance
		last_completed = session.execute(
			select(MaintenanceWork.actual_end)
			.where(
				MaintenanceWork.asset_id == asset_id,
				MaintenanceWork.status == "COMPLETED",
				MaintenanceWork.actual_end.is_not(None),
			)
			.order_by(MaintenanceWork.actual_end.desc())
			.limit(1)
		).scalar_one_or_none()

		if last_completed is None:
			days_since = 999
		else:
			lc = last_completed
			if hasattr(lc, "date"):
				lc = lc.replace(tzinfo=timezone.utc) if lc.tzinfo is None else lc
				days_since = (now - lc).days
			else:
				days_since = 999

		staleness_score = 5 if days_since > 90 else 0
		score += staleness_score
		factors["days_since_last_maintenance"] = days_since if days_since < 999 else None
		factors["staleness_score"] = staleness_score

		# Map score to maintenance priority
		if score >= 30:
			priority = "URGENT"
		elif score >= 18:
			priority = "HIGH"
		elif score >= 9:
			priority = "MEDIUM"
		else:
			priority = "LOW"

		return {
			"asset_id": asset_id,
			"tag_number": asset.tag_number,
			"criticality": asset.criticality,
			"score": score,
			"maintenance_priority": priority,
			"factors": factors,
		}

	# ------------------------------------------------------------------
	# Maintenance backlog
	# ------------------------------------------------------------------

	def generate_maintenance_backlog(
		self,
		facility_id: str,
		session: Any,
	) -> list[dict]:
		"""Return all open / overdue work orders for a facility.

		Enriches each record with days_overdue and criticality from the
		parent asset.  Sorted by: FAILED assets first, then by
		scheduled_start ascending.

		Returns list of dicts suitable for dashboard rendering.
		"""
		from pgappforge.plugins.erp.industry.oil_gas.models import (
			Asset, Facility, MaintenanceWork,
		)

		facility = session.get(Facility, facility_id)
		if facility is None:
			raise FacilityNotFoundError(f"Facility {facility_id!r} not found")

		now = datetime.now(timezone.utc)

		rows = session.execute(
			select(MaintenanceWork, Asset)
			.join(Asset, MaintenanceWork.asset_id == Asset.id)
			.where(
				Asset.facility_id == facility_id,
				MaintenanceWork.status.in_(["PLANNED", "APPROVED", "IN_PROGRESS"]),
			)
			.order_by(MaintenanceWork.scheduled_start)
		).all()

		backlog: list[dict] = []
		for wo, asset in rows:
			sched_end = wo.scheduled_end
			if sched_end is not None and sched_end.tzinfo is None:
				sched_end = sched_end.replace(tzinfo=timezone.utc)
			days_overdue = (
				max(0, (now - sched_end).days)
				if sched_end and sched_end < now
				else 0
			)
			backlog.append({
				"work_order_id": str(wo.id),
				"work_order_number": wo.work_order_number,
				"asset_id": str(asset.id),
				"tag_number": asset.tag_number,
				"asset_class": asset.asset_class,
				"criticality": asset.criticality,
				"asset_status": asset.status,
				"work_type": wo.work_type,
				"description": wo.description,
				"scheduled_start": wo.scheduled_start.isoformat() if wo.scheduled_start else None,
				"scheduled_end": sched_end.isoformat() if sched_end else None,
				"status": wo.status,
				"estimated_cost_cents": wo.estimated_cost_cents,
				"days_overdue": days_overdue,
			})

		# Sort: asset FAILED first, then by days_overdue desc
		backlog.sort(key=lambda x: (x["asset_status"] != "FAILED", -x["days_overdue"]))
		return backlog

	# ------------------------------------------------------------------
	# HSE KPIs
	# ------------------------------------------------------------------

	def calculate_hse_kpis(
		self,
		facility_id: str,
		session: Any,
		period_days: int = 365,
	) -> dict:
		"""Calculate HSE KPIs for a facility over a rolling period.

		Metrics returned:
		  TRIR  = Total Recordable Incident Rate
		         = (recordable_incidents × 200_000) / exposure_hours
		  LTIR  = Lost Time Incident Rate
		         = (lost_time_incidents × 200_000) / exposure_hours
		  spill_count: SPILL incidents in period
		  near_miss_count
		  tier1_count, tier2_count, tier3_count
		  environmental_count
		  total_incidents

		exposure_hours = period_days × 24 × headcount_assumption (default 50).
		TRIR/LTIR denominator 200,000 = 100 workers × 2,000 hrs/year.
		"""
		from pgappforge.plugins.erp.industry.oil_gas.models import IncidentReport

		cutoff = date.today() - timedelta(days=period_days)

		incidents = session.execute(
			select(IncidentReport)
			.where(
				IncidentReport.facility_id == facility_id,
				IncidentReport.occurred_at >= datetime(
					cutoff.year, cutoff.month, cutoff.day,
					tzinfo=timezone.utc,
				),
			)
		).scalars().all()

		total = len(incidents)
		spill_count = sum(1 for i in incidents if i.incident_type == "SPILL")
		near_miss_count = sum(1 for i in incidents if i.incident_type == "NEAR_MISS")
		tier1_count = sum(1 for i in incidents if i.severity == "TIER1")
		tier2_count = sum(1 for i in incidents if i.severity == "TIER2")
		tier3_count = sum(1 for i in incidents if i.severity == "TIER3")
		env_count = sum(1 for i in incidents if i.incident_type == "ENVIRONMENTAL")

		# Recordable = injuries > 0 or TIER1/TIER2
		recordable = sum(
			1 for i in incidents
			if (i.injuries or 0) > 0 or i.severity in ("TIER1", "TIER2")
		)
		# Lost time = casualties > 0 or TIER1
		lost_time = sum(
			1 for i in incidents
			if (i.casualties or 0) > 0 or i.severity == "TIER1"
		)

		headcount = 50
		exposure_hours = period_days * 24 * headcount
		trir = (recordable * 200_000 / exposure_hours) if exposure_hours > 0 else 0.0
		ltir = (lost_time * 200_000 / exposure_hours) if exposure_hours > 0 else 0.0

		return {
			"facility_id": facility_id,
			"period_days": period_days,
			"total_incidents": total,
			"recordable_incidents": recordable,
			"lost_time_incidents": lost_time,
			"spill_count": spill_count,
			"near_miss_count": near_miss_count,
			"environmental_count": env_count,
			"tier1_count": tier1_count,
			"tier2_count": tier2_count,
			"tier3_count": tier3_count,
			"exposure_hours": exposure_hours,
			"trir": round(trir, 4),
			"ltir": round(ltir, 4),
		}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"OilGasService",
	"OilGasServiceError",
	"FacilityNotFoundError",
	"AssetNotFoundError",
	"InvalidProductTypeError",
]
