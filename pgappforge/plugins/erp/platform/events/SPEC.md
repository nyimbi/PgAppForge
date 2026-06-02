# Platform Events Plugin — SPEC

## Domain
`platform` — cross-cutting event infrastructure

## Purpose
Extends the foundation in-process `_EVENT_BUS` with a durable, persistent
subscription registry and delivery audit log.  Enables replay, dead-letter
handling, and per-plugin delivery accounting.

## Entities

### EventSubscription
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | gen_random_uuid() |
| tenant_id | UUID | NULL = system-wide |
| subscriber_plugin | VARCHAR(200) | e.g. `finance.gl` |
| event_type | VARCHAR(200) | e.g. `invoice.paid` |
| handler_function | VARCHAR(500) | dotted import path |
| is_active | BOOL | soft delete |
| retry_count | INT DEFAULT 3 | max attempts |
| dead_letter_after | INT DEFAULT 5 | failure budget |
| filter_conditions | JSONB | JSONLogic expression |
| description | TEXT | |
| created_at / updated_at | TIMESTAMPTZ | |

UNIQUE (subscriber_plugin, event_type)

### EventDeliveryLog *(append-only)*
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| event_id | VARCHAR(36) | logical FK → erp_domain_event_log.event_id |
| subscription_id | UUID FK | → EventSubscription |
| delivery_attempt | INT | 1-based |
| delivered_at | TIMESTAMPTZ DEFAULT NOW() | |
| status | VARCHAR(20) | DELIVERED \| FAILED \| DEAD_LETTER |
| error_message | TEXT | |
| response_code | INT | HTTP code for webhook; NULL in-process |

**NEVER UPDATE** rows in EventDeliveryLog.

## Business Rules
1. Only one active subscription per (subscriber_plugin, event_type).
2. retry_count ≤ dead_letter_after.
3. Delivery is best-effort in-process; failures are logged, not re-raised.
4. Replay re-fires handlers without re-inserting DomainEventLog rows.
5. DENY effect in AccessPolicy overrides ALLOW (identity plugin concern).

## Events Emitted
- `event.subscription.created`
- `event.subscription.deactivated`
- `event.delivery.failed`
- `event.delivery.dead_lettered`
- `event.replayed`

## Events Consumed
None (cross-cutting concern).

## API Endpoints

| Method | Path | Description |
|---|---|---|
| GET | /platform/events/subscriptions/ | List subscriptions |
| POST | /platform/events/subscriptions/ | Create subscription |
| POST | /platform/events/subscriptions/{id}/deactivate | Deactivate |
| GET | /platform/events/delivery-log/ | Browse delivery log |
| GET | /platform/events/stats | Delivery statistics |
| POST | /platform/events/replay | Replay events in time window |
| GET | /platform/events/reports/delivery-summary | Per-subscription delivery rate |
| GET | /platform/events/reports/dead-letters | All DEAD_LETTER entries |
| GET | /platform/events/reports/event-volume | Event type frequency |

## Rules Engine Rulesets (3)
1. `event_subscription.no_self_loop` — plugin cannot subscribe to its own events
2. `event_subscription.retry_limits` — retry_count ≤ dead_letter_after
3. `event_delivery.immutable` — block UPDATE on EventDeliveryLog

## Cross-plugin Composability
- **Upstream**: foundation (DomainEventLog)
- **Downstream**: all ERP plugins (consume via subscription registry)
