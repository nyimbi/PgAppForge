# SPEC — Fleet Management Plugin

**Module**: `pgappforge.plugins.erp.operations.fleet`
**Table prefix**: `fleet_`
**Plugin key**: `operations.fleet` (registered in `ERP_GROUPS`)
**Depends on**: `foundation`, `finance.gl`, `hcm.personnel`

---

## Overview

Full fleet lifecycle management: vehicle register, compliance document tracking
(KRA, NTSA, TLB), driver licensing and demerit points, trip authorisation and
log, fuel consumption tracking, garage service history, incident and insurance
claim management, maintenance scheduling (km and calendar-based), and cost
reporting.

Optimised for the Kenyan regulatory environment (KRA road tax, NTSA inspection,
PSV badge), with generic international applicability.

---

## Key Entities

### Vehicle
Central vehicle register.

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID PK | |
| `tenant_id` | UUID | |
| `reg_number` | String(20) | Official registration plate e.g. KCA 123A |
| `make`, `model` | String(100) | |
| `year_of_manufacture` | Integer | |
| `chassis_number` | String(30) | Unique globally; cross-verified with logbook |
| `engine_number` | String(30) | |
| `fuel_type` | String | `PETROL \| DIESEL \| ELECTRIC \| HYBRID \| LPG` |
| `body_type` | String | `SALOON \| SUV \| PICKUP \| LORRY \| BUS \| VAN \| MOTORCYCLE` |
| `seating_capacity` | Integer | |
| `payload_kg` | Numeric(8,2) | Commercial vehicle payload |
| `acquisition_date` | Date | |
| `acquisition_cost_cents` | BigInteger | Purchase price in cents |
| `current_odometer_km` | Numeric(10,2) | Updated on each closed TripLog / FuelRecord |
| `status` | String | `ACTIVE \| IN_MAINTENANCE \| OUT_OF_SERVICE \| DISPOSED` |
| `assigned_driver_id` | UUID | Advisory FK to fleet_driver.id |
| `department_id` | UUID | Advisory FK to HR department |
| `gps_device_id` | String(50) | GPS tracker device identifier |
| `average_fuel_consumption_per_100km` | Numeric(6,2) | Rolling average; updated on FuelRecord |

### VehicleDocument
Compliance documents with expiry alerting.

| Field | Type | Description |
|-------|------|-------------|
| `doc_type` | String | `LOGBOOK \| INSURANCE \| ROAD_TAX \| INSPECTION \| DRIVING_CERT \| OTHER` |
| `document_number` | String(60) | |
| `issuing_authority` | String(100) | e.g. KRA, NTSA, Transport Licensing Board |
| `issue_date`, `expiry_date` | Date | |
| `cost_cents` | BigInteger | |
| `alert_days_before` | Integer | Default 30; days before expiry to trigger alert |

### Driver
Fleet driver record — links to an HR employee with fleet-specific attributes.

| Field | Type | Description |
|-------|------|-------------|
| `employee_id` | UUID | Advisory FK to HR employee |
| `license_number` | String(20) | NTSA license number |
| `license_class` | String(10) | e.g. BCE, C, D (Kenya NTSA classes) |
| `license_expiry` | Date | |
| `psvb_expiry` | Date | PSV badge expiry (Transport Licensing Board, Kenya) |
| `medical_expiry` | Date | NTSA medical certificate expiry |
| `status` | String | `ACTIVE \| SUSPENDED \| BLACKLISTED` |
| `demerit_points` | Integer | Accumulates from incidents; >= 12 triggers auto-suspend |
| `total_trips` | Integer | Running total |
| `total_km` | Numeric(12,2) | Running total |

### TripLog
One row per vehicle movement.

| Field | Type | Description |
|-------|------|-------------|
| `trip_type` | String | `OFFICIAL \| PERSONAL \| DELIVERY \| PASSENGER` |
| `start_datetime`, `end_datetime` | DateTime | `end_datetime` NULL while trip is open |
| `start_odometer`, `end_odometer` | Numeric(10,2) | |
| `distance_km` | Numeric(8,2) | Computed on close: `end - start` |
| `start_location`, `end_location` | String(200) | |
| `authorized_by` | UUID | Advisory FK to employee who authorised |
| `fuel_used_litres` | Numeric(8,2) | Optional: from vehicle fuel sensor |

### FuelRecord
One fuelling transaction.

