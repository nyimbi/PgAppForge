"""
pgappforge/plugins/erp/platform/process_mining/events.py

Domain events for the Process Mining plugin.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from pgappforge.plugins.erp.foundation.events import DomainEvent

__all__ = [
	"ProcessDiscoveredEvent",
	"BottleneckFoundEvent",
]


@dataclass
class ProcessDiscoveredEvent(DomainEvent):
	"""Emitted when a process graph is discovered from event log data."""
	event_type: str = "platform.process_mining.process.discovered"
	definition_id: str = ""
	tenant_id: str = ""
	case_count: int = 0
	edge_count: int = 0


@dataclass
class BottleneckFoundEvent(DomainEvent):
	"""Emitted for each bottleneck transition found during analysis."""
	event_type: str = "platform.process_mining.bottleneck.found"
	tenant_id: str = ""
	from_event: str = ""
	to_event: str = ""
	avg_wait_seconds: float = 0.0
	impact_pct: float = 0.0
