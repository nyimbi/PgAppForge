# SPEC — Enterprise Asset Management / CMMS Plugin

**Module**: `pgappforge.plugins.erp.operations.eam`
**Table prefix**: `eam_`
**Plugin key**: `operations.eam` (registered in `ERP_GROUPS`)
**Depends on**: `foundation`, `finance.gl`, `operations.inventory`

---

## Overview

Enterprise Asset Management (EAM) and Computerised Maintenance Management System
(CMMS) covering the full maintenance lifecycle: asset register, location hierarchy,
meter reading ingestion, maintenance planning (calendar / meter / condition-based),
work order execution, safety permitting, labour and parts costing, failure analysis,
and MTBF / reliability reporting.

Targets industries with significant physical assets: manufacturing, energy,
utilities, mining, facilities management, transport, and healthcare (clinical
equipment maintenance).

Note: **Depreciation** is owned by the `finance.assets` plugin. EAM holds the
maintenance lifecycle only. `ManagedAsset.finance_asset_id` is an advisory
cross-plugin reference — no hard FK constraint.

---

## Key Entities

### AssetLocation
Physical or logical location hierarchy (site → building → floor → room).

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID PK | |
| `tenant_id` | UUID | |
| `code` | String(20) | Short code, unique per tenant |
| `name` | String(200) | |
| `parent_location_id` | UUID FK | Self-referential; NULL = root |
| `level` | Integer | Depth from root (denormalised for fast subtree queries) |
| `address` | Text | |
| `gps_lat`, `gps_lng` | Numeric(9,6) | GPS coordinates for map-based tracking |

### ManagedAsset
Physical asset subject to maintenance management.

| Field | Type | Description |
|-------|------|-------------|
| `asset_code` | String(20) | Unique per tenant |
| `asset_location_id` | UUID FK | Current location |
| `parent_asset_id` | UUID FK | Self-referential; sub-component hierarchy |
| `asset_type` | String | `EQUIPMENT \| VEHICLE \| BUILDING \| INFRASTRUCTURE \| IT` |
| `manufacturer`, `model_number`, `serial_number` | String | Identification |
| `install_date` | Date | |
| `warranty_expiry` | Date | |
| `expected_life_years` | Integer | For end-of-life planning |
| `replacement_cost_cents` | BigInteger | Current replacement cost estimate |
| `status` | String | `ACTIVE \| IN_MAINTENANCE \| OUT_OF_SERVICE \| DECOMMISSIONED` |
| `criticality` | String | `CRITICAL \| HIGH \| MEDIUM \| LOW` |
| `finance_asset_id` | UUID | Advisory FK to finance/assets depreciation record |

### MeterReading
Immutable odometer / runtime hour / cycle count event log.

| Field | Type | Description |
|-------|------|-------------|
| `meter_type` | String | `HOURS \| KM \| CYCLES \| UNITS` |
| `reading_value` | Numeric(12,2) | Cumulative meter value at reading time |
| `reading_date` | Date | |
| `recorded_by` | UUID | Employee who recorded the reading |

Rows are **never updated** — corrections are new readings. `MeterReading` has no
`updated_at` column.

### JobPlan
Reusable maintenance task template — the standard operating procedure for a maintenance type.

| Field | Type | Description |
|-------|------|-------------|
| `code` | String(20) | Unique per tenant |
| `estimated_hours` | Numeric(6,2) | |
| `steps` | JSONB | `[{step_no, description, estimated_mins}]` |
| `required_skills` | JSONB | `["ELECTRICIAN", "MECHANIC", ...]` |
| `safety_precautions` | Text | |
| `parts_list` | JSONB | `[{part_code, quantity}]` |

### MaintenancePlan
Scheduled or condition-based maintenance plan — the trigger definition for generating work orders.

| Field | Type | Description |
|-------|------|-------------|
| `plan_type` | String | `CALENDAR \| METER \| CONDITION` |
| `trigger_interval_days` | Integer | CALENDAR plans: days between WOs |
| `trigger_meter_value` | Numeric | METER plans: meter delta before triggering |
| `trigger_meter_type` | String | METER plans: which meter to watch |
| `lead_days` | Integer | Generate WO this many days before due date |
| `job_plan_id` | UUID FK | Template to use for generated WOs |
| `last_generated_at` | DateTime | |
| `next_due_at` | DateTime | Next scheduled trigger point |
| `is_active` | Boolean | |

