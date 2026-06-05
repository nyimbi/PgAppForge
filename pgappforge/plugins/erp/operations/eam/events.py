"""
pgappforge/plugins/erp/operations/eam/events.py

Domain events for the Enterprise Asset Management (EAM/CMMS) plugin.

All monetary amounts are integer cents — never float.
Metric values (MTBF, MTTR, hours) are Decimal-compatible strings.

Events emitted:
  eam.asset.created                  — new managed asset registered
  eam.work_order.created             — work order opened (preventive or corrective)
  eam.work_order.completed           — work order closed with actual costs
  eam.maintenance_plan.triggered     — plan due date / meter threshold crossed
  eam.safety_permit.issued           — safety permit issued against a work order
  eam.asset.metrics_calculated       — MTBF / MTTR / availability computed for a period
"""
from __future__ import annotations

from dataclasses import dataclass, field

from pgappforge.plugins.erp.foundation.events import DomainEvent


# ---------------------------------------------------------------------------
# Asset events
# ---------------------------------------------------------------------------

@dataclass
class AssetCreatedEvent(DomainEvent):
	"""Emitted when a new ManagedAsset is registered in the system."""
	event_type: str = "eam.asset.created"
	asset_id: str = ""
	asset_code: str = ""
	name: str = ""
	asset_type: str = ""          # EQUIPMENT / VEHICLE / BUILDING / INFRASTRUCTURE / IT
	criticality: str = ""         # CRITICAL / HIGH / MEDIUM / LOW
	asset_location_id: str = ""
	finance_asset_id: str = ""    # link to finance/assets depreciation record; "" if none


@dataclass
class AssetMetricsCalculatedEvent(DomainEvent):
	"""Emitted after calculate_asset_metrics() completes."""
	event_type: str = "eam.asset.metrics_calculated"
	asset_id: str = ""
	from_date: str = ""           # ISO date
	to_date: str = ""             # ISO date
	mtbf_hours: str = ""          # Decimal string; "" when undefined (0 failures)
	mttr_hours: str = ""          # Decimal string; "" when undefined (0 WOs)
	availability_pct: str = ""    # "99.12" style
	total_maintenance_cost_cents: int = 0
	failure_count: int = 0
	wo_count: int = 0


# ---------------------------------------------------------------------------
# Work order events
# ---------------------------------------------------------------------------

@dataclass
class WorkOrderCreatedEvent(DomainEvent):
	"""Emitted when any MaintenanceWorkOrder row is created."""
	event_type: str = "eam.work_order.created"
	wo_id: str = ""
	wo_number: str = ""
	asset_id: str = ""
	work_type: str = ""           # PREVENTIVE / CORRECTIVE / EMERGENCY / INSPECTION / STATUTORY
	priority: int = 3             # 1=Emergency … 4=Low
	status: str = "PLANNED"
	planned_start: str = ""       # ISO datetime
	planned_end: str = ""         # ISO datetime
	estimated_cost_cents: int = 0
	triggered_by_plan_id: str = ""   # non-empty when auto-generated from a MaintenancePlan


@dataclass
class WorkOrderCompletedEvent(DomainEvent):
	"""Emitted when a work order transitions to COMPLETED status."""
	event_type: str = "eam.work_order.completed"
	wo_id: str = ""
	wo_number: str = ""
	asset_id: str = ""
	work_type: str = ""
	actual_start: str = ""        # ISO datetime
	actual_end: str = ""          # ISO datetime
	actual_cost_cents: int = 0
	downtime_hours: str = ""      # Decimal string; "" if not recorded
	remedy_code: str = ""
	gl_journal_id: str = ""       # populated when GL plugin is active


# ---------------------------------------------------------------------------
# Maintenance plan events
# ---------------------------------------------------------------------------

@dataclass
class MaintenancePlanTriggeredEvent(DomainEvent):
	"""Emitted when a MaintenancePlan threshold is crossed and a WO is generated."""
	event_type: str = "eam.maintenance_plan.triggered"
	plan_id: str = ""
	plan_name: str = ""
	asset_id: str = ""
	trigger_type: str = ""        # CALENDAR / METER / CONDITION
	wo_id: str = ""
	wo_number: str = ""
	meter_reading_id: str = ""    # non-empty when triggered by a meter reading


# ---------------------------------------------------------------------------
# Safety permit events
# ---------------------------------------------------------------------------

@dataclass
class SafetyPermitIssuedEvent(DomainEvent):
	"""Emitted when a SafetyPermit is issued against a work order."""
	event_type: str = "eam.safety_permit.issued"
	permit_id: str = ""
	wo_id: str = ""
	wo_number: str = ""
	permit_type: str = ""         # HOT_WORK / CONFINED_SPACE / ELECTRICAL / HEIGHT / CHEMICAL / GENERAL
	issued_by: str = ""           # UUID of employee
	issued_at: str = ""           # ISO datetime
	expires_at: str = ""          # ISO datetime


__all__ = [
	"AssetCreatedEvent",
	"AssetMetricsCalculatedEvent",
	"WorkOrderCreatedEvent",
	"WorkOrderCompletedEvent",
	"MaintenancePlanTriggeredEvent",
	"SafetyPermitIssuedEvent",
]
