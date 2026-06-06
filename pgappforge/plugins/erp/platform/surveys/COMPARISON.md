# Survey Builder — World-Class Comparison

## Our Implementation
- Question types: TEXT, SINGLE_CHOICE, MULTI_CHOICE, RATING_SCALE, NPS, BOOLEAN, DATE
- Anonymous responses with secure token generation; duplicate-submission guard per respondent
- Required-question validation at submission time
- Built-in NPS computation (promoters/passives/detractors/score) and per-question analytics
- eNPS: finds latest ENPS survey, computes score, derives trend vs. previous quarter
- BPM actions: `platform.surveys.create_survey` (with auto-publish), `platform.surveys.get_results`
- Lifecycle states: DRAFT → PUBLISHED → CLOSED

**Integration points:** BPM workflow engine (HR onboarding, exit interviews, customer feedback loops), HCM module (eNPS)

---

## Benchmark: SurveyMonkey

| Feature | Ours | SurveyMonkey |
|---|---|---|
| Multiple question types | ✓ (7 types) | ✓ (15+ types) |
| Anonymous responses | ✓ | ✓ |
| Duplicate submission prevention | ✓ | ✓ |
| NPS calculation | ✓ built-in | ✓ |
| Skip logic / branching | ✗ | ✓ |
| Multilingual surveys | ✗ | ✓ |
| Email distribution | ✗ | ✓ |
| Custom branding | ✗ | ✓ |
| Export to CSV/SPSS | ✗ | ✓ |
| ERP workflow integration | ✓ | ✗ |
| Transactional response storage | ✓ | ✗ (SaaS) |

## Benchmark: Odoo Surveys

| Feature | Ours | Odoo |
|---|---|---|
| Question types | ✓ (7) | ✓ (8+) |
| NPS | ✓ | ✓ |
| eNPS / employee surveys | ✓ | ✓ |
| Scoring / certification mode | ✗ | ✓ |
| Time limit per survey | ✗ | ✓ |
| Live session / presentation mode | ✗ | ✓ |
| Visual analytics dashboard | ✗ | ✓ |
| BPM / workflow triggers | ✓ | ✓ |
| Per-question analytics API | ✓ | partial |

---

## Differentiation

**Where we exceed:**
- eNPS trend computation is native (quarter-over-quarter delta) — Odoo requires manual comparison
- BPM integration is deeper: surveys can be created, published, and results retrieved as first-class workflow steps
- Response storage is fully transactional; no separate analytics pipeline needed for basic NPS/choice distributions

**Remaining gaps:**
- No skip logic or conditional branching
- No time limits, scoring, or pass/fail certification
- No visual dashboard (charts); analytics returned as dicts for callers to render
- No survey invitation/distribution mechanism (email, SMS)
- Matrix/ranking question types not implemented