### MaintenanceWorkOrder
Central work order record.

| Field | Type | Description |
|-------|------|-------------|
| `wo_number` | String(20) | Unique per tenant |
| `work_type` | String | `PREVENTIVE \| CORRECTIVE \| EMERGENCY \| INSPECTION \| STATUTORY` |
| `priority` | Integer | 1=Emergency, 2=Urgent, 3=Routine, 4=Low |
| `status` | String | See state machine |
| `job_plan_id` | UUID FK | Optional task template |
| `failure_code`, `cause_code`, `remedy_code` | String | ISO 14224 or custom taxonomy |
| `assigned_to` | UUID | Employee UUID |
| `planned_start`, `planned_end` | DateTime | |
| `actual_start`, `actual_end` | DateTime | |
| `estimated_cost_cents` | BigInteger | |
| `actual_cost_cents` | BigInteger | Accumulated from labour and parts lines |
| `downtime_hours` | Numeric(8,2) | Asset downtime for OEE calculation |
| `safety_permit_required` | Boolean | If True, SafetyPermit must be issued before IN_PROGRESS |

### WorkOrderLabor
Labour line on a work order (no `updated_at` — append-only in practice).

| Field | Type | Description |
|-------|------|-------------|
| `craft` | String(30) | e.g. ELECTRICIAN, MECHANIC |
| `planned_hours` | Numeric(6,2) | |
| `actual_hours` | Numeric(6,2) | |
| `rate_cents_per_hour` | Integer | |
| `total_cost_cents` | Computed property | `actual_hours × rate`; not stored |

### WorkOrderPart
Parts and materials consumed on a work order.

| Field | Type | Description |
|-------|------|-------------|
| `part_code` | String(30) | |
| `quantity` | Numeric(8,2) | |
| `unit_cost_cents` | Integer | |
| `total_cost_cents` | BigInteger | `quantity × unit_cost` |
| `sourced_from` | String | `STOCK \| PURCHASE \| WARRANTY` |

### SafetyPermit
Work permit required before high-risk WOs can proceed.

| Field | Type | Description |
|-------|------|-------------|
| `permit_type` | String | `HOT_WORK \| CONFINED_SPACE \| ELECTRICAL \| HEIGHT \| CHEMICAL \| GENERAL` |
| `issued_by` | UUID | Employee who issued the permit |
| `issued_at`, `expires_at` | DateTime | |
| `conditions` | Text | |
| `status` | String | `ISSUED \| ACTIVE \| SUSPENDED \| CLOSED` |

### FailureReport
Failure event record — feeds MTBF and reliability analytics.

| Field | Type | Description |
|-------|------|-------------|
| `wo_id` | UUID FK | Optional: nullable before a corrective WO is raised |
| `failure_description` | Text | |
| `failure_code`, `cause_code` | String(20) | ISO 14224 or custom |

---

## State Machines

### ManagedAsset Status
```
ACTIVE ↔ IN_MAINTENANCE  (WO opened / closed)
ACTIVE → OUT_OF_SERVICE  (manual override or automatic on EMERGENCY WO)
OUT_OF_SERVICE → ACTIVE  (repair completed)
ACTIVE | IN_MAINTENANCE | OUT_OF_SERVICE → DECOMMISSIONED
```

### MaintenanceWorkOrder Status
```
PLANNED → APPROVED → ASSIGNED → IN_PROGRESS
                                 ↘ PENDING_PARTS (material shortage)
                                 ↘ ON_HOLD (external block)
                   IN_PROGRESS | PENDING_PARTS | ON_HOLD → COMPLETED
COMPLETED → CLOSED (supervisor sign-off)
Any non-terminal → CANCELLED
```

Safety gate: if `safety_permit_required=True`, the WO cannot transition to
`IN_PROGRESS` until a `SafetyPermit` with status `ACTIVE` exists for the WO.

### SafetyPermit Status
```
ISSUED → ACTIVE (work starts)
ACTIVE → SUSPENDED (emergency stop)
SUSPENDED → ACTIVE (work resumes)
ACTIVE | SUSPENDED → CLOSED (work complete or abandoned)
```

---

## Events Emitted

