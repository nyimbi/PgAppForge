# HCM Talent Management Plugin — Specification

**Domain**: hcm  
**Module**: talent  
**Version**: 1.0.0  
**Depends on**: foundation

---

## Entities & Relationships

```
Requisition (1) ──< Application (1) ──< Interview
                         │
                         └──< Offer (1-to-1)

Employee ──< PerformanceReview

TrainingCourse (1) ──< TrainingEnrollment

foundation.Party (0..1) ──< Candidate (1) ──< Application
```

### Requisition
Approved headcount request for a position.

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | UUID | PK | |
| tenant_id | UUID | NOT NULL | |
| requisition_number | VARCHAR(30) | NOT NULL | Unique per tenant; REQ-YYYY-NNNN |
| position_id | UUID | | Soft FK to position master |
| hiring_manager_id | UUID | | Soft FK to HCM employee |
| recruiter_id | UUID | | Soft FK to HCM employee |
| department_id | UUID | | |
| headcount | INTEGER | NOT NULL, default=1 | Seats to fill |
| target_start_date | DATE | | |
| salary_range_min_cents | INTEGER | | Must be < max |
| salary_range_max_cents | INTEGER | | |
| currency_code | CHAR(3) | NOT NULL | |
| status | VARCHAR(20) | NOT NULL | DRAFT\|APPROVED\|POSTED\|IN_PROGRESS\|FILLED\|CANCELLED |
| job_description | TEXT | | |
| required_skills | JSONB | NOT NULL | [{name, level, required: bool}] |

**Unique**: (tenant_id, requisition_number)

### Candidate
Candidate master record (internal or external).

| Column | Type | Notes |
|--------|------|-------|
| party_id | UUID | Nullable; links to foundation.Party for internal candidates |
| source | VARCHAR(20) | REFERRAL\|JOB_BOARD\|LINKEDIN\|AGENCY\|DIRECT |
| current_employer | VARCHAR(255) | |
| current_title | VARCHAR(255) | |
| desired_salary_cents | INTEGER | Candidate's stated desired annual salary |
| notice_period_days | INTEGER | |
| work_authorization | VARCHAR(100) | CITIZEN, PR, H1B, OPT, VISA_REQUIRED |
| experience_years | NUMERIC(4,1) | |
| skills | JSONB | [{name, years, proficiency: BEGINNER\|INTERMEDIATE\|EXPERT}] |
| linkedin_url | VARCHAR(500) | |
| portfolio_url | VARCHAR(500) | |
| resume_url | VARCHAR(500) | Object-store URL |

### Application
Many-to-many junction between Candidate and Requisition with pipeline state.

| Column | Type | Notes |
|--------|------|-------|
| requisition_id | UUID | FK tal_requisition.id |
| candidate_id | UUID | FK tal_candidate.id |
| applied_at | TIMESTAMPTZ | NOT NULL, DEFAULT NOW() |
| stage | VARCHAR(20) | APPLIED\|SCREENING\|INTERVIEW\|OFFER\|ACCEPTED\|REJECTED |
| rejection_reason | VARCHAR(200) | |
| recruiter_notes | TEXT | |

**Unique**: (requisition_id, candidate_id)  
**Stage transitions**: forward-only except REJECTED which is permitted from any stage.

### Interview
Scheduled interview for an application. Supports panel interviews via UUID[].

| Column | Type | Notes |
|--------|------|-------|
| interview_type | VARCHAR(20) | PHONE\|VIDEO\|ONSITE\|TECHNICAL\|PANEL |
| scheduled_at | TIMESTAMPTZ | NOT NULL |
| duration_minutes | INTEGER | default=60 |
| interviewer_ids | UUID[] | PostgreSQL ARRAY — panel support without join table |
| location | VARCHAR(500) | Physical address or video URL |
| status | VARCHAR(20) | SCHEDULED\|COMPLETED\|CANCELLED |
| scorecard | JSONB | {dimension: score, notes: str} |
| overall_rating | NUMERIC(3,1) | 1.0–5.0 |
| recommendation | VARCHAR(10) | HIRE\|NO_HIRE\|MAYBE |

