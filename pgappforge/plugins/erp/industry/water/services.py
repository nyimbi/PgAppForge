"""
pgappforge/plugins/erp/industry/water/services.py

Business logic for the Water Management plugin.

All methods are stateless beyond construction.
All volume values returned as Decimal strings.
Session passed explicitly; never committed inside service methods.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import sqlalchemy as sa

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Quality thresholds (WHO/EU WFD defaults — configurable by tenant)
# ---------------------------------------------------------------------------

DEFAULT_THRESHOLDS: dict[str, dict[str, Any]] = {
	"PH":           {"min": Decimal("6.5"), "max": Decimal("8.5"), "unit": "pH"},
	"DO":           {"min": Decimal("5.0"), "max": None,           "unit": "mg/L"},
	"TURBIDITY":    {"min": None,           "max": Decimal("4.0"),  "unit": "NTU"},
	"CONDUCTIVITY": {"min": None,           "max": Decimal("2500"), "unit": "µS/cm"},
	"NITRATE":      {"min": None,           "max": Decimal("10.0"), "unit": "mg/L"},
	"PHOSPHATE":    {"min": None,           "max": Decimal("0.1"),  "unit": "mg/L"},
	"ECOLI":        {"min": None,           "max": Decimal("0.0"),  "unit": "CFU/100mL"},
}

# Flood warning level thresholds (m above gauge datum) — informational defaults
FLOOD_LEVEL_THRESHOLDS: dict[str, Decimal] = {
	"ADVISORY":  Decimal("2.0"),
	"WATCH":     Decimal("3.0"),
	"WARNING":   Decimal("4.0"),
	"EMERGENCY": Decimal("5.0"),
}


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class WaterServiceError(Exception):
	"""Base error for Water Management service layer."""


class WaterBodyNotFoundError(WaterServiceError):
	pass


class StationNotFoundError(WaterServiceError):
	pass


class AllocationNotFoundError(WaterServiceError):
	pass


class InvalidWarningLevelError(WaterServiceError):
	pass


# ---------------------------------------------------------------------------
# WaterService
# ---------------------------------------------------------------------------

class WaterService:
	"""Stateless Water Management service.

	All volume values accepted/returned as Decimal strings.
	"""

	# ------------------------------------------------------------------
	# check_water_quality
	# ------------------------------------------------------------------

	def check_water_quality(
		self,
		station_id: str,
		session: Any,
		parameters: list[str] | None = None,
		thresholds: dict[str, dict[str, Any]] | None = None,
	) -> dict[str, Any]:
		"""Check latest measurement for each parameter against thresholds.

		Returns:
		  {
		    "station_id": str,
		    "checked_at": str,
		    "overall_status": GOOD | SUSPECT | BAD,
		    "violations": [{parameter, value, unit, threshold, direction}],
		    "readings": [{parameter, value, unit, quality_flag, measured_at}],
		  }
		"""
		from pgappforge.plugins.erp.industry.water.models import WaterQualityMeasurement, MonitoringStation

		station = session.get(MonitoringStation, station_id)
		if station is None:
			raise StationNotFoundError(f"MonitoringStation {station_id!r} not found")

		thr = thresholds or DEFAULT_THRESHOLDS
		params_filter = parameters or list(thr.keys())

		violations: list[dict[str, Any]] = []
		readings: list[dict[str, Any]] = []

		for param in params_filter:
			latest = session.execute(
				sa.select(WaterQualityMeasurement).where(
					WaterQualityMeasurement.station_id == station_id,
					WaterQualityMeasurement.parameter == param,
				).order_by(sa.desc(WaterQualityMeasurement.measured_at)).limit(1)
			).scalar_one_or_none()

			if latest is None:
				continue

			val = Decimal(str(latest.value))
			readings.append({
				"parameter": param,
				"value": str(val),
				"unit": latest.unit,
				"quality_flag": latest.quality_flag,
				"measured_at": latest.measured_at.isoformat() if latest.measured_at else None,
			})

			param_thr = thr.get(param, {})
			min_v = param_thr.get("min")
			max_v = param_thr.get("max")

			if min_v is not None and val < Decimal(str(min_v)):
				violations.append({
					"parameter": param,
					"value": str(val),
					"unit": latest.unit,
					"threshold": str(min_v),
					"direction": "BELOW_MIN",
				})
			elif max_v is not None and val > Decimal(str(max_v)):
				violations.append({
					"parameter": param,
					"value": str(val),
					"unit": latest.unit,
					"threshold": str(max_v),
					"direction": "ABOVE_MAX",
				})

		if not violations:
			overall_status = "GOOD"
		elif len(violations) >= 3:
			overall_status = "BAD"
		else:
			overall_status = "SUSPECT"

		return {
			"station_id": station_id,
			"checked_at": datetime.now(timezone.utc).isoformat(),
			"overall_status": overall_status,
			"violations": violations,
			"readings": readings,
		}

	# ------------------------------------------------------------------
	# detect_contamination_events
	# ------------------------------------------------------------------

	def detect_contamination_events(
		self,
		water_body_id: str,
		session: Any,
		threshold_violations: int = 2,
		lookback_hours: int = 24,
	) -> list[dict[str, Any]]:
		"""Detect contamination events across all active stations on a water body.

		A contamination event is defined as >= threshold_violations
		parameter violations at the same station within lookback_hours.

		Returns list of {station_id, station_code, violations, severity, detected_at}
		"""
		from pgappforge.plugins.erp.industry.water.models import (
			WaterBody, MonitoringStation, WaterQualityMeasurement,
		)
		from pgappforge.plugins.erp.industry.water.events import ContaminationDetectedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		wb = session.get(WaterBody, water_body_id)
		if wb is None:
			raise WaterBodyNotFoundError(f"WaterBody {water_body_id!r} not found")

		stations = session.execute(
			sa.select(MonitoringStation).where(
				MonitoringStation.water_body_id == water_body_id,
				MonitoringStation.is_active == True,
			)
		).scalars().all()

		events: list[dict[str, Any]] = []

		for station in stations:
			quality_result = self.check_water_quality(station.id, session)
			viols = quality_result["violations"]
			if len(viols) >= threshold_violations:
				if len(viols) >= 4:
					severity = "CRITICAL"
				elif len(viols) >= 3:
					severity = "HIGH"
				else:
					severity = "MEDIUM"

				events.append({
					"station_id": station.id,
					"station_code": station.station_code,
					"water_body_id": water_body_id,
					"violations": viols,
					"severity": severity,
					"detected_at": datetime.now(timezone.utc).isoformat(),
				})

				emit_event(
					ContaminationDetectedEvent(
						aggregate_id=station.id,
						aggregate_type="MonitoringStation",
						tenant_id=station.tenant_id,
						water_body_id=water_body_id,
						station_id=station.id,
						violated_parameters=viols,
						severity=severity,
					),
					session,
				)

		return events

	# ------------------------------------------------------------------
	# forecast_flood_risk
	# ------------------------------------------------------------------

	def forecast_flood_risk(
		self,
		water_body_id: str,
		session: Any,
		forecast_hours: int = 72,
	) -> dict[str, Any]:
		"""Estimate flood risk based on recent flow trends.

		Uses rate-of-rise analysis on the last 48 hours of flow records
		across all active stations, extrapolated forward.

		Returns:
		  {
		    "water_body_id": str,
		    "forecast_hours": int,
		    "risk_level": LOW | MEDIUM | HIGH | CRITICAL,
		    "current_max_level_m": str,
		    "projected_peak_level_m": str,
		    "trend": RISING | STABLE | FALLING,
		    "stations_analyzed": int,
		    "recommendation": str,
		  }
		"""
		from pgappforge.plugins.erp.industry.water.models import (
			WaterBody, MonitoringStation, WaterFlowRecord,
		)

		wb = session.get(WaterBody, water_body_id)
		if wb is None:
			raise WaterBodyNotFoundError(f"WaterBody {water_body_id!r} not found")

		stations = session.execute(
			sa.select(MonitoringStation).where(
				MonitoringStation.water_body_id == water_body_id,
				MonitoringStation.is_active == True,
			)
		).scalars().all()

		if not stations:
			return {
				"water_body_id": water_body_id,
				"forecast_hours": forecast_hours,
				"risk_level": "LOW",
				"current_max_level_m": "0",
				"projected_peak_level_m": "0",
				"trend": "STABLE",
				"stations_analyzed": 0,
				"recommendation": "No active monitoring stations — risk cannot be assessed",
			}

		current_levels: list[Decimal] = []
		rise_rates: list[Decimal] = []  # m/hr

		for station in stations:
			# Last 48hr of flow records
			recent = session.execute(
				sa.select(WaterFlowRecord).where(
					WaterFlowRecord.station_id == station.id,
					WaterFlowRecord.quality_flag != "BAD",
					WaterFlowRecord.measured_at >= sa.func.now() - sa.text("INTERVAL '48 hours'"),
				).order_by(WaterFlowRecord.measured_at)
			).scalars().all()

			if not recent:
				continue

			levels = [Decimal(str(r.water_level_m or "0")) for r in recent if r.water_level_m is not None]
			if levels:
				current_levels.append(levels[-1])

			# Rate of rise: (current - 24hr ago) / 24hr
			if len(recent) >= 2:
				oldest = recent[0]
				newest = recent[-1]
				if oldest.measured_at and newest.measured_at and oldest.water_level_m and newest.water_level_m:
					dt_hours = (newest.measured_at - oldest.measured_at).total_seconds() / 3600
					if dt_hours > 0:
						rate = (Decimal(str(newest.water_level_m)) - Decimal(str(oldest.water_level_m))) / Decimal(str(dt_hours))
						rise_rates.append(rate)

		if not current_levels:
			return {
				"water_body_id": water_body_id,
				"forecast_hours": forecast_hours,
				"risk_level": "LOW",
				"current_max_level_m": "0",
				"projected_peak_level_m": "0",
				"trend": "STABLE",
				"stations_analyzed": len(stations),
				"recommendation": "Insufficient flow data for forecast",
			}

		current_max = max(current_levels)
		avg_rise_rate = (sum(rise_rates) / len(rise_rates)) if rise_rates else Decimal("0")
		projected_peak = (current_max + avg_rise_rate * Decimal(str(forecast_hours))).quantize(
			Decimal("0.001"), rounding=ROUND_HALF_UP
		)
		projected_peak = max(projected_peak, current_max)  # never forecast below current

		# Trend
		if avg_rise_rate > Decimal("0.05"):
			trend = "RISING"
		elif avg_rise_rate < Decimal("-0.05"):
			trend = "FALLING"
		else:
			trend = "STABLE"

		# Risk level based on projected peak vs threshold levels
		if projected_peak >= FLOOD_LEVEL_THRESHOLDS["EMERGENCY"]:
			risk_level = "CRITICAL"
			recommendation = "EMERGENCY: Immediate evacuation of flood-risk areas. Activate emergency response protocol."
		elif projected_peak >= FLOOD_LEVEL_THRESHOLDS["WARNING"]:
			risk_level = "HIGH"
			recommendation = "WARNING: Issue flood warning. Alert emergency services. Monitor continuously."
		elif projected_peak >= FLOOD_LEVEL_THRESHOLDS["WATCH"]:
			risk_level = "MEDIUM"
			recommendation = "WATCH: Prepare flood response teams. Alert downstream communities."
		elif projected_peak >= FLOOD_LEVEL_THRESHOLDS["ADVISORY"]:
			risk_level = "LOW"
			recommendation = "ADVISORY: Monitor river levels. Review emergency plans."
		else:
			risk_level = "LOW"
			recommendation = "No flood risk — continue routine monitoring."

		return {
			"water_body_id": water_body_id,
			"forecast_hours": forecast_hours,
			"risk_level": risk_level,
			"current_max_level_m": str(current_max),
			"projected_peak_level_m": str(projected_peak),
			"avg_rise_rate_m_per_hr": str(avg_rise_rate.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)),
			"trend": trend,
			"stations_analyzed": len(stations),
			"recommendation": recommendation,
		}

	# ------------------------------------------------------------------
	# issue_flood_warning
	# ------------------------------------------------------------------

	def issue_flood_warning(
		self,
		water_body_id: str,
		level: str,
		forecast_details: dict[str, Any],
		session: Any,
		issued_by: str | None = None,
	) -> Any:
		"""Create and persist a FloodWarning. Emits FloodWarningIssuedEvent.

		forecast_details keys (all optional):
		  peak_level_m: Decimal string
		  peak_at: ISO datetime string
		  affected_areas: list[dict]
		  notes: str
		"""
		from pgappforge.plugins.erp.industry.water.models import FloodWarning, WaterBody
		from pgappforge.plugins.erp.industry.water.events import FloodWarningIssuedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		valid_levels = ("ADVISORY", "WATCH", "WARNING", "EMERGENCY")
		if level not in valid_levels:
			raise InvalidWarningLevelError(f"Invalid warning level {level!r}; must be one of {valid_levels}")

		wb = session.get(WaterBody, water_body_id)
		if wb is None:
			raise WaterBodyNotFoundError(f"WaterBody {water_body_id!r} not found")

		peak_at = None
		peak_at_str = forecast_details.get("peak_at")
		if peak_at_str:
			try:
				peak_at = datetime.fromisoformat(peak_at_str)
			except (ValueError, TypeError):
				pass

		warning = FloodWarning(
			tenant_id=wb.tenant_id,
			water_body_id=water_body_id,
			warning_level=level,
			issued_at=datetime.now(timezone.utc),
			forecast_peak_level_m=forecast_details.get("peak_level_m"),
			forecast_peak_at=peak_at,
			affected_areas=forecast_details.get("affected_areas") or [],
			status="ACTIVE",
			issued_by=issued_by,
			notes=forecast_details.get("notes"),
		)
		session.add(warning)
		session.flush()

		emit_event(
			FloodWarningIssuedEvent(
				aggregate_id=warning.id,
				aggregate_type="FloodWarning",
				tenant_id=wb.tenant_id,
				warning_id=warning.id,
				water_body_id=water_body_id,
				water_body_name=wb.name,
				warning_level=level,
				forecast_peak_level_m=str(warning.forecast_peak_level_m or ""),
				forecast_peak_at=warning.forecast_peak_at.isoformat() if warning.forecast_peak_at else "",
				affected_area_count=len(warning.affected_areas),
			),
			session,
		)
		return warning

	# ------------------------------------------------------------------
	# cancel_flood_warning
	# ------------------------------------------------------------------

	def cancel_flood_warning(
		self,
		warning_id: str,
		reason: str,
		cancelled_by: str,
		session: Any,
	) -> Any:
		"""Set FloodWarning status to CANCELLED. Emits FloodWarningCancelledEvent."""
		from pgappforge.plugins.erp.industry.water.models import FloodWarning
		from pgappforge.plugins.erp.industry.water.events import FloodWarningCancelledEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		warning = session.get(FloodWarning, warning_id)
		if warning is None:
			raise WaterServiceError(f"FloodWarning {warning_id!r} not found")
		if warning.status != "ACTIVE":
			raise WaterServiceError(f"FloodWarning is already {warning.status!r}")

		warning.status = "CANCELLED"
		warning.updated_at = datetime.now(timezone.utc)

		emit_event(
			FloodWarningCancelledEvent(
				aggregate_id=warning.id,
				aggregate_type="FloodWarning",
				tenant_id=warning.tenant_id,
				warning_id=warning.id,
				water_body_id=warning.water_body_id,
				cancelled_by=cancelled_by,
				reason=reason,
			),
			session,
		)
		return warning

	# ------------------------------------------------------------------
	# track_allocation_usage
	# ------------------------------------------------------------------

	def track_allocation_usage(
		self,
		allocation_id: str,
		session: Any,
	) -> dict[str, Any]:
		"""Return current usage statistics for a water allocation.

		Returns:
		  {
		    "allocation_id": str,
		    "permit_number": str,
		    "allocated_m3": str,
		    "used_m3": str,
		    "remaining_m3": str,
		    "usage_pct": str,
		    "status": str,
		    "days_remaining_in_year": int,
		    "projected_year_end_usage_m3": str,
		    "warning": str | None,
		  }
		"""
		from pgappforge.plugins.erp.industry.water.models import WaterAllocation
		from pgappforge.plugins.erp.industry.water.events import AllocationExceededEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		alloc = session.get(WaterAllocation, allocation_id)
		if alloc is None:
			raise AllocationNotFoundError(f"WaterAllocation {allocation_id!r} not found")

		allocated = Decimal(str(alloc.allocated_m3_per_year))
		used = Decimal(str(alloc.used_m3_this_year))
		remaining = (allocated - used).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

		usage_pct = Decimal("0")
		if allocated > Decimal("0"):
			usage_pct = (used / allocated * Decimal("100")).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)

		today = date.today()
		year_end = date(today.year, 12, 31)
		days_remaining = (year_end - today).days
		day_of_year = today.timetuple().tm_yday
		days_in_year = 366 if today.year % 4 == 0 else 365

		# Linear projection to year end
		projected_year_end = Decimal("0")
		if day_of_year > 0 and used > Decimal("0"):
			daily_rate = used / Decimal(str(day_of_year))
			projected_year_end = (daily_rate * Decimal(str(days_in_year))).quantize(
				Decimal("0.01"), rounding=ROUND_HALF_UP
			)

		warning: str | None = None
		if usage_pct >= Decimal("100"):
			warning = f"CRITICAL: Allocation exceeded — {usage_pct}% used of annual entitlement"
			emit_event(
				AllocationExceededEvent(
					aggregate_id=alloc.id, aggregate_type="WaterAllocation",
					tenant_id=alloc.tenant_id, allocation_id=alloc.id,
					permit_number=alloc.permit_number, holder_id=str(alloc.holder_id),
					allocated_m3=str(allocated), used_m3=str(used),
					usage_pct=str(usage_pct), severity="CRITICAL",
				),
				session,
			)
		elif usage_pct >= Decimal("80"):
			warning = f"WARNING: {usage_pct}% of annual water allocation consumed — projected {projected_year_end}m³ at year end"
			emit_event(
				AllocationExceededEvent(
					aggregate_id=alloc.id, aggregate_type="WaterAllocation",
					tenant_id=alloc.tenant_id, allocation_id=alloc.id,
					permit_number=alloc.permit_number, holder_id=str(alloc.holder_id),
					allocated_m3=str(allocated), used_m3=str(used),
					usage_pct=str(usage_pct), severity="WARNING",
				),
				session,
			)

		return {
			"allocation_id": allocation_id,
			"permit_number": alloc.permit_number,
			"allocation_type": alloc.allocation_type,
			"allocated_m3": str(allocated),
			"used_m3": str(used),
			"remaining_m3": str(remaining),
			"usage_pct": str(usage_pct),
			"status": alloc.status,
			"days_remaining_in_year": days_remaining,
			"projected_year_end_usage_m3": str(projected_year_end),
			"warning": warning,
		}

	# ------------------------------------------------------------------
	# record_abstraction
	# ------------------------------------------------------------------

	def record_abstraction(
		self,
		allocation_id: str,
		volume_m3: Decimal,
		session: Any,
	) -> Any:
		"""Increment used_m3_this_year for an allocation and check for overage."""
		from pgappforge.plugins.erp.industry.water.models import WaterAllocation

		alloc = session.get(WaterAllocation, allocation_id)
		if alloc is None:
			raise AllocationNotFoundError(f"WaterAllocation {allocation_id!r} not found")
		if alloc.status != "ACTIVE":
			raise WaterServiceError(f"Allocation {allocation_id!r} is {alloc.status!r} — cannot record abstraction")
		if volume_m3 <= Decimal("0"):
			raise WaterServiceError("volume_m3 must be positive")

		alloc.used_m3_this_year = (
			Decimal(str(alloc.used_m3_this_year)) + volume_m3
		).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
		alloc.updated_at = datetime.now(timezone.utc)
		return alloc

	# ------------------------------------------------------------------
	# generate_water_quality_report
	# ------------------------------------------------------------------

	def generate_water_quality_report(
		self,
		water_body_id: str,
		period_start: date,
		period_end: date,
		session: Any,
	) -> dict[str, Any]:
		"""Generate a water quality report for a water body over a date range.

		Returns:
		  {
		    "water_body": {id, name, type, status},
		    "period": {start, end},
		    "stations": int,
		    "total_measurements": int,
		    "parameter_summary": [
		      {parameter, count, mean, min, max, bad_count, violation_count}
		    ],
		    "overall_quality": GOOD | MODERATE | POOR | BAD,
		    "active_warnings": [FloodWarning summaries],
		  }
		"""
		from pgappforge.plugins.erp.industry.water.models import (
			WaterBody, MonitoringStation, WaterQualityMeasurement, FloodWarning,
		)

		wb = session.get(WaterBody, water_body_id)
		if wb is None:
			raise WaterBodyNotFoundError(f"WaterBody {water_body_id!r} not found")

		stations = session.execute(
			sa.select(MonitoringStation).where(
				MonitoringStation.water_body_id == water_body_id,
			)
		).scalars().all()

		station_ids = [s.id for s in stations]
		param_summary: list[dict[str, Any]] = []
		total_measurements = 0

		if station_ids:
			# Aggregate by parameter
			param_rows = session.execute(
				sa.select(
					WaterQualityMeasurement.parameter,
					sa.func.count().label("count"),
					sa.func.avg(WaterQualityMeasurement.value).label("mean"),
					sa.func.min(WaterQualityMeasurement.value).label("min_val"),
					sa.func.max(WaterQualityMeasurement.value).label("max_val"),
					sa.func.sum(
						sa.case((WaterQualityMeasurement.quality_flag == "BAD", 1), else_=0)
					).label("bad_count"),
				).where(
					WaterQualityMeasurement.station_id.in_(station_ids),
					WaterQualityMeasurement.measured_at >= sa.func.cast(period_start.isoformat(), sa.Date),
					WaterQualityMeasurement.measured_at <= sa.func.cast(period_end.isoformat(), sa.Date),
				).group_by(WaterQualityMeasurement.parameter)
				.order_by(WaterQualityMeasurement.parameter)
			).all()

			for row in param_rows:
				thr = DEFAULT_THRESHOLDS.get(row.parameter, {})
				mean_val = Decimal(str(row.mean or "0"))
				min_val = Decimal(str(row.min_val or "0"))
				max_val = Decimal(str(row.max_val or "0"))

				# Violation count: measurements outside threshold
				violations = 0
				if thr.get("max") is not None and max_val > Decimal(str(thr["max"])):
					violations += 1
				if thr.get("min") is not None and min_val < Decimal(str(thr["min"])):
					violations += 1

				param_summary.append({
					"parameter": row.parameter,
					"count": row.count,
					"mean": str(mean_val.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)),
					"min": str(min_val.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)),
					"max": str(max_val.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)),
					"bad_count": row.bad_count or 0,
					"violation_count": violations,
					"unit": thr.get("unit", ""),
				})
				total_measurements += row.count

		# Overall quality score
		total_bad = sum(p["bad_count"] for p in param_summary)
		total_violations = sum(p["violation_count"] for p in param_summary)
		if total_measurements == 0:
			overall_quality = "MODERATE"
		elif total_violations >= 3 or (total_bad / max(total_measurements, 1)) > 0.2:
			overall_quality = "BAD"
		elif total_violations >= 1 or (total_bad / max(total_measurements, 1)) > 0.05:
			overall_quality = "POOR"
		elif total_bad > 0:
			overall_quality = "MODERATE"
		else:
			overall_quality = "GOOD"

		# Active warnings
		active_warnings_rows = session.execute(
			sa.select(FloodWarning).where(
				FloodWarning.water_body_id == water_body_id,
				FloodWarning.status == "ACTIVE",
			).order_by(sa.desc(FloodWarning.issued_at))
		).scalars().all()

		active_warnings = [
			{
				"warning_id": w.id,
				"level": w.warning_level,
				"issued_at": w.issued_at.isoformat() if w.issued_at else None,
				"forecast_peak_level_m": str(w.forecast_peak_level_m or ""),
			}
			for w in active_warnings_rows
		]

		return {
			"water_body": {
				"id": wb.id,
				"name": wb.name,
				"type": wb.body_type,
				"status": wb.status,
				"catchment_area_km2": str(wb.catchment_area_km2 or ""),
			},
			"period": {
				"start": period_start.isoformat(),
				"end": period_end.isoformat(),
			},
			"stations": len(stations),
			"total_measurements": total_measurements,
			"parameter_summary": param_summary,
			"overall_quality": overall_quality,
			"active_warnings": active_warnings,
		}


__all__ = [
	"WaterService",
	"WaterServiceError",
	"WaterBodyNotFoundError",
	"StationNotFoundError",
	"AllocationNotFoundError",
	"InvalidWarningLevelError",
	"DEFAULT_THRESHOLDS",
	"FLOOD_LEVEL_THRESHOLDS",
]
