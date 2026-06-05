"""
pgappforge/plugins/erp/finance/fpa/events.py

Domain events for the FP&A plugin.

All amounts are integer cents (BigInteger — no float, ever).
Emitted inside the same SQLAlchemy session as the mutating operation so
persistence is atomic with the business transaction.
"""
from __future__ import annotations

from dataclasses import dataclass

from pgappforge.plugins.erp.foundation.events import DomainEvent, emit_event  # noqa: F401


# ---------------------------------------------------------------------------
# FP&A events
# ---------------------------------------------------------------------------

@dataclass
class BudgetCycleOpenedEvent(DomainEvent):
	"""Emitted when a BudgetCycle transitions to INPUT_OPEN."""
	event_type: str = "fpa.budget_cycle.opened"
	cycle_id: str = ""
	cycle_name: str = ""
	fiscal_year: int = 0
	cycle_type: str = ""          # ANNUAL|QUARTERLY|ROLLING_12M
	input_deadline: str = ""      # ISO date string, may be empty


@dataclass
class BudgetApprovedEvent(DomainEvent):
	"""Emitted when a BudgetVersion is approved and lines are locked."""
	event_type: str = "fpa.budget.approved"
	cycle_id: str = ""
	version_id: str = ""
	version_name: str = ""
	approved_by: str = ""         # user UUID string
	total_budget_cents: int = 0   # sum of all approved BudgetLine amounts


@dataclass
class ForecastSnapshotTakenEvent(DomainEvent):
	"""Emitted after FPAService.take_forecast_snapshot() completes."""
	event_type: str = "fpa.forecast_snapshot.taken"
	cycle_id: str = ""
	snapshot_date: str = ""       # ISO date string
	accounts_processed: int = 0
	total_actual_cents: int = 0
	total_budget_cents: int = 0
	total_variance_cents: int = 0
	variance_pct: float = 0.0     # overall variance % (float for event payload)


@dataclass
class ScenarioGeneratedEvent(DomainEvent):
	"""Emitted when generate_scenario() creates a new BudgetVersion."""
	event_type: str = "fpa.scenario.generated"
	scenario_id: str = ""
	scenario_name: str = ""
	scenario_type: str = ""       # OPTIMISTIC|BASE|PESSIMISTIC|STRESS|CUSTOM
	base_version_id: str = ""
	generated_version_id: str = ""
	lines_generated: int = 0


@dataclass
class KPIStatusChangedEvent(DomainEvent):
	"""Emitted when a KPITarget's status changes (e.g. ON_TRACK → AT_RISK)."""
	event_type: str = "fpa.kpi.status_changed"
	kpi_target_id: str = ""
	kpi_code: str = ""
	cycle_id: str = ""
	period_month: str = ""        # ISO date string (first of month)
	old_status: str = ""          # ON_TRACK|AT_RISK|OFF_TRACK
	new_status: str = ""
	target_value: float = 0.0
	actual_value: float = 0.0
	variance_pct: float = 0.0


@dataclass
class VarianceAlertEvent(DomainEvent):
	"""Emitted when a variance exceeds a configurable threshold.

	Raised by take_forecast_snapshot() and get_variance_analysis() when
	abs(variance_pct) > alert_threshold_pct (default 15%).
	"""
	event_type: str = "fpa.variance.alert"
	cycle_id: str = ""
	period_month: str = ""        # ISO date string
	gl_account_code: str = ""
	cost_center_code: str = ""    # may be empty
	actual_cents: int = 0
	budget_cents: int = 0
	variance_cents: int = 0
	variance_pct: float = 0.0
	alert_threshold_pct: float = 15.0


__all__ = [
	"BudgetCycleOpenedEvent",
	"BudgetApprovedEvent",
	"ForecastSnapshotTakenEvent",
	"ScenarioGeneratedEvent",
	"KPIStatusChangedEvent",
	"VarianceAlertEvent",
	"emit_event",
]