### Offer
Employment offer. One per application (enforced by unique constraint).

| Column | Type | Notes |
|--------|------|-------|
| base_salary_cents | INTEGER | NOT NULL; annual base salary |
| currency_code | CHAR(3) | |
| signing_bonus_cents | INTEGER | NOT NULL, default=0 |
| equity_details | JSONB | {shares, cliff_months, vest_months, strike_price_cents} |
| start_date | DATE | NOT NULL |
| expiry_date | DATE | NOT NULL; before start_date |
| status | VARCHAR(20) | DRAFT\|SENT\|ACCEPTED\|DECLINED\|EXPIRED |

**Unique**: (application_id)  
**Immutable**: once ACCEPTED or DECLINED, do not mutate.

### PerformanceReview
Employee performance review across multiple cycles.

| Column | Type | Notes |
|--------|------|-------|
| employee_id | UUID | Soft FK to employee master |
| reviewer_id | UUID | Soft FK to employee (manager) |
| review_cycle | VARCHAR(20) | ANNUAL\|MID_YEAR\|PROBATION\|360 |
| period_start | DATE | NOT NULL |
| period_end | DATE | NOT NULL |
| overall_rating | NUMERIC(3,1) | 1.0–5.0 |
| rating_label | VARCHAR(50) | EXCEEDS_EXPECTATIONS\|MEETS_EXPECTATIONS\|BELOW_EXPECTATIONS\|PIP |
| goals_achievement | JSONB | [{goal_id, goal_text, target, actual, score}] |
| competency_scores | JSONB | [{competency, weight, score}] |
| development_plan | TEXT | |
| status | VARCHAR(20) | DRAFT\|SUBMITTED\|CALIBRATED\|FINAL |

### TrainingCourse
Training course catalogue entry.

| Column | Type | Notes |
|--------|------|-------|
| course_code | VARCHAR(50) | Unique per tenant |
| title | VARCHAR(255) | |
| provider | VARCHAR(255) | External provider or "Internal" |
| delivery | VARCHAR(20) | ONLINE\|CLASSROOM\|BLENDED |
| duration_hours | NUMERIC(5,1) | |
| cost_cents | INTEGER | Per-seat cost |
| skills_taught | JSONB | [{name, proficiency_gained}] |

### TrainingEnrollment
Employee enrollment in a training course.

| Column | Type | Notes |
|--------|------|-------|
| employee_id | UUID | Soft FK to employee master |
| course_id | UUID | FK tal_training_course.id |
| enrolled_at | TIMESTAMPTZ | DEFAULT NOW() |
| completed_at | TIMESTAMPTZ | |
| score | NUMERIC(5,2) | 0.00–100.00 |
| certificate_url | VARCHAR(500) | |
| status | VARCHAR(20) | ENROLLED\|IN_PROGRESS\|COMPLETED\|WITHDRAWN\|FAILED |

**Unique**: (employee_id, course_id)

---

## Business Rules

