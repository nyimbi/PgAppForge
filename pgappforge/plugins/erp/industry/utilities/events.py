"""
pgappforge/plugins/erp/industry/utilities/events.py

Utilities / Smart Grid plugin domain events.

Events emitted:
  utilities.ami.data_ingested
  utilities.outage.detected
  utilities.outage.restored
  utilities.demand_response.dispatched
  utilities.demand_response.completed
  utilities.reliability.indices_calculated
"""
from __future__ import annotations

from dataclasses import dataclass, field

from pgappforge.plugins.erp.foundation.events import DomainEvent


@dataclass
class AMIDataIngestedEvent(DomainEvent):
	event_type: str = "utilities.ami.data_ingested"
	meter_id: str = ""
	record_count: int = 0
	period_start: str = ""
	period_end: str = ""


@dataclass
class OutageDetectedEvent(DomainEvent):
	event_type: str = "utilities.outage.detected"
	outage_id: str = ""
	outage_type: str = ""
	cause: str = ""
	affected_customers: int = 0
	affected_asset_count: int = 0


@dataclass
class OutageRestoredEvent(DomainEvent):
	event_type: str = "utilities.outage.restored"
	outage_id: str = ""
	restored_at: str = ""
	saidi_minutes: float = 0.0
	saifi_occurrences: float = 0.0


@dataclass
class DemandResponseDispatchedEvent(DomainEvent):
	event_type: str = "utilities.demand_response.dispatched"
	dr_event_id: str = ""
	program_name: str = ""
	target_reduction_kw: float = 0.0
	enrolled_customers: int = 0


@dataclass
class DemandResponseCompletedEvent(DomainEvent):
	event_type: str = "utilities.demand_response.completed"
	dr_event_id: str = ""
	program_name: str = ""
	achieved_reduction_kw: float = 0.0
	target_reduction_kw: float = 0.0


@dataclass
class ReliabilityIndicesCalculatedEvent(DomainEvent):
	event_type: str = "utilities.reliability.indices_calculated"
	saidi: float = 0.0
	saifi: float = 0.0
	caidi: float = 0.0
	period_start: str = ""
	period_end: str = ""


__all__ = [
	"AMIDataIngestedEvent",
	"OutageDetectedEvent",
	"OutageRestoredEvent",
	"DemandResponseDispatchedEvent",
	"DemandResponseCompletedEvent",
	"ReliabilityIndicesCalculatedEvent",
]
