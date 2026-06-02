"""
pgappforge/plugins/erp/grc/sustainability/events.py

GRC Sustainability plugin domain events.

Events emitted:
  sustainability.emission.recorded
  sustainability.emission.verified
  sustainability.esg_metric.target_set
  sustainability.esg_snapshot.captured
  sustainability.esg_snapshot.target_missed

Events consumed:
  operations.production.completed  — auto-record scope 1 emissions from production
  finance.ap.invoice_approved      — capture scope 3 spend-based emissions
"""
from __future__ import annotations

from dataclasses import dataclass

from pgappforge.plugins.erp.foundation.events import DomainEvent


@dataclass
class EmissionRecordedEvent(DomainEvent):
	event_type: str = "sustainability.emission.recorded"
	record_id: str = ""
	source_id: str = ""
	scope: int = 0
	period_date: str = ""
	co2e_tonnes: str = ""  # string to avoid float; convert from Decimal
	method: str = ""


@dataclass
class EmissionVerifiedEvent(DomainEvent):
	event_type: str = "sustainability.emission.verified"
	record_id: str = ""
	source_id: str = ""
	verified_by: str = ""
	co2e_tonnes: str = ""


@dataclass
class ESGMetricTargetSetEvent(DomainEvent):
	event_type: str = "sustainability.esg_metric.target_set"
	metric_id: str = ""
	metric_code: str = ""
	pillar: str = ""
	target_value: str = ""
	target_year: int = 0


@dataclass
class ESGSnapshotCapturedEvent(DomainEvent):
	event_type: str = "sustainability.esg_snapshot.captured"
	snapshot_id: str = ""
	metric_id: str = ""
	metric_code: str = ""
	snapshot_year: int = 0
	actual_value: str = ""
	target_value: str = ""
	improvement_pct: str = ""


@dataclass
class ESGTargetMissedEvent(DomainEvent):
	event_type: str = "sustainability.esg_snapshot.target_missed"
	snapshot_id: str = ""
	metric_id: str = ""
	metric_code: str = ""
	snapshot_year: int = 0
	actual_value: str = ""
	target_value: str = ""
	gap: str = ""


__all__ = [
	"EmissionRecordedEvent",
	"EmissionVerifiedEvent",
	"ESGMetricTargetSetEvent",
	"ESGSnapshotCapturedEvent",
	"ESGTargetMissedEvent",
]
