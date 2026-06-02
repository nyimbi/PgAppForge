"""
pgappforge/plugins/erp/analytics/operational/events.py

Domain events for the Operational Analytics plugin.

Events emitted
--------------
  analytics.kpi.snapshot_recorded   — new KPI snapshot inserted
  analytics.kpi.status_changed      — KPI status transitioned (ON_TRACK→AT_RISK etc.)
  analytics.report.generated        — a report was generated and delivered
  analytics.query.executed          — a saved query was run
"""
from __future__ import annotations

from dataclasses import dataclass, field

from pgappforge.plugins.erp.foundation.events import DomainEvent, emit_event  # noqa: F401


@dataclass
class KPISnapshotRecordedEvent(DomainEvent):
	event_type: str = "analytics.kpi.snapshot_recorded"
	kpi_id: str = ""
	kpi_code: str = ""
	snapshot_date: str = ""
	actual_value: str = ""   # Decimal as string — never float
	target_value: str = ""
	status: str = ""


@dataclass
class KPIStatusChangedEvent(DomainEvent):
	event_type: str = "analytics.kpi.status_changed"
	kpi_id: str = ""
	kpi_code: str = ""
	previous_status: str = ""
	new_status: str = ""
	snapshot_date: str = ""


@dataclass
class AnalyticsReportGeneratedEvent(DomainEvent):
	event_type: str = "analytics.report.generated"
	report_id: str = ""
	report_name: str = ""
	category: str = ""
	recipient_count: int = 0


@dataclass
class AnalyticsQueryExecutedEvent(DomainEvent):
	event_type: str = "analytics.query.executed"
	query_id: str = ""
	query_name: str = ""
	runtime_ms: int = 0
	row_count: int = 0


__all__ = [
	"KPISnapshotRecordedEvent",
	"KPIStatusChangedEvent",
	"AnalyticsReportGeneratedEvent",
	"AnalyticsQueryExecutedEvent",
	"emit_event",
]
