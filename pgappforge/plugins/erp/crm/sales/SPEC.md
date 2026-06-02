# Sales Force Automation (SFA) Plugin — SPEC.md

**Plugin**: `sales`  
**Domain**: `crm`  
**Version**: 1.0.0  
**Depends on**: `foundation`  
**Optionally integrates with**: `cpq` (quote generation), `ar` (invoice on win)

---

## Entities & Relationships

```
foundation.Party ──────┐
                        │ (party_id, optional)
                        ▼
                  SalesAccount ◄──── parent_account_id (self-ref)
                        │
                        ├──── SalesContact (many)
                        │         └──── Activity (many)
                        │
                        └──── Opportunity (many)
                                   ├──── Activity (many)
                                   └──── cpq.Quote (many)

Lead ──(converted)──► SalesAccount + SalesContact + Opportunity

Employee/ab_user ──► SalesTarget (owner_id)
Employee/ab_user ──► SalesForecast (owner_id)
```

### SalesAccount
| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | gen_random_uuid() |
| tenant_id | UUID NOT NULL | Multi-tenant key |
| party_id | UUID FK erp_party | Optional Party link |
| account_number | VARCHAR(30) | Unique per tenant |
| name | VARCHAR(255) NOT NULL | |
| account_type | VARCHAR(30) | PROSPECT/CUSTOMER/PARTNER/COMPETITOR |
| industry | VARCHAR(100) | |
| annual_revenue_cents | INTEGER | Cents, never float |
| employee_count | INTEGER | |
| parent_account_id | UUID FK self | Account hierarchy |
| owner_id | UUID | FK Employee |
| health_score | NUMERIC(3,1) | 0.0–10.0 |
| churn_risk_score | NUMERIC(3,1) | 0.0–10.0 |
| lifetime_value_cents | INTEGER | Cumulative value |
| nps_score | INTEGER | -100 to 100 |
| billing_address | JSONB | Snapshot |
| shipping_address | JSONB | Snapshot |

### SalesContact
Tracks seniority, influence role, engagement score, and opt-out preferences.

### Lead
UTM attribution fields for marketing source tracking. Score (0–100) and grade (A/B/C/D). Converts to SalesAccount + SalesContact + Opportunity atomically.

### Opportunity
7-stage pipeline with probability and forecast_category derived from stage. einstein_score stored as NUMERIC(3,1) — computed externally, stored here.

### Activity
Polymorphic log linking to contact, account, and/or opportunity. Updates engagement_score on linked SalesContact on COMPLETED.

### SalesTarget
Per-owner, per-period, per-type quota. achieved_amount_cents incremented on CLOSED_WON.

### SalesForecast
Period-level forecast with pipeline/best_case/commit/closed buckets + AI forecast. Immutable once submitted (corrections insert new row).

---

## Business Rules

1. **Lead qualification**: score ≥ 70 auto-advances to QUALIFIED (Rules Engine).
2. **Lead conversion**: must be QUALIFIED/WORKING/CONTACTED; creates Account + Contact + Opportunity atomically.
3. **Stage transitions**: CLOSED_WON/LOST are terminal; re-open via NEGOTIATION only.
4. **Amount required**: PROPOSAL stage and beyond require amount_cents (Rules Engine).
5. **Close date required**: NEGOTIATION requires expected_close_date (Rules Engine).
6. **Target credit**: advance_stage to CLOSED_WON increments SalesTarget.achieved_amount_cents.
7. **Stale deals**: opportunities with no update in 30+ days trigger a log_warning (Rules Engine).
8. **Disqualified leads**: cannot be converted without re-qualification (Rules Engine).

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | /crm/accounts/ | List accounts (HTML) |
| GET | /crm/accounts/`<id>` | Account detail (JSON) |
| POST | /crm/accounts/ | Create account |
| PUT | /crm/accounts/`<id>` | Update account |
| GET | /crm/contacts/ | List contacts (HTML) |
| GET | /crm/contacts/`<id>` | Contact detail (JSON) |
| POST | /crm/contacts/ | Create contact |
| PUT | /crm/contacts/`<id>` | Update contact |
| GET | /crm/leads/ | List leads (HTML) |
| GET | /crm/leads/`<id>` | Lead detail (JSON) |
| POST | /crm/leads/ | Create lead |
| PUT | /crm/leads/`<id>` | Update lead |
| POST | /crm/leads/`<id>`/score | Re-score lead (Einstein) |
| POST | /crm/leads/`<id>`/convert | Convert to account/contact/opp |
| POST | /crm/leads/`<id>`/disqualify | Mark DISQUALIFIED |
| GET | /crm/opportunities/ | List opportunities (HTML) |
| GET | /crm/opportunities/`<id>` | Opportunity detail (JSON) |
| POST | /crm/opportunities/ | Create opportunity |
| PUT | /crm/opportunities/`<id>` | Update opportunity |
| POST | /crm/opportunities/`<id>`/advance | Advance stage |
| GET | /crm/activities/ | List activities (JSON) |
| POST | /crm/activities/ | Log activity |
| PUT | /crm/activities/`<id>` | Update activity |
| GET | /crm/reports/pipeline | Pipeline by Stage (HTML) |
| GET | /crm/reports/forecast | Forecast Summary (HTML) |
| GET | /crm/reports/leaderboard | Rep Leaderboard (HTML) |

---

## Events

### Emitted
| Event | Trigger |
|-------|---------|
| `crm.lead.created` | New lead created |
| `crm.lead.scored` | Score recomputed |
| `crm.lead.qualified` | Status → QUALIFIED |
| `crm.lead.converted` | Lead converted |
| `crm.lead.disqualified` | Status → DISQUALIFIED |
| `crm.opportunity.created` | New opportunity |
| `crm.opportunity.stage_advanced` | Stage changed |
| `crm.opportunity.won` | Stage → CLOSED_WON |
| `crm.opportunity.lost` | Stage → CLOSED_LOST |
| `crm.activity.logged` | Activity COMPLETED |
| `crm.forecast.submitted` | Forecast submitted |

### Consumed
| Event | Action |
|-------|--------|
| `crm.quote.accepted` | Auto-advance opportunity to CLOSED_WON |
| `ar.invoice.paid` | Update account lifetime_value_cents |

---

## Reports

1. **Pipeline by Stage** (`/crm/reports/pipeline`): deal count, total value, probability-weighted value per open stage.
2. **Forecast Summary** (`/crm/reports/forecast`): pipeline/best_case/commit/closed/AI forecast per rep per period.
3. **Rep Leaderboard** (`/crm/reports/leaderboard`): closed-won deal count and revenue ranked by rep.

---

## Rules Engine Rulesets (5)

1. `crm.lead.auto_qualify` — auto-advance lead to QUALIFIED at score ≥ 70
2. `crm.opportunity.amount_required_for_proposal` — block advance to PROPOSAL without amount_cents
3. `crm.opportunity.close_date_required` — block NEGOTIATION without expected_close_date
4. `crm.opportunity.stale_deal_warning` — warn on opportunities with no update in 30+ days
5. `crm.lead.no_convert_disqualified` — block conversion of DISQUALIFIED leads
