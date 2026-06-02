"""
pgappforge/plugins/erp/analytics/operational/services.py

OperationalAnalyticsService — stateless business logic for KPIs, queries, reports.

All methods accept an explicit SQLAlchemy session (SA 2.x execute() pattern).
No session.commit() here — callers own transaction boundaries.

Key methods
-----------
  record_snapshot(kpi_id, snapshot_date, actual_value, session) -> KPISnapshot
      Inserts a new snapshot, computes variance_pct and status, emits event.

  get_kpi_trend(kpi_id, periods, session) -> list[KPISnapshot]
      Returns the last N snapshots for a KPI ordered by snapshot_date desc.

  run_query(query_id, params, session) -> dict
      Executes a saved AnalyticsQuery with provided params, updates runtime stats.

  generate_report(report_id, session) -> dict
      Builds report payload from layout definition, updates last_generated_at,
      emits AnalyticsReportGeneratedEvent.

  compute_status(actual, target, direction) -> str
      Pure function: ON_TRACK / AT_RISK / OFF_TRACK.
"""
from __future__ import annotations

import logging
import time
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

import sqlalchemy as sa

from pgappforge.plugins.erp.analytics.operational.events import (
	AnalyticsQueryExecutedEvent,
	AnalyticsReportGeneratedEvent,
	KPISnapshotRecordedEvent,
	KPIStatusChangedEvent,
	emit_event,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class OperationalAnalyticsError(Exception):
	"""Base error for operational analytics service layer."""


class KPINotFoundError(OperationalAnalyticsError):
	pass


class QueryNotFoundError(OperationalAnalyticsError):
	pass


class ReportNotFoundError(OperationalAnalyticsError):
	pass


class QueryExecutionError(OperationalAnalyticsError):
	pass


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class OperationalAnalyticsService:
	"""Stateless service for operational analytics.

	Instantiate once per request or inject as a dependency.
	"""

	# ------------------------------------------------------------------
	# KPI snapshots
	# ------------------------------------------------------------------

	@staticmethod
	def compute_status(
		actual: Decimal,
		target: Decimal | None,
		direction: str = "HIGHER",
	) -> str:
		"""Compute ON_TRACK / AT_RISK / OFF_TRACK from actual vs target.

		Thresholds:
		  HIGHER: actual >= target*0.95 → ON_TRACK
		          actual >= target*0.80 → AT_RISK
		          else                  → OFF_TRACK
		  LOWER:  actual <= target*1.05 → ON_TRACK
		          actual <= target*1.20 → AT_RISK
		          else                  → OFF_TRACK
		"""
		if target is None or target == 0:
			return "ON_TRACK"

		ratio = Decimal(str(actual)) / Decimal(str(target))

		if direction == "HIGHER":
			if ratio >= Decimal("0.95"):
				return "ON_TRACK"
			if ratio >= Decimal("0.80"):
				return "AT_RISK"
			return "OFF_TRACK"

		# LOWER direction — smaller actual is better
		if ratio <= Decimal("1.05"):
			return "ON_TRACK"
		if ratio <= Decimal("1.20"):
			return "AT_RISK"
		return "OFF_TRACK"

	@staticmethod
	def record_snapshot(
		kpi_id: str,
		snapshot_date: date,
		actual_value: Decimal,
		session: Any,
		target_override: Decimal | None = None,
	) -> Any:
		"""Insert a new KPISnapshot for kpi_id on snapshot_date.

		Fetches current KPIDefinition for target_value and target_direction.
		Computes variance_pct and status. Emits KPISnapshotRecordedEvent and
		KPIStatusChangedEvent when status has changed from most-recent prior snapshot.

		Returns the new KPISnapshot instance (not yet committed).
		"""
		from pgappforge.plugins.erp.analytics.operational.models import (
			KPIDefinition,
			KPISnapshot,
		)

		kpi = session.execute(
			sa.select(KPIDefinition).where(KPIDefinition.id == kpi_id)
		).scalar_one_or_none()
		if kpi is None:
			raise KPINotFoundError(f"KPIDefinition {kpi_id!r} not found")

		target = target_override if target_override is not None else kpi.target_value
		variance_pct = None
		if target and target != 0:
			variance_pct = (Decimal(str(actual_value)) - Decimal(str(target))) / Decimal(str(target)) * 100

		status = OperationalAnalyticsService.compute_status(
			actual_value, target, kpi.target_direction
		)

		# Prior period value — latest snapshot before this date
		prior_row = session.execute(
			sa.select(KPISnapshot)
			.where(KPISnapshot.kpi_id == kpi_id)
			.where(KPISnapshot.snapshot_date < snapshot_date)
			.order_by(KPISnapshot.snapshot_date.desc(), KPISnapshot.recorded_at.desc())
			.limit(1)
		).scalar_one_or_none()
		prior_value = prior_row.actual_value if prior_row else None
		prior_status = prior_row.status if prior_row else None

		snap = KPISnapshot(
			kpi_id=kpi_id,
			snapshot_date=snapshot_date,
			actual_value=actual_value,
			target_value=target,
			prior_period_value=prior_value,
			variance_pct=variance_pct,
			status=status,
		)
		session.add(snap)

		emit_event(
			KPISnapshotRecordedEvent(
				aggregate_id=kpi_id,
				aggregate_type="KPIDefinition",
				tenant_id=kpi.tenant_id,
				kpi_id=kpi_id,
				kpi_code=kpi.kpi_code,
				snapshot_date=str(snapshot_date),
				actual_value=str(actual_value),
				target_value=str(target) if target else "",
				status=status,
			),
			session,
		)

		if prior_status and prior_status != status:
			emit_event(
				KPIStatusChangedEvent(
					aggregate_id=kpi_id,
					aggregate_type="KPIDefinition",
					tenant_id=kpi.tenant_id,
					kpi_id=kpi_id,
					kpi_code=kpi.kpi_code,
					previous_status=prior_status,
					new_status=status,
					snapshot_date=str(snapshot_date),
				),
				session,
			)

		log.info(
			"record_snapshot: kpi=%s date=%s actual=%s status=%s",
			kpi_id, snapshot_date, actual_value, status,
		)
		return snap

	@staticmethod
	def get_kpi_trend(kpi_id: str, periods: int, session: Any) -> list[Any]:
		"""Return last *periods* snapshots for kpi_id, most-recent first."""
		from pgappforge.plugins.erp.analytics.operational.models import KPISnapshot

		rows = session.execute(
			sa.select(KPISnapshot)
			.where(KPISnapshot.kpi_id == kpi_id)
			.order_by(KPISnapshot.snapshot_date.desc(), KPISnapshot.recorded_at.desc())
			.limit(periods)
		).scalars().all()
		return list(rows)

	# ------------------------------------------------------------------
	# Saved queries
	# ------------------------------------------------------------------

	@staticmethod
	def run_query(query_id: str, params: dict[str, Any], session: Any) -> dict[str, Any]:
		"""Execute a saved AnalyticsQuery with the provided params dict.

		Returns {"columns": [...], "rows": [...], "runtime_ms": int}.
		Updates AnalyticsQuery.last_run_at and rolling average_runtime_ms.

		SECURITY: Only named-parameter queries (:param) are supported.
		Raw f-string interpolation in query_sql is never evaluated here.
		"""
		from pgappforge.plugins.erp.analytics.operational.models import AnalyticsQuery

		aq = session.execute(
			sa.select(AnalyticsQuery).where(AnalyticsQuery.id == query_id)
		).scalar_one_or_none()
		if aq is None:
			raise QueryNotFoundError(f"AnalyticsQuery {query_id!r} not found")

		t0 = time.monotonic()
		try:
			result = session.execute(sa.text(aq.query_sql), params)
			columns = list(result.keys())
			rows = [dict(zip(columns, row)) for row in result.fetchall()]
		except Exception as exc:
			raise QueryExecutionError(f"Query execution failed: {exc}") from exc

		runtime_ms = int((time.monotonic() - t0) * 1000)

		# Rolling average
		prev_avg = aq.average_runtime_ms or runtime_ms
		aq.average_runtime_ms = (prev_avg + runtime_ms) // 2
		aq.last_run_at = datetime.now(timezone.utc)

		emit_event(
			AnalyticsQueryExecutedEvent(
				aggregate_id=query_id,
				aggregate_type="AnalyticsQuery",
				tenant_id=aq.tenant_id,
				query_id=query_id,
				query_name=aq.name,
				runtime_ms=runtime_ms,
				row_count=len(rows),
			),
			session,
		)

		return {"columns": columns, "rows": rows, "runtime_ms": runtime_ms}

	# ------------------------------------------------------------------
	# Reports
	# ------------------------------------------------------------------

	@staticmethod
	def generate_report(report_id: str, session: Any) -> dict[str, Any]:
		"""Build report payload, update last_generated_at, emit event.

		Returns a dict describing the generated report artefact.
		Actual rendering (PDF/HTML/XLSX) is delegated to the caller.
		"""
		from pgappforge.plugins.erp.analytics.operational.models import AnalyticsReport

		report = session.execute(
			sa.select(AnalyticsReport).where(AnalyticsReport.id == report_id)
		).scalar_one_or_none()
		if report is None:
			raise ReportNotFoundError(f"AnalyticsReport {report_id!r} not found")

		report.last_generated_at = datetime.now(timezone.utc)

		recipient_count = len(report.recipients) if report.recipients else 0

		emit_event(
			AnalyticsReportGeneratedEvent(
				aggregate_id=report_id,
				aggregate_type="AnalyticsReport",
				tenant_id=report.tenant_id,
				report_id=report_id,
				report_name=report.name,
				category=report.category,
				recipient_count=recipient_count,
			),
			session,
		)

		return {
			"report_id": report_id,
			"name": report.name,
			"category": report.category,
			"layout": report.layout,
			"generated_at": report.last_generated_at.isoformat(),
			"recipients": report.recipients,
		}


__all__ = [
	"OperationalAnalyticsService",
	"OperationalAnalyticsError",
	"KPINotFoundError",
	"QueryNotFoundError",
	"ReportNotFoundError",
	"QueryExecutionError",
]