| Field | Type | Description |
|-------|------|-------------|
| `fuel_type` | String | Actual fuel type on this fill |
| `litres` | Numeric(8,2) | |
| `cost_per_litre_cents` | BigInteger | |
| `total_cost_cents` | BigInteger | `litres × cost_per_litre`; validated in service |
| `odometer_km` | Numeric(10,2) | At time of fuelling |
| `station_name` | String(100) | |
| `receipt_number` | String(50) | |
| `payment_method` | String | `CASH \| CARD \| FLEET_CARD \| ACCOUNT` |

### VehicleService
One garage/workshop service event.

| Field | Type | Description |
|-------|------|-------------|
| `service_type` | String | `ROUTINE \| MAJOR \| REPAIR \| TYRES \| BATTERY \| ELECTRICAL \| BODY` |
| `odometer_km` | Numeric(10,2) | At time of service |
| `garage_name` | String(100) | |
| `parts_cost_cents`, `labour_cost_cents`, `total_cost_cents` | BigInteger | |
| `invoice_number` | String(50) | |
| `next_service_km` | Numeric(10,2) | Feeds MaintenanceSchedule update |
| `next_service_date` | Date | |

### FleetIncident
Accident, breakdown, traffic violation, theft, or vandalism record.

| Field | Type | Description |
|-------|------|-------------|
| `incident_type` | String | `ACCIDENT \| BREAKDOWN \| TRAFFIC_VIOLATION \| THEFT \| VANDALISM \| OTHER` |
| `police_report_number` | String(50) | |
| `insurance_claim_number` | String(50) | |
| `third_party_involved` | Boolean | Triggers insurance liaison workflow |
| `estimated_damage_cents` | BigInteger | |
| `status` | String | `REPORTED \| UNDER_INVESTIGATION \| CLOSED` |

ACCIDENT incidents apply demerit points to the driver via `FleetService.report_incident()`.
At `demerit_points >= 12`, the driver is automatically suspended (`status = SUSPENDED`).

### MaintenanceSchedule
Per-vehicle maintenance trigger (km and/or calendar).

| Field | Type | Description |
|-------|------|-------------|
| `schedule_type` | String | `ROUTINE_SERVICE \| OIL_CHANGE \| TYRE_ROTATION \| MAJOR_SERVICE \| INSPECTION` |
| `trigger_km` | Numeric(10,2) | Service interval in km |
| `trigger_days` | Integer | Service interval in days |
| `last_done_km`, `last_done_date` | Numeric / Date | Set by `record_service()` |
| `next_due_km`, `next_due_date` | Numeric / Date | Computed by `record_service()` |
| `estimated_cost_cents` | BigInteger | Budget for next service |

One row per vehicle per `schedule_type` (UNIQUE constraint).

---

## State Machines

### Vehicle Status
```
ACTIVE ↔ IN_MAINTENANCE  (service or incident repair)
ACTIVE → OUT_OF_SERVICE  (breakdown, suspension)
OUT_OF_SERVICE → ACTIVE  (repair complete)
Any → DISPOSED           (end-of-life decommission)
```

### Driver Status
```
ACTIVE → SUSPENDED  (demerit >= 12, or manual HR action)
SUSPENDED → ACTIVE  (demerit points cleared, investigation complete)
ACTIVE | SUSPENDED → BLACKLISTED  (permanent ban)
```

### TripLog
```
Open (end_datetime = NULL) → Closed (end_datetime set)
```
Closing a trip updates `vehicle.current_odometer_km` and `driver.total_km`.

### FleetIncident Status
```
REPORTED → UNDER_INVESTIGATION → CLOSED
```

---

## Events Emitted

| Event | Trigger |
|-------|---------|
| `fleet.vehicle.registered` | New Vehicle saved |
| `fleet.vehicle.status_changed` | Vehicle status transition |
| `fleet.document.expiring` | Document within `alert_days_before` of expiry |
| `fleet.document.expired` | Document past expiry date |
| `fleet.driver.suspended` | Driver status → SUSPENDED |
| `fleet.driver.blacklisted` | Driver status → BLACKLISTED |
| `fleet.trip.started` | TripLog created |
| `fleet.trip.completed` | TripLog closed |
| `fleet.fuel.recorded` | FuelRecord saved |
| `fleet.service.recorded` | VehicleService saved |
| `fleet.incident.reported` | FleetIncident created |
| `fleet.maintenance.due` | `next_due_km` or `next_due_date` threshold crossed |

