# Customer Data Platform (CDP) Plugin — SPEC

## Domain
`analytics` — sub-plugin of the Analytics domain.

## Purpose
Unified 360° customer profiles, deterministic and probabilistic identity
resolution, audience segmentation (STATIC/DYNAMIC/AI-driven), and high-volume
behavioural event stream ingestion.

---

## Entities

### UnifiedProfile
One row per canonical Party per tenant. Updated (not inserted) on recompute.

| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| tenant_id | UUID NOT NULL | |
| party_id | UUID FK erp_party | CASCADE; unique per tenant |
| identity_graph | JSONB | `{"nodes":[...], "edges":[...]}` |
| segments | TEXT[] | Denormalised segment names |
| propensity_scores | JSONB | `{"upsell":0.73,"churn":0.12}` |
| lifetime_value_cents | INT | Cumulative LTV — never float |
| churn_probability | NUMERIC(5,4) | 0–1 |
| next_best_action | TEXT | |
| last_computed_at | TIMESTAMPTZ | |

### IdentityEdge
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| tenant_id | UUID NOT NULL | |
| source_type | VARCHAR(100) | email \| cookie_id \| phone_e164 \| crm_contact_id |
| source_id | VARCHAR(500) | Identifier value |
| target_party_id | UUID FK erp_party | |
| confidence_score | NUMERIC(5,4) | 0–1 |
| match_method | VARCHAR(20) | DETERMINISTIC \| PROBABILISTIC |
| matched_attributes | JSONB | `{"email":1.0,"name":0.82}` |

Unique constraint on (source_type, source_id).

### Segment
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| tenant_id | UUID NOT NULL | |
| segment_name | VARCHAR(500) | Unique per tenant |
| segment_type | VARCHAR(20) | STATIC \| DYNAMIC \| AI |
| definition | JSONB | Criteria per type |
| member_count | INT | Denormalised; refreshed by segmentation |
| last_computed_at | TIMESTAMPTZ | |
| tags | TEXT[] | |

### SegmentMembership
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| segment_id | UUID FK Segment | CASCADE |
| party_id | UUID FK erp_party | CASCADE |
| joined_at | TIMESTAMPTZ | DEFAULT NOW() |
| score | NUMERIC(5,4) | Propensity score that triggered membership |

Unique constraint on (segment_id, party_id).

### EventStream
High-volume time-series. BRIN index on occurred_at for efficient range scans.

| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| tenant_id | UUID NOT NULL | |
| party_id | UUID FK erp_party nullable | NULL for anonymous events |
| session_id | VARCHAR(200) | |
| event_type | VARCHAR(200) | Dotted e.g. page.view |
| event_source | VARCHAR(100) | web \| ios \| android \| pos \| api |
| properties | JSONB | Event-specific payload |
| occurred_at | TIMESTAMPTZ | BRIN indexed |
| processed | BOOLEAN | DEFAULT false |

---

## Business Rules
1. Probabilistic identity edges with confidence_score < 0.80 are blocked by Rules Engine.
2. DYNAMIC segments must have `definition.sql` populated (blocked by Rules Engine).
3. AI segments must have `definition.model_name` populated (blocked by Rules Engine).
4. `run_segmentation()` on STATIC segments raises SegmentationError.
5. `lifetime_value_cents` is always integer cents — never float.
6. UnifiedProfile not recomputed in 7+ days triggers stale warning via Rules Engine.
7. When `churn_probability` ≥ 0.70 and `next_best_action` is NULL, Rules Engine sets it to `RETENTION_OFFER`.
8. Identity resolution: multi-match → highest aggregate confidence wins.

---

## Key Service Methods

### CDPService
| Method | Signature | Description |
|---|---|---|
| compute_unified_profile | `(party_id, session)` → UnifiedProfile | Aggregates identity, segments, LTV, churn |
| run_segmentation | `(segment_id, session)` → int | Refreshes DYNAMIC/AI segment membership |
| activate_segment | `(segment_id, channel, session)` → dict | Emits activation event for delivery |
| resolve_identity | `(identifiers: dict, tenant_id, session)` → str | Returns canonical party_id |
| add_identity_edge | `(source_type, source_id, party_id, ...)` → IdentityEdge | Upsert edge |
| ingest_events | `(events: list, tenant_id, session)` → int | Bulk insert EventStream |

---

## API Endpoints

| Method | Path | Description |
|---|---|---|
| GET | /analytics/cdp/profiles/ | Profile list by LTV desc (HTML) |
| GET | /analytics/cdp/profiles/`<party_id>` | Profile detail (JSON) |
| POST | /analytics/cdp/profiles/`<party_id>`/compute | Trigger profile recompute (JSON) |
| GET | /analytics/cdp/segments/ | Segment list (HTML) |
| POST | /analytics/cdp/segments/ | Create segment (JSON) |
| POST | /analytics/cdp/segments/`<id>`/compute | Run segmentation (JSON) |
| POST | /analytics/cdp/segments/`<id>`/activate | Activate to channel (JSON) |
| POST | /analytics/cdp/identity/resolve | Resolve identifiers → party_id (JSON) |
| POST | /analytics/cdp/identity/edge | Add identity edge (JSON) |
| GET | /analytics/cdp/reports/segment_summary | Segment membership counts (HTML) |
| GET | /analytics/cdp/reports/ltv_distribution | LTV bucket distribution (JSON) |

---

## Events Emitted
- `analytics.cdp.profile_computed`
- `analytics.cdp.segment_computed`
- `analytics.cdp.identity_resolved`
- `analytics.cdp.segment_activated`
- `analytics.cdp.event_stream_ingested`

## Events Consumed
- `party.created` — create UnifiedProfile stub
- `ar.invoice.paid` — update lifetime_value_cents
- `crm.opportunity.won` — update LTV and next_best_action
- `analytics.prediction.created` — update propensity_scores

---

## Rules Engine Rulesets (5)
1. `analytics.cdp.block_low_confidence_probabilistic`
2. `analytics.cdp.warn_stale_profile`
3. `analytics.cdp.require_definition_for_dynamic_segment`
4. `analytics.cdp.require_model_for_ai_segment`
5. `analytics.cdp.high_churn_next_best_action`

---

## ReportForge Templates (2)
1. **Segment Summary** — member counts and share by segment (HTML)
2. **LTV Distribution** — bucketed LTV tiers across all profiles (JSON for charting)
