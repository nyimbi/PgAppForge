# Field Service Plugin — SPEC

## Domain
`crm` / `field_service`

## Purpose
Schedule and dispatch field technicians to customer sites. Manage territories,
resource skills/availability, work orders, and customer appointments with
time-slot confirmation flow.

## Entities

| Model | Table | Key Fields |
|---|---|---|
| ServiceTerritory | fs_service_territory | name, manager_id (Employee FK), boundary GEOMETRY(POLYGON,4326) |
| ServiceResource | fs_service_resource | employee_id (unique/tenant), territory_id FK, skills JSONB, availability JSONB, capacity_per_day |
| WorkOrder | fs_work_order | work_order_number (unique/tenant), case_id FK nullable, account_id, contact_id, work_type, scheduled_start/end TIMESTAMPTZ, assigned_to FK ServiceResource, status, location GEOMETRY(Point,4326), address JSONB, parts_used JSONB, labor_minutes, completion_notes |
| ServiceAppointment | fs_service_appointment | work_order_id FK, contact_id, proposed_slots JSONB, confirmed_slot JSONB (TSTZRANGE), confirmation_sent_at, reminder_sent_at, status |

## Relationships
- ServiceTerritory →(many) ServiceResource
- ServiceResource →(many) WorkOrder (assigned_to)
- WorkOrder →(many) ServiceAppointment (cascade delete)
- WorkOrder →(1) Case (SET NULL — optional)

## Business Rules
1. WorkOrder cannot be COMPLETED without an assigned resource.
2. CANCELLED work orders cannot be re-opened — create a new work order.
3. ServiceAppointment confirmed_slot chosen from proposed_slots by index.
4. Geometry stored via Geoalchemy2 when available; JSONB GeoJSON fallback.
5. parts_used is a JSONB array of `{sku, qty, unit_cost_cents}` — amounts always integer cents.
6. capacity_per_day enforced at application level in scheduling service.

## Work Type Values
INSTALL | REPAIR | MAINTENANCE | INSPECTION

## Status Transitions
```
WorkOrder:          DRAFT → SCHEDULED → IN_PROGRESS → COMPLETED
                         ↘ CANCELLED (from any non-COMPLETED)
ServiceAppointment: PENDING → CONFIRMED → COMPLETED
                           ↘ CANCELLED | NO_SHOW
```

## API Endpoints
| Method | Path | Description |
|---|---|---|
| GET | /field-service/territories/ | List territories |
| POST | /field-service/territories/ | Create territory |
| GET | /field-service/resources/ | List resources |
| GET | /field-service/resources/<id>/schedule | Resource calendar |
| GET | /field-service/work-orders/ | List work orders |
| POST | /field-service/work-orders/ | Create work order |
| POST | /field-service/work-orders/<id>/schedule | Assign resource + times |
| POST | /field-service/work-orders/<id>/complete | Record completion |
| POST | /field-service/appointments/propose | Propose slots |
| POST | /field-service/appointments/<id>/confirm | Confirm slot |
| POST | /field-service/appointments/<id>/cancel | Cancel |
| GET | /field-service/reports/open-work-orders | Open WOs by type/status |
| GET | /field-service/reports/resource-utilisation | Labor by territory |
| GET | /field-service/reports/completion-rate | Completion rate by work type |

## Events
**Emitted:** work_order.created, work_order.scheduled, work_order.completed,
appointment.confirmed, appointment.cancelled

**Consumed:** service.case.created (WO creation hook), service.case.escalated
(priority scheduling flag)

## Rules Engine Rulesets (3)
1. `fs.work_order.complete_requires_resource` — block completion without resource
2. `fs.work_order.schedule_conflict` — warn on potential double-booking
3. `fs.appointment.confirm_requires_slots` — block confirm with empty slots

## ReportForge Templates
- **Open Work Orders** — count by work_type and status
- **Resource Utilisation** — completed WOs and total labor by territory
- **Completion Rate** — completed / total by work type with % rate

## Dependencies
- `foundation` (DomainEventLog)
- `service` (Case FK — optional link)
- Geoalchemy2 (optional) for PostGIS GEOMETRY columns; JSONB fallback active
