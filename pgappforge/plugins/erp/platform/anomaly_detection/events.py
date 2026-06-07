from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pgappforge.plugins.erp.foundation.events import DomainEvent

__all__ = [
	"GLAnomalyDetectedEvent",
	"APDuplicateDetectedEvent",
	"WeekendJournalFlaggedEvent",
	"LargeTransactionFlaggedEvent",
	"AnomalyResolvedEvent",
	"AnomalyBatchRunCompletedEvent",
]


@dataclass
class GLAnomalyDetectedEvent(DomainEvent):
	event_type: str = field(default="platform.anomaly.gl.detected", init=False)
	anomaly_id: str = ""
	journal_id: str = ""
	anomaly_type: str = ""
	severity: str = ""
	tenant_id: str = ""


@dataclass
class APDuplicateDetectedEvent(DomainEvent):
	event_type: str = field(default="platform.anomaly.ap.duplicate", init=False)
	anomaly_id: str = ""
	invoice_id: str = ""
	duplicate_invoice_id: str = ""
	vendor_id: str = ""


@dataclass
class WeekendJournalFlaggedEvent(DomainEvent):
	event_type: str = field(default="platform.anomaly.weekend_journal", init=False)
	journal_id: str = ""
	posted_at: str = ""
	amount_cents: int = 0


@dataclass
class LargeTransactionFlaggedEvent(DomainEvent):
	event_type: str = field(default="platform.anomaly.large_transaction", init=False)
	journal_id: str = ""
	amount_cents: int = 0
	z_score: str = ""


@dataclass
class AnomalyResolvedEvent(DomainEvent):
	event_type: str = field(default="platform.anomaly.resolved", init=False)
	anomaly_id: str = ""
	resolved_by: str = ""
	resolution: str = ""


@dataclass
class AnomalyBatchRunCompletedEvent(DomainEvent):
	event_type: str = field(default="platform.anomaly.batch.completed", init=False)
	run_id: str = ""
	tenant_id: str = ""
	anomalies_found: int = 0