| Event | Trigger |
|-------|---------|
| `eam.work_order.created` | New WO saved |
| `eam.work_order.approved` | Status → APPROVED |
| `eam.work_order.started` | Status → IN_PROGRESS |
| `eam.work_order.completed` | Status → COMPLETED |
| `eam.work_order.cancelled` | Status → CANCELLED |
| `eam.asset.status_changed` | Asset status transition |
| `eam.asset.warranty_expiring` | Warrant expiry within 30 days |
| `eam.meter_reading.recorded` | New MeterReading saved |
| `eam.maintenance_plan.triggered` | Scheduler generates new WO |
| `eam.safety_permit.issued` | SafetyPermit created |
| `eam.failure_report.created` | FailureReport saved |

## Events Consumed

| Event | Action |
|-------|--------|
| `inventory.stock.low` | Check if low-stock part is on any pending `WorkOrderPart` — escalate WO to PENDING_PARTS if so |
| `scm.shipment.delivered` | Attempt to transition any PENDING_PARTS WOs that were waiting for this delivery |

---

## GL Account Usage

| Posting | DR | CR | Notes |
|---------|----|----|-------|
| Parts consumed from stock | COGS (5100) | INVENTORY (1140) | Stock issue for WO |
| Labour cost accrued | DIRECT_LABOUR (5200) | ACCRUED_SALARIES (2110) | Internal labour |
| External contractor cost | ACCRUED_EXPENSES (2100) | AP_CONTROL (2000) | On AP invoice approval |
| Emergency replacement capitalised | FIXED_ASSETS_COST (1600) | AP_CONTROL (2000) | If meets capitalisation threshold |

---

## Integration Points

| Plugin | How Used |
|--------|----------|
| `foundation` | Party master for contractor suppliers |
| `finance.assets` | `finance_asset_id` links to fixed asset for replacement cost context |
| `operations.inventory` | Parts stock lookup; stock issue when `WorkOrderPart.sourced_from == STOCK` |
| `operations.scm` | Purchase order raised for `sourced_from == PURCHASE` parts |
| `hcm.personnel` | Employee lookup for `assigned_to` and `recorded_by` fields |
| `finance.gl` | Cost posting on WO completion |

---

## World-Class Features vs Market Leaders

| Feature | PgAppForge | IBM Maximo | SAP PM | IFS Maintenance |
|---------|-----------|------------|--------|----------------|
| Calendar + meter + condition-based plans | Yes | Yes | Yes | Yes |
| Safety permit management | Yes | Yes | Partial | Yes |
| Failure code taxonomy (ISO 14224) | Yes | Yes | Yes | Yes |
| MTBF / reliability analytics | Via analytics plugin | Yes | Partial | Yes |
| Sub-component asset hierarchy | Yes | Yes | Yes | Yes |
| GPS location tracking | Yes (lat/lng) | Yes | No | Partial |
| Job plan templates with skill requirements | Yes | Yes | Yes | Yes |
| Cross-plugin parts integration (inventory) | Yes | Yes | Yes | Yes |
| Advisory FK to depreciation (not hard FK) | Yes | N/A | N/A | N/A |

---

## Architecture Decisions

**WHY `MeterReading` is immutable (no `updated_at`)**: Odometer and runtime hour
readings are physical measurements. Allowing corrections via UPDATE would break
the trigger computation for `MaintenancePlan` — the scheduler computes meter
delta from the last reading. Incorrect readings are superseded by a new reading
with a corrected value and a note.

**WHY `finance_asset_id` is advisory with no FK constraint**: The EAM plugin
can be installed without `finance.assets`. Many organisations manage maintenance
without capitalised asset accounting (e.g. lease equipment, fully-depreciated
fleet). Hard FK would make EAM depend on a finance plugin that may not exist.

**WHY `actual_cost_cents` is accumulated on the WO row rather than always
summed from labour/parts lines**: Real-time cost visibility on work order lists.
Summing `WorkOrderLabor` and `WorkOrderPart` at query time is expensive for
maintenance dashboards showing hundreds of open WOs. The service layer maintains
`actual_cost_cents` as a running total on WO close.

**WHY `priority` is an integer 1–4 rather than a string enum**: Integer allows
natural sort and comparison (`priority <= 2` = urgent or higher). The
`CHECK (priority BETWEEN 1 AND 4)` constraint enforces the domain. String enums
require custom sort logic.

**WHY `safety_permit_required` is a boolean flag rather than a WO type**: Some
CORRECTIVE and EMERGENCY WOs require permits; others do not. The flag is
evaluated per-WO based on the asset's criticality and work type, set by
`EAMService.create_work_order()`. Routing it through WO type would require
adding permit types to every WO type combination.
