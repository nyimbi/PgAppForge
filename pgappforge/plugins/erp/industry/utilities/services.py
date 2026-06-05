"""
pgappforge/plugins/erp/industry/utilities/services.py

UtilitiesService — stateless service for the Utilities / Smart Grid domain.

Responsibilities:
  - AMI interval data ingestion (bulk)
  - Outage detection and lifecycle management
  - SAIDI / SAIFI / CAIDI reliability index calculation
  - Probabilistic load forecasting (hour-ahead, day-ahead)
  - Demand response event dispatching
  - Green Button ESPI XML export (NAESB REQ.21)
"""
from __future__ import annotations

import logging
import math
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy import select, func

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class UtilitiesServiceError(Exception):
	"""Base error for Utilities domain violations."""


class MeterNotFoundError(UtilitiesServiceError):
	"""No EnergyMeter with the given id."""


class OutageNotFoundError(UtilitiesServiceError):
	"""No OutageEvent with the given id."""


class InvalidIntervalError(UtilitiesServiceError):
	"""Interval data failed validation (overlap, gap, bad values)."""


# ---------------------------------------------------------------------------
# UtilitiesService
# ---------------------------------------------------------------------------

class UtilitiesService:
	"""Stateless Utilities / Smart Grid service."""

	VALID_ASSET_TYPES = frozenset({
		"SUBSTATION", "TRANSFORMER", "LINE", "SWITCH", "METER", "GENERATOR",
	})
	VALID_OUTAGE_TYPES = frozenset({"PLANNED", "UNPLANNED", "EMERGENCY"})
	VALID_DR_STATUSES = frozenset({"PLANNED", "ACTIVE", "COMPLETED"})

	# ------------------------------------------------------------------
	# AMI Data Ingestion
	# ------------------------------------------------------------------

	def ingest_ami_data(
		self,
		session: Any,
		meter_id: str,
		interval_data: list[dict],
		tenant_id: str = "",
	) -> int:
		"""Bulk-ingest AMI interval data for a meter.

		Each dict in interval_data must contain:
		  interval_start: ISO timestamp string or datetime
		  interval_end:   ISO timestamp string or datetime
		  consumption_kwh: float / Decimal
		  demand_kw:       float (optional)
		  power_factor:    float 0–1 (optional)
		  quality_code:    int (optional, default 0)

		Skips duplicate (meter_id, interval_start) rows silently.
		Returns count of rows actually inserted.
		"""
		from pgappforge.plugins.erp.industry.utilities.models import (
			EnergyMeter, IntervalData,
		)
		from pgappforge.plugins.erp.industry.utilities.events import AMIDataIngestedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event as _emit

		meter = session.get(EnergyMeter, meter_id)
		if meter is None:
			raise MeterNotFoundError(f"EnergyMeter {meter_id!r} not found")

		# Fetch existing interval_starts for this meter to skip dupes
		existing_starts: set[datetime] = set(
			session.execute(
				select(IntervalData.interval_start).where(
					IntervalData.meter_id == meter_id
				)
			).scalars().all()
		)

		inserted = 0
		period_start: datetime | None = None
		period_end: datetime | None = None

		for row in interval_data:
			iv_start = _parse_ts(row["interval_start"])
			iv_end = _parse_ts(row["interval_end"])

			if iv_start in existing_starts:
				continue

			rec = IntervalData(
				tenant_id=tenant_id or str(meter.tenant_id),
				meter_id=meter_id,
				interval_start=iv_start,
				interval_end=iv_end,
				consumption_kwh=Decimal(str(row["consumption_kwh"])),
				demand_kw=(
					Decimal(str(row["demand_kw"])) if row.get("demand_kw") is not None else None
				),
				power_factor=(
					Decimal(str(row["power_factor"])) if row.get("power_factor") is not None else None
				),
				quality_code=int(row.get("quality_code", 0)),
			)
			session.add(rec)
			existing_starts.add(iv_start)
			inserted += 1

			if period_start is None or iv_start < period_start:
				period_start = iv_start
			if period_end is None or iv_end > period_end:
				period_end = iv_end

		if inserted:
			session.flush()
			# Update last_read_date on the meter
			if period_end:
				meter.last_read_date = period_end.date()

			_emit(AMIDataIngestedEvent(
				aggregate_id=meter_id,
				aggregate_type="EnergyMeter",
				tenant_id=tenant_id,
				meter_id=meter_id,
				record_count=inserted,
				period_start=period_start.isoformat() if period_start else "",
				period_end=period_end.isoformat() if period_end else "",
			), session)

		log.info(
			"UtilitiesService: ingest_ami_data meter=%r inserted=%d",
			meter_id, inserted,
		)
		return inserted

	# ------------------------------------------------------------------
	# Outage Detection
	# ------------------------------------------------------------------

	def detect_outage(
		self,
		session: Any,
		affected_assets: list[str],
		cause: str,
		outage_type: str = "UNPLANNED",
		tenant_id: str = "",
		affected_customers: int = 0,
	) -> Any:
		"""Create an OutageEvent record for a detected outage.

		affected_assets: list of GridAsset.id UUIDs.
		Emits OutageDetectedEvent.

		Returns the newly created OutageEvent.
		"""
		from pgappforge.plugins.erp.industry.utilities.models import OutageEvent
		from pgappforge.plugins.erp.industry.utilities.events import OutageDetectedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event as _emit

		if outage_type not in self.VALID_OUTAGE_TYPES:
			raise UtilitiesServiceError(
				f"outage_type must be one of {self.VALID_OUTAGE_TYPES}"
			)

		import uuid as _uuid
		now = datetime.now(timezone.utc)
		outage_id = f"OUT-{now.strftime('%Y%m%d')}-{_uuid.uuid4().hex[:8].upper()}"

		event = OutageEvent(
			tenant_id=tenant_id,
			outage_id=outage_id,
			outage_type=outage_type,
			cause=cause,
			affected_assets=affected_assets,
			affected_customers=affected_customers,
			reported_at=now,
			started_at=now,
			status="REPORTED",
			saidi_minutes=Decimal("0"),
			saifi_occurrences=Decimal("0"),
			crew_ids=[],
		)
		session.add(event)
		session.flush()

		_emit(OutageDetectedEvent(
			aggregate_id=event.id,
			aggregate_type="OutageEvent",
			tenant_id=tenant_id,
			outage_id=event.id,
			outage_type=outage_type,
			cause=cause,
			affected_customers=affected_customers,
			affected_asset_count=len(affected_assets),
		), session)

		log.info(
			"UtilitiesService: outage detected id=%r type=%r assets=%d",
			outage_id, outage_type, len(affected_assets),
		)
		return event

	# ------------------------------------------------------------------
	# Reliability Indices
	# ------------------------------------------------------------------

	def calculate_reliability_indices(
		self,
		session: Any,
		period_start: datetime,
		period_end: datetime,
		tenant_id: str = "",
		total_customers: int = 1,
	) -> dict:
		"""Calculate SAIDI, SAIFI, CAIDI for a reporting period.

		SAIDI = sum(customer_interruption_durations) / total_customers
		SAIFI = sum(customer_interruptions) / total_customers
		CAIDI = SAIDI / SAIFI  (0 if SAIFI = 0)

		Uses OutageEvent rows with status=RESTORED within the period.

		Args:
		  total_customers: denominator (utility total connected customers)

		Returns:
		  {
		    "period_start": str,
		    "period_end": str,
		    "total_customers": int,
		    "total_outages": int,
		    "saidi_minutes": float,
		    "saifi": float,
		    "caidi_minutes": float,
		    "availability_pct": float,
		  }
		"""
		from pgappforge.plugins.erp.industry.utilities.models import OutageEvent
		from pgappforge.plugins.erp.industry.utilities.events import (
			ReliabilityIndicesCalculatedEvent,
		)
		from pgappforge.plugins.erp.foundation.events import emit_event as _emit

		q = (
			select(
				func.sum(OutageEvent.saidi_minutes).label("total_saidi"),
				func.sum(OutageEvent.saifi_occurrences).label("total_saifi"),
				func.count().label("outage_count"),
			)
			.where(
				OutageEvent.status == "RESTORED",
				OutageEvent.started_at >= period_start,
				OutageEvent.started_at <= period_end,
			)
		)
		if tenant_id:
			q = q.where(OutageEvent.tenant_id == tenant_id)

		row = session.execute(q).one()
		total_saidi = float(row.total_saidi or 0)
		total_saifi = float(row.total_saifi or 0)
		outage_count = int(row.outage_count or 0)

		n = max(1, total_customers)
		saidi = total_saidi / n
		saifi = total_saifi / n
		caidi = (saidi / saifi) if saifi > 0 else 0.0

		# Availability = 1 - SAIDI / (minutes in period)
		period_minutes = (period_end - period_start).total_seconds() / 60.0
		availability_pct = max(0.0, (1 - saidi / period_minutes) * 100) if period_minutes else 100.0

		result = {
			"period_start": period_start.isoformat(),
			"period_end": period_end.isoformat(),
			"total_customers": total_customers,
			"total_outages": outage_count,
			"saidi_minutes": round(saidi, 4),
			"saifi": round(saifi, 6),
			"caidi_minutes": round(caidi, 4),
			"availability_pct": round(availability_pct, 4),
		}

		_emit(ReliabilityIndicesCalculatedEvent(
			aggregate_id=tenant_id or "system",
			aggregate_type="UtilitySystem",
			tenant_id=tenant_id,
			saidi=saidi,
			saifi=saifi,
			caidi=caidi,
			period_start=period_start.isoformat(),
			period_end=period_end.isoformat(),
		), session)

		return result

	# ------------------------------------------------------------------
	# Load Forecasting
	# ------------------------------------------------------------------

	def model_load_forecast(
		self,
		session: Any,
		area_id: str,
		hours_ahead: int = 24,
		tenant_id: str = "",
	) -> list[dict]:
		"""Generate an hour-ahead load forecast using historical AMI data.

		Method: same-day-of-week average from last 4 weeks of interval data
		aggregated across all meters linked to grid assets in the area.

		area_id: GridAsset.id (typically a SUBSTATION) — forecasts its subtree.

		Returns list of hourly dicts:
		  [{"hour": "2024-01-01T00:00:00Z", "forecast_mw": 12.34}, ...]
		"""
		from pgappforge.plugins.erp.industry.utilities.models import (
			GridAsset, EnergyMeter, IntervalData,
		)

		now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
		target_dow = now.weekday()	# 0=Mon…6=Sun

		# Fetch meters linked to this area's grid asset
		meter_ids = session.execute(
			select(EnergyMeter.id).where(
				EnergyMeter.grid_asset_id == area_id,
			)
		).scalars().all()

		if not meter_ids:
			# No meters — return zeroed forecast
			return [
				{
					"hour": (now + timedelta(hours=h)).isoformat(),
					"forecast_mw": 0.0,
					"confidence": 0.0,
				}
				for h in range(hours_ahead)
			]

		# Historical same-day-of-week intervals for last 4 weeks
		lookback_start = now - timedelta(weeks=4)
		historical = session.execute(
			select(
				func.date_trunc("hour", IntervalData.interval_start).label("hour_bucket"),
				func.sum(IntervalData.consumption_kwh).label("total_kwh"),
				func.count().label("meter_count"),
			)
			.where(
				IntervalData.meter_id.in_(list(meter_ids)),
				IntervalData.interval_start >= lookback_start,
				IntervalData.interval_start < now,
				sa.extract("dow", IntervalData.interval_start) == target_dow,
			)
			.group_by("hour_bucket")
			.order_by("hour_bucket")
		).all()

		# Build hour-of-day → average MW map
		hour_avg: dict[int, list[float]] = {}
		for row in historical:
			if row.hour_bucket and row.total_kwh:
				h = row.hour_bucket.hour
				# kWh per 15-min interval → kW → MW
				mw = float(row.total_kwh) / 1000.0
				hour_avg.setdefault(h, []).append(mw)

		avg_by_hour = {
			h: sum(vals) / len(vals) for h, vals in hour_avg.items()
		}

		forecast = []
		for i in range(hours_ahead):
			target_hour = now + timedelta(hours=i)
			h = target_hour.hour
			mw = avg_by_hour.get(h, 0.0)
			confidence = 0.8 if h in avg_by_hour else 0.0
			forecast.append({
				"hour": target_hour.isoformat(),
				"forecast_mw": round(mw, 3),
				"confidence": confidence,
			})

		log.info(
			"UtilitiesService: load_forecast area=%r hours=%d",
			area_id, hours_ahead,
		)
		return forecast

	# ------------------------------------------------------------------
	# Demand Response
	# ------------------------------------------------------------------

	def dispatch_demand_response(
		self,
		session: Any,
		program_name: str,
		target_reduction_kw: float,
		event_start: datetime | None = None,
		event_end: datetime | None = None,
		enrolled_customers: int = 0,
		tenant_id: str = "",
	) -> Any:
		"""Create and activate a demand response event.

		Emits DemandResponseDispatchedEvent.
		Returns the newly created DemandResponseEvent.
		"""
		from pgappforge.plugins.erp.industry.utilities.models import DemandResponseEvent
		from pgappforge.plugins.erp.industry.utilities.events import (
			DemandResponseDispatchedEvent,
		)
		from pgappforge.plugins.erp.foundation.events import emit_event as _emit

		now = datetime.now(timezone.utc)
		if event_start is None:
			event_start = now
		if event_end is None:
			event_end = event_start + timedelta(hours=2)

		if target_reduction_kw <= 0:
			raise UtilitiesServiceError("target_reduction_kw must be positive")

		dr = DemandResponseEvent(
			tenant_id=tenant_id,
			program_name=program_name,
			event_start=event_start,
			event_end=event_end,
			target_reduction_kw=Decimal(str(target_reduction_kw)),
			enrolled_customers=enrolled_customers,
			achieved_reduction_kw=Decimal("0"),
			status="ACTIVE",
		)
		session.add(dr)
		session.flush()

		_emit(DemandResponseDispatchedEvent(
			aggregate_id=dr.id,
			aggregate_type="DemandResponseEvent",
			tenant_id=tenant_id,
			dr_event_id=dr.id,
			program_name=program_name,
			target_reduction_kw=float(target_reduction_kw),
			enrolled_customers=enrolled_customers,
		), session)

		log.info(
			"UtilitiesService: DR dispatched program=%r target=%.2fkW",
			program_name, target_reduction_kw,
		)
		return dr

	# ------------------------------------------------------------------
	# Green Button ESPI XML Export
	# ------------------------------------------------------------------

	def generate_green_button_export(
		self,
		session: Any,
		meter_id: str,
		start_date: datetime,
		end_date: datetime,
	) -> str:
		"""Generate a Green Button ESPI XML export for a meter and date range.

		Returns: well-formed ESPI XML string (NAESB REQ.21 / Energy Services
		Provider Interface).  The caller is responsible for serving it with
		Content-Type: application/atom+xml.

		The ESPI structure:
		  <feed>
		    <entry> — UsagePoint
		      <content><UsagePoint>...</UsagePoint></content>
		    </entry>
		    <entry> — MeterReading
		      <content><MeterReading>...</MeterReading></content>
		    </entry>
		    <entry> per IntervalBlock
		      <content><IntervalBlock>...</IntervalBlock></content>
		    </entry>
		  </feed>
		"""
		from pgappforge.plugins.erp.industry.utilities.models import (
			EnergyMeter, IntervalData,
		)

		meter = session.get(EnergyMeter, meter_id)
		if meter is None:
			raise MeterNotFoundError(f"EnergyMeter {meter_id!r} not found")

		rows = session.execute(
			select(IntervalData)
			.where(
				IntervalData.meter_id == meter_id,
				IntervalData.interval_start >= start_date,
				IntervalData.interval_end <= end_date,
			)
			.order_by(IntervalData.interval_start)
		).scalars().all()

		# ESPI namespace
		ns = "http://naesb.org/espi"
		atom = "http://www.w3.org/2005/Atom"

		feed = ET.Element(f"{{{atom}}}feed")
		ET.SubElement(feed, f"{{{atom}}}id").text = f"urn:uuid:{meter.meter_id}"
		ET.SubElement(feed, f"{{{atom}}}title").text = f"Green Button Data — {meter.meter_id}"
		ET.SubElement(feed, f"{{{atom}}}updated").text = datetime.now(timezone.utc).isoformat()

		# UsagePoint entry
		up_entry = ET.SubElement(feed, f"{{{atom}}}entry")
		ET.SubElement(up_entry, f"{{{atom}}}id").text = (
			f"urn:uuid:usage-point-{meter.meter_id}"
		)
		ET.SubElement(up_entry, f"{{{atom}}}title").text = "UsagePoint"
		up_content = ET.SubElement(up_entry, f"{{{atom}}}content")
		usage_point = ET.SubElement(up_content, f"{{{ns}}}UsagePoint")
		ET.SubElement(usage_point, f"{{{ns}}}kind").text = "0"  # 0=electricity

		# MeterReading entry
		mr_entry = ET.SubElement(feed, f"{{{atom}}}entry")
		ET.SubElement(mr_entry, f"{{{atom}}}id").text = (
			f"urn:uuid:meter-reading-{meter.meter_id}"
		)
		ET.SubElement(mr_entry, f"{{{atom}}}title").text = "MeterReading"
		mr_content = ET.SubElement(mr_entry, f"{{{atom}}}content")
		meter_reading = ET.SubElement(mr_content, f"{{{ns}}}MeterReading")
		reading_type = ET.SubElement(meter_reading, f"{{{ns}}}ReadingType")
		ET.SubElement(reading_type, f"{{{ns}}}accumulationBehaviour").text = "4"  # deltaData
		ET.SubElement(reading_type, f"{{{ns}}}commodity").text = "1"  # electricity
		ET.SubElement(reading_type, f"{{{ns}}}uom").text = "72"  # Wh

		# IntervalBlock entries (group by day)
		if rows:
			ib_entry = ET.SubElement(feed, f"{{{atom}}}entry")
			ET.SubElement(ib_entry, f"{{{atom}}}id").text = (
				f"urn:uuid:interval-block-{meter.meter_id}"
			)
			ET.SubElement(ib_entry, f"{{{atom}}}title").text = "IntervalBlock"
			ib_content = ET.SubElement(ib_entry, f"{{{atom}}}content")
			interval_block = ET.SubElement(ib_content, f"{{{ns}}}IntervalBlock")

			# Block interval: full requested range
			block_interval = ET.SubElement(interval_block, f"{{{ns}}}interval")
			ET.SubElement(block_interval, f"{{{ns}}}duration").text = str(
				int((end_date - start_date).total_seconds())
			)
			ET.SubElement(block_interval, f"{{{ns}}}start").text = str(
				int(start_date.timestamp())
			)

			for r in rows:
				ir = ET.SubElement(interval_block, f"{{{ns}}}IntervalReading")
				iv = ET.SubElement(ir, f"{{{ns}}}timePeriod")
				duration_secs = int(
					(r.interval_end - r.interval_start).total_seconds()
				)
				ET.SubElement(iv, f"{{{ns}}}duration").text = str(duration_secs)
				ET.SubElement(iv, f"{{{ns}}}start").text = str(
					int(r.interval_start.timestamp())
				)
				# kWh → Wh (integer)
				wh = int(float(r.consumption_kwh) * 1000)
				ET.SubElement(ir, f"{{{ns}}}value").text = str(wh)
				ET.SubElement(ir, f"{{{ns}}}ReadingQuality").text = str(r.quality_code)

		return ET.tostring(feed, encoding="unicode", xml_declaration=False)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_ts(value: Any) -> datetime:
	"""Parse an ISO string or pass-through a datetime."""
	if isinstance(value, datetime):
		return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
	if isinstance(value, str):
		dt = datetime.fromisoformat(value)
		return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
	raise TypeError(f"Expected datetime or ISO string, got {type(value)}")


__all__ = [
	"UtilitiesService",
	"UtilitiesServiceError",
	"MeterNotFoundError",
	"OutageNotFoundError",
	"InvalidIntervalError",
]
