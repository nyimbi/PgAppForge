# Service Cloud Plugin — SPEC

## Domain
`crm` / `service`

## Purpose
Full support case lifecycle with SLA enforcement, knowledge base, multi-channel
case comments, and CSAT/NPS/CES survey collection.

## Entities

| Model | Table | Key Fields |
|---|---|---|
| SLAPolicy | sc_sla_policy | name, priority (P1-P4), first_response_minutes, resolution_minutes, business_hours_only |
| Case | sc_case | case_number (unique/tenant), account_id, contact_id, subject, priority, status, channel, owner_id, escalated_to, sla_policy_id, sla_breach_at, resolved_at, csat_score, knowledge_articles_used UUID[] |
| KnowledgeArticle | sc_knowledge_article | title, category, status (DRAFT/REVIEW/PUBLISHED/ARCHIVED), content, tags[], author_id, views, helpful_votes, last_published_at, embedding (JSONB, 1536-dim) |
| CaseComment | sc_case_comment | case_id, author_id, is_public, body, sent_at, channel (INTERNAL/EMAIL/CHAT) |
| SurveyResponse | sc_survey_response | case_id, contact_id, survey_type (CSAT/NPS/CES), score, comment, submitted_at — APPEND-ONLY |

## Relationships
- Case →(many) CaseComment (cascade delete)
- Case →(many) SurveyResponse (cascade delete, append-only)
- Case →(1) SLAPolicy (SET NULL on delete)
- SLAPolicy →(many) Case

## Business Rules
1. SLA breach time computed at case creation from SLAPolicy.resolution_minutes.
2. Cases must be RESOLVED before CLOSED (rules engine enforces).
3. SurveyResponse is append-only — never update submitted scores.
4. CSAT score: 1–5. NPS: 0–10. CES: 1–7. Validated in service layer.
5. KnowledgeArticle can only publish from DRAFT or REVIEW.
6. P1 escalations recompute SLA from first_response_minutes.

## Status Transitions
```
Case: NEW → OPEN → PENDING_CUSTOMER ↔ OPEN → ESCALATED → RESOLVED → CLOSED
KnowledgeArticle: DRAFT → REVIEW → PUBLISHED → ARCHIVED
CaseComment.channel: INTERNAL | EMAIL | CHAT
```

## API Endpoints
| Method | Path | Description |
|---|---|---|
| GET | /service/cases/ | List cases |
| POST | /service/cases/ | Create case |
| GET | /service/cases/<id> | Case detail |
| POST | /service/cases/<id>/escalate | Escalate |
| POST | /service/cases/<id>/resolve | Resolve |
| POST | /service/cases/<id>/close | Close + CSAT |
| POST | /service/cases/<id>/comments | Add comment |
| POST | /service/cases/<id>/survey | Submit survey |
| GET | /service/sla-policies/ | List SLA policies |
| GET | /service/knowledge/ | List articles |
| POST | /service/knowledge/<id>/publish | Publish article |
| GET | /service/reports/open-by-priority | Open case counts by priority |
| GET | /service/reports/sla-compliance | SLA compliance rate |
| GET | /service/reports/csat-summary | Average CSAT |

## Events
**Emitted:** case.created, case.escalated, case.resolved, case.closed,
sla.breached, survey.submitted, knowledge.published

**Consumed:** ar.invoice.paid (auto-close billing cases), party.updated (sync contact)

## Rules Engine Rulesets (4)
1. `service.case.sla_breach_escalate` — warn on P1 SLA breach
2. `service.case.close_guard` — block CLOSED unless RESOLVED
3. `service.survey.csat_range` — validate CSAT score 1–5
4. `service.knowledge.publish_guard` — only DRAFT/REVIEW → PUBLISHED

## ReportForge Templates
- **Open Cases by Priority** — bar chart: P1/P2/P3/P4 open counts
- **SLA Compliance** — on-time resolution rate with totals
- **CSAT Summary** — average CSAT score with trend

## Dependencies
- `foundation` (DomainEventLog, Party)
- PostgreSQL ARRAY type for knowledge_articles_used and tags
- Optional: pgvector for embedding similarity search on KnowledgeArticle
