"""
pgappforge/plugins/erp/platform/analytics_engine/events.py

Domain events for the Analytics Engine plugin.
"""
from __future__ import annotations

from dataclasses import dataclass

from pgappforge.plugins.erp.foundation.events import DomainEvent

__all__ = [
	"CubeDefinedEvent",
	"CubeRefreshedEvent",
	"ReportRunEvent",
]


@dataclass
class CubeDefinedEvent(DomainEvent):
	"""Emitted when a new analytics cube is defined."""
	event_type: str = "platform.analytics.cube.defined"
	cube_id: str = ""
	cube_name: str = ""
	view_name: str = ""
	tenant_id: str = ""


@dataclass
class CubeRefreshedEvent(DomainEvent):
	"""Emitted when a materialized view backing an analytics cube is refreshed."""
	event_type: str = "platform.analytics.cube.refreshed"
	cube_id: str = ""
	cube_name: str = ""
	row_count: int = 0


@dataclass
class ReportRunEvent(DomainEvent):
	"""Emitted when an analytics report is executed."""
	event_type: str = "platform.analytics.report.run"
	report_id: str = ""
	cube_id: str = ""
	rows_returned: int = 0
	duration_ms: int = 0
