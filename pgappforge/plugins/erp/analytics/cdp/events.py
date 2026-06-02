"""
pgappforge/plugins/erp/analytics/cdp/events.py

Domain events for the Customer Data Platform (CDP) plugin.

Events emitted
--------------
  analytics.cdp.profile_computed      — UnifiedProfile recomputed for a party
  analytics.cdp.segment_computed      — Segment membership recomputed
  analytics.cdp.identity_resolved     — source ID resolved to canonical party
  analytics.cdp.segment_activated     — segment activated for a delivery channel
  analytics.cdp.event_stream_ingested — batch of EventStream rows ingested
"""
from __future__ import annotations

from dataclasses import dataclass, field

from pgappforge.plugins.erp.foundation.events import DomainEvent, emit_event  # noqa: F401


@dataclass
class ProfileComputedEvent(DomainEvent):
	event_type: str = "analytics.cdp.profile_computed"
	profile_id: str = ""
	party_id: str = ""
	lifetime_value_cents: int = 0
	churn_probability: str = ""   # Decimal as string
	segment_count: int = 0


@dataclass
class SegmentComputedEvent(DomainEvent):
	event_type: str = "analytics.cdp.segment_computed"
	segment_id: str = ""
	segment_name: str = ""
	member_count: int = 0
	segment_type: str = ""


@dataclass
class IdentityResolvedEvent(DomainEvent):
	event_type: str = "analytics.cdp.identity_resolved"
	edge_id: str = ""
	source_type: str = ""
	source_id: str = ""
	target_party_id: str = ""
	match_method: str = ""
	confidence_score: str = ""   # Decimal as string


@dataclass
class SegmentActivatedEvent(DomainEvent):
	event_type: str = "analytics.cdp.segment_activated"
	segment_id: str = ""
	segment_name: str = ""
	channel: str = ""
	member_count: int = 0


@dataclass
class EventStreamIngestedEvent(DomainEvent):
	event_type: str = "analytics.cdp.event_stream_ingested"
	event_count: int = 0
	source: str = ""


__all__ = [
	"ProfileComputedEvent",
	"SegmentComputedEvent",
	"IdentityResolvedEvent",
	"SegmentActivatedEvent",
	"EventStreamIngestedEvent",
	"emit_event",
]