1. **Requisition gating**: Applications only accepted for POSTED or IN_PROGRESS requisitions.
2. **Stage monotonicity**: Application stages advance forward only; REJECTED is always permitted.
3. **Offer uniqueness**: One active offer per application. Revision = expire old offer, create new.
4. **Offer expiry**: `expiry_date` must precede `start_date`. `expire_stale_offers()` is called daily.
5. **Offer acceptance gating**: Application cannot move to ACCEPTED stage without an ACCEPTED offer.
6. **Requisition auto-fill**: When `accepted_count >= headcount`, requisition status → FILLED.
7. **Interview recommendation**: HIRE | NO_HIRE | MAYBE — required before completing interview.
8. **Review finalisation**: `overall_rating` must be set before `finalise_review()`.
9. **Salary positive**: `desired_salary_cents` and `base_salary_cents` must be positive integers.
10. **Integer cents**: All monetary fields stored as integer cents; never float.

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | /talent/requisitions/ | List requisitions |
| POST | /talent/requisitions/ | Create DRAFT requisition |
| GET | /talent/requisitions/<id> | Detail |
| POST | /talent/requisitions/<id>/approve | DRAFT → APPROVED |
| POST | /talent/requisitions/<id>/post | APPROVED → POSTED |
| POST | /talent/requisitions/<id>/cancel | → CANCELLED |
| GET | /talent/candidates/ | List candidates |
| POST | /talent/candidates/ | Create candidate |
| GET | /talent/candidates/<id> | Detail |
| PUT | /talent/candidates/<id> | Update |
| GET | /talent/applications/ | List applications |
| POST | /talent/applications/ | Create application |
| GET | /talent/applications/<id> | Detail with interviews |
| POST | /talent/applications/<id>/advance | Advance pipeline stage |
| GET | /talent/interviews/ | List interviews |
| POST | /talent/interviews/ | Schedule interview |
| GET | /talent/interviews/<id> | Detail |
| POST | /talent/interviews/<id>/complete | Record scorecard |
| POST | /talent/interviews/<id>/cancel | Cancel |
| GET | /talent/offers/ | List offers |
| POST | /talent/offers/ | Extend offer (DRAFT) |
| GET | /talent/offers/<id> | Detail |
| POST | /talent/offers/<id>/send | DRAFT → SENT |
| POST | /talent/offers/<id>/accept | SENT → ACCEPTED |
| POST | /talent/offers/<id>/decline | SENT → DECLINED |
| GET | /talent/reviews/ | List reviews |
| POST | /talent/reviews/ | Create DRAFT review |
| GET | /talent/reviews/<id> | Detail |
| POST | /talent/reviews/<id>/submit | DRAFT → SUBMITTED |
| POST | /talent/reviews/<id>/finalise | → FINAL |
| GET | /talent/training/courses | List courses |
| POST | /talent/training/courses | Create course |
| POST | /talent/training/enroll | Enroll employee |
| GET | /talent/training/enrollments | List enrollments |
| POST | /talent/training/enrollments/<id>/complete | Mark completed |
| GET | /talent/reports/pipeline | Pipeline Funnel |
| GET | /talent/reports/offers | Offer Analytics |
| GET | /talent/reports/training | Training Completion |

---

## Events

### Emitted
| Event | Trigger |
|-------|---------|
| hcm.talent.requisition.approved | `approve_requisition()` |
| hcm.talent.requisition.filled | `_check_requisition_filled()` when headcount met |
| hcm.talent.application.stage_changed | `advance_stage()` |
| hcm.talent.offer.sent | `send_offer()` |
| hcm.talent.offer.accepted | `accept_offer()` |
| hcm.talent.offer.declined | `decline_offer()` |
| hcm.talent.review.finalised | `finalise_review()` |
| hcm.talent.training.completed | `complete_training()` |

### Consumed
| Event | Handler |
|-------|---------|
| hcm.employee.created | Auto-create PROBATION review |
| hcm.payroll.run.paid | Trigger merit raise review window |

---

## Reports

| Report | Endpoint | Key Metrics |
|--------|----------|-------------|
| Pipeline Funnel | /talent/reports/pipeline?requisition_id=X | Stage counts, conversion rates, avg interview rating |
| Offer Analytics | /talent/reports/offers | Acceptance rate, avg/min/max base salary per status |
| Training Completion | /talent/reports/training | Enrolled vs completed per course, avg assessment score |

---

## Rules Engine Pre-configuration (5 rulesets)

| Ruleset | Model | Trigger | Action |
|---------|-------|---------|--------|
| talent.requisition.salary_range_valid | Requisition | on_before_create | Reject if max ≤ min |
| talent.application.require_posted_requisition | Application | on_before_create | Reject if req not POSTED/IN_PROGRESS |
| talent.offer.positive_salary | Offer | on_before_create | Reject if base_salary_cents ≤ 0 |
| talent.offer.expiry_after_start | Offer | on_before_create | Reject if expiry ≥ start_date |
| talent.review.rating_range | PerformanceReview | on_before_update | Reject if rating not in [1.0, 5.0] |
