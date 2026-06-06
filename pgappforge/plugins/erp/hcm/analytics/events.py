"""
pgappforge/plugins/erp/hcm/analytics/events.py

Domain events for the HR Analytics plugin.

Events emitted:
  hcm.analytics.report.generated    — analytics snapshot/report generated
  hcm.analytics.turnover.alert      — turnover rate exceeded threshold
  hcm.analytics.flight_risk.alert   — employee flight risk HIGH/CRITICAL
  hcm.analytics.diversity.report    — diversity report generated
  hcm.analytics.headcount.changed   — headcount change detected
"""
from __future__ import annotations

from dataclasses import dataclass, field

from pgappforge.plugins.erp.foundation.events import DomainEvent


# ---------------------------------------------------------------------------
# Analytics report generated
# ---------------------------------------------------------------------------

@dataclass
class AnalyticsReportGeneratedEvent(DomainEvent):
	"""Emitted when generate_snapshot() or any report method completes."""
	event_type: str = "hcm.analytics.report.generated"
	report_id: str = ""
	report_type: str = ""   # HEADCOUNT | TURNOVER | DIVERSITY | COST_PER_HIRE | TIME_TO_FILL | ENGAGEMENT
	period: str = ""        # e.g. "2025-Q1", "2025-01"
	entity_id: str = ""     # department/cost-centre ID — empty = whole tenant


# ---------------------------------------------------------------------------
# Turnover alert
# ---------------------------------------------------------------------------

@dataclass
class TurnoverAlertEvent(DomainEvent):
	"""Emitted when turnover rate crosses the configured alert threshold."""
	event_type: str = "hcm.analytics.turnover.alert"
	entity_id: str = ""     # department/cost-centre ID — empty = whole tenant
	rate_pct: str = ""      # Decimal string e.g. "18.5" (never float)
	period: str = ""        # period string e.g. "2025-Q1"


# ---------------------------------------------------------------------------
# Flight risk alert
# ---------------------------------------------------------------------------

@dataclass
class FlightRiskAlertEvent(DomainEvent):
	"""Emitted when compute_flight_risk() scores an employee as HIGH or CRITICAL."""
	event_type: str = "hcm.analytics.flight_risk.alert"
	employee_id: str = ""
	risk_score: int = 0     # 0–100
	risk_level: str = ""    # HIGH | CRITICAL
	factors: list = field(default_factory=list)   # [{factor, weight, value}, ...]


# ---------------------------------------------------------------------------
# Diversity report generated
# ---------------------------------------------------------------------------

@dataclass
class DiversityReportGeneratedEvent(DomainEvent):
	"""Emitted when a diversity snapshot is stored."""
	event_type: str = "hcm.analytics.diversity.report"
	period: str = ""
	entity_id: str = ""     # department/cost-centre ID — empty = whole tenant


# ---------------------------------------------------------------------------
# Headcount changed
# ---------------------------------------------------------------------------

@dataclass
class HeadcountChangedEvent(DomainEvent):
	"""Emitted when a headcount snapshot detects a change from the previous snapshot."""
	event_type: str = "hcm.analytics.headcount.changed"
	entity_id: str = ""     # department/cost-centre ID — empty = whole tenant
	prev_count: int = 0
	new_count: int = 0
	change_reason: str = "" # HIRE | TERMINATION | TRANSFER | REORG | SNAPSHOT


__all__ = [
	"AnalyticsReportGeneratedEvent",
	"TurnoverAlertEvent",
	"FlightRiskAlertEvent",
	"DiversityReportGeneratedEvent",
	"HeadcountChangedEvent",
]
