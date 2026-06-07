"""
pgappforge/plugins/erp/platform/ipaas/events.py

Domain events for the iPaaS (Integration Platform as a Service) plugin.
"""
from __future__ import annotations

from dataclasses import dataclass

from pgappforge.plugins.erp.foundation.events import DomainEvent

__all__ = [
	"FlowExecutedEvent",
	"ConnectorRegisteredEvent",
	"IntegrationErrorEvent",
]


@dataclass
class FlowExecutedEvent(DomainEvent):
	"""Emitted when an integration flow completes execution."""
	event_type: str = "platform.ipaas.flow.executed"
	flow_id: str = ""
	run_id: str = ""
	records_processed: int = 0
	errors_count: int = 0
	status: str = ""


@dataclass
class ConnectorRegisteredEvent(DomainEvent):
	"""Emitted when a new connector definition is registered."""
	event_type: str = "platform.ipaas.connector.registered"
	connector_id: str = ""
	connector_name: str = ""
	protocol: str = ""


@dataclass
class IntegrationErrorEvent(DomainEvent):
	"""Emitted when an integration flow run fails or produces errors."""
	event_type: str = "platform.ipaas.integration.error"
	flow_id: str = ""
	run_id: str = ""
	error_message: str = ""
	errors_count: int = 0
