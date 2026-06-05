"""
pgappforge/plugins/erp/industry/track_trace/events.py

Domain events for the Track & Trace plugin (GS1 EPCIS 2.0).

Events emitted:
  track_trace.epcis.event_recorded       — EPCIS event appended to ledger
  track_trace.cold_chain.excursion        — temperature excursion detected
  track_trace.recall.initiated            — product recall initiated
  track_trace.recall.item_identified      — affected item found during recall
  track_trace.recall.completed            — recall closed out
"""
from __future__ import annotations

from dataclasses import dataclass, field

from pgappforge.plugins.erp.foundation.events import DomainEvent


@dataclass
class EPCISEventRecordedEvent(DomainEvent):
	"""Emitted when an EPCIS supply chain event is recorded."""
	event_type: str = "track_trace.epcis.event_recorded"
	epcis_event_id: str = ""          # the EPCIS eventID (not the PK)
	epcis_event_type: str = ""        # OBJECT|AGGREGATION|TRANSACTION|TRANSFORMATION
	action: str = ""
	biz_step: str = ""
	epc_count: int = 0
	event_time: str = ""              # ISO datetime


@dataclass
class ColdChainExcursionEvent(DomainEvent):
	"""Emitted when a temperature or humidity excursion is detected."""
	event_type: str = "track_trace.cold_chain.excursion"
	item_epc: str = ""
	device_id: str = ""
	temperature_c: str = ""           # str to avoid float serialization issues
	measured_at: str = ""             # ISO datetime
	excursion_duration_minutes: int = 0


@dataclass
class RecallInitiatedEvent(DomainEvent):
	"""Emitted when a product recall is initiated."""
	event_type: str = "track_trace.recall.initiated"
	recall_id: str = ""
	affected_gtin: str = ""
	affected_lots: list = field(default_factory=list)
	scope: str = ""
	initiated_by: str = ""
	initiated_at: str = ""            # ISO datetime


@dataclass
class RecallItemIdentifiedEvent(DomainEvent):
	"""Emitted when an item is identified as affected by a recall."""
	event_type: str = "track_trace.recall.item_identified"
	recall_id: str = ""
	item_epc: str = ""
	current_owner_id: str = ""
	current_location: dict = field(default_factory=dict)


@dataclass
class RecallCompletedEvent(DomainEvent):
	"""Emitted when a recall event is closed (COMPLETED or CANCELLED)."""
	event_type: str = "track_trace.recall.completed"
	recall_id: str = ""
	affected_gtin: str = ""
	final_status: str = ""
	items_identified: int = 0
	items_recovered: int = 0
	recovery_rate_pct: float = 0.0


__all__ = [
	"EPCISEventRecordedEvent",
	"ColdChainExcursionEvent",
	"RecallInitiatedEvent",
	"RecallItemIdentifiedEvent",
	"RecallCompletedEvent",
]