## Events Consumed

| Event | Action |
|-------|--------|
| `hcm.personnel.employee.terminated` | Check if terminated employee is an active Driver; if so, set Driver status to SUSPENDED pending handover |

---

## GL Account Usage

| Posting | DR | CR | Notes |
|---------|----|----|-------|
| Fuel purchase (cash) | TRAVEL_AND_ENTERTAINMENT (6300) | CASH_AND_NOSTRO (1011) | Or petty cash 1013 |
| Fuel purchase (fleet card / account) | TRAVEL_AND_ENTERTAINMENT (6300) | AP_CONTROL (2000) | On statement settlement |
| Vehicle service payment | ACCRUED_EXPENSES (2100) | CASH_AND_NOSTRO (1011) | After AP invoice approval |
| Vehicle service cost accrual | TRAVEL_AND_ENTERTAINMENT (6300) | AP_CONTROL (2000) | On invoice receipt |
| Vehicle acquisition capitalised | FIXED_ASSETS_COST (1600) | AP_CONTROL (2000) | If meets capitalisation threshold |
| Insurance claim received | CASH_AND_NOSTRO (1011) | OTHER_INCOME (4500) | Claim settlement proceeds |

---

## Integration Points

| Plugin | How Used |
|--------|----------|
| `foundation` | Party for fleet card suppliers and garage vendors |
| `hcm.personnel` | Employee lookup for driver and authorized_by fields; termination event |
| `finance.gl` | Cost postings for fuel, service, incident damage |
| `finance.assets` | Vehicle capitalisation — acquisition_cost_cents fed to fixed asset record on purchase |
| `hcm.travel_expense` | Mileage logs from fleet trips can feed MileageLog in T&E for employee reimbursement |

---

## World-Class Features vs Market Leaders

| Feature | PgAppForge | FleetComplete | SAP Fleet Mgmt | Microsoft Dynamics Fleet |
|---------|-----------|---------------|----------------|--------------------------|
| Kenya KRA/NTSA document compliance | Yes | No | No | No |
| PSV badge + medical certificate tracking | Yes | No | No | No |
| Demerit point auto-suspension | Yes | Partial | No | No |
| Fuel consumption rolling average | Yes | Yes | Yes | Partial |
| km + calendar dual-trigger maintenance | Yes | Yes | Yes | Yes |
| GPS device ID field | Yes | Yes | Yes | Partial |
| Multi-currency acquisition cost | Yes | No | Yes | Yes |
| GL cost posting on fuel/service | Yes | No | Yes | Yes |
| Incident → insurance claim lifecycle | Yes | Partial | Partial | No |

---

## Architecture Decisions

**WHY string CHECK constraints instead of PG ENUM types**: PostgreSQL ENUM types
require `ALTER TYPE` DDL to add values. As fleet regulations add new fuel types
(hydrogen is emerging), vehicle body types, or document types, a string column
with a CHECK constraint allows adding values via migration without breaking
existing data or requiring `CASCADE` rebuild of dependent indexes. The constraint
still enforces validity; failure messages are readable.

**WHY `demerit_points` is incremented in the service layer rather than computed
from incident rows at query time**: Demerit points accumulate over time but may
be formally reduced by HR action (rehabilitation programmes). The stored value
is the authoritative, HR-managed number. Computing from incidents would not
reflect manual adjustments.

**WHY `average_fuel_consumption_per_100km` is a stored rolling average**: Fuel
consumption is queried constantly in fleet dashboards. Computing it from all
`FuelRecord` rows at query time across a large fleet is expensive. The rolling
average is updated on each `FuelRecord` insert using: `(prev_avg × prev_distance
+ litres × 100) / (prev_distance + distance_km)`.

**WHY `chassis_number` has a global UNIQUE constraint (not per-tenant)**: A
chassis number is a physical property of a vehicle — it is unique in the real
world. Two tenants cannot legitimately share a chassis number (except data entry
error). The global constraint prevents accidental duplication across tenants and
supports cross-tenant stolen-vehicle detection.

**WHY `assigned_driver_id` and `department_id` are advisory FKs**: Fleet
management is often deployed without full HCM. Vehicles exist before HR records
for drivers are created. Advisory FK allows bootstrapping without dependency on
HCM plugin being fully initialised.
