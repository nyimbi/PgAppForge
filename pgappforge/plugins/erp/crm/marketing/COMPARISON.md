# Marketing Module — Competitive Benchmark

**Date:** 2026-06-04  
**Benchmarked against:** Salesforce Marketing Cloud, HubSpot, Marketo, Klaviyo, Mailchimp

---

## Score Summary

| Dimension | Score | Notes |
|-----------|-------|-------|
| Campaign lifecycle | 45/100 | Missing: DRAFT/SCHEDULED/CANCELLED statuses, code field, goal_type |
| Lead management | 0/100 | No Lead or LeadActivity models at all |
| List management | 55/100 | STATIC/DYNAMIC present; missing: source, last_synced_at, MarketingListMember table |
| Campaign assets | 0/100 | EmailTemplate exists but not linked as a CampaignAsset; no SMS/AD_COPY/LANDING_PAGE |
| Campaign metrics | 0/100 | No CampaignMetrics table; funnel only via CampaignMember.status counts |
| Lead scoring | 0/100 | Not implemented |
| Attribution/ROI | 30/100 | roi_pct computed on-the-fly; no stored CampaignMetrics; no cost_per_lead |
| Dashboard | 0/100 | No get_marketing_dashboard; no MQL count; no pipeline value |
| Service coverage | 35/100 | 6 services exist; 10 required services missing entirely |
| **TOTAL** | **~18/100** | — |

---

## Gap Analysis

### CRITICAL (score = 0 without them)

#### Models
1. **Lead** — first/last name, email (unique per tenant), phone, company, job_title, source, source_campaign_id FK, status enum, lead_score, assigned_to, converted_at, converted_contact_id. HubSpot/Marketo lead objects are the foundation of all marketing automation; absence is a complete capability gap.
2. **LeadActivity** — lead_id FK, activity_type enum, occurred_at, description, score_delta. Required for lead scoring, attribution, and journey triggers.
3. **CampaignAsset** — campaign_id FK, asset_type, name, content, subject_line, status, send_at, sent_count. Klaviyo/Mailchimp treat each send as an asset with its own lifecycle; current model has no such concept.
4. **CampaignMetrics** — per-campaign delivered/open/click/bounce/unsubscribe/conversion counts plus revenue_attributed, cost_per_lead, roi_pct, updated_at. Without this, ROI is recomputed each time from denormalised fields, not the actual delivery pipeline.
5. **MarketingListMember** — list_id FK, party_id, added_at, status (ACTIVE/UNSUBSCRIBED/BOUNCED), source. Current module has no membership table for marketing lists (MarketingList.member_count is a bare integer with no backing rows).

#### Services
6. **create_campaign** — current code only has a view-layer create; no service-layer method with validation, code generation, and goal tracking.
7. **build_dynamic_list** — `refresh_list_count` is a stub that only updates a timestamp; no actual query execution against erp_party.
8. **send_campaign_asset** — no concept of per-asset sending lifecycle.
9. **score_lead / decay** — no lead scoring at all.
10. **qualify_lead / convert_lead** — lead qualification/conversion pipeline absent.
11. **record_campaign_activity** — no way to increment individual metrics counters (opens, clicks, bounces).
12. **get_campaign_roi** — current `campaign_performance_report` computes roi from campaign.budget_cents which is often null; no stored roi_pct; no cost_per_lead.
13. **get_marketing_dashboard** — absent entirely.

### HIGH

#### Models
- Campaign: missing `code` (unique per-tenant short identifier), `campaign_type` enum missing CONTENT/PAID_ADS, `status` missing DRAFT/SCHEDULED/CANCELLED, `goal_type` field, `target_list_id` FK, `target_leads`/`target_revenue_cents`.
- MarketingList: missing `source` VARCHAR(50), `last_synced_at` (vs current `last_updated_at`), `description` field.

#### Services
- `add_list_members` bulk operation (current `add_member` only adds to campaigns, not lists).
- `unsubscribe` works at campaign level; no list-level unsubscribe that propagates to MarketingListMember.

### MEDIUM
- No A/B test variant support on CampaignAsset.
- No suppression list concept.
- No send-time optimisation metadata.
- Journey engine is schema-only (no executor).

---

## Implementation Plan

All CRITICAL and HIGH gaps implemented in this commit:
1. Add missing models: `MarketingListMember`, `CampaignAsset`, `CampaignMetrics`, `Lead`, `LeadActivity`
2. Extend `Campaign` and `MarketingList` with missing fields
3. Add new events: `LeadQualifiedEvent`, `LeadConvertedEvent`, `CampaignAssetSentEvent`
4. Implement all 10 missing services on `MarketingService`
5. Update `__all__` in models, services, events, and `__init__`
