# Marketing Automation — World-Class Comparison

## Our Implementation
- Campaign lifecycle: DRAFT → ACTIVE with full audit via events
- Multi-step sequences: EMAIL, SMS, WEBHOOK, WAIT, CONDITION step types with configurable `delay_hours`
- Per-step condition evaluation engine (eq/neq/gt/gte/lt/lte/in/not_in/is_null/contains against contact context)
- A/B variant assignment with weighted random distribution; per-variant conversion analytics
- Lead scoring: upsert model with letter grades (D→A+), factor history log, grade-change events
- Revenue attribution: LAST_TOUCH model with `CampaignAttribution` row and campaign spend accumulation
- Campaign analytics: enrollment/active/completed/unsubscribed/bounced counts, conversion rate, CPC, A/B performance
- BPM actions: `crm.marketing.enroll_contact`, `crm.marketing.score_lead`

**Integration points:** BPM workflow engine, GL (revenue attribution), CRM contacts

---

## Benchmark: HubSpot Marketing Hub

| Feature | Ours | HubSpot |
|---|---|---|
| Multi-step sequences | ✓ | ✓ |
| Conditional branching in sequences | ✓ (per-step) | ✓ (visual) |
| A/B testing | ✓ (weighted) | ✓ |
| Lead scoring | ✓ (custom factors) | ✓ |
| Revenue attribution | ✓ (LAST_TOUCH) | ✓ (multi-model) |
| Email send (native) | ✗ (event only) | ✓ |
| Landing pages | ✗ | ✓ |
| CRM contact sync | ✓ (via contact_id) | ✓ (native) |
| Behavioral triggers (page visits) | ✗ | ✓ |
| Social media publishing | ✗ | ✓ |
| Attribution models | ✓ (1) | ✓ (6+) |

## Benchmark: Mailchimp

| Feature | Ours | Mailchimp |
|---|---|---|
| Automated sequences | ✓ | ✓ |
| A/B testing | ✓ | ✓ |
| Audience segmentation | ✗ | ✓ |
| Template editor | ✗ | ✓ |
| Email delivery | ✗ (delegate only) | ✓ |
| Analytics / open rates | ✗ | ✓ |
| ERP/BPM integration | ✓ | ✗ |

## Benchmark: Odoo Marketing Automation

| Feature | Ours | Odoo |
|---|---|---|
| Sequences with delays | ✓ | ✓ |
| Filter conditions | ✓ | ✓ |
| A/B testing | ✓ | ✓ |
| Lead scoring | ✓ | ✓ |
| SMS steps | ✓ | ✓ |
| WhatsApp steps | ✗ | ✓ |
| Revenue attribution | ✓ | partial |
| BPM workflow triggers | ✓ | limited |

---

## Differentiation

**Where we exceed:**
- Attribution events are transactional (same DB session as business mutation) — no async sync lag
- Lead scoring factors carry full history log, making audit trails trivial
- A/B variant data flows through to conversion analytics without external ETL

**Remaining gaps:**
- No native email/SMS delivery — step execution emits events and logs; actual dispatch requires an external gateway wired to the event bus
- Single attribution model (LAST_TOUCH); first-touch, linear, time-decay not implemented
- No behavioral triggers (web visits, link clicks) without external event ingestion
- No audience segmentation builder
