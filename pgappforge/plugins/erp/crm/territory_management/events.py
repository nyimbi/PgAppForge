"""
pgappforge/plugins/erp/crm/territory_management/events.py

Domain events for the Territory Management plugin.
"""
from __future__ import annotations

from dataclasses import dataclass

from pgappforge.plugins.erp.foundation.events import DomainEvent

__all__ = [
	"TerritoryDefinedEvent",
	"TerritoryAssignedEvent",
]


@dataclass
class TerritoryDefinedEvent(DomainEvent):
	"""Emitted when a new sales territory is defined."""
	event_type: str = "crm.territory.defined"
	territory_id: str = ""
	name: str = ""
	region: str = ""
	tenant_id: str = ""


@dataclass
class TerritoryAssignedEvent(DomainEvent):
	"""Emitted when a territory is assigned to a salesperson."""
	event_type: str = "crm.territory.assigned"
	territory_id: str = ""
	salesperson_id: str = ""
	effective_from: str = ""
