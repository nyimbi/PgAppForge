# Marketing Plugin — SPEC

## Domain
`crm` / `marketing`

## Purpose
End-to-end campaign management: plan budgets, build audiences, execute
multi-channel sends, track engagement funnels, run automation journeys,
and measure ROI attribution.

## Entities

| Model | Table | Key Fields |
|---|---|---|
| Campaign | mkt_campaign | campaign_name (unique/tenant), campaign_type, status, start_date, end_date, budget_cents, actual_cost_cents, target_audience JSONB, owner_id, expected/actual_leads, expected/actual_revenue_cents |
| EmailTemplate | mkt_email_template | name (unique/tenant), subject, html_body, text_body, sender_name, sender_email, is_active, tags TEXT[] |
| CampaignMember | mkt_campaign_member | campaign_id + party_id (unique), member_type (LEAD/CONTACT), status funnel, responded_at, source_campaign_id |
| MarketingList | mkt_list | name (unique/tenant), list_type (STATIC/DYNAMIC), filter_criteria JSONB, member_count, last_updated_at |
| JourneyStep | mkt_journey_step | journey_id, step_number, step_type, config JSONB, next_step_id, branch_yes_id, branch_no_id (self-ref DAG) |

## Relationships
- Campaign →(many) CampaignMember (cascade delete)
- JourneyStep → JourneyStep (self-ref: next_step, branch_yes, branch_no)
- CampaignMember →(soft) Party (no hard FK — cross-schema compatible)

## Monetary Fields (all integer cents)
- budget_cents, actual_cost_cents, expected_revenue_cents, actual_revenue_cents

## Business Rules
1. Members cannot be added to COMPLETED or ARCHIVED campaigns.
2. Budget overspend triggers rule engine warning (not block).
3. Unsubscribed party re-add triggers consent warning.
4. CampaignMember status progression: SENT → DELIVERED → OPENED → CLICKED → RESPONDED | UNSUBSCRIBED.
5. actual_leads auto-incremented on add_member.
6. ROI = (actual_revenue_cents - actual_cost_cents) / budget_cents × 100.

## Campaign Type Values
EMAIL | SMS | PAID | EVENT | WEBINAR | SOCIAL

## Status Transitions
```
Campaign:       PLANNING → ACTIVE ↔ PAUSED → COMPLETED → ARCHIVED
CampaignMember: SENT → DELIVERED → OPENED → CLICKED → RESPONDED
                                                    ↘ UNSUBSCRIBED (any stage)
JourneyStep:    EMAIL | SMS | WAIT | BRANCH | SCORE
```

## API Endpoints
| Method | Path | Description |
|---|---|---|
| GET | /marketing/campaigns/ | List campaigns |
| POST | /marketing/campaigns/ | Create campaign |
| POST | /marketing/campaigns/<id>/activate | PLANNING → ACTIVE |
| POST | /marketing/campaigns/<id>/complete | → COMPLETED |
| POST | /marketing/campaigns/<id>/members | Add member |
| PATCH | /marketing/campaigns/members/<id>/status | Update engagement status |
| GET | /marketing/email-templates/ | List templates |
| GET | /marketing/lists/ | List marketing lists |
| GET | /marketing/reports/campaign-performance | Funnel + ROI |
| GET | /marketing/reports/lead-pipeline | Conversion by campaign type |
| GET | /marketing/reports/top-campaigns | Top by revenue |

## Events
**Emitted:** campaign.activated, campaign.completed, lead.responded,
member.unsubscribed, journey.step_executed

**Consumed:** party.created (lead seeding), ar.invoice.paid (revenue attribution)

## Rules Engine Rulesets (3)
1. `mkt.campaign.no_members_after_complete` — block add after complete
2. `mkt.campaign.budget_overspend` — warn when actual > budget
3. `mkt.member.unsubscribe_honour` — warn on re-adding unsubscribed party

## ReportForge Templates
- **Campaign Performance** — funnel stages, open/click rates, cost/revenue/ROI
- **Lead Pipeline** — sent/responded counts and conversion rate by campaign type
- **Top Campaigns** — ranked by actual_revenue_cents

## Dependencies
- `foundation` (DomainEventLog, Party)
- `ar` (optional: invoice attribution via ar.invoice.paid event)
