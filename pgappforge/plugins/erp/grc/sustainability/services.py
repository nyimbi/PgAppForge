"""
pgappforge/plugins/erp/grc/sustainability/services.py

SustainabilityService — stateless service for ESG / GHG emissions domain.

Responsibilities:
  - EmissionSource CRUD (factor master data)
  - EmissionRecord creation with automatic CO2e calculation
  - ESGMetric definition and target management
  - ESGSnapshot capture with YoY improvement calculation
  - GHG scope rollup reporting
  - ESG dashboard data assembly
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

import sqlalchemy as sa
from sqlalchemy import select, func

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class SustainabilityServiceError(Exception):
	"""Base error for Sustainability domain violations."""


class EmissionSourceNotFoundError(SustainabilityServiceError):
	"""No EmissionSource with the given id."""


class ESGMetricNotFoundError(SustainabilityServiceError):
	"""No ESGMetric with the given id or code."""


class ESGSnapshotExistsError(SustainabilityServiceError):
	"""Snapshot already exists for this metric+year; cannot duplicate."""


class VerifiedRecordError(SustainabilityServiceError):
	"""Cannot modify a verified emission record; insert a correction instead."""


# ---------------------------------------------------------------------------
# SustainabilityService
# ---------------------------------------------------------------------------

class SustainabilityService:
	"""Stateless ESG / sustainability service."""

	VALID_SCOPES = frozenset({1, 2, 3})
	VALID_METHODS = frozenset({"CALCULATED", "MEASURED", "ESTIMATED"})
	VALID_QUALITY = frozenset({"HIGH", "MEDIUM", "LOW"})
	VALID_PILLARS = frozenset({"ENVIRONMENTAL", "SOCIAL", "GOVERNANCE"})
	VALID_FRAMEWORKS = frozenset({"GRI", "SASB", "TCFD", "CDP"})

	# ------------------------------------------------------------------
	# EmissionSource
	# ------------------------------------------------------------------

	def create_emission_source(
		self,
		session: Any,
		tenant_id: str,
		source_name: str,
		scope: int,
		emission_category: str,
		activity_type: str,
		unit_of_measure: str,
		emission_factor: Decimal,
		emission_factor_source: str,
		effective_from: date,
	) -> dict:
		"""Create an emission factor master record."""
		from pgappforge.plugins.erp.grc.sustainability.models import EmissionSource

		if scope not in self.VALID_SCOPES:
			raise SustainabilityServiceError(
				f"scope must be 1, 2, or 3 (GHG Protocol), got {scope!r}"
			)

		src = EmissionSource(
			tenant_id=tenant_id,
			source_name=source_name,
			scope=scope,
			emission_category=emission_category,
			activity_type=activity_type,
			unit_of_measure=unit_of_measure,
			emission_factor=emission_factor,
			emission_factor_source=emission_factor_source,
			effective_from=effective_from,
		)
		session.add(src)
		session.flush()
		log.info(
			"SustainabilityService: created emission source %r scope=%d",
			source_name, scope,
		)
		return {"source_id": src.id, "status": "created"}

	def get_effective_factor(
		self,
		session: Any,
		tenant_id: str,
		activity_type: str,
		as_of_date: date,
	) -> dict | None:
		"""Return the most recent emission factor for an activity type as of date."""
		from pgappforge.plugins.erp.grc.sustainability.models import EmissionSource

		row = session.execute(
			select(EmissionSource)
			.where(
				EmissionSource.tenant_id == tenant_id,
				EmissionSource.activity_type == activity_type,
				EmissionSource.effective_from <= as_of_date,
			)
			.order_by(EmissionSource.effective_from.desc())
			.limit(1)
		).scalar_one_or_none()

		if row is None:
			return None
		return {
			"source_id": row.id,
			"source_name": row.source_name,
			"scope": row.scope,
			"emission_factor": str(row.emission_factor),
			"unit_of_measure": row.unit_of_measure,
			"emission_factor_source": row.emission_factor_source,
			"effective_from": row.effective_from.isoformat(),
		}

	# ------------------------------------------------------------------
	# EmissionRecord
	# ------------------------------------------------------------------

	def record_emission(
		self,
		session: Any,
		tenant_id: str,
		source_id: str,
		period_date: date,
		activity_quantity: Decimal,
		method: str = "CALCULATED",
		data_quality: str = "MEDIUM",
		notes: str | None = None,
	) -> dict:
		"""Record an emission activity.

		For CALCULATED method, co2e_tonnes = activity_quantity * emission_factor / 1000.
		Emits EmissionRecordedEvent.
		"""
		from pgappforge.plugins.erp.grc.sustainability.models import (
			EmissionSource,
			EmissionRecord,
		)
		from pgappforge.plugins.erp.grc.sustainability.events import EmissionRecordedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		if method not in self.VALID_METHODS:
			raise SustainabilityServiceError(
				f"method must be one of {self.VALID_METHODS}"
			)
		if data_quality not in self.VALID_QUALITY:
			raise SustainabilityServiceError(
				f"data_quality must be one of {self.VALID_QUALITY}"
			)

		source = session.get(EmissionSource, source_id)
		if source is None:
			raise EmissionSourceNotFoundError(
				f"EmissionSource {source_id!r} not found"
			)

		if method == "CALCULATED":
			# kg CO2e / 1000 = tCO2e
			co2e_kg = Decimal(str(activity_quantity)) * Decimal(str(source.emission_factor))
			co2e_tonnes = (co2e_kg / Decimal("1000")).quantize(
				Decimal("0.0001"), rounding=ROUND_HALF_UP
			)
		else:
			# For MEASURED/ESTIMATED, caller provides in the activity_quantity field
			# as tonnes directly — document this convention in the API
			co2e_tonnes = Decimal(str(activity_quantity)).quantize(
				Decimal("0.0001"), rounding=ROUND_HALF_UP
			)

		record = EmissionRecord(
			tenant_id=tenant_id,
			source_id=source_id,
			period_date=period_date,
			activity_quantity=activity_quantity,
			uom=source.unit_of_measure,
			co2e_tonnes=co2e_tonnes,
			method=method,
			verified=False,
			data_quality=data_quality,
			notes=notes,
		)
		session.add(record)
		session.flush()

		emit_event(
			EmissionRecordedEvent(
				aggregate_id=record.id,
				aggregate_type="EmissionRecord",
				tenant_id=tenant_id,
				record_id=record.id,
				source_id=source_id,
				scope=source.scope,
				period_date=period_date.isoformat(),
				co2e_tonnes=str(co2e_tonnes),
				method=method,
			),
			session,
		)
		log.info(
			"SustainabilityService: emission recorded source=%r period=%s co2e=%s tCO2e",
			source_id, period_date, co2e_tonnes,
		)
		return {
			"record_id": record.id,
			"co2e_tonnes": str(co2e_tonnes),
			"status": "recorded",
		}

	def verify_emission_record(
		self,
		session: Any,
		record_id: str,
		verified_by: str,
	) -> dict:
		"""Mark an emission record as externally verified."""
		from pgappforge.plugins.erp.grc.sustainability.models import EmissionRecord
		from pgappforge.plugins.erp.grc.sustainability.events import EmissionVerifiedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		record = session.get(EmissionRecord, record_id)
		if record is None:
			raise EmissionSourceNotFoundError(
				f"EmissionRecord {record_id!r} not found"
			)
		if record.verified:
			raise VerifiedRecordError(
				f"EmissionRecord {record_id!r} is already verified; "
				"insert a correction record instead"
			)

		record.verified = True
		record.verified_by = verified_by

		emit_event(
			EmissionVerifiedEvent(
				aggregate_id=record_id,
				aggregate_type="EmissionRecord",
				tenant_id=str(record.tenant_id),
				record_id=record_id,
				source_id=str(record.source_id),
				verified_by=verified_by,
				co2e_tonnes=str(record.co2e_tonnes),
			),
			session,
		)
		return {"record_id": record_id, "verified": True}

	# ------------------------------------------------------------------
	# ESGMetric
	# ------------------------------------------------------------------

	def create_metric(
		self,
		session: Any,
		tenant_id: str,
		metric_code: str,
		metric_name: str,
		pillar: str,
		unit: str,
		reporting_framework: str,
		target_value: Decimal | None = None,
		target_year: int | None = None,
		description: str | None = None,
	) -> dict:
		"""Create an ESG metric definition."""
		from pgappforge.plugins.erp.grc.sustainability.models import ESGMetric
		from pgappforge.plugins.erp.grc.sustainability.events import ESGMetricTargetSetEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		if pillar not in self.VALID_PILLARS:
			raise SustainabilityServiceError(
				f"pillar must be one of {self.VALID_PILLARS}"
			)
		if reporting_framework not in self.VALID_FRAMEWORKS:
			raise SustainabilityServiceError(
				f"reporting_framework must be one of {self.VALID_FRAMEWORKS}"
			)

		metric = ESGMetric(
			tenant_id=tenant_id,
			metric_code=metric_code,
			metric_name=metric_name,
			pillar=pillar,
			unit=unit,
			reporting_framework=reporting_framework,
			target_value=target_value,
			target_year=target_year,
			description=description,
		)
		session.add(metric)
		session.flush()

		if target_value is not None and target_year is not None:
			emit_event(
				ESGMetricTargetSetEvent(
					aggregate_id=metric.id,
					aggregate_type="ESGMetric",
					tenant_id=tenant_id,
					metric_id=metric.id,
					metric_code=metric_code,
					pillar=pillar,
					target_value=str(target_value),
					target_year=target_year,
				),
				session,
			)

		return {"metric_id": metric.id, "status": "created"}

	# ------------------------------------------------------------------
	# ESGSnapshot
	# ------------------------------------------------------------------

	def capture_snapshot(
		self,
		session: Any,
		tenant_id: str,
		metric_id: str,
		snapshot_year: int,
		actual_value: Decimal,
		target_value: Decimal | None = None,
		notes: str | None = None,
		verified_by: str | None = None,
	) -> dict:
		"""Capture an annual ESG snapshot with YoY improvement calculation.

		Raises ESGSnapshotExistsError if a snapshot for this metric+year exists.
		"""
		from pgappforge.plugins.erp.grc.sustainability.models import ESGMetric, ESGSnapshot
		from pgappforge.plugins.erp.grc.sustainability.events import (
			ESGSnapshotCapturedEvent,
			ESGTargetMissedEvent,
		)
		from pgappforge.plugins.erp.foundation.events import emit_event

		metric = session.get(ESGMetric, metric_id)
		if metric is None:
			raise ESGMetricNotFoundError(f"ESGMetric {metric_id!r} not found")

		# Check for duplicate
		existing = session.execute(
			select(ESGSnapshot).where(
				ESGSnapshot.tenant_id == tenant_id,
				ESGSnapshot.metric_id == metric_id,
				ESGSnapshot.snapshot_year == snapshot_year,
			)
		).scalar_one_or_none()
		if existing is not None:
			raise ESGSnapshotExistsError(
				f"ESGSnapshot for metric {metric_id!r} year {snapshot_year} already exists"
			)

		# YoY improvement: compare to prior year snapshot
		prior = session.execute(
			select(ESGSnapshot).where(
				ESGSnapshot.tenant_id == tenant_id,
				ESGSnapshot.metric_id == metric_id,
				ESGSnapshot.snapshot_year == snapshot_year - 1,
			)
		).scalar_one_or_none()

		improvement_pct: Decimal | None = None
		if prior is not None and prior.actual_value and prior.actual_value != 0:
			raw = ((actual_value - prior.actual_value) / prior.actual_value * 100)
			improvement_pct = Decimal(str(raw)).quantize(
				Decimal("0.01"), rounding=ROUND_HALF_UP
			)

		effective_target = target_value or metric.target_value
		verified_at = datetime.now(timezone.utc) if verified_by else None

		snapshot = ESGSnapshot(
			tenant_id=tenant_id,
			metric_id=metric_id,
			snapshot_year=snapshot_year,
			actual_value=actual_value,
			target_value=effective_target,
			improvement_pct=improvement_pct,
			notes=notes,
			verified_by=verified_by,
			verified_at=verified_at,
		)
		session.add(snapshot)
		session.flush()

		emit_event(
			ESGSnapshotCapturedEvent(
				aggregate_id=snapshot.id,
				aggregate_type="ESGSnapshot",
				tenant_id=tenant_id,
				snapshot_id=snapshot.id,
				metric_id=metric_id,
				metric_code=metric.metric_code,
				snapshot_year=snapshot_year,
				actual_value=str(actual_value),
				target_value=str(effective_target) if effective_target else "",
				improvement_pct=str(improvement_pct) if improvement_pct is not None else "",
			),
			session,
		)

		# Emit target missed event if applicable
		if effective_target is not None:
			# For reduction targets (lower = better), actual > target = missed
			# Simple heuristic: if actual > target and pillar is ENVIRONMENTAL
			if metric.pillar == "ENVIRONMENTAL" and actual_value > effective_target:
				gap = actual_value - effective_target
				emit_event(
					ESGTargetMissedEvent(
						aggregate_id=snapshot.id,
						aggregate_type="ESGSnapshot",
						tenant_id=tenant_id,
						snapshot_id=snapshot.id,
						metric_id=metric_id,
						metric_code=metric.metric_code,
						snapshot_year=snapshot_year,
						actual_value=str(actual_value),
						target_value=str(effective_target),
						gap=str(gap),
					),
					session,
				)

		log.info(
			"SustainabilityService: snapshot captured metric=%r year=%d actual=%s",
			metric.metric_code, snapshot_year, actual_value,
		)
		return {
			"snapshot_id": snapshot.id,
			"snapshot_year": snapshot_year,
			"actual_value": str(actual_value),
			"improvement_pct": str(improvement_pct) if improvement_pct is not None else None,
		}

	# ------------------------------------------------------------------
	# GHG Scope Rollup
	# ------------------------------------------------------------------

	def get_scope_rollup(
		self,
		session: Any,
		tenant_id: str,
		period_from: date,
		period_to: date,
		verified_only: bool = False,
	) -> dict:
		"""Sum co2e_tonnes grouped by scope for a date range.

		Returns: {"scope_1": Decimal, "scope_2": Decimal, "scope_3": Decimal, "total": Decimal}
		"""
		from pgappforge.plugins.erp.grc.sustainability.models import (
			EmissionRecord,
			EmissionSource,
		)

		q = (
			select(
				EmissionSource.scope,
				func.sum(EmissionRecord.co2e_tonnes).label("total_co2e"),
			)
			.join(EmissionSource, EmissionSource.id == EmissionRecord.source_id)
			.where(
				EmissionRecord.tenant_id == tenant_id,
				EmissionRecord.period_date >= period_from,
				EmissionRecord.period_date <= period_to,
			)
			.group_by(EmissionSource.scope)
		)
		if verified_only:
			q = q.where(EmissionRecord.verified.is_(True))

		rows = session.execute(q).all()
		result = {"scope_1": Decimal("0"), "scope_2": Decimal("0"), "scope_3": Decimal("0")}
		for row in rows:
			key = f"scope_{row.scope}"
			if key in result:
				result[key] = Decimal(str(row.total_co2e or 0))

		result["total"] = result["scope_1"] + result["scope_2"] + result["scope_3"]
		# Convert to strings for JSON safety
		return {k: str(v) for k, v in result.items()}


__all__ = [
	"SustainabilityService",
	"SustainabilityServiceError",
	"EmissionSourceNotFoundError",
	"ESGMetricNotFoundError",
	"ESGSnapshotExistsError",
	"VerifiedRecordError",
]
